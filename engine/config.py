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
    ("retrieval.reranker_version", lambda v: v != "identity",
     "Reranker version string — only 'identity' passthrough exists"),
]

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
    "provider": "chronicle",
    "store": "sqlite",
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
    # on 1-2 vCPU self-hosted boxes). No remote-API tier: memory excerpts never
    # leave the host. Hosts too weak for nomic run DEGRADED (FTS + queued embeds).
    # Set model: hashing to force the offline embedder (eval/CI only), or a
    # specific id to pin one. $CHRONICLE_EMBED_MODEL overrides this value.
    # max_input_tokens: the model's real context window, in tokens; clamped
    # [256, 32768]. overflow: "truncate" (default, boundary-aware first slice)
    # | "chunk_mean" (split into cap-sized chunks, embed each, L2-normalize and
    # mean, then re-normalize). Both exist so an oversized excerpt is clamped
    # BEFORE it ever reaches the model — never sent over-cap, never raises for
    # length (§27; the nemotron->nomic 2048-token overflow incident).
    "embeddings": {"model": "auto", "dimensions": 768, "base_url": None, "api_key": None,
                   "exclude_session_prefixes": [], "max_input_tokens": 2048, "overflow": "truncate"},
    "vector_index": {"backend": "bruteforce", "bruteforce_ceiling": 100000},

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
        "deployment": "shared_core",          # shared_core | per_agent_isolated
        "default_cross_agent_read": "allow",
        "users": [],
        "agents": [],
        "encryption": {"restricted_partition_keys": True},
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
        "llm": {"base_url": None, "model": None, "api_key": None, "timeout": 30},
        "multi_hypothesis_threshold": 0.6,
        "signal_confidence_min": 0.7,
        "granularities": ["atomic", "entity", "session_summary"],
        "self_consistency": {"passes": 1, "vote": True},
        "promote_on_read": True,
        "reextract": {"mode": "eager", "read_budget_per_query": 2},
    },
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
        # Temporal channel (§18.6): rerank raw-tier survivors when the query names
        # an absolute date/month/year. 0 disables; clamped to [0, 2] in code.
        "temporal_boost": 0.5, "graph_weight": 0.25,
        "reranker_version": "identity", "prefetch_budget": 1200,
        "predictive_prefetch": True,
        "raw_tier": {"enabled": True, "span_index": True, "session_index": True},
        "read_and_answer": {"enabled": True, "confidence_gate": 0.55,
                            "read_budget_tokens": 4000, "max_hops": 2,
                            "apply_derivation_rules": True},
        "query_understanding": {"decompose": True, "expand_synonyms": True, "hyde": True},
        # Federated query channel (§g3, federation.local_dbs). OFF by default:
        # it reads databases outside Chronicle's own store, so it is opt-in.
        "federated_channel": False,
    },
    "context": {"default_token_budget": 1500,
                "session_window": True,
                "session_window_max_sessions": 5,
                "session_window_max_events": 60,
                "weights": {"relevance": 0.4, "recency": 0.25, "salience": 0.25, "pinned": 0.1}},
    "capture": {"max_excerpt_chars": 4000,          # per-chunk cap, clamped [500, 16000] (§12.1)
                "sync_turn": {"mode": "observe_only"},
                "precompress": {"budget_ms": 400},
                "agent_memory_write": {"salience": "high", "confidence_discount": 0}},
    "reaper": {"enabled": True, "schedule": "*/5 * * * *", "idle_threshold": "20m",
               "reap_threshold": "45m", "startup_recovery": True},
    "confidence": {"base": CONFIDENCE_BASE, "trust_ceiling": TRUST_CEILING},
    "calibration": {"min_obs": 50, "refit_every": 100},
    "forgetting": {"confirm_critical": True,
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
                 "identity_threshold": 0.85, "consolidate_min_facts": 50},
    "consolidation": {"enable_parametric": False},
    "health": {"schedule": "0 4 * * *",
               "ghost_fact": {"confidence_min": 0.8, "age_days": 14},
               "consistency_sweep": {"enabled": True}, "self_heal": {"tier1_auto": True}},
    "learning": {"max_active_deltas": 8, "max_delta_magnitude": 0.15,
                 "mutable_dimensions": ["rrf_weights", "context_weights", "decay_multipliers",
                                        "reranker", "calibration", "read_confidence_gate",
                                        "derivation_rule_enable"]},
    "consent": {"default_scope": ["*"], "enforce_purpose": True},
    "security": {"encrypt_at_rest": True},
    "git": {"enabled": True, "max_commit_rows": 1000, "max_lag_minutes": 30,
            "snapshot_interval": "0 * * * *"},
    "tier_triggers": {"write_lock_contention": 0.20, "vector_count": 5000000, "sqlite_max_gb": 20},

    # Context-engine slot (§27 context:)
    "context_engine": {
        "engine": "chronicle",
        "keep_weights": {"relevance": 0.35, "recency": 0.20, "salience": 0.20,
                         "criticality": 0.20, "redundancy_vs_store": 0.30},
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
        self._d = _deep_merge(DEFAULTS, overrides or {})
        env_model = (os.environ.get(EMBED_MODEL_ENV) or "").strip()
        if env_model:
            if not isinstance(self._d.get("embeddings"), dict):
                self._d["embeddings"] = {}
            self._d["embeddings"]["model"] = env_model
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

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    @property
    def raw(self) -> dict[str, Any]:
        return self._d
