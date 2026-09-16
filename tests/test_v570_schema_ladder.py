"""
Chronicle v5.7.0 — the merged schema ladder, walked from a REAL v11 store.

WHY THIS FILE EXISTS. Six independent ladder-10 trees each added a migration
rung and, between them, claimed version 12 or 13 four times over. The v5.7.0
integration sequences them into ONE chain (engine/store.py's ladder comment):

    12  procedures.body                                   A0fix
    13  session_index.model                               A0e2
    14  rerank_hints.principal                            A1   (claimed 12)
    15  goals/reflections.owner, .read_acl                A1b  (claimed 13)
    16  maintenance_runs                                  A3   (claimed 12)
    17  curation_jobs task CHECK narrowed + rebuilt       A13  (claimed 13)
    18  queue + vector-census indexes                     A7   (claimed 13)

`tests/test_l9_schema_ladder.py` covers the ladder-9 rungs, and only A3 (of the
ladder-10 trees) extended it — so the rungs from A0fix, A0e2, A1, A1b, A7 and
A13 had NO coverage of the walk itself. Each tree tested its own rung against
its own parent; nothing tested all seven in one chain, which is precisely the
thing the renumbering could break.

THE FIXTURE IS A REAL v11 STORE, not a hand-written one. It is built by
v5.6.0's OWN CODE, in a subprocess whose cwd and sys.path are the shipped
v5.6.0 worktree (`../v560`, commit c7ca775, SCHEMA_VERSION = 11), through
ChronicleMemoryProvider over h1_store_dump.TURNS. A hand-rolled CREATE TABLE
would be this integrator's idea of what v11 looked like; this is what v11
actually was. The store is then opened IN-PROCESS by the merged MemoryStore,
which is the upgrade under test.

Fake fixtures only (Pat Testley, Acme Fake Co), offline (hashing embedder).

NOT COVERED HERE: the plan's "fixture 2", a read-only snapshot of the live VPS
store. No such snapshot exists on this box, so the rebuild's wall time at
production scale (A7's notes cite a 105k-row embed backlog, and rung 17 copies
every row under the write lock) is UNMEASURED. That is a gap, not a pass.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.store import (  # noqa: E402
    CURATION_TASKS,
    RETIRED_CURATION_TASKS,
    SCHEMA_VERSION,
    MemoryStore,
)

HERE = Path(__file__).parent.parent
#: The shipped v5.6.0 worktree. Read-only: the fixture subprocess only imports
#: from it and writes its database into a temp dir.
V560 = Path(os.environ.get("CHRONICLE_V560_TREE") or (HERE.parent / "v560"))

#: Every index the merged ladder must leave behind (plan D.2, assertion 5).
#: idx_jobs_ready / idx_jobs_dedupe predate ladder 10; the next three are rung
#: 18's queue indexes; the three *_model_width are rung 18's expression indexes;
#: idx_rerank_hints_owner is ladder-9 F4c's, and it is here because rung 17
#: REBUILDS curation_jobs and rung 18 runs after it -- an index lost to a
#: rebuild is exactly the failure this list is watching for.
REQUIRED_INDEXES = (
    "idx_jobs_ready", "idx_jobs_dedupe",
    "idx_jobs_task_ready", "idx_jobs_lease", "idx_jobs_terminal",
    "idx_ov_model_width", "idx_mv_model_width", "idx_qpv_model_width",
    "idx_rerank_hints_owner",
)

# The subprocess that builds the fixture. It runs entirely inside v5.6.0: the
# provider, the reducer, the curation worker and the schema are all v11's.
_BUILD_V11 = r'''
import json, os, sys
TREE = sys.argv[1]
DB_HOME = sys.argv[2]
sys.path.insert(0, TREE)
os.environ["CHRONICLE_EMBED_MODEL"] = "hashing"

import engine.core  # noqa: F401
sys.path.insert(0, os.path.join(TREE, "tests"))
from h1_store_dump import TURNS, _freeze_clock
from provider import ChronicleMemoryProvider

_freeze_clock()
prov = ChronicleMemoryProvider()
# host_model.piggyback ON, so host_model_* and rerank_hints carry rows -- the
# tables rungs 14 and 17 touch must not be empty, or the migration would be
# proved only against a store with nothing in it.
prov.initialize("s-ladder", hermes_home=DB_HOME, principal_id="assistant",
                config={"embeddings": {"model": "hashing"},
                        "host_model": {"piggyback": True}})
for user, assistant in TURNS:
    if hasattr(prov, "pre_llm_call"):
        prov.pre_llm_call()
    prov.sync_turn(user, assistant, session_id="s-ladder")
    prov.core.process_pending()
prov.on_session_end([])
prov.core.process_pending()

store = prov.core.store
# A rerank_hints row, written through v11's own writer so its column set is
# v11's. piggyback alone does not guarantee a host reply in an offline run.
with store.transaction() as c:
    c.execute("INSERT OR REPLACE INTO rerank_hints"
              "(query_key,belief_id,weight,tokens,query_text,created_at,expires_at,owner) "
              "VALUES('qk_fake','b_fake',0.5,'[]','where does Pat work',"
              "'2026-01-02T03:04:05.00Z','2036-01-02T03:04:05.00Z','default')")
    # A goal and a reflection, for rung 15. Columns are v5.6.0's own
    # (goals.id/goal, reflections.id/situation/...), not the merged build's.
    c.execute("INSERT OR REPLACE INTO goals(id,goal,status,created_at) "
              "VALUES('g_fake','ship the fake release','active','2026-01-02T03:04:05.00Z')")
    c.execute("INSERT OR REPLACE INTO reflections"
              "(id,situation,action,outcome,lesson,applicability,created_at) "
              "VALUES('r_fake','a fake retro','wrote it down','fine','keep notes','general',"
              "'2026-01-02T03:04:05.00Z')")

# Rung 17's whole subject: jobs queued under task names this build admits and
# the merged build retires. Both pending and done, plus a depends_on edge.
ids = {}
for task, status in (("route", "pending"), ("route", "done"),
                     ("criticality", "pending"), ("criticality", "done"),
                     ("contradiction", "pending"), ("contradiction", "done"),
                     ("consistency", "pending")):
    with store.transaction() as c:
        cur = c.execute(
            "INSERT INTO curation_jobs(task,payload,status,created_at,finished_at) "
            "VALUES(?,?,?,'2026-01-02T03:04:05.00Z',?)",
            (task, json.dumps({"fixture": task + "/" + status}), status,
             "2026-01-02T03:04:06.00Z" if status == "done" else None))
        ids[task + ":" + status] = cur.lastrowid
with store.transaction() as c:
    cur = c.execute(
        "INSERT INTO curation_jobs(task,payload,status,created_at,depends_on) "
        "VALUES('extract',?,'pending','2026-01-02T03:04:05.00Z',?)",
        (json.dumps({"fixture": "dependent"}), ids["consistency:pending"]))
    ids["extract:dependent"] = cur.lastrowid

assert store.get_meta("schema_version") == "11", store.get_meta("schema_version")
print(json.dumps({"db": store.path if hasattr(store, "path") else "",
                  "ids": ids}))
'''


def _sqlite_master_indexes(conn):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_autoindex_%'").fetchall()}


def _table_names(conn):
    return sorted(r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'").fetchall())


def _table_info(conn, table):
    return [tuple(r) for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _canonical_dump(conn, table, columns):
    """Every row of `table`, restricted to `columns`, sorted -- comparable
    across an upgrade that must not touch the data."""
    cols = ",".join('"%s"' % c for c in columns)
    rows = [tuple("" if v is None else v for v in r)
            for r in conn.execute("SELECT %s FROM %s" % (cols, table)).fetchall()]
    return sorted(repr(r) for r in rows)


class _LadderCase(unittest.TestCase):
    """One real v11 store per test, built by v5.6.0's own code."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        if not (V560 / "provider.py").exists():
            raise unittest.SkipTest("v5.6.0 worktree not available at %s" % V560)
        cls._master = tempfile.mkdtemp(prefix="v570-ladder-master-")
        proc = subprocess.run(
            [sys.executable, "-c", _BUILD_V11, str(V560), cls._master],
            cwd=str(V560), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            shutil.rmtree(cls._master, ignore_errors=True)
            raise AssertionError("v11 fixture build failed:\n%s"
                                 % proc.stderr.decode()[-4000:])
        cls.fixture_ids = json.loads(proc.stdout.decode().strip().splitlines()[-1])["ids"]
        cls._master_db = os.path.join(cls._master, "chronicle.db")
        if not os.path.exists(cls._master_db):
            found = [os.path.join(dp, f) for dp, _dn, fn in os.walk(cls._master)
                     for f in fn if f.endswith(".db")]
            assert found, "fixture produced no database under %s" % cls._master
            cls._master_db = found[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "_master", ""), ignore_errors=True)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v570-ladder-")
        self.db = os.path.join(self.dir, "chronicle.db")
        shutil.copy(self._master_db, self.db)
        self.pre = sqlite3.connect(self.db)
        self.pre.row_factory = sqlite3.Row
        self.pre_tables = _table_names(self.pre)
        self.pre_cols = {t: [c[1] for c in _table_info(self.pre, t)] for t in self.pre_tables}
        self.pre_counts = {t: self.pre.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                           for t in self.pre_tables}
        self.pre_dumps = {t: _canonical_dump(self.pre, t, self.pre_cols[t])
                          for t in self.pre_tables}
        self.pre.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _upgraded(self):
        return MemoryStore(self.db)

    def _conn(self):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        return c


