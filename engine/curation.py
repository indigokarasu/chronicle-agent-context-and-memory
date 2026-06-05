"""
Chronicle — Curation pipeline (§17).

A worker claims the lowest-id ready job and writes every result via
`append_event` (no special path). DAG: extract → route → criticality →
canonicalize → consolidate → contradiction → identity → derive → consistency.
Heuristics are a pre-filter + sanity bound, never a silent writer.
"""

from __future__ import annotations

import json
import logging
import os

from .store import now_iso

logger = logging.getLogger("chronicle.curation")

# source_type → memory domain (governs decay/contradiction, §8.4)
_DOMAIN = {"user_direct": "user", "session_transcript": "user", "rescue_extraction": "user",
           "agent_memory_write": "agent", "delegation": "agent", "ocas_journal": "user",
           "inference": "user"}


def domain_for(source_type: str) -> str:
    return _DOMAIN.get(source_type, "general")


class CurationWorker:
    def __init__(self, core):
        self.core = core
        self.store = core.store
        self.cfg = core.cfg

    # -- loop --------------------------------------------------------------

    def run_once(self) -> bool:
        job = self.store.claim_curation_job()
        if job is None:
            return False
        try:
            handler = getattr(self, f"_task_{job['task']}", None)
            if handler is None:
                self.store.complete_curation_job(job["id"], error="no_handler")
                return True
            payload = json.loads(job["payload"] or "{}")
            handler(payload)
            self.store.complete_curation_job(job["id"])
        except Exception as e:  # sanity bound: a failed job never corrupts state
            logger.exception("curation job %s failed", job["id"])
            self.store.complete_curation_job(job["id"], error=str(e)[:300])
        return True

    def drain(self, max_jobs: int = 1000) -> int:
        n = 0
        while n < max_jobs and self.run_once():
            n += 1
        return n

    # -- tasks -------------------------------------------------------------

    def _task_extract(self, payload):
        eid = payload.get("event_id")
        ev = self.store.get_event(eid) if eid else None
        if not ev:
            return
        version = self.core.extractor.version
        if self.store.has_extraction(eid, version):
            return  # idempotent (I9)
        # I16: never promote observed events from an abandoned branch (kept for audit).
        sid = ev.get("session_id")
        s = self.store.get_session(sid) if sid else None
        if s and s.get("branch_point_seq") is not None and ev["seq"] > s["branch_point_seq"]:
            self.store.record_extraction(eid, version, {"skipped": "branch_abandoned"}, 0, "skip")
            return
        p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
        excerpt = p.get("excerpt", "")
        source_type = p.get("source_type", "session_transcript")
        domain = domain_for(source_type)
        owner = ev["owner"]
        result = self.core.extractor.extract(excerpt, source_event=eid, owner=owner,
                                             domain=domain, session_id=ev.get("session_id") or "")
        subjects = set()
        for item in result.items:
            if item.get("route") == "skip":
                continue
            if self._maybe_delegate(item, owner, domain):
                continue
            self._emit_item(item, ev, owner, domain, source_type, version)
            if item.get("kind") == "fact":
                subjects.add(item["key"].get("entity_id"))
        self.store.record_extraction(eid, version,
                                     {"n": len(result.items)}, 1 if result.ambiguous else 0, result.route)
        self._advance_watermark(ev)
        # Inline derive for touched subjects (guarded; §9.4).
        for subj in subjects:
            if subj:
                self.core.derivation.derive_for_subject(subj, self.core.active_principal)
        # Canonicalize newly seen predicates.
        self.store.enqueue_curation("canonicalize", {"subjects": list(subjects)})

    def _emit_item(self, item, ev, owner, domain, source_type, version):
        kind = item.get("kind", "fact")
        risk = item.get("key", {}).get("risk_tier", "low")
        # Risk-tiered application (§16.4): behavior-changing high-risk → draft + review.
        status = item.get("status", "active")
        if kind == "note" and item.get("key", {}).get("note_type") in ("norm", "procedure"):
            if risk == "high":
                status = "draft"
        ext = {"extractor_version": version, "valid_from": ev.get("occurred_at")}
        if "_entity_id" in item:
            ext["entity_token"] = item["_entity_id"]
        self.core.capture.append("asserted", {
            "kind": kind, "key": item["key"], "body": item["body"], "domain": domain,
            "confidence": item.get("confidence", 0.8), "source_event": item["source_event"],
            "source_type": source_type, "status": status,
            "extractor_version": version, "valid_from": ev.get("occurred_at")},
            actor="curator", owner=owner, session_id=ev.get("session_id"),
            trust_level=ev.get("trust_level", 2))
        # Typed learning signal audit (§16.2)
        if item.get("signal_type"):
            self.core.capture.append("signal", {"signal_type": item["signal_type"],
                                                "body": item["body"][:200], "source_event": item["source_event"]},
                                     actor="curator", owner=owner)

    def _maybe_delegate(self, item, owner, domain) -> bool:
        """Route into a claimed capability as a pointer, not an owned belief (§14, I20)."""
        fed = self.core.federation
        if fed is None or item.get("kind") != "fact":
            return False
        predicate = item["key"].get("predicate_canonical", "")
        cap = fed.capability_for_predicate(predicate)
        if not cap:
            return False
        fed.route_delegate(capability=cap, entity_id=item["key"].get("entity_id"),
                           predicate=predicate, value=item["body"], owner=owner)
        return True

    def _advance_watermark(self, ev):
        sid = ev.get("session_id")
        if not sid:
            return
        s = self.store.get_session(sid)
        if s and ev["seq"] > (s.get("last_extracted_seq") or 0):
            self.store.upsert_session({"session_id": sid, "last_extracted_seq": ev["seq"]})

    def _task_derive(self, payload):
        subjects = payload.get("subjects")
        if subjects:
            for s in subjects:
                self.core.derivation.derive_for_subject(s, self.core.active_principal)
        else:
            self.core.derivation.materialize_all(self.core.active_principal)

    def _task_canonicalize(self, payload):
        """Predicate schema induction (§17): ensure predicates table + infer cardinality."""
        rows = self.store.query_beliefs("facts", "status='active'", (), limit=5000)
        by_pred = {}
        for r in rows:
            by_pred.setdefault(r["predicate_canonical"], {}).setdefault(r["entity_id"], set()).add(r["value"])
        for pred, ents in by_pred.items():
            if not pred:
                continue
            multi = any(len(vals) > 1 for vals in ents.values())
            from .extraction import canonical_predicate
            _, seed_card = canonical_predicate(pred)
            cardinality = "multi" if (multi and seed_card != "single") else seed_card
            if self.store.get_predicate(pred) is None:
                self.store.upsert_predicate(pred, pred, cardinality)

    def _task_consolidate(self, payload):
        self._task_canonicalize(payload)
        self.core.derivation.materialize_all(self.core.active_principal)

    def _task_contradiction(self, payload):
        self.core.health.consistency_sweep()

    def _task_identity(self, payload):
        """Exact name/alias dedup → merge (§17). Fuzzy is proposed, never auto."""
        ents = self.store.query_beliefs("entities", "merged_into IS NULL", (), limit=5000)
        by_name = {}
        for e in ents:
            by_name.setdefault((e["normalized_name"], e["owner"], e["domain"]), []).append(e)
        for group in by_name.values():
            if len(group) > 1:
                keep = group[0]
                for dup in group[1:]:
                    self.core.capture.append("merged", {"from_entity": dup["belief_id"],
                                                        "into_entity": keep["belief_id"],
                                                        "evidence": "exact_name_match"},
                                             actor="curator", owner=keep["owner"])

    def _task_verify(self, payload):
        """Verify a high-criticality fact against its source span (§16.6)."""
        bid = payload.get("belief_id")
        f = self.store.get_belief("facts", bid) if bid else None
        if not f:
            return
        prov = json.loads(f.get("provenance") or "{}")
        src = self.store.get_event(prov.get("source_event", ""))
        ok = False
        if src:
            sp = json.loads(src["payload"]) if isinstance(src["payload"], str) else src["payload"]
            ok = f["value"].lower() in (sp.get("excerpt", "").lower())
        self.core.capture.append("verified", {"belief_id": bid, "status": "verified" if ok else "refuted",
                                              "method": "source_span"}, actor="curator", owner=f["owner"])
        self.store.bump_calibration(prov.get("source_type", "session_transcript"),
                                    _bucket(f.get("confidence", 0.5)), ok)

    def _task_decay(self, payload):
        self.core.forgetting.decay_sweep()

    def _task_consistency(self, payload):
        self.core.health.consistency_sweep()

    def _task_health(self, payload):
        self.core.health.run()

    def _task_reextract(self, payload):
        """Replay extraction at the current version, criticality-prioritized (§16.5)."""
        events = self.store.get_events_by_type("observed")
        version = self.core.extractor.version
        prioritized = sorted(events, key=lambda e: e["seq"])
        for ev in prioritized[: payload.get("limit", 200)]:
            if not self.store.has_extraction(ev["event_id"], version):
                self.store.enqueue_curation("extract", {"event_id": ev["event_id"],
                                                        "session_id": ev.get("session_id")})

    def _task_session_summarize(self, payload):
        sid = payload.get("session_id")
        if not sid:
            return
        events = self.store.get_events_by_session(sid)
        excerpts = []
        for ev in events:
            if ev["type"] == "observed":
                p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
                excerpts.append(p.get("excerpt", ""))
        if not excerpts:
            return
        summary = " ".join(excerpts)[:1000]
        owner = events[0]["owner"] if events else "default"
        vec = b""
        if self.core.embedder is not None:
            try:
                from .embeddings import pack
                vec = pack(self.core.embedder.embed(summary))
            except Exception:
                vec = b""
        self.store.add_session_vector(sid, summary, vec, owner, events[0].get("occurred_at", now_iso()))

    def _task_journal_ingest(self, payload):
        """OCAS journals → observed events, deduped by content addressing (§14.1)."""
        paths = self.cfg.get("sources.ocas_journals.paths", [])
        for path in paths:
            path = os.path.expanduser(path)
            if not os.path.isdir(path):
                continue
            for fn in sorted(os.listdir(path)):
                fp = os.path.join(path, fn)
                if not os.path.isfile(fp):
                    continue
                try:
                    with open(fp, "r", encoding="utf-8") as fh:
                        text = fh.read()
                except OSError:
                    continue
                self.core.capture.append("observed",
                                         {"source_type": "ocas_journal", "excerpt": text[:4000],
                                          "source_ref": fp}, actor="user", trust_level=2)


def _bucket(score: float) -> str:
    return f"{int(max(0.0, min(0.999, score)) * 10) / 10:.1f}"
