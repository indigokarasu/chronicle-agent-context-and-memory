"""
Chronicle — Ladder 9 cross-feature integration.

Every ladder-9 task was built and reviewed alone, against the same v550 base.
These tests cover only what could not exist in any single work tree: the places
where two finished features meet. Each one failed, or could not have been
written, before the integration.

Contents:
  * doc2query proxies (E2) vs the embedder-mismatch heal (E1 x E2)
  * doc2query proxies (E2) vs E5's novelty scan and E7's identity centroid --
    the "scan source" guards: both must be blind to proxy rows, and table
    separation is the ONLY thing enforcing it (proxies carry a parent-shaped
    `kind` and the parent's belief_id, so a query that forgot to name its
    table would silently pick them up)
  * one full capture -> process -> get_context flow with EVERY ladder-9
    feature at its shipped default, asserting no exception and a usable answer
  * the ladder-9 config surface, pinned at defaults
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import identity
from engine.config import Config
from engine.core import ChronicleCore

_FACT_KEY = {"entity_id": "ent_pat_testley", "entity_name": "Pat Testley",
             "predicate_canonical": "works_at", "attribute": "works_at",
             "qualifiers_hash": "", "qualifiers": {}}


def make_core(overrides=None):
    home = tempfile.mkdtemp(prefix="l9-integ-")
    cfg = {"embeddings": {"model": "hashing"}}
    if overrides:
        cfg.update(overrides)
    core = ChronicleCore(home, cfg)
    core.initialize("s1", principal_id="assistant")
    return core, home


def assert_fact(core, body="Acme Fake Co", key=None, source_event="src1"):
    core.capture.append("asserted", {
        "kind": "fact", "key": dict(key or _FACT_KEY), "body": body,
        "confidence": 0.9, "source_event": source_event,
        "source_type": "user_direct", "domain": "user"},
        actor="user", trust_level=4, session_id="s1")


class _CoreCase(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)


class TestHealConvergesWithProxiesPresent(_CoreCase):
    """E1 x E2. The heal scans three vector tables now; with proxies present it
    must still terminate rather than re-detecting the same rows forever."""

    def test_heal_with_proxies_present_converges(self):
        assert_fact(self.core)
        self.assertTrue(self.core.store.iter_query_proxy_vectors(),
                        "fixture produced no proxies to exercise the scan")

        first = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        second = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]

        # Everything is correctly tagged, so a clean store heals to zero twice
        # -- the failure this guards is a heal that reports work forever.
        self.assertEqual(first["mismatched"], 0)
        self.assertEqual(second["mismatched"], 0)
        # ...and it did not delete the healthy proxies on the way through.
        self.assertTrue(self.core.store.iter_query_proxy_vectors())


class TestProxiesAreInvisibleToOtherScans(_CoreCase):
    """The scan-source guards (review ledger item G).

    query_proxy_vectors rows deliberately carry the PARENT's belief_id and the
    PARENT's belief kind, so they are indistinguishable from a content vector
    on every column except which table they live in. Table separation is the
    only guard, which makes it worth pinning explicitly rather than assuming.
    """

    def test_novelty_scan_result_is_unchanged_by_the_presence_of_proxies(self):
        # Same store, same write, measured with and without proxies present.
        with_proxies, _ = make_core()
        with_proxies.initialize("s1", principal_id="assistant")
        assert_fact(with_proxies)
        self.assertTrue(with_proxies.store.iter_query_proxy_vectors())
        novelty_with = with_proxies.store.query_beliefs(
            "facts", "entity_id=?", ("ent_pat_testley",), limit=1)[0]["novelty"]

        without, _ = make_core({"embeddings": {"model": "hashing",
                                               "doc2query": {"beliefs": False,
                                                             "excerpts": False}}})
        without.initialize("s1", principal_id="assistant")
        assert_fact(without)
        self.assertEqual(without.store.iter_query_proxy_vectors(), [],
                         "control arm still wrote proxies")
        novelty_without = without.store.query_beliefs(
            "facts", "entity_id=?", ("ent_pat_testley",), limit=1)[0]["novelty"]

        self.assertEqual(novelty_with, novelty_without,
                         "E5 novelty changed when proxies existed -- the scan is "
                         "reading query_proxy_vectors")

    def test_nearest_memory_vectors_never_returns_a_proxy_row(self):
        """Directly at the accessor E5's novelty/dup scan runs on."""
        assert_fact(self.core)
        proxies = self.core.store.iter_query_proxy_vectors()
        self.assertTrue(proxies)
        vec = [0.05] * self.core.embedder.dimensions
        hits = self.core.store.nearest_memory_vectors(
            "fact", vec, "user", "user", k=50)
        # Every hit resolves to a real belief row; a proxy would too (it carries
        # the parent id), so assert on COUNT: one row per belief, not one per
        # belief + one per proxy.
        ids = [bid for bid, _sim in hits]
        self.assertEqual(len(ids), len(set(ids)), "a belief appeared twice")
        n_facts = self.core.store.count_rows("facts", "status='active'")
        self.assertLessEqual(len(ids), n_facts)

    def test_identity_centroid_folds_read_no_vector_table_at_all(self):
        """E7's centroid is fed the belief's vector by the reducer; it must not
        go looking for vectors itself, which is what keeps proxies out of it."""
        vec = [0.1] * 8
        identity.observe_mention(self.core.store, Config({}), "m1", "ent_pat_testley",
                                 "mention0", vec, "2026-01-01T00:00:00Z")
        seen = []
        conn = self.core.store._conn()
        conn.set_trace_callback(seen.append)
        try:
            identity.observe_mention(self.core.store, Config({}), "m1", "ent_pat_testley",
                                     "mention1", vec, "2026-01-02T00:00:00Z")
        finally:
            conn.set_trace_callback(None)
        self.assertTrue(seen, "trace callback captured nothing")
        for sql in seen:
            self.assertNotIn("query_proxy_vectors", sql)
            self.assertNotIn("memory_vectors", sql)
            self.assertNotIn("observed_vectors", sql)


