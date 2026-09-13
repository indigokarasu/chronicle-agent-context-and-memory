# AGENTS.md — Chronicle Repository Instructions & Guidelines for AI Coding Agents

Chronicle is a local-first memory and context management system for Hermes Agent. It consists of two Hermes plugin adapters (`provider.py` for long-term memory, `context.py` for working memory context compression) sharing an in-process core (`engine/`).

This document provides architectural rules, structural conventions, invariants, and verification workflows for AI agents maintaining or extending this codebase.

---

## Architecture & Subsystem Boundaries

The codebase is split into plugin adapters at the root level and the core subsystem in `engine/`.

### Root Adapters
- **`provider.py` (`ChronicleMemoryProvider`)**: Hermes memory provider plugin slot. Handles durable turn capture (`sync_turn`), lifecycle hooks (`on_session_end`, `on_turn_start`, `on_session_switch`), post-tool retrieval caching (`post_tool_call`), and agent delegation capture (`subagent_stop`).
- **`context.py` (`ChronicleContextEngine`)**: Hermes context engine plugin slot. Handles working memory compression (`compress`), score-based eviction, FOLD tombstoning (`chronicle_expand`), rolling checkpoint digests, and focus rehydration.
- **`__init__.py`**: Exposes `register(ctx)` to register both plugin slots from `ChronicleCore`.
- **`_base.py`**: Stand-in abstract base classes (`MemoryProvider`, `ContextEngine`) used when Hermes package dependencies are not present during local testing.

### Core Subsystem (`engine/`)
- **`core.py` (`ChronicleCore`)**: Process singleton managing system lifecycle, scope switching, and wiring subsystems.
- **`store.py` (`MemoryStore`)**: SQLite storage layer (WAL mode). Handles events, beliefs, entities, predicates, and session state.
- **`capture.py` (`CaptureEngine`, `Reaper`)**: Durably captures turns/events, manages unextracted session cleanup and crash recovery.
- **`reducer.py` (`Reducer`)**: Pure projection engine folding raw captured events into structured belief models (facts, entities, episodes).
- **`retrieval.py` (`RetrievalEngine`)**: Hybrid FTS5 + vector retrieval, RRF scoring, raw tier fallback, answer-support verification (`verify_answer`), and abstention gating.
- **`extraction.py` (`Extractor`, `HeuristicExtractor`, `LLMExtractor`)**: Salient span extraction with heuristic regex-based offline fallback.
- **`derivation.py` (`DerivationEngine`)**: Guarded compositional inference and Truth Maintenance System (TMS).
- **`forgetting.py` (`ForgettingEngine`)**: Asymmetric decay, fidelity ladder degradation, and unlearning.
- **`tools.py` (`Tools`)**: Exposes agent-facing tools (`chronicle_remember`, `chronicle_search`, `chronicle_answer`, `chronicle_forget`, `chronicle_get_context`, etc.).
- **`vector_index.py` (`VectorIndex`)**: Dual-mode vector store (SQLite brute-force or `sqlite-vec` ANN extension).
- **`embeddings.py`**: Pluggable embedding providers (`auto`, `hashing`, OpenAI-compatible local server, `DegradedEmbedder`).
- **`config.py` (`Config`)**: Default settings reference and hierarchical parameter lookup.

---

## Critical Invariants & Rules

When modifying code in this repository, you **MUST** uphold the following invariants:

1. **Dual-Mode Import Pattern**:
   - Files under `engine/` and root plugin files must support both relative imports (when loaded as a Hermes plugin package) and absolute imports (when run standalone/pytest).
   - Pattern:
     ```python
     try:
         from .engine.core import ChronicleCore
     except Exception:
         from engine.core import ChronicleCore
     ```

2. **Durable Capture is Non-Blocking**:
   - `sync_turn` and capture hooks must perform only local appending of events without blocking on remote LLM calls or long calculations.
   - Background processes (extraction, curation, vector indexing) are drained deferred via `process_pending()` or `on_turn_start`.

3. **Context Eviction Lossless Guarantee (I17)**:
   - Spans evicted from context in `context.py` must be made durable first (`_ensure_durable`) before being removed or replaced by FOLD tombstone stubs (`_fold`).
   - Eviction must strictly respect `never_evict` rules (pinned content, explicit directives).

4. **Abstention Gating on Retrieval**:
   - `retrieval.answer()` uses a support gate (`abstain_gate`) to prevent hallucinated answers when stored evidence is insufficient. Do not remove or bypass abstention checks.

5. **Thread-Safe Single-Writer SQLite**:
   - `MemoryStore` relies on SQLite WAL mode and thread-local connections. Always handle database connections using existing transaction/lock helpers.

6. **Error Resilience & Graceful Degradation**:
   - Unreachable embedding servers degrade gracefully (`DegradedEmbedder`) to queued jobs or FTS retrieval rather than crashing.
   - Context compression falls back to `_heuristic()` if core initialization fails, retrying safely in background locks.

---

## Coding Standards & Conventions

- **Python Version**: Python >= 3.9 compatibility.
- **Type Annotations**: Use type hints for public methods and functions. PEP 561 compliance is enforced via `py.typed`.
- **Code Style**: Follow PEP 8 guidelines. Format code and clean imports using `ruff`.
- **Logging**: Use module-level loggers (`logger = logging.getLogger("chronicle...")`). Avoid bare `print()` statements in core logic.

---

## Testing & Verification Workflow

Always verify your changes by running tests before committing.

### Running Pytest
```bash
python -m pytest tests/ -q
```
*All tests in `tests/` must pass.*

### Running Ruff (Linter & Formatter Check)
```bash
ruff check .
```

### Baseline & Evaluation Scripts (when touching context/retrieval engine)
- Compression fidelity harness: `python tests/test_compression_fidelity.py`
- Context eval benchmark: `python scripts/ctx_eval.py`
- Abstention sweep: `python scripts/sweep_abstain.py`

---

## Guidelines for AI Coding Agents

1. **Read Before Writing**: Inspect existing patterns in `engine/core.py`, `engine/store.py`, and `context.py` before modifying core logic.
2. **Never Edit Build Artifacts**: Make edits only to primary source code files.
3. **Verify Every Step**: Execute pytest and read-only checks after code edits to confirm zero regressions.
4. **Keep Commits Clean**: Group changes logically and follow conventional commit formatting.
