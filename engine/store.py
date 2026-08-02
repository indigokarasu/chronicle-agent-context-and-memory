"""
Chronicle — Storage abstraction & SQLite backend (§24.2, §24.1).

Single-node store: WAL, FTS5, brute-force vectors, recursive-CTE graph, single
writer. The write path is the consistency unit (§25): `append_event` inserts the
event, updates the head, enqueues the git-mirror row, runs the incremental
reduce, and advances the projection watermark — all inside ONE re-entrant
transaction (I7, §6.3 step 6). Readers never see a belief without its
justifications because both are written in that single transaction.
"""

from __future__ import annotations

import datetime
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("chronicle.store")

# Bumped whenever _SCHEMA changes shape; recorded in meta.schema_version by
# _migrate. 2 = curation_jobs.run_after + task 'embed' (deferred embeds, §24.4).
# 3 = task 'digest' (entity consolidation digests, §u2).
SCHEMA_VERSION = 3

# Belief tables that carry the common envelope (§8.1).
BELIEF_TABLES = ["facts", "episodes", "notes", "refs", "relationships", "procedures"]
# Statuses that take a belief out of search; its embedding becomes dead weight.
_INACTIVE_STATUSES = {"retracted", "superseded", "inactive", "expired"}
KIND_TABLE = {
    "fact": "facts", "episode": "episodes", "note": "notes", "reference": "refs",
    "relationship": "relationships", "entity": "entities", "procedure": "procedures",
    "user_knowledge": "user_knowledge",
}


