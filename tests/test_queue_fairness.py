"""
Chronicle — acceptance tests for A7: fair drain, job leases, bounded queue,
incremental heal.

THE FAILURES THESE PIN, all four measured on the live store:

  1. STARVATION. `claim_curation_job` was strict FIFO by id and `drain` took
     whatever it handed back. One heal run enqueues an embed job per stale
     vector — 105k on the live store, and the production embedder sustains
     ~0.5 texts/s, so that backlog is DAYS long. Every `extract` enqueued after
     it sat behind all of them: the premise's own write path (a new turn
     becoming memory) simply stopped.
  2. LEASES. A claimed job is marked 'running'; nothing ever marked it back, so
     a worker killed mid-job left the row 'running' forever, invisible to every
     later claim. The live store had 245 `extract` rows in exactly that state.
  3. UNBOUNDED QUEUE. done/failed rows were never deleted, so `curation_jobs`
     grew for the life of the store and every enqueue's dedupe probe paid for
     the whole history.
  4. FULL-TABLE HEAL. The embedder-mismatch census was a GROUP BY over every
     vector row, on every health run, on a store with nothing wrong with it.
     Measured here on a 100k-row synthetic store: 0.5-1.3 s unindexed, versus
     ~0.1 ms for the equivalent index-seeked question.

Fixtures are synthetic throughout (Pat Testley, Acme Fake Co, hashing
embedder). Nothing here touches a network or a paid API.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import embedder_model_tag, pack
from engine.store import (
    _CURATION_JOBS_DDL,
    SCHEMA_VERSION,
    TASK_CLASS,
    TASK_CLASSES,
    drain_quotas,
    task_class,
    tasks_in_class,
)

CFG = {"embeddings": {"model": "hashing", "dimensions": 32}}


def _iso_days_ago(days):
    import datetime
    t = (datetime.datetime.now(datetime.timezone.utc)
         - datetime.timedelta(days=days))
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


class _CoreCase(unittest.TestCase):
    CFG = CFG

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a7_")
        self.core = ChronicleCore(self.home, self.CFG)
        self.store = self.core.store

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def _bulk_jobs(self, task, n, payload_prefix="p"):
        """Insert `n` pending jobs of `task` directly. Bypassing enqueue_curation
        is deliberate: these tests are about which jobs the DRAIN claims, and a
        10k-row flood built one dedupe-probe at a time would measure the enqueue
        path instead."""
        rows = [(task, json.dumps({"i": "%s%d" % (payload_prefix, i)}), "2026-01-01T00:00:00.00Z")
                for i in range(n)]
        with self.store.transaction() as c:
            c.executemany("INSERT INTO curation_jobs(task,payload,created_at,status) "
                          "VALUES(?,?,?,'pending')", rows)

    def _status_counts(self, task):
        return dict(self.store._conn().execute(
            "SELECT status, COUNT(*) FROM curation_jobs WHERE task=? GROUP BY status",
            (task,)).fetchall())

    def _stub_handlers(self, *tasks):
        """Replace the named task handlers with recorders. `run_once` resolves a
        handler with getattr(self, "_task_<task>"), so an instance attribute
        wins — the CLAIM, the attempt counter and the completion are all still
        the real ones, which is the machinery under test."""
        seen = []
        for t in tasks:
            setattr(self.core.curation, "_task_%s" % t,
                    (lambda _p, _t=t: seen.append(_t)))
        return seen


# ---------------------------------------------------------------------------
# 1. The apportionment itself
# ---------------------------------------------------------------------------
class TestDrainQuotas(unittest.TestCase):
    def test_class_map_covers_every_task_the_check_allows(self):
        """A task the CHECK accepts but the map does not know silently falls to
        `maintenance` and loses its share. The migration's `missing` list drifted
        from this same CHECK twice; assert the coupling instead of documenting it."""
        allowed = set(re.findall(r"'([a-z_]+)'", _CURATION_JOBS_DDL.split("task TEXT CHECK")[1]
                                 .split(")")[0]))
        self.assertTrue(allowed, "could not parse the task CHECK")
        self.assertEqual(allowed, set(TASK_CLASS), "TASK_CLASS drifted from the task CHECK")
        for cls in TASK_CLASSES:
            self.assertTrue(tasks_in_class(cls), "class %r has no tasks" % cls)
        self.assertEqual(sorted(t for c in TASK_CLASSES for t in tasks_in_class(c)),
                         sorted(TASK_CLASS))

    def test_default_split_is_the_declared_share_exactly(self):
        q = drain_quotas(16, {"write_path": 0.5, "embed": 0.3, "maintenance": 0.2})
        self.assertEqual(q, {"write_path": 8, "embed": 5, "maintenance": 3})
        self.assertEqual(sum(q.values()), 16)

    def test_quotas_always_sum_to_the_budget(self):
        for budget in range(0, 40):
            q = drain_quotas(budget, {"write_path": 0.5, "embed": 0.3, "maintenance": 0.2})
            self.assertEqual(sum(q.values()), budget, "budget %d leaked" % budget)

    def test_a_positive_share_too_small_to_round_up_is_lent_one_job(self):
        """The anti-starvation floor: a class with pending work is served EVERY
        turn, so no other class's backlog can push its completion out unboundedly."""
        q = drain_quotas(4, {"write_path": 0.98, "embed": 0.01, "maintenance": 0.01})
        self.assertEqual(sum(q.values()), 4)
        for c in TASK_CLASSES:
            self.assertGreaterEqual(q[c], 1, "%r was rounded away: %r" % (c, q))

    def test_degenerate_shares_do_not_stop_the_drain(self):
        q = drain_quotas(9, {"write_path": 0, "embed": 0, "maintenance": 0})
        self.assertEqual(sum(q.values()), 9)
        self.assertEqual(q, {"write_path": 3, "embed": 3, "maintenance": 3})

    def test_unknown_task_is_maintenance_never_write_path(self):
        self.assertEqual(task_class("a_task_this_build_never_heard_of"), "maintenance")
        self.assertEqual(task_class(""), "maintenance")
        self.assertEqual(task_class("extract"), "write_path")

    def test_split_is_identical_across_hash_seeds(self):
        """Nothing in the apportionment may depend on dict/set iteration order:
        a per-process split would make the fairness guarantee unreproducible and
        the failure would look like phantom nondeterminism (the PYTHONHASHSEED
        class of bug), not like a scheduler bug."""
        prog = ("import sys; sys.path.insert(0, %r);"
                "from engine.store import drain_quotas;"
                "print(sorted(drain_quotas(7, {'write_path':0.5,'embed':0.3,"
                "'maintenance':0.2}).items()))" % str(Path(__file__).parent.parent))
        outs = set()
        for seed in ("0", "1", "12345", "99991"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            outs.add(subprocess.run([sys.executable, "-c", prog], env=env,
                                    capture_output=True, text=True, check=True).stdout.strip())
        self.assertEqual(len(outs), 1, "quota split varies with PYTHONHASHSEED: %r" % outs)


# ---------------------------------------------------------------------------
# 2. Starvation — the headline acceptance
# ---------------------------------------------------------------------------
class TestStarvationIsImpossible(_CoreCase):
    FLOOD = 10000

    def test_five_extracts_behind_ten_thousand_embeds_all_run_in_one_turn(self):
        seen = self._stub_handlers("embed", "extract")
        self._bulk_jobs("embed", self.FLOOD)
        self._bulk_jobs("extract", 5)           # enqueued AFTER: every id is higher

        done = self.core.curation.drain()       # exactly one turn, default budget 16

        self.assertEqual(done, 16, "the turn must still spend its whole budget")
        self.assertEqual(self._status_counts("extract").get("done"), 5,
                         "an extract behind %d embeds was starved: %r"
                         % (self.FLOOD, self._status_counts("extract")))
        self.assertEqual(seen.count("extract"), 5)
        self.assertEqual(seen.count("embed"), 11,
                         "leftover write_path quota must be spent, not thrown away")

    def test_removing_the_quota_reproduces_the_starvation(self):
        """The control. Same fixture, pre-A7 drain (strict FIFO, no per-class
        claim): zero extracts run. If this ever passes with extracts completing,
        the test above is not measuring what it claims to."""
        self._stub_handlers("embed", "extract")
        self._bulk_jobs("embed", self.FLOOD)
        self._bulk_jobs("extract", 5)

        n = 0
        while n < 16 and self.core.curation.run_once():   # tasks=None == pre-A7
            n += 1

        self.assertEqual(n, 16)
        self.assertEqual(self._status_counts("extract").get("done"), None,
                         "FIFO must starve the extracts — otherwise the fixture is wrong")
        self.assertEqual(self._status_counts("embed").get("done"), 16)

    def test_write_path_throughput_is_a_fixed_floor_per_turn(self):
        """100 extracts behind a permanent 10k embed backlog: with a write_path
        quota of 8/turn they must all be done in ceil(100/8) = 13 turns. This is
        the bound that makes starvation IMPOSSIBLE rather than merely unlikely —
        it does not depend on the backlog's size."""
        self._stub_handlers("embed", "extract")
        self._bulk_jobs("embed", self.FLOOD)
        self._bulk_jobs("extract", 100)

        turns = 0
        while self._status_counts("extract").get("done", 0) < 100 and turns < 40:
            self.core.curation.drain()
            turns += 1

        self.assertEqual(self._status_counts("extract").get("done"), 100)
        self.assertLessEqual(turns, 13, "write_path fell below its 8-job quota")
        self.assertGreater(self._status_counts("embed").get("done", 0), 0,
                           "fairness must not stop the embed queue either")

    def test_maintenance_flood_cannot_starve_the_write_path_either(self):
        """Starvation is symmetric: a strict priority order would just move
        which queue starves. A maintenance flood must not lock out extraction,
        and extraction's own flood must not lock out maintenance."""
        self._stub_handlers("decay", "extract")
        self._bulk_jobs("decay", 5000)
        self._bulk_jobs("extract", 5000)
        self.core.curation.drain()
        counts = {t: self._status_counts(t).get("done", 0) for t in ("decay", "extract")}
        self.assertGreaterEqual(counts["extract"], 8, counts)
        self.assertGreaterEqual(counts["decay"], 3, counts)

    def test_uncontended_queue_still_drains_the_full_budget(self):
        """Fairness costs no throughput in the common case: one class with work
        and two idle ones spends the whole per-turn budget, exactly as pre-A7."""
        self._stub_handlers("extract")
        self._bulk_jobs("extract", 50)
        self.assertEqual(self.core.curation.drain(), 16)
        self.assertEqual(self._status_counts("extract").get("done"), 16)

    def test_configured_budget_and_shares_are_honoured(self):
        home = tempfile.mkdtemp(prefix="a7cfg_")
        try:
            core = ChronicleCore(home, dict(
                CFG, curation={"drain": {"per_turn": 10, "share_write_path": 0.8,
                                         "share_embed": 0.1, "share_maintenance": 0.1}}))
            seen = []
            for t in ("embed", "extract", "decay"):
                setattr(core.curation, "_task_%s" % t, (lambda _p, _t=t: seen.append(_t)))
            # All three classes contended, so the split IS the declared share
            # (0.8/0.1/0.1 over 10 = 8/1/1) with no work-conservation slack.
            with core.store.transaction() as c:
                c.executemany("INSERT INTO curation_jobs(task,payload,created_at,status) "
                              "VALUES(?,'{}','2026-01-01T00:00:00.00Z','pending')",
                              [("embed",)] * 50 + [("extract",)] * 50 + [("decay",)] * 50)
            self.assertEqual(core.curation.drain(), 10)
            self.assertEqual([seen.count("extract"), seen.count("embed"), seen.count("decay")],
                             [8, 1, 1])
        finally:
            shutil.rmtree(home, ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. Leases
# ---------------------------------------------------------------------------
class TestJobLeases(_CoreCase):
    def _age_running(self, days=1):
        with self.store.transaction() as c:
            c.execute("UPDATE curation_jobs SET started_at=? WHERE status='running'",
                      (_iso_days_ago(days),))

    def test_a_job_whose_worker_died_is_reclaimed_and_then_completes(self):
        seen = self._stub_handlers("extract")
        self.store.enqueue_curation("extract", {"turn": "t1"})
        claimed = self.store.claim_curation_job()          # worker claims...
        self.assertIsNotNone(claimed)
        self.assertEqual(self._status_counts("extract"), {"running": 1})
        self.assertEqual(self.core.curation.drain(), 0,
                         "a running job must be invisible to every other claim")

        self._age_running()                                # ...and never comes back
        out = self.core.health.queue_maintenance()["job_leases"]

        self.assertEqual(out["reclaimed"], 1)
        self.assertEqual(out["failed"], 0)
        self.assertEqual(self.core.curation.drain(), 1)
        self.assertEqual(self._status_counts("extract"), {"done": 1})
        self.assertEqual(seen, ["extract"])

    def test_a_fresh_lease_is_not_reclaimed(self):
        self.store.enqueue_curation("extract", {"turn": "t1"})
        self.store.claim_curation_job()
        out = self.core.health.queue_maintenance()["job_leases"]
        self.assertEqual(out, {"reclaimed": 0, "failed": 0, "lease_seconds": 900})
        self.assertEqual(self._status_counts("extract"), {"running": 1})

    def test_attempt_cap_is_honoured_and_states_its_reason(self):
        self.store.enqueue_curation("extract", {"turn": "t1"})
        job = self.store.claim_curation_job()
        with self.store.transaction() as c:
            c.execute("UPDATE curation_jobs SET attempts=20 WHERE id=?", (job["id"],))
        self._age_running()

        out = self.core.health.queue_maintenance()["job_leases"]

        self.assertEqual((out["reclaimed"], out["failed"]), (0, 1))
        row = self.store._conn().execute(
            "SELECT status, error FROM curation_jobs WHERE id=?", (job["id"],)).fetchone()
        self.assertEqual(row[0], "failed")
        self.assertIn("lease expired after 20 attempts", row[1])
        self.assertIn("re-enqueue", row[1], "a cap must say how to clear it")

    def test_an_exhausted_attempt_counter_is_not_a_tombstone(self):
        """Ladder-6: re-enqueueing the same unit of work resets attempts. Both
        enqueue paths guarantee it by different mechanisms — enqueue_curation
        writes a fresh row (its dedupe looks at pending/running only), and
        enqueue_embed_job re-arms the terminal row in place."""
        self.store.enqueue_curation("extract", {"turn": "t1"})
        job = self.store.claim_curation_job()
        with self.store.transaction() as c:
            c.execute("UPDATE curation_jobs SET attempts=20 WHERE id=?", (job["id"],))
        self._age_running()
        self.core.health.queue_maintenance()

        new_id = self.store.enqueue_curation("extract", {"turn": "t1"})
        self.assertIsNotNone(new_id)
        row = self.store._conn().execute(
            "SELECT status, attempts FROM curation_jobs WHERE id=?", (new_id,)).fetchone()
        self.assertEqual((row[0], row[1]), ("pending", 0))

        # ...and the embed path, whose rows are re-armed rather than re-inserted.
        eid = self.store.enqueue_embed_job("ev1", "observed", "synthetic excerpt")
        with self.store.transaction() as c:
            c.execute("UPDATE curation_jobs SET status='failed', attempts=20 WHERE id=?", (eid,))
        again = self.store.enqueue_embed_job("ev1", "observed", "synthetic excerpt")
        self.assertEqual(again, eid, "the same work must re-arm the same row")
        row = self.store._conn().execute(
            "SELECT status, attempts FROM curation_jobs WHERE id=?", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), ("pending", 0))

    def test_reclaim_is_bounded_per_run(self):
        for i in range(30):
            self.store.enqueue_curation("extract", {"turn": "t%d" % i})
            self.store.claim_curation_job()
        self._age_running()
        out = self.store.reclaim_stale_jobs(lease_seconds=60, limit=10)
        self.assertEqual(out["reclaimed"], 10)
        self.assertEqual(self._status_counts("extract"), {"pending": 10, "running": 20})


# ---------------------------------------------------------------------------
# 4. Retention
# ---------------------------------------------------------------------------
class TestQueueRetention(_CoreCase):
    def _seed(self, status, n, finished_days_ago=None, task="embed"):
        fin = _iso_days_ago(finished_days_ago) if finished_days_ago is not None else None
        with self.store.transaction() as c:
            c.executemany(
                "INSERT INTO curation_jobs(task,payload,created_at,status,finished_at) "
                "VALUES(?,'{}','2026-01-01T00:00:00.00Z',?,?)",
                [(task, status, fin)] * n)

    def _total(self):
        return self.store._conn().execute("SELECT COUNT(*) FROM curation_jobs").fetchone()[0]

    def test_done_and_failed_rows_are_pruned_by_age(self):
        self._seed("done", 40, finished_days_ago=30)
        self._seed("failed", 10, finished_days_ago=30)
        self._seed("done", 7, finished_days_ago=1)
        out = self.store.prune_curation_jobs(max_age_days=7, max_rows=10**6)
        self.assertEqual(out["pruned_age"], 50)
        self.assertEqual(self._total(), 7)

    def test_pending_and_running_work_is_never_pruned(self):
        self._seed("pending", 5, finished_days_ago=999)
        self._seed("running", 5, finished_days_ago=999)
        out = self.store.prune_curation_jobs(max_age_days=0, max_rows=0)
        self.assertEqual((out["pruned_age"], out["pruned_cap"]), (0, 0))
        self.assertEqual(self._total(), 10)

    def test_the_row_cap_catches_a_store_that_outruns_the_age_bound(self):
        self._seed("done", 200, finished_days_ago=0)
        out = self.store.prune_curation_jobs(max_age_days=7, max_rows=50)
        self.assertEqual(out["pruned_age"], 0, "nothing is old enough")
        self.assertEqual(out["pruned_cap"], 150)
        self.assertEqual(self._total(), 50)

    def test_a_depended_on_row_survives_and_the_pair_converges(self):
        """Pruning a depended-on row would make the dependent job unclaimable
        forever — the prune would re-create the stuck-forever state A7 removes.
        `depends_on REFERENCES curation_jobs(id)` is also enforced, so deleting
        a referenced row does not merely orphan the dependent, it raises
        IntegrityError and aborts the whole prune. Hence: never prune a row
        anything still points at, and let the pair converge over two passes."""
        parent = self.store.enqueue_curation("extract", {"turn": "t1"})
        child = self.store.enqueue_curation("digest", {"turn": "t1"}, depends_on=parent)
        with self.store.transaction() as c:
            c.execute("UPDATE curation_jobs SET status='done', finished_at=? WHERE id=?",
                      (_iso_days_ago(400), parent))
        out = self.store.prune_curation_jobs(max_age_days=1, max_rows=0)
        self.assertEqual((out["pruned_age"], out["pruned_cap"]), (0, 0))
        self.assertIsNotNone(self.store._conn().execute(
            "SELECT 1 FROM curation_jobs WHERE id=?", (parent,)).fetchone())

        # The dependent finishes. Pass 1 prunes the CHILD (terminal, unreferenced);
        # pass 2 then finds the parent unreferenced and prunes it. No FK error,
        # and the pair does not accumulate.
        with self.store.transaction() as c:
            c.execute("UPDATE curation_jobs SET status='done', finished_at=? WHERE id=?",
                      (_iso_days_ago(400), child))
        self.assertEqual(self.store.prune_curation_jobs(
            max_age_days=1, max_rows=10**6)["pruned_age"], 1)
        self.assertEqual(self.store.prune_curation_jobs(
            max_age_days=1, max_rows=10**6)["pruned_age"], 1)
        self.assertEqual(self._total(), 0)

    def test_health_runs_retention_and_the_switch_turns_it_off(self):
        self._seed("done", 30, finished_days_ago=30)
        self.assertEqual(self.core.health.queue_maintenance()["job_retention"]["pruned_age"], 30)

        off = ChronicleCore(tempfile.mkdtemp(prefix="a7ret_"),
                            dict(CFG, curation={"retention": {"enabled": False}}))
        with off.store.transaction() as c:
            c.executemany("INSERT INTO curation_jobs(task,payload,created_at,status,finished_at) "
                          "VALUES('embed','{}','2026-01-01T00:00:00.00Z','done',?)",
                          [(_iso_days_ago(400),)] * 5)
        res = off.health.queue_maintenance()["job_retention"]
        self.assertEqual(res, {"pruned_age": 0, "pruned_cap": 0, "enabled": False})
        self.assertEqual(off.store._conn().execute(
            "SELECT COUNT(*) FROM curation_jobs").fetchone()[0], 5)


# ---------------------------------------------------------------------------
# 5. Visibility
# ---------------------------------------------------------------------------
class TestPendingCountsAreVisible(_CoreCase):
    def test_embedding_status_reports_pending_work_per_task_and_class(self):
        """"Embeds are queued" was already reported; what it never said was
        whether anything ELSE was queued behind them — the question an operator
        staring at a stalled store actually has."""
        self._bulk_jobs("embed", 12)
        self._bulk_jobs("extract", 3)
        self._bulk_jobs("decay", 1)
        # One job that is RUNNING, so it must not appear in the pending counts.
        # A7 used "route" here; the v5.7.0 integration retires that task value
        # (A13, ladder rung 17), so this uses another write_path task instead --
        # the assertion is about pending-vs-running, never about "route".
        self.store.enqueue_curation("verify", {"x": 1})
        self.store.claim_curation_job(tasks=["verify"])

        q = self.core.embedding_status()["queue"]
        self.assertEqual(q["by_task"], {"embed": 12, "extract": 3, "decay": 1})
        self.assertEqual(q["by_class"], {"write_path": 3, "embed": 12, "maintenance": 1})
        self.assertEqual(q["running"], 1)


# ---------------------------------------------------------------------------
# 6. Incremental heal
# ---------------------------------------------------------------------------
class _HealCase(unittest.TestCase):
    """A store with real vectors, built once per test from synthetic text."""
    NDOCS = 12

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a7heal_")
        self.core = ChronicleCore(self.home, CFG)
        self.store = self.core.store
        self.core.initialize("s1", principal_id="assistant")
        self.core.capture.observe(
            "I am Pat Testley\nI live in Fake City\nI work at Acme Fake Co", "",
            session_id="s1")
        self.core.process_pending()
        self.core.curation.drain(max_jobs=200)
        self.active = embedder_model_tag(self.core.embedder)
        self.dims = int(self.core.embedder.dimensions)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _count(self, table, where="1=1", params=()):
        return self.store._conn().execute(
            "SELECT COUNT(*) FROM %s WHERE %s" % (table, where), tuple(params)).fetchone()[0]

    def _seed_memory_vectors(self, n, model, blob_dims):
        """n synthetic facts, each with one memory_vector at `blob_dims` width."""
        blob = pack([0.1] * blob_dims)
        facts = [("b_a7_%05d" % i, "synthetic value %d" % i) for i in range(n)]
        with self.store.transaction() as c:
            c.executemany(
                "INSERT OR REPLACE INTO facts(belief_id,entity_id,attribute,value,status,owner,"
                "domain,created_at,provenance) VALUES(?,'e_fake','attr',?,'active','default',"
                "'user','2026-01-01T00:00:00.00Z','{}')", facts)
            c.executemany(
                "INSERT OR REPLACE INTO memory_vectors(belief_id,kind,embedding,model,created_at) "
                "VALUES(?,'fact',?,?,'2026-01-01T00:00:00.00Z')",
                [(f[0], blob, model) for f in facts])


class TestHealIsIncremental(_HealCase):
    def test_the_census_indexes_exist_after_migration(self):
        names = {r[0] for r in self.store._conn().execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        for n in ("idx_ov_model_width", "idx_mv_model_width", "idx_qpv_model_width",
                  "idx_jobs_task_ready", "idx_jobs_lease", "idx_jobs_terminal"):
            self.assertIn(n, names)
        # A7 claimed 13; the v5.7.0 integration renumbered its index rung to
        # the top of the merged ladder (see engine/store.py). Asserted against
        # the constant, not a literal, so the rung stays pinned to the ladder
        # rather than to a number this test would have to chase.
        self.assertEqual(self.store.get_meta("schema_version"), str(SCHEMA_VERSION))

    def test_every_mismatch_probe_is_an_index_seek_not_a_scan(self):
        """The whole difference between O(all) and O(mismatched). `model != ?`
        is deliberately written as a `<`/`>` pair because SQLite cannot use an
        index for `!=`; if that ever regresses, the heal quietly becomes a full
        scan again and nothing else notices."""
        conn = self.store._conn()
        for table, idx in (("observed_vectors", "idx_ov_model_width"),
                           ("memory_vectors", "idx_mv_model_width"),
                           ("query_proxy_vectors", "idx_qpv_model_width")):
            for op in ("<", ">"):
                plan = " ".join(r[3] for r in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT model, length(embedding), COUNT(*) FROM %s "
                    "WHERE model %s ? GROUP BY model, length(embedding)" % (table, op),
                    (self.active,)))
                self.assertIn("SEARCH", plan, plan)
                self.assertIn(idx, plan, plan)
            plan = " ".join(r[3] for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT model, length(embedding), COUNT(*) FROM %s "
                "WHERE model IS ? AND length(embedding) > ? GROUP BY model, length(embedding)"
                % table, (self.active, self.dims * 4)))
            self.assertIn("SEARCH", plan, plan)
            self.assertIn(idx, plan, plan)

    def test_a_healthy_store_finds_nothing_and_reads_nothing(self):
        for t in ("observed_vectors", "memory_vectors", "query_proxy_vectors"):
            self.assertEqual(
                self.core.health._mismatched_groups(t, self.active, self.dims * 4), [])
        res = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual((res["mismatched"], res["retagged"], res["requeued"]), (0, 0, 0))

    def test_a_null_tag_never_reads_as_healthy(self):
        """NULL sorts outside both inequality ranges, so it needs its own probe.
        A row written by something with no embedder identity is exactly the row
        that must not pass the census."""
        with self.store.transaction() as c:
            c.execute("UPDATE memory_vectors SET model=NULL")
        groups = self.core.health._mismatched_groups("memory_vectors", self.active, self.dims * 4)
        self.assertTrue(groups)
        self.assertEqual(sum(g[2] for g in groups), self._count("memory_vectors"))

    def test_a_healthy_run_reuses_the_cached_denominator(self):
        """The one part of the census that cannot be a seek is the exact
        COUNT(*). It is cached with the timestamp it was taken at, so a healthy
        store never re-reads its corpus just to print a denominator."""
        first = self.core.health._embedder_mismatch_heal()
        self.assertIsNotNone(first["vectors_total_at"])
        self._seed_memory_vectors(50, self.active, self.dims)   # healthy rows

        second = self.core.health._embedder_mismatch_heal()
        self.assertEqual(second["vectors_total"], first["vectors_total"],
                         "a healthy run must not recount")
        self.assertEqual(second["vectors_total_at"], first["vectors_total_at"])
        self.assertEqual(second["embedder_mismatch"]["mismatched"], 0)

    def test_finding_a_mismatch_forces_a_live_recount(self):
        first = self.core.health._embedder_mismatch_heal()
        self._seed_memory_vectors(20, "other-model", self.dims)

        second = self.core.health._embedder_mismatch_heal()
        self.assertGreater(second["embedder_mismatch"]["mismatched"], 0)
        # The denominator is live the moment it is used: the 20 rows added after
        # the cached count are in it. (The `at` stamp is millisecond-resolution,
        # so two heal runs in the same millisecond share one — the count itself
        # is the evidence of a recount, not the timestamp.)
        self.assertEqual(second["vectors_total"], first["vectors_total"] + 20)
        self.assertEqual(second["vectors_total"], sum(second["vectors_by_table"].values()))
        self.assertEqual(second["vectors_by_table"]["memory_vectors"],
                         self._count("memory_vectors"))

    def test_a_stale_cache_is_recounted_and_an_unreadable_one_is_not_trusted(self):
        self.core.health._embedder_mismatch_heal()
        self.store.set_meta(self.core.health._CENSUS_KEY, "{not json")
        res = self.core.health._embedder_mismatch_heal()
        self.assertEqual(res["vectors_total"], sum(res["vectors_by_table"].values()))
        self.assertGreater(res["vectors_total"], 0)