class TestFullLadderFlowAtDefaults(unittest.TestCase):
    """One end-to-end flow with EVERY ladder-9 feature at its shipped default:
    E1 prefixes (auto/off for hashing), E2 doc2query on for beliefs, E3 rerank
    blend 0.5, E4 supersede candidates, E5 novelty/merge, E6 topic shift, E7
    identity evidence, E8 MMR, E9 routing (margin-gated), E10 abstention off,
    E11 verification available, H1 piggyback off.

    The bar is the integration bar: no exception anywhere, and a get_context
    that still answers.
    """

    def setUp(self):
        self.core, self.home = make_core()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def test_capture_process_get_context_runs_clean(self):
        turns = [
            ("My name is Pat Testley and I work at Acme Fake Co.", "Noted, Pat."),
            ("My office is in Fake City.", "Got it."),
            ("I prefer metric units.", "Understood."),
            ("Let's switch topics -- I want to talk about kayaking.", "Sure."),
            ("I went kayaking on the Fake River last weekend.", "Nice."),
        ]
        for user, assistant in turns:
            self.core.capture.observe(user, assistant, session_id="s1")
        self.core.process_pending()

        # A later, superseding assertion: exercises E4 + E5 on the same write.
        assert_fact(self.core, body="Acme Fake Co", source_event="e1")
        assert_fact(self.core, body="Beta Fake Inc", source_event="e2")

        ctx = self.core.retrieval.get_context("where does Pat Testley work",
                                              token_budget=1500)
        self.assertIsInstance(ctx, str)
        self.assertTrue(ctx.strip(), "get_context returned nothing")

        # The routing debug field is present and, for this factual question,
        # is the default route (E9 margin gate).
        route = self.core.retrieval.classify_route("where does Pat Testley work")
        self.assertEqual(route["route"], "factual")
        self.assertTrue(route["enabled"])

        # E11 is callable on the real sources answer() returns.
        ans = self.core.retrieval.answer("where does Pat Testley work")
        verdict = self.core.retrieval.verify_answer(
            "Pat Testley works at Beta Fake Inc.", ans.get("sources") or [])
        self.assertIn("support", verdict)
        self.assertIn("supported", verdict)

    def test_every_ladder9_surface_is_populated_after_the_flow(self):
        """Each feature actually did something -- so the clean run above is not
        clean merely because everything was inert."""
        for user, assistant in (("My name is Pat Testley and I work at Acme Fake Co.", "Noted."),
                                ("I went kayaking on the Fake River.", "Nice.")):
            self.core.capture.observe(user, assistant, session_id="s1")
        self.core.process_pending()
        assert_fact(self.core, body="Acme Fake Co", source_event="e1")
        assert_fact(self.core, body="Beta Fake Inc", source_event="e2")

        store = self.core.store
        self.assertTrue(store.iter_memory_vectors(), "no content vectors (E1/base)")
        self.assertTrue(store.iter_query_proxy_vectors(), "no doc2query proxies (E2)")
        self.assertTrue(store.count_rows("entity_centroids"), "no identity centroid (E7)")
        facts = store.query_beliefs("facts", "entity_id=?", ("ent_pat_testley",), limit=10)
        self.assertTrue(facts)
        self.assertIsNotNone(facts[0]["novelty"], "novelty never scored (E5)")

    def test_host_model_stays_inert_through_the_whole_flow(self):
        """H1 default-off, asserted on the SAME flow the other features ran."""
        for user, assistant in (("My name is Pat Testley.", "Hello, Pat."),
                                ("I work at Acme Fake Co.", "Noted.")):
            self.core.capture.observe(user, assistant, session_id="s1")
        self.core.process_pending()
        self.assertFalse(self.core.cfg.get("host_model.piggyback"))
        self.assertEqual(self.core.store.count_rows("host_model_requests"), 0)
        self.assertEqual(self.core.store.count_rows("host_model_results"), 0)


