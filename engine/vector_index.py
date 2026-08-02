"""
Chronicle — Optional sqlite-vec ANN index (§27 vector_index:).

Guarded exactly like the numpy fast path in embeddings.batch_cosine: `import
sqlite_vec` is best-effort, and every public method is a safe no-op (or an
empty result) when the library isn't importable, the config didn't ask for it,
or -- the case that actually bites on this box's stdlib -- the running
Python's sqlite3 module was built without loadable-extension support at all
(Apple's macOS system Python omits it; `sqlite3.Connection.enable_load_extension`
doesn't exist there, so `sqlite_vec.load(conn)` can never run). All three
"unavailable" reasons collapse to the same paged brute-force path the caller
already has (§24.3), so nothing downstream needs to know which one applies.

When it DOES work: a lazily-created vec0 virtual table mirrors
`observed_vectors`, and KNN `MATCH` queries replace the paged brute-force scan
in retrieve_raw.

Schema setup (CREATE VIRTUAL TABLE) and every row write happen on the CALLER's
OWN connection, never a second one, and NEVER call conn.commit() themselves:
add_observed_vector is sometimes invoked from deep inside reducer._on_observed,
itself nested inside append_event's single re-entrant write transaction (I7,
§6.3) -- MemoryStore's `_write_lock` already serializes every writer thread
against that ONE thread-local connection, so there is no concurrent-table-
creation race to guard against, but a SEPARATE connection opened here to dodge
that (an earlier version of this file did exactly that) would instead
self-deadlock: SQLite allows only one writer per db file, so a second
connection's write blocks on the still-open, not-yet-committed outer
transaction, which can't proceed until this call returns. Piggybacking on the
caller's own connection/transaction avoids the whole class of problem --
whichever `with store.transaction()` block is outermost commits it, same as
every other write in that block.
"""

from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger("chronicle.vector_index")

# vec0 rejects a KNN query outright above this k ("k value in knn query too
# large, provided N and the limit is 4096"), so it is clamped rather than left
# to raise -- an unclamped k would turn a large `limit` into a silent, total
# fall-back to the paged scan. Exported because retrieve_raw's window-widening
# loop needs the same ceiling to know when to stop asking for more.
MAX_K = 4096

# Lazy import guard: if sqlite_vec is not available, every method becomes a no-op.
_SQLITE_VEC_AVAILABLE = False
try:
    import sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    pass

# Tri-state cache: None = not yet probed, else True/False for the lifetime of
# the process. A build either has sqlite3.Connection.enable_load_extension or
# it doesn't -- this can't change at runtime, so probe once and remember.
_EXT_SUPPORT = None


def _extension_loading_possible() -> bool:
    global _EXT_SUPPORT
    if _EXT_SUPPORT is None:
        _EXT_SUPPORT = hasattr(sqlite3.Connection, "enable_load_extension")
        if not _EXT_SUPPORT:
            logger.warning(
                "vector_index: this Python's sqlite3 module has no "
                "enable_load_extension (common on Apple's macOS system Python, "
                "built with SQLITE_OMIT_LOAD_EXTENSION) -- sqlite-vec can never "
                "load in this process; the paged brute-force scan is used instead")
    return _EXT_SUPPORT


def _try_load_extension(conn) -> bool:
    """Best-effort: enable + load the sqlite-vec extension on `conn`.

    Loadable extensions register per-CONNECTION (like an FTS5 tokenizer), and
    MemoryStore hands out one sqlite3.Connection per thread (threading.local),
    so this runs on every access rather than once at startup -- once per vector
    write and once per query.

    Hence the `vec_version()` fast path: that function resolves only when the
    extension is already registered on THIS connection, and costs <1us against
    ~150us to re-run sqlite_vec.load() (dlopen + entry point), which at one
    call per row is a measurable tax on the write path. It is a positive check
    on the connection actually in hand, so unlike a cache keyed on id(conn) --
    sqlite3.Connection supports neither weakrefs nor attribute stashing, so
    that is the only cache available -- it cannot go stale and silently
    mis-report a fresh connection that reused a dead one's id.

    None of these calls touch SQL transaction state (a SELECT never opens a
    write transaction, and a statement that fails to PREPARE changes nothing),
    so this is safe whether or not `conn` has an open transaction.
    """
    if not _SQLITE_VEC_AVAILABLE or not _extension_loading_possible():
        return False
    try:
        conn.execute("SELECT vec_version()")
        return True
    except sqlite3.Error:
        pass  # not registered on this connection yet -- load it below
    try:
        conn.enable_load_extension(True)
    except Exception as e:
        logger.info("vector_index: enable_load_extension failed (%s); using bruteforce", e)
        return False
    try:
        sqlite_vec.load(conn)
        return True
    except Exception as e:
        logger.warning("vector_index: sqlite_vec.load failed (%s); using bruteforce", e)
        return False
    finally:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass


