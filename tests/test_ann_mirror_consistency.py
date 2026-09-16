"""Chronicle — the vec0 ANN mirror must stay EQUAL to observed_vectors.

`retrieve_raw` takes a nonempty KNN result INSTEAD of the paged scan. So a mirror
is only safe when it is complete: a row present in `observed_vectors` but absent
from vec0 is never a vector candidate unless full-text search happens to find
it. "Absent" therefore means invisible, not slower.

Two raw-SQL scripts mutate `observed_vectors` outside MemoryStore and so must
keep the mirror in step themselves:

  * scripts/requeue_hash_vectors.py DELETES hash-tagged rows. It must remove
    exactly those ids from vec0. Clearing the whole mirror (an earlier revision)
    left every UNAFFECTED row missing once the requeued ones were rewritten.
  * scripts/writeback_vectors.py REWRITES embeddings. That is covered in
    tests/test_writeback_vectors.py, which asserts an upsert of the corrected
    blob rather than a delete.

Asserted as a contract on the calls, not on vec0 itself: sqlite-vec cannot load
under Apple's system Python, so a test that needed a real vec0 would SKIP on the
machine this suite is gated on — which is the same as not having one.

Fixtures use only fake values (Pat Testley, Acme Fake Co) and a hashing embedder.
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.requeue_hash_vectors as RQ  # noqa: E402
from _tmp_support import temp_home  # noqa: E402
from engine.core import ChronicleCore  # noqa: E402


class TestRequeueRemovesOnlyTheRowsItDeletes(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="ann_requeue_")
        core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        core.initialize("s1", principal_id="assistant")
        # One observe() is one turn and one observed vector, so several turns.
        for turn in ("I am Pat Testley", "I work at Acme Fake Co", "I live in Springfield",
                     "My manager is Dana Fictional", "I drive a Fake Motors sedan",
                     "My favourite lunch spot is the Acme Fake Co canteen"):
            core.capture.observe(turn, "", session_id="s1")
        core.process_pending()
        core.curation.drain()
        ids = [r[0] for r in core.store._conn().execute(
            "SELECT event_id FROM observed_vectors ORDER BY rowid").fetchall()]
        self.assertGreaterEqual(len(ids), 2, "fixture needs at least two observed vectors")
        kept = ids[: len(ids) // 2]
        with core.store.transaction() as c:
            # Re-tag half to a real model: requeue must leave these alone.
            c.executemany("UPDATE observed_vectors SET model='nomic-embed-text' WHERE event_id=?",
                          [(i,) for i in kept])
        self.kept = set(kept)
        self.doomed = set(ids) - self.kept
        self.assertTrue(self.doomed and self.kept, "fixture must have both kinds of row")
        self.db = core.store.db_path
        core.close()

    def _requeue(self, spy):
        with mock.patch.object(RQ, "_vec0_delete_ids", spy), \
                contextlib.redirect_stdout(io.StringIO()):
            return RQ.requeue(self.db)

    def test_exactly_the_deleted_ids_leave_the_mirror(self):
        calls = []
        real = RQ._vec0_delete_ids

        def spy(conn, event_ids):
            event_ids = list(event_ids)
            calls.append(event_ids)
            return real(conn, event_ids)

        self.assertEqual(self._requeue(spy), 0)
        self.assertEqual(len(calls), 1, "the mirror must be told once, about this delete")
        self.assertEqual(set(calls[0]), self.doomed,
                         "the mirror must lose exactly the rows observed_vectors lost")
        self.assertFalse(set(calls[0]) & self.kept,
                         "an UNAFFECTED row was removed from the mirror: once the requeued "
                         "rows are rewritten it would be invisible to vector search")

    def test_the_primary_table_agrees_with_what_the_mirror_was_told(self):
        self._requeue(lambda conn, ids: 0)
        c = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        try:
            left = {r[0] for r in c.store._conn().execute(
                "SELECT event_id FROM observed_vectors").fetchall()}
        finally:
            c.close()
        self.assertTrue(self.kept <= left, "requeue deleted a row that was not hash-tagged")
        self.assertFalse(self.doomed & left, "requeue left a hash-tagged row in place")


if __name__ == "__main__":
    unittest.main(verbosity=2)
