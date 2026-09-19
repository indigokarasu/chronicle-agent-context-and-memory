"""
Chronicle — acceptance tests for A2: the on-host guard for memory-bearing requests.

THE DEFECT. `config.py` promised "No remote-API tier: memory excerpts never
leave the host". Nothing enforced it. `get_embedder` trusted any explicit
`base_url`, `$CHRONICLE_EMBED_BASE_URL` was honoured unchecked, and
`extraction.llm.base_url` POSTs the raw excerpt to whatever it names. In
production an out-of-tree script pointed exactly that knob at a hosted API and
shipped ~190k excerpts off-host for a month.

WHAT IS TESTED. Every allowed form and every refused form, at default config;
`allow_remote: true` as the single, explicit way through; refusal DEGRADING
rather than raising; the WARNING firing once; DNS resolved once, never in a hot
path, and failing closed; and a capture->process flow against a refused
endpoint that stores beliefs, writes no vectors, and raises nothing.

Two things make these tests mean something rather than merely pass:

  * NO TEST IS ALLOWED TO TOUCH THE NETWORK. `_NoNetwork` patches
    `urllib.request.urlopen` to fail the test if anything calls it, and
    `_FakeResolver` replaces `engine.embeddings._getaddrinfo`. A test that
    "proves" nothing was sent while actually sending it would be worthless, and
    hostname cases would otherwise depend on live DNS.
  * THE MUTATION GUARD (last class) re-runs the same assertions with the
    pre-A2 world injected — a `check_endpoint` that trusts everything — and
    asserts they FAIL. Without it, deleting the guard would leave this file
    green.

Fixtures are fake throughout (Pat Testley, Acme Fake Co, and RFC5737/RFC3849
documentation addresses, which are guaranteed non-routable).
"""

import logging
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import embeddings as E
from engine.config import Config
from engine.core import ChronicleCore
from engine.extraction import HeuristicExtractor, LLMExtractor, make_extractor

# Documentation / test ranges: guaranteed never routed to a real service, so a
# bug that DID open a connection fails on connect rather than reaching anyone.
PUBLIC_IP = "http://203.0.113.7:11434/v1"          # RFC5737 TEST-NET-3
PUBLIC_IP_2 = "http://8.8.8.8:11434/v1"            # a public literal everyone recognises
PUBLIC_HTTPS = "https://api.openrouter.example/v1"  # hosted-API-shaped hostname
PUBLIC_V6 = "http://[2001:db8:dead::1]:11434/v1"   # RFC3849 documentation v6


class _NoNetwork:
    """Context manager: any real HTTP call inside fails the test.

    The guard's entire claim is "nothing is sent". Asserting that with a mock
    that would happily have sent it proves nothing, so every test that claims a
    refusal runs inside this."""

    def __init__(self, testcase):
        self.tc = testcase
        self._p = None

    def __enter__(self):
        def _boom(*a, **kw):
            raise AssertionError("a network call was attempted: %r" % (a[:1],))
        self._p = mock.patch.object(urllib.request, "urlopen", _boom)
        self._p.start()
        return self

    def __exit__(self, *exc):
        self._p.stop()
        return False


class _FakeResolver:
    """A stand-in for `socket.getaddrinfo`, so hostname cases are hermetic.

    `answers` maps hostname -> list of address strings, or to an Exception
    instance to simulate NXDOMAIN/timeout. Counts calls so a test can assert
    that the hot path never resolves and that a name is resolved ONCE."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, host):
        self.calls.append(host)
        ans = self.answers.get(host)
        if isinstance(ans, Exception):
            raise ans
        if ans is None:
            raise OSError("nodename nor servname provided (fake resolver: %s)" % host)
        return [(2, 1, 6, "", (a, 0)) for a in ans]


class _GuardTestCase(unittest.TestCase):
    """Clears every piece of process-wide state the guard keeps, so tests do not
    inherit each other's cache entries or 'already warned' flags."""

    def setUp(self):
        E._HOST_KIND_CACHE.clear()
        E._REMOTE_REFUSED_WARNED.clear()
        E._REMOTE_ALLOWED_WARNED.clear()

    def tearDown(self):
        E._HOST_KIND_CACHE.clear()
        E._REMOTE_REFUSED_WARNED.clear()
        E._REMOTE_ALLOWED_WARNED.clear()


