# Changelog

All notable changes to the Chronicle Hermes plugin. Versioning follows the
`version` in `plugin.yaml`.

## 5.1.0

- Bumped version so the version-checked installer/updater detects changes since
  5.0.0 (the proper-Hermes-plugin restructure — `register(ctx)`, relative
  imports, root-level adapters — is in the 5.0.0 notes below).
- Removed references to other OCAS skills from the plugin (no longer names
  predecessor/sibling skills in manifest, docs, or code).

## 5.0.0

First complete build of the Chronicle memory system — the canonical event-sourced
memory + working-memory context for Hermes.

### Added — packaging
- Hermes **plugin** package: `plugin.yaml` manifest + a `register(ctx)` entry
  point in `__init__.py` that registers BOTH slots (memory provider + context
  engine) from one shared core, defensively across the memory / context-engine /
  general discovery paths. Adapters live at the package root (`provider.py`,
  `context.py`) and use relative imports, so the Hermes loader's synthetic-parent
  package resolves them. Installs via
  `hermes plugins install indigokarasu/chronicle-agent-context-and-memory`;
  activate with `memory.provider: chronicle` / `context.engine: chronicle`.

### Added — engine (all six build phases)
- Event-sourced data plane: append-only log + pure reducer → belief store, with
  atomic append = reduce + git-queue + curation in one transaction; idempotent,
  content-addressed; full-log rebuild is byte-identical.
- Capture + reaper: durable per-turn capture; crash-only finalization independent
  of clean shutdown.
- Recall-oriented extraction (pluggable + deterministic offline default);
  curation worker + DAG.
- Dual-tier retrieval + read-and-answer with promote-on-read (recall floor) and
  abstention; structured + bitemporal lookups; ACL/purpose filtering.
- Truth maintenance + guarded compositional derivation (scoped, hedged,
  defeasible) with the workplace-location starter rule.
- Provenance, trust ceilings, and calibration.
- Capability federation (reference, don't own) with graceful degradation.
- Asymmetric forgetting (criticality floor + fidelity ladder + unlearning).
- Health auditor + consistency sweep + bounded self-repair.
- Bounded learning loop (champion/challenger, capped deltas).
- Reasoning layer (procedures, reflections, plan_context) + user epistemic model.
- Git mirror flush + disk recovery.
- Two Hermes plugin adapters (memory-provider + context-engine slots) sharing one
  core; memory-aware compression that evicts only durable spans.

### Tests
- Property/acceptance suite P1–P21 + worked examples B.1–B.6 (38 tests).

### Deferred (per spec)
- Distributed CRDT tier, L3 parametric adapters, and TLA⁺ models.
- Extraction and read-and-answer use a deterministic offline heuristic behind a
  pluggable interface; a local model drops in without other changes.
