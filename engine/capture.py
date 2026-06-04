"""
Chronicle — Capture engine (§12).

Handles hook → durable event conversion, session management, reaper.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Optional

from .serialize import event_id, cjson_dumps, content_hash

logger = logging.getLogger("chronicle.capture")


class CaptureEngine:
    """Converts Hermes hook calls into durable events."""

    def __init__(self, store, reducer, owner: str = "default"):
        self.store = store
        self.reducer = reducer
        self.owner = owner

    def _now(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def _append(self, type_: str, payload: dict, *,
                parents: list[str] | None = None,
                actor: str = "agent",
                owner: str | None = None,
                trust_level: int = 2,
                session_id: str | None = None,
                branch_id: str | None = None,
                occurred_at: str | None = None) -> str:
        """Append a durable event and run the reducer."""
        now = self._now()
        if parents is None:
            parents = []
        if owner is None:
            owner = self.owner
        if occurred_at is None:
            occurred_at = now

        eid = event_id(type_, payload, parents, actor, occurred_at)

        # Check if already exists (idempotent)
        existing = self.store.get_event(eid)
        if existing:
            return eid

        prev_head = self.store.get_head_event_id()

        event = {
            "event_id": eid,
            "type": type_,
            "payload": payload,
            "parents": parents,
            "actor": actor,
            "owner": owner,
            "trust_level": trust_level,
            "session_id": session_id,
            "branch_id": branch_id,
            "occurred_at": occurred_at,
            "recorded_at": now,
            "prev_head": prev_head,
            "sig": None,
        }

        self.store.append_event(event)
        self.reducer.reduce(event)
        return eid

    def observe(self, user_content: str, assistant_content: str, *,
                session_id: str = "",
                messages: list[dict] | None = None,
                trust_level: int = 2) -> str:
        """sync_turn: append a durable observed event (§12.1, I12)."""
        # Build excerpt from the turn
        excerpt = f"User: {user_content}\nAssistant: {assistant_content}"
        if messages:
            # Use full messages for richer context
            excerpt = "\n".join(
                f"{m.get('role','?')}: {m.get('content','')}"
                for m in messages[-10:]  # last 10 messages
            )

        payload = {
            "source_type": "session_transcript",
            "excerpt": excerpt[:4000],  # cap excerpt size
            "source_ref": session_id,
        }

        eid = self._append(
            "observed", payload,
            actor="user" if user_content else "agent",
            session_id=session_id or None,
            trust_level=trust_level,
        )

        # Update session
        if session_id:
            self._touch_session(session_id)

        return eid

    def agent_explicit(self, action: str, target: str, content: str,
                       metadata: dict | None = None):
        """on_memory_write: high-precision agent memory write (§12.3)."""
        payload = {
            "source_type": "agent_memory_write",
            "excerpt": content[:4000],
            "action": action,
            "target": target,
            "metadata": metadata or {},
        }
        self._append("observed", payload, actor="agent", trust_level=3)

    def rescue_extract(self, messages: list[dict]) -> tuple[list[str], str]:
        """Two-speed rescue extraction (§12.6).

        Returns (event_ids, summary_text).
        """
        event_ids = []
        summaries = []

        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue
            # Quick salience check: keep if it looks important
            # (simple heuristic: contains key phrases)
            is_important = any(
                kw in content.lower()
                for kw in ["remember", "always", "never", "important",
                           "must", "should", "critical", "note:"]
            )
            if is_important and len(content) > 20:
                payload = {
                    "source_type": "rescue_extraction",
                    "excerpt": content[:2000],
                    "document_id": str(uuid.uuid4()),
                }
                eid = self._append("observed", payload, actor="system")
                event_ids.append(eid)
                summaries.append(content[:200])

        summary_text = "\n".join(summaries) if summaries else ""
        return event_ids, summary_text

    def delegation(self, task: str, result: str, *,
                   child_session_id: str = ""):
        """on_delegation: episode + outcome."""
        now = self._now()
        payload = {
            "source_type": "delegation",
            "excerpt": f"Task: {task}\nResult: {result}",
            "task": task,
            "result": result,
            "child_session_id": child_session_id,
        }
        self._append("observed", payload, actor="agent")

    def finalize_session(self, session_id: str, via: str = "clean_exit"):
        """Mark session as ended and enqueue final extraction."""
        now = self._now()
        session = self.store.get_session(session_id)
        if session and session.get("status") in ("ended", "reaped"):
            return  # Already finalized

        self.store.upsert_session({
            "session_id": session_id,
            "status": "ended" if via != "reaped" else "reaped",
            "ended_via": via,
            "ended_at": now,
        })

        # Enqueue final extraction for any remaining observed events
        if session:
            self.store.enqueue_curation("session_summarize", {
                "session_id": session_id,
            })

        logger.info(f"Session {session_id} finalized via {via}")

    def _touch_session(self, session_id: str):
        """Update session activity timestamp."""
        now = self._now()
        existing = self.store.get_session(session_id)
        if existing:
            self.store.upsert_session({
                "session_id": session_id,
                "last_activity_at": now,
            })
        else:
            self.store.upsert_session({
                "session_id": session_id,
                "status": "active",
                "started_at": now,
                "last_activity_at": now,
                "last_extracted_seq": 0,
            })


class Reaper:
    """Guarantees I13: finalizes stale sessions independently."""

    def __init__(self, store, capture: CaptureEngine,
                 idle_threshold: str = "20m",
                 reap_threshold: str = "45m"):
        self.store = store
        self.capture = capture
        self.idle_threshold = self._parse_duration(idle_threshold)
        self.reap_threshold = self._parse_duration(reap_threshold)

    def _parse_duration(self, s: str) -> datetime.timedelta:
        """Parse duration like '20m', '45m', '2h'."""
        s = s.strip()
        if s.endswith("m"):
            return datetime.timedelta(minutes=int(s[:-1]))
        if s.endswith("h"):
            return datetime.timedelta(hours=int(s[:-1]))
        if s.endswith("s"):
            return datetime.timedelta(seconds=int(s[:-1]))
        return datetime.timedelta(minutes=20)

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def _parse_ts(self, ts: str) -> datetime.datetime:
        """Parse RFC3339 timestamp."""
        if not ts:
            return self._now()
        try:
            return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return self._now()

    def run(self):
        """Run the reaper sweep."""
        stale = self.store.get_stale_sessions()
        for session in stale:
            sid = session["session_id"]
            last_activity = self._parse_ts(session.get("last_activity_at", ""))
            idle = self._now() - last_activity

            if idle > self.reap_threshold:
                self.capture.finalize_session(sid, "reaped")
                logger.info(f"Reaped session {sid} (idle {idle})")
            elif idle > self.idle_threshold and session.get("status") == "active":
                self.store.upsert_session({
                    "session_id": sid,
                    "status": "idle",
                })

    def startup_recovery(self):
        """On startup: finalize any sessions left active from a crash."""
        stale = self.store.get_stale_sessions()
        for session in stale:
            if session.get("status") == "active":
                self.capture.finalize_session(session["session_id"], "crash_recovered")
                logger.info(f"Recovered crashed session {session['session_id']}")
