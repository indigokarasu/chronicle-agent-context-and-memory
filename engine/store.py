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
import heapq
import json
import logging
import sqlite3
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from typing import List, Optional  # names this module already annotates with

from .embeddings import batch_cosine_f64

logger = logging.getLogger("chronicle.store")

# Bumped whenever _SCHEMA changes shape; recorded in meta.schema_version by
# _migrate. 2 = curation_jobs.run_after + task 'embed' (deferred embeds, §24.4).
# 3 = task 'digest' (entity consolidation digests, §u2).
# 4 = task 'federate_sweep' + federation_watermarks/link_candidates (§14, g4).
# 5 = task 'backfill_sweep' (session-index backfill sweep, issue #6).
# 6 = belief_tables + novelty (near-duplicate scoring, issue #8/E5).
# 7 = belief_tables + occurrence_count (E5 occurrence count for EVERY kind, not
#     just facts' confirm_count — see _merge_duplicate).
# 8 = entity_centroids + identity_candidates (identity evidence, issue #8 E7).
# 9 = host_model_requests + host_model_results (host-model piggyback, §H1).
#     Both tables stay EMPTY unless host_model.piggyback is turned on.
# 10 = host_model_proxies + rerank_hints (host-model DRAIN, §H2). The two
#     consumers H1 deliberately left unbuilt: a doc2query reply's questions are
#     kept in host_model_proxies so they survive proxy re-generation (and so a
#     proxy row's host provenance is recorded WITHOUT widening
#     query_proxy_vectors, whose column set is pinned byte-for-byte by the H1
#     inertness proof), and a rerank reply becomes bounded, expiring
#     query->evidence hints in rerank_hints. Both tables stay EMPTY unless
#     host_model.piggyback is turned on and a host actually answers.
# 11 = rerank_hints + owner (ladder-9 F4c). rerank_hints was store-global: any
#     owner's hint re-weighted every OTHER owner's textually-similar query, an
#     ordering-only but still real cross-owner leak. `owner` records who the
#     host verdict was FOR (RetrievalEngine._hint_scores now reads it back
#     scoped to the querying principal's owner). Defaulted to 'default' on
#     migration so an old, necessarily-empty-at-defaults row (§H2's own
#     invariant) never needs backfilling.
#
# Ladder 9 renumbering: E5, E7 and H1 were each built against a v5 store and
# each claimed "6" independently. They are sequenced here into ONE ladder --
# there is only one meta.schema_version, so two features cannot both be 6 and
# still be distinguishable on an upgrade. Every step below stays probe-then-
# apply (_has_col / _has_table), so the ladder is order-independent and
# re-entrant: a store at ANY prior version converges by running all of them,
# and the version is stamped LAST so an interrupted migration re-runs rather
# than claiming a shape it never reached.
SCHEMA_VERSION = 11

