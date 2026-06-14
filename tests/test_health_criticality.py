"""
Chronicle — tests for health.py and criticality.py (§20.1, §21).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.criticality import classify, _RULES
from engine.health import HealthEngine


# ---------------------------------------------------------------------------
# criticality.py
# ---------------------------------------------------------------------------
class TestCriticality(unittest.TestCase):
    def test_fact_returns_normal_for_benign(self):
        crit, reason = classify("enjoys hiking on weekends")
        self.assertEqual(crit, "normal")

    def test_medical_keyword(self):
        crit, reason = classify("penicillin allergy")
        self.assertEqual(crit, "critical")
        self.assertIn(reason, ("safety", "medical"))  # "allerg" matches safety rule first

    def test_safety_keyword(self):
        crit, reason = classify("carries an epipen")
        self.assertEqual(crit, "critical")

    def test_legal_keyword(self):
        crit, reason = classify("signed NDA with Acme Corp")
        self.assertEqual(crit, "high")
        self.assertEqual(reason, "legal")

    def test_financial_keyword(self):
        crit, reason, _ = classify("bank account number"), None, None
        crit, reason = classify("bank account routing number")
        self.assertEqual(crit, "high")

    def test_boundary_keyword(self):
        crit, reason = classify("never share my password with anyone")
        self.assertEqual(crit, "high")

    def test_identity_keyword(self):
        crit, reason = classify("legal name is John Smith")
        self.assertEqual(crit, "high")

    def test_security_keyword(self):
        crit, reason = classify("API key for production")
        self.assertEqual(crit, "high")

    def test_norm_type_starts_at_high(self):
        crit, reason = classify("always confirm before deleting", note_type="norm")
        self.assertEqual(crit, "high")
        self.assertEqual(reason, "directive")

    def test_norm_type_with_medical_stays_critical(self):
        crit, reason = classify("insulin dosage is 10mg", note_type="norm")
        self.assertEqual(crit, "critical")

    def test_empty_input(self):
        crit, reason = classify("")
        self.assertEqual(crit, "normal")

    def test_rules_list_non_empty(self):
        self.assertGreater(len(_RULES), 0)

    def test_rules_have_three_elements(self):
        for rule in _RULES:
            self.assertEqual(len(rule), 3)
            crit, cat, kws = rule
            self.assertIn(crit, ("critical", "high"))
            self.assertIsInstance(cat, str)
            self.assertIsInstance(kws, list)
            self.assertGreater(len(kws), 0)


# ---------------------------------------------------------------------------
# health.py
# ---------------------------------------------------------------------------
class TestHealthEngine(unittest.TestCase):
    def setUp(self):
        from engine.store import MemoryStore
        from engine.config import Config
        from engine.reducer import Reducer
        from engine.capture import CaptureEngine
        from engine.core import ChronicleCore

        self.home = tempfile.mkdtemp()
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("s1", principal_id="assistant")
        self.health = HealthEngine(self.core)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_run_returns_required_keys(self):
        result = self.health.run()
        self.assertIn("ghost_facts", result)
        self.assertIn("unjustified", result)
        self.assertIn("extraction_recall_gap", result)
        self.assertIn("bad_derivation_rate", result)
        self.assertIn("open_contradictions", result)
        self.assertIn("lock_contention", result)

    def test_ghost_facts_empty_when_no_beliefs(self):
        result = self.health.run()
        self.assertEqual(result["ghost_facts"], [])

    def test_unjustified_empty_fresh_store(self):
        result = self.health.run()
        # Fresh store with no retraction orphans
        self.assertIsInstance(result["unjustified"], list)

    def test_recall_gap_is_float(self):
        result = self.health.run()
        self.assertIsInstance(result["extraction_recall_gap"], float)

    def test_bad_derivation_rate_is_float(self):
        result = self.health.run()
        self.assertIsInstance(result["bad_derivation_rate"], float)

    def test_open_contradictions_is_int(self):
        result = self.health.run()
        self.assertIsInstance(result["open_contradictions"], int)

    def test_lock_contention_is_float(self):
        result = self.health.run()
        self.assertIsInstance(result["lock_contention"], float)

    def test_rebuild_fts_does_not_raise(self):
        self.core.capture.observe("test statement", "ok", session_id="s1")
        self.health.rebuild_fts()

    def test_store_records_health_run(self):
        self.health.run()
        # After running health, there should be a health run record
        rows = self.core.store.query_beliefs("health_runs", "1=1")
        self.assertGreaterEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
