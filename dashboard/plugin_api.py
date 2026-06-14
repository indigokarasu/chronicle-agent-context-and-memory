"""Chronicle dashboard plugin — backend API routes.

Mounted at /api/plugins/chronicle/ by the dashboard plugin system.
Provides endpoints for status, store counts, embedding coverage, and processing.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

log = logging.getLogger(__name__)

router = APIRouter()


def _get_db_path() -> Optional[Path]:
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


def _get_embedding_stats(db_path: Path) -> Dict[str, Any]:
    """Return embedding coverage for every content table."""
    stats: Dict[str, Any] = {}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        for table, kind in [
            ("documents", "document"),
            ("notes", "note"),
            ("episodes", "episode"),
            ("facts", "fact"),
            ("events", "event"),
            ("entities", "entity"),
        ]:
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if total == 0:
                stats[kind] = {"total": 0, "embedded": 0, "pct": 0}
                continue
            # For entities the id column is belief_id, matching memory_vectors.belief_id.
            # For events the id column is event_id, matching memory_vectors.belief_id.
            # For documents the id column is id, matching memory_vectors.belief_id.
            # All other tables also align on belief_id == belief_id.
            embedded = conn.execute(
                "SELECT COUNT(*) FROM memory_vectors WHERE kind = ?", (kind,)
            ).fetchone()[0]
            pct = int(round((embedded / total) * 100))
            stats[kind] = {"total": total, "embedded": embedded, "pct": pct}
        conn.close()
    except Exception as e:
        log.warning("embedding stats failed: %s", e)
    return stats


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
            "SELECT event_id AS id, type AS kind, recorded_at AS created_at, actor AS source FROM events ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return {"events": [dict(r) for r in rows], "count": len(rows)}
    except Exception:
        return {"events": [], "count": 0}


@router.get("/facts")
def get_facts(
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
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