# ---------------------------------------------------------------------------
# (1) the allowed / refused table, at DEFAULT config
# ---------------------------------------------------------------------------

# (url, expected kind). None of these needs DNS.
ALLOWED_NO_DNS = [
    ("http://127.0.0.1:11434/v1", "loopback"),
    ("http://127.5.6.7:8080/v1", "loopback"),          # all of 127/8, not just .0.1
    ("http://localhost:11434/v1", "loopback"),
    ("http://LOCALHOST:1234/v1", "loopback"),          # case-insensitive
    ("http://localhost./v1", "loopback"),              # trailing-dot FQDN form
    ("http://ollama.localhost:11434/v1", "loopback"),  # RFC6761 *.localhost
    ("http://[::1]:11434/v1", "loopback"),
    ("http://0.0.0.0:8080/v1", "loopback"),
    ("http://10.0.0.5:11434/v1", "private"),
    ("http://10.255.255.254:8080/v1", "private"),
    ("http://192.168.1.42:11434/v1", "private"),
    ("http://172.16.0.1:11434/v1", "private"),         # low edge of RFC1918 /12
    ("http://172.31.255.254:11434/v1", "private"),     # high edge of RFC1918 /12
    ("http://172.20.3.4:11434/v1", "private"),         # middle
    ("http://100.64.0.1:11434/v1", "private"),         # RFC6598 shared space
    ("http://[fc00::1]:11434/v1", "private"),          # ULA fc00::/7
    ("http://[fd12:3456::9]:11434/v1", "private"),     # ULA, fd half of fc00::/7
    ("http://169.254.10.1:11434/v1", "link-local"),
    ("http://[fe80::1]:11434/v1", "link-local"),
    ("unix:/var/run/chronicle-embed.sock", "unix"),
    ("http+unix:/var/run/chronicle-embed.sock", "unix"),
]

REFUSED_NO_DNS = [
    (PUBLIC_IP, "remote"),
    (PUBLIC_IP_2, "remote"),
    (PUBLIC_V6, "remote"),
    ("http://172.15.0.1:11434/v1", "remote"),          # just BELOW RFC1918 172.16/12
    ("http://172.32.0.1:11434/v1", "remote"),          # just ABOVE RFC1918 172.16/12
    ("http://11.0.0.1:11434/v1", "remote"),            # adjacent to 10/8
    ("http://192.169.1.1:11434/v1", "remote"),         # adjacent to 192.168/16
    ("http://126.0.0.1:11434/v1", "remote"),           # adjacent to 127/8
    ("http://128.0.0.1:11434/v1", "remote"),           # adjacent to 127/8, other side
    # The IPv4-mapped trap: Python 3.9's ipaddress reports ::ffff:0:0/96 as
    # "private", so classifying by is_private alone would have let a public v4
    # through in a v6 wrapper.
    ("http://[::ffff:8.8.8.8]:11434/v1", "remote"),
    ("http://[2002:808:808::1]:11434/v1", "remote"),   # 6to4 tunnelling 8.8.8.8
]


