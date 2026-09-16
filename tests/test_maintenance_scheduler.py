"""
Chronicle — the hook-driven maintenance scheduler (§17.4, ladder-10 A3).

A3's defect was absence: nothing in the plugin enqueued `health`, `decay`,
`consistency` or `backfill_sweep`, `Reaper.run()` had no caller outside crash
recovery, and the cron-string config keys described a cron job that did not
exist. So forgetting never happened, the consistency sweep never ran, and the
embedder-mismatch heal fired only if something outside the tree called in.

These tests are written against the ways a scheduler goes wrong rather than
the ways it goes right:

  * fires EARLY (a fake clock proves each entry fires at its instant and not
    one minute before);
  * fires TWICE for the same instant, or stacks a queue (one enqueue per hook
    call, watermark confirmed against the DB before the write);
  * forgets it fired (watermark survives a store reopen — and survives
    truncate_projection, which it must, because a watermark is operational
    history, not a claim about the world that the log could replay);
  * fires when the operator said not to (empty cron string, false gate,
    maintenance.enabled false);
  * schedules a task nothing can run (every scheduled task is checked against
    the curation worker's real handler set, and `route`/`criticality` — which
    have no handler at all — are proven to be absent from the schedule);
  * costs the user latency (a hook call with nothing due is measured);
  * is not inert at defaults (the H1 byte-identity proof still holds, and the
    new table is deliberately NOT hidden from it).
"""

import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from engine import scheduler as sched_mod
from engine.core import ChronicleCore
from engine.scheduler import (
    UNSCHEDULED,
    CronError,
    Scheduler,
    next_fire,
    parse_cron,
    prev_fire,
)
from engine.store import SCHEMA_VERSION, MemoryStore, _has_table
from h1_store_dump import H1_TABLES, TURNS

UTC = datetime.timezone.utc
PROBE = Path(__file__).parent / "h1_store_dump.py"


def dt(y, mo, d, h=0, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=UTC)


# ---------------------------------------------------------------------------
# (a) the cron subset, in isolation
# ---------------------------------------------------------------------------
class TestCronSubset(unittest.TestCase):
    """Only the forms DEFAULTS actually uses, plus their obvious neighbours.
    Everything else is REFUSED — a spec that is not understood must disable its
    entry, never approximate it into some other cadence."""

    def test_the_three_shipped_defaults_parse(self):
        for spec in ("*/5 * * * *", "0 * * * *", "0 4 * * *", "0 3 * * *"):
            self.assertIsNotNone(parse_cron(spec), spec)

    def test_step_range_and_list(self):
        s = parse_cron("0,30 9-17/4 * * 1-5")
        self.assertEqual(sorted(s.minutes), [0, 30])
        self.assertEqual(sorted(s.hours), [9, 13, 17])
        self.assertEqual(sorted(s.dows), [1, 2, 3, 4, 5])

    def test_seven_is_sunday(self):
        self.assertEqual(sorted(parse_cron("0 0 * * 7").dows), [0])

    def test_empty_string_is_disabled_not_an_error(self):
        self.assertIsNone(parse_cron(""))
        self.assertIsNone(parse_cron("   "))
        self.assertIsNone(parse_cron(None))

    def test_malformed_specs_are_refused(self):
        for bad in ("0 4 * *", "0 4 * * * *", "* * * * 9", "a * * * *",
                    "*/0 * * * *", "5-1 * * * *", "60 * * * *", "0 24 * * *",
                    "0 0 0 * *", "MON * * * *", "@daily", "0 0 1 * ?"):
            with self.assertRaises(CronError, msg=bad):
                parse_cron(bad)

    def test_prev_and_next_bracket_now(self):
        now = dt(2026, 9, 9, 10, 7)
        for spec, prev, nxt in (("*/5 * * * *", dt(2026, 9, 9, 10, 5), dt(2026, 9, 9, 10, 10)),
                                ("0 * * * *", dt(2026, 9, 9, 10, 0), dt(2026, 9, 9, 11, 0)),
                                ("0 4 * * *", dt(2026, 9, 9, 4, 0), dt(2026, 9, 10, 4, 0))):
            s = parse_cron(spec)
            self.assertEqual(prev_fire(s, now), prev, spec)
            self.assertEqual(next_fire(s, now), nxt, spec)

    def test_prev_fire_is_inclusive_of_now_and_next_fire_is_not(self):
        """The two together must never skip or repeat an instant: `due` is
        `prev_fire(now) > watermark`, and the watermark is set to that same
        instant, so an inclusive prev and an exclusive next tile the timeline."""
        s = parse_cron("0 * * * *")
        self.assertEqual(prev_fire(s, dt(2026, 9, 9, 11, 0)), dt(2026, 9, 9, 11, 0))
        self.assertEqual(next_fire(s, dt(2026, 9, 9, 11, 0)), dt(2026, 9, 9, 12, 0))

    def test_day_of_month_and_day_of_week_are_ORed_when_both_restricted(self):
        """Standard cron, and the rule people get wrong. April 2026: the 1st is
        a Wednesday; Mondays are the 6th, 13th, 20th, 27th."""
        s = parse_cron("0 0 1 * 1")
        days = [d for d in range(1, 30) if s.matches_day(datetime.date(2026, 4, d))]
        self.assertEqual(days, [1, 6, 13, 20, 27])
        self.assertEqual([d for d in range(1, 30)
                          if parse_cron("0 0 1 * *").matches_day(datetime.date(2026, 4, d))], [1])
        self.assertEqual([d for d in range(1, 30)
                          if parse_cron("0 0 * * 1").matches_day(datetime.date(2026, 4, d))],
                         [6, 13, 20, 27])

    def test_an_unsatisfiable_spec_terminates_instead_of_looping(self):
        self.assertIsNone(prev_fire(parse_cron("0 0 30 2 *"), dt(2026, 9, 9, 10, 0)))
        self.assertIsNone(next_fire(parse_cron("0 0 30 2 *"), dt(2026, 9, 9, 10, 0)))

    def test_month_field_is_honoured(self):
        s = parse_cron("0 0 1 3 *")
        self.assertEqual(prev_fire(s, dt(2026, 9, 9, 10, 0)), dt(2026, 3, 1, 0, 0))


