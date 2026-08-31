"""F4e (ladder-9 review): held-out revalidation of _MMR_POOL_OVERFETCH.

engine/retrieval.py's RetrievalEngine._MMR_POOL_OVERFETCH = 1.5 was "capped
empirically against the full ctx_eval + oracle harnesses" (see its docstring)
-- but ctx_eval.py gates on the SAME slice that tuned it: scripts/ctx_eval.py
reads s_ctx100.json (a symlink to lme-datasets/s_sample100.json) and takes
`data[:60]`, the FIRST 60 of that file's 100 instances. A value tuned and
then graded on the identical 60 instances proves nothing about whether it
generalizes.

This script re-runs ctx_eval's own recall methodology (same ingest path, same
hit criterion, same token budgets) against `data[60:]` -- the 40 instances
ctx_eval.py never samples -- at several overfetch values, so 1.5 is judged on
data it was never tuned against. It does not modify _MMR_POOL_OVERFETCH; it
monkeypatches the class attribute per run, in-process, and restores it after.

Usage (same env-var convention as scripts/ctx_eval.py):
    CHRONICLE_EMBED_MODEL=hashing CHRONICLE_DIR=$PWD \
        python3 scripts/mmr_overfetch_heldout.py [path/to/s_sample100.json]

Output: one recall table per overfetch value, plus a verdict line.
"""
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, os.environ.get("CHRONICLE_DIR")
                or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # sibling import below

from engine.core import ChronicleCore                # noqa: E402
from engine.retrieval import RetrievalEngine          # noqa: E402
from ctx_eval import BUDGETS, ingest                  # noqa: E402  (reuse verbatim)

# ctx_eval.py's own `limit = 60  # First 60 instances`. Hardcoded here on
# purpose -- if that limit ever changes, this split must be re-derived from
# the same number, not silently drift out of sync with what ctx_eval.py
# actually gates on.
CTX_EVAL_SAMPLE = 60

# 1.5 is the shipped default; 1.0 disables the eligibility window's widening
# entirely (window == k, MMR only ever sees the naive top-k); 2.0 doubles it;
# a large multiplier stands in for "unbounded" without touching _mmr_select's
# own logic -- realistic candidate pools for these fixtures top out in the
# dozens (the docstring's own worked example: 43 candidates for one query),
# so a window of k*1000 is never actually truncated and behaves as unbounded.
OVERFETCH_VALUES = (1.0, 1.5, 2.0, 1000.0)


def evaluate(data):
    recall = defaultdict(int)
    hits = defaultdict(int)
    errors = 0
    for n, inst in enumerate(data, 1):
        home = tempfile.mkdtemp(prefix="ctx_heldout_")
        try:
            core = ChronicleCore.get(home)
            core.initialize(session_id="eval", principal_id="assistant")
            ingest(core, inst)
            core.process_pending()

            question = inst["question"]
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
            errors += 1
            print(f"Error on held-out instance {n}: {e}", file=sys.stderr)
        finally:
            shutil.rmtree(home, ignore_errors=True)
    return recall, hits, errors


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "s_sample100.json"
    with open(path) as f:
        data = json.load(f)

    heldout = data[CTX_EVAL_SAMPLE:]
    print(f"Source: {path} ({len(data)} instances)")
    print(f"ctx_eval.py samples data[:{CTX_EVAL_SAMPLE}]; this script evaluates "
         f"data[{CTX_EVAL_SAMPLE}:] -- {len(heldout)} instances, fully disjoint.\n")

    original = RetrievalEngine._MMR_POOL_OVERFETCH
    results = {}
    try:
        for of in OVERFETCH_VALUES:
            RetrievalEngine._MMR_POOL_OVERFETCH = of
            recall, hits, errors = evaluate(heldout)
            label = "unbounded" if of >= 1000 else str(of)
            results[label] = {}
            print(f"overfetch={label}" + (f"  ({errors} errored instance(s))" if errors else ""))
            for budget in BUDGETS:
                n, h = recall[budget], hits[budget]
                pct = 100.0 * h / max(1, n) if n else 0
                results[label][budget] = (h, n, pct)
                print(f"  token_budget={budget:5d}:  {h}/{n}  ({pct:6.1f}%)")
            print()
    finally:
        RetrievalEngine._MMR_POOL_OVERFETCH = original

    print("Summary (held-out recall %, by overfetch value):")
    header = "  " + "".join(f"{b:>10}" for b in BUDGETS)
    print(header)
    for label in results:
        row = "  ".join(f"{results[label][b][2]:8.1f}%" for b in BUDGETS)
        print(f"  {label:>9}  {row}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
