"""
Chronicle — embedding reranker (E3): kill the identity passthrough.

After FTS+vector+graph fusion, RetrievalEngine._rerank re-scores the top
`retrieval.rerank_top_k` candidates by cosine(query embedding, candidate
embedding) blended with their MIN-MAX NORMALIZED fusion score
(`retrieval.rerank_blend`), and re-orders before packing.

The normalization is the whole ballgame. Raw fusion scores are RRF
(Σ w/(rrf_k + rank), ≈ 0.002–0.025) and cosine is in [0, 1]; blending them
un-normalized is not a blend, it is a pure cosine re-sort that also sinks every
vectorless candidate by construction. TestRerankScaleCommensurability pins that
down as a regression: it is the defect that cost 8 points of belief turn-recall
on LongMemEval-s.

Two layers of coverage:
  * unit tests of `_rerank` against hand-built vectors — deterministic, and the
    only way to state the scale invariants exactly;
  * end-to-end tests through the REAL `search()` entry point over a real
    MemoryStore, so the spec's acceptance scenario is proven against real FTS
    ranking and real RRF fusion rather than a hand-fed candidate list, and the
    no-embedder degrade is proven where callers actually enter.

Fixture names are the project's standard fakes (Pat Testley, Acme Fake Co).
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import Config
from engine.embeddings import pack
from engine.retrieval import RetrievalEngine
from engine.store import MemoryStore


class _FakeVectorStore:
    """Stands in for MemoryStore for _rerank's one dependency: batch lookup of
    stored belief embeddings by id. `vectors` maps belief_id -> an unpacked
    list[float]; a belief_id absent from the map has no stored vector at all
    (the "no vector" degrade path)."""

    def __init__(self, vectors):
        self._vectors = vectors
        self.lookups = 0

    def get_memory_vectors_by_ids(self, belief_ids):
        self.lookups += 1
        out = {}
        for bid in dict.fromkeys(belief_ids):
            if bid in self._vectors:
                out[bid] = {"embedding": pack(self._vectors[bid])}
        return out


class _NoIndex:
    """A disabled ANN index — keeps RetrievalEngine.__init__ from building a
    real VectorIndex against a bare store."""

    def is_enabled(self):
        return False


def _engine(vectors=None, overrides=None, store=None):
    cfg = Config(overrides or {})
    return RetrievalEngine(store if store is not None else _FakeVectorStore(vectors or {}),
                           cfg, embedder=None, vector_index=_NoIndex())


def _cand(belief_id, score):
    """A minimal search()-shaped candidate: only belief_id and score are
    read/written by _rerank, but the extra keys mirror the real shape."""
    return {"belief_id": belief_id, "table": "notes", "kind": "note",
            "score": score, "channels": ["fts"], "value": belief_id}


def _ids(candidates):
    return [c["belief_id"] for c in candidates]


# --------------------------------------------------------------------------
# The defect this task exists to fix: two incompatible score scales
# --------------------------------------------------------------------------
class TestRerankScaleCommensurability(unittest.TestCase):
    """Fusion scores and cosine must be made commensurate before they are
    blended, or the "blend" is a pure cosine re-sort and every vectorless
    candidate falls off the bottom."""

    def test_vectorless_leader_is_not_displaced_by_a_perfect_cosine_match(self):
        # THE regression. "note:leader" has no stored vector and leads on
        # fusion; every rival has a vector parallel to the query (cosine 1.0).
        # Un-normalized, the rivals score ~0.5 against the leader's ~0.02 and
        # it is sunk to last. Normalized, the leader's f = 1.0 and no rival can
        # reach it: max rival = blend*1 + (1-blend)*f_rival < 1.
        eng = _engine(vectors={"note:rival1": [1.0, 0.0], "note:rival2": [1.0, 0.0]})
        out = eng._rerank([_cand("note:leader", 0.020), _cand("note:rival1", 0.018),
                           _cand("note:rival2", 0.016)], [1.0, 0.0])
        self.assertEqual(_ids(out)[0], "note:leader")
        # ...and its score is still the top of the original envelope.
        self.assertAlmostEqual(out[0]["score"], 0.020, places=9)

    def test_no_candidate_is_sunk_below_the_original_fusion_envelope(self):
        # Every re-scored candidate stays inside [min fusion, max fusion]: the
        # reranker re-orders, it does not move the score scale downstream gates
        # (_confident, _support_gate "score" mode) are calibrated against.
        eng = _engine(vectors={"a": [1.0, 0.0], "b": [0.0, 1.0], "c": [-1.0, 0.0]})
        out = eng._rerank([_cand("a", 0.020), _cand("b", 0.017), _cand("c", 0.011)],
                          [1.0, 0.0])
        for c in out:
            self.assertGreaterEqual(c["score"], 0.011)
            self.assertLessEqual(c["score"], 0.020)
        self.assertAlmostEqual(max(c["score"] for c in out), 0.020, places=9)
        self.assertAlmostEqual(min(c["score"] for c in out), 0.011, places=9)

    def test_a_decisive_fusion_lead_survives_a_cosine_disagreement(self):
        # min-max normalization (not rank normalization) is chosen precisely so
        # RRF magnitude still means something: "a" is far ahead on fusion and a
        # merely-better cosine on "b" must not overturn it.
        eng = _engine(vectors={"a": [0.8, 0.6], "b": [1.0, 0.0]})
        out = eng._rerank([_cand("a", 0.0250), _cand("b", 0.0072),
                           _cand("c", 0.0070)], [1.0, 0.0])
        self.assertEqual(_ids(out)[0], "a")

    def test_a_near_tie_on_fusion_is_broken_by_cosine(self):
        # ...and the flip side: where RRF has effectively no opinion (the
        # common case — adjacent ranks differ by ~1e-5), cosine decides.
        eng = _engine(vectors={"a": [0.0, 1.0], "b": [1.0, 0.0]})
        out = eng._rerank([_cand("a", 0.016300), _cand("b", 0.016299),
                           _cand("c", 0.016100)], [1.0, 0.0])
        self.assertEqual(_ids(out)[0], "b")


# --------------------------------------------------------------------------
# The spec's acceptance scenario, at the unit level
# --------------------------------------------------------------------------
class TestRerankFlipsOrder(unittest.TestCase):
    def test_low_cosine_high_fusion_loses_to_high_cosine_low_fusion(self):
        # "Pat Testley" keyword-spam note: best fusion score, but its embedding
        # is nearly orthogonal to the query — irrelevant content. The
        # "employed by Acme Fake Co" note is the truly relevant one: weaker
        # fusion, embedding parallel to the query.
        eng = _engine(vectors={
            "note:keyword_spam": [0.1, 0.99498743],
            "note:true_answer": [0.9, 0.43588989],
            "note:filler": [0.0, 1.0],
        })
        out = eng._rerank([_cand("note:keyword_spam", 0.020),
                           _cand("note:true_answer", 0.018),
                           _cand("note:filler", 0.016)], [1.0, 0.0])
        self.assertEqual(_ids(out), ["note:true_answer", "note:keyword_spam", "note:filler"])

    def test_blend_weight_is_configurable(self):
        # blend=0.9 hands the ordering almost entirely to cosine, so even a
        # decisive fusion lead is overturned.
        eng = _engine(vectors={"a": [0.0, 1.0], "b": [1.0, 0.0], "c": [0.0, 1.0]},
                      overrides={"retrieval": {"rerank_blend": 0.9}})
        out = eng._rerank([_cand("a", 0.0250), _cand("b", 0.0072), _cand("c", 0.0070)],
                          [1.0, 0.0])
        self.assertEqual(_ids(out)[0], "b")

    def test_blend_zero_is_an_exact_identity(self):
        # blend=0 → sim drops out entirely and the min-max round trip is exact,
        # so both order AND scores come back byte-identical to fusion.
        eng = _engine(vectors={"a": [0.0, 1.0], "b": [1.0, 0.0]},
                      overrides={"retrieval": {"rerank_blend": 0}})
        out = eng._rerank([_cand("a", 0.020), _cand("b", 0.016)], [1.0, 0.0])
        self.assertEqual(_ids(out), ["a", "b"])
        self.assertEqual([c["score"] for c in out], [0.020, 0.016])


# --------------------------------------------------------------------------
# Degrade paths
# --------------------------------------------------------------------------
class TestRerankDegradeCases(unittest.TestCase):
    def test_candidate_without_vector_keeps_its_normalized_fusion_score(self):
        # "b" has NO stored vector, so its blended score is exactly its
        # normalized fusion score (sim imputed as f = 0.4286) — nothing is
        # subtracted for the missing vector. It therefore holds its ground
        # above "c", which HAS a vector but a mediocre cosine and less fusion,
        # and is passed only by "a", which earns it with a perfect cosine.
        # "x" keeps the lead its decisive fusion score bought it.
        eng = _engine(vectors={"x": [0.1, 0.99498743], "c": [0.55, 0.83516465],
                               "a": [1.0, 0.0]})
        out = eng._rerank([_cand("x", 0.0200), _cand("b", 0.0180),
                           _cand("c", 0.0170), _cand("a", 0.0165)], [1.0, 0.0])
        self.assertEqual(_ids(out), ["x", "a", "b", "c"])

    def test_all_equal_fusion_scores_are_left_alone(self):
        # No spread to normalize against: any constant we imputed for the
        # vectorless candidates would systematically sink one group or the
        # other, so the set passes through untouched.
        eng = _engine(vectors={"a": [0.0, 1.0], "b": [1.0, 0.0]})
        candidates = [_cand("a", 0.02), _cand("b", 0.02)]
        out = eng._rerank(candidates, [1.0, 0.0])
        self.assertIs(out, candidates)
        self.assertEqual(_ids(out), ["a", "b"])

    def test_no_query_embedding_is_identity_fallback(self):
        """No embedder / degraded mode: query_understanding never produces an
        embedding, so _rerank must be a complete no-op -- same object, same
        order, scores untouched (today's fusion-only behavior)."""
        eng = _engine(vectors={"a": [1.0, 0.0], "b": [0.0, 1.0]})
        candidates = [_cand("a", 0.05), _cand("b", 0.01)]
        out = eng._rerank(candidates, None)
        self.assertIs(out, candidates)
        self.assertEqual([c["score"] for c in out], [0.05, 0.01])

    def test_no_query_embedding_never_touches_the_vector_store(self):
        store = _FakeVectorStore({"a": [1.0, 0.0]})
        eng = _engine(store=store)
        eng._rerank([_cand("a", 0.05)], None)
        self.assertEqual(store.lookups, 0)

    def test_negative_cosine_is_floored_not_propagated(self):
        # An anti-parallel embedding means "no relevance", not negative
        # relevance. Floored at 0, "a" keeps half its fusion lead and lands
        # strictly above the envelope floor; propagated as -1 it would blend to
        # 0.0 and be pinned to the floor alongside the genuinely unrelated "c".
        eng = _engine(vectors={"a": [-1.0, 0.0], "b": [1.0, 0.0], "c": [0.0, 1.0]})
        out = eng._rerank([_cand("a", 0.020), _cand("b", 0.018), _cand("c", 0.016)],
                          [1.0, 0.0])
        self.assertEqual(_ids(out), ["b", "a", "c"])
        by_id = {c["belief_id"]: c["score"] for c in out}
        self.assertGreater(by_id["a"], 0.016)
        self.assertAlmostEqual(by_id["c"], 0.016, places=9)

    def test_empty_candidate_list_is_a_no_op(self):
        eng = _engine()
        self.assertEqual(eng._rerank([], [1.0, 0.0]), [])


class TestRerankTopKBoundary(unittest.TestCase):
    def test_candidates_outside_top_k_are_never_reranked(self):
        # Three candidates already sorted by fusion score descending; top_k=2
        # means only the first two are eligible for re-scoring. "c" would win
        # on cosine alone (parallel to the query) but sits outside the top-K
        # window by fusion score, so it must stay last, untouched.
        eng = _engine(vectors={"a": [0.0, 1.0], "b": [0.0, 1.0], "c": [1.0, 0.0]},
                      overrides={"retrieval": {"rerank_top_k": 2}})
        out = eng._rerank([_cand("a", 0.05), _cand("b", 0.04), _cand("c", 0.001)],
                          [1.0, 0.0])
        self.assertEqual(out[-1]["belief_id"], "c")
        self.assertEqual(out[-1]["score"], 0.001)  # untouched fusion score

    def test_default_top_k_is_fifty(self):
        # 60 candidates, all with vectors identical to the query (cos=1.0):
        # only the default top_k=50 are eligible for re-scoring, so the tail
        # (ranks 51-60) must be returned exactly as given.
        vectors = {"b%d" % i: [1.0, 0.0] for i in range(60)}
        eng = _engine(vectors=vectors)
        out = eng._rerank([_cand("b%d" % i, 0.06 - i * 0.001) for i in range(60)],
                          [1.0, 0.0])
        self.assertEqual(_ids(out)[50:], ["b%d" % i for i in range(50, 60)])


class TestRerankConfigDefaults(unittest.TestCase):
    def test_default_blend_is_one_half(self):
        self.assertEqual(_engine()._rerank_blend(), 0.5)

    def test_blend_clamped_into_zero_one(self):
        self.assertEqual(_engine(overrides={"retrieval": {"rerank_blend": 5}})._rerank_blend(), 1.0)
        self.assertEqual(_engine(overrides={"retrieval": {"rerank_blend": -2}})._rerank_blend(), 0.0)

    def test_blend_bad_value_falls_back_to_default(self):
        eng = _engine(overrides={"retrieval": {"rerank_blend": "not-a-number"}})
        self.assertEqual(eng._rerank_blend(), 0.5)

    def test_reranker_version_key_removed(self):
        # F4a: `retrieval.reranker_version` was a vestigial config knob -- no
        # engine code ever read it to select a reranker implementation (it
        # survived only as a DORMANT declaration so a nonsense value still
        # warned at boot). Ladder-9 F4a removed it outright: assert it stays
        # gone rather than silently reappearing with a stale default. The
        # real, only off-switch is rerank_blend: 0 (TestRerankConfigDefaults
        # above covers that knob).
        cfg = Config({})
        self.assertIsNone(cfg.get("retrieval.reranker_version"))
        self.assertNotIn("reranker_version", cfg.raw["retrieval"])


# --------------------------------------------------------------------------
# End-to-end: the acceptance scenario through the real search() entry point
# --------------------------------------------------------------------------
QUERY = "where does Pat Testley work"
QVEC = [1.0, 0.0, 0.0]
RELEVANT = [0.95, 0.3122498999, 0.0]   # cosine to QVEC ≈ 0.95
IRRELEVANT = [0.30, 0.9539392014, 0.0]  # cosine to QVEC ≈ 0.30


class _FixedEmbedder:
    """Every query embeds to QVEC. The acceptance scenario needs stored
    embeddings that DISAGREE with lexical overlap, which a content-derived
    embedder cannot produce by construction — a keyword-spam document is, to a
    hashing embedder, a good match for those keywords."""

    def embed(self, text):
        return list(QVEC)


class _ExplodingLookup(Exception):
    pass


_FIXED = object()  # sentinel: "use _FixedEmbedder", distinct from an explicit None


class TestRerankThroughSearch(unittest.TestCase):
    """Real MemoryStore, real belief_fts ranking, real RRF fusion, real
    search() — no candidate list is hand-fed to _rerank anywhere here."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="e3_")
        self.store = MemoryStore(os.path.join(self.home, "chronicle.db"))
        # Five keyword-spam notes that hammer the query's terms and nothing
        # else, plus the one note that actually answers it in words the query
        # does not use ("employed by", not "work").
        for i in range(5):
            self._note("note:decoy%d" % i, "Pat Testley",
                       "Pat Testley Pat Testley work work Pat Testley work "
                       "where where Pat Testley work", IRRELEVANT)
        self._note("note:answer", "employment",
                   "Pat Testley has been employed by Acme Fake Co since 2019 "
                   "as a staff engineer on the payments team.", RELEVANT)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _note(self, bid, subject, body, vec):
        self.store.upsert_belief("notes", {
            "belief_id": bid, "note_type": "belief", "subject": subject, "body": body,
            "domain": "personal", "owner": "assistant", "read_acl": '["*"]',
            "status": "active", "confidence": 0.8, "created_at": "2026-01-01T00:00:00Z",
            "provenance": '{"source_type":"session_transcript"}'})
        self.store.add_memory_vector(bid, "note", pack(vec), "test-fixed")

    def _search(self, blend=None, embedder=_FIXED, limit=6):
        overrides = {} if blend is None else {"retrieval": {"rerank_blend": blend}}
        eng = RetrievalEngine(self.store, Config(overrides),
                              embedder=_FixedEmbedder() if embedder is _FIXED else embedder,
                              vector_index=_NoIndex())
        return eng.search(QUERY, limit=limit)

    def test_fts_really_does_rank_the_irrelevant_keyword_match_first(self):
        # Guards the premise of the acceptance test: if FTS ever stopped
        # preferring the spam notes, the test below would pass for free.
        fts = [r["belief_id"] for r in self.store.fts_search_beliefs(QUERY, 20)]
        self.assertEqual(fts[0], "note:decoy0")
        self.assertEqual(fts[-1], "note:answer")

    def test_fusion_alone_leaves_the_irrelevant_item_on_top(self):
        # blend=0 is an exact identity, so this IS the pre-rerank fused order.
        self.assertEqual(_ids(self._search(blend=0))[0], "note:decoy0")

    def test_rerank_promotes_the_truly_relevant_item_to_the_top(self):
        # Same store, same query, same fusion — only the default reranker
        # (blend=0.5) differs. THE acceptance criterion.
        self.assertEqual(_ids(self._search())[0], "note:answer")

    def test_rerank_preserves_the_top_score_downstream_gates_read(self):
        fused, reranked = self._search(blend=0), self._search()
        self.assertNotEqual(_ids(fused)[0], _ids(reranked)[0])   # order did change
        self.assertAlmostEqual(fused[0]["score"], reranked[0]["score"], places=12)

    def test_no_embedder_search_is_fusion_order_and_never_looks_up_vectors(self):
        """End-to-end degrade guard AT THE search() ENTRY POINT: with no
        embedder there is no query embedding, so search() must return the plain
        fused ranking without the reranker touching the vector store at all."""
        def boom(_belief_ids):
            raise _ExplodingLookup("reranker must not run without a query embedding")

        self.store.get_memory_vectors_by_ids = boom
        try:
            out = self._search(embedder=None)
        except _ExplodingLookup as e:            # pragma: no cover - failure path
            self.fail(str(e))
        self.assertTrue(out)
        scores = [c["score"] for c in out]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(_ids(out)[0], "note:decoy0")

    def test_no_embedder_matches_blend_zero_ordering_of_the_lexical_channels(self):
        # Belt and braces: with the vector channel gone, the surviving lexical
        # ranking still leads with the FTS winner and still contains the
        # answer note — the degrade loses precision, never the candidate.
        out = _ids(self._search(embedder=None))
        self.assertEqual(out[0], "note:decoy0")
        self.assertIn("note:answer", out)


if __name__ == "__main__":
    unittest.main()