# ---------------------------------------------------------------------------
# a core with a clock we control
# ---------------------------------------------------------------------------
class _Rig(unittest.TestCase):
    config = None

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a3-")
        cfg = {"embeddings": {"model": "hashing"}}
        if self.config:
            cfg.update(self.config)
        self.core = ChronicleCore(self.home, cfg)
        self.core.initialize("s-a3", principal_id="assistant")
        self.store = self.core.store
        self.sched = self.core.scheduler
        # One real event, so the scheduler's anchor is the store's own
        # beginning rather than this process's start (the production shape).
        self.core.capture.observe("hello", "hi there", session_id="s-a3")
        # …then PIN that event's timestamp, because the anchor is the instant
        # every `at(...)` in this file measures from and an anchor taken from
        # the wall clock makes the whole file depend on the minute the suite
        # happens to start. `consistency` and `backfill_sweep` are both hourly
        # ("0 * * * *"), so a run begun at :57 puts a top-of-the-hour inside the
        # six-minute window `at(6 * 60)` opens and both entries fire, while a run
        # begun at :10 leaves them idle. Found as an intermittent failure of
        # test_the_dashboard_reads_the_watermarks, which asserts exactly which
        # entries fired (A13; the scheduler itself is A3's and is unchanged).
        #
        # 12:00:30 yesterday: always in the past, so _anchor_dt's future-clamp
        # never engages; :30 past the hour so the hourly entries' most recent
        # fire instant falls just BEFORE the anchor rather than just after; and
        # midday, so the 03:00 and 04:00 dailies are behind it too.
        pinned = (datetime.datetime.now(UTC) - datetime.timedelta(days=1)).replace(
            hour=12, minute=0, second=30, microsecond=0)
        with self.store.transaction() as conn:
            conn.execute("UPDATE events SET recorded_at=?", (sched_mod.iso(pinned),))
        self.sched._anchor = None                       # _anchor_dt caches
        self.anchor = self.sched._anchor_dt()
        self._now = self.anchor
        self.sched.now_fn = lambda: self._now

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def at(self, seconds):
        self._now = self.anchor + datetime.timedelta(seconds=seconds)

    def jobs(self, task=None, payload=None):
        rows = self.store.get_curation_jobs(limit=500)
        out = []
        for r in rows:
            if task and r["task"] != task:
                continue
            if payload is not None and json.loads(r["payload"] or "{}") != payload:
                continue
            out.append(r)
        return out

    def hooks(self, n=12):
        """n hook calls; returns the entry names that were scheduled."""
        return [name for name in (self.sched.on_hook("turn") for _ in range(n)) if name]

    def maintenance_jobs(self):
        """Only the jobs the SCHEDULER could have written — matched against the
        (task, payload) bindings it owns.

        A raw job count is not the scheduler's contribution, because the
        curation queue enqueues into itself: `_task_extract` files a
        `canonicalize` (and a `digest` per subject) as it completes. So a
        `tick()` that drains one pending `extract` and then schedules one sweep
        adds TWO rows, one of which the scheduler never touched. Counting the
        bindings keeps "at most one enqueue per hook call" a claim about the
        scheduler rather than about the whole pipeline."""
        want = set()
        for e in self.sched.entries():
            want.add((e.task, json.dumps(dict(e.payload), sort_keys=True)))
        out = []
        for r in self.store.get_curation_jobs(limit=500):
            key = (r["task"], json.dumps(json.loads(r["payload"] or "{}"), sort_keys=True))
            if key in want:
                out.append(r)
        return out


# ---------------------------------------------------------------------------
# (b) fires when due, and NOT BEFORE
# ---------------------------------------------------------------------------
class TestFiresWhenDueAndNotBefore(_Rig):
    def test_nothing_is_due_on_a_store_that_was_just_created(self):
        """The anchor property: a store's first maintenance happens at the first
        schedule instant AFTER the store began, not the instant it opened. This
        is also what keeps the default path inert (see TestInertAtDefaults)."""
        self.assertEqual(self.hooks(20), [])
        self.assertEqual(self.store.get_maintenance_runs(), [])

    def test_each_entry_fires_at_its_own_instant_and_not_one_minute_earlier(self):
        """Walked forward on ONE clock, cumulatively: entries share instants
        (consistency and backfill_sweep are both hourly), so "did X fire" has
        to be asked of everything that has fired so far, not of the last hook
        call — otherwise a sibling that fired an instant earlier reads as a
        failure and, worse, an entry that fired EARLY reads as a pass."""
        by_instant = {}
        for entry, spec in (("reaper", "*/5 * * * *"), ("consistency", "0 * * * *"),
                            ("backfill_sweep", "0 * * * *"), ("decay", "0 3 * * *"),
                            ("health", "0 4 * * *")):
            by_instant.setdefault(next_fire(parse_cron(spec), self.anchor), []).append(entry)
        self.assertEqual(sum(len(v) for v in by_instant.values()), 5)
        fired = set()
        # Ascending, because the clock only moves forward — and grouped,
        # because two entries can legitimately share an instant.
        for fire in sorted(by_instant):
            group = by_instant[fire]
            self._now = fire - datetime.timedelta(minutes=1)
            fired.update(self.hooks(20))
            for entry in group:
                self.assertNotIn(entry, fired, "%s fired before %s" % (entry, fire))
            self._now = fire
            fired.update(self.hooks(20))
            for entry in group:
                self.assertIn(entry, fired, "%s did not fire at %s" % (entry, fire))

    def test_an_entry_fires_once_per_instant_not_once_per_hook(self):
        self.at(6 * 60)                                  # past the first */5
        self.assertEqual(self.hooks(20).count("reaper"), 1)
        self.assertEqual(len(self.jobs("decay", {"sweep": "reaper"})), 1)
        # 200 more hook calls at the same clock: still one.
        self.assertEqual(self.hooks(200), [])
        self.assertEqual(len(self.jobs("decay", {"sweep": "reaper"})), 1)

    def test_the_next_instant_fires_again(self):
        self.at(6 * 60)
        self.hooks(20)
        self.store.complete_curation_job(self.jobs("decay", {"sweep": "reaper"})[0]["id"])
        self.at(11 * 60)
        self.assertEqual(self.hooks(20).count("reaper"), 1)
        self.assertEqual(len(self.jobs("decay", {"sweep": "reaper"})), 2)

    def test_a_missed_instant_is_caught_up_once_not_once_per_missed_instant(self):
        """A host that was offline for three days must not wake up owing three
        days of hourly sweeps. Cron semantics with a watermark: due iff the most
        recent instant is newer than the watermark — one catch-up, not a queue."""
        self.at(3 * 86400)
        fired = self.hooks(60)
        self.assertEqual(sorted(fired), ["backfill_sweep", "consistency", "decay",
                                         "health", "identity", "reaper"])
        self.assertEqual(len(self.jobs("consistency")), 1)

    def test_watermark_records_the_schedule_instant_not_the_wall_clock(self):
        self.at(6 * 60)
        self.hooks(20)
        row = self.store.get_maintenance_run("reaper")
        fired_at = sched_mod.parse_iso(row["last_fire_at"])
        self.assertEqual(fired_at.second, 0)
        self.assertEqual(fired_at.minute % 5, 0)
        self.assertLessEqual(fired_at, self._now)