class TestTheFixtureIsReallyV11(_LadderCase):
    def test_it_was_built_by_v560_and_stamped_11(self):
        conn = self._conn()
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            "11")
        # …and it does NOT already carry any ladder-10 rung.
        cols = {c[1] for c in _table_info(conn, "procedures")}
        self.assertNotIn("body", cols)
        self.assertNotIn("model", {c[1] for c in _table_info(conn, "session_index")})
        self.assertNotIn("principal", {c[1] for c in _table_info(conn, "rerank_hints")})
        self.assertNotIn("owner", {c[1] for c in _table_info(conn, "goals")})
        self.assertNotIn("maintenance_runs", _table_names(conn))
        conn.close()

    def test_the_planted_rows_are_there(self):
        conn = self._conn()
        tasks = [r[0] for r in conn.execute("SELECT task FROM curation_jobs").fetchall()]
        for t in RETIRED_CURATION_TASKS:
            self.assertIn(t, tasks, t)
        self.assertTrue(conn.execute("SELECT COUNT(*) FROM rerank_hints").fetchone()[0])
        self.assertTrue(conn.execute("SELECT COUNT(*) FROM session_index").fetchone()[0])
        conn.close()


class TestTheWalkReachesTheTop(_LadderCase):
    """Assertions 1-3 and 5 of plan D.2."""

    def test_1_the_stamp_is_the_top_of_the_merged_ladder(self):
        store = self._upgraded()
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        self.assertEqual(SCHEMA_VERSION, 18)

    def test_2_every_column_rung_landed_with_its_declared_shape(self):
        self._upgraded()
        conn = self._conn()

        def col(table, name):
            for c in _table_info(conn, table):
                if c[1] == name:
                    return {"type": c[2], "notnull": c[3], "default": c[4]}
            return None

        # 12 / 13: no default, nullable -- the legacy-NULL rule.
        for table, name in (("procedures", "body"), ("session_index", "model")):
            c = col(table, name)
            self.assertIsNotNone(c, "%s.%s missing" % (table, name))
            self.assertEqual(c["type"], "TEXT")
            self.assertEqual(c["notnull"], 0)
            self.assertIsNone(c["default"])
        # 14: NOT NULL DEFAULT '' -- and `owner` (ladder-9 F4c) still present.
        c = col("rerank_hints", "principal")
        self.assertIsNotNone(c, "rerank_hints.principal missing")
        self.assertEqual(c["type"], "TEXT")
        self.assertEqual(c["notnull"], 1)
        self.assertEqual(str(c["default"]).strip("'\""), "")
        self.assertIsNotNone(col("rerank_hints", "owner"))
        # 15: four nullable, defaultless columns.
        for table in ("goals", "reflections"):
            for name in ("owner", "read_acl"):
                c = col(table, name)
                self.assertIsNotNone(c, "%s.%s missing" % (table, name))
                self.assertEqual(c["type"], "TEXT")
                self.assertEqual(c["notnull"], 0)
                self.assertIsNone(c["default"])
        conn.close()

    def test_3_the_maintenance_runs_table_exists(self):
        self._upgraded()
        conn = self._conn()
        self.assertIn("maintenance_runs", _table_names(conn))
        conn.close()

    def test_5_every_declared_index_exists(self):
        self._upgraded()
        conn = self._conn()
        names = set(_sqlite_master_indexes(conn))
        for idx in REQUIRED_INDEXES:
            self.assertIn(idx, names, "%s is missing after the walk" % idx)
        conn.close()

    def test_5b_the_rebuild_did_not_eat_the_queue_indexes(self):
        """The H2 cross-rung case, with A7's REAL indexes rather than the
        hypothetical lease columns tests/test_a13_retired_task_migration.py
        uses. Rung 17 rebuilds curation_jobs by replaying sqlite_master; rung 18
        creates A7's three queue indexes. Whichever way they run, all five
        curation_jobs indexes must be on the table at the end AND must name
        `curation_jobs`, not a leftover `curation_jobs_new`."""
        self._upgraded()
        conn = self._conn()
        idx = _sqlite_master_indexes(conn)
        on_jobs = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='curation_jobs' "
            "AND name NOT LIKE 'sqlite_autoindex_%'").fetchall()}
        for name in ("idx_jobs_ready", "idx_jobs_dedupe", "idx_jobs_task_ready",
                     "idx_jobs_lease", "idx_jobs_terminal"):
            self.assertIn(name, on_jobs, name)
            self.assertNotIn("curation_jobs_new", idx[name] or "")
        self.assertNotIn("curation_jobs_new", _table_names(conn))
        conn.close()


