"""
Chronicle — tests for compress()'s cut-point geometry + prefix stability
(Ladder 7, R5).

test_compression_fidelity.py's prefix_stability_across_growth check already
guards the property "a tail-protected span must not be dropped once the
conversation grows" -- but its fixture is small enough that R2's watermark
budget never actually forces an eviction, so that check can pass for the
wrong reason (nothing is ever evicted, tail-protected or not). These tests
force REAL eviction pressure (a tight context_length budget, like
test_context_engine_watermarks.py does for R2) so the R5 guarantee is
exercised for real:

  1. Once compress() commits to a prefix, a LATER pass under real eviction
     pressure reproduces that exact prefix byte-for-byte and in the same
     order -- new content is genuinely appended, not interleaved back in by
     re-scoring the whole window from scratch (the old bug: a message that
     was tail-protected slides into the rescored middle as the window grows
     and gets evicted -- see BASELINE.md assertion #11).
  2. compress() does not hoist system-role messages to the front of the
     window when they weren't already there -- the other named cause of
     provider-cache-hostile prefix churn.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.embeddings import estimate_tokens
from context import ChronicleContextEngine

CFG = {"embeddings": {"model": "hashing"}}  # offline, deterministic


def _msg(role, text):
    return {"role": role, "content": text}


class CutPointStabilityTests(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="r5_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("r5-s1", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertIsNotNone(self.eng.core, "test setup expected the real (non-heuristic) engine")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    # -- append-only growth under real eviction pressure ---------------------

    def test_settled_prefix_survives_growth_under_real_eviction_pressure(self):
        self.eng.update_model("test-model", context_length=1500)  # budget = 0.55 * 1500 = 825
        # A10b units restatement: 2000 x 3 = 6000 = 1500 x 4.

        head = [_msg("user", "head %d" % i) for i in range(3)]
        small_middle = [_msg("assistant", "small filler %d" % i) for i in range(4)]
        stable_tail = [_msg("assistant", "STABLE-TAIL-%d" % i) for i in range(6)]
        pass1 = head + small_middle + stable_tail  # well under budget -> nothing evicted yet

        result1 = self.eng.compress(list(pass1), focus_topic=None)
        self.assertEqual(result1, pass1, "setup invariant: small pass-1 window should pass through untouched")

        pad = "padding " * 40  # sized so 20 of these alone blow well past the remaining budget
        growth = [_msg("user" if i % 2 else "assistant", "GROWTH-%d %s" % (i, pad)) for i in range(20)]
        pass2 = list(result1) + growth

        before = len(self.core.store.get_events_by_type("observed"))
        result2 = self.eng.compress(pass2, focus_topic=None)
        after = len(self.core.store.get_events_by_type("observed"))

        # 1) the pass-1 window is reproduced byte-for-byte, in the same
        #    order, as an exact PREFIX of the pass-2 output -- nothing about
        #    it was rescored, reordered, or reconsidered for eviction.
        self.assertEqual(result2[:len(result1)], result1,
                          "settled prefix must survive growth unchanged -- compress() should never "
                          "re-litigate a decision it already committed to (R5)")

        # 2) this was a REAL test of eviction, not a vacuous one: the tight
        #    budget must have forced at least one new GROWTH span to be
        #    evicted (and made durable per I17), not silently admitted.
        self.assertGreater(after, before,
                            "fixture should force real eviction of new growth content -- otherwise "
                            "this test cannot tell append-only-on-purpose from nothing-ever-evicted")
        total_tokens = sum(estimate_tokens(m.get("content")) for m in result2)
        budget = self.eng._target_budget()
        self.assertLessEqual(total_tokens, budget,
                              "compress() must still honor the R2 budget guarantee while doing so")

    def test_repeated_compression_never_shrinks_or_reorders_the_settled_prefix(self):
        """Multiple compression passes in a row, each adding more growth.

        A pass that EXTENDS must reproduce the settled prefix byte for byte
        (R5): the provider's prompt cache keeps it. But a settled prefix only
        grows, and the old version of this test pinned what happened once it
        filled the budget: every later pass folded ALL new content -- the
        protected latest turns included -- so the message count "converged"
        on a window frozen in the past that never showed the model a new
        message. Now such a pass REBASES instead (context.py step 0): earlier
        handoffs and everything after the head are re-decided, and one handoff
        stands for what was folded. So the invariants are:
          * no message is silently blanked (the original R5 regression);
          * every pass stays within the R2 budget;
          * the newest message is ALWAYS in the window;
          * the head is always first;
          * an extending pass keeps the previous output as its prefix.
        """
        from engine.embeddings import COMPRESSION_BUDGET, estimate_tokens
        self.eng.update_model("test-model", context_length=2250)  # budget = 1237
        # A10b units restatement: 3000 x 3 = 9000 = 2250 x 4.
        pad = "padding " * 30
        messages = [_msg("system", "sys"), _msg("user", "head 0"), _msg("user", "head 1")]
        prev_result = None
        modes = []
        for round_ in range(6):
            growth = [_msg("assistant", "ROUND%d-%d %s" % (round_, i, pad)) for i in range(8)]
            messages = (list(prev_result) if prev_result is not None else messages) + growth
            result = self.eng.compress(messages, focus_topic=None)
            modes.append(self.eng.last_pass)

            blanked = [i for i, m in enumerate(result) if not (m.get("content") or "").strip()]
            self.assertEqual(blanked, [],
                              "round %d: message(s) silently reduced to empty content instead of "
                              "durably folded -- positions %r" % (round_, blanked))
            used = sum(estimate_tokens(m.get("content") or "", margin=COMPRESSION_BUDGET)
                       for m in result)
            self.assertLessEqual(used, self.eng._target_budget(), "round %d over budget" % round_)
            self.assertEqual(result[-1]["content"], growth[-1]["content"],
                             "round %d: the newest message is not in the window" % round_)
            self.assertEqual([m["content"] for m in result[:3]], ["sys", "head 0", "head 1"])
            if prev_result is not None and self.eng.last_pass == "extend":
                self.assertEqual(result[:len(prev_result)], prev_result,
                                  "round %d: an extending pass rewrote the settled prefix" % round_)
            prev_result = result
        self.assertIn("extend", modes, "the fixture never exercised an extending pass: %r" % modes)

    # -- no system-role hoist --------------------------------------------------

    def test_system_message_not_hoisted_when_not_already_first(self):
        """A system-role span that occurs mid-conversation must stay where it
        is relative to its neighbors -- compress() must not pull every
        system-role message to the front of the window (the other named R5
        cause of prefix churn: 'system hoist')."""
        self.eng.update_model("test-model", context_length=75000)  # no budget pressure -- isolate ordering
        messages = (
            [_msg("user", "u0"), _msg("assistant", "a0")]
            + [_msg("system", "MID-SYSTEM-NOTE")]
            + [_msg("user", "u%d" % i) for i in range(1, 10)]
            + [_msg("assistant", "a%d" % i) for i in range(1, 10)]
        )
        result = self.eng.compress(list(messages), focus_topic=None)
        contents = [m.get("content") for m in result]
        self.assertIn("MID-SYSTEM-NOTE", contents)
        idx = contents.index("MID-SYSTEM-NOTE")
        self.assertGreater(idx, 0,
                            "a system-role span that was not first in the input must not be hoisted "
                            "to position 0 of the compressed output (R5)")
        # it should still be near where it started (right after u0/a0), not
        # merely "somewhere not first".
        self.assertIn("u0", contents[:idx])


if __name__ == "__main__":
    unittest.main()
