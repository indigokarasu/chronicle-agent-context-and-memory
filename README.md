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

The context engine hooks into `on_pre_compress` and owns compression when active. The memory provider hooks into `on_session_end`, `on_turn_start`, `on_delegation`, and `on_memory_write`.

## Installation

```bash
hermes plugins install indigokarasu/chronicle-agent-context-and-memory
```

Requires Hermes Agent with plugin support. Python 3.9+.

## Configuration

Set in `~/.hermes/config.yaml`:

```yaml
memory:
  provider: chronicle
  store: sqlite
  db_path: ~/.hermes/commons/db/chronicle/chronicle.db
  git_repo: ~/.hermes/commons/db/chronicle/git
  embeddings:
    model: auto          # auto-detect the local server's embedding model; or pin an id, or 'hashing'
                         # for offline vectors. Unreachable = degraded (queued embeds), never hashed.
                         # $CHRONICLE_EMBED_MODEL overrides this.
    dimensions: 768
  vector_index:
    backend: bruteforce  # default: paged scan over observed_vectors — always correct, cost
                         # grows with the corpus. 'sqlite-vec' opts into the ANN fast path,
                         # which needs `pip install sqlite-vec` AND a sqlite3 built with
                         # loadable-extension support (Apple's macOS system Python has
                         # neither). Missing either — or a vec0 left over at a different
                         # embedding width — falls back to the paged scan on its own. The
                         # top-k is the same either way; only the time to get it changes.
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
git clone https://github.com/indigokarasu/chronicle-agent-context-and-memory.git
cd chronicle-agent-context-and-memory
pip install -e ".[dev]"
python -m pytest tests/ -q
ruff check .
```

Tests run against an in-memory SQLite database. No external services needed.

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

## Battle card: Chronicle vs. agent memory systems

Generic memory tools solve storage and retrieval. Chronicle solves the Hermes
failure mode: useful context disappearing when a long session is compressed.

| Capability | **Chronicle** | Hermes files | Mem0 | Hindsight | Graphiti |
|---|:---:|:---:|:---:|:---:|:---:|
| Native Hermes integration | **✓ Memory + context** | Files only | Adapter | Bridge | Bridge |
| Pre-eviction capture | **✓** | — | — | — | — |
| No external stack | **✓ SQLite** | ✓ Markdown | — | — | — |
| Recall without embeddings | **✓ FTS + raw turns** | Injected only | — | △ Keyword | — |
| Hermes lifecycle tools | **✓** | Manual | Adapter | Adapter | Adapter |
| Controls compaction | **✓** | — | — | — | — |

**Legend:** ✓ built in · △ partial · — not provided without custom integration.

The external stack behind the dashes is substantial: Mem0 needs model and
vector-store configuration; Hindsight needs an LLM plus PostgreSQL/pgvector;
Graphiti needs LLM/embeddings plus a graph database.

For Hermes, the only no-integration choices are the built-in files and
Chronicle. Use the files for a short, hand-maintained memo. Use Chronicle when
memory must be automatic, searchable, auditable, and survive compaction. The
other systems add an integration and infrastructure layer without closing the
Hermes context-compression gap.

Comparison is based on documented default architecture and integration surface,
not a synthetic quality benchmark: [Hermes memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers),
[Mem0 OSS](https://docs.mem0.ai/open-source/overview),
[Hindsight](https://github.com/vectorize-io/hindsight/blob/main/hindsight-api/README.md),
and [Graphiti](https://help.getzep.com/graphiti/getting-started/quick-start).

## Contributing

Bug reports, use cases, and focused pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and the best
places to start.

## License

MIT. See LICENSE.
