"""
Chronicle — E11 answer-support verification (§27 retrieval.support_threshold,
ladder-9 issue #8).

Provider API: verify_answer(answer_text, evidence_refs) -> {support, supported}
  support   = max cosine(answer embedding, evidence embeddings)
  supported = support >= retrieval.support_threshold (default 0.55)

Read-only, host-LLM-mode hallucination check. Covers the acceptance bar
verbatim: (a) an answer echoing evidence text scores high and
supported=True at the default threshold; (b) a fabricated answer over
unrelated evidence scores low and supported=False; (c) no embedder -> both
None; (d) evidence refs with no vectors -> both None; (e) read-only proof
(row counts + a content checksum identical before/after); (f) threshold
honored when overridden in config, INCLUDING the >= equality boundary.
Also covers real-world evidence_refs -- integration tests that feed
answer()'s ACTUAL `sources` field (not hand-built ref lists) into
verify_answer, on both the tier-1 (belief_id, plus an entity-id that must
be silently skipped) and tier-2 (event_id) paths. Runs entirely under the
offline hashing embedder (deterministic, no network) — the same mode the
recall/ctx_eval gate harnesses use. Fixtures use obviously fake values (Pat
Testley, Acme Fake Co) per the ladder-9 shared constraints.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import DegradedEmbedder
from engine.retrieval import RetrievalEngine
from provider import ChronicleMemoryProvider

FACT_TEXT = "Pat Testley works at Acme Fake Co"
UNRELATED_TEXT = "The vintage bicycle needed a new chain before the weekend ride"


def make_core(cfg_overrides=None):
    # Force the offline hashing embedder so tests are deterministic and never
    # probe localhost embedding servers (same convention as test_build.py /
    # test_query_routing.py).
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return ChronicleCore(home, cfg), home


def remember_fact(core, entity="pat_testley", attribute="works_at", content=FACT_TEXT,
                  principal="default"):
    """Write a fact through the real tool-dispatch path (same code path an
    agent's chronicle_remember call runs) and return its belief_id. A `fact`
    kind embeds synchronously at write time (reducer._insert_belief), so no
    process_pending() drain is needed for the vector to exist."""
    core.tools.dispatch(principal, "remember",
                        {"kind": "fact", "content": content, "entity": entity, "attribute": attribute})
    rows = core.store.query_beliefs("facts", "entity_id=? AND attribute=? AND status='active'",
                                    (entity, attribute), 5)
    assert rows, "fixture fact was not stored"
    return rows[0]["belief_id"]


def db_fingerprint(store):
    """Row counts + a content checksum across every table (§E11 acceptance
    (e), read-only proof). Deliberately reads through the SAME connection
    accessor (_conn()) the store itself uses everywhere -- no new surface,
    just an assertion helper."""
    conn = store._conn()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    counts = {}
    h = hashlib.sha256()
    for t in tables:
        try:
            rows = conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
        except Exception:
            # WITHOUT ROWID tables / FTS5 virtual tables have no rowid column;
            # sort the fetched tuples in Python instead so the checksum is
            # still order-independent and stable across two identical reads.
            rows = sorted(conn.execute(f"SELECT * FROM {t}").fetchall(), key=lambda r: repr(tuple(r)))
        counts[t] = len(rows)
        h.update(t.encode("utf-8"))
        for r in rows:
            h.update(repr(tuple(r)).encode("utf-8"))
    return counts, h.hexdigest()


# ---------------------------------------------------------------------------
# (a)/(b)/(d)/(f): core scoring behavior, real hashing embedder
# ---------------------------------------------------------------------------
class TestVerifyAnswerScoring(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.belief_id = remember_fact(self.core)

    def test_echoing_answer_scores_high_and_supported(self):
        result = self.core.retrieval.verify_answer(FACT_TEXT, [self.belief_id])
        self.assertIsNotNone(result["support"])
        self.assertGreater(result["support"], 0.9)  # identical text under the same embedder
        self.assertTrue(result["supported"])

    def test_fabricated_answer_over_unrelated_evidence_not_supported(self):
        result = self.core.retrieval.verify_answer(UNRELATED_TEXT, [self.belief_id])
        self.assertIsNotNone(result["support"])
        self.assertLess(result["support"], 0.55)  # default retrieval.support_threshold
        self.assertFalse(result["supported"])

    def test_evidence_refs_with_no_vectors_returns_null(self):
        result = self.core.retrieval.verify_answer(
            FACT_TEXT, ["b_does_not_exist", "evt_does_not_exist_either"])
        self.assertEqual(result, {"support": None, "supported": None})

    def test_empty_evidence_refs_returns_null(self):
        self.assertEqual(self.core.retrieval.verify_answer(FACT_TEXT, []),
                         {"support": None, "supported": None})
        self.assertEqual(self.core.retrieval.verify_answer(FACT_TEXT, None),
                         {"support": None, "supported": None})

    def test_refs_without_vectors_are_skipped_not_fatal(self):
        """A mix of a real ref and junk refs still resolves through the real one."""
        result = self.core.retrieval.verify_answer(
            FACT_TEXT, ["b_does_not_exist", self.belief_id, "evt_does_not_exist"])
        self.assertIsNotNone(result["support"])
        self.assertTrue(result["supported"])

    def test_threshold_honored_when_overridden(self):
        partial_answer = "Pat Testley is employed at Acme Fake Co"

        # Ground truth support via the REAL code path (core.retrieval.verify_answer),
        # not a hand-rolled embed()-vs-embed() comparison: the evidence side goes
        # through a pack()/unpack() float32 storage round-trip inside
        # _resolve_evidence_vectors, which shifts the low bits of the cosine value
        # relative to comparing two raw (float64) embed() outputs directly. Using
        # the real path is what makes the exact-equality boundary check below
        # meaningful instead of comparing against a slightly-off ground truth.
        baseline = self.core.retrieval.verify_answer(partial_answer, [self.belief_id])
        true_support = baseline["support"]
        self.assertIsNotNone(true_support)
        self.assertTrue(baseline["supported"])  # default threshold 0.55 well under true_support

        # Deterministic repro (hashing embedder, dimensions=768 as ChronicleCore's
        # default embeddings.dimensions actually configures it, float32 storage
        # round-trip): documented exactly so a future embedder/storage change that
        # silently shifts this value gets caught here, not just re-baselined blind.
        self.assertAlmostEqual(true_support, 0.8017837125872066, places=12)

        # Equality boundary (support_threshold's contract is ">=", not ">"):
        # support_threshold set to EXACTLY true_support must still be `supported`.
        # Mutating verify_answer's `support >= self._support_threshold()` to a
        # strict `>` makes this assertion fail.
        exact_core, exact_home = make_core({"retrieval": {"support_threshold": true_support}})
        self.addCleanup(shutil.rmtree, exact_home, ignore_errors=True)
        exact_bid = remember_fact(exact_core)
        exact = exact_core.retrieval.verify_answer(partial_answer, [exact_bid])
        self.assertEqual(exact["support"], true_support)
        self.assertTrue(exact["supported"], "support == support_threshold must count as supported (>=)")

        strict_core, strict_home = make_core(
            {"retrieval": {"support_threshold": min(1.0, true_support + 0.01)}})
        self.addCleanup(shutil.rmtree, strict_home, ignore_errors=True)
        strict_bid = remember_fact(strict_core)
        strict = strict_core.retrieval.verify_answer(partial_answer, [strict_bid])
        self.assertAlmostEqual(strict["support"], true_support, places=12)
        self.assertFalse(strict["supported"])  # raised threshold now exceeds true_support

        lenient_core, lenient_home = make_core(
            {"retrieval": {"support_threshold": max(0.0, true_support - 0.01)}})
        self.addCleanup(shutil.rmtree, lenient_home, ignore_errors=True)
        lenient_bid = remember_fact(lenient_core)
        lenient = lenient_core.retrieval.verify_answer(partial_answer, [lenient_bid])
        self.assertTrue(lenient["supported"])  # lowered threshold now under true_support


# ---------------------------------------------------------------------------
# (c): no embedder -> both None, never an error
# ---------------------------------------------------------------------------
class TestVerifyAnswerNoEmbedder(unittest.TestCase):
    def test_none_embedder_returns_null(self):
        eng = RetrievalEngine(None, None, embedder=None)
        result = eng.verify_answer(FACT_TEXT, ["some_ref"])
        self.assertEqual(result, {"support": None, "supported": None})

    def test_none_embedder_with_no_refs_still_returns_null(self):
        eng = RetrievalEngine(None, None, embedder=None)
        self.assertEqual(eng.verify_answer(FACT_TEXT, []), {"support": None, "supported": None})

    def test_degraded_embedder_returns_null(self):
        """A present-but-unreachable backend (DegradedEmbedder, embed() raises
        EmbeddingsUnavailable) must degrade exactly like a missing one --
        never bubble the exception to the host."""
        degraded = DegradedEmbedder(model="auto", base_url="http://127.0.0.1:1")  # nothing listens
        eng = RetrievalEngine(None, None, embedder=degraded)
        result = eng.verify_answer(FACT_TEXT, ["some_ref"])
        self.assertEqual(result, {"support": None, "supported": None})


# ---------------------------------------------------------------------------
# (e): read-only proof
# ---------------------------------------------------------------------------
class TestVerifyAnswerReadOnly(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.belief_id = remember_fact(self.core)

    def test_row_counts_and_checksum_unchanged_by_a_supported_call(self):
        before = db_fingerprint(self.core.store)
        result = self.core.retrieval.verify_answer(FACT_TEXT, [self.belief_id])
        self.assertTrue(result["supported"])  # sanity: the call actually did work
        after = db_fingerprint(self.core.store)
        self.assertEqual(before, after)

    def test_row_counts_and_checksum_unchanged_by_an_unsupported_call(self):
        before = db_fingerprint(self.core.store)
        result = self.core.retrieval.verify_answer(UNRELATED_TEXT, [self.belief_id])
        self.assertFalse(result["supported"])
        after = db_fingerprint(self.core.store)
        self.assertEqual(before, after)

    def test_row_counts_and_checksum_unchanged_by_the_null_path(self):
        before = db_fingerprint(self.core.store)
        result = self.core.retrieval.verify_answer(FACT_TEXT, ["b_does_not_exist"])
        self.assertIsNone(result["support"])
        after = db_fingerprint(self.core.store)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Integration: feed answer()'s REAL `sources` field into verify_answer,
# instead of a hand-built evidence_refs list. Covers both id namespaces
# `sources` actually returns (belief_id on tier 1, event_id on tier 2), and
# the tier-1 case where `sources` also contains a bare entity_id (an
# `entities` row's belief_id IS its entity_id, e.g. "pat_testley" -- §R12,
# entities carry no vector of their own) that must be silently skipped
# rather than break resolution of the real refs alongside it.
# ---------------------------------------------------------------------------
class TestVerifyAnswerRealSourcesTier1(unittest.TestCase):
    """answer() answering from the belief layer (tier 1): sources is a mix of
    a fact belief_id ('b_...') and the entity's own belief_id, which for the
    `entities` table is the raw entity_id itself ('pat_testley') -- confirmed
    empirically: core.retrieval.answer('where does Pat Testley work')
    returns sources == ['b_<hash>', 'pat_testley']."""

    def setUp(self):
        self.core, self.home = make_core()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        remember_fact(self.core)
        self.ans = self.core.retrieval.answer("where does Pat Testley work")

    def test_answer_is_tier_1_with_mixed_sources(self):
        self.assertFalse(self.ans["abstain"])
        self.assertEqual(self.ans["tier"], 1)
        self.assertIn("pat_testley", self.ans["sources"])  # the entity_id, unresolvable to a vector
        self.assertTrue(any(s.startswith("b_") for s in self.ans["sources"]))  # the fact belief_id

    def test_entity_id_alone_resolves_to_nothing_and_is_skipped(self):
        # "pat_testley" looks like a plausible ref (it IS a real belief_id, of
        # the `entities` table) but names no memory_vectors/observed_vectors
        # row -- the skip rule, not an error, and -- alone -- the null path.
        result = self.core.retrieval.verify_answer(FACT_TEXT, ["pat_testley"])
        self.assertEqual(result, {"support": None, "supported": None})

    def test_echoing_answer_supported_via_real_sources(self):
        result = self.core.retrieval.verify_answer(FACT_TEXT, self.ans["sources"])
        self.assertIsNotNone(result["support"])
        self.assertGreater(result["support"], 0.9)
        self.assertTrue(result["supported"])

    def test_fabricated_answer_not_supported_via_real_sources(self):
        result = self.core.retrieval.verify_answer(UNRELATED_TEXT, self.ans["sources"])
        self.assertIsNotNone(result["support"])
        self.assertFalse(result["supported"])


class TestVerifyAnswerRealSourcesTier2(unittest.TestCase):
    """answer() falling back to the raw tier (tier 2, no belief written yet):
    sources is a plain event_id ('ev_...'), resolved through
    get_observed_vectors_by_ids -- confirmed empirically: observing a raw
    turn and asking about it (before curation ever promotes it to a belief)
    returns tier == 2 and sources == ['ev_<hash>']."""

    TURN_TEXT = ("Pat Testley mentioned that Acme Fake Co just opened a new "
                "office in Reykjavik")

    def setUp(self):
        self.core, self.home = make_core()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.core.capture.observe(self.TURN_TEXT, "Got it, noted.", session_id="s1")
        # Deliberately NOT calling process_pending(): draining the "extract"
        # curation job would promote this into an episode belief and answer
        # from tier 1 instead -- the raw event's vector is already written
        # synchronously by _on_observed, which is all tier 2 needs.
        self.ans = self.core.retrieval.answer("where did Acme Fake Co open a new office")

    def test_answer_is_tier_2_with_event_id_source(self):
        self.assertFalse(self.ans["abstain"])
        self.assertEqual(self.ans["tier"], 2)
        self.assertEqual(len(self.ans["sources"]), 1)
        self.assertTrue(self.ans["sources"][0].startswith("ev_"))

    def test_echoing_answer_supported_via_real_event_source(self):
        result = self.core.retrieval.verify_answer(self.TURN_TEXT, self.ans["sources"])
        self.assertIsNotNone(result["support"])
        self.assertGreater(result["support"], 0.55)
        self.assertTrue(result["supported"])


# ---------------------------------------------------------------------------
# Provider layer: verify_answer surfaced on ChronicleMemoryProvider exactly
# like the other thin delegating provider APIs (prefetch, system_prompt_block).
# ---------------------------------------------------------------------------
class TestVerifyAnswerProviderLayer(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.provider = ChronicleMemoryProvider()
        self.provider.initialize("s1", hermes_home=self.home, principal_id="default",
                                 config={"embeddings": {"model": "hashing"}})

    def test_delegates_to_retrieval_engine(self):
        belief_id = remember_fact(self.provider.core)
        result = self.provider.verify_answer(FACT_TEXT, [belief_id])
        self.assertTrue(result["supported"])
        self.assertGreater(result["support"], 0.9)

    def test_uninitialized_provider_returns_null_not_an_error(self):
        blank = ChronicleMemoryProvider()
        self.assertEqual(blank.verify_answer("anything", ["ref"]),
                         {"support": None, "supported": None})

    def test_default_evidence_refs_argument(self):
        # evidence_refs omitted entirely -> treated as empty, not a TypeError.
        result = self.provider.verify_answer(FACT_TEXT)
        self.assertEqual(result, {"support": None, "supported": None})


if __name__ == "__main__":
    unittest.main()
