"""
Chronicle — E5 acceptance tests: novelty scoring + near-duplicate merge (issue #8).

Covers the two defects that got the first E5 attempt review-rejected:

  (1) CRITICAL migration bug: `novelty REAL` was added to the 6 belief tables
      only via `CREATE TABLE IF NOT EXISTS`, a no-op on a DB that already has
      those tables. SCHEMA_VERSION never bumped and there was no ALTER TABLE,
      so reopening a pre-E5 DB crashed on the first fact write:
      OperationalError: table facts has no column named novelty.

  (2) Spec acceptance unmet: an identical re-assertion through the REAL
      capture pipeline produced 1 item but only 1 provenance entry, because
      the pre-existing _apply_fact_conflict/_confirm short-circuits resolved
      the re-assertion before the new near-duplicate-merge code ever ran.
      Zero test coverage existed for this.

TestOldSchemaMigration exercises (1). TestIdenticalReassertionProvenance and
TestDistinctFactsGetNovelty exercise (2) plus the intended novelty behavior,
through the real CaptureEngine/Reducer/MemoryStore stack — no mocks.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.capture import CaptureEngine
from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder
from engine.reducer import Reducer
from engine.store import BELIEF_TABLES, SCHEMA_VERSION, MemoryStore, _has_col

# ---------------------------------------------------------------------------
# The pre-E5 (schema_version 5) shape of the 6 belief tables, copied verbatim
# from the v550 baseline — i.e. WITHOUT `novelty`. Used to build a DB file
# that predates E5 by hand, the way a real upgrade would find one on disk.
# ---------------------------------------------------------------------------
_PRE_E5_BELIEF_SCHEMA = """
CREATE TABLE facts (
    belief_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, attribute TEXT NOT NULL,
    predicate_canonical TEXT, value TEXT NOT NULL, value_type TEXT DEFAULT 'string',
    value_num REAL, value_ts TEXT, qualifiers TEXT NOT NULL DEFAULT '{}',
    qualifiers_hash TEXT NOT NULL DEFAULT '', pointer_id TEXT, confirm_count INTEGER DEFAULT 0,
    contradiction_count INTEGER DEFAULT 0, last_confirmed_at TEXT, extractor_version TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT DEFAULT 'active',
    salience TEXT DEFAULT 'normal', criticality TEXT DEFAULT 'normal', criticality_reason TEXT,
    confidence REAL DEFAULT 0.8 CHECK(confidence BETWEEN 0 AND 1), trust_level INTEGER,
    valid_from TEXT, valid_until TEXT, superseded_by TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT DEFAULT 'verbatim', utility REAL DEFAULT 0, purpose_scope TEXT NOT NULL DEFAULT '["*"]',
    consent TEXT, provenance TEXT NOT NULL, verification TEXT DEFAULT '{"status":"unverified"}',
    rule_id TEXT, premises TEXT);
CREATE INDEX idx_facts_active ON facts(entity_id, predicate_canonical) WHERE status='active';

CREATE TABLE episodes (
    belief_id TEXT PRIMARY KEY, title TEXT, summary TEXT, participants TEXT DEFAULT '[]',
    occurred_at TEXT, session_ref TEXT, derived_facts TEXT DEFAULT '[]', pointer_id TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT,
    criticality TEXT DEFAULT 'normal', criticality_reason TEXT, confidence REAL, trust_level INTEGER,
    valid_from TEXT, valid_until TEXT, superseded_by TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT, utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT,
    verification TEXT DEFAULT '{"status":"unverified"}');

CREATE TABLE notes (
    belief_id TEXT PRIMARY KEY, note_type TEXT CHECK(note_type IN ('procedure','norm','belief')),
    subject TEXT, body TEXT, body_hash TEXT, imperative INTEGER DEFAULT 0, always_inject INTEGER DEFAULT 0,
    risk_tier TEXT DEFAULT 'low' CHECK(risk_tier IN ('low','high')),
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT,
    criticality TEXT DEFAULT 'normal', criticality_reason TEXT, confidence REAL, trust_level INTEGER,
    valid_from TEXT, valid_until TEXT, superseded_by TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT, utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT,
    verification TEXT DEFAULT '{"status":"unverified"}');

CREATE TABLE refs (
    belief_id TEXT PRIMARY KEY, topic TEXT, retrieval_url TEXT, retrieved_at TEXT,
    ttl_days INTEGER DEFAULT 30, cached_summary TEXT, stale_after TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT DEFAULT 'normal',
    criticality TEXT DEFAULT 'normal', confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT,
    superseded_by TEXT, created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim',
    utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT);

