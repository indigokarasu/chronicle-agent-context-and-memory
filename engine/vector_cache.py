"""
Chronicle — in-process float16 copies of `observed_vectors` and
`projection_vectors` for the raw tier.

The sections below are the observed copy's. ProjectionVectorCache, at the
bottom of this file, reuses its design; its own docstring says where the two
differ and why (exact rescoring, and a staleness check this table needs).

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
import time
from typing import Callable, List, Optional, Tuple

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


# -- projection_vectors ----------------------------------------------------

# Error bounds for the shortlist margin (ProjectionVectorCache.shortlist).
# float16 rounds a normal value to within 2^-11 of itself (relative) and a
# subnormal one to within 2^-25 (absolute); float32 rounds to within 2^-24.
_F16_REL = 2.0 ** -11
_F16_ABS = 2.0 ** -25
_F32_U = 2.0 ** -24
_F16_MAX = 65504.0          # largest finite float16; anything above becomes inf

# One consistent snapshot of the table's fingerprint: row count (answered from
# the covering provider index, not the blobs), max rowid (one b-tree descent),
# and the identity of the row at the rowid the copy was current at. Scalar
# subqueries rather than `COUNT(*), MAX(rowid)` side by side, because SQLite
# only takes its count and min/max shortcuts for a lone aggregate: the two
# together scan the table.
_PROJ_STATE_SQL = (
    "SELECT s.n, s.m, p.provider, p.external_id, p.owner, p.created_at, "
    "length(p.embedding), CASE WHEN length(p.embedding) = ? THEN p.embedding END "
    "FROM (SELECT (SELECT COUNT(*) FROM projection_vectors) AS n, "
    "(SELECT COALESCE(MAX(rowid), 0) FROM projection_vectors) AS m) AS s "
    "LEFT JOIN projection_vectors AS p ON p.rowid = ?")

# The same identity columns, per row, for a load. Only blobs at the copy's width
# cross into Python; every row is still counted, because the fingerprint is
# over the whole table.
_PROJ_LOAD_SQL = (
    "SELECT rowid, provider, external_id, owner, created_at, length(embedding), "
    "CASE WHEN length(embedding) = ? THEN embedding END "
    "FROM projection_vectors WHERE rowid > ?")

_NO_ROW = (None,) * 6        # the identity of a rowid that holds no row


class _Loaded:
    """What one read of projection_vectors returned (see ProjectionVectorCache._read)."""
    __slots__ = ("seen", "last_rowid", "last_identity", "rowids", "providers", "ext_ids",
                 "owners", "blocks", "max_norm", "servable")

    def __init__(self, after_rowid: int):
        self.seen = 0
        self.last_rowid = after_rowid
        self.last_identity = None
        self.rowids: list = []
        self.providers: list = []
        self.ext_ids: list = []
        self.owners: list = []
        self.blocks: list = []
        self.max_norm = 0.0
        self.servable = True


class _WidthCopy:
    """One width's float16 copy and the table fingerprint it is current at.

    Never mutated once built: an append builds a new copy, so a reader holding
    the previous one keeps a self-consistent set of arrays while it scores."""
    __slots__ = ("width", "rowids", "prov_codes", "providers", "ext_ids", "owner_codes",
                 "owners", "mat", "max_norm", "servable", "count", "max_rowid", "top")

    @classmethod
    def build(cls, width, got, base=None, count=0, max_rowid=0, top=_NO_ROW):
        import numpy as np
        c = cls()
        d = width // 4
        providers = list(base.providers) if base else []
        owners = list(base.owners) if base else []
        pidx = {v: i for i, v in enumerate(providers)}
        oidx = {v: i for i, v in enumerate(owners)}
        pcodes, ocodes = [], []
        for v in got.providers:
            if v not in pidx:
                pidx[v] = len(providers)
                providers.append(v)
            pcodes.append(pidx[v])
        for v in got.owners:
            if v not in oidx:
                oidx[v] = len(owners)
                owners.append(v)
            ocodes.append(oidx[v])
        new_rowids = np.asarray(got.rowids, dtype=np.int64)
        # Filled block by block, each block freed once copied: np.concatenate
        # would hold every block AND the whole matrix at once -- twice the
        # copy's size at its peak, on a box where every process keeps one.
        new_mat = np.empty((len(got.rowids), d), np.float16)
        at = 0
        while got.blocks:
            blk = got.blocks.pop(0)
            new_mat[at:at + blk.shape[0]] = blk
            at += blk.shape[0]
        if base is not None:
            c.rowids = np.concatenate([base.rowids, new_rowids])
            c.prov_codes = np.concatenate([base.prov_codes, np.asarray(pcodes, dtype=np.int32)])
            c.owner_codes = np.concatenate([base.owner_codes, np.asarray(ocodes, dtype=np.int32)])
            c.ext_ids = base.ext_ids + got.ext_ids
            c.mat = np.concatenate([base.mat, new_mat]) if len(new_rowids) else base.mat
            c.max_norm = max(base.max_norm, got.max_norm)
            c.servable = base.servable and got.servable
        else:
            c.rowids = new_rowids
            c.prov_codes = np.asarray(pcodes, dtype=np.int32)
            c.owner_codes = np.asarray(ocodes, dtype=np.int32)
            c.ext_ids = list(got.ext_ids)
            c.mat = new_mat
            c.max_norm = got.max_norm
            c.servable = got.servable
        c.width, c.providers, c.owners = width, providers, owners
        c.count, c.max_rowid, c.top = count, max_rowid, top
        return c

    @property
    def nbytes(self) -> int:
        return int(self.mat.nbytes)


class ProjectionVectorCache:
    """The projection tier's candidates from memory instead of a table scan.

    WHY. The raw tier's projection pass read every `projection_vectors` row from
    SQLite on every query -- ~95k 768-dim blobs, ~280 MB paged into Python and
    scored, 1.2-1.6 s of a 1.3-1.7 s search -- and the table grows with every
    embedded source. The rows change rarely next to how often they are read.

    WHAT IT HOLDS. Per query width, a float16 matrix of the rows at that width
    (~146 MB for 95k x 768; ~215 MB at 140k) plus each row's rowid, provider,
    external_id and owner. A query at another width gets a separate copy of its
    own rows, so the two never evict each other and neither holds the other's.

    WHAT IT RETURNS -- and why it is not simply the float16 scores. The tier's
    contract is exact: score = cosine * 0.5 over the stored float32 blob, a
    0.15 floor, the ACL check, a streaming top-`limit` heap, then rendering.
    float16 moves a cosine by up to ~1e-3, which is enough to reorder near
    neighbours and to push a row across the floor or the top-k cutoff. So the
    copy only decides which rows CAN be in the top-`limit`: every readable row
    whose float16 score is within a proven error bound (`eps`) of the floor
    and of the limit-th best. The caller re-reads exactly those rows' float32
    blobs by rowid and runs the unchanged tier loop over them in rowid order.
    Rows left out score below the final heap's minimum, and a row below that
    minimum never changes which rows the heap ends with (it can only occupy a
    slot that any higher row takes from it), so the result -- ids, scores and
    order -- is the paged scan's.

    STALENESS. Checked on every use, like the observed cache: row count and max
    rowid. Two differences, both measured or forced by this table:
      * The fingerprint is over the WHOLE table, not the rows at the query's
        width. projection_vectors has no width index, so a width-filtered
        COUNT reads every row's page (~0.25 s at 95k rows) -- a third of what
        the cache exists to save. The whole-table count comes from the
        provider index in well under a millisecond, and it is conservative: a
        change at any width is seen.
      * The identity of the row AT the recorded max rowid is part of the
        fingerprint. A source row whose text changes has its vector DELETED
        and later re-inserted by the embedding backlog; if the deleted row was
        the newest, SQLite hands the re-inserted row the same rowid, and count
        and max rowid both come back exactly as they were. With that row's
        identity (key, owner, created_at, width, blob) unchanged, any other
        delete shows in the count -- every insert lands above it -- so an
        append can be told from a delete exactly.
    Appends load only the new rows; anything else rebuilds. A copy that cannot
    prove it is current is not used.

    NOT SEEN: an in-place `UPDATE ... SET embedding` of a row other than the
    newest (the vector write-back tool does this). The rescoring above reads
    the current blob of every shortlisted row, so such a row is never scored
    stale; it can only be missed from the shortlist until the next rebuild.
    The observed cache has the same blind spot.
    """

    def __init__(self, store, max_rows: int = 400_000):
        self.store = store
        self.max_rows = int(max_rows)
        self._lock = threading.Lock()
        self._copies: dict = {}          # width in bytes -> _WidthCopy
        self._over_cap_warned = False
        self.rebuilds = 0
        self.appends = 0
        self.served = 0

    # -- state -------------------------------------------------------------
    def _read(self, conn, width: int, after_rowid: int, upto_rowid: Optional[int]) -> _Loaded:
        """Rows with rowid in (after_rowid, upto_rowid], in rowid order, in ONE
        statement -- so the count, the last row and the vectors are one
        snapshot. Loaded a chunk at a time: the transient is one chunk of
        blobs, not the table."""
        import numpy as np
        sql, params = _PROJ_LOAD_SQL, [width, after_rowid]
        if upto_rowid is not None:
            sql += " AND rowid <= ?"
            params.append(upto_rowid)
        cur = conn.execute(sql + " ORDER BY rowid", params)
        got = _Loaded(after_rowid)
        d = width // 4
        while True:
            rows = cur.fetchmany(_CHUNK)
            if not rows:
                break
            got.seen += len(rows)
            got.last_rowid = int(rows[-1][0])
            got.last_identity = tuple(rows[-1][1:7])
            keep = [r for r in rows if r[6] is not None]
            if not keep:
                continue
            m = np.frombuffer(b"".join(r[6] for r in keep), dtype=np.float32).reshape(len(keep), d)
            # A value float16 cannot hold (NaN, inf, beyond +/-65504) would make
            # the error bound meaningless; such a copy is never served.
            if not np.isfinite(m).all() or float(np.abs(m).max()) > _F16_MAX:
                got.servable = False
            else:
                got.max_norm = max(got.max_norm, float(np.linalg.norm(m, axis=1).max()))
            got.blocks.append(m.astype(np.float16))
            got.rowids.extend(r[0] for r in keep)
            got.providers.extend(r[1] for r in keep)
            got.ext_ids.extend(r[2] for r in keep)
            got.owners.extend(r[3] for r in keep)
        if got.last_identity is None:
            got.last_identity = _NO_ROW
        return got

    def _rebuild(self, conn, width: int) -> _WidthCopy:
        t0 = time.monotonic()
        self._copies.pop(width, None)     # not the old copy and the new one at once
        got = self._read(conn, width, 0, None)
        copy = _WidthCopy.build(width, got, count=got.seen, max_rowid=got.last_rowid,
                                top=got.last_identity)
        self._copies[width] = copy
        self.rebuilds += 1
        logger.info("projection-vector cache: %d of %d rows at %d dims in memory, %.1f MB "
                    "float16, loaded in %.2fs", copy.mat.shape[0], got.seen, width // 4,
                    copy.nbytes / 1e6, time.monotonic() - t0)
        return copy

    def _current(self, conn, width: int) -> Optional[_WidthCopy]:
        """The copy at `width`, brought up to date; None when it must not be used."""
        copy = self._copies.get(width)
        row = conn.execute(_PROJ_STATE_SQL, (width, copy.max_rowid if copy else 0)).fetchone()
        count, max_rowid = int(row[0]), int(row[1])
        if count > self.max_rows:
            if not self._over_cap_warned:
                logger.warning("projection-vector cache off: %d rows is over "
                               "retrieval.projection_cache.max_rows (%d); paged scan",
                               count, self.max_rows)
                self._over_cap_warned = True
            self._copies.clear()                    # do not hold memory it cannot use
            return None
        self._over_cap_warned = False
        if copy is None or tuple(row[2:8]) != copy.top:
            return self._rebuild(conn, width)      # first use, or the newest row changed
        if (count, max_rowid) == (copy.count, copy.max_rowid):
            return copy
        if count > copy.count and max_rowid > copy.max_rowid:
            got = self._read(conn, width, copy.max_rowid, max_rowid)
            # Every row above the old max is new, and the old max still stands,
            # so the count grew by exactly the rows read -- or something was
            # deleted too.
            if got.seen == count - copy.count and got.last_rowid == max_rowid:
                copy = _WidthCopy.build(width, got, base=copy, count=count,
                                        max_rowid=max_rowid, top=got.last_identity)
                self._copies[width] = copy
                self.appends += 1
                return copy
        return self._rebuild(conn, width)          # a delete, or anything else

    def invalidate(self, width: Optional[int] = None) -> None:
        """Drop one width's copy (or all): the next use rebuilds it."""
        with self._lock:
            if width is None:
                self._copies.clear()
            else:
                self._copies.pop(width, None)

    # -- use ---------------------------------------------------------------
    def shortlist(self, query, limit: int, floor: float,
                  readable: Callable[[Optional[str]], bool]):
        """Every row that can be in the tier's top-`limit` for `query`, as
        (rowid, provider, external_id, owner) in rowid order: readable, float16
        score within `eps` of above `floor`, and -- when at least `limit` rows
        are certainly above the floor -- within 2*eps of the limit-th best of
        them. None when the cache cannot serve (numpy absent, a bad query,
        the table over max_rows, a read error, values float16 cannot hold).

        The margin. With |m16 - m| <= 2^-11|m| + 2^-25 per component and
        float32 dot products off by at most d*2^-24 of sum|m_j q_j|, a float16
        score is within
            eps0 = |q| * max|m| * (2^-11 + 2.02 * d * 2^-24) + 2^-25 * sum|q_j|
        of the float32 one the tier computes; `eps` is twice that. If U is the
        limit-th best float16 score among rows certainly above the floor, at
        least `limit` eligible rows score >= U - eps exactly, so the final
        heap's minimum T >= U - eps, and every row scoring >= T exactly has a
        float16 score >= U - 2*eps."""
        try:
            import numpy as np
        except Exception:
            return None
        q = np.asarray(query, dtype=np.float32)
        if q.ndim != 1 or not q.shape[0] or limit <= 0 or not np.isfinite(q).all():
            return None
        d = int(q.shape[0])
        width = d * 4
        with self._lock:
            try:
                copy = self._current(self.store._conn(), width)
            except Exception as e:                 # never fail a search over the cache
                logger.warning("projection-vector cache unavailable (%s); paged scan", e)
                self._copies.clear()
                return None
            if copy is None or not copy.servable:
                return None
            self.served += 1
        n = copy.mat.shape[0]
        if n == 0:
            return []
        ok = np.fromiter((bool(readable(o)) for o in copy.owners), dtype=bool,
                         count=len(copy.owners))
        can = ok[copy.owner_codes]
        sims = np.empty(n, dtype=np.float32)
        for a in range(0, n, _CHUNK):
            sims[a:a + _CHUNK] = copy.mat[a:a + _CHUNK].astype(np.float32) @ q
        np.clip(sims, -1.0, 1.0, out=sims)         # as batch_cosine clips
        q64 = q.astype(np.float64)
        eps = 2.0 * (float(np.linalg.norm(q64)) * copy.max_norm * (_F16_REL + 2.02 * d * _F32_U)
                     + _F16_ABS * float(np.abs(q64).sum()))
        keep = can & (sims > floor - eps)
        sure = can & (sims > floor + eps)
        if int(sure.sum()) >= limit:
            kth = float(np.partition(sims[sure], -limit)[-limit])
            keep &= sims >= kth - 2.0 * eps
        return [(int(copy.rowids[i]), copy.providers[copy.prov_codes[i]], copy.ext_ids[i],
                 copy.owners[copy.owner_codes[i]]) for i in np.nonzero(keep)[0]]
