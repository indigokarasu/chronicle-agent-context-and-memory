<p align="center">
  <img src="./assets/readme/hero.jpg" width="100%" alt="Chronicle — durable memory moving through an indigo and magenta archive">
</p>

# Chronicle

### Local-first memory for Hermes Agent that survives restarts, long chats, and context compression.

[![CI](https://github.com/indigokarasu/chronicle-agent-context-and-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/indigokarasu/chronicle-agent-context-and-memory/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/indigokarasu/chronicle-agent-context-and-memory)](https://github.com/indigokarasu/chronicle-agent-context-and-memory/releases/latest)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/license-MIT-2ea44f.svg)](LICENSE)
[![No required services](https://img.shields.io/badge/required_services-none-6f42c1.svg)](#why-chronicle)

Version: 5.8.20.

Chronicle gives your Hermes agent durable long-term memory and safer working-memory
compression in one install. Names, preferences, decisions, and prior work stay on
your machine in SQLite; relevant memories come back when they are useful.

## Why Chronicle

- **Local by default.** No account, API key, or hosted memory service is required.
- **Survives context compression.** Chronicle persists a span before the context
  engine evicts it, then rehydrates relevant memory later.
- **Inspectable and correctable.** Memories are event-sourced with provenance,
  history, correction, forgetting, and access-control tools.
- **Honest when evidence is weak.** Retrieval can fall back to captured turns and
  abstains instead of confidently inventing an answer.
- **Works without an embedding model.** Full-text recall remains available; a local
  OpenAI-compatible embedding server can improve semantic recall when present.

## Try it in two minutes

Install directly from GitHub:

```bash
hermes plugins install indigokarasu/chronicle-agent-context-and-memory
```

Then open `hermes plugins` and select **Chronicle** for the Memory Provider.
Selecting it for the Context Engine is optional, but enables memory-aware
compression. The equivalent manual configuration is:

```yaml
memory:  { provider: chronicle }
context: { engine: chronicle }
plugins: { enabled: [chronicle] }
```

Start Hermes and try this small persistence test:

1. Say: `Remember that my project launch day is Friday.`
2. Start a new session and ask: `When is my project launch day?`
3. Run `/chronicle` to see the active embedder and local store counts.

The database is created automatically at
`~/.hermes/commons/db/chronicle/chronicle.db`. Chronicle has no required Python
dependencies and no separate database or migration step.

> If Chronicle earns a place in your agent setup, please
> [star the repository](https://github.com/indigokarasu/chronicle-agent-context-and-memory)
> so other Hermes users can find it.

## What gets installed

Two Hermes plugin slots share one in-process core:

- **ChronicleMemoryProvider** durably captures conversation history and retrieves
  relevant facts, episodes, and raw turns across sessions.
- **ChronicleContextEngine** replaces the default compressor with memory-aware
  compaction that makes spans durable before eviction.

Either slot can run without the other. Under Hermes, capture and lifecycle hooks
run automatically. The agent receives memory tools including `chronicle_remember`,
`chronicle_search`, `chronicle_answer`, `chronicle_explain`, `chronicle_correct`,
and `chronicle_forget`.

### Embeddings and graceful degradation

Embeddings default to `auto`: Chronicle checks local OpenAI-compatible servers
(LM Studio on `:1234`, Ollama on `:11434`, and llama.cpp on `:8080`) and uses the
model they serve. If none is reachable, vector work is queued while full-text
retrieval remains active. Set `model: hashing` or
`CHRONICLE_EMBED_MODEL=hashing` to deliberately choose the offline embedder.

Requires Python 3.9 or newer. The optional `blake3` package enables BLAKE3
content addressing; otherwise Chronicle uses BLAKE2b-256.

## Programmatic quickstart

This smoke test does not require Hermes:

```python
from engine.core import ChronicleCore

core = ChronicleCore.get("/tmp/hermes_home")
core.initialize(session_id="s1", principal_id="assistant")
core.capture.observe(
    "My name is Pat Testley. I work at Acme Fake Co.",
    "Hi Pat!",
    session_id="s1",
)
core.process_pending()

print(core.retrieval.answer("where do I work?"))
```

## Architecture

Both plugins share a process-singleton `ChronicleCore` that owns:

- **MemoryStore**: SQLite WAL mode, single-writer with thread-local connections
- **CaptureEngine**: observes turns, extracts salient spans, runs the reaper
- **Reducer**: folds events into the belief store (facts, entities, episodes)
- **RetrievalEngine**: dual-tier recall: FTS5 + structured lookup over beliefs, plus raw event access

When the context engine is selected, Hermes hands it compaction: it calls the engine's `compress()` and `prune_tool_results_only()` itself (the memory provider's `on_pre_compress` then returns nothing, so nothing is summarised twice). The memory provider hooks into `on_session_end`, `on_turn_start`, `on_delegation`, and `on_memory_write`.

### How a compaction works

- **It follows your `compression:` settings.** Hermes does not pass its policy
  to a plugin engine, so Chronicle reads it: it compacts at `threshold` of the
  window, down to twice `threshold × target_ratio`, keeps `protect_first_n`
  and `protect_last_n` messages, and also folds down to half of
  `hygiene_hard_message_limit` when the gateway compacts on message count.
  Explicit `context_engine.high_watermark_percent` / `low_watermark_percent`
  still win.
- **What it keeps.** The protected head and tail, the user's newest request
  (even behind a long tool loop), pinned spans and the user's own
  "never/always/must" instructions, then the best-scoring older turns that fit.
  A tool call and its results are kept or folded together, never split. When
  even the protected spans do not fit, the newest turn wins, then the user's
  newest request, then the rest of the tail newest first; a turn's stale
  recall block (Hermes' `api_content` sidecar) goes before the user's words,
  and a span shortened to fit says how to restore it.
- **What it leaves in their place.** One message where the folded turns were,
  in a conversation role (a mid-conversation `system` message would become
  the system prompt on Anthropic's API):
  `[CONTEXT COMPACTION — REFERENCE ONLY] Chronicle folded …`, listing the
  user's folded requests verbatim, one line per folded tool step (the command
  and its output or error), facts stated in them, memory recalled for a focus
  (or passed by Hermes as `memory_context`), and the ids of anything there was
  no room to show.
- **Nothing is lost.** Every folded message is archived first;
  `chronicle_expand(span_id)` restores it byte for byte.
- **Cache-friendly.** A pass extends the settled prefix byte for byte while it
  is small; once it is most of the budget, the next pass rebases into one
  consolidated handoff (one cache break, as Hermes' own compressor pays).
- **Inspectable.** `chronicle_context_status` reports the policy in force, the
  passes so far and what the handoff carries; each pass logs one
  `chronicle compaction:` line.

### What goes into a turn unasked

The memory provider's per-turn recall is memory about the user and about the
message just sent: an item must share a content word with it — as written or
inflected (book/booked, city/cities), not merely as a prefix — and a message
with more than three content words needs two of them in an item. A shorter
message's single shared word is often a coincidence ("system health check" and
a prescription's `health_event`), so such a match must also be near the
message in meaning: the item's stored vector against the message's (a short
item with none is embedded on the spot, a few per turn), within a second and a
half of quick requests to the embedder (`retrieval.prefetch_min_similarity`;
measured per model, 0.65 for nomic-embed-text). Only the user's own words in a
past exchange are asked; URLs, short numbers, host framing, tool output and
the agent's own memory writes never count. A scheduled job's turn gets none
(`retrieval.prefetch_automation`). Explicit search, `chronicle_answer` and the
context engine's recall are not gated.

**Maintenance runs on those hooks, not on cron.** There is no daemon, no timer
and no background thread: on a hook call the `Scheduler` (`engine/scheduler.py`)
compares each schedule's cron string against a persisted watermark
(`maintenance_runs`) and enqueues **at most one** due job onto the ordinary
curation queue, inside a wall-clock budget (`maintenance.budget_ms`, default
5ms; a call with nothing due costs ~0.08ms and executes no SQL at all). The work
itself is then done by the existing bounded per-turn drain, on the ordinary
`append_event` write path. What is scheduled: session reaping
(`reaper.schedule`), belief decay (`forgetting.decay_schedule`), the CSP
consistency sweep (`health.consistency_sweep.schedule`), the health/self-heal
run (`health.schedule`), the session-index backfill
(`curation.sweep_schedule`), and the exact-name identity sweep
(`identity.schedule`). An empty cron string disables a schedule; so does
an unparseable one, loudly. `core.maintenance_status()` reports last-run and
next-due per schedule, plus the tasks that are deliberately **not** scheduled
and why (e.g. `derive`, which mints new beliefs — a capture path, not
maintenance).

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

## Installation

```bash
hermes plugins install indigokarasu/chronicle-agent-context-and-memory
```

Requires Hermes Agent with plugin support. Python 3.9+.

## Configuration

Set in `~/.hermes/config.yaml`:

```yaml
memory:
  provider: chronicle    # the HOST's slot selector — Hermes reads this, not Chronicle
  db_path: ~/.hermes/commons/db/chronicle/chronicle.db
  git_repo: ~/.hermes/commons/db/chronicle/git
  embeddings:
    model: auto          # auto-detect the local server's embedding model; or pin an id, or 'hashing'
                         # for offline vectors. Unreachable = degraded (queued embeds), never hashed.
                         # $CHRONICLE_EMBED_MODEL overrides this.
    dimensions: 768
    allow_remote: false  # permission to send memory excerpts OFF this host. See "Where memory
                         # is allowed to go" below. Leave false unless you mean it.
  extraction:
    llm:
      allow_remote: false  # same, for extraction.backend: llm — that path POSTs the raw excerpt
  vector_index:
    backend: bruteforce  # default: paged scan over observed_vectors — always correct, cost
                         # grows with the corpus. 'sqlite-vec' opts into the ANN fast path,
                         # which needs `pip install sqlite-vec` AND a sqlite3 built with
                         # loadable-extension support (Apple's macOS system Python has
                         # neither). Missing either — or a vec0 left over at a different
                         # embedding width — falls back to the paged scan on its own. The
                         # top-k is the same either way; only the time to get it changes.
  maintenance:            # the in-process cadence; see "Maintenance runs on
    enabled: true         # those hooks, not on cron" above
    budget_ms: 5
  reaper:
    enabled: true        # false stops the idle-session reaper and its startup recovery
    schedule: "*/5 * * * *"   # 5-field cron, UTC; "" disables
    idle_threshold: "20m"
    reap_threshold: "45m"
  retrieval:
    fts_weight: 0.4
    vector_weight: 0.6
    rrf_k: 60
    rerank_blend: 0.5
    abstain_gate: focus
    include_drafts: true  # drafts are rendered [DRAFT], not hidden; false shows
                          # only confirmed truth. Read at the one _readable gate.
  context:
    breadth_floor: true          # reserve room for N sessions in the ranked fill
    breadth_floor_sessions: 5
  forgetting:
    decay_schedule: "0 3 * * *"
  identity:
    schedule: "0 5 * * *"   # exact-name sweep: proposes merge CANDIDATES only
  health:
    schedule: "0 4 * * *"
    consistency_sweep:
      enabled: true
      schedule: "0 * * * *"
    census_total_max_age_hours: 24
    self_heal:
      embedder_mismatch_max: 500  # vectors ONE health run may requeue to re-embed
  confidence:
    base:
      user_direct: 0.85  # per source_type; this table decides a stored fact's confidence
    trust_ceiling:
      4: 1.00            # C(level) cap applied after the base
  domains:
    user:
      contradiction_policy: flag_for_review   # flag_for_review | newer_wins | refetch
  curation:
    drain:
      per_turn: 16       # split across task classes by the three share_* weights
      share_write_path: 0.5
      share_embed: 0.3
      share_maintenance: 0.2
    lease_seconds: 900   # a 'running' job older than this is treated as abandoned
    max_attempts: 20
    retention:
      enabled: true      # prune terminal job rows; false accepts unbounded growth
      done_days: 7
      max_rows: 20000
  sweeps:
    row_budget: 5000     # shared per-run pace for every sweep without its own entry
    page_rows: 1000
    budgets:
      consistency: 2000
  learning:
    max_active_deltas: 8
    max_delta_magnitude: 0.15
```

Keys that `engine/config.py` declares but no shipped code reads are deliberately
absent from this sample — `python3 scripts/audit_config.py` lists them as
DORMANT with a reason for each. Setting one does nothing, which is why it is not
shown here as though it did.

### Where memory is allowed to go

Chronicle is local-first, and that is now a **control, not a claim**. Two endpoints in
the engine can carry memory content off the machine: the embeddings server
(`embeddings.base_url`, or `$CHRONICLE_EMBED_BASE_URL`) and the optional LLM extractor
(`extraction.llm.base_url`, which POSTs the raw excerpt in its prompt). Before either
one is used, Chronicle resolves its host and **refuses anything that is not on this
host or its private network**:

| Allowed | Refused |
|---------|---------|
| `127.0.0.0/8`, `::1`, `0.0.0.0`/`::` | any public IP literal |
| the literal name `localhost` (and `*.localhost`) — no DNS needed | a public hostname, e.g. a hosted inference API |
| RFC1918 `10/8`, `172.16/12`, `192.168/16`; ULA `fc00::/7`; CGNAT `100.64/10` | an `https://` URL to a third-party endpoint |
| link-local `169.254.0.0/16`, `fe80::/10` | a hostname that will not resolve (**fail closed**) |
| a `unix:` / `http+unix:` socket URL | a hostname with **any** public answer in its DNS result |

A hostname is resolved **once**, when the client is constructed, and the verdict is
cached — the embed path itself never does DNS.

Refusal is not a crash. Embeddings fall to **degraded mode** (no vectors written, every
embed queued for retry, FTS retrieval unaffected) and the LLM extractor falls back to
the offline heuristic. One `WARNING` per process explains what was refused and why.
Nothing is sent.

To deliberately send memory excerpts to a remote endpoint, set
`embeddings.allow_remote: true` (and/or `extraction.llm.allow_remote: true`). Both
default to `false`. With them true, Chronicle logs one warning stating plainly that
memory content is leaving the host, and the local-first guarantee no longer applies to
that deployment.

### Key options

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

### New in 5.7.0

`engine/config.py`'s `DEFAULTS` gained 35 leaf keys this release and lost 15
(see "Configuration honesty" below for the ones that went). Every key here is
read by shipped code — `python3 scripts/audit_config.py` prints the file and
line that reads each one, and `tests/test_config_honesty.py` fails the build if
that ever stops being true.

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

### Configuration honesty

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

### Security: Chronicle does not encrypt anything at rest

Stated plainly because a previous release shipped `security.encrypt_at_rest:
true` as a **default** while nothing anywhere encrypted anything. The SQLite
database, its WAL, the git mirror and every vector blob are written in the
clear. Both `security.encrypt_at_rest` and `principals.encryption.
restricted_partition_keys` have been **removed**, and setting either one now
makes `Config()` raise rather than ignore it: silently ignoring a security key
leaves an operator believing in protection they do not have.

Use full-disk or filesystem-level encryption on the host. Read isolation
between principals is enforced by `access.can_read` — an ACL, not cryptography.

## Database

Stored at `~/.hermes/commons/db/chronicle/chronicle.db`. The database is self-contained: events, beliefs, principals, and FTS indices in a single file. WAL mode means readers don't block writers.

**Back up with SQLite, not with `cp`:**

```bash
sqlite3 ~/.hermes/commons/db/chronicle/chronicle.db ".backup /path/to/copy.db"
```

`.backup` is safe against a running writer and folds in the WAL. `cp` of a live
WAL-mode database gives a torn copy that silently loses committed frames, and
`VACUUM INTO` may renumber rowids, which breaks anything keyed on them. If you
would rather copy files, stop Hermes first and take `.db`, `.db-wal` **and**
`.db-shm` together. `MemoryStore.close()` / `ChronicleCore.close()` checkpoint
the WAL and release the sidecars if you are shutting down from code.

## Tools

The memory provider exposes these tools to the agent:

- **chronicle_remember**: Store a fact or observation explicitly
- **chronicle_search**: Search the belief store and raw events
- **chronicle_answer**: Ask a question against stored memory
- **chronicle_forget**: Remove a memory entry
- **chronicle_list_directives**: List active memory directives

The context engine adds:

- **chronicle_pin_context**: Pin a context span so compression never evicts it
- **chronicle_focus**: Set the focus topic for memory-aware compression

## Dashboard

Chronicle ships a Hermes dashboard tab (`dashboard/`) with two views.

**Overview** shows store counts, embedding coverage, recent activity, and a
button that queues extraction for turns that have none.

**Tapestry** is how the memory itself is browsed, by what it is about rather
than by how it arrived. The rail counts what Chronicle holds — people, places,
things, events, ideas, and whatever it cannot classify — and picking one lists
them, biggest first. An entity's page shows what memory says about it now, what
it used to say, the events it appears in, and every captured turn that names it,
each labelled with who was speaking in that turn (you, a scheduled job, the
assistant, a tool, the host), so nothing reads as yours that was not.

Above it, the **weave** puts the dated events on one time axis with a thread per
entity they involve: a knot on your thread and on the person's, joined where an
event names them both. Threads are ordered by how much of your memory runs
through them, and the quieter ones are counted rather than drawn a pixel high.

Classification comes from the sources, never from a guess: an entity's kind from
its own recorded type or its predicates, a contact's person-or-company from the
people store that owns that record (an unreviewed row stays "unreviewed"), and
an event's date from the date the importer wrote into its title.

**Provenance is a drill-down, not the way in.** From any fact or mention,
"provenance" opens the log: every event drawn as a point on the row of whatever
wrote it — a cron job, a chat session, the curator — with the chart above
counting events over time, inspectors for an event, a run or a belief, and
lenses for open contradictions, replaced facts and duplicate notes.

The Tapestry reads the store with a `mode=ro` SQLite connection per request, so it
cannot write memory and never holds a read transaction open. Drawing is done on
the GPU with deck.gl, which keeps the whole log (hundreds of thousands of events)
interactive. The deck.gl bundle (`dist/tapestry.js`) is loaded only when the Tapestry
tab is opened.

The UI is built from `dashboard/web/src`, and the built files in
`dashboard/dist` are committed, because the dashboard loads them with no build
step on the host:

```bash
cd dashboard/web && npm install && npm run build
```

`dashboard/web/harness/server.py --db <chronicle.db>` serves the UI and the
plugin API against a local store behind a stand-in for the plugin SDK, for
working on the UI without the OAuth-gated dashboard. It never writes.

## Development

```bash
git clone https://github.com/indigokarasu/chronicle-agent-context-and-memory.git
cd chronicle-agent-context-and-memory
pip install -e ".[dev]"
/usr/bin/python3 -m pytest tests/ -q --ignore=tests/exercise/test_manual.py
ruff check .
```

Tests run against temporary SQLite databases in a sandbox the harness removes.
The suite is hermetic — no network, no `$HOME`, no ambient environment, no
collection-order dependence — and it has **four** modes, all of which must be
green. `tests/README.md` is the reference; `tests/exercise/` holds acceptance
scripts rather than unit tests, and `test_manual.py` is excluded from the gate
by design.

## Project structure

```
chronicle/             # installs to ~/.hermes/plugins/chronicle/
  __init__.py          # plugin entry: register(ctx) registers both slots + __version__
  provider.py          # ChronicleMemoryProvider (memory-provider slot)
  context.py           # ChronicleContextEngine (context-engine slot, I17)
  _base.py             # minimal ABCs so the adapters import offline (dev/tests)
  plugin.yaml          # Hermes plugin manifest (name/version/description/hooks)
  pyproject.toml       # dev/test metadata
  engine/              # shared core (relative-imported by both slots)
    core.py            # ChronicleCore singleton + Scope, wires every subsystem (§11)
    config.py          # Configuration reference + defaults (§27)
    serialize.py       # CJSON + content addressing, BLAKE3/BLAKE2b (§5)
    store.py           # MemoryStore: atomic append = reduce+git+curation (§6/§24, I7)
    reducer.py         # Pure projection: events → belief store (§7)
    trust.py           # Trust ceilings + confidence + calibration (§10)
    criticality.py     # Criticality rules floor (§20.1)
    access.py          # ACL logic: default-allow within a user (§15)
    capture.py         # CaptureEngine + Reaper (§12)
    extraction.py      # Pluggable Extractor + heuristic default (§16)
    derivation.py      # Guarded compositional inference + TMS (§9, I24)
    curation.py        # Curation worker + DAG (§17)
    scheduler.py       # Hook-driven maintenance cadence, no daemon (§17.4)
    sweeps.py          # Resumable, observably-bounded sweep pacing (§A9)
    retrieval.py       # Dual-tier + read-and-answer + promote-on-read (§18)
    federation.py      # Capability registry: reference, don't own (§14, I20)
    forgetting.py      # Asymmetric decay + fidelity ladder + unlearning (§20)
    health.py          # Auditor + consistency sweep + self-heal (§21)
    learning.py        # Bounded learning loop, champion/challenger (§22, I19)
    reasoning.py       # Procedures, reflections, plan_context, epistemic (§19, §23)
    gitmirror.py       # Git mirror flusher + disk recovery (§26)
    embeddings.py      # Pluggable embedder + offline default (§24.4)
    tools.py           # Full agent tool surface (§23)
    errors.py          # Error codes (§32)
  dashboard/           # Hermes dashboard tab
    manifest.json      # tab registration
    plugin_api.py      # FastAPI routes: status, recent activity, extraction queue
    tapestry_api.py       # read-only Tapestry routes (event stream, inspectors, lenses)
    dist/              # built UI the dashboard loads (index.js, tapestry.js); committed
    web/               # UI source + build script + local harness
  tests/
    test_build.py      # Unit + property tests P1–P21 + worked examples B.1–B.6
```

### Implementation status

All six build phases (§31) are implemented and exercised by the test suite:
data plane + capture + principals + federation (Phase 1); recall-oriented
extraction + dual-tier retrieval + read-and-answer (Phase 2); TMS + guarded
derivation + provenance/trust/ACL (Phase 3); curation + representation +
health/self-heal (Phase 4); context engine + bounded learning + reasoning +
epistemic + procedures (Phase 5); git-mirror recovery + the property suite
(Phase 6). Extraction and read-and-answer use a deterministic offline heuristic
behind a pluggable interface — a real deployment swaps in a local model without
touching the pipeline. Deferred per spec: the distributed CRDT tier (§24.5),
L3 parametric adapters (§20.4), and the TLA⁺ models (§29).

## How Chronicle compares

Mem0 and Hindsight are native Hermes memory providers. The meaningful difference
is which Hermes extension points a system owns and what must run behind it.

### Hermes integration

| System | Memory provider | Context engine | Auto-capture | Auto-recall |
|---|:---:|:---:|:---:|:---:|
| **Chronicle** | **✓** | **✓** | Every turn | ✓ |
| Hermes files | Built in | — | Agent-directed | Always injected |
| Mem0 | ✓ | — | Every turn | ✓ |
| Hindsight | ✓ | — | Default on | Default on |
| Graphiti | — | — | MCP/custom | MCP/custom |

**Auto-capture** means Hermes stores completed turns without the model choosing a
tool. **Auto-recall** means memory is added to turn context automatically, not
merely exposed through a search tool.

### Deployment and controls

| System | Default Hermes setup | No model/service | Hermes-facing controls |
|---|---|:---:|---|
| **Chronicle** | Local SQLite | **✓** | Remember, search, correct, forget |
| Hermes files | Local Markdown | ✓ | Add, replace, remove |
| Mem0 | Mem0 Platform | — | Search, add, update, delete |
| Hindsight | Hindsight Cloud | — | Retain, recall, reflect |
| Graphiti | No provider | — | MCP episode/graph tools |

Among these systems, Chronicle alone fills both the Hermes memory-provider and
context-engine slots. Its context engine rescues valuable spans into durable
memory before compaction, then rebuilds the working context. Mem0 and Hindsight
also capture every turn, but do not control Hermes compression. Hermes files are
always injected and have built-in editing tools, but are agent-curated rather
than automatically extracted. Graphiti currently requires MCP or custom wiring.

Chronicle also runs without a model, API key, or separate service. If embeddings
are unavailable, it keeps recalling through local full-text, structured, and
raw-turn fallbacks. Mem0 additionally offers self-hosted and in-process OSS
modes, which require its model, embedder, and vector-store stack. Hindsight also
offers embedded-local and external-server modes; embedded-local includes its
database but still requires a configured LLM. Graphiti supports local components
but still needs model, embedding, and graph backends.

This compares documented integration and deployment surfaces, not retrieval
quality: [Hermes provider API](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin),
[Mem0 for Hermes](https://docs.mem0.ai/integrations/hermes),
[Hindsight provider](https://github.com/NousResearch/hermes-agent/tree/main/plugins/memory/hindsight),
and [Graphiti MCP](https://help.getzep.com/graphiti/getting-started/mcp-server).

## Contributing

Bug reports, use cases, and focused pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and the best
places to start.

## License

MIT. See LICENSE.
