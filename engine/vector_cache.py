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
count, max rowid, and the identity of the row AT that rowid, all at the
query's width (see ProjectionVectorCache below for why identity is part of
the fingerprint -- the short version: a delete followed by an insert can hand
the newest row's rowid straight back, so count and max rowid alone cannot
tell that from no change at all). Rows appended since the last check are
loaded incrementally; anything else (a delete, an identity change at the top,
or a re-embed) rebuilds the whole copy. A cache that cannot prove it is
current is never used stale.

A FOURTH signal, `generation` (F3, `MemoryStore.bump_vector_generation` / a
`meta` row per vector table -- see its docstring), catches the one write the
three above cannot: `scripts/writeback_vectors.py` UPDATEs a vector row IN
PLACE on its existing natural key, which moves none of count, max rowid or
the anchor's identity when the updated row is neither the newest nor deleted.
It is checked FIRST and, when it has moved since the copy's own last sync,
forces an unconditional rebuild -- the changed row could be anywhere in the
table, so nothing short of a full reload can be trusted. When it has NOT
moved, everything below is exactly the pre-F3 logic: an ordinary insert,
`INSERT OR REPLACE`, or delete -- including ones written by the server-side
ops scripts that issue raw SQL and never touch the generation at all -- is
still told apart by count, max rowid and identity alone, precisely as it
always was. The generation is deliberately NOT part of the append-vs-rebuild
arithmetic: an ops script's ordinary insert must keep taking the cheap
incremental path even though it never bumps anything.

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

from .passages import is_passage_id, split_passage_id

logger = logging.getLogger("chronicle.vector_cache")

# Rows scored per matrix product: bounds the float32 temporary to
# CHUNK * width * 4 bytes (8192 x 768 -> 24 MB) whatever the table size.
_CHUNK = 8192


# The table's (count, max rowid) at a width, plus the identity of the row AT
# a caller-given anchor rowid: event_id, owner, created_at, model and the
# embedding blob. The anchor is the CACHE's own last-known max rowid, not the
# table's current one (mirroring ProjectionVectorCache's `_PROJ_STATE_SQL`):
# a pure append never touches the row already sitting at the old max, so its
# identity comes back unchanged and only a delete (of that row, or a
# delete-then-reinsert that lands a new row on the same rowid) moves it.
# Reading identity by rowid, not by the scan `_load` uses, keeps a plain
# append to a large table an O(1) check instead of a second table scan.
_OBS_STATE_SQL = (
    "SELECT s.n, s.m, o.event_id, o.owner, o.created_at, o.model, o.embedding "
    "FROM (SELECT COUNT(*) AS n, COALESCE(MAX(rowid), 0) AS m FROM observed_vectors "
    "WHERE length(embedding) = ?) AS s LEFT JOIN observed_vectors AS o ON o.rowid = ?")

_OBS_NO_ROW = (None,) * 5     # the identity of a rowid that holds no row
_OBS_TABLE = "observed_vectors"


