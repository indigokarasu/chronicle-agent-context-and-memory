# Configuration

Set in `~/.hermes/config.yaml` (single bot) or `~/.hermes/profiles/<name>/config.yaml` (one file per bot in a multi-bot chat).

## What is Chronicle-only vs. standard config

Every key **inside the `memory:` block below is Chronicle-only**. Chronicle reads only that block.
The host (Hermes Agent) owns the rest of `config.yaml`; Chronicle does not read or change host keys.

- `memory.provider: chronicle` is the **host's** slot selector. Hermes reads it to load this plugin; Chronicle never reads it.
- `memory.memory_enabled` and `memory.user_profile_enabled` are also **host** keys: they switch Hermes' own `MEMORY.md` and `USER.md`. Chronicle does not use them; `recall_check.py` only reports them.
- Every other key under `memory:` (`db_path`, `embeddings`, `retrieval`, `curation`, …) is Chronicle's own config.

## Where this config belongs

- Single bot / default profile: `~/.hermes/config.yaml`.
- Per-bot profile: `~/.hermes/profiles/<profile-name>/config.yaml`. Each profile keeps its own database path and schedule, so two bots do not share state.

## Example: two-bot (multi-bot) chat

Bot A (default profile, `~/.hermes/config.yaml`):

```yaml
memory:
  provider: chronicle
  db_path: ~/.hermes/commons/db/chronicle/bot-a.db
  embeddings:
    model: auto
  retrieval:
    abstain_gate: focus         # retrieval abstain threshold mode
```

Bot B (profile `support`, `~/.hermes/profiles/support/config.yaml`):

```yaml
memory:
  provider: chronicle
  db_path: ~/.hermes/commons/db/chronicle/bot-b.db
  embeddings:
    model: auto
  retrieval:
    abstain_gate: focus
```

Both run the same plugin; only `db_path` (and any per-bot overrides) differs, so each bot keeps separate memory.

> **Where the paths land.** `db_path` and `git_repo` are resolved against the **active profile's home** (`$HERMES_HOME`). A value that starts with `~/.hermes` means that home, so the canonical `~/.hermes/commons/db/chronicle/chronicle.db` is `~/.hermes/commons/...` for the default profile and `~/.hermes/profiles/<name>/commons/...` for a named profile. Absolute paths are used as written. A `~/.hermes/profiles/<name>/...` path written by hand also works: Chronicle drops the repeated profile part and logs one warning asking you to remove it from the config. The canonical `~/.hermes/...` form is the simplest choice.
>
> **Stores from earlier releases.** Releases before 5.12 sometimes wrote a profile's store or git mirror to a path the config does not name; an absolute `db_path` was ignored, for example. On its first start with 5.12, Chronicle moves such a store to the path the config names, when that is safe. The old name becomes a symlink to the new file, and each move is recorded in `chronicle-migration.json` next to the new store. When the new location is on another disk, the store is copied and checked first, and the original is kept at `<old name>.migrated-<time>`. When a move is not safe, nothing is moved and the log says why: if another process has the store open, the move is retried at the next start; if both locations hold data, Chronicle keeps opening the old location, as before, and logs one warning that says how to choose. A profile's git mirror is always its own: the profile's events are queued once for it, and the old shared mirror is left in place.
>
> **Installing per profile.** Each profile has its own `plugins/` directory (`~/.hermes/profiles/<name>/plugins/` for a named profile), so install the plugin into each profile that should use Chronicle:
>
> ```bash
> hermes -p <profile> plugins install indigokarasu/chronicle-agent-context-and-memory
> hermes -p <profile> memory setup chronicle
> ```
> Then restart the gateways (`hermes gateway start`, and `hermes -p <profile> gateway start` for each profile).

## Annotated example

