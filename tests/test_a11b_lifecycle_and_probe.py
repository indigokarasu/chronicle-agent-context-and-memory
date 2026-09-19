"""
Chronicle — acceptance tests for A11b: four ENGINE defects the A11 hermeticity
audit found and, correctly, refused to fix under a tests-only scope.

THE FOUR DEFECTS.

  1. `MemoryStore` had no `close()`. Its SQLite connection is thread-local and
     was never closed, so every store ever constructed held its handle until the
     process died and left `<db>-wal` / `<db>-shm` on disk. A11 papered over it
     in tests with a `remove_db()` helper that unlinked the sidecars by hand.

  2. `get_embedder("auto")` — the DEFAULT, i.e. what every `ChronicleCore(...)`
     built without an explicit embeddings config got — opened TCP connections to
     localhost:1234, :11434 and :8080 DURING CONSTRUCTION. Whether a machine
     happened to be running Ollama therefore decided which embedder the core
     held and which geometry every vector written afterwards lived in. Two
     machines on the same commit did not agree. That is a REPRODUCIBILITY
     defect first and a hermeticity defect second.

  3. The probe loop was `except Exception: continue`, twice. A guard refusal, an
     HTTP 500, a malformed /v1/models body and "nothing is listening" were the
     same silent `continue`, so a broken deployment and an empty one produced
     identical output.

  4. `engine/serialize.py` read `CHRONICLE_REQUIRE_BLAKE3` at IMPORT time, which
     forced A11's conftest to pin the environment before any test module was
     imported — an ordering constraint imposed by a module-level side effect.

WHAT MAKES THESE TESTS MEAN SOMETHING. Each guard is killed by a named test,
and the two that could pass vacuously carry an explicit counter-proof:

  * `test_the_defect_two_fake_listeners_change_the_embedder_without_injection`
    runs the SAME construction under two different fake listeners with NO probe
    injected and asserts the results DIFFER. Without it, a fix that ignored the
    injected probe entirely would leave the determinism test green.
  * `TestSocketSentinelIsReal` proves the socket sentinel actually fires,
    so "zero socket operations" is not a claim made by a sentinel that never
    watches anything.

No test here touches the network, and the sentinel makes that enforced rather
than asserted. Fixtures are fake throughout (RFC5737/RFC3849 documentation
addresses, which are guaranteed non-routable).
"""

import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import embeddings as E
from engine import serialize as S
from engine.core import ChronicleCore
from engine.store import DB_SIDECARS, MemoryStore, StoreClosed

PUBLIC_IP = "http://203.0.113.7:11434/v1"           # RFC5737 TEST-NET-3

# Two mutually exclusive "worlds": what a machine happens to have listening.
OLLAMA_WORLD = {"http://localhost:11434/v1": {"models": ["nomic-embed-text"], "dimensions": 768}}
LMSTUDIO_WORLD = {"http://localhost:1234/v1": {"models": ["text-embedding-qwen3"],
                                               "dimensions": 1024}}


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

class _SocketSentinel:
    """Context manager: ANY socket operation inside is an error, and is counted.

    Stronger than patching `urllib.request.urlopen`: it denies socket
    CREATION, `create_connection` and name resolution, so a code path that
    reaches the network by some other route (http.client directly, a DNS lookup
    inside the A2 guard) is caught too. `ops` records what was attempted, so a
    failure names the operation instead of just failing."""

    def __init__(self, strict: bool = True):
        self.ops: list = []
        self.strict = strict
        self._patches: list = []

    def _deny(self, label):
        def _boom(*a, **kw):
            self.ops.append((label, a[:2]))
            if self.strict:
                raise AssertionError("socket operation %s%r attempted" % (label, a[:2]))
            raise OSError("denied by _SocketSentinel")
        return _boom

    def __enter__(self):
        sentinel = self

        class _Socket(socket.socket):
            def __init__(self, family=socket.AF_INET, *a, **kw):
                if family in (socket.AF_INET, socket.AF_INET6):
                    sentinel.ops.append(("socket", (family,)))
                    if sentinel.strict:
                        raise AssertionError("INET socket creation attempted (family=%r)" % family)
                super().__init__(family, *a, **kw)

        for target, name, repl in (
            (socket, "socket", _Socket),
            (socket, "create_connection", self._deny("create_connection")),
            (socket, "getaddrinfo", self._deny("getaddrinfo")),
            (socket, "gethostbyname", self._deny("gethostbyname")),
            (E, "_getaddrinfo", self._deny("engine._getaddrinfo")),
        ):
            p = mock.patch.object(target, name, repl)
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        self._patches = []
        return False