class TestClassificationTableNoDNS(_GuardTestCase):
    """Every allowed and refused form, decided with NO name resolution."""

    def _resolver_that_must_not_be_called(self):
        return _FakeResolver({})

    def test_allowed_forms_classify_on_host_and_never_resolve(self):
        r = self._resolver_that_must_not_be_called()
        with mock.patch.object(E, "_getaddrinfo", r):
            for url, expected in ALLOWED_NO_DNS:
                self.assertEqual(E.endpoint_kind(url), expected, url)
                self.assertIn(E.endpoint_kind(url), E.ONHOST_KINDS, url)
                # and check_endpoint lets it through at DEFAULT config
                self.assertEqual(E.check_endpoint(url, allow_remote=False), expected, url)
        self.assertEqual(r.calls, [],
                         "IP literals and the localhost family must be classified without DNS")

    def test_refused_forms_are_remote_and_raise_at_default_config(self):
        r = self._resolver_that_must_not_be_called()
        with mock.patch.object(E, "_getaddrinfo", r):
            for url, expected in REFUSED_NO_DNS:
                self.assertEqual(E.endpoint_kind(url), expected, url)
                self.assertNotIn(E.endpoint_kind(url), E.ONHOST_KINDS, url)
                with self.assertRaises(E.RemoteEndpointRefused, msg=url):
                    E.check_endpoint(url, allow_remote=False)
        self.assertEqual(r.calls, [], "IP literals must be classified without DNS")

    def test_allow_remote_true_permits_every_refused_form(self):
        with mock.patch.object(E, "_getaddrinfo", _FakeResolver({})):
            for url, _expected in REFUSED_NO_DNS:
                # returns the (still honest) kind rather than raising
                self.assertNotIn(E.check_endpoint(url, allow_remote=True), ("none",), url)

    def test_no_endpoint_configured_is_not_a_refusal(self):
        for url in (None, "", "   "):
            self.assertEqual(E.endpoint_kind(url), "none")
            self.assertEqual(E.check_endpoint(url, allow_remote=False), "none")

    def test_a_url_with_no_host_is_refused(self):
        # Cannot name the destination -> cannot vouch for it.
        for url in ("http://", "://nonsense"):
            self.assertNotIn(E.endpoint_kind(url), E.ONHOST_KINDS, url)
            with self.assertRaises(E.RemoteEndpointRefused, msg=url):
                E.check_endpoint(url, allow_remote=False)


# ---------------------------------------------------------------------------
# (2) hostname resolution: once, cached, fail closed
# ---------------------------------------------------------------------------

