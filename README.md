# Chronicle Memory Provider

A local-first, crash-safe memory system for Hermes Agent. Replaces ocas-elephas.

Chronicle captures conversation and tool activity, turns it into structured beliefs, retrieves them with vector + FTS + graph traversal, and improves its own retrieval policies from observed outcomes. All data stays on your machine.

## What it does

Two plugins, one core:

- **Memory Provider** — long-term memory. Captures session activity as an append-only event log, reduces it into a belief store, serves queries through dual-tier retrieval (structured beliefs first, raw history as fallback).
- **Context Engine** — working memory. Replaces the default Hermes compressor with memory-aware compression that only evicts spans backed by durable events, and re-injects relevant long-term memory into the context window.

Either plugin runs without the other. Together they form a multiplier: the context engine can reason over what the memory provider captured.

## Architecture

```
Hooks → Event Log (append-only)
              ↓
          Reducer → Belief Store
              ↓
    Retrieval Engine → Response
```

- **Event log** — immutable, append-only. Every hook emission becomes a numbered event with content addressing (SHA-256 hash).
- **Reducer** — projects events into the belief store. Handles creation, revision, and retirement of beliefs. Truth-maintained with provenance tracking.
- **Belief store** — SQLite-backed. Stores entities, relationships, and derived facts with full provenance chains.
- **Retrieval engine** — dual-tier. Tier 1 queries the belief store via vector similarity, full-text search, and graph traversal. Tier 2 falls back to reading raw event history when no belief exists yet.
- **Forgetting** — raw events compress to gist after 365 days. The reaper closes stale transactions and compacts storage.
- **Learning loop** — bounded self-improvement. Adjusts retrieval weights and curation policies from observed outcomes, capped at 8 active deltas with max magnitude 0.15.

## Installation

```bash
hermes plugins install indigokarasu/chronicle-plugin
```

Requires Hermes Agent with plugin support and Python 3.13+.

## Configuration

Set in `~/.hermes/config.yaml`:

```yaml
memory:
  provider: chronicle
```

Full configuration reference:

```yaml
memory:
  provider: chronicle
  store: sqlite
  db_path: ~/.hermes/commons/db/chronicle/chronicle.db
  git_repo: ~/.hermes/commons/db/chronicle/git
  git_remote: null  # set to a remote URL for git mirroring
  embeddings:
    model: embeddinggemma-300m
    dimensions: 768
  vector_index:
    backend: sqlite-vec
    bruteforce_ceiling: 100000
  reaper:
    enabled: true
    schedule: "*/5 * * * *"
    idle_threshold: "20m"
    reap_threshold: "45m"
    startup_recovery: true
  extraction:
    version: "extractor-v1"
    promote_on_read: true
  retrieval:
    fts_weight: 0.4
    vector_weight: 0.6
    rrf_k: 60
    default_limit: 10
    raw_tier:
      enabled: true
  capture:
    sync_turn:
      mode: observe_only
  forgetting:
    raw_retention:
      keep_verbatim_days: 365
      then: gist
  health:
    schedule: "0 4 * * *"
  learning:
    max_active_deltas: 8
    max_delta_magnitude: 0.15
```

### Key options

| Option | Default | What it does |
|---|---|---|
| `db_path` | `~/.hermes/commons/db/chronicle/chronicle.db` | SQLite database file |
| `git_repo` | `~/.hermes/commons/db/chronicle/git` | Local git repo for event log mirroring |
| `embeddings.model` | `embeddinggemma-300m` | Embedding model for vector search |
| `retrieval.fts_weight` | `0.4` | Full-text search weight in hybrid retrieval |
| `retrieval.vector_weight` | `0.6` | Vector similarity weight in hybrid retrieval |
| `reaper.enabled` | `true` | Run periodic cleanup of stale transactions |
| `forgetting.raw_retention.keep_verbatim_days` | `365` | Days to keep raw events before compressing to gist |

## Usage

Once installed and configured, Chronicle runs automatically. It hooks into the Hermes event system and requires no manual invocation for capture or retrieval.

### Provided tools

When the memory provider is active, these tools become available to the agent:

| Tool | Purpose |
|---|---|
| `chronicle_remember` | Store a new memory with optional scope and tags |
| `chronicle_search` | Query memories via hybrid retrieval |
| `chronicle_answer` | Ask a question backed by stored memory |
| `chronicle_forget` | Retire a specific memory or scope |
| `chronicle_list_directives` | List active curation directives |

### Plugin hooks

Chronicle registers these Hermes hooks:

| Hook | Fires when |
|---|---|
| `on_session_end` | A session closes |
| `on_pre_compress` | Context window compression begins |
| `on_memory_write` | The agent writes to memory |
| `on_delegation` | A task is delegated to a sub-agent |
| `on_turn_start` | A new conversation turn begins |
| `on_session_switch` | The active session changes |
| `system_prompt_block` | The system prompt is assembled |
| `prefetch` | Background prefetch cycle runs |
| `queue_prefetch` | Queued prefetch items are processed |

## Database

Chronicle stores data in two places:

- **SQLite database** — beliefs, entities, relationships, and the vector index. Default: `~/.hermes/commons/db/chronicle/chronicle.db`.
- **Git repo** — append-only event log mirrored to a local git repository. Default: `~/.hermes/commons/db/chronicle/git`. Set `git_remote` to push to a remote.

## Development

### Running tests

```bash
cd chronicle-plugin
python -m pytest tests/ -v
```

Tests cover serialization, event log integrity, reducer correctness, capture engine behavior, and retrieval accuracy. All tests use temporary databases and clean up after themselves.

### Project structure

```
chronicle-plugin/
  __init__.py          # Package metadata, version
  plugin.yaml          # Hermes plugin manifest
  engine/              # Core modules (shared by both plugins)
    core.py            # ChronicleCore — shared state and lifecycle
    serialize.py       # Content addressing, canonical JSON
    store.py           # SQLite-backed belief store
    reducer.py         # Event → belief projection
    capture.py         # Hook processing, reaper
    retrieval.py       # Dual-tier retrieval engine
    __init__.py        # Public engine API
  plugins/             # Hermes plugin adapters
    memory_provider.py # MemoryProvider ABC implementation
    context_engine.py  # ContextEngine ABC implementation
  tests/
    test_build.py      # Build verification tests (43 tests)
```

### Build spec

For the full design document, see [BUILD_SPEC.md](BUILD_SPEC.md). It covers the architecture, data model, invariants, capture policy, retrieval design, truth maintenance, forgetting lifecycle, and implementation phases.

## Contributing

Bug reports and pull requests are welcome. Before submitting:

1. Run the test suite and confirm all tests pass.
2. Keep changes focused. One concern per pull request.
3. Update the build spec if the change affects architecture or invariants.
4. Do not add dependencies without a specific reason. Chronicle has zero external runtime dependencies beyond what Hermes already provides.

## License

MIT