class _A11bCase(unittest.TestCase):
    """Resets every piece of process-wide state these fixes keep, so tests do
    not inherit each other's caches, reports or 'already warned' flags."""

    def setUp(self):
        self._reset()
        self.addCleanup(self._reset)

    def _reset(self):
        E._HOST_KIND_CACHE.clear()
        E._REMOTE_REFUSED_WARNED.clear()
        E._REMOTE_ALLOWED_WARNED.clear()
        E.reset_probe_report()
        E.set_default_probe(None)
        S.reset_hash_probe()
        ChronicleCore._active = None
        ChronicleCore._instances.clear()

    def temp_dir(self, prefix="a11b-"):
        path = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def sidecars(self, db_path):
        return sorted(s for s in DB_SIDECARS if os.path.exists(db_path + s))


# ===========================================================================
# DEFECT 1 — MemoryStore.close()
# ===========================================================================

class TestStoreClose(_A11bCase):

    def _store(self):
        d = self.temp_dir("a11b-store-")
        path = os.path.join(d, "chronicle.db")
        return MemoryStore(path), path

    def test_an_open_store_really_does_leave_wal_sidecars(self):
        """The precondition. If this fails the release test below is vacuous."""
        store, path = self._store()
        self.addCleanup(store.close)
        store.count_rows("events")
        self.assertEqual(self.sidecars(path), ["-shm", "-wal"],
                         "a WAL store should have both sidecars while it is open")

    def test_close_releases_the_wal_sidecars(self):
        store, path = self._store()
        store.count_rows("events")
        report = store.close()
        self.assertEqual(self.sidecars(path), [],
                         "close() must leave no -wal/-shm behind; got %s" % self.sidecars(path))
        self.assertTrue(report["sidecars_released"])
        self.assertEqual(report["journal_mode"], "delete")
        self.assertEqual(report["foreign"], [])
        self.assertEqual(report["closed"], 1)

    def test_close_preserves_the_data_it_checkpointed(self):
        """Releasing the WAL must FOLD it in, not discard it."""
        store, path = self._store()
        store.upsert_predicate("works_at", "employment", "single")
        store.close()
        self.assertEqual(self.sidecars(path), [])
        reopened = MemoryStore(path)
        self.addCleanup(reopened.close)
        self.assertIsNotNone(reopened.get_predicate("works_at"))

    def test_double_close_is_safe(self):
        store, path = self._store()
        first = store.close()
        second = store.close()
        self.assertFalse(first["already_closed"])
        self.assertTrue(second["already_closed"])
        self.assertEqual(second["closed"], 0)
        store.close()  # and a third, for good measure
        self.assertTrue(store.closed)

    def test_use_after_close_raises_a_clear_error(self):
        store, path = self._store()
        store.close()
        with self.assertRaises(StoreClosed) as ctx:
            store.count_rows("events")
        self.assertIn(path, str(ctx.exception),
                      "the error must name the database it refers to")

    def test_use_after_close_does_not_silently_reopen(self):
        """The failure mode worth pinning: a reopen would look like success AND
        put the sidecars back, undoing the close."""
        store, path = self._store()
        store.close()
        for _ in range(3):
            with self.assertRaises(StoreClosed):
                store.count_rows("events")
        self.assertEqual(self.sidecars(path), [])

    def test_store_is_a_context_manager(self):
        d = self.temp_dir("a11b-ctx-")
        path = os.path.join(d, "chronicle.db")
        with MemoryStore(path) as store:
            store.count_rows("events")
            self.assertEqual(self.sidecars(path), ["-shm", "-wal"])
        self.assertTrue(store.closed)
        self.assertEqual(self.sidecars(path), [])

    def test_context_manager_closes_on_exception(self):
        d = self.temp_dir("a11b-ctx2-")
        path = os.path.join(d, "chronicle.db")
        store = MemoryStore(path)
        with self.assertRaises(ValueError):
            with store:
                raise ValueError("boom")
        self.assertTrue(store.closed)
        self.assertEqual(self.sidecars(path), [])

    def test_a_foreign_threads_connection_is_reported_not_silently_leaked(self):
        """sqlite3 pins a connection to its creating thread — `close()` on it
        from anywhere else raises ProgrammingError — so a store whose worker
        thread is still alive CANNOT be fully closed from the owner's thread.
        The requirement is that this is said out loud, and that the sidecars are
        NOT deleted while a connection still holds the database."""
        store, path = self._store()
        opened = threading.Event()
        release = threading.Event()
        closed_in_thread = []

        def worker():
            store.count_rows("events")          # opens this thread's connection
            opened.set()
            release.wait(10)
            closed_in_thread.append(store.close_thread_connection())

        t = threading.Thread(target=worker)
        t.start()
        self.assertTrue(opened.wait(10))
        store.count_rows("events")              # the owner thread's own connection
        with self.assertLogs("chronicle.store", level="WARNING") as cm:
            report = store.close()
        release.set()
        t.join(10)

        self.assertEqual(len(report["foreign"]), 1,
                         "the worker's connection must be reported, not dropped in silence")
        self.assertFalse(report["sidecars_released"],
                         "sidecars must not be unlinked while another connection is open")
        self.assertNotEqual(report["journal_mode"], "delete",
                            "the journal-mode switch is the interlock: it cannot succeed here")
        self.assertTrue(any("still-live thread" in m for m in cm.output))
        self.assertEqual(closed_in_thread, [True],
                         "the worker's own close_thread_connection() must work")


