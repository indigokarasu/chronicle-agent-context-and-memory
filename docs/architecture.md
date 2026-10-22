# Architecture

Section numbers (§) and the A- and I- tags on this page refer to the design specification
that the code comments cite.

Both plugins share a process-singleton `ChronicleCore` that owns:

- **MemoryStore**: SQLite WAL mode, single-writer with thread-local connections
- **CaptureEngine**: observes turns, extracts salient spans, runs the reaper
- **Reducer**: folds events into the belief store (facts, entities, episodes)
- **RetrievalEngine**: dual-tier recall: FTS5 + structured lookup over beliefs, plus raw event access

When the context engine is selected, Hermes hands it compaction: it calls the engine's `compress()` and `prune_tool_results_only()` itself (the memory provider's `on_pre_compress` then returns nothing, so nothing is summarised twice). The memory provider hooks into `on_session_end`, `on_turn_start`, `on_delegation`, and `on_memory_write`.

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
    dist/              # built UI the dashboard loads (index.js); committed
    web/               # UI source + build script + local harness
  tests/
    test_build.py      # Unit + property tests P1–P21 + worked examples B.1–B.6
```

## Implementation status

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