class TestHostnameResolution(_GuardTestCase):

    def test_hostname_resolving_to_private_is_allowed(self):
        r = _FakeResolver({"embed.lan": ["10.4.5.6"]})
        with mock.patch.object(E, "_getaddrinfo", r):
            self.assertEqual(E.endpoint_kind("http://embed.lan:11434/v1"), "private")
            self.assertEqual(E.check_endpoint("http://embed.lan:11434/v1"), "private")

    def test_hostname_resolving_to_loopback_is_allowed(self):
        r = _FakeResolver({"my-box.internal": ["127.0.0.1"]})
        with mock.patch.object(E, "_getaddrinfo", r):
            self.assertEqual(E.endpoint_kind("http://my-box.internal:8080/v1"), "loopback")

    def test_public_hostname_is_refused(self):
        r = _FakeResolver({"api.openrouter.example": ["104.18.2.7"]})
        with mock.patch.object(E, "_getaddrinfo", r):
            self.assertEqual(E.endpoint_kind(PUBLIC_HTTPS), "remote")
            with self.assertRaises(E.RemoteEndpointRefused):
                E.check_endpoint(PUBLIC_HTTPS, allow_remote=False)

    def test_resolution_failure_refuses_fail_closed(self):
        r = _FakeResolver({"gone.invalid": OSError("NXDOMAIN")})
        with mock.patch.object(E, "_getaddrinfo", r):
            self.assertEqual(E.endpoint_kind("http://gone.invalid/v1"), "unresolvable")
            with self.assertRaises(E.RemoteEndpointRefused):
                E.check_endpoint("http://gone.invalid/v1", allow_remote=False)

    def test_empty_answer_refuses(self):
        r = _FakeResolver({"silent.lan": []})
        with mock.patch.object(E, "_getaddrinfo", r):
            self.assertEqual(E.endpoint_kind("http://silent.lan/v1"), "unresolvable")

    def test_one_public_answer_makes_the_whole_name_remote(self):
        # Split-horizon / DNS rebinding must not buy access by returning one
        # private address alongside a public one.
        r = _FakeResolver({"mixed.lan": ["10.0.0.9", "104.18.2.7"]})
        with mock.patch.object(E, "_getaddrinfo", r):
            self.assertEqual(E.endpoint_kind("http://mixed.lan/v1"), "remote")
            with self.assertRaises(E.RemoteEndpointRefused):
                E.check_endpoint("http://mixed.lan/v1", allow_remote=False)

    def test_a_name_is_resolved_once_and_cached(self):
        r = _FakeResolver({"embed.lan": ["10.4.5.6"]})
        with mock.patch.object(E, "_getaddrinfo", r):
            for _ in range(25):
                E.endpoint_kind("http://embed.lan:11434/v1")
                E.endpoint_kind("http://embed.lan:9999/v2")   # same host, other port
        self.assertEqual(r.calls, ["embed.lan"],
                         "the guard must resolve a hostname exactly once per process")

    def test_the_hot_path_never_resolves(self):
        """Construction resolves; embed() must not.

        The constructor is where DNS is allowed to happen. If a later embed
        re-resolved, a 50-per-turn drain would pay a lookup per item and, worse,
        the verdict could change under the running process."""
        r = _FakeResolver({"embed.lan": ["10.4.5.6"]})
        with mock.patch.object(E, "_getaddrinfo", r):
            emb = E.OpenAICompatEmbedder("http://embed.lan:11434/v1", "nomic-embed-text", 8,
                                         max_attempts=1)
            self.assertEqual(len(r.calls), 1)
            self.assertEqual(emb.endpoint_kind, "private")
            with mock.patch.object(emb, "_embed_raw", lambda text, timeout: [0.1] * 8):
                for _ in range(10):
                    emb.embed("Pat Testley works at Acme Fake Co")
            self.assertEqual(len(r.calls), 1, "embed() must never resolve")


# ---------------------------------------------------------------------------
# (3) the embedder: refusal degrades, never raises; nothing is sent
# ---------------------------------------------------------------------------

