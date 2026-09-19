"""
Chronicle — Truth maintenance & guarded derivation (§9.4, I24).

Compositional inference via a small set of *guarded join rules* — never eager
transitive closure (I24e). A rule fires for a binding only if all guards hold:
(1) entity-grounded premises, (2) cardinality (required predicates single-valued),
(3) temporal overlap, (4) shared readable ACL/domain. The conclusion is bound to
a reified scope node (so it states "the user's Acme office is downtown,"
never "Acme is downtown," I24b), carries source_type=inference with
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

from . import access, sweeps
from .config import INFERENCE_TRUST

logger = logging.getLogger("chronicle.derivation")


def _parse_ts(ts: str | None):
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
    return not (bu is not None and af is not None and bu <= af)


class Rule:
    rule_id = ""
    name = ""
    materialize = "high_value"

    def antecedent_predicates(self) -> list[str]:
        return []

    def derive(self, subject: str, store, principal: str, cfg) -> list[dict]:
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


class TransitiveLocationRule(Rule):
    """A located_in B ∧ B located_in C  ⇒  A located_in C (guarded, 1-hop max)."""

    rule_id = "transitive_location"
    name = "Transitive location"
    materialize = "high_value"

    def antecedent_predicates(self):
        return ["located_in", "lives_in", "works_in"]

    def derive(self, subject, store, principal, cfg):
        # Check if subject has lives_in or works_in or located_in
        direct_locs = []
        for pred in ("lives_in", "works_in", "located_in"):
            direct_locs.extend(_active_facts(store, subject, pred, principal))
        if not direct_locs:
            return []

        results = []
        from .extraction import entity_token
        for dloc in direct_locs:
            b_entity = entity_token(dloc["value"])
            b_locs = _active_facts(store, b_entity, "located_in", principal)
            for bloc in b_locs:
                if not temporal_overlap(dloc, bloc):
                    continue
                if dloc["domain"] != bloc["domain"]:
                    continue
                if not (access.can_read(dloc.get("read_acl"), dloc.get("owner"), principal) and
                        access.can_read(bloc.get("read_acl"), bloc.get("owner"), principal)):
                    continue

                c_val = bloc["value"]
                pred = "lives_in" if dloc["attribute"] == "lives_in" else "located_in"
                conf = min(dloc["confidence"], bloc["confidence"]) * cfg.get("derivation.confidence.rule_factor", 0.9)
                conf = min(conf, cfg.get("derivation.confidence.ceiling", 0.70))
                status = cfg.get("derivation.default_status.agent", "active")
                body = f"{subject} is in {c_val}"
                key = {"entity_id": subject, "predicate_canonical": pred,
                       "attribute": pred, "qualifiers_hash": "", "qualifiers": {},
                       "entity_name": subject, "owner": dloc["owner"], "domain": dloc["domain"]}
                results.append({
                    "kind": "fact", "key": key, "body": body, "confidence": conf,
                    "rule_id": self.rule_id, "premises": sorted([dloc["belief_id"], bloc["belief_id"]]),
                    "status": status, "owner": dloc["owner"], "domain": dloc["domain"],
                })
        return results


_STARTER_RULES = [WorkplaceLocationRule(), TransitiveLocationRule()]


class DerivationEngine:
    def __init__(self, store, cfg, append_fn):
        self.store = store
        self.cfg = cfg
        self.append = append_fn        # capture.append, to emit `derived` events
        self.rules: dict[str, Rule] = {r.rule_id: r for r in _STARTER_RULES}
        # Mirrors RetrievalEngine.active_principal, kept in step by
        # ChronicleCore.set_active_principal: explain() is a read surface and
        # needs a principal to filter by when a caller passes none (A1).
        self.active_principal = "default"

    def seed_rules(self):
        for r in self.rules.values():
            if self.store.get_derivation_rule(r.rule_id) is None:
                self.store.upsert_derivation_rule({
                    "rule_id": r.rule_id, "name": r.name, "enabled": 1,
                    "pattern": json.dumps(r.antecedent_predicates()), "guards": "entity,cardinality,temporal,acl",
                    "conclusion": "scoped", "scope": "reified", "materialize": r.materialize})

    def enabled_rules(self) -> list[Rule]:
        rows = {row["rule_id"]: row for row in self.store.get_derivation_rules(enabled_only=False)}
        out = []
        for rid, rule in self.rules.items():
            row = rows.get(rid)
            if row is None or row["enabled"]:
                out.append(rule)
        return out

    def derive_for_subject(self, subject: str, principal: str = "default", *, materialize: bool = True) -> list[dict]:
        """Run all enabled rules for one subject. Returns derived payloads;
        materializes them as `derived` events when materialize=True (I24c)."""
        derived = []
        for rule in self.enabled_rules():
            for payload in rule.derive(subject, self.store, principal, self.cfg):
                derived.append(payload)
                if materialize:
                    self._materialize(payload)
        return derived

    def materialize_all(self, principal: str = "default", max_subjects=None):
        """The `derive` curation task: materialize high-value rules over affected
        subjects, bounded by fanout (never full closure, I24e).

        The fanout bound stays — full closure is the invariant this must not
        violate. What changes in §A9 is that the bound is now a PACE rather than
        a ceiling: the 500 subjects are the next 500 after a persisted cursor,
        so consecutive `derive`/`consolidate` jobs materialize the whole store
        instead of re-deriving the same head of `facts` forever. `max_subjects`
        still wins when a caller names one; otherwise the pace is
        `sweeps.budgets.derive_subjects`."""
        page = self._affected_subjects_page(max_subjects)
        for subj in page.rows:
            self.derive_for_subject(subj, principal, materialize=True)
        return sweeps.commit(self.store, page)

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

    def _affected_subjects_page(self, limit=None):
        """The next page of entities carrying a fact some enabled rule reads.

        §A9. The old loop ran one `query_beliefs(..., limit=500)` PER antecedent
        predicate — an unordered prefix each time, with no cursor — so the
        subjects it found were whichever ones happened to sit at the head of
        `facts` for those predicates, identically on every run. Entities past
        that prefix were never derived over, and `materialize_all` returned as
        though it had covered the store.

        One DISTINCT-entity page over all antecedent predicates replaces N
        prefixes: it is resumable, it is one query instead of one per predicate,
        and the deduplication the old code did in Python is now the DISTINCT.
        No enabled rules means no antecedents, hence an empty page rather than
        a scan of every fact in the store.

        A15's DETERMINISM FIX LIVES HERE, not in the shim below, and saying so
        is the point: A15 fixed `for pred in preds` (a set, therefore a
        PYTHONHASHSEED-dependent order, therefore a PYTHONHASHSEED-dependent
        order of the `derived` events `materialize_all` appends, their seq and
        their prev_head) by sorting at the boundary where the set stops being a
        membership test and becomes a sequence. A9 then replaced the per-
        predicate loop with one DISTINCT page, and the naive merge -- take the
        paged body, drop the sorted() -- would have resolved every conflict
        marker and silently reverted A15.

        Both halves are therefore kept, and they are NOT redundant:
          * `sorted(...)` below orders the predicates. In the paged form they
            reach SQL as `IN (?, ?, ...)` parameters, where order does not
            change the result -- so this is now the belt, not the braces, and
            it stays because a future edit that turns `preds` back into an
            iterated sequence must not have to rediscover the bug.
          * `next_distinct_page` -> `store.scan_distinct_after` carries
            `ORDER BY v`, a TOTAL order on the grouping value. That is what
            actually makes the subject order process-stable now, and it is
            strictly stronger than A15's original guarantee: A15 ordered the
            predicates and inherited each predicate's unordered row prefix,
            while this orders the subjects themselves.
          * The resume cursor is that same value, so a paged walk visits
            subjects in one total order across pages as well as within one.

        Pinned by tests/test_precision_packing.py::
        TestDeterminismSiblingsAreProcessStable::
        test_the_derive_task_visits_subjects_in_one_order, which runs the whole
        thing in five subprocesses under five PYTHONHASHSEEDs."""
        preds = set()
        for r in self.enabled_rules():
            preds.update(r.antecedent_predicates())
        preds = sorted(p for p in preds if p)
        # An explicit `max_subjects` is a caller naming its own batch and wins
        # outright; otherwise the pace is config, defaulting to the documented 500.
        budget = (max(1, int(limit)) if limit is not None
                  else sweeps.sweep_budget(self.cfg, "derive_subjects", default=500))
        if not preds:
            # None, not "": for a group cursor "" already means "the ''-group is
            # done", and a rule set that is merely disabled today must not leave
            # a cursor that skips a group when the rules come back.
            return sweeps.SweepPage("derive_subjects", [], None, None, 0, budget, True, 0)
        marks = ",".join("?" * len(preds))
        return sweeps.next_distinct_page(
            self.store, self.cfg, "derive_subjects", "facts", "entity_id",
            "status='active' AND predicate_canonical IN (%s)" % marks,
            tuple(preds), budget=budget)

    def _affected_subjects(self, limit=None):
        """Back-compat shim: just the ids of the next page."""
        return list(self._affected_subjects_page(limit).rows)

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

    def explain(self, belief_id: str, principal: str = "") -> dict:
        """Audit a derived belief (§9.4 safety): premises + rule + conclusion.

        ACL-filtered at the same access.can_read choke point every retrieval
        channel uses (A1). An unreadable belief returns the SAME shape a
        missing one does — belief ids are content hashes that surface in
        contradiction rows and tool output, so a distinguishable refusal would
        make this an existence oracle. The premise list is filtered too: a
        justification names another belief, and naming it is a disclosure even
        when its body is not returned."""
        principal = principal or self.active_principal
        found = self.store.find_belief(belief_id)
        if not found:
            return {"error": "not_found"}
        _table, row = found
        if not access.can_read(row.get("read_acl"), row.get("owner"), principal):
            return {"error": "not_found"}
        justs = self.store.get_justifications(belief_id)
        return {
            "belief_id": belief_id, "body": row.get("value") or row.get("body"),
            "source_type": json.loads(row.get("provenance") or "{}").get("source_type"),
            "rule_id": row.get("rule_id"),
            "premises": [j["support"] for j in justs
                         if j["support_kind"] == "belief" and self._premise_readable(j["support"], principal)],
            "confidence": row.get("confidence"), "status": row.get("status")}

    def _premise_readable(self, support: str, principal: str) -> bool:
        found = self.store.find_belief(support or "")
        if not found:
            return True   # dangling premise id names no content
        return access.can_read(found[1].get("read_acl"), found[1].get("owner"), principal)


def _active_facts(store, subject, predicate, principal) -> list[dict]:
    rows = store.query_beliefs(
        "facts", "entity_id=? AND predicate_canonical=? AND status='active'",
        (subject, predicate), limit=20)
    return [r for r in rows if access.can_read(r.get("read_acl"), r.get("owner"), principal)]