class TestCurationJobsRung17(_LadderCase):
    """Assertion 4 of plan D.2."""

    def test_the_check_admits_exactly_curation_tasks(self):
        store = self._upgraded()
        sql = store._conn().execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='curation_jobs'"
        ).fetchone()[0]
        for task in CURATION_TASKS:
            self.assertIn("'%s'" % task, sql, task)
        for task in RETIRED_CURATION_TASKS:
            self.assertNotIn("'%s'" % task, sql, task)

    def test_inserting_a_retired_task_raises_on_upgraded_and_on_fresh(self):
        store = self._upgraded()
        with self.assertRaises(sqlite3.IntegrityError):
            with store.transaction() as c:
                c.execute("INSERT INTO curation_jobs(task,payload,status,created_at) "
                          "VALUES('route','{}','pending','2026-01-02T03:04:05.00Z')")
        fresh_dir = tempfile.mkdtemp(prefix="v570-fresh-")
        try:
            fresh = MemoryStore(os.path.join(fresh_dir, "chronicle.db"))
            with self.assertRaises(sqlite3.IntegrityError):
                with fresh.transaction() as c:
                    c.execute("INSERT INTO curation_jobs(task,payload,status,created_at) "
                              "VALUES('route','{}','pending','2026-01-02T03:04:05.00Z')")
        finally:
            shutil.rmtree(fresh_dir, ignore_errors=True)

    def test_contradiction_rows_became_consistency_and_kept_everything_else(self):
        pre = {}
        conn = self._conn()
        for r in conn.execute("SELECT id,payload,status,finished_at FROM curation_jobs "
                              "WHERE task='contradiction'").fetchall():
            pre[r["id"]] = (r["payload"], r["status"], r["finished_at"])
        conn.close()
        self.assertTrue(pre, "fixture planted no contradiction rows")

        self._upgraded()
        conn = self._conn()
        for jid, (payload, status, finished) in pre.items():
            row = conn.execute("SELECT task,payload,status,finished_at FROM curation_jobs "
                               "WHERE id=?", (jid,)).fetchone()
            self.assertIsNotNone(row, "contradiction row %s vanished" % jid)
            self.assertEqual(row["task"], "consistency")
            self.assertEqual(row["payload"], payload)
            self.assertEqual(row["status"], status)
            self.assertEqual(row["finished_at"], finished)
        conn.close()

    def test_retired_rows_are_recorded_in_meta_at_this_ladders_version(self):
        store = self._upgraded()
        raw = store.get_meta("curation_tasks_retired")
        self.assertTrue(raw, "nothing recorded the retirement")
        rec = json.loads(raw)
        self.assertEqual(str(rec.get("schema_version")), str(SCHEMA_VERSION))
        self.assertEqual(str(rec.get("schema_version")), "18")

    def test_the_depends_on_edge_still_resolves(self):
        dep_id = self.fixture_ids["extract:dependent"]
        parent_id = self.fixture_ids["consistency:pending"]
        self._upgraded()
        conn = self._conn()
        row = conn.execute("SELECT depends_on FROM curation_jobs WHERE id=?",
                           (dep_id,)).fetchone()
        self.assertEqual(row["depends_on"], parent_id)
        self.assertIsNotNone(
            conn.execute("SELECT 1 FROM curation_jobs WHERE id=?", (parent_id,)).fetchone(),
            "the parent of the depends_on edge did not survive the rebuild")
        conn.close()


