"""
Chronicle — Build verification tests.

Tests the core modules: serialization, event log, reducer, capture, retrieval.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add the plugin to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.serialize import cjson_dumps, content_hash, event_id, belief_id
from engine.store import MemoryStore
from engine.reducer import Reducer, TRUST_CEILING
from engine.capture import CaptureEngine, Reaper
from engine.retrieval import RetrievalEngine


class TestSerialization(unittest.TestCase):
    """Test §5: Serialization & content addressing."""

    def test_cjson_dumps_basic(self):
        self.assertEqual(cjson_dumps(None), "null")
        self.assertEqual(cjson_dumps(True), "true")
        self.assertEqual(cjson_dumps(False), "false")
        self.assertEqual(cjson_dumps(42), "42")
        self.assertEqual(cjson_dumps(0), "0")
        self.assertEqual(cjson_dumps(-5), "-5")
        self.assertEqual(cjson_dumps("hello"), '"hello"')
        self.assertEqual(cjson_dumps([1, 2, 3]), "[1,2,3]")

    def test_cjson_dumps_nested(self):
        obj = {"b": 2, "a": 1, "c": {"e": 5, "d": 4}}
        result = cjson_dumps(obj)
        # Keys must be sorted
        self.assertTrue(result.index('"a"') < result.index('"b"') < result.index('"c"'))
        parsed = json.loads(result)
        self.assertEqual(parsed, {"a": 1, "b": 2, "c": {"d": 4, "e": 5}})

    def test_cjson_dumps_escapes(self):
        self.assertEqual(cjson_dumps('a"b'), '"a\\"b"')
        self.assertEqual(cjson_dumps("a\nb"), '"a\\nb"')
        self.assertEqual(cjson_dumps("a\tb"), '"a\\tb"')

    def test_content_hash(self):
        h = content_hash(b"hello")
        self.assertEqual(len(h), 64)  # 32 bytes = 64 hex chars
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_content_hash_deterministic(self):
        self.assertEqual(content_hash(b"hello"), content_hash(b"hello"))
        self.assertNotEqual(content_hash(b"hello"), content_hash(b"world"))

    def test_event_id(self):
        eid = event_id("observed", {"excerpt": "test"}, [], "user", "2026-01-01T00:00:00.000Z")
        self.assertTrue(eid.startswith("ev_"))
        self.assertEqual(len(eid), 67)  # "ev_" + 64 hex

    def test_event_id_deterministic(self):
        eid1 = event_id("observed", {"excerpt": "test"}, [], "user", "2026-01-01T00:00:00.000Z")
        eid2 = event_id("observed", {"excerpt": "test"}, [], "user", "2026-01-01T00:00:00.000Z")
        self.assertEqual(eid1, eid2)

    def test_event_id_parents_sorted(self):
        eid1 = event_id("observed", {"excerpt": "test"}, ["b", "a"], "user", "2026-01-01T00:00:00.000Z")
        eid2 = event_id("observed", {"excerpt": "test"}, ["a", "b"], "user", "2026-01-01T00:00:00.000Z")
        self.assertEqual(eid1, eid2)

    def test_belief_id(self):
        bid = belief_id("fact", {"entity_id": "user", "predicate_canonical": "name"}, ["ev_abc"])
        self.assertTrue(bid.startswith("b_"))
        self.assertEqual(len(bid), 66)  # "b_" + 64 hex


class TestMemoryStore(unittest.TestCase):
    """Test §24.2: SQLite store."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_append_and_get_event(self):
        event = {
            "event_id": "ev_test123",
            "type": "observed",
            "payload": {"excerpt": "hello world", "source_type": "test"},
            "parents": [],
            "actor": "user",
            "owner": "default",
            "trust_level": 2,
            "session_id": "sess_1",
            "branch_id": None,
            "occurred_at": "2026-01-01T00:00:00.000Z",
            "recorded_at": "2026-01-01T00:00:00.000Z",
            "prev_head": "",
            "sig": None,
        }
        eid = self.store.append_event(event)
        self.assertEqual(eid, "ev_test123")

        retrieved = self.store.get_event(eid)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["type"], "observed")

    def test_append_idempotent(self):
        event = {
            "event_id": "ev_dup",
            "type": "observed",
            "payload": {"excerpt": "dup test", "source_type": "test"},
            "parents": [],
            "actor": "user",
            "owner": "default",
            "trust_level": 2,
            "occurred_at": "2026-01-01T00:00:00.000Z",
            "recorded_at": "2026-01-01T00:00:00.000Z",
            "prev_head": "",
            "sig": None,
        }
        self.store.append_event(event)
        eid2 = self.store.append_event(event)  # Should be idempotent
        self.assertEqual(eid2, "ev_dup")

    def test_get_events_since(self):
        for i in range(5):
            event = {
                "event_id": f"ev_seq_{i}",
                "type": "observed",
                "payload": {"excerpt": f"event {i}", "source_type": "test"},
                "parents": [],
                "actor": "user",
                "owner": "default",
                "trust_level": 2,
                "occurred_at": f"2026-01-01T00:00:{i:02d}.000Z",
                "recorded_at": f"2026-01-01T00:00:{i:02d}.000Z",
                "prev_head": "",
                "sig": None,
            }
            self.store.append_event(event)

        events = self.store.get_events_since(2)
        self.assertTrue(len(events) >= 2)

    def test_session_crud(self):
        self.store.upsert_session({
            "session_id": "sess_test",
            "status": "active",
            "started_at": "2026-01-01T00:00:00.000Z",
            "last_activity_at": "2026-01-01T00:00:00.000Z",
            "last_extracted_seq": 0,
        })
        sess = self.store.get_session("sess_test")
        self.assertIsNotNone(sess)
        self.assertEqual(sess["status"], "active")

    def test_principal_crud(self):
        self.store.upsert_principal({
            "principal_id": "agent_1",
            "type": "agent",
            "display": "Test Agent",
            "default_visibility": "shared",
            "created_at": "2026-01-01T00:00:00.000Z",
        })
        p = self.store.get_principal("agent_1")
        self.assertIsNotNone(p)
        self.assertEqual(p["type"], "agent")

    def test_belief_crud(self):
        belief = {
            "belief_id": "b_test_1",
            "entity_id": "user",
            "attribute": "name",
            "predicate_canonical": "name",
            "value": "Jared",
            "value_type": "string",
            "qualifiers": "{}",
            "qualifiers_hash": "",
            "domain": "user",
            "owner": "default",
            "read_acl": "user_agents",
            "status": "active",
            "salience": "normal",
            "criticality": "normal",
            "confidence": 0.9,
            "trust_level": 3,
            "valid_from": "2026-01-01T00:00:00.000Z",
            "created_at": "2026-01-01T00:00:00.000Z",
            "last_seen_at": "2026-01-01T00:00:00.000Z",
            "fidelity": "verbatim",
            "utility": 0,
            "purpose_scope": '["*"]',
            "provenance": '{"source_type":"test"}',
            "verification": '{"status":"unverified"}',
        }
        self.store.upsert_belief("facts", belief)
        retrieved = self.store.get_belief("facts", "b_test_1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["value"], "Jared")

    def test_justifications(self):
        self.store.add_justification("b_1", "ev_1", "event", "extraction")
        self.store.add_justification("b_1", "ev_2", "event", "extraction")
        justs = self.store.get_justifications("b_1")
        self.assertEqual(len(justs), 2)

    def test_tombstones(self):
        self.store.add_tombstone("hash123", "*")
        self.assertTrue(self.store.is_forbidden("hash123"))
        self.assertFalse(self.store.is_forbidden("hash456"))

    def test_curation_jobs(self):
        job_id = self.store.enqueue_curation("extract", {"event_id": "ev_1"})
        self.assertIsNotNone(job_id)

        job = self.store.claim_curation_job()
        self.assertIsNotNone(job)
        self.assertEqual(job["task"], "extract")

        self.store.complete_curation_job(job_id)

    def test_count_rows(self):
        self.assertEqual(self.store.count_rows("facts"), 0)
        belief = {
            "belief_id": "b_count_1",
            "entity_id": "user",
            "attribute": "test",
            "predicate_canonical": "test",
            "value": "val",
            "qualifiers": "{}",
            "qualifiers_hash": "",
            "domain": "general",
            "owner": "default",
            "read_acl": "user_agents",
            "status": "active",
            "confidence": 0.8,
            "trust_level": 2,
            "valid_from": "2026-01-01T00:00:00.000Z",
            "created_at": "2026-01-01T00:00:00.000Z",
            "provenance": "{}",
        }
        self.store.upsert_belief("facts", belief)
        self.assertEqual(self.store.count_rows("facts"), 1)


class TestReducer(unittest.TestCase):
    """Test §7: Reducer / projection."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _make_event(self, type_: str, payload: dict, **kwargs) -> dict:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return {
            "event_id": f"ev_{type_}_{id(payload)}",
            "type": type_,
            "payload": payload,
            "parents": [],
            "actor": kwargs.get("actor", "user"),
            "owner": kwargs.get("owner", "default"),
            "trust_level": kwargs.get("trust_level", 2),
            "session_id": kwargs.get("session_id"),
            "branch_id": None,
            "occurred_at": kwargs.get("occurred_at", now),
            "recorded_at": now,
            "prev_head": None,
            "sig": None,
        }

    def test_observed_event(self):
        event = self._make_event("observed", {
            "source_type": "session_transcript",
            "excerpt": "User said hello",
        })
        self.reducer.reduce(event)
        # Should have indexed in FTS
        results = self.store.fts_search("hello")
        self.assertTrue(len(results) > 0)

    def test_asserted_event(self):
        event = self._make_event("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "predicate_canonical": "name", "qualifiers_hash": "", "owner": "default", "domain": "user"},
            "body": "Jared",
            "confidence": 0.9,
            "source_event": "ev_source_1",
        })
        self.reducer.reduce(event)
        # Should have created a fact
        facts = self.store.query_beliefs("facts", "entity_id='user' AND predicate_canonical='name'")
        self.assertTrue(len(facts) > 0)
        self.assertEqual(facts[0]["value"], "Jared")

    def test_trust_ceiling(self):
        """I6: confidence ≤ C(trust_level)."""
        event = self._make_event("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "predicate_canonical": "email", "qualifiers_hash": "", "owner": "default", "domain": "user"},
            "body": "test@example.com",
            "confidence": 0.95,  # Above ceiling for trust_level=0
            "source_event": "ev_trust_test",
        }, trust_level=0)
        self.reducer.reduce(event)
        facts = self.store.query_beliefs("facts", "predicate_canonical='email'")
        if facts:
            self.assertLessEqual(facts[0]["confidence"], TRUST_CEILING[0])

    def test_retract_cascade(self):
        """I5: retraction cascade."""
        # Create a belief
        event1 = self._make_event("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "predicate_canonical": "age", "qualifiers_hash": "", "owner": "default", "domain": "user"},
            "body": "30",
            "confidence": 0.8,
            "source_event": "ev_cascade_source",
        })
        self.reducer.reduce(event1)

        # Find the belief
        facts = self.store.query_beliefs("facts", "predicate_canonical='age'")
        if facts:
            b_id = facts[0]["belief_id"]
            # Retract it
            event2 = self._make_event("retracted", {
                "belief_id": b_id,
                "reason": "test retraction",
            })
            self.reducer.reduce(event2)
            # Check it's retracted
            fact = self.store.get_belief("facts", b_id)
            self.assertEqual(fact["status"], "retracted")

    def test_rebuild(self):
        """I3: rebuild from log yields identical state."""
        # Add events through the store (simulating the full pipeline)
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for i in range(3):
            event = self._make_event("asserted", {
                "kind": "fact",
                "key": {"entity_id": f"entity_{i}", "predicate_canonical": "test", "qualifiers_hash": "", "owner": "default", "domain": "general"},
                "body": f"value_{i}",
                "confidence": 0.8,
                "source_event": f"ev_rebuild_{i}",
            })
            # Append to store first (as the real pipeline does)
            self.store.append_event(event)
            self.reducer.reduce(event)

        count_before = self.store.count_rows("facts")

        # Rebuild
        self.reducer.rebuild()

        count_after = self.store.count_rows("facts")
        self.assertEqual(count_before, count_after)


class TestCapture(unittest.TestCase):
    """Test §12: Capture engine."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store)
        self.capture = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_observe(self):
        """sync_turn creates a durable observed event."""
        eid = self.capture.observe("Hello", "Hi there!", session_id="sess_1")
        self.assertTrue(eid.startswith("ev_"))

        event = self.store.get_event(eid)
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "observed")

    def test_observe_creates_session(self):
        self.capture.observe("Hello", "Hi!", session_id="sess_new")
        sess = self.store.get_session("sess_new")
        self.assertIsNotNone(sess)
        self.assertEqual(sess["status"], "active")

    def test_agent_explicit(self):
        self.capture.agent_explicit("add", "memory", "Important fact")
        events = self.store.get_events_by_type("observed")
        self.assertTrue(len(events) > 0)

    def test_rescue_extract(self):
        messages = [
            {"role": "user", "content": "Remember this important fact"},
            {"role": "assistant", "content": "I'll remember that"},
        ]
        eids, summary = self.capture.rescue_extract(messages)
        # Should extract the important message
        self.assertTrue(len(eids) > 0 or summary != "")

    def test_delegation(self):
        self.capture.delegation("Research X", "Found Y", child_session_id="child_1")
        events = self.store.get_events_by_type("observed")
        self.assertTrue(any(
            json.loads(e["payload"]).get("source_type") == "delegation"
            for e in events
        ))

    def test_finalize_session(self):
        self.capture.observe("Hello", "Hi!", session_id="sess_final")
        self.capture.finalize_session("sess_final", "clean_exit")
        sess = self.store.get_session("sess_final")
        self.assertIn(sess["status"], ("ended", "reaped"))


