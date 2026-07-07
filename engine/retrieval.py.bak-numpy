"""
Chronicle — Retrieval (§18): dual-tier + read-and-answer.

Tier 1 hits the belief layer (FTS5 + brute-force ANN + structured), fused by
Reciprocal Rank Fusion. When Tier 1 is insufficient, Tier 2 retrieves raw spans
+ session summaries (the recall floor, I23) and a read step answers from them and
writes the belief back (promote-on-read, §16.7) — so a fact present in a durable
`observed` event is answerable even if eager extraction missed it. Every path
applies, in order: ACL (active principal), status, trust/info-label, purpose
(I11), temporal validity, domain. With no support in either tier or via
derivation, it abstains (I8) rather than fabricates.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List

from . import access
from .embeddings import unpack, cosine
from .trust import Calibrator, confidence_summary
from .store import now_iso, KIND_TABLE

logger = logging.getLogger("chronicle.retrieval")

_STOP = {"the", "a", "an", "is", "are", "what", "who", "where", "when", "how", "do", "does",
         "did", "my", "your", "of", "to", "in", "on", "for", "and", "or", "i", "me", "s",
         "was", "were", "it", "that", "this", "with", "about", "tell", "show", "name"}


class RetrievalEngine:
    def __init__(self, store, cfg=None, embedder=None, derivation=None, active_principal="default"):
        self.store = store
        self.cfg = cfg
        self.embedder = embedder
        self.derivation = derivation
        self.active_principal = active_principal
        min_obs = cfg.get("calibration.min_obs", 50) if cfg else 50
        self.calibrator = Calibrator(store, min_obs)
        self._rrf_k = cfg.get("retrieval.rrf_k", 60) if cfg else 60
        self._fts_w = cfg.get("retrieval.fts_weight", 0.4) if cfg else 0.4
        self._vec_w = cfg.get("retrieval.vector_weight", 0.6) if cfg else 0.6
        self._gate = cfg.get("retrieval.read_and_answer.confidence_gate", 0.55) if cfg else 0.55
        self._miss_threshold = cfg.get("retrieval.miss_threshold", 0.15) if cfg else 0.15

    # -- query understanding (§18.2) --------------------------------------

    def query_understanding(self, query: str) -> dict:
        tokens = [t for t in re.findall(r"[A-Za-z0-9']+", query.lower()) if t not in _STOP and len(t) > 1]
        expansions = set(tokens)
        for t in list(tokens):
            for syn in self.store.predicate_synonyms(t):
                expansions.add(syn)
        emb = None
        if self.embedder is not None:
            try:
                emb = self.embedder.embed(" ".join(expansions) or query)
            except Exception:
                emb = None  # vector channel drops out; FTS + structured still answer
        return {"raw": query, "tokens": tokens, "expanded": list(expansions), "embedding": emb}

    # -- Tier 1 (§18.1) ----------------------------------------------------

    def search(self, query, *, limit=10, domain=None, purpose="*", principal=None):
        principal = principal or self.active_principal
        q = self.query_understanding(query)
        ranked: Dict[str, dict] = {}

        def add(bid, table, rank, channel):
            row = self.store.get_belief(table, bid)
            if not row or not self._readable(row, principal, purpose, domain):
                return
            w = {"fts": self._fts_w, "vector": self._vec_w}.get(channel, 0.3)
            entry = ranked.setdefault(bid, {"row": row, "table": table, "score": 0.0, "why": set()})
            entry["score"] += w / (self._rrf_k + rank)
            entry["why"].add(channel)

        of = self.cfg_overfetch()
        for i, r in enumerate(self.store.fts_search_beliefs(query, limit=limit * of)):
            add(r["belief_id"], _table_of_kind(r["kind"]), i + 1, "fts")
        if q["embedding"] is not None:
            for i, (bid, kind, _s) in enumerate(self._vector_beliefs(q["embedding"], limit * of)):
                add(bid, _table_of_kind(kind), i + 1, "vector")
        for tok in q["tokens"]:
            for r in self.store.query_beliefs(
                    "facts", "status IN ('active','draft') AND (value LIKE ? OR attribute LIKE ? "
                    "OR predicate_canonical LIKE ?)", (f"%{tok}%", f"%{tok}%", f"%{tok}%"), limit=limit):
                add(r["belief_id"], "facts", 5, "structured")

        out = []
        for bid, e in ranked.items():
            row = e["row"]
            out.append({
                "belief_id": bid, "table": e["table"], "kind": _kind_of_table(e["table"]),
                "score": e["score"], "channels": sorted(e["why"]),
                "value": row.get("value") or row.get("body") or row.get("summary") or row.get("name"),
                "entity_id": row.get("entity_id"), "attribute": row.get("attribute"),
                "confidence": row.get("confidence"), "status": row.get("status"),
                "source_type": json.loads(row.get("provenance") or "{}").get("source_type"),
            })
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:limit]

    # -- Tier 2 (§18.1) — raw layer (recall floor) ------------------------

    def retrieve_raw(self, query, *, limit=20, principal=None):
        principal = principal or self.active_principal
        q = self.query_understanding(query)
        scored: Dict[str, dict] = {}
        for i, r in enumerate(self.store.fts_search_observed(query, limit=limit)):
            ev = self.store.get_event(r["event_id"])
            if ev and access.can_read(access.DEFAULT_ACL, ev["owner"], principal):
                scored.setdefault(r["event_id"], {"excerpt": r["excerpt"], "score": 0.0,
                                                  "owner": ev["owner"]})["score"] += self._fts_w / (self._rrf_k + i + 1)
        if q["embedding"] is not None:
            for v in self.store.iter_observed_vectors():
                if not access.can_read(access.DEFAULT_ACL, v.get("owner"), principal):
                    continue
                sim = cosine(q["embedding"], unpack(v["embedding"]))
                if sim > 0.1:
                    ev = self.store.get_event(v["event_id"])
                    p = json.loads(ev["payload"]) if ev and isinstance(ev["payload"], str) else (ev or {}).get("payload", {})
                    scored.setdefault(v["event_id"], {"excerpt": p.get("excerpt", ""), "score": 0.0,
                                                      "owner": v.get("owner")})["score"] += self._vec_w * sim
        for s in self.store.iter_session_vectors():
            if q["embedding"] is not None and s.get("embedding"):
                sim = cosine(q["embedding"], unpack(s["embedding"]))
                if sim > 0.15 and access.can_read(access.DEFAULT_ACL, s.get("owner"), principal):
                    scored.setdefault("session:" + s["session_id"],
                                      {"excerpt": s.get("summary", ""), "score": sim * 0.5, "owner": s.get("owner")})
        out = [{"event_id": k, "excerpt": v["excerpt"], "score": v["score"]} for k, v in scored.items()]
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:limit]

    # -- read-and-answer (§18.4, I23) -------------------------------------

    def answer(self, query, *, read_budget=4000, purpose="*", principal=None) -> dict:
        principal = principal or self.active_principal
        q = self.query_understanding(query)
        t1 = self.search(query, limit=10, purpose=purpose, principal=principal)
        top = t1[0]["score"] if t1 else 0.0

        if t1 and self._confident(t1):
            self.store.log_retrieval(query, "*", top)
            return self._answer_from_beliefs(t1, tier=1)

        t2 = self.retrieve_raw(query, principal=principal)
        # Lexical grounding: a raw span only counts as support if it shares a query
        # token (guards against spurious vector hits → false answers).
        focus = set(q["tokens"])
        t2 = [c for c in t2 if any(w in (c["excerpt"] or "").lower() for w in focus)]
        if not t1 and not t2:
            self.store.log_retrieval(query, "*", 0.0)
            return {"answer": "", "abstain": True, "sources": [], "tier": 0, "confidence": 0.0,
                    "why": "no_support"}  # abstention (I8, B.3)

        ans = self._read_and_extract(query, q, t1, t2, principal, read_budget)
        if ans.get("abstain") and not t1:
            self.store.log_retrieval(query, "*", 0.0)
            return {"answer": "", "abstain": True, "sources": [], "tier": 0, "confidence": 0.0,
                    "why": "no_support"}
        if top < self._miss_threshold and t2:
            self.store.log_miss(query, "*", top)
            for cand in t2[:2]:
                if not cand["event_id"].startswith("session:"):
                    self.store.enqueue_curation("extract", {"event_id": cand["event_id"]})
        return ans

    def _answer_from_beliefs(self, beliefs, *, tier):
        lead = beliefs[0]
        row = self.store.get_belief(lead["table"], lead["belief_id"]) or {}
        cal = self.calibrator.calibrate(row.get("confidence", lead["score"]),
                                        lead.get("source_type") or "session_transcript")
        text = "\n".join(self._render(b) for b in beliefs[:5])
        return {"answer": text, "abstain": False, "sources": [b["belief_id"] for b in beliefs[:5]],
                "tier": tier, "confidence": round(cal, 4), "confidence_summary": confidence_summary(row, cal),
                "derived": [b["belief_id"] for b in beliefs if b.get("source_type") == "inference"]}

    def _read_and_extract(self, query, q, t1, t2, principal, read_budget):
        focus = set(q["tokens"])
        best, best_score, budget = None, -1, read_budget
        for cand in t2:
            span = cand["excerpt"][: max(0, budget)]
            budget -= len(span)
            sc = sum(1 for w in focus if w in span.lower())
            if sc > best_score:
                best, best_score = span, sc
            if budget <= 0:
                break
        promoted = self._promote_from_span(best, focus, principal) if best else []
        answer = self._focus_sentence(best or (t1[0]["value"] if t1 else ""), focus)
        conf = 0.5 if best else (t1[0]["score"] if t1 else 0.0)
        conf = self.calibrator.calibrate(conf, "session_transcript")
        return {"answer": answer, "abstain": not answer, "tier": 2 if best else 1,
                "sources": [c["event_id"] for c in t2[:3]] + [b["belief_id"] for b in t1[:2]],
                "confidence": round(conf, 4), "promoted": promoted}

    def _promote_from_span(self, span, focus, principal) -> List[str]:
        """Write beliefs back from a raw span (§16.7). Returns promoted belief ids."""
        from .extraction import entity_token
        from .serialize import belief_id as bid_fn
        promoted = []
        for m in re.finditer(r"([A-Z][\w'-]+)\s+is\s+(?:a|an)\s+([^.,;\n]+)", span):
            subj, val = m.group(1), m.group(2).strip()
            ent = entity_token(subj)
            key = {"entity_id": ent, "predicate_canonical": "occupation", "attribute": "occupation",
                   "qualifiers_hash": "", "qualifiers": {}, "entity_name": subj,
                   "owner": principal, "domain": "user"}
            self._append("asserted", {"kind": "fact", "key": key, "body": val[:200], "confidence": 0.6,
                                      "source_event": "read_and_answer", "source_type": "session_transcript"},
                         principal)
            promoted.append(bid_fn("fact", key, ["read_and_answer"]))
        return promoted

    # -- context assembly (§18.5) -----------------------------------------

    def get_context(self, hint, *, token_budget=1500, include_directives=True, purpose="*",
                    principal=None, epistemic=None) -> str:
        principal = principal or self.active_principal
        parts: List[str] = []
        if include_directives:
            for d in self.store.query_beliefs("notes", "always_inject=1 AND status='active'", (), 20):
                if d.get("body"):
                    parts.append(f"[DIRECTIVE] {d['body']}")
        for c in self.store.get_open_contradictions(5):
            parts.append(f"[CONTRADICTION] {c.get('detail','') or c.get('belief_a','')}")
        for c in self.store.query_beliefs("facts", "criticality!='normal' AND status='active'", (), 5):
            if self._readable(c, principal, purpose, None):
                parts.append(f"[CRITICAL] {c.get('attribute','')}: {c['value']}")
        for b in self.search(hint, limit=10, purpose=purpose, principal=principal):
            ann = epistemic.annotate(b) if epistemic else ""
            parts.append(self._render(b) + (f"  ({ann})" if ann else ""))
        ctx = "\n".join(_dedupe(parts))
        max_chars = token_budget * 4
        return ctx if len(ctx) <= max_chars else ctx[:max_chars] + "\n… (truncated)"

    def get_directives(self) -> str:
        ds = self.store.query_beliefs("notes", "always_inject=1 AND status='active'", (), 50)
        if not ds:
            return ""
        return "\n".join(["=== CHRONICLE DIRECTIVES ==="] + [f"- {d['body']}" for d in ds if d.get("body")])

    def static_block(self, principal: str) -> str:
        lines = []
        d = self.get_directives()
        if d:
            lines.append(d)
        crit = [c for c in self.store.query_beliefs("facts", "criticality='critical' AND status='active'", (), 5)
                if self._readable(c, principal, "*", None)]
        if crit:
            lines.append("=== CRITICAL ===")
            lines += [f"- {c.get('attribute','')}: {c['value']}" for c in crit]
        con = self.store.get_open_contradictions(5)
        if con:
            lines.append("=== OPEN CONTRADICTIONS ===")
            lines += [f"- {c.get('detail','')}" for c in con]
        return "\n".join(lines)

    # -- structured lookups (§18.3) ---------------------------------------

    def ask_about(self, entity_id, *, principal=None):
        principal = principal or self.active_principal
        rows = self.store.query_beliefs("facts", "entity_id=? AND status='active'", (entity_id,), 50)
        return [self._render_fact(r) for r in rows if self._readable(r, principal, "*", None)]

    def around(self, entity_id, depth=1, *, principal=None):
        principal = principal or self.active_principal
        seen, frontier, out = {entity_id}, [entity_id], []
        for _ in range(depth):
            nxt = []
            for e in frontier:
                for r in self.store.query_beliefs("relationships",
                                                  "(source_id=? OR target_id=?) AND status='active'",
                                                  (e, e), 50):
                    if not self._readable(r, principal, "*", None):
                        continue
                    out.append({"source": r["source_id"], "predicate": r["predicate"], "target": r["target_id"]})
                    for nb in (r["source_id"], r["target_id"]):
                        if nb not in seen:
                            seen.add(nb)
                            nxt.append(nb)
            frontier = nxt
        return out

    def timeline(self, *, principal=None, limit=50):
        principal = principal or self.active_principal
        rows = self.store.query_beliefs("episodes", "status='active'", (), limit, order="occurred_at DESC")
        return [{"title": r["title"], "occurred_at": r["occurred_at"], "summary": r.get("summary")}
                for r in rows if self._readable(r, principal, "*", None)]

    def history(self, belief_id):
        chain, cur, guard = [], belief_id, 0
        while cur and guard < 100:
            found = self.store.find_belief(cur)
            if not found:
                break
            row = found[1]
            chain.append({"belief_id": cur, "value": row.get("value") or row.get("body"),
                          "status": row.get("status"), "valid_from": row.get("valid_from"),
                          "valid_until": row.get("valid_until")})
            cur = row.get("superseded_by")
            guard += 1
        return chain

    def as_of(self, world=None, knowledge=None) -> List[dict]:
        """Bitemporal query (§7.4): as-known-at `knowledge`, as-true-at `world`."""
        events = self.store.get_events_as_of(knowledge) if knowledge else self.store.get_events_since(0)
        facts = {}
        for ev in events:
            if ev["type"] != "asserted":
                continue
            p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
            if p.get("kind") != "fact":
                continue
            k = p["key"]
            facts[(k.get("entity_id"), k.get("predicate_canonical"))] = {
                "value": p.get("body"), "valid_from": p.get("valid_from") or ev["occurred_at"]}
        out = []
        for (ent, pred), v in facts.items():
            if world and v["valid_from"] and v["valid_from"] > world:
                continue
            out.append({"entity_id": ent, "predicate": pred, "value": v["value"]})
        return out

    def changes_since(self, ts: str) -> List[dict]:
        rows = self.store.query_beliefs("facts", "created_at > ?", (ts,), 100, order="created_at")
        return [{"belief_id": r["belief_id"], "value": r["value"], "status": r["status"]} for r in rows]

    # -- helpers -----------------------------------------------------------

    def cfg_overfetch(self):
        return self.cfg.get("retrieval.overfetch", 4) if self.cfg else 4

    def _confident(self, t1):
        # RRF scores are small (≈ w/(k+rank)); scale the configured gate accordingly.
        return bool(t1) and t1[0]["score"] >= (self._fts_w + self._vec_w) / (self._rrf_k + 1) * 0.9

    def _vector_beliefs(self, query_emb, limit):
        scored = []
        for v in self.store.iter_memory_vectors():
            sim = cosine(query_emb, unpack(v["embedding"]))
            if sim > 0.1:
                scored.append((v["belief_id"], v["kind"], sim))
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:limit]

    def _readable(self, row, principal, purpose, domain) -> bool:
        if row.get("status") not in ("active", "draft", None):
            return False
        if not access.can_read(row.get("read_acl"), row.get("owner"), principal):
            return False
        if domain and row.get("domain") and row["domain"] != domain:
            return False
        ps = row.get("purpose_scope")
        if ps and purpose and purpose != "*":
            try:
                scopes = json.loads(ps)
                if "*" not in scopes and purpose not in scopes:
                    return False
            except Exception:
                pass
        if row.get("info_label") == "secret" and purpose != "secret":
            return False
        return True

    def _render(self, b):
        if b["kind"] == "fact":
            tag = "DERIVED" if b.get("source_type") == "inference" else "FACT"
            return f"[{tag}] {b.get('attribute') or ''}: {b.get('value')} (conf {round(b.get('confidence') or 0, 2)})"
        if b["kind"] == "note":
            return f"[NOTE] {b.get('value')}"
        if b["kind"] == "episode":
            return f"[EPISODE] {b.get('value')}"
        return f"[{b['kind'].upper()}] {b.get('value')}"

    def _render_fact(self, r):
        return {"belief_id": r["belief_id"], "attribute": r["attribute"], "value": r["value"],
                "confidence": r["confidence"], "status": r["status"],
                "derived": json.loads(r.get("provenance") or "{}").get("source_type") == "inference"}

    def _focus_sentence(self, text, focus):
        if not text:
            return ""
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if any(w in sent.lower() for w in focus):
                return sent.strip()
        return text.split("\n")[0][:200].strip()

    def _append(self, type_, payload, principal):
        from .serialize import event_id
        now = now_iso()
        eid = event_id(type_, payload, [], "curator", now)
        self.store.append_event({"event_id": eid, "type": type_, "payload": payload, "parents": [],
                                 "actor": "curator", "owner": principal, "trust_level": 2,
                                 "session_id": None, "branch_id": None, "occurred_at": now,
                                 "recorded_at": now, "prev_head": self.store.get_head_event_id(), "sig": None})


def _table_of_kind(kind):
    return KIND_TABLE.get(kind, "facts")


def _kind_of_table(table):
    rev = {"facts": "fact", "episodes": "episode", "notes": "note", "refs": "reference",
           "relationships": "relationship", "procedures": "procedure", "entities": "entity"}
    return rev.get(table, "fact")


def _dedupe(parts):
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
