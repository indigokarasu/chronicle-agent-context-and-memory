"""
Chronicle — L9 integration: the renumbered schema-migration ladder.

E5, E7 and H1 were each built against a schema_version 5 store and each claimed
version 6 for its own tables. There is only ONE meta.schema_version, so those
claims are not composable: whichever merged last would have silently redefined
what "6" means, and a store stamped 6 by an older build would then be treated as
already carrying tables it has never had.

The integration sequences them into one ladder:
    6  = novelty                (E5)
    7  = occurrence_count       (E5)
    8  = identity tables        (E7)
    9  = host-model tables      (H1)
    10 = host-model drain tables (H2: host_model_proxies + rerank_hints)

The property that makes the renumbering safe is that every step is
probe-then-apply (_has_col / _has_table) and the version is stamped LAST. That
makes the ladder order-independent and re-entrant: a store at ANY prior version
converges by running all of the steps, and an interrupted migration re-runs
instead of claiming a shape it never reached. These tests pin that property at
each entry point into the ladder, including the mid-states that only exist
because of the renumbering (a store stamped 6 or 7 by a pre-integration build).
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.store import SCHEMA_VERSION, BELIEF_TABLES, MemoryStore, _has_col, _has_table

# The pre-E5 (schema_version 5) belief-table shape, reused from E5's own
# migration suite rather than restated here: it is a verbatim copy of the v550
# baseline, so these tests exercise the real column set a real upgrade meets.
from test_e5_novelty_provenance import _PRE_E5_BELIEF_SCHEMA

_V5_SUBSET = _PRE_E5_BELIEF_SCHEMA   # already carries its own `meta` table

_NEW_TABLES = ("entity_centroids", "identity_candidates",
               "host_model_requests", "host_model_results",
               "host_model_proxies", "rerank_hints")


class _LadderCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="l9-ladder-")
        self.path = os.path.join(self.dir, "chronicle.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def _seed(self, version, *, with_novelty=False, with_occurrence=False):
        """A raw store as some older build left it, stamped `version`."""
        conn = sqlite3.connect(self.path)
        conn.executescript(_V5_SUBSET)
        if with_novelty:
            for t in BELIEF_TABLES:
                conn.execute("ALTER TABLE %s ADD COLUMN novelty REAL" % t)
        if with_occurrence:
            for t in BELIEF_TABLES:
                conn.execute(
                    "ALTER TABLE %s ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 1" % t)
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)", (str(version),))
        conn.execute("INSERT INTO facts(belief_id, entity_id, attribute, value, owner, domain, "
                     "status, read_acl, provenance, created_at, last_seen_at, valid_from) "
                     "VALUES('b_old','pat_testley','works_at','Acme Fake Co',"
                     "'default','user','active','[\"*\"]','{}',"
                     "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
        conn.commit()
        conn.close()

    def _assert_fully_migrated(self, store):
        conn = store._conn()
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        for t in BELIEF_TABLES:
            self.assertTrue(_has_col(conn, t, "novelty"), "%s missing novelty" % t)
            self.assertTrue(_has_col(conn, t, "occurrence_count"),
                            "%s missing occurrence_count" % t)
        for t in _NEW_TABLES:
            self.assertTrue(_has_table(conn, t), "%s missing" % t)
        # The pre-existing row survived the whole chain.
        row = store.get_belief("facts", "b_old")
        self.assertIsNotNone(row)
        self.assertEqual(row["value"], "Acme Fake Co")
        # occurrence_count backfills to a TRUTHFUL 1 (the row IS one
        # occurrence), never 0 or NULL.
        self.assertEqual(row["occurrence_count"], 1)


class TestUpgradeFromEveryEntryPoint(_LadderCase):
    """A store stamped at any prior version converges to the full shape."""

    def test_a_raw_v5_store_upgrades_through_the_whole_chain(self):
        self._seed(5)
        self._assert_fully_migrated(MemoryStore(self.path))

    def test_a_v6_midstate_store_upgrades(self):
        """Only reachable because of the renumbering: a build that shipped E5's
        novelty step alone stamped this store 6."""
        self._seed(6, with_novelty=True)
        self._assert_fully_migrated(MemoryStore(self.path))

    def test_a_v7_midstate_store_upgrades(self):
        self._seed(7, with_novelty=True, with_occurrence=True)
        self._assert_fully_migrated(MemoryStore(self.path))

    def test_a_store_stamped_6_by_a_DIFFERENT_feature_still_converges(self):
        """The renumbering's whole point. A pre-integration E7 or H1 build also
        stamped 6, but for tables, not columns -- so a store can be stamped 6
        while MISSING novelty entirely. Because each step probes rather than
        trusting the stamp, it still converges."""
        self._seed(6)                      # stamped 6, but no novelty column
        conn = sqlite3.connect(self.path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(facts)").fetchall()]
        conn.close()
        self.assertNotIn("novelty", cols, "fixture was supposed to lack novelty")
        self._assert_fully_migrated(MemoryStore(self.path))


class TestLadderIsReentrant(_LadderCase):
    def test_reopening_is_idempotent(self):
        self._seed(5)
        first = MemoryStore(self.path)
        self._assert_fully_migrated(first)
        cols_before = {t: len(first._conn().execute("PRAGMA table_info(%s)" % t).fetchall())
                       for t in BELIEF_TABLES}
        # Reopen twice more: no duplicate columns, no error, same version.
        for _ in range(2):
            store = MemoryStore(self.path)
            self._assert_fully_migrated(store)
        cols_after = {t: len(store._conn().execute("PRAGMA table_info(%s)" % t).fetchall())
                      for t in BELIEF_TABLES}
        self.assertEqual(cols_before, cols_after, "a reopen added columns")

    def test_a_dropped_table_is_recreated_by_the_probe(self):
        """Exercises the _has_table branch directly: the stamp already says 9,
        so only the probe (not the version check) can bring the table back."""
        store = MemoryStore(self.path)
        conn = store._conn()
        for t in _NEW_TABLES:
            conn.execute("DROP TABLE %s" % t)
        conn.commit()
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        conn2 = MemoryStore(self.path)._conn()
        for t in _NEW_TABLES:
            self.assertTrue(_has_table(conn2, t), "%s not recreated" % t)


class TestVersionIsStampedLast(_LadderCase):
    def test_an_interrupted_migration_does_not_claim_the_new_version(self):
        """The stamp is the LAST statement in _migrate, so a failure partway
        leaves the OLD version and the next open re-runs the chain.

        Interruption is injected through store._has_col -- the probe every
        column step calls -- rather than by patching sqlite3.Connection, whose
        C-level attributes cannot be reassigned."""
        self._seed(5)

        class _Boom(Exception):
            pass

        import engine.store as store_mod
        real_has_col = store_mod._has_col
        state = {"armed": True}

        def flaky(conn, table, col):
            if state["armed"] and col == "occurrence_count":
                raise _Boom("simulated interruption")
            return real_has_col(conn, table, col)

        store_mod._has_col = flaky
        try:
            with self.assertRaises(_Boom):
                MemoryStore(self.path)
        finally:
            store_mod._has_col = real_has_col
            state["armed"] = False

        # The version was NOT advanced by the partial run...
        conn = sqlite3.connect(self.path)
        stamped = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        conn.close()
        self.assertNotEqual(stamped, str(SCHEMA_VERSION))
        # ...and a clean reopen converges anyway.
        self._assert_fully_migrated(MemoryStore(self.path))


if __name__ == "__main__":
    unittest.main()
