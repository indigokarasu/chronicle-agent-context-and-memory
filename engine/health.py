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
        # Self-heal Tier-1: requeue vectors written by mismatched embedder.
        results.update(self._embedder_mismatch_heal())
        # Enqueue one bounded federation sweep per health run (§14, g4). The
        # health sweep is the schedule: enqueue_curation collapses an identical
        # pending job, so a backlogged queue never stacks sweeps, and each run
        # picks up where the last one's cursors left off.
        if self.cfg.get("federation.local_dbs"):
            results["federate_sweep_queued"] = bool(
                self.store.enqueue_curation("federate_sweep", {}))
        self.store.record_health_run(results)
        return results

    def _ghost_facts(self, gf) -> list[str]:
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
        groups: dict[tuple, list] = {}
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

    def _embedder_mismatch_heal(self) -> dict:
        """Tier-1 auto-repair: requeue vectors whose embedder model ≠ active model.

        Skip if embedder is None or has no model attribute. Returns {mismatched: N, requeued: N}."""
        embedder = self.core.embedder
        if embedder is None or not hasattr(embedder, "model"):
            return {"embedder_mismatch": {"mismatched": 0, "requeued": 0}}

        # Vectors are recorded via model_with_prefix_marker() (e.g.
        # "nomic-embed-text[prefixed]"), not the bare embedder.model. Comparing
        # against the bare name would mark correctly-tagged vectors as
        # mismatched forever and requeue them in an infinite loop.
        marker_fn = getattr(embedder, "model_with_prefix_marker", None)
        active_model = marker_fn() if callable(marker_fn) else embedder.model
        mismatched = 0
        requeued = 0

        # Scan observed_vectors for mismatched model.
        for row in self.store._conn().execute(
            "SELECT event_id, model FROM observed_vectors WHERE model != ?", (active_model,)).fetchall():
            mismatched += 1
            event_id, _model = row[0], row[1]
            # Extract text from the event payload (same logic as requeue_hash_vectors).
            ev = self.store._conn().execute("SELECT payload FROM events WHERE event_id=?", (event_id,)).fetchone()
            if ev:
                payload = json.loads(ev[0]) if isinstance(ev[0], str) else (ev[0] if ev[0] else {})
                text = (payload or {}).get("excerpt", "")
                if text and self.store.enqueue_embed_job(event_id, "observed", text) is not None:
                    requeued += 1
                    self._fingerprint("embedder_mismatch", "tier1", "requeue_embed", auto=1)

        # Scan memory_vectors for mismatched model.
        for row in self.store._conn().execute(
            "SELECT belief_id, kind, model FROM memory_vectors WHERE model != ?", (active_model,)).fetchall():
            mismatched += 1
            belief_id, kind, _model = row[0], row[1], row[2]
            # Extract text from the belief (same logic as requeue_hash_vectors).
            _BELIEF_TEXT = {
                "fact": ("facts", "value"), "episode": ("episodes", "summary"),
                "note": ("notes", "body"), "reference": ("refs", "cached_summary"),
                "procedure": ("procedures", "name")}
            table, col = _BELIEF_TEXT.get(kind, (None, None))
            text = ""
            if table:
                b = self.store._conn().execute(f"SELECT {col} FROM {table} WHERE belief_id=?",
                                               (belief_id,)).fetchone()
                text = (b[0] or "") if b else ""
            if text and self.store.enqueue_embed_job(belief_id, kind, text) is not None:
                requeued += 1
                self._fingerprint("embedder_mismatch", "tier1", "requeue_embed", auto=1)

        # Scan query_proxy_vectors (E2 doc2query) for mismatched model.
        #
        # Without this the heal has a permanent blind spot: proxies are stored
        # with their own `model` tag, but only observed_vectors and
        # memory_vectors were ever scanned, so after a model change -- or an E1
        # task-prefix flip, which rewrites the tag to "<model>[prefixed]" --
        # every proxy stays stale FOREVER. Nothing else notices: proxies are
        # regenerated only on a rewrite of their parent belief, and retrieval
        # happily scores the stale vectors against new-model query embeddings,
        # so doc2query silently degrades to noise while health reports clean.
        #
        # Deleted rather than requeued, because a proxy is not requeueable the
        # way a content vector is: the embed-job queue is keyed (target, kind)
        # and regenerates ONE vector from stored text, whereas a proxy set is
        # the variable-length output of doc2query generation over the parent's
        # key/body. Deleting is the convergent move -- a stale proxy is worse
        # than no proxy (it scores garbage similarity into the fused ranking),
        # the parent belief and its own vector are untouched, and the reducer
        # regenerates the set on that belief's next write. Two heals in a row
        # therefore report the mismatch once and then zero.
        stale_proxy_ids = [r[0] for r in self.store._conn().execute(
            "SELECT DISTINCT belief_id FROM query_proxy_vectors WHERE model != ?",
            (active_model,)).fetchall()]
        for belief_id in stale_proxy_ids:
            mismatched += self.store.count_query_proxy_vectors(belief_id)
            self.store.delete_query_proxy_vectors(belief_id)
            self._fingerprint("embedder_mismatch", "tier1", "drop_stale_proxies", auto=1)

        return {"embedder_mismatch": {"mismatched": mismatched, "requeued": requeued}}
