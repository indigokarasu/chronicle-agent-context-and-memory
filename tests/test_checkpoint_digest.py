"""
Chronicle — tests for the deterministic no-LLM checkpoint digest (Ladder 7, R7).

compress() folds every span it evicts into a rolling digest built purely from
extraction artifacts (facts/entities/directives/episodes) -- no model call,
ever, regardless of extraction.backend. The digest is refreshed on every
compression pass that evicts something, capped so it can never grow without
bound across a long session, and durably recorded as its own `checkpoint_digest`
audit event.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import estimate_tokens
from engine import extraction as extraction_mod
from context import ChronicleContextEngine

CFG = {"embeddings": {"model": "hashing"}}  # offline, deterministic

# Big enough that head(3) + tail(6) of this alone consumes the ENTIRE default
# context.default_token_budget (1500) once _fit_within_budget clips it -- the
# same technique test_output_fits_token_budget (R0/R2) uses to force a single
# scored middle span to be evicted deterministically, with the compress()
# budget left at exactly 0 remaining afterward (no reinjection to worry about).
def _msg(role, text):
    return {"role": role, "content": text}


def _pad50(s):
    """Pad/truncate `s` to exactly 50 chars: uniform span size (so recency
    ordering alone decides eviction, no tiny-span-slips-into-leftover) AND
    under the HeuristicExtractor's 60-char episode threshold (so a filler
    contributes NOTHING to the digest and the evicted fact is the only thing
    that lands in it)."""
    return (s + " " + "z" * 60)[:50]


def _filler(i):
    return _pad50("filler padding row %03d" % i)  # no fact/entity/directive pattern


def _body_with_middle(fact_text):
    """small head(3) + the fact span as the OLDEST middle span + a run of
    same-size, extract-nothing fillers newer than it + small tail(6).

    Every middle span is exactly 50 chars, so recency-weighted scoring (§R3)
    orders them purely by age and the OLDEST (the fact) is deterministically
    evicted once the run's combined size exceeds the default 1500-token budget
    -- no dependence on budget-boundary arithmetic, and no tiny span slipping
    into leftover. Fillers are under the 60-char episode threshold and match no
    fact/entity/directive pattern, so the ONLY thing that lands in the
    checkpoint digest is the evicted fact. (The prior fixture leaned on
    oversized head/tail clipped-but-kept; under §R5 an over-budget protected
    span is durably folded instead, which polluted the digest, so the eviction
    target moved into a uniform filler run.)
    """
    return (
        [_msg("user", "head %d" % i) for i in range(3)]
        + [_msg("user", _pad50(fact_text))]
        + [_msg("assistant" if i % 2 else "user", _filler(i)) for i in range(120)]
        + [_msg("assistant", "tail %d" % i) for i in range(6)]
    )


class CheckpointDigestTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="r7_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("r7-s1", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertIsNotNone(self.eng.core, "test setup expected the real (non-heuristic) engine")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    # -- basic behavior -----------------------------------------------------

    def test_empty_before_any_eviction(self):
        self.assertEqual(self.eng.get_checkpoint_digest(), "")

    def test_digest_populated_from_evicted_content(self):
        body = _body_with_middle("I work at Acme Fake Co.")
        out = self.eng.compress(list(body))
        self.assertNotIn(_pad50("I work at Acme Fake Co."), [m.get("content") for m in out],
                          "setup invariant: the fact-bearing middle span must be evicted")
        digest = self.eng.get_checkpoint_digest()
        self.assertIn("works_at", digest)
        self.assertIn("Acme Fake Co", digest)

    def test_digest_not_touched_when_nothing_evicted(self):
        # 8 messages: below protect_first_n(3) + protect_last_n(6) = 9, so
        # compress() returns everything untouched -- no eviction at all.
        body = [_msg("user", "hi %d" % i) for i in range(8)]
        self.eng.compress(list(body))
        self.assertEqual(self.eng.get_checkpoint_digest(), "")

    # -- determinism (no randomness, no clock, no network) -------------------

    def test_digest_is_deterministic_across_independent_engines(self):
        body = _body_with_middle("My phone is 555-0100.")
        home2 = tempfile.mkdtemp(prefix="r7_det_")
        eng2 = ChronicleContextEngine()
        eng2.on_session_start("r7-s2", hermes_home=home2, principal_id="pat", config=CFG)
        try:
            self.eng.compress(list(body))
            eng2.compress(list(body))
            self.assertEqual(self.eng.get_checkpoint_digest(), eng2.get_checkpoint_digest())
        finally:
            ChronicleCore._instances.pop(home2, None)
            shutil.rmtree(home2, ignore_errors=True)

    def test_digest_unchanged_by_a_repeated_identical_compress_call(self):
        body = _body_with_middle("I live in Springfield.")
        self.eng.compress(list(body))
        first = self.eng.get_checkpoint_digest()
        n_events_before = len(self.core.store.get_events_by_type("checkpoint_digest"))
        self.eng.compress(list(body))  # identical input again
        self.assertEqual(self.eng.get_checkpoint_digest(), first,
                          "identical input must not change the digest (replay determinism)")
        n_events_after = len(self.core.store.get_events_by_type("checkpoint_digest"))
        self.assertEqual(n_events_after, n_events_before,
                          "no NEW checkpoint_digest event should be written when nothing changed")

    # -- no model call, ever -------------------------------------------------

    def test_digest_never_calls_the_llm_extractor(self):
        """Even with extraction.backend configured to 'llm', the checkpoint
        digest must use the deterministic HeuristicExtractor -- compress() is
        on the hot request path and must never depend on a model/network call
        being reachable."""
        called = []
        original_chat = extraction_mod.LLMExtractor._chat

        def spy(self, prompt):
            called.append(prompt)
            return original_chat(self, prompt)

        extraction_mod.LLMExtractor._chat = spy
        home = tempfile.mkdtemp(prefix="r7_nollm_")
        try:
            llm_cfg = {
                "embeddings": {"model": "hashing"},
                "extraction": {"backend": "llm",
                               "llm": {"base_url": "http://127.0.0.1:1/unreachable",
                                       "model": "does-not-exist"}},
            }
            eng = ChronicleContextEngine()
            eng.on_session_start("r7-nollm", hermes_home=home, principal_id="pat", config=llm_cfg)
            self.assertIsNotNone(eng.core)
            body = _body_with_middle("I work in Metropolis.")
            eng.compress(list(body))
            self.assertIn("works_in", eng.get_checkpoint_digest(),
                          "the digest should still be populated deterministically")
            self.assertEqual(called, [],
                              "checkpoint digest must never invoke LLMExtractor._chat")
        finally:
            extraction_mod.LLMExtractor._chat = original_chat
            ChronicleCore._instances.pop(home, None)
            shutil.rmtree(home, ignore_errors=True)

    # -- capped size -----------------------------------------------------------

    def test_digest_stays_within_configured_cap_across_many_passes(self):
        cap = 20
        home = tempfile.mkdtemp(prefix="r7_cap_")
        try:
            small_cfg = {"embeddings": {"model": "hashing"},
                        "context_engine": {"checkpoint_digest_max_tokens": cap}}
            eng = ChronicleContextEngine()
            eng.on_session_start("r7-cap", hermes_home=home, principal_id="pat", config=small_cfg)
            self.assertIsNotNone(eng.core)
            facts = ["I work at Acme Fake Co.", "I live in Springfield.",
                     "My phone is 555-0100.", "I work in Metropolis.",
                     "My email is pat@example.com."]
            for fact in facts:
                eng.compress(list(_body_with_middle(fact)))
                digest = eng.get_checkpoint_digest()
                self.assertLessEqual(estimate_tokens(digest), cap,
                                      "checkpoint digest exceeded its configured cap after "
                                      "folding %r in: %r" % (fact, digest))
            # the cap actually did something -- later facts pushed earlier ones out
            self.assertNotIn("Acme Fake Co", eng.get_checkpoint_digest(),
                              "the oldest fact should have rolled off under a tight cap")
        finally:
            ChronicleCore._instances.pop(home, None)
            shutil.rmtree(home, ignore_errors=True)

    def test_digest_rolls_forward_keeping_recent_content(self):
        home = tempfile.mkdtemp(prefix="r7_roll_")
        try:
            small_cfg = {"embeddings": {"model": "hashing"},
                        "context_engine": {"checkpoint_digest_max_tokens": 20}}
            eng = ChronicleContextEngine()
            eng.on_session_start("r7-roll", hermes_home=home, principal_id="pat", config=small_cfg)
            eng.compress(list(_body_with_middle("I work at Acme Fake Co.")))
            eng.compress(list(_body_with_middle("My email is pat@example.com.")))
            self.assertIn("email", eng.get_checkpoint_digest(),
                          "the most recently folded content should be present")
        finally:
            ChronicleCore._instances.pop(home, None)
            shutil.rmtree(home, ignore_errors=True)

    # -- durable audit trail ---------------------------------------------------

    def test_digest_refresh_is_durably_recorded(self):
        body = _body_with_middle("I work at Acme Fake Co.")
        self.eng.compress(list(body))
        events = self.core.store.get_events_by_type("checkpoint_digest")
        matches = [e for e in events if e.get("session_id") == "r7-s1"]
        self.assertGreaterEqual(len(matches), 1,
                                 "a refreshed digest should be recorded as its own audit event")
        import json
        payload = json.loads(matches[-1]["payload"])
        self.assertEqual(payload.get("digest"), self.eng.get_checkpoint_digest())

    # -- injected back into the window when there is room ----------------------

    def test_digest_injected_into_window_when_budget_allows(self):
        self.eng.update_model("test-model", context_length=100000)  # -> budget = 55000
        budget = self.eng._target_budget()
        item_chars = 900                              # -> estimate_tokens == 300 per item
        item_cost = estimate_tokens("z" * item_chars)
        n_items = 200                                  # total middle cost (60000) > budget
        target_index = 0                               # oldest -> recency-evicted first (§R3)

        def item(i):
            if i == target_index:
                prefix = "I work at Acme Fake Co. "
                return (prefix + "z" * item_chars)[:item_chars]
            return "z" * item_chars

        body = (
            [_msg("user", "head%d" % i) for i in range(3)]
            + [_msg("user", item(i)) for i in range(n_items)]
            + [_msg("assistant", "tail%d" % i) for i in range(6)]
        )
        out = self.eng.compress(list(body))
        self.assertLess(len(out), len(body), "fixture should force real eviction")
        digest = self.eng.get_checkpoint_digest()
        self.assertIn("works_at", digest)

        checkpoint_spans = [m for m in out if m.get("role") == "system"
                            and (m.get("content") or "").startswith("[Checkpoint:")]
        self.assertTrue(checkpoint_spans,
                         "expected a [Checkpoint: ...] system span injected into the window "
                         "given ~%d tokens of slack under the %d budget" % (item_cost, budget))

        total = sum(estimate_tokens(m.get("content")) for m in out)
        self.assertLessEqual(total, budget,
                              "checkpoint injection must never break the compress() "
                              "output<=budget guarantee (R2)")


if __name__ == "__main__":
    unittest.main()