# SQLite busy timeouts, milliseconds.
#
# BUSY_TIMEOUT_MS is the steady-state wait and is deliberately long: Chronicle's
# own writes are short, so out-waiting a concurrent writer beats failing a
# capture. INIT_BUSY_TIMEOUT_MS bounds the *start-up* path only (schema +
# migration here, core.initialize() via init_busy_timeout()). Start-up has a
# caller that can degrade and retry — the context engine falls back to heuristic
# compression and re-inits later — so blocking it for the full steady-state
# timeout buys nothing and stalls the host session instead.
BUSY_TIMEOUT_MS = 30000
INIT_BUSY_TIMEOUT_MS = 5000

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
            conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_MS / 1000.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def init_busy_timeout(self):
        """Run a block with the short start-up busy timeout, then restore.

        Scoped rather than global on purpose. Lowering the connect-time timeout
        would make every steady-state write give up sooner, which is the opposite
        of what contention needs; what actually has to be bounded is the one
        caller that can degrade instead of waiting. `ChronicleCore.get()` hands
        back a WARM singleton without touching SQLite, so a context-engine start
        typically meets the lock inside `core.initialize()`'s first write — on a
        connection opened long ago at the steady-state timeout — which is why the
        bound has to be applicable to an existing connection and not just to a
        fresh one.
        """
        conn = self._conn()
        # Restore whatever was there rather than assuming the connect-time value,
        # so nesting (a cold ChronicleCore.get() inside an init block) cannot
        # hand the outer block back the steady-state timeout half way through.
        prev = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.execute("PRAGMA busy_timeout=%d" % int(INIT_BUSY_TIMEOUT_MS))
        try:
            yield conn
        finally:
            try:
                conn.execute("PRAGMA busy_timeout=%d" % int(prev))
            except Exception:  # pragma: no cover - a dead conn is the caller's problem
                logger.debug("could not restore busy_timeout on %s", self.db_path)

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
        # Bounded by the start-up timeout: a store opened while another process
        # holds the write lock (the live 2026-08-02 case was a concurrent
        # migration) must fail in seconds so its caller can degrade and retry,
        # not block the host for the steady-state timeout.
        with self.init_busy_timeout() as conn:
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
        # This list must be kept in lockstep with _CURATION_JOBS_DDL's task CHECK
        # below — every value added there needs its OWN entry here too, or an
        # existing store never rebuilds and the first enqueue of the new task
        # raises IntegrityError inside append_event's txn (already missed twice:
        # 'digest' at schema_version 3, 'federate_sweep' at schema_version 4).
        missing = [t for t in ("embed", "digest", "federate_sweep", "backfill_sweep")
                   if row and f"'{t}'" not in (row[0] or "")]
        if missing:
            logger.info("schema migration: curation_jobs task CHECK += %s", ", ".join(missing))
            self._rebuild_curation_jobs(conn)
        # federation_watermarks predates its second cursor in stores swept by an
        # earlier build; CREATE TABLE IF NOT EXISTS would leave them one column short.
        if not _has_col(conn, "federation_watermarks", "rescan_cursor"):
            logger.info("schema migration: federation_watermarks + rescan_cursor")
            conn.execute("ALTER TABLE federation_watermarks ADD COLUMN rescan_cursor INTEGER DEFAULT 0")
        if not _has_col(conn, "link_candidates", "provider"):
            logger.info("schema migration: link_candidates + provider")
            conn.execute("ALTER TABLE link_candidates ADD COLUMN provider TEXT")
        # novelty (schema_version 6, E5): CREATE TABLE IF NOT EXISTS in _SCHEMA added
        # `novelty REAL` to all 6 BELIEF_TABLES, but that DDL is a no-op on a table
        # that already exists — an existing store never got the column and crashed
        # on its first fact write (OperationalError: table facts has no column
        # named novelty). Same probe-then-ALTER pattern as every migration above.
        for t in BELIEF_TABLES:
            if not _has_col(conn, t, "novelty"):
                logger.info("schema migration: %s + novelty", t)
                conn.execute(f"ALTER TABLE {t} ADD COLUMN novelty REAL")
        # occurrence_count (schema_version 7, E5): how many times this item has
        # been observed. Facts already had confirm_count, so the first E5 pass
        # counted occurrences for facts ONLY and silently dropped the count on
        # every other kind — a near-duplicate episode/reference/procedure merged
        # away with nothing left to say it had been seen twice. One explicit
        # column on all six belief tables, defaulted to 1 (the row itself is the
        # first occurrence), so an insert never has to name it and a pre-E5 row
        # migrates to a truthful value rather than 0/NULL.
        for t in BELIEF_TABLES:
            if not _has_col(conn, t, "occurrence_count"):
                logger.info("schema migration: %s + occurrence_count", t)
                conn.execute(
                    f"ALTER TABLE {t} ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 1")
        # schema_version 8 (E7): the identity-evidence pair. Spliced into _SCHEMA
        # as well, so a fresh install and a migrated one cannot drift — but kept
        # here too because _migrate has to be sufficient on its OWN connection:
        # anything that hands this method a conn (a repair path, a test opening a
        # raw old-version file) must end up with the same shape as a fresh store,
        # without depending on _SCHEMA having been executed first.
        if not _has_table(conn, "identity_candidates") or not _has_table(conn, "entity_centroids"):
            logger.info("schema migration: entity_centroids + identity_candidates (identity evidence)")
            conn.executescript(_IDENTITY_DDL)
        # schema_version 9 (§H1). executescript(_SCHEMA) above already ran the
        # CREATE TABLE IF NOT EXISTS, so this probe is normally a no-op — it is
        # here so the migration ladder states every version's change explicitly
        # and so a store whose _SCHEMA run was interrupted still converges.
        for table, ddl in (("host_model_requests", _HOST_MODEL_REQUESTS_DDL),
                           ("host_model_results", _HOST_MODEL_RESULTS_DDL)):
            if not _has_table(conn, table):
                logger.info("schema migration: %s (host-model piggyback)", table)
                conn.execute(ddl)
        # schema_version 10 (§H2) — same probe-then-apply shape, same reason.
        if not _has_table(conn, "host_model_proxies") or not _has_table(conn, "rerank_hints"):
            logger.info("schema migration: host_model_proxies + rerank_hints (host-model drain)")
            conn.executescript(_HOST_DRAIN_DDL)
        # schema_version 11 (ladder-9 F4c): rerank_hints + owner. Plain
        # probe-then-ALTER, same as curation_jobs.run_after and
        # federation_watermarks.rescan_cursor above -- no PK change, so a
        # store on ANY prior version converges with one ADD COLUMN. Existing
        # rows default to 'default': §H2's own inertness proof already
        # guarantees the table is empty unless host_model.piggyback was
        # turned on, so there is nothing real to backfill correctly, only a
        # column to add.
        if not _has_col(conn, "rerank_hints", "owner"):
            logger.info("schema migration: rerank_hints + owner (owner-scoped rerank hints)")
            conn.execute("ALTER TABLE rerank_hints ADD COLUMN owner TEXT NOT NULL DEFAULT 'default'")
        # Unconditional and OUTSIDE the probe above: by this point the owner
        # column exists either way (added just now, or already there on a
        # fresh install whose _SCHEMA run created it directly) -- see
        # _HOST_DRAIN_DDL's comment for why the index itself cannot live in
        # _SCHEMA.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rerank_hints_owner "
                     "ON rerank_hints(owner, expires_at)")
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

    def get_meta(self, key: str, default: str | None = None) -> str | None:
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

    def get_event(self, event_id: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return dict(row) if row else None

    def get_events_since(self, seq: int, limit: int | None = None) -> list[dict]:
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

    def get_events_as_of(self, recorded_at: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM events WHERE recorded_at <= ? ORDER BY seq", (recorded_at,)).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_session(self, session_id: str, since_seq: int = 0,
                              types: Sequence[str] | None = None,
                              limit: int | None = None) -> list[dict]:
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
            q += " AND type IN ({})".format(",".join(["?"] * len(types)))
            params.extend(types)
        q += " ORDER BY seq"
        if limit is not None:
            q += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn().execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_type(self, type_: str, since_seq: int = 0) -> list[dict]:
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

    def fts_search_observed(self, query: str, limit: int = 20) -> list[dict]:
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

    def fts_search_beliefs(self, query: str, limit: int = 20) -> list[dict]:
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
        prune_observed_vectors's bulk keep-list rebuild.

        §H2: the event's doc2query EXCERPT proxies go with it. Those rows are
        keyed by event_id under kind='observed' and, now that the excerpt tier
        actually resolves through the raw channel, a surviving proxy would keep
        scoring a span whose own vector has just been deleted -- i.e. it would
        resurrect forbidden content by the back door. Unconditional because it
        is a delete: on a store that never enabled embeddings.doc2query.excerpts
        there are no such rows and the statement is a no-op."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM observed_vectors WHERE event_id=?", (event_id,))
            self.delete_excerpt_proxies(event_id)   # re-entrant: same transaction
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

    def get_observed_vector_model(self, event_id: str) -> Optional[str]:
        """Get the model name of an existing observed vector, or None if not found."""
        row = self._conn().execute("SELECT model FROM observed_vectors WHERE event_id=?",
                                   (event_id,)).fetchone()
        return row["model"] if row else None

    def has_memory_vector(self, belief_id: str, kind: str) -> bool:
        return self._conn().execute("SELECT 1 FROM memory_vectors WHERE belief_id=? AND kind=?",
                                    (belief_id, kind)).fetchone() is not None

    def get_memory_vector_model(self, belief_id: str, kind: str) -> Optional[str]:
        """Get the model name of an existing memory vector, or None if not found."""
        row = self._conn().execute("SELECT model FROM memory_vectors WHERE belief_id=? AND kind=?",
                                   (belief_id, kind)).fetchone()
        return row["model"] if row else None

    def get_memory_vector(self, belief_id: str, kind: str) -> Optional[bytes]:
        """Get a single belief's packed embedding blob, or None if it has none
        (never embedded, or dropped via delete_memory_vector). Used by geometric
        abstention (E10) to compare the query embedding against the specific
        candidate that ranked first, rather than a fused score."""
        row = self._conn().execute("SELECT embedding FROM memory_vectors WHERE belief_id=? AND kind=?",
                                   (belief_id, kind)).fetchone()
        return row["embedding"] if row else None

    def delete_memory_vector(self, belief_id: str):
        """Drop a belief's embedding once it is no longer searchable. Without
        this, retracted/superseded beliefs leak vectors that bloat the brute-
        force scan forever (their facts stay out of results, but the vectors
        are still scanned on every query)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM memory_vectors WHERE belief_id=?", (belief_id,))

    # -- doc2query proxy vectors (§24.4, E2) -------------------------------

    def add_query_proxy_vector(self, belief_id: str, proxy_idx: int, kind: str, question: str,
                               embedding: bytes, model: str):
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO query_proxy_vectors"
                "(belief_id,proxy_idx,kind,question,embedding,model,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (belief_id, proxy_idx, kind, question, embedding, model, now_iso()))

    def delete_query_proxy_vectors(self, belief_id: str):
        """Drop every proxy vector for one item, mirroring delete_memory_vector's
        cleanup on retract/supersede/forget so a proxy never outlives the belief
        it resolves to.

        NOTE this is also the delete half of the reducer's delete-then-write
        regeneration, so it must NOT touch host_model_proxies: that table is
        exactly what has to survive a regeneration (§H2). Retract/supersede
        cleans it up separately, at the call sites that mean "this item is
        gone" rather than "this item's proxies are being rewritten"."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM query_proxy_vectors WHERE belief_id=?", (belief_id,))

    def iter_query_proxy_vectors(self) -> list[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM query_proxy_vectors").fetchall()]

    def query_proxy_rows(self, belief_id: str) -> list:
        """One item's proxy rows, proxy_idx-ordered. The scoped companion to
        iter_query_proxy_vectors, which reads the whole table — retrieval needs
        every row, but the §H2 drain only ever needs one parent's."""
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM query_proxy_vectors WHERE belief_id=? ORDER BY proxy_idx",
            (belief_id,)).fetchall()]

    def count_query_proxy_vectors(self, belief_id: str) -> int:
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM query_proxy_vectors WHERE belief_id=?", (belief_id,)).fetchone()
        return row["n"] if row else 0

    def delete_excerpt_proxies(self, event_id: str):
        """Drop the doc2query proxies of ONE raw event (§H2/E2 excerpt tier).

        Keyed by event_id under kind='observed', which is why this cannot just
        be delete_query_proxy_vectors: that one is scoped by belief_id alone,
        and an event id and a belief id are drawn from different namespaces —
        deleting by id without the kind guard would be a wider statement than
        the caller means. Called wherever a raw event stops being retrievable,
        so an excerpt proxy can never outlive the span it resolves to."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM query_proxy_vectors WHERE belief_id=? AND kind='observed'",
                         (event_id,))

    # -- host-model drain: doc2query questions (§H2) ------------------------

    def set_host_proxy_questions(self, belief_id: str, questions, request_id: str = ""):
        """Record the question set a host model returned for one item.

        Replaces the previous set outright (a fresh host answer supersedes an
        older one), so the stored rows are always exactly the latest reply."""
        now = now_iso()
        with self.transaction() as conn:
            conn.execute("DELETE FROM host_model_proxies WHERE belief_id=?", (belief_id,))
            for idx, q in enumerate(questions):
                conn.execute(
                    "INSERT INTO host_model_proxies"
                    "(belief_id,proxy_idx,question,source,request_id,created_at) "
                    "VALUES(?,?,?,'host_model',?,?)", (belief_id, idx, q, request_id or None, now))

    def host_proxy_questions(self, belief_id: str) -> list:
        """The host-generated questions for one item, in the order returned.

        [] for every item on a default-configured store — nothing writes this
        table unless host_model.piggyback is on and a host answered."""
        return [r["question"] for r in self._conn().execute(
            "SELECT question FROM host_model_proxies WHERE belief_id=? ORDER BY proxy_idx",
            (belief_id,)).fetchall()]

    def host_proxy_rows(self, belief_id=None) -> list:
        sql = "SELECT * FROM host_model_proxies"
        params: tuple = ()
        if belief_id:
            sql += " WHERE belief_id=?"
            params = (belief_id,)
        return [dict(r) for r in self._conn().execute(
            sql + " ORDER BY belief_id, proxy_idx", params).fetchall()]

    def delete_host_proxy_questions(self, belief_id: str):
        with self.transaction() as conn:
            conn.execute("DELETE FROM host_model_proxies WHERE belief_id=?", (belief_id,))

    # -- host-model drain: rerank hints (§H2) ------------------------------

    def add_rerank_hints(self, query_key: str, query_text: str, tokens, hints,
                         expires_at: str, max_entries: int = 200, owner: str = "default"):
        """Persist one host rerank verdict as (belief_id -> weight) hints,
        scoped to `owner` (schema_version 11, ladder-9 F4c).

        `hints` is an iterable of (belief_id, weight). The whole verdict for a
        query_key is replaced -- but ONLY this owner's prior verdict for it:
        two different owners' queries hashing to the same query_key (a very
        plausible collision -- the signature is just a sorted, stemmed token
        set) must not let one owner's write delete the other's hints. Then
        the table is pruned within this owner's own rows: expired rows go
        first, then oldest-first eviction down to `max_entries` -- a per-owner
        budget, not a shared one, so one noisy owner can never evict another
        owner's hints. Both bounds are enforced HERE, in the same transaction
        as the insert, so the table length is an invariant rather than a hope
        — the same discipline host_model_requests' queue cap uses."""
        now = now_iso()
        token_json = json.dumps(list(tokens), sort_keys=False)
        with self.transaction() as conn:
            conn.execute("DELETE FROM rerank_hints WHERE query_key=? AND owner=?",
                        (query_key, owner))
            for belief_id, weight in hints:
                conn.execute(
                    "INSERT OR REPLACE INTO rerank_hints"
                    "(query_key,belief_id,weight,tokens,query_text,created_at,expires_at,owner) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (query_key, belief_id, float(weight), token_json, query_text or "", now,
                     expires_at, owner))
            conn.execute("DELETE FROM rerank_hints WHERE expires_at<=? AND owner=?", (now, owner))
            cap = max(1, int(max_entries))
            over = conn.execute(
                "SELECT COUNT(*) FROM rerank_hints WHERE owner=?", (owner,)).fetchone()[0] - cap
            if over > 0:
                conn.execute(
                    "DELETE FROM rerank_hints WHERE rowid IN "
                    "(SELECT rowid FROM rerank_hints WHERE owner=? "
                    "ORDER BY created_at ASC, rowid ASC LIMIT ?)",
                    (owner, over))

    def live_rerank_hints(self, now: str = "", limit: int = 400, owner: Optional[str] = None) -> list:
        """Every unexpired hint row, newest first, hard-capped.

        `owner=None` (the default) returns hints across every owner -- kept
        for introspection call sites (tests, admin tooling) that want the
        table's whole live contents. The real query path,
        RetrievalEngine._hint_scores, always passes the querying principal's
        owner so a search() from one owner can never be re-weighted by
        another owner's verdict.

        One statement, and it returns nothing at all on a default store, so the
        read side costs a single indexed lookup against an empty table."""
        sql = "SELECT * FROM rerank_hints WHERE expires_at>?"
        params: list = [now or now_iso()]
        if owner is not None:
            sql += " AND owner=?"
            params.append(owner)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return [dict(r) for r in self._conn().execute(sql, tuple(params)).fetchall()]

    def count_rerank_hints(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM rerank_hints").fetchone()[0]

    def add_session_vector(self, session_id: str, summary: str, embedding: bytes, owner: str, occurred_at: str):
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO session_index(session_id,summary,embedding,owner,occurred_at) "
                         "VALUES(?,?,?,?,?)", (session_id, summary, embedding, owner, occurred_at))

    def nearest_memory_vectors(self, kind: str, query_vec, owner: str, domain: str, k: int = 25,
                               extra_where: str = "", extra_params: Sequence = (),
                               batch_size: int = 500) -> list:
        """Top-k `(belief_id, cosine)` among ACTIVE same-KIND memory vectors,
        scoped to owner+domain, cosine-descending.

        This is the nearest-neighbour path E5's novelty and near-duplicate
        checks run on. What it replaces mattered: a `query_beliefs(..., limit=
        100)` call with NO ORDER BY — i.e. the OLDEST 100 rows by rowid — plus
        one `SELECT embedding` per row. Past 100 items of a kind the newest ones
        stopped being candidates entirely, so a fresh duplicate of a recent item
        scored as fully novel and stored a second copy, and the degradation was
        invisible. Here the join covers EVERY same-kind vector; it is paged by
        rowid so memory stays O(batch_size) whatever the corpus size, cosines
        come from the vectorized `batch_cosine_f64` (one numpy matmul per page,
        float64 so the stored novelty stays exactly `1 − max cosine`), and
        only the top-k survives, in a bounded heap.

        `extra_where` is an optional boolean SQL fragment over the belief
        table's own columns — it is how the caller makes a subject / natural-key
        restriction STRUCTURAL. A merge candidate that must match a subject is
        filtered in SQL here, not checked afterwards in Python, so no code path
        can produce a candidate from a different subject.

        Ordering is fully determined by (cosine, belief_id): no clock, no RNG,
        so replay stays byte-identical (I3).
        """
        table = KIND_TABLE.get(kind)
        if table not in BELIEF_TABLES or not query_vec:
            return []
        k = max(1, int(k))
        where = "v.kind=? AND b.owner=? AND b.domain=? AND b.status='active'"
        params = [kind, owner, domain]
        if extra_where:
            where += f" AND ({extra_where})"
            params.extend(extra_params)
        sql = (f"SELECT v.rowid AS rid, v.belief_id AS bid, v.embedding AS emb "
               f"FROM memory_vectors v JOIN {table} b ON b.belief_id = v.belief_id "
               f"WHERE v.rowid > ? AND {where} ORDER BY v.rowid LIMIT ?")
        conn = self._conn()
        best: list = []          # min-heap of (cosine, belief_id), size ≤ k
        min_rowid = 0
        while True:
            rows = conn.execute(sql, (min_rowid, *params, batch_size)).fetchall()
            if not rows:
                break
            sims = batch_cosine_f64(query_vec, [r["emb"] for r in rows])
            for r, sim in zip(rows, sims):
                if len(best) < k:
                    heapq.heappush(best, (sim, r["bid"]))
                elif sim > best[0][0]:
                    heapq.heapreplace(best, (sim, r["bid"]))
            min_rowid = rows[-1]["rid"]
            if len(rows) < batch_size:
                break
        return [(bid, sim) for sim, bid in sorted(best, reverse=True)]

    def iter_memory_vectors(self) -> list[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM memory_vectors").fetchall()]

    def get_memory_vectors_by_ids(self, belief_ids) -> dict[str, dict]:
        """Stored vectors for specific beliefs, keyed by belief_id.

        TWO consumers, one accessor (E3 and E8 each introduced an identical
        copy; they are merged here so the later definition cannot shadow the
        earlier one):

        - E3's reranker needs embeddings for a bounded top-K slice of
          already-fused candidates, for the query-side cosine.
        - E8's MMR selection needs pairwise similarity among a small candidate
          set (typically limit*overfetch, tens of rows).

        Both want random access rather than the full-table scan that
        iter_memory_vectors()/_vector_beliefs pay. Random access mirrors
        get_observed_vectors_by_ids. A belief_id with no row is simply absent
        from the result -- callers treat that as "no vector", not an error.
        Chunked to stay under SQLITE_MAX_VARIABLE_NUMBER; a belief_id repeated
        in the input is only looked up once.
        """
        out: dict[str, dict] = {}
        ids = [b for b in dict.fromkeys(belief_ids) if b]
        if not ids:
            return out
        conn = self._conn()
        chunk = 500
        for i in range(0, len(ids), chunk):
            part = ids[i:i + chunk]
            ph = ",".join("?" * len(part))
            for r in conn.execute(
                    "SELECT belief_id, kind, embedding FROM memory_vectors "
                    f"WHERE belief_id IN ({ph})", part).fetchall():
                out[r["belief_id"]] = dict(r)
        return out

    def iter_observed_vectors(self) -> list[dict]:
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

    def get_observed_vectors_by_ids(self, event_ids) -> dict[str, dict]:
        """Stored vectors for specific events, keyed by event_id (§24.4, u5).

        Random access is what the paged scan never needs and the ANN fast path
        cannot do without: `iter_observed_vectors_paged` visits EVERY row, so
        retrieve_raw's paged branch credits every already-scored FTS hit as a
        side effect of scanning past it, while a bounded KNN window reaches
        only its own top-k. Without a by-id lookup an FTS hit outside that
        window silently loses its whole vector contribution. Chunked to stay
        under SQLITE_MAX_VARIABLE_NUMBER; ids with no vector are simply absent.
        """
        out: dict[str, dict] = {}
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

    def get_projection_vector_model(self, provider: str, external_id: str) -> str | None:
        """Get the model name of an existing projection vector, or None if not found."""
        row = self._conn().execute("SELECT model FROM projection_vectors WHERE provider=? AND external_id=?",
                                   (provider, external_id)).fetchone()
        return row["model"] if row else None

    def get_projection_vectors_by_ids(self, proj_ids: list[tuple[str, str]]) -> dict[str, dict]:
        """Stored projection vectors for specific (provider, external_id) pairs.

        Returns dict keyed by "proj:<provider>:<external_id>" namespace id, mirroring
        the retrieval.retrieve_raw session id namespacing "session:<session_id>".
        Chunked to stay under SQLITE_MAX_VARIABLE_NUMBER.
        """
        out: dict[str, dict] = {}
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

    def iter_session_vectors(self) -> list[dict]:
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
        """Content vectors only: memory_vectors + observed_vectors.

        Deliberately EXCLUDES query_proxy_vectors (E2) and projection_vectors.
        Its consumer is the tier_triggers.vector_count sizing threshold, which
        is about how much primary memory this store holds; doc2query proxies
        are a derived multiplier on that (up to 4 per belief) and counting them
        would trip the threshold at a quarter of the real corpus. Anything that
        wants the physical row total must add count_rows("query_proxy_vectors")
        explicitly."""
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
            self.delete_query_proxy_vectors(belief_id)
            # §H2: the item is GONE (retracted/superseded/expired), not being
            # regenerated, so the host's questions for it go too. Left behind
            # they are a slow leak that a belief_id collision could one day
            # hand to a different item entirely.
            self.delete_host_proxy_questions(belief_id)

    def update_belief_all_tables(self, belief_id: str, **fields):
        sets = ",".join(f"{k}=?" for k in fields)
        with self.transaction() as conn:
            for t in BELIEF_TABLES:
                if all(_has_col(conn, t, k) for k in fields):
                    conn.execute(f"UPDATE {t} SET {sets} WHERE belief_id=?",
                                 [*fields.values(), belief_id])
        if fields.get("status") in _INACTIVE_STATUSES:
            self.delete_memory_vector(belief_id)
            self.delete_query_proxy_vectors(belief_id)
            # §H2: the item is GONE (retracted/superseded/expired), not being
            # regenerated, so the host's questions for it go too. Left behind
            # they are a slow leak that a belief_id collision could one day
            # hand to a different item entirely.
            self.delete_host_proxy_questions(belief_id)

    def get_belief(self, table: str, belief_id: str) -> dict | None:
        row = self._conn().execute(f"SELECT * FROM {table} WHERE belief_id=?", (belief_id,)).fetchone()
        return dict(row) if row else None

    def find_belief(self, belief_id: str) -> tuple[str, dict] | None:
        for t in BELIEF_TABLES + ["entities", "user_knowledge"]:
            row = self._conn().execute(f"SELECT * FROM {t} WHERE belief_id=?", (belief_id,)).fetchone()
            if row:
                return t, dict(row)
        return None

    def query_beliefs(self, table: str, where: str = "1=1", params: tuple = (),
                      limit: int = 50, order: str = "") -> list[dict]:
        order_sql = f" ORDER BY {order}" if order else ""
        rows = self._conn().execute(
            f"SELECT * FROM {table} WHERE {where}{order_sql} LIMIT ?", (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    # -- justifications (§9.1) --------------------------------------------

    def add_justification(self, belief_id: str, support: str, support_kind: str, rule: str = ""):
        with self.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO justifications(belief_id,support,support_kind,rule) "
                         "VALUES(?,?,?,?)", (belief_id, support, support_kind, rule))

    def get_justifications(self, belief_id: str) -> list[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM justifications WHERE belief_id=?", (belief_id,)).fetchall()]

    def get_dependents(self, support: str) -> list[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM justifications WHERE support=?", (support,)).fetchall()]

    def delete_justifications(self, belief_id: str):
        with self.transaction() as conn:
            conn.execute("DELETE FROM justifications WHERE belief_id=?", (belief_id,))

    def active_unjustified(self) -> list[str]:
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

    def get_open_contradictions(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM contradictions WHERE status='open' ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()]

    def resolve_contradiction(self, contradiction_id: str):
        with self.transaction() as conn:
            conn.execute("UPDATE contradictions SET status='resolved' WHERE id=?", (contradiction_id,))

    # -- supersede candidates (Ladder 9 E4, §issue-8) -----------------------

    def add_supersede_candidate(self, new_belief_id: str, old_belief_id: str, similarity: float,
                                new_value: str = "", old_value: str = "", kind: str = "fact",
                                created_at: str | None = None):
        """Record a dated, non-destructive "this looks like an update of that"
        edge. INSERT OR IGNORE on the (new,old) pair so re-deriving the same
        candidate (e.g. a rebuild replay) never raises or duplicates."""
        import uuid
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO supersede_candidates"
                "(id,new_belief_id,old_belief_id,kind,similarity,new_value,old_value,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), new_belief_id, old_belief_id, kind, similarity,
                 new_value, old_value, created_at or now_iso()))

    def get_supersede_candidates(self, belief_id: str) -> list[dict]:
        """Direct edges touching `belief_id`, either side, oldest first."""
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM supersede_candidates WHERE new_belief_id=? OR old_belief_id=? "
            "ORDER BY created_at", (belief_id, belief_id)).fetchall()]

    def get_supersede_chain(self, belief_id: str, max_nodes: int = 10) -> list[dict]:
        """The connected component of supersede-candidate edges containing
        `belief_id`, as dated (value, created_at) points, oldest first -- so a
        reader can apply "latest wins" just by taking the last entry.

        A small BFS over the edge table rather than a single-hop lookup: a
        belief can be superseded more than once (A -> B -> C), and each hop is
        its own edge row. Bounded (`max_nodes`) so a pathological, densely
        cross-linked store can never make one get_context call unbounded.
        """
        seen = {belief_id}
        frontier = [belief_id]
        while frontier and len(seen) < max_nodes:
            nxt = []
            for bid in frontier:
                for row in self.get_supersede_candidates(bid):
                    for other in (row["new_belief_id"], row["old_belief_id"]):
                        if other not in seen and len(seen) < max_nodes:
                            seen.add(other)
                            nxt.append(other)
            frontier = nxt
        if len(seen) <= 1:
            return []
        points = []
        for bid in seen:
            row = self.get_belief("facts", bid)
            if not row:
                continue
            points.append({"belief_id": bid, "value": row.get("value", ""),
                           "created_at": row.get("valid_from") or row.get("created_at") or ""})
        points.sort(key=lambda p: p["created_at"] or "")
        return points

    # -- corrections -------------------------------------------------------

    def record_correction(self, belief_id: str, reason: str, correction_ref: str, propagated: list[str]):
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

    def get_session(self, session_id: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def get_sessions_by_status(self, statuses) -> list[dict]:
        marks = ",".join("?" * len(statuses))
        return [dict(r) for r in self._conn().execute(
            f"SELECT * FROM sessions WHERE status IN ({marks})", tuple(statuses)).fetchall()]

    def get_sessions_needing_index_backfill(self, limit: int = 200) -> list[str]:
        """Find ended/reaped sessions lacking a session_index row, ordered by
        session_id for deterministic pagination. Watermarked: returns only sessions
        after the recorded watermark, advancing it on success. Idempotent."""
        watermark = self.get_meta("backfill_sweep_watermark", "")
        # Sessions that ended/reaped but have no index row, ordered for pagination.
        rows = self._conn().execute(
            """SELECT s.session_id FROM sessions s
               WHERE s.status IN ('ended', 'reaped')
               AND s.session_id NOT IN (SELECT session_id FROM session_index)
               AND s.session_id > ?
               ORDER BY s.session_id
               LIMIT ?""",
            (watermark, limit)).fetchall()
        sids = [dict(r)["session_id"] for r in rows]
        # Advance watermark to the last processed session for idempotency.
        if sids:
            self.set_meta("backfill_sweep_watermark", sids[-1])
        return sids

    # -- curation jobs (§17) ----------------------------------------------

    def enqueue_curation(self, task: str, payload: dict, depends_on: int | None = None) -> int | None:
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
                         owner: str | None = None, provider: str | None = None,
                         external_id: str | None = None) -> int | None:
        """Queue a deferred vector write (§24.4), unless the same one is already
        queued. Degraded mode can re-touch one belief many times (every update
        re-enters the reduce), and the queue must not grow without bound; the
        payload is canonical json, so an identical (target, kind, text, ...)
        dedupes. Returns the job id, or None when deduped.

        `owner`/`provider`/`external_id` are optional extras carried through to
        the handler for kinds that need them (kind='projection', §g5) — the
        'observed'/belief-kind callers omit them and see no change in the
        dedup key, so this is additive, not a behavior change for them.

        Validates target_id, kind, and text; logs a WARNING and returns None if
        any are empty or missing. On re-enqueue of a done/failed job, rearms it
        to pending with attempts=0 and run_after=NULL."""
        # Validate required fields
        if not target_id or not kind or not text:
            logger.warning("enqueue_embed_job: skipping invalid payload (target_id=%r, kind=%r, text=%r)",
                          target_id, kind, bool(text))
            return None
        payload_dict = {"target_id": target_id, "kind": kind, "text": (text or "")[:8000]}
        if owner is not None:
            payload_dict["owner"] = owner
        if provider is not None:
            payload_dict["provider"] = provider
        if external_id is not None:
            payload_dict["external_id"] = external_id
        payload = json.dumps(payload_dict, sort_keys=True)
        with self.transaction() as conn:
            # Check for existing job in pending/running state
            dup = conn.execute("SELECT id FROM curation_jobs WHERE task='embed' AND "
                               "status IN ('pending','running') AND payload=?", (payload,)).fetchone()
            if dup is not None:
                return None
            # Check for done/failed job with same payload and re-arm it
            old_job = conn.execute("SELECT id FROM curation_jobs WHERE task='embed' AND "
                                   "status IN ('done','failed') AND payload=?", (payload,)).fetchone()
            if old_job is not None:
                # Re-arm: reset to pending with attempts=0 and run_after=NULL
                conn.execute("UPDATE curation_jobs SET status='pending', attempts=0, run_after=NULL, "
                            "started_at=NULL, finished_at=NULL, error=NULL WHERE id=?", (old_job["id"],))
                return old_job["id"]
            # Enqueue new job
            cur = conn.execute("INSERT INTO curation_jobs(task,payload,created_at) "
                               "VALUES('embed',?,?)", (payload, now_iso()))
            return cur.lastrowid

    def enqueue_projection_embed(self, provider: str, external_id: str, text: str,
                                 owner: str | None = None) -> int | None:
        """Queue a projection's rendered text for embedding via the SAME deferred
        embed-job path every other vector channel uses — never inline at sweep
        time (§g5a). The target id is namespaced "proj:<provider>:<external_id>",
        mirroring the id retrieve_raw's projection scan produces, so a queued
        job and its eventual vector agree on identity by construction."""
        target_id = f"proj:{provider}:{external_id}"
        return self.enqueue_embed_job(target_id, "projection", text, owner=owner,
                                      provider=provider, external_id=external_id)

    def claim_curation_job(self) -> dict | None:
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

    def complete_curation_job(self, job_id: int, error: str | None = None):
        with self.transaction() as conn:
            conn.execute("UPDATE curation_jobs SET status=?, finished_at=?, error=? WHERE id=?",
                         ("failed" if error else "done", now_iso(), error, job_id))

    def defer_curation_job(self, job_id: int, delay_seconds: int, error: str | None = None):
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

    def get_curation_jobs(self, where: str = "1=1", limit: int = 100) -> list[dict]:
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

    def get_principal(self, principal_id: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM principals WHERE principal_id=?",
                                   (principal_id,)).fetchone()
        return dict(row) if row else None

    def all_principals(self) -> list[dict]:
        return [dict(r) for r in self._conn().execute("SELECT * FROM principals").fetchall()]

    # -- git queue (§26) ---------------------------------------------------

    def get_unflushed_git_events(self, limit: int = 1000) -> list[dict]:
        rows = self._conn().execute(
            "SELECT gq.id AS gid, e.* FROM git_queue gq JOIN events e ON gq.event_id=e.event_id "
            "WHERE gq.committed=0 ORDER BY gq.id LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_git_flushed(self, gids: list[int], git_commit: str):
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

    def get_derivation_rules(self, enabled_only: bool = True) -> list[dict]:
        q = "SELECT * FROM derivation_rules" + (" WHERE enabled=1" if enabled_only else "")
        return [dict(r) for r in self._conn().execute(q).fetchall()]

    def get_derivation_rule(self, rule_id: str) -> dict | None:
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

    def add_nogood(self, nogood_id: str, assumptions: list[str]):
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

    def get_predicate(self, surface: str) -> dict | None:
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

    def predicate_synonyms(self, canonical: str) -> list[str]:
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

    def get_capability_provider(self, capability: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM capability_providers WHERE capability=?",
                                   (capability,)).fetchone()
        return dict(row) if row else None

    def get_capability_providers(self) -> list[dict]:
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

    def get_pointer(self, pointer_id: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM pointers WHERE id=?", (pointer_id,)).fetchone()
        return dict(row) if row else None

    def find_pointer(self, capability: str, provider: str, external_id: str) -> Optional[dict]:
        """The pointer for one external row, by its natural key.

        upsert_pointer mints a fresh uuid when it is not given an id, and the
        table's UNIQUE(capability, provider, external_id) turns that into an
        INSERT OR REPLACE — i.e. refreshing a projection through the naive path
        silently CHANGES the pointer's id and breaks every belief referencing it.
        Callers refreshing a known row look it up here first and pass the id back."""
        row = self._conn().execute(
            "SELECT * FROM pointers WHERE capability=? AND provider=? AND external_id=?",
            (capability, provider, external_id)).fetchone()
        return dict(row) if row else None

    # -- federation sweep bookkeeping (§14) --------------------------------

    def get_federation_state(self, db_name: str) -> dict:
        """Sweep cursors for one registered provider (see the DDL for why two)."""
        row = self._conn().execute(
            "SELECT last_row_id, rescan_cursor, last_sync_at FROM federation_watermarks "
            "WHERE db_name=?", (db_name,)).fetchone()
        if not row:
            return {"last_row_id": 0, "rescan_cursor": 0, "last_sync_at": None}
        return {"last_row_id": int(row[0] or 0), "rescan_cursor": int(row[1] or 0),
                "last_sync_at": row[2]}

    def set_federation_state(self, db_name: str, *, last_row_id: Optional[int] = None,
                             rescan_cursor: Optional[int] = None):
        """Persist whichever cursor(s) the run advanced; the other is left alone."""
        cur = self.get_federation_state(db_name)
        lo = cur["last_row_id"] if last_row_id is None else int(last_row_id)
        rc = cur["rescan_cursor"] if rescan_cursor is None else int(rescan_cursor)
        with self.transaction() as conn:
            conn.execute("INSERT INTO federation_watermarks(db_name, last_row_id, rescan_cursor, "
                         "last_sync_at) VALUES(?,?,?,?) ON CONFLICT(db_name) DO UPDATE SET "
                         "last_row_id=excluded.last_row_id, rescan_cursor=excluded.rescan_cursor, "
                         "last_sync_at=excluded.last_sync_at",
                         (db_name, lo, rc, now_iso()))

    def enqueue_link_candidate(self, entity_id: str, external_ref: str, reason: str,
                               score: float, provider: str = "") -> Optional[str]:
        """Queue a POSSIBLE entity↔external-row link for review (I20, never a link).

        Idempotent on (entity_id, external_ref): a rescan that sees the same
        collision again keeps the original row — including an operator's decision
        on it — instead of resurrecting it as new. Returns the new candidate id,
        or None when the pair was already queued."""
        import uuid
        cand_id = str(uuid.uuid4())
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO link_candidates"
                "(id, entity_id, external_ref, provider, candidate_reason, score, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (cand_id, entity_id, external_ref, provider, reason, score, now_iso()))
            inserted = cur.rowcount
        return cand_id if inserted else None

    def get_link_candidates(self, reviewed: bool = False, limit: int = 100) -> List[dict]:
        """Pending (default) or already-adjudicated link candidates."""
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM link_candidates WHERE reviewed=? ORDER BY created_at, id LIMIT ?",
            (1 if reviewed else 0, int(limit))).fetchall()]

    def get_link_candidate(self, candidate_id: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT * FROM link_candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row) if row else None

    def resolve_link_candidate(self, candidate_id: str, decision: str):
        """Record an adjudication. The DECISION is stored; acting on it (creating
        the link) stays outside the sweep — nothing here ever links by itself."""
        with self.transaction() as conn:
            conn.execute("UPDATE link_candidates SET reviewed=1, decision=?, reviewed_at=? "
                         "WHERE id=?", (decision, now_iso(), candidate_id))

    # -- identity evidence (§E7): centroids + adjudication queue -----------

    def get_entity_centroid(self, entity_id: str) -> Optional[dict]:
        """The running (sum, n, dims, model) state for one entity, or None."""
        row = self._conn().execute(
            "SELECT * FROM entity_centroids WHERE entity_id=?", (entity_id,)).fetchone()
        return dict(row) if row else None

    def put_entity_centroid(self, entity_id: str, sum_vec: bytes, n: int, dims: int,
                            model: str, now: str):
        """Persist the folded state. The CALLER does the O(dims) add — the store
        only stores — so nothing here ever re-reads an entity's mentions."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO entity_centroids(entity_id, sum_vec, n, dims, model, updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET "
                "sum_vec=excluded.sum_vec, n=excluded.n, dims=excluded.dims, "
                "model=excluded.model, updated_at=excluded.updated_at",
                (entity_id, sum_vec, int(n), int(dims), model, now or now_iso()))

    def recent_entity_centroids(self, exclude_id: str = "", model: str = "", dims: int = 0,
                                limit: int = 50) -> List[dict]:
        """The `limit` most recently updated centroids in the SAME geometry.

        This is the bound on E7's pairwise merge check: the entity just written is
        compared against this capped, recently-touched working set instead of
        every entity in the store, so a write costs O(limit·dims) and never O(N²).
        Ordering is (updated_at DESC, entity_id DESC) — total and deterministic,
        so a projection replay sees the identical candidate set."""
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM entity_centroids WHERE entity_id<>? AND model=? AND dims=? AND n>0 "
            "ORDER BY updated_at DESC, entity_id DESC LIMIT ?",
            (exclude_id, model, int(dims), int(limit))).fetchall()]

    def enqueue_identity_candidate(self, kind: str, entity_id: str, other_id: str,
                                   mention_ref: str, similarity: float,
                                   now: str = "") -> Optional[str]:
        """Queue a POSSIBLE split/merge for adjudication. NEVER applies anything.

        Idempotent on (kind, entity_id, other_id, mention_ref): re-processing the
        same mention, or meeting the same entity pair again, keeps the original
        row — decision included — instead of duplicating a pending question.
        Returns the new candidate id, or None when it was already queued."""
        import uuid
        cand_id = str(uuid.uuid4())
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO identity_candidates"
                "(id, kind, entity_id, other_id, mention_ref, similarity, status, created_at) "
                "VALUES(?,?,?,?,?,?,'pending',?)",
                (cand_id, kind, entity_id, other_id or "", mention_ref or "",
                 float(similarity), now or now_iso()))
            inserted = cur.rowcount
        return cand_id if inserted else None

    def get_identity_candidates(self, status: str = "pending", kind: str = "",
                                limit: int = 100) -> List[dict]:
        """The adjudication queue. `status=''`/None returns every status."""
        where, params = [], []
        if status:
            where.append("status=?")
            params.append(status)
        if kind:
            where.append("kind=?")
            params.append(kind)
        clause = " AND ".join(where) if where else "1=1"
        params.append(int(limit))
        return [dict(r) for r in self._conn().execute(
            f"SELECT * FROM identity_candidates WHERE {clause} ORDER BY created_at, id LIMIT ?",
            tuple(params)).fetchall()]

    def get_identity_candidate(self, candidate_id: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT * FROM identity_candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row) if row else None

    def resolve_identity_candidate(self, candidate_id: str, status: str):
        """Record an adjudication OUTCOME on a queue row. Data only -- a direct
        projection write, addressed by row id.

        Nothing in this codebase reads this status and then merges or splits an
        entity: performing the decision is deliberately out of scope (issue #8
        E7). This exists so a reviewer can take a question off the queue.

        DOES NOT SURVIVE a projection rebuild (ladder-9 F4d): identity_candidates
        is projection state truncated and re-derived by truncate_projection +
        replay, and a row's id is a fresh uuid4 minted only on first creation --
        re-derivation from the same mention events after a truncate mints a
        NEW id for the same logical candidate. Calling this method durably
        records nothing an event log can replay. Use
        resolve_identity_candidate_by_key (via capture.append("adjudicated",
        ...) -- see reducer._on_adjudicated) for an outcome that must survive
        a rebuild."""
        with self.transaction() as conn:
            conn.execute("UPDATE identity_candidates SET status=?, resolved_at=? WHERE id=?",
                         (status, now_iso(), candidate_id))

    def resolve_identity_candidate_by_key(self, kind: str, entity_id: str, other_id: str,
                                          mention_ref: str, status: str,
                                          resolved_at: str = "") -> None:
        """Record an adjudication outcome addressed by the candidate's DEDUPE
        KEY (kind, entity_id, other_id, mention_ref) -- the same tuple
        enqueue_identity_candidate's UNIQUE index is keyed on -- rather than
        its row id (ladder-9 F4d).

        This is what makes an adjudication REPLAY-SAFE: reducer._on_adjudicated
        calls this from the 'adjudicated' event, and because the dedupe key
        (unlike the row's uuid4 id) is the same before and after a
        truncate_projection + full replay, the same UPDATE lands on whichever
        row identity.py's mention-driven enqueue just re-derived -- even
        though that row's id is brand new.

        A no-op, not an error, when the candidate does not exist yet -- e.g. a
        replay ordering where this fires before defensive-programming allows
        for (matches the "if found" shape _on_grant/_on_revoke already use for
        an event whose target may not resolve)."""
        with self.transaction() as conn:
            conn.execute(
                "UPDATE identity_candidates SET status=?, resolved_at=? "
                "WHERE kind=? AND entity_id=? AND other_id=? AND mention_ref=?",
                (status, resolved_at or now_iso(), kind, entity_id, other_id or "",
                 mention_ref or ""))

    # -- user knowledge (§19) ---------------------------------------------

    def upsert_user_knowledge(self, uk: dict):
        with self.transaction() as conn:
            cols = list(uk.keys())
            ph = ",".join(["?"] * len(cols))
            updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "belief_id")
            conn.execute(f"INSERT INTO user_knowledge({','.join(cols)}) VALUES({ph}) "
                         f"ON CONFLICT(belief_id) DO UPDATE SET {updates}", [uk[c] for c in cols])

    def query_user_knowledge(self, where: str = "1=1", params: tuple = (), limit: int = 50) -> list[dict]:
        return [dict(r) for r in self._conn().execute(
            f"SELECT * FROM user_knowledge WHERE {where} LIMIT ?", (*params, limit)).fetchall()]

    # -- calibration (§10.5) ----------------------------------------------

    def get_calibration_obs(self, source_type: str) -> list[dict]:
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

    def get_unresolved_misses(self, limit: int = 50) -> list[dict]:
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

    def get_active_policy(self, kind: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM policies WHERE kind=? AND active=1 LIMIT 1",
                                   (kind,)).fetchone()
        return dict(row) if row else None

    def get_policy(self, version: str) -> dict | None:
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

    def get_active_goals(self) -> list[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM goals WHERE status='active' ORDER BY created_at DESC").fetchall()]

    def add_reflection(self, reflection: dict):
        with self.transaction() as conn:
            cols = list(reflection.keys())
            ph = ",".join(["?"] * len(cols))
            conn.execute(f"INSERT OR REPLACE INTO reflections({','.join(cols)}) VALUES({ph})",
                         [reflection[c] for c in cols])

    def search_reflections(self, like: str, limit: int = 5) -> list[dict]:
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
            # query_proxy_vectors (E2) is derived exactly like the other three
            # vector tables here -- the reducer regenerates it on replay -- so
            # leaving it out would let doc2query proxies for beliefs that no
            # longer exist survive a projection rebuild and keep resolving to
            # ids the rebuild may never reissue.
            #
            # entity_centroids/identity_candidates are PROJECTION state (§E7):
            # both are folded from the log on the write path, so a rebuild that
            # kept them would double-count every mention into the running sums
            # and break byte-identical replay (I3). link_candidates is NOT here
            # for the opposite reason — it is fed by the federation sweep from
            # databases outside the log, so replaying the log cannot recreate it.
            #
            # rerank_hints (§H2) joins the list for the query_proxy_vectors
            # reason, not the entity_centroids one: a hint is a (query ->
            # belief_id) pointer, and a rebuild may never reissue those belief
            # ids, so a surviving hint would boost an id that no longer names
            # anything (or, worse, a DIFFERENT belief that happened to hash the
            # same way). Hints are cheap, bounded and expiring; stale pointers
            # into a rebuilt projection are not. host_model_proxies is NOT here
            # — it holds a host's reply verbatim, which the log cannot
            # regenerate, and the reducer re-applies it on the next write.
            for t in (BELIEF_TABLES + ["entities", "user_knowledge", "justifications",
                                       "corrections", "nogoods", "contradictions", "supersede_candidates",
                                       "entity_centroids", "identity_candidates",
                                       "observed_vectors", "session_index", "memory_vectors",
                                       "projection_vectors", "query_proxy_vectors",
                                       "rerank_hints"]):
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


def _has_table(conn, table: str) -> bool:
    """Companion probe to _has_col, for migrations that add whole TABLES.

    PRAGMA table_info on a missing table returns an empty set rather than
    raising, so this is the same cheap catalog read _has_col does.

    E7 and H1 each introduced an identical copy of this helper; merged to one
    definition so the later cannot shadow the earlier (ruff F811)."""
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (table,)).fetchone()
    return row is not None


def _belief_fts_text(table: str, b: dict) -> tuple[str, str]:
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
        'journal_ingest','session_summarize','embed','digest','federate_sweep','backfill_sweep')),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT,
    run_after TEXT);"""
_JOBS_INDEX_DDLS = (
    ("CREATE INDEX IF NOT EXISTS idx_jobs_ready ON curation_jobs(status, id) "
    "WHERE status='pending';"),
    # Serves the enqueue_curation / enqueue_embed_job dedup probe. Without it
    # every enqueue scans curation_jobs, which grows as the drain proceeds, so
    # the guard that exists to REMOVE work costs O(queue) per call and eats most
    # of what it saves.
    ("CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON curation_jobs(task, payload) "
    "WHERE status IN ('pending','running');"),
)
# One string for the _SCHEMA splice (executescript takes many statements);
# the rebuild path executes them one at a time (conn.execute takes exactly one).
_JOBS_INDEX_DDL = "\n".join(_JOBS_INDEX_DDLS)
_JOB_COLS = ("id,task,payload,depends_on,status,attempts,created_at,started_at,finished_at,"
             "error,run_after")

# Identity evidence (§E7, issue #8). Spliced into _SCHEMA below AND executed by
# _migrate, from this ONE definition, so a fresh install and an upgraded store
# can never disagree about the shape.
#
# entity_centroids is INCREMENTAL state, not a cache of a derivable value: it
# holds the running SUM of an entity's mention-context vectors plus the count, so
# a write folds a mention in with one O(dims) add instead of re-reading every
# mention. `model`/`dims` are part of the state because a sum accumulated under
# one embedding model is incomparable geometry under another (§24.4) — the row is
# reset, never mixed.
#
# identity_candidates is a review QUEUE and nothing else. A row here has never
# changed an entity: nothing in this codebase merges or splits an entity from a
# similarity, exactly as nothing links an external row from a name collision
# (§14.2, I20). Identity is adjudicated, never inferred.
#   kind='split'  -> (entity_id, mention_ref): this mention looks like a
#                    different subject than the entity's other mentions.
#   kind='merge'  -> (entity_id, other_id) held in sorted order so (A,B) and
#                    (B,A) are ONE row: these two entities look like one subject.
# The UNIQUE index is the dedupe: re-processing the same mention, or meeting the
# same pair again on a later write, is a no-op that KEEPS the original row —
# including any decision already recorded on it — instead of piling up duplicates
# or resurrecting an answered question (same contract as link_candidates).
_IDENTITY_DDL = """
CREATE TABLE IF NOT EXISTS entity_centroids (
    entity_id TEXT PRIMARY KEY, sum_vec BLOB, n INTEGER NOT NULL DEFAULT 0,
    dims INTEGER NOT NULL DEFAULT 0, model TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_entity_centroids_recent
    ON entity_centroids(updated_at DESC, entity_id DESC);

CREATE TABLE IF NOT EXISTS identity_candidates (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('split','merge')),
    entity_id TEXT NOT NULL, other_id TEXT NOT NULL DEFAULT '',
    mention_ref TEXT NOT NULL DEFAULT '', similarity REAL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','merged','split','rejected')),
    created_at TEXT, resolved_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_candidates_dedupe
    ON identity_candidates(kind, entity_id, other_id, mention_ref);
CREATE INDEX IF NOT EXISTS idx_identity_candidates_status
    ON identity_candidates(status, created_at, id);
"""

# Host-model piggyback (§H1). Spliced into _SCHEMA below AND probed by _migrate,
# so a fresh install and an upgraded store get the identical table.
#
# host_model_requests is the bounded queue: one row per unit of enrichment work
# Chronicle would like a host model to answer. `status` is exactly the spec's
# three-state lifecycle; `attached_at` is bookkeeping for "this one is riding on
# a turn right now", which is what keeps the hook to ONE in-flight request.
#
# host_model_results is the holding table for validated doc2query / rerank
# answers. H1 was built standalone, where E2/E3 did not exist; both are now in
# this tree, but H1 is plumbing-only by spec, so the results are still PARKED
# rather than consumed -- wiring E2's doc2query_callback and E3's reranker to
# drain this table is follow-up work, not part of H1. See
# engine/hostmodel.py HostModelRegistry.record_result for the hook.
#
# BOTH tables are empty on a default config — nothing writes to them unless
# host_model.piggyback is explicitly enabled.
_HOST_MODEL_REQUESTS_DDL = """CREATE TABLE IF NOT EXISTS host_model_requests (
    request_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('extract_facts','doc2query','rerank')),
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','answered','expired')),
    attached_at TEXT, resolved_at TEXT);"""
_HOST_MODEL_RESULTS_DDL = """CREATE TABLE IF NOT EXISTS host_model_results (
    request_id TEXT PRIMARY KEY, kind TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT);"""

# Host-model DRAIN (§H2). The two consumers H1 parked. Both tables are EMPTY on a
# default config: nothing writes to either unless host_model.piggyback is on AND a
# host actually returned a valid reply.
#
# host_model_proxies — the question set a host returned for one item, kept
# separately from the query_proxy_vectors rows it produces. Two jobs, one table:
#   1. DURABILITY. _write_doc2query_proxies is delete-then-write (integration fix
#      D), so a later re-assertion of the same belief would wipe host questions
#      and regenerate templates only. Keeping the host set here lets every future
#      regeneration re-apply the merge rule instead of silently reverting.
#   2. PROVENANCE. §H2 wants host-sourced proxies marked `source: host_model`.
#      That mark CANNOT be a new column on query_proxy_vectors: the H1 inertness
#      proof diffs a full row dump against the pre-H1 tree, that table is
#      non-empty at defaults, and one extra column changes every one of its rows.
#      A side table that is empty at defaults carries the mark instead, and is
#      excluded from the dump exactly the way H1's own two tables are.
#
# rerank_hints — a host rerank verdict, persisted as query->evidence relevance
# hints. A rerank reply arrives a turn LATE and so cannot reorder its own query
# (§H2); what it can do is inform the NEXT similar query. `query_key` is the
# hashed signature of the query's distinctive tokens (exact repeat match) and
# `tokens` is that same token list kept verbatim so a near-miss can still be
# scored by Jaccard overlap. `weight` is reciprocal-rank in the host's order,
# `expires_at` is the hard TTL, and the row count is capped
# (host_model.rerank_hints.max_entries) with oldest-first eviction — the same
# bounded-queue discipline host_model_requests uses. `owner` (schema_version
# 11, ladder-9 F4c) scopes both the write-time replace/cap and the read-time
# lookup so one owner's verdict can never re-weight, or evict, another
# owner's hints for a textually similar query.
_HOST_DRAIN_DDL = """
CREATE TABLE IF NOT EXISTS host_model_proxies (
    belief_id TEXT NOT NULL, proxy_idx INTEGER NOT NULL, question TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'host_model', request_id TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY(belief_id, proxy_idx));

CREATE TABLE IF NOT EXISTS rerank_hints (
    query_key TEXT NOT NULL, belief_id TEXT NOT NULL, weight REAL NOT NULL,
    tokens TEXT NOT NULL DEFAULT '[]', query_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT 'default',
    PRIMARY KEY(query_key, belief_id));
CREATE INDEX IF NOT EXISTS idx_rerank_hints_expiry ON rerank_hints(expires_at, created_at);
"""
# idx_rerank_hints_owner is deliberately NOT here: _SCHEMA (this DDL included)
# runs unconditionally on every _init_db, BEFORE _migrate. A real store
# sitting at exactly schema_version 10 has a rerank_hints table but no owner
# column yet, and CREATE INDEX IF NOT EXISTS still validates the columns it
# references even when the index itself is new -- "no such column: owner"
# out of the FIRST executescript, before the migration that would have added
# it ever runs. The index is created in _migrate, in the same probe-then-
# ALTER step that adds the column, where it is safe by construction.

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
    novelty REAL, occurrence_count INTEGER NOT NULL DEFAULT 1, rule_id TEXT, premises TEXT);
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
    novelty REAL, occurrence_count INTEGER NOT NULL DEFAULT 1,
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
    novelty REAL, occurrence_count INTEGER NOT NULL DEFAULT 1,
    verification TEXT DEFAULT '{"status":"unverified"}');
