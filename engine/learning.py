"""
Chronicle — Learning loop, bounded (§22, I19).

Credit assignment feeds utility (EWMA) back into ranking/decay; calibration
refits; derivation rules accrue precision and auto-disable below threshold.
Policy changes go through champion/challenger and are hard-bounded: ≤
max_active_deltas active, each ≤ max_delta_magnitude, only whitelisted
dimensions tunable. Restricted-partition signals never train shared policy.
"""

from __future__ import annotations

import json
import logging

from .errors import E_LEARN_BOUND
from .store import now_iso

logger = logging.getLogger("chronicle.learning")


class LearningLoop:
    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.cfg = core.cfg
        self.max_active = self.cfg.get("learning.max_active_deltas", 8)
        self.max_mag = self.cfg.get("learning.max_delta_magnitude", 0.15)
        self.mutable = set(self.cfg.get("learning.mutable_dimensions", []))

    def record_outcome(self, belief_id: str, used: bool, outcome: float = 1.0):
        """utility = EWMA(used ? outcome : small_neg) (§22)."""
        found = self.store.find_belief(belief_id)
        if not found:
            return
        table, row = found
        if "utility" not in row:
            return
        prev = row.get("utility") or 0.0
        signal = outcome if used else -0.05
        new = round(0.8 * prev + 0.2 * signal, 4)
        self.store.update_belief(table, belief_id, utility=new)

    def auto_disable_low_precision_rules(self):
        thresh = self.cfg.get("derivation.auto_disable_precision_below", 0.6)
        for r in self.store.get_derivation_rules(enabled_only=True):
            n = r["precision_n"] or 0
            if n >= 10:
                prec = (r["precision_correct"] or 0) / n
                if prec < thresh:
                    self.store.set_rule_enabled(r["rule_id"], False)
                    logger.info("auto-disabled low-precision rule %s (%.2f)", r["rule_id"], prec)

    def propose_policy(self, kind: str, params: dict, parent_version: str = "") -> str:
        """Champion/challenger: validate bounds before a policy can be activated (I19)."""
        self._check_bounds(kind, params)
        import uuid
        version = f"{kind}-{uuid.uuid4().hex[:8]}"
        self.store.upsert_policy({"version": version, "kind": kind, "params": json.dumps(params),
                                  "parent_version": parent_version, "active": 0, "created_at": now_iso()})
        return version

    def activate_policy(self, version: str, *, beats_champion: bool):
        """Activate only if it beats champion with no regression; bounded count (I19)."""
        if self.store.count_active_policies() >= self.max_active:
            raise E_LEARN_BOUND("max active deltas exceeded", cap=self.max_active)
        if not beats_champion:
            raise E_LEARN_BOUND("challenger did not beat champion")
        self.store.upsert_policy({"version": version, "kind": "", "params": "{}",
                                  "parent_version": "", "active": 1})

    def _check_bounds(self, kind, params):
        if kind not in self.mutable:
            raise E_LEARN_BOUND(f"dimension {kind} not in mutable set", dimension=kind)
        for k, v in params.items():
            if isinstance(v, (int, float)) and abs(v) > self.max_mag + 1e-9:
                raise E_LEARN_BOUND(f"delta {k}={v} exceeds magnitude cap", cap=self.max_mag)
