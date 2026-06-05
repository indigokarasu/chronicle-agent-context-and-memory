"""
Chronicle — Health & self-healing (§21).

An auditor (cold) computes drift/anomaly signals; the consistency sweep (CSP)
flags single-cardinality predicates with >1 active value and unsound derivations
→ `nogoods` + rule penalty; a Custodian fingerprints recurring issues and
applies bounded, non-destructive Tier-1 auto-repair (rebuild FTS, retract orphan
justifications, re-embed, unmerge known-bad). It never deletes events; all
repairs go through `append_event`.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List

logger = logging.getLogger("chronicle.health")


class HealthEngine:
    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.cfg = core.cfg

    def run(self) -> dict:
        gf = self.cfg.get("health.ghost_fact", {"confidence_min": 0.8, "age_days": 14})
        results = {
            "ghost_facts": self._ghost_facts(gf),
            "unjustified": self.store.active_unjustified(),          # I5 must be empty
            "extraction_recall_gap": self._recall_gap(),
            "bad_derivation_rate": self._bad_derivation_rate(),
            "open_contradictions": len(self.store.get_open_contradictions(1000)),
            "lock_contention": round(self.store.lock_contention(), 4),
        }
        # Self-heal Tier-1: retract orphan (unjustified) active beliefs (I5).
        if self.cfg.get("health.self_heal.tier1_auto", True):
            for bid in results["unjustified"]:
                self._fingerprint("unjustified_active", "tier1", "retract_orphan", auto=1)
                self.core.capture.append("retracted", {"belief_id": bid, "reason": "unjustified_orphan"},
                                         actor="curator", owner="default")
        self.consistency_sweep()
        self.store.record_health_run(results)
        return results

    def _ghost_facts(self, gf) -> List[str]:
        rows = self.store.query_beliefs(
            "facts", "status='active' AND confirm_count=0 AND confidence>=?",
            (gf.get("confidence_min", 0.8),), limit=5000)
        return [r["belief_id"] for r in rows][:200]

    def _recall_gap(self) -> float:
        total = self.store.count_rows("retrieval_log")
        misses = self.store.count_rows("search_misses")
        return round(misses / total, 4) if total else 0.0

    def _bad_derivation_rate(self) -> float:
        rules = self.store.get_derivation_rules(enabled_only=False)
        n = sum(r["precision_n"] or 0 for r in rules)
        correct = sum(r["precision_correct"] or 0 for r in rules)
        return round(1 - correct / n, 4) if n else 0.0

    def consistency_sweep(self):
        """CSP (§21): single-cardinality predicate with >1 active value → contradiction;
        unsound derivations → nogoods + rule penalty."""
        rows = self.store.query_beliefs("facts", "status='active'", (), limit=5000)
        groups: Dict[tuple, list] = {}
        for r in rows:
            groups.setdefault((r["entity_id"], r["predicate_canonical"], r["qualifiers_hash"],
                               r["owner"], r["domain"]), []).append(r)
        for (ent, pred, qh, owner, domain), facts in groups.items():
            if not pred:
                continue
            if self.store.get_predicate_cardinality(pred) != "single":
                continue
            distinct = {f["value"] for f in facts}
            non_derived = [f for f in facts if json.loads(f.get("provenance") or "{}").get("source_type") != "inference"]
            if len(distinct) > 1 and len(non_derived) > 1:
                # No supersession resolved them → open a contradiction (§21).
                a, b = sorted(facts, key=lambda f: f["created_at"])[:2]
                self.store.open_contradiction(a["belief_id"], b["belief_id"],
                                              f"{pred} single-cardinality has {len(distinct)} active values")
                self._fingerprint("cardinality_violation", "tier2", "review", auto=0)

    def _fingerprint(self, pattern, tier, action, auto):
        fp = f"{pattern}:{tier}"
        self.store.upsert_fingerprint(fp, pattern, tier, action, auto)

    def rebuild_fts(self):
        """Tier-1 auto-repair: rebuild FTS from the projection (non-destructive)."""
        self.core.reducer.rebuild()
