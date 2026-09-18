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
import re
import uuid

from . import speaker as spk
from .criticality import classify as classify_criticality
from .serialize import event_id, hash_str
from .store import now_iso

logger = logging.getLogger("chronicle.capture")

_RESCUE_KW = ["remember", "always", "never", "important", "must", "should",
              "critical", "note:", "don't", "do not", "allerg", "medication"]

# Excerpt chunking (§12.1). capture.max_excerpt_chars, clamped: a cap below
# _CAP_MIN shreds turns into unreadable confetti, above _CAP_MAX defeats the
# point of a bounded event payload.
_CAP_DEFAULT, _CAP_MIN, _CAP_MAX = 4000, 500, 16000
_MSG_START = re.compile(r"\n(?=[^\s:][^:\n]{0,32}: )")   # next "role: …" message
_SENTENCE_END = re.compile(r"[.!?]\s|\n")


def _split_excerpt(text: str, cap: int) -> list[str]:
    """Chunk `text` into pieces of at most `cap` chars — §12.1, no silent truncation.

    Boundary preference: start of the next message ("role: …") > last sentence
    end ([.!?]\\s or newline) before `cap` > hard character cut. ``"".join`` of
    the result reproduces `text` byte for byte; that losslessness is the point.
    """
    if len(text) <= cap:
        return [text]
    chunks, pos = [], 0
    while pos < len(text):
        rest = text[pos:]
        if len(rest) <= cap:
            chunks.append(rest)
            break
        window = rest[:cap]
        cut = 0
        for rx in (_MSG_START, _SENTENCE_END):
            found = list(rx.finditer(window))
            if found:
                cut = found[-1].end()       # last boundary that still fits
                break
        cut = cut or cap                    # last resort: hard cut, still lossless
        chunks.append(window[:cut])
        pos += cut
    return chunks


