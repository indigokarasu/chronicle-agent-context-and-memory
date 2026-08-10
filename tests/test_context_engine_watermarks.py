"""
Chronicle — tests for context.py two-watermark hysteresis + real token
accounting (Ladder 7, R2).

Ladder 7's R0 gives this area its own end-to-end fidelity harness
(tests/test_compression_fidelity.py: byte-exact I17 recovery, fallback
parity, pin survival, ...). These tests are scoped tighter, to the two
things R2 itself changes:

  1. compress() bounds its own output by a real token budget (the LOW
     watermark, a fraction of context_length) instead of an unbounded
     score>=0.5 keep/evict bit that kept everything clearing the cutoff
     with no notion of how much room that took.
  2. the eviction decision and the re-injected memory block both use REAL
     per-span token estimates (engine.embeddings.estimate_tokens), not a
     flat, model-unaware constant -- the config default_token_budget=1500
     that get_context's own signature already declared but context.py
     ignored, and the literal 500 hardcoded at the call site.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import estimate_tokens
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


class ContextEngineWatermarkTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="r2_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("r2-s1", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertIsNotNone(self.eng.core, "test setup expected the real (non-heuristic) engine")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    @staticmethod
    def _output_tokens(out):
        return sum(estimate_tokens(m.get("content")) for m in out)

    # -- 1. compress() guarantees output <= budget -----------------------
    def test_compress_output_stays_under_low_watermark_budget(self):
        self.eng.update_model("test-model", context_length=2000)  # -> budget = 0.55 * 2000 = 1100
        messages = _messages(40)
        out = self.eng.compress(list(messages), focus_topic=None)
        budget = self.eng._target_budget()
        total = self._output_tokens(out)
        self.assertLessEqual(total, budget,
                              "compress() exceeded its own budget: %d tokens > %d budget" % (total, budget))
        self.assertLess(len(out), len(messages), "fixture should be large enough to force real eviction")

    def test_compress_clips_oversized_protected_tail_to_stay_under_budget(self):
        # Regression: protected head/tail/never-evict content used to be
        # added to `used` unconditionally with no clamp. should_compress
        # only fires once the window is already past the HIGH watermark, so
        # a single large recent tool-output turn landing in protect_last_n
        # (the last 6 messages) is a realistic way for the protected set
        # alone to blow past the LOW watermark budget before a single
        # evictable middle span is even considered.
        self.eng.update_model("test-model", context_length=1000)  # -> budget = 0.55 * 1000 = 550
        huge = "Acme Fake Co tool output: " + ("x" * 6000)  # ~2009 tokens, alone > budget
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + [_msg("user", "middle filler %d %s" % (i, "pad " * 20)) for i in range(10)]
            + [_msg("assistant", "tail %d" % i) for i in range(5)]
            + [_msg("assistant", huge)]  # 6th-from-end -> lands inside protect_last_n
        )
        out = self.eng.compress(list(messages), focus_topic=None)
        budget = self.eng._target_budget()
        total = self._output_tokens(out)
        self.assertLessEqual(total, budget,
                              "compress() exceeded its own budget even with an oversized "
                              "protected span: %d tokens > %d budget" % (total, budget))
        self.assertTrue(
            any("Acme Fake Co tool output:" in (m.get("content") or "") for m in out),
            "the oversized protected span must stay present (clipped), not be dropped")

    def test_compress_output_stays_under_budget_with_pressure_warning(self):
        # R9 regression: the pressure-warning span (emitted once compress()
        # detects last_prompt_tokens >= threshold_tokens, the HIGH watermark)
        # must be counted against the SAME budget as everything else. A first
        # cut appended it after budget-fitting, uncounted, and landed at 615
        # tokens against this exact fixture's 550-token budget.
        self.eng.update_model("test-model", context_length=1000)  # budget = 550, threshold = 750
        huge = "Acme Fake Co tool output: " + ("x" * 6000)  # ~2009 tokens alone, > budget
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + [_msg("user", "middle filler %d %s" % (i, "pad " * 20)) for i in range(10)]
            + [_msg("assistant", "tail %d" % i) for i in range(5)]
            + [_msg("assistant", huge)]  # lands inside protect_last_n
        )
        self.eng.update_from_response({"prompt_tokens": self.eng.threshold_tokens,
                                       "completion_tokens": 0, "total_tokens": 0})
        self.assertTrue(self.eng.is_under_pressure(), "test setup: fixture must be at/above the HIGH watermark")
        out = self.eng.compress(list(messages), focus_topic=None)
        budget = self.eng._target_budget()
        total = self._output_tokens(out)
        self.assertLessEqual(total, budget,
                              "compress() exceeded its own budget once the pressure-warning span "
                              "is included: %d tokens > %d budget" % (total, budget))

    def test_pressure_warning_latches_once_not_lost_by_small_body_shortcut(self):
        # R9 regression: compress()'s small-body early return
        # (len(body) <= protect_first_n + protect_last_n) used to run AFTER
        # the warning flag was already latched True, so the flag was set but
        # the warning never reached the caller -- permanently, since the flag
        # only resets when update_from_response observes pressure drop below
        # the watermark. The internal latch must never disagree with whether
        # a warning was actually delivered.
        self.eng.update_model("test-model", context_length=2000)  # threshold = 1500
        small_body = [_msg("user" if i % 2 == 0 else "assistant", "pad %d" % i) for i in range(4)]
        self.assertLessEqual(len(small_body), self.eng.protect_first_n + self.eng.protect_last_n,
                              "test setup: body must be small enough to hit the early-return shortcut")
        messages = [_msg("system", "sys")] + small_body
        self.eng.update_from_response({"prompt_tokens": self.eng.threshold_tokens,
                                       "completion_tokens": 0, "total_tokens": 0})
        out = self.eng.compress(list(messages), focus_topic=None)
        delivered = any(m.get("role") == "system" and "[Context pressure warning]" in (m.get("content") or "")
                        for m in out)
        self.assertTrue(delivered, "small-body shortcut must still deliver the pressure warning")
        self.assertEqual(self.eng._pressure_warning_injected, delivered,
                          "internal latch must match whether the warning was actually delivered")

    def test_budget_scales_with_context_length(self):
        self.eng.update_model("small-model", context_length=400)
        small_budget = self.eng._target_budget()
        self.eng.update_model("big-model", context_length=40000)
        big_budget = self.eng._target_budget()
        self.assertGreater(big_budget, small_budget,
                            "budget should scale with the model's actual context window")
        self.assertEqual(small_budget, int(400 * 0.55))
        self.assertEqual(big_budget, int(40000 * 0.55))

    def test_budget_falls_back_to_config_default_without_context_length(self):
        # update_model() never called on a fresh engine: context_length stays 0,
        # matching a standalone caller that hasn't reported a model window yet.
        fresh = ChronicleContextEngine()
        fresh.on_session_start("r2-s2", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertEqual(fresh.context_length, 0)
        budget = fresh._target_budget()
        self.assertEqual(budget, self.core.cfg.get("context.default_token_budget", 1500))

    def test_high_watermark_config_drives_should_compress_threshold(self):
        self.eng.update_model("test-model", context_length=1000)
        self.assertEqual(self.eng.threshold_percent,
                          self.core.cfg.get("context_engine.high_watermark_percent", 0.75))
        self.assertEqual(self.eng.threshold_tokens, int(1000 * self.eng.threshold_percent))

    # -- 2. real per-span accounting replaces the score>=0.5 bit ----------
    def test_highest_scoring_spans_survive_under_pressure(self):
        self.eng.update_model("test-model", context_length=800)  # budget ~440: too tight for all 12 spans
        focus = "quarterly-roadmap"
        pad = "padding " * 20
        relevant = [_msg("user", "quarterly-roadmap detail %d: %s" % (i, pad)) for i in range(6)]
        irrelevant = [_msg("assistant", "off topic filler %d: %s" % (i, pad)) for i in range(6)]
        middle = []
        for r, ir in zip(relevant, irrelevant):  # interleave: order alone can't explain the outcome
            middle.append(ir)
            middle.append(r)
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + middle
            + [_msg("assistant", "tail %d" % i) for i in range(6)]
        )
        out = self.eng.compress(list(messages), focus_topic=focus)
        kept_contents = {m.get("content") for m in out}
        kept_relevant = sum(1 for m in relevant if m["content"] in kept_contents)
        kept_irrelevant = sum(1 for m in irrelevant if m["content"] in kept_contents)
        self.assertGreater(kept_relevant, kept_irrelevant,
                            "focus-relevant spans should be admitted before irrelevant ones "
                            "under budget pressure (kept_relevant=%d, kept_irrelevant=%d)"
                            % (kept_relevant, kept_irrelevant))

    def test_evicted_spans_are_made_durable_before_eviction_I17(self):
        self.eng.update_model("test-model", context_length=2000)
        messages = _messages(40)
        before = len(self.core.store.get_events_by_type("observed"))
        out = self.eng.compress(list(messages), focus_topic=None)
        after = len(self.core.store.get_events_by_type("observed"))
        self.assertLess(len(out), len(messages), "fixture should force at least one eviction")
        self.assertGreater(after, before,
                            "evicted spans must be durable (I17) -- no 'observed' events were written")

    # -- 3. reinjection budget is config-driven, not the bare 500 --------
    def test_reinjection_budget_is_not_the_bare_500_constant(self):
        seen = {}
        real_get_context = self.core.retrieval.get_context

        def spy(hint, **kwargs):
            seen["token_budget"] = kwargs.get("token_budget")
            return real_get_context(hint, **kwargs)

        self.core.retrieval.get_context = spy
        self.eng.update_model("test-model", context_length=100000)  # plenty of headroom for injection
        messages = _messages(20)
        self.eng.compress(list(messages), focus_topic="something")
        self.assertIn("token_budget", seen, "get_context was not called for reinjection")
        self.assertNotEqual(seen["token_budget"], 500,
                             "reinjection still hardcodes the old 500-token constant")
        self.assertLessEqual(seen["token_budget"], self.core.cfg.get("context.default_token_budget", 1500))


if __name__ == "__main__":
    unittest.main()