class TestCoreClose(_A11bCase):

    def _core(self):
        home = self.temp_dir("a11b-core-")
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}},
                             embedder_probe=E.NullProbe())
        return core, core.store.db_path

    def test_core_close_closes_its_store_and_releases_sidecars(self):
        """Ownership: the core constructs the store, so the core closes it."""
        core, db_path = self._core()
        core.initialize("s1", principal_id="assistant")
        self.assertEqual(self.sidecars(db_path), ["-shm", "-wal"])
        report = core.close()
        self.assertTrue(report["sidecars_released"])
        self.assertEqual(self.sidecars(db_path), [])
        with self.assertRaises(StoreClosed):
            core.store.count_rows("events")

    def test_core_close_deregisters_the_singleton(self):
        """A cached core whose store is closed would hand every later get()
        caller a store that raises."""
        home = self.temp_dir("a11b-core2-")
        cfg = {"embeddings": {"model": "hashing"}}
        core = ChronicleCore.get(home, cfg, embedder_probe=E.NullProbe())
        self.assertIs(ChronicleCore.get(home, cfg), core)
        core.close()
        self.assertNotIn(home, ChronicleCore._instances)
        self.assertIsNone(ChronicleCore._active)
        fresh = ChronicleCore.get(home, cfg, embedder_probe=E.NullProbe())
        self.addCleanup(fresh.close)
        self.assertIsNot(fresh, core)
        self.assertEqual(fresh.store.count_rows("events"), 0)

    def test_core_close_is_idempotent_and_a_context_manager(self):
        core, db_path = self._core()
        core.close()
        core.close()
        home = self.temp_dir("a11b-core3-")
        with ChronicleCore(home, {"embeddings": {"model": "hashing"}},
                           embedder_probe=E.NullProbe()) as c2:
            path2 = c2.store.db_path
        self.assertTrue(c2.store.closed)
        self.assertEqual(self.sidecars(path2), [])


