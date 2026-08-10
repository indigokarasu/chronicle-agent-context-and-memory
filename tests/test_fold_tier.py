"""
Chronicle — tests for context.py's FOLD tier: reversible eviction via
tombstone stubs + chronicle_expand (Ladder 7, R4).

Scope, tight to what R4 itself changes on top of R2's watermark eviction and
R11's chunked durability:

  1. A span compress() evicts leaves a one-line tombstone stub AT ITS OLD
     POSITION in the window (id + digest), instead of vanishing outright.
  2. chronicle_expand(span_id) rehydrates that span back to its original
     content byte-for-byte, whether it fit in a single durable event or had
     to be chunked (R11) across several.
  3. The stub -- and therefore compress()'s whole output -- stays fully
     deterministic across repeated calls on identical input (span_id/digest
     are a content hash, not derived from any event id or timestamp).
  4. Tombstones are themselves budget-accounted: compress() never exceeds
     its token budget just because it started adding stubs back in.
  5. An unknown span_id fails closed, not with a stack trace.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import estimate_tokens
from engine.serialize import hash_str
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


def _lorem(n_chars):
    """Realistic prose (not a repeated char), long enough to force chunking
    past the default excerpt cap (_CAP_DEFAULT=4000)."""
    sentence = ("The quarterly review with Pat Testley at Acme Fake Co covered "
                "onboarding, billing, and the migration timeline. ")
    out, total = [], 0
    while total < n_chars:
        out.append(sentence)
        total += len(sentence)
    return "".join(out)[:n_chars]


class FoldTierTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="r4_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("r4-s1", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertIsNotNone(self.eng.core, "test setup expected the real (non-heuristic) engine")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    @staticmethod
    def _output_tokens(out):
        return sum(estimate_tokens(m.get("content")) for m in out)

    @staticmethod
    def _fold_stub(out):
        """The (at most one, in this fixture) tombstone stub in `out`, or None."""
        stubs = [m for m in out if (m.get("content") or "").startswith("[FOLD ")]
        return stubs[0] if stubs else None

    @staticmethod
    def _span_id_from_stub(stub):
        # "[FOLD fold_xxxxxxxxxxxx yyyyyyyy]" -> "fold_xxxxxxxxxxxx"
        return stub["content"].split(" ")[1]

    # -- 1. eviction leaves an in-window tombstone, not a silent drop -----
    def test_evicted_span_leaves_a_tombstone_stub_in_window(self):
        # A few large middle spans against a budget that keeps most of them
        # but not all: recency-weighted scoring (§R3) keeps the newest, the
        # oldest lose the budget race, and the room left over is comfortably
        # larger than a one-line tombstone -- so at least one evicted span
        # reliably leaves a [FOLD ...] stub. (The prior uniform-40-span
        # fixture depended on exact budget-boundary arithmetic that R3's
        # recency reorder perturbs; large distinct spans make the assertion
        # structural rather than luck-of-the-packing.)
        self.eng.update_model("test-model", context_length=1000)  # budget = 550
        # 20 uniform ~50-token middle spans: recency-weighted scoring keeps the
        # ~10 newest that fit, evicting ~10. The leftover budget fits a couple
        # of one-line tombstones but not all ten, so the output both SHRINKS
        # (most evicted spans have no in-window stub) and still carries at least
        # one [FOLD ...] tombstone. Uniform span sizes make this structural, not
        # dependent on budget-boundary arithmetic that R3's recency reorder
        # would otherwise perturb.
        mid = lambda i: "mid " + ("x" * 140) + (" %03d" % i)  # constant length -> ~50 tokens
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + [_msg("assistant" if i % 2 else "user", mid(i)) for i in range(20)]
            + [_msg("assistant", "tail %d" % i) for i in range(6)]
        )
        out = self.eng.compress(list(messages), focus_topic=None)
        self.assertLess(len(out), len(messages), "fixture should force real eviction")
        stub = self._fold_stub(out)
        self.assertIsNotNone(stub, "an evicted span should leave a [FOLD ...] tombstone in-window")
        # "[FOLD <span_id> <digest-prefix>]" -- both an id and a digest, one line.
        parts = stub["content"].strip("[]").split(" ")
        self.assertEqual(len(parts), 3)
        self.assertTrue(parts[1].startswith("fold_"))

    # -- 2. chronicle_expand rehydrates byte-exact -------------------------
    def test_chronicle_expand_rehydrates_small_span_byte_exact(self):
        self.eng.update_model("test-model", context_length=1000)  # budget = 550
        # 10 small same-score fillers comfortably fit budget with room left
        # over (~80 tokens); target (~240 tokens) is the one thing too big to
        # also fit, so it -- and only it -- is evicted, and the room left
        # over after the fillers is enough for its own tombstone.
        target = "UNIQUE-FOLD-TARGET " + ("z" * 700)
        # Target is the OLDEST middle span (before the fillers): recency-weighted
        # scoring (§R3) keeps the newer fillers and evicts the oldest, so the
        # single large target -- and only it -- loses the budget race. (Pre-R3
        # the target could sit last and rely on flat scoring; recency now
        # prefers the newest, so an evicted target must be positioned as old.)
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + [_msg("user", target)]
            + [_msg("assistant" if i % 2 else "user", _LONG_BODY % i) for i in range(10)]
            + [_msg("assistant", "tail %d" % i) for i in range(6)]
        )
        out = self.eng.compress(list(messages), focus_topic=None)
        self.assertNotIn(target, [m.get("content") for m in out], "target should be evicted")
        expected_span_id = "fold_" + hash_str(target)[:12]
        stubs = [m for m in out if (m.get("content") or "").startswith("[FOLD %s " % expected_span_id)]
        self.assertEqual(len(stubs), 1, "expected exactly one tombstone for the target span")
        span_id = self._span_id_from_stub(stubs[0])
        self.assertEqual(span_id, expected_span_id)
        result = json.loads(self.eng.handle_tool_call("chronicle_expand", {"span_id": span_id}))
        self.assertEqual(result.get("content"), target)
        self.assertTrue(result.get("verified"), "rehydrated content should verify against its digest")
        self.assertEqual(result.get("role"), "user")

    def test_chronicle_expand_rehydrates_chunked_span_byte_exact(self):
        """A span past the excerpt cap is chunked (R11) across multiple durable
        events; chronicle_expand must still reassemble it byte-for-byte."""
        self.eng.update_model("test-model", context_length=100000)  # plenty of budget headroom
        target = "UNIQUE-LARGE-" + _lorem(9000)
        self.assertGreater(len(target), 4000)
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + [_msg("assistant", target)]
            + [_msg("assistant" if i % 2 else "user", "always keep this pinned filler %d" % i)
               for i in range(2)]  # "always" -> never_evict, keeps middle non-trivial
            + [_msg("assistant", "tail %d" % i) for i in range(6)]
        )
        # Force eviction of the (otherwise low-score) large span directly, the
        # same way compress() would once its score loses the budget race --
        # exercised end-to-end via a tight budget instead:
        self.eng.update_model("test-model", context_length=200)  # budget = 110: too tight to keep it
        out = self.eng.compress(list(messages), focus_topic=None)
        stub = self._fold_stub(out)
        self.assertIsNotNone(stub, "the oversized span should be evicted and folded under a tight budget")
        span_id = self._span_id_from_stub(stub)
        result = json.loads(self.eng.handle_tool_call("chronicle_expand", {"span_id": span_id}))
        self.assertEqual(result.get("content"), target)
        self.assertTrue(result.get("verified"))

    # -- 3. determinism: identical input -> identical stub -----------------
    def test_fold_stub_is_deterministic_across_repeated_compress_calls(self):
        self.eng.update_model("test-model", context_length=2000)
        messages = _messages(40)
        out1 = self.eng.compress([dict(m) for m in messages], focus_topic=None)
        out2 = self.eng.compress([dict(m) for m in messages], focus_topic=None)
        self.assertEqual(out1, out2,
                          "compress() must partition + stub identically for identical input")

    # -- 4. tombstones are budget-accounted, not free ----------------------
    def test_output_with_tombstones_still_fits_budget(self):
        self.eng.update_model("test-model", context_length=2000)
        messages = _messages(40)
        out = self.eng.compress(list(messages), focus_topic=None)
        budget = self.eng._target_budget()
        total = self._output_tokens(out)
        self.assertLessEqual(total, budget,
                              "compress() exceeded its budget once tombstone stubs were added back in")

    def test_no_room_for_tombstone_still_durable_just_not_in_window(self):
        """When the protected set alone exhausts the budget, a stub may not fit
        -- the span must still be durably recoverable (I17) even without an
        in-window tombstone."""
        self.eng.update_model("test-model", context_length=1000)  # budget = 550
        huge = "Acme Fake Co tool output: " + ("x" * 6000)
        messages = (
            [_msg("system", "sys")]
            + [_msg("user", "head %d" % i) for i in range(3)]
            + [_msg("user", "middle filler %d %s" % (i, "pad " * 20)) for i in range(10)]
            + [_msg("assistant", "tail %d" % i) for i in range(5)]
            + [_msg("assistant", huge)]
        )
        before = len(self.core.store.get_events_by_type("observed"))
        out = self.eng.compress(list(messages), focus_topic=None)
        after = len(self.core.store.get_events_by_type("observed"))
        budget = self.eng._target_budget()
        self.assertLessEqual(self._output_tokens(out), budget)
        self.assertGreater(after, before, "evicted middle spans must still be made durable (I17)")

    # -- 5. unknown span_id fails closed ------------------------------------
    def test_chronicle_expand_unknown_span_id_returns_error(self):
        result = json.loads(self.eng.handle_tool_call("chronicle_expand", {"span_id": "fold_doesnotexist"}))
        self.assertIn("error", result)

    def test_chronicle_expand_missing_span_id_returns_error(self):
        result = json.loads(self.eng.handle_tool_call("chronicle_expand", {}))
        self.assertIn("error", result)

    # -- 6. the compressed audit event carries real span ids (R6-adjacent) -
    def test_compressed_audit_event_carries_evicted_span_ids(self):
        self.eng.update_model("test-model", context_length=2000)
        messages = _messages(40)
        self.eng.compress(list(messages), focus_topic=None)
        events = self.core.store.get_events_by_type("compressed")
        self.assertTrue(events)
        payload = json.loads(events[-1]["payload"])
        evicted = payload.get("evicted_spans")
        self.assertIsInstance(evicted, list)
        self.assertGreater(len(evicted), 0)
        self.assertTrue(all(isinstance(s, str) and s.startswith("fold_") for s in evicted))


if __name__ == "__main__":
    unittest.main()
