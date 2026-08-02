"""Context assembly recall evaluation.

Measures get_context() recall at different token budgets. A hit is any
haystack turn with has_answer=true whose first 80 chars appear (case-
insensitive) in the returned context — the actual answer-bearing evidence,
not the dataset's short top-level `answer` field. Each instance gets a fresh
store (prevents cross-contamination).
"""
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.environ.get("CHRONICLE_DIR")
                or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from engine.core import ChronicleCore

BUDGETS = (1500, 4000)


def iso(d):
    """'2023/04/10 (Mon) 17:50' -> ISO 8601."""
    try:
        return datetime.strptime(d, "%Y/%m/%d (%a) %H:%M").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(d)


def ingest(core, inst):
    """One `observed` event per user->assistant pair, stamped with session date.

    The whole haystack is in hand up front, so it goes in through
    capture.append_many, which appends exactly the events the equivalent
    capture.append loop appends — same ids, same order, same vectors — but
    fetches each window's embeddings in ONE round trip. That is not a
    measurement change; it is where a networked embedder otherwise spends ~96%
    of this script's wall clock, one blocking 50ms call per turn.
    """
    sessions = inst["haystack_sessions"]
    sids = inst["haystack_session_ids"]
    dates = inst["haystack_dates"]
    events = []
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
            events.append({
                "type": "observed",
                "payload": {"source_type": "session_transcript", "excerpt": excerpt,
                            "source_ref": sid},
                "actor": "user", "session_id": sid, "occurred_at": when})
            pend = None
        if pend is not None:
            events.append({
                "type": "observed",
                "payload": {"source_type": "session_transcript",
                            "excerpt": (f"User: {pend}")[:4000], "source_ref": sid},
                "actor": "user", "session_id": sid, "occurred_at": when})
    core.capture.append_many(events)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "s_ctx100.json"
    limit = 60  # First 60 instances

    with open(path) as f:
        data = json.load(f)

    data = data[:limit]

    recall = defaultdict(int)
    hits = defaultdict(int)

    for n, inst in enumerate(data, 1):
        home = tempfile.mkdtemp(prefix="ctx_")
        try:
            core = ChronicleCore.get(home)
            core.initialize(session_id="eval", principal_id="assistant")
            ingest(core, inst)
            core.process_pending()

            question = inst["question"]

            # Hit criterion (per spec): any haystack turn with has_answer=true
            # whose first 80 chars appear in the returned context.
            answer_keys = [
                (turn.get("content") or "")[:80].lower()
                for sess in inst["haystack_sessions"] for turn in sess
                if turn.get("has_answer")
            ]
            if not answer_keys:
                continue

            for budget in BUDGETS:
                ctx = core.retrieval.get_context(question, token_budget=budget).lower()
                is_hit = any(key in ctx for key in answer_keys)
                recall[budget] += 1
                hits[budget] += int(is_hit)
        except Exception as e:
            print(f"Error on instance {n}: {e}", file=sys.stderr)
        finally:
            shutil.rmtree(home, ignore_errors=True)

        if n % 10 == 0:
            print(f"  ...{n}/{len(data)}", flush=True)

    print(f"\nContext Retrieval Recall ({len(data)} instances)\n")
    for budget in BUDGETS:
        n = recall[budget]
        h = hits[budget]
        pct = 100.0 * h / max(1, n) if n else 0
        print(f"  token_budget={budget:4d}:  {h}/{n}  ({pct:6.1f}%)")


if __name__ == "__main__":
    main()