class ObservedVectorCache:
    """Per-store, per-process. `scores(query)` or None when it cannot serve.

    Freshness is (count, max rowid, identity-of-the-row-at-the-old-max) at
    the query's width -- see ProjectionVectorCache's docstring, which this
    design mirrors, for the full reasoning. In short: curation and the
    degraded-embedder retry queue delete an event's vector and later
    re-insert it (a changed embedding, sometimes under the same event_id and
    event-derived `created_at`, so those two columns alone do not always
    change either). When the deleted row held the table's max rowid, the
    reinsert can get that exact rowid back, so count and max rowid alone come
    back unchanged and a cache keyed on them only would keep serving the
    stale row under a vanished identity while the reinserted vector stays
    invisible. The identity check below closes that gap the same way the
    projection cache's does.

    A THIRD gap the identity check does NOT close (F3): an in-place `UPDATE`
    of a row that is neither the newest nor deleted -- `scripts/
    writeback_vectors.py` does exactly this, by design, on its natural key.
    Such a row never appears at the anchor rowid and never appears in an
    append's "rowid > old max" read, so it would sit in the copy under its
    stale bytes forever. `_generation` (MemoryStore.bump_vector_generation, a
    `meta` counter) is the signal for that case, checked FIRST and separately
    from everything below: when it has moved since the copy's last sync, the
    copy is rebuilt unconditionally, because the changed row could be any row
    in the table. `bump_vector_generation` is called ONLY for a same-rowid
    change to an existing row (see its docstring in engine/store.py) -- never
    for an ordinary insert or delete, which the count/max-rowid/identity
    checks below already tell apart on their own, and which is how most of
    this table's rows actually get written: the server-side ops scripts that
    embed new events issue raw SQL against the connection and never touch the
    generation at all. So when the generation has NOT moved, the appends path
    below is exactly the pre-F3 arithmetic, unconditionally on count and max
    rowid alone -- it has no generation term, on purpose, or every one of
    those scripts' ordinary batches would force a full rebuild instead of the
    cheap incremental load they are supposed to get.
    """

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
        self._top: tuple = _OBS_NO_ROW
        self._generation = 0                    # table's write generation at last sync
        self.rebuilds = 0
        self.appends = 0

    # -- state -------------------------------------------------------------
    def _table_state(self, conn, width: int, at_rowid: int) -> Tuple[int, int, tuple]:
        row = conn.execute(_OBS_STATE_SQL, (width, at_rowid)).fetchone()
        return int(row[0]), int(row[1]), tuple(row[2:7])

    def _load(self, conn, width: int, after_rowid: int):
        """Rows with rowid > after_rowid, in rowid order, plus the last one's
        rowid and identity -- the same shape `_table_state` returns, so a
        rebuild or append can set `_top` from data it already read instead of
        a second query."""
        import numpy as np
        rows = conn.execute(
            "SELECT rowid, event_id, owner, created_at, model, embedding FROM observed_vectors "
            "WHERE length(embedding) = ? AND rowid > ? ORDER BY rowid",
            (width, after_rowid)).fetchall()
        ids = [r[1] for r in rows]
        owners = [r[2] for r in rows]
        d = width // 4
        mat = (np.frombuffer(b"".join(r[5] for r in rows), dtype=np.float32)
               .reshape(len(rows), d).astype(np.float16)) if rows else np.zeros((0, d), np.float16)
        top_rowid = int(rows[-1][0]) if rows else after_rowid
        top = tuple(rows[-1][1:6]) if rows else None
        return ids, owners, mat, top_rowid, top

    def _rebuild(self, conn, width: int, count: int, generation: int) -> None:
        ids, owners, mat, max_rowid, top = self._load(conn, width, 0)
        self._width, self._ids, self._owners, self._mat = width, ids, owners, mat
        self._index = {eid: i for i, eid in enumerate(ids)}
        self._count, self._max_rowid = len(ids), max_rowid
        self._top = top if top is not None else _OBS_NO_ROW
        self._generation = generation
        self.rebuilds += 1
        if len(ids) != count:          # a write landed between the two reads
            self._count = -1           # forces the next use to re-check

    def _current(self, conn, width: int) -> bool:
        """Bring the copy up to date. False when it must not be used."""
        import numpy as np
        # Read BEFORE `_table_state`: a write that lands between the two
        # reads can only make the generation MORE current than the table
        # state we are about to compare it against, never the other way --
        # so a write we are about to price into `count`/`max_rowid` can never
        # be missing from `generation`. The reverse order could hide a
        # same-generation write behind a `count`/`max_rowid` read that
        # already reflects it.
        generation = self.store.get_vector_generation(_OBS_TABLE)
        count, max_rowid, top = self._table_state(conn, width, self._max_rowid)
        if count > self.max_rows:
            return False
        if generation != self._generation:
            # An in-place UPDATE landed somewhere in the table (F3) -- it
            # could be any row, not just one the checks below account for, so
            # nothing short of a full reload can be trusted.
            self._rebuild(conn, width, count, generation)
            return True
        if self._width != width or self._mat is None or top != self._top:
            self._rebuild(conn, width, count, generation)   # first use, or the anchor row changed
            return True
        if (count, max_rowid) == (self._count, self._max_rowid):
            return True
        if count > self._count >= 0 and max_rowid > self._max_rowid:
            # Pre-F3 arithmetic, deliberately with no generation term (see the
            # class docstring): most appends never bump it at all.
            ids, owners, mat, loaded_max, loaded_top = self._load(conn, width, self._max_rowid)
            if (self._count + len(ids) == count
                    and not any(eid in self._index for eid in ids)):
                base = len(self._ids)
                self._ids.extend(ids)
                self._owners.extend(owners)
                self._index.update({eid: base + i for i, eid in enumerate(ids)})
                self._mat = np.concatenate([self._mat, mat]) if len(ids) else self._mat
                self._count, self._max_rowid = count, loaded_max
                self._top = loaded_top if loaded_top is not None else self._top
                self.appends += 1
                return True
        self._rebuild(conn, width, count, generation)   # deletes, re-embeds, anything else
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
_PROJ_TABLE = "projection_vectors"


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
                 "owners", "mat", "max_norm", "servable", "count", "max_rowid", "top",
                 "has_passages", "generation")

    @classmethod
    def build(cls, width, got, base=None, count=0, max_rowid=0, top=_NO_ROW, generation=0):
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
        # Whether any row is a passage (engine/passages.py). Without one every
        # row is its own record and the shortlist keeps its row-level cut
        # unchanged; with one, the cut is taken over RECORDS (see shortlist).
        c.has_passages = bool(base is not None and base.has_passages) or any(
            is_passage_id(e) for e in got.ext_ids)
        c.generation = generation
        return c

    @property
    def nbytes(self) -> int:
        return int(self.mat.nbytes)