```yaml

memory:
  provider: chronicle              # Hermes slot selector: loads this plugin (host-owned key)
  db_path: ~/.hermes/commons/db/chronicle/chronicle.db   # SQLite store path (~ expands to profile home)
  git_repo: ~/.hermes/commons/db/chronicle/git          # git mirror for memory provenance
  embeddings:
    model: auto                    # auto | hashing | <model id>; $CHRONICLE_EMBED_MODEL overrides
    dimensions: 768                 # vector width; must match the embedder model
    allow_remote: false            # allow sending memory excerpts off-host for embedding
  extraction:
    llm:
      allow_remote: false          # allow POSTing raw excerpts to an off-host LLM extractor
  maintenance:                     # in-process cadence; runs on hooks, not cron
    enabled: true                  # master switch for maintenance
    budget_ms: 5                   # wall-clock ceiling per hook scheduling decision (ms)
  reaper:                          # idle-session reaper
    enabled: true                  # false stops reaper and startup recovery
    schedule: "*/5 * * * *"       # 5-field cron, UTC; empty string disables
    idle_threshold: "20m"          # mark session idle after this duration
    reap_threshold: "45m"          # finalize idle session after this duration
  retrieval:
    fts_weight: 0.4                # FTS5 score weight in hybrid retrieval (0-1)
    vector_weight: 0.6             # vector score weight in hybrid retrieval (0-1)
    rrf_k: 60                      # reciprocal rank fusion constant
    rerank_blend: 0.5              # blend weight for the reranker (0-1)
    abstain_gate: focus            # abstain threshold mode for weak matches
    include_drafts: true           # show drafts as [DRAFT]; false shows only confirmed
  context:
    breadth_floor: true            # reserve room for N distinct sessions in ranked fill
    breadth_floor_sessions: 5      # number of sessions to reserve
  forgetting:
    decay_schedule: "0 3 * * *"    # daily 03:00 UTC fidelity decay sweep
  identity:
    schedule: "0 5 * * *"         # daily 05:00 UTC exact-name sweep (proposes candidates only)
  health:
    schedule: "0 4 * * *"         # daily 04:00 UTC health and self-heal run
    consistency_sweep:
      enabled: true                # hourly CSP consistency sweep
      schedule: "0 * * * *"       # hourly
    census_total_max_age_hours: 24  # cache age for vector count census (hours)
    self_heal:
      embedder_mismatch_max: 500  # vectors one health run may requeue to re-embed
  confidence:
    base:
      user_direct: 0.85            # starting confidence for a directly-stated user fact
    trust_ceiling:
      4: 1.00                      # confidence cap at trust level 4
  domains:
    user:
      contradiction_policy: flag_for_review   # flag_for_review | newer_wins | refetch
  curation:
    drain:
      per_turn: 16                 # jobs one hook call may drain in total
      share_write_path: 0.5        # relative weight for write-path jobs
      share_embed: 0.3             # relative weight for deferred vector writes
      share_maintenance: 0.2       # relative weight for sweeps and repair
    sweep_schedule: "0 * * * *"    # hourly session-index backfill for ended sessions
    lease_seconds: 900             # a running job older than this is abandoned (seconds)
    max_attempts: 20               # claims before a job is failed
    retention:
      enabled: true                # prune terminal job rows
      done_days: 7                 # age bound for pruning (days)
      max_rows: 20000              # row-count bound for pruning
  sweeps:
    row_budget: 5000               # shared per-run row pace
    page_rows: 1000                # memory page size for full-table folds
    budgets:
      consistency: 2000            # groups per CSP consistency sweep
  learning:
    max_active_deltas: 8           # max concurrent self-improvement deltas
    max_delta_magnitude: 0.15      # max magnitude of a single delta
```

Keys that `engine/config.py` declares but no shipped code reads are deliberately
absent from this sample — `python3 scripts/audit_config.py` lists them as
DORMANT with a reason for each. Setting one does nothing, which is why it is not
shown here as though it did.

## Key options

Option | Default | Purpose
-------|---------|--------
`db_path` | `~/.hermes/commons/db/chronicle/chronicle.db` | SQLite database location
`embeddings.allow_remote` | `false` | Permit embedding memory excerpts on an off-host endpoint
`extraction.llm.allow_remote` | `false` | Permit POSTing raw excerpts to an off-host LLM extractor
`maintenance.enabled` | `true` | Master switch for the in-process maintenance cadence
`maintenance.budget_ms` | `5` | Wall-clock ceiling for one hook's scheduling decision
`reaper.enabled` | `true` | Run the idle-session reaper and its startup recovery
`reaper.schedule` | `*/5 * * * *` | Cron (UTC) for session reaping; `""` disables
`forgetting.decay_schedule` | `0 3 * * *` | Cron (UTC) for the fidelity-decay sweep
`health.schedule` | `0 4 * * *` | Cron (UTC) for the health + self-heal run
`health.consistency_sweep.schedule` | `0 * * * *` | Cron (UTC) for the CSP sweep
`curation.sweep_schedule` | `0 * * * *` | Cron (UTC) for the session-index backfill
`reaper.idle_threshold` | `20m` | Mark session idle after this duration
`reaper.reap_threshold` | `45m` | Finalize idle sessions after this duration
`retrieval.fts_weight` | `0.4` | FTS5 score weight in hybrid retrieval
`retrieval.vector_weight` | `0.6` | Vector score weight in hybrid retrieval
`confidence.base.<source_type>` | see `config.py` | Starting confidence for a fact from that source
`confidence.trust_ceiling.<level>` | `{0:.40 … 4:1.00}` | Cap applied to confidence at each trust level
`domains.<domain>.contradiction_policy` | per domain | What happens when a new value contradicts a stored one
`identity.schedule` | `0 5 * * *` | Cron (UTC) for the exact-name identity sweep; `""` disables
`learning.max_active_deltas` | `8` | Max concurrent self-improvement deltas
`context_engine.high_watermark_percent` | host `threshold`, else `0.75` | Compact when the prompt passes this share of the window
`context_engine.low_watermark_percent` | `2 × threshold × target_ratio`, else `0.55` | What a compaction folds down to
`retrieval.prefetch_relevance_gate` | `true` | Per-turn recall only for items that share content words with the message
`retrieval.prefetch_automation` | `false` | Per-turn recall on scheduled-job (cron) turns too
`embeddings.exclude_session_prefixes` | `[]` | Session prefixes never embedded (e.g. `cron_`); still full-text searchable