class TestEmbedderRefusalDegrades(_GuardTestCase):

    def test_explicit_model_plus_remote_base_url_yields_degraded_and_sends_nothing(self):
        with _NoNetwork(self):
            emb = E.get_embedder("nomic-embed-text", 768, PUBLIC_IP, "sk-fake-not-a-key")
        self.assertIsInstance(emb, E.DegradedEmbedder)
        self.assertFalse(emb.allow_remote)
        # embed() raises the ordinary degraded exception every caller already handles
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed("Pat Testley works at Acme Fake Co")

    def test_https_public_url_yields_degraded(self):
        r = _FakeResolver({"api.openrouter.example": ["104.18.2.7"]})
        with mock.patch.object(E, "_getaddrinfo", r), _NoNetwork(self):
            emb = E.get_embedder("nomic-embed-text", 768, PUBLIC_HTTPS, "sk-fake-not-a-key")
        self.assertIsInstance(emb, E.DegradedEmbedder)

    def test_constructing_the_client_directly_raises_rather_than_existing(self):
        """The refusal is in __init__, so no object able to POST is ever built."""
        with _NoNetwork(self):
            with self.assertRaises(E.RemoteEndpointRefused):
                E.OpenAICompatEmbedder(PUBLIC_IP, "nomic-embed-text", 768)

    def test_loopback_base_url_still_builds_a_real_client(self):
        with _NoNetwork(self):
            emb = E.OpenAICompatEmbedder("http://127.0.0.1:11434/v1", "nomic-embed-text", 768)
        self.assertEqual(emb.endpoint_kind, "loopback")

    def test_allow_remote_true_builds_a_real_client_for_a_public_url(self):
        with _NoNetwork(self), \
             mock.patch.object(E.OpenAICompatEmbedder, "healthcheck",
                               side_effect=RuntimeError("not probing in a test")):
            emb = E.get_embedder("nomic-embed-text", 768, PUBLIC_IP, "sk-fake-not-a-key",
                                 allow_remote=True)
        self.assertIsInstance(emb, E.OpenAICompatEmbedder)
        self.assertEqual(emb.endpoint_kind, "remote")

    def test_env_base_url_is_guarded_too(self):
        """$CHRONICLE_EMBED_BASE_URL was the unchecked door in the audit."""
        with mock.patch.dict(os.environ, {"CHRONICLE_EMBED_BASE_URL": PUBLIC_IP}), \
             _NoNetwork(self):
            self.assertEqual(E._permitted_urls(None, allow_remote=False), [],
                             "an off-host $CHRONICLE_EMBED_BASE_URL must not be probed")
            emb = E.get_embedder("auto", 768, None, None)
        self.assertIsInstance(emb, E.DegradedEmbedder)

    def test_env_base_url_is_probed_when_allow_remote_is_true(self):
        with mock.patch.dict(os.environ, {"CHRONICLE_EMBED_BASE_URL": PUBLIC_IP}):
            self.assertEqual(E._permitted_urls(None, allow_remote=True), [PUBLIC_IP])

    def test_recheck_keeps_refusing_the_same_off_host_endpoint(self):
        """A degraded-because-off-host embedder must not adopt that endpoint on
        a later probe. Fixing it means fixing the config, not waiting."""
        with _NoNetwork(self):
            emb = E.get_embedder("nomic-embed-text", 768, PUBLIC_IP, "sk-fake-not-a-key")
            self.assertIsInstance(emb, E.DegradedEmbedder)
            for _ in range(3):
                self.assertFalse(emb.recheck(force=True))
            self.assertIsNone(emb.live)

    def test_hashing_mode_is_untouched(self):
        with _NoNetwork(self):
            emb = E.get_embedder("hashing", 256, PUBLIC_IP, "sk-fake-not-a-key")
        self.assertIsInstance(emb, E.HashingEmbedder)
        self.assertEqual(len(emb.embed("Pat Testley")), 256)


# ---------------------------------------------------------------------------
# (4) the WARNING fires once
# ---------------------------------------------------------------------------

class TestWarnsOncePerProcess(_GuardTestCase):

    def _refusals(self, n, url=PUBLIC_IP):
        with self.assertLogs("chronicle.embeddings", level="DEBUG") as cm:
            for _ in range(n):
                try:
                    E.check_endpoint(url, allow_remote=False, purpose="embeddings")
                except E.RemoteEndpointRefused:
                    pass
        return cm.records

    def test_refusal_warns_exactly_once_across_many_refusals(self):
        records = self._refusals(12)
        warnings = [r for r in records if r.levelno >= logging.WARNING]
        self.assertEqual(len(warnings), 1,
                         "exactly one WARNING per process; got %d" % len(warnings))
        msg = warnings[0].getMessage()
        self.assertIn("REFUSED", msg)
        self.assertIn("embeddings.allow_remote", msg)
        # later refusals are still visible, just not at WARNING
        self.assertTrue([r for r in records if r.levelno == logging.DEBUG])

    def test_the_warning_names_what_happens_instead(self):
        msg = self._refusals(1)[0].getMessage()
        self.assertIn("queued", msg)

    def test_extraction_gets_its_own_one_warning(self):
        """Two different memory-bearing paths; silencing one must not silence
        the other, or a remote extractor could ride in behind a remote embedder."""
        with self.assertLogs("chronicle.embeddings", level="WARNING") as cm:
            for purpose, key in (("embeddings", "embeddings.allow_remote"),
                                 ("extraction", "extraction.llm.allow_remote")):
                for _ in range(4):
                    try:
                        E.check_endpoint(PUBLIC_IP, False, purpose=purpose, config_key=key)
                    except E.RemoteEndpointRefused:
                        pass
        self.assertEqual(len(cm.records), 2)

    def test_allow_remote_also_warns_once_and_says_memory_is_leaving(self):
        with self.assertLogs("chronicle.embeddings", level="WARNING") as cm:
            for _ in range(5):
                E.check_endpoint(PUBLIC_IP, allow_remote=True, purpose="embeddings")
        self.assertEqual(len(cm.records), 1)
        self.assertIn("OFF-HOST", cm.records[0].getMessage())

    def test_the_api_key_is_not_echoed_into_the_log(self):
        with self.assertLogs("chronicle.embeddings", level="WARNING") as cm:
            try:
                E.check_endpoint("https://198.51.100.9/v1?api_key=sk-super-secret",
                                 allow_remote=False)
            except E.RemoteEndpointRefused:
                pass
        self.assertNotIn("sk-super-secret", cm.records[0].getMessage())


