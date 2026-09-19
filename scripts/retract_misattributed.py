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
import time
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
_DEFAULT_BATCH = 100          # belief ids per `retracted` event
_RETRIES = 6                  # per batch, on a write lock held by the live agent


def _fold(s) -> str:
    return " ".join(str(s or "").lower().split())


def _connect_ro(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(str(Path(path).resolve())), uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


class _Events:
    """event_id -> (type, session_id, actor, payload), cached.

    BOUNDED. Beliefs share supporting events, so a cache pays for itself, but an
    unbounded one holds every payload it has seen: on the production store this
    run reached 697 MB of RSS behind a live agent on a box with an OOM history.
    At the cap the whole cache is dropped rather than evicted one by one — the
    work is a single ordered pass, so the next belief's events are re-read at
    most once."""

    _CAP = 20000

    def __init__(self, conn):
        self.conn = conn
        self.cache = {}

    def get(self, eid):
        if eid not in self.cache:
            if len(self.cache) >= self._CAP:
                self.cache.clear()
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


def justification_map(conn) -> dict:
    """`belief_id -> [supporting event ids]`, in one pass for the same reason
    `human_events` exists: 112,652 single-row queries is not a plan."""
    out = collections.defaultdict(list)
    try:
        for bid, support in conn.execute(
                "SELECT belief_id, support FROM justifications WHERE support_kind='event'"):
            out[bid].append(support)
    except sqlite3.Error:
        return {}
    return out


def _observed_ids(events: _Events, belief_id, prov_events, just) -> list:
    """Observed event ids behind a belief: its justifications, plus provenance
    entries (which may name the asserting event rather than the observed one)."""
    ids = list(just.get(belief_id, ()))
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


def human_events(conn) -> dict:
    """`event_id -> whether the user's own words are in it`, for every observed event.

    ONE sequential pass instead of a random read per belief: the beliefs to
    judge share their supporting events, and on the production store the
    per-belief reads were 112,652 lookups over a 3 GB file behind a live agent
    on a CPU-capped box — the scan moved 132 rows in ten minutes.

    A scheduled job's session is answered without parsing its payload at all:
    its user side is automation by construction (engine/speaker.py), whether the
    event carries spans or predates them, and 98% of a production store's turns
    are that. What is left is small enough to read properly."""
    out = {}
    for eid, sid, actor, payload in conn.execute(
            "SELECT event_id, session_id, actor, payload FROM events WHERE type='observed'"):
        sid = sid or ""
        if spk.is_automation_session(sid):
            out[eid] = False
            continue
        try:
            p = json.loads(payload) if isinstance(payload, str) else {}
        except ValueError:
            p = {}
        out[eid] = spk.has_human(spk.attribute_lines(p, session_id=sid, actor=actor or ""))
    return out


def _judge(events: _Events, kind, text, observed_ids, human) -> tuple:
    """(supported, [why not, per event]).

    `human` is the map from `human_events`; a payload is read only for an event
    that has the user in it at all, which is where the text has to be checked."""
    why = []
    want = _fold(text)
    for eid in observed_ids:
        has_human = human.get(eid)
        if has_human is None:              # not an observed event in this log
            ev = events.get(eid)
            if ev is None:
                why.append("event no longer in the log")
            else:
                why.append("support is a %s event" % ev[0])
            continue
        if not has_human:
            why.append("no words by the user")
            continue
        if kind == "episode":
            return True, []
        ev = events.get(eid)
        if ev is None:                     # deleted between the pass and here
            why.append("event no longer in the log")
            continue
        lines = spk.attribute_lines(ev[3], session_id=ev[1], actor=ev[2])
        if want and want in _fold(spk.human_text(lines)):
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
        human = human_events(conn)
        just = justification_map(conn)
        for table, (kind, col, extra) in TABLES.items():
            cols = ", ".join(("belief_id", col, "owner", "status", "provenance") + extra)
            for row in conn.execute("SELECT %s FROM %s WHERE status IN ('active','draft')" % (cols, table)):
                types, prov_events = _channels(row["provenance"])
                if not types or not types <= EXTRACTION_SOURCES:
                    continue  # another channel vouches for it, or provenance is unreadable
                obs = _observed_ids(events, row["belief_id"], prov_events, just)
                supported, why = _judge(events, kind, row[col], obs, human)
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


def apply(db_path: str, targets, batch: int = _DEFAULT_BATCH) -> tuple:
    """Append the retractions for `(belief_id, owner)` pairs. Returns (beliefs, events)."""
    from engine.capture import CaptureEngine
    from engine.config import Config
    from engine.reducer import Reducer
    from engine.store import MemoryStore
    by_owner = collections.defaultdict(list)
    for belief_id, owner in targets:
        by_owner[owner or "default"].append(belief_id)
    store = MemoryStore(db_path)
    try:
        reducer = Reducer(store, None, Config({}))
        capture = CaptureEngine(store, reducer, cfg=Config({}))
        beliefs = events = waits = 0
        for owner, ids in sorted(by_owner.items()):
            for i in range(0, len(ids), max(1, batch)):
                chunk = ids[i:i + batch]
                waits += _append_with_retry(capture, chunk, owner)
                beliefs += len(chunk)
                events += 1
                if events % 20 == 0:
                    print("  retracted %d of %d beliefs (%d lock waits)"
                          % (beliefs, len(targets), waits), flush=True)
        if waits:
            print("  waited for the store's write lock %d time(s)" % waits, flush=True)
        return beliefs, events
    finally:
        store.close()


def _append_with_retry(capture, chunk, owner) -> int:
    """Append one retraction, waiting out the live agent's write lock.

    A cleanup runs against a store an agent is still writing to, and SQLite has
    one writer: on the production box the apply reached 17 batches and then died
    with "database is locked" — the run is restartable (a retracted belief is no
    longer a candidate), but stopping on the first collision means babysitting a
    two-hour job. Returns the number of waits so the run reports contention
    rather than hiding it."""
    delay, waits = 2.0, 0
    for attempt in range(_RETRIES):
        try:
            capture.append("retracted", {"belief_ids": chunk, "reason": REASON},
                           actor="curator", owner=owner)
            return waits
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() and "busy" not in str(e).lower():
                raise
            if attempt == _RETRIES - 1:
                raise
            waits += 1
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    return waits


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

    # Streamed, not collected: the report goes to disk as it is decided and only
    # the ids to retract stay in memory. Holding every record cost 438 MB of RSS
    # on the production store, behind a live agent on a box with an OOM history.
    retract, kept = [], collections.Counter()
    by_label = collections.Counter()
    samples = collections.defaultdict(list)
    report_fh = None
    try:
        if args.report:
            report_fh = open(args.report, "w", encoding="utf-8")
        for verdict, rec in scan(args.db):
            if verdict == "keep":
                kept[_label(rec)] += 1
                continue
            retract.append((rec["belief_id"], rec["owner"]))
            label = "%s [%s]" % (_label(rec), ",".join(rec["channels"]))
            by_label[label] += 1
            if len(samples[label]) < 3:
                samples[label].append(str(rec["text"] or "")[:100])
            if report_fh:
                report_fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    except sqlite3.Error as e:
        print("database error: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("cannot write the report: %s" % e, file=sys.stderr)
        return 1
    finally:
        if report_fh:
            report_fh.close()

    print("would retract %d beliefs:" % len(retract) if not args.apply else "retracting %d beliefs:" % len(retract))
    for label, n in by_label.most_common():
        print("  %7d  %s" % (n, label))
        for s in samples[label]:
            print("           e.g. %r" % s)
    print("kept (transcript-derived and said by the user): %d" % sum(kept.values()))
    for label, n in kept.most_common():
        print("  %7d  %s" % (n, label))

    if args.report:
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