## Options added in 5.7.0

Every key here is read by shipped code — `python3 scripts/audit_config.py` prints the file and
line that reads each one, and `tests/test_config_honesty.py` fails the build if that ever stops
being true.

**The curation queue** (A7). Before this release the queue was strict FIFO with
no lease and no retention, so one health run's backlog could park the write path
for weeks and `curation_jobs` grew for the life of the store.

Option | Default | Purpose
-------|---------|--------
`curation.drain.per_turn` | `16` | Jobs one hook call may drain in total
`curation.drain.share_write_path` | `0.5` | Relative weight for `extract`/`digest`/`canonicalize`/`session_summarize`/…
`curation.drain.share_embed` | `0.3` | Relative weight for deferred vector writes
`curation.drain.share_maintenance` | `0.2` | Relative weight for sweeps and periodic repair
`curation.lease_seconds` | `900` | How long a claimed job may stay `running` before health treats it as abandoned and re-arms it. Set it above your slowest real job — a lease shorter than the work duplicates it
`curation.max_attempts` | `20` | Claims one job may burn before it is failed with a stated reason. Resets to 0 when the same unit of work is re-enqueued
`curation.reclaim_batch` | `200` | Rows one lease sweep may reclaim
`curation.retention.enabled` | `true` | Prune terminal (`done`/`failed`) job rows. `false` accepts unbounded growth
`curation.retention.done_days` | `7` | Age bound — catches a quiet store
`curation.retention.max_rows` | `20000` | Row-count bound — catches a busy store that outruns the age bound
`curation.retention.batch` | `5000` | Rows one prune pass may delete

The three `share_*` values are relative weights, not percentages: they are
normalised, so `{2, 1, 1}` and `{0.5, 0.25, 0.25}` are the same config. A
positive share too small to round up to a whole job is lent exactly one job
rather than rounded away, which is the anti-starvation guarantee. Pending and
running rows are never pruned, and neither is a `done` row that a pending job
still depends on.

**Sweep pacing** (A9). Every periodic sweep used to carry a literal `limit=5000`
with no cursor, so past 5000 matching rows it re-read the same prefix forever
and reported success. The bound stays; it is now a stated pace with a persisted
cursor behind it and a `processed`/`remaining`/`bounded`/`wrapped` report in
`health.run()` in front of it.

Option | Default | Purpose
-------|---------|--------
`sweeps.row_budget` | `5000` | Shared per-run row budget. Every sweep without its own entry below takes this number, so raising it speeds up `decay`, `ghost_facts` and `identity` together
`sweeps.page_rows` | `1000` | Memory page size for full-table folds (a paging bound, not a work bound — these never truncate)
`sweeps.budgets.ghost_facts` | `200` | Rows the ghost-fact report scans, which is now also what it displays
`sweeps.budgets.consistency` | `2000` | Groups per CSP consistency sweep
`sweeps.budgets.canonicalize` | `2000` | Groups per canonicalisation sweep
`sweeps.budgets.derive_subjects` | `500` | Subjects per derivation sweep
`sweeps.budgets.backfill` | `200` | Rows per session-index backfill
`sweeps.budgets.reextract` | `200` | Events per re-extraction pass

Only the sweeps whose pace deliberately DIFFERS from `row_budget` are listed, so
the table stays a list of decisions rather than a restatement of the default.

**Vector self-heal** (A0/A7).

