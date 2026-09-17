"""
Chronicle — dashboard/tapestry_api.py, the data behind the Tapestry memory navigator.

The Tapestry is a reader of the production store while Hermes writes it, so the
properties pinned here are the ones a wrong implementation would get away with
silently:

  * the delta-encoded event stream decodes to EXACTLY the log (seq, time, type,
    writer), across chunk boundaries;
  * every function is read-only: the store's bytes are unchanged afterwards and
    a write through the Tapestry connection is refused by SQLite itself;
  * inspectors connect a belief to the events that justify it, to what it
    replaced and what replaced it, and to what contradicts it — through the
    store's own tables, not a heuristic;
  * plugin_api.py mounts the routes when loaded the way the dashboard host loads
    it (by path, no parent package).

Fixtures use obviously fake values.
"""

import hashlib
import importlib.util
import os
import shutil
import sqlite3
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore

_DASH = Path(__file__).parent.parent / "dashboard"
CRON = "cron_abc123def456_20260917_010000"
CHAT = "20260917_010203_ab12cd"


_MISSING = object()


def _load(name, path, routes=None):
    """Load a dashboard module by path, the way the dashboard host does.

    With `routes`, a recording fastapi stub is installed for the duration of the
    load whatever is already in sys.modules (a real fastapi, or another test's
    stub), and the previous module is restored afterwards; so route recording
    works in every collection order and on a machine that has fastapi. Without
    `routes`, a stub is installed only if fastapi is absent."""
    prev = sys.modules.get("fastapi", _MISSING)
    install = routes is not None or prev is _MISSING
    if install:
        stub = types.ModuleType("fastapi")

        class _Router:
            def get(self, p, *a, **k):
                if routes is not None:
                    routes.append(("GET", p))
                return lambda fn: fn

            def post(self, p, *a, **k):
                if routes is not None:
                    routes.append(("POST", p))
                return lambda fn: fn

        stub.APIRouter = _Router
        stub.Query = lambda default=None, **k: default
        sys.modules["fastapi"] = stub
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if install:
            if prev is _MISSING:
                sys.modules.pop("fastapi", None)
            else:
                sys.modules["fastapi"] = prev
    return mod


A = _load("chronicle_tapestry_under_test", _DASH / "tapestry_api.py")


def _fact(core, entity, predicate, body, domain, confidence, session_id, src):
    core.capture.append("asserted", {
        "kind": "fact", "key": {"entity_id": entity, "predicate_canonical": predicate,
                                "attribute": predicate, "qualifiers_hash": "", "qualifiers": {}},
        "body": body, "confidence": confidence, "source_event": src,
        "source_type": "user_direct", "domain": domain},
        actor="user", owner="default", session_id=session_id)
    core.process_pending()


def _files_sha(db):
    h = hashlib.sha256()
    for ext in ("", "-wal"):
        p = db + ext
        if os.path.exists(p):
            h.update(open(p, "rb").read())
    return h.hexdigest()


