## 5.4.0
Abstention support gate; chunked capture; degraded-mode embeddings with retry queue and self-heal; paged vector scan + optional sqlite-vec; session-grouped dated context with session windows; temporal channel (absolute + relative w/ now=); graph read channel; entity digests; standing user profile; NOOP-dedup; corrected chronicle_correct/chronicle_remember; generic local-DB federation provider + projection embeddings + SELECT-only db_query tool; config honesty audit. Canonical embedder: nomic-embed-text (local only).

# Changelog

All notable changes to the Chronicle Hermes plugin. Versioning follows the
`version` in `plugin.yaml`.

## 5.6.0

### Ladder 9 fix program (F1 / F2X / F5 / F4) — integration summary

Four independently-developed work items, integrated onto `v560` in that order.
Each has its own full entry below; this is the map of what the program set out
to fix and, at the end, the one place where two of the items meet.

**F1 — the E12 firing shuffle was never float jitter.** The same six
LongMemEval instances fired E12 on 4 of 6 one day and 5 of 6 the next with no
code change, and the cause was found rather than guessed at:
`query_understanding` joined a `set` into the text it embedded, and CPython
randomises string hashing per process, so the same question was embedded as a
different **word order in every process**. A word-order-sensitive embedder
therefore produced a different query vector, a different top-20, and a
different gate answer each run. It went unseen because every offline gate runs
the hashing embedder — a bag of hashed tokens, and so the one embedder that
cannot observe the bug. Recorded so nobody re-derives it: ollama/nomic returns
bit-identical vectors for identical input, and two stores built from one
instance inside ONE process agree to the last float. There is no per-build
jitter in this pipeline at all. The REAL ties that remain are handled
separately, by a relative tie epsilon, a tie-aware head and an event-id
tiebreak, so the gate's ordering and its head boundary can never disagree
about who is tied.

**F2X — two always-on refusals for E12, both from measured failures.** The
supersede-chain veto: the cut drops every session but the modal one *and*
skips the ranked-belief block, which is the only place E4's
`[history: A -> B]` annotation renders, so on evidence the store has already
recorded an update for, it hands the reader the pre-update value with nothing
anywhere to say a later one exists. Scoped to the measured head rather than
the leader, because the head is the pool the gate's own claim is made over.
The true-argmax gate: E9's margin gate sends an unconvincing winner back to
`"factual"`, so the route string conflated "factual is nearest" with "nothing
else was convincing" — and E12 read the string. Neither refusal is a dial;
neither adds a config key.

**F5 — the preference route was dead code, and so was the E12 guard that
depended on it.** One global 0.20 routing margin assumed four prototype routes
separate equally well; measured over 250 real questions the shipped
distribution was factual 240 / aggregation 10 / preference 0 / temporal 0.
Per-kind margins make the route reachable; preference packing then spends the
budget on the user's own turns instead of assistant prose; and E9's dead
`[PREFERENCE]` addendum was excised rather than repaired, after measuring that
repairing it does not work.

**F4 — four review findings and one revalidation.** A vestigial
`reranker_version` knob removed rather than documented again (F4a); the E10
config-coercion path driven end-to-end through `answer()` instead of only in
isolation (F4b); rerank hints scoped to an owner, closing an ordering-only but
real cross-owner leak, at `schema_version` 11 (F4c); identity-candidate
adjudications made replay-safe by addressing them through their stable dedupe
key rather than a uuid4 row id a rebuild re-mints (F4d); and
`_MMR_POOL_OVERFETCH = 1.5` revalidated on the 40 `ctx_eval` instances it was
never tuned against, confirming the value (F4e).

**Where F5 and F2X meet — two independent layers, both kept.** A preference
question is now excluded from E12 precision packing for two separate reasons:
F5 routes it `preference`, so E12's `route == "factual"` precondition excludes
it, and F2X's `_raw_route` requires the raw score geometry to name factual,
which on a preference question it does not — even when the margin gate has
snapped the route *string* back. The overlap is real, not notional: F5 shipped
one discriminating test that restored the 0.20 margin and asserted the defect
returned, and on the merged tree that assertion is false, because F2X holds
the gate on its own. `tests/test_pref_pack.py::TestE12DoesNotPrecisionPackPreference`
therefore disables the layers one at a time — plus a case with both off,
showing the original defect still reproduces on the fixture. This matters
concretely: with F5's route guard deleted and F2X left standing, exactly one
test in the whole suite fails, and it is the one written for this. Without it,
that layer could have been removed with a fully green suite.

