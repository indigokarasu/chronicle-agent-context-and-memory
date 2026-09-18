"""
Chronicle — what goes into EVERY system prompt.

The provider's static block rides in every agent's system prompt, scheduled
jobs included, whatever the turn is about. On the production store its
"CRITICAL" section was a prescription refill, a lab visit and a past
procedure ("Quest Diagnostics" is critical by its name: medical facts are
critical so they never decay), and its "USER PROFILE" an attended birthday.
Only safety facts belong there always; a medical fact never decays and
surfaces when a message is about it. The profile is who the user is, not what
happened to them.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore

P = "default"


class TestTheStaticBlock(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="static_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("s-static", principal_id=P)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def fact(self, attribute, predicate, value):
        self.core.capture.append("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "attribute": attribute, "predicate_canonical": predicate,
                    "qualifiers_hash": "", "qualifiers": {}, "owner": P, "domain": "user"},
            "body": value, "confidence": 0.9, "source_event": "test", "source_type": "user_direct"},
            actor="user", trust_level=3)
        self.core.process_pending()

    def test_safety_is_always_there_medical_history_is_not(self):
        self.fact("allergy", "allergic_to", "severe penicillin allergy, carries an epipen")
        self.fact("health_event", "health_event", "Zorbaxol prescription refill ordered for Pat Testley")
        self.fact("had_appointment", "had_appointment", "Fake Diagnostics lab visit — 2026-01-14")
        crit = dict(self.core.store._conn().execute(
            "SELECT attribute, criticality_reason FROM facts WHERE criticality='critical'").fetchall())
        self.assertEqual(crit.get("allergy"), "safety", "setup: the allergy is a safety fact")
        self.assertEqual(crit.get("health_event"), "medical", "setup: the refill is a medical fact")
        block = self.core.retrieval.static_block(P)
        self.assertIn("penicillin", block)
        self.assertNotIn("Zorbaxol", block)
        self.assertNotIn("Fake Diagnostics", block)

    def test_the_profile_is_who_not_what_happened(self):
        self.fact("city", "lives_in", "Riverton")
        self.fact("attended_event", "attended_event", "Robin Placeholder's birthday — 2025-03-06")
        self.fact("purchased", "purchased", "SunFake 9000 from Acme Fake Co")
        block = self.core.retrieval.static_block(P)
        self.assertIn("city: Riverton", block)
        self.assertNotIn("birthday", block)
        self.assertNotIn("SunFake 9000", block)


if __name__ == "__main__":
    unittest.main()