# ---------------------------------------------------------------------------
# (c) at most ONE enqueue per hook call
# ---------------------------------------------------------------------------
class TestOneEnqueuePerHookCall(_Rig):
    def test_every_due_entry_takes_its_own_hook_call(self):
        self.at(3 * 86400)                       # everything is overdue
        entries = [e.name for e in self.sched.entries()]
        before = len(self.jobs())
        first = self.sched.on_hook("turn")
        self.assertIsNotNone(first)
        self.assertEqual(len(self.jobs()) - before, 1,
                         "one hook call enqueued more than one maintenance job")
        seen = [first]
        for _ in range(len(entries) - 1):
            seen.append(self.sched.on_hook("turn"))
        self.assertEqual(sorted(seen), sorted(entries))
        self.assertIsNone(self.sched.on_hook("turn"))

    def test_the_most_overdue_entry_goes_first(self):
        """Ordering is by schedule instant, oldest first, so a daily sweep that
        has been due since 03:00 is not starved by a 5-minute one that came due
        at 10:55."""
        self.at(3 * 86400)
        first = self.sched.on_hook("turn")
        rows = {e["entry"]: e for e in self.core.maintenance_status()["tasks"]}
        self.assertEqual(rows[first]["due_now"], False)   # it just fired
        self.assertIn(first, ("decay", "health"))         # 03:00/04:00 beat */5

    def test_a_backlogged_queue_does_not_stack_duplicate_sweeps(self):
        """The job from the last instant is still pending (nothing drained it).
        The next instant's decision collapses into it — the watermark advances
        because the work IS queued, but no second row is created."""
        self.at(65 * 60)
        self.hooks(20)
        n = len(self.jobs("consistency"))
        self.at(125 * 60)
        self.hooks(20)
        self.assertEqual(len(self.jobs("consistency")), n,
                         "a pending sweep was enqueued twice")
        self.assertEqual(self.store.get_maintenance_run("consistency")["decisions"], 2)
        self.assertEqual(self.store.get_maintenance_run("consistency")["enqueues"], 1)


# ---------------------------------------------------------------------------
# (d) the watermark's durability, and where it does NOT belong
# ---------------------------------------------------------------------------
class TestWatermarkDurability(_Rig):
    def test_it_survives_a_store_reopen(self):
        self.at(6 * 60)
        self.hooks(20)
        mark = self.store.get_maintenance_run("reaper")["last_fire_at"]
        reopened = MemoryStore(self.store.db_path)
        self.assertEqual(reopened.get_maintenance_run("reaper")["last_fire_at"], mark)

    def test_a_second_process_on_the_same_store_does_not_refire(self):
        """The in-memory mark is a cache, not the truth: a fresh Scheduler with
        an empty cache confirms against the DB before enqueuing."""
        self.at(6 * 60)
        self.hooks(20)
        n = len(self.jobs("decay", {"sweep": "reaper"}))
        other = Scheduler(self.core)
        other.now_fn = lambda: self._now
        self.assertIsNone(other.on_hook("turn"))
        self.assertEqual(len(self.jobs("decay", {"sweep": "reaper"})), n)

    def test_it_survives_truncate_projection(self):
        """Deliberate, and the reason is the sharpest one on that list: a
        watermark is not derived from the event log, so a rebuild cannot
        recreate it. Clearing it would make every rebuilt store look like one
        that has never run maintenance, and fire every sweep at once."""
        self.at(3 * 86400)
        self.hooks(60)
        before = self.store.get_maintenance_runs()
        self.assertEqual(len(before), len(self.sched.entries()))
        self.store.truncate_projection()
        self.assertEqual(self.store.get_maintenance_runs(), before)
        # ...and the rebuilt store does not immediately re-fire everything.
        self.assertEqual(self.hooks(20), [])

    def test_the_projection_really_was_truncated(self):
        """Without this, the test above could pass on a truncate that did
        nothing at all."""
        self.core.process_pending()
        self.assertTrue(self.store.count_rows("observed_vectors"))
        self.store.truncate_projection()
        self.assertEqual(self.store.count_rows("observed_vectors"), 0)


