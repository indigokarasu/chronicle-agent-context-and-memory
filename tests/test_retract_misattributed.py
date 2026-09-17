"""
Chronicle — scripts/retract_misattributed.py.

Earlier builds extracted memory about the user from text the user never wrote
(cron prompts, tool output, rescue and eviction text, the assistant's replies).
The script retracts a belief only when every channel it came from is transcript
extraction and no supporting event shows the user saying it; it keeps anything
another channel vouches for and anything in the user's own words.

The store here is built the way an older build left it: observed events without
attribution, and the `asserted` events its extractor wrote from them. Fixture
values are obviously fake.
"""

import contextlib
import io
import json
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from provider import ChronicleMemoryProvider
from scripts.retract_misattributed import main

CFG = {"embeddings": {"model": "hashing", "dimensions": 64}}
HUMAN_SESSION = "20260101_000000_abcd1234"
CRON_SESSION = "cron_9a0b2b502470_20260826_113441"


class TestRetractMisattributed(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.p = ChronicleMemoryProvider()
        self.p.initialize(HUMAN_SESSION, hermes_home=self.home, principal_id="default", config=CFG)
        self.cap = self.p.core.capture
        self.db = self.p.core.store.db_path

        cron = self._observed("user: My email is support@example.invalid\nassistant: done",
                              CRON_SESSION)
        human = self._observed("user: My name is Pat Testley.\n"
                               "assistant: My name is Indigo. Never retry inline.", HUMAN_SESSION)
        self.b = {
            "cron_email": self._fact("user", "email", "support@example.invalid", cron),
            "cron_episode": self._episode("My email is support@example.invalid", cron),
            "cron_draft": self._note("Always check the queue first", cron, subject="rescued",
                                     status="draft"),
            "human_name": self._fact("user", "name", "Pat Testley", human),
            "assistant_name": self._fact("user", "role_name", "Indigo", human),
            "assistant_norm": self._note("Never retry inline", human),
            "human_episode": self._episode("My name is Pat Testley.", human),
            "purged": self._note("Do not guess a destination", "ev_no_longer_in_the_log"),
            # A second owner: a retraction is owned, so one event may not speak
            # for two of them.
            "other_owner": self._note("Never retry inline either", cron, owner="someone_else"),
            "calendar": self._fact("user", "attended_event", "Robin Placeholder's birthday", "sands:1",
                                   source_type="external_sands:robin"),
        }

    # -- building an older build's store ----------------------------------

    def _observed(self, excerpt, session_id):
        store = self.p.core.store
        store.reducer = None     # as an older build captured it: no attribution, no queued extraction
        try:
            return self.cap.append("observed", {"source_type": "session_transcript",
                                                "excerpt": excerpt, "source_ref": session_id},
                                   actor="user", session_id=session_id)
        finally:
            store.reducer = self.p.core.reducer

    def _assert(self, kind, key, body, src, source_type, status="active", owner="default"):
        self.cap.append("asserted", {"kind": kind, "key": key, "body": body, "confidence": 0.8,
                                     "source_event": src, "source_type": source_type,
                                     "domain": "user", "status": status},
                        parents=[src] if src.startswith("ev_") else [], actor="curator",
                        owner=owner)
        c = sqlite3.connect(self.db)
        try:
            table = {"fact": "facts", "note": "notes", "episode": "episodes"}[kind]
            col = {"fact": "value", "note": "body", "episode": "summary"}[kind]
            return c.execute("SELECT belief_id FROM %s WHERE %s=?" % (table, col), (body,)).fetchone()[0]
        finally:
            c.close()

    def _fact(self, entity, predicate, value, src, source_type="session_transcript"):
        return self._assert("fact", {"entity_id": entity, "predicate_canonical": predicate,
                                     "attribute": predicate, "qualifiers_hash": "", "qualifiers": {}},
                            value, src, source_type)

    def _note(self, body, src, subject="directive", status="active", owner="default"):
        return self._assert("note", {"note_type": "norm", "subject": subject, "risk_tier": "low"},
                            body, src, "session_transcript", status=status, owner=owner)

    def _episode(self, body, src):
        return self._assert("episode", {"title": body[:48], "session_ref": HUMAN_SESSION},
                            body, src, "session_transcript")

    def _status(self):
        c = sqlite3.connect(self.db)
        try:
            out = {}
            for name, bid in self.b.items():
                for table in ("facts", "notes", "episodes"):
                    row = c.execute("SELECT status FROM %s WHERE belief_id=?" % table, (bid,)).fetchone()
                    if row:
                        out[name] = row[0]
            return out
        finally:
            c.close()

    def _run(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--db", self.db, *extra])
        return code, out.getvalue()

    # -- the verdicts -----------------------------------------------------

    RETRACTED = {"cron_email", "cron_episode", "cron_draft", "assistant_name", "assistant_norm",
                 "purged", "other_owner"}

    def test_dry_run_reports_exactly_the_misattributed_and_changes_nothing(self):
        before = self._status()
        report = Path(self.home) / "report.jsonl"
        code, out = self._run("--report", str(report))
        self.assertEqual(code, 0)
        self.assertIn("would retract 7 beliefs", out)
        rows = [json.loads(line) for line in report.read_text().splitlines()]
        names = {n for n, bid in self.b.items() if bid in {r["belief_id"] for r in rows}}
        self.assertEqual(names, self.RETRACTED)
        self.assertEqual(self._status(), before)

    def test_a_cron_session_is_answered_without_reading_its_payload(self):
        """The fast path the live store needs: a scheduled job's session has no
        person in it by construction, whatever its payload says."""
        from scripts.retract_misattributed import human_events
        c = sqlite3.connect(self.db)
        try:
            human = human_events(c)
        finally:
            c.close()
        by_session = {}
        for eid, sid in sqlite3.connect(self.db).execute(
                "SELECT event_id, session_id FROM events WHERE type='observed'"):
            by_session.setdefault(sid or "", []).append(eid)
        self.assertTrue(by_session[CRON_SESSION])
        self.assertTrue(all(human[e] is False for e in by_session[CRON_SESSION]))
        self.assertTrue(any(human[e] for e in by_session[HUMAN_SESSION]))

    def test_the_report_says_why(self):
        report = Path(self.home) / "report.jsonl"
        self._run("--report", str(report))
        why = {r["belief_id"]: r["why"] for r in map(json.loads, report.read_text().splitlines())}
        self.assertEqual(why[self.b["cron_email"]], ["no words by the user"])
        self.assertEqual(why[self.b["assistant_norm"]], ["not in the user's words"])
        self.assertEqual(why[self.b["purged"]], ["event no longer in the log"])

    def test_apply_retracts_them_through_the_log_and_keeps_the_rest(self):
        code, _ = self._run("--apply")   # noqa: F841 - `_` is the captured output, asserted below
        self.assertEqual(code, 0)
        status = self._status()
        self.assertEqual({n for n, s in status.items() if s == "retracted"}, self.RETRACTED)
        self.assertEqual({n for n, s in status.items() if s == "active"},
                         set(self.b) - self.RETRACTED)
        c = sqlite3.connect(self.db)
        try:
            payloads = [json.loads(r[0]) for r in
                        c.execute("SELECT payload FROM events WHERE type='retracted'")]
        finally:
            c.close()
        # One decision per owner: a production cleanup is >100,000 beliefs, and a
        # retraction is owned, so a batch may not cross owners.
        self.assertEqual([pl["reason"] for pl in payloads], ["misattributed"] * 2)
        by_owner = {len(pl["belief_ids"]): set(pl["belief_ids"]) for pl in payloads}
        self.assertEqual(by_owner[1], {self.b["other_owner"]})
        self.assertEqual(by_owner[6], {self.b[n] for n in self.RETRACTED if n != "other_owner"})
        self.assertIn("retracted 7 beliefs in 2 event(s)", _)
        self.assertIn("would retract 0 beliefs", self._run()[1])

    def test_a_batch_splits_at_the_batch_size(self):
        code, out = self._run("--apply", "--batch", "2")
        self.assertEqual(code, 0)
        self.assertIn("retracted 7 beliefs in 4 event(s)", out)
        self.assertEqual({n for n, s in self._status().items() if s == "retracted"}, self.RETRACTED)

    def test_a_rebuild_reproduces_the_retractions(self):
        """I3: the projection comes from the log, so a batch retraction survives
        a rebuild exactly as a per-belief one would."""
        self._run("--apply")
        before = self._status()
        self.p.core.reducer.rebuild()
        self.assertEqual(self._status(), before)

    def test_a_held_write_lock_is_waited_out_not_fatal(self):
        """The store has one writer and an agent is using it: the apply waits
        rather than dying 17 batches in, as it did on the production box."""
        import scripts.retract_misattributed as mod
        calls = {"n": 0}
        real_sleep = mod.time.sleep

        class _LockedOnce:
            def __init__(self, capture):
                self.capture = capture

            def append(self, *a, **kw):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise sqlite3.OperationalError("database is locked")
                return self.capture.append(*a, **kw)

        mod.time.sleep = lambda _s: None
        try:
            waits = mod._append_with_retry(_LockedOnce(self.cap), ["b_x"], "default")
        finally:
            mod.time.sleep = real_sleep
        self.assertEqual((waits, calls["n"]), (1, 2))

    def test_an_error_that_is_not_a_lock_is_raised(self):
        import scripts.retract_misattributed as mod

        class _Broken:
            def append(self, *a, **kw):
                raise sqlite3.OperationalError("no such table: events")

        with self.assertRaises(sqlite3.OperationalError):
            mod._append_with_retry(_Broken(), ["b_x"], "default")

    def test_a_missing_database_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--db", str(Path(self.home) / "nope.db")]), 1)


if __name__ == "__main__":
    unittest.main()