def now_iso() -> str:
    """RFC3339, UTC, millisecond precision, Z suffix (§5.4)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def _iso_in(seconds: float) -> str:
    """now_iso() shifted forward — identical fixed-width format, so a stored
    timestamp and a live one compare with plain string ordering (job run_after)."""
    t = (datetime.datetime.now(datetime.timezone.utc)
         + datetime.timedelta(seconds=max(0.0, float(seconds))))
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


class MemoryStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self.reducer = None  # set by ChronicleCore; enables inline reduce on append (I7)
        self.vector_index = None  # set by ChronicleCore; optional ANN index for fast KNN
        self._lock_waits = 0
        self._lock_acqs = 0
        self._init_db()

    # -- connection & transaction ------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        if getattr(self._local, "conn", None) is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def transaction(self):
        """Re-entrant exclusive write transaction; only the outermost commits."""
        contended = self._write_lock.acquire(blocking=False)
        if not contended:
            self._lock_waits += 1
            self._write_lock.acquire()
        self._lock_acqs += 1
        conn = self._conn()
        depth = getattr(self._local, "depth", 0)
        self._local.depth = depth + 1
        try:
            yield conn
            if self._local.depth == 1:
                conn.commit()
        except Exception:
            if self._local.depth == 1:
                conn.rollback()
            raise
        finally:
            self._local.depth -= 1
            self._write_lock.release()

    def lock_contention(self) -> float:
        return (self._lock_waits / self._lock_acqs) if self._lock_acqs else 0.0

    # -- schema ------------------------------------------------------------

    def _init_db(self):
        conn = self._conn()
        conn.executescript(_SCHEMA)
        self._migrate(conn)
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('projection_seq','0')")
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('head_event_id','')")
        # Seed the monotonic event_seq counter (used by append_event's atomic
        # UPDATE...RETURNING). Omitting this left fresh DBs with no event_seq row,
        # so the first append_event crashed with "NoneType is not subscriptable".
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('event_seq', "
                     "(SELECT COALESCE(MAX(seq),0) FROM events))")
        conn.commit()

    def _migrate(self, conn):
        """Bring an EXISTING db up to _SCHEMA, idempotently (I2 in spirit).

        `CREATE TABLE IF NOT EXISTS` is a no-op on a table that already exists, so
        every _SCHEMA edit is invisible to older stores unless it is migrated here.
        Skipping this is not cosmetic: an old curation_jobs makes append_event's
        enqueue fail the task CHECK *inside* the durable-capture transaction (I12),
        and makes every claim fail on the missing run_after column.

        Each step probes the live schema first, so re-running costs two catalog
        reads and changes nothing."""
        if not _has_col(conn, "curation_jobs", "run_after"):
            logger.info("schema migration: curation_jobs + run_after (deferred retry)")
            conn.execute("ALTER TABLE curation_jobs ADD COLUMN run_after TEXT")
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                           ("curation_jobs",)).fetchone()
        # Each new task value needs its OWN membership check: a DB migrated for
        # 'embed' (schema_version 2) already has 'embed' in the CHECK, so testing
        # only that string misses 'digest' (schema_version 3) entirely and every
        # v2 DB enqueues a 'digest' job that fails the CHECK inside append_event's
        # txn (I12), aborting the enclosing extract job. One rebuild covers both.
        missing = [t for t in ("embed", "digest") if row and f"'{t}'" not in (row[0] or "")]
        if missing:
            logger.info("schema migration: curation_jobs task CHECK += %s", ", ".join(missing))
            self._rebuild_curation_jobs(conn)
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))

    def _rebuild_curation_jobs(self, conn):
        """Recreate curation_jobs so its task CHECK admits 'embed' (SQLite cannot
        ALTER a CHECK): create → copy → drop → rename → reindex, all in ONE explicit
        transaction, per SQLite's documented table-rebuild procedure.

        foreign_keys is toggled OUTSIDE the transaction (the pragma is a silent
        no-op inside one) because curation_jobs.depends_on references the very
        table being dropped. executescript() is avoided for the same reason — it
        commits before running."""
        conn.commit()                                   # no implicit txn open, so the pragma bites
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.execute("BEGIN")
            conn.execute(_CURATION_JOBS_DDL % "curation_jobs_new")
            conn.execute(f"INSERT INTO curation_jobs_new({_JOB_COLS}) "
                         f"SELECT {_JOB_COLS} FROM curation_jobs")
            conn.execute("DROP TABLE curation_jobs")
            conn.execute("ALTER TABLE curation_jobs_new RENAME TO curation_jobs")
            for ddl in _JOBS_INDEX_DDLS:
                conn.execute(ddl)
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")     # must not mask the real failure
            except Exception:
                pass
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")

    # -- meta --------------------------------------------------------------

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str):
        with self.transaction() as conn:
            conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    # -- event log (the only write entrypoint, §6.3) -----------------------

    def append_event(self, event: dict) -> str:
        """Append + reduce + git-queue + watermark atomically (I7). Idempotent (I2)."""
        eid = event["event_id"]
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM events WHERE event_id=?", (eid,)).fetchone():
                return eid  # idempotent hit: no reduce, no git, no curation
            # Monotonic seq from a single authoritative counter (meta.event_seq),
            # updated atomically inside this transaction. Replaces the racy
            # "SELECT MAX(seq)+1" which caused UNIQUE(seq) collisions under
            # concurrent writers (chronicle_event_seq_unique_constraint defect).
            # Self-heal: ensure the event_seq counter row exists even on a DB
            # opened before _init_db() ran (e.g. existing DBs missing the seed).
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('event_seq', "
                         "(SELECT COALESCE(MAX(seq),0) FROM events))")
            seq = conn.execute(
                "UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='event_seq' "
                "RETURNING CAST(value AS INTEGER)"
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO events(event_id,seq,order_key,type,payload,parents,actor,owner,
                   trust_level,session_id,branch_id,occurred_at,recorded_at,prev_head,sig)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (eid, seq, event.get("order_key"), event["type"],
                 _as_json(event["payload"]), _as_json(event.get("parents", [])),
                 event["actor"], event["owner"], event.get("trust_level", 2),
                 event.get("session_id"), event.get("branch_id") or event.get("session_id"),
                 event["occurred_at"], event.get("recorded_at") or now_iso(),
                 event.get("prev_head"), event.get("sig")))
            conn.execute("UPDATE meta SET value=? WHERE key='head_event_id'", (eid,))
            conn.execute("INSERT INTO git_queue(event_id,created_at) VALUES(?,?)",
                         (eid, event.get("recorded_at") or now_iso()))
            ev = dict(event)
            ev["seq"] = seq
            if self.reducer is not None:
                self.reducer.reduce(ev)            # nested txn → same conn (I7)
            conn.execute("UPDATE meta SET value=? WHERE key='projection_seq'", (str(seq),))
        return eid

    def get_event(self, event_id: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return dict(row) if row else None

    def get_events_since(self, seq: int, limit: Optional[int] = None) -> List[dict]:
        """Events with seq > `seq`, ascending. Pass limit=None (default) for
        unbounded full-scan; pass an explicit N for paginated reads."""
        q = "SELECT * FROM events WHERE seq > ? ORDER BY seq"
        params: list = [seq]
        if limit is not None:
            q += " LIMIT ?"
            params.append(limit)
        rows = self._conn().execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def iter_events_since(self, seq: int, batch_size: int = 50000):
        """Stream events with seq > `seq` in batches of `batch_size`, ascending
        by seq. Memory-safe for multi-hundred-k event stores: never holds more
        than one batch in memory at a time."""
        cur_seq = seq
        while True:
            rows = self._conn().execute(
                "SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?",
                (cur_seq, batch_size)).fetchall()
            if not rows:
                break
            for r in rows:
                yield dict(r)
            new_seq = rows[-1]["seq"]
            if new_seq == cur_seq:
                break
            cur_seq = new_seq

    def get_events_as_of(self, recorded_at: str) -> List[dict]:
        rows = self._conn().execute(
            "SELECT * FROM events WHERE recorded_at <= ? ORDER BY seq", (recorded_at,)).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_session(self, session_id: str, since_seq: int = 0,
                              types: Optional[Sequence[str]] = None,
                              limit: Optional[int] = None) -> List[dict]:
        """Events of one session, ascending by seq.

        `types` and `limit` exist so a caller that wants "the first N observed
        turns" can say so IN SQL. A session has no natural size bound — a
        long-running assistant session accumulates thousands of events — and
        filtering/slicing in Python still pays to read every row, build a dict
        for each, and (for retrieval) json-decode each payload. idx_events_session
        is (session_id, seq), which serves both the WHERE and the ORDER BY, so
        LIMIT stops the scan early rather than sorting the session first.
        """
        q = "SELECT * FROM events WHERE session_id=? AND seq > ?"
        params: list = [session_id, since_seq]
        if types:
            q += " AND type IN (%s)" % ",".join(["?"] * len(types))
            params.extend(types)
        q += " ORDER BY seq"
        if limit is not None:
            q += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn().execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_type(self, type_: str, since_seq: int = 0) -> List[dict]:
        rows = self._conn().execute(
            "SELECT * FROM events WHERE type=? AND seq > ? ORDER BY seq", (type_, since_seq)).fetchall()
        return [dict(r) for r in rows]

    def get_head_event_id(self) -> str:
        return self.get_meta("head_event_id", "") or ""

    def get_projection_seq(self) -> int:
        return int(self.get_meta("projection_seq", "0") or "0")

    def set_projection_seq(self, seq: int):
        self.set_meta("projection_seq", str(seq))

    def max_seq(self) -> int:
        return self._conn().execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]

    # -- raw FTS (§8.6) — keyed by event_id so forbidden can delete --------

    def fts_index_observed(self, event_id: str, excerpt: str):
        with self.transaction() as conn:
            conn.execute("DELETE FROM observed_fts WHERE event_id=?", (event_id,))
            conn.execute("INSERT INTO observed_fts(event_id, excerpt) VALUES(?,?)", (event_id, excerpt))

    def fts_search_observed(self, query: str, limit: int = 20) -> List[dict]:
        q = _fts_query(query)
        if not q:
            return []
        try:
            rows = self._conn().execute(
                "SELECT event_id, excerpt, rank FROM observed_fts WHERE observed_fts MATCH ? "
                "ORDER BY rank LIMIT ?", (q, limit)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def fts_delete_observed(self, event_id: str):
        with self.transaction() as conn:
            conn.execute("DELETE FROM observed_fts WHERE event_id=?", (event_id,))

    # -- belief FTS (Tier-1, §18.1) ---------------------------------------

    def fts_search_beliefs(self, query: str, limit: int = 20) -> List[dict]:
        q = _fts_query(query)
        if not q:
            return []
        try:
            rows = self._conn().execute(
                "SELECT belief_id, kind, rank FROM belief_fts WHERE belief_fts MATCH ? "
                "ORDER BY rank LIMIT ?", (q, limit)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _fts_index_belief(self, conn, belief_id: str, kind: str, text: str):
        conn.execute("DELETE FROM belief_fts WHERE belief_id=?", (belief_id,))
        if text:
            conn.execute("INSERT INTO belief_fts(belief_id, kind, text) VALUES(?,?,?)",
                         (belief_id, kind, text))

    # -- vectors (§24.4, brute force) -------------------------------------

    def add_observed_vector(self, event_id: str, embedding: bytes, model: str, owner: str):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO observed_vectors(event_id,embedding,model,owner,created_at) "
                         "VALUES(?,?,?,?,?)", (event_id, embedding, model, owner, now_iso()))
            # Mirror into the optional ANN index (§27 vector_index, u5), on the
            # SAME connection/transaction -- this can be nested arbitrarily deep
            # inside append_event's single re-entrant transaction (I7), so it
            # must never commit independently (see vector_index.py docstring).
            if self.vector_index:
                try:
                    self.vector_index.add_observed_vector(conn, event_id, embedding)
                except Exception as e:
                    logger.warning("Failed to update vector_index for %s: %s", event_id, e)

    def delete_observed_vector(self, event_id: str):
        """Drop a single observed event's vector (both the brute-force row and
        its ANN mirror). Used where a raw event stops being retrievable outright
        -- e.g. §20.5 unlearn/forbidden content -- as opposed to
        prune_observed_vectors's bulk keep-list rebuild."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM observed_vectors WHERE event_id=?", (event_id,))
            if self.vector_index:
                try:
                    self.vector_index.delete_observed_vector(conn, event_id)
                except Exception as e:
                    logger.warning("Failed to delete vector_index entry for %s: %s", event_id, e)

    def add_memory_vector(self, belief_id: str, kind: str, embedding: bytes, model: str):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO memory_vectors(belief_id,kind,embedding,model,created_at) "
                         "VALUES(?,?,?,?,?)", (belief_id, kind, embedding, model, now_iso()))

    def has_observed_vector(self, event_id: str) -> bool:
        return self._conn().execute("SELECT 1 FROM observed_vectors WHERE event_id=?",
                                    (event_id,)).fetchone() is not None

    def has_memory_vector(self, belief_id: str, kind: str) -> bool:
        return self._conn().execute("SELECT 1 FROM memory_vectors WHERE belief_id=? AND kind=?",
                                    (belief_id, kind)).fetchone() is not None

    def delete_memory_vector(self, belief_id: str):
        """Drop a belief's embedding once it is no longer searchable. Without
        this, retracted/superseded beliefs leak vectors that bloat the brute-
        force scan forever (their facts stay out of results, but the vectors
        are still scanned on every query)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM memory_vectors WHERE belief_id=?", (belief_id,))

    def add_session_vector(self, session_id: str, summary: str, embedding: bytes, owner: str, occurred_at: str):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO session_index(session_id,summary,embedding,owner,occurred_at) "
                         "VALUES(?,?,?,?,?)", (session_id, summary, embedding, owner, occurred_at))

    def iter_memory_vectors(self) -> List[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM memory_vectors").fetchall()]

    def iter_observed_vectors(self) -> List[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM observed_vectors").fetchall()]

    def iter_observed_vectors_paged(self, batch_size: int = 1000):
        """Yield batches of observed_vectors, paged by rowid (streaming, O(batch) memory)."""
        conn = self._conn()
        min_rowid = 0
        while True:
            rows = conn.execute(
                "SELECT rowid, * FROM observed_vectors WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (min_rowid, batch_size)).fetchall()
            if not rows:
                break
            batch = [dict(r) for r in rows]
            if batch:
                min_rowid = batch[-1]["rowid"]
            yield batch

    def get_observed_vectors_by_ids(self, event_ids) -> Dict[str, dict]:
        """Stored vectors for specific events, keyed by event_id (§24.4, u5).

        Random access is what the paged scan never needs and the ANN fast path
        cannot do without: `iter_observed_vectors_paged` visits EVERY row, so
        retrieve_raw's paged branch credits every already-scored FTS hit as a
        side effect of scanning past it, while a bounded KNN window reaches
        only its own top-k. Without a by-id lookup an FTS hit outside that
        window silently loses its whole vector contribution. Chunked to stay
        under SQLITE_MAX_VARIABLE_NUMBER; ids with no vector are simply absent.
        """
        out: Dict[str, dict] = {}
        ids = [e for e in dict.fromkeys(event_ids) if e]
        if not ids:
            return out
        conn = self._conn()
        chunk = 500
        for i in range(0, len(ids), chunk):
            part = ids[i:i + chunk]
            ph = ",".join("?" * len(part))
            for r in conn.execute(
                    "SELECT event_id, embedding, owner FROM observed_vectors "
                    f"WHERE event_id IN ({ph})", part).fetchall():
                out[r["event_id"]] = dict(r)
        return out

    def add_projection_vector(self, provider: str, external_id: str, embedding: bytes, model: str,
                              owner: str):
        """Store or update a projection vector from an external data source.

        `owner` is a REAL principal-shaped owner (e.g. the principal that
        triggered the sweep/enqueue, same convention as observed/session
        vectors) — never a placeholder — so the retrieve_raw scan can run the
        same access.can_read check it runs for every other vector channel."""
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO projection_vectors"
                         "(provider,external_id,embedding,model,owner,created_at) "
                         "VALUES(?,?,?,?,?,?)", (provider, external_id, embedding, model, owner, now_iso()))

    def has_projection_vector(self, provider: str, external_id: str) -> bool:
        return self._conn().execute(
            "SELECT 1 FROM projection_vectors WHERE provider=? AND external_id=?",
            (provider, external_id)).fetchone() is not None

    def get_projection_vectors_by_ids(self, proj_ids: List[Tuple[str, str]]) -> Dict[str, dict]:
        """Stored projection vectors for specific (provider, external_id) pairs.

        Returns dict keyed by "proj:<provider>:<external_id>" namespace id, mirroring
        the retrieval.retrieve_raw session id namespacing "session:<session_id>".
        Chunked to stay under SQLITE_MAX_VARIABLE_NUMBER.
        """
        out: Dict[str, dict] = {}
        if not proj_ids:
            return out
        conn = self._conn()
        chunk = 250  # half of 500 event chunk due to 2 params per id
        for i in range(0, len(proj_ids), chunk):
            part = proj_ids[i:i + chunk]
            params = []
            conditions = []
            for provider, external_id in part:
                conditions.append("(provider=? AND external_id=?)")
                params.extend([provider, external_id])
            where_clause = " OR ".join(conditions)
            for r in conn.execute(
                    f"SELECT provider, external_id, embedding, owner FROM projection_vectors "
                    f"WHERE {where_clause}", params).fetchall():
                key = f"proj:{r['provider']}:{r['external_id']}"
                out[key] = {"embedding": r["embedding"], "provider": r["provider"],
                            "external_id": r["external_id"], "owner": r["owner"]}
        return out

    def iter_projection_vectors_paged(self, batch_size: int = 1000):
        """Yield batches of projection_vectors, paged by rowid (streaming, O(batch) memory)."""
        conn = self._conn()
        min_rowid = 0
        while True:
            rows = conn.execute(
                "SELECT rowid, * FROM projection_vectors WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (min_rowid, batch_size)).fetchall()
            if not rows:
                break
            batch = [dict(r) for r in rows]
            if batch:
                min_rowid = batch[-1]["rowid"]
            yield batch

    def delete_projection_vectors(self, provider: str):
        """Delete all projection vectors from a specific provider."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM projection_vectors WHERE provider=?", (provider,))

    def iter_session_vectors(self) -> List[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM session_index").fetchall()]

    def iter_session_vectors_paged(self, batch_size: int = 1000):
        """Yield batches of session_index, paged by rowid (streaming, O(batch) memory)."""
        conn = self._conn()
        min_rowid = 0
        while True:
            rows = conn.execute(
                "SELECT rowid, * FROM session_index WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (min_rowid, batch_size)).fetchall()
            if not rows:
                break
            batch = [dict(r) for r in rows]
            if batch:
                min_rowid = batch[-1]["rowid"]
            yield batch

    def vector_count(self) -> int:
        return self.count_rows("memory_vectors") + self.count_rows("observed_vectors")

    # -- belief CRUD -------------------------------------------------------

    def upsert_belief(self, table: str, belief: dict):
        with self.transaction() as conn:
            cols = list(belief.keys())
            ph = ",".join(["?"] * len(cols))
            names = ",".join(cols)
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "belief_id")
            conn.execute(
                f"INSERT INTO {table}({names}) VALUES({ph}) "
                f"ON CONFLICT(belief_id) DO UPDATE SET {updates}",
                [belief[c] for c in cols])
            kind, text = _belief_fts_text(table, belief)
            if kind:
                self._fts_index_belief(conn, belief["belief_id"], kind, text)

    def update_belief(self, table: str, belief_id: str, **fields):
        if not fields:
            return
        with self.transaction() as conn:
            sets = ",".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE {table} SET {sets} WHERE belief_id=?",
                         [*fields.values(), belief_id])
        if fields.get("status") in _INACTIVE_STATUSES:
            self.delete_memory_vector(belief_id)

    def update_belief_all_tables(self, belief_id: str, **fields):
        sets = ",".join(f"{k}=?" for k in fields)
        with self.transaction() as conn:
            for t in BELIEF_TABLES:
                if all(_has_col(conn, t, k) for k in fields):
                    conn.execute(f"UPDATE {t} SET {sets} WHERE belief_id=?",
                                 [*fields.values(), belief_id])
        if fields.get("status") in _INACTIVE_STATUSES:
            self.delete_memory_vector(belief_id)

    def get_belief(self, table: str, belief_id: str) -> Optional[dict]:
        row = self._conn().execute(f"SELECT * FROM {table} WHERE belief_id=?", (belief_id,)).fetchone()
        return dict(row) if row else None

    def find_belief(self, belief_id: str) -> Optional[Tuple[str, dict]]:
        for t in BELIEF_TABLES + ["entities", "user_knowledge"]:
            row = self._conn().execute(f"SELECT * FROM {t} WHERE belief_id=?", (belief_id,)).fetchone()
            if row:
                return t, dict(row)
        return None

    def query_beliefs(self, table: str, where: str = "1=1", params: tuple = (),
                      limit: int = 50, order: str = "") -> List[dict]:
        order_sql = f" ORDER BY {order}" if order else ""
        rows = self._conn().execute(
            f"SELECT * FROM {table} WHERE {where}{order_sql} LIMIT ?", (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    # -- justifications (§9.1) --------------------------------------------

    def add_justification(self, belief_id: str, support: str, support_kind: str, rule: str = ""):
        with self.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO justifications(belief_id,support,support_kind,rule) "
                         "VALUES(?,?,?,?)", (belief_id, support, support_kind, rule))

    def get_justifications(self, belief_id: str) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM justifications WHERE belief_id=?", (belief_id,)).fetchall()]

    def get_dependents(self, support: str) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM justifications WHERE support=?", (support,)).fetchall()]

    def delete_justifications(self, belief_id: str):
        with self.transaction() as conn:
            conn.execute("DELETE FROM justifications WHERE belief_id=?", (belief_id,))

    def active_unjustified(self) -> List[str]:
        """Active beliefs with zero justifications (I5 health check)."""
        out = []
        conn = self._conn()
        for t in BELIEF_TABLES:
            rows = conn.execute(
                f"SELECT belief_id FROM {t} WHERE status='active' AND belief_id NOT IN "
                f"(SELECT belief_id FROM justifications)").fetchall()
            out.extend(r["belief_id"] for r in rows)
        return out

    # -- contradictions ----------------------------------------------------

    def open_contradiction(self, belief_a: str, belief_b: str, detail: str = ""):
        import uuid
        with self.transaction() as conn:
            conn.execute("INSERT INTO contradictions(id,belief_a,belief_b,detail,status,created_at) "
                         "VALUES(?,?,?,?, 'open', ?)",
                         (str(uuid.uuid4()), belief_a, belief_b, detail, now_iso()))

    def get_open_contradictions(self, limit: int = 50) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM contradictions WHERE status='open' ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()]

    def resolve_contradiction(self, contradiction_id: str):
        with self.transaction() as conn:
            conn.execute("UPDATE contradictions SET status='resolved' WHERE id=?", (contradiction_id,))

    # -- corrections -------------------------------------------------------

    def record_correction(self, belief_id: str, reason: str, correction_ref: str, propagated: List[str]):
        import uuid
        with self.transaction() as conn:
            conn.execute("INSERT INTO corrections(id,belief_id,reason,correction_ref,propagated,created_at) "
                         "VALUES(?,?,?,?,?,?)",
                         (str(uuid.uuid4()), belief_id, reason, correction_ref,
                          json.dumps(propagated), now_iso()))

    # -- sessions (§12.2) --------------------------------------------------

    def upsert_session(self, session: dict):
        with self.transaction() as conn:
            cols = list(session.keys())
            ph = ",".join(["?"] * len(cols))
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "session_id")
            conn.execute(f"INSERT INTO sessions({','.join(cols)}) VALUES({ph}) "
                         f"ON CONFLICT(session_id) DO UPDATE SET {updates}",
                         [session[c] for c in cols])

    def get_session(self, session_id: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def get_sessions_by_status(self, statuses) -> List[dict]:
        marks = ",".join("?" * len(statuses))
        return [dict(r) for r in self._conn().execute(
            f"SELECT * FROM sessions WHERE status IN ({marks})", tuple(statuses)).fetchall()]

    # -- curation jobs (§17) ----------------------------------------------

    def enqueue_curation(self, task: str, payload: dict, depends_on: Optional[int] = None) -> Optional[int]:
        """Queue a curation job, collapsing an identical (task, payload) pair that
        is already pending or running — the same guard enqueue_embed_job applies
        below, on the same canonical-json key and served by the same partial index.

        Callers that enqueue unconditionally are the reason. _task_extract ends
        with `enqueue_curation("digest", {"entity_id": s})` for every subject it
        touched (§u2 deliberately puts the >=3-fact threshold in the handler, not
        the enqueue) and one `canonicalize` job per extract — including the very
        common `{"subjects": []}`. Draining N byte-identical jobs recomputes one
        answer N times. It is safe to collapse them precisely because they are
        byte-identical: each handler reads current state when it runs, so the one
        surviving job — which stays pending behind the extract jobs that queued
        it, since claim is by ascending id — sees everything the collapsed ones
        would have, and the end state is the same.

        depends_on is left out of the key on purpose: two jobs with the same
        (task, payload) are the same unit of work whoever is waiting on them.
        Returns the job id, or None when it deduped."""
        canon = json.dumps(payload, sort_keys=True)
        with self.transaction() as conn:
            dup = conn.execute(
                "SELECT id FROM curation_jobs WHERE task=? AND status IN ('pending','running') "
                "AND payload=?", (task, canon)).fetchone()
            if dup is not None:
                return None
            cur = conn.execute(
                "INSERT INTO curation_jobs(task,payload,depends_on,created_at) VALUES(?,?,?,?)",
                (task, canon, depends_on, now_iso()))
            return cur.lastrowid

    def enqueue_embed_job(self, target_id: str, kind: str, text: str, *,
                         owner: Optional[str] = None, provider: Optional[str] = None,
                         external_id: Optional[str] = None) -> Optional[int]:
        """Queue a deferred vector write (§24.4), unless the same one is already
        queued. Degraded mode can re-touch one belief many times (every update
        re-enters the reduce), and the queue must not grow without bound; the
        payload is canonical json, so an identical (target, kind, text, ...)
        dedupes. Returns the job id, or None when deduped.

        `owner`/`provider`/`external_id` are optional extras carried through to
        the handler for kinds that need them (kind='projection', §g5) — the
        'observed'/belief-kind callers omit them and see no change in the
        dedup key, so this is additive, not a behavior change for them."""
        payload_dict = {"target_id": target_id, "kind": kind, "text": (text or "")[:8000]}
        if owner is not None:
            payload_dict["owner"] = owner
        if provider is not None:
            payload_dict["provider"] = provider
        if external_id is not None:
            payload_dict["external_id"] = external_id
        payload = json.dumps(payload_dict, sort_keys=True)
        with self.transaction() as conn:
            dup = conn.execute("SELECT id FROM curation_jobs WHERE task='embed' AND "
                               "status IN ('pending','running') AND payload=?", (payload,)).fetchone()
            if dup is not None:
                return None
            cur = conn.execute("INSERT INTO curation_jobs(task,payload,created_at) "
                               "VALUES('embed',?,?)", (payload, now_iso()))
            return cur.lastrowid

    def enqueue_projection_embed(self, provider: str, external_id: str, text: str,
                                 owner: Optional[str] = None) -> Optional[int]:
        """Queue a projection's rendered text for embedding via the SAME deferred
        embed-job path every other vector channel uses — never inline at sweep
        time (§g5a). The target id is namespaced "proj:<provider>:<external_id>",
        mirroring the id retrieve_raw's projection scan produces, so a queued
        job and its eventual vector agree on identity by construction."""
        target_id = f"proj:{provider}:{external_id}"
        return self.enqueue_embed_job(target_id, "projection", text, owner=owner,
                                      provider=provider, external_id=external_id)

    def claim_curation_job(self) -> Optional[dict]:
        """Lowest-id ready job. Ready = pending, dependencies done, and NOT deferred:
        a job whose run_after is still in the future stays invisible (§17.3)."""
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM curation_jobs WHERE status='pending' AND "
                "(run_after IS NULL OR run_after <= ?) AND "
                "(depends_on IS NULL OR depends_on IN (SELECT id FROM curation_jobs WHERE status='done')) "
                "ORDER BY id LIMIT 1", (now_iso(),)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE curation_jobs SET status='running', started_at=?, attempts=attempts+1 "
                         "WHERE id=?", (now_iso(), row["id"]))
            return dict(row)

    def complete_curation_job(self, job_id: int, error: Optional[str] = None):
        with self.transaction() as conn:
            conn.execute("UPDATE curation_jobs SET status=?, finished_at=?, error=? WHERE id=?",
                         ("failed" if error else "done", now_iso(), error, job_id))

    def defer_curation_job(self, job_id: int, delay_seconds: int, error: Optional[str] = None):
        """Put a claimed job back as pending, invisible until `delay_seconds` from now.

        run_after is written in the same now_iso() format as every other timestamp
        column so claim's `run_after <= ?` comparison is a plain lexicographic one
        on fixed-width RFC3339 (a SQLite-computed 'YYYY-MM-DD HH:MM:SS' would sort
        BELOW every 'T'-separated value and fire instantly). The reason is parked in
        `error` so the queue explains itself; status stays 'pending', so it reads as
        waiting, not failed."""
        run_after = _iso_in(delay_seconds)
        with self.transaction() as conn:
            conn.execute("UPDATE curation_jobs SET status='pending', run_after=?, started_at=NULL, "
                         "error=? WHERE id=?", (run_after, error, job_id))
        return run_after

    def pending_curation_count(self) -> int:
        return self.count_rows("curation_jobs", "status='pending'")

    def get_curation_jobs(self, where: str = "1=1", limit: int = 100) -> List[dict]:
        """Job rows for diagnostics/tests (same trusted-where contract as count_rows)."""
        return [dict(r) for r in self._conn().execute(
            f"SELECT * FROM curation_jobs WHERE {where} ORDER BY id LIMIT ?", (int(limit),)).fetchall()]

    # -- extractions (§16) -------------------------------------------------

    def record_extraction(self, observed_event: str, extractor_version: str,
                          produced: dict, ambiguous: int, route: str) -> bool:
        """Returns True if newly recorded, False if already done (idempotent, I9)."""
        import uuid
        with self.transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM extractions WHERE observed_event=? AND extractor_version=?",
                (observed_event, extractor_version)).fetchone()
            if exists:
                return False
            conn.execute("INSERT INTO extractions(id,observed_event,extractor_version,produced,"
                         "ambiguous,route,created_at) VALUES(?,?,?,?,?,?,?)",
                         (str(uuid.uuid4()), observed_event, extractor_version,
                          json.dumps(produced), ambiguous, route, now_iso()))
            return True

    def has_extraction(self, observed_event: str, extractor_version: str) -> bool:
        return self._conn().execute(
            "SELECT 1 FROM extractions WHERE observed_event=? AND extractor_version=?",
            (observed_event, extractor_version)).fetchone() is not None

    # -- principals (§15) --------------------------------------------------

    def upsert_principal(self, principal: dict):
        with self.transaction() as conn:
            cols = list(principal.keys())
            ph = ",".join(["?"] * len(cols))
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "principal_id")
            conn.execute(f"INSERT INTO principals({','.join(cols)}) VALUES({ph}) "
                         f"ON CONFLICT(principal_id) DO UPDATE SET {updates}",
                         [principal[c] for c in cols])

    def get_principal(self, principal_id: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM principals WHERE principal_id=?",
                                   (principal_id,)).fetchone()
        return dict(row) if row else None

    def all_principals(self) -> List[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM principals").fetchall()]

    # -- git queue (§26) ---------------------------------------------------

    def get_unflushed_git_events(self, limit: int = 1000) -> List[dict]:
        rows = self._conn().execute(
            "SELECT gq.id AS gid, e.* FROM git_queue gq JOIN events e ON gq.event_id=e.event_id "
            "WHERE gq.committed=0 ORDER BY gq.id LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_git_flushed(self, gids: List[int], git_commit: str):
        with self.transaction() as conn:
            for gid in gids:
                conn.execute("UPDATE git_queue SET committed=1, committed_at=?, git_commit=? WHERE id=?",
                             (now_iso(), git_commit, gid))

    def git_lag(self) -> int:
        return self.count_rows("git_queue", "committed=0")

    # -- tombstones --------------------------------------------------------

    def is_forbidden(self, content_hash: str) -> bool:
        return self._conn().execute("SELECT 1 FROM tombstones WHERE content_hash=?",
                                    (content_hash,)).fetchone() is not None

    def add_tombstone(self, content_hash: str, scope: str = "*"):
        with self.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO tombstones(content_hash,scope,created_at) VALUES(?,?,?)",
                         (content_hash, scope, now_iso()))

    # -- derivation rules (§9.1) ------------------------------------------

    def get_derivation_rules(self, enabled_only: bool = True) -> List[dict]:
        q = "SELECT * FROM derivation_rules" + (" WHERE enabled=1" if enabled_only else "")
        return [dict(r) for r in self._conn().execute(q).fetchall()]

    def get_derivation_rule(self, rule_id: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM derivation_rules WHERE rule_id=?", (rule_id,)).fetchone()
        return dict(row) if row else None

    def upsert_derivation_rule(self, rule: dict):
        with self.transaction() as conn:
            cols = list(rule.keys())
            ph = ",".join(["?"] * len(cols))
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "rule_id")
            conn.execute(f"INSERT INTO derivation_rules({','.join(cols)}) VALUES({ph}) "
                         f"ON CONFLICT(rule_id) DO UPDATE SET {updates}", [rule[c] for c in cols])

    def set_rule_enabled(self, rule_id: str, enabled: bool):
        with self.transaction() as conn:
            conn.execute("UPDATE derivation_rules SET enabled=? WHERE rule_id=?",
                         (1 if enabled else 0, rule_id))

    def add_nogood(self, nogood_id: str, assumptions: List[str]):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO nogoods(nogood_id,assumptions) VALUES(?,?)",
                         (nogood_id, json.dumps(sorted(assumptions))))

    # -- predicates (§8.3) -------------------------------------------------

    def upsert_predicate(self, surface: str, canonical: str, cardinality: str = "single",
                         confidence: float = 0.8):
        with self.transaction() as conn:
            conn.execute("INSERT INTO predicates(surface,canonical,cardinality,confidence,created_at) "
                         "VALUES(?,?,?,?,?) ON CONFLICT(surface) DO UPDATE SET "
                         "canonical=excluded.canonical, cardinality=excluded.cardinality",
                         (surface, canonical, cardinality, confidence, now_iso()))

    def get_predicate(self, surface: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM predicates WHERE surface=?", (surface,)).fetchone()
        return dict(row) if row else None

    def get_predicate_cardinality(self, canonical: str) -> str:
        rows = self._conn().execute(
            "SELECT cardinality FROM predicates WHERE canonical=? OR surface=?",
            (canonical, canonical)).fetchall()
        if not rows:
            return "single"
        # Conservative: if any sense is multi, treat as multi (don't over-fire derivations).
        return "multi" if any(r["cardinality"] == "multi" for r in rows) else "single"

    def predicate_synonyms(self, canonical: str) -> List[str]:
        rows = self._conn().execute("SELECT surface FROM predicates WHERE canonical=?",
                                    (canonical,)).fetchall()
        return [r["surface"] for r in rows]

    # -- capability providers (§14) ---------------------------------------

    def upsert_capability_provider(self, cap: dict):
        with self.transaction() as conn:
            conn.execute("INSERT INTO capability_providers(capability,provider,declared_by,precedence,status) "
                         "VALUES(?,?,?,?,?) ON CONFLICT(capability) DO UPDATE SET "
                         "provider=excluded.provider, declared_by=excluded.declared_by, "
                         "precedence=excluded.precedence, status=excluded.status",
                         (cap["capability"], cap["provider"], cap.get("declared_by", ""),
                          cap.get("precedence", 0), cap.get("status", "active")))

    def get_capability_provider(self, capability: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM capability_providers WHERE capability=?",
                                   (capability,)).fetchone()
        return dict(row) if row else None

    def get_capability_providers(self) -> List[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM capability_providers").fetchall()]

    def set_capability_status(self, capability: str, status: str):
        with self.transaction() as conn:
            conn.execute("UPDATE capability_providers SET status=? WHERE capability=?", (status, capability))

    # -- pointers (§14) ----------------------------------------------------

    def upsert_pointer(self, pointer: dict) -> str:
        import uuid
        pid = pointer.get("id") or str(uuid.uuid4())
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO pointers(id,capability,provider,external_id,"
                         "cached_projection,cache_ttl,created_at) VALUES(?,?,?,?,?,?,?)",
                         (pid, pointer.get("capability"), pointer.get("provider"),
                          pointer.get("external_id"), pointer.get("cached_projection"),
                          pointer.get("cache_ttl"), now_iso()))
        return pid

    def get_pointer(self, pointer_id: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM pointers WHERE id=?", (pointer_id,)).fetchone()
        return dict(row) if row else None

    # -- user knowledge (§19) ---------------------------------------------

    def upsert_user_knowledge(self, uk: dict):
        with self.transaction() as conn:
            cols = list(uk.keys())
            ph = ",".join(["?"] * len(cols))
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "belief_id")
            conn.execute(f"INSERT INTO user_knowledge({','.join(cols)}) VALUES({ph}) "
                         f"ON CONFLICT(belief_id) DO UPDATE SET {updates}", [uk[c] for c in cols])

    def query_user_knowledge(self, where: str = "1=1", params: tuple = (), limit: int = 50) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            f"SELECT * FROM user_knowledge WHERE {where} LIMIT ?", (*params, limit)).fetchall()]

    # -- calibration (§10.5) ----------------------------------------------

    def get_calibration_obs(self, source_type: str) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM calibration_obs WHERE source_type=?", (source_type,)).fetchall()]

    def bump_calibration(self, source_type: str, bucket: str, correct: bool):
        with self.transaction() as conn:
            conn.execute("INSERT INTO calibration_obs(source_type,predicted_bucket,n,correct) "
                         "VALUES(?,?,1,?) ON CONFLICT(source_type,predicted_bucket) DO UPDATE SET "
                         "n=n+1, correct=correct+?", (source_type, bucket, 1 if correct else 0,
                                                      1 if correct else 0))

    # -- logs: retrieval / misses (§18.7, §22) ----------------------------

    def log_retrieval(self, query: str, domain: str, top_score: float):
        with self.transaction() as conn:
            conn.execute("INSERT INTO retrieval_log(query,domain,top_score,created_at) VALUES(?,?,?,?)",
                         (query, domain, top_score, now_iso()))

    def log_miss(self, query: str, domain: str, top_score: float):
        with self.transaction() as conn:
            conn.execute("INSERT INTO search_misses(query,domain,top_score,resolved,created_at) "
                         "VALUES(?,?,?,0,?)", (query, domain, top_score, now_iso()))

    def get_unresolved_misses(self, limit: int = 50) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM search_misses WHERE resolved=0 ORDER BY id LIMIT ?", (limit,)).fetchall()]

    def mark_miss_resolved(self, miss_id: int):
        with self.transaction() as conn:
            conn.execute("UPDATE search_misses SET resolved=1 WHERE id=?", (miss_id,))

    # -- health (§21) ------------------------------------------------------

    def record_health_run(self, results: dict):
        with self.transaction() as conn:
            conn.execute("INSERT INTO health_runs(created_at,results) VALUES(?,?)",
                         (now_iso(), json.dumps(results)))

    def upsert_fingerprint(self, fingerprint: str, pattern: str, tier: str, repair_action: str, auto: int):
        with self.transaction() as conn:
            conn.execute("INSERT INTO issue_fingerprints(fingerprint,pattern,tier,repair_action,"
                         "occurrences,last_seen,auto_repair) VALUES(?,?,?,?,1,?,?) "
                         "ON CONFLICT(fingerprint) DO UPDATE SET occurrences=occurrences+1, last_seen=?",
                         (fingerprint, pattern, tier, repair_action, now_iso(), auto, now_iso()))

    # -- policies / eval (§22) --------------------------------------------

    def upsert_policy(self, policy: dict):
        with self.transaction() as conn:
            cols = list(policy.keys())
            ph = ",".join(["?"] * len(cols))
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "version")
            conn.execute(f"INSERT INTO policies({','.join(cols)}) VALUES({ph}) "
                         f"ON CONFLICT(version) DO UPDATE SET {updates}", [policy[c] for c in cols])

    def get_active_policy(self, kind: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM policies WHERE kind=? AND active=1 LIMIT 1",
                                   (kind,)).fetchone()
        return dict(row) if row else None

    def get_policy(self, version: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM policies WHERE version=?", (version,)).fetchone()
        return dict(row) if row else None

    def count_active_policies(self) -> int:
        return self.count_rows("policies", "active=1")

    # -- goals / reflections (§23) ----------------------------------------

    def upsert_goal(self, goal: dict):
        with self.transaction() as conn:
            cols = list(goal.keys())
            ph = ",".join(["?"] * len(cols))
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
            conn.execute(f"INSERT INTO goals({','.join(cols)}) VALUES({ph}) "
                         f"ON CONFLICT(id) DO UPDATE SET {updates}", [goal[c] for c in cols])

    def get_active_goals(self) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM goals WHERE status='active' ORDER BY created_at DESC").fetchall()]

    def add_reflection(self, reflection: dict):
        with self.transaction() as conn:
            cols = list(reflection.keys())
            ph = ",".join(["?"] * len(cols))
            conn.execute(f"INSERT OR REPLACE INTO reflections({','.join(cols)}) VALUES({ph})",
                         [reflection[c] for c in cols])

    def search_reflections(self, like: str, limit: int = 5) -> List[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM reflections WHERE situation LIKE ? OR lesson LIKE ? LIMIT ?",
            (f"%{like}%", f"%{like}%", limit)).fetchall()]

    # -- stats -------------------------------------------------------------

    def count_rows(self, table: str, where: str = "1=1") -> int:
        row = self._conn().execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()
        return row[0] if row else 0

    def truncate_projection(self):
        """Drop everything derived (I3); the event log + extractions are kept."""
        with self.transaction() as conn:
            for t in (BELIEF_TABLES + ["entities", "user_knowledge", "justifications",
                                       "corrections", "nogoods", "contradictions",
                                       "observed_vectors", "session_index", "memory_vectors", "projection_vectors"]):
                conn.execute(f"DELETE FROM {t}")
            conn.execute("DELETE FROM observed_fts")
            conn.execute("DELETE FROM belief_fts")
            if self.vector_index:
                try:
                    self.vector_index.prune_observed_vectors(conn, set())  # keep nothing -- full rebuild
                except Exception as e:
                    logger.warning("Failed to clear vector_index on truncate: %s", e)


