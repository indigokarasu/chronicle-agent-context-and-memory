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
import re
import sqlite3
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from typing import List, Optional  # names this module already annotates with

from .embeddings import batch_cosine_f64
from .serialize import projection_row_id

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
# Ladder 9 renumbering: E5, E7 and H1 were each built against a v5 store and
# each claimed "6" independently. They are sequenced here into ONE ladder --
# there is only one meta.schema_version, so two features cannot both be 6 and
# still be distinguishable on an upgrade. Every step below stays probe-then-
# apply (_has_col / _has_table), so the ladder is order-independent and
# re-entrant: a store at ANY prior version converges by running all of them,
# and the version is stamped LAST so an interrupted migration re-runs rather
# than claiming a shape it never reached.
# 12 = procedures + body (A0fix D3). Every other vectored belief kind stores the
#     text reducer.vector_text() embedded in a projection column (facts.value,
#     episodes.summary, notes.body, refs.cached_summary); `procedure` stored only
#     `procedures.name`, which tools._t_remember sets to content[:40]. A
#     procedure asserted with a body was therefore VECTORISED from the full body
#     and, whenever anything re-embedded it (the heal, migrate_vectors,
#     requeue_hash_vectors), RE-vectorised from a 40-character truncation and
#     then stamped with the canonical tag that says the vector is correct. The
#     column closes the gap: NULL means "written before this column existed, the
#     body is not recorded" — an honest unknown that reducer.belief_vector_text()
#     refuses on rather than guessing — while '' means the body really was empty
#     and key.name is what the reducer embedded.
# 13 = session_index + model (A0e). session_index was the ONE embedding-bearing
#     table with no model column, so a session-summary vector's geometry was
#     recorded nowhere: staleness there was undetectable by any tag check and
#     visible only as a blob width, and neither the heal nor
#     scripts/migrate_vectors.py scanned the table at all. On the live store
#     that left 6,753 of 7,288 session vectors (93%) at 2048 dims under a
#     768-dim embedder, with nothing in the system that would ever find them —
#     and session summaries are the whole-conversation handle multi-session
#     retrieval leans on, so that was a materially degraded channel, not a
#     cosmetic gap.
#
#     THE LEGACY-NULL RULE, stated once here because three modules depend on it:
#     the column is added with NO DEFAULT, so every pre-existing row is NULL.
#     NULL means "unknown geometry" — nothing on this box knows which embedder
#     wrote those bytes — and is classified STALE by both
#     HealthEngine._classify_tag and migrate_vectors.classify
#     (split_model_tag(None) canonicalizes to the 'auto' placeholder, which is
#     never a real model id). It is stale EXACTLY ONCE: the re-embed stamps the
#     canonical tag, after which the row reads "ok" and a second run does
#     nothing. There is deliberately NO BACKFILL, for the same reason A1b gave:
#     backfilling invents a fact the store never recorded, and a guessed tag
#     would make an incomparable vector look canonical forever — undetectable,
#     where NULL is detectable.
# --- v5.7.0 integration ladder (ladder 10) ----------------------------------
# Six independent ladder-10 trees each claimed 12 and/or 13 against v5.6.0's 11.
# They are sequenced here into ONE chain, exactly as ladder 9 sequenced E5/E7/H1
# above and for the same reason: there is only one meta.schema_version. 12 and
# 13 keep the A0-family meanings because that chain (A0 -> A2 -> A0fix -> A0e2)
# is the reviewed production-gate code and its tests pin those numbers. The
# disjoint-table rungs follow, and the two curation_jobs rungs go LAST, rebuild
# before index, so a v11 store never builds indexes a rebuild then has to carry.
# Rungs land in this file as their trees are merged; a number is RESERVED until
# then so no two trees can claim it (same discipline A7 used for A3's 12).
# 14 = rerank_hints + principal (ladder-10 A1; claimed 12 in its own tree).
#     `owner` (11) closed the CROSS-OWNER leak; it cannot close the SANDBOX
#     one, because a sandboxed agent shares its owner with exactly the
#     siblings it must not reach. `principal` records WHICH principal the host
#     verdict was recorded for, so RetrievalEngine._hint_scores can drop hints
#     authored by a sandboxed principal before they re-weight a sibling's
#     ranking. Defaults to '' -- an unattributed row, which the read path
#     treats as un-sandboxed exactly as it did before the column existed
#     (§H2's inertness invariant means a default store has no such rows to
#     get wrong).
# 15 = goals + reflections carry `owner` and `read_acl` (ladder-10 A1b;
#     claimed 13 in its own tree). A1 put every user-visible read behind
#     access.can_read, but two surfaces could not be closed at the choke
#     point: reasoning.active_goals() and reasoning.recall_similar_situations()
#     (the latter reaching user-visible output through plan_context). Those two
#     tables carried NO owner and NO read_acl, so there was nothing for
#     can_read to decide on -- a sandboxed agent's goals and reflections
#     surfaced in another principal's plan context. The two columns are the SAME
#     pair every other belief table already carries
#     (facts/notes/episodes/procedures/user_knowledge: `owner TEXT, read_acl
#     TEXT`), added with the same probe-then-ALTER shape. Both are nullable with
#     NO default, deliberately: NULL is the durable mark of a row written before
#     this version, i.e. LEGACY / unattributed, and the read gate resolves it to
#     the pre-topology "default" principal (reasoning.LEGACY_OWNER) -- which a
#     configured topology matches nothing in, so a legacy row fails CLOSED for
#     every declared principal and can never reach a sandboxed or foreign one.
#     See reasoning._readable_row.
# 16 = maintenance_runs table (ladder-10 A3; claimed 12 in its own tree, which
#     A7 had already reserved for it). The watermark table the in-process
#     maintenance scheduler (engine/scheduler.py) consults on each hook call:
#     one row per SCHEDULE ENTRY (not per task -- `decay` is driven by two
#     schedules), recording the cron instant it was last enqueued FOR. It is
#     OPERATIONAL state, not projection state, which is why truncate_projection
#     leaves it alone (see the comment there). Empty until the first maintenance
#     job is actually scheduled, which on a freshly created store is never
#     within one session (see Scheduler._anchor_dt). Same probe-then-apply shape
#     as every step above, from the SAME _MAINTENANCE_DDL that _SCHEMA splices,
#     so a fresh install and a migrated store cannot disagree about the shape.
# 17 = curation_jobs task CHECK NARROWED (ladder-10 A13; claimed 13 in its own
#     tree). 'route' and 'criticality' were CHECK-listed with no _task_ handler
#     in any build: an enqueue passed the CHECK, sat in the queue and completed
#     as 'no_handler'. 'contradiction' had a handler that was a second name for
#     health.consistency_sweep(). All three leave the CHECK, generated now from
#     CURATION_TASKS so the list cannot drift from the handlers again. This is
#     the FIRST step on the ladder that removes rather than adds, so it is the
#     first whose probe looks for a value that is PRESENT, and the first that
#     has to resolve existing rows before the rebuild copies them (see
#     _retire_removed_task_rows). It runs EARLY in _migrate, inside the existing
#     curation_jobs block right after run_after, so the retired rows are dealt
#     with before the rebuild's copy INSERT meets the narrower CHECK.
#
#     meta.curation_tasks_retired records SCHEMA_VERSION at the time of
#     retirement, so on this ladder it reads 18, not A13's 13.
# 18 = queue + vector-census INDEXES (§A7): idx_jobs_task_ready (the fair
#     drain's per-class claim), idx_jobs_lease (the stale-lease scan),
#     idx_jobs_terminal (the retention prune), and one expression index per
#     vector table on (model, length(embedding)) so the embedder-mismatch heal
#     seeks the mismatched rows instead of scanning every blob in the store.
#     Index-only: no column and no row is touched, so this step is pure
#     probe-then-create. It is sequenced LAST in _migrate so that A13's
#     curation_jobs rebuild (17) runs first and this loop then creates the
#     indexes once, on the rebuilt table, instead of building them and making
#     the rebuild replay them. Every DDL uses IF NOT EXISTS, so the reverse
#     order is also safe -- the ordering is about work, not correctness.
#
# The number is bookkeeping: every rung below is probe-then-apply and the stamp
# is the LAST statement of _migrate, so a store at ANY prior version -- or one
# stamped 12/13 by a DIFFERENT ladder-10 tree than the one that owns the number
# here -- converges by running all of them.
SCHEMA_VERSION = 18

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
# Every table truncate_projection() empties -- i.e. everything the reducer is
# expected to be able to re-derive from the event log alone (I3). Named once,
# here, so a determinism test cannot silently drift from what actually gets
# truncated: tests/test_replay_determinism.py snapshots exactly this list.
PROJECTION_TABLES = BELIEF_TABLES + [
    "entities", "user_knowledge", "justifications", "corrections", "nogoods",
    "contradictions", "supersede_candidates", "entity_centroids",
    "identity_candidates", "observed_vectors", "session_index", "memory_vectors",
    "projection_vectors", "query_proxy_vectors", "rerank_hints",
]
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


def _quote_ident(name) -> str:
    """Double-quote a SQL identifier. Only ever applied to a name that has just
    been confirmed against the live schema (§A9 `_checked_ident`) — quoting is
    the last step of splicing a known-good name, never a substitute for the
    check."""
    return '"%s"' % str(name).replace('"', '""')


def _iso_in(seconds: float) -> str:
    """now_iso() shifted forward — identical fixed-width format, so a stored
    timestamp and a live one compare with plain string ordering (job run_after)."""
    t = (datetime.datetime.now(datetime.timezone.utc)
         + datetime.timedelta(seconds=max(0.0, float(seconds))))
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


class StoreClosed(RuntimeError):
    """A closed `MemoryStore` was used again (A11b).

    Deliberately NOT a silent reopen: a store is closed because its owner
    decided the database's lifetime was over, and a call arriving afterwards is
    a lifetime bug in the caller. Reopening would hide it and re-create the WAL
    sidecars the close just released."""


#: Files SQLite can leave beside a database in WAL mode. Apple's SQLite build
#: (3.54.0 ...apl) does NOT unlink `-shm` when the last connection closes, and
#: leaves a zero-length `-wal` behind in some paths, so `close()` removes the
#: residue itself once it has proven no connection is left (see `close()`).
DB_SIDECARS = ("-wal", "-shm")
def _iso_ago(seconds: float) -> str:
    """Mirror of `_iso_in` pointing BACKWARD — the lease/retention cutoffs
    (§A7). Same fixed-width format for the same reason: every comparison
    against a stored timestamp stays a plain lexicographic one."""
    t = (datetime.datetime.now(datetime.timezone.utc)
         - datetime.timedelta(seconds=max(0.0, float(seconds))))
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


# -- queue fairness (§A7) ----------------------------------------------------
#
# WHY A CLASS MAP AND NOT A PRIORITY COLUMN: a strict priority order is still a
# starvation order — it just moves which queue starves. The live failure was the
# reverse of the naive fix: 105k `embed` jobs enqueued by one heal run sat ahead
# of every later `extract` in a strict-FIFO claim, so the premise's own write
# path (a new turn becoming facts) stopped for as long as the backlog took
# (measured: extract had 245 rows stuck 'running' and 147 failed while embed
# flooded the queue). Weighted round-robin over CLASSES fixes both directions:
# no class can be locked out by another class's backlog, whichever way the flood
# runs.
#
# Fairness is a property of THE QUEUE, not of callers: a caller (a turn tick, a
# maintenance scheduler, a CLI drain) asks for N jobs and the queue decides the
# mix. Adding a new producer therefore cannot change the mix — only its own
# class's share of it.
#
# CLASSES
#   write_path  — a new turn becoming memory, and the per-write follow-ups it
#                 enqueues. This is the premise's write path; it must ALWAYS
#                 make progress, so it holds the largest share and is served
#                 first within each round.
#   embed       — deferred vector writes (§24.4). Bulk by nature: one heal, one
#                 migration or one degraded-mode recovery enqueues them by the
#                 tens of thousands.
#   maintenance — sweeps and periodic repair. Bulk by nature for the same
#                 reason, and the class a scheduler (A3) enqueues into.
TASK_CLASSES = ("write_path", "embed", "maintenance")

# Every task value in _CURATION_JOBS_DDL's CHECK appears here exactly once;
# tests/test_queue_fairness.py asserts that, so the map cannot drift from the
# CHECK the way the migration's `missing` list did twice.
#
# v5.7.0 integration: `route`, `criticality` and `contradiction` are GONE from
# this map because A13 removed them from CURATION_TASKS (rung 17). A7 wrote the
# map against the wider CHECK, so this is exactly the drift the assertion above
# exists to catch -- it auto-merged without a conflict marker and failed
# test_queue_fairness's `assertEqual(allowed, set(TASK_CLASS))`. Note the CLASS
# change it carries: `contradiction` work was classed `write_path`, and it is
# re-tasked by the migration to `consistency`, which is `maintenance`. That is
# correct rather than a demotion -- the handler `contradiction` would have run
# was byte-for-byte health.consistency_sweep(), which is maintenance by any
# reading; it was only on the write path because it had been misfiled.
TASK_CLASS = {
    "extract": "write_path",
    "canonicalize": "write_path",
    "consolidate": "write_path",
    "identity": "write_path",
    "derive": "write_path",
    "verify": "write_path",
    "reextract": "write_path",
    "journal_ingest": "write_path",
    "session_summarize": "write_path",
    "digest": "write_path",
    "embed": "embed",
    "decay": "maintenance",
    "consistency": "maintenance",
    "health": "maintenance",
    "federate_sweep": "maintenance",
    "backfill_sweep": "maintenance",
}
# An unmapped task is treated as maintenance, never as write_path: a task this
# build does not know about is by definition not part of the write path it does
# know about, and mis-promoting it would hand an unknown producer the share that
# exists to keep extraction alive. It still gets a share — unknown is not
# starved, only not privileged.
_UNKNOWN_TASK_CLASS = "maintenance"