class TestNothingOutsideTheDeclaredRungsMoved(_LadderCase):
    """Assertion 6 of plan D.2 -- the one that catches a rung with a side
    effect nobody declared."""

    def test_row_counts_are_unchanged_except_for_retired_jobs(self):
        self._upgraded()
        conn = self._conn()
        dropped = len([t for t in ("route", "criticality") for _ in range(0)])  # see below
        for table in self.pre_tables:
            after = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            if table == "curation_jobs":
                # route/criticality rows are retired per A13; nothing else moves.
                self.assertLessEqual(after, self.pre_counts[table], table)
                continue
            if table == "meta":
                # schema_version is updated in place; curation_tasks_retired is
                # a new key, which is the rung declaring what it did.
                self.assertGreaterEqual(after, self.pre_counts[table], table)
                continue
            self.assertEqual(after, self.pre_counts[table],
                             "%s changed row count during the walk" % table)
        self.assertEqual(dropped, 0)
        conn.close()

    def test_every_preexisting_table_dumps_byte_identically(self):
        self._upgraded()
        conn = self._conn()
        for table in self.pre_tables:
            if table in ("curation_jobs", "meta"):
                continue          # asserted separately above
            self.assertEqual(
                _canonical_dump(conn, table, self.pre_cols[table]),
                self.pre_dumps[table],
                "%s was rewritten by a rung that does not declare it" % table)
        conn.close()

    def test_curation_jobs_rows_that_are_not_retired_are_untouched(self):
        conn = self._conn()
        keep_cols = self.pre_cols["curation_jobs"]
        before = {}
        for r in conn.execute("SELECT %s FROM curation_jobs"
                              % ",".join('"%s"' % c for c in keep_cols)).fetchall():
            row = dict(zip(keep_cols, tuple(r)))
            if row["task"] in RETIRED_CURATION_TASKS:
                continue
            before[row["id"]] = row
        conn.close()
        self.assertTrue(before)

        self._upgraded()
        conn = self._conn()
        for jid, row in before.items():
            after = conn.execute("SELECT %s FROM curation_jobs WHERE id=?"
                                 % ",".join('"%s"' % c for c in keep_cols),
                                 (jid,)).fetchone()
            self.assertIsNotNone(after, "job %s vanished" % jid)
            self.assertEqual(dict(zip(keep_cols, tuple(after))), row)
        conn.close()


