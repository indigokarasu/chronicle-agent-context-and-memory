"""
Chronicle — Configuration reference (§27).

Defaults that mirror the build spec's YAML. ChronicleCore reads a flat config
dict (typically loaded from ~/.hermes/config.yaml under `memory:`) merged over
these defaults. Nothing here touches the network; every value has a safe local
default so the system is fully functional on Hermes hooks alone (I18).
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any, Callable

# Env override for the embedding model (§27 embeddings.model). Deliberately wins
# over file config: eval/CI must be able to pin the deterministic offline embedder
# on a host whose config says `auto`, without editing anyone's config.yaml.
EMBED_MODEL_ENV = "CHRONICLE_EMBED_MODEL"

# Support gates selectable via retrieval.abstain_gate — §18.4
ABSTAIN_GATES = ("score", "overlap", "focus")

# Dormant flags: declared in DEFAULTS but never read by engine code. Boot warns
# once per process when a flag is actually "live" — see is_enabled below. This is
# NOT a default-value diff: two of these (hyde, expand_synonyms, decompose) are
# *already* True in DEFAULTS, so a stock boot will warn for them exactly once —
# that is the honest report, since the shipped config claims those features run
# and nothing implements them (§u1 audit). Each entry:
#   (config path, is_enabled(current_val) -> bool, reason comment)
DORMANT: list[tuple[str, Callable[[Any], bool], str]] = [
    ("retrieval.query_understanding.hyde", lambda v: bool(v),
     "Hypothetical Document Embeddings — rewrite loop not yet implemented"),
    ("retrieval.query_understanding.expand_synonyms", lambda v: bool(v),
     "Query synonym expansion — synonym detection not yet wired"),
    ("retrieval.query_understanding.decompose", lambda v: bool(v),
     "Query decomposition — multi-clause strategy not yet implemented"),
    # §A12. Two shapes of broken promise get a runtime warning, not just a
    # DECLARED_DORMANT entry:
    #   * `lambda v: bool(v)` — the value ON claims a protection that does not
    #     run. Stock defaults trip these, which is the honest report.
    #   * `lambda v: not v`  — the value OFF claims the feature is disabled when
    #     it in fact still runs. Silent at defaults; loud the moment an operator
    #     tries to turn something off and would otherwise believe they had.
    ("forgetting.confirm_critical", lambda v: bool(v),
     "critical forgets are NOT confirmed — unlearn/retract apply immediately"),
    ("behavior_change.high_risk_requires_review", lambda v: bool(v),
     "high-risk changes are written as drafts, and drafts are readable — nothing reviews them"),
    ("consent.enforce_purpose", lambda v: bool(v),
     "purpose strings are recorded but never enforced against a consent scope"),
    ("extraction.promote_on_read", lambda v: bool(v),
     "read-time promotion is unconditional — this flag cannot switch it"),
    ("derivation.enabled", lambda v: not v,
     "derivation cannot be disabled from config; use the rule table's enabled column"),
    ("retrieval.raw_tier.enabled", lambda v: not v,
     "the raw tier always participates in retrieval; this flag cannot disable it"),
    ("retrieval.read_and_answer.enabled", lambda v: not v,
     "read_and_answer always runs; only its confidence_gate is read"),
    ("representation.canonicalize.enabled", lambda v: not v,
     "the canonicalize task cannot be turned off from config"),
    ("context_engine.reinject.enabled", lambda v: not v,
     "re-injection always runs when budget allows; this flag cannot disable it"),
    ("sources.hermes_hooks.enabled", lambda v: not v,
     "the hook surface is always present; disabling it is a host-side decision"),
    # A13. Nothing reads this key. It was the switch for a background warm-cache
    # hook whose only implementation, ChronicleProvider.queue_prefetch, was
    # `pass` — so the flag has defaulted to True and meant nothing for its whole
    # life. It is declared here rather than deleted because deleting a key an
    # operator may have set in their own config makes the setting vanish
    # silently; declared, it says so once per process. (`retrieval.prefetch_budget`
    # is NOT dormant — provider.prefetch reads it on the synchronous path.)
    ("retrieval.predictive_prefetch", lambda v: bool(v),
     "Predictive prefetch — no background warm-cache path exists; the "
     "synchronous `prefetch` tool is unaffected"),
]

# ---------------------------------------------------------------------------
# DECLARATION BLOCK (§A12) — DECLARED_DORMANT
# ---------------------------------------------------------------------------
# Every DEFAULTS leaf key that engine code does NOT read, with the reason. This
# is the machine-checkable half of Chronicle's premise that config must never
# promise what code does not deliver: scripts/audit_config.py classifies each
# key WIRED / DORMANT / UNREAD, and tests/test_config_honesty.py FAILS on any
# UNREAD key -- a new knob that nothing reads cannot land quietly, and a
# declaration that goes stale (because the key got wired, or deleted) fails too.
#
# Adding an entry here is a decision, not a shrug: the alternative dispositions
# are wiring the key or deleting it, and a key stays here only while it names a
# real, named gap someone intends to close.
DECLARED_DORMANT: dict[str, str] = {
    # -- behaviour gates that nothing consults ------------------------------
    "behavior_change.high_risk_requires_review":
        "no review gate: a high-risk norm is written as a draft and drafts are "
        "readable (A16); nothing consults this flag",
    "behavior_change.risk_tier_default":
        "risk tiering is not computed; every behaviour change is written the same way",
    "consent.default_scope":
        "no consent scoping layer; read access is decided by access.can_read alone",
    "consent.enforce_purpose":
        "purpose strings are carried on queries but never enforced against a scope",
    "consolidation.enable_parametric":
        "parametric (model-weight) consolidation does not exist; consolidation is "
        "the event-driven `consolidate` curation task only",

    # -- capture ------------------------------------------------------------
    "capture.sync_turn.mode":
        "capture is always observe-only; no synchronous turn-blocking mode exists",
    "capture.agent_memory_write.salience":
        "agent memory writes take the salience on the call, defaulting to 'normal' "
        "in tools.py; this default is never consulted",
    "capture.agent_memory_write.confidence_discount":
        "no discount is applied to agent self-writes; they take confidence.base",

    # -- curation / representation ------------------------------------------
    "curation.mode":
        "curation is event-driven and cannot be switched; there is no polling mode",
    "curation.identity_threshold":
        "superseded by identity.merge_above / identity.split_below, which ARE read; "
        "kept only because tests pin its default",
    "curation.consolidate_min_facts":
        "the consolidate task has no minimum-fact gate",
    "representation.canonicalize.enabled":
        "the canonicalize task cannot be turned off from config",
    "representation.canonicalize.similarity_threshold":
        "canonicalization matches on normalized predicate text, not similarity",
    "representation.canonicalize.auto_apply_domain":
        "canonicalization applies to every domain; the allowlist is not consulted",

    # -- derivation ---------------------------------------------------------
    "derivation.enabled":
        "derivation cannot be disabled from config; the rule table's own "
        "`enabled` column is the only switch",
    "derivation.materialize":
        "materialization is decided per rule (Rule.materialize), not by this value",
    "derivation.max_depth":
        "derivation is single-hop; there is no depth to bound",
    "derivation.max_fanout":
        "fanout is bounded by sweeps.budgets.derive_subjects, which IS read",
    "derivation.confidence.aggregate":
        "aggregation is hard-coded to min() in derivation._materialize",

    # -- epistemic / forgetting ---------------------------------------------
    "epistemic.redundant_window":
        "no redundancy window is computed; E5 merges only exact duplicates",
    "epistemic.forgot_window":
        "no forgot-window tracking exists",
    "forgetting.confirm_critical":
        "critical forgets are NOT confirmed: unlearn/retract apply immediately",
    "forgetting.raw_retention.keep_verbatim_days":
        "raw events are never gisted or aged out; retention is unbounded by design",
    "forgetting.raw_retention.then":
        "see keep_verbatim_days -- there is no gist step to schedule",

    # -- extraction ---------------------------------------------------------
    "extraction.multi_hypothesis_threshold":
        "the heuristic extractor emits one hypothesis per span",
    "extraction.signal_confidence_min":
        "extracted spans carry no signal confidence to threshold",
    "extraction.granularities":
        "granularity is fixed (atomic spans + session summary); not selectable",
    "extraction.self_consistency.passes":
        "no self-consistency ensemble; one extraction pass per excerpt",
    "extraction.self_consistency.vote":
        "see passes -- there is nothing to vote over",
    "extraction.promote_on_read":
        "read-time promotion is unconditional in retrieval's read_and_answer path",
    "extraction.reextract.mode":
        "the reextract sweep is eager and has no mode selector",
    "extraction.reextract.read_budget_per_query":
        "no per-query reextraction budget is applied on the read path",

    # -- federation ---------------------------------------------------------
    "federation.mode":
        "capability binding is always dynamic discovery + config pins; no static mode",
    "federation.discover":
        "the discovery source list is fixed in federation.py, not read from config",
    "federation.rebind_on_change":
        "rebinding happens on every registry refresh; it cannot be switched off",
    "federation.precedence":
        "precedence is hard-coded (config pin > declaration order) in federation.py",
    "federation.provider_trust.default":
        "federated rows take the caller's trust level; no per-provider trust map",

    # -- git ----------------------------------------------------------------
    "git.max_lag_minutes":
        "the mirror commits on demand; no lag watchdog exists to bound",
    "git.snapshot_interval":
        "no scheduler; snapshots happen when gitmirror is called (A3)",

    # -- health / reaper schedules ------------------------------------------
    # `health.schedule`, `health.consistency_sweep.enabled`,
    # `health.consistency_sweep.schedule`, `reaper.schedule` and
    # `curation.sweep_schedule` were declared dormant by A12 with the note "no
    # scheduler (A3)". A3 IS the scheduler and it reads all five, so their
    # declarations are gone -- audit_config now reports them WIRED, which is
    # what A12's CHANGELOG predicted would happen ("the scheduler-shaped keys
    # A3 will re-type"). This is the H7 reconciliation for this step: a key that
    # becomes wired must lose its dormant declaration in the SAME commit that
    # wires it, or the honesty guard is reporting yesterday's tree.
    "health.ghost_fact.age_days":
        "the ghost scan filters on confidence and confirm_count only "
        "(health.GHOST_WHERE); the age bound is declared but not applied",

    # -- outputs ------------------------------------------------------------
    "outputs.ocas_signal_emit.enabled":
        "no signal emitter exists; nothing writes to the sink",
    "outputs.ocas_signal_emit.sink":
        "see enabled -- the sink path is never opened",

    # -- retrieval ----------------------------------------------------------
    # A13's key, declared in the map A12's guard actually reads. A13 added it to
    # the runtime-warning list (DORMANT) only, because A13's own audit script
    # predates A12's; under the merged guard a key must be declared HERE too or
    # it reads as UNREAD. (`retrieval.prefetch_budget` is NOT dormant --
    # provider.prefetch reads it on the synchronous path.)
    "retrieval.predictive_prefetch":
        "no background warm-cache path exists -- its only consumer, "
        "provider.queue_prefetch, had `pass` for a body and A13 removed it; "
        "the synchronous `prefetch` tool is unaffected",
    "retrieval.default_limit":
        "search()/get_context() carry their own literal defaults (limit=10); this "
        "key is not consulted",
    "retrieval.max_limit":
        "no caller-supplied limit is clamped against a configured ceiling",
    "retrieval.raw_tier.enabled":
        "the raw tier always participates; it cannot be disabled from config",
    "retrieval.raw_tier.span_index":
        "span indexing is unconditional at capture time",
    "retrieval.raw_tier.session_index":
        "session indexing is unconditional at capture time",
    "retrieval.read_and_answer.enabled":
        "read_and_answer always runs; only its confidence_gate is read",
    "retrieval.read_and_answer.read_budget_tokens":
        "the read budget is the caller's token_budget; this key is not consulted",
    "retrieval.read_and_answer.max_hops":
        "the path is single-hop; there is no hop counter to bound",
    "retrieval.read_and_answer.apply_derivation_rules":
        "derivation rules are applied whenever derivation is constructed",
    "retrieval.query_understanding.hyde":
        "Hypothetical Document Embeddings -- rewrite loop not implemented",
    "retrieval.query_understanding.expand_synonyms":
        "query synonym expansion -- synonym detection not wired",
    "retrieval.query_understanding.decompose":
        "query decomposition -- multi-clause strategy not implemented",

    # -- sources ------------------------------------------------------------
    "sources.hermes_hooks.enabled":
        "the hook surface is always present; disabling it is a host-side decision",

    # -- context engine slot -------------------------------------------------
    "context_engine.engine":
        "the engine name is read by the HOST when it selects a context engine; "
        "Chronicle itself never branches on it",
    "context_engine.never_evict":
        "_never_evict() hard-protects directives and pinned spans by kind; the "
        "class name here is not consulted",
    "context_engine.standalone_fallback":
        "standalone mode always uses the heuristic path; there is no alternative "
        "to fall back to",
    "context_engine.reinject.enabled":
        "re-injection always runs when there is budget for it; no off switch",
    "context_engine.should_compress.on_memory_pressure":
        "should_compress() tests the high watermark unconditionally",
    "context_engine.should_compress.on_focus_shift":
        "focus shift does not trigger a compression pass",
}

# Security promises are not merely dormant: a config that says data is encrypted
# when nothing encrypts anything is worse than no key at all, because an operator
# reads it and stops asking. These keys were DELETED from DEFAULTS (A12); if an
# operator's config.yaml still sets one, Config() REFUSES to boot rather than
# ignore it silently. Refusing beats ignoring here: ignoring keeps the operator's
# false belief intact, refusing forces them to learn the truth exactly once.
REFUSED_KEYS: dict[str, str] = {
    "security.encrypt_at_rest":
        "Chronicle does not encrypt anything at rest: the SQLite store, the git "
        "mirror and the vector blobs are all written in the clear. This key was "
        "removed rather than left to promise encryption that does not happen. "
        "Use full-disk or filesystem-level encryption on the host instead.",
    "principals.encryption.restricted_partition_keys":
        "There are no per-partition encryption keys. Read isolation between "
        "principals is enforced by access.can_read only, and that is an ACL, "
        "not cryptography.",
}


def check_refused_keys(merged: dict) -> None:
    """Raise on any config that sets a removed security promise (§A12)."""
    for path, why in REFUSED_KEYS.items():
        cur: Any = merged
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if cur is not None:
            raise ValueError(
                "config key {!r} is not supported and has been removed (§A12). {} "
                "Delete the key from your config to boot.".format(path, why))


# Flags already warned about in this process. Config() boots repeatedly (every
# LME query, every ChronicleCore() call) — without this, the loop below would
# re-log the same warning on every single boot. Module-level (not per-Config)
# so it survives across the many short-lived Config instances in one run.
# Tests may `.clear()` this to re-arm warnings for a fresh assertion.
_DORMANT_WARNED: set = set()

# Trust ceiling C(level) — §10.3
TRUST_CEILING = {0: 0.40, 1: 0.60, 2: 0.75, 3: 0.90, 4: 1.00}
INFERENCE_TRUST = 2  # inference ceiling = C(2) = 0.75 (§9.4, §10.3)

# Confidence base per source_type — §27 confidence.base
CONFIDENCE_BASE = {
    "user_direct": 0.85,
    "session_transcript": 0.70,
    "agent_memory_write": 0.85,
    "ocas_journal": 0.70,
    "tool_output": 0.50,
    "web_retrieval": 0.40,
    "inference": 0.60,
    "rescue_extraction": 0.70,
    "delegation": 0.60,
}

DEFAULTS: dict[str, Any] = {
    "db_path": "~/.hermes/commons/db/chronicle/chronicle.db",
    "git_repo": "~/.hermes/commons/db/chronicle/git",
    "git_remote": None,
    # Default = auto: detect a running local OpenAI-compatible server (base_url
    # null → LM Studio :1234, Ollama :11434, llama.cpp :8080, or
    # $CHRONICLE_EMBED_BASE_URL) and use whatever embedding model IT serves — no
    # model id is hardcoded. If none is reachable the engine runs DEGRADED (no
    # vectors written, embeds queued for retry, §24.4) — it never silently hashes.
    # Canonical recommendation (locked 2026-07-31): nomic-embed-text, served
    # locally — Ollama (:11434) or llama.cpp --embedding (:8080, ~350MB RSS, runs
    # on 1-2 vCPU self-hosted boxes). Hosts too weak for nomic run DEGRADED
    # (FTS + queued embeds).
    # allow_remote (A2): FALSE by default, and it is ENFORCED, not advisory.
    # What it permits when true: sending memory excerpts — the actual text of
    # what the user said — to an embeddings endpoint that is NOT on this host or
    # its private network. While it is false the engine REFUSES any base_url
    # (config or $CHRONICLE_EMBED_BASE_URL) that does not resolve to loopback
    # (127.0.0.0/8, ::1, localhost), an RFC1918/ULA/link-local address, or a
    # unix socket — one WARNING, then DEGRADED mode: nothing is sent, no vectors
    # are written, embeds queue. A name that will not resolve is refused too
    # (fail closed). So the guarantee this config can honestly make is:
    #   with allow_remote false, memory excerpts never leave the host.
    # This line used to state that as an unconditional absolute -- "no remote-API
    # tier", full stop -- with nothing in the engine checking it, which is how an
    # out-of-tree script shipped ~190k excerpts to a hosted API for a month. An
    # absolute no code enforces is not a stronger promise than a conditional one
    # that it does; it is a weaker one, because nobody goes looking for the gap.
    # See extraction.llm.allow_remote for the same flag on the extractor, which
    # is the path that sends whole excerpts rather than embeddings of them.
    # Set model: hashing to force the offline embedder (eval/CI only), or a
    # specific id to pin one. $CHRONICLE_EMBED_MODEL overrides this value.
    # max_input_tokens: the model's real context window, in tokens; clamped
    # [256, 32768]. overflow: "truncate" (default, boundary-aware first slice)
    # | "chunk_mean" (split into cap-sized chunks, embed each, L2-normalize and
    # mean, then re-normalize). Both exist so an oversized excerpt is clamped
    # BEFORE it ever reaches the model — never sent over-cap, never raises for
    # length (§27; the nemotron->nomic 2048-token overflow incident).
    # task_prefixes: "auto" (default: enabled iff model name contains "nomic") |
    # true (always prepend "search_query: " to queries, "search_document: " to
    # documents) | false (never prepend). Hashing mode never prefixes. Nomic-
    # embed-text is an asymmetric model trained on task prefixes; prepending
    # improves both query and document embeddings (E1).
    # doc2query (E2, §24.4): at write time, generate the questions an item can
    # answer and embed those alongside its content vector as `query_proxy_vectors`
    # rows (kind='query_proxy' role, but stored keyed by the parent's own belief
    # kind so a hit resolves straight back to it -- see engine/doc2query.py).
    # `beliefs` covers facts/notes/episodes/procedures/references (on by default);
    # `excerpts` covers raw observed spans, off by default -- Tier-1 template
    # generation is strong for structured beliefs but only a "simple transform"
    # for free text, so the volume/quality tradeoff favors leaving it off until a
    # host model (H1/H2) can generate better excerpt questions.
    # §H2.4: `excerpts` is now FUNCTIONAL rather than inert. Its rows are keyed
    # by event_id under kind='observed'; before H2 retrieval resolved them
    # against the belief tier (_table_of_kind's "facts" default), found no row
    # and dropped every one. They now resolve through the RAW channel
    # (RetrievalEngine._observed_proxies -> retrieve_raw), where an event id
    # means something. The default stays OFF -- the flag now does what it says,
    # which is the precondition for measuring whether it is worth enabling, not
    # a reason to enable it.
    "embeddings": {"model": "auto", "dimensions": 768, "base_url": None, "api_key": None,
                   "allow_remote": False,
                   "exclude_session_prefixes": [], "max_input_tokens": 2048, "overflow": "truncate",
                   "task_prefixes": "auto",
                   "doc2query": {"beliefs": True, "excerpts": False},
                   # Seconds one embed request may take OFF the critical path:
                   # the deferred embed job and a session summary. The request
                   # timeout the live paths use is short so a turn never waits
                   # on a busy server; a background job has nobody waiting, and
                   # on a CPU-bound host a long excerpt needs more than that
                   # (measured: ~7 s for 200 words on the production VPS).
                   # Clamped to [10, 600] (engine/curation.py).
                   "background_timeout": 120},
    # A12: `bruteforce_ceiling` was declared here and read by nothing. There is
    # exactly one index backend (engine/vector_index.py brute force); a ceiling
    # past which a nonexistent ANN backend takes over is not a knob, it is a
    # claim. Deleted rather than declared dormant: it promises a second backend.
    "vector_index": {"backend": "bruteforce"},

    # §15.8 (issue #5): the declarative users/agents access topology. can_read's
    # ceiling comes from here -- per-memory read_acl narrows within it but a
    # runtime grant() can never widen past it (see engine/access.py Topology).
    #   users: explicit user roster (optional; agents' user/users also populate it)
    #   agents: [{id, user|users, reads: [principal_id,...]?, sandbox: bool?}]
    #     - no `reads` declared -> falls through to default_cross_agent_read for
    #       same-user peers; cross-user is NEVER implicit regardless
    #     - `reads` declared -> authoritative ceiling for this agent (narrows
    #       same-user default; the ONLY way to grant an explicit cross-user edge)
    #     - sandbox: true -> absolute veto on inbound reads to this agent's data,
    #       even from same-user siblings under default_cross_agent_read: allow
    "principals": {
        "default_cross_agent_read": "allow",
        "users": [],
        "agents": [],
    },

    "sources": {
        "hermes_hooks": {"enabled": True},
        "ocas_journals": {"enabled": "auto", "paths": ["~/.hermes/commons/journals/"]},
    },
    "federation": {
        "mode": "dynamic",
        "discover": ["hermes_plugins", "mcp", "skills", "config"],
        "rebind_on_change": True,
        "precedence": ["config_pin", "most_specific", "most_recent"],
        "cache_ttl": "24h",
        "pins": {},
        "provider_trust": {"default": 2},
        # Local SQLite databases this deployment declares, e.g.
        #   [{"name": "somedb", "path": "/abs/path.db", "read_only": True}]
        # Nothing about a particular database is hard-coded anywhere in engine/:
        # the name is the capability, the path is opened mode=ro, and the schema
        # is introspected. Optional per-entry "read_acl" (§15) defaults to
        # user_agents. Empty by default — a Chronicle with no declared DBs has
        # no federated channel to run (I18).
        # The federate_sweep job (§14, g4) reads the same declarations; entries
        # may additionally carry:
        #   {table, id_column, content_columns: [...], name_column?, capability?}
        # `name` is the provider id in pointers/watermarks, `content_columns` are
        # what the cached projection holds, and the optional `name_column` is the
        # only thing that can propose an identity link — for review, never applied.
        "local_dbs": [],
    },
    "outputs": {"ocas_signal_emit": {"enabled": "auto", "sink": "~/.hermes/commons/signals/"}},

    "extraction": {
        "version": "extractor-v1",
        # backend: heuristic (default — deterministic, offline, replayable) | llm.
        # llm calls an OpenAI-compatible chat endpoint per excerpt and falls back
        # to the heuristic on ANY failure, so capture never depends on a model.
        # The write path stays LLM-free unless explicitly opted in (I9, §16).
        "backend": "heuristic",
        # llm.allow_remote (A2): false by default and ENFORCED. This endpoint
        # receives the RAW EXCERPT in its prompt, so it is the most
        # memory-bearing request Chronicle can make. While the flag is false an
        # off-host base_url is refused (one WARNING) and the heuristic extractor
        # is used instead — capture is unaffected, and nothing is sent. Setting
        # it true permits the user's own transcript text to be POSTed to a third
        # party. Same host policy as embeddings.allow_remote.
        "llm": {"base_url": None, "model": None, "api_key": None, "timeout": 30,
                "allow_remote": False},
        "multi_hypothesis_threshold": 0.6,
        "signal_confidence_min": 0.7,
        "granularities": ["atomic", "entity", "session_summary"],
        "self_consistency": {"passes": 1, "vote": True},
        "promote_on_read": True,
        "reextract": {"mode": "eager", "read_budget_per_query": 2},
    },
    # Host-model piggyback (§H1). The host agent already runs an LLM; when this
    # is on, Chronicle may attach ONE compact enrichment request (≤400 chars) to
    # a turn the host is paying for anyway, and parse a fenced JSON block out of
    # the next reply. OFF by default and inert at defaults: with piggyback false
    # nothing is enqueued, nothing is attached, nothing is parsed, and the
    # heuristic write path is byte-for-byte unchanged (tests/test_host_model.py
    # proves this by diffing a full store dump against the pre-H1 tree).
    #   piggyback         — the master switch. False = every H1 path is dead code.
    #   max_pending       — queue cap; a 33rd enqueue oldest-expires. [1, 256]
    #   max_request_chars — rendered-request ceiling. Clamped to ≤400; config can
    #                       only make requests SMALLER, never bigger.
    #   max_reply_chars   — a fenced block above this is dropped unparsed.
    #
    # §H2 drains all three request kinds into real consumers. Two of them need
    # knobs of their own:
    #
    #   doc2query — a host's questions are merged with the Tier-1 templates
    #     under doc2query.MERGE_RULE ("host_first_template_fill": host questions
    #     take the leading slots, templates fill the rest of the <=4 budget) and
    #     written through the reducer's own delete-then-write proxy path. The
    #     merge rule is a code constant, not a config knob: it is a correctness
    #     contract with the volume bound, not a preference.
    #
    #   rerank_hints — a rerank reply arrives a TURN LATE and cannot reorder its
    #     own query, so it is persisted as query->evidence relevance hints and
    #     applied when a similar query recurs (RetrievalEngine._hint_scores).
    #     enabled      — read-side switch. On, but the store is empty unless
    #                    piggyback is on and a host answered, so "on" costs one
    #                    indexed lookup against an empty table.
    #     weight       — channel weight of a top-ranked hint, clamped [0, 2].
    #                    1.0 (= fts_weight + vector_weight) makes one leading
    #                    hint worth about a candidate topping BOTH channels.
    #                    0 is the off-switch. A hint can only re-weight a
    #                    candidate retrieval already found; it never adds one.
    #     similarity   — Jaccard floor on distinctive-token overlap for a hint
    #                    filed under a DIFFERENT query to apply at all; below it
    #                    the hint is ignored, at or above it the weight is
    #                    scaled by the overlap. Exact signature matches skip it.
    #     ttl_days     — hard expiry stamped on each row; the applied weight also
    #                    decays linearly to zero across that window.
    #     max_entries  — whole-table row cap, oldest-first eviction.
    #     max_per_query— how many beliefs ONE verdict may hint at.
    "host_model": {"piggyback": False, "max_pending": 32,
                   "max_request_chars": 400, "max_reply_chars": 4000,
                   "rerank_hints": {"enabled": True, "weight": 1.0, "similarity": 0.6,
                                    "ttl_days": 30, "max_entries": 200, "max_per_query": 8}},

    "derivation": {
        "enabled": True,
        "materialize": "high_value",
        "max_depth": 2,
        "max_fanout": 32,
        "confidence": {"aggregate": "min", "rule_factor": 0.9, "ceiling": 0.75},
        "default_status": {"user": "draft", "agent": "active"},
        "auto_disable_precision_below": 0.6,
    },
    "retrieval": {
        "fts_weight": 0.4, "vector_weight": 0.6, "rrf_k": 60, "overfetch": 4,
        "default_limit": 10, "max_limit": 50, "miss_threshold": 0.15,
        # A16: may a DRAFT belief reach a reader at all?
        #
        # TRUE = included and MARKED `[DRAFT]` in every render (the default,
        # and the honest one). A draft is not confirmed truth -- it is the
        # losing side of a `flag_for_review` contradiction, a high-risk
        # behaviour-changing norm parked for review, or a user-domain
        # inference derivation refuses to assert -- and before A16 all three
        # reached search()/answer()/Tier-1 context rendered as a plain
        # `[FACT]`/`[NOTE]`, indistinguishable from a confirmed one.
        #
        # Not excluded by default because three separate producers deliberately
        # write a draft RATHER THAN dropping the value: excluding would delete
        # the losing side of every flagged contradiction from the reader's view,
        # a bigger honesty problem in the other direction. FALSE is for a
        # deployment that wants only confirmed truth in front of its reader;
        # it is read at retrieval._readable, the single choke point every
        # channel and every packing path already passes through.
        "include_drafts": True,
        # Support gate for abstention (I8, §18.4). Only the threshold belonging to
        # the active gate is read. The dial (scripts/sweep_abstain.py, LongMemEval
        # _abs set): 0.78 → 21/30 abstained but 57/100 answerable REFUSED; 0.5 →
        # 3/30 abstained, 8/100 refused. No lexical signal separates "unanswerable"
        # from "answerable" (the _abs haystacks are on-topic, they just omit the
        # asked fact). Default is PERMISSIVE: in production the reading agent gets
        # a second abstention chance over get_context, so a refusal loop costs more
        # than a checkable wrong answer. Raise toward 0.78 where fabrication is
        # the greater harm.
        "abstain_gate": "focus", "score_threshold": 0.0148,
        "focus_coverage": 0.5, "overlap_min_tokens": 1,
        # Geometric abstention (E10): if set, abstain when the best candidate's
        # cosine distance exceeds this threshold (distance = 1 - similarity).
        # None (default) disables; when enabled, off-topic queries abstain with
        # reason "no sufficiently close memory".
        "abstain_distance": None,
        # A16, reconciled with upstream 7b83049. A draft is not yet verified and
        # should not back a CONFIDENT answer. This is a DIFFERENT question from
        # `include_drafts` above, which decides whether a draft is READABLE at
        # all -- collapsing the two onto one key (as the naive merge did) means
        # an operator who sets it false to keep drafts out of confident answers
        # instead deletes drafts from every read path. False: drafts still
        # render, marked `[DRAFT]`, in search()/get_context(); they just never
        # back answer()'s confident path.
        #
        # DEFAULT IS FALSE, matching upstream 7b83049. A draft is a belief the
        # writer declined to assert; letting one back answer()'s CONFIDENT path
        # returns it with `abstain: false` AND a confidence score, and the
        # `[DRAFT]` marker in the rendered text does not undo that -- the caller
        # has already been told the answer is confident. Marking is an honesty
        # measure for a reader; it is not a substitute for not claiming
        # confidence in the first place.
        #
        # An earlier revision of this merge defaulted it TRUE to avoid changing
        # v5.7.0's behaviour, on the grounds that `test_a_draft_reaches_answer_
        # marked` is a mutation-kill guard on the MARKING and an excluding
        # default makes it vacuous rather than green. That objection was real but
        # the remedy was wrong: the guard now sets this key explicitly, which is
        # what a test of marking should have done anyway, and the safer default
        # no longer costs coverage.
        #
        # Set True to let drafts back confident answers; they render `[DRAFT]`
        # either way, and `include_drafts` above still decides whether they are
        # READABLE at all.
        "confident_answer_from_drafts": False,
        # Temporal channel (§18.6): rerank raw-tier survivors when the query names
        # an absolute date/month/year. 0 disables; clamped to [0, 2] in code.
        "temporal_boost": 0.5, "graph_weight": 0.25,
        # §L9 E8: greedy-MMR trade-off for search()'s Tier-1 candidate
        # selection -- next = argmax lam*relevance - (1-lam)*max_similarity_
        # to_already_selected. 0.7 favors relevance, spending the rest on
        # diversity so near-duplicate hits stop crowding out distinct
        # evidence. Clamped to [0, 1]. No embedder / no query vector ->
        # unaffected, today's plain score-order top-N.
        "mmr_lambda": 0.7,
        "prefetch_budget": 1200,
        # The per-turn injection's relevance gate (retrieval._GATE_FILLER):
        # an item goes into the user's turn unasked only if it shares a
        # content word with the message. false = the pre-5.7.5 behaviour,
        # which fills the whole budget with the nearest items whatever they are.
        "prefetch_relevance_gate": True,
        # A scheduled job's turn (a cron_ session, or an automation platform)
        # gets no per-turn recall: nobody asked, the "message" is the job's own
        # prompt, and on the production box those turns were ~98% of all turns
        # -- up to 4,800 characters of the user's memory each, and a search
        # that ran past the host's timeout. true = recall on those turns too.
        "prefetch_automation": False,
        # A12 DELETED this key and A13 KEPT it with a dormant declaration. Both
        # for the same measured reason -- its only consumer would have been
        # provider.queue_prefetch, whose body was `pass` (A13 removed that dead
        # method). The v5.7.0 integration keeps A13's form, and the tie-break is
        # A12's own rule rather than a preference: A12's contract is that every
        # key is WIRED, DELETED or DECLARED, and "declared" satisfies it exactly
        # as "deleted" does -- `scripts/audit_config.py` still reports UNREAD =
        # 0 either way. What is NOT equal is what happens to an operator who
        # already set the key: a deleted key is read back silently and does
        # nothing, while a declared one logs once per process saying so. A12
        # refuses only two removed SECURITY keys (REFUSED_KEYS) and lets every
        # other deleted key pass in silence, so deletion here would be the
        # quieter of the two options -- and quieter is the thing A12 exists to
        # stop. Declared it is.
        "predictive_prefetch": True,
        # Embedding reranker (E3): after FTS+vector+graph fusion, the top
        # rerank_top_k candidates are re-scored by cosine(query embedding,
        # candidate embedding) blended with their fusion score --
        # blend*cosine + (1-blend)*normalized_fusion -- and re-ordered before
        # packing. The fusion term is min-max normalized to [0,1] across the
        # re-scored set FIRST: raw RRF scores live near 0.002-0.025, so an
        # un-normalized blend is a pure cosine re-sort (see
        # RetrievalEngine._rerank). A candidate with no stored vector keeps its
        # normalized fusion score, unpenalized. No query embedding (embedder
        # absent/degraded) is a complete no-op: fusion order passes through
        # exactly as before. blend=0 is also an exact no-op.
        #
        # rerank_blend: 0 IS THE OFF-SWITCH -- the only one. (A prior build
        # carried a `reranker_version` flag alongside this one, documented as
        # vestigial since no engine code read it; ladder-9 F4a removed it
        # outright rather than continue documenting a dead knob. There is no
        # "identity" mode to fall back to -- rerank_blend: 0 is the complete
        # off-switch.)
        "rerank_blend": 0.5, "rerank_top_k": 50,
        "raw_tier": {"enabled": True, "span_index": True, "session_index": True},
        "read_and_answer": {"enabled": True, "confidence_gate": 0.55,
                            "read_budget_tokens": 4000, "max_hops": 2,
                            "apply_derivation_rules": True},
        "query_understanding": {"decompose": True, "expand_synonyms": True, "hyde": True},
        # Federated query channel (§g3, federation.local_dbs). OFF by default:
        # it reads databases outside Chronicle's own store, so it is opt-in.
        "federated_channel": False,
        # E9 (§18.2): classify each query by nearest prototype centroid (a fixed
        # built-in phrase bank per question kind, embedded once per process) and
        # route get_context's evidence assembly accordingly. On by default; a
        # missing/degraded embedder always falls back to the factual/default
        # route, so this is a no-op wherever no vector channel exists.
        "query_routing": True,
        # How far a non-factual centroid must BEAT the factual one before the
        # query leaves the default route. A bare argmax over four prototype
        # centroids over-routes badly (45/60 real questions -> "aggregation",
        # costing ctx_eval@4000 3.4 points); genuine route queries win by
        # +0.22..+0.55, so 0.20 discards the ambiguous middle without touching
        # confident classifications. 0.0 restores the plain argmax.
        "query_routing_margin": 0.20,
        # PER-KIND OVERRIDE of that margin (F5). 0.20 was calibrated on the
        # built-in acceptance set, whose phrasings are near-duplicates of the
        # prototype bank itself; real questions do not clear it. Measured over
        # all 250 stratified LongMemEval questions with real nomic embeddings
        # (F3 §4a, `f3dump/routes_all.jsonl`): the shipped distribution is
        # factual 240 / aggregation 10 / preference 0 / temporal 0 -- both the
        # preference and temporal routes are dead code at 0.20.
        #
        # `preference` is nonetheless the MOST separable kind in that corpus:
        # it is the argmax on 15/15 single-session-preference questions and the
        # only type whose preference-minus-factual margin is positive for every
        # instance (min +0.025, median +0.065, max +0.138). The threshold below
        # is read off the measured sweep, not chosen by taste:
        #
        #   margin | pref route fires on | of which the 15 targets | collateral
        #     0.02 |                  38 |                   15/15 |         23
        #     0.05 |                  27 |                   12/15 |         15
        #     0.08 |                  11 |                    6/15 |          5
        #     0.20 |                   0 |                    0/15 |          0
        #
        # 0.05 covers 12 of 15 targets and BOTH instances where E12 precision
        # packing measurably misfired on a preference question (1d4e3b97 at
        # 0.0648, caf03d32 at 0.0615) at 15 collateral rather than 23. Every
        # other kind keeps `query_routing_margin`; a kind absent from this map
        # is byte-identical to before. Set {"preference": 0.20} to make F5's
        # routing change inert.
        "query_routing_margins": {"preference": 0.05},
        "query_routing_aggregation_limit": 40,
        "query_routing_aggregation_session_cap": 3,
        # (F5 removed `query_routing_preference_cap`: the E9 preference-belief
        # addendum it capped is gone. See engine/retrieval.py's note at
        # get_context's precision/pref_pack return.)
        # Answer-support verification (E11, ladder-9 issue #8): the minimum
        # cosine similarity between a host-generated answer and its best
        # matching evidence vector for RetrievalEngine.verify_answer to call
        # it `supported`. Read-only, host-LLM-mode hallucination check — never
        # consulted on the write path, so raising/lowering it changes nothing
        # about what gets stored.
        "support_threshold": 0.55,
    },
    "context": {"default_token_budget": 1500,
                "session_window": True,
                "session_window_max_sessions": 5,
                "session_window_max_events": 60,
                # L8: get_context's unconditional [DIRECTIVE] block, count-capped.
                # Was an unbounded-in-practice 20 (real stores reach ~110 active
                # norm notes); a judged reader given 12k tokens of context led by
                # ~20 directive lines abstained 30/30 even when the evidence was
                # present later in the same context (measured, L8 diagnosis).
                "max_directives": 5,
                # E12 precision packing (ladder-9 issue #8). When a query routes
                # factual AND retrieval has converged on ONE session,
                # get_context packs that session's best evidence item plus its
                # immediate neighbors into `precision_budget` tokens and stops.
                # Measured basis (stratified-250, real nomic, judged gpt-4o
                # reader): contexts that made the reader abstain at a 12k budget
                # were answered correctly when cut to ~1k of the SAME items'
                # head — abstention tracks context volume, not evidence quality.
                "precision_packing": True,
                # RESTATEMENT, not a retune -- and now restated back. The
                # measurement behind this number is a CHAR size: the probed
                # contexts that flipped a judged reader from abstain to correct
                # were 5 994-5 997 chars. A10 moved 1500 -> 2000 to hold ~6 000
                # chars at its chars/3 estimator; A10b's estimate is chars/4
                # (engine.embeddings), so the token figure that buys the SAME
                # ~6 000 chars is 1500 again:
                #     2000 tokens * 3 chars = 6000 = 1500 tokens * 4 chars
                # The measured quantity never moved; only the unit it is
                # expressed in did, twice.
                "precision_budget": 1500,
                # THE GATE. Minimum share of the top-5 raw candidates that
                # must come from ONE session ("retrieval converged there")
                # before get_context cuts to the precision budget. 0.60 = at
                # least 3 of the 5.
                #
                # Chosen from two measured distributions, not intuition:
                #   * the six LongMemEval `single-session-user` questions this
                #     feature exists for (real nomic, s_strat250): modal share
                #     of the top-5 is 1.00, 1.00, 1.00, 0.80, 0.40, 0.40 — four
                #     of the six at or above 0.60. (Their heads are near-tied,
                #     so a re-run shuffles which questions land at 0.40 vs
                #     0.60; the count at this threshold has been 4-5 across
                #     runs, never fewer.)
                #   * the 30 factual-route queries of the ctx_eval corpus
                #     (hashing): 0.80 once, 0.60 nine times, 0.40 or 0.20 for
                #     the other twenty — questions whose evidence really is
                #     spread across sessions.
                # At 0.60 (with the leader-agrees rule below) the gate fires on
                # 4 of the 6 and on 5 of the 30, and ctx_eval@1500 goes UP,
                # 75.9% -> 77.6%, with @4000 and @12000 unchanged: 165 of the
                # corpus's 180 contexts come back byte-identical to the pre-E12
                # tree and the 15 that change are the firing ones. 0.80 would
                # be tighter still but fires on only 3 of the 6 and misses the
                # case this exists for; below 0.60 the gate is firing on heads
                # that are mostly NOT one session, which is the definition of
                # the ambiguity it must refuse (at 0.60 WITHOUT the
                # leader-agrees rule it fires on 10 of the 30 and ctx_eval
                # drops to 72.4/79.3/82.8).
                "precision_concentration": 0.60,
                # SECONDARY tightening dial: extra lead ((s0 - s1) / s0) the
                # leading candidate must hold over the runner-up, on top of
                # concentration. Default 0.0 — no extra requirement — and that
                # default is itself a measurement, not laziness. On those same
                # six questions the leader's relative margin is 0.004-0.155
                # (0.010, 0.013, 0.045, 0.051, 0.150 in the run that set these
                # numbers), while the crowded ctx_eval queries run up to
                # 0.458: margin does not separate the two
                # populations in either direction. An earlier build of this
                # feature gated on margin ALONE and was either inert (0.50 —
                # fired on none of the six) or destructive (0.30 -> -1.7
                # ctx_eval points, 0.20 -> -8.6, 0.10 -> -12.1). Raise it to
                # tighten the gate on a corpus where it does separate; 1.0
                # makes the feature inert.
                "precision_margin": 0.0,
                # F5 preference packing. On the E9 `preference` route,
                # get_context packs the LEADING message of each ranked excerpt
                # (the user's own turn) across every session first, defers the
                # assistant halves, and cuts to `preference_budget` tokens.
                #
                # Measured basis (F3, stratified-250, real nomic): 73-91% of a
                # packed preference context is assistant prose, and only the
                # user's half of an excerpt can carry a preference. Across the
                # six probed gold sessions the whole of what the user said
                # about themselves is 870-1 419 chars (5-8% of the session's
                # text), so ALL of it fits where today 2 of 7-9 excerpts fit
                # whole. Re-measured after the change: the packed contexts are
                # 94-95% user text.
                "preference_packing": True,
                # 3 000 rather than the 1 500 precision packing uses, and the
                # difference is arithmetic, not taste. The F3 design proposed
                # 1 500 on the estimate that a 6 000-char budget holds "25-30
                # user heads ... across all ~10 sessions the raw fill would
                # have touched", i.e. ~2.5 heads per session. Counted on the
                # six probed haystacks the median session has 6 user turns
                # totalling 823-1 310 chars, so 6 000 chars holds 4.6-7.3
                # sessions COMPLETE, not 10 -- and the ones past the cut get a
                # header and nothing else.
                #
                # That matters more than it looks, because `retrieve_raw`'s
                # ordering of near-tied candidates is not stable run to run
                # (measured on v560 as well as here: two sequential probes of
                # the same instance put the answer session at header rank 4 and
                # then 5). At 6 000 chars that reordering decides whether the
                # answer session gets 7 of its user turns or none of them --
                # measured, both outcomes, same instance. At 12 000 it holds
                # 9.2-14.6 sessions complete, which covers the whole group list
                # the raw fill produces, so the ordering stops deciding.
                # Still a quarter of the chars a 12k-token caller would
                # otherwise get. Raise it further only with a judged reader run.
                #
                # RESTATEMENT, not a retune -- same reasoning as
                # precision_budget above, and the counting in this very comment
                # is why: every figure that set this number is a CHAR count
                # ("6 000 chars holds 4.6-7.3 sessions complete", "at 12 000 it
                # holds 9.2-14.6", which is the regime where retrieve_raw's
                # unstable tie order stops deciding what the reader sees).
                # 12 000 chars is 4000 tokens at A10's chars/3 and 3000 at
                # A10b's chars/4:
                #     4000 tokens * 3 chars = 12000 = 3000 tokens * 4 chars
                # The feature still packs the same 12 000 chars it was measured
                # at; leaving it at 4000 would hand it 16 000 instead.
                "preference_budget": 3000,
                # -- A18 BREADTH FLOOR --------------------------------
                # A per-session CHAR ceiling on the raw-evidence fill, applied
                # only on the routes whose answer is spread across sessions.
                #
                # Measured on the 58-instance ctx_eval corpus (hashing
                # embedder, `scripts/ctx_eval_probe.py`), per budget tier, as
                # "what share of the raw-evidence fill does the LARGEST single
                # session claim" and "how many distinct sessions arrive":
                #
                #   budget | aggregation route      | multi-gold instances
                #   -------+------------------------+----------------------
                #    1 500 | 1.6 sessions, top 99%  | 1.6 sessions, top 100%
                #    4 000 | 4.0 sessions, top 56%  | 3.6 sessions, top  58%
                #   12 000 | 12.2 sessions, top 19% | 11.4 sessions, top  19%
                #
                # At 1 500 tokens the fill is ONE session in 13 of 28
                # aggregation-route instances and the median session claims
                # ~100% of it, while the budget is 100% saturated -- 13 of 33
                # multi-gold instances carry no gold session at all, 12 of
                # those with <=2 sessions emitted. At 12 000 the effect is
                # gone. So this is a TIGHT-BUDGET property of the packer, not
                # a constant one, and the ceiling is sized as a share of the
                # budget rather than a fixed number of chars.
                #
                # THE MECHANISM: group i of the first N may claim
                # `remaining // (N - i)` chars of the ranked-excerpt fill --
                # the first session a third of it, the second half of what is
                # then left, the Nth and everything after it all of it. A
                # session that reaches its share yields to the next instead of
                # spending the rest of the budget, and a session that takes
                # LESS than its share hands the surplus to the next divisor,
                # so nothing is reserved and then wasted: measured over the
                # corpus, mean chars emitted / char ceiling is 99.9% / 97.6% /
                # 94.6% with the floor on, the same three figures as without
                # it. It rations the ranked fill only; the session-window
                # expansion that follows is depth bought with what breadth did
                # not need, and rationing that too measurably left budget
                # unspent (see engine/retrieval.py).
                #
                # SCOPE. Factual questions are answered by ONE session and
                # E12 precision packing depends on concentrating there, so the
                # factual route is excluded BY CONSTRUCTION and its output is
                # byte-identical (asserted over the whole corpus by
                # tests/test_breadth_floor.py). The preference route runs
                # `_pref_pack_fill`, which already weighs every group against
                # every other before emitting anything, so it is excluded too.
                # Set to False to restore the pre-A18 fill exactly.
                "breadth_floor": True,
                # N: the number of distinct sessions the fill reserves room
                # for. Measured, not chosen -- swept over the whole ctx_eval
                # corpus at all three tiers (scripts/ctx_eval_probe.py with
                # A18_FLOOR=n; full table in MEASUREMENTS.md):
                #
                #   N   | @1500 | @4000 | @12000 | sessions | largest-of-fill
                #   off | 44/58 | 49/58 |  52/58 |     1.62 |  99%
                #    2  | 44/58 | 49/58 |  52/58 |     2.52 |  52%
                #    3  | 44/58 | 49/58 |  52/58 |     3.69 |  35%
                #    4  | 45/58 | 49/58 |  52/58 |     4.86 |  26%
                #    5  | 45/58 | 50/58 |  52/58 |     5.55 |  23%   <- shipped
                #    6  | 45/58 | 49/58 |  52/58 |     6.66 |  20%
                #    8  | 46/58 | 48/58 |  52/58 |     8.62 |  16%
                #
                # (sessions / largest-of-fill measured at 1 500 on the routes
                # the floor covers.) 5 is the largest N that costs nothing:
                # it is the only value that improves BOTH tight tiers, and 8 --
                # which buys one more @1500 hit -- pays for it at @4000, where
                # rationing a budget that already held four or five sessions
                # only shortens each of them. N is clamped to the number of
                # groups that actually have something to emit, so a query that
                # grouped into fewer sessions than N is unaffected, and N=1 is
                # arithmetically the pre-A18 fill (`remaining // 1`).
                "breadth_floor_sessions": 5,
                # The routes that get it. E9's aggregation route counts
                # occurrences ACROSS sessions and its temporal route orders
                # events across them; both are breadth-shaped by definition,
                # and the aggregation route already caps per-session excerpts
                # (`query_routing_aggregation_session_cap`) for exactly this
                # reason -- a cap in ITEMS, which a 4 000-char excerpt walks
                # straight through. "factual" and "preference" here would be
                # honoured, but see SCOPE above before adding them.
                #
                # HONEST ABOUT THE EVIDENCE: `aggregation` is measured (28 of
                # the 58 corpus instances route there under the offline hashing
                # embedder). `temporal` is NOT -- exactly one instance routes
                # temporal on this corpus, so it rides on the E9 semantics
                # ("order these events", which needs both sessions by
                # definition) and on that single instance not regressing, not
                # on a distribution. Drop it from this list if you want only
                # what the corpus can support.
                "breadth_floor_routes": ["aggregation", "temporal"],
                # (A12 deleted `context.weights`: nothing read it, and the weight
                # set the context engine actually uses is `context_engine.
                # keep_weights`, which has different names AND different values.
                # Two weight tables, one of them fictional, is worse than one.
                # A18 was built before that landed and still carried the key
                # here; it is dropped rather than re-added, and
                # tests/test_config_honesty.py::TestDeletedKeys asserts it
                # stays gone.)
                },
    "capture": {"max_excerpt_chars": 4000,          # per-chunk cap, clamped [500, 16000] (§12.1)
                "sync_turn": {"mode": "observe_only"},
                "precompress": {"budget_ms": 400},
                # Declared here because provider.py READS both (issue #7.1
                # automatic reference capture) with an inline default, and an
                # operator-facing knob the engine reads but DEFAULTS does not
                # declare is invisible to audit_config.py, to the dashboard and
                # to anyone reading this file — the same defect the duplicate
                # "health" key caused. Values must equal provider.py's
                # _DEFAULT_RETRIEVAL_TOOLS / _DEFAULT_REFERENCE_TTL_DAYS; a test
                # in tests/test_config_honesty.py pins them so they cannot drift
                # (config.py cannot import provider.py — circular).
                "tool_reference": {"allowlist": ["web_fetch", "webfetch", "fetch",
                                                 "web_search", "websearch",
                                                 "file_read", "read_file", "readfile",
                                                 "read"],
                                   "ttl_days": 30},
                "agent_memory_write": {"salience": "high", "confidence_discount": 0}},
    "reaper": {"enabled": True, "schedule": "*/5 * * * *", "idle_threshold": "20m",
               "reap_threshold": "45m", "startup_recovery": True},
    "confidence": {"base": CONFIDENCE_BASE, "trust_ceiling": TRUST_CEILING},
    # A12: `refit_every` deleted -- the calibrator refits on every read from the
    # live observation table (trust.Calibrator.calibrate); there is no periodic
    # refit job for a cadence to configure.
    "calibration": {"min_obs": 50},
    "forgetting": {"confirm_critical": True,
                   # Belief decay cadence (§20, §17.4). DAILY on purpose, not
                   # hourly: decay_sweep takes ONE rung off the fidelity ladder
                   # (verbatim -> gist -> parametric_only -> tombstone) per run
                   # for every eligible belief, so the sweep interval, not the
                   # domain's decay_days, is what sets how fast an already-old
                   # belief reaches the bottom. Empty string disables it.
                   "decay_schedule": "0 3 * * *",
                   "raw_retention": {"keep_verbatim_days": 365, "then": "gist"}},
    "salience": {"decay_multipliers": {"pinned": 0, "high": 0.25, "normal": 1.0, "incidental": 4.0}},
    "representation": {"canonicalize": {"enabled": True, "similarity_threshold": 0.8,
                                        "auto_apply_domain": ["agent"]}},
    "behavior_change": {"risk_tier_default": "low", "high_risk_requires_review": True},
    "epistemic": {"redundant_window": "48h", "forgot_window": "30d"},
    "domains": {
        "user": {"auto_decay": False, "contradiction_policy": "flag_for_review"},
        "agent": {"auto_decay": True, "decay_days": 90, "contradiction_policy": "newer_wins"},
        "general": {"auto_decay": True, "decay_days": 30, "contradiction_policy": "refetch"},
    },
    "curation": {"mode": "event_driven", "sweep_schedule": "0 * * * *",
                 "identity_threshold": 0.85, "consolidate_min_facts": 50,
                 # How many nearest same-kind neighbours the novelty scan looks
                 # at. Declared for the same reason as capture.tool_reference
                 # above: engine/reducer.py reads it with an inline default, so
                 # without this line it is a knob nothing can enumerate. Must
                 # equal reducer.NOVELTY_TOP_K; pinned by a test.
                 "novelty_top_k": 25,
                 # `dup_similarity` (the E5 merge's 0.95 cosine floor) was deleted,
                 # not declared dormant: the merge is now an exact-content match
                 # (reducer._exact_duplicate) that reads no threshold. Cosine
                 # cannot tell an update from a paraphrase -- "9am" -> "10am"
                 # scored 0.9945 on production nomic, above a true paraphrase --
                 # so a floor on it promised a safety it could not deliver.
                 # Ladder 9 E4 (§issue-8): cosine floor for "this write looks like
                 # an update of that belief" (nearest same-subject neighbor, or the
                 # global-store neighbor when no same-subject candidate exists).
                 # High on purpose -- a false positive links two unrelated facts
                 # into a misleading "history"; missing a real update only means a
                 # reader sees two separate facts instead of a dated chain, which
                 # is exactly today's behavior. An exact re-assertion is absorbed
                 # by the E5 merge before E4 ever sees it; anything less than
                 # identical, however close, stays a row this floor can link.
                 "supersede_similarity": 0.82,
                 # §E6: neighbor-cosine floor between consecutive observed-event
                 # embeddings within one session. Absolute, not a rolling
                 # baseline -- the simplest rule that is still correct, and it
                 # mirrors identity.split_below's fixed-floor shape rather than
                 # tracking a moving average that a slow topic drift could ride
                 # under. Below this, session_summarize opens a new episode.
                 # Hashing-mode vectors for genuinely unrelated excerpts land
                 # near-orthogonal (~0.0-0.15 cosine, no shared vocabulary);
                 # same-topic paraphrases share tokens and sit well above it.
                 # 0.35 is a conservative middle that a real sentence embedder
                 # (nomic et al.) also respects -- unrelated topics score below
                 # it, ordinary within-topic variation does not.
                 "topic_shift_threshold": 0.35,

                 # -- fair drain (§A7) -------------------------------------
                 # `drain.per_turn` is the whole per-turn job budget (was a
                 # hard-coded 16 in core.tick()). The three `share_*` keys
                 # split it across the task CLASSES in engine/store.TASK_CLASS:
                 #   write_path  — a new turn becoming memory (extract, route,
                 #                 canonicalize, digest, session_summarize, ...)
                 #   embed       — deferred vector writes (§24.4)
                 #   maintenance — sweeps and periodic repair; also the class a
                 #                 scheduler (A3) enqueues into
                 # Shares are relative weights, not percentages: they are
                 # normalised, so {2,1,1} and {0.5,0.25,0.25} are the same
                 # config. The split IS the declared share wherever whole jobs
                 # allow it (0.5/0.3/0.2 over 16 = 8/5/3); a positive share too
                 # small to round up to one job is lent exactly one job from
                 # the largest class rather than being rounded away, so a class
                 # with pending work is served EVERY turn.
                 #
                 # That floor is the anti-starvation guarantee, and it is the
                 # whole point: pre-A7 the claim was strict FIFO by id, so one
                 # heal run's 105k embed jobs sat in front of every later
                 # extract and the write path simply stopped. Leftover budget
                 # is never thrown away — a class with nothing pending hands
                 # its unused quota back and the drain spends it elsewhere, so
                 # fairness costs no throughput on an uncontended queue.
                 "drain": {"per_turn": 16,
                           "share_write_path": 0.5,
                           "share_embed": 0.3,
                           "share_maintenance": 0.2,
                           # Run the per-turn slice on ONE background thread
                           # per core instead of inside the turn. Hermes calls
                           # on_turn_start synchronously before the model, and
                           # an embed job on a busy server could hold a user's
                           # turn for the whole request timeout. Applies when a
                           # host drives the core (provider / context engine);
                           # a core used directly drains where it is called.
                           "background": True},

                 # -- job leases (§A7) -------------------------------------
                 # A claimed job is marked 'running' with a started_at stamp.
                 # If its worker dies (OOM, a gateway restart killing in-flight
                 # cron work, a plain crash) nothing ever moves the row back:
                 # pre-A7 it stayed 'running' forever, invisible to every
                 # future claim — the live store had 245 extract rows in
                 # exactly that state. `lease_seconds` is how long a running
                 # job may go unfinished before health treats it as abandoned
                 # and re-arms it. Set it comfortably above the slowest real
                 # job (a big extract against a slow local model), because a
                 # lease shorter than the work duplicates it.
                 "lease_seconds": 900,
                 # Claims one job may burn before it is failed with a stated
                 # reason instead of being retried forever. THE RESET RULE:
                 # attempts go back to 0 when the SAME unit of work is
                 # re-enqueued (enqueue_curation / enqueue_embed_job both
                 # re-arm an identical done/failed row) — an exhausted counter
                 # is a statement about one attempt streak, never a permanent
                 # tombstone (ladder-6).
                 "max_attempts": 20,
                 # Rows one lease sweep may reclaim, so recovery is bounded
                 # work like every other repair pass.
                 "reclaim_batch": 200,

                 # -- queue retention (§A7) --------------------------------
                 # curation_jobs was unbounded: done/failed rows were never
                 # deleted, so every enqueue's dedupe probe and every claim's
                 # dependency sub-select paid for the whole history of the
                 # store forever. Terminal rows only — pending/running work is
                 # never pruned, and neither is a done row a pending job still
                 # depends on (pruning that would make the dependent job
                 # unclaimable, i.e. re-create the stuck-forever state this
                 # whole task removes). Both bounds apply: age catches a quiet
                 # store, the row cap catches a busy one that outruns the age
                 # bound. `enabled: False` turns the prune off and accepts
                 # unbounded growth.
                 "retention": {"enabled": True, "done_days": 7,
                               "max_rows": 20000, "batch": 5000}},

    # Identity evidence (§E7, issue #8). Similarity produces CANDIDATES only —
    # nothing here ever merges or splits an entity; identity is adjudicated,
    # never inferred. split_below: a new mention whose cosine to its entity's
    # running centroid falls below this is queued as a possible split (one id
    # carrying two subjects). merge_above: two entity centroids above this are
    # queued as a possible merge (two ids carrying one subject).
    # merge_scan_limit BOUNDS the pairwise check — the entity just written is
    # compared against at most this many most-recently-updated centroids (the
    # working set), never against every entity in the store. Inert without an
    # embedder: no vector reaches the check, so no state and no candidates.
    # `schedule` (ladder-10 A8) drives the OTHER producer of the same queue: the
    # `identity` curation sweep, which proposes a merge candidate for every
    # exact (normalized_name, owner, domain) collision. It used to MERGE those
    # entities outright, which is why it had no cadence until A8. Daily; empty
    # string disables it. `enabled: false` disables BOTH producers.
    "identity": {"enabled": True, "split_below": 0.30, "merge_above": 0.90,
                 "merge_scan_limit": 50, "schedule": "0 5 * * *"},
    "consolidation": {"enable_parametric": False},

    # -- sweeps (§A9) ---------------------------------------------------------
    # Every periodic sweep used to carry a literal `limit=5000` with no ORDER BY
    # and no cursor, so past 5000 matching rows it read the same prefix on every
    # run, never reached the rest, and returned success. The bound stays — an
    # unbounded sweep on a 2-core box is the hazard the A7 drain exists to
    # prevent — but it is now a stated pace with a persisted cursor behind it
    # and a processed/remaining/bounded report in front of it.
    #
    #   row_budget  — rows (or groups) one run of a sweep may process. The
    #                 SHARED pace: every sweep without an entry under budgets.*
    #                 takes this number, so raising this one value speeds up
    #                 `decay`, `ghost_facts` and `identity` together.
    #   page_rows   — SQL page size for the folds that must be COMPLETE
    #                 (reducer._on_forbidden, _beliefs_matching_hash). A memory
    #                 bound, not a work bound: the loop still runs to exhaustion.
    #   budgets.*   — per-sweep override, read as sweeps.budgets.<name>. ANY
    #                 sweep name is accepted here — including the three that
    #                 ship without an entry (decay, ghost_facts, identity) —
    #                 but only the ones whose pace deliberately DIFFERS from
    #                 row_budget are declared, so this table stays a list of
    #                 decisions rather than a restatement of the default. Those
    #                 differences: group-shaped sweeps (consistency,
    #                 canonicalize) do one extra query per group, so their unit
    #                 of work is dearer than a decay row's; derive_subjects and
    #                 backfill keep the fanout/batch pace their call sites
    #                 already documented; reextract's page becomes a queue of
    #                 extract jobs, and 200 is what that queue was sized for;
    #                 ghost_facts is a list a human reads, and 200 is what it
    #                 always displayed — the difference is that 200 is now also
    #                 what it SCANS, so the report is the scan rather than a
    #                 second, hidden truncation of a 5000-row prefix.
    "sweeps": {"row_budget": 5000,
               "page_rows": 1000,
               "budgets": {"ghost_facts": 200,
                           "consistency": 2000,
                           "canonicalize": 2000,
                           "derive_subjects": 500,
                           "backfill": 200,
                           "reextract": 200}},
    # self_heal.embedder_mismatch_max (A0b): how many vectors ONE health run may
    # requeue for re-embedding. Bounds the expensive action only -- re-tagging a
    # same-model-different-name row is a metadata UPDATE and is never bounded by
    # it. Throughput at the default: 500 rows/run on the default daily schedule,
    # so a corpus with 170k wrongly-embedded vectors converges through the heal
    # in ~340 days. A wholesale model change is a MIGRATION, not a heal: run
    # scripts/migrate_vectors.py, which does the whole corpus in one resumable
    # pass. Raise this to trade box load for convergence time.
    #
    # THE ONE "health" LITERAL. Until the v5.7.0 pre-ship review this key was
    # defined TWICE in this dict -- once here (A7 + A0b) and once ~70 lines below
    # (A3) -- and Python keeps the last, so A7's `census_total_max_age_hours` and
    # A0b's `self_heal.embedder_mismatch_max` were silently deleted from
    # DEFAULTS. Nothing broke at runtime only because both readers happen to pass
    # an inline default that matches (health.py's `cfg.get(..., 500)` and
    # `cfg.get(..., 24)`), but the keys vanished from the config surface an
    # operator and the dashboard enumerate, and audit_config.py's "UNREAD 0 of
    # 228" headline was computed over a DEFAULTS missing two keys the engine
    # reads. Had the two blocks appeared in the other order the casualty would
    # have been A3's `consistency_sweep.schedule` and the hourly sweep would have
    # silently lost its cadence. Merged here, keeping all three.
    # `tests/test_config_honesty.py` now asserts both directions and the lint
    # gate runs ruff's F601; either alone would have caught it.
    #
    # INTEGRATOR NOTE (ladder-10 A3 / A0 / A7 ordering): `health.schedule` is
    # live, and health.run() calls the embedder-mismatch heal. On a store whose
    # vectors carry a stale model tag that heal is unbounded — it scans every
    # vector row and enqueues one embed job per mismatch (the 105k-job case in
    # A0/A7) — and a DegradedEmbedder reports the literal model "degraded", which
    # makes EVERY row look mismatched while the backend is down. A3 gives the
    # heal a cadence; A0 gives it a canonical tag and A7 bounds and prioritises
    # the queue. If A3 lands before those, set `health.schedule: ""` until they
    # do — the schedule is disabled by an empty string, by design, and every
    # other maintenance schedule keeps running.
    "health": {"schedule": "0 4 * * *",
               "ghost_fact": {"confidence_min": 0.8, "age_days": 14},
               # A3: the hourly cadence of the consistency sweep.
               "consistency_sweep": {"enabled": True, "schedule": "0 * * * *"},
               # §A7: how long the heal may reuse a CACHED count of the vector
               # tables as the denominator in "N of M vectors are off-model".
               # The mismatch numerator is always live and exact; only the
               # total is cached, and it is force-recounted the moment a run
               # finds anything mismatched. This exists because an exact
               # COUNT(*) is the one part of the census that cannot be a seek:
               # cold, it was measured at ~300ms for a 100k-row store, on every
               # health run, on a store with nothing wrong with it. 0 disables
               # the cache (count every run).
               "census_total_max_age_hours": 24,
               "self_heal": {"tier1_auto": True, "embedder_mismatch_max": 500}},
    # -- maintenance cadence (§17.4, ladder-10 A3) -------------------------
    #
    # The `*.schedule` keys below USED to be fiction: they held cron strings
    # that no code read, describing a cron job nobody installed. Nothing in the
    # plugin enqueued `health`, `decay` or `consistency`, and `Reaper.run()` had
    # no caller, so a store maintained itself only if something outside the tree
    # remembered to call in. engine/scheduler.py is the cadence now — in-process,
    # hook-driven, no thread and no daemon — and every key here is read.
    #
    # CRON SUBSET (parsed by engine/scheduler.py with the stdlib alone):
    #     minute hour day-of-month month day-of-week
    #     *   */N   A   A-B   A-B/N   and comma-separated lists of those.
    #     day-of-week 0-6, Sunday=0 (7 also accepted as Sunday).
    #     NOT supported: names (JAN/MON), @daily nicknames, seconds, L/W/#/?.
    #     Both day-of-month and day-of-week restricted => a day matches if
    #     EITHER matches (standard cron).
    #     Times are UTC — every timestamp Chronicle stores is UTC, so
    #     "0 4 * * *" is 04:00 UTC, not 04:00 local.
    #     An EMPTY string disables that schedule entirely. An INVALID string
    #     also disables it, with one warning: a typo fails closed rather than
    #     quietly running at some other cadence.
    #
    # WHAT IS SCHEDULED (config key -> curation task):
    #     reaper.schedule                    -> decay {"sweep":"reaper"}
    #     forgetting.decay_schedule          -> decay {"sweep":"beliefs"}
    #     health.consistency_sweep.schedule  -> consistency
    #     health.schedule                    -> health
    #     curation.sweep_schedule            -> backfill_sweep
    #     identity.schedule                  -> identity          (ladder-10 A8)
    #
    # WHAT IS DELIBERATELY NOT SCHEDULED (the full list, with reasons, lives in
    # engine/scheduler.py's UNSCHEDULED dict and is surfaced at runtime by
    # core.maintenance_status()["unscheduled"]). The short version:
    #     derive/consolidate — mint new beliefs; that is capture, not
    #                    maintenance, and their config keys are still unread.
    #     reextract    — materialises the whole observed event table first.
    # `contradiction` (an alias of `consistency`) and `route`/`criticality` (no
    # handler in any build) are no longer on that list because they are no longer
    # task values at all: A13 removed them from the curation_jobs CHECK
    # (schema_version 13). A name the schema admits that nothing can run is a
    # schema defect, not a scheduling decision.
    "maintenance": {
        # Master switch: false means no hook call ever enqueues maintenance.
        "enabled": True,
        # Wall-clock ceiling for the DECISION taken on one hook call (not for
        # the work, which the curation worker does later inside its existing
        # bounded drain). The scan resumes where it stopped on the next call,
        # so a budget this small cannot starve an entry.
        "budget_ms": 5,
    },
    # (A3's "health" block used to sit HERE, shadowing the one above. Merged into
    # it; see THE ONE "health" LITERAL there. Do not re-add a second one.)
    "learning": {"max_active_deltas": 8, "max_delta_magnitude": 0.15,
                 "mutable_dimensions": ["rrf_weights", "context_weights", "decay_multipliers",
                                        "reranker", "calibration", "read_confidence_gate",
                                        "derivation_rule_enable"]},
    "consent": {"default_scope": ["*"], "enforce_purpose": True},
    # `encryption_key` declared because engine/gitmirror.py READS it
    # (`cfg.get("git.encryption_key")`) -- an undeclared read is the same defect
    # as an unread declaration, just pointing the other way: the config surface
    # would not promise a key the code consults. None means "no client-side
    # payload encryption"; CHRONICLE_GIT_ENCRYPTION_KEY takes precedence over it,
    # and remains the right place to put an actual secret.
    "git": {"enabled": True, "max_commit_rows": 1000, "max_lag_minutes": 30,
            "snapshot_interval": "0 * * * *", "encryption_key": None},

    # Context-engine slot (§27 context:)
    "context_engine": {
        "engine": "chronicle",
        # A12: `redundancy_vs_store` deleted -- _score_message has four
        # dimensions (relevance/recency/salience/criticality) and no redundancy
        # term; the fifth weight was scored by nothing.
        "keep_weights": {"relevance": 0.35, "recency": 0.20, "salience": 0.20,
                         "criticality": 0.20},
        "never_evict": "directives",
        "should_compress": {"on_memory_pressure": True, "on_focus_shift": True},
        # Two-watermark hysteresis (§R2): HIGH is when should_compress() decides
        # a pass is due (fraction of the model's context window); LOW is the
        # target fraction compress() evicts DOWN TO. Using two different points
        # instead of one is the hysteresis -- a single cutoff either re-triggers
        # a pass on every call sitting right at the edge, or (the previous bug)
        # doesn't bound the compressed size at all. Both are fractions of
        # context_length, so the actual token count scales with whatever model
        # is configured instead of a number picked for no particular window.
        "high_watermark_percent": 0.75,
        "low_watermark_percent": 0.55,
        "reinject": {"enabled": True},
        "standalone_fallback": "heuristic",
        # §R7: cap (tokens) on the rolling, no-model checkpoint digest of
        # everything compression has folded out this session; oldest lines
        # drop first once a refresh would push it over this.
        "checkpoint_digest_max_tokens": 300,
        # Proactive tool-output trim — the host's prune_tool_results_only hook.
        # Hermes calls it on a LOWER trigger than full compaction; its built-in
        # compressor implements it and a plugin engine inherits a no-op, so
        # without this, switching to Chronicle silently stopped trimming old
        # tool output. Deterministic, no model, no embedder. `at_percent` of the
        # window starts it; `min_reclaim_tokens` is what a trim must save to be
        # worth breaking the provider's prompt cache; old results over
        # `min_chars` keep their first `keep_head_chars` and last
        # `keep_tail_chars`.
        "prune_tool_results": {"enabled": True, "at_percent": 0.5, "min_chars": 2000,
                               "keep_head_chars": 500, "keep_tail_chars": 300,
                               "min_reclaim_tokens": 1500},
    },
}


def check_abstain_gate(name: str) -> str:
    """Reject an unknown retrieval.abstain_gate loudly (§18.4).

    A typo here would silently disable abstention, which is the one failure the
    gate exists to prevent — so it is a hard error, not a fallback.
    """
    if name not in ABSTAIN_GATES:
        raise ValueError("retrieval.abstain_gate must be one of {} (got {!r})".format(", ".join(ABSTAIN_GATES), name))
    return name


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    """Thin dotted-path accessor over a merged config dict."""

    def __init__(self, overrides: dict[str, Any] | None = None):
        check_refused_keys(overrides or {})
        self._d = _deep_merge(DEFAULTS, overrides or {})
        # What the CALLER actually said, kept apart from what DEFAULTS supplies.
        # See `explicit()` for why the difference is load-bearing (A0g).
        self._explicit = copy.deepcopy(overrides) if overrides else {}
        env_model = (os.environ.get(EMBED_MODEL_ENV) or "").strip()
        if env_model:
            if not isinstance(self._d.get("embeddings"), dict):
                self._d["embeddings"] = {}
            self._d["embeddings"]["model"] = env_model
            # An environment override is an operator statement too.
            self._explicit.setdefault("embeddings", {})
            if isinstance(self._explicit["embeddings"], dict):
                self._explicit["embeddings"]["model"] = env_model
        check_abstain_gate(self._d["retrieval"].get("abstain_gate"))
        self._check_dormant_flags()

    def _check_dormant_flags(self):
        """Warn once per process for each DORMANT flag that is currently live.

        `is_enabled` decides liveness directly from the value, not from a diff
        against some remembered default — that was the sonnet-1 bug: comparing
        against a stored default_val of True made `hyde=False` trip `!= True`
        and warn "is enabled" anyway (§u1 review triage).
        """
        log = logging.getLogger("chronicle.config")
        for path, is_enabled, reason in DORMANT:
            if path in _DORMANT_WARNED:
                continue
            if is_enabled(self.get(path)):
                log.warning("dormant config flag %s is enabled: %s", path, reason)
                _DORMANT_WARNED.add(path)

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self._d
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def explicit(self, path: str, default: Any = None) -> Any:
        """The value at `path` only if the CALLER supplied it; `default` otherwise.

        `get` answers "what is the effective value", and that is never absent --
        every leaf exists in DEFAULTS. A few decisions need the other question,
        "did the operator STATE this?", because a default and a declaration do not
        mean the same thing. `embeddings.dimensions` is the case this exists for
        (A0g width guard): the default 768 is a recommendation that must not make
        a 1024-dim model look misconfigured, while a DECLARED 768 is an
        expectation that a probe answering 384 contradicts -- and contradicting it
        is how a misreporting endpoint would come to re-geometry a whole store.
        Reads nothing from DEFAULTS, so an unmentioned key is absent here even
        when it has one."""
        cur: Any = self._explicit
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    @property
    def raw(self) -> dict[str, Any]:
        return self._d