# ---------------------------------------------------------------------------
# (5) the extractor — the path that sends the RAW excerpt
# ---------------------------------------------------------------------------

class TestExtractorGuard(_GuardTestCase):

    def _cfg(self, base_url, allow_remote=False):
        return Config({"extraction": {"backend": "llm",
                                      "llm": {"base_url": base_url, "model": "fake-chat-model",
                                              "allow_remote": allow_remote}}})

    def test_remote_llm_endpoint_falls_back_to_the_heuristic(self):
        with _NoNetwork(self):
            ex = make_extractor(self._cfg(PUBLIC_IP))
        self.assertIsInstance(ex, HeuristicExtractor)

    def test_remote_llm_extraction_still_extracts(self):
        """Refusal must not cost capture anything — that is why it is a
        fallback and not an error."""
        with _NoNetwork(self):
            ex = make_extractor(self._cfg(PUBLIC_IP))
            res = ex.extract("My name is Pat Testley. I work at Acme Fake Co.",
                             source_event="ev1", owner="default", domain="user", session_id="s1")
        self.assertTrue(res.items, "the heuristic must still produce items")

    def test_loopback_llm_endpoint_is_allowed(self):
        with _NoNetwork(self):
            ex = make_extractor(self._cfg("http://127.0.0.1:8080/v1"))
        self.assertIsInstance(ex, LLMExtractor)
        self.assertEqual(ex.endpoint_kind, "loopback")

    def test_private_llm_endpoint_is_allowed(self):
        with _NoNetwork(self):
            ex = make_extractor(self._cfg("http://192.168.1.42:8080/v1"))
        self.assertIsInstance(ex, LLMExtractor)

    def test_allow_remote_true_permits_the_llm_endpoint(self):
        with _NoNetwork(self):
            ex = make_extractor(self._cfg(PUBLIC_IP, allow_remote=True))
        self.assertIsInstance(ex, LLMExtractor)
        self.assertEqual(ex.endpoint_kind, "remote")

    def test_heuristic_backend_is_untouched(self):
        with _NoNetwork(self):
            ex = make_extractor(Config({}))
        self.assertIsInstance(ex, HeuristicExtractor)


# ---------------------------------------------------------------------------
# (6) end to end: capture -> process against a refused endpoint
# ---------------------------------------------------------------------------