class TestFreshEqualsUpgraded(_LadderCase):
    """Assertion 7 of plan D.2 -- the one that catches a rung whose DDL never
    made it into the _SCHEMA splice, which is invisible until a fresh install
    and a migrated one disagree in production."""

    def test_every_table_has_the_same_shape_either_way(self):
        self._upgraded()
        up = self._conn()
        fresh_dir = tempfile.mkdtemp(prefix="v570-fresh-")
        try:
            fresh_path = os.path.join(fresh_dir, "chronicle.db")
            MemoryStore(fresh_path)
            fr = sqlite3.connect(fresh_path)
            fr.row_factory = sqlite3.Row
            for table in _table_names(fr):
                self.assertIn(table, _table_names(up), "%s only exists on a fresh store" % table)
                self.assertEqual(_table_info(up, table), _table_info(fr, table),
                                 "%s has a different shape upgraded vs fresh" % table)
            fr.close()
        finally:
            shutil.rmtree(fresh_dir, ignore_errors=True)
        up.close()

    def test_the_index_set_is_the_same_either_way(self):
        self._upgraded()
        up = self._conn()
        fresh_dir = tempfile.mkdtemp(prefix="v570-fresh-")
        try:
            fresh_path = os.path.join(fresh_dir, "chronicle.db")
            MemoryStore(fresh_path)
            fr = sqlite3.connect(fresh_path)
            self.assertEqual(sorted(_sqlite_master_indexes(fr)),
                             sorted(_sqlite_master_indexes(up)))
            fr.close()
        finally:
            shutil.rmtree(fresh_dir, ignore_errors=True)
        up.close()