class TestHealConvergesUnderBound(_HealCase):
    N = 1000

    def test_a_thousand_mismatched_rows_converge_with_bounded_work_per_run(self):
        """Bounded per run (`health.self_heal.embedder_mismatch_max`, 500) and
        converging. The bound is on the QUEUE, not on the call: run 2 requeues
        NOTHING because run 1's 500 jobs are still pending, and that is the
        point — the production embedder does ~0.5 texts/s, so a heal that added
        another 500 every run would rebuild the unbounded backlog this task
        exists to bound. Progress resumes exactly as the queue drains."""
        self._seed_memory_vectors(self.N, "some-other-model", self.dims)

        r1 = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(r1["mismatched"], self.N)
        self.assertEqual(r1["requeued"], 500, "one run must not requeue the corpus")
        self.assertTrue(r1["bounded"])
        self.assertEqual(r1["outstanding"], 500)
        self.assertEqual(r1["queued_backlog"], 0)

        r2 = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(r2["requeued"], 0, "the bound is already spent on the backlog")
        self.assertEqual(r2["queued_backlog"], 500)
        self.assertEqual(r2["requeue_room"], 0)
        self.assertTrue(r2["bounded"], "a full queue must report WHY, not read as a stall")
        self.assertEqual(self._count("curation_jobs", "task='embed' AND status='pending'"), 500)

        # Drain the queue: those 500 rows are actually fixed...
        while self.core.curation.drain(max_jobs=500):
            pass
        self.assertEqual(self._count("memory_vectors", "model IS NOT ?", (self.active,)), 500)

        # ...and the next heal picks up the remaining 500, with room again.
        r3 = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual((r3["mismatched"], r3["requeued"], r3["outstanding"]), (500, 500, 0))
        while self.core.curation.drain(max_jobs=500):
            pass
        self.assertEqual(self._count("memory_vectors", "model IS NOT ?", (self.active,)), 0)

        r4 = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual((r4["mismatched"], r4["requeued"], r4["bounded"]), (0, 0, False))

    def test_wrong_width_rows_are_requeued_and_counted(self):
        self._seed_memory_vectors(10, self.active, self.dims * 2)
        r = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(r["mismatched"], 10)
        self.assertEqual(r["wrong_dim"], 10)
        self.assertEqual(r["requeued"], 10)