# -- helpers --------------------------------------------------------------

def _as_json(v) -> str:
    return v if isinstance(v, str) else json.dumps(v)


def _has_col(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)


def _belief_fts_text(table: str, b: dict) -> Tuple[str, str]:
    if table == "facts":
        return "fact", f"{b.get('attribute','')} {b.get('value','')}".strip()
    if table == "episodes":
        return "episode", f"{b.get('title','')} {b.get('summary','')}".strip()
    if table == "notes":
        return "note", f"{b.get('subject','')} {b.get('body','')}".strip()
    if table == "refs":
        return "reference", f"{b.get('topic','')} {b.get('cached_summary','') or ''}".strip()
    if table == "relationships":
        return "relationship", f"{b.get('predicate','')}".strip()
    if table == "procedures":
        return "procedure", f"{b.get('name','')}".strip()
    if table == "entities":
        return "entity", f"{b.get('name','')} {b.get('normalized_name','')}".strip()
    return "", ""


def _fts_query(query: str) -> str:
    """Sanitize a free-text query into a safe FTS5 OR-of-terms match string."""
    import re
    terms = re.findall(r"[A-Za-z0-9]+", query or "")
    terms = [t for t in terms if len(t) > 1]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


# curation_jobs is spliced into _SCHEMA from these, so the migration rebuild
# (_rebuild_curation_jobs) recreates the EXACT table+index and can never drift
# from the fresh-install schema. `run_after` = deferred retry (§17.3, §24.4).
_CURATION_JOBS_DDL = """CREATE TABLE IF NOT EXISTS %s (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT CHECK(task IN ('extract','route','criticality','canonicalize','consolidate',
        'contradiction','identity','derive','verify','decay','consistency','health','reextract',
        'journal_ingest','session_summarize','embed','digest')),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT,
    run_after TEXT);"""
