# Chronicle Plugins

Two plugins, one core. A local-first memory system for Hermes Agent.

**ChronicleMemoryProvider** persists conversation history, facts, and agent knowledge across sessions using an event-sourced SQLite store. **ChronicleContextEngine** replaces the default context compressor with memory-aware compaction that evicts only durable spans and re-injects relevant long-term memory.

Replaces: ocas-elephas skill. Version: 5.0.0.

## Architecture

Both plugins share a process-singleton `ChronicleCore` that owns:

- **MemoryStore**: SQLite WAL mode, single-writer with thread-local connections
- **CaptureEngine**: observes turns, extracts salient spans, runs the reaper
- **Reducer**: folds events into the belief store (facts, entities, episodes)
- **RetrievalEngine**: dual-tier recall: FTS5 + structured lookup over beliefs, plus raw event access

The context engine hooks into `on_pre_compress` and owns compression when active. The memory provider hooks into `on_session_end`, `on_turn_start`, `on_delegation`, and `on_memory_write`.

## Installation

```bash
hermes plugins install indigokarasu/chronicle-plugin
```

Requires Hermes Agent with plugin support. Python 3.12+.

## Configuration

Set in `~/.hermes/config.yaml`:

```yaml
memory:
  provider: chronicle
  store: sqlite
  db_path: ~/.hermes/commons/db/chronicle/chronicle.db
  git_repo: ~/.hermes/commons/db/chronicle/git
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

Option | Default | Purpose
-------|---------|--------
`db_path` | `~/.hermes/commons/db/chronicle/chronicle.db` | SQLite database location
`reaper.enabled` | `true` | Run idle-session reaper on schedule
`reaper.idle_threshold` | `20m` | Mark session idle after this duration
`reaper.reap_threshold` | `45m` | Finalize idle sessions after this duration
`retrieval.fts_weight` | `0.4` | FTS5 score weight in hybrid retrieval
`retrieval.vector_weight` | `0.6` | Vector score weight in hybrid retrieval
`forgetting.raw_retention.keep_verbatim_days` | `365` | Days to keep raw events before gist conversion
`learning.max_active_deltas` | `8` | Max concurrent self-improvement deltas

## Database

Stored at `~/.hermes/commons/db/chronicle/chronicle.db`. The database is self-contained: events, beliefs, principals, and FTS indices in a single file. WAL mode means readers don't block writers.

Back up by copying the `.db` and `.db-wal` files while Hermes is stopped.

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

## Development

```bash
git clone https://github.com/indigokarasu/chronicle-plugin.git
cd chronicle-plugin
pip install -e ".[dev]"
pytest tests/
```

Tests run against an in-memory SQLite database. No external services needed.

## Project structure

```
chronicle-plugin/
  __init__.py          # Package init, version
  pyproject.toml       # Package metadata
  plugin.yaml          # Hermes plugin manifest
  engine/              # Core modules (shared by both plugins)
    core.py            # ChronicleCore singleton + Scope
    store.py           # MemoryStore (SQLite backend)
    capture.py         # CaptureEngine + Reaper
    reducer.py         # Reducer (event folding)
    retrieval.py       # RetrievalEngine (dual-tier)
    serialize.py       # Serialization helpers
  plugins/             # Hermes plugin adapters
    memory_provider.py # ChronicleMemoryProvider
    context_engine.py  # ChronicleContextEngine
  tests/
    test_build.py      # Build verification tests
```

## Contributing

Open an issue or pull request on GitHub. Keep changes small and tested. Run `pytest tests/` before submitting.

## License

MIT. See LICENSE.
