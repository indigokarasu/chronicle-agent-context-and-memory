#!/usr/bin/env python3
"""
Chronicle abstain-gate sweep (§18.4, I8) — pick retrieval.abstain_gate.

Sweeps the pluggable support gate (`RetrievalEngine._support_gate`) over a
parameter grid and reports, per config:
  - abstained/30      on the LongMemEval `_abs` (unanswerable) instances
  - false-abstain/N   on the first N answerable instances (default 100)

Each instance gets a FRESH temp home, for the same reason lme_recall.py does:
Chronicle's core is a per-home singleton, so a shared home would let one
instance answer from another's memory — and answer() writes (promote-on-read,
curation queue), so a shared home would also contaminate the next config.

Selection (in this order):
  1. abstained >= 20/30 AND false-abstain <= 5/N  — the spec's bar.
  2. otherwise ACCEPTANCE-FIRST: among configs clearing abstained >= 20/30,
     the one with the fewest false abstains. The harness acceptance line
     (lme_recall.py ABSTENTION >= 20/30) is the contract; the false-abstain
     budget is advisory, so it is reported as a cost, not used to veto.
  3. the advisory rule (max abstained with false-abstain <= 8) is printed too,
     so the trade-off both rules imply is visible side by side.

The score grid stops at 0.03 on purpose: a Tier-1 RRF score is bounded by
(fts_weight + vector_weight)/(rrf_k + 1) + structured ≈ 0.021, so any higher
threshold makes the Tier-1 arm of the score gate vacuously false and turns the
gate into a bare Tier-2 cosine test. That scores well here and means nothing.

Usage: CHRONICLE_DIR=/path/to/chronicle python3 scripts/sweep_abstain.py \
           /path/to/oracle.json [n_answerable=100]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.environ.get("CHRONICLE_DIR") or str(Path(__file__).resolve().parent.parent))

from engine.core import ChronicleCore

# (gate, attr, value) — attr is the RetrievalEngine field the gate reads, so a
# trial applies straight onto a fresh engine without rebuilding the config.
GRID = ([("score", "_score_threshold", t) for t in (0.005, 0.01, 0.0148, 0.02, 0.03)]
        + [("overlap", "_overlap_min_tokens", n) for n in (1, 2, 3, 4, 5, 6)]
        + [("focus", "_focus_coverage", c)
           for c in (0.34, 0.5, 0.6, 0.7, 0.75, 0.78, 0.8, 0.85, 0.9)])


def iso(d):
    """'2023/04/10 (Mon) 17:50' -> ISO 8601 (mirrors lme_recall.iso)."""
    try:
        return datetime.strptime(d, "%Y/%m/%d (%a) %H:%M").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(d)


def ingest(core, inst):
    """One `observed` event per user->assistant pair, stamped with the session's
    real date — byte-for-byte the ingestion lme_recall.py measures against."""
    sids, dates = inst["haystack_session_ids"], inst["haystack_dates"]
    for si, sess in enumerate(inst["haystack_sessions"]):
        sid = sids[si] if si < len(sids) else "s%d" % si
        when = iso(dates[si]) if si < len(dates) else None
        pend = None
        for turn in sess:
            content = turn.get("content") or ""
            if turn.get("role") == "user":
                pend = content
                continue
            excerpt = ("User: {}\nAssistant: {}".format(pend or "", content))[:4000]
            core.capture.append("observed",
                                {"source_type": "session_transcript", "excerpt": excerpt,
                                 "source_ref": sid},
                                actor="user", session_id=sid, occurred_at=when)
            pend = None
        if pend is not None:  # trailing user turn with no assistant reply
            core.capture.append("observed",
                                {"source_type": "session_transcript",
                                 "excerpt": (f"User: {pend}")[:4000], "source_ref": sid},
                                actor="user", session_id=sid, occurred_at=when)


def abstains(inst, gate, attr, value) -> bool:
    home = tempfile.mkdtemp(prefix="sweep_abstain_")
    try:
        core = ChronicleCore.get(home)
        core.initialize(session_id="eval", principal_id="assistant")
        core.retrieval._abstain_gate = gate
        setattr(core.retrieval, attr, value)
        ingest(core, inst)
        core.process_pending()
        return bool(core.retrieval.answer(inst["question"]).get("abstain"))
    finally:
        # Drop the singleton too: the sweep builds ~2600 cores, and get() caches
        # every one (lme_recall.py builds 500 and can afford to leak them).
        ChronicleCore._instances.pop(home, None)
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    oracle = sys.argv[1] if len(sys.argv) > 1 else "oracle.json"
    n_ans = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    data = json.load(open(oracle))
    unanswerable = [q for q in data if str(q.get("question_id", "")).endswith("_abs")]
    answerable = [q for q in data if not str(q.get("question_id", "")).endswith("_abs")][:n_ans]

    print("sweeping %d configs over %d _abs + %d answerable instances"
          % (len(GRID), len(unanswerable), len(answerable)), flush=True)
    t0 = time.time()
    rows = []
    for gate, attr, value in GRID:
        ab = sum(abstains(i, gate, attr, value) for i in unanswerable)
        fa = sum(abstains(i, gate, attr, value) for i in answerable)
        rows.append((gate, attr, value, ab, fa))
        print("  %-8s %-18s abstained %2d/%d   false-abstain %3d/%d"
              % (gate, "{}={}".format(attr.lstrip("_"), value), ab, len(unanswerable), fa,
                 len(answerable)), flush=True)

    n_abs, n_a = len(unanswerable), len(answerable)
    print("\n%-8s %-20s %-14s %-18s" % ("gate", "param", "abstained/%d" % n_abs,
                                        "false-abstain/%d" % n_a))
    print("-" * 62)
    for gate, attr, value, ab, fa in rows:
        print("%-8s %-20s %-14s %-18s"
              % (gate, "{}={}".format(attr.lstrip("_"), value), "%d/%d" % (ab, n_abs),
                 "%d/%d" % (fa, n_a)))
    print("\n(%.1fs)" % (time.time() - t0))

    both = [r for r in rows if r[3] >= 20 and r[4] <= 5]
    floor = [r for r in rows if r[3] >= 20]
    advisory = [r for r in rows if r[4] <= 8]
    if both:
        pick = max(both, key=lambda r: (r[3], -r[4]))
        note = "clears abstained>=20/%d AND false-abstain<=5/%d" % (n_abs, n_a)
    elif floor:
        pick = min(floor, key=lambda r: (r[4], -r[3]))
        note = ("ACCEPTANCE-FIRST: no config clears both bars, so this is the cheapest "
                "config that still clears abstained>=20/%d" % n_abs)
    else:
        pick = max(rows, key=lambda r: r[3])
        note = "NOTHING reaches abstained>=20/%d — acceptance cannot be met by this grid" % n_abs

    print("\nSELECTED: abstain_gate=%s %s=%s  (abstained %d/%d, false-abstain %d/%d)"
          % (pick[0], pick[1].lstrip("_"), pick[2], pick[3], n_abs, pick[4], n_a))
    print(f"  {note}")
    if pick[4] > 8:
        print("  COST: %d/%d answerable questions are refused at this setting. The lexical"
              % (pick[4], n_a))
        print("  signals available here (fused score, token overlap, token coverage) do not")
        print("  separate 'unanswerable' from 'answerable' on this corpus — the _abs")
        print("  haystacks are topically on-question, they just omit the one fact asked for.")
    if advisory:
        a = max(advisory, key=lambda r: (r[3], -r[4]))
        print("\nADVISORY rule (max abstained with false-abstain<=8): abstain_gate=%s %s=%s"
              "  (abstained %d/%d, false-abstain %d/%d) — below the %d/%d acceptance floor."
              % (a[0], a[1].lstrip("_"), a[2], a[3], n_abs, a[4], n_a, 20, n_abs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