CREATE INDEX IF NOT EXISTS idx_notes_directive ON notes(always_inject) WHERE always_inject=1;

CREATE TABLE IF NOT EXISTS refs (
    belief_id TEXT PRIMARY KEY, topic TEXT, retrieval_url TEXT, retrieved_at TEXT,
    ttl_days INTEGER DEFAULT 30, cached_summary TEXT, stale_after TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT DEFAULT 'normal',
    criticality TEXT DEFAULT 'normal', confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT,
    superseded_by TEXT, created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim',
    utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT, novelty REAL,
    occurrence_count INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_refs_stale ON refs(stale_after);

CREATE TABLE IF NOT EXISTS relationships (
    belief_id TEXT PRIMARY KEY, source_id TEXT, predicate TEXT, target_id TEXT, external_ref TEXT,
    domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT, status TEXT, salience TEXT DEFAULT 'normal',
    criticality TEXT DEFAULT 'normal', confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT,
    superseded_by TEXT, created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim',
    utility REAL DEFAULT 0, purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT,
    novelty REAL, occurrence_count INTEGER NOT NULL DEFAULT 1, rule_id TEXT, premises TEXT);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id) WHERE status='active';

CREATE TABLE IF NOT EXISTS procedures (
    belief_id TEXT PRIMARY KEY, name TEXT, params TEXT, steps TEXT, success_criteria TEXT,
    derived_from TEXT DEFAULT '[]', domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT,
    status TEXT, salience TEXT DEFAULT 'normal', criticality TEXT DEFAULT 'normal',
    confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT, superseded_by TEXT,
    created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim', utility REAL DEFAULT 0,
    purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT, novelty REAL,
    occurrence_count INTEGER NOT NULL DEFAULT 1);

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