_JOBS_INDEX_DDLS = (
    "CREATE INDEX IF NOT EXISTS idx_jobs_ready ON curation_jobs(status, id) "
    "WHERE status='pending';",
    # Serves the enqueue_curation / enqueue_embed_job dedup probe. Without it
    # every enqueue scans curation_jobs, which grows as the drain proceeds, so
    # the guard that exists to REMOVE work costs O(queue) per call and eats most
    # of what it saves.
    "CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON curation_jobs(task, payload) "
    "WHERE status IN ('pending','running');",
)
# One string for the _SCHEMA splice (executescript takes many statements);
# the rebuild path executes them one at a time (conn.execute takes exactly one).
_JOBS_INDEX_DDL = "\n".join(_JOBS_INDEX_DDLS)
_JOB_COLS = ("id,task,payload,depends_on,status,attempts,created_at,started_at,finished_at,"
             "error,run_after")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, seq INTEGER NOT NULL UNIQUE, order_key TEXT,
    type TEXT NOT NULL, payload TEXT NOT NULL, parents TEXT NOT NULL DEFAULT '[]',
    actor TEXT NOT NULL CHECK(actor IN ('user','agent','curator','system')),
    owner TEXT NOT NULL, trust_level INTEGER NOT NULL, session_id TEXT, branch_id TEXT,
    occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, prev_head TEXT, sig TEXT);
CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq);
CREATE INDEX IF NOT EXISTS idx_events_recorded ON events(recorded_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, seq);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, seq);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, parent_session_id TEXT, domain TEXT,
    status TEXT CHECK(status IN ('active','idle','ended','reaped')),
    started_at TEXT, last_activity_at TEXT, last_extracted_seq INTEGER NOT NULL DEFAULT 0,
    branch_point_seq INTEGER, ended_via TEXT, ended_at TEXT);

CREATE TABLE IF NOT EXISTS principals (
    principal_id TEXT PRIMARY KEY, type TEXT CHECK(type IN ('user','agent')), display TEXT,
    default_visibility TEXT CHECK(default_visibility IN ('shared','private')) DEFAULT 'shared',
    key_ref TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS entities (
    belief_id TEXT PRIMARY KEY, type TEXT, name TEXT, normalized_name TEXT, aliases TEXT DEFAULT '[]',
    domain TEXT, owner TEXT, read_acl TEXT, merged_into TEXT,
    external_ref TEXT, external_provider TEXT, cache_ttl TEXT,
    fact_count INTEGER DEFAULT 0, relationship_count INTEGER DEFAULT 0,
    created_at TEXT, last_seen_at TEXT);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(domain, normalized_name);
CREATE INDEX IF NOT EXISTS idx_entities_owner ON entities(owner);
CREATE INDEX IF NOT EXISTS idx_entities_ext ON entities(external_provider, external_ref);

CREATE TABLE IF NOT EXISTS pointers (
    id TEXT PRIMARY KEY, capability TEXT, provider TEXT, external_id TEXT,
    cached_projection TEXT, cache_ttl TEXT, created_at TEXT,
    UNIQUE(capability, provider, external_id));

CREATE TABLE IF NOT EXISTS facts (
    belief_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, attribute TEXT NOT NULL,
    predicate_canonical TEXT, value TEXT NOT NULL, value_type TEXT DEFAULT 'string',
    value_num REAL, value_ts TEXT, qualifiers TEXT NOT NULL DEFAULT '{}',
    qualifiers_hash TEXT NOT NULL DEFAULT '', pointer_id TEXT, confirm_count INTEGER DEFAULT 0,
    contradiction_count INTEGER DEFAULT 0, last_confirmed_at TEXT, extractor_version TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT DEFAULT 'active',
    salience TEXT DEFAULT 'normal', criticality TEXT DEFAULT 'normal', criticality_reason TEXT,
    confidence REAL DEFAULT 0.8 CHECK(confidence BETWEEN 0 AND 1), trust_level INTEGER,
    valid_from TEXT, valid_until TEXT, superseded_by TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT DEFAULT 'verbatim', utility REAL DEFAULT 0, purpose_scope TEXT NOT NULL DEFAULT '["*"]',
    consent TEXT, provenance TEXT NOT NULL, verification TEXT DEFAULT '{"status":"unverified"}',
    rule_id TEXT, premises TEXT);
CREATE INDEX IF NOT EXISTS idx_facts_active ON facts(entity_id, predicate_canonical) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_facts_owner ON facts(owner, domain);
CREATE INDEX IF NOT EXISTS idx_facts_crit ON facts(criticality) WHERE criticality!='normal';
CREATE INDEX IF NOT EXISTS idx_facts_valnum ON facts(entity_id, predicate_canonical, value_num) WHERE value_num IS NOT NULL;

CREATE TABLE IF NOT EXISTS episodes (
    belief_id TEXT PRIMARY KEY, title TEXT, summary TEXT, participants TEXT DEFAULT '[]',
    occurred_at TEXT, session_ref TEXT, derived_facts TEXT DEFAULT '[]', pointer_id TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT,
    criticality TEXT DEFAULT 'normal', criticality_reason TEXT, confidence REAL, trust_level INTEGER,
    valid_from TEXT, valid_until TEXT, superseded_by TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT, utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT,
    verification TEXT DEFAULT '{"status":"unverified"}');
CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(occurred_at);

CREATE TABLE IF NOT EXISTS notes (
    belief_id TEXT PRIMARY KEY, note_type TEXT CHECK(note_type IN ('procedure','norm','belief')),
    subject TEXT, body TEXT, body_hash TEXT, imperative INTEGER DEFAULT 0, always_inject INTEGER DEFAULT 0,
    risk_tier TEXT DEFAULT 'low' CHECK(risk_tier IN ('low','high')),
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT,
    criticality TEXT DEFAULT 'normal', criticality_reason TEXT, confidence REAL, trust_level INTEGER,
    valid_from TEXT, valid_until TEXT, superseded_by TEXT, created_at TEXT, last_seen_at TEXT,
    fidelity TEXT, utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT,
    verification TEXT DEFAULT '{"status":"unverified"}');
CREATE INDEX IF NOT EXISTS idx_notes_directive ON notes(always_inject) WHERE always_inject=1;

CREATE TABLE IF NOT EXISTS refs (
    belief_id TEXT PRIMARY KEY, topic TEXT, retrieval_url TEXT, retrieved_at TEXT,
    ttl_days INTEGER DEFAULT 30, cached_summary TEXT, stale_after TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT DEFAULT 'normal',
    criticality TEXT DEFAULT 'normal', confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT,
    superseded_by TEXT, created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim',
    utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT);
CREATE INDEX IF NOT EXISTS idx_refs_stale ON refs(stale_after);

CREATE TABLE IF NOT EXISTS relationships (
    belief_id TEXT PRIMARY KEY, source_id TEXT, predicate TEXT, target_id TEXT, external_ref TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT DEFAULT 'normal',
    criticality TEXT DEFAULT 'normal', confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT,
    superseded_by TEXT, created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim',
    utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT,
    rule_id TEXT, premises TEXT);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id) WHERE status='active';