def task_class(task: str) -> str:
    return TASK_CLASS.get(task or "", _UNKNOWN_TASK_CLASS)


def tasks_in_class(cls: str) -> list:
    """Task values belonging to `cls`, sorted — the claim filter for that class."""
    return sorted(t for t, c in TASK_CLASS.items() if c == cls)


def _largest_remainder(total: int, weights: dict) -> dict:
    """Apportion `total` whole units across `weights` (all >= 0, sum > 0) so the
    result sums to exactly `total`. Ties break on class name, so the split is
    deterministic across processes — the PYTHONHASHSEED lesson: nothing here may
    depend on dict or set iteration order."""
    keys = sorted(weights)
    wsum = float(sum(weights[k] for k in keys))
    if total <= 0 or wsum <= 0:
        return {k: 0 for k in keys}
    exact = {k: weights[k] / wsum * total for k in keys}
    out = {k: int(exact[k]) for k in keys}
    left = total - sum(out.values())
    for k in sorted(keys, key=lambda k: (-(exact[k] - int(exact[k])), k)):
        if left <= 0:
            break
        out[k] += 1
        left -= 1
    return out


def drain_quotas(budget: int, shares: dict) -> dict:
    """Split a per-turn budget across TASK_CLASSES by share, exactly.

    Three properties, all load-bearing:

    * the quotas SUM to the budget (largest-remainder apportionment), so three
      independent roundings cannot silently shrink a turn's drain;
    * the split IS the declared share wherever whole numbers allow it — the
      default 0.5/0.3/0.2 over 16 is 8/5/3, not "about half"; and
    * a class whose share is positive but too small to round up to a whole job
      is lent ONE job from the largest class rather than getting zero. That
      floor is the anti-starvation guarantee: a class with pending work is
      served EVERY turn, so no other class's backlog — however large — can push
      its completion out past a bounded number of turns.

    A config with no positive share at all is a degenerate one, not an
    instruction to stop working: it falls back to an even split rather than
    draining nothing (which would stall the write path outright)."""
    budget = max(0, int(budget))
    vals = {}
    for c in TASK_CLASSES:
        try:
            v = float(shares.get(c, 0.0)) if shares else 0.0
        except (TypeError, ValueError):
            v = 0.0
        vals[c] = v if v > 0 else 0.0
    if not any(vals.values()):
        vals = {c: 1.0 for c in TASK_CLASSES}
    if budget <= 0:
        return {c: 0 for c in TASK_CLASSES}
    quotas = _largest_remainder(budget, vals)
    # Floor pass: lend one job to each starved-but-positive class, taking it
    # from the largest quota that can spare it. Deterministic (ties break on
    # class name) and never takes a donor below 1, so lending cannot itself
    # starve the donor.
    for c in sorted(TASK_CLASSES):
        if vals[c] <= 0 or quotas[c] > 0:
            continue
        donor = max(sorted(TASK_CLASSES), key=lambda k: quotas[k])
        if quotas[donor] > 1:
            quotas[donor] -= 1
            quotas[c] = 1
    return quotas


