"""
Chronicle — schema_version 13: retiring three curation task names (A13).

Every earlier rung of the migration ladder ADDS (a column, a table, a permitted
value), so every earlier probe asks "is this thing missing?". This one removes,
which makes it the first rung with two properties nothing before it had:

  * its probe has to look for a value that is PRESENT — a store whose CHECK
    still admits `route` keeps admitting it forever otherwise, because
    `CREATE TABLE IF NOT EXISTS` cannot narrow an existing constraint. A fresh
    install would reject the enqueue and an upgraded store would accept it: the
    exact shape-drift the ladder exists to prevent.
  * it has to resolve rows that already exist under the retired names BEFORE
    the table rebuild copies them, because the copy INSERT is checked against
    the NEW, narrower CHECK and one surviving row aborts the whole migration.

The two outcomes are deliberately different, and that difference is the point of
these tests: `contradiction` rows are RE-TASKED to `consistency` (the handler
they would have run was that same sweep, so the row's name becomes true rather
than lost), while `route`/`criticality` rows are DROPPED and recorded (no build
ever had a handler for them, so they were never work that was waiting).
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

from engine.store import (CURATION_TASKS, RETIRED_CURATION_TASKS, SCHEMA_VERSION,
                          MemoryStore, _has_col)

# The curation_jobs table EXACTLY as builds up to schema_version 12 created it:
# the wide CHECK, with 'route', 'criticality' and 'contradiction' in it. Restated
# verbatim rather than derived, because deriving it from the current constant
# would make the fixture change whenever the thing under test changes.
_PRE_A13_JOBS_DDL = """CREATE TABLE IF NOT EXISTS curation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT CHECK(task IN ('extract','route','criticality','canonicalize','consolidate',
        'contradiction','identity','derive','verify','decay','consistency','health','reextract',
        'journal_ingest','session_summarize','embed','digest','federate_sweep','backfill_sweep')),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT,
    run_after TEXT);"""

# …and the schema_version 1 shape, which predates run_after entirely: the
# migration has to add the column AND narrow the CHECK on the same open.
_V1_JOBS_DDL = _PRE_A13_JOBS_DDL.replace(",\n    run_after TEXT);", ");")

_TS = "2026-01-01T00:00:00.00Z"


class _MigrationCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="a13-migrate-")
        self.path = os.path.join(self.dir, "chronicle.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _seed(self, jobs, *, ddl=_PRE_A13_JOBS_DDL, version=12):
        """A store as a pre-A13 build left it: wide CHECK, `jobs` queued."""
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.executescript(ddl)
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)", (str(version),))
        for task, payload, status in jobs:
            conn.execute("INSERT INTO curation_jobs(task,payload,status,created_at) "
                         "VALUES(?,?,?,?)", (task, payload, status, _TS))
        conn.commit()
        conn.close()

    def _jobs(self, store):
        return [dict(r) for r in store._conn().execute(
            "SELECT id, task, payload, status FROM curation_jobs ORDER BY id").fetchall()]

    def _check_sql(self, store):
        return store._conn().execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='curation_jobs'"
        ).fetchone()[0]


class TestTheCheckIsActuallyNarrowed(_MigrationCase):
    def test_an_upgraded_store_rejects_what_a_fresh_one_rejects(self):
        """The drift test. Before this rung, an upgraded store's CHECK was
        whatever the build that created it wrote, forever."""
        self._seed([])
        store = MemoryStore(self.path)
        sql = self._check_sql(store)
        for task in RETIRED_CURATION_TASKS:
            self.assertNotIn("'%s'" % task, sql, task)
        for task in CURATION_TASKS:
            self.assertIn("'%s'" % task, sql, task)
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        with self.assertRaises(sqlite3.IntegrityError):
            with store.transaction() as conn:
                conn.execute("INSERT INTO curation_jobs(task,payload,created_at) "
                             "VALUES('route','{}',?)", (_TS,))

    def test_a_v1_store_gains_run_after_and_loses_the_retired_names_at_once(self):
        """Both probes fire on one open, and in an order that works: run_after
        is ADDed to the old table before the rebuild copies its columns."""
        self._seed([("route", "{}", "pending"), ("extract", '{"event_id": "e1"}', "pending")],
                   ddl=_V1_JOBS_DDL, version=1)
        store = MemoryStore(self.path)
        self.assertTrue(_has_col(store._conn(), "curation_jobs", "run_after"))
        self.assertNotIn("'route'", self._check_sql(store))
        self.assertEqual([j["task"] for j in self._jobs(store)], ["extract"])

    def test_reopening_is_idempotent(self):
        """Once narrowed, the `retired` probe finds nothing and no rebuild runs
        — so a reopen must not disturb ids, rows or the version."""
        self._seed([("extract", '{"event_id": "e1"}', "pending"),
                    ("contradiction", "{}", "pending")])
        first = MemoryStore(self.path)
        before = self._jobs(first)
        for _ in range(2):
            store = MemoryStore(self.path)
            self.assertEqual(self._jobs(store), before)
            self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))


class TestContradictionRowsAreRetaskedNotLost(_MigrationCase):
    def test_a_pending_contradiction_becomes_a_pending_consistency(self):
        """It is real, runnable work: _task_contradiction's body was
        health.consistency_sweep(), which is _task_consistency's body."""
        self._seed([("contradiction", "{}", "pending")])
        jobs = self._jobs(MemoryStore(self.path))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["task"], "consistency")
        self.assertEqual(jobs[0]["status"], "pending")

    def test_a_finished_contradiction_row_keeps_its_history(self):
        """A done row is a true record that a consistency sweep ran; renaming it
        keeps that true rather than erasing it."""
        self._seed([("contradiction", "{}", "done"), ("contradiction", "{}", "failed")])
        jobs = self._jobs(MemoryStore(self.path))
        self.assertEqual([(j["task"], j["status"]) for j in jobs],
                         [("consistency", "done"), ("consistency", "failed")])

    def test_the_rename_cannot_break_the_dedupe_invariant(self):
        """enqueue_curation collapses an identical (task, payload) that is
        pending or running. A rename that produced a second live
        ('consistency', '{}') would smuggle a duplicate past that guard and
        sweep twice for one answer, so the duplicate is collapsed first."""
        self._seed([("consistency", "{}", "pending"),
                    ("contradiction", "{}", "pending"),
                    ("contradiction", "{}", "running")])
        jobs = self._jobs(MemoryStore(self.path))
        live = [j for j in jobs if j["status"] in ("pending", "running")]
        self.assertEqual(len(live), 1, live)
        self.assertEqual(live[0]["task"], "consistency")

    def test_a_finished_row_is_not_treated_as_a_duplicate(self):
        """Only PENDING/RUNNING rows are deduped — a done row is history, and
        collapsing it into a live job would delete the record of a sweep."""
        self._seed([("consistency", "{}", "pending"), ("contradiction", "{}", "done")])
        jobs = self._jobs(MemoryStore(self.path))
        self.assertEqual([(j["task"], j["status"]) for j in jobs],
                         [("consistency", "pending"), ("consistency", "done")])