class TestCaptureAgainstRefusedEndpoint(_GuardTestCase):
    """Beliefs are stored, NO vectors are written, nothing raises, nothing is sent.

    This is the shape of the production incident with the guard in place: the
    operator has pointed Chronicle at a hosted API, and the engine keeps every
    memory while sending none of it."""

    TRANSCRIPT = ("My name is Pat Testley\n"
                  "I work at Acme Fake Co\n"
                  "I live in Springfield\n"
                  "My manager is Dana Fictional")

    def setUp(self):
        super().setUp()
        self.home = tempfile.mkdtemp(prefix="a2_e2e_")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        super().tearDown()

    def _core(self, overrides):
        env = dict(os.environ)
        env.pop("CHRONICLE_EMBED_MODEL", None)   # eval/CI pin must not decide this test
        with mock.patch.dict(os.environ, env, clear=True):
            return ChronicleCore(self.home, overrides)

    def test_refused_endpoint_stores_beliefs_with_no_vectors_and_no_exception(self):
        with _NoNetwork(self):
            core = self._core({"embeddings": {"model": "nomic-embed-text",
                                              "base_url": PUBLIC_IP,
                                              "api_key": "sk-fake-not-a-key"}})
            self.assertIsInstance(core.embedder, E.DegradedEmbedder)
            core.initialize("s1", principal_id="assistant")
            core.capture.observe(self.TRANSCRIPT, "", session_id="s1")
            core.process_pending()
            core.curation.drain()

            conn = core.store._conn()
            beliefs = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            self.assertGreater(beliefs, 0, "capture must not depend on an embedder")
            for table in ("memory_vectors", "observed_vectors", "query_proxy_vectors"):
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0], 0,
                                 "%s must be empty when the endpoint was refused" % table)
            # and retrieval still answers from FTS/structured channels
            hits = core.retrieval.search("where does Pat Testley work", limit=5)
            self.assertTrue(hits, "FTS retrieval must still work in degraded mode")

    def test_a_loopback_endpoint_is_not_refused_by_the_same_code_path(self):
        """The control: same config shape, on-host URL — the engine keeps the
        configured client instead of degrading. (It is unreachable in CI, which
        is a different, pre-existing state; what matters is that it was not
        REFUSED.)"""
        with _NoNetwork(self), \
             mock.patch.object(E.OpenAICompatEmbedder, "healthcheck",
                               side_effect=RuntimeError("not probing in a test")):
            core = self._core({"embeddings": {"model": "nomic-embed-text",
                                              "base_url": "http://127.0.0.1:11434/v1"}})
        self.assertIsInstance(core.embedder, E.OpenAICompatEmbedder)
        self.assertEqual(core.embedder.endpoint_kind, "loopback")

    def test_allow_remote_true_reaches_the_engine_from_config(self):
        with _NoNetwork(self), \
             mock.patch.object(E.OpenAICompatEmbedder, "healthcheck",
                               side_effect=RuntimeError("not probing in a test")):
            core = self._core({"embeddings": {"model": "nomic-embed-text",
                                              "base_url": PUBLIC_IP,
                                              "allow_remote": True}})
        self.assertIsInstance(core.embedder, E.OpenAICompatEmbedder)


# ---------------------------------------------------------------------------
# (7) config honesty
# ---------------------------------------------------------------------------

class TestConfigHonesty(_GuardTestCase):

    def test_both_flags_exist_and_default_to_false(self):
        cfg = Config({})
        self.assertIs(cfg.get("embeddings.allow_remote"), False)
        self.assertIs(cfg.get("extraction.llm.allow_remote"), False)

    def test_the_config_comment_no_longer_states_an_unenforced_absolute(self):
        """`config.py` used to say flatly "No remote-API tier: memory excerpts
        never leave the host" with nothing checking it. The comment must now
        state the guarantee the code actually provides — one conditional on the
        flag — or the same class of defect returns as documentation."""
        src = (Path(__file__).parent.parent / "engine" / "config.py").read_text(encoding="utf-8")
        self.assertNotIn("No remote-API tier: memory excerpts never", src)
        self.assertIn("allow_remote", src)
        self.assertIn("with allow_remote false, memory excerpts never leave the host", src)

    def test_readme_documents_the_flag(self):
        src = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("allow_remote", src)
        self.assertIn("extraction.llm.allow_remote", src)

    def test_dashboard_docstring_no_longer_credits_out_of_tree_scripts(self):
        src = (Path(__file__).parent.parent / "dashboard" / "plugin_api.py").read_text(
            encoding="utf-8")
        i = src.index("def _get_embedding_stats")
        doc = src[i:i + 2500]
        self.assertIn("NEVER WRITES THAT KIND", doc,
                      "the docstring must say the engine does not write kind='document'")
        self.assertNotIn("Mirrors the actual embedding pipeline (see scripts/enrich_embeddings.py",
                         src)

    def test_the_engine_really_does_not_write_kind_document(self):
        """The claim the corrected docstring makes, checked against the code
        rather than trusted."""
        from engine.store import KIND_TABLE
        self.assertNotIn("document", KIND_TABLE)


