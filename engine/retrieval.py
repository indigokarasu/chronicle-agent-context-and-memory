"""
Chronicle — Retrieval engine (§18).

Dual-tier retrieval: Tier 1 (belief layer) + Tier 2 (raw layer + read-and-answer).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("chronicle.retrieval")


class RetrievalEngine:
    """Dual-tier retrieval over the belief store and raw event log."""

    def __init__(self, store, active_principal: str = "default"):
        self.store = store
        self.active_principal = active_principal

    def search(self, query: str, *, limit: int = 10,
               domain: str | None = None) -> list[dict]:
        """Tier 1: Search the belief layer (FTS + structured)."""
        results = []

        # FTS over facts
        try:
            fts_results = self.store.fts_search(query, "observed_fts", limit=limit)
            for r in fts_results:
                results.append({
                    "source": "raw_fts",
                    "excerpt": r.get("excerpt", ""),
                    "score": 1.0,
                })
        except Exception:
            pass

        # Structured lookup: search facts by value/attribute
        rows = self.store.query_beliefs(
            "facts",
            "status='active' AND (value LIKE ? OR attribute LIKE ?)",
            (f"%{query}%", f"%{query}%"),
            limit=limit,
        )
        for r in rows:
            if self._check_read_access(r):
                results.append({
                    "source": "belief",
                    "kind": "fact",
                    "belief_id": r["belief_id"],
                    "entity_id": r["entity_id"],
                    "attribute": r["attribute"],
                    "value": r["value"],
                    "confidence": r.get("confidence", 0),
                    "score": r.get("confidence", 0.5),
                })

        # Search entities
        entity_rows = self.store.query_beliefs(
            "entities",
            "normalized_name LIKE ? OR name LIKE ?",
            (f"%{query.lower()}%", f"%{query}%"),
            limit=limit,
        )
        for r in entity_rows:
            results.append({
                "source": "entity",
                "belief_id": r["belief_id"],
                "name": r["name"],
                "type": r.get("type", ""),
                "score": 0.5,
            })

        # Search notes
        note_rows = self.store.query_beliefs(
            "notes",
            "status='active' AND (body LIKE ? OR subject LIKE ?)",
            (f"%{query}%", f"%{query}%"),
            limit=limit,
        )
        for r in note_rows:
            if self._check_read_access(r):
                results.append({
                    "source": "note",
                    "belief_id": r["belief_id"],
                    "note_type": r.get("note_type", ""),
                    "body": r.get("body", "")[:500],
                    "score": r.get("confidence", 0.5),
                })

        # Sort by score descending
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]

    def get_context(self, hint: str, *, token_budget: int = 1500,
                    include_directives: bool = True) -> str:
        """Context assembly (§18.5): union of search + directives + pinned."""
        parts = []

        # Directives (always_inject)
        if include_directives:
            directives = self.store.query_beliefs(
                "notes", "always_inject=1 AND status='active'", limit=20
            )
            for d in directives:
                if d.get("body"):
                    parts.append(f"[DIRECTIVE] {d['body']}")

        # Search results
        results = self.search(hint, limit=10)
        for r in results:
            if r["source"] == "belief":
                parts.append(f"[{r['entity_id']}] {r['attribute']}: {r['value']} "
                             f"(conf: {r.get('confidence', '?')})")
            elif r["source"] == "note":
                parts.append(f"[Note] {r.get('body', '')}")
            elif r["source"] == "raw_fts":
                parts.append(f"[Raw] {r.get('excerpt', '')[:300]}")

        # Critical beliefs
        critical = self.store.query_beliefs(
            "facts", "criticality='critical' AND status='active'", limit=5
        )
        for c in critical:
            if self._check_read_access(c):
                parts.append(f"[CRITICAL] {c['entity_id']} {c.get('attribute','')}: {c['value']}")

        context = "\n".join(parts)

        # Rough token budget (chars / 4)
        max_chars = token_budget * 4
        if len(context) > max_chars:
            context = context[:max_chars] + "\n... (truncated)"

        return context

    def get_directives(self) -> str:
        """system_prompt_block: return directives for the system prompt."""
        directives = self.store.query_beliefs(
            "notes", "always_inject=1 AND status='active'", limit=50
        )
        if not directives:
            return ""
        lines = ["=== CHRONICLE DIRECTIVES ==="]
        for d in directives:
            if d.get("body"):
                lines.append(f"- {d['body']}")
        return "\n".join(lines)

    def get_static_block(self, principal: str) -> str:
        """Return static system prompt block."""
        return self.get_directives()

    def answer(self, query: str, *, read_budget: int = 4000) -> dict:
        """Read-and-answer (§18.4): Tier 1 → Tier 2 fallback."""
        # Tier 1
        t1 = self.search(query, limit=10)

        if t1 and t1[0].get("score", 0) > 0.5:
            return {
                "answer": self._format_answer(t1[:5]),
                "sources": [r.get("belief_id", r.get("source", "?")) for r in t1[:5]],
                "tier": 1,
                "confidence": t1[0].get("score", 0),
            }

        # Tier 2: raw layer
        t2 = self.store.fts_search(query, "observed_fts", limit=20)
        if t2:
            excerpts = [r.get("excerpt", "") for r in t2[:5]]
            return {
                "answer": "Based on raw records:\n" + "\n".join(f"- {e[:200]}" for e in excerpts),
                "sources": ["raw_tier"],
                "tier": 2,
                "confidence": 0.3,
            }

        return {
            "answer": "",
            "sources": [],
            "tier": 0,
            "confidence": 0,
        }

    def _format_answer(self, results: list[dict]) -> str:
        lines = []
        for r in results:
            if r["source"] == "belief":
                lines.append(f"{r['entity_id']} — {r['attribute']}: {r['value']}")
            elif r["source"] == "note":
                lines.append(r.get("body", ""))
            elif r["source"] == "raw_fts":
                lines.append(r.get("excerpt", "")[:200])
        return "\n".join(lines) if lines else "No relevant information found."

    def _check_read_access(self, belief: dict) -> bool:
        """ACL check (§15.3): default-allow within user."""
        read_acl = belief.get("read_acl", "user_agents")
        owner = belief.get("owner", "")
        if read_acl == "user_agents":
            return True
        if owner == self.active_principal:
            return True
        return False

    def get_tool_schemas(self) -> list[dict]:
        """Return tool schemas for Chronicle tools."""
        return [
            {
                "name": "chronicle_remember",
                "description": "Store a fact, note, or episode in Chronicle memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["fact", "episode", "note", "reference", "procedure"]},
                        "content": {"type": "string", "description": "The content to remember."},
                        "entity": {"type": "string", "description": "Entity name (for facts)."},
                        "attribute": {"type": "string", "description": "Attribute/predicate (for facts)."},
                        "salience": {"type": "string", "enum": ["pinned", "high", "normal", "incidental"]},
                    },
                    "required": ["kind", "content"],
                },
            },
            {
                "name": "chronicle_search",
                "description": "Search Chronicle memory for relevant beliefs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "chronicle_answer",
                "description": "Ask a question and get an answer from Chronicle memory (dual-tier retrieval).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The question to answer."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "chronicle_forget",
                "description": "Remove a belief from Chronicle memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "belief_id": {"type": "string", "description": "The belief to forget."},
                        "reason": {"type": "string", "description": "Reason for forgetting."},
                    },
                    "required": ["belief_id"],
                },
            },
            {
                "name": "chronicle_list_directives",
                "description": "List all active directives (always/never rules) in Chronicle.",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    def dispatch_tool(self, tool_name: str, args: dict) -> str:
        """Handle a Chronicle tool call. Returns JSON string."""
        import json as _json

        if tool_name == "chronicle_remember":
            return self._tool_remember(args)
        elif tool_name == "chronicle_search":
            results = self.search(args.get("query", ""), limit=args.get("limit", 10))
            return _json.dumps({"results": results}, default=str)
        elif tool_name == "chronicle_answer":
            ans = self.answer(args.get("query", ""))
            return _json.dumps(ans, default=str)
        elif tool_name == "chronicle_forget":
            return self._tool_forget(args)
        elif tool_name == "chronicle_list_directives":
            directives = self.store.query_beliefs(
                "notes", "always_inject=1 AND status='active'", limit=50
            )
            return _json.dumps({"directives": [
                {"belief_id": d["belief_id"], "body": d.get("body", "")}
                for d in directives
            ]}, default=str)
        else:
            return _json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _tool_remember(self, args: dict) -> str:
        import json as _json
        kind = args.get("kind", "note")
        content = args.get("content", "")
        if not content:
            return _json.dumps({"error": "content is required"})

        # Create an asserted event
        from .serialize import event_id
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        key = {"subject": args.get("entity", "general")}
        if kind == "fact":
            key = {
                "entity_id": args.get("entity", "unknown"),
                "predicate_canonical": args.get("attribute", "has_note"),
                "qualifiers_hash": "",
                "owner": self.active_principal,
                "domain": "general",
            }

        payload = {
            "kind": kind,
            "key": key,
            "body": content,
            "confidence": 0.9,
            "source_event": "agent_memory_write",
        }

        eid = event_id("asserted", payload, [], "agent", now)
        prev_head = self.store.get_head_event_id()

        event = {
            "event_id": eid,
            "type": "asserted",
            "payload": payload,
            "parents": [],
            "actor": "agent",
            "owner": self.active_principal,
            "trust_level": 3,
            "session_id": None,
            "branch_id": None,
            "occurred_at": now,
            "recorded_at": now,
            "prev_head": prev_head,
            "sig": None,
        }
        self.store.append_event(event)
        return _json.dumps({"status": "stored", "event_id": eid})

    def _tool_forget(self, args: dict) -> str:
        import json as _json
        b_id = args.get("belief_id", "")
        if not b_id:
            return _json.dumps({"error": "belief_id is required"})

        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        payload = {"belief_id": b_id, "reason": args.get("reason", "user_request")}
        from .serialize import event_id
        eid = event_id("retracted", payload, [], "agent", now)
        prev_head = self.store.get_head_event_id()

        event = {
            "event_id": eid,
            "type": "retracted",
            "payload": payload,
            "parents": [],
            "actor": "agent",
            "owner": self.active_principal,
            "trust_level": 3,
            "occurred_at": now,
            "recorded_at": now,
            "prev_head": prev_head,
            "sig": None,
        }
        self.store.append_event(event)
        return _json.dumps({"status": "retracted", "event_id": eid})