class TestReentrant(_LadderCase):
    """Assertion 8 of plan D.2."""

    def test_a_second_open_changes_nothing(self):
        self._upgraded()
        conn = self._conn()
        master = sorted((r[0], r[1], r[2]) for r in conn.execute(
            "SELECT type, name, sql FROM sqlite_master").fetchall())
        conn.close()
        with self.assertLogs("chronicle.store", level="INFO") as cm:
            import logging
            logging.getLogger("chronicle.store").info("sentinel")
            MemoryStore(self.db)
        self.assertEqual([m for m in cm.output if "schema migration:" in m], [],
                         "a re-open re-ran a rung")
        conn = self._conn()
        self.assertEqual(sorted((r[0], r[1], r[2]) for r in conn.execute(
            "SELECT type, name, sql FROM sqlite_master").fetchall()), master)
        conn.close()


class TestTheStampIsLast(_LadderCase):
    """Assertion 9 of plan D.2 -- an interrupted migration must NOT claim a
    shape it never reached."""

    def test_a_rung_that_raises_leaves_the_old_stamp(self):
        import engine.store as store_mod
        boom = list(store_mod._JOBS_INDEX_DDLS) + ["CREATE INDEX definitely not sql"]
        original = store_mod._JOBS_INDEX_DDLS
        store_mod._JOBS_INDEX_DDLS = tuple(boom)
        try:
            with self.assertRaises(sqlite3.Error):
                MemoryStore(self.db)
        finally:
            store_mod._JOBS_INDEX_DDLS = original
        conn = self._conn()
        self.assertEqual(
            conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
            "11", "the stamp moved even though the last rung failed")
        conn.close()
        # …and with the patch gone it converges.
        store = MemoryStore(self.db)
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))