class TestNoHandlerRowsAreFailedExplicitly(_MigrationCase):
    def test_they_do_not_survive_as_pending_work(self):
        """The defect: a `route` job could be enqueued, and then waited forever
        — claimed, completed 'no_handler', or simply sat there. It is never
        left in that state by an upgrade."""
        self._seed([("route", '{"belief_id": "b1"}', "pending"),
                    ("criticality", "{}", "running"),
                    ("extract", '{"event_id": "e1"}', "pending")])
        store = MemoryStore(self.path)
        self.assertEqual([j["task"] for j in self._jobs(store)], ["extract"])

    def test_what_happened_to_them_is_recorded_durably(self):
        """A row that cannot keep its name cannot be marked 'failed' in place,
        so the failure is recorded where it survives the row: meta. An operator
        who finds a shorter queue can find out why."""
        self._seed([("route", '{"belief_id": "b1"}', "pending"),
                    ("route", "{}", "done"),
                    ("criticality", "{}", "pending")])
        store = MemoryStore(self.path)
        record = json.loads(store.get_meta("curation_tasks_retired"))
        self.assertEqual(record["counts"], {"route": 2, "criticality": 1})
        self.assertEqual(record["schema_version"], SCHEMA_VERSION)
        self.assertIn("no handler", record["reason"])
        self.assertEqual(len(record["job_ids"]), 3)
        self.assertFalse(record["job_ids_truncated"])

    def test_a_clean_store_gains_no_such_record(self):
        """The breadcrumb is evidence of something having happened; a store that
        never queued one of these must not carry it."""
        self._seed([("extract", '{"event_id": "e1"}', "pending")])
        store = MemoryStore(self.path)
        self.assertIsNone(store.get_meta("curation_tasks_retired"))

    def test_a_fresh_store_never_sees_the_migration_at_all(self):
        store = MemoryStore(self.path)
        self.assertIsNone(store.get_meta("curation_tasks_retired"))
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))


