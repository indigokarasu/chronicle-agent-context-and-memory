"""
Chronicle — Capture engine (§12).

Durability at capture; every hook best-effort; a reaper guarantees the work.
`observe` is the I12 anchor: it appends a durable `observed` event (one local
txn, no network) and returns. Heavy understanding is deferred to curation. The
reaper + startup recovery finalize sessions independent of `on_session_end`
(I13), making the system crash-only.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import List, Optional, Tuple

from .serialize import event_id, hash_str
from .criticality import classify as classify_criticality
from .store import now_iso

logger = logging.getLogger("chronicle.capture")

_RESCUE_KW = ["remember", "always", "never", "important", "must", "should",
              "critical", "note:", "don't", "do not", "allerg", "medication"]


class CaptureEngine:
    def __init__(self, store, reducer, owner: str = "default", extractor_version: str = "extractor-v1"):
        self.store = store
        self.reducer = reducer
        self.owner = owner
        self.extractor_version = extractor_version
        if self.store.reducer is None:      # ensure append() runs the inline reduce (I7)
            self.store.reducer = reducer

    def _now(self) -> str:
        return now_iso()

    # -- the single append path -------------------------------------------

    def append(self, type_: str, payload: dict, *, parents=None, actor="agent",
               owner: Optional[str] = None, trust_level: int = 2,
               session_id: Optional[str] = None, branch_id: Optional[str] = None,
               occurred_at: Optional[str] = None) -> str:
        now = self._now()
        owner = owner or self.owner
        occurred_at = occurred_at or now
        parents = parents or []
        eid = event_id(type_, payload, parents, actor, occurred_at)
        return self.store.append_event({
            "event_id": eid, "type": type_, "payload": payload, "parents": parents,
            "actor": actor, "owner": owner, "trust_level": trust_level,
            "session_id": session_id, "branch_id": branch_id or session_id,
            "occurred_at": occurred_at, "recorded_at": now,
            "prev_head": self.store.get_head_event_id(), "sig": None})

    # -- hooks → events ----------------------------------------------------

    def observe(self, user_content: str, assistant_content: str, *, session_id: str = "",
                messages: Optional[List[dict]] = None, trust_level: int = 2) -> str:
        """sync_turn: durable observed event (§12.1, I12)."""
        if messages:
            excerpt = "\n".join(f"{m.get('role','?')}: {m.get('content','')}" for m in messages[-12:])
        else:
            excerpt = f"User: {user_content}\nAssistant: {assistant_content}"
        excerpt = excerpt[:4000]
        if self.store.is_forbidden(hash_str(excerpt)):
            return ""  # forbidden content is never re-captured
        eid = self.append("observed",
                          {"source_type": "session_transcript", "excerpt": excerpt, "source_ref": session_id},
                          actor="user" if user_content else "agent",
                          session_id=session_id or None, trust_level=trust_level)
        if session_id:
            self._touch_session(session_id)
        return eid

    def agent_explicit(self, action: str, target: str, content: str, metadata=None) -> str:
        """on_memory_write: highest-precision signal, no confidence discount (§12.3)."""
        return self.append("observed",
                           {"source_type": "agent_memory_write", "excerpt": content[:4000],
                            "action": action, "target": target, "metadata": metadata or {},
                            "salience": "high"},
                           actor="agent", trust_level=3)

    def delegation(self, task: str, result: str, *, child_session_id: str = "") -> str:
        return self.append("observed",
                           {"source_type": "delegation", "excerpt": f"Task: {task}\nResult: {result}",
                            "task": task, "result": result, "child_session_id": child_session_id},
                           actor="agent")

    def rescue(self, messages: List[dict], *, session_id: str = "") -> Tuple[List[str], str]:
        """Two-speed rescue (§12.6, I14): durably persist + fast-extract high-salience spans
        to `asserted(draft, salience=high)` so nothing critical is lost on eviction."""
        belief_events, summaries = [], []
        for msg in messages:
            content = (msg.get("content") or "").strip()
            if len(content) < 20:
                continue
            crit, _ = classify_criticality(content)
            important = crit != "normal" or any(kw in content.lower() for kw in _RESCUE_KW)
            if not important:
                continue
            # 1) raw durability (recall floor) + 2) draft belief (I14)
            obs = self.append("observed",
                             {"source_type": "rescue_extraction", "excerpt": content[:2000],
                              "source_ref": session_id, "document_id": str(uuid.uuid4())},
                             actor="system", session_id=session_id or None)
            note_type = "norm" if any(k in content.lower() for k in ["always", "never", "must", "don't", "do not"]) else "belief"
            self.append("asserted",
                       {"kind": "note", "key": {"note_type": note_type, "subject": "rescued", "salience": "high"},
                        "body": content[:500], "confidence": 0.7, "source_event": obs,
                        "source_type": "rescue_extraction", "status": "draft"},
                       actor="system", session_id=session_id or None)
            belief_events.append(obs)
            summaries.append(content[:200])
        return belief_events, ("\n".join(summaries) if summaries else "")

    # -- sessions & reaper -------------------------------------------------

    def finalize_session(self, session_id: str, via: str = "clean_exit"):
        """Mark ended + enqueue final extraction for unprocessed spans (§12.4, I13). Idempotent."""
        if not session_id:
            return
        s = self.store.get_session(session_id)
        if s and s.get("status") in ("ended", "reaped"):
            return
        last_seq = (s or {}).get("last_extracted_seq", 0)
        pending = self.store.get_events_by_session(session_id, since_seq=last_seq)
        max_seq = last_seq
        for ev in pending:
            if ev["type"] == "observed":
                self.store.enqueue_curation("extract", {"event_id": ev["event_id"], "session_id": session_id})
            max_seq = max(max_seq, ev["seq"])
        self.store.enqueue_curation("session_summarize", {"session_id": session_id})
        self.store.upsert_session({
            "session_id": session_id, "status": "reaped" if via == "reaped" else "ended",
            "ended_via": via, "ended_at": self._now(), "last_extracted_seq": max_seq})
        logger.info("Session %s finalized via %s (%d pending)", session_id, via, len(pending))

    def _touch_session(self, session_id: str):
        now = self._now()
        if self.store.get_session(session_id):
            self.store.upsert_session({"session_id": session_id, "last_activity_at": now})
        else:
            self.store.upsert_session({"session_id": session_id, "status": "active", "started_at": now,
                                       "last_activity_at": now, "last_extracted_seq": 0})

    def flush_best_effort(self):
        pass  # not relied upon (§12.3 shutdown)


class Reaper:
    """Finalizes stale sessions independently → I13."""

    def __init__(self, store, capture: CaptureEngine, idle_threshold: str = "20m",
                 reap_threshold: str = "45m"):
        self.store = store
        self.capture = capture
        self.idle_threshold = _parse_duration(idle_threshold)
        self.reap_threshold = _parse_duration(reap_threshold)

    def run(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        for s in self.store.get_sessions_by_status(["active", "idle"]):
            idle = now - _parse_ts(s.get("last_activity_at"))
            if idle > self.reap_threshold:
                self.capture.finalize_session(s["session_id"], "reaped")
            elif idle > self.idle_threshold and s.get("status") == "active":
                self.store.upsert_session({"session_id": s["session_id"], "status": "idle"})

    def startup_recovery(self):
        """Every crash leaves observed events past last_extracted_seq; finalize them (§12.4)."""
        for s in self.store.get_sessions_by_status(["active", "idle"]):
            self.capture.finalize_session(s["session_id"], "crash_recovered")


def _parse_duration(s: str) -> datetime.timedelta:
    s = (s or "").strip()
    try:
        if s.endswith("m"):
            return datetime.timedelta(minutes=int(s[:-1]))
        if s.endswith("h"):
            return datetime.timedelta(hours=int(s[:-1]))
        if s.endswith("s"):
            return datetime.timedelta(seconds=int(s[:-1]))
    except ValueError:
        pass
    return datetime.timedelta(minutes=20)


def _parse_ts(ts: str) -> datetime.datetime:
    if not ts:
        return datetime.datetime.now(datetime.timezone.utc)
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.datetime.now(datetime.timezone.utc)