- **E12 will not cut a context that has a recorded update in it, and will not
  cut on a `factual` route it got by default (Ladder 9 F2X).** Two refusals,
  both from measured LongMemEval failures (`reports/F2-ku-abstention.md`), both
  always-on safety semantics rather than dials — no new config key, and no
  effect on any query where E12 was not going to fire.
  * **Supersede-chain veto** (`_head_has_live_update`, consulted last in
    `_precision_decision`). The cut drops every session but the modal one *and*
    skips the ranked-belief block — the only place E4's `[history: A -> B]`
    annotation renders — so on evidence the store has already recorded an
    update for, it delivers the pre-update value with nothing anywhere to say a
    later one exists. Measured on `07741c44` ("Where do I initially keep my old
    sneakers?", real nomic): 47,998 chars → 5,904 with the updated location
    absent, and a reader that answered correctly at full budget said "I don't
    know". Scope is the **measured head**, not the leading candidate: the
    leader-only version was implemented first and does not fire on that
    instance (the leader's derived belief has no chain, the head's fifth
    member's does), and the gate's own claim — "the modal session holds
    `precision_concentration` of the top candidates" — is a claim about the
    head. Honest about what it detects: "this head carries a live update edge",
    not "that edge answers this query"; it refuses rather than resolves.
  * **True-argmax gate** (`_raw_route`, at the E12 call site in
    `get_context`). E9's margin gate sends any non-factual winner that fails to
    beat `factual` by `retrieval.query_routing_margin` back to `"factual"`, so
    the route *string* conflates "factual is nearest" with "nothing else was
    convincing". E12 read the string and cut a multi-session cost comparison
    whose true argmax was `preference` (0.448 vs factual 0.373, the lowest of
    the four) down to one clean session; the reader stopped abstaining and
    produced a confident fare breakdown (`09ba9854`, 47,992 → 5,997). E12 now
    additionally requires the raw geometry to name `factual`. E9 itself is
    untouched — same route string, same margin, same debug field — and
    `_raw_route` reads `scores` only, so how the margin is applied can change
    without moving it. Empty `scores` (routing disabled, no embedder, an
    unembeddable bank) returns `"factual"`, so a tree with no routing signal is
    byte-identical to before.
  Gates: 853 tests (15 new, each differential against the same store with the
  guard removed); union@1 **67.6%**; compression fidelity 12/12; H1 inertness
  dump byte-identical to `v560_preH1`. `ctx_eval` **77.6/84.5/89.7 →
  75.9/84.5/89.7**, attributed instance by instance: 4 of the 5 firing
  instances stop firing (all four have a non-factual raw argmax **under the
  hashing embedder**, where that argmax is a token-overlap hash and least
  meaningful), 3 of them score identically at every budget, and exactly one
  (`gpt4_731e37d7`) loses the answer-bearing turn at `token_budget=1500` only —
  it is still a hit at 4000 and 12000, so this is a position change at the
  tightest budget, not lost evidence. The chain veto changes **nothing** on
  either offline corpus: E4's default `curation.supersede_similarity` (0.82) is
  dormant under hashing, so no edge exists there to trip on.
  Cost recorded rather than hidden: under real nomic the true-argmax gate also
  stops the cut on `58ef2f1c` (argmax `temporal`) and `af8d2e46` (argmax
  `aggregation`), two single-session-user questions where E12 fires today. Both
  are arguably questions E12's own doc-comment says should never take this
  path, but the reader-accuracy effect is **unmeasured**.

- **The embedded query text no longer depends on `PYTHONHASHSEED` (Ladder 9
  F1).** `query_understanding` built its expansion as a `set` and then
  `" ".join(...)`-ed it into the text handed to the embedder. CPython
  randomises string hashing per process, so the same question was embedded as a
  different **word order in every process** — and a semantic embedder is word-
  order sensitive, so the query vector, the candidate pool, its top five and
  therefore the E12 gate's answer changed from one run to the next **on the
  same store**. That was the whole "E12 fires on 4 of its 6 motivating
  LongMemEval instances today and 5 tomorrow" defect. It is now the query's own
  content words in the order they were asked, deduped, then predicate synonyms
  in a fixed order.
  Not embedder noise, which is where it was expected to be: measured while
  chasing it, ollama/nomic returns **bit-identical** vectors for identical
  input (single and batched), and two stores built from one instance inside a
  single process produce candidate pools that agree to the last float. Nothing
  in the existing suite could have caught this because every offline gate runs
  the hashing embedder, which is a bag of hashed tokens and therefore order-
  **invariant** — the one embedder that cannot observe the bug. The regression
  test is consequently cross-process, over five `PYTHONHASHSEED` values.
  Measured effect: the six instances now probe **byte-identically across three
  independent store builds each** (18/18 runs), where before the firing set
  moved between runs. Every offline gate is unchanged (union@1 67.6%,
  ctx_eval 77.6/84.5/89.7, all 180 corpus contexts byte-identical to v560),
  precisely because the hashing embedder cannot see word order.

- **The precision gate's answer is a function of the scores, not of arrival
  order (Ladder 9 F1).** Two guards on E12's head, both about ties that are
  real rather than noise:
  * `_precision_order` — the gate and its packing now read the pool ordered by
    **tie bucket** (the score as a fraction of the pool's best, snapped to a
    `_PRECISION_TIE_EPS` = 1e-3 relative grid) and then by event id. Before,
    equal-scoring candidates came back in whatever order `retrieve_raw`'s dict
    was filled in — an FTS pass followed by a heap drain.
  * `_precision_head` — the 5-candidate head boundary is **tie-aware**: it is
    drawn on the same buckets, so every member of a tie at the cut is counted
    instead of whichever one sorted fifth. The suite's own dominant fixture has
    such a tie (ranks 5-7 are three bulk turns agreeing to better than a
    thousandth) and its head came out 5 long or 7 long from an identical pool.
    The extension is not a "be more conservative" knob — it can move the share
    either way (`e47becba` measures 0.40 under the hard cut and 0.50 tie-aware)
    — it just returns one number.
  The reported `margin` is floored at zero, because inside one bucket the id
  decides the order and the runner-up's raw score can sit a hair above the
  leader's; unfloored, a negative lead would silently refuse the query, since
  `context.precision_margin` defaults to 0.0.
  Also: `_precision_decision` no longer takes a `principal` no code read (the
  pool was already ACL-cleared by `retrieve_raw`; the argument now lives in the
  docstring), and `_expand_session_window` takes `existing_event_ids` so the
  precision leader is excluded from its own session window by identity rather
  than by exact excerpt-string equality. Scoped to the precision path: on the
  full-budget path `retrieve_raw` can hand phase 1 an FTS row whose excerpt is
  not the payload's, and that path's bar is byte-identity with a pre-E12 tree.

- **Per-kind query-routing margins (Ladder 9 F5).** `retrieval.query_routing_margins`
  overrides `retrieval.query_routing_margin` for named question kinds; ships as
  `{"preference": 0.05}`. One global threshold assumed the four prototype routes
  separate equally well and they do not: measured over 250 real LongMemEval
  questions with a real embedder, `preference` is the argmax on 15/15
  single-session-preference questions but never leads `factual` by more than
  0.138, so at 0.20 the shipped route distribution was factual 240 /
  aggregation 10 / **preference 0** / **temporal 0**. Both the E9 preference
  route and the E12 guard that depends on it were dead code. 0.05 is read off
  the measured sweep — it covers 12 of the 15 targets at 15 cross-type
  collateral, against 15/15 at 23 collateral for 0.02 — and it is what makes
  E12's `route == "factual"` gate non-vacuous here: a preference question was
  measurably precision-packed onto the wrong session (`1d4e3b97`), which is
  what that gate exists to prevent. Kinds absent from the map are unchanged.
  Note the narrowed contract: `query_routing_margin: 1.0` no longer forces every
  kind factual — `query_routing: false` is the switch that disables routing.

- **Preference packing: user turns first (Ladder 9 F5).** On the `preference`
  route `get_context` now packs the **leading message of every ranked excerpt**
  — the user's own turn — across all sessions first, defers the assistant
  halves, skips the tier-1 ranked-belief block, and cuts to
  `context.preference_budget` (default 3000 tokens). Why: a preference question
  is not answered by any item in memory, so the reader needs everything the user
  said about themselves, and measurement said it was not getting it — 73–91% of
  a packed preference context was assistant prose, and the one instance E12 had
  already cut to 1500 tokens spent 5 471 of 5 994 chars on a recipe list and
  delivered 3 of the gold session's 9 user turns. Re-measured after this change,
  the same contexts are 94–95% user text at a quarter of the volume, and on the
  probed preference misses the answer session's evidence turn arrives verbatim
  where it did not: `1d4e3b97` 0/2 → 2/2 (2 runs), `06f04340` 0/1 → 1/1
  (5 runs), with `caf03d32` 2/2 and `57f827a0` 1/1 held at 1/4 the bytes.
  `75832dbd`, whose answer session ranks 6th–9th of 10–12, is the one that got
  less reliable rather than more: 1/1 on 3 of 5 runs against 1/1 at the old 48k.
  Gated on a non-empty raw tier: with nothing to pack, trading the belief tier
  away is not a trade, so the route stays on the full-budget path.
  `context.preference_packing: false` restores the un-split fill. The decision
  joins the E12 fields on `RetrievalEngine.last_context_debug` as `pref_pack`.
  The budget is 3000 rather than precision packing's 1500 because of counting,
  not taste: a median session in these haystacks holds 6 user turns totalling
  ~1 000 chars, so 6 000 chars fits 4.6–7.3 sessions complete, not the ~10 the
  design assumed. That shortfall is worse than it sounds, because `retrieve_raw`
  orders near-tied candidates differently from run to run (measured on v560 as
  well: the same instance's answer session came back at header rank 4, then 5),
  so at 1500 tokens the same instance delivered 7 of 7 answer-session user turns
  on one run and a bare header on the next. 12 000 chars holds 9.2–14.6 sessions
  complete, which covers the whole group list and takes the ordering out of the
  decision.

- **E9's preference-belief addendum removed (Ladder 9 F5).** `get_context` no
  longer appends `[PREFERENCE] <attribute>: <value>` lines on the preference
  route, and `retrieval.query_routing_preference_cap` is gone with it. It
  selected those lines with no relevance term and no `ORDER BY` — rowid order —
  and it was dead in three independent ways: the route never fired, the default
  heuristic extractor emits no preference-shaped facts (0 rows in 7 of 8 probed
  haystacks), and its `len(ctx) < max_chars` guard cannot fire against a raw
  fill that spends the budget to the last byte. Repairing it was measured
  rather than assumed: adding first-person preference patterns to the extractor
  yields 211 facts across the 9 probed haystacks of which 8 (3.8%) come from
  the answer session, and no ordering rescues the five lines it would inject
  (rowid 0/45 from the answer session, `created_at DESC` 3/45, ASC 0/45).
  Preference packing delivers the same content from the primary source — the
  user's own sentence, out of the sessions retrieval ranked for that question.

- **Precision packing: deliver less when confident (Ladder 9 E12).**
  `get_context` now cuts to `context.precision_budget` (default 1500 tokens)
  when — and only when — the query routes **factual** (E9) *and* retrieval has
  **converged on one session**: the modal session of the top-5 raw candidates
  holds at least `context.precision_concentration` (default 0.60, i.e. 3 of 5)
  of that head, and the leading candidate is itself inside it. It then packs
  that leader first (§L8 evidence-forward, unchanged), the rest of that session
  interleaved nearest-turn / best-ranked, and nothing else — no ranked-belief
  block, no directives/contradictions/critical facts, no digests or federated
  rows. Why: measured on stratified-250 with a real embedder and a judged
  reader, contexts that made the reader **abstain** at a 12k budget were
  answered correctly when cut to ~1k of the same items' head, evidence position
  unchanged — abstention tracks context volume, not evidence quality.
  Session concentration is the gate because it is what measurement showed
  separates the two populations: on the six single-session-user questions this
  exists for, the leader's score margin is 0.02–0.16, inside the range of the
  crowded multi-evidence questions (up to 0.46), while their top-5 piles into
  one session (0.6–1.0) where the crowded ones spread (0.2–0.4). An earlier
  margin-gated build was either inert on all six or cost up to 12 ctx_eval
  points; the shipped gate fires on 4 of the 6 (48k-char contexts → ~6k, each
  still carrying its evidence turn) and *lifts* ctx_eval@1500 from 75.9% to
  77.6% with @4000/@12000 unchanged — 165 of that corpus's 180 contexts come
  back byte-identical to the pre-E12 tree, and the 15 that change are the
  firing ones.
  The gate is conservative by construction and every ambiguity resolves to the
  full budget: a spread head, a pool too short to fill the head, a pool that
  only knows one session (nothing to converge away from), a leader outside the
  modal session, a leader that is a `session:`/`proj:` pointer rather than a
  turn, a non-factual route, or no embedder (with no cosine term the head is
  FTS rank order, which cannot say where retrieval converged).
  `context.precision_margin` (default 0.0) is a secondary tightening dial on
  the leader's lead. Config-gated by `context.precision_packing` (default on);
  off, and in every non-firing case, output is byte-identical to before.
  Costs no extra retrieval: the probe is the same `retrieve_raw` call the raw
  fill already made. The decision is exposed as
  `RetrievalEngine.last_context_debug` (`route`, `precision`,
  `precision_concentration`, `precision_margin`, `precision_session`,
  `precision_event_id`, `token_budget`) and on the `get_context` tool result,
  so an eval can attribute an answer to the packing that produced it.

- **Context-pressure warning span (Ladder 7 R9).** `compress()` now emits a
  one-shot system-role advisory the first time `last_prompt_tokens` reaches
  the HIGH watermark (`context_engine.is_under_pressure()`), so the agent has
  a chance to `chronicle_pin_context` anything it wants to keep before forced
  eviction runs; the flag re-arms once `update_from_response` observes the
  window drop back below the watermark. The warning is fit against the same
  `_target_budget()`/`used` accounting as the rest of the output (clipped, or
  skipped and left un-latched if there's no room this call) so it can never
  push `compress()` over its own R2 budget guarantee, and it is only latched
  once actually included in what's returned -- so the small-body early-return
  shortcut can no longer latch the flag without ever delivering the span.
- **`vector_index.backend: sqlite-vec` is real.** It was configuration fiction —
  the setting existed, and every query brute-forced anyway. It now maintains a
  `vec0` virtual table mirroring `observed_vectors` (created lazily, written on
  add, cleaned on delete/prune/truncate) and serves `retrieve_raw`'s vector scan
  by KNN `MATCH`. Strictly optional, guarded like the numpy path in
  `embeddings.batch_cosine`: the library missing, a sqlite3 built without
  loadable extensions (Apple's macOS system Python), or a `vec0` left at a
  different embedding width all fall back to the paged scan, permanently and
  quietly. `bruteforce` stays the default and is untouched. Results are the same
  either way — the paged scan credits every FTS hit's vector contribution as a
  side effect of scanning past it, so the fast path fetches those vectors by id
  rather than letting a bounded window drop them, and widens the window when ACL
  filtering prunes its top. 5,000 vectors, 50 queries: 37.5ms → 6.4ms per query.

- **No more silent hash fallback.** `model: auto` with no reachable embedding
  server used to quietly switch to the offline hashing embedder — hash vectors are
  indistinguishable from model vectors downstream and permanently skew retrieval.
  It now runs **degraded**: no vectors are written, each one becomes an `embed`
  curation job that is deferred and retried with backoff (30s → 30m) until a
  server appears, at which point the worker adopts it and drains the backlog. One
  loud log line at init says which mode is live and why. `model: hashing` is
  unchanged — that is the deliberate offline/CI setting.
- `$CHRONICLE_EMBED_MODEL` overrides `embeddings.model`, so eval/CI can pin the
  deterministic offline embedder without editing config.
- Schema v2 + migration: `curation_jobs.run_after` (deferred retry) and task
  `'embed'`. Existing stores are migrated in place on open — `CREATE TABLE IF NOT
  EXISTS` never touches an existing table, so without this an old store would fail
  the task CHECK *inside* the durable-capture transaction and fail every claim on
  the missing column. `meta.schema_version` records the level.
- `scripts/requeue_hash_vectors.py <db> [--dry-run]`: delete vectors written by
  the hashing embedder and requeue the real embeds. Idempotent.

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
