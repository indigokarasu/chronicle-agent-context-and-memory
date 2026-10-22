# Maintenance

Chronicle has no process of its own: everything below runs inside the Hermes hooks that the
memory provider and context engine already receive.

**Maintenance runs on those hooks, not on cron.** There is no daemon, no timer
and no background thread: on a hook call the `Scheduler` (`engine/scheduler.py`)
compares each schedule's cron string against a persisted watermark
(`maintenance_runs`) and enqueues **at most one** due job onto the ordinary
curation queue, inside a wall-clock budget (`maintenance.budget_ms`, default
5ms; a call with nothing due costs ~0.08ms and, once the first call has set the scheduler's anchor, executes no SQL at all). The work
itself is then done by the existing bounded per-turn drain, on the ordinary
`append_event` write path. An empty cron string disables a schedule; so does
an unparseable one, loudly. `core.maintenance_status()` reports last-run and
next-due per schedule, plus the tasks that are deliberately **not** scheduled
and why (e.g. `derive`, which mints new beliefs — a capture path, not
maintenance).

Six maintenance jobs are scheduled, each on its own cadence:

| Job | Config key | Default schedule | What it does |
|-----|------------|------------------|--------------|
| Session reaper | `reaper.schedule` | `*/5 * * * *` (every 5 min) | Finalizes sessions idle past `reaper.reap_threshold` and recovers interrupted reap on startup (§12.4). Runs most often because sessions go stale in minutes. |
| Belief decay | `forgetting.decay_schedule` | `0 3 * * *` (daily 03:00 UTC) | Asymmetric fidelity decay — verbatim → gist → parametric_only — one rung off each belief per sweep (§20). Daily because fidelity fades over months, and each sweep is bounded. |
| CSP consistency sweep | `health.consistency_sweep.schedule` | `0 * * * *` (hourly) | Single-cardinality predicates with more than one active value (§21). Hourly so contradictions surface quickly without waiting for the daily health run. |
| Health / self-heal | `health.schedule` | `0 4 * * *` (daily 04:00 UTC) | Auditor, Tier-1 self-heal, embedder-mismatch heal and federate sweep (§21). Runs at 04:00, deliberately offset from identity (05:00) so a hook call never has to choose between two due jobs. |
| Session-index backfill | `curation.sweep_schedule` | `0 * * * *` (hourly) | Backfills index rows for ended sessions that have none (issue #6). Hourly, independent of health. |
| Identity sweep | `identity.schedule` | `0 5 * * *` (daily 05:00 UTC) | Exact-name sweep that **proposes merge candidates only** — it never merges automatically (§E7). Gated on `identity.enabled`, which also gates the mention-driven proposal path since both write to the same queue. |

**Identity is adjudicated, never inferred.** The `identity` sweep exists to ask
questions, not answer them: an exact `(normalized_name, owner, domain)`
collision between two entities becomes a `merge` row on the
`identity_candidates` queue, and nothing is applied. It used to *merge* those
entities, which is why it had no schedule until it was fixed — two different
people who share a name are the ordinary case, and `merged_into` collapses
their provenance chains irreversibly. An explicit `merged` event still merges,
because that event records a decision someone made.

**Memory about the user comes only from the user.** Capture records who said
each part of a turn (`engine/speaker.py`): the person, a scheduled job or bot, the
assistant, a tool, or the host itself. The host context decides the user side:
Hermes' `agent_context` and `platform`, and the turn author. Inside a person's
message, Hermes' control frames (compaction handoffs, `[System note: ...]`,
background-process results, the gateway origin header) and Chronicle's own
recalled `<memory-context>` block count as host text. The spans are stored on
the event, and extraction takes facts, preferences, standing instructions and
entity types only from the person's own words. Everything else stays captured
and searchable, and never becomes memory about the user.
`scripts/retract_misattributed.py` retracts what earlier builds extracted from
text the user never wrote. It runs as a dry run with a report unless given
`--apply`.