class TestSurvivingWorkIsUntouched(_MigrationCase):
    def test_unrelated_jobs_keep_their_ids_payloads_and_status(self):
        """The rebuild copies the table; a copy that renumbered ids would break
        depends_on, which references curation_jobs(id)."""
        self._seed([("extract", '{"event_id": "e1"}', "pending"),
                    ("route", "{}", "pending"),
                    ("digest", '{"entity_id": "x"}', "done"),
                    ("embed", '{"target_id": "t"}', "failed")])
        jobs = self._jobs(MemoryStore(self.path))
        self.assertEqual([(j["id"], j["task"], j["status"]) for j in jobs],
                         [(1, "extract", "pending"), (3, "digest", "done"),
                          (4, "embed", "failed")])

    def test_a_dependency_edge_still_resolves_after_the_rebuild(self):
        self._seed([("extract", '{"event_id": "e1"}', "done")])
        conn = sqlite3.connect(self.path)
        conn.execute("INSERT INTO curation_jobs(task,payload,depends_on,status,created_at) "
                     "VALUES('digest','{}',1,'pending',?)", (_TS,))
        conn.execute("INSERT INTO curation_jobs(task,payload,status,created_at) "
                     "VALUES('route','{}','pending',?)", (_TS,))
        conn.commit()
        conn.close()
        store = MemoryStore(self.path)
        row = store._conn().execute(
            "SELECT depends_on FROM curation_jobs WHERE task='digest'").fetchone()
        self.assertEqual(row["depends_on"], 1)
        # …and claim() honours it: the dependency is 'done', so it is claimable.
        self.assertIsNotNone(store.claim_curation_job())

    def test_the_dedupe_index_survives_the_rebuild(self):
        """_rebuild_curation_jobs recreates the partial indexes by hand; without
        idx_jobs_dedupe every enqueue scans the queue it is trying to shorten."""
        self._seed([("route", "{}", "pending")])
        store = MemoryStore(self.path)
        names = {r[0] for r in store._conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='curation_jobs'"
        ).fetchall()}
        self.assertIn("idx_jobs_dedupe", names)
        self.assertIn("idx_jobs_ready", names)


