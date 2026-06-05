"""
Chronicle — Configuration reference (§27).

Defaults that mirror the build spec's YAML. ChronicleCore reads a flat config
dict (typically loaded from ~/.hermes/config.yaml under `memory:`) merged over
these defaults. Nothing here touches the network; every value has a safe local
default so the system is fully functional on Hermes hooks alone (I18).
"""

from __future__ import annotations

import copy
from typing import Any, Dict

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

DEFAULTS: Dict[str, Any] = {
    "provider": "chronicle",
    "store": "sqlite",
    "db_path": "~/.hermes/commons/db/chronicle/chronicle.db",
    "git_repo": "~/.hermes/commons/db/chronicle/git",
    "git_remote": None,
    "embeddings": {"model": "embeddinggemma-300m", "dimensions": 768},
    "vector_index": {"backend": "bruteforce", "bruteforce_ceiling": 100000},

    "principals": {
        "deployment": "shared_core",          # shared_core | per_agent_isolated
        "default_cross_agent_read": "allow",
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
    },
    "outputs": {"ocas_signal_emit": {"enabled": "auto", "sink": "~/.hermes/commons/signals/"}},

    "extraction": {
        "version": "extractor-v1",
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
        "reranker_version": "identity", "prefetch_budget": 1200,
        "predictive_prefetch": True,
        "raw_tier": {"enabled": True, "span_index": True, "session_index": True},
        "read_and_answer": {"enabled": True, "confidence_gate": 0.55,
                            "read_budget_tokens": 4000, "max_hops": 2,
                            "apply_derivation_rules": True},
        "query_understanding": {"decompose": True, "expand_synonyms": True, "hyde": True},
    },
    "context": {"default_token_budget": 1500,
                "weights": {"relevance": 0.4, "recency": 0.25, "salience": 0.25, "pinned": 0.1}},
    "capture": {"sync_turn": {"mode": "observe_only"},
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
        "reinject": {"enabled": True},
        "standalone_fallback": "heuristic",
    },
}


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    """Thin dotted-path accessor over a merged config dict."""

    def __init__(self, overrides: Dict[str, Any] = None):
        self._d = _deep_merge(DEFAULTS, overrides or {})

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
    def raw(self) -> Dict[str, Any]:
        return self._d
