"""
Chronicle — an in-process float16 copy of `observed_vectors` for the raw tier.

WHY. `chronicle_search` spent ~3.0 of its 3.4 s in the raw tier's paged
brute-force scan: 66,576 observed vectors read from SQLite a page at a time on
every query (1.0 s paging blobs, 0.7 s cosine, the rest Python). The vectors
do not change between two queries a second apart, so reading them from disk
every time is the waste. This keeps them in memory, once per process, as a
float16 matrix -- half the bytes of the float32 blobs (a 768-wide store of
66k rows is ~100 MB) -- and scores a query against all of them at once.

WHY NOT sqlite-vec. Its vec0 index is filled only by NEW writes and is never
backfilled, so switching it on over a populated store hides every vector
already stored (see engine/vector_index.py). The owner chose this cache instead
(2026-09-18 21:03).

STALENESS. Other processes write the same store (the gateway captures turns
while the dashboard reads), so the cache checks the table on every use: row
count and max rowid at the query's width. Rows appended since the last check
are loaded incrementally; anything else (a delete, or a re-embed, which
REPLACEs the row and gives it a new rowid) rebuilds the whole copy. A cache
that cannot prove it is current is never used stale.

PRECISION. float16 keeps ~3 significant digits; a cosine computed from it is
within ~1e-3 of the float32 one. Retrieval's floor (0.1) and its fused ranking
are far coarser than that, but two candidates within 1e-3 of each other may
swap places -- the one difference from the paged scan.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional, Tuple

logger = logging.getLogger("chronicle.vector_cache")

# Rows scored per matrix product: bounds the float32 temporary to
# CHUNK * width * 4 bytes (8192 x 768 -> 24 MB) whatever the table size.
_CHUNK = 8192


class ObservedVectorCache:
    """Per-store, per-process. `scores(query)` or None when it cannot serve."""

    def __init__(self, store, max_rows: int = 250_000):
        self.store = store
        self.max_rows = int(max_rows)
        self._lock = threading.Lock()
        self._width: Optional[int] = None      # bytes per blob the copy holds
        self._ids: List[str] = []
        self._owners: List[Optional[str]] = []
        self._index: dict = {}
        self._mat = None                        # numpy float16 (n, d)
        self._count = 0
        self._max_rowid = 0
        self.rebuilds = 0
        self.appends = 0

    # -- state -------------------------------------------------------------
    def _table_state(self, conn, width: int) -> Tuple[int, int]:
        row = conn.execute("SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM observed_vectors "
                           "WHERE length(embedding) = ?", (width,)).fetchone()
        return int(row[0]), int(row[1])

    def _load(self, conn, width: int, after_rowid: int):
        import numpy as np
        rows = conn.execute("SELECT rowid, event_id, owner, embedding FROM observed_vectors "
                            "WHERE length(embedding) = ? AND rowid > ? ORDER BY rowid",
                            (width, after_rowid)).fetchall()
        ids = [r[1] for r in rows]
        owners = [r[2] for r in rows]
        d = width // 4
        mat = (np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float32)
               .reshape(len(rows), d).astype(np.float16)) if rows else np.zeros((0, d), np.float16)
        top = int(rows[-1][0]) if rows else after_rowid
        return ids, owners, mat, top

    def _rebuild(self, conn, width: int, count: int) -> None:
        ids, owners, mat, top = self._load(conn, width, 0)
        self._width, self._ids, self._owners, self._mat = width, ids, owners, mat
        self._index = {eid: i for i, eid in enumerate(ids)}
        self._count, self._max_rowid = len(ids), top
        self.rebuilds += 1
        if len(ids) != count:          # a write landed between the two reads
            self._count = -1           # forces the next use to re-check

    def _current(self, conn, width: int) -> bool:
        """Bring the copy up to date. False when it must not be used."""
        import numpy as np
        count, max_rowid = self._table_state(conn, width)
        if count > self.max_rows:
            return False
        if self._width != width or self._mat is None:
            self._rebuild(conn, width, count)
            return True
        if (count, max_rowid) == (self._count, self._max_rowid):
            return True
        if count > self._count >= 0 and max_rowid > self._max_rowid:
            ids, owners, mat, top = self._load(conn, width, self._max_rowid)
            if (self._count + len(ids) == count
                    and not any(eid in self._index for eid in ids)):
                base = len(self._ids)
                self._ids.extend(ids)
                self._owners.extend(owners)
                self._index.update({eid: base + i for i, eid in enumerate(ids)})
                self._mat = np.concatenate([self._mat, mat]) if len(ids) else self._mat
                self._count, self._max_rowid = count, top
                self.appends += 1
                return True
        self._rebuild(conn, width, count)   # deletes, re-embeds, anything else
        return True

    # -- use ---------------------------------------------------------------
    def scores(self, query):
        """(ids, owners, sims, index) for every cached row at the query's width,
        sims a float32 numpy array aligned to ids; None when the cache cannot
        serve (numpy absent, table over max_rows, a read error)."""
        try:
            import numpy as np
        except Exception:
            return None
        q = np.asarray(query, dtype=np.float32)
        if q.ndim != 1 or not q.shape[0]:
            return None
        width = int(q.shape[0]) * 4
        with self._lock:
            try:
                if not self._current(self.store._conn(), width):
                    return None
            except Exception as e:                 # never fail a search over the cache
                logger.warning("observed-vector cache unavailable (%s); paged scan", e)
                self._mat = None
                return None
            mat, ids, owners, index = self._mat, list(self._ids), list(self._owners), self._index
        n = mat.shape[0]
        sims = np.empty(n, dtype=np.float32)
        for a in range(0, n, _CHUNK):
            sims[a:a + _CHUNK] = mat[a:a + _CHUNK].astype(np.float32) @ q
        return ids, owners, sims, dict(index)