class _TapestryCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = temp_home(prefix="tapestry-")
        core = ChronicleCore(cls.home, {"embeddings": {"model": "hashing"}})
        core.initialize(CRON, principal_id="assistant")
        core.capture.observe("Pat Testley said the Acme Fake Co offsite moved to Denver.",
                             "Noted.", session_id=CRON)
        core.capture.observe("Robin Placeholder will run the standup on Monday.",
                             "Understood.", session_id=CRON)
        core.process_pending()
        core.initialize(CHAT, principal_id="assistant")
        core.capture.observe("I like kayaking on weekends.", "Nice.", session_id=CHAT)
        core.capture.observe("We moved house last spring.", "Good to know.", session_id=CHAT)
        core.process_pending()
        # Facts cite the observed turn they were extracted from, as extraction does.
        conn = core.store._conn()
        cron_turns = [r[0] for r in conn.execute(
            "SELECT event_id FROM events WHERE session_id=? AND type='observed' ORDER BY seq", (CRON,))]
        chat_turns = [r[0] for r in conn.execute(
            "SELECT event_id FROM events WHERE session_id=? AND type='observed' ORDER BY seq", (CHAT,))]
        # a value history (agent domain: newer wins)
        _fact(core, "pat_testley", "works_at", "Acme Fake Co", "agent", 0.9, CRON, cron_turns[0])
        _fact(core, "pat_testley", "works_at", "Globex Fake Inc", "agent", 0.9, CRON, cron_turns[-1])
        # a contradiction (user domain: flag for review)
        _fact(core, "pat_testley", "lives_in", "Riverton", "user", 0.9, CHAT, chat_turns[0])
        _fact(core, "pat_testley", "lives_in", "Springfield", "user", 0.5, CHAT, chat_turns[-1])
        # two legacy identical active notes, as a pre-exact-merge store holds them,
        # plus the same text under ANOTHER subject, which is not a copy of them
        with core.store.transaction() as conn:
            for bid, subject in (("b_legacy_dup_1", "directive"), ("b_legacy_dup_2", "directive"),
                                 ("b_same_text_other_subject", "style guide")):
                conn.execute(
                    "INSERT INTO notes(belief_id, note_type, subject, body, owner, domain, status, "
                    "created_at, provenance) VALUES(?, 'norm', ?, "
                    "'Do not refactor unrelated code', 'default', 'general', 'active', "
                    "'2026-09-01T00:00:00.000Z', '{\"source_type\": \"rescue_extraction\"}')",
                    (bid, subject))
        # A person the calendar names, and the calendar fact that names them: the
        # entity read model reads both, and each test must see them whatever
        # order the suite runs in.
        core.capture.append("asserted", {
            "kind": "entity", "key": {"entity_type": "person", "type": "person",
                                      "name": "Robin Placeholder",
                                      "normalized_name": "robin placeholder",
                                      "owner": "default", "domain": "user"},
            "body": "Robin Placeholder", "confidence": 0.7, "source_event": "ev_seed",
            "source_type": "session_transcript"}, actor="curator")
        core.process_pending()
        _fact(core, "user", "attended_event", "Robin Placeholder's birthday — 2026-03-06",
              "user", 0.7, CHAT, "sands:1")
        cls.db = core.store.db_path
        cls.core = core

    @classmethod
    def tearDownClass(cls):
        cls.core.close()
        shutil.rmtree(cls.home, ignore_errors=True)

    def _log(self):
        c = sqlite3.connect(self.db)
        rows = c.execute("SELECT seq, CAST(strftime('%s', recorded_at) AS INTEGER), type, "
                         "COALESCE(session_id,''), actor FROM events ORDER BY seq").fetchall()
        c.close()
        return rows

    @staticmethod
    def _decode(chunks):
        out = []
        for ch in chunks:
            seq, t = ch["seq0"], ch["t0"]
            for i in range(ch["n"]):
                seq += ch["dseq"][i]
                t += ch["dt"][i]
                sid, lane = ch["writers"][ch["writer"][i]]
                out.append((seq, t, ch["types"][ch["type"][i]], sid, lane))
        return out


class TestEventStream(_TapestryCase):
    def test_one_chunk_decodes_to_the_log(self):
        ch = A.events_chunk(self.db, 0)
        self.assertTrue(ch["done"])
        decoded = self._decode([ch])
        self.assertEqual([d[:4] for d in decoded], [r[:4] for r in self._log()])
        self.assertEqual(ch["next_after_seq"], self._log()[-1][0])

    def test_small_chunks_decode_to_the_same_log(self):
        chunks, after = [], 0
        while True:
            ch = A.events_chunk(self.db, after, limit=3)
            chunks.append(ch)
            after = ch["next_after_seq"]
            if ch["done"]:
                break
        self.assertGreater(len(chunks), 2)
        self.assertEqual([d[:4] for d in self._decode(chunks)], [r[:4] for r in self._log()])

    def test_after_the_last_seq_is_empty_and_done(self):
        last = self._log()[-1][0]
        ch = A.events_chunk(self.db, last)
        self.assertEqual((ch["n"], ch["done"], ch["next_after_seq"]), (0, True, last))

    def test_full_chunks_are_cached_and_the_live_tail_is_not(self):
        import json as _json
        A._chunk_cache.clear()
        first = A.events_json(self.db, 0, 3)            # full chunk: cacheable
        self.assertEqual(_json.loads(first), A.events_chunk(self.db, 0, 3))
        self.assertEqual(len(A._chunk_cache), 1)
        self.assertIs(A.events_json(self.db, 0, 3), first, "a full chunk was recomputed")
        last = self._log()[-1][0]
        tail = A.events_json(self.db, last - 1, 50000)   # reaches the end: live tail
        self.assertTrue(_json.loads(tail)["done"])
        self.assertEqual(len(A._chunk_cache), 1, "the live tail was cached")

    def test_lanes(self):
        self.assertEqual(A.lane_of(CRON, "user"), "cron:abc123def456")
        self.assertEqual(A.lane_of(CHAT, "user"), "session:" + CHAT)
        self.assertEqual(A.lane_of(None, "curator"), "background:curator")
        lanes = {d[4] for d in self._decode([A.events_chunk(self.db, 0)])}
        self.assertIn("cron:abc123def456", lanes)
        self.assertIn("session:" + CHAT, lanes)


