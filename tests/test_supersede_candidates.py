"""
Chronicle — tests for Ladder 9 E4: update detection (supersede candidates).

On write of a fact, a nearest-neighbor search among same-subject active facts
(falling back to a global scan when there is no same-subject candidate) may
find a high-similarity, different-value match. When it does, a DATED
`supersede_candidates` edge is recorded so a reader can apply "latest wins"
downstream (get_context) -- but nothing about the belief itself is touched:
no status change, no deletion, no auto-supersede. That destructive-adjacent
behavior stays exactly the job of the pre-existing exact-key conflict policy
in `_apply_fact_conflict`, which is untouched by this feature.

Fixtures use obviously-fake values (Pat Testley, Acme Fake Co, Sam Vimes),
per the shared Ladder 9 test-fixture convention.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.reducer import Reducer
from engine.store import MemoryStore


def make_core(cfg_overrides=None):
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return ChronicleCore(home, cfg), home


def _assert_fact(core, key, body, *, source_event, domain="general", owner="assistant"):
    core.capture.append(
        "asserted",
        {"kind": "fact", "key": key, "body": body, "confidence": 0.8,
         "source_event": source_event, "source_type": "user_direct", "domain": domain},
        actor="user", owner=owner, trust_level=3)


class TestSupersedeCandidateStore(unittest.TestCase):
    """Store-layer contract in isolation, no embedder involved."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(str(Path(self.tmp) / "chronicle.db"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_and_chain(self):
        self.store.upsert_belief("facts", {
            "belief_id": "f1", "entity_id": "pat_testley", "attribute": "works_at",
            "predicate_canonical": "works_at", "value": "Acme Fake Co", "domain": "general",
            "owner": "assistant", "status": "active", "provenance": "{}",
            "created_at": "2026-01-01T00:00:00.000Z", "valid_from": "2026-01-01T00:00:00.000Z"})
        self.store.upsert_belief("facts", {
            "belief_id": "f2", "entity_id": "pat_testley", "attribute": "works_at",
            "predicate_canonical": "works_at", "value": "Beta Fake Inc", "domain": "general",
            "owner": "assistant", "status": "active", "provenance": "{}",
            "created_at": "2026-03-01T00:00:00.000Z", "valid_from": "2026-03-01T00:00:00.000Z"})
        self.store.add_supersede_candidate("f2", "f1", 0.9, new_value="Beta Fake Inc",
                                           old_value="Acme Fake Co")
        chain = self.store.get_supersede_chain("f2")
        self.assertEqual([c["belief_id"] for c in chain], ["f1", "f2"])  # date-ordered, oldest first
        self.assertEqual(chain[0]["value"], "Acme Fake Co")
        self.assertEqual(chain[1]["value"], "Beta Fake Inc")
        # Nothing destructive: both facts are still active.
        self.assertEqual(self.store.get_belief("facts", "f1")["status"], "active")
        self.assertEqual(self.store.get_belief("facts", "f2")["status"], "active")

    def test_chain_empty_when_no_edges(self):
        self.store.upsert_belief("facts", {
            "belief_id": "f1", "entity_id": "pat_testley", "attribute": "works_at",
            "value": "Acme Fake Co", "domain": "general", "owner": "assistant",
            "status": "active", "provenance": "{}", "created_at": "2026-01-01T00:00:00.000Z"})
        self.assertEqual(self.store.get_supersede_chain("f1"), [])

    def test_add_is_idempotent(self):
        for bid, val in (("f1", "Acme Fake Co"), ("f2", "Beta Fake Inc")):
            self.store.upsert_belief("facts", {
                "belief_id": bid, "entity_id": "pat_testley", "attribute": "works_at",
                "value": val, "domain": "general", "owner": "assistant", "status": "active",
                "provenance": "{}", "created_at": "2026-01-01T00:00:00.000Z"})
        self.store.add_supersede_candidate("f2", "f1", 0.9)
        self.store.add_supersede_candidate("f2", "f1", 0.9)  # replay-safe (rebuild)
        rows = self.store._conn().execute("SELECT COUNT(*) c FROM supersede_candidates").fetchone()
        self.assertEqual(rows["c"], 1)

    def test_truncate_projection_clears_candidates(self):
        for bid, val in (("f1", "Acme Fake Co"), ("f2", "Beta Fake Inc")):
            self.store.upsert_belief("facts", {
                "belief_id": bid, "entity_id": "pat_testley", "attribute": "works_at",
                "value": val, "domain": "general", "owner": "assistant", "status": "active",
                "provenance": "{}", "created_at": "2026-01-01T00:00:00.000Z"})
        self.store.add_supersede_candidate("f2", "f1", 0.9)
        self.store.truncate_projection()
        rows = self.store._conn().execute("SELECT COUNT(*) c FROM supersede_candidates").fetchone()
        self.assertEqual(rows["c"], 0)


