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

from engine import access
from engine.capture import CaptureEngine
from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder, cosine, pack, unpack
from engine.reducer import TRUST_CEILING, Reducer
from engine.serialize import HASH_NAME, cjson_dumps, content_hash, decimalize, event_id
from engine.store import SCHEMA_VERSION, MemoryStore


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

    def test_embedder_explicit_defers_to_runtime_retry(self):
        # An explicit model + endpoint is trusted: an unreachable endpoint at init
        # does NOT fall back to hashing. It returns the retrying client, which
        # waits+retries at runtime and raises on exhaustion (never hash vectors).
        from engine.embeddings import (
            DegradedEmbedder,
            EmbeddingsUnavailable,
            HashingEmbedder,
            OpenAICompatEmbedder,
            get_embedder,
        )
        e = get_embedder("embeddinggemma-300m", 768, base_url="http://127.0.0.1:9")
        self.assertIsInstance(e, OpenAICompatEmbedder)
        self.assertEqual(e.dimensions, 768)
        # 'auto' with nothing reachable is DEGRADED, never a silent hash fallback:
        # it writes no vectors and the work is queued for retry (§24.4).
        d = get_embedder("auto", 768, base_url="http://127.0.0.1:9")
        self.assertIsInstance(d, DegradedEmbedder)
        self.assertRaises(EmbeddingsUnavailable, d.embed, "anything")
        # Hashing stays exactly as it was, but only when asked for by name.
        self.assertIsInstance(get_embedder("hashing"), HashingEmbedder)

    def test_openai_embedder_retries_then_raises(self):
        # A failing endpoint must NOT silently emit hash vectors. embed() waits +
        # retries (bounded) and then RAISES; callers catch it and skip the vector
        # for this item (FTS/structured retrieval continue).
        from engine.embeddings import OpenAICompatEmbedder
        emb = OpenAICompatEmbedder("http://127.0.0.1:9/v1", "x", 768,
                                   max_attempts=2, backoff_base=0.0, backoff_cap=0.0)
        with self.assertRaises(OSError):
            emb.embed("hello")

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

    def test_migrate_v2_fixture_adds_digest(self):  # §u2 triage
        """A real v2 curation_jobs (has 'embed' from t2, missing 'digest' from
        this task) must be rebuilt on the NEXT _migrate call independent of the
        'embed' check already being satisfied — that check alone (pre-fix) never
        looked at 'digest', so a v2 db never rebuilt and every digest enqueue
        raised IntegrityError inside the enclosing extract job's transaction."""
        conn = self.store._conn()
        conn.executescript(
            "DROP TABLE curation_jobs;\n"
            "CREATE TABLE curation_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "task TEXT CHECK(task IN ('extract','route','criticality','canonicalize',"
            "'consolidate','contradiction','identity','derive','verify','decay','consistency',"
            "'health','reextract','journal_ingest','session_summarize','embed')),"
            "payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),"
            "status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',"
            "attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT,"
            "error TEXT, run_after TEXT);\n"
            "INSERT INTO curation_jobs(task,payload,status,created_at) "
            "VALUES('health','{}','done','x');")
        conn.commit()
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='curation_jobs'").fetchone()[0]
        self.assertNotIn("'digest'", sql)
        self.assertIn("'embed'", sql)  # this is v2 (post-t2), not the older pre-t2 shape

        self.store._migrate(conn)  # the code path a fresh MemoryStore.__init__ runs
        self.store.enqueue_curation("digest", {"entity_id": "e1"})  # raised IntegrityError pre-fix
        self.assertEqual(self.store.get_meta("schema_version"), str(SCHEMA_VERSION))
        self.assertEqual(self.store.count_rows("curation_jobs", "task='health'"), 1)


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
        self._fact("name", "Pat")
        f = self.store.query_beliefs("facts", "predicate_canonical='name'")[0]
        self.assertEqual(f["value"], "Pat")
        self.assertGreaterEqual(len(self.store.get_justifications(f["belief_id"])), 1)

    def test_trust_ceiling(self):  # P6 / I6
        self._fact("email", "a@b.com", trust=0, conf=0.95)
        f = self.store.query_beliefs("facts", "predicate_canonical='email'")[0]
        self.assertLessEqual(f["confidence"], TRUST_CEILING[0])

    def test_conflict_supersede_user_domain(self):  # §8.5
        self._fact("name", "Pat")
        self._fact("name", "Pat M", conf=0.95)
        active = self.store.query_beliefs("facts", "predicate_canonical='name' AND status='active'")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["value"], "Pat M")

    def test_conflict_equal_confirms(self):  # §8.5 — corroboration from a distinct source
        self._fact("city", "Denver", src="ev_a", occurred_at="2026-01-01T00:00:00.000Z")
        self._fact("city", "Denver", src="ev_b", occurred_at="2026-01-02T00:00:00.000Z")
        f = self.store.query_beliefs("facts", "predicate_canonical='city'")[0]
        self.assertGreaterEqual(f["confirm_count"], 1)

    def test_rebuild_identical(self):  # P3 / I3
        self._fact("name", "Pat")
        self._fact("city", "Denver")
        before = self._snapshot()
        self.reducer.rebuild()
        self.assertEqual(before, self._snapshot())

    def test_reducer_deterministic(self):  # P4
        self._fact("name", "Pat")
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
        self.cap.observe("My name is Pat", "ok", session_id="s1")
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
        self.core.capture.observe("My name is Pat", "ok", session_id="s1")
        self.assertEqual(self.core.store.count_rows("git_queue"), before_git + 1)
        self.assertEqual(self.core.store.pending_curation_count(), before_jobs + 1)

    def test_P12_trigger_independence(self):  # I13
        self.core.capture.observe("My name is Pat and I live in Denver", "ok", session_id="s1")
        self.core.store.upsert_session({"session_id": "s1", "status": "active"})
        self.core.reaper.startup_recovery()
        self.core.process_pending()
        facts = self.core.store.query_beliefs("facts", "status='active'")
        self.assertTrue(any(f["value"] == "Pat" for f in facts))

    def test_P16_source_independence(self):  # I18
        self.core.capture.observe("My name is Pat", "ok", session_id="s1")
        self.core.process_pending()
        self.assertGreaterEqual(self.core.store.count_rows("facts", "status='active'"), 1)

    def test_P19_access_control(self):  # I22
        self.core.capture.observe("My name is Pat", "ok", session_id="s1")
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

    def test_P20_support_gate_rejects_unrelated_top_hit(self):  # I8, §18.4
        # The gap the gate closes: search() is never empty, so a top hit that
        # ranks well but shares nothing with the question used to be answered
        # anyway (30/30 unanswerable LongMemEval questions, median confidence
        # 0.600). Dropping the rejected t1 matters — otherwise _read_and_extract's
        # `best or t1[0]["value"]` fallback re-admits it and abstention never fires.
        r = self.core.retrieval
        r.search = lambda *a, **k: [{"belief_id": "b1", "table": "facts", "kind": "fact",
                                     "score": 1.0, "channels": ["vector"], "value": "Acme Fake Co",
                                     "entity_id": "user", "attribute": "employer",
                                     "confidence": 0.9, "status": "active", "source_type": None}]
        r.retrieve_raw = lambda *a, **k: []
        ans = r.answer("how many kayaking trips did I take in Sacramento")
        self.assertTrue(ans["abstain"])
        self.assertEqual(ans["tier"], 0)
        self.assertEqual(ans["why"], "low_support")
        self.assertEqual(ans["answer"], "")

    def test_P20_support_gate_passes_real_support(self):  # I8, §18.4
        # Same gate, supported question: the raw span carries every distinctive
        # token, so it must answer rather than abstain.
        r = self.core.retrieval
        r.search = lambda *a, **k: []
        r.retrieve_raw = lambda *a, **k: [
            {"event_id": "e1", "score": 0.9,
             "excerpt": "User: my kayaking trips in Sacramento were in June."}]
        ans = r.answer("when were my kayaking trips in Sacramento")
        self.assertFalse(ans["abstain"])
        self.assertEqual(ans["tier"], 2)

    def test_P20_support_gate_config_bounds(self):  # I8, §18.4
        from engine.config import DEFAULTS, Config
        d = DEFAULTS["retrieval"]
        self.assertEqual(self.core.retrieval._abstain_gate, d["abstain_gate"])
        self.assertEqual(self.core.retrieval._focus_coverage, d["focus_coverage"])
        eng = type(self.core.retrieval)(
            self.core.store, Config({"retrieval": {"abstain_gate": "overlap", "focus_coverage": 9,
                                                   "score_threshold": -3, "overlap_min_tokens": 0}}))
        self.assertEqual(eng._abstain_gate, "overlap")
        self.assertEqual(eng._focus_coverage, 1.0)      # clamped
        self.assertEqual(eng._score_threshold, 0.0)     # clamped
        self.assertEqual(eng._overlap_min_tokens, 1)    # clamped

    def test_P21_derivation_scoped_and_defeasible(self):  # I24 / B.4
        self.core.capture.observe("I work at Acme Fake Co", "ok", session_id="s1")
        self.core.capture.observe("My office is in downtown", "ok", session_id="s1")
        self.core.process_pending()
        derived = self._derived()
        self.assertEqual(len(derived), 1)
        d = derived[0]
        self.assertIn("workplace", d["entity_id"])           # scoped (I24b)
        self.assertNotIn("Acme Fake Co is", d["value"])
        self.assertLessEqual(d["confidence"], 0.75)
        self.assertEqual(d["status"], "draft")
        wa = self.core.store.query_beliefs("facts", "predicate_canonical='works_at' AND status='active'")[0]
        self.core.capture.append("corrected", {"belief_id": wa["belief_id"], "reason": "left"},
                                 actor="user", owner="assistant")
        self.assertEqual(self.core.store.get_belief("facts", d["belief_id"])["status"], "retracted")

    def test_P21_guards_block_multi(self):  # I24 guards
        self.core.store.upsert_predicate("works_at", "works_at", "multi")
        self.core.capture.observe("I work at Acme Fake Co", "ok", session_id="s1")
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
        eid = self.core.capture.observe("My name is Pat", "ok", session_id="s1")
        self.assertIsNotNone(self.core.store.get_event(eid))   # durable capture survived
        self.core.process_pending()
        self.assertTrue(any(f["value"] == "Pat"
                            for f in self.core.store.query_beliefs("facts", "status='active'")))
        ans = self.core.retrieval.answer("what is my name")    # query path survives too
        self.assertIn("tier", ans)

    def test_B1_crash_capture(self):
        eid = self.core.capture.observe("Remember my flight is at 9am", "ok", session_id="s1")
        self.assertIsNotNone(self.core.store.get_event(eid))

    def test_B5_multiagent_privacy(self):
        self.core.capture.observe("My name is Pat", "ok", session_id="s1")
        self.core.process_pending()
        f = self.core.store.query_beliefs("facts", "predicate_canonical='name'")[0]
        self.assertTrue(access.can_read(f["read_acl"], f["owner"], "research"))
        self.core.tools.dispatch("assistant", "chronicle_set_acl",
                                 {"belief_id": f["belief_id"], "visibility": "private"})
        f2 = self.core.store.get_belief("facts", f["belief_id"])
        self.assertFalse(access.can_read(f2["read_acl"], f2["owner"], "research"))
        self.assertTrue(access.can_read(f2["read_acl"], f2["owner"], "assistant"))

    def test_I16_branch_isolation(self):
        e1 = self.core.capture.observe("My name is Pat", "ok", session_id="s1")
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
        self.core.capture.observe("My name is Pat", "ok", session_id="s1")
        self.core.process_pending()
        n1 = self.core.store.count_rows("facts")
        ev = self.core.store.get_events_by_type("observed")[0]
        self.core.store.enqueue_curation("extract", {"event_id": ev["event_id"]})
        self.core.process_pending()
        self.assertEqual(self.core.store.count_rows("facts"), n1)

    def test_health_no_unjustified(self):  # I5
        self.core.capture.observe("My name is Pat", "ok", session_id="s1")
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

    def test_embedding_status(self):  # diagnostic
        st = self.core.embedding_status()
        self.assertIn("supports_embeddings", st)
        self.assertEqual(st["mode"], "offline_hashing")   # make_core forces hashing
        self.assertFalse(st["supports_embeddings"])
        t = json.loads(self.core.tools.dispatch("assistant", "chronicle_embedding_status", {}))
        self.assertIn("mode", t)

    def test_git_mirror_flush(self):  # §26
        self.core.capture.observe("My name is Pat", "ok", session_id="s1")
        flushed = self.core.gitmirror.flush()
        self.assertGreaterEqual(flushed, 1)
        self.assertEqual(self.core.store.git_lag(), 0)


# --------------------------------------------------------------------------
# §u2 Entity consolidation digests
# --------------------------------------------------------------------------
class TestDigest(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _digests(self):
        return self.core.store.query_beliefs(
            "notes", "subject LIKE 'digest:%' AND note_type='belief' AND status='active'", (), 10)

    def test_digest_created_at_3_facts(self):
        self.core.capture.observe("I am Pat Testley", "", session_id="s1")
        self.core.capture.observe("I work at Acme Fake Co", "", session_id="s1")
        self.core.capture.observe("I live in Springfield", "", session_id="s1")
        self.core.process_pending()
        digests = self._digests()
        self.assertEqual(len(digests), 1)
        self.assertGreaterEqual(digests[0]["body"].count("="), 3)

    def test_digest_below_threshold_is_noop(self):
        self.core.capture.observe("I am Pat Testley", "", session_id="s1")
        self.core.capture.observe("I work at Acme Fake Co", "", session_id="s1")
        self.core.process_pending()
        self.assertEqual(self._digests(), [])

    def test_digest_upserts_not_duplicates_on_new_fact(self):  # §u2 triage
        """Re-digesting after a fact that actually changes the digest line must
        replace the existing note (same belief_id), never add a second active
        row — a content-derived key (e.g. folding hash(digest_line) into it)
        changes belief_id whenever content changes, so this is the one case a
        no-op re-drain can't distinguish from a correct fix."""
        self.core.capture.observe("I am Pat Testley", "", session_id="s1")
        self.core.capture.observe("I work at Acme Fake Co", "", session_id="s1")
        self.core.capture.observe("I live in Springfield", "", session_id="s1")
        self.core.process_pending()
        before = self._digests()
        self.assertEqual(len(before), 1)
        bid, body_before = before[0]["belief_id"], before[0]["body"]

        self.core.capture.observe("My phone is 555-1234", "", session_id="s1")
        self.core.process_pending()
        after = self._digests()
        self.assertEqual(len(after), 1,
                         f"digest duplicated instead of upserted: {[d['body'] for d in after]}")
        self.assertEqual(after[0]["belief_id"], bid, "belief_id must stay stable across re-digest")
        self.assertNotEqual(after[0]["body"], body_before, "digest should pick up the new fact")
        self.assertIn("phone", after[0]["body"])

    def _seed(self):
        for t in ("I am Pat Testley", "I work at Acme Fake Co", "I live in Springfield"):
            self.core.capture.observe(t, "", session_id="s1")
        self.core.process_pending()
        digests = self._digests()
        self.assertEqual(len(digests), 1)
        return digests[0]

    def test_digest_lineage_resolves(self):  # §u2 triage
        """Every support the digest files must resolve to a real OBSERVED event,
        and the digest event must carry the observed turns as parents. Passing
        the entity's belief_id as source_event (the shape this replaces) writes a
        justification through reducer's 'event' path that no event lookup finds."""
        d = self._seed()
        supports = self.core.store.get_justifications(d["belief_id"])
        self.assertTrue(supports, "digest filed no justification at all")
        for j in supports:
            if j["support_kind"] != "event":
                continue
            ev = self.core.store.get_event(j["support"])
            self.assertIsNotNone(ev, f"dangling justification support {j['support']!r}")
            self.assertEqual(ev["type"], "observed")
        asserted = [e for e in self.core.store.get_events_by_type("asserted")
                    if json.loads(e["payload"]).get("key", {}).get("subject", "").startswith("digest:")]
        self.assertTrue(asserted, "no digest asserted event")
        for e in asserted:
            parents = json.loads(e["parents"])
            self.assertTrue(parents, "digest event has no parents")
            for p in parents:
                pev = self.core.store.get_event(p)
                self.assertIsNotNone(pev, f"digest parent {p!r} is not an event")
                self.assertEqual(pev["type"], "observed")

    def test_digest_is_not_a_directive_and_not_searchable(self):  # §u2
        """A digest is consolidation, not instruction (always_inject=0), and it is
        scoped to ask_about — leaving it in search() would let a summary outrank
        the verbatim facts it was built from."""
        d = self._seed()
        self.assertEqual(d["always_inject"], 0)
        self.assertEqual(d["note_type"], "belief")
        hits = self.core.retrieval.search("Pat Testley Springfield Acme", limit=20)
        self.assertNotIn(d["belief_id"], [h["belief_id"] for h in hits])
        asked = self.core.retrieval.ask_about("user")
        self.assertEqual(asked[0].get("kind"), "digest")

    def test_stale_digest_is_retired_not_left_active(self):  # §u2
        """The 'exactly one active digest' contract must not rest on the anchor
        never moving: re-extraction at a new version can mint a fact off an OLDER
        observed event and lower the minimum, which changes belief_id. A digest
        under any other id is retracted on the next run."""
        d = self._seed()
        stale = dict(d)
        stale.update({"belief_id": "b_stale_digest_fixture", "body_hash": "deadbeef",
                      "body": "user: stale=yes (episodes: 9)"})
        self.core.store.upsert_belief("notes", stale)
        self.assertEqual(len(self._digests()), 2)
        self.core.capture.observe("My phone is 555-1234", "", session_id="s1")
        self.core.process_pending()
        after = self._digests()
        self.assertEqual(len(after), 1, f"stale digest survived: {[x['body'] for x in after]}")
        self.assertEqual(after[0]["belief_id"], d["belief_id"])

    def test_get_context_adds_digest_only_when_budget_allows(self):  # §u2
        """get_context surfaces the digest for a graph-seeded entity, and drops it
        when the budget is too tight — raw evidence is what carries turn recall,
        so the digest may only ever spend space nothing else claimed."""
        self._seed()
        hint = "what do we know about the user"
        self.assertEqual(self.core.retrieval._graph_seeds(
            self.core.retrieval._tokens(hint)), ["user"])
        ctx = self.core.retrieval.get_context(hint)
        self.assertIn("[DIGEST] user:", ctx)
        self.assertNotIn("[DIGEST]", self.core.retrieval.get_context(hint, token_budget=20))

    def test_get_context_expands_complete_session_window(self):  # r2 / session_window
        """get_context with session_window enabled expands a multi-turn session into
        a complete contiguous window, including all observed events even when only
        one turn ranks highly. This ensures readers see the full conversation context."""
        # Create a multi-turn session with distinct turns
        turns = [
            "I am Pat Testley",
            "I work at Acme Fake Co",
            "I live in Springfield",
            "My phone is 555-1234",
        ]
        for turn in turns:
            self.core.capture.observe(turn, "", session_id="s1")
        self.core.process_pending()

        # Query for something that matches late in the conversation (phone)
        # so only one turn ranks highly in retrieve_raw
        hint = "What is the phone number"
        ctx = self.core.retrieval.get_context(hint, token_budget=8000, include_directives=False)

        # All turns should appear in the context due to session window expansion
        for turn in turns:
            # Each turn should appear as an excerpt in the session block
            self.assertIn(turn, ctx, f"Turn '{turn}' missing from context: {ctx}")

        # Verify it's all grouped under a single SESSION header
        session_blocks = ctx.count("[SESSION s1")
        self.assertGreaterEqual(session_blocks, 1, "Session should appear at least once")

    def test_get_context_respects_session_window_disable(self):
        """When context.session_window is disabled, only top-ranked excerpts appear."""
        turns = [
            "I am Pat Testley",
            "I work at Acme Fake Co",
            "I live in Springfield",
            "My phone is 555-1234",
        ]
        for turn in turns:
            self.core.capture.observe(turn, "", session_id="s1")
        self.core.process_pending()

        # Create a new core with session_window disabled
        cfg = {"context": {"session_window": False}}
        from engine.core import ChronicleCore
        core2 = ChronicleCore(self.home, cfg)
        core2.initialize("s1", principal_id="assistant")

        hint = "What is the phone number"
        ctx = core2.retrieval.get_context(hint, token_budget=8000, include_directives=False)

        # With session_window disabled, not all turns are guaranteed to appear
        # (only the most relevant ones will be included)
        phone_present = "555-1234" in ctx
        self.assertTrue(phone_present, "Query-matched turn should still appear")

    def test_unchanged_redigest_appends_no_event(self):  # §u2
        """Digest jobs are enqueued unconditionally on every extract, so a run
        that renders the same line must be a true no-op — otherwise the event log
        grows by one asserted event per drain forever."""
        self._seed()
        before = self.core.store.count_rows("events", "1=1")
        self.core.store.enqueue_curation("digest", {"entity_id": "user"})
        self.core.curation.drain(max_jobs=10)
        self.assertEqual(self.core.store.count_rows("events", "1=1"), before)


# --------------------------------------------------------------------------
# §r6 Topic-relevant standing notes reach the reader
# --------------------------------------------------------------------------
class TestTopicGatedStandingNotes(unittest.TestCase):
    """A user preference ("I always prefer window seats") is stored as a
    note_type='norm' row. get_context delivers the FIRST 20 always_inject rows
    in store order, and search()'s LIKE channel covers the facts table only —
    so past 20 notes the preference that answers the question is reachable only
    by exact FTS token, and "seats" does not match the query token "seat".
    get_context appends those from leftover budget, after the raw fill."""

    SEAT = "I always prefer window seats when flying"

    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _seed_past_cap(self):
        """24 unrelated standing instructions, then the seat one LAST so it lands
        outside the 20-row unconditional window (query_beliefs has no ORDER BY)."""
        self.core.capture.observe("I am Pat Testley", "", session_id="s1")
        for i in range(24):
            self.core.capture.observe(
                "Always file the Acme Fake Co paperwork in folder number %d" % i,
                "", session_id="s1")
        self.core.capture.observe(self.SEAT, "", session_id="s1")
        self.core.process_pending()
        rows = self.core.store.query_beliefs(
            "notes", "always_inject=1 AND status='active'", (), 200)
        self.assertGreater(len(rows), 20, "scenario needs more norm notes than the cap")
        self.assertNotIn(self.SEAT, [r.get("body") for r in rows[:20]],
                         "seat note must start outside the unconditional window")

    def test_preference_beyond_cap_reaches_context(self):
        self._seed_past_cap()
        ctx = self.core.retrieval.get_context("what seat should I book", token_budget=2000)
        self.assertIn(self.SEAT, ctx)

    def test_topic_irrelevant_preference_is_not_appended(self):
        """Only always_inject rows are delivered unconditionally; a note past the
        cap must earn its own line with a shared focus token, not appear on every ask.

        Scoped to the standing-note channel, because that is the channel r6 gates.
        The same sentence also sits inside the raw observed turn the note was
        extracted from, and r2's session-window fill delivers that turn to any
        query that reaches this session — on purpose. Raw evidence is what carries
        turn-level recall (evidence never delivered is 71% of the judged
        benchmark's misses), so keeping a substring out of the context is not a
        reason to stop delivering it; a bare `assertNotIn(SEAT, ctx)` was testing
        the raw fill by accident and could only be satisfied by suppressing it.
        """
        self._seed_past_cap()
        ctx = self.core.retrieval.get_context("what is the capital of France", token_budget=2000)
        self.assertNotIn(f"[DIRECTIVE] {self.SEAT}", ctx)
        self.assertNotIn(f"[NOTE] {self.SEAT}", ctx)
        # The gate is what kept it out — not an empty context, and not a session
        # window that stopped delivering the turn it came from.
        self.assertIn("[DIRECTIVE] ", ctx)
        self.assertIn(f"User: {self.SEAT}", ctx,
                      "raw evidence for the seat turn must still be delivered")

    def test_unconditional_delivery_is_untouched(self):
        """Additive only: the 20 rows the unconditional block carries are still
        all there, in place, and a note it already delivered is never restated."""
        self._seed_past_cap()
        first20 = [r["body"] for r in self.core.store.query_beliefs(
            "notes", "always_inject=1 AND status='active'", (), 20)]
        ctx = self.core.retrieval.get_context("what seat should I book", token_budget=2000)
        lines = ctx.split("\n")
        self.assertEqual(lines[:20], [f"[DIRECTIVE] {b}" for b in first20])
        for body in first20 + [self.SEAT]:
            self.assertEqual(lines.count(f"[DIRECTIVE] {body}"), 1, body)

    def test_include_directives_false_still_suppresses_notes(self):
        """A caller that opted out of standing notes must not get them back
        through the topic-gated path."""
        self._seed_past_cap()
        ctx = self.core.retrieval.get_context(
            "what seat should I book", token_budget=2000, include_directives=False)
        self.assertNotIn("[DIRECTIVE]", ctx)
        self.assertNotIn(self.SEAT, ctx)

    def test_below_cap_context_is_unchanged(self):
        """With one note the unconditional block already carries it — the
        topic-gated pass must add nothing and duplicate nothing."""
        self.core.capture.observe("I am Pat Testley", "", session_id="s1")
        self.core.capture.observe("I always prefer window seats", "", session_id="s1")
        self.core.process_pending()
        ctx = self.core.retrieval.get_context("what seat should I book", token_budget=2000)
        self.assertEqual(ctx.count("[DIRECTIVE] I always prefer window seats"), 1)
        self.assertIn("window seats", ctx.lower())

    def test_raw_evidence_keeps_first_claim_on_budget(self):
        """r1 priority: the pass spends leftover chars only, so a budget already
        consumed by raw evidence yields byte-identical context."""
        self._seed_past_cap()
        tight = self.core.retrieval.get_context("what seat should I book", token_budget=120)
        self.assertNotIn(self.SEAT, tight)
        self.assertLessEqual(len(tight), 120 * 4 + len("\n… (truncated)"))

    def test_session_header_deduplication_by_sid(self):
        """Session window expansion must dedupe [SESSION] headers by sid, not by
        full header text with an embedded timestamp.

        Phase 1 (retrieve_raw, limit=20) only ever surfaces a subset of a big
        session's turns; the remainder reaches context via phase 2's session-window
        expansion, which walks EVERY observed event in the session directly from
        the store. Two turns is not enough to exercise that path — with only two
        events in the session, phase 1's top-20 swallows both and phase 2 never
        runs. Seed enough turns (25, each with a GENUINELY different occurred_at,
        a minute apart) that some are left over for phase 2 to expand, and check
        that expansion emits at most one [SESSION s1 ...] header — not one
        differently-timestamped header per expanded turn, which is what the old
        header-per-turn text (compared by exact string against a `ctx` snapshot
        the loop never updates) used to produce."""
        from datetime import datetime, timedelta
        base = datetime(2026, 8, 1, 10, 0, 0)
        for i in range(25):
            self.core.capture.observe(
                "Turn number %d in s1" % i, "", session_id="s1",
                occurred_at=(base + timedelta(minutes=i)).isoformat() + "Z")
        self.core.process_pending()

        ctx = self.core.retrieval.get_context("turn in session", token_budget=8000)
        # Count how many [SESSION s1 ...] headers appear (with or without a
        # timestamp suffix, whatever that suffix is) — the assertion is that at
        # most one survives, regardless of whether the expanded turns' timestamps
        # would have produced identical or differing header text.
        import re
        session_headers = re.findall(r'\[SESSION s1[^\]]*\]', ctx)
        self.assertLessEqual(len(session_headers), 1,
                            f"Found multiple session headers: {session_headers}")
        # And the expansion actually ran (all 25 turns present) — otherwise the
        # single-header assertion above would be vacuous.
        self.assertEqual(ctx.count(" in s1"), 25)


class TestSessionWindowBounds(unittest.TestCase):
    """r2's phase-2 expansion, bounded on both axes and capped where the rows are.

    A query can group into as many sessions as retrieve_raw returned, and a
    session has no size limit, so an unbounded expansion is an unbounded read on
    the hottest surface in the codebase.
    """

    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _seed(self, sessions, turns_each):
        for s in range(sessions):
            for t in range(turns_each):
                self.core.capture.observe(
                    "migration planning session %d turn %d" % (s, t), "",
                    session_id="sess%d" % s)
        self.core.process_pending()

    def _spy_on_session_reads(self):
        calls = []
        real = self.core.store.get_events_by_session

        def spy(session_id, since_seq=0, types=None, limit=None):
            calls.append({"sid": session_id, "types": types, "limit": limit})
            return real(session_id, since_seq, types, limit)

        self.core.store.get_events_by_session = spy
        return calls

    def test_events_by_session_filters_and_limits_in_sql(self):
        """The store does the filtering and the slicing, not the caller."""
        self.core.capture.observe("I am Pat Testley", "", session_id="sess0")
        self._seed(1, 12)
        rows = self.core.store.get_events_by_session("sess0", types=("observed",), limit=5)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r["type"] == "observed" for r in rows))
        self.assertEqual([r["seq"] for r in rows], sorted(r["seq"] for r in rows))
        # The type filter is doing real work on this fixture: extraction wrote
        # `asserted` events into the same session.
        every = self.core.store.get_events_by_session("sess0")
        self.assertIn("asserted", {r["type"] for r in every})
        self.assertGreater(len(every), len(rows))

    def test_expansion_is_one_capped_query_per_session(self):
        self._seed(3, 40)
        calls = self._spy_on_session_reads()
        self.core.retrieval.get_context("migration planning", token_budget=4000)
        self.assertTrue(calls, "session-window expansion never ran")
        self.assertEqual(len(calls), len({c["sid"] for c in calls}),
                         f"one query per session, not one per turn: {calls!r}")
        for c in calls:
            self.assertEqual(c["types"], ("observed",))
            self.assertEqual(c["limit"], 60, "default context.session_window_max_events")

    def test_max_sessions_caps_how_many_are_expanded(self):
        core = ChronicleCore(self.home + "-cap", {
            "embeddings": {"model": "hashing"},
            "context": {"session_window_max_sessions": 2}})
        try:
            core.initialize("s1", principal_id="assistant")
            for s in range(6):
                for t in range(6):
                    core.capture.observe("migration planning session %d turn %d" % (s, t),
                                         "", session_id="sess%d" % s)
            core.process_pending()
            calls = []
            real = core.store.get_events_by_session

            def spy(session_id, since_seq=0, types=None, limit=None):
                calls.append(session_id)
                return real(session_id, since_seq, types, limit)

            core.store.get_events_by_session = spy
            core.retrieval.get_context("migration planning", token_budget=8000)
            self.assertLessEqual(len(calls), 2, f"expanded more sessions than the cap: {calls!r}")
        finally:
            shutil.rmtree(self.home + "-cap", ignore_errors=True)

    def test_zero_limit_returns_nothing_and_reads_nothing(self):
        self._seed(1, 4)
        calls = self._spy_on_session_reads()
        out = self.core.retrieval._expand_session_window("sess0", "assistant", set(), limit=0)
        self.assertEqual(out, [])
        self.assertEqual(calls, [], "a zero cap must not issue the query at all")

    def test_cap_config_is_clamped_not_trusted(self):
        """A cap that a bad config value can switch off is not a cap."""
        from engine.config import Config
        from engine.retrieval import _clamp_cfg
        key = "context.session_window_max_events"
        self.assertEqual(_clamp_cfg(Config({"context": {"session_window_max_events": None}}),
                                    key, 60, 1, 1000), 60)
        self.assertEqual(_clamp_cfg(Config({"context": {"session_window_max_events": "nope"}}),
                                    key, 60, 1, 1000), 60)
        self.assertEqual(_clamp_cfg(Config({"context": {"session_window_max_events": -5}}),
                                    key, 60, 1, 1000), 1)
        self.assertEqual(_clamp_cfg(Config({"context": {"session_window_max_events": 10 ** 9}}),
                                    key, 60, 1, 1000), 1000)
        self.assertEqual(_clamp_cfg(None, key, 60, 1, 1000), 60)


