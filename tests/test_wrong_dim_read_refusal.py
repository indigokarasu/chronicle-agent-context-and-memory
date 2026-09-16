"""
Chronicle — acceptance tests for A0c: loud wrong-dimension refusal on the read path.

The silence this ends: a stored blob whose byte length did not match the query's
dimensionality scored 0.0, and 0.0 is below every similarity floor in retrieval,
so the row simply never appeared. On the live store that was 88% of memory —
~170k vectors written by a 2048-dim model, read by a 768-dim one — contributing
nothing, with no error, no log line and no counter. The store looked healthy.

Wrong-length blobs are still SKIPPED (there is no meaningful cosine between two
geometries). What changes is that skipping is now COUNTED per query, counted
process-wide, and logged once at WARNING.

The last test is the mutation guard: it re-runs the same assertions with the OLD
behavior injected (score 0.0, count nothing) and asserts they FAIL. Without it,
a regression back to silence would leave every other test in this file green.

Fixtures use only fake values (Pat Testley, Acme Fake Co).
"""

import logging
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import embeddings as E
from engine.core import ChronicleCore
from engine.retrieval import RetrievalEngine

QUERY = "where does Pat Testley work"


class _WrongDimStore(unittest.TestCase):
    """A store holding exactly 3 correctly-dimensioned memory vectors and 2
    wrong-dimension ones."""

    N_GOOD = 3
    N_BAD = 2

    def setUp(self):
        E.reset_wrong_dim_skipped()
        self.home = tempfile.mkdtemp(prefix="a0c_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("s1", principal_id="assistant")
        self.core.capture.observe(
            "I am Pat Testley\n"
            "I work at Acme Fake Co\n"
            "I live in Springfield\n"
            "My manager is Dana Fictional\n"
            "I drive a Fake Motors sedan\n"
            "My favorite lunch spot is the Acme Fake Co canteen", "",
            session_id="s1")
        self.core.process_pending()
        self.core.curation.drain()

        conn = self.core.store._conn()
        ids = [(r[0], r[1]) for r in conn.execute(
            "SELECT belief_id, kind FROM memory_vectors ORDER BY rowid").fetchall()]
        self.assertGreaterEqual(len(ids), self.N_GOOD + self.N_BAD,
                                "fixture needs at least 5 memory vectors, got %d" % len(ids))
        keep = ids[:self.N_GOOD + self.N_BAD]
        keep_ids = [b for b, _k in keep]
        with self.core.store.transaction() as c:
            ph = ",".join("?" * len(keep_ids))
            c.execute("DELETE FROM memory_vectors WHERE belief_id NOT IN (%s)" % ph, keep_ids)
            # The two "nemotron" rows: a DIFFERENT width, same tag, same table.
            for bid, kind in keep[self.N_GOOD:]:
                c.execute("UPDATE memory_vectors SET embedding=? WHERE belief_id=? AND kind=?",
                          (E.pack([0.02] * 2048), bid, kind))
        self.good_ids = set(keep_ids[:self.N_GOOD])
        self.bad_ids = set(keep_ids[self.N_GOOD:])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0],
            self.N_GOOD + self.N_BAD)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        E.reset_wrong_dim_skipped()

    # -- assertions shared with the mutation guard -------------------------
    def _assert_loud_refusal(self):
        E.reset_wrong_dim_skipped()
        ans = self.core.retrieval.answer(QUERY)
        debug = ans.get("debug") or {}
        # (1) the good vectors still answer …
        hits = {c["belief_id"] for c in self.core.retrieval.search(QUERY, limit=10)}
        self.assertFalse(hits & self.bad_ids,
                         "a wrong-dimension vector must never be scored into a result")
        # (2) … and the skipped ones are REPORTED, per query, by identity.
        self.assertEqual(debug.get("vectors_skipped_wrong_dim"), self.N_BAD, debug)
        # (3) and counted process-wide.
        self.assertGreaterEqual(E.wrong_dim_skipped(), self.N_BAD)


