"""Chronicle dashboard plugin — backend API routes.

Mounted at /api/plugins/chronicle/ by the dashboard plugin system.
Provides endpoints for status, store counts, embedding coverage, and processing.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

log = logging.getLogger(__name__)

router = APIRouter()


def _get_db_path() -> Path | None:
    """Locate the Chronicle SQLite database."""
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    for rel in ["commons/db/chronicle/chronicle.db", "commons/db/chronicle.db", "chronicle.db"]:
        p = home / rel
        if p.exists():
            return p
    return None


def _count(db_path: Path, table: str, where: str = "") -> int:
    try:
        q = f"SELECT COUNT(*) FROM {table}"
        if where:
            q += f" WHERE {where}"
        return sqlite3.connect(str(db_path), timeout=10).execute(q).fetchone()[0]
    except Exception:
        return 0


def _get_embedding_stats(db_path: Path) -> dict[str, Any]:
    """Return embedding coverage for every content table.

    Mirrors the actual embedding pipeline (see scripts/enrich_embeddings.py and
    chronicle_daily_embed.py):
      - documents: rows with an abstract -> memory_vectors kind='document'
      - notes/episodes/facts: ONLY status='active' rows are embedded
      - events: type='observed' rows; vectors live in observed_vectors, NOT
        memory_vectors (so the old kind='event' count was always 0)
      - entities: not part of the embedding pipeline
    Percentages are capped at 100 (some events accrue >1 vector over time).
    """
    stats: dict[str, Any] = {}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        # (key, total_query, embedded_query)
        queries = [
            ("document",
             "SELECT COUNT(*) FROM documents WHERE abstract IS NOT NULL",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='document'"),
            ("note",
             "SELECT COUNT(*) FROM notes WHERE status='active'",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='note'"),
            ("episode",
             "SELECT COUNT(*) FROM episodes WHERE status='active'",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='episode'"),
            ("fact",
             "SELECT COUNT(*) FROM facts WHERE status='active'",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='fact'"),
            ("event",
             "SELECT COUNT(*) FROM events WHERE type='observed'",
             "SELECT COUNT(DISTINCT ov.event_id) FROM observed_vectors ov "
             "JOIN events e ON e.event_id = ov.event_id "
             "WHERE e.type='observed'"),
        ]
        for kind, total_q, emb_q in queries:
            total = conn.execute(total_q).fetchone()[0]
            if total == 0:
                stats[kind] = {"total": 0, "embedded": 0, "pct": 0}
                continue
            embedded = conn.execute(emb_q).fetchone()[0]
            if embedded > total:
                # Numerator/denominator disagree on population: a query bug, not
                # saturation. Clamping alone once reported a false 100%.
                log.warning("coverage[%s]: embedded %d > total %d; check queries",
                            kind, embedded, total)
            embedded = min(embedded, total)
            pct = min(100, round((embedded / total) * 100))
            stats[kind] = {"total": total, "embedded": embedded, "pct": pct}
        # Entities are not embedded by the current pipeline.
        _ent = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        stats["entity"] = {"total": _ent, "embedded": 0, "pct": 0}
        conn.close()
    except Exception as e:
        log.warning("embedding stats failed: %s", e)
    return stats


_VERB = {
    "observed": "Remembered",
    "asserted": "Asserted",
    "retracted": "Retracted",
    "extracted": "Extracted",
    "curated": "Curated",
    "embedded": "Embedded",
    "updated": "Updated",
    "corrected": "Corrected",
    "signal": "Signalled",
}


def _summarize_event(kind: str, payload) -> str:
    """Build a short human-readable summary of what an event recorded.

    Extracts content from the payload fields that various event types use:
      - asserted/signal events store their primary text in ``body``
      - observed events use ``excerpt``
      - other historical tables use ``text`` / ``value`` / ``summary`` / ``content`` / ``note``
    When no direct text is found, falls back to structured fields to say WHAT
    happened: kind for asserted, signal_type for signals, action+target for observed.
    """
    if not isinstance(payload, dict):
        try:
            payload = json.loads(payload) if isinstance(payload, str) else {}
        except Exception:
            payload = {}
    # Direct text — body first since it's the primary field for asserted/signal
    text = (
        payload.get("body")
        or payload.get("excerpt")
        or payload.get("text")
        or payload.get("value")
        or payload.get("summary")
        or payload.get("content")
        or payload.get("note")
    )
    if text:
        s = str(text).replace("\n", " ").strip()
        return s[:120] + ("…" if len(s) > 120 else "")
    # Structured fallback — say WHAT happened even when there's no free-text body
    if kind == "asserted":
        sub_kind = payload.get("kind", "item")
        key = payload.get("key", {})
        if isinstance(key, dict):
            title = key.get("title") or key.get("subject") or key.get("note_type") or ""
        elif isinstance(key, str):
            title = key
        else:
            title = ""
        if title:
            return f"Asserted {sub_kind} · {str(title)[:100]}"
        return f"Asserted {sub_kind}"
    if kind == "signal":
        sig_type = payload.get("signal_type", "directive")
        return f"Signal · {sig_type}"
    if kind == "observed":
        action = payload.get("action", "")
        target = payload.get("target", "")
        if action and target:
            return f"{action} {target}"
        if action:
            return action
    if payload.get("attribute") and payload.get("value"):
        return f"{payload['attribute']}: {payload['value']}"
    if payload.get("belief_id"):
        return f"belief {payload['belief_id']}"
    if payload.get("event_id"):
        return f"event {payload['event_id']}"
    if payload.get("entity_id"):
        return f"entity {payload['entity_id']}"
    return ""


@router.get("/status")
def get_status():
    db_path = _get_db_path()
    if not db_path:
        return {"plugin": "chronicle", "status": "no_db"}

    store = {
        "events": _count(db_path, "events"),
        "facts": _count(db_path, "facts"),
        "episodes": _count(db_path, "episodes"),
        "notes": _count(db_path, "notes"),
        "procedures": _count(db_path, "procedures"),
        "entities": _count(db_path, "entities"),
        "documents": _count(db_path, "documents"),
        "pending_jobs": _count(db_path, "curation_jobs", "status='pending'"),
    }
    return {
        "plugin": "chronicle",
        "version": "5.3.3",
        "status": "active",
        "store": store,
        "embeddings": _get_embedding_stats(db_path),
    }


@router.post("/process-embeddings")
def process_embeddings():
    """Enqueue curation jobs for unprocessed events."""
    db_path = _get_db_path()
    if not db_path:
        return {"ok": False, "error": "no_database"}
    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
        unembedded = conn.execute(
            """SELECT e.event_id FROM events e
               LEFT JOIN extractions ext ON ext.observed_event = e.event_id
               WHERE ext.observed_event IS NULL
               ORDER BY e.seq ASC LIMIT 500"""
        ).fetchall()
        enqueued = 0
        for (event_id,) in unembedded:
            existing = conn.execute(
                "SELECT id FROM curation_jobs WHERE status='pending' AND payload LIKE ?",
                (f'%"{event_id}"%',),
            ).fetchone()
            if not existing:
                import json as _json
                conn.execute(
                    "INSERT INTO curation_jobs (task, payload, status, created_at) VALUES (?, ?, 'pending', datetime('now'))",
                    ("extract", _json.dumps({"event_id": event_id})),
                )
                enqueued += 1
        conn.commit()
        conn.close()
        return {"ok": True, "enqueued": enqueued}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/recent")
def get_recent(limit: int = Query(20, ge=1, le=100)):
    db_path = _get_db_path()
    if not db_path:
        return {"events": [], "count": 0}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event_id AS id, type AS kind, recorded_at AS created_at, actor AS source, payload FROM events ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        events = []
        for r in rows:
            d = dict(r)
            try:
                pl = json.loads(d["payload"]) if isinstance(d.get("payload"), str) else (d.get("payload") or {})
            except Exception:
                pl = {}
            kind = d.get("kind") or "event"
            d["summary"] = _summarize_event(kind, pl)
            d["verb"] = _VERB.get(kind, kind.capitalize())
            # Surface domain + confidence from payload for frontend chips
            d["domain"] = pl.get("domain")
            d["confidence"] = pl.get("confidence")
            # For signal events, include signal_type for richer display
            d["signal_type"] = pl.get("signal_type") if kind == "signal" else None
            events.append(d)
        return {"events": events, "count": len(events)}
    except Exception:
        return {"events": [], "count": 0}


@router.get("/facts")
def get_facts(
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
):
    db_path = _get_db_path()
    if not db_path:
        return {"facts": [], "count": 0}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        where = ""
        params: list = []
        if status:
            where = "WHERE status = ?"
            params.append(status)
        rows = conn.execute(
            f"SELECT belief_id, entity_id, attribute, value, status, created_at, salience FROM facts {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params + [limit]),
        ).fetchall()
        conn.close()
        return {"facts": [dict(r) for r in rows], "count": len(rows)}
    except Exception:
        return {"facts": [], "count": 0}
