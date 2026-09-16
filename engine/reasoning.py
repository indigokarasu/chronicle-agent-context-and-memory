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

from . import access
from .store import now_iso

# The identity a goal/reflection row written BEFORE schema_version 13 is read
# as (ladder-10 A1b). Those rows have owner IS NULL: nobody recorded who wrote
# them, and inventing an owner would be a lie the store then carries forever.
#
# "default" is the pre-topology principal this codebase already uses for the
# unattributed case (ChronicleCore.active_principal's initial value,
# EpistemicModel.note_informed's owner default, rerank_hints' v11 backfill), and
# resolving NULL to it makes the legacy rule fall out of access.can_read rather
# than being restated beside it:
#
#   * no `principals:` config (the single-principal install every legacy row
#     actually comes from): can_read's legacy ceiling is same-user, user_of()
#     of an un-namespaced id is "_user" for BOTH sides, so the row stays
#     visible exactly as it was before this column existed;
#   * any configured topology: "default" is not a declared agent, shares no
#     user with one, and no `reads` edge can name it -- so every declared
#     principal is DENIED, sandboxed and foreign ones included. Fail closed.
#
# The cost is stated rather than hidden: under a topology a principal cannot
# read even its OWN pre-13 rows, because the store never recorded that they
# were its own. Losing sight of an unattributed row is the recoverable failure;
# handing a sandbox's dossier to its sibling is not.
LEGACY_OWNER = "default"

# The access-control machinery on a goal/reflection row. Stripped before the row
# is returned to a caller (ReasoningLayer._public): these two columns are how
# the gate decides, not content the surface is there to deliver, and printing
# them would tell every reader WHO owns each memory -- attribution metadata the
# rest of the read paths do not emit either. Keeping them out also means A1b
# leaves the shape of active_goals()/recall_similar_situations() exactly as it
# was, so the single-principal default case is byte-identical rather than
# byte-identical-except-for-two-new-keys.
_ACL_COLUMNS = ("owner", "read_acl")


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

    def what_user_knows(self, topic: str, principal: str = "default") -> list[dict]:
        """(A1) user_knowledge carries owner + read_acl like any other belief
        table, and a proposition is content -- so this listing goes through the
        same access.can_read choke point every retrieval channel uses."""
        rows = self.store.query_user_knowledge("proposition LIKE ?", (f"%{topic}%",), limit=20)
        return [{"proposition": r["proposition"], "state": r["state"],
                 "last_communicated": r["last_communicated"],
                 "times_communicated": r["times_communicated"]} for r in rows
                if access.can_read(r.get("read_acl"), r.get("owner"), principal)]

    def annotate(self, belief: dict, principal: str = "default") -> str:
        """get_context annotation: suppress recently-told, flag likely-forgotten/never-told.

        (A1) The annotation is user-visible output derived from user_knowledge
        rows, which carry owner + read_acl -- so the rows go through the same
        access.can_read choke point. An unreadable row cannot flip the
        annotation, which is a one-bit disclosure that SOMEONE recorded telling
        the user this. `principal` defaults to the pre-topology "default"
        identity, which under a configured topology matches nothing and so can
        only under-report -- never widen."""
        val = belief.get("value") or ""
        if not val:
            return ""
        rows = [r for r in self.store.query_user_knowledge(
                    "proposition LIKE ?", (f"%{val[:40]}%",), limit=5)
                if access.can_read(r.get("read_acl"), r.get("owner"), principal)]
        if not rows:
            return "why=never_told" if (belief.get("criticality") in ("high", "critical")) else ""
        return "why=likely_forgotten"