class TestWrongDimIsSkippedAndCounted(_WrongDimStore):
    def test_query_answers_from_the_good_vectors_and_reports_the_skips(self):
        self._assert_loud_refusal()

    def test_vector_channel_still_reaches_the_good_beliefs(self):
        emb = self.core.embedder.embed_query(QUERY)
        scored = self.core.retrieval._vector_beliefs(emb, 10)
        got = {bid for bid, _k, _s in scored}
        self.assertTrue(got, "the good vectors must still be scored")
        self.assertFalse(got & self.bad_ids)

    def test_warning_is_logged_once_per_process(self):
        E.reset_wrong_dim_skipped()
        with self.assertLogs("chronicle.embeddings", level=logging.WARNING) as cm:
            self.core.retrieval.answer(QUERY)
        loud = [m for m in cm.output if "WRONG-DIMENSION" in m]
        self.assertEqual(len(loud), 1, cm.output)
        self.assertIn("migrate_vectors", loud[0])
        # A second query must not re-log: this fires from inside per-page scan
        # loops, so per-occurrence logging would be pure noise.
        before = len(loud)
        with mock.patch.object(E.logger, "warning") as w:
            self.core.retrieval.answer(QUERY)
            self.assertEqual(w.call_count, 0)
        self.assertEqual(before, 1)

    def test_counter_keeps_climbing_across_queries(self):
        E.reset_wrong_dim_skipped()
        self.core.retrieval.answer(QUERY)
        first = E.wrong_dim_skipped()
        self.core.retrieval.answer(QUERY)
        self.assertGreater(E.wrong_dim_skipped(), first)

    def test_health_surfaces_the_read_side_counter(self):
        E.reset_wrong_dim_skipped()
        self.core.retrieval.answer(QUERY)
        results = self.core.health.run()
        self.assertIn("vector_reads_skipped_wrong_dim", results)
        self.assertGreaterEqual(results["vector_reads_skipped_wrong_dim"], self.N_BAD)

    def test_get_context_reports_the_skips_too(self):
        self.core.retrieval.get_context(QUERY, token_budget=500)
        self.assertEqual(
            self.core.retrieval.last_context_debug.get("vectors_skipped_wrong_dim"), self.N_BAD)

    def test_clean_store_reports_zero(self):
        with self.core.store.transaction() as c:
            ph = ",".join("?" * len(self.bad_ids))
            c.execute("DELETE FROM memory_vectors WHERE belief_id IN (%s)" % ph,
                      list(self.bad_ids))
        E.reset_wrong_dim_skipped()
        ans = self.core.retrieval.answer(QUERY)
        self.assertEqual((ans.get("debug") or {}).get("vectors_skipped_wrong_dim"), 0)
        self.assertEqual(E.wrong_dim_skipped(), 0)


class TestOldSilentBehaviorFailsTheTest(_WrongDimStore):
    """MUTATION GUARD. Restore the pre-A0c read path — score a wrong-length
    blob as 0.0 and count nothing — and the assertions above must FAIL. If they
    still pass, this file is not testing anything."""

    def test_silent_zero_scoring_is_detected(self):
        with mock.patch.object(E, "note_wrong_dim", lambda n, where="": None), \
             mock.patch.object(RetrievalEngine, "_note_wrong_dim_rows",
                               lambda self, *a, **k: None):
            with self.assertRaises(AssertionError):
                self._assert_loud_refusal()

    def test_under_the_mutation_the_store_looks_clean(self):
        """Spelled out because it is the actual production symptom: with the old
        behavior the query still returns an answer, the debug field says zero
        skipped, and nothing anywhere reports that 2 of 5 memories were
        unreachable."""
        with mock.patch.object(E, "note_wrong_dim", lambda n, where="": None), \
             mock.patch.object(RetrievalEngine, "_note_wrong_dim_rows",
                               lambda self, *a, **k: None):
            E.reset_wrong_dim_skipped()
            ans = self.core.retrieval.answer(QUERY)
            self.assertEqual((ans.get("debug") or {}).get("vectors_skipped_wrong_dim"), 0)
            self.assertEqual(E.wrong_dim_skipped(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