-- Ladder 9 E4 (update detection, §issue-8 E4): a NEVER-destructive, dated edge
-- recording that `new_belief_id` LOOKS like an update of `old_belief_id` --
-- same subject (or, absent one, the single closest match store-wide),
-- similarity above curation.supersede_similarity, but a different normalized
-- value. Nothing here changes belief status or deletes anything; it is a
-- candidate for a reader (or downstream adjudication) to reason about, e.g.
-- "latest wins". old_value/new_value are copied in at write time so the
-- chain renders without a join back through the (possibly since-changed)
-- belief tables.
CREATE TABLE IF NOT EXISTS supersede_candidates (
    id TEXT PRIMARY KEY, new_belief_id TEXT NOT NULL, old_belief_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fact', similarity REAL, new_value TEXT, old_value TEXT,
    created_at TEXT, UNIQUE(new_belief_id, old_belief_id));
CREATE INDEX IF NOT EXISTS idx_supersede_new ON supersede_candidates(new_belief_id);
CREATE INDEX IF NOT EXISTS idx_supersede_old ON supersede_candidates(old_belief_id);

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

-- E2 doc2query: question-prediction proxy vectors, linked back to the PARENT
-- item (belief_id for beliefs, event_id for the off-by-default excerpt path)
-- by belief_id + a 0-based proxy_idx (<= doc2query.MAX_PROXIES rows/item).
-- `kind` mirrors the parent's own belief kind ("fact","note",... or
-- "observed") so retrieval can resolve a proxy hit straight back to the
-- parent's own table/content -- the `question` text is stored for
-- inspectability only and is NEVER surfaced as answer content (§E2).
CREATE TABLE IF NOT EXISTS query_proxy_vectors (
    belief_id TEXT, proxy_idx INTEGER, kind TEXT, question TEXT,
    embedding BLOB, model TEXT, created_at TEXT, PRIMARY KEY(belief_id, proxy_idx));

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