class MemoryStore:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self.reducer = None  # set by ChronicleCore; enables inline reduce on append (I7)
        self.vector_index = None  # set by ChronicleCore; optional ANN index for fast KNN
        self._lock_waits = 0
        self._lock_acqs = 0
        # A11b: every connection this store hands out, keyed by the thread that
        # owns it. sqlite3 refuses cross-thread use INCLUDING close(), so the
        # registry is not enough on its own to close a worker's connection --
        # but it is what lets `close()` say exactly which threads still hold one
        # instead of leaving the sidecars behind in silence.
        self._conns = {}
        self._conns_lock = threading.Lock()
        self._closed = False
        self._init_db()

    # -- connection & transaction ------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        if self._closed:
            raise StoreClosed(
                "MemoryStore(%s) is closed; open a new MemoryStore instead of reusing this one"
                % self.db_path)
        if getattr(self._local, "conn", None) is None:
            conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_MS / 1000.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
            with self._conns_lock:
                self._conns[threading.get_ident()] = conn
        return self._local.conn

    # -- close (A11b) -------------------------------------------------------
    #
    # THE LEAK THIS ENDS. Connections are thread-local and there was no close()
    # at all, so every MemoryStore ever constructed held its SQLite handle until
    # the process exited and left `<db>-wal` / `<db>-shm` on disk. In a test run
    # that was ~100 stray files; on a host it is a database that is never
    # checkpointed down and a file handle per store per thread.
    #
    # Ownership: whoever constructed the store closes it. ChronicleCore.close()
    # does it for a core; MemoryStore is also a context manager, so a script or
    # a test can write `with MemoryStore(path) as store:`.

    @property
    def closed(self) -> bool:
        return self._closed

    def close_thread_connection(self) -> bool:
        """Close THIS thread's connection, if it has one. True if one was closed.

        A worker thread calls this on its way out. sqlite3 pins a connection to
        its creating thread — `close()` from any other thread raises
        ProgrammingError — so a thread that opened a connection is the only one
        that can give it back before interpreter shutdown."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return False
        self._local.conn = None
        with self._conns_lock:
            self._conns.pop(threading.get_ident(), None)
        try:
            conn.close()
        except Exception as e:  # pragma: no cover - a dead conn is already gone
            logger.debug("closing %s connection: %s", self.db_path, e)
        return True

    def close(self) -> dict:
        """Close the store and release its WAL sidecars. Idempotent.

        Returns a report: ``{"closed": n, "foreign": [thread_ident, ...],
        "sidecars_released": bool, "journal_mode": str}``. `foreign` names the
        threads whose connections could not be closed from here — they must call
        `close_thread_connection()` themselves — and is empty in the normal
        single-threaded case.

        Releasing the sidecars is done explicitly rather than trusted to SQLite:
        this platform's SQLite (3.54.0 Apple build) keeps `-shm` after the last
        connection closes. The sequence is checkpoint(TRUNCATE) → `PRAGMA
        journal_mode=DELETE` → close → unlink the residue. Step 2 is also the
        SAFETY INTERLOCK: switching out of WAL needs an exclusive lock, so it
        answers 'wal' instead of 'delete' whenever any other connection (this
        process or another) still has the database open, and the unlink is
        skipped in exactly that case. No data is at risk either way — the
        checkpoint has already folded the WAL into the main database."""
        if self._closed:
            return {"closed": 0, "foreign": [], "sidecars_released": False,
                    "journal_mode": "", "already_closed": True}
        mode = ""
        own = getattr(self._local, "conn", None)
        if own is not None:
            try:
                own.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                row = own.execute("PRAGMA journal_mode=DELETE").fetchone()
                mode = (row[0] if row else "") or ""
            except Exception as e:
                logger.debug("checkpointing %s before close: %s", self.db_path, e)
        # Mark closed BEFORE dropping connections so a concurrent caller gets
        # StoreClosed rather than silently opening a fresh connection into the
        # window between the checkpoint and the unlink.
        self._closed = True
        with self._conns_lock:
            registry = dict(self._conns)
            self._conns.clear()
        self._local.conn = None
        n, foreign = 0, []
        for ident, conn in registry.items():
            try:
                conn.close()
                n += 1
            except sqlite3.ProgrammingError:
                foreign.append(ident)
            except Exception as e:  # pragma: no cover
                logger.debug("closing %s connection: %s", self.db_path, e)
        released = False
        if not foreign and mode.lower() == "delete":
            released = self._unlink_sidecars()
        elif foreign:
            logger.warning(
                "Chronicle store: %s closed, but %d connection(s) belong to still-live thread(s) %s "
                "and can only be closed there (sqlite3 pins a connection to its creating thread). "
                "The WAL sidecars stay until they call close_thread_connection().",
                self.db_path, len(foreign), foreign)
        return {"closed": n, "foreign": foreign, "sidecars_released": released,
                "journal_mode": mode, "already_closed": False}

    def _unlink_sidecars(self) -> bool:
        """Remove residual `-wal`/`-shm`. Only ever called once journal_mode has
        already been switched to DELETE, which proves nothing else holds the db."""
        import os
        ok = True
        for suffix in DB_SIDECARS:
            path = self.db_path + suffix
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError as e:  # pragma: no cover - permissions / read-only fs
                ok = False
                logger.debug("could not remove %s: %s", path, e)
        return ok

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

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
        # This probe is generated from CURATION_TASKS rather than restated, so
        # the bug it exists to prevent cannot recur by omission: an earlier
        # hand-maintained list here silently missed 'digest' (schema_version 3)
        # and 'federate_sweep' (schema_version 4), and each miss left existing
        # stores enqueuing a task their CHECK rejected -- an IntegrityError
        # raised INSIDE append_event's durable-capture transaction (I12), which
        # aborts the enclosing extract job. One rebuild covers every value.
        missing = [t for t in CURATION_TASKS if row and f"'{t}'" not in (row[0] or "")]
        # …and the inverse (schema_version 13, ladder-10 A13): a store whose
        # CHECK still admits a RETIRED task. CREATE TABLE IF NOT EXISTS cannot
        # narrow an existing CHECK, so without this probe an upgraded store keeps
        # accepting enqueues of 'route'/'criticality' (which nothing can run) for
        # the rest of its life while a fresh install rejects them -- the two
        # shapes drift apart, which is exactly what the ladder exists to prevent.
        retired = [t for t in RETIRED_CURATION_TASKS if row and f"'{t}'" in (row[0] or "")]
        if retired:
            # ORDERING IS LOAD-BEARING: the depends_on index must exist BEFORE
            # the retirement deletes, not after. _SCHEMA splices _JOBS_INDEX_DDLS
            # and _init_db executescripts it before calling us, so on today's code
            # path the index is already there — but that is an accident of where
            # the splice lives, and the whole cost of rung 17 turns on it (12.57 s
            # -> 0.06 s on a 105k-row store; see _JOBS_INDEX_DDLS). Stating it
            # here, idempotently, means a later refactor of _SCHEMA cannot
            # silently reintroduce the stall. Creating it at rung 18 (the loop at
            # the end of _migrate) would be too late: the deletes are paid for
            # first. The index build itself costs ~0.03 s.
            conn.execute(_JOBS_DEPENDS_ON_INDEX_DDL)
            # Rows already queued under a retired name have to be dealt with
            # BEFORE the rebuild: the copy INSERT is checked against the NEW,
            # narrower CHECK and would abort the whole migration on the first
            # such row. They are never left pending — see the method.
            self._retire_removed_task_rows(conn, retired)
        if missing or retired:
            if missing:
                logger.info("schema migration: curation_jobs task CHECK += %s", ", ".join(missing))
            if retired:
                logger.info("schema migration: curation_jobs task CHECK -= %s", ", ".join(retired))
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
        # schema_version 12 (A0fix D3): procedures + body. Deliberately added
        # WITHOUT a DEFAULT, so existing rows get NULL and stay distinguishable
        # from a row whose body really was empty. Backfilling them with
        # `procedures.name` is exactly the corruption this fixes -- the name is a
        # 40-char truncation of the text that was actually vectorised -- so they
        # are left NULL and reducer.belief_vector_text() reports them as
        # unrecoverable-from-the-projection instead (it then tries the source
        # event, and refuses loudly if that is gone too).
        if not _has_col(conn, "procedures", "body"):
            logger.info("schema migration: procedures + body (vectorised text of a procedure)")
            conn.execute("ALTER TABLE procedures ADD COLUMN body TEXT")
        # schema_version 13 (A0e): session_index + model. Same probe-then-ALTER
        # shape as every column step above, so it is idempotent and
        # order-independent whatever number the integrator ends up renumbering
        # it to. Deliberately NO DEFAULT: unlike rerank_hints.owner (whose table
        # is provably empty at defaults, so 'default' backfills nothing real),
        # session_index is POPULATED on every live store and an existing row's
        # true embedder is unknowable after the fact. NULL IS that unknown, and
        # _classify_tag reads NULL as stale, so the heal re-embeds those rows
        # from their own `summary` instead of trusting a fabricated tag. See the
        # SCHEMA_VERSION ladder comment for the full legacy-NULL rule.
        if not _has_col(conn, "session_index", "model"):
            logger.info("schema migration: session_index + model (vector identity, A0e)")
            conn.execute("ALTER TABLE session_index ADD COLUMN model TEXT")
        # schema_version 14 (ladder-10 A1; claimed 12 in A1's own tree,
        # renumbered by the v5.7.0 integration): rerank_hints + principal. Same
        # probe-then-ALTER shape as `owner` above and for the same reason --
        # no PK change, so a store on ANY prior version converges with one ADD
        # COLUMN. '' means "unattributed": the read path treats it as
        # un-sandboxed, which is exactly how every row behaved before this
        # column existed, and §H2's inertness invariant means a default store
        # has no rows here to mis-attribute.
        if not _has_col(conn, "rerank_hints", "principal"):
            logger.info("schema migration: rerank_hints + principal (sandbox-scoped rerank hints)")
            conn.execute("ALTER TABLE rerank_hints ADD COLUMN principal TEXT NOT NULL DEFAULT ''")
        # schema_version 15 (ladder-10 A1b; claimed 13 in A1b's own tree,
        # renumbered by the v5.7.0 integration): goals + reflections get the
        # `owner`/`read_acl` pair every other belief table already carries, so
        # access.can_read has something to decide on for the two surfaces A1
        # could not close (active_goals / recall_similar_situations ->
        # plan_context). Same probe-then-ALTER shape as every column step
        # above; no PK change, so a store on ANY prior version converges.
        #
        # NO DEFAULT, unlike rerank_hints.owner above, and that is the point:
        # a NULL here is the durable, honest record that the row predates
        # attribution. Backfilling it to any live principal would be an
        # invention, and backfilling it to '' would make a legacy row
        # indistinguishable from an attributed one. The read gate resolves
        # NULL to the pre-topology "default" identity instead, which fails
        # closed under any configured topology (reasoning._readable_row).
        for _t in ("goals", "reflections"):
            for _c in ("owner", "read_acl"):
                if not _has_col(conn, _t, _c):
                    logger.info("schema migration: %s + %s (owner-scoped %s)", _t, _c, _t)
                    conn.execute("ALTER TABLE %s ADD COLUMN %s TEXT" % (_t, _c))
        # schema_version 16 (ladder-10 A3; claimed 12 in A3's own tree, which
        # A7 had reserved for it, renumbered by the v5.7.0 integration): the
        # maintenance scheduler's
        # watermarks. Same probe-then-apply shape as every step above, from the
        # SAME _MAINTENANCE_DDL that _SCHEMA splices, so a fresh install and a
        # migrated store cannot disagree about the shape. A store that has never
        # met the scheduler simply gets an empty table.
        if not _has_table(conn, "maintenance_runs"):
            logger.info("schema migration: maintenance_runs (maintenance scheduler watermarks)")
            conn.executescript(_MAINTENANCE_DDL)
        # schema_version 18 (§A7; claimed 13 in A7's own tree, renumbered by the
        # v5.7.0 integration — see the ladder comment at the top of this file).
        # INDEX-ONLY: no column, no table, no data rewrite, so a store at ANY
        # prior version converges by creating six indexes and nothing about its
        # rows changes. Unconditional and idempotent for the same reason
        # idx_rerank_hints_owner above is: by this point the tables exist either
        # way, and CREATE INDEX IF NOT EXISTS on an index that is already there
        # is two catalog reads.
        #
        # THIS LOOP STAYS LAST in _migrate, immediately before the stamp. A13's
        # curation_jobs rebuild (rung 17) replays the indexes it finds in
        # sqlite_master onto the rebuilt table, so running the rebuild first and
        # this loop after means the indexes are built once rather than built,
        # dropped and replayed. Both orders are CORRECT (every DDL here is
        # IF NOT EXISTS, and the rebuild reads sqlite_master rather than a
        # hardcoded list); only one of them is cheap.
        for ddl in _JOBS_INDEX_DDLS + _VECTOR_CENSUS_INDEX_DDLS:
            conn.execute(ddl)
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))

    def _retire_removed_task_rows(self, conn, retired):
        """Resolve every curation_jobs row whose task is leaving the CHECK (A13).

        Two outcomes, and the difference between them is whether the queued work
        still has a truthful name:

        * `contradiction` -> `consistency`. _task_contradiction's entire body was
          a call to health.consistency_sweep() — the same call _task_consistency
          makes. A pending row is therefore real, runnable work, and a done/failed
          row is a true record of a consistency sweep. Both are RE-TASKED, not
          dropped. Duplicates are collapsed first so the rename cannot violate
          enqueue_curation's (task, payload) dedupe invariant among pending/
          running rows: two byte-identical sweeps produce one answer twice.

        * `route`, `criticality` -> deleted. No build ever had a _task_route or
          _task_criticality, so these rows are not work that is waiting; they are
          work that could never happen. Leaving them pending is the defect A13
          exists to remove (a queue depth that never drains), and marking them
          'failed' is not available — the row cannot keep a task name the new
          CHECK rejects. So they are FAILED EXPLICITLY the only way a vanishing
          row can be: counted, logged at WARNING with their ids, and recorded in
          meta under `curation_tasks_retired` (schema_version, timestamp, per-task
          counts, and up to 200 ids) so an operator reading the store afterwards
          finds out what happened rather than noticing a queue got shorter.

        Runs INSIDE _migrate's transaction and BEFORE _rebuild_curation_jobs,
        which commits it: the rebuild's copy INSERT is checked against the new,
        narrower CHECK, so a surviving retired row would abort the migration.

        THE DEPENDENCY GUARD (v5.7.0 review §7). Both deletes below are deletes
        from the PARENT side of `depends_on INTEGER REFERENCES curation_jobs(id)`,
        and that foreign key is ENFORCED here: __init__ sets PRAGMA
        foreign_keys=ON, and the only place it is turned off is inside
        _rebuild_curation_jobs, which runs AFTER us. So an inbound edge pointing
        AT a doomed row raises `sqlite3.IntegrityError: FOREIGN KEY constraint
        failed` inside _migrate's transaction, which propagates out of
        MemoryStore.__init__ — and because the migration is re-attempted on every
        open and fails identically every time, the store is not degraded, it is
        UNOPENABLE, permanently, until someone hand-edits it. This is the same
        hazard prune_curation_jobs already guards; rung 17 did not.

        Each delete clears its inbound edges first, and the two make DIFFERENT
        choices because the doomed rows mean different things:

        * The COLLAPSE delete drops a duplicate whose work survives under another
          id. A dependent that was waiting for that sweep should keep waiting for
          the identical one, so its edge is RE-POINTED at the surviving twin
          (lowest id of the live consistency rows with the same payload). Nulling
          here would silently let the dependent run early.
        * The RETIRED-NAME delete drops work no build could ever run. There is no
          heir, so the edge is NULLED. claim_curation_job treats `depends_on IS
          NULL` as ready, which is the correct outcome and the point of A13:
          leaving the child pointed at a job that can never reach 'done' is the
          never-drains queue depth this rung exists to remove. (Retiring the
          child too was considered and rejected — the child is a live, runnable
          job of a DIFFERENT task; deleting it would destroy real work to tidy up
          a dangling pointer, and would cascade.)

        Neither branch loses information silently: both log a count, and the
        retired-name branch's meta record already names every dropped id."""
        for old_task in retired:
            new_task = RETIRED_TASK_ALIASES.get(old_task)
            if not new_task:
                continue
            # Collapse a rename that would duplicate a live (task, payload) pair.
            # Take the doomed ids and their heirs FIRST, under exactly the
            # predicate the DELETE below uses, so the edge repair and the delete
            # cannot disagree about which rows are doomed.
            doomed = conn.execute(
                "SELECT j.id AS id, (SELECT MIN(c2.id) FROM curation_jobs c2 "
                "WHERE c2.task=? AND c2.status IN ('pending','running') "
                "AND IFNULL(c2.payload,'') = IFNULL(j.payload,'')) AS heir "
                "FROM curation_jobs j WHERE j.task=? AND j.status IN ('pending','running') "
                "AND EXISTS (SELECT 1 FROM curation_jobs c2 WHERE c2.task=? "
                "AND c2.status IN ('pending','running') "
                "AND IFNULL(c2.payload,'') = IFNULL(j.payload,''))",
                (new_task, old_task, new_task)).fetchall()
            moved = 0
            for r in doomed:
                # heir is non-NULL by the EXISTS above; the fallback is defensive
                # only, and NULL is still safe (the dependent becomes ready).
                #
                # The CASE is not decoration. If the row waiting on the doomed
                # duplicate IS the heir -- the surviving sweep was itself queued
                # behind its own twin -- a plain re-point would make it depend on
                # ITSELF, and claim_curation_job resolves `depends_on IN (SELECT
                # id ... WHERE status='done')`, which a pending row's own id can
                # never satisfy. That is the permanently-stuck state this whole
                # guard exists to remove, arriving through a different door and
                # this time with no IntegrityError to announce it. A self-edge is
                # also vacuous on its face, so it becomes NULL.
                cur = conn.execute(
                    "UPDATE curation_jobs SET depends_on = "
                    "CASE WHEN id=? THEN NULL ELSE ? END WHERE depends_on=?",
                    (r["heir"], r["heir"], r["id"]))
                moved += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            if moved:
                logger.info("schema migration: re-pointed %d depends_on edge(s) from "
                            "collapsed '%s' duplicate(s) to the surviving '%s' row",
                            moved, old_task, new_task)
            conn.execute(
                "DELETE FROM curation_jobs WHERE task=? AND status IN ('pending','running') "
                "AND EXISTS (SELECT 1 FROM curation_jobs c2 WHERE c2.task=? "
                "AND c2.status IN ('pending','running') "
                "AND IFNULL(c2.payload,'') = IFNULL(curation_jobs.payload,''))",
                (old_task, new_task))
            n = conn.execute("UPDATE curation_jobs SET task=? WHERE task=?",
                             (new_task, old_task)).rowcount
            if n:
                logger.info("schema migration: re-tasked %d '%s' job(s) as '%s' "
                            "(same handler, one name)", n, old_task, new_task)

        dead = [t for t in retired if t not in RETIRED_TASK_ALIASES]
        if not dead:
            return
        marks = ",".join("?" * len(dead))
        rows = conn.execute(
            "SELECT id, task, status FROM curation_jobs WHERE task IN (%s) "
            "ORDER BY id" % marks, tuple(dead)).fetchall()
        if not rows:
            return
        counts = {}
        for r in rows:
            counts[r["task"]] = counts.get(r["task"], 0) + 1
        ids = [r["id"] for r in rows]
        logger.warning(
            "schema migration: dropping %d curation job(s) whose task has NO HANDLER "
            "in any build (%s); they could never have run. job ids: %s",
            len(rows), ", ".join("%s=%d" % kv for kv in sorted(counts.items())),
            ",".join(str(i) for i in ids[:200]))
        record = {"schema_version": SCHEMA_VERSION, "retired_at": now_iso(),
                  "reason": "no handler exists; task removed from curation_jobs CHECK",
                  "counts": counts, "job_ids": ids[:200], "job_ids_truncated": len(ids) > 200}
        conn.execute(
            "INSERT INTO meta(key,value) VALUES('curation_tasks_retired',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(record, sort_keys=True),))
        # Clear inbound edges before the delete — see THE DEPENDENCY GUARD above.
        # Expressed as a subquery rather than an `IN (<ids>)` list so the
        # statement carries len(dead) parameters however many rows are doomed
        # (SQLITE_MAX_VARIABLE_NUMBER is 999 on older builds; this set can exceed
        # that). idx_jobs_depends_on, created before this method was called,
        # makes it a lookup rather than a scan.
        cur = conn.execute(
            "UPDATE curation_jobs SET depends_on=NULL WHERE depends_on IN "
            "(SELECT id FROM curation_jobs WHERE task IN (%s))" % marks, tuple(dead))
        orphaned = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        if orphaned:
            logger.warning(
                "schema migration: cleared %d depends_on edge(s) that pointed at a "
                "dropped job; those jobs could never have reached 'done', so the "
                "dependents were blocked forever and are now claimable", orphaned)
        conn.execute("DELETE FROM curation_jobs WHERE task IN (%s)" % marks, tuple(dead))

    def _curation_jobs_rebuild_ddl(self, conn):
        """(new-table DDL, comma-joined copy list) for the rebuild below.

        Both are derived from the LIVE table via PRAGMA table_info, NOT from
        `_CURATION_JOBS_DDL`'s column list, and that is the whole point of this
        method. A rebuild is how this codebase changes a CHECK, and more than one
        migration rung wants one: this rung narrows the task CHECK, and another
        adds lease/attempt COLUMNS to the same table. Whichever runs second sees
        a table this build's DDL does not describe. If it recreated the table
        from the hardcoded column list, every install that upgrades through both
        rungs would silently lose the other rung's columns and their data — the
        table would still be there, still queryable, just missing state, which is
        the kind of loss that surfaces days later as jobs that never expire.

        So: the canonical columns come from `_CURATION_JOBS_DDL` (they carry this
        build's constraints, including the narrowed CHECK), and any column the
        live table has that the canonical list does not is re-declared from its
        live type/NOT NULL/DEFAULT and appended. The copy list is exactly the
        live columns, each of which is therefore present in the new table.
        The reverse case — a live table MISSING a canonical column, e.g. a
        schema_version 1 store without `run_after` — is already handled by the
        _has_col ALTERs that run before this, and would be safe regardless: the
        new table has the column and the copy simply does not name it.
        """
        canonical = set(_JOB_COLS.split(","))
        live = conn.execute("PRAGMA table_info(curation_jobs)").fetchall()
        ddl = _CURATION_JOBS_DDL % "curation_jobs_new"
        extras = []
        for col in live:
            if col["name"] in canonical:
                continue
            decl = '"%s" %s' % (col["name"].replace('"', '""'), col["type"] or "")
            if col["notnull"]:
                decl += " NOT NULL"
            if col["dflt_value"] is not None:
                decl += " DEFAULT %s" % col["dflt_value"]
            extras.append(decl.strip())
        if extras:
            body = ddl.rstrip().rstrip(";").rstrip()
            if not body.endswith(")"):                  # never seen; refuse to guess
                raise RuntimeError("curation_jobs DDL is not in the expected form")
            ddl = body[:-1] + ", " + ", ".join(extras) + ");"
            logger.info("schema migration: curation_jobs rebuild preserving %d "
                        "column(s) this build's DDL does not declare: %s",
                        len(extras), ", ".join(c["name"] for c in live
                                               if c["name"] not in canonical))
        cols = ",".join('"%s"' % c["name"].replace('"', '""') for c in live)
        return ddl, cols

    def _rebuild_curation_jobs(self, conn):
        """Recreate curation_jobs so its task CHECK matches this build (SQLite
        cannot ALTER a CHECK): create → copy → drop → rename → reindex, all in
        ONE explicit transaction, per SQLite's documented table-rebuild procedure.

        foreign_keys is toggled OUTSIDE the transaction (the pragma is a silent
        no-op inside one) because curation_jobs.depends_on references the very
        table being dropped. executescript() is avoided for the same reason — it
        commits before running.

        DROP TABLE also drops the table's indexes and triggers, so anything on
        curation_jobs that this build does not declare in _JOBS_INDEX_DDLS is
        captured from sqlite_master first and replayed after the rename — same
        reason the column list is taken live: a concurrent rung's index must not
        disappear because this rung rebuilt the table."""
        ddl, cols = self._curation_jobs_rebuild_ddl(conn)
        # Objects DROP TABLE will take with it. sql IS NULL filters SQLite's own
        # auto-indexes, which it recreates itself and refuses to be given.
        carried = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name='curation_jobs' "
            "AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        conn.commit()                                   # no implicit txn open, so the pragma bites
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.execute("BEGIN")
            conn.execute(ddl)
            conn.execute(f"INSERT INTO curation_jobs_new({cols}) "
                         f"SELECT {cols} FROM curation_jobs")
            conn.execute("DROP TABLE curation_jobs")
            conn.execute("ALTER TABLE curation_jobs_new RENAME TO curation_jobs")
            for index_ddl in _JOBS_INDEX_DDLS:
                conn.execute(index_ddl)
            present = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE tbl_name='curation_jobs' "
                "AND type IN ('index','trigger')").fetchall()}
            for obj in carried:
                if obj["name"] not in present:
                    conn.execute(obj["sql"])
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

    # -- sweep state (§A9) --------------------------------------------------
    #
    # One row per sweep in `meta`, holding BOTH halves of the fix: the cursor
    # that makes the next run resume where this one stopped, and the last run's
    # processed/remaining/bounded, which is what makes a permanently-partial
    # sweep visible instead of silent. They live together on purpose — a cursor
    # with no reported `remaining` is exactly the state that hid this defect
    # (`get_sessions_needing_index_backfill` had a watermark and still reported
    # nothing about how far behind it was). No new table: `meta` is where
    # `_sweep_local_db`'s federation cursors already live.
    SWEEP_META_PREFIX = "sweep:"

    def get_sweep_state(self, name: str) -> dict:
        raw = self.get_meta(self.SWEEP_META_PREFIX + name, "")
        if not raw:
            return {}
        try:
            state = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def save_sweep_state(self, name: str, state: dict):
        self.set_meta(self.SWEEP_META_PREFIX + name, json.dumps(state, sort_keys=True))

    def list_sweep_states(self) -> dict:
        """Every sweep's last-run report, keyed by sweep name — the health
        snapshot's window onto work that is still outstanding."""
        out = {}
        n = len(self.SWEEP_META_PREFIX)
        for row in self._conn().execute(
                "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
                (self.SWEEP_META_PREFIX + "%",)).fetchall():
            try:
                out[row["key"][n:]] = json.loads(row["value"])
            except (TypeError, ValueError):
                continue
        return out

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

    def add_observed_vector(self, event_id: str, embedding: bytes, model: str, owner: str,
                            created_at: str = ""):
        """`created_at` is the observed EVENT's own timestamp when the reducer
        writes this row (Ladder 10 A4): observed_vectors is in
        `truncate_projection`'s list, so a wall-clock stamp here made a replay
        of the same log produce a different byte in every row. An operational
        writer outside the fold (the degraded-embedder retry queue in
        curation.py) may still omit it and get wall clock; a rebuild then
        replaces its rows with the event-derived ones."""
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO observed_vectors(event_id,embedding,model,owner,created_at) "
                         "VALUES(?,?,?,?,?)", (event_id, embedding, model, owner,
                                               created_at or now_iso()))
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

    def add_memory_vector(self, belief_id: str, kind: str, embedding: bytes, model: str,
                          created_at: str = ""):
        """`created_at` is the asserting EVENT's timestamp on the reducer path
        — same reason as add_observed_vector (Ladder 10 A4)."""
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO memory_vectors(belief_id,kind,embedding,model,created_at) "
                         "VALUES(?,?,?,?,?)", (belief_id, kind, embedding, model,
                                               created_at or now_iso()))

    def has_observed_vector(self, event_id: str) -> bool:
        return self._conn().execute("SELECT 1 FROM observed_vectors WHERE event_id=?",
                                    (event_id,)).fetchone() is not None

    def get_observed_vector_model(self, event_id: str) -> Optional[str]:
        """Get the model name of an existing observed vector, or None if not found."""
        row = self._conn().execute("SELECT model FROM observed_vectors WHERE event_id=?",
                                   (event_id,)).fetchone()
        return row["model"] if row else None

    def get_observed_vector_len(self, event_id: str) -> Optional[int]:
        """Byte length of an existing observed vector's blob, or None (A0b).

        The companion to get_observed_vector_model: a tag alone cannot say
        whether a row is healthy, because a WRONG-DIMENSION blob can carry a
        perfectly current tag (that is exactly what the live nemotron rows
        did). Every "is this vector already fine?" check needs both."""
        row = self._conn().execute("SELECT length(embedding) AS n FROM observed_vectors WHERE event_id=?",
                                   (event_id,)).fetchone()
        return row["n"] if row else None

    def has_memory_vector(self, belief_id: str, kind: str) -> bool:
        return self._conn().execute("SELECT 1 FROM memory_vectors WHERE belief_id=? AND kind=?",
                                    (belief_id, kind)).fetchone() is not None

    def get_memory_vector_model(self, belief_id: str, kind: str) -> Optional[str]:
        """Get the model name of an existing memory vector, or None if not found."""
        row = self._conn().execute("SELECT model FROM memory_vectors WHERE belief_id=? AND kind=?",
                                   (belief_id, kind)).fetchone()
        return row["model"] if row else None

    def get_memory_vector_len(self, belief_id: str, kind: str) -> Optional[int]:
        """Byte length of an existing memory vector's blob, or None (A0b)."""
        row = self._conn().execute(
            "SELECT length(embedding) AS n FROM memory_vectors WHERE belief_id=? AND kind=?",
            (belief_id, kind)).fetchone()
        return row["n"] if row else None

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
                               embedding: bytes, model: str, created_at: str = ""):
        """`created_at` is the parent belief's event timestamp on the reducer
        path — same reason as add_observed_vector (Ladder 10 A4)."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO query_proxy_vectors"
                "(belief_id,proxy_idx,kind,question,embedding,model,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (belief_id, proxy_idx, kind, question, embedding, model,
                 created_at or now_iso()))

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
        """WHOLE TABLE into Python (see iter_memory_vectors' note). The query
        path uses iter_query_proxy_vectors_paged instead (A5)."""
        return [dict(r) for r in self._conn().execute("SELECT * FROM query_proxy_vectors").fetchall()]

    def iter_query_proxy_vectors_paged(self, batch_size: int = 1000, width=None,
                                       kind: str = "", exclude_kind: str = ""):
        """Streaming half of `iter_query_proxy_vectors` (A5), rowid-ordered.

        `kind` / `exclude_kind` push retrieval's two disjoint readers into SQL:
        `_vector_proxies` wants every row EXCEPT kind='observed' (belief
        proxies), `_observed_proxies` wants exactly those (the §H2.4 excerpt
        tier). Both used to read the whole table and throw the other half away
        in Python -- one full copy of an 18k-row, ~150 MB blob table per query,
        twice per `search()`+`retrieve_raw` pair. Same `width` contract as
        iter_memory_vectors_paged: it restates batch_cosine's own hard-0.0 rule
        in SQL, so it cannot change a result.
        """
        where, params = "", []
        if kind:
            where, params = "kind = ?", [kind]
        elif exclude_kind:
            # COALESCE, not a bare `kind != ?`: `kind` has no NOT NULL constraint,
            # and SQL evaluates `NULL != 'observed'` as NULL -- i.e. NOT a match --
            # so a bare inequality silently DROPS every NULL-kind proxy row. The
            # Python filter this predicate replaced kept them (`None != "observed"`
            # is True there), so pushing the filter into SQL without this would be
            # a behaviour change hidden inside a performance fix.
            where, params = "COALESCE(kind, '') != ?", [exclude_kind]
        yield from self._paged_vector_scan("query_proxy_vectors", batch_size, width,
                                           where, params)

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
                         expires_at: str, max_entries: int = 200, owner: str = "default",
                         principal: str = ""):
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
                    "(query_key,belief_id,weight,tokens,query_text,created_at,expires_at,owner,principal) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (query_key, belief_id, float(weight), token_json, query_text or "", now,
                     expires_at, owner, principal or ""))
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

    def add_session_vector(self, session_id: str, summary: str, embedding: bytes, owner: str,
                           occurred_at: str, *, model):
        """Write a session summary + its vector (A0e).

        `model` is KEYWORD-ONLY AND REQUIRED. It is deliberately not defaulted,
        because every default is a lie in one direction or the other: defaulting
        to the active tag would stamp a canonical name onto bytes some other
        embedder may have produced, and defaulting to NULL would let a writer
        forget silently — which is exactly the state this column exists to end.
        A caller with no vector to record passes `model=None` explicitly
        (alongside `embedding=b""`), and that NULL then means what it says:
        unknown geometry, treat as stale.

        Callers stamp `embeddings.embedder_model_tag(embedder)`, never the bare
        `embedder.model` — the same single choke point every other vector table
        goes through, so one model under three names is one identity here too."""
        with self.transaction() as conn:
            conn.execute("INSERT OR REPLACE INTO "
                         "session_index(session_id,summary,embedding,owner,occurred_at,model) "
                         "VALUES(?,?,?,?,?,?)",
                         (session_id, summary, embedding, owner, occurred_at, model))

    def update_session_vector(self, session_id: str, embedding: bytes, model) -> bool:
        """Re-point an EXISTING session row at a new vector + tag (A0e).

        Every repair path (the health requeue -> curation._task_embed, and
        scripts/migrate_vectors.py) uses this rather than add_session_vector, so
        a re-embed can never rewrite the summary, the owner or occurred_at — the
        three columns it has no business touching and no authority to re-derive.
        Returns False when there is no such row: a re-embed never INVENTS a
        session."""
        with self.transaction() as conn:
            cur = conn.execute("UPDATE session_index SET embedding=?, model=? WHERE session_id=?",
                               (embedding, model, session_id))
            return cur.rowcount > 0

    def get_session_vector(self, session_id: str) -> Optional[dict]:
        row = self._conn().execute("SELECT * FROM session_index WHERE session_id=?",
                                   (session_id,)).fetchone()
        return dict(row) if row else None

    def get_session_vector_model(self, session_id: str) -> Optional[str]:
        """Model tag of an existing session vector, or None (A0e).

        None is genuinely ambiguous — no row at all, or a legacy row written
        before the column existed — and both meanings are handled identically by
        curation's `_already_current`: "not known to be current"."""
        row = self._conn().execute("SELECT model FROM session_index WHERE session_id=?",
                                   (session_id,)).fetchone()
        return row["model"] if row else None

    def get_session_vector_len(self, session_id: str) -> Optional[int]:
        """Byte length of an existing session vector's blob, or None (A0e)."""
        row = self._conn().execute(
            "SELECT length(embedding) AS n FROM session_index WHERE session_id=?",
            (session_id,)).fetchone()
        return row["n"] if row else None

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
        """WHOLE TABLE into Python. Kept for the write-side/diagnostic callers
        that genuinely want every row (tests, exercise scripts); the QUERY path
        must not use it -- see iter_memory_vectors_paged (A5)."""
        return [dict(r) for r in self._conn().execute("SELECT * FROM memory_vectors").fetchall()]

    def iter_memory_vectors_paged(self, batch_size: int = 1000, width: Optional[int] = None):
        """Stream `memory_vectors` in rowid order, `batch_size` rows at a time.

        A5. `iter_memory_vectors()` was the single largest runtime cost in the
        engine: `SELECT * FROM memory_vectors` into a list of dicts on EVERY
        `search()` -- measured at production size (108,581 rows, mixed 3072 B /
        8192 B blobs) as ~750 MB of resident Python per query, most of it
        scored 0.0 and discarded. This yields the same rows in the same order
        with O(batch_size) blobs alive at once.

        `width`, when given, is `len(query_vector) * 4` and becomes
        `length(embedding) = ?` in SQL. That predicate is EXACTLY the one
        `batch_cosine` already applies in Python -- a blob whose byte length is
        not `dims * 4` scores a hard 0.0 there (embeddings.py), and every
        consumer's floor is above 0.0 -- so filtering in SQL cannot change a
        result, it only stops SQLite from handing Python ~88% of production's
        vector bytes (the nemotron/nomic width split, A0) to be discarded. It
        is deliberately NOT `WHERE model = ?`: two model TAGS can name the same
        geometry (A0's whole subject), so a tag filter would change which rows
        score, and this is an optimisation, not a behaviour change.

        FORWARD HAZARD, stated because it is not obvious: A0 proposes to make
        a wrong-width blob LOUD on read instead of silently 0.0. This
        predicate would hide exactly those rows from the read path, so the
        refusal must be raised where the blob is WRITTEN (a choke point on
        put_vector) or by a scan that deliberately passes `width=None` --
        never by relying on a query-time scan to trip over them. A0 owns that
        call; A5 must not quietly foreclose it.

        Rowid order is the scan order `SELECT *` already returned, so a caller
        that reproduces the old tie-breaking (first-seen wins) sees byte-
        identical rankings.
        """
        yield from self._paged_vector_scan("memory_vectors", batch_size, width)

    def wrong_dim_vector_ids(self, table: str, id_col: str, width: int,
                             extra_where: str = "", extra_params: Sequence = (),
                             limit: Optional[int] = None) -> list:
        """(id, byte_length) for every row whose embedding is PRESENT but is not
        `width` bytes -- the exact COMPLEMENT of `_paged_vector_scan`'s filter.

        The read-path twin of health's `_mismatched_groups`, and it exists for
        the same reason A5's docstring above names as a FORWARD HAZARD: once a
        scan filters on `length(embedding) = ?`, the rows A0c has to report are
        the rows the scan can no longer see. Asking for them directly is the
        only way to keep both -- the cheap scan and the honest count.

        ID-ONLY, deliberately. `length(embedding)` is answerable from the
        `(model, length(embedding))` expression indexes A7 added, so nothing
        here loads a blob; the pre-A5 code that this restores the signal of
        loaded every one of them.

        An absent embedding is "no vector", never a wrong-dimension one, and is
        excluded here exactly as `embeddings.wrong_dim_indices` excludes it."""
        qtable, qid = self._checked_ident(table, id_col)
        where = "embedding IS NOT NULL AND length(embedding) != ?"
        params: list = [int(width)]
        if extra_where:
            where += " AND (%s)" % extra_where
            params.extend(extra_params)
        sql = ("SELECT %s AS ident, length(embedding) AS nbytes FROM %s WHERE %s"
               % (qid, qtable, where))
        if limit is not None:
            # A5's bound applies to the DIAGNOSTIC too. Pushed into SQL rather
            # than sliced in Python so the rows past the sample are never
            # materialised at all. The reported COUNT does not come from here --
            # see `wrong_dim_vector_count` -- so bounding the sample cannot make
            # the number wrong, which is the one thing A0c must not do.
            sql += " LIMIT ?"
            params.append(int(limit))
        try:
            rows = self._conn().execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as e:                 # table absent on an old store
            logger.debug("wrong-dim probe skipped for %s (%s)", table, e)
            return []
        return [(r["ident"], r["nbytes"]) for r in rows if r["ident"] is not None]

    def wrong_dim_vector_count(self, table: str, id_col: str, width: int,
                               extra_where: str = "", extra_params: Sequence = ()) -> int:
        """How many rows `wrong_dim_vector_ids` would return, unbounded.

        Split from the identity query so the identities can be SAMPLED while the
        number stays exact. `length(embedding)` is answerable from
        `idx_{ov,mv,qpv}_model_width`, so this is an index scan that loads no
        blob and builds no Python object per row -- which is the whole point:
        on an 88%-mismatched store the identity list was ~93k tuples per
        channel, five to six times per top-level query, retained until the next
        one. The count is what every consumer actually reports; the identities
        are a 20-item sample in one debug field."""
        qtable, qid = self._checked_ident(table, id_col)
        where = "embedding IS NOT NULL AND length(embedding) != ?"
        params: list = [int(width)]
        if extra_where:
            where += " AND (%s)" % extra_where
            params.extend(extra_params)
        try:
            row = self._conn().execute(
                "SELECT COUNT(*) FROM %s WHERE %s AND %s IS NOT NULL"
                % (qtable, where, qid), tuple(params)).fetchone()
        except sqlite3.Error as e:                 # table absent on an old store
            logger.debug("wrong-dim count skipped for %s (%s)", table, e)
            return 0
        return int(row[0]) if row else 0

    def _paged_vector_scan(self, table: str, batch_size: int, width: Optional[int],
                           extra_where: str = "", extra_params: Sequence = ()):
        """Shared rowid-paged streaming scan for the vector tables (A5).

        The `rowid > ? ORDER BY rowid LIMIT ?` shape (already used by
        `nearest_memory_vectors` and `iter_observed_vectors_paged`) rather than
        a single open cursor: it keeps each statement short-lived, so a long
        scan never pins a read transaction open across the whole query.
        """
        conn = self._conn()
        where = "rowid > ?"
        params: list = []
        if width is not None:
            where += " AND length(embedding) = ?"
            params.append(int(width))
        if extra_where:
            where += f" AND ({extra_where})"
            params.extend(extra_params)
        sql = (f"SELECT rowid AS _rid, * FROM {table} WHERE {where} "
               f"ORDER BY rowid LIMIT ?")
        min_rowid = 0
        batch_size = max(1, int(batch_size))
        while True:
            rows = conn.execute(sql, (min_rowid, *params, batch_size)).fetchall()
            if not rows:
                break
            min_rowid = rows[-1]["_rid"]
            yield [dict(r) for r in rows]
            if len(rows) < batch_size:
                break

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

    def iter_observed_vectors_paged(self, batch_size: int = 1000, width=None):
        """Yield batches of observed_vectors, paged by rowid (streaming, O(batch) memory).

        `width` (A5): the same `length(embedding) = len(query)*4` prefilter the
        memory-vector scan takes. `batch_cosine` scores any other width a hard
        0.0 and retrieve_raw's floor is 0.1, so this cannot change a result --
        it stops SQLite from shipping the blobs of the 88% of production rows
        that were embedded at a different width (A0) across the boundary only
        to be zeroed.
        """
        conn = self._conn()
        where = "rowid > ?"
        params: list = []
        if width is not None:
            where += " AND length(embedding) = ?"
            params.append(int(width))
        sql = f"SELECT rowid, * FROM observed_vectors WHERE {where} ORDER BY rowid LIMIT ?"
        min_rowid = 0
        while True:
            rows = conn.execute(sql, (min_rowid, *params, batch_size)).fetchall()
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

    def get_projection_vector_len(self, provider: str, external_id: str) -> Optional[int]:
        """Byte length of an existing projection vector's blob, or None (A0b)."""
        row = self._conn().execute(
            "SELECT length(embedding) AS n FROM projection_vectors WHERE provider=? AND external_id=?",
            (provider, external_id)).fetchone()
        return row["n"] if row else None

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

    def iter_projection_vectors_paged(self, batch_size: int = 1000, width=None):
        """Yield batches of projection_vectors, paged by rowid (streaming, O(batch) memory).

        `width` (A5): identical contract to iter_observed_vectors_paged's."""
        conn = self._conn()
        where = "rowid > ?"
        params: list = []
        if width is not None:
            where += " AND length(embedding) = ?"
            params.append(int(width))
        sql = f"SELECT rowid, * FROM projection_vectors WHERE {where} ORDER BY rowid LIMIT ?"
        min_rowid = 0
        while True:
            rows = conn.execute(sql, (min_rowid, *params, batch_size)).fetchall()
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

    def iter_session_vectors_paged(self, batch_size: int = 1000, width=None):
        """Yield batches of session_index, paged by rowid (streaming, O(batch) memory).

        `width` (A5) is the optional `length(embedding) = len(query)*4` guard.
        The session scan is the one vector scan still scored by the SCALAR
        `cosine()` rather than `batch_cosine`, deliberately: batching it would
        move the arithmetic from Python's left-to-right float64 sum to a
        float32 (or f64) matmul, which shifts scores by ~1e-8 and is therefore
        a behaviour change, not an optimisation. What CAN be removed for free
        is the rows scalar `cosine()` already scores a hard 0.0 -- it returns
        0.0 whenever `len(a) != len(b)`, and the caller's floor is 0.15 -- so
        those rows are filtered in SQL and never unpacked into a 768-float
        Python list at all.
        """
        conn = self._conn()
        where = "rowid > ?"
        params: list = []
        if width is not None:
            where += " AND length(embedding) = ?"
            params.append(int(width))
        sql = f"SELECT rowid, * FROM session_index WHERE {where} ORDER BY rowid LIMIT ?"
        min_rowid = 0
        while True:
            rows = conn.execute(sql, (min_rowid, *params, batch_size)).fetchall()
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

    # -- paged sweep primitives (§A9) --------------------------------------
    #
    # `query_beliefs(..., limit=N)` is a PREFIX, not a page: no ORDER BY, no
    # cursor, so a sweep built on it reads the same first N rows on every run
    # forever and reports success. These four are the paged replacements. They
    # take the scan key explicitly so the caller -- not the SQL -- decides what
    # "next" means:
    #
    #   scan/count `_after`      -- rowid paging, for sweeps whose unit of work
    #                               is one ROW (decay: each belief decays alone).
    #   scan/count `_distinct_after` -- value paging over a column, for sweeps
    #                               whose unit of work is a GROUP (consistency
    #                               needs every active fact of one entity in the
    #                               same page, or a page boundary bisects the
    #                               group and the contradiction is never seen).
    #
    # Table and column names are module constants at every call site, never
    # caller input, but they are still checked against the live schema before
    # being spliced -- the same rule `_local_columns` follows for foreign DBs.

    def _checked_ident(self, table: str, column: str = "") -> tuple:
        """Confirm `table` (and optionally `column`) exist, via BOUND queries.

        A typo becomes a clean ValueError instead of a SQL syntax error from a
        half-built statement, and nothing that failed this check is ever
        interpolated."""
        row = self._conn().execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name=?",
            (table,)).fetchone()
        if row is None:
            raise ValueError("no table or view named %r" % table)
        if column:
            cols = {r["name"] for r in self._conn().execute(
                "PRAGMA table_info(%s)" % _quote_ident(table)).fetchall()}
            if column not in cols:
                raise ValueError("no column %r on %r" % (column, table))
        return _quote_ident(table), (_quote_ident(column) if column else "")

    def scan_beliefs_after(self, table: str, where: str, params: tuple,
                           after_rowid: int, limit: int) -> list[dict]:
        """One page of rows matching `where`, in rowid order, strictly after
        `after_rowid`. Each row carries `_rowid` so the caller can advance the
        cursor without re-deriving it."""
        qtable, _ = self._checked_ident(table)
        rows = self._conn().execute(
            f"SELECT rowid AS _rowid, * FROM {qtable} WHERE ({where}) AND rowid > ? "
            f"ORDER BY rowid LIMIT ?", (*params, int(after_rowid), int(limit))).fetchall()
        return [dict(r) for r in rows]

    def count_beliefs_after(self, table: str, where: str, params: tuple,
                            after_rowid: int) -> int:
        """How many rows matching `where` are still ahead of the cursor -- the
        `remaining` a bounded sweep has to report to be honest about itself."""
        qtable, _ = self._checked_ident(table)
        row = self._conn().execute(
            f"SELECT COUNT(*) AS n FROM {qtable} WHERE ({where}) AND rowid > ?",
            (*params, int(after_rowid))).fetchone()
        return int(row["n"] if row else 0)

    def scan_distinct_after(self, table: str, column: str, where: str, params: tuple,
                            after: str, limit: int) -> list[str]:
        """One page of DISTINCT `column` values matching `where`, in value order,
        strictly after `after`. The paging key for group-shaped sweeps.

        The grouping column is read through COALESCE(col,''), and that is not
        cosmetic: `normalized_name` and `predicate_canonical` are nullable, and
        `col > ?` is NULL -- never true -- for a NULL. A plain comparison would
        therefore make every NULL-keyed row permanently invisible to the sweep,
        which is the exact defect (rows the sweep never reaches, silently) in a
        smaller costume. NULL sorts as the empty string, i.e. first in the lap."""
        qtable, qcol = self._checked_ident(table, column)
        key = f"COALESCE({qcol},'')"
        # `after IS NULL` is "no lower bound", NOT the empty string: nothing sorts
        # before '', so an ''-as-start sentinel would make the ''-keyed group (the
        # COALESCE'd NULLs) unreachable on every run — the defect again, one group
        # wide. See sweeps._cursor_text.
        rows = self._conn().execute(
            f"SELECT DISTINCT {key} AS v FROM {qtable} WHERE ({where}) "
            f"AND (? IS NULL OR {key} > ?) ORDER BY v LIMIT ?",
            (*params, after, after, int(limit))).fetchall()
        return [r["v"] for r in rows]

    def count_distinct_after(self, table: str, column: str, where: str, params: tuple,
                             after: str) -> int:
        """Distinct grouping values still ahead of the cursor -- the `remaining`
        a group-shaped sweep reports. Same COALESCE key as the scan, so the count
        and the scan can never disagree about what is left."""
        qtable, qcol = self._checked_ident(table, column)
        key = f"COALESCE({qcol},'')"
        row = self._conn().execute(
            f"SELECT COUNT(DISTINCT {key}) AS n FROM {qtable} WHERE ({where}) "
            f"AND (? IS NULL OR {key} > ?)", (*params, after, after)).fetchone()
        return int(row["n"] if row else 0)

    def beliefs_for_values(self, table: str, column: str, values, where: str = "1=1",
                           params: tuple = (), chunk: int = 400) -> list[dict]:
        """Every row whose `column` is one of `values` — the second half of a
        group-shaped sweep.

        `next_distinct_page` names the groups; this loads them WHOLE, which is
        the property that makes group paging correct: a consistency check that
        saw half of an entity's facts would conclude the entity is consistent.
        Chunked so the IN-list never approaches SQLITE_MAX_VARIABLE_NUMBER, and
        deliberately not row-capped: the caller already bounded the work by
        bounding the number of groups."""
        vals = list(values)
        if not vals:
            return []
        qtable, qcol = self._checked_ident(table, column)
        conn, out = self._conn(), []
        step = max(1, int(chunk))
        for i in range(0, len(vals), step):
            part = vals[i:i + step]
            marks = ",".join("?" * len(part))
            rows = conn.execute(
                f"SELECT * FROM {qtable} WHERE ({where}) AND COALESCE({qcol},'') IN ({marks})",
                (*params, *part)).fetchall()
            out.extend(dict(r) for r in rows)
        return out

    def predicate_has_multi_value(self, predicate: str) -> bool:
        """Does any single entity carry >1 active value for this predicate?

        Asked of the DATABASE, not of a page. The old canonicalize sweep decided
        cardinality by grouping whatever 5000 rows it happened to read, so the
        answer depended on the prefix; this is exact regardless of how the sweep
        is paged, and stops at the first witness."""
        row = self._conn().execute(
            "SELECT 1 FROM facts WHERE status='active' AND predicate_canonical=? "
            "GROUP BY entity_id HAVING COUNT(DISTINCT value) > 1 LIMIT 1",
            (predicate,)).fetchone()
        return row is not None

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

    def open_contradiction(self, belief_a: str, belief_b: str, detail: str = "",
                           source: str = "", created_at: str = ""):
        """Record an open contradiction between two beliefs, ONCE per pair.

        TWO RULES MEET HERE, and both are kept.

        A4 (determinism). `contradictions` is PROJECTION state
        (`truncate_projection` wipes it), so both of a row's non-content columns
        are derived rather than minted: the id is a content hash of (belief_a,
        belief_b, detail, source) and `created_at` is the TRIGGERING EVENT's
        timestamp. A replay of the same log writes the identical row, bytes
        included, instead of a fresh uuid4 at a fresh wall-clock reading.
        `source` is the event_id (or, for a caller outside the log, a stable
        label for the detector) -- it keeps two different events that reach the
        same belief pair from collapsing into one row.

        A3 (cadence). Nothing ran the consistency sweep on a cadence before, so
        re-detecting a still-unresolved pair never happened. The moment it runs
        hourly, an unconditional INSERT files the same disagreement 24 times a
        day into `get_open_contradictions`, which feeds both the health snapshot
        and the [CONTRADICTIONS] context block. So: if an OPEN row already names
        this ordered pair, this is a no-op -- WHATEVER the detail says, because a
        re-detection that phrases itself differently ("again, an hour later") is
        still the same unresolved disagreement.

        The pair is matched as ORDERED (a, b): both writers (the reducer's
        conflict path and the CSP sweep) derive their order deterministically
        from the same rows, so an ordered match is sufficient, and a genuinely
        reversed pair from some future writer is still recorded rather than
        silently swallowed.

        A RESOLVED row does not block a fresh open -- a contradiction that
        reappears after being resolved IS news. Composing that with A4's
        content-derived id needs one extra step and nothing more: when the
        reappearing contradiction is byte-identical to the resolved one, its id
        is also identical, so there is no second row to mint. It is REOPENED
        instead. Minting a uuid there would give up A4's replay identity; using
        a bare INSERT OR IGNORE there would give up A3's "it came back" signal.
        Reopening is the only outcome that is both, and it is not a third
        behaviour: the row a caller gets back is the same row A3 would have
        filed and the same row A4 would have derived.

        This path never runs during a replay -- `truncate_projection` empties
        the table first, so every derived row takes the plain INSERT.

        `created_at` may be omitted ONLY by an operational caller that is not
        part of the replayed fold -- the health sweep is the one such caller,
        and it stamps wall clock deliberately.
        """
        cid = projection_row_id("con", {"belief_a": belief_a, "belief_b": belief_b,
                                        "detail": detail, "source": source})
        stamp = created_at or now_iso()
        with self.transaction() as conn:
            if conn.execute(
                    "SELECT 1 FROM contradictions WHERE belief_a=? AND belief_b=? "
                    "AND status='open'", (belief_a, belief_b)).fetchone():
                return
            reopened = conn.execute(
                "UPDATE contradictions SET status='open', detail=?, created_at=? WHERE id=?",
                (detail, stamp, cid)).rowcount
            if not reopened:
                conn.execute("INSERT INTO contradictions"
                             "(id,belief_a,belief_b,detail,status,created_at) "
                             "VALUES(?,?,?,?, 'open', ?)",
                             (cid, belief_a, belief_b, detail, stamp))

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
        candidate (e.g. a rebuild replay) never raises or duplicates.

        The id is derived from the edge itself — the same (new, old) pair the
        UNIQUE index is built on — so it is stable across a
        truncate_projection + replay and identical in two stores built from
        the same log (Ladder 10 A4). `similarity` is deliberately NOT in the
        hash: it is a float read off the embedder, and an id that moved when
        the embedding did would not be an identity for the edge."""
        cid = projection_row_id("sup", {"new_belief_id": new_belief_id,
                                        "old_belief_id": old_belief_id})
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO supersede_candidates"
                "(id,new_belief_id,old_belief_id,kind,similarity,new_value,old_value,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (cid, new_belief_id, old_belief_id, kind, similarity,
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
        # A15: `seen` is a set, so iterating it ordered `points` by
        # PYTHONHASHSEED, and the sort below is stable and keyed on
        # `created_at` ALONE -- which ties constantly, because the facts in one
        # chain are typically asserted from the same source event and carry the
        # same `valid_from`. get_context renders this chain verbatim as
        # `[history: a (d) -> b (d)]` (retrieval.py:2516), so a tied pair
        # printed in a different order in every process. Sort the set into a
        # fixed sequence, then break the timestamp tie on belief_id -- a content
        # hash, so it is the same relation `_precision_order` uses and it
        # survives a store rebuild, which insertion order does not.
        points = []
        for bid in sorted(seen):
            row = self.get_belief("facts", bid)
            if not row:
                continue
            points.append({"belief_id": bid, "value": row.get("value", ""),
                           "created_at": row.get("valid_from") or row.get("created_at") or ""})
        points.sort(key=lambda p: (p["created_at"] or "", p["belief_id"]))
        return points

    # -- corrections -------------------------------------------------------

    def record_correction(self, belief_id: str, reason: str, correction_ref: str,
                          propagated: list[str], source: str = "", created_at: str = ""):
        """Record that `belief_id` was corrected/retracted, and why.

        `corrections` is PROJECTION state, so — exactly as for
        `open_contradiction` (Ladder 10 A4) — the id is a content hash of
        (belief_id, reason, correction_ref, propagated, source) and
        `created_at` comes from the triggering EVENT. `source` is that event's
        id, so two separate corrections of one belief for one reason stay two
        rows while a replay of either stays one.

        INSERT OR IGNORE makes the revision cascade idempotent: `_cascade`
        recurses through the justification graph and can reach the same
        dependent twice within a single event, which previously wrote two
        uuid4 rows for one logical correction."""
        cid = projection_row_id("cor", {"belief_id": belief_id, "reason": reason,
                                        "correction_ref": correction_ref,
                                        "propagated": list(propagated or []),
                                        "source": source})
        with self.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO corrections"
                         "(id,belief_id,reason,correction_ref,propagated,created_at) "
                         "VALUES(?,?,?,?,?,?)",
                         (cid, belief_id, reason, correction_ref,
                          json.dumps(propagated), created_at or now_iso()))

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

    # Sessions that ended or were reaped but never got a session_index row.
    BACKFILL_WHERE = ("status IN ('ended','reaped') AND session_id NOT IN "
                      "(SELECT session_id FROM session_index)")

    def get_sessions_needing_index_backfill(self, limit: int = 200) -> list[str]:
        """One page of ended/reaped sessions lacking a session_index row.

        Watermarked and, since §A9, WRAPPING and REPORTING. It always had a
        cursor — but the cursor only ever moved forward, so once it reached the
        last session id the sweep returned an empty list forever, including for
        sessions behind the cursor that lost their index row later. And it said
        nothing about how much was left, so a store 40k sessions deep looked
        identical to a store that was caught up. Both are now handled by the
        shared sweep page: a short page ends the lap and resets the cursor, and
        the run's processed/remaining/bounded is persisted under `sweep:backfill`
        for `list_sweep_states` to surface."""
        from .sweeps import commit, next_distinct_page      # local: store loads first
        page = next_distinct_page(self, None, "backfill", "sessions", "session_id",
                                  self.BACKFILL_WHERE, (), budget=limit)
        commit(self, page)
        return list(page.rows)

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
            # THE ATTEMPT-RESET RULE, stated here because it differs from
            # enqueue_embed_job's and both have to be true (ladder-6: an
            # exhausted attempt counter must never block re-enqueue forever).
            # This dedupe deliberately looks at pending/running ONLY, so an
            # identical job that already ran — including one that FAILED after
            # burning its attempt cap — does not suppress a new one: the
            # re-enqueue lands as a fresh row with attempts=0. enqueue_embed_job
            # cannot do that (its rows are keyed to a target that is re-touched
            # constantly, so a new row per touch is the unbounded-growth bug it
            # was written to avoid), which is why it re-arms the terminal row in
            # place instead. Different mechanism, same guarantee.
            #
            # A fresh row per re-enqueue is what prune_curation_jobs bounds:
            # terminal rows are deleted by age and by count, so "one row per
            # occurrence" stays a bounded table rather than the store's whole
            # job history (§A7).
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
        # NO independent clamp on the text (A0g N1). This used to store
        # `text[:8000]`, and curation._task_embed then embedded that PAYLOAD for
        # observed and belief kinds, so the deferred/heal path and the write path
        # embedded different strings for any item over 8000 characters -- silently,
        # under the same canonical model tag. Measured on the production shape
        # (max_input_tokens 650, overflow chunk_mean, which means every chunk of the
        # input reaches the model): a 9,736-character note re-embedded from 8,017
        # wire characters, a different vector for the same note. `_task_embed` now
        # re-resolves the text through the reducer's authority for every kind, so
        # this payload is the dedup key and the audit record of what was asked for --
        # and for a `projection` it is the ONLY record of the rendered text (§g5a),
        # which is exactly the string that must not be truncated here.
        payload_dict = {"target_id": target_id, "kind": kind, "text": (text or "")}
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

    def claim_curation_job(self, tasks=None) -> dict | None:
        """Lowest-id ready job, optionally restricted to a set of task values.

        Ready = pending, dependencies done, and NOT deferred: a job whose
        run_after is still in the future stays invisible (§17.3).

        `tasks` is how the drain expresses fairness (§A7): FIFO **within** a
        class, round-robin **across** classes. It is a filter, not a priority —
        the queue never reorders by id, so a class's own jobs still run oldest
        first and the deferred-retry contract is untouched. `tasks=None` keeps
        the pre-A7 behavior (any task), which every existing caller relies on.

        A claimed row's `started_at` is the LEASE stamp: reclaim_stale_jobs
        below uses it to recover a job whose worker died mid-flight."""
        params = [now_iso()]
        filt = ""
        if tasks is not None:
            tasks = [t for t in tasks if t]
            if not tasks:
                return None
            filt = " AND task IN (%s)" % ",".join("?" for _ in tasks)
            params.extend(tasks)
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM curation_jobs WHERE status='pending' AND "
                "(run_after IS NULL OR run_after <= ?)" + filt + " AND "
                "(depends_on IS NULL OR depends_on IN (SELECT id FROM curation_jobs WHERE status='done')) "
                "ORDER BY id LIMIT 1", tuple(params)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE curation_jobs SET status='running', started_at=?, attempts=attempts+1 "
                         "WHERE id=?", (now_iso(), row["id"]))
            return dict(row)

    def reclaim_stale_jobs(self, lease_seconds: int = 900, max_attempts: int = 20,
                           limit: int = 200) -> dict:
        """Recover jobs left `running` by a worker that never came back (§A7).

        `claim_curation_job` moves a row to 'running' and stamps `started_at`.
        Nothing else ever moves it back: a process killed mid-job (OOM, a
        gateway restart draining and then killing in-flight cron work, a plain
        crash) leaves the row 'running' FOREVER, invisible to every future
        claim. That is not hypothetical — the live store had 245 `extract` rows
        stuck 'running'. `started_at` is therefore read as a LEASE: a running
        row older than `lease_seconds` is presumed abandoned.

        An abandoned job is re-armed to 'pending' (retried) unless it has
        already burned `max_attempts` claims, in which case it is failed with a
        stated reason instead of looping forever.

        THE RESET RULE (ladder-6: an exhausted attempt counter must never block
        re-enqueue forever): `attempts` is reset to 0 by re-enqueueing the same
        unit of work — `enqueue_curation` and `enqueue_embed_job` both re-arm an
        identical done/failed row to pending with attempts=0. So "failed after
        20 attempts" is a statement about one attempt streak, not a permanent
        tombstone: the next producer of that same work gets a fresh budget.

        Bounded by `limit` per call, like every other repair sweep, and returns
        the counts so a caller can report them."""
        cutoff = _iso_ago(lease_seconds)
        out = {"reclaimed": 0, "failed": 0, "lease_seconds": int(lease_seconds)}
        with self.transaction() as conn:
            rows = conn.execute(
                "SELECT id, task, attempts FROM curation_jobs WHERE status='running' AND "
                "(started_at IS NULL OR started_at <= ?) ORDER BY id LIMIT ?",
                (cutoff, int(limit))).fetchall()
            for r in rows:
                attempts = int(r["attempts"] or 0)
                if max_attempts and attempts >= int(max_attempts):
                    conn.execute(
                        "UPDATE curation_jobs SET status='failed', finished_at=?, error=? WHERE id=?",
                        (now_iso(),
                         "lease expired after %d attempts (cap %d); re-enqueue the same work "
                         "to reset attempts" % (attempts, int(max_attempts)), r["id"]))
                    out["failed"] += 1
                else:
                    conn.execute(
                        "UPDATE curation_jobs SET status='pending', started_at=NULL, run_after=NULL, "
                        "error=? WHERE id=?",
                        ("lease expired (attempt %d) — worker did not finish" % attempts, r["id"]))
                    out["reclaimed"] += 1
        if out["reclaimed"] or out["failed"]:
            logger.warning("curation queue: reclaimed %d and failed %d job(s) whose %ds lease expired",
                           out["reclaimed"], out["failed"], int(lease_seconds))
        return out

    def prune_curation_jobs(self, max_age_days: float = 7, max_rows: int = 20000,
                            batch: int = 5000) -> dict:
        """Keep `curation_jobs` bounded (§A7).

        Pre-A7 nothing ever deleted a job row: `done` and `failed` accumulated
        for the life of the store, and every enqueue's dedupe probe, every
        claim's dependency sub-select and every VACUUM paid for them. One heal
        run alone could add 105k rows that would never leave.

        Two independent bounds, because either alone has a hole: by AGE (a
        quiet store still forgets last year's jobs) and by COUNT (a busy store
        cannot outrun the age bound). Only TERMINAL rows are eligible —
        pending/running work is never pruned.

        THE DEPENDENCY GUARD: a row that ANY surviving row still points at is
        never pruned, whatever its age. Two independent reasons, and the guard
        has to satisfy both:

        * CORRECTNESS. `claim_curation_job` treats a job as ready only when
          `depends_on IN (SELECT id ... WHERE status='done')`. Deleting a done
          row that a pending job points at would make that job unclaimable
          forever — pruning the queue would silently create the exact
          stuck-forever state this task exists to remove.
        * THE FOREIGN KEY. `depends_on REFERENCES curation_jobs(id)` is
          enforced, so deleting a referenced row raises IntegrityError and
          aborts the whole prune — including when the referrer is itself
          terminal. Guarding only on pending/running referrers therefore does
          not merely prune too little, it makes the prune FAIL on any store that
          has ever run a job with a dependency.

        Excluding every referenced row still converges: a dependent row is
        itself terminal and unreferenced, so it is pruned first and its parent
        becomes prunable on the next pass."""
        out = {"pruned_age": 0, "pruned_cap": 0}
        referenced = ("id NOT IN (SELECT depends_on FROM curation_jobs "
                      "WHERE depends_on IS NOT NULL)")
        terminal = "status IN ('done','failed')"
        with self.transaction() as conn:
            if max_age_days is not None and float(max_age_days) >= 0:
                cutoff = _iso_ago(float(max_age_days) * 86400.0)
                cur = conn.execute(
                    "DELETE FROM curation_jobs WHERE id IN (SELECT id FROM curation_jobs "
                    "WHERE %s AND COALESCE(finished_at, created_at) <= ? AND %s "
                    "ORDER BY id LIMIT ?)" % (terminal, referenced), (cutoff, int(batch)))
                out["pruned_age"] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            if max_rows is not None and int(max_rows) >= 0:
                n = conn.execute("SELECT COUNT(*) FROM curation_jobs WHERE %s" % terminal).fetchone()[0]
                excess = int(n) - int(max_rows)
                if excess > 0:
                    cur = conn.execute(
                        "DELETE FROM curation_jobs WHERE id IN (SELECT id FROM curation_jobs "
                        "WHERE %s AND %s ORDER BY id LIMIT ?)" % (terminal, referenced),
                        (min(excess, int(batch)),))
                    out["pruned_cap"] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        if out["pruned_age"] or out["pruned_cap"]:
            logger.info("curation queue: pruned %d aged + %d over-cap terminal job rows",
                        out["pruned_age"], out["pruned_cap"])
        return out

    def pending_counts_by_task(self) -> dict:
        """`{task: pending_count}` for every task with pending work, plus the
        per-CLASS rollup the fair drain actually apportions over. Surfaced by
        `embedding_status()` so "why is nothing extracting?" is answerable
        without opening the db."""
        rows = self._conn().execute(
            "SELECT task, COUNT(*) FROM curation_jobs WHERE status='pending' GROUP BY task").fetchall()
        by_task = {r[0]: r[1] for r in rows}
        by_class = {c: 0 for c in TASK_CLASSES}
        for task, n in by_task.items():
            by_class[task_class(task)] = by_class.get(task_class(task), 0) + n
        return {"by_task": by_task, "by_class": by_class,
                "running": self.count_rows("curation_jobs", "status='running'")}

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

    # -- maintenance watermarks (§17.4, ladder-10 A3) ----------------------

    def get_maintenance_run(self, entry: str) -> Optional[dict]:
        """One schedule entry's watermark, or None if it has never fired."""
        row = self._conn().execute(
            "SELECT * FROM maintenance_runs WHERE entry=?", (entry,)).fetchone()
        return dict(row) if row else None

    def get_maintenance_runs(self) -> list[dict]:
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM maintenance_runs ORDER BY entry").fetchall()]

    def record_maintenance_run(self, entry: str, *, task: str, payload=None,
                               fire_at: str, enqueued: bool = True):
        """Advance one entry's watermark to the schedule instant it fired for.

        Written AFTER the enqueue, deliberately: if the process dies between the
        two, the next hook call re-decides and enqueues again — which
        enqueue_curation collapses, because the identical job is still pending.
        The opposite order would lose the job silently."""
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO maintenance_runs(entry,task,payload,last_fire_at,last_enqueued_at,"
                "enqueues,decisions) VALUES(?,?,?,?,?,?,1) "
                "ON CONFLICT(entry) DO UPDATE SET task=excluded.task, payload=excluded.payload, "
                "last_fire_at=excluded.last_fire_at, last_enqueued_at=excluded.last_enqueued_at, "
                "enqueues=enqueues+excluded.enqueues, decisions=decisions+1",
                (entry, task, json.dumps(payload or {}, sort_keys=True), fire_at,
                 now_iso(), 1 if enqueued else 0))

    # -- extractions (§16) -------------------------------------------------

    def record_extraction(self, observed_event: str, extractor_version: str,
                          produced: dict, ambiguous: int, route: str) -> bool:
        """Returns True if newly recorded, False if already done (idempotent, I9).

        The id is derived from the row's own UNIQUE key (observed_event,
        extractor_version) rather than minted as a uuid4 (Ladder 10 A4). This
        table is NOT projection state — `truncate_projection` deliberately
        keeps it — so this is not a replay-determinism fix; it is what lets the
        H1 inertness probe drop its `uuid.uuid4` monkeypatch, since
        extractions.id was the last random id a default capture flow wrote.
        `created_at` stays wall clock on purpose: it records when the
        extractor actually ran, which no event determines."""
        with self.transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM extractions WHERE observed_event=? AND extractor_version=?",
                (observed_event, extractor_version)).fetchone()
            if exists:
                return False
            conn.execute("INSERT INTO extractions(id,observed_event,extractor_version,produced,"
                         "ambiguous,route,created_at) VALUES(?,?,?,?,?,?,?)",
                         (projection_row_id("xtr", {"observed_event": observed_event,
                                                    "extractor_version": extractor_version}),
                          observed_event, extractor_version,
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
        Returns the new candidate id, or None when it was already queued.

        The id IS that dedupe key, content-hashed (Ladder 10 A4): it was a
        uuid4, so a truncate_projection + replay re-derived every candidate
        under a brand-new id and nothing could reference a candidate across a
        rebuild. That is precisely why F4d had to address an adjudication
        outcome by the dedupe key instead
        (`resolve_identity_candidate_by_key`); with the id derived from the
        same tuple, the two addressings now name the same row, and
        `resolve_identity_candidate` is replay-stable as well."""
        cand_id = projection_row_id("idc", {"kind": kind, "entity_id": entity_id,
                                            "other_id": other_id or "",
                                            "mention_ref": mention_ref or ""})
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

    def count_inferred_entity_merges(self) -> int:
        """How many entity merges in this store's log were INFERRED from an exact
        name match rather than adjudicated (ladder-10 A8).

        Before A8 the `identity` curation task merged every entity pair sharing
        (normalized_name, owner, domain), stamping `evidence: exact_name_match`
        on the `merged` event. That path is gone — the collision is a candidate
        now — but the events it already wrote are still in the log, and the
        entities they merged are still merged.

        They are deliberately NOT un-merged. Reversing them in bulk would be the
        same mistake pointed the other way: an automatic identity decision, made
        from the absence of evidence instead of from a name, and some of those
        merges were certainly correct ("Robin Placeholder" recorded twice really is one
        person). Un-merging is an adjudication too. This method exists so the
        count is VISIBLE — it rides `health.run()` — rather than being a silent
        historical fact nobody can see.

        Cheap: idx_events_type(type, seq) makes this an index seek over the
        handful of `merged` rows a store holds, not a table scan.
        """
        row = self._conn().execute(
            "SELECT COUNT(*) FROM events WHERE type='merged' "
            "AND payload LIKE '%exact_name_match%'").fetchone()
        return int(row[0]) if row else 0

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

    def get_goal(self, goal_id: str) -> dict | None:
        """One goal by id, ANY status (ladder-10 A1b).

        get_active_goals cannot serve the write path: ReasoningLayer.update_goal
        flips a goal to a NON-active status, so the row it must check the ACL of
        is frequently one get_active_goals has already filtered away."""
        row = self._conn().execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        return dict(row) if row else None

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
            #
            # maintenance_runs (§17.4, A3) is NOT here either, and the reason is
            # the sharpest one on this list: it is not derived from the log at
            # all. A watermark is a record of an OPERATIONAL decision this host
            # took at a wall-clock instant ("the 04:00 health job was queued"),
            # not a claim about what is true. Replaying the log cannot recreate
            # it, and clearing it would make a rebuild look, to the scheduler,
            # exactly like a store that has never run maintenance -- so every
            # sweep would fire again immediately after every rebuild, which is
            # the thundering-herd version of the bug A3 exists to fix. Truth is
            # rebuilt from the log; operational history is kept.
            #
            # A4 named this list PROJECTION_TABLES so the replay test can assert
            # over exactly the tables a rebuild is allowed to touch. Its members
            # are the same ones A3 spelled out here, maintenance_runs excluded.
            for t in PROJECTION_TABLES:
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


# THE word-token definition for every keyword path (FTS queries here; routing,
# overlap and hint tokens in retrieval.py): runs of Unicode letters and digits,
# the characters FTS5's unicode61 tokenizer indexes, with an in-word apostrophe
# kept ("don't") and the typographic one (U+2019) folded to it. The previous
# ASCII-only `[A-Za-z0-9]+` turned "Zürich" into "rich" and "José" into "Jos",
# so the keyword arm searched for words nobody wrote, and a Cyrillic or CJK
# query produced no terms at all.
_WORD_RX = re.compile(r"[^\W_]+(?:'[^\W_]+)*")


def word_tokens(text: str) -> list:
    """Words in `text`, in order, case preserved. See _WORD_RX."""
    return _WORD_RX.findall((text or "").replace("\u2019", "'"))


def _fts_query(query: str) -> str:
    """Sanitize a free-text query into a safe FTS5 OR-of-terms match string.

    Terms are split at apostrophes as well: unicode61 indexes "don't" as "don"
    and "t", so a quoted "don't" would be a phrase query that happens to work,
    and splitting keeps every term a bare word. Single ASCII characters are
    dropped as noise; a single non-ASCII letter (a CJK word) is kept."""
    terms = [t for w in word_tokens(query) for t in w.split("'")]
    terms = [t for t in terms if len(t) > 1 or (t and not t.isascii())]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


# curation_jobs is spliced into _SCHEMA from these, so the migration rebuild
# (_rebuild_curation_jobs) recreates the EXACT table+index and can never drift
# from the fresh-install schema. `run_after` = deferred retry (§17.3, §24.4).
# The CLOSED set of curation task names. This tuple is the single source of
# truth: the CHECK below is generated from it, _migrate's "is this store's CHECK
# stale?" probe reads it, and tests/test_task_check_handler_consistency.py
# asserts it equals the set of CurationWorker._task_* handlers. Adding a value
# here without adding a handler (or vice versa) now fails a test instead of
# producing a job that completes as 'no_handler' forever (ladder-10 A13).
CURATION_TASKS = (
    "extract", "canonicalize", "consolidate", "identity", "derive", "verify",
    "decay", "consistency", "health", "reextract", "journal_ingest",
    "session_summarize", "embed", "digest", "federate_sweep", "backfill_sweep",
)

# Task names an EARLIER build's CHECK permitted and this one does not (A13).
# `route` and `criticality` never had a handler in ANY build -- an enqueue of
# either passed the CHECK, sat in the queue, and completed as 'no_handler'.
# `contradiction` had a handler, but one that called health.consistency_sweep()
# and nothing else: the same sweep `consistency` runs. Kept here (not merely
# deleted from the tuple above) because _migrate has to RECOGNISE an old store's
# wider CHECK to know it must rebuild, and has to decide what happens to rows
# already queued under these names -- see _retire_removed_task_rows.
RETIRED_CURATION_TASKS = ("route", "criticality", "contradiction")

# `contradiction` rows are RE-TASKED rather than dropped: the handler they would
# have run is byte-for-byte the sweep `consistency` runs, so the queued work (and
# the record of work already done under that name) stays TRUE after the rename.
# `route`/`criticality` rows have no such equivalent and are dropped.
RETIRED_TASK_ALIASES = {"contradiction": "consistency"}

_CURATION_JOBS_DDL = ("""CREATE TABLE IF NOT EXISTS %s (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT CHECK(task IN (""" + ",".join("'%s'" % t for t in CURATION_TASKS) + """)),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT,
    run_after TEXT);""")
_JOBS_INDEX_DDLS = (
    ("CREATE INDEX IF NOT EXISTS idx_jobs_ready ON curation_jobs(status, id) "
    "WHERE status='pending';"),
    # Serves the enqueue_curation / enqueue_embed_job dedup probe. Without it
    # every enqueue scans curation_jobs, which grows as the drain proceeds, so
    # the guard that exists to REMOVE work costs O(queue) per call and eats most
    # of what it saves.
    ("CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON curation_jobs(task, payload) "
    "WHERE status IN ('pending','running');"),
    # A7. Serves the fair drain's per-CLASS claim (`task IN (...) AND
    # status='pending' ORDER BY id`). Without it, claiming one extract from
    # behind 10k pending embeds walks 10k index entries per claim — the shape
    # this task exists to remove, reintroduced one level down.
    ("CREATE INDEX IF NOT EXISTS idx_jobs_task_ready ON curation_jobs(task, id) "
    "WHERE status='pending';"),
    # A7. Serves reclaim_stale_jobs' lease scan. Partial on status='running',
    # so it holds only the in-flight rows (single digits in steady state) and
    # the sweep costs nothing on a healthy queue.
    ("CREATE INDEX IF NOT EXISTS idx_jobs_lease ON curation_jobs(started_at) "
    "WHERE status='running';"),
    # A7. Serves prune_curation_jobs' age cutoff over terminal rows.
    ("CREATE INDEX IF NOT EXISTS idx_jobs_terminal ON curation_jobs(finished_at, id) "
    "WHERE status IN ('done','failed');"),
    # v5.7.0 review §8. The ONLY index on the referencing side of
    # `depends_on REFERENCES curation_jobs(id)`, and it is a deploy-cost fix, not
    # a query-plan nicety. SQLite verifies an enforced foreign key on every
    # DELETE from the parent table by scanning the child column; with no index on
    # `depends_on` that is one FULL TABLE SCAN of curation_jobs PER DELETED ROW.
    # Measured on a 105k-row v11 backlog upgrading to 18: rung 17's two deletes
    # (805 rows) cost 12.57 s with foreign_keys=ON and no index, 0.020 s with
    # foreign_keys=OFF, and 0.060 s with this index -- exactly linear at ~16 ms
    # per deleted row without it. Rung 17 is the first ladder step that ever
    # deletes from this table, so that stall was new in v5.7.0 and a gateway paid
    # it at startup. It also permanently speeds prune_curation_jobs, whose
    # dependency guard (`id NOT IN (SELECT depends_on ...)`) scans this same
    # column, and the edge-clearing guard in _retire_removed_task_rows.
    #
    # Deliberately FULL, not partial. A `WHERE depends_on IS NOT NULL` index
    # would be smaller and measured just as fast here (0.043 s vs 0.062 s on the
    # same store, the gap being index-build time) -- but SQLite's documented
    # contract for the child side of a foreign key is an ORDINARY index, and
    # whether the planner reaches for a partial one during FK verification is not
    # a guarantee. A 200x deploy-critical speedup does not get to rest on an
    # undocumented planner behaviour, so this pays ~1 MB for a promise.
    ("CREATE INDEX IF NOT EXISTS idx_jobs_depends_on ON curation_jobs(depends_on);"),
)
# Named separately because rung 17 must create it BEFORE it deletes anything;
# see the call site in _migrate. It is the last element of the tuple above.
_JOBS_DEPENDS_ON_INDEX_DDL = _JOBS_INDEX_DDLS[-1]
# One string for the _SCHEMA splice (executescript takes many statements);
# the rebuild path executes them one at a time (conn.execute takes exactly one).
_JOBS_INDEX_DDL = "\n".join(_JOBS_INDEX_DDLS)
_JOB_COLS = ("id,task,payload,depends_on,status,attempts,created_at,started_at,finished_at,"
             "error,run_after")

# -- vector census indexes (§A7) --------------------------------------------
#
# The heal (health._embedder_mismatch_heal) has to answer one question on every
# health run: "which stored vectors are NOT in the active embedder's geometry?"
# A0 already reduced that from one row per vector to one GROUP BY, but a GROUP
# BY over (model, length(embedding)) still reads every row's blob. MEASURED on a
# synthetic 100k-row store (.a7bench, 159 MB, 1 KB blobs), same file, same warm
# cache, index dropped vs present:
#     unindexed GROUP BY over both vector tables   489 - 1279 ms
#     the mismatch seeks below, all three tables     0.09 - 0.11 ms
# — on a store with nothing wrong with it, on every health run. A healthy store
# must not pay for the sick case.
#
# These EXPRESSION indexes (SQLite >= 3.9) put the tag and the blob WIDTH — the
# two things `_classify_tag` decides on — in an index, so the heal's scans
# become range seeks that touch only the mismatched rows:
#   wrong tag  : model < active_tag  /  model > active_tag   (two range scans)
#   wrong width: model = active_tag AND length(embedding) </>/IS NULL expected
# On a healthy store all four seek straight past the end of their range and
# return nothing, in microseconds; the cost becomes O(mismatched), not O(all).
# They also serve the retag UPDATE and the requeue SELECT, which are keyed on
# exactly the same (model, width) pair.
_VECTOR_CENSUS_INDEX_DDLS = (
    "CREATE INDEX IF NOT EXISTS idx_ov_model_width ON observed_vectors(model, length(embedding));",
    "CREATE INDEX IF NOT EXISTS idx_mv_model_width ON memory_vectors(model, length(embedding));",
    "CREATE INDEX IF NOT EXISTS idx_qpv_model_width ON query_proxy_vectors(model, length(embedding));",
)
_VECTOR_CENSUS_INDEX_DDL = "\n".join(_VECTOR_CENSUS_INDEX_DDLS)

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
# owner's hints for a textually similar query. `principal` (schema_version 12,
# ladder-10 A1) records the exact principal the verdict was recorded for, which
# is what `owner` cannot express: a sandboxed agent shares its owner with the
# siblings it must not influence, so the read path drops its hints by principal.
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
    principal TEXT NOT NULL DEFAULT '',
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

# Maintenance-scheduler watermarks (§17.4, ladder-10 A3). Spliced into _SCHEMA
# below AND probed by _migrate, from this ONE definition.
#
# Keyed by ENTRY, not by task: `decay` is driven by two schedules (session
# reaping every few minutes, belief decay daily), so a task-keyed watermark
# would have the reaper and the decay sweep overwriting each other's history.
#
# `last_fire_at` is the SCHEDULE INSTANT the entry was last enqueued for — not
# the wall clock, and not the job's outcome. Two consequences worth stating:
# a job that fails is retried at the next schedule instant instead of being
# spun on (a permanently broken task cannot become an infinite enqueue loop),
# and comparing a fresh `prev_fire` against this column is a plain
# lexicographic comparison of two fixed-width RFC3339 strings.
#
# `enqueues` counts the times an enqueue actually produced a job; a decision
# that collapsed into an already-pending identical job still advances
# `last_fire_at` (the work IS queued) but does not count.
_MAINTENANCE_DDL = """
CREATE TABLE IF NOT EXISTS maintenance_runs (
    entry TEXT PRIMARY KEY, task TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
    last_fire_at TEXT, last_enqueued_at TEXT,
    enqueues INTEGER NOT NULL DEFAULT 0, decisions INTEGER NOT NULL DEFAULT 0);
"""

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

-- `body` (A0fix, rung 12) is LAST for the same reason goals.owner is: the
-- migration appends it with ALTER TABLE ADD COLUMN, so declaring it beside
-- `name` here would leave a fresh install and an upgraded store with different
-- column ORDER permanently.
CREATE TABLE IF NOT EXISTS procedures (
    belief_id TEXT PRIMARY KEY, name TEXT, params TEXT, steps TEXT, success_criteria TEXT,
    derived_from TEXT DEFAULT '[]', domain TEXT, owner TEXT, read_acl TEXT, info_label TEXT,
    status TEXT, salience TEXT DEFAULT 'normal', criticality TEXT DEFAULT 'normal',
    confidence REAL, trust_level INTEGER, valid_from TEXT, valid_until TEXT, superseded_by TEXT,
    created_at TEXT, last_seen_at TEXT, fidelity TEXT DEFAULT 'verbatim', utility REAL DEFAULT 0,
    purpose_scope TEXT DEFAULT '["*"]', consent TEXT, provenance TEXT, novelty REAL,
    occurrence_count INTEGER NOT NULL DEFAULT 1, body TEXT);

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
-- `model` is declared LAST on purpose: ALTER TABLE ADD COLUMN can only append,
-- so a migrated store and a fresh one keep the identical column ORDER and
-- `SELECT *` means the same thing on both (A0e).
CREATE TABLE IF NOT EXISTS session_index (
    session_id TEXT PRIMARY KEY, summary TEXT, embedding BLOB, owner TEXT, occurred_at TEXT,
    model TEXT);
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

-- goals / reflections (§23). `owner`/`read_acl` (schema_version 13, ladder-10
-- A1b) are the same pair facts/notes/episodes/procedures/user_knowledge carry,
-- and for the same reason: both tables reach user-visible output (active_goals,
-- and recall_similar_situations via plan_context), so both need something for
-- access.can_read to decide on. Nullable with no default -- NULL means the row
-- was written before attribution existed; see reasoning.LEGACY_OWNER.
-- goals / reflections: `owner` and `read_acl` (A1b, rung 15) are LAST, and the
-- position is load-bearing. The migration adds them with ALTER TABLE ADD
-- COLUMN, which can only APPEND, so declaring them mid-table here would make a
-- fresh install and an upgraded store disagree about column ORDER for the rest
-- of their lives -- `SELECT *` would return a different tuple shape on the two.
-- Nothing in this tree reads these rows positionally today, which is exactly
-- why the drift would have gone unnoticed; ladder-9 F4c put rerank_hints.owner
-- last for the same reason. Found by tests/test_v570_schema_ladder.py's
-- fresh-equals-upgraded assertion.
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY, goal TEXT, status TEXT DEFAULT 'active',
    created_at TEXT, updated_at TEXT, owner TEXT, read_acl TEXT);

CREATE TABLE IF NOT EXISTS reflections (
    id TEXT PRIMARY KEY, situation TEXT, action TEXT, outcome TEXT, lesson TEXT,
    applicability TEXT, created_at TEXT, owner TEXT, read_acl TEXT);

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
""" + _HOST_DRAIN_DDL + "\n" + _MAINTENANCE_DDL + "\n" + _VECTOR_CENSUS_INDEX_DDL
