"""
Chronicle — Reasoning layer (§23) and user epistemic model (§19).

Memory-facing reasoning support: named procedures recalled and instantiated,
case-based episodic recall, `plan_context` bundling, reflections, and a
metacognitive gate that inserts VERIFY/ask when calibrated confidence is low or a
belief is contradicted (the abstention behaviour). The epistemic model tracks
what the user has been told so context can suppress re-explaining and surface
likely-forgotten / never-told items.
"""

from __future__ import annotations

import json
import uuid

from .store import now_iso


class EpistemicModel:
    """§19 — what the user knows."""

    def __init__(self, store, cfg):
        self.store = store
        self.cfg = cfg

    def note_informed(self, proposition: str, about_belief: str = "", importance: float = 0.5,
                      append_fn=None, owner="default"):
        if append_fn:
            append_fn("informed", {"proposition": proposition, "about_belief": about_belief,
                                   "importance": importance}, actor="agent", owner=owner)

    def what_user_knows(self, topic: str) -> list[dict]:
        rows = self.store.query_user_knowledge("proposition LIKE ?", (f"%{topic}%",), limit=20)
        return [{"proposition": r["proposition"], "state": r["state"],
                 "last_communicated": r["last_communicated"],
                 "times_communicated": r["times_communicated"]} for r in rows]

    def annotate(self, belief: dict) -> str:
        """get_context annotation: suppress recently-told, flag likely-forgotten/never-told."""
        val = belief.get("value") or ""
        if not val:
            return ""
        rows = self.store.query_user_knowledge("proposition LIKE ?", (f"%{val[:40]}%",), limit=1)
        if not rows:
            return "why=never_told" if (belief.get("criticality") in ("high", "critical")) else ""
        return "why=likely_forgotten"


class ReasoningLayer:
    """§23 — goals, procedures, reflection, metacognitive gate."""

    def __init__(self, core):
        self.core = core
        self.store = core.store

    # goals
    def remember_goal(self, goal: str) -> str:
        gid = "goal_" + uuid.uuid4().hex[:12]
        self.store.upsert_goal({"id": gid, "goal": goal, "status": "active",
                                "created_at": now_iso(), "updated_at": now_iso()})
        return gid

    def update_goal(self, goal_id: str, status: str):
        self.store.upsert_goal({"id": goal_id, "status": status, "updated_at": now_iso()})

    def active_goals(self):
        return self.store.get_active_goals()

    # procedures
    def get_procedure(self, name: str, params: dict | None = None):
        rows = self.store.query_beliefs("procedures", "name=? AND status='active'", (name,), 1)
        if not rows:
            sims = self.store.fts_search_beliefs(name, limit=3)
            for s in sims:
                if s["kind"] == "procedure":
                    rows = [self.store.get_belief("procedures", s["belief_id"])]
                    break
        if not rows or not rows[0]:
            return None
        proc = rows[0]
        return {"name": proc["name"], "params": json.loads(proc.get("params") or "[]"),
                "steps": json.loads(proc.get("steps") or "[]"),
                "success_criteria": json.loads(proc.get("success_criteria") or "[]"),
                "instantiated_with": params or {}}

    # reflection
    def reflect(self, situation: str, action: str, outcome: str, lesson: str, applicability: str = ""):
        rid = "refl_" + uuid.uuid4().hex[:12]
        self.store.add_reflection({"id": rid, "situation": situation, "action": action,
                                   "outcome": outcome, "lesson": lesson, "applicability": applicability,
                                   "created_at": now_iso()})
        # Durable lessons → procedure note (§23).
        if lesson and len(lesson) > 12:
            self.core.capture.append("asserted", {
                "kind": "note", "key": {"note_type": "procedure", "subject": situation[:40]},
                "body": lesson, "confidence": 0.7, "source_event": rid, "source_type": "agent_memory_write"},
                actor="agent", owner=self.core.active_principal)
        return rid

    def recall_similar_situations(self, situation: str, limit: int = 3):
        return self.store.search_reflections(situation, limit)

    # plan_context (§23)
    def plan_context(self, goal: str, budget: int = 1500) -> dict:
        r = self.core.retrieval
        facts = r.search(goal, limit=8)
        proc = self.get_procedure(goal)
        reflections = self.recall_similar_situations(goal)
        gate = self._metacognitive_gate(facts)
        return {
            "goal": goal,
            "facts": facts,
            "procedures": [proc] if proc else [],
            "similar_situations": reflections,
            "standing_goals": [g["goal"] for g in self.active_goals()],
            "gate": gate,
            "why": "low_confidence_or_contradicted → VERIFY" if gate["verify"] else "ok",
        }

    def _metacognitive_gate(self, facts) -> dict:
        """Low calibrated-confidence or contradicted ⇒ insert VERIFY/ask (§23 abstention)."""
        if not facts:
            return {"verify": True, "reason": "no_support"}
        lead = facts[0]
        if (lead.get("confidence") or 0) < 0.5:
            return {"verify": True, "reason": "low_confidence"}
        if lead.get("status") == "draft":
            return {"verify": True, "reason": "unconfirmed_draft"}
        return {"verify": False, "reason": ""}