# ===========================================================================
# DEFECT 2 — the probe is injectable, and construction can be socket-free
# ===========================================================================

class TestSocketSentinelIsReal(_A11bCase):
    """Counter-proof: the sentinel the next class relies on actually fires."""

    def test_sentinel_catches_socket_creation(self):
        s = _SocketSentinel()
        with s:
            with self.assertRaises(AssertionError):
                socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.assertTrue(s.ops)

    def test_sentinel_catches_a_real_urlopen(self):
        import urllib.request
        s = _SocketSentinel()
        with s:
            with self.assertRaises(Exception):
                urllib.request.urlopen("http://127.0.0.1:1/v1/models", timeout=1)
        self.assertTrue(s.ops, "urlopen must have been observed reaching the socket layer")


class TestInjectedProbeIsSocketFree(_A11bCase):

    #: An explicit `auto` embeddings config. Explicit because the point of these
    #: tests is that the ANSWER does not depend on the ambient environment —
    #: relying on the default while `$CHRONICLE_EMBED_MODEL` can redirect it
    #: would be the same class of defect one level up.
    AUTO_CFG = {"embeddings": {"model": "auto"}}

    def _construct(self, probe, cfg=None):
        home = self.temp_dir("a11b-probe-")
        core = ChronicleCore(home, self.AUTO_CFG if cfg is None else cfg, embedder_probe=probe)
        self.addCleanup(core.close)
        return core

    def test_core_construction_with_an_injected_probe_performs_zero_socket_operations(self):
        """The headline: a default-configured core (no embeddings config at all,
        so `auto`) builds with NOT ONE socket operation when a probe is given."""
        sentinel = _SocketSentinel()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            with sentinel:
                core = self._construct(E.NullProbe())
        self.assertEqual(sentinel.ops, [],
                         "construction attempted socket operations: %r" % (sentinel.ops,))
        self.assertIsInstance(core.embedder, E.DegradedEmbedder)

    def test_get_embedder_auto_with_a_null_probe_opens_nothing(self):
        sentinel = _SocketSentinel()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            with sentinel:
                emb = E.get_embedder("auto", 768, None, None, probe=E.NullProbe())
        self.assertEqual(sentinel.ops, [])
        self.assertIsInstance(emb, E.DegradedEmbedder)

    def test_a_static_probe_yields_a_real_client_without_a_socket(self):
        """Injection is not only 'find nothing': a fake listener resolves to a
        real client, deterministically, with no I/O."""
        sentinel = _SocketSentinel()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            with sentinel:
                emb = E.get_embedder("auto", 768, None, None,
                                     probe=E.StaticProbe(OLLAMA_WORLD))
        self.assertEqual(sentinel.ops, [])
        self.assertIsInstance(emb, E.OpenAICompatEmbedder)
        self.assertEqual(emb.model, "nomic-embed-text")
        self.assertEqual(emb.base_url, "http://localhost:11434/v1")
        self.assertEqual(emb.dimensions, 768)

    def _identity(self, emb):
        return (type(emb).__name__, emb.model_tag(), emb.dimensions,
                getattr(emb, "base_url", None))

    def test_the_defect_two_fake_listeners_change_the_embedder_without_injection(self):
        """COUNTER-PROOF. With no probe injected, the same construction under
        two different listeners produces two different embedders. This is the
        reproducibility defect itself, and it is what makes the next test a
        real assertion rather than a tautology."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            E.set_default_probe(E.StaticProbe(OLLAMA_WORLD))
            a = E.get_embedder("auto", 768, None, None)
            E.set_default_probe(E.StaticProbe(LMSTUDIO_WORLD))
            b = E.get_embedder("auto", 768, None, None)
        self.assertNotEqual(self._identity(a), self._identity(b),
                            "without injection the ambient listener decides the embedder")

    def test_an_injected_probe_gives_the_same_embedder_under_both_worlds(self):
        """THE FIX. Same construction, same injected probe, two different fake
        listeners in the ambient world: one answer."""
        sentinel = _SocketSentinel()
        injected = E.NullProbe()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            with sentinel:
                E.set_default_probe(E.StaticProbe(OLLAMA_WORLD))
                a = E.get_embedder("auto", 768, None, None, probe=injected)
                E.set_default_probe(E.StaticProbe(LMSTUDIO_WORLD))
                b = E.get_embedder("auto", 768, None, None, probe=injected)
        self.assertEqual(sentinel.ops, [])
        self.assertEqual(self._identity(a), self._identity(b))
        self.assertEqual(self._identity(a), ("DegradedEmbedder", "degraded", 768, None))

    def test_a_core_is_deterministic_under_both_worlds_too(self):
        """The same property one level up, where it actually bites: the object
        the core holds, and therefore the geometry of every vector it writes."""
        sentinel = _SocketSentinel()
        ids = []
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            with sentinel:
                for world in (OLLAMA_WORLD, LMSTUDIO_WORLD):
                    E.set_default_probe(E.StaticProbe(world))
                    core = self._construct(E.NullProbe())
                    ids.append(self._identity(core.embedder))
        self.assertEqual(sentinel.ops, [])
        self.assertEqual(ids[0], ids[1])

    def test_set_default_probe_makes_every_construction_deterministic(self):
        """For a harness that does not own the call sites: install the probe
        process-wide once and no `probe=` argument is needed anywhere."""
        sentinel = _SocketSentinel()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            E.set_default_probe(E.NullProbe())
            with sentinel:
                core = self._construct(None, cfg=self.AUTO_CFG)
        self.assertEqual(sentinel.ops, [])
        self.assertIsInstance(core.embedder, E.DegradedEmbedder)

    def test_set_default_probe_none_restores_the_network_probe(self):
        E.set_default_probe(E.NullProbe())
        self.assertIsInstance(E.default_probe(), E.NullProbe)
        E.set_default_probe(None)
        self.assertIsInstance(E.default_probe(), E.NetworkProbe)


class TestInjectedProbeCannotBypassTheA2Guard(_A11bCase):
    """A probe supplies the REACHABILITY answer. It never supplies the
    DESTINATION policy — that stays with A2's `check_endpoint`."""

    def test_a_probe_declaring_an_off_host_server_is_still_refused(self):
        probe = E.StaticProbe({PUBLIC_IP: {"models": ["nomic-embed-text"], "dimensions": 768}})
        with mock.patch.dict(os.environ, {"CHRONICLE_EMBED_BASE_URL": PUBLIC_IP}):
            emb = E.get_embedder("auto", 768, None, None, probe=probe)
        self.assertIsInstance(emb, E.DegradedEmbedder)
        outcomes = {r["outcome"] for r in emb.probe_report}
        self.assertEqual(outcomes, {"refused"})

    def test_a_probe_that_returns_an_off_host_client_is_refused_on_the_way_back(self):
        """The lying-probe case: candidate URL is loopback and passes the gate,
        but `make()` hands back a client pointed somewhere else. The guard is
        re-applied to what came back, so the swap is caught."""

        class _LyingProbe(E.NullProbe):
            def list_models(self, url, api_key):
                return ["nomic-embed-text"]

            def make(self, url, model, dims, **kw):
                kw["allow_remote"] = True         # build it despite the guard
                return E.OpenAICompatEmbedder(PUBLIC_IP, model, dims, **kw)

            def healthcheck(self, embedder):
                raise AssertionError("healthcheck must never be reached for a refused client")

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            emb = E.get_embedder("auto", 768, None, None, probe=_LyingProbe())
        self.assertIsInstance(emb, E.DegradedEmbedder)
        self.assertTrue(any(r["outcome"] == "refused" for r in emb.probe_report),
                        "the returned client's destination must be re-checked: %r" % emb.probe_report)

    def test_a_degraded_embedder_rechecks_with_the_probe_it_was_given(self):
        """Otherwise an injected-probe session would adopt a real server on the
        first recheck and reintroduce exactly the nondeterminism it removed."""
        sentinel = _SocketSentinel()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            with sentinel:
                emb = E.get_embedder("auto", 768, None, None, probe=E.NullProbe())
                E.set_default_probe(E.StaticProbe(OLLAMA_WORLD))   # a server "appears"
                for _ in range(3):
                    self.assertFalse(emb.recheck(force=True))
        self.assertEqual(sentinel.ops, [])
        self.assertIsNone(emb.live)