class TestRetagIsNeverBlockedBehindTheEmbedQueue(_HealCase):
    """FIELD CONTEXT: on the live store 30,198 vectors need only a retag (free,
    no embedder) while 186,374 need re-embedding at ~0.5 texts/s — days of work.
    The retag path must therefore never be gated on the embed queue draining,
    and must never enqueue an embed job of its own."""

    def test_a_rename_is_repaired_immediately_under_a_ten_thousand_job_backlog(self):
        with self.store.transaction() as c:
            c.executemany("INSERT INTO curation_jobs(task,payload,created_at,status) "
                          "VALUES('embed',?, '2026-01-01T00:00:00.00Z','pending')",
                          [(json.dumps({"i": i}),) for i in range(10000)])
        backlog = self._count("curation_jobs", "task='embed'")
        self.assertEqual(backlog, 10000)

        renamed = "/opt/models/" + self.active            # same identity, new NAME
        self._seed_memory_vectors(1000, renamed, self.dims)

        res = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]

        self.assertEqual(res["retagged"], 1000)
        self.assertEqual(res["requeued"], 0, "a rename must never cost an embed")
        self.assertEqual(res["outstanding"], 0)
        self.assertFalse(res["bounded"], "the retag path is not subject to the requeue bound")
        self.assertEqual(self._count("curation_jobs", "task='embed'"), backlog,
                         "the retag path must not add to the embed backlog")
        self.assertEqual(self._count("memory_vectors", "model=?", (renamed,)), 0)
        self.assertEqual(self._count("memory_vectors", "model=?", (self.active,)),
                         self._count("memory_vectors"))