class TestInspectors(_TapestryCase):
    def _belief_id(self, table, where, params=()):
        c = sqlite3.connect(self.db)
        r = c.execute("SELECT belief_id FROM %s WHERE %s" % (table, where), params).fetchone()
        c.close()
        self.assertIsNotNone(r, where)
        return r[0]

    def test_session_lists_its_turns_and_the_beliefs_they_justify(self):
        s = A.session_detail(self.db, CRON)
        self.assertTrue(s["found"])
        self.assertEqual(s["lane"], "cron:abc123def456")
        self.assertEqual([t["seq"] for t in s["turns"]], sorted(t["seq"] for t in s["turns"]))
        self.assertTrue(any("offsite moved to Denver" in t["text"] for t in s["turns"]))
        works_at = {b["text"] for b in s["beliefs"] if b["label"] == "works_at"}
        self.assertEqual(works_at, {"Acme Fake Co", "Globex Fake Inc"})
        self.assertFalse(A.session_detail(self.db, "no-such-session")["found"])

    def test_belief_shows_what_it_replaced_and_its_sources(self):
        new = self._belief_id("facts", "value='Globex Fake Inc'")
        b = A.belief_detail(self.db, new)
        self.assertTrue(b["found"])
        self.assertEqual([v["text"] for v in b["replaced"]], ["Acme Fake Co"])
        self.assertEqual(b["replaced_by"], [])
        self.assertTrue(b["supports"], "no justifying event returned")
        self.assertTrue(all(s["session_id"] == CRON for s in b["supports"]))
        old = A.belief_detail(self.db, self._belief_id("facts", "value='Acme Fake Co'"))
        self.assertEqual(old["status"], "superseded")
        self.assertEqual([v["text"] for v in old["replaced_by"]], ["Globex Fake Inc"])

    def test_belief_shows_its_contradiction(self):
        b = A.belief_detail(self.db, self._belief_id("facts", "value='Riverton'"))
        others = [c["other"]["text"] for c in b["contradictions"] if c.get("other")]
        self.assertIn("Springfield", others)

    def test_identical_active_copies_are_counted(self):
        b = A.belief_detail(self.db, "b_legacy_dup_1")
        self.assertEqual(b["identical_active"], 2)

    def test_event_detail_names_the_beliefs_it_supports(self):
        c = sqlite3.connect(self.db)
        seq = c.execute("SELECT e.seq FROM events e JOIN justifications j ON j.support=e.event_id "
                        "JOIN facts f ON f.belief_id=j.belief_id WHERE f.value='Riverton'").fetchone()[0]
        c.close()
        e = A.event_detail(self.db, seq)
        self.assertTrue(e["found"])
        self.assertIn("Riverton", {b["text"] for b in e["beliefs"]})
        self.assertNotIn("{", e["text"][:1], "event text leaked raw JSON")

    def test_an_assertion_links_to_the_turn_it_was_extracted_from(self):
        """Beliefs cite the turn, not the assertion event, so the assertion's own
        inspector must follow payload.source_event to be of any use."""
        c = sqlite3.connect(self.db)
        seq = c.execute("SELECT seq FROM events WHERE type='asserted' AND payload LIKE '%Riverton%'"
                        ).fetchone()[0]
        c.close()
        e = A.event_detail(self.db, seq)
        self.assertEqual(e["beliefs"], [], "fixture: nothing cites the assertion itself")
        self.assertIsNotNone(e["source"])
        self.assertEqual(e["source"]["type"], "observed")
        self.assertIn("Riverton", {b["text"] for b in e["source_beliefs"]})

    def test_unknown_ids(self):
        self.assertFalse(A.belief_detail(self.db, "b_nope")["found"])
        self.assertFalse(A.event_detail(self.db, 10 ** 9)["found"])