class ReasoningLayer:
    """§23 — goals, procedures, reflection, metacognitive gate."""

    def __init__(self, core):
        self.core = core
        self.store = core.store

    # -- the ACL choke point for goals and reflections (A1b) ---------------
    #
    # THE one place a goals/reflections row is decided on. A1 routed every
    # other user-visible read through access.can_read, but could not close
    # these two: the tables carried no owner and no read_acl, so there was
    # nothing to decide. schema_version 13 adds that pair; this method is the
    # single gate that consults it, so active_goals(), recall_similar_
    # situations() and the write path cannot drift apart, and a future surface
    # over either table has one thing to reuse.

    def _readable_row(self, row, principal: str) -> bool:
        """Whether `principal` may see one goal/reflection row (§15, A1b).

        No ACL rule is restated here: the decision is access.can_read's, on the
        row's own read_acl and owner. The one thing this adds is the legacy
        resolution -- owner IS NULL (a row written before schema_version 13)
        reads as LEGACY_OWNER, which fails closed under any configured
        topology. See LEGACY_OWNER for why that identity and not another."""
        return access.can_read(row.get("read_acl"), row.get("owner") or LEGACY_OWNER,
                               principal)

    def _public(self, row: dict) -> dict:
        """One row as a read surface renders it: content, not ACL machinery."""
        return {k: v for k, v in row.items() if k not in _ACL_COLUMNS}

    def _stamp(self, principal: str) -> dict:
        """The owner/read_acl pair every goal and reflection write carries.

        A write that skipped this would mint a row indistinguishable from a
        pre-13 legacy one, which is the one shape the read gate has to be
        lenient about -- so an unstamped write is a hole in the gate, not just
        a missing field."""
        return {"owner": principal or self.core.active_principal,
                "read_acl": access.DEFAULT_ACL}

    # goals
    def remember_goal(self, goal: str, principal: str = "") -> str:
        gid = "goal_" + uuid.uuid4().hex[:12]
        row = {"id": gid, "goal": goal, "status": "active",
               "created_at": now_iso(), "updated_at": now_iso()}
        row.update(self._stamp(principal))
        self.store.upsert_goal(row)
        return gid

    def update_goal(self, goal_id: str, status: str, principal: str = ""):
        """Flip a goal's status, for a goal THIS principal may read (A1b).

        upsert_goal is an INSERT ... ON CONFLICT, so before A1b an update
        naming a stranger's -- or a nonexistent -- id silently wrote the row
        anyway, with no owner at all. Two consequences, both closed here: it
        was a cross-principal write, and the row it minted was unattributed,
        i.e. it manufactured a fresh 'legacy' row the read gate then had to be
        lenient about.

        An unreadable target is a silent no-op that returns exactly what a
        successful update returns (None). Goal ids appear in tool output, so
        raising or reporting would turn a guessed id into an existence
        oracle -- the same shape history()/explain() settled on in A1."""
        principal = principal or self.core.active_principal
        row = self.store.get_goal(goal_id)
        if row is not None and not self._readable_row(row, principal):
            return
        patch = {"id": goal_id, "status": status, "updated_at": now_iso()}
        # Keep the existing attribution; only an id that does not exist yet (or
        # a legacy row this principal was already allowed to read) takes this
        # principal's stamp. An update must never RE-owner someone else's goal.
        patch["owner"] = (row or {}).get("owner") or (principal or self.core.active_principal)
        patch["read_acl"] = (row or {}).get("read_acl") or access.DEFAULT_ACL
        self.store.upsert_goal(patch)

    def active_goals(self, principal: str = ""):
        """(A1b) Standing goals THIS principal may read.

        Reaches user-visible output twice: the chronicle_active_goals tool and
        plan_context's `standing_goals`. Filtered AFTER the store's own query,
        deliberately not by widening it -- back-filling a restricted
        principal's listing with extra rows would make the count itself report
        on rows it may not see (A1, RetrievalEngine.open_contradictions)."""
        principal = principal or self.core.active_principal
        return [self._public(g) for g in self.store.get_active_goals()
                if self._readable_row(g, principal)]

    # procedures
    def get_procedure(self, name: str, params: dict | None = None, principal: str = ""):
        """(A1) A procedure's steps are content: filtered at the choke point,
        via the retrieval engine's own _readable so this surface cannot drift
        from what search()/ask_about() would have allowed."""
        principal = principal or self.core.active_principal
        rows = self.store.query_beliefs("procedures", "name=? AND status='active'", (name,), 1)
        if not rows:
            sims = self.store.fts_search_beliefs(name, limit=3)
            for s in sims:
                if s["kind"] == "procedure":
                    rows = [self.store.get_belief("procedures", s["belief_id"])]
                    break
        if not rows or not rows[0]:
            return None
        if not self.core.retrieval._readable(rows[0], principal, "*", None):
            return None
        proc = rows[0]
        return {"name": proc["name"], "params": json.loads(proc.get("params") or "[]"),
                "steps": json.loads(proc.get("steps") or "[]"),
                "success_criteria": json.loads(proc.get("success_criteria") or "[]"),
                "instantiated_with": params or {}}

    # reflection
    def reflect(self, situation: str, action: str, outcome: str, lesson: str,
                applicability: str = "", principal: str = ""):
        principal = principal or self.core.active_principal
        rid = "refl_" + uuid.uuid4().hex[:12]
        row = {"id": rid, "situation": situation, "action": action,
               "outcome": outcome, "lesson": lesson, "applicability": applicability,
               "created_at": now_iso()}
        # (A1b) The reflection row is stamped with the SAME principal the
        # derived note below is owned by. They are two records of one thought;
        # attributing them differently would let the note be filtered out of a
        # reader's context while the reflection it came from stayed visible.
        row.update(self._stamp(principal))
        self.store.add_reflection(row)
        # Durable lessons → procedure note (§23).
        if lesson and len(lesson) > 12:
            self.core.capture.append("asserted", {
                "kind": "note", "key": {"note_type": "procedure", "subject": situation[:40]},
                "body": lesson, "confidence": 0.7, "source_event": rid, "source_type": "agent_memory_write"},
                actor="agent", owner=principal)
        return rid

    def recall_similar_situations(self, situation: str, limit: int = 3, principal: str = ""):
        """(A1b) Reflections THIS principal may read.

        The leak A1 reported and could not close: this is plan_context's
        `similar_situations`, so a sandboxed agent's reflection text -- its
        situation, its lesson -- was composed into another principal's plan
        context verbatim. Same choke point, same post-query filtering rule as
        active_goals()."""
        principal = principal or self.core.active_principal
        return [self._public(r) for r in self.store.search_reflections(situation, limit)
                if self._readable_row(r, principal)]

    # plan_context (§23)
    def plan_context(self, goal: str, budget: int = 1500, principal: str = "") -> dict:
        """Every component composed here is filtered for `principal` (A1b).

        The bundle is user-visible output, and it has five sources: `facts`
        (search() -> _readable), `procedures` (get_procedure -> _readable),
        `similar_situations` (recall_similar_situations -> _readable_row),
        `standing_goals` (active_goals -> _readable_row), and `gate`, which is
        computed from the ALREADY-filtered facts and so cannot see anything
        they could not. A1 closed the first two; A1b closes the middle two,
        which had no owner column to be closed against."""
        r = self.core.retrieval
        principal = principal or self.core.active_principal
        facts = r.search(goal, limit=8, principal=principal)
        proc = self.get_procedure(goal, principal=principal)
        reflections = self.recall_similar_situations(goal, principal=principal)
        gate = self._metacognitive_gate(facts)
        return {
            "goal": goal,
            "facts": facts,
            "procedures": [proc] if proc else [],
            "similar_situations": reflections,
            "standing_goals": [g["goal"] for g in self.active_goals(principal)],
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