class TestAnEdgePointingATADeletedRowDoesNotAbortTheMigration(_MigrationCase):
    """The case the v5.7.0 pre-ship review found, and the reason it was missed.

    Three tests already exercised `depends_on` across this rung
    (`test_a_dependency_edge_still_resolves_after_the_rebuild` above,
    `test_v570_schema_ladder.py::test_the_depends_on_edge_still_resolves` and
    `test_queue_fairness.py`) and every one of them pointed the edge at a row
    that SURVIVES. None pointed an edge AT a row this rung deletes — which is
    the only arrangement that can fail.

    Why it fails without the guard: both deletes in `_retire_removed_task_rows`
    are deletes from the PARENT side of `depends_on REFERENCES
    curation_jobs(id)`, and that key is enforced at this point (`__init__` sets
    `PRAGMA foreign_keys=ON`; the only place it is turned off is inside
    `_rebuild_curation_jobs`, which runs after). So an inbound edge raises
    `sqlite3.IntegrityError` inside `_migrate`'s transaction, which propagates
    out of `MemoryStore.__init__`. That is not a degraded start: the store
    cannot be opened AT ALL, and since the migration re-runs on every open and
    fails identically, it stays that way until somebody hand-edits the database.

    Measured before the fix, on a 105k-row v11 store with 8% `depends_on` edges:
    three consecutive opens, three `IntegrityError: FOREIGN KEY constraint
    failed`. Hence `test_and_it_opens_again_and_again` below — one successful
    open would not have distinguished a fix from luck.
    """

    def _dependent_on(self, parent_id, task="extract"):
        """Add a pending `task` row whose depends_on points at `parent_id`."""
        conn = sqlite3.connect(self.path)
        cur = conn.execute(
            "INSERT INTO curation_jobs(task,payload,depends_on,status,created_at) "
            "VALUES(?,'{}',?,'pending',?)", (task, parent_id, _TS))
        conn.commit()
        dep_id = cur.lastrowid
        conn.close()
        return dep_id

    def test_an_edge_into_a_dropped_route_row_does_not_abort_the_open(self):
        self._seed([("route", "{}", "pending")])
        dep = self._dependent_on(1)
        store = MemoryStore(self.path)                     # raised IntegrityError before
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        self.assertIsNotNone(store._conn().execute(
            "SELECT 1 FROM curation_jobs WHERE id=?", (dep,)).fetchone(),
            "the dependent row was collateral damage")

    def test_an_edge_into_a_dropped_criticality_row_does_not_abort_the_open(self):
        self._seed([("criticality", "{}", "running")])
        self._dependent_on(1)
        self.assertEqual(MemoryStore(self.path).get_meta("schema_version"),
                         str(SCHEMA_VERSION))

    def test_and_it_opens_again_and_again(self):
        """The failure was not self-healing: it re-raised on EVERY open. One
        successful open proves nothing, so open three times."""
        self._seed([("route", "{}", "pending"), ("criticality", "{}", "done")])
        self._dependent_on(1)
        self._dependent_on(2)
        for attempt in range(3):
            store = MemoryStore(self.path)
            self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION),
                             "open #%d did not reach the top of the ladder" % (attempt + 1))

    def test_the_dangling_edge_is_nulled_and_the_dependent_becomes_claimable(self):
        """The documented choice for a dropped row: NULL, not retire-the-child.

        `route` had no handler in any build, so it could never reach 'done', so
        `claim_curation_job`'s `depends_on IN (SELECT id ... WHERE
        status='done')` would never fire and the dependent was blocked forever.
        Clearing the edge is what actually removes the never-drains queue depth
        this rung exists to remove."""
        self._seed([("route", "{}", "pending")])
        dep = self._dependent_on(1)
        store = MemoryStore(self.path)
        row = store._conn().execute(
            "SELECT depends_on FROM curation_jobs WHERE id=?", (dep,)).fetchone()
        self.assertIsNone(row["depends_on"])
        self.assertIsNone(store._conn().execute(
            "SELECT 1 FROM curation_jobs WHERE id=1").fetchone(),
            "the route row should be gone")
        claimed = store.claim_curation_job()
        self.assertIsNotNone(claimed, "the unblocked dependent is still not claimable")
        self.assertEqual(claimed["id"], dep)

    def test_an_edge_into_a_collapsed_duplicate_is_repointed_at_the_survivor(self):
        """The other documented choice, and it is deliberately NOT the same one.

        A collapsed `contradiction` row is a duplicate of a live `consistency`
        row with the same payload: the work survives under another id. A
        dependent that was waiting for that sweep should keep waiting for the
        identical one, so its edge moves to the survivor. Nulling here would
        silently let the dependent run BEFORE the sweep it ordered itself
        after."""
        self._seed([("consistency", '{"scope": "all"}', "pending"),     # 1: survivor
                    ("contradiction", '{"scope": "all"}', "pending")])  # 2: collapsed
        dep = self._dependent_on(2)
        store = MemoryStore(self.path)
        conn = store._conn()
        self.assertIsNone(conn.execute("SELECT 1 FROM curation_jobs WHERE id=2").fetchone(),
                          "the duplicate should have been collapsed")
        row = conn.execute("SELECT depends_on FROM curation_jobs WHERE id=?",
                           (dep,)).fetchone()
        self.assertEqual(row["depends_on"], 1,
                         "the edge should follow the work to the surviving row")
        heir = conn.execute("SELECT task, status FROM curation_jobs WHERE id=1").fetchone()
        self.assertEqual((heir["task"], heir["status"]), ("consistency", "pending"))

    def test_the_survivor_is_never_made_to_depend_on_itself(self):
        """Re-pointing must not manufacture a self-edge.

        Reachable when the row waiting on the collapsed duplicate IS the
        surviving twin: a plain re-point would set its `depends_on` to its own
        id, and `claim_curation_job` resolves `depends_on IN (SELECT id ...
        WHERE status='done')`, which a pending row's own id can never satisfy.
        That is the same never-claimable state the rest of this class is about,
        reached without any IntegrityError to announce it -- the migration would
        report success and the queue would simply stop draining."""
        self._seed([("consistency", '{"scope": "all"}', "pending"),     # 1: survivor
                    ("contradiction", '{"scope": "all"}', "pending")])  # 2: collapsed
        conn = sqlite3.connect(self.path)
        conn.execute("UPDATE curation_jobs SET depends_on=2 WHERE id=1")
        conn.commit()
        conn.close()
        store = MemoryStore(self.path)
        row = store._conn().execute(
            "SELECT depends_on FROM curation_jobs WHERE id=1").fetchone()
        self.assertIsNone(row["depends_on"],
                          "the surviving row was left depending on itself")
        claimed = store.claim_curation_job()
        self.assertIsNotNone(claimed, "the survivor can never be claimed")
        self.assertEqual(claimed["id"], 1)

    def test_the_store_is_left_with_no_dangling_edge_at_all(self):
        """Whole-table check rather than per-row: both branches at once, plus
        SQLite's own verdict."""
        self._seed([("route", "{}", "pending"),                         # 1
                    ("criticality", "{}", "pending"),                   # 2
                    ("consistency", '{"scope": "all"}', "pending"),     # 3
                    ("contradiction", '{"scope": "all"}', "pending"),   # 4
                    ("contradiction", '{"scope": "other"}', "pending")])  # 5 (re-tasked)
        for parent in (1, 2, 4, 5):
            self._dependent_on(parent)
        conn = MemoryStore(self.path)._conn()
        self.assertEqual(conn.execute(
            "SELECT COUNT(*) FROM curation_jobs p WHERE p.depends_on IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM curation_jobs q WHERE q.id=p.depends_on)"
        ).fetchone()[0], 0)
        self.assertEqual(len(conn.execute("PRAGMA foreign_key_check").fetchall()), 0)

    def test_the_foreign_key_really_is_enforced_while_the_deletes_run(self):
        """The control: these tests are only load-bearing if the constraint is
        live at that moment. If a future change 'fixes' this by turning
        foreign_keys off for the whole migration, every assertion above would
        still pass while `claim_curation_job` silently inherited dangling
        edges — so pin the precondition itself."""
        seen = {}
        orig = MemoryStore._retire_removed_task_rows

        def spy(inner_self, conn, retired):
            seen["fk"] = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            return orig(inner_self, conn, retired)

        self._seed([("route", "{}", "pending")])
        self._dependent_on(1)
        MemoryStore._retire_removed_task_rows = spy
        try:
            MemoryStore(self.path)
        finally:
            MemoryStore._retire_removed_task_rows = orig
        self.assertEqual(seen.get("fk"), 1,
                         "foreign_keys was not ON during the retirement deletes, so the "
                         "guard these tests cover is not the thing protecting the store")


