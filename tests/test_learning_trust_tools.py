"""
Chronicle — tests for learning.py, trust.py, and tools.py (§10, §22, §23).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.trust import (
    ceiling, base_confidence, raw_confidence,
    clamp_to_ceiling, bucket_of, Calibrator, confidence_summary,
)
from engine.config import TRUST_CEILING, CONFIDENCE_BASE
from engine.errors import E_LEARN_BOUND


# ---------------------------------------------------------------------------
# trust.py
# ---------------------------------------------------------------------------
class TestTrustCeiling(unittest.TestCase):
    def test_ceiling_level_0(self):
        self.assertEqual(ceiling(0), 0.40)

    def test_ceiling_level_4(self):
        self.assertEqual(ceiling(4), 1.00)

    def test_ceiling_unknown_level(self):
        self.assertEqual(ceiling(99), 0.75)  # default

    def test_ceiling_negative(self):
        self.assertEqual(ceiling(-1), 0.75)  # -1 not in TRUST_CEILING, default 0.75


class TestBaseConfidence(unittest.TestCase):
    def test_user_direct(self):
        self.assertEqual(base_confidence("user_direct"), 0.85)

    def test_unknown_source(self):
        self.assertEqual(base_confidence("unknown_source"), 0.60)

    def test_inference(self):
        self.assertEqual(base_confidence("inference"), 0.60)


class TestRawConfidence(unittest.TestCase):
    def test_base_only(self):
        r = raw_confidence("user_direct")
        self.assertAlmostEqual(r, 0.85)

    def test_with_confirmations(self):
        r = raw_confidence("user_direct", confirm_count=3)
        self.assertAlmostEqual(r, 0.85 + 0.05 * 3)

    def test_confirm_capped_at_5(self):
        r5 = raw_confidence("user_direct", confirm_count=5)
        r10 = raw_confidence("user_direct", confirm_count=10)
        self.assertEqual(r5, r10)

    def test_with_contradictions(self):
        r = raw_confidence("user_direct", contradiction_count=1)
        self.assertAlmostEqual(r, 0.85 - 0.10)

    def test_clamped_to_zero(self):
        r = raw_confidence("web_retrieval", contradiction_count=10)
        self.assertGreaterEqual(r, 0.0)

    def test_clamped_to_one(self):
        r = raw_confidence("user_direct", confirm_count=100)
        self.assertLessEqual(r, 1.0)


class TestClampToCeiling(unittest.TestCase):
    def test_below_ceiling_unchanged(self):
        self.assertAlmostEqual(clamp_to_ceiling(0.3, 0), 0.3)

    def test_above_ceiling_clamped(self):
        self.assertAlmostEqual(clamp_to_ceiling(0.95, 0), 0.40)

    def test_corroborated_raises_band(self):
        # trust_level=2 ceiling=0.75, corroborated → level=3 ceiling=0.90
        self.assertAlmostEqual(clamp_to_ceiling(0.85, 2, corroborated=True), 0.85)
        self.assertAlmostEqual(clamp_to_ceiling(0.85, 2, corroborated=False), 0.75)

    def test_corroborated_capped_at_4(self):
        # trust_level=4 + corroborated stays at 4
        self.assertAlmostEqual(clamp_to_ceiling(1.0, 4, corroborated=True), 1.0)


class TestBucketOf(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(bucket_of(0.0), "0.0")

    def test_mid(self):
        self.assertEqual(bucket_of(0.5), "0.5")

    def test_near_one(self):
        self.assertEqual(bucket_of(0.99), "0.9")

    def test_exactly_one(self):
        self.assertEqual(bucket_of(1.0), "0.9")


class TestCalibrator(unittest.TestCase):
    def setUp(self):
        from engine.store import MemoryStore
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.cal = Calibrator(self.store, min_obs=2)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_identity_with_no_obs(self):
        # No calibration data → returns raw
        self.assertAlmostEqual(self.cal.calibrate(0.8, "user_direct"), 0.8)

    def test_identity_below_min_obs(self):
        # Below min_obs → identity (no calibration obs stored)
        # MemoryStore has get_calibration_obs but not upsert_calibration_obs
        # so we just verify identity behavior with empty obs
        self.assertAlmostEqual(self.cal.calibrate(0.8, "user_direct"), 0.8)


class TestConfidenceSummary(unittest.TestCase):
    def test_summary_shape(self):
        belief = {
            "provenance": json.dumps({"source_type": "user_direct"}),
            "confirm_count": 1,
            "contradiction_count": 0,
            "last_confirmed_at": "2026-01-01T00:00:00Z",
            "trust_level": 4,
        }
        s = confidence_summary(belief, 0.95)
        self.assertAlmostEqual(s["score"], 0.95)
        self.assertEqual(s["sources"], ["user_direct"])
        self.assertTrue(s["user_confirmed"])
        self.assertFalse(s["ever_contradicted"])
        self.assertEqual(s["trust_level"], 4)

    def test_summary_with_no_provenance(self):
        belief = {"provenance": None, "confirm_count": 0, "contradiction_count": 1}
        s = confidence_summary(belief, 0.5)
        self.assertEqual(s["sources"], ["unknown"])
        self.assertFalse(s["user_confirmed"])
        self.assertTrue(s["ever_contradicted"])


# ---------------------------------------------------------------------------
# learning.py
# ---------------------------------------------------------------------------
class TestLearningLoop(unittest.TestCase):
    def setUp(self):
        from engine.store import MemoryStore
        from engine.config import Config
        from engine.reducer import Reducer
        from engine.capture import CaptureEngine
        from engine.core import ChronicleCore

        self.home = tempfile.mkdtemp()
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("s1", principal_id="assistant")
        self.learning = self.core.learning

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_max_active_from_config(self):
        self.assertGreater(self.learning.max_active, 0)

    def test_max_mag_from_config(self):
        self.assertGreater(self.learning.max_mag, 0)

    def test_mutable_dimensions_non_empty(self):
        self.assertGreater(len(self.learning.mutable), 0)

    def test_propose_policy_valid(self):
        # rrf_weights is in the default mutable set
        version = self.learning.propose_policy("rrf_weights", {"fts": 0.1, "vector": 0.1})  # within magnitude cap
        self.assertTrue(version.startswith("rrf_weights-"))

    def test_propose_policy_immutable_dimension_raises(self):
        with self.assertRaises(E_LEARN_BOUND):
            self.learning.propose_policy("nonexistent_dim", {"x": 0.1})

    def test_propose_policy_exceeds_magnitude_raises(self):
        with self.assertRaises(E_LEARN_BOUND):
            self.learning.propose_policy("rrf_weights", {"fts": 0.99})

    def test_activate_policy_not_beats_champion_raises(self):
        version = self.learning.propose_policy("rrf_weights", {"fts": 0.1})  # within magnitude cap
        with self.assertRaises(E_LEARN_BOUND):
            self.learning.activate_policy(version, beats_champion=False)

    def test_record_outcome_no_belief_silent(self):
        # Should not raise for nonexistent belief_id
        self.learning.record_outcome("nonexistent", used=True)

    def test_auto_disable_low_precision_rules_no_crash(self):
        # No rules in fresh store → should not raise
        self.learning.auto_disable_low_precision_rules()


# ---------------------------------------------------------------------------
# tools.py
# ---------------------------------------------------------------------------
class TestTools(unittest.TestCase):
    def setUp(self):
        from engine.core import ChronicleCore
        self.home = tempfile.mkdtemp()
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("s1", principal_id="assistant")
        self.tools = self.core.tools

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_schemas_returns_list(self):
        schemas = self.tools.schemas()
        self.assertIsInstance(schemas, list)
        self.assertGreater(len(schemas), 0)

    def test_schemas_all_have_name_and_description(self):
        for s in self.tools.schemas():
            self.assertIn("name", s)
            self.assertIn("description", s)
            self.assertIn("parameters", s)
            self.assertTrue(s["name"].startswith("chronicle_"))

    def test_dispatch_unknown_tool(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_nonexistent", {}))
        self.assertIn("error", result)

    def test_dispatch_without_prefix(self):
        result = json.loads(self.tools.dispatch("assistant", "nonexistent", {}))
        self.assertIn("error", result)

    def test_remember_fact(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_remember", {
            "kind": "fact", "content": "test fact", "entity": "user", "attribute": "test"
        }))
        self.assertEqual(result["status"], "stored")

    def test_remember_note(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_remember", {
            "kind": "note", "content": "test note"
        }))
        self.assertEqual(result["status"], "stored")

    def test_remember_empty_content(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_remember", {
            "content": ""
        }))
        self.assertIn("error", result)

    def test_search(self):
        self.tools.dispatch("assistant", "chronicle_remember", {
            "kind": "fact", "content": "the operator lives in Denver", "entity": "user", "attribute": "city"
        })
        self.core.process_pending()
        result = json.loads(self.tools.dispatch("assistant", "chronicle_search", {
            "query": "Denver"
        }))
        self.assertIn("results", result)

    def test_answer(self):
        self.tools.dispatch("assistant", "chronicle_remember", {
            "kind": "fact", "content": "My name is the operator", "entity": "user", "attribute": "name"
        })
        self.core.process_pending()
        result = json.loads(self.tools.dispatch("assistant", "chronicle_answer", {
            "query": "what is my name"
        }))
        self.assertIn("tier", result)

    def test_ask_about(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_ask_about", {
            "entity": "user"
        }))
        self.assertIn("facts", result)

    def test_timeline(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_timeline", {}))
        self.assertIn("timeline", result)

    def test_list_directives(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_list_directives", {}))
        self.assertIn("directives", result)

    def test_list_contradictions(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_list_contradictions", {}))
        self.assertIn("contradictions", result)

    def test_list_principals(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_list_principals", {}))
        self.assertIn("principals", result)

    def test_list_derivation_rules(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_list_derivation_rules", {}))
        self.assertIn("rules", result)

    def test_embedding_status(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_embedding_status", {}))
        self.assertIn("mode", result)

    def test_correct(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_correct", {
            "belief_id": "fake_id", "new_value": "new"
        }))
        self.assertEqual(result["status"], "corrected")

    def test_forget(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_forget", {
            "belief_id": "fake_id"
        }))
        self.assertEqual(result["status"], "retracted")

    def test_set_acl_not_found(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_set_acl", {
            "belief_id": "nonexistent", "visibility": "private"
        }))
        self.assertIn("error", result)

    def test_set_agent_privacy(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_set_agent_privacy", {
            "agent": "test_agent", "private": True
        }))
        self.assertEqual(result["status"], "set")

    def test_reflect(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_reflect", {
            "situation": "test", "action": "test", "outcome": "test", "lesson": "test"
        }))
        self.assertEqual(result["status"], "reflected")

    def test_remember_goal(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_remember_goal", {
            "goal": "learn Python"
        }))
        self.assertEqual(result["status"], "ok")

    def test_active_goals(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_active_goals", {}))
        self.assertIn("goals", result)

    def test_note_informed(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_note_informed", {
            "proposition": "user was told about backups"
        }))
        self.assertEqual(result["status"], "noted")

    def test_unmerge(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_unmerge", {
            "entity_id": "some_entity"
        }))
        self.assertEqual(result["status"], "unmerged")

    def test_set_rule_enabled(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_set_rule_enabled", {
            "rule_id": "rule_1", "enabled": False
        }))
        self.assertEqual(result["status"], "ok")

    def test_list_capabilities(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_list_capabilities", {}))
        self.assertIn("capabilities", result)

    def test_history(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_history", {
            "belief_id": "fake_id"
        }))
        self.assertIn("history", result)

    def test_get_context(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_get_context", {
            "hint": "user preferences"
        }))
        self.assertIn("context", result)

    def test_explain(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_explain", {
            "belief_id": "fake_id"
        }))
        # Should return something (possibly error for nonexistent belief)
        self.assertIsInstance(result, dict)

    def test_withdraw_consent(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_withdraw_consent", {
            "belief_id": "fake_id"
        }))
        self.assertEqual(result["status"], "unlearned")

    def test_verify(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_verify", {
            "belief_id": "fake_id"
        }))
        self.assertEqual(result["status"], "queued")

    def test_grant_read(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_grant_read", {
            "belief_id": "fake_id", "principal": "research"
        }))
        self.assertEqual(result["status"], "granted")

    def test_revoke_read(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_revoke_read", {
            "belief_id": "fake_id", "principal": "research"
        }))
        self.assertEqual(result["status"], "revoked")

    def test_plan_context(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_plan_context", {
            "goal": "organize files"
        }))
        self.assertIsInstance(result, dict)

    def test_what_user_knows(self):
        result = json.loads(self.tools.dispatch("assistant", "chronicle_what_user_knows", {
            "topic": "backups"
        }))
        self.assertIn("knows", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