# ---------------------------------------------------------------------------
# (8) MUTATION GUARD — remove the guard, these tests must fail
# ---------------------------------------------------------------------------

def _pre_a2_check_endpoint(url, allow_remote=False, purpose="embeddings",
                           config_key="embeddings.allow_remote"):
    """The world before A2: any URL is trusted, nothing is refused."""
    return "loopback"


class TestMutationGuard(_GuardTestCase):
    """Every assertion above is only worth as much as its behaviour under the
    defect. These re-run the load-bearing checks with the guard removed and
    assert they FAIL."""

    def _core_assertions_of_the_guard(self, check):
        """The two claims the whole task rests on: a public IP is refused, and a
        hosted-API URL is refused, at default config."""
        raised = 0
        for url in (PUBLIC_IP, PUBLIC_HTTPS):
            try:
                check(url, False, "embeddings", "embeddings.allow_remote")
            except E.RemoteEndpointRefused:
                raised += 1
        assert raised == 2, "expected both off-host endpoints to be refused, got %d" % raised

    def test_the_assertions_hold_with_the_guard_present(self):
        r = _FakeResolver({"api.openrouter.example": ["104.18.2.7"]})
        with mock.patch.object(E, "_getaddrinfo", r):
            self._core_assertions_of_the_guard(E.check_endpoint)

    def test_the_assertions_fail_with_the_guard_removed(self):
        with self.assertRaises(AssertionError):
            self._core_assertions_of_the_guard(_pre_a2_check_endpoint)

    def test_degradation_disappears_with_the_guard_removed(self):
        """With the guard neutered, get_embedder builds a live client for a
        public endpoint again — which is exactly the production incident."""
        with mock.patch.object(E, "check_endpoint", _pre_a2_check_endpoint), \
             mock.patch.object(E.OpenAICompatEmbedder, "healthcheck",
                               side_effect=RuntimeError("not probing in a test")), \
             _NoNetwork(self):
            emb = E.get_embedder("nomic-embed-text", 768, PUBLIC_IP, "sk-fake-not-a-key")
        self.assertNotIsInstance(emb, E.DegradedEmbedder,
                                 "sanity: without the guard this must NOT degrade")
        self.assertIsInstance(emb, E.OpenAICompatEmbedder)

    def test_extractor_fallback_disappears_with_the_guard_removed(self):
        import engine.extraction as X
        with mock.patch.object(X, "check_endpoint", _pre_a2_check_endpoint), _NoNetwork(self):
            ex = make_extractor(Config({"extraction": {
                "backend": "llm",
                "llm": {"base_url": PUBLIC_IP, "model": "fake-chat-model"}}}))
        self.assertIsInstance(ex, LLMExtractor,
                              "sanity: without the guard the remote extractor is built")

    def test_ipv4_mapped_hole_reopens_if_classification_trusts_is_private(self):
        """The specific mutation this codebase would most plausibly regress to:
        classifying with `ipaddress.is_private` instead of the explicit table.
        On Python 3.9 that reports ::ffff:0:0/96 as private, so a public v4 in a
        v6 wrapper would be admitted."""
        import ipaddress as _ip
        naive = _ip.ip_address("::ffff:8.8.8.8")
        self.assertTrue(naive.is_private or naive.ipv4_mapped is not None,
                        "fixture assumption: the naive check would not say 'remote'")
        self.assertEqual(E.classify_address(naive), "remote",
                         "the guard must judge an IPv4-mapped address by the v4 inside it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
