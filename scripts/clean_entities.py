"""
Chronicle — repair the entity rows a store already holds.

`entities` is a projection: rows derived from the log, with no status of their
own, so unlike a belief an entity is not retracted — it is rebuilt. This script
applies the rules in engine/entities.py to a store that was built before them,
which is what a rebuild would do without replaying 400,000 events on a live box.

Measured on a production store's 1,488 rows:

  * 433 are not names: pronouns ("This", "There", "Each one"), sentence
    fragments ("So any flow that needs a browser I hold but can't bridge to"),
    and two lowercase tokens ("user", "indigo"). The reducer now refuses them,
    so a rebuild would drop them;
  * 1,003 are named by another store's id, and 991 of those have a `name` fact
    right beside them ("Pat Testley", "Robin Placeholder"); the reducer now
    applies that name when the fact arrives, but the rows already written keep
    the id;
  * entities existed TWICE — a hash-keyed row carrying the type and a
    token-keyed row carrying the facts — because the extractor's entity token
    never reached the fold. One of each pair is a duplicate of the other.

What it does, and nothing else:

  DROP       a row whose name is not a name AND that no fact points at.
  RENAME     an id-named row to the name the log asserts for that id.
  MERGE      the hash-keyed half of a "one entity, two rows" pair into the
             token-keyed row facts point at, keeping the type it carried. Two
             rows that merely share a NAME are never merged: two people called
             the same thing are the ordinary case, and identity is adjudicated,
             never inferred (the identity sweep files those as candidates).
  CLEAR TYPE a type that is a clause rather than a category ("dead end for
             getting a usable key into my environment").

A row that any fact points at is never dropped, whatever its name: the facts
are the memory, and an entity id with no row behind it is a dangling reference.
That includes `user`, the principal's own row, whose name is not a proper noun.
A name another store asserts is taken as it stands (see entities.resolve_name),
so a rename never makes a row droppable — running this twice changes nothing
the second time.

Usage:
  python3 scripts/clean_entities.py --db PATH [--report FILE.jsonl] [--apply]

Dry run by default. Exit codes: 0 ok, 1 usage or database error.
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import entities as ents


# The principal's own row: every fact about the user points at it, and "user" is
# not a proper noun.
_NEVER_DROP = frozenset({"user"})


def _connect(path: str, write: bool) -> sqlite3.Connection:
    uri = "file:%s" % urllib.parse.quote(str(Path(path).resolve()))
    conn = sqlite3.connect(uri if write else uri + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def plan(conn) -> list:
    """The repairs this store needs, in the order they must be applied."""
    rows = [dict(r) for r in conn.execute(
        "SELECT belief_id, type, name, normalized_name, owner, domain, aliases, fact_count "
        "FROM entities")]
    # Only LIVE facts hold a row open: a retracted fact is not memory any more,
    # so the junk entity it used to point at is free to go (run
    # scripts/retract_misattributed.py first).
    referenced = {r[0] for r in conn.execute(
        "SELECT DISTINCT entity_id FROM facts WHERE entity_id IS NOT NULL AND entity_id != '' "
        "AND status IN ('active','draft')")}
    named = {r[0]: r[1] for r in conn.execute(
        "SELECT entity_id, value FROM facts WHERE predicate_canonical='name' AND status='active'")}

    out = []
    by_name = collections.defaultdict(list)
    for row in rows:
        keeps_facts = row["belief_id"] in referenced or row["belief_id"] in _NEVER_DROP
        readable = ents.plausible_name(row["name"]) or ents.is_id_like(row["name"])
        if not readable and not keeps_facts:
            out.append({"action": "drop", "belief_id": row["belief_id"], "name": row["name"],
                        "type": row["type"], "referenced": False})
            continue
        if row["type"] and not ents.plausible_type(row["type"]):
            out.append({"action": "clear_type", "belief_id": row["belief_id"],
                        "name": row["name"], "type": row["type"],
                        "referenced": keeps_facts})
        by_name[(row["normalized_name"], row["owner"], row["domain"])].append(row)

    for (_norm, _owner, _domain), group in sorted(by_name.items()):
        # The pair this repairs is ONE entity written as two rows by the old
        # extractor: a content-hash row carrying the type, and the token row the
        # facts point at. Anything else that shares a name is left alone.
        hash_rows = [r for r in group if r["belief_id"].startswith("b_")]
        others = [r for r in group if not r["belief_id"].startswith("b_")]
        survivor = None
        if hash_rows and len(others) == 1:
            survivor = others[0]
            for dup in hash_rows:
                carried = dup["type"] if ents.plausible_type(dup["type"]) else ""
                out.append({"action": "merge", "belief_id": dup["belief_id"],
                            "into": survivor["belief_id"], "name": dup["name"],
                            "type": carried,   # a clause is not a type worth carrying over
                            "referenced": dup["belief_id"] in referenced})
        merged = {r["belief_id"] for r in hash_rows} if survivor is not None else set()
        for row in group:
            if row["belief_id"] in merged:
                continue
            resolved = ents.resolve_name(row["name"], named.get(row["belief_id"]))
            if resolved != row["name"]:
                out.append({"action": "rename", "belief_id": row["belief_id"],
                            "name": row["name"], "to": resolved, "type": row["type"],
                            "referenced": row["belief_id"] in referenced})
    return out


def apply(conn, repairs) -> dict:
    counts = collections.Counter()
    with conn:
        for rep in repairs:
            bid = rep["belief_id"]
            if rep["action"] == "drop":
                conn.execute("DELETE FROM entities WHERE belief_id=?", (bid,))
                conn.execute("DELETE FROM justifications WHERE belief_id=?", (bid,))
            elif rep["action"] == "merge":
                keep = rep["into"]
                if rep.get("type"):
                    conn.execute("UPDATE entities SET type=? WHERE belief_id=? AND "
                                 "(type IS NULL OR type='')", (rep["type"], keep))
                conn.execute("UPDATE entities SET fact_count=fact_count+"
                             "(SELECT fact_count FROM entities WHERE belief_id=?) "
                             "WHERE belief_id=?", (bid, keep))
                conn.execute("UPDATE justifications SET belief_id=? WHERE belief_id=?", (keep, bid))
                conn.execute("DELETE FROM entities WHERE belief_id=?", (bid,))
            elif rep["action"] == "clear_type":
                conn.execute("UPDATE entities SET type='' WHERE belief_id=?", (bid,))
            elif rep["action"] == "rename":
                conn.execute("UPDATE entities SET name=?, normalized_name=? WHERE belief_id=?",
                             (rep["to"], rep["to"].lower(), bid))
            counts[rep["action"]] += 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Repair entity rows written before engine/entities.py.")
    ap.add_argument("--db", required=True, help="path to chronicle.db")
    ap.add_argument("--report", help="write one JSON line per repair")
    ap.add_argument("--apply", action="store_true", help="apply the repairs (default: dry run)")
    args = ap.parse_args(argv)
    if not Path(args.db).is_file():
        print("no database at %s" % args.db, file=sys.stderr)
        return 1

    conn = _connect(args.db, write=args.apply)
    try:
        repairs = plan(conn)
        counts = collections.Counter(r["action"] for r in repairs)
        total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        print("%d entity rows; %d repairs" % (total, len(repairs)))
        for action in ("drop", "merge", "rename", "clear_type"):
            if not counts[action]:
                continue
            print("  %-7s %6d" % (action, counts[action]))
            for rep in [r for r in repairs if r["action"] == action][:3]:
                print("          e.g. %r%s" % (str(rep["name"])[:60],
                                               " -> %r" % rep["to"] if action == "rename" else ""))
        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                for rep in repairs:
                    fh.write(json.dumps(rep, ensure_ascii=False, sort_keys=True) + "\n")
            print("report: %s" % args.report)
        if args.apply and repairs:
            done = apply(conn, repairs)
            print("applied: %s" % dict(done))
            print("%d entity rows remain" % conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
        elif not args.apply:
            print("(dry run; nothing written)")
    except sqlite3.Error as e:
        print("database error: %s" % e, file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