def _kth_record_score(copy, sims, sure, limit: int) -> Optional[float]:
    """The limit-th best RECORD score among `sure` rows, or None when fewer
    than `limit` distinct records have one.

    WHY RECORDS. The projection tier keeps one heap slot per record -- a
    record scores as its best vector, its own or a passage's
    (engine/passages.py) -- so its top-`limit` is the top-`limit` records,
    and with passages that reaches deeper than the limit-th best ROW: twenty
    passages of one document can fill the first twenty rows. Cutting at the
    row would drop records the paged scan keeps. The margin argument of
    `shortlist` carries over unchanged with U taken over records: at least
    `limit` records have a sure row with float16 score >= U, so the final
    heap's minimum is >= U - eps, and the best row of every record in it
    scores >= U - 2*eps in float16.

    Cost: one argpartition over the sure rows, then a walk down at most m of
    them in score order, m starting at 4*limit and widening only while fewer
    than `limit` records have been seen (one record can own many rows)."""
    import numpy as np
    idx = np.nonzero(sure)[0]
    s = sims[idx]
    n = int(idx.shape[0])
    m = min(n, max(1, limit) * 4)
    while True:
        if m < n:
            top = np.argpartition(-s, m - 1)[:m]
        else:
            top = np.arange(n)
        top = top[np.argsort(-s[top], kind="stable")]
        seen = set()
        for t in top:
            i = int(idx[t])
            seen.add((int(copy.prov_codes[i]), split_passage_id(copy.ext_ids[i])[0]))
            if len(seen) >= limit:
                return float(s[t])
        if m >= n:
            return None
        m = min(n, m * 4)


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
    A fourth signal, `generation` (F3): `scripts/writeback_vectors.py` UPDATEs
    a row IN PLACE on its natural key, which moves none of count, max rowid or
    the anchor's identity when the updated row is neither the newest nor
    deleted. `MemoryStore.bump_vector_generation` advances a `meta` counter
    for exactly that case -- a same-rowid change to an existing row -- and
    nothing else; see its docstring in engine/store.py. It is checked FIRST,
    separately from the three signals above: when it has moved since the
    copy's own last sync, the copy is rebuilt unconditionally, because the
    changed row could be any row in the table, not only ones the checks below
    would catch. It deliberately does NOT participate in the append-vs-delete
    arithmetic below: an ordinary insert never bumps it (most of this table's
    rows are written by ops scripts issuing raw SQL that never call
    bump_vector_generation at all), so once the generation check has passed,
    appends and deletes are told apart exactly as they were before F3.
    Appends load only the new rows; anything else rebuilds. A copy that cannot
    prove it is current is not used.

    The rescoring in `shortlist` reads the CURRENT blob of every row it
    returns, by rowid, so a shortlisted row is never scored from stale bytes
    even when the copy predates F3 or a generation race slips through; the
    remaining risk `generation` closes is a stale row being MISSED from the
    shortlist entirely because the copy's own float16 vector -- used only to
    decide who is a candidate -- was never refreshed.
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

    def _rebuild(self, conn, width: int, generation: int) -> _WidthCopy:
        t0 = time.monotonic()
        self._copies.pop(width, None)     # not the old copy and the new one at once
        got = self._read(conn, width, 0, None)
        copy = _WidthCopy.build(width, got, count=got.seen, max_rowid=got.last_rowid,
                                top=got.last_identity, generation=generation)
        self._copies[width] = copy
        self.rebuilds += 1
        logger.info("projection-vector cache: %d of %d rows at %d dims in memory, %.1f MB "
                    "float16, loaded in %.2fs", copy.mat.shape[0], got.seen, width // 4,
                    copy.nbytes / 1e6, time.monotonic() - t0)
        return copy

    def _current(self, conn, width: int) -> Optional[_WidthCopy]:
        """The copy at `width`, brought up to date; None when it must not be used."""
        copy = self._copies.get(width)
        # Read BEFORE the row/rowid state (same ordering argument as
        # ObservedVectorCache._current): a write landing between the two reads
        # can only make `generation` at least as current as the state we
        # compare it against, never behind it.
        generation = self.store.get_vector_generation(_PROJ_TABLE)
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
        if copy is not None and generation != copy.generation:
            # An in-place UPDATE landed somewhere in the table (F3) -- it
            # could be any row, not just one the checks below account for, so
            # nothing short of a full reload can be trusted.
            return self._rebuild(conn, width, generation)
        if copy is None or tuple(row[2:8]) != copy.top:
            return self._rebuild(conn, width, generation)   # first use, or the newest row changed
        if (count, max_rowid) == (copy.count, copy.max_rowid):
            return copy
        if count > copy.count and max_rowid > copy.max_rowid:
            # Pre-F3 arithmetic, deliberately with no generation term (see the
            # class docstring): most appends never bump it at all.
            got = self._read(conn, width, copy.max_rowid, max_rowid)
            # Every row above the old max is new, and the old max still stands,
            # so the count grew by exactly the rows read -- or something was
            # deleted too.
            if got.seen == count - copy.count and got.last_rowid == max_rowid:
                copy = _WidthCopy.build(width, got, base=copy, count=count,
                                        max_rowid=max_rowid, top=got.last_identity,
                                        generation=generation)
                self._copies[width] = copy
                self.appends += 1
                return copy
        return self._rebuild(conn, width, generation)          # a delete, or anything else

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
            if copy.has_passages:
                kth = _kth_record_score(copy, sims, sure, limit)
            else:
                kth = float(np.partition(sims[sure], -limit)[-limit])
            if kth is not None:
                keep &= sims >= kth - 2.0 * eps
        return [(int(copy.rowids[i]), copy.providers[copy.prov_codes[i]], copy.ext_ids[i],
                 copy.owners[copy.owner_codes[i]]) for i in np.nonzero(keep)[0]]