class TestSupersedeCandidateWrite(unittest.TestCase):
    """End-to-end through the reducer: `capture.append("asserted", ...)`."""

    def setUp(self):
        # Hashing mode is a coarse, purely lexical similarity signal -- two
        # DIFFERENT company names ("Acme Fake Co" vs "Beta Fake Inc") share no
        # tokens with each other, so the full asserted clause (which shares
        # "Pat Testley works at") is what actually carries the "same claim,
        # different value" signal, at ~0.71 cosine (measured). A real semantic
        # embedder resolves genuinely-related-but-different values well above
        # the shipped 0.82 default without needing this override; hashing
        # mode's default-config behavior is exercised separately below
        # (test_default_threshold_stays_dormant_for_hashing_mode) precisely
        # because it stays a no-op there, by design (§issue-8 shared
        # constraints: "must degrade to a no-op or today's heuristic").
        self.core, self.home = make_core({"curation": {"supersede_similarity": 0.65}})

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _pat_key(self, qualifiers_hash=""):
        return {"entity_id": "pat_testley", "predicate_canonical": "works_at", "attribute": "works_at",
                "qualifiers_hash": qualifiers_hash, "qualifiers": {}, "entity_name": "Pat Testley",
                "owner": "assistant", "domain": "general"}

    def test_same_subject_update_creates_dated_chain_never_destructive(self):
        _assert_fact(self.core, self._pat_key(""), "Pat Testley works at Acme Fake Co",
                    source_event="e1")
        _assert_fact(self.core, self._pat_key("v2"), "Pat Testley works at Beta Fake Inc",
                    source_event="e2")

        facts = self.core.store.query_beliefs("facts", "entity_id=?", ("pat_testley",), limit=10)
        self.assertEqual(len(facts), 2)
        # Never destructive: both remain active, no deletes.
        self.assertTrue(all(f["status"] == "active" for f in facts))

        new_fact = next(f for f in facts if "Beta Fake Inc" in f["value"])
        old_fact = next(f for f in facts if "Acme Fake Co" in f["value"])

        chain = self.core.store.get_supersede_chain(new_fact["belief_id"])
        self.assertEqual(len(chain), 2)
        self.assertEqual(chain[0]["belief_id"], old_fact["belief_id"])   # oldest first
        self.assertEqual(chain[1]["belief_id"], new_fact["belief_id"])
        self.assertIn("Acme Fake Co", chain[0]["value"])
        self.assertIn("Beta Fake Inc", chain[1]["value"])
        self.assertTrue(chain[0]["created_at"] and chain[1]["created_at"])  # dated

        # get_context shows BOTH values, dated.
        ctx = self.core.retrieval.get_context("Pat Testley works at", token_budget=1500)
        self.assertIn("Acme Fake Co", ctx)
        self.assertIn("Beta Fake Inc", ctx)
        self.assertIn("history", ctx)

    def test_identical_reassertion_is_not_a_candidate(self):
        """E4's claim: re-stating the SAME value is not an update, so it must
        never produce a supersede chain.

        Integration note (E4 x E5): this originally also asserted that the two
        assertions stored as two separate facts. Once E5's near-duplicate merge
        is in the tree that is no longer the expected shape -- E5's acceptance
        bar is verbatim "identical re-assertion merges (1 item, 2 provenance
        entries)", and this fixture is exactly an identical re-assertion. The
        two specs agree on the thing E4 is actually testing (no chain); only
        the storage shape underneath it changed, so the count assertion follows
        E5 and the chain assertion -- E4's real subject -- is unchanged.
        """
        _assert_fact(self.core, self._pat_key(""), "Pat Testley works at Acme Fake Co",
                    source_event="e1")
        _assert_fact(self.core, self._pat_key("v2"), "Pat Testley works at Acme Fake Co",
                    source_event="e2")
        facts = self.core.store.query_beliefs("facts", "entity_id=?", ("pat_testley",), limit=10)
        self.assertEqual(len(facts), 1, "E5 merges an identical re-assertion into one item")
        # THE E4 ASSERTION, unchanged: no supersession was inferred.
        for f in facts:
            self.assertEqual(self.core.store.get_supersede_chain(f["belief_id"]), [])
        # And the merge really was a merge, not a dropped write (E5 provenance).
        self.assertGreaterEqual(facts[0].get("occurrence_count") or 1, 2)

    def test_dissimilar_same_subject_facts_stay_unchained(self):
        _assert_fact(self.core, self._pat_key(""), "Pat Testley works at Acme Fake Co",
                    source_event="e1")
        key2 = self._pat_key("v2")
        key2["predicate_canonical"] = "hobby"
        key2["attribute"] = "hobby"
        _assert_fact(self.core, key2, "Sam Vimes enjoys long walks on the beach", source_event="e2")
        facts = self.core.store.query_beliefs("facts", "entity_id=?", ("pat_testley",), limit=10)
        hobby = next(f for f in facts if "walks" in f["value"])
        self.assertEqual(self.core.store.get_supersede_chain(hobby["belief_id"]), [])


