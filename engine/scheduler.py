"""
Chronicle — hook-driven maintenance scheduler (§17.4, ladder-10 A3).

The maintenance half of Chronicle was unreachable: nothing in the plugin ever
enqueued `health`, `decay`, `consistency`, `backfill_sweep`, and `Reaper.run()`
had no caller at all outside crash recovery. The cron-string config keys
(`health.schedule`, `reaper.schedule`, `curation.sweep_schedule`) were read by
no code, so they described a cron job that does not exist. Consequence: nothing
ever decayed, no session was ever reaped on a cadence, the consistency sweep
never ran, and the embedder-mismatch heal fired only when something OUTSIDE the
tree called `core.health.run()`. Chronicle's premise says the store maintains
itself locally, with no external orchestrator.

This module is that cadence, and it is deliberately NOT a daemon:

  * No thread, no timer, no process outlives a hook call. (The context engine
    once leaked ~850MB/min from a background loop; a scheduler that owns a
    thread is a scheduler that can do that again.)
  * The only thing a hook call does is DECIDE. It enqueues at most ONE due
    maintenance job — the work itself is done later by the existing curation
    worker, inside the existing bounded per-turn drain, on the existing
    `append_event` write path.
  * The decision is bounded by a wall-clock budget (`maintenance.budget_ms`)
    and resumes where it stopped, so a hook call can never become a sweep.
  * Nothing is due on a store that has just been created (see `_anchor`), so
    the default path is inert until the first real schedule instant passes.

Where it is called from — deliberately two places, not every hook:
  * `ChronicleCore.tick()`, which the host reaches through `on_turn_start` and
    `on_memory_write`. tick() drains FIRST and decides second, so a job
    scheduled this turn cannot execute inside this turn.
  * `provider.on_session_end`, the cheapest moment in the lifecycle (no turn is
    waiting) and the one hook a host that never calls `on_turn_start` still
    calls, so maintenance cannot be stranded by a sparse host.
`sync_turn` is deliberately left alone: its contract is one local append and
nothing else, and tick() already covers the per-turn cadence.

Watermarks live in `maintenance_runs` (schema_version 12), keyed by ENTRY name
rather than task name because one task can be driven by two schedules (session
reaping and belief decay are both the `decay` task, at very different
cadences). A watermark records the schedule instant the entry was last
enqueued FOR — not the job's outcome. A job that fails is retried at the next
schedule instant rather than spun on, which is what keeps a permanently-broken
task from turning into an infinite enqueue loop.

Cron syntax (stdlib only — the subset actually used by DEFAULTS, plus the
obvious neighbours; anything else is refused rather than silently reinterpreted):

    minute hour day-of-month month day-of-week      (5 fields, whitespace-separated)

    *          every value
    */N        every Nth value from the start of the field's range
    A          a single value
    A-B        an inclusive range
    A-B/N      every Nth value of a range
    a,b,c      a comma-separated list of any of the above

    day-of-week is 0-6 with Sunday=0; 7 is accepted as Sunday. Month and
    day-of-week NAMES (JAN, MON) are NOT supported. Neither are @daily-style
    nicknames, seconds fields, or the Quartz extensions (L, W, #, ?).

    When BOTH day-of-month and day-of-week are restricted, a day matches if
    EITHER matches — standard cron, and the one rule people get wrong.

    Times are UTC, not host-local: every timestamp Chronicle stores is UTC, so
    "0 4 * * *" means 04:00 UTC. This is stated in the config comments too.

    An EMPTY string disables that entry entirely — it is never evaluated and can
    never enqueue. An INVALID string also disables it, with a one-time warning:
    a typo must fail closed, never fall back to some other cadence.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Optional

from .store import now_iso

logger = logging.getLogger("chronicle.scheduler")

_UTC = datetime.timezone.utc

# Field bounds, in cron order. `dow` is normalised to 0-6 (7 -> 0) at parse.
_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))

# How far back `prev_fire` will look for a matching day before giving up. A
# schedule that matches no day inside four years (e.g. "0 0 30 2 *", Feb 30)
# is unsatisfiable; bounding the search means an unsatisfiable spec costs a
# few thousand cheap tuple tests once per hook call instead of looping forever.
_MAX_DAYS_SCAN = 1500

_DAY = datetime.timedelta(days=1)


class CronError(ValueError):
    """A cron string this parser refuses. Refusing is the point: a spec that is
    not understood must disable its entry, never approximate it."""


class CronSpec:
    """One parsed 5-field cron expression, as sets of matching field values."""

    __slots__ = ("text", "minutes", "hours", "doms", "months", "dows",
                 "dom_restricted", "dow_restricted")

    def __init__(self, text, minutes, hours, doms, months, dows,
                 dom_restricted, dow_restricted):
        self.text = text
        self.minutes = minutes
        self.hours = hours
        self.doms = doms
        self.months = months
        self.dows = dows
        self.dom_restricted = dom_restricted
        self.dow_restricted = dow_restricted

    def __repr__(self):
        return "CronSpec(%r)" % (self.text,)

    # -- matching ---------------------------------------------------------

    def matches_day(self, d: datetime.date) -> bool:
        if d.month not in self.months:
            return False
        # Python: Monday=0..Sunday=6. Cron: Sunday=0..Saturday=6.
        dow = (d.weekday() + 1) % 7
        if self.dom_restricted and self.dow_restricted:
            return d.day in self.doms or dow in self.dows
        if self.dom_restricted:
            return d.day in self.doms
        if self.dow_restricted:
            return dow in self.dows
        return True

    def matches(self, t: datetime.datetime) -> bool:
        return (t.minute in self.minutes and t.hour in self.hours
                and self.matches_day(t.date()))


def _parse_field(raw: str, index: int) -> frozenset:
    lo, hi = _BOUNDS[index]
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise CronError("empty list element in field %d of a cron spec" % (index + 1))
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            part = part.strip()
            try:
                step = int(step_s)
            except ValueError:
                raise CronError("non-integer step %r" % (step_s,))
            if step < 1:
                raise CronError("step must be >= 1, got %r" % (step_s,))
        if part == "*":
            start, end = lo, hi
        elif "-" in part.lstrip("-"):
            a_s, _, b_s = part.partition("-")
            try:
                start, end = int(a_s), int(b_s)
            except ValueError:
                raise CronError("non-integer range %r" % (part,))
        else:
            try:
                start = end = int(part)
            except ValueError:
                raise CronError("non-integer value %r" % (part,))
        if start > end:
            raise CronError("inverted range %r" % (part,))
        if start < lo or end > hi:
            raise CronError("value %r outside %d-%d" % (part, lo, hi))
        out.update(range(start, end + 1, step))
    if index == 4:                       # day-of-week: 7 is Sunday, same as 0
        if 7 in out:
            out.discard(7)
            out.add(0)
    if not out:
        raise CronError("field %d matches nothing" % (index + 1))
    return frozenset(out)


def parse_cron(spec) -> Optional[CronSpec]:
    """Parse a 5-field cron string. Returns None for an empty/whitespace string
    (an explicitly DISABLED entry); raises CronError for anything malformed."""
    text = (spec or "").strip() if isinstance(spec, str) else ""
    if not text:
        return None
    fields = text.split()
    if len(fields) != 5:
        raise CronError("expected 5 fields, got %d in %r" % (len(fields), text))
    parsed = [_parse_field(f, i) for i, f in enumerate(fields)]
    return CronSpec(text, parsed[0], parsed[1], parsed[2], parsed[3], parsed[4],
                    dom_restricted=fields[2].strip() != "*",
                    dow_restricted=fields[4].strip() != "*")


def prev_fire(spec: CronSpec, now: datetime.datetime) -> Optional[datetime.datetime]:
    """The most recent instant at or before `now` that `spec` fires.

    Day-at-a-time backwards search rather than minute-at-a-time: a daily
    schedule last run a week ago costs 1 day test, not 10 080 minute tests, and
    the worst case (an unsatisfiable spec) is bounded by _MAX_DAYS_SCAN.
    """
    t = now.astimezone(_UTC).replace(second=0, microsecond=0)
    day = t.date()
    ceil_h, ceil_m = t.hour, t.minute
    for _ in range(_MAX_DAYS_SCAN):
        if spec.matches_day(day):
            hours = sorted((h for h in spec.hours if h <= ceil_h), reverse=True)
            for h in hours:
                mins = [m for m in spec.minutes if h < ceil_h or m <= ceil_m]
                if mins:
                    return datetime.datetime(day.year, day.month, day.day, h, max(mins),
                                             tzinfo=_UTC)
        day = day - _DAY
        ceil_h, ceil_m = 23, 59
    return None


def next_fire(spec: CronSpec, after: datetime.datetime) -> Optional[datetime.datetime]:
    """The first instant strictly after `after` that `spec` fires (for display:
    the "next due" column of the maintenance summary)."""
    t = (after.astimezone(_UTC).replace(second=0, microsecond=0)
         + datetime.timedelta(minutes=1))
    day = t.date()
    floor_h, floor_m = t.hour, t.minute
    for _ in range(_MAX_DAYS_SCAN):
        if spec.matches_day(day):
            for h in sorted(h for h in spec.hours if h >= floor_h):
                mins = [m for m in spec.minutes if h > floor_h or m >= floor_m]
                if mins:
                    return datetime.datetime(day.year, day.month, day.day, h, min(mins),
                                             tzinfo=_UTC)
        day = day + _DAY
        floor_h, floor_m = 0, 0
    return None


# ---------------------------------------------------------------------------
# What is scheduled — and, just as load-bearing, what is NOT
# ---------------------------------------------------------------------------
#
# Every entry below names a task with a REAL handler (`CurationWorker._task_*`)
# that does real work when it runs; `Scheduler.audit()` re-checks that at
# runtime and the test suite asserts it. A task with no handler, or whose
# handler is a no-op or an alias, is never scheduled — a scheduled no-op is
# worse than an unscheduled one, because it looks like maintenance.
#
# A13 closed the other half of that rule. `route` and `criticality` used to be
# listed below as "NO HANDLER"; a task the schema admits and nothing can run is
# not an unscheduled task, it is a schema defect, so they were removed from the
# curation_jobs CHECK entirely (store.RETIRED_CURATION_TASKS) rather than
# explained here. `contradiction` went with them: its handler was a second name
# for health.consistency_sweep(), which the `consistency` entry below already
# schedules. Every name that remains in this dict has a real, distinct handler
# and is unscheduled for a reason about CADENCE, not about existence.
#
# UNSCHEDULED, with the reason (also stated in engine/config.py and surfaced by
# `Scheduler.status()["unscheduled"]`, so the reason is visible at runtime and
# not only in a comment):
# `identity` used to head this list, "blocked on A8": its handler AUTO-MERGED
# entities on an exact name match, so a cadence bolted onto it would have merged
# two different people who share a name, on a timer. Ladder-10 A8 replaced that
# merge with an E7 adjudication CANDIDATE — the handler now proposes and never
# applies — so it moved down into _ENTRY_DEFS and out of this dict.
UNSCHEDULED = {
    # `identity` is GONE from this dict, not rewritten: A8 replaced its
    # auto-merge with a candidate proposal, so it is SCHEDULED now, and a
    # scheduled task listed as unscheduled is a lie the audit surface tells.
    # `contradiction` is gone for a different reason: A13 retired the task
    # value entirely (it was a second name for `consistency`), and a name the
    # schema no longer admits is not a scheduling decision.
    "derive": "writes new `derived` beliefs (derivation.materialize_all). A "
              "cadence that mints beliefs is a capture path, not maintenance, "
              "and derivation.enabled/materialize/max_depth are still unread "
              "config (A12). Left to the read path until those are wired.",
    "consolidate": "canonicalize + materialize_all — the same belief-minting "
                   "objection as `derive`, and its canonicalize half already has "
                   "a producer (_task_extract enqueues it per extract).",
    "reextract": "handler exists but materialises the WHOLE observed event table "
                 "(get_events_by_type('observed')) before slicing 200 off it. "
                 "Needs the A9/A5 bounding work before it can run on a cadence; "
                 "at 400k events one sweep is a full-table copy.",
    "canonicalize": "already has a producer: _task_extract enqueues one per "
                    "extract, so a schedule would be redundant work.",
    "verify": "already has a producer: the chronicle_verify tool "
              "(tools.py _t_verify) enqueues one per belief a caller asks about.",
    "digest": "already has a producer: _task_extract enqueues one per subject.",
    "embed": "already has a producer: the deferred-vector path "
             "(store.enqueue_embed_job) and health's mismatch heal.",
    "federate_sweep": "already has a producer: health.run() enqueues one bounded "
                      "sweep per health run, so it rides `health` below.",
    "session_summarize": "already has a producer: capture.finalize_session, plus "
                         "the backfill_sweep entry below for the ones that were "
                         "missed.",
    "journal_ingest": "already has a producer: core.start_sources().",
    "extract": "already has a producer: capture.observe / append.",
}


class _Entry:
    """One (schedule -> curation job) binding."""

    __slots__ = ("name", "task", "payload", "key", "default", "gate", "purpose",
                 "spec", "disabled")

    def __init__(self, name, task, payload, key, default, gate, purpose):
        self.name = name
        self.task = task
        self.payload = payload
        self.key = key                 # config key holding the cron string
        self.default = default         # fallback if the key is absent entirely
        self.gate = gate               # optional boolean config key
        self.purpose = purpose
        self.spec = None
        self.disabled = ""             # non-empty == why this entry is inert


# name, task, payload, config key, built-in default, boolean gate, purpose.
#
# The payload is what distinguishes two entries that share a task: `decay`
# drives BOTH the session reaper (every 5 minutes — sessions go stale in
# minutes) and belief decay (daily — fidelity is supposed to fade over months,
# and each sweep takes one rung off the ladder). One task, two cadences, two
# watermarks; enqueue_curation's dedupe key is (task, canonical payload), so
# they never collapse into each other.
_ENTRY_DEFS = (
    ("reaper", "decay", {"sweep": "reaper"}, "reaper.schedule", "*/5 * * * *",
     "reaper.enabled",
     "finalize sessions idle past reaper.reap_threshold (§12.4)"),
    ("decay", "decay", {"sweep": "beliefs"}, "forgetting.decay_schedule", "0 3 * * *",
     None,
     "asymmetric fidelity decay: verbatim -> gist -> parametric_only (§20)"),
    ("consistency", "consistency", {}, "health.consistency_sweep.schedule", "0 * * * *",
     "health.consistency_sweep.enabled",
     "CSP sweep: single-cardinality predicates with >1 active value (§21)"),
    ("health", "health", {}, "health.schedule", "0 4 * * *", None,
     "auditor + Tier-1 self-heal + embedder-mismatch heal + federate sweep (§21)"),
    ("backfill_sweep", "backfill_sweep", {}, "curation.sweep_schedule", "0 * * * *", None,
     "session-index backfill for ended sessions with no index row (issue #6)"),
    # Ladder-10 A8. Daily, and deliberately not at 04:00 with `health`: two daily
    # sweeps sharing a schedule instant means one of them waits for the next hook
    # call, since a hook enqueues at most one due job.
    #
    # Gated on `identity.enabled` — the same switch E7's mention-driven proposal
    # reads, because both produce rows in the same queue and "identity evidence
    # off" has to mean both of them are off, not one.
    ("identity", "identity", {}, "identity.schedule", "0 5 * * *",
     "identity.enabled",
     "exact-name entity collisions -> merge CANDIDATES for adjudication (§E7, A8)"),
)


class Scheduler:
    """Decides, on a hook call, whether one maintenance job is due.

    Owns no thread and no state that outlives the process except the
    `maintenance_runs` watermarks. Every public method is exception-safe: a
    scheduler failure degrades to "no maintenance this call", never to a broken
    hook (I12/I18).
    """

    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.cfg = core.cfg
        # Tests inject a fake clock here; production leaves it None and reads
        # the module-level now_iso, which is what the H1 dump probe freezes.
        self.now_fn = None
        self._entries = None
        self._anchor = None
        self._marks = {}
        self._cursor = 0

    # -- clock -------------------------------------------------------------

    def now(self) -> datetime.datetime:
        if self.now_fn is not None:
            t = self.now_fn()
            return t if t.tzinfo else t.replace(tzinfo=_UTC)
        return parse_iso(now_iso()) or datetime.datetime.now(_UTC)

    def _anchor_dt(self) -> datetime.datetime:
        """The instant a NEVER-RUN entry measures its first fire from.

        A watermark says "last enqueued for instant X"; an entry that has never
        run has no such instant, and the answer to "is it due?" has to come from
        somewhere. It comes from the store's own beginning: the earliest event
        it holds, falling back to this process's start for a store with no
        events yet.

        That choice does three things at once. (1) It writes NOTHING — a
        bootstrap that persisted an anchor row would put a row in
        `maintenance_runs` on the default path and break the H1 byte-identity
        proof. (2) It is DURABLE and identical in every process, so a daily
        schedule is not reset by a restart the way a purely in-memory anchor
        would be — that is the flaw that would let a short-lived process never
        reach a 04:00 task. (3) It makes a freshly-created store inert until a
        real schedule instant passes, while an EXISTING store that has never run
        maintenance (which is every store today) finds everything due on the
        first hook call — and gets it one job at a time.
        """
        if self._anchor is None:
            first = None
            try:
                row = self.store._conn().execute(
                    "SELECT MIN(recorded_at) FROM events").fetchone()
                first = parse_iso(row[0]) if row and row[0] else None
            except Exception as e:
                logger.debug("scheduler: could not read the store anchor: %s", e)
            now = self.now()
            # Clamped to now: an event stamped in the FUTURE (clock skew, an
            # imported or hand-edited store) would otherwise put the anchor
            # ahead of every schedule instant and silently mean "maintenance
            # never runs" — the failure this whole module exists to end.
            self._anchor = min(first, now) if first is not None else now
        return self._anchor

    # -- entries -----------------------------------------------------------

    def entries(self):
        """The (schedule -> task) bindings, parsed once per process.

        Config is immutable for a Config instance's lifetime, so the cron
        strings are parsed exactly once — the per-hook fast path does set
        lookups and integer comparisons and touches neither config nor SQLite.
        """
        if self._entries is None:
            out = []
            enabled = self.cfg.get("maintenance.enabled", True)
            for name, task, payload, key, default, gate, purpose in _ENTRY_DEFS:
                e = _Entry(name, task, payload, key, default, gate, purpose)
                raw = self.cfg.get(key, default)
                if not enabled:
                    e.disabled = "maintenance.enabled is false"
                elif gate is not None and not self.cfg.get(gate, True):
                    e.disabled = "%s is false" % gate
                else:
                    try:
                        e.spec = parse_cron(raw)
                    except CronError as ex:
                        e.disabled = "%s is not a cron string (%s)" % (key, ex)
                        logger.warning("chronicle maintenance: %s=%r disabled: %s",
                                       key, raw, ex)
                    if e.spec is None and not e.disabled:
                        e.disabled = "%s is empty (disabled)" % key
                out.append(e)
            self._entries = out
        return self._entries

    # -- the hook ----------------------------------------------------------

    def on_hook(self, hook: str = "turn", now=None) -> Optional[str]:
        """Enqueue at most ONE due maintenance job. Returns the entry name, or
        None when nothing was due (the overwhelmingly common case).

        `hook` is advisory and recorded only for logging: the decision is the
        same wherever it is taken, so a store cannot end up with a different
        cadence because the host calls a different set of hooks.
        """
        try:
            return self._on_hook(hook, now)
        except Exception as e:      # a scheduler may never break a hook (I12)
            logger.warning("chronicle maintenance scheduler skipped this hook: %s", e)
            return None

    def _on_hook(self, hook, now):
        entries = [e for e in self.entries() if not e.disabled]
        if not entries:
            return None
        t0 = time.monotonic()
        budget = _budget_ms(self.cfg)
        now = now or self.now()
        if now.tzinfo is None:          # a naive caller means UTC here, not local
            now = now.replace(tzinfo=_UTC)
        anchor = self._anchor_dt()
        n = len(entries)
        best = None
        stopped_at = None
        for i in range(n):
            idx = (self._cursor + i) % n
            # `i and ...`: at least ONE entry is always evaluated. A budget so
            # small that it is already spent must degrade to "check one entry
            # per hook call", never to "check nothing, forever" — and the
            # cursor left behind means the next call resumes at the entry this
            # one did not reach, so no entry can starve.
            if i and (time.monotonic() - t0) * 1000.0 >= budget:
                stopped_at = idx
                break
            e = entries[idx]
            fire = prev_fire(e.spec, now)
            if fire is None:
                continue
            floor = self._marks.get(e.name) or anchor
            if fire > floor and (best is None or fire < best[1]):
                best = (e, fire, idx)
        if best is None:
            self._cursor = stopped_at if stopped_at is not None else 0
            return None
        entry, fire, idx = best
        self._cursor = (idx + 1) % n
        # Confirm against the DB before writing: another process on the same
        # store may have fired this entry since our in-memory mark was taken.
        # (Belt and braces — enqueue_curation already collapses an identical
        # pending job — but it also keeps the watermark honest.)
        row = self.store.get_maintenance_run(entry.name)
        if row and row.get("last_fire_at"):
            mark = parse_iso(row["last_fire_at"])
            if mark is not None:
                self._marks[entry.name] = mark
                if mark >= fire:
                    return None
        job_id = self.store.enqueue_curation(entry.task, dict(entry.payload))
        self.store.record_maintenance_run(
            entry.name, task=entry.task, payload=entry.payload,
            fire_at=iso(fire), enqueued=job_id is not None)
        self._marks[entry.name] = fire
        logger.info("chronicle maintenance: enqueued %s (task=%s) for %s [hook=%s]",
                    entry.name, entry.task, iso(fire), hook)
        return entry.name

    # -- introspection ------------------------------------------------------

    def status(self) -> dict:
        """Last run / next due, per entry — for the health snapshot and the
        dashboard. Read-only: calling this never schedules anything."""
        try:
            now = self.now()
            rows = {r["entry"]: r for r in self.store.get_maintenance_runs()}
            tasks = []
            for e in self.entries():
                r = rows.get(e.name) or {}
                nxt, due_now = None, False
                if e.spec is not None and not e.disabled:
                    last = parse_iso(r.get("last_fire_at") or "") or self._anchor_dt()
                    overdue = prev_fire(e.spec, now)
                    if overdue is not None and overdue > last:
                        # Already past a fire instant this entry has not been
                        # enqueued for: it is due NOW, and that instant is the
                        # honest "next due" for an operator reading this.
                        nxt, due_now = overdue, True
                    else:
                        nxt = next_fire(e.spec, now)
                tasks.append({
                    "entry": e.name, "task": e.task, "payload": dict(e.payload),
                    "purpose": e.purpose, "config_key": e.key,
                    "schedule": e.spec.text if e.spec is not None else "",
                    "disabled": e.disabled or None,
                    "last_fire_at": r.get("last_fire_at"),
                    "last_enqueued_at": r.get("last_enqueued_at"),
                    "enqueues": r.get("enqueues") or 0,
                    "next_due_at": iso(nxt) if nxt else None,
                    "due_now": due_now,
                })
            return {"now": iso(now), "anchor": iso(self._anchor_dt()),
                    "budget_ms": _budget_ms(self.cfg),
                    "tasks": tasks, "unscheduled": dict(UNSCHEDULED)}
        except Exception as e:
            logger.warning("chronicle maintenance status unavailable: %s", e)
            return {"error": str(e)}

    def audit(self) -> dict:
        """Every scheduled entry -> whether the curation worker can actually
        dispatch it. A scheduled task with no `_task_<name>` handler completes
        as 'no_handler' and looks like maintenance while doing nothing; this is
        the runtime check for that, and the test suite asserts it is empty."""
        worker = getattr(self.core, "curation", None)
        missing = []
        for e in self.entries():
            if worker is None or not callable(getattr(worker, "_task_%s" % e.task, None)):
                missing.append(e.name)
        return {"entries": [e.name for e in self.entries()], "missing_handler": missing}


def _budget_ms(cfg) -> float:
    """Wall-clock ceiling for one hook's DECISION. 0 is legal and means "one
    entry per hook call" (see the `i and ...` guard in _on_hook), not "no
    maintenance"; a non-numeric value falls back to the shipped default rather
    than disabling the cadence."""
    try:
        return max(0.0, float(cfg.get("maintenance.budget_ms", 5)))
    except (TypeError, ValueError):
        return 5.0


def iso(t: datetime.datetime) -> str:
    """A datetime in the store's own fixed-width RFC3339 form, so a watermark
    and every other timestamp column compare as plain strings."""
    return t.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def parse_iso(ts) -> Optional[datetime.datetime]:
    """Parse one of the store's timestamps. Returns None rather than raising:
    a malformed stored timestamp must not take a hook down with it.

    The fractional part is padded to microseconds first. On 3.9,
    `fromisoformat` accepts EXACTLY 3 or 6 fractional digits and rejects
    everything else — and Chronicle has timestamps with two ("...05.00Z" is
    what the H1 dump probe's frozen clock produces, and it is what a hand-
    written fixture reaches for). Rejecting those would silently push the
    scheduler onto the real clock inside a frozen-clock run, which is the exact
    shape of a test that proves nothing. (engine/forgetting.py's _age_days has
    the same 3.9 sharp edge and returns 0.0 there; it is only ever handed
    now_iso() output, which is always 3 digits, so it is left alone here.)
    """
    if not ts:
        return None
    text = str(ts).strip().replace("Z", "+00:00")
    head, dot, rest = text.partition(".")
    if dot:
        digits = ""
        for ch in rest:
            if ch.isdigit():
                digits += ch
            else:
                break
        text = "%s.%s%s" % (head, (digits + "000000")[:6], rest[len(digits):])
    try:
        t = datetime.datetime.fromisoformat(text)
    except (ValueError, AttributeError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=_UTC)
