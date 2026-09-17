"""Chronicle Atlas — read-only data for the dashboard's memory navigator.

Loaded by path from plugin_api.py (the dashboard host mounts that file with no
parent package), so this module imports nothing from the engine and reads the
store with raw SQL, the same way every other panel does.

Everything here is READ-ONLY and short-lived. Each call opens its own
connection, runs a bounded query and closes it: a long-lived read transaction on
a WAL store pins the WAL and blocks checkpoints, which on the production box is
the difference between a dashboard and an outage.

The data functions take a database path and return plain dicts, so they are
testable without FastAPI; `register(router, get_db_path)` binds them to routes.

Shapes are chosen for the browser, not for symmetry with the schema:

* `events_chunk` streams the whole log as delta-encoded integer columns, so
  ~420k events cost a few MB of JSON and a single typed-array pass to render;
* `lane_of` assigns every event a "writer" lane — one per cron job, one per
  interactive session, one per background actor — because that is the axis
  along which memory is actually written.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

_BUSY_MS = 5000
_EXCERPT = 600          # characters of any text returned for display
_CHUNK_MAX = 50000      # events per /atlas/events call
_SUPPORT_MAX = 50       # source events returned per belief
_SESSION_TURNS = 200    # events returned per session inspector
_SESSION_BELIEFS = 200  # beliefs returned per session inspector

# Belief tables: (table, kind, text column, label column). The text column is
# the one the engine's belief-text authority names for the kind where it has
# one (reducer.BELIEF_VECTOR_SOURCE); entities and relationships carry no body.
_BELIEF_TABLES = (
    ("facts", "fact", "value", "predicate_canonical"),
    ("notes", "note", "body", "subject"),
    ("episodes", "episode", "summary", "title"),
    ("refs", "reference", "cached_summary", "topic"),
    ("procedures", "procedure", "body", "name"),
    ("entities", "entity", "name", "type"),
    ("relationships", "relationship", "predicate", "source_id"),
)

_CRON_RX = re.compile(r"^cron_([0-9a-f]{6,})_")


# --------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------
def _connect(db_path) -> sqlite3.Connection:
    """A read-only connection that has provably opened the file.

    `mode=ro` is enforced by SQLite, so nothing here can write the live store.
    It cannot open a WAL database whose -shm does not exist; the live store
    always has one while Hermes runs, and a store nothing has open is read with
    `immutable=1`, which is exact when no -wal holds frames."""
    # quoted: a "?" or "#" in the path would otherwise end the file name
    uri = "file:%s?mode=ro" % quote(Path(db_path).as_posix())
    last = None
    for suffix in ("", "&immutable=1"):
        if suffix:
            wal = Path(str(db_path) + "-wal")
            if wal.exists() and wal.stat().st_size > 0:
                break
        try:
            conn = sqlite3.connect(uri + suffix, uri=True, timeout=_BUSY_MS / 1000.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=%d" % _BUSY_MS)
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            return conn
        except sqlite3.Error as e:
            last = e
    raise sqlite3.OperationalError("cannot open %s read-only: %s" % (db_path, last))


def _cols(conn, table) -> List[str]:
    try:
        return [r[1] for r in conn.execute('PRAGMA table_info("%s")' % table)]
    except sqlite3.Error:
        return []


def _clip(text, n=_EXCERPT) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= n else s[: n - 1] + "…"


def _payload(raw) -> dict:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        p = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError:
        return {}
    return p if isinstance(p, dict) else {}


def _epoch(conn, iso) -> Optional[int]:
    if not iso:
        return None
    row = conn.execute("SELECT CAST(strftime('%s', ?) AS INTEGER)", (iso,)).fetchone()
    return row[0] if row else None


def event_text(etype: str, payload: dict) -> str:
    """What an event SAYS, for a human: the excerpt of a turn, the body of an
    assertion, the kind of a signal. Never the raw JSON."""
    p = payload or {}
    if etype == "observed":
        return _clip(p.get("excerpt") or p.get("text") or "")
    if etype in ("asserted", "derived"):
        body = p.get("body") or ""
        key = p.get("key") if isinstance(p.get("key"), dict) else {}
        label = key.get("predicate_canonical") or key.get("subject") or key.get("title") or ""
        kind = p.get("kind") or ""
        head = " · ".join(x for x in (kind, label) if x)
        return _clip(("%s: %s" % (head, body)) if head else body)
    if etype == "signal":
        return _clip("%s %s" % (p.get("signal_type") or "", p.get("body") or "")).strip()
    if etype == "corrected":
        return _clip(p.get("new_body") or "")
    for k in ("summary", "detail", "reason", "body"):
        if p.get(k):
            return _clip(p[k])
    return ""


def lane_of(session_id: Optional[str], actor: str) -> str:
    """The writer lane: `cron:<job>` for a cron run, `session:<id>` for any
    other session, `background:<actor>` for sessionless writes."""
    sid = session_id or ""
    if not sid:
        return "background:%s" % (actor or "unknown")
    m = _CRON_RX.match(sid)
    if m:
        return "cron:%s" % m.group(1)
    return "session:%s" % sid


class _TTLCache:
    def __init__(self):
        self._d: Dict[Any, Any] = {}
        self._lock = threading.Lock()

    def get(self, key, ttl, compute):
        now = time.monotonic()
        with self._lock:
            hit = self._d.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = compute()
        with self._lock:
            self._d[key] = (now, value)
        return value

    def clear(self):
        with self._lock:
            self._d.clear()


_cache = _TTLCache()


# --------------------------------------------------------------------------
# data functions
# --------------------------------------------------------------------------
# The kinds whose status counts the Atlas header shows. Counting every belief
# table scanned 67k episodes and 44k notes per call: 5.7 s warm and 57 s cold on
# the CPU-capped production host, every minute the tab was open.
_SUMMARY_KINDS = ("fact", "note")


def summary(db_path) -> dict:
    """The numbers the Atlas header shows, and only those: event count and
    extent, fact and note counts by status, open contradictions."""
    conn = _connect(db_path)
    try:
        def one(sql, params=()):
            try:
                row = conn.execute(sql, params).fetchone()
                return row[0] if row else None
            except sqlite3.Error:
                return None

        out: Dict[str, Any] = {
            "max_seq": one("SELECT MAX(seq) FROM events") or 0,
            "events": one("SELECT COUNT(*) FROM events") or 0,
            "first_t": _epoch(conn, one("SELECT recorded_at FROM events ORDER BY seq LIMIT 1")),
            "last_t": _epoch(conn, one("SELECT recorded_at FROM events ORDER BY seq DESC LIMIT 1")),
            "beliefs": {},
        }
        for table, kind, _text, _label in _BELIEF_TABLES:
            if kind not in _SUMMARY_KINDS or "status" not in _cols(conn, table):
                continue
            rows = conn.execute('SELECT COALESCE(status, \'active\'), COUNT(*) FROM "%s" '
                                "GROUP BY 1" % table).fetchall()
            out["beliefs"][kind] = {r[0]: r[1] for r in rows}
        out["contradictions_open"] = one(
            "SELECT COUNT(*) FROM contradictions WHERE COALESCE(status,'open')='open'") or 0
        return out
    finally:
        conn.close()


def events_chunk(db_path, after_seq: int = 0, limit: int = _CHUNK_MAX) -> dict:
    """Events with seq > after_seq, oldest first, as delta-encoded columns.

    `dseq[i]` / `dt[i]` are differences from the previous event (the first from
    `seq0` / `t0`), `type[i]` indexes `types`, `writer[i]` indexes `writers`
    (a `[session_id, lane]` pair per distinct writer in THIS chunk). The client
    rebuilds absolute values in one pass. `next_after_seq` is the seq to ask
    from next; `done` is true when this chunk reached the end of the log."""
    limit = max(1, min(int(limit or _CHUNK_MAX), _CHUNK_MAX))
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT seq, CAST(strftime('%s', recorded_at) AS INTEGER), type, "
            "COALESCE(session_id, ''), actor FROM events WHERE seq > ? ORDER BY seq LIMIT ?",
            (int(after_seq or 0), limit)).fetchall()
    finally:
        conn.close()
    types: List[str] = []
    type_ix: Dict[str, int] = {}
    writers: List[List[str]] = []
    writer_ix: Dict[tuple, int] = {}
    dseq: List[int] = []
    dt: List[int] = []
    tcol: List[int] = []
    wcol: List[int] = []
    prev_seq = prev_t = None
    seq0 = t0 = None
    for seq, t, etype, sid, actor in rows:
        t = int(t or 0)
        if seq0 is None:
            seq0, t0 = seq, t
            prev_seq, prev_t = seq, t
        dseq.append(seq - prev_seq)
        dt.append(t - prev_t)
        prev_seq, prev_t = seq, t
        if etype not in type_ix:
            type_ix[etype] = len(types)
            types.append(etype)
        tcol.append(type_ix[etype])
        wkey = (sid, actor if not sid else "")
        if wkey not in writer_ix:
            writer_ix[wkey] = len(writers)
            writers.append([sid, lane_of(sid, actor)])
        wcol.append(writer_ix[wkey])
    return {
        "seq0": seq0, "t0": t0, "n": len(rows),
        "dseq": dseq, "dt": dt, "type": tcol, "writer": wcol,
        "types": types, "writers": writers,
        "next_after_seq": prev_seq if prev_seq is not None else int(after_seq or 0),
        "done": len(rows) < limit,
    }


_CHUNK_CACHE_BYTES = 32 * 1024 * 1024
_chunk_cache: Dict[tuple, bytes] = {}
_chunk_lock = threading.Lock()


def events_json(db_path, after_seq: int = 0, limit: int = _CHUNK_MAX) -> bytes:
    """`events_chunk` serialized, with FULL chunks cached as bytes.

    The log is append-only, so a chunk that did not reach the end of it (`done`
    false) can never change: every later open of the Atlas gets it without a
    query or a serialization, which on a CPU-capped host is the difference
    between a 20-second load and an instant one. The last chunk — the live
    tail — is never cached. Bounded to _CHUNK_CACHE_BYTES, oldest out first."""
    key = (str(db_path), int(after_seq or 0), max(1, min(int(limit or _CHUNK_MAX), _CHUNK_MAX)))
    with _chunk_lock:
        hit = _chunk_cache.get(key)
    if hit is not None:
        return hit
    chunk = events_chunk(db_path, key[1], key[2])
    body = json.dumps(chunk, separators=(",", ":")).encode("utf-8")
    if not chunk["done"]:
        with _chunk_lock:
            _chunk_cache[key] = body
            while sum(len(v) for v in _chunk_cache.values()) > _CHUNK_CACHE_BYTES and len(_chunk_cache) > 1:
                _chunk_cache.pop(next(iter(_chunk_cache)))
    return body


def _beliefs_supported_by(conn, event_ids: List[str], cap: int) -> List[dict]:
    """Beliefs whose justifications cite any of `event_ids`."""
    if not event_ids:
        return []
    found: Dict[str, str] = {}
    for i in range(0, len(event_ids), 500):
        part = event_ids[i:i + 500]
        q = "SELECT belief_id, support FROM justifications WHERE support IN (%s)" % (
            ",".join("?" * len(part)))
        for r in conn.execute(q, part):
            found.setdefault(r[0], r[1])
        if len(found) >= cap:
            break
    return _belief_rows(conn, list(found)[:cap])


def _belief_rows(conn, belief_ids: List[str]) -> List[dict]:
    """Compact belief records for ids, looked up table by table."""
    out: List[dict] = []
    remaining = set(belief_ids)
    for table, kind, text_col, label_col in _BELIEF_TABLES:
        if not remaining:
            break
        cols = _cols(conn, table)
        if not cols or text_col not in cols:
            continue
        want = [c for c in ("belief_id", text_col, label_col, "status", "confidence",
                            "created_at", "occurrence_count") if c in cols]
        ids = list(remaining)
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            q = 'SELECT %s FROM "%s" WHERE belief_id IN (%s)' % (
                ", ".join(want), table, ",".join("?" * len(part)))
            for r in conn.execute(q, part):
                d = dict(r)
                remaining.discard(d["belief_id"])
                out.append({
                    "belief_id": d["belief_id"], "kind": kind, "table": table,
                    "label": _clip(d.get(label_col), 80),
                    "text": _clip(d.get(text_col)),
                    "status": d.get("status") or "active",
                    "confidence": d.get("confidence"),
                    "created_at": d.get("created_at"),
                    "occurrences": d.get("occurrence_count"),
                })
    return out


def event_detail(db_path, seq: int) -> dict:
    conn = _connect(db_path)
    try:
        r = conn.execute(
            "SELECT event_id, seq, type, actor, owner, session_id, recorded_at, occurred_at, payload "
            "FROM events WHERE seq=?", (int(seq),)).fetchone()
        if r is None:
            return {"found": False, "seq": int(seq)}
        d = dict(r)
        p = _payload(d.pop("payload"))
        d["text"] = event_text(d["type"], p)
        d["lane"] = lane_of(d.get("session_id"), d.get("actor"))
        d["beliefs"] = _beliefs_supported_by(conn, [d["event_id"]], _SESSION_BELIEFS)
        # An assertion is rarely cited itself: the belief it wrote cites the turn
        # it was extracted FROM (payload.source_event). Without this, clicking any
        # of the store's hundreds of thousands of assertions says "nothing cites
        # this", which is true and useless.
        src = p.get("source_event")
        d["source"] = None
        if src and src != d["event_id"]:
            srow = conn.execute("SELECT seq, type, actor, session_id, recorded_at, payload FROM events "
                                "WHERE event_id=?", (src,)).fetchone()
            if srow is not None:
                d["source"] = {"seq": srow["seq"], "type": srow["type"], "actor": srow["actor"],
                               "session_id": srow["session_id"], "recorded_at": srow["recorded_at"],
                               "text": event_text(srow["type"], _payload(srow["payload"]))}
            d["source_beliefs"] = _beliefs_supported_by(conn, [src], _SESSION_BELIEFS)
        d["found"] = True
        return d
    finally:
        conn.close()


def session_detail(db_path, session_id: str) -> dict:
    """One writer's session: its summary, its turns in order, and the beliefs
    those turns justify."""
    conn = _connect(db_path)
    try:
        stats = conn.execute(
            "SELECT COUNT(*), MIN(seq), MAX(seq) FROM events WHERE session_id=?",
            (session_id,)).fetchone()
        count = stats[0] if stats else 0
        out: Dict[str, Any] = {"session_id": session_id, "events": count,
                               "lane": lane_of(session_id, "")}
        if not count:
            out["found"] = False
            return out
        out["found"] = True
        try:
            s = conn.execute("SELECT summary, occurred_at FROM session_index WHERE session_id=?",
                             (session_id,)).fetchone()
        except sqlite3.Error:
            s = None
        out["summary"] = _clip(s[0], 2000) if s and s[0] else None
        types = conn.execute("SELECT type, COUNT(*) FROM events WHERE session_id=? GROUP BY type "
                             "ORDER BY 2 DESC", (session_id,)).fetchall()
        out["types"] = {t: n for t, n in types}
        rows = conn.execute(
            "SELECT event_id, seq, type, actor, recorded_at, payload FROM events "
            "WHERE session_id=? ORDER BY seq LIMIT ?", (session_id, _SESSION_TURNS)).fetchall()
        turns = []
        for r in rows:
            p = _payload(r["payload"])
            turns.append({"seq": r["seq"], "type": r["type"], "actor": r["actor"],
                          "recorded_at": r["recorded_at"], "text": event_text(r["type"], p)})
        out["turns"] = turns
        out["first_at"] = rows[0]["recorded_at"] if rows else None
        ids = [r[0] for r in conn.execute("SELECT event_id FROM events WHERE session_id=?",
                                          (session_id,))]
        out["beliefs"] = _beliefs_supported_by(conn, ids, _SESSION_BELIEFS)
        return out
    finally:
        conn.close()


def _find_belief(conn, belief_id):
    """(table, kind, text_col, label_col, row) for a belief id, or None."""
    for table, kind, text_col, label_col in _BELIEF_TABLES:
        if not _cols(conn, table):
            continue
        r = conn.execute('SELECT * FROM "%s" WHERE belief_id=?' % table, (belief_id,)).fetchone()
        if r is not None:
            return table, kind, text_col, label_col, dict(r)
    return None


def _supports(conn, belief_id):
    rows = conn.execute(
        "SELECT e.seq, e.type, e.actor, e.session_id, e.recorded_at, e.payload, j.rule "
        "FROM justifications j JOIN events e ON e.event_id = j.support "
        "WHERE j.belief_id=? ORDER BY e.seq LIMIT ?", (belief_id, _SUPPORT_MAX)).fetchall()
    return [{"seq": s["seq"], "type": s["type"], "actor": s["actor"], "session_id": s["session_id"],
             "recorded_at": s["recorded_at"], "rule": s["rule"],
             "text": event_text(s["type"], _payload(s["payload"]))} for s in rows]


def _replaced_by(conn, first_successor, seen, cap=20):
    """The chain of beliefs that replaced this one, oldest replacement first."""
    chain, cur = [], first_successor
    while cur and cur not in seen and len(chain) < cap:
        seen.add(cur)
        nxt = _belief_rows(conn, [cur])
        if not nxt:
            break
        chain.append(nxt[0])
        try:
            r = conn.execute('SELECT superseded_by FROM "%s" WHERE belief_id=?' % nxt[0]["table"],
                             (cur,)).fetchone()
        except sqlite3.Error:
            r = None
        cur = r[0] if r else None
    return chain


def _replaced(conn, table, belief_id, seen, cap=20):
    """The chain of beliefs this one replaced, oldest first."""
    if "superseded_by" not in _cols(conn, table):
        return []
    chain, cur = [], belief_id
    while len(chain) < cap:
        r = conn.execute('SELECT belief_id FROM "%s" WHERE superseded_by=? ORDER BY created_at'
                         % table, (cur,)).fetchone()
        if r is None or r[0] in seen:
            break
        seen.add(r[0])
        prev = _belief_rows(conn, [r[0]])
        if not prev:
            break
        chain.insert(0, prev[0])
        cur = r[0]
    return chain


def _contradictions_of(conn, belief_id):
    try:
        cons = conn.execute(
            "SELECT id, belief_a, belief_b, detail, COALESCE(status,'open'), created_at "
            "FROM contradictions WHERE belief_a=? OR belief_b=? ORDER BY created_at DESC LIMIT 50",
            (belief_id, belief_id)).fetchall()
    except sqlite3.Error:
        return []
    other_id = {c[0]: (c[2] if c[1] == belief_id else c[1]) for c in cons}
    by_id = {b["belief_id"]: b for b in _belief_rows(conn, list(other_id.values()))}
    return [{"id": c[0], "detail": _clip(c[3], 200), "status": c[4], "created_at": c[5],
             "other": by_id.get(other_id[c[0]])} for c in cons]


def _identical_active(conn, table, text_col, row):
    """Active rows with this belief's exact text in the scope the exact-content
    merge uses: identical text under another owner or subject is not a copy."""
    body = row.get(text_col)
    tcols = _cols(conn, table)
    if not body or "status" not in tcols:
        return None
    scope = [c for c in ("owner", "domain", "note_type", "subject") if c in tcols]
    where = " AND ".join(["status='active'", "%s=?" % text_col] +
                         ["COALESCE(%s,'')=COALESCE(?,'')" % c for c in scope])
    return conn.execute('SELECT COUNT(*) FROM "%s" WHERE %s' % (table, where),
                        [body] + [row.get(c) for c in scope]).fetchone()[0]


_BELIEF_FIELDS = ("status", "confidence", "trust_level", "created_at", "last_seen_at", "valid_from",
                  "valid_until", "superseded_by", "occurrence_count", "entity_id", "note_type",
                  "domain", "owner", "salience", "criticality")


def belief_detail(db_path, belief_id: str) -> dict:
    """A belief with everything that explains it: the events that justify it,
    what it replaced and what replaced it, what contradicts it, and how many
    identical active copies exist."""
    conn = _connect(db_path)
    try:
        found = _find_belief(conn, belief_id)
        if found is None:
            return {"found": False, "belief_id": belief_id}
        table, kind, text_col, label_col, row = found
        out: Dict[str, Any] = {
            "found": True, "belief_id": belief_id, "kind": kind, "table": table,
            "label": _clip(row.get(label_col), 120), "text": _clip(row.get(text_col), 4000),
        }
        out.update({k: row[k] for k in _BELIEF_FIELDS if k in row})
        prov = _payload(row.get("provenance"))
        out["provenance"] = {"source_type": prov.get("source_type"),
                             "sightings": len(prov.get("provenances") or []) or (1 if prov else 0)}
        if kind == "fact" and row.get("entity_id"):
            e = conn.execute("SELECT name FROM entities WHERE belief_id=?", (row["entity_id"],)).fetchone()
            out["entity_name"] = e[0] if e else None
        out["supports"] = _supports(conn, belief_id)
        out["supports_total"] = conn.execute(
            "SELECT COUNT(*) FROM justifications WHERE belief_id=?", (belief_id,)).fetchone()[0]
        seen = {belief_id}
        out["replaced_by"] = _replaced_by(conn, row.get("superseded_by"), seen)
        out["replaced"] = _replaced(conn, table, belief_id, seen)
        out["contradictions"] = _contradictions_of(conn, belief_id)
        identical = _identical_active(conn, table, text_col, row)
        if identical is not None:
            out["identical_active"] = identical
        return out
    finally:
        conn.close()


def contradictions(db_path, limit: int = 100, offset: int = 0, status: str = "open") -> dict:
    limit = max(1, min(int(limit), 500))
    conn = _connect(db_path)
    try:
        try:
            total = conn.execute("SELECT COUNT(*) FROM contradictions WHERE COALESCE(status,'open')=?",
                                 (status,)).fetchone()[0]
            rows = conn.execute(
                "SELECT id, belief_a, belief_b, detail, created_at FROM contradictions "
                "WHERE COALESCE(status,'open')=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, int(offset))).fetchall()
        except sqlite3.Error:
            return {"total": 0, "items": []}
        beliefs = {b["belief_id"]: b for b in _belief_rows(
            conn, [x for r in rows for x in (r[1], r[2]) if x])}
        return {"total": total, "items": [{
            "id": r[0], "detail": _clip(r[3], 200), "created_at": r[4],
            "a": beliefs.get(r[1]) or {"belief_id": r[1], "missing": True},
            "b": beliefs.get(r[2]) or {"belief_id": r[2], "missing": True},
        } for r in rows]}
    finally:
        conn.close()


def fact_histories(db_path, limit: int = 100) -> dict:
    """Facts that were replaced, grouped into their value histories: every
    version of an (entity, predicate) in order, with when each held."""
    limit = max(1, min(int(limit), 500))
    conn = _connect(db_path)
    try:
        cols = _cols(conn, "facts")
        if "superseded_by" not in cols:
            return {"total": 0, "items": []}
        keys = conn.execute(
            "SELECT entity_id, predicate_canonical, COUNT(*) n, MAX(created_at) last "
            "FROM facts GROUP BY entity_id, predicate_canonical "
            "HAVING SUM(superseded_by IS NOT NULL) > 0 ORDER BY last DESC LIMIT ?",
            (limit,)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM facts GROUP BY entity_id, predicate_canonical "
            "HAVING SUM(superseded_by IS NOT NULL) > 0)").fetchone()[0]
        names = {}
        ents = [k[0] for k in keys if k[0]]
        for i in range(0, len(ents), 500):
            part = ents[i:i + 500]
            for r in conn.execute("SELECT belief_id, name FROM entities WHERE belief_id IN (%s)"
                                  % ",".join("?" * len(part)), part):
                names[r[0]] = r[1]
        items = []
        for entity_id, predicate, n, _last in keys:
            versions = conn.execute(
                "SELECT belief_id, value, status, created_at, valid_from, valid_until, superseded_by "
                "FROM facts WHERE entity_id=? AND predicate_canonical=? ORDER BY created_at, belief_id",
                (entity_id, predicate)).fetchall()
            items.append({
                "entity_id": entity_id, "entity": names.get(entity_id) or entity_id,
                "predicate": predicate, "versions": [{
                    "belief_id": v[0], "value": _clip(v[1], 160), "status": v[2],
                    "created_at": v[3], "valid_from": v[4], "valid_until": v[5],
                    "superseded_by": v[6]} for v in versions]})
        return {"total": total, "items": items}
    finally:
        conn.close()


def duplicate_notes(db_path, limit: int = 50) -> dict:
    """Groups of ACTIVE notes with byte-identical bodies under one owner and
    subject — the rows the exact-content merge folds together from now on, but
    that a store written before it still holds."""
    limit = max(1, min(int(limit), 200))
    conn = _connect(db_path)
    try:
        cols = _cols(conn, "notes")
        if "body" not in cols:
            return {"groups": 0, "redundant": 0, "items": []}
        rows = conn.execute(
            "SELECT owner, note_type, subject, body, COUNT(*) n, MIN(created_at), MAX(created_at), "
            "MIN(belief_id) FROM notes WHERE status='active' "
            "GROUP BY owner, domain, note_type, subject, body HAVING n > 1 ORDER BY n DESC").fetchall()
        return {
            "groups": len(rows),
            "redundant": sum(r[4] - 1 for r in rows),
            "items": [{"owner": r[0], "note_type": r[1], "subject": r[2], "text": _clip(r[3], 240),
                       "copies": r[4], "first_at": r[5], "last_at": r[6], "example_id": r[7]}
                      for r in rows[:limit]],
        }
    finally:
        conn.close()


def cron_job_names(hermes_home) -> Dict[str, str]:
    """{job_id: name} from Hermes' cron job registry, if one is readable.

    Best-effort labelling only: a missing or unfamiliar file returns {} and the
    lanes keep their job ids."""
    names: Dict[str, str] = {}
    for rel in ("cron/jobs.json",):
        p = Path(hermes_home) / rel
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        jobs = data.get("jobs") if isinstance(data, dict) else data
        if isinstance(jobs, dict):
            jobs = [dict(v, id=k) if isinstance(v, dict) else {"id": k} for k, v in jobs.items()]
        for j in jobs or []:
            if isinstance(j, dict) and j.get("id"):
                names[str(j["id"])] = str(j.get("name") or j.get("title") or j["id"])[:80]
    return names


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
def register(router, get_db_path: Callable[[], Optional[Path]], hermes_home: Callable[[], Path],
             query: Callable = None):
    """Bind the data functions to `router` under /atlas/…"""
    Q = query or (lambda default=None, **_k: default)

    def _db():
        p = get_db_path()
        if not p:
            raise FileNotFoundError("no Chronicle database")
        return p

    def _safe(fn, empty):
        try:
            return fn()
        except FileNotFoundError:
            return dict(empty, error="no Chronicle database")
        except sqlite3.Error as e:
            return dict(empty, error="store unreadable: %s" % e)

    @router.get("/atlas/summary")
    def atlas_summary():
        return _safe(lambda: _cache.get(("summary", str(_db())), 300, lambda: summary(_db())),
                     {"events": 0})

    try:
        from fastapi.responses import Response as _Response
    except Exception:   # the test stub has no responses module
        _Response = None

    @router.get("/atlas/events")
    def atlas_events(after_seq: int = Q(0, ge=0), limit: int = Q(_CHUNK_MAX, ge=1, le=_CHUNK_MAX)):
        empty = {"n": 0, "done": True, "next_after_seq": after_seq}
        if _Response is None:
            return _safe(lambda: events_chunk(_db(), after_seq, limit), empty)
        try:
            return _Response(content=events_json(_db(), after_seq, limit), media_type="application/json")
        except FileNotFoundError:
            return dict(empty, error="no Chronicle database")
        except sqlite3.Error as e:
            return dict(empty, error="store unreadable: %s" % e)

    @router.get("/atlas/event")
    def atlas_event(seq: int = Q(0, ge=0)):
        return _safe(lambda: event_detail(_db(), seq), {"found": False})

    @router.get("/atlas/session")
    def atlas_session(session_id: str = Q("", alias="id")):
        return _safe(lambda: session_detail(_db(), session_id), {"found": False})

    @router.get("/atlas/belief")
    def atlas_belief(belief_id: str = Q("", alias="id")):
        return _safe(lambda: belief_detail(_db(), belief_id), {"found": False})

    @router.get("/atlas/contradictions")
    def atlas_contradictions(limit: int = Q(100, ge=1, le=500), offset: int = Q(0, ge=0)):
        return _safe(lambda: _cache.get(("contra", str(_db()), limit, offset), 30,
                                        lambda: contradictions(_db(), limit, offset)),
                     {"total": 0, "items": []})

    @router.get("/atlas/histories")
    def atlas_histories(limit: int = Q(100, ge=1, le=500)):
        return _safe(lambda: _cache.get(("hist", str(_db()), limit), 60,
                                        lambda: fact_histories(_db(), limit)),
                     {"total": 0, "items": []})

    @router.get("/atlas/duplicates")
    def atlas_duplicates(limit: int = Q(50, ge=1, le=200)):
        return _safe(lambda: _cache.get(("dups", str(_db()), limit), 120,
                                        lambda: duplicate_notes(_db(), limit)),
                     {"groups": 0, "redundant": 0, "items": []})

    @router.get("/atlas/lanes")
    def atlas_lanes():
        try:
            return {"cron_names": cron_job_names(hermes_home())}
        except Exception:
            return {"cron_names": {}}

    return router
