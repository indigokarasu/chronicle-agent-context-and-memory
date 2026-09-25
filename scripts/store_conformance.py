#!/usr/bin/env python3
"""
Chronicle — invariants that must hold on a REAL store.

WHY THIS EXISTS. The suite had 2,370 passing tests while, on the production
store: the session vector index was 94% wrong-geometry, 7,612 vectors sat in
the wrong table, and extraction had produced 63,000 beliefs from conversation
of which exactly zero were still active. Not one test failed, and they could
not have: every one of them builds a fresh temp store, writes three or four
fixtures and asserts on them. A fresh store has one embedder, correct table
routing, no history and no drift. Those tests check that the CODE is
self-consistent against data the test itself just made. Nothing checked the
data that actually accumulated.

So this is not more unit tests. It reads a real store and asserts things that
only a real store can be wrong about — a model switch that left two geometries
behind, a backfill that filed rows in the wrong table, a pruning that removed
months, an extractor whose whole output was later retracted.

Each check names the number it found. A check that cannot be evaluated says so
rather than passing: "no data" is not "healthy".

    python store_conformance.py <chronicle.db> [--json]

Exit 0 = every check passed. Exit 2 = at least one failed. Read-only: the
database is opened mode=ro and nothing here writes.
"""
from __future__ import annotations

import json
import sqlite3
import sys

VECTOR_TABLES = (("observed_vectors", "event_id"), ("memory_vectors", "belief_id"),
                 ("session_index", "session_id"), ("projection_vectors", None),
                 ("query_proxy_vectors", None))
BELIEF_TABLES = ("facts", "notes", "episodes")


class Result:
    def __init__(self, name, ok, detail, found=None, why=""):
        self.name, self.ok, self.detail, self.found, self.why = name, ok, detail, found, why

    def line(self):
        mark = "PASS" if self.ok is True else ("FAIL" if self.ok is False else "n/a ")
        return "  [%s] %-34s %s" % (mark, self.name, self.detail)


def _tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def one_embedding_geometry(db, present):
    """A store must speak ONE embedding geometry. Two means a model changed and
    the older rows are invisible to the vector channel -- not scored, not
    ranked, not retrieved. Found on production: 2048-dim rows beside 768-dim
    ones, and a gguf path beside a canonical tag."""
    seen = {}
    for table, _key in VECTOR_TABLES:
        if table not in present:
            continue
        for model, dims, n in db.execute(
                "SELECT COALESCE(model,'(none)'), LENGTH(embedding)/4, COUNT(*) FROM %s "
                "WHERE embedding IS NOT NULL GROUP BY 1,2" % table):
            seen[(model, dims)] = seen.get((model, dims), 0) + n
    if not seen:
        return Result("one embedding geometry", None, "no vectors in this store")
    widths = {d for (_m, d) in seen}
    tags = {m for (m, _d) in seen}
    if len(widths) == 1 and len(tags) == 1:
        return Result("one embedding geometry", True,
                      "%d vectors, all %s @ %d dims" % (sum(seen.values()), list(tags)[0], list(widths)[0]))
    worst = sorted(seen.items(), key=lambda kv: -kv[1])[:4]
    return Result("one embedding geometry", False,
                  "%d geometries: %s" % (len(seen), ", ".join(
                      "%s@%d=%d" % (m, d, n) for (m, d), n in worst)),
                  found=len(seen))


def vectors_filed_in_the_right_table(db, present):
    """observed_vectors is for OBSERVED events. A backfill filed 7,612 belief
    and signal vectors there; they have no excerpt to re-embed from, so the
    repair tool could never fix them, and they pollute conversation search with
    rows that are not conversation."""
    if "observed_vectors" not in present or "events" not in present:
        return Result("vectors filed correctly", None, "no observed_vectors/events")
    rows = db.execute(
        "SELECT COALESCE(e.type,'(missing event)'), COUNT(*) FROM observed_vectors v "
        "LEFT JOIN events e ON e.event_id = v.event_id GROUP BY 1").fetchall()
    total = sum(n for _t, n in rows)
    wrong = [(t, n) for t, n in rows if t != "observed"]
    if not total:
        return Result("vectors filed correctly", None, "observed_vectors is empty")
    if not wrong:
        return Result("vectors filed correctly", True, "all %d rows are observed events" % total)
    return Result("vectors filed correctly", False,
                  "%d of %d are not observed events: %s" % (
                      sum(n for _t, n in wrong), total,
                      ", ".join("%s=%d" % (t, n) for t, n in wrong)),
                  found=sum(n for _t, n in wrong))


def conversation_produced_memory(db, present):
    """The point of the system. If extraction ran and EVERY belief it made was
    later retracted, the store learned nothing from talking -- which is true on
    production: 63,000 extracted, 0 active. A store that never ran extraction
    is 'n/a'; a store that ran it and kept nothing is a FAILURE."""
    made = kept = 0
    for table in BELIEF_TABLES:
        if table not in present:
            continue
        for status, n in db.execute(
                "SELECT status, COUNT(*) FROM %s WHERE "
                "json_extract(provenance,'$.source_type')='session_transcript' GROUP BY 1" % table):
            made += n
            if status == "active":
                kept += n
    if not made:
        return Result("conversation produced memory", None, "extraction has never run here")
    if kept:
        return Result("conversation produced memory", True,
                      "%d active of %d extracted (%.1f%%)" % (kept, made, 100.0 * kept / made))
    return Result("conversation produced memory", False,
                  "%d extracted from conversation, 0 still active" % made, found=made)


