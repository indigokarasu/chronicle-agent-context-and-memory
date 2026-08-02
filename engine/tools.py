"""
Chronicle — Tool surface (§23, exposed via get_tool_schemas/handle_tool_call).

A single dispatcher over ChronicleCore. Tool names are accepted with or without
the `chronicle_` prefix. Every write goes through the atomic append path; every
read is ACL-filtered for the active principal (§15).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from . import access
from .reducer import _normalize_value as _norm_fact_value


class Tools:
    def __init__(self, core):
        self.core = core

    # -- registry ----------------------------------------------------------

    def schemas(self):
        def s(name, desc, props=None, required=None):
            return {"name": f"chronicle_{name}", "description": desc,
                    "parameters": {"type": "object", "properties": props or {}, "required": required or []}}
        text = {"type": "string"}
        return [
            s("db_query", "Query a registered external SQLite database (SELECT-only).",
              {"db": text, "sql": text}, ["db", "sql"]),
            s("remember", "Store a fact/note/episode/reference/procedure in memory.",
              {"kind": {"type": "string", "enum": ["fact", "episode", "note", "reference", "procedure"]},
               "content": text, "entity": text, "attribute": text,
               "salience": {"type": "string", "enum": ["pinned", "high", "normal", "incidental"]}},
              ["content"]),
            s("search", "Search the belief store + raw events (dual-tier).", {"query": text, "limit": {"type": "integer"}}, ["query"]),
            s("answer", "Answer a question from memory (read-and-answer, abstains if unknown).", {"query": text}, ["query"]),
            s("ask_about", "All known facts about an entity.", {"entity": text}, ["entity"]),
            s("timeline", "Recent episodes in time order.", {}),
            s("history", "Supersession history of a belief.", {"belief_id": text}, ["belief_id"]),
            s("get_context", "Assemble relevant context for a hint.", {"hint": text}, ["hint"]),
            s("explain", "Explain a derived belief (premises + rule).", {"belief_id": text}, ["belief_id"]),
            s("list_directives", "List active always/never directives.", {}),
            s("list_contradictions", "List open contradictions.", {}),
            s("correct", "Correct a belief (supersede or retract).", {"belief_id": text, "new_value": text, "reason": text}, ["belief_id"]),
            s("forget", "Retract a belief.", {"belief_id": text, "reason": text}, ["belief_id"]),
            s("withdraw_consent", "Withdraw consent → unlearn a belief.", {"belief_id": text}, ["belief_id"]),
            s("verify", "Queue verification of a belief against its source.", {"belief_id": text}, ["belief_id"]),
            s("grant_read", "Grant a principal read access to a belief.", {"belief_id": text, "principal": text}, ["belief_id", "principal"]),
            s("revoke_read", "Revoke a principal's read access.", {"belief_id": text, "principal": text}, ["belief_id", "principal"]),
            s("set_acl", "Set a belief's read ACL (e.g. private).", {"belief_id": text, "visibility": text}, ["belief_id"]),
            s("set_agent_privacy", "Mark an agent private/shared.", {"agent": text, "private": {"type": "boolean"}}, ["agent"]),
            s("list_principals", "List principals (agents/users).", {}),
            s("list_derivation_rules", "List derivation rules.", {}),
            s("set_rule_enabled", "Enable/disable a derivation rule.", {"rule_id": text, "enabled": {"type": "boolean"}}, ["rule_id", "enabled"]),
            s("list_capabilities", "List federated capability providers.", {}),
            s("embedding_status", "Report the active embedder: real local model (with a live test "
                                  "embed) vs offline hashing fallback.", {}),
            s("plan_context", "Bundle facts + procedures + reflections for a goal.", {"goal": text}, ["goal"]),
            s("reflect", "Record a reflection lesson.", {"situation": text, "action": text, "outcome": text, "lesson": text}, ["situation", "lesson"]),
            s("remember_goal", "Add a standing goal.", {"goal": text}, ["goal"]),
            s("active_goals", "List active goals.", {}),
            s("what_user_knows", "What the user has been told about a topic.", {"topic": text}, ["topic"]),
            s("note_informed", "Record that the user was told something.", {"proposition": text}, ["proposition"]),
            s("unmerge", "Reverse an entity merge.", {"entity_id": text}, ["entity_id"]),
        ]

    # -- dispatch ----------------------------------------------------------

    def dispatch(self, principal: str, name: str, args: Dict[str, Any]) -> str:
        name = name[len("chronicle_"):] if name.startswith("chronicle_") else name
        fn = getattr(self, f"_t_{name}", None)
        if fn is None:
            return json.dumps({"error": f"unknown tool: {name}"})
        try:
            return json.dumps(fn(principal, args), default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _emit(self, type_, payload, principal, **kw):
        return self.core.capture.append(type_, payload, owner=kw.pop("owner", principal),
                                        actor=kw.pop("actor", "agent"), **kw)

    # writes
    def _t_remember(self, principal, a):
        kind = a.get("kind", "note")
        content = a.get("content", "")
        if not content:
            return {"error": "content required"}
        if kind == "fact":
            key = {"entity_id": a.get("entity", "user"),
                   "predicate_canonical": a.get("attribute", "note"),
                   "attribute": a.get("attribute", "note"), "qualifiers_hash": "", "qualifiers": {},
                   "owner": principal, "domain": "user"}
        elif kind == "note":
            key = {"note_type": "belief", "subject": a.get("entity", "general")}
        elif kind == "episode":
            key = {"title": content[:48]}
        elif kind == "reference":
            key = {"topic": a.get("entity", content[:40])}
        else:
            key = {"name": a.get("entity", content[:40])}

        # Pre-flight conflict check (facts only, §8.5 domain contradiction policy): look
        # for the active belief this remember is about to collide with, using the exact
        # same lookup + NOOP-dedup normalization the reducer itself uses (_find_existing /
        # _normalize_value in reducer.py), so what we report here matches what the reducer
        # is about to do. domain is forced to 'user' below for every fact written through
        # this tool -- that's what routes it into DOMAIN_POLICY['user'] = 'flag_for_review'
        # instead of the 'general' default (whose conflict handler silently drops the new
        # value and only refreshes last_seen_at on the old one).
        conflicting_belief_id = None
        if kind == "fact":
            existing = self.core.store.query_beliefs(
                "facts",
                "entity_id=? AND predicate_canonical=? AND qualifiers_hash=? AND owner=? "
                "AND domain='user' AND status='active'",
                (key["entity_id"], key["predicate_canonical"], key["qualifiers_hash"], principal),
                limit=1)
            if existing and _norm_fact_value(existing[0]["value"]) != _norm_fact_value(content):
                conflicting_belief_id = existing[0]["belief_id"]

        # For facts, source_event must be unique per call -- the shared literal "tool" made
        # compute_belief_id(kind, key, [source_event]) collapse every conflicting remember
        # for the same key onto the SAME belief_id, so the "new" belief overwrote the
        # "existing" one in place instead of superseding it as a distinct row (destroying
        # the losing value and self-linking the contradiction to its own replacement).
        # Scoped to facts deliberately: for note/episode/reference/procedure that collapse
        # is the DESIRED behavior (no contradiction policy applies to them), and it is what
        # keeps N identical non-fact remembers deduping onto one belief_id / one search hit.
        source_event = f"tool_remember_{uuid.uuid4().hex}" if kind == "fact" else "tool"
        payload = {"kind": kind, "key": key, "body": content, "confidence": 0.9,
                  "source_event": source_event, "source_type": "agent_memory_write",
                  "salience": a.get("salience", "normal")}
        if kind == "fact":
            payload["domain"] = "user"
        eid = self._emit("asserted", payload, principal, actor="agent", trust_level=3)

        if conflicting_belief_id:
            return {"status": "conflict_recorded", "event": eid,
                    "conflicts_with": conflicting_belief_id,
                    "message": f"This conflicts with an existing belief ({conflicting_belief_id}); "
                               f"both are recorded and linked via a contradiction for review."}
        return {"status": "stored", "event": eid}

    def _t_correct(self, principal, a):
        self._emit("corrected", {"belief_id": a["belief_id"], "new_body": a.get("new_value"),
                                 "reason": a.get("reason", "user_correction")}, principal, actor="user")
        return {"status": "corrected"}

    def _t_forget(self, principal, a):
        self._emit("retracted", {"belief_id": a["belief_id"], "reason": a.get("reason", "user_request")},
                   principal, actor="user")
        return {"status": "retracted"}

    def _t_withdraw_consent(self, principal, a):
        self.core.forgetting.unlearn(a["belief_id"], "consent_withdrawn")
        return {"status": "unlearned"}

    def _t_verify(self, principal, a):
        self.core.store.enqueue_curation("verify", {"belief_id": a["belief_id"]})
        return {"status": "queued"}

    def _t_grant_read(self, principal, a):
        self._emit("grant", {"belief_id": a["belief_id"], "principal": a["principal"]}, principal)
        return {"status": "granted"}

    def _t_revoke_read(self, principal, a):
        self._emit("revoke", {"belief_id": a["belief_id"], "principal": a["principal"]}, principal)
        return {"status": "revoked"}

    def _t_set_acl(self, principal, a):
        found = self.core.store.find_belief(a["belief_id"])
        if not found:
            return {"error": "not_found"}
        acl = access.make_private(principal) if a.get("visibility") == "private" else access.DEFAULT_ACL
        self.core.store.update_belief(found[0], a["belief_id"], read_acl=acl)
        return {"status": "acl_set", "read_acl": acl}

    def _t_set_agent_privacy(self, principal, a):
        self.core.set_agent_privacy(a["agent"], a.get("private", True))
        return {"status": "set"}

    def _t_unmerge(self, principal, a):
        self._emit("unmerged", {"from_entity": a["entity_id"]}, principal, actor="curator")
        return {"status": "unmerged"}

    def _t_set_rule_enabled(self, principal, a):
        self.core.store.set_rule_enabled(a["rule_id"], bool(a.get("enabled", True)))
        return {"status": "ok"}

    def _t_reflect(self, principal, a):
        rid = self.core.reasoning.reflect(a.get("situation", ""), a.get("action", ""),
                                          a.get("outcome", ""), a.get("lesson", ""), a.get("applicability", ""))
        return {"status": "reflected", "id": rid}

    def _t_remember_goal(self, principal, a):
        return {"status": "ok", "id": self.core.reasoning.remember_goal(a["goal"])}

    def _t_note_informed(self, principal, a):
        self._emit("informed", {"proposition": a["proposition"], "importance": a.get("importance", 0.5)},
                   principal, actor="agent")
        return {"status": "noted"}

    # reads
    def _t_search(self, principal, a):
        return {"results": self.core.retrieval.search(a.get("query", ""), limit=a.get("limit", 10),
                                                      principal=principal)}

    def _t_answer(self, principal, a):
        return self.core.retrieval.answer(a.get("query", ""), principal=principal,
                                          purpose=a.get("purpose", "*"))

    def _t_ask_about(self, principal, a):
        return {"facts": self.core.retrieval.ask_about(a["entity"], principal=principal)}

    def _t_timeline(self, principal, a):
        return {"timeline": self.core.retrieval.timeline(principal=principal)}

    def _t_history(self, principal, a):
        return {"history": self.core.retrieval.history(a["belief_id"])}

    def _t_get_context(self, principal, a):
        return {"context": self.core.retrieval.get_context(a["hint"], principal=principal,
                                                           epistemic=self.core.epistemic)}

    def _t_explain(self, principal, a):
        return self.core.derivation.explain(a["belief_id"])

    def _t_list_directives(self, principal, a):
        ds = self.core.store.query_beliefs("notes", "always_inject=1 AND status='active'", (), 50)
        return {"directives": [{"belief_id": d["belief_id"], "body": d.get("body")} for d in ds]}

    def _t_list_contradictions(self, principal, a):
        return {"contradictions": self.core.store.get_open_contradictions(50)}

    def _t_list_principals(self, principal, a):
        return {"principals": self.core.store.all_principals()}

    def _t_list_derivation_rules(self, principal, a):
        return {"rules": self.core.store.get_derivation_rules(enabled_only=False)}

    def _t_list_capabilities(self, principal, a):
        return {"capabilities": self.core.federation.list_capabilities() if self.core.federation else []}

    def _t_embedding_status(self, principal, a):
        return self.core.embedding_status()

    def _t_db_query(self, principal, a):
        """Query a registered external SQLite database (SELECT-only).

        Hard rules:
        - Only registered databases (federation.local_dbs) are accessible.
        - Only SELECT statements allowed (rejects INSERT/UPDATE/DELETE/PRAGMA/ATTACH).
        - Single statement only (no multi-statement).
        - Row count capped at 50.
        - Read-only connection enforced.
        """
        import re
        import sqlite3

        db_name = a.get("db", "").strip()
        sql_query = a.get("sql", "").strip()

        if not db_name:
            return {"error": "db name required"}
        if not sql_query:
            return {"error": "sql query required"}

        # Get registered databases from config
        local_dbs = self.core.cfg.get("federation.local_dbs") or []
        db_config = next((d for d in local_dbs if d.get("name") == db_name), None)
        if not db_config:
            return {"error": f"database '{db_name}' not registered"}

        # Parse and validate SQL: single SELECT statement only
        sql_upper = sql_query.upper().strip()

        # Check for forbidden keywords by TOKEN, not substring: a space-delimited
        # " PRAGMA " check misses SQLite's pragma virtual-table functions
        # (pragma_table_info(...), pragma_database_list — no space after
        # "pragma", so " PRAGMA " never matches, and they read PRAGMA-equivalent
        # schema/state without ever using the PRAGMA statement keyword). Extract
        # every identifier-shaped token and reject an exact forbidden keyword OR
        # any identifier starting with "pragma_" (SQLite's whole family of
        # pragma_* table-valued functions), so both spellings are caught. This
        # runs BEFORE the "starts with SELECT" check so e.g. a bare "INSERT ..."
        # still reports the specific operation, not the generic message.
        forbidden = {"INSERT", "UPDATE", "DELETE", "PRAGMA", "ATTACH", "DETACH", "ALTER", "DROP"}
        for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql_query):
            tok_upper = tok.upper()
            if tok_upper in forbidden or tok_upper.startswith("PRAGMA_"):
                return {"error": f"operation '{tok}' not allowed (SELECT-only)"}

        # Ensure starts with SELECT
        if not sql_upper.startswith("SELECT"):
            return {"error": "only SELECT queries allowed"}

        # Check for multiple statements (semicolon not in string literal)
        in_string = False
        quote_char = None
        stmt_count = 0
        for i, c in enumerate(sql_query):
            if c in ('"', "'") and (i == 0 or sql_query[i-1] != "\\"):
                if not in_string:
                    in_string = True
                    quote_char = c
                elif c == quote_char:
                    in_string = False
            elif c == ";" and not in_string:
                stmt_count += 1
        if stmt_count > 0:
            # Allow trailing semicolon but reject multiple statements
            if not sql_query.rstrip().endswith(";") or stmt_count > 1:
                return {"error": "multiple statements not allowed"}

        # Open read-only connection and execute
        try:
            db_path = db_config.get("path")
            if not db_path:
                return {"error": f"database '{db_name}' has no path configured"}

            # Expand home directory
            from pathlib import Path
            db_path = str(Path(db_path).expanduser())

            # Open read-only: URI with mode=ro
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute(sql_query)
                rows = cursor.fetchmany(50)  # Cap at 50 rows
                result_rows = [dict(r) for r in rows]
                return {
                    "provenance": {"db": db_name, "path": db_path, "read_only": True},
                    "rows": result_rows,
                    "count": len(result_rows),
                    "limited": cursor.rowcount > 50 if cursor.rowcount >= 0 else False
                }
            finally:
                conn.close()
        except sqlite3.Error as e:
            return {"error": f"query failed: {str(e)}"}
        except Exception as e:
            return {"error": f"unexpected error: {str(e)}"}

    def _t_plan_context(self, principal, a):
        return self.core.reasoning.plan_context(a["goal"])

    def _t_active_goals(self, principal, a):
        return {"goals": self.core.reasoning.active_goals()}

    def _t_what_user_knows(self, principal, a):
        return {"knows": self.core.epistemic.what_user_knows(a["topic"])}
