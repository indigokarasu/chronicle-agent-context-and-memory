"""
Chronicle — tests for context.py should_compress_preflight (Ladder 7, R10).

should_compress_preflight was hardcoded `return False`: the 400ms
`capture.precompress.budget_ms` config existed but no code path ever spent
it. R10 wires it to do the I/O-heavy part of a compress() pass -- rescue
(§12.6/I14) and pre-durabilizing (§I17) the spans that would be evicted if
compress() ran right now ("fold candidates", in the R4 sense) -- ahead of
the HIGH watermark, so that work is already paid for by the time
should_compress() actually forces compress() onto the reactive/deadline
path.

These tests are scoped to what R10 itself changes:
  1. Preflight only acts in the LOW..HIGH watermark gap: no pressure yet
     below LOW, and at/above HIGH the reactive path already owns the pass.
  2. In that gap, it durably stores the current fold candidates (I17) and
     runs rescue, and reports back that it did so.
  3. It never blows past `capture.precompress.budget_ms`.
  4. compress() itself is unaffected -- still bounds output to budget and
     still evicts correctly whether or not preflight ran first.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from context import ChronicleContextEngine

CFG = {"embeddings": {"model": "hashing"}}  # offline, deterministic

_LONG_BODY = ("Acme Fake Co turn %d: unrelated filler padded out to cost real "
              "tokens under the hashing embedder so eviction actually has work to do.")


def _msg(role, text):
    return {"role": role, "content": text}


def _messages(n, body_text=_LONG_BODY):
    return (
        [_msg("system", "You are helping Pat Testley at Acme Fake Co.")]
        + [_msg("user" if i % 2 == 0 else "assistant", body_text % i) for i in range(n)]
    )


def _durability_events(core, session_id):
    import json
    evs = core.store.get_events_by_session(session_id)
    return [e for e in evs if e["type"] == "observed"
            and json.loads(e["payload"]).get("source_type") == "context_eviction"]


class PreflightWatermarkGateTests(unittest.TestCase):
    """When preflight is allowed to act at all (§R10 gate)."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="r10_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("r10-s1", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertIsNotNone(self.eng.core, "test setup expected the real (non-heuristic) engine")
        self.eng.update_model("test-model", context_length=2000)  # HIGH=1500, LOW=1100

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_false_without_a_core(self):
        """No store to rescue/durabilize into -- matches R1's heuristic-fallback parity."""
        fresh = ChronicleContextEngine()  # no on_session_start -> self.core stays None
        self.assertFalse(fresh.should_compress_preflight(_messages(28)))

    def test_false_below_low_watermark(self):
        """No pressure yet -- nothing worth prepping for."""
        messages = _messages(22)  # ~981 tokens, under the 1100 LOW watermark
        self.assertFalse(self.eng.should_compress_preflight(messages))
        self.assertEqual(_durability_events(self.core, "r10-s1"), [],
                          "preflight must not do fold-candidate work below the low watermark")

    def test_false_at_or_above_high_watermark(self):
        """Already due -- should_compress() owns this pass now, not preflight."""
        messages = _messages(40)  # ~1791 tokens, over the 1500 HIGH watermark
        self.assertGreaterEqual(sum(self._tokens(m) for m in messages), self.eng.threshold_tokens)
        self.assertFalse(self.eng.should_compress_preflight(messages))

    def test_false_without_a_known_context_length(self):
        """context_length never set (update_model not yet called) -- watermarks are undefined."""
        fresh = ChronicleContextEngine()
        fresh.on_session_start("r10-s2", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertEqual(fresh.context_length, 0)
        self.assertFalse(fresh.should_compress_preflight(_messages(28)))

    @staticmethod
    def _tokens(m):
        from engine.embeddings import estimate_tokens
        return estimate_tokens(m.get("content"))


class PreflightDoesTheWorkTests(unittest.TestCase):
    """In the LOW..HIGH gap, preflight actually rescues + pre-durabilizes (§R10)."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="r10_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("r10-s1", hermes_home=self.home, principal_id="pat", config=CFG)
        self.eng.update_model("test-model", context_length=2000)  # HIGH=1500, LOW=1100
        self.messages = _messages(28)  # ~1251 tokens: squarely inside the gap

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_true_in_the_gap(self):
        self.assertTrue(self.eng.should_compress_preflight(list(self.messages)))

    def test_rescue_runs(self):
        calls = []
        real_rescue = self.core.capture.rescue

        def spy(messages, **kw):
            calls.append((messages, kw))
            return real_rescue(messages, **kw)

        self.core.capture.rescue = spy
        self.eng.should_compress_preflight(list(self.messages))
        self.assertEqual(len(calls), 1, "preflight must rescue exactly once per call")
        self.assertEqual(calls[0][1].get("session_id"), "r10-s1")

    def test_fold_candidates_are_durably_stored_ahead_of_compress(self):
        """The I17 durability write for spans compress() would evict happens
        during preflight, BEFORE compress() itself is ever called."""
        before = _durability_events(self.core, "r10-s1")
        self.assertEqual(before, [], "setup invariant: nothing durable yet")
        self.eng.should_compress_preflight(list(self.messages))
        after = _durability_events(self.core, "r10-s1")
        self.assertGreater(len(after), 0,
                            "preflight should have pre-durabilized at least one fold candidate")

    def test_preflight_then_compress_still_evicts_correctly_and_stays_under_budget(self):
        """R2's guarantees hold whether or not preflight ran first."""
        from engine.embeddings import estimate_tokens
        self.eng.should_compress_preflight(list(self.messages))
        grown = self.messages + _messages(15)[1:]  # append more turns; drop the extra system msg
        out = self.eng.compress(list(grown))
        total = sum(estimate_tokens(m.get("content")) for m in out)
        budget = self.eng._target_budget()
        self.assertLessEqual(total, budget,
                              "compress() must still honor its budget after a preflight pass")
        self.assertLess(len(out), len(grown), "growth past HIGH should still force real eviction")


class PreflightBudgetTests(unittest.TestCase):
    """capture.precompress.budget_ms actually bounds the work done (§R10)."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="r10_budget_")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_zero_budget_skips_fold_candidate_work(self):
        """budget_ms=0: rescue may still run, but the (potentially large) fold-
        candidate durability loop must not -- the deadline is already spent
        the instant should_compress_preflight starts scoring the window."""
        cfg = {"embeddings": {"model": "hashing"},
               "capture": {"precompress": {"budget_ms": 0}}}
        core = ChronicleCore.get(self.home, cfg)
        eng = ChronicleContextEngine()
        eng.on_session_start("r10-budget-s1", hermes_home=self.home, principal_id="pat", config=cfg)
        eng.update_model("test-model", context_length=2000)
        self.assertEqual(core.cfg.get("capture.precompress.budget_ms"), 0)

        messages = _messages(28)  # same in-gap fixture as above
        eng.should_compress_preflight(list(messages))
        evs = _durability_events(core, "r10-budget-s1")
        self.assertEqual(evs, [],
                          "a zero-ms budget must skip fold-candidate pre-durability entirely")

    def test_default_budget_is_read_from_config_not_reimplemented(self):
        """The previously-dead 400ms default (capture.precompress.budget_ms)
        is the value actually driving the deadline -- not a hardcoded literal
        in context.py."""
        cfg = {"embeddings": {"model": "hashing"},
               "capture": {"precompress": {"budget_ms": 5000}}}  # generous: never trips mid-test
        core = ChronicleCore.get(self.home, cfg)
        eng = ChronicleContextEngine()
        eng.on_session_start("r10-budget-s2", hermes_home=self.home, principal_id="pat", config=cfg)
        eng.update_model("test-model", context_length=2000)
        self.assertEqual(core.cfg.get("capture.precompress.budget_ms"), 5000)

        messages = _messages(28)
        eng.should_compress_preflight(list(messages))
        evs = _durability_events(core, "r10-budget-s2")
        self.assertGreater(len(evs), 0,
                            "a generous budget should let fold-candidate durability complete")


if __name__ == "__main__":
    unittest.main()