def capture_is_continuous(db, present, max_gap_days=3):
    """Capture that silently stops is the failure nobody notices. Reports the
    largest gap between consecutive days that have any observed event."""
    if "events" not in present:
        return Result("capture is continuous", None, "no events table")
    days = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(recorded_at,1,10) d FROM events WHERE type='observed' "
        "AND recorded_at IS NOT NULL ORDER BY d")]
    if len(days) < 2:
        return Result("capture is continuous", None, "fewer than two days of capture")
    import datetime
    worst, when = 0, ""
    prev = None
    for d in days:
        try:
            cur = datetime.date.fromisoformat(d)
        except ValueError:
            continue
        if prev is not None:
            gap = (cur - prev).days
            if gap > worst:
                worst, when = gap, "%s -> %s" % (prev.isoformat(), d)
        prev = cur
    ok = worst <= max_gap_days
    return Result("capture is continuous", ok,
                  "largest gap %d day(s)%s; %s .. %s" % (worst, " (%s)" % when if when else "",
                                                          days[0], days[-1]),
                  found=worst)


def session_index_is_usable(db, present, floor=0.80):
    """The channel that decides WHICH session is relevant. Rows whose geometry
    does not match the majority are invisible, so a mostly-broken index means
    semantic session search is blind even though every unit test passes."""
    if "session_index" not in present:
        return Result("session index is usable", None, "no session_index table")
    rows = db.execute("SELECT LENGTH(embedding)/4 d, COUNT(*) FROM session_index "
                      "WHERE embedding IS NOT NULL GROUP BY 1").fetchall()
    total = sum(n for _d, n in rows)
    if not total:
        return Result("session index is usable", None, "session_index has no vectors")

    # NOT the majority inside this table. The first version of this check
    # measured the share of session_index's OWN majority geometry, which means
    # a 94%-broken index reads as 94% healthy -- it would have blessed exactly
    # the state it exists to catch. Usable means "matches what the store is
    # writing NOW", so the reference is observed_vectors, the table that is
    # appended to continuously.
    ref = None
    if "observed_vectors" in present:
        ref_rows = db.execute("SELECT LENGTH(embedding)/4 d, COUNT(*) FROM observed_vectors "
                              "WHERE embedding IS NOT NULL GROUP BY 1").fetchall()
        if ref_rows:
            ref = max(ref_rows, key=lambda r: r[1])[0]
    if ref is None:
        return Result("session index is usable", None,
                      "no observed_vectors to say which geometry is current")
    usable = sum(n for d, n in rows if d == ref)
    share = usable / float(total)
    return Result("session index is usable", share >= floor,
                  "%d of %d rows match the live geometry (%d dims) = %.1f%%"
                  % (usable, total, ref, 100.0 * share), found=round(share, 3))


def automation_is_not_embedded(db, present, tolerate=0.05):
    """Embedding cron turns is paid twice and used never.

    Per-turn recall passes exclude_automation=True, so an automation vector is
    never retrieved on a turn -- and the index is brute force
    (vector_index.backend), so every vector is scanned by every search. On the
    production store 66,332 cron events were embedded against 3,741
    interactive ones: ~95% of the scan cost, for rows the live path refuses by
    construction. `embeddings.exclude_session_prefixes` exists to stop this;
    this asserts it is actually being honoured rather than merely declared.

    Measured on RECENT events only -- the historical backlog predates the
    setting and a check that fails forever on old data is one people stop
    reading."""
    if "observed_vectors" not in present or "events" not in present:
        return Result("automation is not embedded", None, "no observed_vectors/events")
    recent = db.execute(
        "SELECT MAX(recorded_at) FROM events WHERE type='observed'").fetchone()[0]
    if not recent:
        return Result("automation is not embedded", None, "no observed events")
    cutoff = recent[:10]
    row = db.execute(
        "SELECT COUNT(*), SUM(CASE WHEN v.event_id IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM events e LEFT JOIN observed_vectors v ON v.event_id = e.event_id "
        "WHERE e.type='observed' AND e.session_id LIKE 'cron_%' AND substr(e.recorded_at,1,10) >= ?",
        (cutoff,)).fetchone()
    total, embedded = row[0] or 0, row[1] or 0
    if not total:
        return Result("automation is not embedded", None,
                      "no cron events on %s to judge" % cutoff)
    share = embedded / float(total)
    return Result("automation is not embedded", share <= tolerate,
                  "%d of %d cron events on %s are embedded = %.1f%%"
                  % (embedded, total, cutoff, 100.0 * share), found=round(share, 3))


CHECKS = (one_embedding_geometry, vectors_filed_in_the_right_table,
          conversation_produced_memory, capture_is_continuous, session_index_is_usable,
          automation_is_not_embedded)


def run(db_path):
    db = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    present = _tables(db)
    return [fn(db, present) for fn in CHECKS]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    results = run(argv[1])
    if "--json" in argv:
        print(json.dumps([{"check": r.name, "ok": r.ok, "detail": r.detail} for r in results],
                         indent=1))
    else:
        print("Chronicle store conformance: %s" % argv[1])
        for r in results:
            print(r.line())
        bad = [r for r in results if r.ok is False]
        na = [r for r in results if r.ok is None]
        print("\n%d passed, %d FAILED, %d not applicable"
              % (len(results) - len(bad) - len(na), len(bad), len(na)))
    return 2 if any(r.ok is False for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