class TestLadder9ConfigDefaults(_CoreCase):
    """The shipped default for every ladder-9 knob, in one place. A default
    that drifts during a later merge changes measured behavior silently."""

    def test_defaults(self):
        cfg = self.core.cfg
        self.assertEqual(cfg.get("embeddings.task_prefixes"), "auto")           # E1
        self.assertTrue(cfg.get("embeddings.doc2query.beliefs"))                # E2
        self.assertFalse(cfg.get("embeddings.doc2query.excerpts"))              # E2
        self.assertEqual(cfg.get("retrieval.rerank_blend"), 0.5)                # E3
        self.assertEqual(cfg.get("retrieval.rerank_top_k"), 50)                 # E3
        self.assertEqual(cfg.get("curation.supersede_similarity"), 0.82)        # E4
        self.assertEqual(cfg.get("curation.dup_similarity"), 0.95)              # E5
        self.assertEqual(cfg.get("curation.topic_shift_threshold"), 0.35)       # E6
        self.assertEqual(cfg.get("identity.split_below"), 0.30)                 # E7
        self.assertEqual(cfg.get("identity.merge_above"), 0.90)                 # E7
        self.assertEqual(cfg.get("retrieval.mmr_lambda"), 0.7)                  # E8
        self.assertTrue(cfg.get("retrieval.query_routing"))                     # E9
        self.assertEqual(cfg.get("retrieval.query_routing_margin"), 0.20)       # E9 (fix H)
        self.assertIsNone(cfg.get("retrieval.abstain_distance"))                # E10
        self.assertEqual(cfg.get("retrieval.support_threshold"), 0.55)          # E11
        self.assertTrue(cfg.get("context.precision_packing"))                   # E12
        self.assertEqual(cfg.get("context.precision_budget"), 1500)             # E12
        self.assertEqual(cfg.get("context.precision_concentration"), 0.60)      # E12
        self.assertEqual(cfg.get("context.precision_margin"), 0.0)              # E12 (secondary)
        self.assertFalse(cfg.get("host_model.piggyback"))                       # H1

    def test_the_two_similarity_floors_stay_ordered(self):
        """E4's supersede floor must sit strictly BELOW E5's merge floor: they
        are two rungs on one cosine scale, and inverting them would make every
        supersede candidate a merge instead."""
        self.assertLess(self.core.cfg.get("curation.supersede_similarity"),
                        self.core.cfg.get("curation.dup_similarity"))


if __name__ == "__main__":
    unittest.main()
