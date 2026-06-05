"""
Chronicle — build verification & property tests (§29, §31).

Unit coverage of the data plane plus the property/acceptance tests P1–P21 and the
worked examples B.1–B.6. Runs against a temp SQLite db; no network/model needed.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.serialize import cjson_dumps, content_hash, event_id, decimalize, HASH_NAME
from engine.store import MemoryStore
from engine.reducer import Reducer, TRUST_CEILING
from engine.capture import CaptureEngine
from engine.embeddings import HashingEmbedder, pack, unpack, cosine
from engine import access
from engine.core import ChronicleCore


def make_core():
    # Force the offline hashing embedder so tests are deterministic and never
    # probe localhost embedding servers.
    home = tempfile.mkdtemp()
    return ChronicleCore(home, {"embeddings": {"model": "hashing"}}), home


# --------------------------------------------------------------------------
# §5 Serialization & content addressing
# --------------------------------------------------------------------------
class TestSerialization(unittest.TestCase):
    def test_cjson_basic(self):
        self.assertEqual(cjson_dumps(None), "null")
        self.assertEqual(cjson_dumps(True), "true")
        self.assertEqual(cjson_dumps(42), "42")
        self.assertEqual(cjson_dumps(-5), "-5")
        self.assertEqual(cjson_dumps([1, 2, 3]), "[1,2,3]")

    def test_cjson_keys_sorted(self):
        self.assertEqual(cjson_dumps({"b": 2, "a": 1}), '{"a":1,"b":2}')

    def test_cjson_forbids_raw_float(self):
        with self.assertRaises(ValueError):
            cjson_dumps({"x": 0.5})

    def test_decimalize_floats(self):
        d = decimalize({"c": 0.9, "n": 3})
        self.assertEqual(d["c"], "0.900000")
        self.assertEqual(d["n"], 3)

    def test_event_id_deterministic_and_parents_sorted(self):
        a = event_id("observed", {"x": "t"}, ["b", "a"], "user", "2026-01-01T00:00:00.000Z")
        b = event_id("observed", {"x": "t"}, ["a", "b"], "user", "2026-01-01T00:00:00.000Z")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("ev_") and len(a) == 67)

    def test_event_id_handles_float_payload(self):
        # confidence floats in payloads must not break id computation (§5.1)
        eid = event_id("asserted", {"confidence": 0.9}, [], "user", "2026-01-01T00:00:00.000Z")
        self.assertTrue(eid.startswith("ev_"))

    def test_hash_len(self):
        self.assertEqual(len(content_hash(b"hello")), 64)
        self.assertIn(HASH_NAME, ("blake3-256", "blake2b-256"))

    def test_embeddings_roundtrip(self):
        v = HashingEmbedder().embed("vet in denver")
        self.assertAlmostEqual(cosine(v, v), 1.0, places=5)
        self.assertEqual(len(unpack(pack(v))), len(v))

    def test_embedder_local_default_falls_back_offline(self):
        # Local model is the default, but an unreachable endpoint must fall back
        # to the offline hashing embedder (never hard-break retrieval).
        from engine.embeddings import get_embedder, HashingEmbedder
        e = get_embedder("embeddinggemma-300m", 768, base_url="http://127.0.0.1:9")
        self.assertIsInstance(e, HashingEmbedder)
        self.assertEqual(e.dimensions, 768)
        # 'auto' with no reachable server also falls back to hashing
        self.assertIsInstance(get_embedder("auto", 768, base_url="http://127.0.0.1:9"), HashingEmbedder)
        self.assertIsInstance(get_embedder("hashing"), HashingEmbedder)

    def test_openai_embedder_runtime_resilient(self):
        # A reachable-at-init-but-then-failing endpoint must not raise from embed()
        # — it trips to offline hashing (same dim) instead.
        from engine.embeddings import OpenAICompatEmbedder
        emb = OpenAICompatEmbedder("http://127.0.0.1:9/v1", "x", 768)
        v = emb.embed("hello")          # endpoint dead → must NOT raise
        self.assertEqual(len(v), 768)
        self.assertEqual(len(emb.embed("again")), 768)


# --------------------------------------------------------------------------
# §6/§24 Event log & store
# --------------------------------------------------------------------------
class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.store = MemoryStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _ev(self, eid="ev_x", type_="observed", payload=None):
        return {"event_id": eid, "type": type_, "payload": payload or {"excerpt": "hi", "source_type": "t"},
                "parents": [], "actor": "user", "owner": "default", "trust_level": 2,
                "occurred_at": "2026-01-01T00:00:00.000Z", "recorded_at": "2026-01-01T00:00:00.000Z",
                "prev_head": "", "sig": None}

    def test_append_and_get(self):
        self.store.append_event(self._ev())
        self.assertEqual(self.store.get_event("ev_x")["type"], "observed")

    def test_append_idempotent_and_git_queue(self):  # P1 / I2 / I7
        self.store.append_event(self._ev())
        self.store.append_event(self._ev())
        self.assertEqual(self.store.count_rows("events", "event_id='ev_x'"), 1)
        self.assertEqual(self.store.count_rows("git_queue"), 1)

    def test_fts_keyed_by_event_id(self):
        self.store.fts_index_observed("ev_1", "the quick brown fox")
        hits = self.store.fts_search_observed("fox")
        self.assertEqual(hits[0]["event_id"], "ev_1")
        self.store.fts_delete_observed("ev_1")
        self.assertEqual(self.store.fts_search_observed("fox"), [])

    def test_curation_jobs(self):
        jid = self.store.enqueue_curation("extract", {"event_id": "ev_1"})
        job = self.store.claim_curation_job()
        self.assertEqual(job["task"], "extract")
        self.store.complete_curation_job(jid)
        self.assertIsNone(self.store.claim_curation_job())


# --------------------------------------------------------------------------
# §7 Reducer / projection
# --------------------------------------------------------------------------
class TestReducer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store)
        self.store.reducer = self.reducer
        self.cap = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def _fact(self, pred, val, **kw):
        key = {"entity_id": kw.get("entity", "user"), "predicate_canonical": pred, "attribute": pred,
               "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": kw.get("domain", "user")}
        return self.cap.append("asserted", {"kind": "fact", "key": key, "body": val,
                                            "confidence": kw.get("conf", 0.9),
                                            "source_event": kw.get("src", "src"),
                                            "source_type": kw.get("st", "user_direct"),
                                            "domain": kw.get("domain", "user")},
                               actor="user", owner="default", trust_level=kw.get("trust", 4),
                               occurred_at=kw.get("occurred_at"))

    def test_asserted_projects_and_justifies(self):  # I5
        self._fact("name", "Jared")
        f = self.store.query_beliefs("facts", "predicate_canonical='name'")[0]
        self.assertEqual(f["value"], "Jared")
        self.assertGreaterEqual(len(self.store.get_justifications(f["belief_id"])), 1)

    def test_trust_ceiling(self):  # P6 / I6
        self._fact("email", "a@b.com", trust=0, conf=0.95)
        f = self.store.query_beliefs("facts", "predicate_canonical='email'")[0]
        self.assertLessEqual(f["confidence"], TRUST_CEILING[0])

    def test_conflict_supersede_user_domain(self):  # §8.5
        self._fact("name", "Jared")
        self._fact("name", "Jared M", conf=0.95)
        active = self.store.query_beliefs("facts", "predicate_canonical='name' AND status='active'")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["value"], "Jared M")

    def test_conflict_equal_confirms(self):  # §8.5 — corroboration from a distinct source
        self._fact("city", "Denver", src="ev_a", occurred_at="2026-01-01T00:00:00.000Z")
        self._fact("city", "Denver", src="ev_b", occurred_at="2026-01-02T00:00:00.000Z")
        f = self.store.query_beliefs("facts", "predicate_canonical='city'")[0]
        self.assertGreaterEqual(f["confirm_count"], 1)

    def test_rebuild_identical(self):  # P3 / I3
        self._fact("name", "Jared")
        self._fact("city", "Denver")
        before = self._snapshot()
        self.reducer.rebuild()
        self.assertEqual(before, self._snapshot())

    def test_reducer_deterministic(self):  # P4
        self._fact("name", "Jared")
        s1 = self._snapshot()
        self.reducer.rebuild()
        self.reducer.rebuild()
        self.assertEqual(s1, self._snapshot())

    def test_retract_cascade_no_orphan(self):  # P5 / P7
        self._fact("age", "30")
        f = self.store.query_beliefs("facts", "predicate_canonical='age'")[0]
        self.cap.append("retracted", {"belief_id": f["belief_id"], "reason": "t"}, actor="user", owner="default")
        self.assertEqual(self.store.get_belief("facts", f["belief_id"])["status"], "retracted")
        self.assertEqual(self.store.active_unjustified(), [])

    def _snapshot(self):
        return [(r["belief_id"], r["value"], r["status"], round(r["confidence"] or 0, 4), r["confirm_count"])
                for r in self.store.query_beliefs("facts", "1=1", (), 999, order="belief_id")]


# --------------------------------------------------------------------------
# §12 Capture & reaper
# --------------------------------------------------------------------------
class TestCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store)
        self.store.reducer = self.reducer
        self.cap = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_observe_durable(self):  # P11 / I12
        eid = self.cap.observe("Hello", "Hi", session_id="s1")
        self.assertEqual(self.store.get_event(eid)["type"], "observed")
        self.assertEqual(self.store.get_session("s1")["status"], "active")

    def test_rescue_makes_draft_belief(self):  # I14
        self.cap.rescue([{"role": "user", "content": "Always confirm before deleting files"}], session_id="s1")
        self.assertGreaterEqual(len(self.store.query_beliefs("notes", "status='draft'")), 1)

    def test_finalize_reextracts(self):  # part of I13
        self.cap.observe("My name is Jared", "ok", session_id="s1")
        while self.store.claim_curation_job():
            pass
        for j in self.store.query_beliefs("curation_jobs", "status='running'"):
            self.store.complete_curation_job(j["id"])
        self.cap.finalize_session("s1", "reaped")
        self.assertGreater(self.store.pending_curation_count(), 0)


# --------------------------------------------------------------------------
# Integration: invariants & worked examples via ChronicleCore
# --------------------------------------------------------------------------
class TestInvariants(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_P8_durable_enqueue(self):  # I7
        before_git = self.core.store.count_rows("git_queue")
        before_jobs = self.core.store.pending_curation_count()
        self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.assertEqual(self.core.store.count_rows("git_queue"), before_git + 1)
        self.assertEqual(self.core.store.pending_curation_count(), before_jobs + 1)

    def test_P12_trigger_independence(self):  # I13
        self.core.capture.observe("My name is Jared and I live in Denver", "ok", session_id="s1")
        self.core.store.upsert_session({"session_id": "s1", "status": "active"})
        self.core.reaper.startup_recovery()
        self.core.process_pending()
        facts = self.core.store.query_beliefs("facts", "status='active'")
        self.assertTrue(any(f["value"] == "Jared" for f in facts))

    def test_P16_source_independence(self):  # I18
        self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.core.process_pending()
        self.assertGreaterEqual(self.core.store.count_rows("facts", "status='active'"), 1)

    def test_P19_access_control(self):  # I22
        self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.core.process_pending()
        f = self.core.store.query_beliefs("facts", "predicate_canonical='name'")[0]
        self.assertTrue(access.can_read(f["read_acl"], f["owner"], "research"))
        self.core.capture.append("revoke", {"belief_id": f["belief_id"], "principal": "research"},
                                 actor="user", owner="assistant")
        f2 = self.core.store.get_belief("facts", f["belief_id"])
        self.assertFalse(access.can_read(f2["read_acl"], f2["owner"], "research"))
        self.assertTrue(access.can_read(f2["read_acl"], f2["owner"], "assistant"))

    def test_P19_cross_user_isolation(self):  # I21
        self.assertFalse(access.can_read("user_agents", "alice:agent", "bob:agent"))

    def test_P20_recall_floor_and_abstain(self):  # I23 / B.2 / B.3
        self.core.capture.observe("For the record, Mara is a veterinarian in Denver", "noted", session_id="s1")
        ans = self.core.retrieval.answer("what is Mara")          # not extracted → Tier-2
        self.assertEqual(ans["tier"], 2)
        self.assertGreaterEqual(len(ans.get("promoted", [])), 1)
        ans2 = self.core.retrieval.answer("what is my favorite planet")
        self.assertEqual(ans2["tier"], 0)
        self.assertTrue(ans2["abstain"])

    def test_P21_derivation_scoped_and_defeasible(self):  # I24 / B.4
        self.core.capture.observe("I work at Innovaccer", "ok", session_id="s1")
        self.core.capture.observe("My office is in downtown", "ok", session_id="s1")
        self.core.process_pending()
        derived = self._derived()
        self.assertEqual(len(derived), 1)
        d = derived[0]
        self.assertIn("workplace", d["entity_id"])           # scoped (I24b)
        self.assertNotIn("Innovaccer is", d["value"])
        self.assertLessEqual(d["confidence"], 0.75)
        self.assertEqual(d["status"], "draft")
        wa = self.core.store.query_beliefs("facts", "predicate_canonical='works_at' AND status='active'")[0]
        self.core.capture.append("corrected", {"belief_id": wa["belief_id"], "reason": "left"},
                                 actor="user", owner="assistant")
        self.assertEqual(self.core.store.get_belief("facts", d["belief_id"])["status"], "retracted")

    def test_P21_guards_block_multi(self):  # I24 guards
        self.core.store.upsert_predicate("works_at", "works_at", "multi")
        self.core.capture.observe("I work at Innovaccer", "ok", session_id="s1")
        self.core.capture.observe("My office is in downtown", "ok", session_id="s1")
        self.core.process_pending()
        self.assertEqual(len(self._derived()), 0)

    def test_P18_reference_not_own(self):  # I20
        from engine.federation import CapabilityProvider

        class Contacts(CapabilityProvider):
            name = "weave"; capability = "contacts"
            def is_available(self): return True

        self.core.federation.register(Contacts())
        self.assertEqual(self.core.federation.capability_for_predicate("phone"), "contacts")
        before = self.core.store.count_rows("facts", "predicate_canonical='phone'")
        self.core.federation.route_delegate(capability="contacts", entity_id="user",
                                            predicate="phone", value="555-1234", owner="assistant")
        self.assertGreaterEqual(self.core.store.count_rows("pointers"), 1)
        self.assertEqual(self.core.store.count_rows("facts", "predicate_canonical='phone'"), before)

    def test_embed_failure_never_breaks_capture(self):  # I12 robustness
        # Worst case: an embedder that ALWAYS raises (server died mid-session, or a
        # model that accepted the healthcheck but rejects real input). Capture,
        # extraction, and retrieval must all still work — FTS carries recall.
        class BoomEmbedder:
            model = "boom"; dimensions = 768
            def embed(self, text):
                raise RuntimeError("embedding server down")
        boom = BoomEmbedder()
        self.core.embedder = boom
        self.core.reducer.embedder = boom
        self.core.retrieval.embedder = boom
        eid = self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.assertIsNotNone(self.core.store.get_event(eid))   # durable capture survived
        self.core.process_pending()
        self.assertTrue(any(f["value"] == "Jared"
                            for f in self.core.store.query_beliefs("facts", "status='active'")))
        ans = self.core.retrieval.answer("what is my name")    # query path survives too
        self.assertIn("tier", ans)

    def test_B1_crash_capture(self):
        eid = self.core.capture.observe("Remember my flight is at 9am", "ok", session_id="s1")
        self.assertIsNotNone(self.core.store.get_event(eid))

    def test_B5_multiagent_privacy(self):
        self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.core.process_pending()
        f = self.core.store.query_beliefs("facts", "predicate_canonical='name'")[0]
        self.assertTrue(access.can_read(f["read_acl"], f["owner"], "research"))
        self.core.tools.dispatch("assistant", "chronicle_set_acl",
                                 {"belief_id": f["belief_id"], "visibility": "private"})
        f2 = self.core.store.get_belief("facts", f["belief_id"])
        self.assertFalse(access.can_read(f2["read_acl"], f2["owner"], "research"))
        self.assertTrue(access.can_read(f2["read_acl"], f2["owner"], "assistant"))

    def test_I16_branch_isolation(self):
        e1 = self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.core.capture.observe("Actually call me Bob on this branch", "ok", session_id="s1")
        bp = self.core.store.get_event(e1)["seq"]
        self.core.abandon_after("s1", bp)        # abandon everything after e1
        self.core.process_pending()
        # e2's content must not be promoted to an active belief
        self.assertFalse(any("Bob" in (f["value"] or "") for f in
                             self.core.store.query_beliefs("facts", "status='active'")))

    def _derived(self):
        return [f for f in self.core.store.query_beliefs("facts", "1=1", (), 50)
                if json.loads(f.get("provenance") or "{}").get("source_type") == "inference"]


# --------------------------------------------------------------------------
# §17 curation & §21 health & §20 forgetting
# --------------------------------------------------------------------------
class TestCurationHealth(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_extract_idempotent(self):  # I9
        self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.core.process_pending()
        n1 = self.core.store.count_rows("facts")
        ev = self.core.store.get_events_by_type("observed")[0]
        self.core.store.enqueue_curation("extract", {"event_id": ev["event_id"]})
        self.core.process_pending()
        self.assertEqual(self.core.store.count_rows("facts"), n1)

    def test_health_no_unjustified(self):  # I5
        self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        self.core.process_pending()
        self.assertEqual(self.core.health.run()["unjustified"], [])

    def test_decay_spares_critical(self):  # I10
        key = {"entity_id": "user", "predicate_canonical": "allergy", "attribute": "allergy",
               "qualifiers_hash": "", "qualifiers": {}, "owner": "assistant", "domain": "user"}
        self.core.capture.append("asserted", {"kind": "fact", "key": key, "body": "penicillin allergy",
                                              "confidence": 0.9, "source_event": "x", "source_type": "user_direct",
                                              "domain": "user"}, actor="user", owner="assistant", trust_level=4)
        f = self.core.store.query_beliefs("facts", "predicate_canonical='allergy'")[0]
        self.assertEqual(f["criticality"], "critical")
        import datetime
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=4000)
        self.core.forgetting.decay_sweep(now=future)
        self.assertEqual(self.core.store.get_belief("facts", f["belief_id"])["fidelity"], "verbatim")

    def test_git_mirror_flush(self):  # §26
        self.core.capture.observe("My name is Jared", "ok", session_id="s1")
        flushed = self.core.gitmirror.flush()
        self.assertGreaterEqual(flushed, 1)
        self.assertEqual(self.core.store.git_lag(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
