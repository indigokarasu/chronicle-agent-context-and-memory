"""
Chronicle — tests for §L9 E8: greedy-MMR diversity packing in
RetrievalEngine.search()'s Tier-1 candidate SELECTION.

Budget packing used to take candidates in plain score order, so a cluster of
near-duplicate hits (the same fact restated, or several near-identical
excerpts) could occupy every slot the fixed `limit` allows, crowding out
distinct evidence that scored lower only because nothing else agreed with it.
`_mmr_select` fixes the SELECTION step only; get_context's evidence-forward
ORDERING (§L8) is untouched -- search() still returns its result sorted by
score, descending, exactly as before this task.

Fixtures use obviously-fake values (Pat Testley, Acme Fake Co).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import Config, DEFAULTS
from engine.embeddings import HashingEmbedder, pack
from engine.retrieval import RetrievalEngine
from engine.store import MemoryStore


def _vec(direction, dims=4):
    """A crisp, already-normalized basis vector so cosine similarity between
    fixture items is exact and trivial to reason about: identical direction
    -> cosine 1.0 (a true near-duplicate), orthogonal directions -> cosine
    0.0 (a genuinely distinct item), independent of the hashing embedder's
    own (much messier) geometry."""
    v = [0.0] * dims
    v[direction] = 1.0
    return v


class MMRSelectTests(unittest.TestCase):
    """Direct tests of RetrievalEngine._mmr_select (§L9 E8 acceptance)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.eng = RetrievalEngine(self.store, cfg=None, embedder=None)
        self.assertAlmostEqual(self.eng._mmr_lambda, DEFAULTS["retrieval"]["mmr_lambda"])

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _put(self, belief_id, direction):
        self.store.add_memory_vector(belief_id, "fact", pack(_vec(direction)), "test")

    def test_near_duplicates_no_longer_crowd_out_distinct_items(self):
        """§L9 E8 acceptance: synthetic candidates with a near-duplicate
        cluster + 2 distinct relevant items + 5 slots -> the distinct items
        get in, even though plain score order would have excluded both."""
        # A 5-member near-duplicate cluster (all direction 0: cosine 1.0 to
        # each other), scored highest -- plain top-5 by score alone would be
        # exactly this cluster, in full, crowding out every other candidate.
        dup_scores = [1.00, 0.97, 0.94, 0.91, 0.88]
        for i, s in enumerate(dup_scores):
            bid = f"dup{i+1}"
            self._put(bid, 0)

        # Two genuinely distinct, still-relevant items (orthogonal directions
        # 1 and 2 -- zero similarity to the duplicate cluster AND to each
        # other), scored below the cluster but above the filler anchor.
        self._put("distinct1", 1)
        self._put("distinct2", 2)

        # A low-score, low-relevance filler (direction 3, orthogonal to
        # everything) that anchors the min-max normalization floor without
        # ever being a real contender.
        self._put("filler", 3)

        candidates = (
            [{"belief_id": f"dup{i+1}", "score": s} for i, s in enumerate(dup_scores)]
            + [{"belief_id": "distinct1", "score": 0.85},
               {"belief_id": "distinct2", "score": 0.83},
               {"belief_id": "filler", "score": 0.50}]
        )
        k = 5

        # Sanity/positive-control: confirm the fixture actually reproduces
        # the bug this task fixes -- plain score-order top-k excludes BOTH
        # distinct items.
        plain_top_k = {c["belief_id"] for c in
                       sorted(candidates, key=lambda c: c["score"], reverse=True)[:k]}
        self.assertNotIn("distinct1", plain_top_k, "fixture assumption broken")
        self.assertNotIn("distinct2", plain_top_k, "fixture assumption broken")

        selected = set(self.eng._mmr_select(candidates, k, self.eng._mmr_lambda))

        self.assertEqual(len(selected), k)
        self.assertIn("distinct1", selected,
                       "MMR selection still let the duplicate cluster crowd out distinct1")
        self.assertIn("distinct2", selected,
                       "MMR selection still let the duplicate cluster crowd out distinct2")
        # The redundant tail of the cluster is what MMR is supposed to trade
        # away for that room -- at least one of the lowest-scoring duplicates
        # must have lost its slot.
        self.assertFalse({"dup4", "dup5"} <= selected,
                         "MMR kept the whole duplicate cluster instead of making room")

    def test_pool_not_larger_than_k_returns_everything_unfiltered(self):
        """No selection pressure -> no-op (every candidate fits)."""
        candidates = [{"belief_id": "a", "score": 0.9}, {"belief_id": "b", "score": 0.1}]
        got = self.eng._mmr_select(candidates, 5, 0.7)
        self.assertEqual(set(got), {"a", "b"})

    def test_k_zero_returns_nothing(self):
        candidates = [{"belief_id": "a", "score": 0.9}]
        self.assertEqual(self.eng._mmr_select(candidates, 0, 0.7), [])

    def test_empty_candidates_returns_nothing(self):
        self.assertEqual(self.eng._mmr_select([], 5, 0.7), [])

    def test_lambda_one_is_pure_relevance_same_as_legacy_score_order(self):
        """lam=1.0 zeroes the diversity term entirely (val = relevance always,
        independent of what's already picked), so greedy selection degenerates
        to exactly the legacy top-k-by-score behavior this task changes the
        default away from -- the mathematical regression check for §L8's
        'no embedder -> score order' / lam-independent invariant."""
        for i in range(4):
            self._put(f"dup{i}", 0)
        candidates = [{"belief_id": f"dup{i}", "score": 1.0 - i * 0.1} for i in range(4)]
        selected = self.eng._mmr_select(candidates, 2, 1.0)
        self.assertEqual(set(selected), {"dup0", "dup1"},
                         "lam=1.0 must reduce to plain top-k by score")

    def test_vectorless_candidate_fills_only_genuine_leftover_room(self):
        """A candidate with no stored memory_vector (entities: §R12, they
        carry no vector by design) must never be exempt from the diversity
        penalty in a way that lets it OUTCOMPETE a penalized vectored
        candidate -- it only gets a slot once the vectored pool's own `k`
        share is decided and there's genuine room left over."""
        self._put("has_vec", 0)
        # "no_vec" deliberately gets no add_memory_vector call.
        candidates = [
            {"belief_id": "has_vec", "score": 0.9},
            {"belief_id": "no_vec", "score": 0.5},
        ]
        # Must not raise, and must return both when k covers the whole pool
        # (the len(candidates) <= k shortcut, before any tiering happens).
        selected = self.eng._mmr_select(candidates, 2, 0.7)
        self.assertEqual(set(selected), {"has_vec", "no_vec"})

    def test_vectorless_candidate_cannot_displace_a_penalized_vectored_candidate(self):
        """Regression (ctx_eval s_ctx100.json instance #4, token_budget=1500):
        a bare vector-less entity stub ('[ENTITY] IKEA', no vector -- §R12)
        leapfrogged the actual answer-bearing episode (which DOES have a
        vector, and paid the redundancy tax for legitimately overlapping an
        earlier same-topic pick) into the last Tier-1 slot, even though the
        episode outscored it before either was penalized. Minimal repro: a
        2-member near-duplicate vectored cluster (A1 clearly wins the first
        slot; A2 is redundant with A1 and would be penalized for it) plus one
        vector-less candidate scoring just below A2. Since the vectored pool
        (2 items) already covers all of k=2's slots, the vector-less
        candidate must never bump A2 out."""
        self._put("A1", 0)
        self._put("A2", 0)  # same direction as A1 -> cosine(A1, A2) == 1.0
        # "ent" deliberately gets no add_memory_vector call.
        candidates = [
            {"belief_id": "A1", "score": 0.90},
            {"belief_id": "A2", "score": 0.50},
            {"belief_id": "ent", "score": 0.48},
        ]
        selected = set(self.eng._mmr_select(candidates, 2, 0.7))
        self.assertEqual(selected, {"A1", "A2"},
                         "vector-less 'ent' displaced the penalized-but-legitimate A2")

    def test_vectorless_candidates_fill_leftover_slots_by_their_own_relevance(self):
        """When the vectored pool is smaller than k, the leftover slots go to
        the highest-scoring vector-less candidates -- they are never simply
        dropped for lacking a vector."""
        self._put("A1", 0)
        candidates = [
            {"belief_id": "A1", "score": 0.90},
            {"belief_id": "ent_hi", "score": 0.50},
            {"belief_id": "ent_lo", "score": 0.10},
        ]
        selected = set(self.eng._mmr_select(candidates, 2, 0.7))
        self.assertEqual(selected, {"A1", "ent_hi"})

    def test_deep_tail_off_topic_candidate_cannot_win_a_slot(self):
        """Regression (ctx_eval instance "94f70d80", s_ctx100.json,
        budget=1500), found AFTER the vector-less fix above landed and still
        failing with it in place: full-pipeline `search()` feeds
        `_mmr_select` the WHOLE fused candidate pool (43 items for that
        query, k=10), not just the natural top-k -- it must, since a
        crowded-out item is by definition ranked below the naive cutoff. But
        an unbounded pool lets the argmax reach arbitrarily deep for
        "diversity": a rank-17 off-topic candidate beat the rank-9
        answer-bearing item into the last slot, purely because rank-17 had
        zero similarity to anything already selected while the true answer
        paid a redundancy tax for legitimately overlapping an earlier
        same-topic pick. Both carried vectors, so the vector-less split does
        not apply -- the pool itself must be bounded (§_mmr_select's
        ELIGIBILITY WINDOW).

        Minimal repro: 3 mutually-orthogonal anchors clearly win the first 3
        of k=4 slots. For the last slot, `target` (on-topic, but redundant
        with anchor_a -- cosine 1.0) competes against two other in-window
        candidates ALSO redundant with an anchor (so nothing "easy" is left
        to win instead) and `distractor`, ranked just past the eligibility
        window, in whose favor no in-window competitor exists. Positive
        control below proves `distractor` actually would win the slot in an
        unbounded pool -- confirming the window, not something else, is what
        fixes it."""
        dims = 6
        pool = [
            ("anchor_a", 0, 1.00), ("anchor_b", 1, 0.90), ("anchor_c", 2, 0.80),
            ("target", 0, 0.30),            # redundant w/ anchor_a
            ("filler_r1", 1, 0.28),          # redundant w/ anchor_b
            ("filler_r2", 2, 0.26),          # redundant w/ anchor_c
            ("distractor", 5, 0.20),         # orthogonal to everything; rank 6, outside the k=4 window (6)
        ]
        for bid, direction, _ in pool:
            self.store.add_memory_vector(bid, "fact", pack(_vec(direction, dims)), "test")
        candidates = [{"belief_id": bid, "score": s} for bid, _, s in pool]
        k, lam = 4, 0.7

        # Positive control: an unbounded pool (window >= full pool) lets the
        # off-topic tail candidate win instead of the redundant-but-on-topic
        # target -- confirms the fixture reproduces the bug this task fixes.
        orig_overfetch = self.eng._MMR_POOL_OVERFETCH
        try:
            self.eng._MMR_POOL_OVERFETCH = len(candidates)  # window covers everything
            unbounded = set(self.eng._mmr_select(candidates, k, lam))
        finally:
            self.eng._MMR_POOL_OVERFETCH = orig_overfetch
        self.assertIn("distractor", unbounded,
                       "fixture assumption broken: unbounded MMR should let the tail candidate win")
        self.assertNotIn("target", unbounded,
                          "fixture assumption broken: unbounded MMR should crowd target out")

        # With the real (windowed) eligibility bound, the tail candidate is
        # never even in the running -- target wins the slot instead.
        selected = set(self.eng._mmr_select(candidates, k, lam))
        self.assertNotIn("distractor", selected,
                         "MMR selection reached past the eligibility window for a diversity pick")
        self.assertIn("target", selected,
                       "windowed MMR selection still dropped the on-topic redundant item")


