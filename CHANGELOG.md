# Changelog

All notable changes to the Chronicle Hermes plugin. Versioning follows the
`version` in `plugin.yaml`.

## 5.3.3

- Fix: context engine not loading ("Context engine 'chronicle' loaded but no
  engine instance found" → fell back to the built-in compressor). The
  context-engine loader's subclass-fallback path scans the module for a
  ContextEngine subclass, but the classes were only imported lazily inside
  register(). Now ChronicleContextEngine / ChronicleMemoryProvider are exposed at
  package top level so that path finds them.
- Hardened register(ctx): each slot (memory / context / command) is registered
  independently, so a loader collector that rejects command registration can no
  longer discard an already-registered context engine.

## 5.3.2

- Added a user-facing **`/chronicle`** slash command (registered via the general
  plugin system) that prints status in-session — including whether embeddings are
  a live local model or the offline hashing fallback, plus store counts. Tools are
  agent-invoked; this gives the user a direct handle Hermes understands.

## 5.3.1

- Added an embedding diagnostic so you can confirm whether the selected model
  actually embeds: `scripts/embedding_check.py` (shell) reports the configured
  model, visible local servers/models, the resolved embedder, and a strict live
  test embed (exit 0 = real model, 2 = offline hashing, 3 = selected-but-failing).
  Also exposed as the `chronicle_embedding_status` tool / `core.embedding_status()`
  for checking the live runtime selection from within Hermes.

## 5.3.0

- Embedding model default is now **`auto`** (no hardcoded `embeddinggemma-300m`).
  Auto-detects a running local OpenAI-compatible server and uses **whatever
  embedding model it serves** — queries `/v1/models`, picks an embedding-looking
  id (or test-embeds candidates), so it adapts to Ollama / LM Studio / llama.cpp
  naming instead of assuming an id. Pin a specific id to override; `hashing`
  forces offline; falls back to hashing if nothing is reachable.

## 5.2.1

- Graceful failure when a local model is configured but can't embed. `embed()` is
  now resilient: a model with no embeddings support, a missing `/v1/embeddings`
  route, a wrong model id, a timeout, or a server that dies mid-session no longer
  raises — the embedder trips to the offline hashing embedder (same dimensions)
  for the session and logs once.
- The durable capture path is guarded independently (`reducer._safe_vec`), so the
  embedding backend can never roll back a `sync_turn` write (I12); retrieval and
  session-summary embedding are guarded too. FTS retrieval continues regardless.
- `healthcheck()` stays strict (init still cleanly falls back to hashing when the
  endpoint/model can't embed) and uses a short timeout so a hung server can't
  stall startup.

## 5.2.0

- **Local embedding model is now the default.** Embeddings use a real local
  model (`embeddinggemma-300m`) over an OpenAI-compatible `/v1/embeddings`
  endpoint, auto-detected across common local servers (LM Studio :1234, Ollama
  :11434, llama.cpp :8080) or a configured `embeddings.base_url` /
  `$CHRONICLE_EMBED_BASE_URL`. New `OpenAICompatEmbedder` (stdlib `urllib`, no
  new deps).
- If no local server is reachable, Chronicle **falls back to the offline hashing
  embedder** with a warning — retrieval (FTS + vectors) never hard-breaks, and
  the box still works with no model running. Set `embeddings.model: hashing` to
  force offline.
- Setup wizard adds an `embeddings_base_url` field; `embeddings_model` now
  defaults to the local model.

## 5.1.1

- Embeddings are honest about the default: the built-in **offline hashing**
  embedder is the default and always-available fallback. `engine/config.py`,
  the core, and the setup-wizard field now agree (no more `embeddinggemma-300m`
  shown as the default when hashing is what actually runs).
- The core now builds its embedder from config via `get_embedder(...)`; setting
  a real model name attempts to load a local runtime and **falls back to hashing
  with a warning** if unavailable (`engine/embeddings.py:_load_model_embedder`
  is the pluggable hook), instead of being ignored.

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
