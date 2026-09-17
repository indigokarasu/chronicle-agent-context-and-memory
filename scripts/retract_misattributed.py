"""
Chronicle — retract memory about the user that the user never said.

Before engine/speaker.py, extraction read any line not labelled `Assistant:` as
the user's. On one production store that turned cron prompts, tool output,
compression rescue, context eviction, Hermes' control frames and Chronicle's own
recalled context into 30,018 active always-injected "directive" notes and facts
such as the user's name being the agent's. Fixing capture and extraction stops
new ones; this script removes the ones already in the projection.

A belief is RETRACTED when every channel it came from is transcript extraction
(session_transcript, rescue_extraction, context_eviction, delegation,
delegation_start, ocas_journal) and no supporting event shows the user saying
it. An event supports a belief when its attribution (the spans recorded at
capture, or the legacy reading, which never assumes the user) has human lines
and:
  * a fact's value or a note's body appears in those lines (case and whitespace
    folded), or
  * the belief is an episode, which summarises the whole turn.
A belief with any other channel in its provenance (a tool call, an explicit
agent memory write, an import such as a calendar or the people store, a
derivation) is kept: something other than transcript extraction vouches for it.
An event that is no longer in the log supports nothing.

Retraction is an event (`retracted`, reason `misattributed`), applied by the
reducer like any other, so the log keeps the original assertion and the
projection can be rebuilt; anything derived from a retracted belief is
cascaded by the reducer. One event carries a batch of belief ids (`belief_ids`,
grouped by owner): a cleanup is one decision, and a hundred thousand separate
events would put a hundred thousand transactions and git-mirror rows through a
live agent's write path.

Usage:
  python3 scripts/retract_misattributed.py --db PATH [--report FILE.jsonl] [--apply]

The default is a dry run over a read-only connection: a summary on stdout and,
with --report, one JSON line per belief it would retract (table, kind, text,
channels, and why each supporting event did not support it). --apply appends
the retractions through the engine's own append path. Run --apply with the
Chronicle build that contains engine/speaker.py and with the store backed up.

Exit codes: 0 ok, 1 usage or database error.
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

from engine import speaker as spk

EXTRACTION_SOURCES = frozenset({"session_transcript", "rescue_extraction", "context_eviction",
                                "delegation", "delegation_start", "ocas_journal"})

# table -> (kind, text column, extra columns for the report)
TABLES = {
    "facts": ("fact", "value", ("entity_id", "predicate_canonical")),
    "notes": ("note", "body", ("note_type", "subject")),
    "episodes": ("episode", "summary", ("title",)),
}

REASON = "misattributed"
_DEFAULT_BATCH = 250          # belief ids per `retracted` event


def _fold(s) -> str:
    return " ".join(str(s or "").lower().split())


def _connect_ro(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(str(Path(path).resolve())), uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


class _Events:
    """event_id -> (type, session_id, actor, payload), cached."""

    def __init__(self, conn):
        self.conn = conn
        self.cache = {}

    def get(self, eid):
        if eid not in self.cache:
            row = self.conn.execute("SELECT type, session_id, actor, payload FROM events WHERE event_id=?",
                                    (eid,)).fetchone()
            if row is None:
                self.cache[eid] = None
            else:
                try:
                    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else {}
                except ValueError:
                    payload = {}
                self.cache[eid] = (row["type"], row["session_id"] or "", row["actor"] or "", payload)
        return self.cache[eid]


def _channels(provenance) -> tuple:
    """(source types, provenance source events) from a provenance column."""
    try:
        p = json.loads(provenance or "{}")
    except ValueError:
        return None, []
    if not isinstance(p, dict):
        return None, []
    entries = [p] + [e for e in (p.get("provenances") or []) if isinstance(e, dict)]
    types = {e.get("source_type") for e in entries if e.get("source_type")}
    events = [e.get("source_event") for e in entries if e.get("source_event")]
    return types, events


def _observed_ids(events: _Events, belief_id, prov_events, conn) -> list:
    """Observed event ids behind a belief: its justifications, plus provenance
    entries (which may name the asserting event rather than the observed one)."""
    ids = [r[0] for r in conn.execute(
        "SELECT support FROM justifications WHERE belief_id=? AND support_kind='event'", (belief_id,))]
    for eid in prov_events:
        ev = events.get(eid)
        if ev and ev[0] == "asserted":
            src = ev[3].get("source_event")
            if src:
                ids.append(src)
        else:
            ids.append(eid)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _judge(events: _Events, kind, text, observed_ids) -> tuple:
    """(supported, [why not, per event])."""
    why = []
    want = _fold(text)
    for eid in observed_ids:
        ev = events.get(eid)
        if ev is None:
            why.append("event no longer in the log")
            continue
        etype, sid, actor, payload = ev
        if etype != "observed":
            why.append("support is a %s event" % etype)
            continue
        lines = spk.attribute_lines(payload, session_id=sid, actor=actor)
        if not spk.has_human(lines):
            who = sorted({w for _, w in lines}) or ["nothing"]
            why.append("no words by the user (%s%s)" % ("/".join(who),
                                                      ", cron session" if spk.is_automation_session(sid) else ""))
            continue
        if kind == "episode" or (want and want in _fold(spk.human_text(lines))):
            return True, []
        why.append("not in the user's words")
    if not observed_ids:
        why.append("no supporting event recorded")
    return False, why


def scan(db_path: str):
    """Yield (verdict, record) for every candidate belief; verdict is 'retract' or 'keep'."""
    conn = _connect_ro(db_path)
    events = _Events(conn)
    try:
        for table, (kind, col, extra) in TABLES.items():
            cols = ", ".join(("belief_id", col, "owner", "status", "provenance") + extra)
            for row in conn.execute("SELECT %s FROM %s WHERE status IN ('active','draft')" % (cols, table)):
                types, prov_events = _channels(row["provenance"])
                if not types or not types <= EXTRACTION_SOURCES:
                    continue  # another channel vouches for it, or provenance is unreadable
                obs = _observed_ids(events, row["belief_id"], prov_events, conn)
                supported, why = _judge(events, kind, row[col], obs)
                rec = {"table": table, "kind": kind, "belief_id": row["belief_id"],
                       "owner": row["owner"], "status": row["status"], "text": row[col],
                       "channels": sorted(types), "support": obs}
                rec.update({k: row[k] for k in extra})
                if supported:
                    yield "keep", rec
                else:
                    rec["why"] = why
                    yield "retract", rec
    finally:
        conn.close()


def _label(rec) -> str:
    if rec["kind"] == "fact":
        return "fact %s.%s" % ("user" if rec["entity_id"] == "user" else "entity", rec["predicate_canonical"])
    if rec["kind"] == "note":
        return "note %s/%s" % (rec["note_type"], rec["subject"])
    return rec["kind"]


def apply(db_path: str, records, batch: int = _DEFAULT_BATCH) -> tuple:
    """Append the retractions. Returns (beliefs, events)."""
    from engine.capture import CaptureEngine
    from engine.config import Config
    from engine.reducer import Reducer
    from engine.store import MemoryStore
    by_owner = collections.defaultdict(list)
    for rec in records:
        by_owner[rec["owner"] or "default"].append(rec["belief_id"])
    store = MemoryStore(db_path)
    try:
        reducer = Reducer(store, None, Config({}))
        capture = CaptureEngine(store, reducer, cfg=Config({}))
        beliefs = events = 0
        for owner, ids in sorted(by_owner.items()):
            for i in range(0, len(ids), max(1, batch)):
                chunk = ids[i:i + batch]
                capture.append("retracted", {"belief_ids": chunk, "reason": REASON},
                               actor="curator", owner=owner)
                beliefs += len(chunk)
                events += 1
                if events % 20 == 0:
                    print("  retracted %d of %d beliefs" % (beliefs, len(records)), flush=True)
        return beliefs, events
    finally:
        store.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Retract memory about the user that the user never said.")
    ap.add_argument("--db", required=True, help="path to chronicle.db")
    ap.add_argument("--report", help="write one JSON line per belief to retract")
    ap.add_argument("--apply", action="store_true", help="append the retractions (default: dry run)")
    ap.add_argument("--batch", type=int, default=_DEFAULT_BATCH, metavar="N",
                    help="belief ids per retracted event (default %d)" % _DEFAULT_BATCH)
    args = ap.parse_args(argv)
    if not Path(args.db).is_file():
        print("no database at %s" % args.db, file=sys.stderr)
        return 1

    retract, kept = [], collections.Counter()
    by_label = collections.Counter()
    samples = collections.defaultdict(list)
    try:
        for verdict, rec in scan(args.db):
            if verdict == "keep":
                kept[_label(rec)] += 1
                continue
            retract.append(rec)
            label = "%s [%s]" % (_label(rec), ",".join(rec["channels"]))
            by_label[label] += 1
            if len(samples[label]) < 3:
                samples[label].append(str(rec["text"] or "")[:100])
    except sqlite3.Error as e:
        print("database error: %s" % e, file=sys.stderr)
        return 1

    print("would retract %d beliefs:" % len(retract) if not args.apply else "retracting %d beliefs:" % len(retract))
    for label, n in by_label.most_common():
        print("  %7d  %s" % (n, label))
        for s in samples[label]:
            print("           e.g. %r" % s)
    print("kept (transcript-derived and said by the user): %d" % sum(kept.values()))
    for label, n in kept.most_common():
        print("  %7d  %s" % (n, label))

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            for rec in retract:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        print("report: %s" % args.report)

    if args.apply and retract:
        try:
            n, events = apply(args.db, retract, batch=args.batch)
        except sqlite3.Error as e:
            print("database error while applying: %s" % e, file=sys.stderr)
            return 1
        print("retracted %d beliefs in %d event(s)" % (n, events))
    return 0


if __name__ == "__main__":
    sys.exit(main())