class _BatchSpyEmbedder:
    """Real vectors (hashing), but it counts how it was asked for them."""

    model = "spy-v1"
    dimensions = 8

    def __init__(self):
        self.singles = 0
        self.batches = 0
        self._h = HashingEmbedder(dimensions=8)

    def embed(self, text):
        self.singles += 1
        return self._h.embed(text)

    def embed_batch(self, texts, chunk=64):
        self.batches += 1
        return [self._h.embed(t) for t in texts]


class TestBulkAppendBatchesEmbeddings(unittest.TestCase):
    """capture.append_many is an ingest optimisation and nothing more: it must
    produce the same store as the append() loop it replaces."""

    def _specs(self, n):
        return [{"type": "observed",
                 "payload": {"source_type": "session_transcript",
                             "excerpt": "User: turn %d about travel\nAssistant: noted" % i,
                             "source_ref": "s1"},
                 "actor": "user", "session_id": "s1",
                 "occurred_at": "2026-08-01T10:%02d:00Z" % i}
                for i in range(n)]

    def _run(self, bulk):
        core, home = make_core()
        spy = _BatchSpyEmbedder()
        core.reducer.embedder = spy
        try:
            core.initialize("s1", principal_id="assistant")
            spy.singles = spy.batches = 0
            specs = self._specs(20)
            if bulk:
                core.capture.append_many(specs)
            else:
                for s in specs:
                    s = dict(s)
                    core.capture.append(s.pop("type"), s.pop("payload"), **s)
            events = [{k: r[k] for k in ("event_id", "seq", "type", "payload", "actor",
                                         "session_id", "occurred_at")}
                      for r in core.store.get_events_by_session("s1", types=("observed",))]
            vectors = {r["event_id"]: r["embedding"]
                       for r in core.store.iter_observed_vectors()}
            return events, vectors, spy
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_append_many_is_equivalent_to_the_append_loop(self):
        loop_events, loop_vectors, loop_spy = self._run(bulk=False)
        bulk_events, bulk_vectors, bulk_spy = self._run(bulk=True)
        self.assertEqual(len(loop_events), 20)
        self.assertEqual(loop_events, bulk_events)      # same ids, order, payloads
        self.assertEqual(loop_vectors, bulk_vectors)    # byte-identical vectors
        # ...bought with one round trip instead of twenty.
        self.assertEqual((loop_spy.batches, loop_spy.singles), (0, 20))
        self.assertEqual((bulk_spy.batches, bulk_spy.singles), (1, 0))

    def test_prefetch_failure_falls_back_to_single_embeds(self):
        """The cache is an optimisation; a backend that cannot batch must not
        cost a single vector."""
        core, home = make_core()
        spy = _BatchSpyEmbedder()

        def broken(texts, chunk=64):
            spy.batches += 1
            raise RuntimeError("batch endpoint down")

        spy.embed_batch = broken
        core.reducer.embedder = spy
        try:
            core.initialize("s1", principal_id="assistant")
            spy.singles = spy.batches = 0
            core.capture.append_many(self._specs(6))
            self.assertEqual(spy.batches, 1)
            self.assertEqual(spy.singles, 6)
            self.assertEqual(len(core.store.iter_observed_vectors()), 6)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_extraction_batches_its_asserted_items(self):
        core, home = make_core()
        spy = _BatchSpyEmbedder()
        core.reducer.embedder = spy
        try:
            core.initialize("s1", principal_id="assistant")
            core.capture.observe(
                "I am Pat Testley\nI live in Springfield\nI work at Acme Fake Co", "",
                session_id="s1")
            spy.singles = spy.batches = 0
            core.process_pending()
            # One extract job, four vectored items (3 facts + the episode), one
            # round trip. Without the prefetch each item blocks on its own embed.
            self.assertEqual(spy.batches, 1, "extraction embedded its items one at a time")
            # The single that remains is the u2 digest note, written by a LATER
            # job than the one that batched; the four extraction items are not.
            self.assertLessEqual(spy.singles, 1)
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestCurationQueueDedup(unittest.TestCase):
    """Unconditional enqueues (u2's per-subject digest, canonicalize) must not
    make the drain replay one answer N times."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.store = MemoryStore(os.path.join(self.home, "c.db"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_identical_pending_job_is_collapsed(self):
        first = self.store.enqueue_curation("digest", {"entity_id": "e1"})
        self.assertIsNotNone(first)
        self.assertIsNone(self.store.enqueue_curation("digest", {"entity_id": "e1"}))
        self.assertIsNotNone(self.store.enqueue_curation("digest", {"entity_id": "e2"}))
        self.assertIsNotNone(self.store.enqueue_curation("canonicalize", {"entity_id": "e1"}))
        self.assertEqual(self.store.count_rows("curation_jobs", "1=1"), 3)

    def test_dedup_key_is_canonical_not_dict_order(self):
        self.store.enqueue_curation("canonicalize", {"subjects": [], "owner": "default"})
        self.assertIsNone(self.store.enqueue_curation(
            "canonicalize", {"owner": "default", "subjects": []}))

    def test_a_finished_job_can_be_queued_again(self):
        """Collapsing pending work must not turn into refusing new work: the
        guard is 'already queued', not 'ever queued'."""
        self.store.enqueue_curation("digest", {"entity_id": "e1"})
        job = self.store.claim_curation_job()
        self.assertIsNone(self.store.enqueue_curation("digest", {"entity_id": "e1"}),
                          "a running job still counts as queued")
        self.store.complete_curation_job(job["id"])
        self.assertIsNotNone(self.store.enqueue_curation("digest", {"entity_id": "e1"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