class TestTheDependsOnIndexIsThereBeforeAnythingIsDeleted(_MigrationCase):
    """v5.7.0 review §8 — the deploy-cost half of the same defect.

    SQLite verifies an enforced foreign key by scanning the child column on
    every parent DELETE. With no index on `depends_on` that is one full scan of
    `curation_jobs` per deleted row: measured 12.57 s for 805 deleted rows on a
    105k-row store, exactly linear at ~16 ms/row, versus 0.020 s with
    foreign_keys=OFF and 0.060 s with the index. A gateway paid that at startup.

    The ordering is the whole fix, so it is what gets asserted: an index created
    at rung 18 lands AFTER the deletes have already been paid for."""

    def _indexes_at_retirement(self):
        seen = {}
        orig = MemoryStore._retire_removed_task_rows

        def spy(inner_self, conn, retired):
            seen["names"] = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='curation_jobs'").fetchall()}
            return orig(inner_self, conn, retired)

        MemoryStore._retire_removed_task_rows = spy
        try:
            store = MemoryStore(self.path)
        finally:
            MemoryStore._retire_removed_task_rows = orig
        return seen.get("names", set()), store

    def test_the_index_exists_before_the_retirement_deletes(self):
        self._seed([("route", "{}", "pending")])
        names, _store = self._indexes_at_retirement()
        self.assertIn("idx_jobs_depends_on", names,
                      "idx_jobs_depends_on was not created before rung 17's deletes; "
                      "every deleted row now costs a full table scan")

    def test_the_index_survives_the_rebuild(self):
        """_rebuild_curation_jobs drops the table, taking its indexes with it."""
        self._seed([("route", "{}", "pending")])
        store = MemoryStore(self.path)
        names = {r[0] for r in store._conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='curation_jobs'").fetchall()}
        self.assertIn("idx_jobs_depends_on", names)

    def test_a_fresh_store_has_it_too(self):
        """Fresh installs and migrated stores must not drift: the DDL lives in
        _JOBS_INDEX_DDLS, which _SCHEMA splices."""
        fresh = MemoryStore(os.path.join(self.dir, "fresh.db"))
        names = {r[0] for r in fresh._conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='curation_jobs'").fetchall()}
        self.assertIn("idx_jobs_depends_on", names)

    def test_it_is_a_plain_index_not_a_partial_one(self):
        """SQLite's documented contract for the CHILD side of a foreign key is
        an ordinary index. A partial one measured just as fast here, but whether
        the planner uses it during FK verification is not guaranteed, and a 200x
        deploy-critical speedup does not get to rest on that."""
        fresh = MemoryStore(os.path.join(self.dir, "fresh.db"))
        sql = fresh._conn().execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='idx_jobs_depends_on'").fetchone()[0]
        self.assertNotIn("WHERE", sql.upper())
        self.assertIn("depends_on", sql)


class TestARebuildKeepsColumnsThisBuildNeverHeardOf(_MigrationCase):
    """The cross-rung case, and the reason the rebuild reads PRAGMA table_info.

    A table rebuild is how this codebase changes a CHECK, and it is not the only
    rung that wants curation_jobs: another adds lease/attempt columns to the same
    table. Whichever migration runs SECOND opens a store whose curation_jobs has
    columns its own `_CURATION_JOBS_DDL` does not declare. Recreating the table
    from that hardcoded list would drop them — the table still exists, still
    answers every query in the test suite, and has quietly lost the other rung's
    state. An install that upgrades through both rungs is the normal case, not a
    corner one, so it gets its own fixture here rather than being argued about.
    """

    # curation_jobs as a store that has ALREADY taken the lease-column rung would
    # have it: the pre-A13 wide CHECK (so this migration still fires) plus three
    # columns this build has never heard of, one of them NOT NULL with a DEFAULT.
    _WITH_EXTRA_COLS = _PRE_A13_JOBS_DDL.replace(
        "    run_after TEXT);",
        "    run_after TEXT, lease_owner TEXT, lease_expires_at TEXT,\n"
        "    max_attempts INTEGER NOT NULL DEFAULT 5);")

    def _seed_with_extras(self, jobs):
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.executescript(self._WITH_EXTRA_COLS)
        conn.execute("CREATE INDEX idx_jobs_lease ON curation_jobs(lease_expires_at) "
                     "WHERE lease_owner IS NOT NULL")
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version','12')")
        for task, status, owner, expires, max_attempts in jobs:
            conn.execute(
                "INSERT INTO curation_jobs(task,payload,status,created_at,lease_owner,"
                "lease_expires_at,max_attempts) VALUES(?,'{}',?,?,?,?,?)",
                (task, status, _TS, owner, expires, max_attempts))
        conn.commit()
        conn.close()

    def _cols(self, store):
        return {r["name"]: r for r in
                store._conn().execute("PRAGMA table_info(curation_jobs)").fetchall()}

    def test_the_extra_columns_and_their_data_survive_the_rebuild(self):
        self._seed_with_extras([
            ("extract", "running", "worker-7", "2026-01-01T00:05:00.00Z", 9),
            ("route", "pending", None, None, 5),
            ("contradiction", "pending", "worker-2", "2026-01-01T00:09:00.00Z", 3),
        ])
        store = MemoryStore(self.path)
        # The rung under test actually ran: the CHECK really was narrowed.
        for task in RETIRED_CURATION_TASKS:
            self.assertNotIn("'%s'" % task, self._check_sql(store), task)
        cols = self._cols(store)
        for name in ("lease_owner", "lease_expires_at", "max_attempts"):
            self.assertIn(name, cols, "%s was dropped by the rebuild" % name)
        rows = [dict(r) for r in store._conn().execute(
            "SELECT id, task, status, lease_owner, lease_expires_at, max_attempts "
            "FROM curation_jobs ORDER BY id").fetchall()]
        # id 2 was the `route` row: no handler in any build, so it is gone. The
        # other two keep their ids AND every byte of the other rung's state.
        self.assertEqual(
            rows,
            [{"id": 1, "task": "extract", "status": "running", "lease_owner": "worker-7",
              "lease_expires_at": "2026-01-01T00:05:00.00Z", "max_attempts": 9},
             {"id": 3, "task": "consistency", "status": "pending", "lease_owner": "worker-2",
              "lease_expires_at": "2026-01-01T00:09:00.00Z", "max_attempts": 3}])

    def test_the_extra_columns_keep_their_declared_type_notnull_and_default(self):
        """Copying the values but re-declaring the column as a plain nullable
        TEXT would pass the test above and still break the other rung: its next
        INSERT would not get the default it relies on."""
        self._seed_with_extras([("extract", "pending", None, None, 5)])
        cols = self._cols(MemoryStore(self.path))
        self.assertEqual(cols["max_attempts"]["type"], "INTEGER")
        self.assertEqual(cols["max_attempts"]["notnull"], 1)
        self.assertEqual(cols["max_attempts"]["dflt_value"], "5")
        self.assertEqual(cols["lease_owner"]["type"], "TEXT")
        self.assertEqual(cols["lease_owner"]["notnull"], 0)
        # …and the default is live, not just declared.
        store = MemoryStore(self.path)
        job_id = store.enqueue_curation("health", {})
        row = store._conn().execute(
            "SELECT max_attempts FROM curation_jobs WHERE id=?", (job_id,)).fetchone()
        self.assertEqual(row["max_attempts"], 5)

    def test_an_index_on_an_extra_column_survives_the_rebuild(self):
        """DROP TABLE takes the table's indexes with it, and this build's
        _JOBS_INDEX_DDLS cannot name an index it does not know about."""
        self._seed_with_extras([("route", "pending", None, None, 5)])
        store = MemoryStore(self.path)
        names = {r[0] for r in store._conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='curation_jobs'"
        ).fetchall()}
        self.assertIn("idx_jobs_lease", names)
        self.assertIn("idx_jobs_dedupe", names)   # this build's own, still there

    def test_reopening_a_store_with_extra_columns_changes_nothing(self):
        """Second open: the retired probe finds nothing, no rebuild runs, and
        the foreign columns are not touched a second time either."""
        self._seed_with_extras([("contradiction", "pending", "worker-2", _TS, 3)])
        before = [dict(r) for r in MemoryStore(self.path)._conn().execute(
            "SELECT * FROM curation_jobs ORDER BY id").fetchall()]
        after = [dict(r) for r in MemoryStore(self.path)._conn().execute(
            "SELECT * FROM curation_jobs ORDER BY id").fetchall()]
        self.assertEqual(before, after)


class TestTheUpgradedStoreStillWorks(_MigrationCase):
    def test_enqueue_claim_and_dedupe_all_behave_after_the_rebuild(self):
        self._seed([("route", "{}", "pending"), ("contradiction", "{}", "pending")])
        store = MemoryStore(self.path)
        first = store.enqueue_curation("extract", {"event_id": "e9"})
        self.assertIsNotNone(first)
        self.assertIsNone(store.enqueue_curation("extract", {"event_id": "e9"}),
                          "dedupe stopped working after the table rebuild")
        claimed = store.claim_curation_job()
        self.assertEqual(claimed["task"], "consistency")   # the re-tasked row, lowest id
        store.complete_curation_job(claimed["id"])
        self.assertEqual(store.claim_curation_job()["task"], "extract")


if __name__ == "__main__":
    unittest.main()