class TestAStoreStampedByADifferentClaimant(_LadderCase):
    """Assertion 10 of plan D.2, and the whole point of the renumbering.

    Four trees shipped a store stamped 12 and four shipped one stamped 13, each
    meaning a DIFFERENT rung. A v5.7.0 build meeting any of those eight stores
    must converge to 18 with every rung present -- which it does because the
    number is bookkeeping and each rung probes the live schema. This
    generalises ladder 9's
    `test_a_store_stamped_6_by_a_DIFFERENT_feature_still_converges`.
    """

    def _stamp_and_converge(self, number, rung):
        """Apply ONE claimant's rung by hand, stamp the store with the number
        THAT claimant used, then open it with the merged build."""
        conn = sqlite3.connect(self.db)
        rung(conn)
        conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(number),))
        conn.commit()
        conn.close()
        store = MemoryStore(self.db)
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        c = self._conn()
        cols = lambda t: {x[1] for x in _table_info(c, t)}          # noqa: E731
        self.assertIn("body", cols("procedures"))
        self.assertIn("model", cols("session_index"))
        self.assertIn("principal", cols("rerank_hints"))
        self.assertIn("owner", cols("goals"))
        self.assertIn("read_acl", cols("reflections"))
        self.assertIn("maintenance_runs", _table_names(c))
        sql = c.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                        "AND name='curation_jobs'").fetchone()[0]
        for task in RETIRED_CURATION_TASKS:
            self.assertNotIn("'%s'" % task, sql, task)
        names = set(_sqlite_master_indexes(c))
        for idx in REQUIRED_INDEXES:
            self.assertIn(idx, names, idx)
        c.close()

    def test_12_as_a0fix_meant_it(self):
        self._stamp_and_converge(
            12, lambda c: c.execute("ALTER TABLE procedures ADD COLUMN body TEXT"))

    def test_12_as_a1_meant_it(self):
        self._stamp_and_converge(
            12, lambda c: c.execute("ALTER TABLE rerank_hints ADD COLUMN principal "
                                    "TEXT NOT NULL DEFAULT ''"))

    def test_12_as_a3_meant_it(self):
        import engine.store as store_mod
        self._stamp_and_converge(12, lambda c: c.executescript(store_mod._MAINTENANCE_DDL))

    def test_13_as_a0e2_meant_it(self):
        self._stamp_and_converge(
            13, lambda c: c.execute("ALTER TABLE session_index ADD COLUMN model TEXT"))

    def test_13_as_a1b_meant_it(self):
        def rung(c):
            for t in ("goals", "reflections"):
                for col in ("owner", "read_acl"):
                    c.execute("ALTER TABLE %s ADD COLUMN %s TEXT" % (t, col))
        self._stamp_and_converge(13, rung)

    def test_13_as_a7_meant_it(self):
        import engine.store as store_mod

        def rung(c):
            for ddl in store_mod._JOBS_INDEX_DDLS + store_mod._VECTOR_CENSUS_INDEX_DDLS:
                c.execute(ddl)
        self._stamp_and_converge(13, rung)

    def test_13_as_a13_meant_it(self):
        """A13's rung is the only one that cannot be replayed by hand here --
        narrowing the CHECK IS the rebuild. Stamping 13 on a store whose CHECK
        is still wide is the honest version of "another tree called its rung
        13": the merged build must still narrow it."""
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE meta SET value='13' WHERE key='schema_version'")
        conn.commit()
        conn.close()
        store = MemoryStore(self.db)
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        sql = store._conn().execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='curation_jobs'"
        ).fetchone()[0]
        for task in RETIRED_CURATION_TASKS:
            self.assertNotIn("'%s'" % task, sql, task)


if __name__ == "__main__":
    unittest.main(verbosity=2)