CREATE TABLE IF NOT EXISTS procedures (
    belief_id TEXT PRIMARY KEY, name TEXT, params TEXT, steps TEXT, success_criteria TEXT,
    derived_from TEXT DEFAULT '[]', domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT,
    status TEXT, salience TEXT DEFAULT 'normal', criticality TEXT DEFAULT 'normal',
    confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT, superseded_by TEXT,
    created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim', utility REAL DEFAULT 0,
    purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT);

CREATE TABLE IF NOT EXISTS predicates (
    surface TEXT PRIMARY KEY, canonical TEXT NOT NULL,
    cardinality TEXT NOT NULL DEFAULT 'single' CHECK(cardinality IN ('single','multi')),
    confidence REAL, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_predicates_canon ON predicates(canonical);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, type TEXT, created_at TEXT, agent TEXT, abstract TEXT, file_path TEXT);

CREATE TABLE IF NOT EXISTS tombstones (content_hash TEXT PRIMARY KEY, scope TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS justifications (
    belief_id TEXT, support TEXT, support_kind TEXT CHECK(support_kind IN ('event','belief','assumption')),
    rule TEXT, PRIMARY KEY(belief_id, support, rule));
CREATE INDEX IF NOT EXISTS idx_just_support ON justifications(support);

CREATE TABLE IF NOT EXISTS nogoods (nogood_id TEXT PRIMARY KEY, assumptions TEXT);

CREATE TABLE IF NOT EXISTS corrections (
    id TEXT PRIMARY KEY, belief_id TEXT, reason TEXT, correction_ref TEXT,
    propagated TEXT DEFAULT '[]', created_at TEXT);

CREATE TABLE IF NOT EXISTS contradictions (
    id TEXT PRIMARY KEY, belief_a TEXT, belief_b TEXT, detail TEXT,
    status TEXT DEFAULT 'open', created_at TEXT);

CREATE TABLE IF NOT EXISTS derivation_rules (
    rule_id TEXT PRIMARY KEY, name TEXT, enabled INTEGER DEFAULT 1, pattern TEXT NOT NULL,
    guards TEXT NOT NULL, conclusion TEXT NOT NULL, scope TEXT NOT NULL,
    materialize TEXT DEFAULT 'high_value', precision_n INTEGER DEFAULT 0, precision_correct INTEGER DEFAULT 0);

""" + (_CURATION_JOBS_DDL % "curation_jobs") + "\n" + _JOBS_INDEX_DDL + """

CREATE TABLE IF NOT EXISTS extractions (
    id TEXT PRIMARY KEY, observed_event TEXT, extractor_version TEXT, produced TEXT,
    ambiguous INTEGER DEFAULT 0, route TEXT, created_at TEXT,
    UNIQUE(observed_event, extractor_version));

CREATE VIRTUAL TABLE IF NOT EXISTS observed_fts USING fts5(event_id UNINDEXED, excerpt);
CREATE VIRTUAL TABLE IF NOT EXISTS belief_fts USING fts5(belief_id UNINDEXED, kind UNINDEXED, text);

CREATE TABLE IF NOT EXISTS observed_vectors (
    event_id TEXT PRIMARY KEY, embedding BLOB, model TEXT, owner TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS session_index (
    session_id TEXT PRIMARY KEY, summary TEXT, embedding BLOB, owner TEXT, occurred_at TEXT);
CREATE TABLE IF NOT EXISTS memory_vectors (
    belief_id TEXT, kind TEXT, embedding BLOB, model TEXT, created_at TEXT, PRIMARY KEY(belief_id, kind));

CREATE TABLE IF NOT EXISTS projection_vectors (
    provider TEXT NOT NULL, external_id TEXT NOT NULL, embedding BLOB, model TEXT,
    owner TEXT, created_at TEXT, PRIMARY KEY(provider, external_id));
CREATE INDEX IF NOT EXISTS idx_proj_vectors_provider ON projection_vectors(provider);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY, source_type TEXT, trust_level INTEGER, info_label TEXT);

CREATE TABLE IF NOT EXISTS calibration_obs (
    source_type TEXT, predicted_bucket TEXT, n INTEGER DEFAULT 0, correct INTEGER DEFAULT 0,
    PRIMARY KEY(source_type, predicted_bucket));

CREATE TABLE IF NOT EXISTS git_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, committed INTEGER DEFAULT 0,
    committed_at TEXT, git_commit TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS user_knowledge (
    belief_id TEXT PRIMARY KEY, proposition TEXT, about_belief TEXT,
    state TEXT CHECK(state IN ('told','stated_by_user','assumed_known')),
    last_communicated TEXT, times_communicated INTEGER DEFAULT 0, importance REAL DEFAULT 0.5,
    owner TEXT, read_acl TEXT, domain TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS retrieval_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, domain TEXT, top_score REAL,
    resolved INTEGER DEFAULT 0, created_at TEXT);

CREATE TABLE IF NOT EXISTS search_misses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT, domain TEXT, top_score REAL,
    resolved INTEGER DEFAULT 0, created_at TEXT);

CREATE TABLE IF NOT EXISTS health_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, results TEXT);

CREATE TABLE IF NOT EXISTS issue_fingerprints (
    fingerprint TEXT PRIMARY KEY, pattern TEXT, tier TEXT, repair_action TEXT,
    occurrences INTEGER DEFAULT 0, last_seen TEXT, auto_repair INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS policies (
    version TEXT PRIMARY KEY, kind TEXT, params TEXT, parent_version TEXT, active INTEGER DEFAULT 0,
    created_at TEXT);

CREATE TABLE IF NOT EXISTS eval_baselines (
    capability TEXT, domain TEXT, metric TEXT, baseline REAL, PRIMARY KEY(capability, domain, metric));

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY, goal TEXT, status TEXT DEFAULT 'active', created_at TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY, situation TEXT, action TEXT, outcome TEXT, lesson TEXT,
    applicability TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS capability_providers (
    capability TEXT PRIMARY KEY, provider TEXT, declared_by TEXT, precedence INTEGER,
    status TEXT CHECK(status IN ('active','unavailable')) DEFAULT 'active');
"""
