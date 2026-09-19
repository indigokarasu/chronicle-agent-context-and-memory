"""Chronicle — main's dada805 as merged into 5.8.31.

Two things came in from main's "stale lock recovery + pointer ingestion":

* `events.pointer` (schema rung 19): kept. An event can carry a skill
  reference such as `weave:<person_id>` instead of a copy of what it points at.
* deleting `-wal` / `-shm` at every store open: NOT kept. A WAL holds committed
  transactions until they are checkpointed, and SQLite replays it on the next
  open; unlinking it first throws them away. The second test is the guard that
  keeps that behaviour from coming back.
"""

import os
import shutil
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _tmp_support import temp_home  # noqa: E402
from engine.capture import CaptureEngine  # noqa: E402
from engine.store import MemoryStore  # noqa: E402


class _NoReducer:
    def reduce(self, *a, **k):
        return None


def _capture(store):
    return CaptureEngine(store, _NoReducer(), owner="default")


class TestEventsPointer(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.store = MemoryStore(os.path.join(self.home, "c.db"))
        self.addCleanup(self.store.close)

    def test_a_pointer_is_stored_with_its_event(self):
        eid = _capture(self.store).append(
            "observed", {"text": "Pat Testley's number changed"}, actor="user",
            session_id="s1", pointer="weave:person_123")
        self.assertEqual(self.store.get_event(eid)["pointer"], "weave:person_123")

    def test_an_event_without_one_stores_null(self):
        eid = _capture(self.store).append(
            "observed", {"text": "nothing to point at"}, actor="user", session_id="s1")
        self.assertIsNone(self.store.get_event(eid)["pointer"])


class TestAWalIsNeverDiscardedOnOpen(unittest.TestCase):
    """A store copied mid-life -- its committed rows still only in the WAL --
    must open with every row. Main's dada805 unlinked the WAL first."""

    def test_rows_only_in_the_wal_survive_the_next_open(self):
        home = temp_home()
        src = os.path.join(home, "live.db")
        store = MemoryStore(src)
        conn = store._conn()
        conn.execute("PRAGMA wal_autocheckpoint=0")  # keep the rows in the WAL
        eid = _capture(store).append(
            "observed", {"text": "committed but not checkpointed"}, actor="user",
            session_id="s1")
        self.assertTrue(os.path.getsize(src + "-wal") > 0, "setup: the WAL must hold the row")

        # A crash leaves exactly this: the main file plus its sidecars.
        dst_dir = temp_home()
        dst = os.path.join(dst_dir, "live.db")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(src + suffix):
                shutil.copyfile(src + suffix, dst + suffix)
        store.close()

        # Without the WAL the row is gone -- which is what deleting it would do.
        bare = os.path.join(temp_home(), "bare.db")
        shutil.copyfile(dst, bare)
        try:
            n = sqlite3.connect(bare).execute(
                "SELECT COUNT(*) FROM events WHERE event_id=?", (eid,)).fetchone()[0]
        except sqlite3.OperationalError:  # not even the schema is checkpointed yet
            n = 0
        self.assertEqual(n, 0, "setup: the row must not be in the main file yet")

        reopened = MemoryStore(dst)
        self.addCleanup(reopened.close)
        self.assertIsNotNone(reopened.get_event(eid))


if __name__ == "__main__":
    unittest.main()
