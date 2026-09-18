"""
Chronicle — the full-text indexes hold what a search can return.

Profiled on the production store (5.8.0): a gated per-turn search spent ~5 s
in each FTS channel on a long prompt. belief_fts held 101,188 rows, 97,790 of
them retracted beliefs that the search ranks and then throws away; the
observed index held 67k transcript rows, ~98% cron runs, which the per-turn
search (the user's own conversations only) ranked and then filtered out.

Now a belief leaves belief_fts when it stops being searchable (and returns if
it is reactivated), and the user's own conversations have their own index,
used once it is known to be complete.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}}
CHAT = "20260917_161616_ff66aa"
CRON = "cron_abc123_20260917_000000"


class _Core(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="ftsh_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.store = self.core.store

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def fts_ids(self, table, col="event_id"):
        return {r[0] for r in self.store._conn().execute("SELECT %s FROM %s" % (col, table))}


class TestBeliefIndexFollowsStatus(_Core):
    def _note(self, body="Pat Testley prefers the Izakaya Nonesuch."):
        self.core.capture.append("asserted", {
            "kind": "note", "key": {"note_type": "belief", "subject": body[:12]},
            "body": body, "confidence": 0.9, "source_event": "test",
            "source_type": "test_seed"}, actor="user", trust_level=3)
        self.core.process_pending()
        rows = self.store.query_beliefs("notes", "status='active' AND body=?", (body,), 5)
        self.assertTrue(rows, "setup: a note was asserted")
        return rows[0]["belief_id"]

    def test_retracted_leaves_and_reactivated_returns(self):
        bid = self._note()
        self.assertIn(bid, self.fts_ids("belief_fts", "belief_id"))
        self.store.update_belief("notes", bid, status="retracted")
        self.assertNotIn(bid, self.fts_ids("belief_fts", "belief_id"))
        self.assertEqual(self.store.fts_search_beliefs("Nonesuch"), [])
        self.store.update_belief("notes", bid, status="active")
        self.assertIn(bid, self.fts_ids("belief_fts", "belief_id"))

    def test_the_all_tables_update_follows_too(self):
        bid = self._note("Robin Placeholder lives in Riverton.")
        self.store.update_belief_all_tables(bid, status="superseded")
        self.assertNotIn(bid, self.fts_ids("belief_fts", "belief_id"))

    def test_a_belief_written_inactive_is_not_indexed(self):
        bid = self._note("Sam Vimes owns a SunFake 9000.")
        row = dict(self.store.get_belief("notes", bid))
        row["status"] = "retracted"
        self.store.upsert_belief("notes", row)
        self.assertNotIn(bid, self.fts_ids("belief_fts", "belief_id"))


class TestTheUsersOwnConversations(_Core):
    def _observe(self, sid, text):
        self.core.initialize(sid, principal_id="default")
        return self.core.capture.observe(text, "Noted.", session_id=sid)

    def test_only_the_users_sessions_are_in_it(self):
        self._observe(CHAT, "We booked the Izakaya Nonesuch for Friday.")
        self._observe(CRON, "Zorblax dispatch run: Izakaya Nonesuch report re-asserted.")
        users = self.fts_ids("observed_user_fts")
        sessions = {r[0] for r in self.store._conn().execute(
            "SELECT session_id FROM events WHERE event_id IN (%s)"
            % ",".join("?" * len(users)), tuple(users))} if users else set()
        self.assertTrue(users)
        self.assertEqual(sessions, {CHAT})

    def test_the_per_turn_search_reads_it_and_answers_the_same(self):
        self._observe(CHAT, "We booked the Izakaya Nonesuch for Friday.")
        for i in range(5):
            self._observe("%s%02d" % (CRON[:-2], i), "Izakaya Nonesuch dispatch run %d." % i)
        self.assertTrue(self.store.user_fts_ready(), "a new store is complete from birth")
        fast = self.store.fts_search_observed("", limit=10, match='"nonesuch"*',
                                              exclude_session_prefixes=("cron_",))
        self.store._conn().execute("UPDATE meta SET value='0' WHERE key='observed_user_fts_ready'")
        slow = self.store.fts_search_observed("", limit=10, match='"nonesuch"*',
                                              exclude_session_prefixes=("cron_",))
        self.assertEqual([r["event_id"] for r in fast], [r["event_id"] for r in slow])
        self.assertEqual(len(fast), 1)

    def test_the_ready_index_is_the_one_read(self):
        """Only the user index has this row: seen when it is read, not otherwise."""
        self.store._conn().execute("INSERT INTO observed_user_fts(event_id, excerpt) "
                                   "VALUES('ev_marker', 'Zorblaxian marker text')")
        hit = self.store.fts_search_observed("", limit=5, match='"zorblaxian"*',
                                             exclude_session_prefixes=("cron_",))
        self.assertEqual([r["event_id"] for r in hit], ["ev_marker"])
        whole = self.store.fts_search_observed("", limit=5, match='"zorblaxian"*')
        self.assertEqual(whole, [], "the ordinary search still reads the whole index")

    def test_forgetting_removes_it_from_both(self):
        eid = self._observe(CHAT, "Robin Placeholder's door code is fake-1234.")
        self.store.fts_delete_observed(eid)
        self.assertNotIn(eid, self.fts_ids("observed_fts"))
        self.assertNotIn(eid, self.fts_ids("observed_user_fts"))

    def test_a_rebuild_refills_it_and_marks_it_complete(self):
        eid = self._observe(CHAT, "We booked the Izakaya Nonesuch for Friday.")
        self._observe(CRON, "Zorblax dispatch run.")
        self.store._conn().execute("UPDATE meta SET value='0' WHERE key='observed_user_fts_ready'")
        self.core.reducer.rebuild()
        self.assertTrue(self.store.user_fts_ready())
        self.assertEqual(self.fts_ids("observed_user_fts"), {eid})


class TestAnUpgradedStoreWaitsForItsBackfill(unittest.TestCase):
    def test_an_older_store_with_rows_is_not_ready(self):
        home = temp_home(prefix="ftsu_")
        self.addCleanup(shutil.rmtree, home, True)
        core = ChronicleCore(home, CFG)
        core.initialize(CHAT, principal_id="default")
        core.capture.observe("We booked the Izakaya Nonesuch.", "Noted.", session_id=CHAT)
        conn = core.store._conn()
        conn.execute("DELETE FROM meta WHERE key='observed_user_fts_ready'")   # as before 5.8.2
        conn.commit()
        again = ChronicleCore(home, CFG)
        self.assertFalse(again.store.user_fts_ready())


if __name__ == "__main__":
    unittest.main()
