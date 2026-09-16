#!/usr/bin/env python3
"""
Chronicle — drop hash vectors and requeue the real embeds (§24.4).

A store that ran while the old silent hashing fallback was in force holds vectors
in an incomparable geometry: nothing downstream can tell them from model vectors,
so every query they touch is quietly wrong. This deletes them and enqueues one
`embed` curation job per source event/belief, which the worker fills in as soon
as a backend is reachable (§17.3).

Opens the db through MemoryStore on purpose: the stores holding hash vectors are
exactly the OLD ones, whose curation_jobs predates task='embed', and MemoryStore's
init migration is what makes the enqueue legal.

Idempotent: deleted rows can't match twice, and an identical queued job dedupes.
--dry-run opens the db READ-ONLY and reports what would happen.

A0b: hash rows are matched by CANONICAL MODEL IDENTITY, not by literal tag
string. The old `model IN ('hashing','hashing-v1','offline','none')` list missed
every spelling variant a writer could produce -- "hashing:latest", "Hashing-v1",
a path-shaped name -- and those rows stayed in the store, in an incomparable
geometry, invisible. Every distinct tag actually present is canonicalized in
Python and the ones that resolve to the hashing family are what gets matched.

Usage:  python3 scripts/requeue_hash_vectors.py <db_path> [--dry-run]

Exit codes: 0 = done   1 = usage / db error
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.vector_index import delete_matching as _vec0_delete
from engine.embeddings import VECTOR_TABLES, _HASHING_CANONICAL, canonical_model_id
from engine.reducer import belief_vector_text, observed_vector_text
from engine.store import MemoryStore

# Source text is resolved ONLY through reducer.belief_vector_text /
# reducer.observed_vector_text -- THE authority on what text a stored vector was
# made of, derived from reducer.vector_text() itself. This script used to import
# a hand-maintained kind->column map from HealthEngine; that map said
# `procedure` -> `procedures.name`, which tools._t_remember sets to
# content[:40], while the reducer embedded the full body. Two definitions of the
# same thing drifted, and the drift was silent. There is no map here now.

# DETECTION covers every embedding-bearing table, bound from
# embeddings.VECTOR_TABLES rather than re-typed here -- this file used to hold a
# third hand-written copy of that list, and all three copies named the same
# three tables (A0e).
_VECTOR_TABLES = VECTOR_TABLES

# REWRITING is narrower than detection, and says so. This script's contract is
# "delete the incomparable vector, requeue an embed of the same text", and only
# these two tables are pure vector rows a delete can safely empty:
# session_index also holds the summary the vector was made OF, and
# projection_vectors' external ids cannot be re-rendered from anything inside
# Chronicle (§g5a). Hash-tagged rows in those two are found (above), REPORTED by
# name (`_unhandled`), and repaired by scripts/migrate_vectors.py, which
# re-embeds them in place from their own recoverable text -- a hashing tag
# canonicalizes to 'hashing-v1', which is never the active model id, so that
# tool already classifies them `reembed`. This is a named scope, not a gap.
_REWRITTEN_TABLES = ("observed_vectors", "memory_vectors")


def _hash_tags(conn) -> tuple:
    """Every distinct tag in this db that canonicalizes to the hashing family.

    Identity, not string matching (A0b): "hashing", "offline", "none",
    "hashing:latest" and "Hashing-v1" all name the one incomparable geometry,
    and a store written by a mixture of them used to have only the exact
    spellings in the hard-coded list cleaned up."""
    tags = set()
    for table in _VECTOR_TABLES:
        try:
            rows = conn.execute("SELECT DISTINCT model FROM %s" % table).fetchall()
        except sqlite3.Error:
            continue                       # table absent on an un-migrated store
        for r in rows:
            if canonical_model_id(r[0]) == _HASHING_CANONICAL:
                tags.add(r[0])
    return tuple(sorted(tags))


def _scan(conn, models, marks):
    """(target_id, kind, text) for every hash-embedded vector row. Read-only, and
    schema-agnostic so it also runs against an un-migrated store."""
    out = []
    if not models:
        return out
    for row in conn.execute(f"SELECT event_id FROM observed_vectors WHERE model IN ({marks})",
                            models).fetchall():
        eid = row[0]
        text, recoverable = observed_vector_text(conn, eid)
        out.append((eid, "observed", text if recoverable else ""))
    for row in conn.execute(f"SELECT belief_id, kind FROM memory_vectors WHERE model IN ({marks})",
                            models).fetchall():
        bid, kind = row[0], row[1]
        # `recoverable` False = the store cannot say what text this vector was
        # made of. Reported as an orphan (no job queued) rather than requeued
        # with the nearest string to hand.
        text, recoverable = belief_vector_text(conn, kind, bid)
        out.append((bid, kind, text if recoverable else ""))
    return out


def _unhandled(conn, models, marks) -> list:
    """(table, rows) for hash-tagged vectors this script FINDS but does not
    rewrite — see `_REWRITTEN_TABLES` for why the scope is narrower than the
    scan. Reported rather than silently omitted: a tool that scans five tables
    and rewrites two must say which two."""
    out = []
    if not models:
        return out
    for table in _VECTOR_TABLES:
        if table in _REWRITTEN_TABLES or table == "query_proxy_vectors":
            continue                       # rewritten, or dropped below
        try:
            n = conn.execute("SELECT COUNT(*) FROM %s WHERE model IN (%s)" % (table, marks),
                             models).fetchone()[0]
        except sqlite3.Error:
            continue                       # column/table absent on an un-migrated store
        if n:
            out.append((table, n))
    return out


def _report(prefix, rows, queued, deleted, unhandled=()):
    orphans = sum(1 for _, _, text in rows if not text)
    print(f"{prefix}hash vectors found : {len(rows)}")
    print(f"{prefix}embed jobs queued  : {queued}")
    print(f"{prefix}vector rows deleted: {deleted}")
    if orphans:
        print(f"{prefix}  ({orphans} had no recoverable source text — deleted, not requeued)")
    for table, n in unhandled:
        print(f"{prefix}NOT rewritten here : {table} holds {n} hash-tagged row(s). "
              f"Run scripts/migrate_vectors.py, which re-embeds them in place from their "
              f"own text.")


def requeue(db_path: str, dry_run: bool = False) -> int:
    path = Path(db_path).expanduser()
    if not path.exists():
        print(f"ERROR: no database at {path}")
        return 1

    if dry_run:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            models = _hash_tags(conn)
            marks = ",".join("?" * len(models))
            rows = _scan(conn, models, marks)
            unhandled = _unhandled(conn, models, marks)
        finally:
            conn.close()
        _report("[dry-run] ", rows, sum(1 for _, _, t in rows if t), len(rows), unhandled)
        return 0

    store = MemoryStore(str(path))          # migrates the schema (see module docstring)
    queued = 0
    unhandled = []
    with store.transaction() as conn:       # delete + enqueue land together or not at all
        models = _hash_tags(conn)
        marks = ",".join("?" * len(models))
        rows = _scan(conn, models, marks)
        unhandled = _unhandled(conn, models, marks)
        for target, kind, text in rows:
            if text and store.enqueue_embed_job(target, kind, text) is not None:
                queued += 1
        if models:
            conn.execute(f"DELETE FROM observed_vectors WHERE model IN ({marks})", models)
            # Same hazard as scripts/writeback_vectors.py, one step worse: these
            # rows are GONE from observed_vectors, so anything left behind in the
            # vec0 ANN mirror is an orphan that KNN can still return and that no
            # primary-table read will ever contradict. There is no id list to
            # scope this to (the DELETE is by model), so the whole mirror goes;
            # retrieval falls through to the paged scan while it is empty and the
            # mirror repopulates as the requeued vectors are rewritten.
            _vec0_delete(conn, "1=1", ())
            conn.execute(f"DELETE FROM memory_vectors WHERE model IN ({marks})", models)
        # E2 doc2query proxies carry their own model tag and were invisible to
        # this script, so a hash-embedded store kept scoring hash proxies
        # against real-model query vectors long after every content vector had
        # been re-embedded. Dropped, not requeued: the embed-job queue writes
        # exactly one vector per (target, kind), which cannot express a
        # variable-length proxy set. The reducer regenerates them on the
        # parent belief's next write. Same reasoning as
        # HealthEngine._embedder_mismatch_heal.
            conn.execute(f"DELETE FROM query_proxy_vectors WHERE model IN ({marks})", models)
    _report("", rows, queued, len(rows), unhandled)
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        print(__doc__)
        return 1
    return requeue(args[0], dry_run="--dry-run" in sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
