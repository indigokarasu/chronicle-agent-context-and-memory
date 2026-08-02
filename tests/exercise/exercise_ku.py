"""
Chronicle — Knowledge-update consolidation exercise (§t3.b).

s_ku20.json holds 20 real LongMemEval knowledge-update instances. Each instance's
`haystack_sessions` embed a fact that changes value across sessions (e.g. a charity
5K personal-best of 27:12 recorded once, then bettered to 25:50 weeks later) — the
exact shape belief consolidation is supposed to react to: extraction should assert
both values under the same (entity, predicate) key, and the fact-conflict policy
(reducer.py:302-334, §8.5) should supersede the stale belief and, when the domain
policy is "flag_for_review" (user domain, DOMAIN_POLICY in reducer.py), open a
contradiction (reducer.py:329).

Per instance: fresh temp home, ingest one `observed` event per real user->assistant
turn in haystack_sessions (mirrors lme_recall.ingest() in ../../../../lme_recall.py),
then core.process_pending() (core.py:190) to actually run the curation queue. This
deliberately does NOT observe inst["question"]/inst["answer"] directly — those are
the benchmark's gold Q&A pair, not conversation content, and feeding them straight in
would be evaluation leakage rather than a realistic ingest.

The previous version of this script hand-rolled a claim/complete loop
(`store.claim_curation_job()` + `store.complete_curation_job()`) that marked every
curation job "done" WITHOUT calling its handler — so extraction never ran, no
beliefs were ever created, and every instance reported 0 active/0 contradictions
regardless of input. That loop is gone; `core.process_pending()` drains the same
job queue through `CurationWorker.run_once()`, which DOES call the handler before
marking a job complete (curation.py:38-53).

Reports, per instance and in aggregate: contradictions opened, beliefs superseded,
beliefs retracted, and beliefs left active. This is a measurement, not a test —
numbers are printed as observed, with no pass/fail forced on them.
"""

import json
import logging
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.core import ChronicleCore

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("exercise_ku")

KU_PATH = Path("/private/tmp/claude-501/-Users-evaluser-temp/3d6d860f-71ee-406d-9aef-b68dfd0642d1/scratchpad/s_ku20.json")

BELIEF_TABLES = ("facts", "notes", "episodes")


def iso(d):
    """'2023/04/10 (Mon) 17:50' -> ISO 8601 (same parse as lme_recall.iso)."""
    try:
        return datetime.strptime(d, "%Y/%m/%d (%a) %H:%M").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(d)


def ingest_instance(core, inst) -> int:
    """One `observed` event per user->assistant pair across haystack_sessions,
    stamped with the session's real date — the same shape lme_recall.ingest() uses.
    Returns the number of events appended."""
    n = 0
    sessions = inst.get("haystack_sessions", [])
    sids = inst.get("haystack_session_ids", [])
    dates = inst.get("haystack_dates", [])
    for si, sess in enumerate(sessions):
        sid = sids[si] if si < len(sids) else "s%d" % si
        when = iso(dates[si]) if si < len(dates) else None
        pend = None
        for turn in sess:
            content = turn.get("content") or ""
            if turn.get("role") == "user":
                pend = content
                continue
            excerpt = ("User: {}\nAssistant: {}".format(pend or "", content))[:4000]
            eid = core.capture.append(
                "observed", {"source_type": "session_transcript", "excerpt": excerpt, "source_ref": sid},
                actor="user", session_id=sid, occurred_at=when, trust_level=2)
            if eid:
                n += 1
            pend = None
        if pend is not None:  # trailing user turn with no assistant reply
            eid = core.capture.append(
                "observed", {"source_type": "session_transcript", "excerpt": (f"User: {pend}")[:4000],
                             "source_ref": sid},
                actor="user", session_id=sid, occurred_at=when, trust_level=2)
            if eid:
                n += 1
    return n


def instance_stats(core) -> dict:
    store = core.store
    return {
        "contradictions": len(store.get_open_contradictions(1000)),
        "superseded": sum(store.count_rows(t, "status='superseded'") for t in BELIEF_TABLES),
        "retracted": sum(store.count_rows(t, "status='retracted'") for t in BELIEF_TABLES),
        "active": sum(store.count_rows(t, "status='active'") for t in BELIEF_TABLES),
    }


def main():
    if not KU_PATH.exists():
        print(f"ERROR: {KU_PATH} not found")
        return 1

    instances = json.loads(KU_PATH.read_text())

    print("\n=== Knowledge-Update Consolidation Exercise (§t3.b) ===")
    print(f"Loaded {len(instances)} instances from {KU_PATH.name}\n")

    agg = {"contradictions": 0, "superseded": 0, "retracted": 0, "active": 0}
    per_instance = []

    for idx, inst in enumerate(instances, 1):
        qid = inst.get("question_id", f"ku_{idx}")
        question = (inst.get("question") or "")[:56]

        tmpdir = tempfile.mkdtemp(prefix=f"chronicle_ku_{idx}_")
        try:
            core = ChronicleCore.get(tmpdir)
            core.initialize(qid, hermes_home=tmpdir, principal_id="user")

            n_events = ingest_instance(core, inst)
            n_jobs = core.process_pending(max_jobs=5000)  # the actual fix: handlers really run
            s = instance_stats(core)

            per_instance.append({"instance": idx, "question_id": qid, "events": n_events,
                                 "jobs_drained": n_jobs, **s})
            for k in agg:
                agg[k] += s[k]

            print(f"[{idx:2d}] {qid:10s} | Q: {question:56s} | events:{n_events:3d} jobs:{n_jobs:4d} "
                 f"| contradictions:{s['contradictions']:2d} superseded:{s['superseded']:2d} "
                 f"retracted:{s['retracted']:2d} active:{s['active']:3d}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print("=== Aggregate (%d instances) ===" % len(per_instance))
    print(f"Total contradictions opened: {agg['contradictions']}")
    print(f"Total beliefs superseded:    {agg['superseded']}")
    print(f"Total beliefs retracted:     {agg['retracted']}")
    print(f"Total beliefs active:        {agg['active']}")
    print()
    print("These are direct store counts after core.process_pending() actually drained the")
    print("curation queue (extract -> canonicalize, plus the reducer's inline fact-conflict")
    print("path on 'asserted' events, §8.5). No pass/fail is asserted here — this measures")
    print("whether consolidation observably reacts to real knowledge updates; read the numbers")
    print("as reported, not adjusted toward an expected outcome.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