-- Federation sweep bookkeeping (§14, g4). TWO cursors per provider, because the
-- sweep has two jobs that must not starve each other: last_row_id bounds how far
-- the ingest of NEW rows has got, rescan_cursor pages back over rows already
-- ingested to notice edits in place (an external row that changes keeps its id,
-- so a watermark alone would never look at it again). rescan_cursor wraps to 0
-- at the end of a lap.
CREATE TABLE IF NOT EXISTS federation_watermarks (
    db_name TEXT PRIMARY KEY, last_row_id INTEGER DEFAULT 0,
    rescan_cursor INTEGER DEFAULT 0, last_sync_at TEXT);

-- Review queue for POSSIBLE identity links (§14.2, I20). Nothing here is a link:
-- an external row that merely looks like a Chronicle entity lands here and waits
-- for adjudication. UNIQUE(entity_id, external_ref) makes re-queueing on every
-- rescan a no-op instead of a pile of duplicates.
CREATE TABLE IF NOT EXISTS link_candidates (
    id TEXT PRIMARY KEY, entity_id TEXT, external_ref TEXT, provider TEXT,
    candidate_reason TEXT, score REAL, reviewed INTEGER DEFAULT 0, decision TEXT,
    created_at TEXT, reviewed_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_link_candidates_pair
    ON link_candidates(entity_id, external_ref);
""" + _IDENTITY_DDL + "\n" + _HOST_MODEL_REQUESTS_DDL + "\n" + _HOST_MODEL_RESULTS_DDL + """
CREATE INDEX IF NOT EXISTS idx_host_model_pending
    ON host_model_requests(created_at) WHERE status='pending';
""" + _HOST_DRAIN_DDL
