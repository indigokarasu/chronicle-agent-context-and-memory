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

Usage:  python3 scripts/prune_vectors.py --db PATH --session-prefix P [--session-prefix Q]... [--dry-run]

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


def prune_vectors(db_path: str, prefixes: list[str], dry_run: bool = False) -> int:
    """Delete (or with dry_run only count) observed_vectors for each prefix.

    Returns the total reported. A real run deletes each row once; a dry run
    reports per prefix, so overlapping prefixes are counted once each."""
    conn = sqlite3.connect(db_path)
    total = 0
    try:
        for prefix in prefixes:
            if dry_run:
                n = conn.execute("SELECT COUNT(*) FROM observed_vectors WHERE " + _MATCH,
                                 (prefix,)).fetchone()[0]
            else:
                n = conn.execute("DELETE FROM observed_vectors WHERE " + _MATCH, (prefix,)).rowcount
                delete_matching(conn, _MATCH, (prefix,))  # best-effort ANN-mirror cleanup
            total += n
            print(f"  {prefix!r}: {n} vectors")
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="Prune observed vectors for sessions matching a prefix.")
    ap.add_argument("--db", required=True, help="path to chronicle.db")
    ap.add_argument("--session-prefix", action="append", dest="prefixes", default=[], metavar="P",
                    help="session_id prefix to prune (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="report what would go, delete nothing")
    args = ap.parse_args()

    if not args.prefixes:
        print("no --session-prefix given; nothing to prune", file=sys.stderr)
        return 1
    if not Path(args.db).exists():
        print(f"no such db: {args.db}", file=sys.stderr)
        return 1

    print(f"{'Would prune' if args.dry_run else 'Pruning'} observed vectors in {args.db}")
    try:
        total = prune_vectors(args.db, args.prefixes, dry_run=args.dry_run)
    except sqlite3.Error as e:
        print(f"sqlite error: {e}", file=sys.stderr)
        return 1
    print(f"TOTAL: {total} vectors {'would be deleted (dry run)' if args.dry_run else 'deleted'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