class MMRConfigTests(unittest.TestCase):
    """§L9 E8: retrieval.mmr_lambda wiring and clamping."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_default_is_point_seven(self):
        self.assertEqual(DEFAULTS["retrieval"]["mmr_lambda"], 0.7)
        eng = RetrievalEngine(self.store, cfg=None, embedder=None)
        self.assertAlmostEqual(eng._mmr_lambda, 0.7)

    def test_explicit_config_value_is_honored(self):
        cfg = Config({"retrieval": {"mmr_lambda": 0.3}})
        eng = RetrievalEngine(self.store, cfg=cfg, embedder=None)
        self.assertAlmostEqual(eng._mmr_lambda, 0.3)

    def test_out_of_range_value_is_clamped_into_zero_one(self):
        cfg = Config({"retrieval": {"mmr_lambda": 5.0}})
        eng = RetrievalEngine(self.store, cfg=cfg, embedder=None)
        self.assertAlmostEqual(eng._mmr_lambda, 1.0)

        cfg2 = Config({"retrieval": {"mmr_lambda": -3.0}})
        eng2 = RetrievalEngine(self.store, cfg=cfg2, embedder=None)
        self.assertAlmostEqual(eng2._mmr_lambda, 0.0)


class SearchMMRWiringTests(unittest.TestCase):
    """§L9 E8: search() gates MMR on embedder + query-vector availability,
    and the returned ORDER stays score-descending either way (selection
    only -- get_context's §L8 evidence-forward ordering is untouched)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _facts(self, n, embedder=None):
        """n distinct facts, all matching the query token "acme", so they all
        land in the same candidate pool and compete for `limit` slots."""
        for i in range(n):
            bid = f"f{i}"
            self.store.upsert_belief("facts", {
                "belief_id": bid, "entity_id": "user",
                "predicate_canonical": "test", "attribute": "note%d" % i,
                "qualifiers_hash": "", "provenance": "{}",
                "value": "Acme Fake Co detail %d" % i, "status": "active",
                "owner": "default", "domain": "user", "fidelity": "verbatim",
                "salience": "normal", "confidence": 0.9, "criticality": "normal",
                "confirm_count": 0, "contradiction_count": 0, "utility": 0.0,
            })
            if embedder is not None:
                self.store.add_memory_vector(
                    bid, "fact", pack(embedder.embed("Acme Fake Co detail %d" % i)), embedder.model)

    def test_no_embedder_never_touches_the_vector_lookup(self):
        """§L9 shared constraint: the embedder may be absent -- search() must
        degrade to today's plain score order without ever hitting the new
        by-id vector lookup (defensive: proves the gate, not just the
        outcome)."""
        self._facts(15)
        eng = RetrievalEngine(self.store, cfg=None, embedder=None)

        def _boom(_ids):
            raise AssertionError("get_memory_vectors_by_ids called with no embedder")
        self.store.get_memory_vectors_by_ids = _boom

        hits = eng.search("Acme Fake Co", limit=5)
        self.assertEqual(len(hits), 5)
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_result_order_is_still_score_descending_with_mmr_active(self):
        """Selection only: MMR may change WHICH candidates are returned, but
        never their order (§L8 evidence-forward contract, r1 priority rule)."""
        emb = HashingEmbedder()
        self._facts(15, embedder=emb)
        eng = RetrievalEngine(self.store, cfg=None, embedder=emb)

        hits = eng.search("Acme Fake Co", limit=5)
        self.assertEqual(len(hits), 5)
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True),
                         "search() must still return candidates in score order")

    def test_small_pool_under_limit_is_unaffected(self):
        """Fewer candidates than `limit` -> nothing to select, MMR is a no-op
        by construction (len(out) > limit gate)."""
        emb = HashingEmbedder()
        self._facts(3, embedder=emb)
        eng = RetrievalEngine(self.store, cfg=None, embedder=emb)
        hits = eng.search("Acme Fake Co", limit=10)
        self.assertEqual(len(hits), 3)


if __name__ == "__main__":
    unittest.main()