CREATE TABLE relationships (
    belief_id TEXT PRIMARY KEY, source_id TEXT, predicate TEXT, target_id TEXT, external_ref TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT DEFAULT 'normal',
    criticality TEXT DEFAULT 'normal', confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT,
    superseded_by TEXT, created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim',
    utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT,
    rule_id TEXT, premises TEXT);

CREATE TABLE procedures (
    belief_id TEXT PRIMARY KEY, name TEXT, params TEXT, steps TEXT, success_criteria TEXT,
    derived_from TEXT DEFAULT '[]', domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT,
    status TEXT, salience TEXT DEFAULT 'normal', criticality TEXT DEFAULT 'normal',
    confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT, superseded_by TEXT,
    created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim', utility REAL DEFAULT 0,
    purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def make_core(extra_cfg=None):
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    if extra_cfg:
        cfg.update(extra_cfg)
    return ChronicleCore(home, cfg), home


class TestOldSchemaMigration(unittest.TestCase):
    """(a) Reopening a pre-E5 DB must not crash, and must gain `novelty` on
    every belief table — the exact defect that got the first attempt rejected."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        # Build a genuinely pre-E5 database by hand: old-shape belief tables
        # (no novelty column), stamped at the old schema_version — nothing
        # from current code is involved in creating this file.
        conn = sqlite3.connect(self.tmp.name)
        conn.executescript(_PRE_E5_BELIEF_SCHEMA)
        conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '5')")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_migration_adds_novelty_to_all_belief_tables_without_crashing(self):
        # Opening the store runs _init_db -> _migrate. Before the fix this left
        # the pre-existing tables exactly as they were (CREATE TABLE IF NOT
        # EXISTS is a no-op here) and schema_version stuck at 5.
        store = MemoryStore(self.tmp.name)
        for t in BELIEF_TABLES:
            self.assertTrue(_has_col(store._conn(), t, "novelty"),
                            f"{t} missing novelty column after migration")
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))

    def test_first_fact_write_survives_reopen(self):
        # This is the literal crash from the review: OperationalError: table
        # facts has no column named novelty, on the FIRST write after reopen.
        store = MemoryStore(self.tmp.name)
        reducer = Reducer(store, embedder=HashingEmbedder())
        store.reducer = reducer
        cap = CaptureEngine(store, reducer)
        key = {"entity_id": "user", "predicate_canonical": "name", "attribute": "name",
               "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"}
        cap.append("asserted", {"kind": "fact", "key": key, "body": "Pat",
                                "confidence": 0.9, "source_event": "ev_migrate",
                                "source_type": "user_direct", "domain": "user"},
                   actor="user", owner="default")
        facts = store.query_beliefs("facts", "predicate_canonical='name' AND status='active'")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["value"], "Pat")
        self.assertIn("novelty", facts[0])


class TestIdenticalReassertionProvenance(unittest.TestCase):
    """(b) An identical re-assertion through the REAL capture pipeline
    (capture.append -> process_pending) must yield exactly 1 active item with
    2 provenance entries — not 1 item and 1 provenance entry, which is the
    defect the review caught (pre-existing _confirm short-circuits dropped
    the second sighting on the floor before the new merge code ever ran)."""

    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_identical_fact_reassertion_fact_branch(self):
        key = {"entity_id": "user", "predicate_canonical": "name", "attribute": "name",
               "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"}

        def payload(src):
            return {"kind": "fact", "key": key, "body": "Pat", "confidence": 0.85,
                    "source_event": src, "source_type": "user_direct", "domain": "user"}

        self.core.capture.append("asserted", payload("ev_src_1"), actor="user", owner="default")
        self.core.capture.append("asserted", payload("ev_src_2"), actor="user", owner="default")
        self.core.process_pending()

        facts = self.core.store.query_beliefs("facts", "predicate_canonical='name' AND status='active'")
        self.assertEqual(len(facts), 1, "identical re-assertion must not create a second item")
        prov = json.loads(facts[0]["provenance"])
        self.assertEqual(len(prov.get("provenances", [])), 2,
                         "second sighting of the same fact must leave its own provenance entry")
        self.assertGreaterEqual(facts[0]["confirm_count"], 1)

    def test_identical_note_reassertion_non_fact_branch(self):
        # note_type + subject + body_hash is how _find_existing matches an existing
        # note, so the key must carry the same body the payload asserts.
        body = "Some durable directive text"
        key = {"note_type": "belief", "subject": "e5-test-subject", "body": body}

        def payload(src):
            return {"kind": "note", "key": key, "body": body, "confidence": 0.8,
                    "source_event": src, "source_type": "user_direct", "domain": "user"}

        self.core.capture.append("asserted", payload("ev_note_1"), actor="user", owner="default")
        self.core.capture.append("asserted", payload("ev_note_2"), actor="user", owner="default")
        self.core.process_pending()

        notes = self.core.store.query_beliefs(
            "notes", "subject='e5-test-subject' AND status='active'")
        self.assertEqual(len(notes), 1, "identical re-assertion must not create a second item")
        prov = json.loads(notes[0]["provenance"])
        self.assertEqual(len(prov.get("provenances", [])), 2,
                         "second sighting of the same note must leave its own provenance entry")


class TestDistinctFactsGetNovelty(unittest.TestCase):
    """(c) A genuinely distinct (non-duplicate) fact stores normally, with
    novelty populated once there is something to compare it against."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store, embedder=HashingEmbedder())
        self.store.reducer = self.reducer
        self.cap = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_second_distinct_fact_gets_populated_novelty(self):
        # Same entity+predicate (so _calculate_novelty has something of the same
        # kind/subject to compare against) but different qualifiers, so they are
        # NOT a conflict (_find_existing keys on qualifiers_hash too) — a
        # multi-valued predicate like "likes" behaves exactly this way in practice.
        def key(qh, item):
            return {"entity_id": "user", "predicate_canonical": "likes", "attribute": "likes",
                    "qualifiers_hash": qh, "qualifiers": {"item": item},
                    "owner": "default", "domain": "user"}

        self.cap.append("asserted", {"kind": "fact", "key": key("q1", "skiing"),
                                     "body": "skiing in the winter", "confidence": 0.9,
                                     "source_event": "ev1", "source_type": "user_direct",
                                     "domain": "user"}, actor="user", owner="default")
        self.cap.append("asserted", {"kind": "fact", "key": key("q2", "cooking"),
                                     "body": "cooking italian food", "confidence": 0.9,
                                     "source_event": "ev2", "source_type": "user_direct",
                                     "domain": "user"}, actor="user", owner="default")

        facts = self.store.query_beliefs("facts", "predicate_canonical='likes' AND status='active'",
                                         (), 10, order="qualifiers_hash")
        self.assertEqual(len(facts), 2, "distinct qualifiers must not be merged/conflicted")
        by_qh = {f["qualifiers_hash"]: f for f in facts}
        # First-ever item of its KIND: nothing to compare against, which is
        # maximal novelty — 1.0, not NULL. NULL means "not computed", and the
        # first E5 pass wrote NULL on nearly every item because it compared
        # against same-SUBJECT items only and the common case is the first item
        # of its subject; the spec's scope is same-KIND.
        self.assertEqual(by_qh["q1"]["novelty"], 1.0)
        # Second: compared against the first's vector, so novelty is a real score.
        novelty2 = by_qh["q2"]["novelty"]
        self.assertIsNotNone(novelty2)
        self.assertGreaterEqual(novelty2, 0.0)
        self.assertLessEqual(novelty2, 1.0)


class TestNoEmbedderDegradePath(unittest.TestCase):
    """(d) With no embedder configured, novelty computation is skipped
    entirely (not attempted-and-failed) and the belief still stores normally —
    the "store as today" behavior the migration must not regress."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store)          # embedder=None, the default
        self.store.reducer = self.reducer
        self.cap = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_fact_stores_with_null_novelty_no_embedder(self):
        key = {"entity_id": "user", "predicate_canonical": "name", "attribute": "name",
               "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"}
        self.cap.append("asserted", {"kind": "fact", "key": key, "body": "Pat",
                                     "confidence": 0.9, "source_event": "ev_noembed",
                                     "source_type": "user_direct", "domain": "user"},
                        actor="user", owner="default")
        facts = self.store.query_beliefs("facts", "predicate_canonical='name' AND status='active'")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["value"], "Pat")
        self.assertIsNone(facts[0]["novelty"])

    def test_second_identical_fact_still_confirms_and_appends_provenance_no_embedder(self):
        # The provenance-merge fix must not depend on an embedder being present —
        # only the near-duplicate MERGE path (_calculate_novelty) needs one.
        key = {"entity_id": "user", "predicate_canonical": "city", "attribute": "city",
               "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"}

        def payload(src):
            return {"kind": "fact", "key": key, "body": "Denver", "confidence": 0.9,
                    "source_event": src, "source_type": "user_direct", "domain": "user"}

        self.cap.append("asserted", payload("ev_a"), actor="user", owner="default")
        self.cap.append("asserted", payload("ev_b"), actor="user", owner="default")

        facts = self.store.query_beliefs("facts", "predicate_canonical='city' AND status='active'")
        self.assertEqual(len(facts), 1)
        prov = json.loads(facts[0]["provenance"])
        self.assertEqual(len(prov.get("provenances", [])), 2)


class TestCrossSubjectMergeIsStructurallyImpossible(unittest.TestCase):
    """The critical defect of the second E5 pass: merge candidates for every
    kind WITHOUT a subject column (episode, reference, procedure) were selected
    on owner+domain alone, so any two same-kind items above dup_similarity
    merged — and the second one's content was destroyed. Episodes are emitted
    for every turn over 60 characters, so this was the highest-volume write
    path in the system silently eating unrelated content.

    Each test below is a pair of items that are near-identical in TEXT and
    unrelated in IDENTITY. Both must survive.
    """

    _T1 = ("Reminder for the Monday standup: the Acme Fake Co migration plan must be "
           "finished before the end of the month, and Pat Testley owns the rollback step.")
    _T2 = ("Reminder for the Friday retro: the Acme Fake Co migration plan must be "
           "finished before the end of the month, and Pat Testley owns the rollback step.")

    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("sess_A", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _assert_kind(self, kind, key, body, src):
        self.core.capture.append(
            "asserted", {"kind": kind, "key": key, "body": body, "confidence": 0.85,
                         "source_event": src, "source_type": "user_direct", "domain": "user"},
            actor="user", owner="default")
        self.core.process_pending()

    def test_two_sessions_near_identical_turns_keep_both_episodes(self):
        from engine.embeddings import cosine
        emb = self.core.embedder
        sim = cosine(emb.embed(self._T1[:400]), emb.embed(self._T2[:400]))
        # If the fixture ever drops below the threshold the test proves nothing.
        self.assertGreaterEqual(sim, 0.95, "fixture must exceed dup_similarity")

        self.core.capture.append("observed", {"excerpt": self._T1, "session_id": "sess_A"},
                                 actor="user", owner="default")
        self.core.process_pending()
        self.core.initialize("sess_B", principal_id="assistant")
        self.core.capture.append("observed", {"excerpt": self._T2, "session_id": "sess_B"},
                                 actor="user", owner="default")
        self.core.process_pending()

        eps = self.core.store.query_beliefs("episodes", "status='active'", (), 20, order="title")
        titles = [e["title"] for e in eps]
        self.assertEqual(len(eps), 2,
                         "two different sessions' episodes were merged into one: %r" % titles)
        self.assertTrue(any("Friday retro" in t for t in titles), titles)
        self.assertTrue(any("Monday standup" in t for t in titles), titles)

    def test_references_with_different_topic_and_url_both_survive(self):
        body = "Acme Fake Co revenue summary for the quarter"
        self._assert_kind("reference", {"topic": "acme quarterly report",
                                        "retrieval_url": "https://example.invalid/a"}, body, "evr1")
        self._assert_kind("reference", {"topic": "beta annual filing",
                                        "retrieval_url": "https://example.invalid/b"}, body, "evr2")
        refs = self.core.store.query_beliefs("refs", "status='active'", (), 10, order="topic")
        self.assertEqual([r["topic"] for r in refs],
                         ["acme quarterly report", "beta annual filing"])

    def test_procedures_with_different_names_both_survive(self):
        body = "run the standard deployment script"
        self._assert_kind("procedure", {"name": "deploy_alpha", "params": [], "steps": ["run script"]},
                          body, "evp1")
        self._assert_kind("procedure", {"name": "deploy_beta", "params": [], "steps": ["run script"]},
                          body, "evp2")
        procs = self.core.store.query_beliefs("procedures", "status='active'", (), 10, order="name")
        self.assertEqual([p["name"] for p in procs], ["deploy_alpha", "deploy_beta"])

    def test_notes_with_different_subjects_both_survive(self):
        body = "Always run the migration in a maintenance window"
        self._assert_kind("note", {"note_type": "belief", "subject": "acme-migration"}, body, "evn1")
        self._assert_kind("note", {"note_type": "belief", "subject": "beta-migration"}, body, "evn2")
        notes = self.core.store.query_beliefs("notes", "status='active'", (), 10, order="subject")
        self.assertEqual([n["subject"] for n in notes], ["acme-migration", "beta-migration"])

    def test_same_natural_key_still_merges(self):
        """The guard must not disable merging: identical items under the SAME
        natural key still collapse to one row with two provenance entries."""
        body = "Acme Fake Co revenue summary for the quarter"
        key = {"topic": "acme quarterly report", "retrieval_url": "https://example.invalid/a"}
        self._assert_kind("reference", key, body, "evr1")
        self._assert_kind("reference", key, body, "evr2")
        refs = self.core.store.query_beliefs("refs", "status='active'", (), 10)
        self.assertEqual(len(refs), 1, "same-URL, same-text reference must merge")
        prov = json.loads(refs[0]["provenance"])
        self.assertEqual(len(prov.get("provenances", [])), 2)

    def test_same_episode_title_and_session_still_merges(self):
        key = {"title": "Weekly sync", "session_ref": "sess_A"}
        body = "The team walked through the Acme Fake Co migration plan in detail"
        self._assert_kind("episode", key, body, "eve1")
        self._assert_kind("episode", key, body, "eve2")
        eps = self.core.store.query_beliefs("episodes", "status='active'", (), 10)
        self.assertEqual(len(eps), 1)
        prov = json.loads(eps[0]["provenance"])
        self.assertEqual(len(prov.get("provenances", [])), 2)


class TestNoveltyIsScopedToKindNotSubject(unittest.TestCase):
    """novelty = 1 − max cosine over same-KIND vectors (§E5), so a duplicate
    text under a DIFFERENT subject scores near zero novelty — while still being
    stored, because novelty is a score and merging is a separate decision."""

    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _fact(self, entity, predicate, body, src):
        key = {"entity_id": entity, "predicate_canonical": predicate, "attribute": predicate,
               "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"}
        self.core.capture.append(
            "asserted", {"kind": "fact", "key": key, "body": body, "confidence": 0.85,
                         "source_event": src, "source_type": "user_direct", "domain": "user"},
            actor="user", owner="default")
        self.core.process_pending()

    def test_identical_text_under_a_different_subject_scores_zero_novelty_and_is_kept(self):
        self._fact("pat_testley", "works_at", "Acme Fake Co", "ev1")
        self._fact("sam_vimes", "works_at", "Acme Fake Co", "ev2")
        rows = self.core.store.query_beliefs(
            "facts", "predicate_canonical='works_at' AND status='active'", (), 10,
            order="entity_id")
        self.assertEqual([r["entity_id"] for r in rows], ["pat_testley", "sam_vimes"])
        self.assertEqual(rows[0]["novelty"], 1.0)       # first of its kind
        self.assertLess(rows[1]["novelty"], 0.01)       # same kind, same text, other subject
        self.assertGreaterEqual(rows[1]["novelty"], 0.0)

    def test_first_write_of_every_kind_gets_novelty_one(self):
        self._fact("pat_testley", "works_at", "Acme Fake Co", "ev1")
        for kind, table, key in (
                ("episode", "episodes", {"title": "Kickoff", "session_ref": "s1"}),
                ("note", "notes", {"note_type": "belief", "subject": "acme"}),
                ("reference", "refs", {"topic": "acme filing",
                                       "retrieval_url": "https://example.invalid/x"}),
                ("procedure", "procedures", {"name": "deploy_alpha", "params": [],
                                             "steps": ["run script"]})):
            self.core.capture.append(
                "asserted", {"kind": kind, "key": key,
                             "body": "Acme Fake Co migration groundwork for the quarter",
                             "confidence": 0.85, "source_event": "ev_%s" % kind,
                             "source_type": "user_direct", "domain": "user"},
                actor="user", owner="default")
            self.core.process_pending()
            rows = self.core.store.query_beliefs(table, "status='active'", (), 10)
            self.assertEqual(len(rows), 1, kind)
            self.assertEqual(rows[0]["novelty"], 1.0,
                             "%s: first item of its kind must score 1.0, not NULL" % kind)


class TestNoveltyBeyondTheOldHundredItemWindow(unittest.TestCase):
    """Candidate retrieval must be a nearest-neighbour query over ALL same-kind
    vectors, not `query_beliefs(limit=100)` with no ORDER BY — which is the
    OLDEST 100 rows by rowid. Past 100 items of a kind, that window stopped
    containing anything recent, so a fresh duplicate of the newest item scored
    as fully novel and was stored twice, silently."""

    N = 120

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        self.reducer = Reducer(self.store, embedder=HashingEmbedder())
        self.store.reducer = self.reducer
        self.cap = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        os.unlink(self.tmp.name)

    @staticmethod
    def _body(i):
        # Pairwise-disjoint tokens, so no two setup items are near-duplicates of
        # each other and the only near-duplicate in the store is the one the
        # test introduces on purpose.
        return "quokka%03d zeppelin%03d marmalade%03d tapioca%03d" % (i, i, i, i)

    def _write(self, qh, body, src):
        key = {"entity_id": "pat_testley", "predicate_canonical": "likes", "attribute": "likes",
               "qualifiers_hash": qh, "qualifiers": {"n": qh}, "owner": "default",
               "domain": "user"}
        self.cap.append("asserted", {"kind": "fact", "key": key, "body": body,
                                     "confidence": 0.9, "source_event": src,
                                     "source_type": "user_direct", "domain": "user"},
                        actor="user", owner="default")

    def test_duplicate_of_the_newest_item_is_detected_past_the_old_window(self):
        for i in range(self.N):
            self._write("q%03d" % i, self._body(i), "ev%03d" % i)
        rows = self.store.query_beliefs("facts", "status='active'", (), 500)
        self.assertEqual(len(rows), self.N, "setup items must be pairwise distinct")

        newest_body = self._body(self.N - 1)
        self._write("q_dup", newest_body, "ev_dup")

        rows = self.store.query_beliefs("facts", "status='active'", (), 500)
        self.assertEqual(len(rows), self.N,
                         "a duplicate of the NEWEST item was stored again: the candidate "
                         "window is still bounded to the oldest rows")
        target = [r for r in rows if r["value"] == newest_body]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["occurrence_count"], 2)
        prov = json.loads(target[0]["provenance"])
        self.assertEqual(len(prov.get("provenances", [])), 2)

    def test_a_distinct_item_past_the_window_still_scores_far_more_novel(self):
        """Novelty itself must not degrade past 100 items either: the distinct
        item is scored against all N, and a duplicate of item N-1 — which the
        old oldest-100 window could not see at all — scores ~0."""
        for i in range(self.N):
            self._write("q%03d" % i, self._body(i), "ev%03d" % i)
        self._write("q_new", "wombat marzipan trombone glacier", "ev_new")
        distinct = self.store.query_beliefs("facts", "qualifiers_hash='q_new'", (), 1)[0]
        self.assertIsNotNone(distinct["novelty"])
        self.assertGreater(distinct["novelty"], 0.5)

        # A near-duplicate of the NEWEST item, under a different subject so the
        # merge cannot fire and the score itself is what gets stored.
        key = {"entity_id": "sam_vimes", "predicate_canonical": "likes", "attribute": "likes",
               "qualifiers_hash": "q_echo", "qualifiers": {}, "owner": "default", "domain": "user"}
        self.cap.append("asserted", {"kind": "fact", "key": key, "body": self._body(self.N - 1),
                                     "confidence": 0.9, "source_event": "ev_echo",
                                     "source_type": "user_direct", "domain": "user"},
                        actor="user", owner="default")
        echo = self.store.query_beliefs("facts", "qualifiers_hash='q_echo'", (), 1)[0]
        self.assertLess(echo["novelty"], 0.01,
                        "the newest item was invisible to the novelty scan")
        self.assertLess(echo["novelty"], distinct["novelty"])


class TestMergeLeavesNoOrphanJustification(unittest.TestCase):
    """I5: every justification must support a belief that exists. The merge path
    returned early from _insert_belief without inserting anything, while the
    caller went on to justify the belief_id that was never written — 1 fact row,
    2 justifications, 1 of them pointing at nothing."""

    A = "skiing in the winter"
    B = "skiing in the winter months"      # cosine(A, B) = 0.894 under HashingEmbedder

    def setUp(self):
        self.core, self.home = make_core({"curation": {"dup_similarity": 0.85}})
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_merged_assertion_justifies_the_surviving_belief(self):
        for qh, body, src in (("q1", self.A, "ev1"), ("q2", self.B, "ev2")):
            key = {"entity_id": "pat_testley", "predicate_canonical": "likes", "attribute": "likes",
                   "qualifiers_hash": qh, "qualifiers": {}, "owner": "default", "domain": "user"}
            self.core.capture.append(
                "asserted", {"kind": "fact", "key": key, "body": body, "confidence": 0.85,
                             "source_event": src, "source_type": "user_direct", "domain": "user"},
                actor="user", owner="default")
            self.core.process_pending()

        facts = self.core.store.query_beliefs("facts", "status='active'", (), 10)
        self.assertEqual(len(facts), 1, "fixture must actually merge")
        survivor = facts[0]["belief_id"]

        conn = self.core.store._conn()
        live = set()
        for t in BELIEF_TABLES + ["entities"]:
            live |= {r[0] for r in conn.execute("SELECT belief_id FROM %s" % t).fetchall()}
        rows = conn.execute("SELECT belief_id, support FROM justifications").fetchall()
        orphans = [dict(r) for r in rows if r["belief_id"] not in live]
        self.assertEqual(orphans, [], "merge left justifications with no belief")
        # ...and the merged-away event still supports the survivor.
        supports = {r["support"] for r in rows if r["belief_id"] == survivor}
        self.assertIn("ev2", supports)


class TestOccurrenceCountForEveryKind(unittest.TestCase):
    """D5 resolution: an explicit `occurrence_count` column on all six belief
    tables (schema_version 7), defaulted to 1, incremented by BOTH paths that
    fold a second sighting into an existing row — the near-duplicate merge and
    the identical re-assertion. Counting via facts' `confirm_count` alone left
    every other kind with no count at all, since facts are the only table that
    ever had that column."""

    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _assert_kind(self, kind, key, body, src):
        self.core.capture.append(
            "asserted", {"kind": kind, "key": key, "body": body, "confidence": 0.85,
                         "source_event": src, "source_type": "user_direct", "domain": "user"},
            actor="user", owner="default")
        self.core.process_pending()

    def test_fresh_item_counts_one_and_a_merge_counts_two_for_every_kind(self):
        cases = (
            ("episode", "episodes", {"title": "Weekly sync", "session_ref": "s1"},
             "The team walked through the Acme Fake Co migration plan in detail"),
            ("reference", "refs", {"topic": "acme filing",
                                   "retrieval_url": "https://example.invalid/a"},
             "Acme Fake Co revenue summary for the quarter"),
            ("procedure", "procedures", {"name": "deploy_alpha", "params": [],
                                         "steps": ["run script"]},
             "run the standard deployment script before the window closes"),
        )
        for kind, table, key, body in cases:
            self._assert_kind(kind, key, body, "ev_%s_1" % kind)
            rows = self.core.store.query_beliefs(table, "status='active'", (), 10)
            self.assertEqual(rows[0]["occurrence_count"], 1, "%s: fresh item counts 1" % kind)
            self._assert_kind(kind, key, body, "ev_%s_2" % kind)
            rows = self.core.store.query_beliefs(table, "status='active'", (), 10)
            self.assertEqual(len(rows), 1, kind)
            self.assertEqual(rows[0]["occurrence_count"], 2,
                             "%s: second sighting must be counted" % kind)

    def test_identical_fact_reassertion_counts_too(self):
        key = {"entity_id": "user", "predicate_canonical": "name", "attribute": "name",
               "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"}
        for src in ("ev_a", "ev_b", "ev_c"):
            self.core.capture.append(
                "asserted", {"kind": "fact", "key": key, "body": "Pat", "confidence": 0.85,
                             "source_event": src, "source_type": "user_direct", "domain": "user"},
                actor="user", owner="default")
        self.core.process_pending()
        facts = self.core.store.query_beliefs(
            "facts", "predicate_canonical='name' AND status='active'", (), 10)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["occurrence_count"], 3)

    def test_migration_adds_occurrence_count_to_a_pre_e5_database(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            conn = sqlite3.connect(tmp.name)
            conn.executescript(_PRE_E5_BELIEF_SCHEMA)
            conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '5')")
            conn.commit()
            conn.close()
            store = MemoryStore(tmp.name)
            for t in BELIEF_TABLES:
                self.assertTrue(_has_col(store._conn(), t, "occurrence_count"),
                                "%s missing occurrence_count after migration" % t)
            self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