# ---------------------------------------------------------------------------
# (e) disabled means disabled
# ---------------------------------------------------------------------------
class TestDisabledByConfig(_Rig):
    # `identity` keeps enabled:True with an empty schedule on purpose: A8's new
    # entry has to be disabled by the SCHEDULE string like every other one, not
    # only by its feature gate.
    config = {"reaper": {"schedule": ""}, "health": {"schedule": "   "},
              "curation": {"sweep_schedule": ""}, "forgetting": {"decay_schedule": ""},
              "identity": {"enabled": True, "schedule": ""}}

    def test_an_empty_cron_string_never_enqueues(self):
        self.at(30 * 86400)
        fired = self.hooks(60)
        self.assertEqual(fired, ["consistency"])       # the only one left enabled
        for entry in ("reaper", "decay", "health", "backfill_sweep", "identity"):
            self.assertIsNone(self.store.get_maintenance_run(entry), entry)

    def test_the_disabled_reason_is_reported(self):
        by_entry = {t["entry"]: t for t in self.core.maintenance_status()["tasks"]}
        self.assertIn("empty", by_entry["reaper"]["disabled"])
        self.assertEqual(by_entry["reaper"]["schedule"], "")
        self.assertIsNone(by_entry["consistency"]["disabled"])


class TestDisabledByGate(_Rig):
    config = {"reaper": {"enabled": False},
              "health": {"consistency_sweep": {"enabled": False}}}

    def test_a_false_gate_disables_the_entry(self):
        self.at(30 * 86400)
        fired = self.hooks(60)
        self.assertNotIn("reaper", fired)
        self.assertNotIn("consistency", fired)
        self.assertIn("health", fired)


class TestMasterSwitch(_Rig):
    config = {"maintenance": {"enabled": False}}

    def test_nothing_at_all_is_enqueued(self):
        self.at(30 * 86400)
        self.assertEqual(self.hooks(60), [])
        self.assertEqual(self.store.get_maintenance_runs(), [])


class TestInvalidCronFailsClosed(_Rig):
    config = {"health": {"schedule": "every day at 4"}}

    def test_a_typo_disables_rather_than_approximating(self):
        self.at(30 * 86400)
        self.assertNotIn("health", self.hooks(60))
        by_entry = {t["entry"]: t for t in self.core.maintenance_status()["tasks"]}
        self.assertIn("not a cron string", by_entry["health"]["disabled"])


# ---------------------------------------------------------------------------
# (f) the work actually happens
# ---------------------------------------------------------------------------
class TestReaperRunsViaTheDecayTask(_Rig):
    def _stale_session(self, sid, minutes_idle):
        when = (datetime.datetime.now(UTC)
                - datetime.timedelta(minutes=minutes_idle)).strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"
        self.store.upsert_session({"session_id": sid, "status": "active",
                                   "started_at": when, "last_activity_at": when,
                                   "last_extracted_seq": 0})

    def test_a_session_idle_past_the_reap_threshold_is_finalized(self):
        """Reaper.run() had NO caller in the tree. This is the end-to-end path
        that gives it one: schedule -> curation job -> handler -> reap."""
        self._stale_session("s-stale", 90)          # reaper.reap_threshold = 45m
        self._stale_session("s-idle", 30)           # idle_threshold = 20m
        self.at(6 * 60)
        self.assertIn("reaper", self.hooks(20))
        self.core.process_pending()
        self.assertEqual(self.store.get_session("s-stale")["status"], "reaped")
        self.assertEqual(self.store.get_session("s-stale")["ended_via"], "reaped")
        self.assertEqual(self.store.get_session("s-idle")["status"], "idle")

    def test_the_reaper_half_does_not_run_the_belief_decay_half(self):
        """The two sweeps share a task and are told apart by payload, so a
        5-minute reap must not drag a daily decay sweep along with it."""
        self._decayable_fact()
        self.at(6 * 60)
        self.hooks(20)
        self.core.process_pending()
        self.assertEqual(self._fidelity(), "verbatim")

    def _decayable_fact(self):
        self.core.capture.append(
            "asserted", {"kind": "fact",
                         "key": {"entity_id": "acme_fake_co", "subject": "Acme Fake Co",
                                 "attribute": "office_status", "predicate": "office_status",
                                 "owner": "default", "domain": "general"},
                         "body": "temporary", "confidence": 0.6,
                         "source_event": "src-decay", "source_type": "session_transcript",
                         "domain": "general"},
            actor="user", trust_level=2, session_id="s-a3")
        self.core.process_pending()
        # THREE fractional digits, like now_iso(): engine/forgetting.py's
        # _age_days uses 3.9's fromisoformat, which rejects two and quietly
        # returns an age of 0.0 — a fixture written with ".00Z" would look
        # brand new and never decay, and this test would "pass" the wrong way.
        old = "2020-01-01T00:00:00.000Z"
        with self.store.transaction() as conn:
            conn.execute("UPDATE facts SET created_at=?, last_seen_at=?, domain='general', "
                         "criticality='normal', salience='normal', fidelity='verbatim'",
                         (old, old))
        self.assertTrue(self.store.query_beliefs("facts", "1=1", (), 10))

    def _fidelity(self):
        return self.store.query_beliefs("facts", "1=1", (), 10)[0]["fidelity"]

    def test_the_decay_half_takes_one_rung_off_the_ladder(self):
        self._decayable_fact()
        self.at(30 * 3600)                             # past the 03:00 decay instant
        self.assertIn("decay", self.hooks(60))
        self.core.process_pending()
        self.assertEqual(self._fidelity(), "gist")

    def test_a_hand_enqueued_decay_job_still_means_both(self):
        """An empty payload is what a dashboard button or an older caller sends;
        it has always meant "decay everything", and it still does — plus the
        reaping that never had a caller at all."""
        self._decayable_fact()
        self._stale_session("s-stale2", 90)
        self.store.enqueue_curation("decay", {})
        self.core.process_pending()
        self.assertEqual(self._fidelity(), "gist")
        self.assertEqual(self.store.get_session("s-stale2")["status"], "reaped")


