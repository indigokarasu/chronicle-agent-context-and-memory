# Chronicle Agent Memory and Context (for Hermes)

Two plugins, one core. A local-first memory system for Hermes Agent.

**ChronicleMemoryProvider** persists conversation history, facts, and agent knowledge across sessions using an event-sourced SQLite store. **ChronicleContextEngine** replaces the default context compressor with memory-aware compaction that evicts only durable spans and re-injects relevant long-term memory.

Version: 5.1.1.

## 🤖 If you are an agent: how to install & set up

> Read this first if you're an AI agent installing or wiring up Chronicle. It is self-contained and matches the actual code — the `engine/` core plus the root `provider.py` / `context.py` adapters and the `register(ctx)` in `__init__.py`.

**What you're installing.** Two Hermes plugins over one shared in-process core (`ChronicleCore`): a **memory provider** (long-term memory) and a **context engine** (working memory). Either runs without the other. Pure Python standard library — no required dependencies, no network, no model server.

**1. Install**

```bash
# Managed by Hermes (registers both plugin slots from plugin.yaml):
hermes plugins install indigokarasu/chronicle-agent-context-and-memory

# OR local/dev install:
git clone https://github.com/indigokarasu/chronicle-agent-context-and-memory.git
cd chronicle-agent-context-and-memory
pip install -e .            # add ".[dev]" for pytest, ".[hash]" for spec-exact BLAKE3
```

Requires **Python ≥ 3.9**. Without the optional `blake3` package, content addressing falls back to BLAKE2b-256 (set `CHRONICLE_REQUIRE_BLAKE3=1` to require BLAKE3).

**2. Both slots register automatically.** `__init__.py` exposes a `register(ctx)`
that the Hermes loader calls; it registers **both** slots from the one shared core:

```python
def register(ctx):
    if hasattr(ctx, "register_memory_provider"):
        ctx.register_memory_provider(ChronicleMemoryProvider())
    if hasattr(ctx, "register_context_engine"):
        ctx.register_context_engine(ChronicleContextEngine())
```

Then activate them in `~/.hermes/config.yaml` (each slot is single-select):

```yaml
memory:  { provider: chronicle }   # everything else has safe defaults (engine/config.py)
context: { engine: chronicle }     # optional — enables memory-aware compression
plugins: { enabled: [chronicle] }  # if not auto-enabled on install
```

**3. First run is zero-setup.** On the first `initialize(...)` the SQLite database and full schema are created automatically at `~/.hermes/commons/db/chronicle/chronicle.db`. There is no migration or `createdb` step. Startup recovery + the reaper finalize any sessions left by a crash.

**4. Verify it works**

```bash
python -m pytest tests/ -q        # 38 property/acceptance tests (P1–P21, B.1–B.6)
```

**5. How you drive it at runtime.** Under Hermes the hooks fire for you (`sync_turn` captures every turn durably; `on_turn_start` drains a slice of background work; `on_pre_compress`/`compress` handle the window). You get agent tools via `get_tool_schemas` — `chronicle_remember`, `chronicle_search`, `chronicle_answer`, `chronicle_ask_about`, `chronicle_get_context`, `chronicle_explain`, `chronicle_correct`, `chronicle_forget`, plus ACL/derivation/reasoning tools (see [Tools](#tools)).

**Programmatic quickstart (no Hermes needed — good for validating an install):**

```python
from engine.core import ChronicleCore

core = ChronicleCore.get("/tmp/hermes_home")          # singleton; auto-creates the db
core.initialize(session_id="s1", principal_id="assistant")

core.capture.observe("My name is Jared. I work at Innovaccer.", "Hi Jared!", session_id="s1")
core.capture.observe("My office is in downtown", "noted", session_id="s1")
core.process_pending()                                 # run extraction → derivation → curation

print(core.retrieval.answer("where is my workplace"))  # dual-tier read-and-answer (abstains if unknown)
print(core.tools.dispatch("assistant", "chronicle_search", {"query": "Innovaccer"}))
```

**Good to know.**
- **Capture is durable and cheap; understanding is deferred.** `sync_turn`/`observe` only appends one local event; extraction, derivation, and curation run in the background (drained by `on_turn_start` or `core.process_pending()`).
- **Recall floor:** anything captured is answerable even if eager extraction missed it — the raw tier + read step recover it and write the belief back. The system abstains rather than fabricates when there's no support.
- **Extraction & read-and-answer use a deterministic offline heuristic** behind a pluggable `Extractor` interface (`engine/extraction.py`). Swap in a local model there for higher precision — nothing else changes.
- **Multi-agent default is open within one user** (every agent reads the user's and siblings' memory); restriction is explicit via `chronicle_set_acl` / `chronicle_revoke_read`.

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

## Contributing

Open an issue or pull request on GitHub. Keep changes small and tested. Run `pytest tests/` before submitting.

## License

MIT. See LICENSE.