class TestLenses(_TapestryCase):
    def test_contradictions(self):
        c = A.contradictions(self.db)
        self.assertGreaterEqual(c["total"], 1)
        pair = {c["items"][0]["a"]["text"], c["items"][0]["b"]["text"]}
        self.assertEqual(pair, {"Riverton", "Springfield"})

    def test_fact_histories(self):
        h = A.fact_histories(self.db)
        works = [i for i in h["items"] if i["predicate"] == "works_at"]
        self.assertEqual(len(works), 1)
        self.assertEqual([v["value"] for v in works[0]["versions"]], ["Acme Fake Co", "Globex Fake Inc"])

    def test_duplicate_notes(self):
        d = A.duplicate_notes(self.db)
        self.assertEqual((d["groups"], d["redundant"]), (1, 1))
        self.assertEqual(d["items"][0]["copies"], 2)

    def test_summary(self):
        s = A.summary(self.db)
        self.assertEqual(s["events"], len(self._log()))
        self.assertEqual(s["beliefs"]["fact"].get("superseded"), 1)
        self.assertGreaterEqual(s["contradictions_open"], 1)


class TestTheEntityReadModel(_TapestryCase):
    """What the Tapestry opens on: the things memory is about, not the machinery."""

    def _index(self, people=None):
        return A.entity_index(self.db, people=people)

    def test_entities_are_listed_with_their_kind(self):
        idx = self._index()
        by_id = {i["id"]: i for i in idx["items"]}
        # Nothing named this row, so it carries the id the facts reference: a
        # reader sees what memory actually holds, not a guess at capitalisation.
        self.assertEqual(by_id["pat_testley"]["name"], "pat_testley")
        self.assertEqual(by_id["pat_testley"]["origin"], "entity")
        self.assertGreaterEqual(by_id["pat_testley"]["facts"], 2)
        self.assertEqual(sum(idx["kinds"].values()), len(idx["items"]))

    def test_a_calendar_fact_is_an_event_with_its_own_date(self):
        items = [i for i in self._index()["items"] if i["kind"] == "event"]
        got = [i for i in items if i["name"].startswith("Robin Placeholder")]
        self.assertEqual(len(got), 1, items)
        self.assertEqual(got[0]["when"], "2026-03-06")
        self.assertEqual(got[0]["name"], "Robin Placeholder's birthday")  # the date tail is the date
        self.assertEqual(got[0]["origin"], "fact")

    def test_an_event_links_to_the_person_it_names(self):
        idx = self._index()
        ev = [i for i in idx["items"] if i["kind"] == "event"
              and i["name"].startswith("Robin Placeholder")][0]
        self.assertEqual(ev.get("participants"), ["robin_placeholder"])

    def test_a_person_reads_as_their_facts_history_and_mentions(self):
        d = A.entity_detail(self.db, "pat_testley")
        self.assertEqual(d["name"], "pat_testley")   # nothing named this row; see above
        current = {(f["predicate_canonical"], f["value"]) for f in d["current"]}
        self.assertIn(("works_at", "Globex Fake Inc"), current)
        self.assertIn(("works_at", "Acme Fake Co"),
                      {(f["predicate_canonical"], f["value"]) for f in d["past"]})
        named = A.entity_detail(self.db, "robin_placeholder")
        self.assertTrue(named["mentions"], "the captured turn naming Robin Placeholder is not shown")
        # That turn is a cron job's, and says so: a mention is never dressed up
        # as something the user said (engine/speaker.py).
        self.assertEqual(named["mentions"][0]["speakers"], ["assistant", "automation"])
        self.assertIn("Robin Placeholder", named["mentions"][0]["excerpt"])

    def test_the_user_is_you(self):
        self.assertEqual(A.entity_detail(self.db, "user")["name"], "You")

    def test_the_people_store_says_who_is_a_person_and_who_is_a_company(self):
        people = {"pat_testley": {"name": "Pat Testley", "is_company": 0, "occupation": "nurse"},
                  "acme": {"name": "Acme Fake Co", "is_company": 1},
                  "unknown_one": {"name": "Sam Vimes", "is_company": None}}
        A._cache.clear()
        by_id = {i["id"]: i for i in self._index(people=people)["items"]}
        self.assertEqual((by_id["pat_testley"]["kind"], by_id["pat_testley"]["subtype"]),
                         ("person", "contact"))
        d = A.entity_detail(self.db, "pat_testley", people=people)
        self.assertEqual(d["people_store"],
                         {"name": "Pat Testley", "is_company": 0, "occupation": "nurse"})

    def test_an_unreviewed_contact_is_not_called_a_company_or_a_person_silently(self):
        people = {"pat_testley": {"name": "Pat Testley", "is_company": None}}
        A._cache.clear()
        by_id = {i["id"]: i for i in self._index(people=people)["items"]}
        self.assertEqual(by_id["pat_testley"]["subtype"], "contact (unreviewed)")

    def test_a_missing_people_store_is_normal(self):
        self.assertEqual(A.people_store(Path(self.home) / "nowhere"), {})