class TestSweepsAreIdempotent(_Rig):
    def test_the_consistency_sweep_does_not_refile_the_same_contradiction(self):
        """Nothing ran this sweep on a cadence before, so re-detecting a
        still-unresolved pair never happened. On an hourly schedule an
        unconditional INSERT would file one disagreement 24 times a day into the
        health snapshot and the [CONTRADICTIONS] context block."""
        a, b = "belief_a_fake", "belief_b_fake"
        self.store.open_contradiction(a, b, "single-cardinality has 2 active values")
        self.store.open_contradiction(a, b, "single-cardinality has 2 active values")
        self.store.open_contradiction(a, b, "again, an hour later")
        rows = self.store.get_open_contradictions(50)
        self.assertEqual(len([r for r in rows if r["belief_a"] == a]), 1)

    def test_a_resolved_contradiction_that_comes_back_is_news(self):
        a, b = "belief_c_fake", "belief_d_fake"
        self.store.open_contradiction(a, b, "first")
        self.store.resolve_contradiction(
            [r for r in self.store.get_open_contradictions(50) if r["belief_a"] == a][0]["id"])
        self.store.open_contradiction(a, b, "it came back")
        self.assertEqual(
            len([r for r in self.store.get_open_contradictions(50) if r["belief_a"] == a]), 1)

    def test_the_backfill_sweep_runs_clean_on_an_empty_store(self):
        self.at(65 * 60)
        self.assertIn("backfill_sweep", self.hooks(20))
        self.core.process_pending()
        self.assertEqual([j for j in self.jobs("backfill_sweep") if j["status"] == "failed"], [])

    def test_scheduled_jobs_complete_rather_than_erroring(self):
        """Every scheduled task, drained for real. A handler that raises would
        show up here as status='failed' with the exception in `error`."""
        self.at(3 * 86400)
        self.hooks(60)
        self.core.process_pending()
        failed = [(j["task"], j["error"]) for j in self.jobs() if j["status"] == "failed"]
        self.assertEqual(failed, [])


# ---------------------------------------------------------------------------
# (g) every scheduled task has a handler; the unscheduled ones are documented
# ---------------------------------------------------------------------------
class TestHandlersExistAndDispatch(_Rig):
    def test_every_scheduled_task_has_a_curation_handler(self):
        audit = self.sched.audit()
        self.assertTrue(audit["entries"])
        self.assertEqual(audit["missing_handler"], [],
                         "a scheduled task has no _task_* handler: it would complete "
                         "as 'no_handler' and look like maintenance while doing nothing")

    def test_the_no_handler_tasks_left_the_schema_instead_of_this_dict(self):
        """A3 listed `route`/`criticality` here as "NO HANDLER" and left the
        CHECK to A13. A13 removed them from the CHECK (and `contradiction`, an
        alias of `consistency`), so they are no longer unscheduled tasks — they
        are not tasks. This asserts the handoff completed in both directions:
        gone from the dict, gone from the schema, still no handler."""
        from engine.store import RETIRED_CURATION_TASKS
        row = self.store._conn().execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='curation_jobs'"
        ).fetchone()[0]
        for task in RETIRED_CURATION_TASKS:
            self.assertNotIn(task, UNSCHEDULED, task)
            self.assertNotIn("'%s'" % task, row, "%s still in the task CHECK" % task)
            self.assertIsNone(getattr(self.core.curation, "_task_%s" % task, None), task)

    def test_no_unscheduled_task_is_ever_enqueued_by_the_scheduler(self):
        scheduled = {e.task for e in self.sched.entries()}
        self.assertFalse(scheduled & set(UNSCHEDULED),
                         "a task listed as deliberately unscheduled is scheduled")

    def test_identity_is_scheduled_now_that_it_only_proposes(self):
        """A8 inverted this test. `identity` was unscheduled because its handler
        AUTO-MERGED entities on an exact name match — a cadence on that merges
        two different people who share a name, on a timer. The handler now
        enqueues an E7 merge CANDIDATE and applies nothing, so it has a cadence,
        and it is out of UNSCHEDULED entirely rather than carrying a stale
        reason."""
        self.assertIn("identity", {e.task for e in self.sched.entries()})
        self.assertNotIn("identity", UNSCHEDULED)
        self.at(30 * 86400)
        self.hooks(60)
        self.assertTrue(self.jobs("identity"), "the identity sweep never ran")

    def test_the_scheduled_identity_sweep_merges_nothing(self):
        """The cadence is only safe because the handler proposes. Assert the
        property at the schedule level too, not just at the handler's."""
        self.at(30 * 86400)
        self.hooks(60)
        self.core.process_pending()
        merged = self.store.get_events_by_type("merged")
        self.assertEqual(merged, [], "a scheduled sweep merged entities")

    def test_every_task_in_the_schema_CHECK_is_either_scheduled_or_explained(self):
        """The honesty check: no task value may be silently unaccounted for."""
        row = self.store._conn().execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='curation_jobs'"
        ).fetchone()[0]
        tasks = set(part.strip().strip("'") for part in
                    row.split("task IN (")[1].split(")")[0].split(","))
        scheduled = {e.task for e in self.sched.entries()}
        unaccounted = tasks - scheduled - set(UNSCHEDULED)
        self.assertEqual(unaccounted, set())

    def test_the_scheduler_owns_no_thread(self):
        """No daemon, no timer, nothing that outlives a hook call — the whole
        shape of this change (the context engine once leaked 850MB/min from a
        background loop)."""
        import threading
        before = threading.active_count()
        self.at(3 * 86400)
        self.hooks(60)
        self.core.process_pending()
        self.assertEqual(threading.active_count(), before)