def _declared_dims(conn):
    """Width vec0 was actually CREATEd with, from its stored DDL, or None if the
    table doesn't exist / can't be parsed."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='vec0'").fetchone()
    if not row or not row[0]:
        return None
    m = re.search(r"FLOAT\s*\[\s*(\d+)\s*\]", row[0], re.I)
    return int(m.group(1)) if m else None


def delete_matching(conn, predicate_sql: str, params) -> int:
    """Best-effort delete from vec0 for standalone scripts that mutate
    `observed_vectors` directly via raw SQL (scripts/prune_vectors.py) instead
    of through MemoryStore/VectorIndex. `predicate_sql` is a boolean SQL
    fragment over vec0's own columns -- vec0 carries the same `event_id`
    column as `observed_vectors`, so the caller's existing WHERE clause applies
    unchanged. Returns 0 (never raises) if sqlite-vec isn't usable here or vec0
    was never created -- the caller's primary delete already succeeded; this
    is strictly a secondary index mirror. Does not commit -- the caller's own
    commit (already needed for its primary delete) covers this too.
    """
    if not _try_load_extension(conn):
        return 0
    try:
        return conn.execute(f"DELETE FROM vec0 WHERE {predicate_sql}", params).rowcount
    except sqlite3.OperationalError:
        return 0  # no such table: vec0 -- sqlite-vec was never engaged on this db


class VectorIndex:
    """Optional ANN index backed by a sqlite-vec `vec0` virtual table.

    One instance is shared between the store (writes: add/delete/prune) and
    the retrieval engine (reads: KNN in retrieve_raw) -- see ChronicleCore,
    which constructs exactly one and hands it to both. Every method degrades
    to a safe no-op the moment `is_enabled()` is false, so an unconfigured or
    library-less deployment never notices this class exists.
    """

    def __init__(self, store, config, embedder=None):
        self.store = store
        self.config = config
        self.embedder = embedder
        self.backend = config.get("vector_index.backend", "bruteforce")
        self._table_ready = False   # sticky: vec0 has been created (or already existed)
        self._load_failed = False  # sticky: a real failure (not just "unconfigured") disables the fast path

    def dims(self) -> int:
        """vec0's column width, read from the ACTIVE embedder at table-creation
        time rather than snapshotted in __init__. DegradedEmbedder writes no
        vectors while degraded and reports the real model's dimensionality only
        after `recheck()` adopts one -- so a width captured at construction
        would be the placeholder, not what actually gets written. Config is the
        fallback for a store with no embedder wired."""
        d = getattr(self.embedder, "dimensions", None)
        return int(d) if d else int(self.config.get("embeddings.dimensions", 768) or 768)

    def is_enabled(self) -> bool:
        """Config asked for sqlite-vec, the library imported, and nothing has
        failed yet. Necessary, not sufficient -- extension loading can still
        fail on first real use (self-heals to False forever via `_load_failed`,
        e.g. a stdlib build with no loadable-extension support at all)."""
        return self.backend == "sqlite-vec" and _SQLITE_VEC_AVAILABLE and not self._load_failed

    def probe(self) -> bool:
        """Force an immediate extension-load attempt on the store's own
        connection and report whether the ANN fast path is really usable in
        this process, right now -- config+import+extension-loading all
        satisfied. Deliberately does NOT touch vec0's schema (table creation
        is lazy, on the first real write, on whichever connection/transaction
        happens to be open there); this only needs to know whether loading the
        extension itself would succeed."""
        if not self.is_enabled():
            return False
        if not _try_load_extension(self.store._conn()):
            self._load_failed = True
            return False
        return True

    # -- writes (always on the CALLER's own connection/transaction) ---------

    def _prepare(self, conn) -> bool:
        """Load the extension + ensure vec0 exists, on `conn` -- the caller's
        own connection. Never a second connection (see module docstring), and
        never a commit of its own: whatever transaction already has `conn`
        open (or none) owns that."""
        if self._load_failed or not self.is_enabled():
            return False
        if not _try_load_extension(conn):
            self._load_failed = True
            return False
        if not self._table_ready:
            dims = self.dims()
            try:
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS vec0 USING vec0("
                    f"event_id TEXT PRIMARY KEY, embedding FLOAT[{dims}])")
            except Exception as e:
                logger.error("vector_index: failed to create vec0: %s", e)
                self._load_failed = True
                return False
            # IF NOT EXISTS silently keeps the width an EXISTING vec0 was created
            # with, so a store whose embedding dimensionality later changed would
            # reject every insert and every query from here to eternity, one
            # logged warning per row. Check once and disable instead: brute force
            # reads the real observed_vectors blobs and is always correct.
            got = _declared_dims(conn)
            if got is not None and got != dims:
                logger.error("vector_index: existing vec0 is dim=%d but the active embedder emits "
                             "dim=%d -- disabling the ANN fast path (drop the vec0 table to rebuild "
                             "it); the paged brute-force scan is used instead", got, dims)
                self._load_failed = True
                return False
            self._table_ready = True
            logger.info("vector_index: vec0 ready (sqlite-vec backend, dim=%d)", dims)
        return True

    def add_observed_vector(self, conn, event_id: str, embedding: bytes):
        """Insert or update a vector in vec0, on `conn` (the caller's own
        connection -- store.add_observed_vector's ambient transaction, which
        may itself be nested arbitrarily deep inside append_event's single
        re-entrant transaction, I7). Never commits: the ambient transaction
        owns that."""
        if not self._prepare(conn):
            return
        try:
            conn.execute("INSERT OR REPLACE INTO vec0(event_id, embedding) VALUES(?, ?)",
                         (event_id, embedding))
        except Exception as e:
            logger.warning("vector_index: failed to add vector for %s: %s", event_id, e)

    def delete_observed_vector(self, conn, event_id: str):
        """Remove a vector from vec0, on the caller's own connection/transaction."""
        if not self._prepare(conn):
            return
        try:
            conn.execute("DELETE FROM vec0 WHERE event_id = ?", (event_id,))
        except Exception as e:
            logger.warning("vector_index: failed to delete vector for %s: %s", event_id, e)

    def prune_observed_vectors(self, conn, keep_event_ids):
        """Delete every vec0 row NOT in `keep_event_ids` (empty set = drop all,
        used by truncate_projection's full rebuild). Runs on the caller's own
        connection/transaction, chunked to respect SQLite's bound on bound
        variables per statement (mirrors scripts/prune_vectors.py's discipline)."""
        if not self._prepare(conn):
            return
        try:
            keep = set(keep_event_ids)
            rows = [r[0] for r in conn.execute("SELECT event_id FROM vec0").fetchall()]
            drop = [eid for eid in rows if eid not in keep]
            chunk = 500
            for i in range(0, len(drop), chunk):
                part = drop[i:i + chunk]
                ph = ",".join("?" * len(part))
                conn.execute(f"DELETE FROM vec0 WHERE event_id IN ({ph})", part)
            if drop:
                logger.info("vector_index: pruned %d vectors from vec0", len(drop))
        except Exception as e:
            logger.warning("vector_index: failed to prune vectors: %s", e)

    # -- reads (standalone: uses the store's own connection, no schema writes) -

    def retrieve_knn(self, query_embedding: bytes, limit: int) -> list:
        """Top-k (event_id, similarity) from vec0 by KNN, similarity-descending.
        `limit` is clamped to MAX_K (see above) rather than allowed to raise.

        Never creates vec0 -- if it doesn't exist (nothing has ever been added
        via add_observed_vector while enabled), the query below fails with "no
        such table", caught and treated as "no results" exactly like an empty
        table would be.

        `distance` from vec0's default metric is Euclidean (L2) over the
        (pre-normalized, §embeddings.pack) embedding; for unit vectors that
        relates to cosine by distance^2 = 2 - 2*cosine, so cosine is recovered
        exactly as 1 - distance^2/2 -- NOT 1 - distance/2, which is a different
        (still monotonic, but numerically wrong) curve. vec0 computes in
        float32, so this lands ~1e-7 off the float64/numpy dot the paged scan
        uses (measured worst case 7.4e-8 over accept_u5's sweep). Returns []
        the moment anything about the fast path isn't available; the caller
        always has a brute-force fallback for that.
        """
        if not self.is_enabled() or not query_embedding:
            return []
        k = max(1, min(int(limit), MAX_K))
        conn = self.store._conn()
        if not _try_load_extension(conn):
            self._load_failed = True
            return []
        try:
            rows = conn.execute(
                "SELECT event_id, distance FROM vec0 WHERE embedding MATCH ? AND k = ? "
                "ORDER BY distance", (query_embedding, k)).fetchall()
        except Exception as e:
            if "no such table" not in str(e).lower():
                logger.debug("vector_index: KNN query error (falling back to brute-force): %s", e)
            return []
        return [(row[0], max(-1.0, min(1.0, 1.0 - (row[1] * row[1]) / 2.0))) for row in rows]
