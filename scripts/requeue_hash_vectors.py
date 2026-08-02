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

Usage:  python3 scripts/requeue_hash_vectors.py <db_path> [--dry-run]

Exit codes: 0 = done   1 = usage / db error
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.embeddings import _HASHING_NAMES
from engine.store import MemoryStore

# The exact column the reducer vectorised, per belief kind (reducer._write_belief:
# `text = body or key.name or key.topic`, and `body` lands in these columns).
_BELIEF_TEXT = {"fact": ("facts", "value"), "episode": ("episodes", "summary"),
                "note": ("notes", "body"), "reference": ("refs", "cached_summary"),
                "procedure": ("procedures", "name")}
_MODELS = tuple(sorted(_HASHING_NAMES))
_MARKS = ",".join("?" * len(_MODELS))


def _scan(conn):
    """(target_id, kind, text) for every hash-embedded vector row. Read-only, and
    schema-agnostic so it also runs against an un-migrated store."""
    out = []
    for row in conn.execute(f"SELECT event_id FROM observed_vectors WHERE model IN ({_MARKS})",
                            _MODELS).fetchall():
        eid = row[0]
        ev = conn.execute("SELECT payload FROM events WHERE event_id=?", (eid,)).fetchone()
        payload = json.loads(ev[0]) if ev and isinstance(ev[0], str) else (ev[0] if ev else {})
        out.append((eid, "observed", (payload or {}).get("excerpt", "")))
    for row in conn.execute(f"SELECT belief_id, kind FROM memory_vectors WHERE model IN ({_MARKS})",
                            _MODELS).fetchall():
        bid, kind = row[0], row[1]
        table, col = _BELIEF_TEXT.get(kind, (None, None))
        text = ""
        if table:
            b = conn.execute(f"SELECT {col} FROM {table} WHERE belief_id=?", (bid,)).fetchone()
            text = (b[0] or "") if b else ""
        out.append((bid, kind, text))
    return out


def _report(prefix, rows, queued, deleted):
    orphans = sum(1 for _, _, text in rows if not text)
    print(f"{prefix}hash vectors found : {len(rows)}")
    print(f"{prefix}embed jobs queued  : {queued}")
    print(f"{prefix}vector rows deleted: {deleted}")
    if orphans:
        print(f"{prefix}  ({orphans} had no recoverable source text — deleted, not requeued)")


def requeue(db_path: str, dry_run: bool = False) -> int:
    path = Path(db_path).expanduser()
    if not path.exists():
        print(f"ERROR: no database at {path}")
        return 1

    if dry_run:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = _scan(conn)
        finally:
            conn.close()
        _report("[dry-run] ", rows, sum(1 for _, _, t in rows if t), len(rows))
        return 0

    store = MemoryStore(str(path))          # migrates the schema (see module docstring)
    queued = 0
    with store.transaction() as conn:       # delete + enqueue land together or not at all
        rows = _scan(conn)
        for target, kind, text in rows:
            if text and store.enqueue_embed_job(target, kind, text) is not None:
                queued += 1
        conn.execute(f"DELETE FROM observed_vectors WHERE model IN ({_MARKS})", _MODELS)
        conn.execute(f"DELETE FROM memory_vectors WHERE model IN ({_MARKS})", _MODELS)
    _report("", rows, queued, len(rows))
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        print(__doc__)
        return 1
    return requeue(args[0], dry_run="--dry-run" in sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
