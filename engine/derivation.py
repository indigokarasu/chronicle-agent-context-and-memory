"""
Chronicle — Truth maintenance & guarded derivation (§9.4, I24).

Compositional inference via a small set of *guarded join rules* — never eager
transitive closure (I24e). A rule fires for a binding only if all guards hold:
(1) entity-grounded premises, (2) cardinality (required predicates single-valued),
(3) temporal overlap, (4) shared readable ACL/domain. The conclusion is bound to
a reified scope node (so it states "the user's Innovaccer office is downtown,"
never "Innovaccer is downtown," I24b), carries source_type=inference with
confidence ≤ C(inference)=0.75, is hedged, and is justified by its premises + the
rule so the TMS retracts it when any premise is (I24d).

The starter set ships here as coded rules; the `derivation_rules` table mirrors
enable state + precision stats so operators can disable a rule and the learning
loop can auto-disable low-precision ones (§22).
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Dict, List, Optional

from . import access
from .config import INFERENCE_TRUST

logger = logging.getLogger("chronicle.derivation")


def _parse_ts(ts: Optional[str]):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def temporal_overlap(a: dict, b: dict) -> bool:
    """[valid_from, valid_until) intervals intersect; open ends are ±infinity."""
    af, au = _parse_ts(a.get("valid_from")), _parse_ts(a.get("valid_until"))
    bf, bu = _parse_ts(b.get("valid_from")), _parse_ts(b.get("valid_until"))
    if au is not None and bf is not None and au <= bf:
        return False
    if bu is not None and af is not None and bu <= af:
        return False
    return True


class Rule:
    rule_id = ""
    name = ""
    materialize = "high_value"

    def antecedent_predicates(self) -> List[str]:
        return []

    def derive(self, subject: str, store, principal: str, cfg) -> List[dict]:
        return []


class WorkplaceLocationRule(Rule):
    """user works_at ORG ∧ user works_in LOCATION  ⇒  the user's ORG workplace
    is located_in LOCATION (scoped, hedged). The canonical §9.4 / B.4 example."""

    rule_id = "workplace_location"
    name = "Workplace location"
    materialize = "high_value"

    def antecedent_predicates(self):
        return ["works_at", "works_in"]

    def derive(self, subject, store, principal, cfg):
        works_at = _active_facts(store, subject, "works_at", principal)
        works_in = _active_facts(store, subject, "works_in", principal)
        if not works_at or not works_in:
            return []
        # Guard 2 — cardinality: both must be single-valued for the subject.
        if store.get_predicate_cardinality("works_at") != "single" or len(works_at) != 1:
            return []
        if store.get_predicate_cardinality("works_in") != "single" or len(works_in) != 1:
            return []
        wa, wi = works_at[0], works_in[0]
        # Guard 1 — entity-grounded: subject + ORG resolve to entities, not raw strings.
        from .extraction import entity_token
        org_token = entity_token(wa["value"])
        if not store.get_belief("entities", org_token) and not store.get_belief("entities", subject):
            return []
        # Guard 3 — temporal overlap.
        if not temporal_overlap(wa, wi):
            return []
        # Guard 4 — shared readable scope/domain.
        if wa["domain"] != wi["domain"]:
            return []
        if not (access.can_read(wa.get("read_acl"), wa.get("owner"), principal) and
                access.can_read(wi.get("read_acl"), wi.get("owner"), principal)):
            return []

        org, loc = wa["value"], wi["value"]
        workplace = f"workplace:{subject}:{org_token}"          # reified scope node (I24b)
        conf = min(wa["confidence"], wi["confidence"]) * cfg.get("derivation.confidence.rule_factor", 0.9)
        conf = min(conf, cfg.get("derivation.confidence.ceiling", 0.75))
        status = cfg.get("derivation.default_status.user", "draft") if wa["domain"] == "user" \
            else cfg.get("derivation.default_status.agent", "active")
        body = f"your {org} workplace is in {loc}"
        key = {"entity_id": workplace, "predicate_canonical": "located_in",
               "attribute": "located_in", "qualifiers_hash": "", "qualifiers": {},
               "entity_name": f"{org} workplace", "owner": wa["owner"], "domain": wa["domain"]}
        return [{
            "kind": "fact", "key": key, "body": body, "confidence": conf,
            "rule_id": self.rule_id, "premises": sorted([wa["belief_id"], wi["belief_id"]]),
            "status": status, "owner": wa["owner"], "domain": wa["domain"],
            "scope_entity": {"belief_id": workplace, "name": f"{org} workplace", "type": "workplace"},
        }]


_STARTER_RULES = [WorkplaceLocationRule()]


class DerivationEngine:
    def __init__(self, store, cfg, append_fn):
        self.store = store
        self.cfg = cfg
        self.append = append_fn        # capture.append, to emit `derived` events
        self.rules: Dict[str, Rule] = {r.rule_id: r for r in _STARTER_RULES}

    def seed_rules(self):
        for r in self.rules.values():
            if self.store.get_derivation_rule(r.rule_id) is None:
                self.store.upsert_derivation_rule({
                    "rule_id": r.rule_id, "name": r.name, "enabled": 1,
                    "pattern": json.dumps(r.antecedent_predicates()), "guards": "entity,cardinality,temporal,acl",
                    "conclusion": "scoped", "scope": "reified", "materialize": r.materialize})

    def enabled_rules(self) -> List[Rule]:
        rows = {row["rule_id"]: row for row in self.store.get_derivation_rules(enabled_only=False)}
        out = []
        for rid, rule in self.rules.items():
            row = rows.get(rid)
            if row is None or row["enabled"]:
                out.append(rule)
        return out

    def derive_for_subject(self, subject: str, principal: str = "default", *, materialize: bool = True) -> List[dict]:
        """Run all enabled rules for one subject. Returns derived payloads;
        materializes them as `derived` events when materialize=True (I24c)."""
        derived = []
        for rule in self.enabled_rules():
            for payload in rule.derive(subject, self.store, principal, self.cfg):
                derived.append(payload)
                if materialize:
                    self._materialize(payload)
        return derived

    def materialize_all(self, principal: str = "default", max_subjects: int = 500):
        """The `derive` curation task: materialize high-value rules over affected
        subjects, bounded by fanout (never full closure, I24e)."""
        subjects = self._affected_subjects(max_subjects)
        for subj in subjects:
            self.derive_for_subject(subj, principal, materialize=True)

    def _materialize(self, payload: dict):
        scope = payload.get("scope_entity")
        if scope and not self.store.get_belief("entities", scope["belief_id"]):
            # Create the reified scope entity so the conclusion is entity-bound.
            self.append("asserted", {
                "kind": "entity",
                "key": {"entity_type": scope["type"], "type": scope["type"], "name": scope["name"],
                        "normalized_name": scope["belief_id"], "owner": payload["owner"],
                        "domain": payload["domain"]},
                "body": scope["name"], "confidence": 0.75, "source_event": payload["rule_id"],
                "source_type": "inference"}, actor="curator", owner=payload["owner"])
        self.append("derived", {
            "kind": payload["kind"], "key": payload["key"], "body": payload["body"],
            "domain": payload["domain"], "rule_id": payload["rule_id"], "premises": payload["premises"],
            "confidence": payload["confidence"], "status": payload["status"]},
            actor="curator", owner=payload["owner"], trust_level=INFERENCE_TRUST)
        self._bump_precision(payload["rule_id"], fired=True)

    def _affected_subjects(self, limit):
        seen, out = set(), []
        preds = set()
        for r in self.enabled_rules():
            preds.update(r.antecedent_predicates())
        for pred in preds:
            for f in self.store.query_beliefs("facts", "predicate_canonical=? AND status='active'",
                                              (pred,), limit=limit):
                if f["entity_id"] not in seen:
                    seen.add(f["entity_id"])
                    out.append(f["entity_id"])
        return out

    def _bump_precision(self, rule_id, fired=True, correct=True):
        row = self.store.get_derivation_rule(rule_id)
        if not row:
            return
        self.store.upsert_derivation_rule({
            "rule_id": rule_id, "name": row["name"], "enabled": row["enabled"],
            "pattern": row["pattern"], "guards": row["guards"], "conclusion": row["conclusion"],
            "scope": row["scope"], "materialize": row["materialize"],
            "precision_n": (row["precision_n"] or 0) + (1 if fired else 0),
            "precision_correct": (row["precision_correct"] or 0) + (1 if correct else 0)})

    def explain(self, belief_id: str) -> dict:
        """Audit a derived belief (§9.4 safety): premises + rule + conclusion."""
        found = self.store.find_belief(belief_id)
        if not found:
            return {"error": "not_found"}
        table, row = found
        justs = self.store.get_justifications(belief_id)
        return {
            "belief_id": belief_id, "body": row.get("value") or row.get("body"),
            "source_type": json.loads(row.get("provenance") or "{}").get("source_type"),
            "rule_id": row.get("rule_id"),
            "premises": [j["support"] for j in justs if j["support_kind"] == "belief"],
            "confidence": row.get("confidence"), "status": row.get("status")}


def _active_facts(store, subject, predicate, principal) -> List[dict]:
    rows = store.query_beliefs(
        "facts", "entity_id=? AND predicate_canonical=? AND status='active'",
        (subject, predicate), limit=20)
    return [r for r in rows if access.can_read(r.get("read_acl"), r.get("owner"), principal)]