Option | Default | Purpose
-------|---------|--------
`health.self_heal.embedder_mismatch_max` | `500` | Vectors ONE health run may requeue for re-embedding. Bounds the expensive action only: re-TAGGING a same-model-different-name row is a metadata `UPDATE` and is never bounded by it. At the default and the default daily schedule, a corpus of 170k wrongly-embedded vectors converges in ~340 days — a wholesale model change is a MIGRATION, not a heal (see `reports/MIGRATION-RUNBOOK.md`, whose Step 0 tells you to set this to `1` for the write-back window)
`health.census_total_max_age_hours` | `24` | How long the heal may reuse a CACHED `COUNT(*)` of the vector tables as the denominator in "N of M vectors are off-model". The numerator is always live and exact; the total is force-recounted the moment a run finds anything mismatched. `0` counts every run (~300 ms cold on a 100k-row store)

**Context packing and retrieval** (A18, A16).

Option | Default | Purpose
-------|---------|--------
`context.breadth_floor` | `true` | Reserve room for N distinct sessions in the ranked fill, instead of letting the top session take 99–100% of it. `false` restores the pre-5.7.0 fill exactly
`context.breadth_floor_sessions` | `5` | N. Swept over the whole ctx_eval corpus at all three budget tiers; 5 was the only value that improved BOTH tight tiers. Clamped to the number of groups that actually have something to emit, so `1` is arithmetically the old behaviour
`context.breadth_floor_routes` | `["aggregation", "temporal"]` | Which E9 routes get it. `factual` is excluded by construction — a factual question is answered by one session and precision packing depends on concentrating there — and `preference` already weighs every group against every other
`retrieval.include_drafts` | `true` | Include `[DRAFT]`-marked beliefs in reads. Drafts are the losing side of a flagged contradiction, a high-risk norm awaiting review, or an inference derivation refuses to assert — three producers write one deliberately RATHER than dropping the value, so excluding by default would silently delete them from the reader's view. `false` is for a deployment that wants only confirmed truth in front of its reader; it is read at the single `_readable` choke point, so it covers every channel and packing path at once
`retrieval.confident_answer_from_drafts` | `false` | May a `[DRAFT]` belief back `answer()`'s CONFIDENT path. A DIFFERENT question from `retrieval.include_drafts` above, and deliberately a separate key: one key for both would mean an operator setting it `false` to keep drafts out of confident answers instead deleting drafts from every read path. `false` (the default) still renders drafts, marked, in `search()`/`get_context()` — it only stops them being returned with `abstain: false` and a confidence score, which the `[DRAFT]` marker in the text does not undo
`git.encryption_key` | `null` | Client-side payload key for the git mirror. Declared because `engine/gitmirror.py` reads it, so the config surface promises what the code consults; `CHRONICLE_GIT_ENCRYPTION_KEY` takes precedence and remains where an actual secret belongs. `null` means no client-side payload encryption

**Automatic reference capture.**

Option | Default | Purpose
-------|---------|--------
`capture.tool_reference.allowlist` | `[web_fetch, webfetch, fetch, web_search, websearch, file_read, read_file, readfile, read]` | Tool names whose successful results are cached as a `reference` belief. Chronicle's own tools are never re-captured
`capture.tool_reference.ttl_days` | `30` | Freshness horizon recorded on a captured reference

**Near-duplicate detection.**

Option | Default | Purpose
-------|---------|--------
`curation.novelty_top_k` | `25` | Nearest same-kind neighbours the novelty scan examines before storing a belief

## Configuration honesty

Chronicle's premise is that **config must never promise what code does not
deliver**, so the key list is audited mechanically rather than by eye:

```bash
python3 scripts/audit_config.py          # WIRED / DORMANT / UNREAD per key
python3 scripts/audit_config.py --unread-only
```

Every leaf key in `engine/config.py`'s `DEFAULTS` is in exactly one of three
states, and there is no fourth:

* **WIRED** — shipped code reads it. The audit finds the read through the AST,
  including the accessor shapes this codebase actually uses (`_clamp_cfg(cfg,
  "path", …)`, a sub-dict fetched once and indexed later, and dynamic key
  templates like `cfg.get(f"sweeps.budgets.{name}")`).
* **DORMANT** — nothing reads it, and `engine.config.DECLARED_DORMANT` says so
  **with a reason**. These are admitted gaps, listed in the audit output. Where
  the value itself makes a false promise at runtime (a protection that is on but
  does not run, or an off-switch that does not switch anything off) booting logs
  a warning naming the flag once per process.
* **UNREAD** — nothing reads it and nothing declares it. This is a defect, and
  `tests/test_config_honesty.py` fails the build on it. A knob that nothing
  reads cannot land quietly, and a declaration that goes stale fails too.