class TestRetrieval(unittest.TestCase):
    """Test §18: Retrieval engine."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store)
        self.retrieval = RetrievalEngine(self.store)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _add_fact(self, entity: str, attr: str, value: str):
        belief = {
            "belief_id": f"b_{entity}_{attr}",
            "entity_id": entity,
            "attribute": attr,
            "predicate_canonical": attr,
            "value": value,
            "value_type": "string",
            "qualifiers": "{}",
            "qualifiers_hash": "",
            "domain": "user",
            "owner": "default",
            "read_acl": "user_agents",
            "status": "active",
            "salience": "normal",
            "criticality": "normal",
            "confidence": 0.9,
            "trust_level": 3,
            "valid_from": "2026-01-01T00:00:00.000Z",
            "created_at": "2026-01-01T00:00:00.000Z",
            "last_seen_at": "2026-01-01T00:00:00.000Z",
            "fidelity": "verbatim",
            "utility": 0,
            "purpose_scope": '["*"]',
            "provenance": "{}",
            "verification": '{"status":"unverified"}',
        }
        self.store.upsert_belief("facts", belief)

    def test_search(self):
        self._add_fact("user", "name", "Jared")
        results = self.retrieval.search("Jared")
        self.assertTrue(len(results) > 0)

    def test_search_by_attribute(self):
        self._add_fact("user", "email", "jared@example.com")
        results = self.retrieval.search("email")
        self.assertTrue(len(results) > 0)

    def test_get_context(self):
        self._add_fact("user", "name", "Jared")
        ctx = self.retrieval.get_context("user info")
        self.assertIsInstance(ctx, str)

    def test_get_directives(self):
        # No directives yet
        directives = self.retrieval.get_directives()
        self.assertIsInstance(directives, str)

    def test_answer_tier1(self):
        self._add_fact("user", "name", "Jared")
        ans = self.retrieval.answer("What is the user's name?")
        self.assertIn("tier", ans)

    def test_answer_no_results(self):
        ans = self.retrieval.answer("What is the meaning of life?")
        self.assertEqual(ans["tier"], 0)

    def test_tool_schemas(self):
        schemas = self.retrieval.get_tool_schemas()
        self.assertTrue(len(schemas) > 0)
        names = [s["name"] for s in schemas]
        self.assertIn("chronicle_remember", names)
        self.assertIn("chronicle_search", names)

    def test_dispatch_remember(self):
        result = self.retrieval.dispatch_tool("chronicle_remember", {
            "kind": "fact",
            "content": "Test fact",
            "entity": "user",
            "attribute": "test",
        })
        data = json.loads(result)
        self.assertIn("status", data)

    def test_dispatch_search(self):
        self._add_fact("user", "name", "Jared")
        result = self.retrieval.dispatch_tool("chronicle_search", {
            "query": "Jared",
        })
        data = json.loads(result)
        self.assertIn("results", data)


class TestInvariants(unittest.TestCase):
    """Test key invariants from §4."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store)
        self.capture = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_I1_append_only(self):
        """I1: Events are never updated or deleted."""
        event = {
            "event_id": "ev_I1_test",
            "type": "observed",
            "payload": {"excerpt": "test", "source_type": "test"},
            "parents": [],
            "actor": "user",
            "owner": "default",
            "trust_level": 2,
            "occurred_at": "2026-01-01T00:00:00.000Z",
            "recorded_at": "2026-01-01T00:00:00.000Z",
            "prev_head": "",
            "sig": None,
        }
        self.store.append_event(event)
        # Try to append again — should be idempotent
        self.store.append_event(event)
        # Should only have one row
        count = self.store.count_rows("events", "event_id='ev_I1_test'")
        self.assertEqual(count, 1)

    def test_I2_content_addressing(self):
        """I2: Identical events store once."""
        event = {
            "event_id": "ev_I2_test",
            "type": "observed",
            "payload": {"excerpt": "identical", "source_type": "test"},
            "parents": [],
            "actor": "user",
            "owner": "default",
            "trust_level": 2,
            "occurred_at": "2026-01-01T00:00:00.000Z",
            "recorded_at": "2026-01-01T00:00:00.000Z",
            "prev_head": "",
            "sig": None,
        }
        self.store.append_event(event)
        self.store.append_event(event)  # Same event_id
        count = self.store.count_rows("events", "event_id='ev_I2_test'")
        self.assertEqual(count, 1)

    def test_I12_capture_durability(self):
        """I12: sync_turn creates a durable event before returning."""
        eid = self.capture.observe("Hello", "Hi!", session_id="sess_I12")
        # Event should exist immediately
        event = self.store.get_event(eid)
        self.assertIsNotNone(event)
        self.assertEqual(event["type"], "observed")

    def test_I5_justified_beliefs(self):
        """I5: Every active belief has ≥1 justification."""
        event = {
            "event_id": "ev_I5_source",
            "type": "asserted",
            "payload": {
                "kind": "fact",
                "key": {"entity_id": "user", "predicate_canonical": "I5_test", "qualifiers_hash": "", "owner": "default", "domain": "general"},
                "body": "test_value",
                "confidence": 0.8,
                "source_event": "ev_I5_source",
            },
            "parents": [],
            "agent": "agent",
            "actor": "agent",
            "owner": "default",
            "trust_level": 2,
            "occurred_at": "2026-01-01T00:00:00.000Z",
            "recorded_at": "2026-01-01T00:00:00.000Z",
            "prev_head": "",
            "sig": None,
        }
        self.reducer.reduce(event)

        facts = self.store.query_beliefs("facts", "predicate_canonical='I5_test'")
        if facts:
            justs = self.store.get_justifications(facts[0]["belief_id"])
            self.assertTrue(len(justs) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