class TestReadOnly(_TapestryCase):
    def test_nothing_the_tapestry_does_changes_the_store(self):
        before = _files_sha(self.db)
        A.summary(self.db)
        A.events_chunk(self.db, 0)
        A.session_detail(self.db, CRON)
        A.belief_detail(self.db, "b_legacy_dup_1")
        A.contradictions(self.db)
        A.fact_histories(self.db)
        A.duplicate_notes(self.db)
        self.assertEqual(_files_sha(self.db), before)

    def test_the_connection_refuses_writes(self):
        conn = A._connect(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM notes")
        finally:
            conn.close()


class TestPluginApiMountsTheTapestry(unittest.TestCase):
    def test_routes_are_registered_when_loaded_by_path(self):
        routes = []
        _load("chronicle_plugin_api_tapestry", _DASH / "plugin_api.py", routes)
        paths = {p for _m, p in routes}
        for p in ("/tapestry/log/summary", "/tapestry/log/events", "/tapestry/log/event", "/tapestry/log/session",
                  "/tapestry/log/belief", "/tapestry/log/contradictions", "/tapestry/log/histories",
                  "/tapestry/log/duplicates", "/tapestry/log/lanes", "/status"):
            self.assertIn(p, paths)


class TestAwkwardPaths(unittest.TestCase):
    def test_a_store_whose_path_has_uri_characters(self):
        d = temp_home(prefix="tapestry-uri-")
        self.addCleanup(shutil.rmtree, d, True)
        odd = Path(d) / "weird #1 ?dir"
        odd.mkdir()
        core = ChronicleCore(str(odd), {"embeddings": {"model": "hashing"}})
        core.initialize("s1", principal_id="assistant")
        core.capture.observe("Robin Placeholder likes kayaking.", "Nice.", session_id="s1")
        core.process_pending()
        db = core.store.db_path
        try:
            self.assertGreater(A.summary(db)["events"], 0)
        finally:
            core.close()


class TestCronNames(unittest.TestCase):
    def test_reads_names_and_tolerates_absence(self):
        d = temp_home(prefix="tapestry-cron-")
        self.addCleanup(shutil.rmtree, d, True)
        self.assertEqual(A.cron_job_names(d), {})
        (Path(d) / "cron").mkdir()
        (Path(d) / "cron" / "jobs.json").write_text(
            '{"jobs": [{"id": "abc123def456", "name": "Acme Fake Co digest"}]}')
        self.assertEqual(A.cron_job_names(d), {"abc123def456": "Acme Fake Co digest"})


if __name__ == "__main__":
    unittest.main()