class CaptureEngine:
    def __init__(self, store, reducer, owner: str = "default", extractor_version: str = "extractor-v1",
                 cfg=None):
        self.store = store
        self.reducer = reducer
        self.owner = owner
        self.extractor_version = extractor_version
        self.cfg = cfg
        if self.store.reducer is None:      # ensure append() runs the inline reduce (I7)
            self.store.reducer = reducer

    def _now(self) -> str:
        return now_iso()

    def _excerpt_cap(self) -> int:
        """capture.max_excerpt_chars, clamped to [_CAP_MIN, _CAP_MAX] (§12.1, §27)."""
        try:
            cap = int(self.cfg.get("capture.max_excerpt_chars", _CAP_DEFAULT)) if self.cfg else _CAP_DEFAULT
        except (TypeError, ValueError):
            cap = _CAP_DEFAULT
        return max(_CAP_MIN, min(_CAP_MAX, cap))

    # -- the single append path -------------------------------------------

    def append(self, type_: str, payload: dict, *, parents=None, actor="agent",
               owner: str | None = None, trust_level: int = 2,
               session_id: str | None = None, branch_id: str | None = None,
               occurred_at: str | None = None) -> str:
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

    def append_many(self, events: list[dict], *, window: int = 64) -> list[str]:
        """Append a KNOWN run of events, embedding each window's text in one round trip.

        `events` is a list of dicts shaped like append()'s arguments —
        ``{"type": …, "payload": …}`` plus any keyword append() itself accepts.
        Every event still goes through append(): same ids, same order, same one
        transaction per event, same inline reduce, same vectors. The store ends
        up byte-identical to the equivalent append() loop (test_build covers
        this). The only thing that changes is that the embeddings for a window
        are fetched together instead of one blocking round trip per event, which
        is where a bulk ingest against a networked embedder spends ~all of its
        wall clock.

        For streaming capture (one turn at a time, which is what `observe` does)
        there is nothing to batch and nothing here to use — this is for backfills
        and transcript imports, where the whole run is in hand up front.
        """
        out: list[str] = []
        window = max(1, int(window or 1))
        try:
            for i in range(0, len(events), window):
                chunk = events[i:i + window]
                self.reducer.prefetch_vectors(chunk)
                for spec in chunk:
                    spec = dict(spec)
                    out.append(self.append(spec.pop("type"), spec.pop("payload"), **spec))
        finally:
            self.reducer.prefetch_vectors(())   # never leave a window resident
        return out

    # -- hooks → events ----------------------------------------------------

    def observe(self, user_content: str, assistant_content: str, *, session_id: str = "",
                messages: list[dict] | None = None, trust_level: int = 2,
                occurred_at: str | None = None, speaker_context: dict | None = None) -> str:
        """sync_turn: durable observed event(s) (§12.1, I12).

        A long turn is chunked, never truncated: one `observed` event per chunk,
        every sibling carrying the turn's session_id / actor / occurred_at /
        source_ref. `chunk_index` is what keeps their ids apart — event_id hashes
        the payload (§5.3) and append_event dedups on it (I2), so byte-identical
        chunks would otherwise collapse into one event, i.e. silent data loss.
        Returns the first chunk's eid; signature unchanged.

        Who said what is decided here (engine/speaker.py) and recorded on the
        chunk as `speakers` spans over its excerpt plus `attribution`, the host
        context it was decided from. `speaker_context` is what the host told the
        provider (agent_context, platform, the turn author); a host that says
        nothing is a person typing, unless the session is a scheduled job's. The
        actor is `user` only when the user side of the turn is a person.

        The record is omitted only when it adds nothing: no host context, a
        person on the user side, and labels that the legacy reading attributes
        exactly as the spans do. Such a chunk's payload, and so its event id, is
        the same as before attribution existed.
        """
        ctx = speaker_context or {}
        author = ctx.get("author") if isinstance(ctx.get("author"), dict) else None
        side = spk.user_side(agent_context=ctx.get("agent_context", ""),
                             platform=ctx.get("platform", ""),
                             session_id=session_id, author=author)
        if messages:
            excerpt, spans = spk.render_messages(messages[-12:], side)
        else:
            excerpt, spans = spk.render_messages(
                [{"role": "User", "content": user_content},
                 {"role": "Assistant", "content": assistant_content}], side)
        chunks = _split_excerpt(excerpt, self._excerpt_cap())
        per_chunk = spk.chunk_spans(spans, chunks)
        attribution = {"user_side": side}
        for k in ("agent_context", "platform"):
            if ctx.get(k):
                attribution[k] = str(ctx[k])
        if author:
            attribution["author"] = {k: author[k] for k in ("id", "name", "is_bot")
                                     if author.get(k) not in (None, "")}
        if not user_content:
            actor = "agent"
        else:
            actor = "user" if side == spk.HUMAN else "system"
        # One occurred_at across the whole turn so siblings stay one group.
        stamp = occurred_at or self._now()
        first = ""
        for i, chunk in enumerate(chunks):
            # Per chunk, not per turn: the chunk is the unit a tombstone can match
            # now, and one forbidden span must not suppress the rest of the turn.
            if self.store.is_forbidden(hash_str(chunk)):
                continue  # forbidden content is never re-captured
            payload = {"source_type": "session_transcript", "excerpt": chunk,
                       "source_ref": session_id,
                       "chunk_index": i, "chunk_count": len(chunks)}
            if len(attribution) > 1 or side != spk.HUMAN or \
                    spk.legacy_lines(chunk, source_type="session_transcript", session_id=session_id,
                                     chunk_index=i) != spk.lines_from_spans(chunk, per_chunk[i]):
                payload["speakers"] = per_chunk[i]
                payload["attribution"] = attribution
            eid = self.append("observed", payload,
                              actor=actor, occurred_at=stamp,
                              session_id=session_id or None, trust_level=trust_level)
            first = first or eid
        if first and session_id:
            self._touch_session(session_id)
        return first

    def agent_explicit(self, action: str, target: str, content: str, metadata=None,
                       *, occurred_at: str | None = None) -> str:
        """on_memory_write: highest-precision signal, no confidence discount (§12.3)."""
        return self.append("observed",
                           {"source_type": "agent_memory_write", "excerpt": content[:4000],
                            "action": action, "target": target, "metadata": metadata or {},
                            "salience": "high"},
                           actor="agent", trust_level=3, occurred_at=occurred_at)

    def delegation(self, task: str, result: str, *, child_session_id: str = "",
                   occurred_at: str | None = None) -> str:
        return self.append("observed",
                           {"source_type": "delegation", "excerpt": f"Task: {task}\nResult: {result}",
                            "task": task, "result": result, "child_session_id": child_session_id},
                           actor="agent", occurred_at=occurred_at)

    def rescue(self, messages: list[dict], *, session_id: str = "",
               speaker_context: dict | None = None) -> tuple[list[str], str]:
        """Two-speed rescue (§12.6, I14): durably persist + fast-extract high-salience spans
        to `asserted(draft, salience=high)` so nothing critical is lost on eviction.

        Every important message is persisted, with its speaker, for recall. Only
        the user's own words become a rescued note: an assistant's "never do X",
        a tool's error text or a compaction handoff is not something the user
        said, and a note is always injected."""
        ctx = speaker_context or {}
        side = spk.user_side(agent_context=ctx.get("agent_context", ""),
                             platform=ctx.get("platform", ""), session_id=session_id,
                             author=ctx.get("author") if isinstance(ctx.get("author"), dict) else None)
        belief_events, summaries = [], []
        for msg in messages:
            content = spk.message_text(msg.get("content")).strip()
            if len(content) < 20:
                continue
            crit, _ = classify_criticality(content)
            important = crit != "normal" or any(kw in content.lower() for kw in _RESCUE_KW)
            if not important:
                continue
            excerpt = content[:2000]
            who = spk.role_speaker(msg.get("role"), side)
            if who in (spk.HUMAN, spk.AUTOMATION):
                spans = spk.split_user_content(excerpt, who)
            else:
                spans = [(0, len(excerpt), who)]
            # 1) raw durability (recall floor)
            obs = self.append("observed",
                             {"source_type": "rescue_extraction", "excerpt": excerpt,
                              "source_ref": session_id, "document_id": str(uuid.uuid4()),
                              "speakers": [list(x) for x in spans],
                              "attribution": {"user_side": side, "role": str(msg.get("role") or "")}},
                             actor="user" if who == spk.HUMAN else "system",
                             session_id=session_id or None)
            belief_events.append(obs)
            summaries.append(content[:200])
            # 2) draft belief (I14), from the user's own words only
            said = "\n".join(excerpt[a:b] for a, b, w in spans if w == spk.HUMAN).strip()
            if len(said) < 20:
                continue
            low = said.lower()
            crit, _ = classify_criticality(said)
            if crit == "normal" and not any(kw in low for kw in _RESCUE_KW):
                continue
            note_type = "norm" if any(k in low for k in ["always", "never", "must", "don't", "do not"]) else "belief"
            self.append("asserted",
                       {"kind": "note", "key": {"note_type": note_type, "subject": "rescued", "salience": "high"},
                        "body": said[:500], "confidence": 0.7, "source_event": obs,
                        "source_type": "rescue_extraction", "status": "draft"},
                       parents=[obs],
                       actor="system", session_id=session_id or None)
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