class TestSupersedeCandidateDefaultThreshold(unittest.TestCase):
    """No config override: exercises the shipped 0.82 default."""

    def setUp(self):
        self.core, self.home = make_core()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_default_threshold_stays_dormant_for_hashing_mode(self):
        """§issue-8 shared constraint: unconfigured, this must not change
        today's behavior. Hashing mode's crude lexical similarity for two
        genuinely different values (~0.71, measured) sits below the shipped
        0.82 default, so no candidate is recorded -- exactly like a store that
        never had E4 at all."""
        key = {"entity_id": "pat_testley", "predicate_canonical": "works_at", "attribute": "works_at",
              "qualifiers_hash": "", "qualifiers": {}, "entity_name": "Pat Testley",
              "owner": "assistant", "domain": "general"}
        _assert_fact(self.core, key, "Pat Testley works at Acme Fake Co", source_event="e1")
        key2 = dict(key, qualifiers_hash="v2")
        _assert_fact(self.core, key2, "Pat Testley works at Beta Fake Inc", source_event="e2")
        facts = self.core.store.query_beliefs("facts", "entity_id=?", ("pat_testley",), limit=10)
        for f in facts:
            self.assertEqual(self.core.store.get_supersede_chain(f["belief_id"]), [])

    def test_global_fallback_when_no_same_subject_candidate(self):
        """No same-subject items exist for the second entity at all, so the
        NN search falls back to a global scan across this owner/domain's other
        active facts. Uses a pair whose hashing-mode similarity (~0.85,
        measured) clears the DEFAULT 0.82 threshold outright -- no override
        needed, so this also doubles as a default-config positive case."""
        key1 = {"entity_id": "acme_fake_co", "predicate_canonical": "hq_location",
                "attribute": "hq_location", "qualifiers_hash": "", "qualifiers": {},
                "entity_name": "Acme Fake Co", "owner": "assistant", "domain": "general"}
        _assert_fact(self.core, key1, "Acme Fake Co is headquartered in Springfield",
                    source_event="e1")
        key2 = {"entity_id": "acme_fake_co_ltd", "predicate_canonical": "hq_location",
                "attribute": "hq_location", "qualifiers_hash": "", "qualifiers": {},
                "entity_name": "Acme Fake Co Ltd", "owner": "assistant", "domain": "general"}
        _assert_fact(self.core, key2, "Acme Fake Co is headquartered in Shelbyville",
                    source_event="e2")

        new_fact = self.core.store.query_beliefs(
            "facts", "entity_id=?", ("acme_fake_co_ltd",), limit=1)[0]
        chain = self.core.store.get_supersede_chain(new_fact["belief_id"])
        self.assertEqual(len(chain), 2)
        self.assertIn("Springfield", chain[0]["value"])
        self.assertIn("Shelbyville", chain[1]["value"])


class TestSupersedeCandidateNoEmbedder(unittest.TestCase):
    """§issue-8 shared constraint: the embedder may be absent -- no-op, no error."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = MemoryStore(str(Path(self.tmp) / "chronicle.db"))
        self.reducer = Reducer(self.store, embedder=None, cfg=None)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_embedder_no_error_no_candidate(self):
        key = {"entity_id": "pat_testley", "predicate_canonical": "works_at",
              "attribute": "works_at", "qualifiers_hash": "", "qualifiers": {},
              "entity_name": "Pat Testley"}
        ev1 = {"event_id": "ev1", "owner": "assistant", "domain": "general", "trust_level": 3,
              "recorded_at": "2026-01-01T00:00:00.000Z"}
        self.reducer._on_asserted({**ev1, "type": "asserted",
                                   "payload": {"kind": "fact", "key": key,
                                               "body": "Acme Fake Co", "confidence": 0.8,
                                               "source_event": "ev1", "source_type": "user_direct",
                                               "domain": "general"}})
        key2 = dict(key, qualifiers_hash="v2")
        ev2 = {"event_id": "ev2", "owner": "assistant", "domain": "general", "trust_level": 3,
              "recorded_at": "2026-02-01T00:00:00.000Z"}
        self.reducer._on_asserted({**ev2, "type": "asserted",
                                   "payload": {"kind": "fact", "key": key2,
                                               "body": "Beta Fake Inc", "confidence": 0.8,
                                               "source_event": "ev2", "source_type": "user_direct",
                                               "domain": "general"}})
        rows = self.store._conn().execute("SELECT COUNT(*) c FROM supersede_candidates").fetchone()
        self.assertEqual(rows["c"], 0)
        facts = self.store.query_beliefs("facts", "entity_id=?", ("pat_testley",), limit=10)
        self.assertEqual(len(facts), 2)


if __name__ == "__main__":
    unittest.main()