# ---------------------------------------------------------------------------
# (g2) the two hooks that actually call it, and the anchor's edges
# ---------------------------------------------------------------------------
class TestTheHooksThatCallIt(_Rig):
    def test_core_tick_drains_first_and_decides_second(self):
        """A job scheduled by this turn must not also execute in this turn."""
        self.at(3 * 86400)
        self.core.tick()
        queued = [j for j in self.jobs() if j["status"] == "pending"]
        self.assertTrue(any(j["task"] in ("decay", "health") for j in queued),
                        "tick() scheduled nothing")
        self.assertEqual([j for j in self.jobs() if j["task"] == "health"
                          and j["status"] == "done"], [])

    def test_one_tick_schedules_at_most_one_job(self):
        """Everything is overdue, so a scheduler that enqueued "what is due"
        instead of "one thing that is due" would put five sweeps on the queue in
        a single turn — the stacking failure this whole design exists to avoid.

        Measured on the scheduler's own bindings and its own watermarks, not on
        the raw job count: tick() drains first, and the drain cascades (the
        pending `extract` files a `canonicalize` as it completes), so the total
        row delta counts a job the scheduler had nothing to do with. See
        `_Rig.maintenance_jobs`."""
        self.at(3 * 86400)
        before = len(self.maintenance_jobs())
        self.core.tick()
        self.assertEqual(len(self.maintenance_jobs()) - before, 1)
        # One decision, one entry advanced — every OTHER entry stays overdue and
        # is picked up by a later turn, one per turn.
        self.assertEqual(len(self.store.get_maintenance_runs()), 1)
        due = [t for t in self.core.maintenance_status()["tasks"] if t["due_now"]]
        self.assertEqual(len(due), len(self.sched.entries()) - 1)

    def test_the_provider_schedules_on_session_end(self):
        from provider import ChronicleMemoryProvider
        prov = ChronicleMemoryProvider()
        prov.core = self.core
        prov._session_id = "s-a3"
        self.at(3 * 86400)
        prov.on_session_end([])
        self.assertTrue(self.store.get_maintenance_runs(),
                        "on_session_end took no scheduling decision")

    def test_an_event_stamped_in_the_future_does_not_freeze_maintenance(self):
        """Clock skew, or an imported store. The anchor is clamped to now, so a
        future-dated event cannot silently mean "nothing is ever due" — which
        is the exact failure this module exists to end."""
        ahead = sched_mod.iso(self._now + datetime.timedelta(days=400))
        with self.store.transaction() as conn:
            conn.execute("UPDATE events SET recorded_at=?", (ahead,))
        fresh = Scheduler(self.core)
        fresh.now_fn = lambda: self._now
        self.assertEqual(fresh._anchor_dt(), self._now)
        self._now = self._now + datetime.timedelta(days=2)
        self.assertIsNotNone(fresh.on_hook("turn"))

    def test_a_naive_timestamp_is_read_as_UTC_not_local(self):
        naive = (self.anchor + datetime.timedelta(days=3)).replace(tzinfo=None)
        self.assertIsNotNone(self.sched.on_hook("turn", now=naive))

    def test_two_fractional_digit_timestamps_parse(self):
        """The H1 probe's frozen clock emits '...05.00Z', which 3.9's
        fromisoformat rejects outright. Falling back to the real clock there
        would quietly un-freeze the scheduler inside a frozen run."""
        self.assertEqual(sched_mod.parse_iso("2026-01-02T03:04:05.00Z"),
                         datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
        self.assertEqual(sched_mod.parse_iso("2026-01-02T03:04:05.123Z"),
                         datetime.datetime(2026, 1, 2, 3, 4, 5, 123000, tzinfo=UTC))
        self.assertEqual(sched_mod.parse_iso("2026-01-02T03:04:05Z"),
                         datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
        self.assertIsNone(sched_mod.parse_iso("not a timestamp"))
        self.assertIsNone(sched_mod.parse_iso(""))


# ---------------------------------------------------------------------------
# (h) the surfaces an operator reads
# ---------------------------------------------------------------------------
class TestStatusSurface(_Rig):
    def test_status_reports_last_run_and_next_due_per_task(self):
        self.at(6 * 60)
        self.hooks(20)
        status = self.core.maintenance_status()
        by_entry = {t["entry"]: t for t in status["tasks"]}
        self.assertEqual(set(by_entry), {"reaper", "decay", "consistency",
                                         "health", "backfill_sweep", "identity"})
        reaper = by_entry["reaper"]
        self.assertTrue(reaper["last_fire_at"])
        self.assertTrue(reaper["last_enqueued_at"])
        self.assertEqual(reaper["enqueues"], 1)
        self.assertTrue(reaper["next_due_at"] > reaper["last_fire_at"])
        self.assertEqual(reaper["config_key"], "reaper.schedule")
        self.assertFalse(reaper["due_now"])

    def test_an_overdue_entry_reads_as_due_now(self):
        self.at(3 * 86400)
        by_entry = {t["entry"]: t for t in self.core.maintenance_status()["tasks"]}
        self.assertTrue(by_entry["health"]["due_now"])

    def test_status_is_read_only(self):
        self.at(3 * 86400)
        self.core.maintenance_status()
        self.core.maintenance_status()
        self.assertEqual(self.store.get_maintenance_runs(), [])
        self.assertEqual(self.jobs("health"), [])

    def test_the_health_snapshot_carries_it(self):
        result = self.core.health.run()
        self.assertIn("maintenance", result)
        self.assertIn("tasks", result["maintenance"])
        # ...and it is JSON-serialisable, because record_health_run stores it.
        json.dumps(result["maintenance"])

    def test_the_unscheduled_reasons_are_visible_at_runtime(self):
        status = self.core.maintenance_status()
        self.assertIn("derive", status["unscheduled"])
        self.assertIn("reextract", status["unscheduled"])
        # A8 removed identity from the dict rather than rewriting its reason: a
        # scheduled task listed as unscheduled is a lie the audit surface tells.
        self.assertNotIn("identity", status["unscheduled"])
        # `route` used to be listed here as "NO HANDLER". A13 removed it from
        # the schema instead, so the runtime surface must no longer offer it as
        # a task that merely lacks a cadence. Same for `contradiction`, which
        # was an alias of `consistency`.
        self.assertNotIn("route", status["unscheduled"])
        self.assertNotIn("contradiction", status["unscheduled"])
        for reason in status["unscheduled"].values():
            self.assertNotIn("NO HANDLER", reason,
                             "an unrunnable task is a schema defect, not a "
                             "scheduling decision")

    def test_the_dashboard_reads_the_watermarks(self):
        """The real dashboard function against the real table. fastapi is not a
        test dependency and the panel does not use it — only the module's import
        line does — so it is stubbed rather than skipped over: a skipped test
        would leave the one operator-facing surface unproven."""
        self.at(6 * 60)
        self.hooks(20)
        import importlib.util
        import types
        stub = types.ModuleType("fastapi")
        stub.APIRouter = lambda *a, **kw: types.SimpleNamespace(
            get=lambda *a, **kw: (lambda fn: fn), post=lambda *a, **kw: (lambda fn: fn))
        stub.Query = lambda default=None, **kw: default
        real = sys.modules.get("fastapi")
        sys.modules["fastapi"] = sys.modules.get("fastapi") or stub
        try:
            spec = importlib.util.spec_from_file_location(
                "a3_dash", str(Path(__file__).parent.parent / "dashboard" / "plugin_api.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            if real is None:
                sys.modules.pop("fastapi", None)
        entries = mod._maintenance(Path(self.store.db_path))["entries"]
        self.assertEqual([e["entry"] for e in entries], ["reaper"])
        self.assertEqual(entries[0]["task"], "decay")
        self.assertTrue(entries[0]["last_fire_at"])

    def test_the_dashboard_panel_tolerates_a_store_without_the_table(self):
        """An older store predates the scheduler; that is a store, not an error."""
        import importlib.util
        import types
        stub = types.ModuleType("fastapi")
        stub.APIRouter = lambda *a, **kw: types.SimpleNamespace(
            get=lambda *a, **kw: (lambda fn: fn), post=lambda *a, **kw: (lambda fn: fn))
        stub.Query = lambda default=None, **kw: default
        real = sys.modules.get("fastapi")
        sys.modules["fastapi"] = real or stub
        try:
            spec = importlib.util.spec_from_file_location(
                "a3_dash2", str(Path(__file__).parent.parent / "dashboard" / "plugin_api.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            if real is None:
                sys.modules.pop("fastapi", None)
        empty = Path(self.home) / "no-such.db"
        self.assertEqual(mod._maintenance(empty), {"entries": []})


# ---------------------------------------------------------------------------
# (i) latency
# ---------------------------------------------------------------------------
class TestHookLatency(_Rig):
    def test_a_hook_call_with_nothing_due_costs_under_a_millisecond(self):
        """The fast path does set lookups and integer comparisons: config is
        parsed once per process, the anchor is cached, and SQLite is not touched
        at all unless something is actually due."""
        self.sched.on_hook("turn")               # warm the anchor + entry cache
        n = 500
        t0 = time.perf_counter()
        for _ in range(n):
            self.assertIsNone(self.sched.on_hook("turn"))
        per_call_ms = (time.perf_counter() - t0) * 1000.0 / n
        self.assertLess(per_call_ms, 1.0,
                        "nothing-due hook call cost %.3fms" % per_call_ms)

    def test_the_nothing_due_path_executes_no_sql_at_all(self):
        """The exact form of the latency claim, which a timing assertion can
        only approximate: a wall-clock number is a property of this machine on
        this day, but "opened no cursor" is a property of the code. If a future
        change moves a config read or a watermark lookup into the fast path,
        this fails on a loaded CI box where the timing assertion still passes."""
        self.sched.on_hook("turn")               # warm the anchor + entry cache
        seen = []
        conn = self.store._conn()
        conn.set_trace_callback(seen.append)
        try:
            for _ in range(200):
                self.assertIsNone(self.sched.on_hook("turn"))
        finally:
            conn.set_trace_callback(None)
        self.assertEqual(seen, [], "the nothing-due path touched SQLite")
        # ...and the same probe DOES see the write when something is due, so an
        # empty list above means "no SQL", not "the callback was never armed".
        self.at(3 * 86400)
        conn.set_trace_callback(seen.append)
        try:
            self.assertIsNotNone(self.sched.on_hook("turn"))
        finally:
            conn.set_trace_callback(None)
        self.assertTrue(seen)

    def test_an_exhausted_budget_degrades_to_one_entry_per_call_not_to_nothing(self):
        """A budget of 0 truncates the scan to a single entry — so the choice
        stops being "the most overdue" and becomes "the next one in the
        rotation" — but the rotation cursor means every entry is still reached,
        one hook call at a time. A budget must never mean "do nothing, forever"."""
        self.at(3 * 86400)
        self.core.cfg._d["maintenance"]["budget_ms"] = 0
        first = self.sched.on_hook("turn")
        self.assertEqual(first, "reaper", "the truncated scan did not start at the cursor")
        entries = [e.name for e in self.sched.entries()]
        seen = [first] + [self.sched.on_hook("turn") for _ in range(len(entries) - 1)]
        self.assertEqual(sorted(x for x in seen if x), sorted(entries))

    def test_a_full_budget_picks_the_most_overdue_instead(self):
        self.at(3 * 86400)
        self.assertIn(self.sched.on_hook("turn"), ("decay", "health"))

    def test_a_broken_scheduler_never_breaks_the_hook(self):
        boom = self.store.get_maintenance_run

        def explode(*a, **kw):
            raise RuntimeError("simulated store failure")

        self.at(3 * 86400)
        self.store.get_maintenance_run = explode
        try:
            self.assertIsNone(self.sched.on_hook("turn"))   # logged, not raised
        finally:
            self.store.get_maintenance_run = boom


# ---------------------------------------------------------------------------
# (j) inertness at defaults — the H1 byte-identity proof still holds
# ---------------------------------------------------------------------------
class TestInertAtDefaults(unittest.TestCase):
    """maintenance_runs is deliberately NOT added to the dump's exclusion list.

    H1's exclusion rule permits hiding a table only when it is empty at defaults
    AND a derived assertion proves that emptiness. This table clears that bar —
    but the stronger move is available and is the one taken: leave it INSIDE the
    byte-identity comparison. The base tree has no such table, so if a default
    flow ever writes a watermark row, the dump gains a line the base dump cannot
    have and test_host_model's byte-identity test fails immediately. Excluding
    it would trade that alarm for a promise.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a3-inert-")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_the_new_table_is_not_hidden_from_the_dump(self):
        self.assertNotIn("maintenance_runs", H1_TABLES,
                         "maintenance_runs was added to the dump's exclusion list; that "
                         "removes the one alarm that catches a watermark written at "
                         "default config")

    def test_the_probe_flow_writes_no_watermark(self):
        """The dump probe's own fixture, its own hooks, its own frozen clock —
        run for real in a subprocess (freezing the clock in-process would
        poison every other test in this file) — and then the table is read back
        out of the store the probe left behind."""
        env = dict(os.environ, CHRONICLE_EMBED_MODEL="hashing",
                   CHRONICLE_A3_KEEP_HOME=self.home)
        script = (
            "import os, sys\n"
            "sys.path.insert(0, %r)\n"
            "sys.path.insert(0, %r)\n"
            "os.chdir(%r)\n"
            "import h1_store_dump as p\n"
            "p.run_flow(os.environ['CHRONICLE_A3_KEEP_HOME'])\n"
            % (str(PROBE.parent.parent), str(PROBE.parent), str(PROBE.parent.parent)))
        proc = subprocess.run([sys.executable, "-c", script], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[-3000:])
        db = Path(self.home) / "commons/db/chronicle/chronicle.db"
        self.assertTrue(db.exists(), "the probe flow left no store behind")
        conn = sqlite3.connect(str(db))
        self.assertTrue(_has_table(conn, "maintenance_runs"))
        rows = conn.execute("SELECT * FROM maintenance_runs").fetchall()
        jobs = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        self.assertEqual(rows, [],
                         "the default flow scheduled maintenance; the H1 byte-identity "
                         "dump would fail on the extra rows")
        self.assertTrue(jobs, "the probe flow wrote nothing, so 'no watermark' proves nothing")

    def test_a_flow_shorter_than_the_tightest_schedule_cannot_schedule_anything(self):
        """WHY it is inert, stated as a property rather than observed once: the
        first fire of any entry is the first schedule instant after the store's
        own first event, and the tightest default schedule is 5 minutes. A
        session that opens and closes inside one clock-minute cannot reach one."""
        core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        core.initialize("s-inert", principal_id="assistant")
        core.capture.observe("My name is Pat Testley.", "Hello, Pat.", session_id="s-inert")
        anchor = core.scheduler._anchor_dt()
        core.scheduler.now_fn = lambda: anchor        # exactly the probe's frozen clock
        for user, assistant in TURNS:
            core.capture.observe(user, assistant, session_id="s-inert")
            core.process_pending()
            core.tick()
        core.scheduler.on_hook("session_end")
        self.assertEqual(core.store.get_maintenance_runs(), [])
        self.assertTrue(core.store.query_beliefs("facts", "1=1", (), 10),
                        "fixture captured nothing, so inertness is untested")


# ---------------------------------------------------------------------------
# (k) schema_version 11 -> 12
# ---------------------------------------------------------------------------
class TestSchemaLadder12(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="a3-mig-")
        self.db = os.path.join(self.dir, "chronicle.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make_v11_db(self):
        """A store as a pre-A3 build left it: no maintenance_runs, stamped 11."""
        store = MemoryStore(self.db)
        store.append_event({
            "event_id": "ev_old_a3", "type": "observed",
            "payload": {"source_type": "session_transcript",
                        "excerpt": "Pat Testley works at Acme Fake Co."},
            "parents": [], "actor": "user", "owner": "default", "trust_level": 2,
            "session_id": "s-old", "branch_id": "s-old",
            "occurred_at": "2026-01-01T00:00:00.00Z", "recorded_at": "2026-01-01T00:00:00.00Z",
            "prev_head": "", "sig": None})
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE IF EXISTS maintenance_runs")
        conn.execute("UPDATE meta SET value='11' WHERE key='schema_version'")
        conn.commit()
        conn.close()

    def test_an_old_db_upgrades_in_place(self):
        self._make_v11_db()
        store = MemoryStore(self.db)                       # reopen == migrate
        conn = store._conn()
        self.assertTrue(_has_table(conn, "maintenance_runs"))
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        # A3 added rung 12; A13 added rung 13 on top of it. This case still
        # proves A3's rung by the table probe above -- the constant just moved
        # on. The v5.7.0 integration renumbered A3's rung to 16 and the top of
        # the merged ladder to 18, so the assertion is on the CONSTANT, not on a
        # literal this test would have to chase every time a rung lands.
        self.assertEqual(SCHEMA_VERSION, 18)
        self.assertIsNotNone(store.get_event("ev_old_a3"))
        # The new table is usable immediately.
        store.record_maintenance_run("health", task="health", payload={},
                                     fire_at="2026-01-02T04:00:00.000Z")
        self.assertEqual(store.get_maintenance_run("health")["task"], "health")

    def test_the_migration_is_reentrant(self):
        self._make_v11_db()
        MemoryStore(self.db).record_maintenance_run(
            "health", task="health", payload={}, fire_at="2026-01-02T04:00:00.000Z")
        for _ in range(2):
            store = MemoryStore(self.db)
            self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        self.assertEqual(len(MemoryStore(self.db).get_maintenance_runs()), 1,
                         "a reopen dropped or duplicated the watermarks")

    def test_an_upgraded_store_with_history_finds_its_maintenance_overdue(self):
        """The other half of the anchor rule, and the point of the whole change:
        a store that has been accumulating events for months has never run a
        sweep, and on its first hook call after the upgrade it starts — one job
        at a time, not all of them at once."""
        home = os.path.join(self.dir, "home")
        os.makedirs(os.path.join(home, "commons/db/chronicle"), exist_ok=True)
        # Built where ChronicleCore will open it. Copying a live SQLite file
        # would leave its WAL behind and lose the very event this test needs.
        self.db = os.path.join(home, "commons/db/chronicle/chronicle.db")
        self._make_v11_db()
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        self.assertIsNotNone(core.store.get_event("ev_old_a3"),
                             "the aged fixture event did not survive into the store")
        fired = [core.scheduler.on_hook("turn") for _ in range(3)]
        self.assertEqual(len([f for f in fired if f]), 3)
        self.assertEqual(len(set(f for f in fired if f)), 3, "the same entry fired twice")


if __name__ == "__main__":
    unittest.main()
