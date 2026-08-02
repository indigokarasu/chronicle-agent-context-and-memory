"""
Chronicle — tests for forgetting.py, gitmirror.py, and federation.py (§14, §20, §26).
"""

import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.federation import (
    E_AUTHORITY_UNAVAILABLE,
    PREDICATE_CAPABILITY,
    CapabilityProvider,
    CapabilityRegistry,
)
from engine.forgetting import _LADDER, ForgettingEngine, _age_days


# ---------------------------------------------------------------------------
# forgetting.py
# ---------------------------------------------------------------------------
class TestAgeDays(unittest.TestCase):
    def test_iso_string(self):
        now = datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc)
        ts = "2026-01-01T00:00:00+00:00"
        self.assertAlmostEqual(_age_days(ts, now), 14.0, places=1)

    def test_z_suffix(self):
        now = datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc)
        ts = "2026-01-01T00:00:00Z"
        self.assertAlmostEqual(_age_days(ts, now), 1.0, places=1)

    def test_none_returns_zero(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertEqual(_age_days(None, now), 0.0)

    def test_empty_string_returns_zero(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertEqual(_age_days("", now), 0.0)

    def test_invalid_string_returns_zero(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertEqual(_age_days("not-a-date", now), 0.0)


class TestForgettingLadder(unittest.TestCase):
    def test_ladder_transitions(self):
        self.assertEqual(_LADDER["verbatim"], "gist")
        self.assertEqual(_LADDER["gist"], "parametric_only")
        self.assertEqual(_LADDER["parametric_only"], "tombstone")

    def test_tombstone_has_no_next(self):
        self.assertIsNone(_LADDER.get("tombstone"))


class TestForgettingEngine(unittest.TestCase):
    def setUp(self):
        from engine.config import Config
        from engine.store import MemoryStore

        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.cfg = Config({})
        self.events = []
        self.engine = ForgettingEngine(self.store, self.cfg, self._append)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _append(self, type_, payload, **kw):
        self.events.append({"type": type_, "payload": payload, **kw})

    def test_critical_never_decays(self):
        row = {
            "belief_id": "b1", "criticality": "critical", "salience": "normal",
            "domain": "general", "fidelity": "verbatim",
            "created_at": "2020-01-01T00:00:00+00:00", "last_seen_at": "2020-01-01T00:00:00+00:00",
            "utility": 0.0, "status": "active", "owner": "default",
        }
        self.assertFalse(self.engine._eligible(row, datetime.datetime.now(datetime.timezone.utc), {"normal": 1.0}))

    def test_pinned_never_decays(self):
        row = {
            "belief_id": "b2", "criticality": "normal", "salience": "pinned",
            "domain": "general", "fidelity": "verbatim",
            "created_at": "2020-01-01T00:00:00+00:00", "last_seen_at": "2020-01-01T00:00:00+00:00",
            "utility": 0.0, "status": "active", "owner": "default",
        }
        self.assertFalse(self.engine._eligible(row, datetime.datetime.now(datetime.timezone.utc), {"pinned": 0.0}))

    def test_high_criticality_never_decays(self):
        row = {
            "belief_id": "b3", "criticality": "high", "salience": "normal",
            "domain": "general", "fidelity": "verbatim",
            "created_at": "2020-01-01T00:00:00+00:00", "last_seen_at": "2020-01-01T00:00:00+00:00",
            "utility": 0.0, "status": "active", "owner": "default",
        }
        self.assertFalse(self.engine._eligible(row, datetime.datetime.now(datetime.timezone.utc), {"normal": 1.0}))

    def test_user_domain_no_auto_decay(self):
        row = {
            "belief_id": "b4", "criticality": "normal", "salience": "normal",
            "domain": "user", "fidelity": "verbatim",
            "created_at": "2020-01-01T00:00:00+00:00", "last_seen_at": "2020-01-01T00:00:00+00:00",
            "utility": 0.0, "status": "active", "owner": "default",
        }
        # User domain auto_decay defaults to False
        self.assertFalse(self.engine._eligible(row, datetime.datetime.now(datetime.timezone.utc), {"normal": 1.0}))

    def test_decay_sweep_empty_store(self):
        self.engine.decay_sweep()
        self.assertEqual(len(self.events), 0)

    def test_unlearn_nonexistent_silent_first(self):
        # Should not raise for nonexistent belief_id
        self.engine.unlearn("nonexistent", "test")

    def test_find_belief_nonexistent(self):
        # Already tested above; this tests store-level find_belief
        row = self.store.find_belief("nonexistent")
        self.assertIsNone(row)

    def test_unlearn_emits_forbidden_and_retracted(self):
        # Directly insert a fact row (bypassing full capture), then unlearn
        import uuid
        bid = str(uuid.uuid4())
        self.store.upsert_belief("facts", {
            "belief_id": bid, "entity_id": "user",
            "predicate_canonical": "test", "attribute": "test",
            "qualifiers_hash": "", "provenance": "{}",
            "value": "secret data", "status": "active",
            "owner": "default", "domain": "user", "fidelity": "verbatim",
            "salience": "normal", "confidence": 0.9, "criticality": "normal",
            "confirm_count": 0, "contradiction_count": 0, "utility": 0.0,
        })
        self.engine.unlearn(bid, "consent_withdrawn")
        types = [e["type"] for e in self.events]
        self.assertIn("forbidden", types)
        self.assertIn("retracted", types)


# ---------------------------------------------------------------------------
# federation.py
# ---------------------------------------------------------------------------
class TestPredicateCapability(unittest.TestCase):
    def test_phone_maps_to_contacts(self):
        self.assertEqual(PREDICATE_CAPABILITY["phone"], "contacts")

    def test_email_maps_to_contacts(self):
        self.assertEqual(PREDICATE_CAPABILITY["email"], "contacts")

    def test_unknown_predicate(self):
        self.assertIsNone(PREDICATE_CAPABILITY.get("nonexistent"))


class TestCapabilityProvider(unittest.TestCase):
    def test_default_available(self):
        p = CapabilityProvider()
        self.assertTrue(p.is_available())

    def test_resolve_raises(self):
        p = CapabilityProvider()
        with self.assertRaises(NotImplementedError):
            p.resolve("ref")

    def test_query_returns_empty(self):
        p = CapabilityProvider()
        self.assertEqual(p.query({}), [])


class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self):
        from engine.config import Config
        from engine.store import MemoryStore

        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.cfg = Config({})
        self.registry = CapabilityRegistry(self.store, self.cfg)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_register_provider(self):
        class FakeProvider(CapabilityProvider):
            name = "fake"
            capability = "contacts"

        self.registry.register(FakeProvider())
        self.assertIn("contacts", self.registry.providers)

    def test_unregister_provider(self):
        class FakeProvider(CapabilityProvider):
            name = "fake"
            capability = "contacts"

        self.registry.register(FakeProvider())
        self.registry.unregister("contacts")
        self.assertNotIn("contacts", self.registry.providers)

    def test_capability_for_predicate_no_provider(self):
        # No provider registered → returns None (Chronicle keeps the belief)
        result = self.registry.capability_for_predicate("phone")
        self.assertIsNone(result)

    def test_capability_for_predicate_with_provider(self):
        class FakeProvider(CapabilityProvider):
            name = "fake"
            capability = "contacts"
        self.registry.register(FakeProvider())
        result = self.registry.capability_for_predicate("phone")
        self.assertEqual(result, "contacts")

    def test_capability_for_unknown_predicate(self):
        result = self.registry.capability_for_predicate("nonexistent")
        self.assertIsNone(result)

    def test_resolve_no_provider_raises(self):
        with self.assertRaises(E_AUTHORITY_UNAVAILABLE):
            self.registry.resolve("contacts", "some_ref")

    def test_list_capabilities(self):
        caps = self.registry.list_capabilities()
        self.assertIsInstance(caps, list)

    def test_route_delegate(self):
        class FakeProvider(CapabilityProvider):
            name = "fake"
            capability = "contacts"
        self.registry.register(FakeProvider())
        pid = self.registry.route_delegate(
            capability="contacts", entity_id="user",
            predicate="phone", value="555-1234", owner="default"
        )
        self.assertIsNotNone(pid)

    def test_bind_with_no_pins(self):
        # Should not raise
        self.registry.bind()


if __name__ == "__main__":
    unittest.main(verbosity=2)
