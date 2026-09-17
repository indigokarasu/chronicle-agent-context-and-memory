"""
Chronicle — scripts/prune_vectors.py --orphans.

Every observed vector is derived from an event. When an event leaves the log (by
hand: no Chronicle code deletes events) its vector is an index entry with nothing
behind it: it cannot be rendered, `migrate_vectors` counts it unrecoverable on
every run, and every brute-force scan still pays for it. One production store
kept 18,394 of them after a manual purge that removed the events and their FTS
rows but not their vectors. `--orphans` removes those vectors and their doc2query
excerpt proxies, and nothing else.

Fixtures use obviously fake values.
"""

import contextlib
import io
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from scripts.prune_vectors import main, prune_orphans

TURNS = ("The Acme Fake Co server room flooded on Tuesday.",
         "Pat Testley moved the backups to the second rack.",
         "Robin Placeholder ordered new dehumidifiers for the room.")


class TestPruneOrphans(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="orph-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing",
                                                             "doc2query": {"excerpts": True}}})
        self.core.initialize("s-o", principal_id="assistant")
        for text in TURNS:
            self.core.capture.observe(text, "Understood.", session_id="s-o")
            self.core.process_pending()
        # A fact, so belief-keyed vectors and proxies exist to be left alone.
        self.core.capture.append("asserted", {
            "kind": "fact", "key": {"entity_id": "pat_testley", "predicate_canonical": "works_at",
                                    "attribute": "works_at", "qualifiers_hash": "",
                                    "qualifiers": {}},
            "body": "Acme Fake Co", "confidence": 0.9, "source_event": "src-o",
            "source_type": "user_direct", "domain": "user"}, actor="user", session_id="s-o")
        self.core.process_pending()
        self.db = self.core.store.db_path
        self.conn = sqlite3.connect(self.db)
        self.addCleanup(self.conn.close)
        self.events = [r[0] for r in self.conn.execute(
            "SELECT event_id FROM observed_vectors ORDER BY rowid")]
        self.assertGreaterEqual(len(self.events), 2, "fixture wrote too few observed vectors")
        self.gone = self.events[0]
        self._purge_event_by_hand(self.gone)

    def _purge_event_by_hand(self, event_id):
        """What the production purge did: event and FTS row gone, vector left."""
        self.conn.execute("DELETE FROM events WHERE event_id=?", (event_id,))
        self.conn.execute("DELETE FROM observed_fts WHERE event_id=?", (event_id,))
        self.conn.commit()

    def _count(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]

    def _state(self):
        return (self._count("SELECT COUNT(*) FROM observed_vectors"),
                self._count("SELECT COUNT(*) FROM query_proxy_vectors WHERE kind='observed'"),
                self._count("SELECT COUNT(*) FROM query_proxy_vectors WHERE kind!='observed'"),
                self._count("SELECT COUNT(*) FROM memory_vectors"))

    def test_dry_run_counts_and_deletes_nothing(self):
        before = self._state()
        with contextlib.redirect_stdout(io.StringIO()):
            n = prune_orphans(self.db, dry_run=True)
        self.assertEqual(n, 1)
        self.assertEqual(self._state(), before)

    def test_removes_exactly_the_orphan_and_its_excerpt_proxies(self):
        proxies_for_gone = self._count(
            "SELECT COUNT(*) FROM query_proxy_vectors WHERE kind='observed' AND belief_id=?",
            (self.gone,))
        self.assertGreater(proxies_for_gone, 0, "fixture wrote no excerpt proxy for the orphan")
        vec, exc, bel_proxies, mem = self._state()

        with contextlib.redirect_stdout(io.StringIO()):
            n = prune_orphans(self.db)

        self.assertEqual(n, 1)
        self.assertEqual(self._count("SELECT COUNT(*) FROM observed_vectors WHERE event_id=?",
                                     (self.gone,)), 0)
        self.assertEqual(self._state(), (vec - 1, exc - proxies_for_gone, bel_proxies, mem))
        survivors = [r[0] for r in self.conn.execute("SELECT event_id FROM observed_vectors")]
        self.assertEqual(sorted(survivors), sorted(self.events[1:]))

    def test_a_second_run_finds_nothing(self):
        with contextlib.redirect_stdout(io.StringIO()):
            prune_orphans(self.db)
            self.assertEqual(prune_orphans(self.db), 0)

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--db", self.db, "--orphans", "--dry-run"]), 0)
        self.assertIn("1 vectors would be deleted", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--db", self.db]), 1)


if __name__ == "__main__":
    unittest.main()
