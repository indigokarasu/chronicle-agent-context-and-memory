"""
Chronicle — the rest of A13's dead-code sweep, with a test per removal.

Each of these was a body that was literally `pass`, or a file that was a copy of
another file. Removing such a thing is only safe if you can say what depended on
it; a test per removal is that statement, written so it fails if the removal was
wrong rather than if the code merely changed shape.

  * `provider.queue_prefetch` — a no-op OVERRIDE of a host method whose base is
    already a no-op. Removed; the host contract still holds by inheritance.
  * `capture.flush_best_effort` — a no-op called by `provider.shutdown()`, i.e.
    a call that read like a durability guarantee and was not one. Removed with
    its call site; capture was already durable at append time.
  * `reducer._on_distilled` — a `pass` entry in the event-dispatch table for an
    event type nothing in this build appends. Removed, so such an event is now
    reported instead of silently swallowed.
  * the `.bak` and `.log` files that were tracked in the tree.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from provider import ChronicleMemoryProvider

_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# provider.queue_prefetch: removed override, contract preserved
# ---------------------------------------------------------------------------
class TestQueuePrefetchOverrideIsGone(unittest.TestCase):
    def test_chronicle_does_not_define_its_own(self):
        """It defined one whose body was `pass` — a second copy of the base's
        own documented no-op default, which reads like unfinished work."""
        self.assertNotIn("queue_prefetch", vars(ChronicleMemoryProvider))

    def test_a_host_can_still_call_it(self):
        """The removal is only safe because the BASE provides it: Hermes calls
        queue_prefetch after every turn (run_agent's queue_prefetch_all), so an
        AttributeError here would be a live crash, not dead code."""
        p = ChronicleMemoryProvider()
        self.assertTrue(hasattr(p, "queue_prefetch"))
        self.assertIsNone(p.queue_prefetch("anything", session_id="s1"))

    def test_prefetch_itself_is_untouched(self):
        """The method that DOES work is Chronicle's own, and stays."""
        self.assertIn("prefetch", vars(ChronicleMemoryProvider))


# ---------------------------------------------------------------------------
# capture.flush_best_effort: removed no-op, and the reason it was safe
# ---------------------------------------------------------------------------
class TestShutdownHasNothingToFlush(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a13-flush-")
        self.provider = ChronicleMemoryProvider()
        self.provider.initialize("s1", hermes_home=self.home, principal_id="assistant",
                                 config={"embeddings": {"model": "hashing"}})

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_the_no_op_method_is_gone_from_both_sides(self):
        """Callee and call site. The name still appears in shutdown()'s
        docstring, which is where the removal is explained, so the call is
        looked for in the AST rather than in the text."""
        import ast
        from engine.capture import CaptureEngine
        self.assertFalse(hasattr(CaptureEngine, "flush_best_effort"))
        tree = ast.parse((_ROOT / "provider.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "flush_best_effort"]
        self.assertEqual(calls, [], "provider.py still calls it")

    def test_a_captured_turn_is_durable_BEFORE_shutdown_is_called(self):
        """Why removing the call is safe: capture is an append_event per turn,
        in its own transaction (I12). A second handle on the same database sees
        the row while the first process is still running — there is no buffer
        for a flush to drain."""
        from engine.store import MemoryStore
        self.provider.sync_turn("Remember the fixture city is Testland",
                                "Noted.", session_id="s1")
        db_path = self.provider.core.store.db_path
        observer = MemoryStore(str(db_path))
        before = observer._conn().execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        self.assertGreater(before, 0, "the turn was still buffered somewhere")
        self.provider.shutdown()
        after = observer._conn().execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        self.assertEqual(after, before, "shutdown wrote events that capture had held back")

    def test_shutdown_still_runs_and_still_mirrors(self):
        """flush_git stays: the git mirror IS deferred, out-of-store work."""
        self.assertIn("flush_git", (_ROOT / "provider.py").read_text(encoding="utf-8"))
        self.provider.shutdown()          # must not raise


# ---------------------------------------------------------------------------
# reducer._on_distilled: a no-op entry for an event nothing writes
# ---------------------------------------------------------------------------
class TestDistilledHandlerIsGone(unittest.TestCase):
    def test_the_dispatch_table_no_longer_swallows_it(self):
        from engine.reducer import Reducer
        self.assertNotIn("distilled", Reducer._HANDLERS)
        self.assertFalse(hasattr(Reducer, "_on_distilled"))

    def test_nothing_in_the_tree_appends_such_an_event(self):
        """The justification for removing rather than documenting: there is no
        producer, so the entry could only ever hide an event from a foreign log.
        Compare `folded`, `signal` and `compressed`, which are near-no-op
        handlers WITH producers and are therefore kept."""
        from engine.reducer import Reducer
        shipped = [p for p in _ROOT.rglob("*.py")
                   if "tests" not in p.parts and "__pycache__" not in p.parts
                   and p.name != "reducer.py"]
        blob = "\n".join(p.read_text(encoding="utf-8") for p in shipped)
        self.assertNotIn('"distilled"', blob)
        self.assertNotIn("'distilled'", blob)
        for kept in ("folded", "signal", "compressed"):
            self.assertIn(kept, Reducer._HANDLERS)
            self.assertIn('"%s"' % kept, blob, "%s lost its producer" % kept)

    def test_an_unknown_type_is_reported_rather_than_dropped(self):
        """What replaces the `pass`: reduce() already logs and returns. That is
        strictly more honest than a handler that silently accepts it."""
        from engine.reducer import Reducer
        r = Reducer.__new__(Reducer)
        with self.assertLogs("chronicle.reducer", level="WARNING") as caught:
            r.reduce({"type": "distilled", "payload": "{}"})
        self.assertIn("Unknown event type", "".join(caught.output))


class TestTheFlagBehindTheRemovedOverrideSaysItIsDormant(unittest.TestCase):
    """Removing `queue_prefetch` leaves `retrieval.predictive_prefetch: True` in
    DEFAULTS with no reader at all. A boolean that is on and means nothing is
    the same defect as a task name the schema admits and nothing can run, so it
    is declared DORMANT (the mechanism this tree already has) rather than left
    to read as a live feature — or deleted, which would make an operator's own
    setting disappear without a word."""

    def test_no_source_file_reads_it(self):
        readers = []
        for path in _ROOT.rglob("*.py"):
            if "/tests/" in str(path) or path.name == "config.py":
                continue
            if "predictive_prefetch" in path.read_text(encoding="utf-8"):
                readers.append(str(path.relative_to(_ROOT)))
        self.assertEqual(readers, [], "it has a reader now; drop the DORMANT entry")

    def test_it_is_declared_dormant_and_warns_while_it_is_on(self):
        from engine.config import DORMANT, _DORMANT_WARNED, Config
        keys = [k for k, _pred, _why in DORMANT]
        self.assertIn("retrieval.predictive_prefetch", keys)
        self.assertTrue(Config({}).get("retrieval.predictive_prefetch"),
                        "still defaults on, so the warning must be reachable")
        _DORMANT_WARNED.discard("retrieval.predictive_prefetch")
        with self.assertLogs("chronicle.config", level="WARNING") as caught:
            Config({})                       # _check_dormant_flags runs in __init__
        self.assertTrue(any("predictive_prefetch" in line for line in caught.output),
                        caught.output)
        # …and once per process, not once per Config: the engine builds one on
        # every LME query.
        with self.assertRaises(AssertionError):
            with self.assertLogs("chronicle.config", level="WARNING"):
                Config({})

    def test_it_stays_quiet_when_an_operator_turns_it_off(self):
        from engine.config import _DORMANT_WARNED, Config
        _DORMANT_WARNED.discard("retrieval.predictive_prefetch")
        with self.assertRaises(AssertionError):
            with self.assertLogs("chronicle.config", level="WARNING"):
                Config({"retrieval": {"predictive_prefetch": False}})

    def test_a_flag_that_IS_read_is_not_declared_dormant(self):
        """The neighbouring key. provider.prefetch reads prefetch_budget on the
        synchronous path, so declaring it dormant would be a false warning."""
        from engine.config import DORMANT
        self.assertNotIn("retrieval.prefetch_budget", [k for k, _p, _w in DORMANT])


# ---------------------------------------------------------------------------
# repo hygiene: a copy of a live file must not ship
# ---------------------------------------------------------------------------
class TestNoBackupOrLogFilesAreTracked(unittest.TestCase):
    def _tracked(self):
        out = subprocess.run(["git", "ls-files"], cwd=str(_ROOT),
                             capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest("not a git checkout")
        return out.stdout.split("\n")

    def test_the_three_named_by_the_audit_are_gone_from_the_tree(self):
        for name in ("dashboard/plugin_api.py.bak",
                     "plugin.yaml.bak.20260625_114235",
                     "ctx_eval_r2.log"):
            self.assertFalse((_ROOT / name).exists(), "%s is back" % name)

    def test_no_backup_or_log_file_is_tracked_at_all(self):
        """The general rule, not the three instances: a stale copy of a live
        module is worse than no copy, because a reader cannot tell which is
        real, and a release tarball ships both."""
        bad = [f for f in self._tracked()
               if f.endswith(".log") or ".bak" in f or f.endswith((".orig", ".rej"))]
        self.assertEqual(bad, [], "backup/artifact files are tracked: %s" % bad)

    def test_gitignore_keeps_them_out(self):
        ignore = (_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("*.bak", "*.bak.*", "*.log"):
            self.assertIn(pattern, ignore)


if __name__ == "__main__":
    unittest.main()