# ===========================================================================
# DEFECT 3 — probe failures are observable
# ===========================================================================

class _FailingProbe(E.NullProbe):
    """A probe whose `list_models` raises whatever it was handed."""

    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def list_models(self, url, api_key):
        raise self.exc


class TestProbeFailuresAreObservable(_A11bCase):

    def _probe(self, probe, base_url=None, allow_remote=False):
        report: list = []
        with mock.patch.dict(os.environ, {}, clear=False):
            if base_url is None:
                os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            emb = E._probe_endpoints("auto", 768, base_url, None, probe=probe, report=report,
                                     allow_remote=allow_remote)
        return emb, report

    def test_a_real_failure_reports_its_reason(self):
        """The defect: `except Exception: continue` made this invisible."""
        emb, report = self._probe(_FailingProbe(ValueError("malformed /v1/models body")))
        self.assertIsNone(emb)
        self.assertEqual(len(report), len(E._DEFAULT_ENDPOINTS))
        for entry in report:
            self.assertEqual(entry["outcome"], "error")
            self.assertIn("malformed /v1/models body", entry["reason"])
            self.assertIn("ValueError", entry["reason"])

    def test_a_real_failure_is_logged_once_per_endpoint_with_the_reason(self):
        with self.assertLogs("chronicle.embeddings", level="DEBUG") as cm:
            self._probe(_FailingProbe(ValueError("boom-42")))
        warnings = [r for r in cm.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), len(E._DEFAULT_ENDPOINTS),
                         "one warning per candidate endpoint, no more and no fewer")
        self.assertTrue(all("boom-42" in r.getMessage() for r in warnings))

    def test_the_same_failure_does_not_re_warn_on_a_second_sweep(self):
        """Observable, not noisy: the reason is said once per (endpoint,
        outcome) per process, then demoted to DEBUG."""
        probe = _FailingProbe(ValueError("boom-42"))
        with self.assertLogs("chronicle.embeddings", level="DEBUG") as first:
            self._probe(probe)
        with self.assertLogs("chronicle.embeddings", level="DEBUG") as second:
            self._probe(probe)
        self.assertTrue([r for r in first.records if r.levelname == "WARNING"])
        self.assertEqual([r for r in second.records if r.levelname == "WARNING"], [],
                         "a repeat of a known failure must not re-warn")

    def test_nothing_listening_is_recorded_but_stays_quiet(self):
        """The ordinary case on a laptop with no embedding server. It must be
        in the report (so it is discoverable) and NOT at WARNING (so a normal
        machine's logs are not full of it)."""
        emb, report = self._probe(_FailingProbe(ConnectionRefusedError(61, "Connection refused")))
        self.assertIsNone(emb)
        self.assertTrue(report)
        self.assertEqual({r["outcome"] for r in report}, {"unreachable"})
        with self.assertLogs("chronicle.embeddings", level="DEBUG") as cm:
            self._probe(_FailingProbe(ConnectionRefusedError(61, "Connection refused")))
        self.assertEqual([r for r in cm.records if r.levelname == "WARNING"], [],
                         "'nothing listening' must not warn")

    def test_an_http_status_counts_as_a_real_failure_not_an_absent_server(self):
        """`urllib.error.HTTPError` is an OSError subclass, so a naive
        classification would file a 500 under 'unreachable' and mute it — but a
        server that answered 500 exists and is broken, which is news."""
        import urllib.error
        err = urllib.error.HTTPError("http://localhost:11434/v1/models", 500,
                                     "Internal Server Error", {}, None)
        emb, report = self._probe(_FailingProbe(err))
        self.assertEqual({r["outcome"] for r in report}, {"error"})

    def test_an_endpoint_that_serves_no_model_is_reported(self):
        emb, report = self._probe(E.NullProbe())
        self.assertIsNone(emb)
        self.assertEqual({r["outcome"] for r in report}, {"no_models"})

    def test_a_guard_refusal_is_visible_in_the_report(self):
        emb, report = self._probe(E.StaticProbe(OLLAMA_WORLD), base_url=PUBLIC_IP)
        self.assertIsNone(emb)
        self.assertEqual([r["outcome"] for r in report], ["refused"])
        self.assertIn("203.0.113.7", report[0]["url"])
        self.assertIn("remote", report[0]["reason"])

    def test_the_report_redacts_credentials_in_the_url(self):
        secret = "http://user:hunter2@localhost:11434/v1"
        emb, report = self._probe(_FailingProbe(ValueError("x")), base_url=secret)
        self.assertTrue(report)
        for entry in report:
            self.assertNotIn("hunter2", entry["url"])

    def test_the_degraded_embedder_carries_the_report(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            emb = E.get_embedder("auto", 768, None, None,
                                 probe=_FailingProbe(ValueError("no json here")))
        self.assertIsInstance(emb, E.DegradedEmbedder)
        self.assertEqual(len(emb.probe_report), len(E._DEFAULT_ENDPOINTS))
        self.assertTrue(all("no json here" in r["reason"] for r in emb.probe_report))

    def test_the_degraded_log_line_names_the_outcomes(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            with self.assertLogs("chronicle.embeddings", level="DEBUG") as cm:
                E.get_embedder("auto", 768, None, None, probe=E.NullProbe())
        degraded = [r.getMessage() for r in cm.records
                    if r.levelname == "WARNING" and "DEGRADED mode" in r.getMessage()]
        self.assertEqual(len(degraded), 1)
        self.assertIn("no_models", degraded[0])
        self.assertIn("localhost:11434", degraded[0])

    def test_last_probe_report_is_readable_without_holding_the_embedder(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            E.get_embedder("auto", 768, None, None, probe=_FailingProbe(ValueError("zz")))
        report = E.last_probe_report()
        self.assertTrue(report)
        self.assertTrue(all(r["outcome"] == "error" for r in report))

    def test_a_success_is_recorded_too(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHRONICLE_EMBED_BASE_URL", None)
            os.environ.pop("CHRONICLE_EMBED_MODEL", None)
            emb, report = self._probe(E.StaticProbe(OLLAMA_WORLD))
        self.assertIsInstance(emb, E.OpenAICompatEmbedder)
        self.assertEqual(report[-1]["outcome"], "ok")
        self.assertEqual(report[-1]["model"], "nomic-embed-text")


# ===========================================================================
# DEFECT 4 — CHRONICLE_REQUIRE_BLAKE3 is read lazily
# ===========================================================================

class TestLazyRequireBlake3(_A11bCase):

    def setUp(self):
        super().setUp()
        self.have_blake3 = S._load_blake3()[0] is not None

    def test_the_default_is_a_deterministic_256_bit_hash(self):
        self.assertIn(S.hash_name(), (S.BLAKE3_NAME, S.BLAKE2B_NAME))
        self.assertEqual(len(S.content_hash(b"Pat Testley")), 64)

    def test_the_variable_is_honoured_when_set_after_import(self):
        """THE DEFECT. The old module read it at import time, so setting it
        here changed nothing and a harness had to win a race against the import
        graph to control it."""
        self.assertNotIn("CHRONICLE_REQUIRE_BLAKE3", os.environ)
        with mock.patch.dict(os.environ, {"CHRONICLE_REQUIRE_BLAKE3": "1"}):
            if self.have_blake3:
                self.assertEqual(S.hash_name(), S.BLAKE3_NAME)
            else:
                with self.assertRaises(S.Blake3Required):
                    S.hash_name()

    def test_content_hash_itself_enforces_the_requirement(self):
        """Not just the name: the thing that actually produces an id."""
        if self.have_blake3:
            self.skipTest("blake3 is installed; the missing-blake3 branch cannot be exercised")
        with mock.patch.dict(os.environ, {"CHRONICLE_REQUIRE_BLAKE3": "1"}):
            for fn, arg in ((S.content_hash, b"x"), (S.hash_str, "x")):
                with self.assertRaises(S.Blake3Required):
                    fn(arg)

    def test_unsetting_it_again_restores_the_fallback(self):
        """Lazy means lazy in both directions — a cached first answer would
        fail this."""
        if self.have_blake3:
            self.skipTest("blake3 is installed; nothing to fall back to")
        with mock.patch.dict(os.environ, {"CHRONICLE_REQUIRE_BLAKE3": "1"}):
            with self.assertRaises(S.Blake3Required):
                S.hash_name()
        self.assertEqual(S.hash_name(), S.BLAKE2B_NAME)

    def test_the_error_says_what_to_do(self):
        if self.have_blake3:
            self.skipTest("blake3 is installed")
        with mock.patch.dict(os.environ, {"CHRONICLE_REQUIRE_BLAKE3": "1"}):
            with self.assertRaises(S.Blake3Required) as ctx:
                S.hash_name()
        msg = str(ctx.exception)
        self.assertIn("CHRONICLE_REQUIRE_BLAKE3", msg)
        self.assertIn("blake3", msg)

    def test_the_module_attribute_is_not_frozen_at_import(self):
        """`serialize.HASH_NAME` and `engine.HASH_NAME` still read, but they
        resolve on ACCESS. Importing the module can no longer decide the answer."""
        import engine
        self.assertIn(S.HASH_NAME, (S.BLAKE3_NAME, S.BLAKE2B_NAME))
        self.assertEqual(engine.HASH_NAME, S.hash_name())
        if self.have_blake3:
            return
        with mock.patch.dict(os.environ, {"CHRONICLE_REQUIRE_BLAKE3": "1"}):
            with self.assertRaises(S.Blake3Required):
                getattr(S, "HASH_NAME")
            with self.assertRaises(S.Blake3Required):
                getattr(engine, "HASH_NAME")

    def test_importing_serialize_reads_nothing_from_the_environment(self):
        """The ordering constraint A11's conftest had to work around: importing
        the module with the variable already set must not raise, because import
        time is not when the question is asked."""
        import subprocess
        env = dict(os.environ)
        env["CHRONICLE_REQUIRE_BLAKE3"] = "1"
        env["PYTHONPATH"] = str(Path(__file__).parent.parent)
        proc = subprocess.run(
            [sys.executable, "-c", "import engine.serialize as S; print('imported')"],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("imported", proc.stdout)

    def test_ids_are_unchanged_by_the_refactor(self):
        """Content addressing is the contract (I2). Pinned literals, so a change
        in the hash pipeline cannot slip through as 'still deterministic'."""
        if self.have_blake3:
            self.skipTest("pinned literals are for the blake2b fallback")
        self.assertEqual(
            S.event_id("observed", {"body": "Pat Testley works at Acme Fake Co"}, [],
                       "user", "2026-01-01T00:00:00.00Z"),
            "ev_50f3b00ec6060f37c6f4eea4892c3483ec2d9fe2ab5d4275cb34693645a68dd8")
        self.assertEqual(
            S.belief_id("fact", {"k": "v"}, ["ev_1"]),
            "b_8372f618a9d0ef5f824c2d0f5ed55c2e9b314589e221e2a18e7ef77e79da0d5a")
        self.assertEqual(
            S.hash_str("chronicle"),
            "6136ba6e3030b3463c1f5d8b3775f85a544ebc7a62c4c56a4e7e35492323b5b5")


if __name__ == "__main__":
    unittest.main()
