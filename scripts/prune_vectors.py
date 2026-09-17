#!/usr/bin/env python3
"""
Chronicle vector prune — drop observed vectors for throwaway sessions (§24.3).

Deletes `observed_vectors` rows whose event belongs to a session whose id starts
with one of the given prefixes. This is the retroactive half of
`embeddings.exclude_session_prefixes` (§27), which only stops NEW vectors being
written; the event log itself is never touched (vectors are a derived index and
come back on a projection rebuild if the exclusion is lifted).

Both the count and the delete match rows with a subselect over `events`, one
statement per prefix — never a Python-side id list, whose IN(?,?,...) blows
SQLITE_LIMIT_VARIABLE_NUMBER (32766 on a stock build) for any prefix matching
more events than that.

Also mirrors the delete into the optional sqlite-vec ANN index (§27
vector_index:, u5), if one was ever populated on this db -- best-effort, via
engine.vector_index.delete_matching on the SAME connection/predicate, so a
pruned session's vectors don't linger in vec0 after this script has run.

§H2: the pruned events' doc2query EXCERPT proxies go too. Those rows are keyed
by event_id under kind='observed' (embeddings.doc2query.excerpts, off by
default) and, since H2 wired them through the raw retrieval channel, a surviving
proxy would keep scoring an event whose own vector this script just deleted --
i.e. it would silently undo the prune for exactly the sessions someone asked to
exclude. Counted separately from observed vectors in the report: they are a
different row population, and adding them into one total would misreport how
much of each was actually there.

--orphans: vectors whose source EVENT is no longer in the log. The log is the
truth and every vector is derived from an event, so a vector of an event that
does not exist is an index entry with nothing behind it: it cannot be rendered,
cannot be re-embedded (migrate_vectors counts it unrecoverable on every run)
and still costs a row in every brute-force scan. Events only leave the log by
hand (no Chronicle code deletes them); one production store kept 18,394 such
vectors after a manual purge that removed the events and their FTS rows. The
same excerpt-proxy and ANN-mirror cleanup applies.

Usage:  python3 scripts/prune_vectors.py --db PATH [--session-prefix P]... [--orphans] [--dry-run]

Exit codes:  0 = pruned (possibly nothing matched)   1 = usage / db error
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.vector_index import delete_matching

# Rows to prune: observed_vectors joined to events by event_id, session prefix match.
# vec0 carries the same event_id column, so this predicate applies unchanged there.
_MATCH = "event_id IN (SELECT event_id FROM events WHERE session_id LIKE ? || '%')"
# The same predicate over query_proxy_vectors (§H2), whose excerpt rows key the
# event id in `belief_id` and are distinguished from belief proxies by kind.
_PROXY_MATCH = ("kind='observed' AND belief_id IN "
                "(SELECT event_id FROM events WHERE session_id LIKE ? || '%')")


# Orphans (--orphans): the source event is gone. `NOT IN` rather than a correlated
# NOT EXISTS so the SAME fragment applies to vec0, whose table name differs.
_ORPHAN_MATCH = "event_id NOT IN (SELECT event_id FROM events)"
_ORPHAN_PROXY_MATCH = "kind='observed' AND belief_id NOT IN (SELECT event_id FROM events)"


def prune_orphans(db_path: str, dry_run: bool = False) -> int:
    """Delete (or with dry_run only count) observed_vectors, and the doc2query
    excerpt proxies, whose event is no longer in `events`. Returns the vector
    count; belief-keyed vectors are never touched."""
    conn = sqlite3.connect(db_path)
    try:
        if dry_run:
            n = conn.execute("SELECT COUNT(*) FROM observed_vectors WHERE " + _ORPHAN_MATCH
                             ).fetchone()[0]
            p = _proxy_rows(conn, "SELECT COUNT(*) FROM query_proxy_vectors WHERE "
                            + _ORPHAN_PROXY_MATCH)
        else:
            n = conn.execute("DELETE FROM observed_vectors WHERE " + _ORPHAN_MATCH).rowcount
            delete_matching(conn, _ORPHAN_MATCH, ())  # best-effort ANN-mirror cleanup
            p = _proxy_rows(conn, "DELETE FROM query_proxy_vectors WHERE " + _ORPHAN_PROXY_MATCH)
            conn.commit()
        print(f"  orphans (event no longer in the log): {n} vectors, {p} excerpt proxies")
        return n
    finally:
        conn.close()


def _proxy_rows(conn, sql: str) -> int:
    """COUNT result or DELETE rowcount; 0 on a store predating query_proxy_vectors."""
    try:
        cur = conn.execute(sql)
        return cur.fetchone()[0] if sql.startswith("SELECT") else cur.rowcount
    except sqlite3.OperationalError:
        return 0


def prune_vectors(db_path: str, prefixes: list[str], dry_run: bool = False) -> int:
    """Delete (or with dry_run only count) observed_vectors — and the matching
    doc2query excerpt proxies — for each prefix.

    Returns the total reported. A real run deletes each row once; a dry run
    reports per prefix, so overlapping prefixes are counted once each."""
    conn = sqlite3.connect(db_path)
    total = 0
    try:
        for prefix in prefixes:
            if dry_run:
                n = conn.execute("SELECT COUNT(*) FROM observed_vectors WHERE " + _MATCH,
                                 (prefix,)).fetchone()[0]
                p = _count_proxies(conn, prefix)
            else:
                n = conn.execute("DELETE FROM observed_vectors WHERE " + _MATCH, (prefix,)).rowcount
                delete_matching(conn, _MATCH, (prefix,))  # best-effort ANN-mirror cleanup
                p = _delete_proxies(conn, prefix)
            total += n
            print(f"  {prefix!r}: {n} vectors, {p} excerpt proxies")
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return total


def _count_proxies(conn, prefix: str) -> int:
    """0 on a store predating query_proxy_vectors, rather than an error: this
    script is run against whatever db an operator points it at."""
    try:
        return conn.execute("SELECT COUNT(*) FROM query_proxy_vectors WHERE " + _PROXY_MATCH,
                            (prefix,)).fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _delete_proxies(conn, prefix: str) -> int:
    try:
        return conn.execute("DELETE FROM query_proxy_vectors WHERE " + _PROXY_MATCH,
                            (prefix,)).rowcount
    except sqlite3.OperationalError:
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Prune observed vectors for sessions matching a prefix, or whose event is gone.")
    ap.add_argument("--db", required=True, help="path to chronicle.db")
    ap.add_argument("--session-prefix", action="append", dest="prefixes", default=[], metavar="P",
                    help="session_id prefix to prune (repeatable)")
    ap.add_argument("--orphans", action="store_true",
                    help="prune vectors whose source event is no longer in the log")
    ap.add_argument("--dry-run", action="store_true", help="report what would go, delete nothing")
    args = ap.parse_args(argv)

    if not args.prefixes and not args.orphans:
        print("no --session-prefix or --orphans given; nothing to prune", file=sys.stderr)
        return 1
    if not Path(args.db).exists():
        print(f"no such db: {args.db}", file=sys.stderr)
        return 1

    print(f"{'Would prune' if args.dry_run else 'Pruning'} observed vectors in {args.db}")
    try:
        total = prune_vectors(args.db, args.prefixes, dry_run=args.dry_run) if args.prefixes else 0
        if args.orphans:
            total += prune_orphans(args.db, dry_run=args.dry_run)
    except sqlite3.Error as e:
        print(f"sqlite error: {e}", file=sys.stderr)
        return 1
    print(f"TOTAL: {total} vectors {'would be deleted (dry run)' if args.dry_run else 'deleted'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
