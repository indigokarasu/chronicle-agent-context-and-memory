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
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

log = logging.getLogger(__name__)

router = APIRouter()


def _resolve_version() -> str:
    """Chronicle's version — never a literal in this file.

    Preferred path: the root package's ``__version__`` (itself read from
    plugin.yaml). That only works when this module is loaded as part of the
    package; the dashboard plugin host mounts it by file path, in which case
    there is no parent package to import from. So the fallback reads the same
    ``version:`` line out of plugin.yaml by path — a pure read, no imports and
    no ``sys.path`` mutation, which matters here because putting the plugin root
    on ``sys.path`` would shadow generically named modules (``context``,
    ``provider``, ``_base``) for the whole dashboard process.
    """
    try:
        from .. import __version__ as package_version

        return package_version
    except Exception:
        pass
    try:
        yaml_path = Path(__file__).resolve().parent.parent / "plugin.yaml"
        with open(yaml_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.startswith("version:"):
                    continue
                value = line.split(":", 1)[1].split("#", 1)[0].strip()
                value = value.strip("\"'").strip()
                if value:
                    return value
    except Exception:  # pragma: no cover - defensive: missing/unreadable manifest
        pass
    log.warning("chronicle: could not resolve plugin version")
    return "unknown"


_VERSION = _resolve_version()


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
    """Return embedding coverage for every content table.

    Mirrors the engine's own embedding pipeline (engine/reducer.py writes the
    vectors; engine/curation.py `_task_embed` drains the queued ones). An
    earlier version of this docstring credited two scripts that are NOT in this
    tree -- `scripts/enrich_embeddings.py` and `chronicle_daily_embed.py` -- as
    the pipeline being mirrored. They were out-of-tree operator scripts writing
    into the same database, and describing them here made an unaudited writer
    look like part of Chronicle. Nothing in this repo runs them, and this
    dashboard is not evidence that anything does (that pair of scripts is the
    same class of out-of-tree writer as the one that sent excerpts off-host
    before the A2 guard existed).
      - documents: the `document` row below counts `memory_vectors kind='document'`,
        and THE ENGINE NEVER WRITES THAT KIND. `_table_of_kind` has no
        'document' table and no writer emits it, so on a store written only by
        Chronicle this row reads 0 of N, permanently. A non-zero count here
        means something outside this tree wrote those rows. The query is left
        in place deliberately: it is the only place that fact is visible, and
        inventing a `kind='document'` writer to make the row green would be
        implementing a feature to satisfy a dashboard label.
      - notes/episodes/facts: ONLY status='active' rows are embedded
      - events: type='observed' rows; vectors live in observed_vectors, NOT
        memory_vectors (so the old kind='event' count was always 0)
      - entities: not part of the embedding pipeline. Entity NAMES carry no
        semantic content and must never drive identity, so entities are never
        vector-embedded — this row stays 0%, permanently, by design (§R12).
      - digest: broken out of the 'note' bucket (same underlying table/kind —
        note_type='belief', subject LIKE 'digest:%') because it is the ONE
        semantic surface an entity has: a consolidation note embedded through
        the ordinary belief-kind path (§u2, §R12). A search that means an
        entity semantically, without naming it, can only ever land here —
        never on the (unembedded) entity row above.
    Percentages are capped at 100 (some events accrue >1 vector over time).
    """
    stats: Dict[str, Any] = {}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        # (key, total_query, embedded_query)
        queries = [
            ("document",
             "SELECT COUNT(*) FROM documents WHERE abstract IS NOT NULL",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='document'"),
            ("note",
             "SELECT COUNT(*) FROM notes WHERE status='active' AND subject NOT LIKE 'digest:%'",
             "SELECT COUNT(*) FROM memory_vectors mv JOIN notes n ON n.belief_id=mv.belief_id "
             "WHERE mv.kind='note' AND n.status='active' AND n.subject NOT LIKE 'digest:%'"),
            ("digest",
             "SELECT COUNT(*) FROM notes WHERE status='active' AND subject LIKE 'digest:%'",
             "SELECT COUNT(*) FROM memory_vectors mv JOIN notes n ON n.belief_id=mv.belief_id "
             "WHERE mv.kind='note' AND n.status='active' AND n.subject LIKE 'digest:%'"),
            ("episode",
             "SELECT COUNT(*) FROM episodes WHERE status='active'",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='episode'"),
            ("fact",
             "SELECT COUNT(*) FROM facts WHERE status='active'",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='fact'"),
            ("session",
             "SELECT COUNT(*) FROM session_index",
             "SELECT COUNT(*) FROM session_index WHERE embedding IS NOT NULL"),
        ("projection",
             "SELECT COUNT(*) FROM pointers",
             "SELECT COUNT(*) FROM projection_vectors"),
        ("reference",
             "SELECT COUNT(*) FROM refs WHERE status='active'",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='reference'"),
        ("procedure",
             "SELECT COUNT(*) FROM procedures WHERE status='active'",
             "SELECT COUNT(*) FROM memory_vectors WHERE kind='procedure'"),
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
            pct = min(100, int(round((embedded / total) * 100)))
            stats[kind] = {"total": total, "embedded": embedded, "pct": pct}
        # Entities are not embedded by the current pipeline — never will be
        # (§R12): the 'digest' row above is their semantic surface instead.
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


def _jobs_breakdown(db_path):
    """Live queue split by status and task -- a to-do list, not a coverage meter."""
    out = {"pending": 0, "running": 0, "failed": 0, "by_task": {}}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        for task, status, n in conn.execute(
                "SELECT task, status, COUNT(*) FROM curation_jobs "
                "WHERE status != 'done' GROUP BY task, status"):
            out[status] = out.get(status, 0) + n
            out["by_task"].setdefault(task, {})[status] = n
        conn.close()
    except Exception:
        pass
    return out


def _maintenance(db_path):
    """Maintenance-scheduler watermarks (§17.4): when each schedule entry last
    fired. Read straight from the table rather than through the engine, like
    every other panel here. An older store has no such table — that is a store
    that predates the scheduler, not an error — so it reports empty."""
    out = {"entries": []}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        rows = conn.execute(
            "SELECT entry, task, payload, last_fire_at, last_enqueued_at, enqueues, decisions "
            "FROM maintenance_runs ORDER BY entry").fetchall()
        conn.close()
        out["entries"] = [
            {"entry": r[0], "task": r[1], "payload": r[2], "last_fire_at": r[3],
             "last_enqueued_at": r[4], "enqueues": r[5], "decisions": r[6]} for r in rows]
    except Exception:
        pass
    return out


def _outstanding_extractions(db_path):
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        n = conn.execute(
            # `type='observed'` because that is what the EXTRACTOR selects
            # (engine/curation.py: "type='observed' AND event_id NOT IN ...").
            # Without it this counts asserted and derived events too, which no
            # extraction will ever cover, so the number could never reach zero
            # however long the queue ran.
            "SELECT COUNT(*) FROM events e LEFT JOIN extractions ext "
            "ON ext.observed_event = e.event_id "
            "WHERE ext.observed_event IS NULL AND e.type='observed'").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


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
        "entities": _count(db_path, "entities"), "relationships": _count(db_path, "relationships", "status='active'"),
        "documents": _count(db_path, "documents"),
        "pending_jobs": _count(db_path, "curation_jobs", "status='pending'"),
        "jobs": _jobs_breakdown(db_path),
        "maintenance": _maintenance(db_path),
        "extractions_outstanding": _outstanding_extractions(db_path),
        # what POST /enqueue-extractions would actually find; 0 means it is a
        # no-op. Same query as _outstanding_extractions above and as the
        # endpoint's own SELECT, so the number the button shows is the number
        # the button acts on.
        "enqueue_candidates": _count(
            db_path, "events e LEFT JOIN extractions ext ON ext.observed_event = e.event_id",
            "ext.observed_event IS NULL AND e.type='observed'"),
    }
    return {
        "plugin": "chronicle",
        "version": _VERSION,
        "status": "active",
        "store": store,
        "embeddings": _get_embedding_stats(db_path),
    }


def _now_iso() -> str:
    """store.now_iso()'s format, restated rather than imported.

    This module is mounted BY FILE PATH by the dashboard plugin host, so there
    is no parent package to import the engine from, and putting the plugin root
    on sys.path would shadow generically named modules (`context`, `provider`,
    `_base`) for the whole dashboard process — see _resolve_version. So the one
    thing this file writes has to reproduce the store's timestamp format here.

    It is not cosmetic. `datetime('now')` — what this used to write — yields
    "2026-09-10 12:34:56": a space instead of 'T', no milliseconds, no 'Z'. Rows
    are compared and ordered as TEXT, so a job stamped that way sorts BEFORE
    every job the engine ever wrote, and any window filter of the form
    created_at >= '<iso>' silently excludes it.
    """
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


@router.post("/enqueue-extractions")
def enqueue_extractions(limit: int = Query(500, ge=1, le=5000)):
    """Queue an `extract` curation job for every observed event that has none.

    Renamed in A13. It was POST /process-embeddings, which was wrong twice over:
    it embeds nothing (extraction is what produces the beliefs that are later
    embedded, by a different task), and a button labelled "process embeddings"
    that enqueues extractions is a control an operator cannot reason about.

    The rows it writes are now indistinguishable from `store.enqueue_curation`'s:

      * canonical payload — json.dumps(payload, sort_keys=True), the exact
        string enqueue_curation stores, so its (task, payload) dedupe probe and
        the idx_jobs_dedupe partial index see this row;
      * the same dedupe rule — collapse an identical (task, payload) already
        pending OR running. The old LIKE '%"<event_id>"%' probe checked only
        pending, so a job the worker had already claimed was enqueued a second
        time, and it matched any payload containing that id as a substring;
      * `now_iso()`'s timestamp format, not `datetime('now')`.

    A job written here is therefore claimable and runnable by the ordinary
    CurationWorker, which is the property tests/test_dashboard_endpoint.py pins.
    """
    db_path = _get_db_path()
    if not db_path:
        return {"ok": False, "error": "no_database"}
    try:
        conn = sqlite3.connect(str(db_path), timeout=30)
        unextracted = conn.execute(
            """SELECT e.event_id, e.session_id FROM events e
               LEFT JOIN extractions ext ON ext.observed_event = e.event_id
               WHERE ext.observed_event IS NULL AND e.type='observed'
               ORDER BY e.seq ASC LIMIT ?""", (int(limit),)
        ).fetchall()
        enqueued = 0
        for event_id, session_id in unextracted:
            payload = json.dumps({"event_id": event_id, "session_id": session_id},
                                 sort_keys=True)
            dup = conn.execute(
                "SELECT id FROM curation_jobs WHERE task='extract' "
                "AND status IN ('pending','running') AND payload=?", (payload,)).fetchone()
            if dup is not None:
                continue
            conn.execute(
                "INSERT INTO curation_jobs(task, payload, status, created_at) "
                "VALUES('extract', ?, 'pending', ?)", (payload, _now_iso()))
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


# --------------------------------------------------------------------------
# Tapestry (memory navigator) routes, from the sibling tapestry_api.py.
#
# Loaded by path for the same reason this file is: the host mounts plugin_api.py
# with no parent package, so a relative import has nothing to resolve against.
# A failure here costs the Tapestry tab its data, never the rest of the dashboard.
# --------------------------------------------------------------------------
def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))


def _mount_tapestry():
    import importlib.util

    path = Path(__file__).resolve().parent / "tapestry_api.py"
    spec = importlib.util.spec_from_file_location("chronicle_dashboard_tapestry", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.register(router, _get_db_path, _hermes_home, Query)


try:
    _mount_tapestry()
except Exception as _atlas_err:  # pragma: no cover - defensive
    log.warning("chronicle: Tapestry routes unavailable (%s)", _atlas_err)
