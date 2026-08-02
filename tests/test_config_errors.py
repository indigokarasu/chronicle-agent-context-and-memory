"""
Chronicle — tests for config.py and errors.py (§27, §32).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import (
    Config, DEFAULTS, TRUST_CEILING, CONFIDENCE_BASE, ABSTAIN_GATES,
    check_abstain_gate, _deep_merge,
)
from engine.errors import (
    ChronicleError, E_SCHEMA, E_NOT_FOUND, E_FORBIDDEN_CONTENT,
    E_TRUST_CEILING, E_CONFLICT, E_BUDGET, E_EVICT_UNSAFE,
    E_RISK_REVIEW, E_LEARN_BOUND, E_AUTHORITY_UNAVAILABLE,
    E_ACCESS_DENIED, E_READ_BUDGET, E_DERIVATION_GUARD,
)


class TestConfig(unittest.TestCase):
    def test_defaults_populated(self):
        required_keys = [
            "provider", "store", "db_path", "git_repo",
            "embeddings", "principals", "sources", "federation",
            "extraction", "derivation", "retrieval", "context",
            "capture", "reaper", "confidence", "forgetting",
            "salience", "domains", "curation", "health",
            "learning", "consent", "security", "git",
            "context_engine",
        ]
        for k in required_keys:
            self.assertIn(k, DEFAULTS, f"missing top-level key: {k}")

    def test_config_get_simple_path(self):
        cfg = Config()
        self.assertEqual(cfg.get("provider"), "chronicle")
        self.assertEqual(cfg.get("store"), "sqlite")

    def test_config_get_nested_path(self):
        cfg = Config()
        self.assertEqual(cfg.get("embeddings.model"), "auto")
        self.assertEqual(cfg.get("embeddings.dimensions"), 768)
        self.assertEqual(cfg.get("forgetting.confirm_critical"), True)

    def test_config_get_missing_returns_default(self):
        cfg = Config()
        self.assertIsNone(cfg.get("nonexistent.key"))
        self.assertEqual(cfg.get("nonexistent.key", "fallback"), "fallback")

    def test_config_override_flat(self):
        cfg = Config({"provider": "custom"})
        self.assertEqual(cfg.get("provider"), "custom")
        self.assertEqual(cfg.get("store"), "sqlite")

    def test_config_override_nested(self):
        cfg = Config({"embeddings": {"model": "hashing", "dimensions": 512}})
        self.assertEqual(cfg.get("embeddings.model"), "hashing")
        self.assertEqual(cfg.get("embeddings.dimensions"), 512)
        self.assertEqual(cfg.get("embeddings.base_url"), None)

    def test_config_override_deep_nested(self):
        cfg = Config({"domains": {"user": {"auto_decay": True}}})
        self.assertTrue(cfg.get("domains.user.auto_decay"))
        self.assertTrue(cfg.get("domains.agent.auto_decay"))
        self.assertTrue(cfg.get("domains.general.auto_decay"))

    def test_config_raw_returns_full_dict(self):
        cfg = Config({"provider": "x"})
        raw = cfg.raw
        self.assertEqual(raw["provider"], "x")
        self.assertIn("store", raw)

    def test_config_indexable(self):
        cfg = Config()
        self.assertEqual(cfg["store"], "sqlite")

    def test_deep_merge_overrides_leaf(self):
        base = {"a": {"b": 1, "c": 2}}
        over = {"a": {"b": 99}}
        merged = _deep_merge(base, over)
        self.assertEqual(merged["a"]["b"], 99)
        self.assertEqual(merged["a"]["c"], 2)

    def test_deep_merge_adds_new_keys(self):
        base = {"a": 1}
        over = {"b": {"c": 3}}
        merged = _deep_merge(base, over)
        self.assertEqual(merged["a"], 1)
        self.assertEqual(merged["b"]["c"], 3)

    def test_deep_merge_does_not_mutate_base(self):
        base = {"a": {"b": 1}}
        over = {"a": {"b": 99}}
        _deep_merge(base, over)
        self.assertEqual(base["a"]["b"], 1)

    def test_trust_ceiling_map(self):
        self.assertEqual(TRUST_CEILING[0], 0.40)
        self.assertEqual(TRUST_CEILING[4], 1.00)

    def test_confidence_base_known_types(self):
        self.assertEqual(CONFIDENCE_BASE["user_direct"], 0.85)
        self.assertEqual(CONFIDENCE_BASE["inference"], 0.60)

    def test_config_context_engine_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.get("context_engine.engine"), "chronicle")
        self.assertEqual(cfg.get("context_engine.never_evict"), "directives")

    def test_config_derivation_defaults(self):
        cfg = Config()
        self.assertTrue(cfg.get("derivation.enabled"))
        self.assertEqual(cfg.get("derivation.materialize"), "high_value")
        self.assertEqual(cfg.get("derivation.max_depth"), 2)

    def test_config_reaper_defaults(self):
        cfg = Config()
        self.assertTrue(cfg.get("reaper.enabled"))
        self.assertTrue(cfg.get("reaper.startup_recovery"))

    def test_config_abstain_gate_defaults(self):  # §18.4 support gate
        cfg = Config()
        self.assertIn(cfg.get("retrieval.abstain_gate"), ABSTAIN_GATES)
        for k in ("score_threshold", "focus_coverage", "overlap_min_tokens"):
            self.assertIsNotNone(cfg.get("retrieval." + k), "retrieval.%s unregistered" % k)

    def test_config_abstain_gate_unknown_raises(self):  # §18.4
        # A typo here would silently disable abstention — the one failure the
        # gate exists to prevent — so it must be loud, not a fallback.
        with self.assertRaises(ValueError):
            Config({"retrieval": {"abstain_gate": "overlp"}})
        with self.assertRaises(ValueError):
            check_abstain_gate(None)

    def test_config_abstain_gate_each_known_accepted(self):  # §18.4
        for g in ABSTAIN_GATES:
            self.assertEqual(Config({"retrieval": {"abstain_gate": g}}).get("retrieval.abstain_gate"), g)


class TestErrors(unittest.TestCase):
    def test_base_error_code(self):
        e = ChronicleError("oops")
        self.assertEqual(str(e), "oops")
        self.assertEqual(e.code, "E_STORE")
        self.assertEqual(e.detail, {})

    def test_base_error_default_message(self):
        e = ChronicleError()
        self.assertEqual(str(e), "E_STORE")

    def test_error_with_detail(self):
        e = ChronicleError("bad", table="events", row_id=42)
        self.assertEqual(e.detail, {"table": "events", "row_id": 42})

    def test_e_schema(self):
        e = E_SCHEMA("invalid payload")
        self.assertEqual(e.code, "E_SCHEMA")
        self.assertIsInstance(e, ChronicleError)

    def test_e_not_found(self):
        e = E_NOT_FOUND("missing")
        self.assertEqual(e.code, "E_NOT_FOUND")

    def test_e_forbidden_content(self):
        e = E_FORBIDDEN_CONTENT("tombstoned")
        self.assertEqual(e.code, "E_FORBIDDEN_CONTENT")

    def test_e_trust_ceiling(self):
        e = E_TRUST_CEILING("ceiling hit")
        self.assertEqual(e.code, "E_TRUST_CEILING")

    def test_e_conflict(self):
        e = E_CONFLICT("duplicate")
        self.assertEqual(e.code, "E_CONFLICT")

    def test_e_budget(self):
        e = E_BUDGET("over budget")
        self.assertEqual(e.code, "E_BUDGET")

    def test_e_evict_unsafe(self):
        e = E_EVICT_UNSAFE("evicting non-durable")
        self.assertEqual(e.code, "E_EVICT_UNSAFE")

    def test_e_risk_review(self):
        e = E_RISK_REVIEW("high risk")
        self.assertEqual(e.code, "E_RISK_REVIEW")

    def test_e_learn_bound(self):
        e = E_LEARN_BOUND("delta too big", cap=0.15)
        self.assertEqual(e.code, "E_LEARN_BOUND")
        self.assertEqual(e.detail["cap"], 0.15)

    def test_e_authority_unavailable(self):
        e = E_AUTHORITY_UNAVAILABLE("no provider", capability="contacts")
        self.assertEqual(e.code, "E_AUTHORITY_UNAVAILABLE")
        self.assertEqual(e.detail["capability"], "contacts")

    def test_e_access_denied(self):
        e = E_ACCESS_DENIED("restricted")
        self.assertEqual(e.code, "E_ACCESS_DENIED")

    def test_e_read_budget(self):
        e = E_READ_BUDGET("budget exceeded")
        self.assertEqual(e.code, "E_READ_BUDGET")

    def test_e_derivation_guard(self):
        e = E_DERIVATION_GUARD("guards unmet")
        self.assertEqual(e.code, "E_DERIVATION_GUARD")

    def test_all_error_codes_unique(self):
        codes = [
            ChronicleError.code, E_SCHEMA.code, E_NOT_FOUND.code,
            E_FORBIDDEN_CONTENT.code, E_TRUST_CEILING.code, E_CONFLICT.code,
            E_BUDGET.code, E_EVICT_UNSAFE.code, E_RISK_REVIEW.code,
            E_LEARN_BOUND.code, E_AUTHORITY_UNAVAILABLE.code,
            E_ACCESS_DENIED.code, E_READ_BUDGET.code, E_DERIVATION_GUARD.code,
        ]
        self.assertEqual(len(codes), len(set(codes)), "duplicate error codes detected")

    def test_errors_are_catchable_as_base(self):
        for cls in [E_SCHEMA, E_NOT_FOUND, E_FORBIDDEN_CONTENT, E_TRUST_CEILING,
                     E_CONFLICT, E_BUDGET, E_EVICT_UNSAFE, E_RISK_REVIEW,
                     E_LEARN_BOUND, E_AUTHORITY_UNAVAILABLE, E_ACCESS_DENIED,
                     E_READ_BUDGET, E_DERIVATION_GUARD]:
            try:
                raise cls("test")
            except ChronicleError:
                pass
            except Exception:
                self.fail(f"{cls.__name__} not catchable as ChronicleError")


if __name__ == "__main__":
    unittest.main(verbosity=2)
