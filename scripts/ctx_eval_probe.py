"""A18 STEP 1 -- breadth-vs-depth measurement probe over the ctx_eval corpus.

Same ingest, same instances, same hit criterion as `ctx_eval.py` (it is a copy
of that script with instrumentation bolted on, so its per-budget totals must
reproduce ctx_eval's exactly -- that equality is the probe's own self-check).

Per instance per budget tier it records:
  route          -- the E9 route get_context actually took (last_context_debug)
  n_sessions     -- DISTINCT `[SESSION ...]` headers in the emitted context
  top_share      -- char share of the largest single session block
  gold_present   -- was ANY gold session (dataset answer_session_ids) emitted
  gold_all       -- were ALL gold sessions emitted
  hit            -- ctx_eval's own criterion (a has_answer turn's first 80 chars)
  saturated      -- emitted chars within 2% of the budget's char ceiling
  sha            -- sha256 of the emitted context (byte-identity A/B across trees)

Usage:
  /usr/bin/python3 scripts/ctx_eval_probe.py [CORPUS.json] [--out PATH|-]

Writes one JSON object per line to --out (default a18_probe.jsonl), or to
stdout with `--out -`. EVERY human-readable line -- progress, the parity table,
the footer -- goes to stderr, so stdout carries the JSONL and nothing else and

  ctx_eval_probe.py corpus.json --out - > pre.jsonl

produces a file scripts/a18_ab.py can read. Redirecting without `--out -` is
harmless rather than wrong: the rows still land in the --out file and the
redirect captures nothing.
"""
import hashlib
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

# Sweep knobs, measurement-only: A18_FLOOR=<n> sets
# context.breadth_floor_sessions, A18_OFF=1 disables the floor entirely.
# Applied to DEFAULTS so every core this script builds sees them; a tree
# without the keys (the pre-A18 baseline) simply ignores both.
try:
    from engine.config import DEFAULTS as _D
    if os.environ.get("A18_FLOOR"):
        _D["context"]["breadth_floor_sessions"] = int(os.environ["A18_FLOOR"])
    if os.environ.get("A18_OFF"):
        _D["context"]["breadth_floor"] = False
except Exception:
    pass

BUDGETS = (1500, 4000, 12000)

_DEFAULT_CORPUS = "s_ctx100.json"
_DEFAULT_OUT = "a18_probe.jsonl"


def say(msg=""):
    """Human-readable output. ALWAYS stderr, so stdout stays machine-readable.

    This script used to write its rows to a file while printing progress and
    the parity table to stdout, so the obvious `ctx_eval_probe.py corpus.json >
    pre.jsonl` produced a file full of summary text and scripts/a18_ab.py then
    died on a JSONDecodeError several minutes later. stdout now carries the
    JSONL or nothing at all."""
    print(msg, file=sys.stderr, flush=True)


def parse_args(argv):
    """-> (corpus_path, out). An unknown option is an ERROR, not a shrug.

    The previous parser took the first bare word as the corpus and silently
    ignored anything beginning with `--`, so a mistyped flag ran the whole
    58-instance sweep against the default corpus and wrote to the default
    file without a word about either."""
    path, out, rest = None, None, list(argv)
    while rest:
        a = rest.pop(0)
        if a in ("-h", "--help"):
            say(__doc__)
            raise SystemExit(0)
        if a == "--out":
            if not rest:
                raise SystemExit("ctx_eval_probe: --out needs a path ('-' for stdout)")
            out = rest.pop(0)
        elif a.startswith("--out="):
            out = a.split("=", 1)[1]
        elif a.startswith("-") and a != "-":
            raise SystemExit("ctx_eval_probe: unknown option %r" % a)
        elif path is None:
            path = a
        else:
            raise SystemExit("ctx_eval_probe: unexpected extra argument %r" % a)
    return path or _DEFAULT_CORPUS, out or _DEFAULT_OUT


def write_rows(rows, out):
    """-> the destination, named for the footer. `-` means stdout."""
    if out == "-":
        for r in rows:
            sys.stdout.write(json.dumps(r) + "\n")
        sys.stdout.flush()
        return "stdout"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return os.path.abspath(out)


def iso(d):
    try:
        return datetime.strptime(d, "%Y/%m/%d (%a) %H:%M").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(d)


def ingest(core, inst):
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


def session_blocks(ctx):
    """-> (ordered [(sid, chars)], preamble_chars). Chars include the header."""
    blocks = []
    pre = 0
    cur = None
    for line in ctx.split("\n"):
        if line.startswith("[SESSION "):
            rest = line[len("[SESSION "):]
            sid = rest.split(" @ ", 1)[0].rstrip("]")
            cur = [sid, 0]
            blocks.append(cur)
        if cur is None:
            pre += len(line) + 1
        else:
            cur[1] += len(line) + 1
    return blocks, pre


def main():
    path, out = parse_args(sys.argv[1:])

    with open(path) as f:
        data = json.load(f)[:60]

    rows = []
    recall = defaultdict(int)
    hits = defaultdict(int)

    for n, inst in enumerate(data, 1):
        home = tempfile.mkdtemp(prefix="ctxp_")
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
            gold_sids = set(inst.get("answer_session_ids") or [])
            # gold sessions derived from the turns themselves (cross-check)
            derived = set()
            for si, sess in enumerate(inst["haystack_sessions"]):
                if any(t.get("has_answer") for t in sess):
                    derived.add(inst["haystack_session_ids"][si])

            for budget in BUDGETS:
                ctx = core.retrieval.get_context(question, token_budget=budget)
                dbg = dict(core.retrieval.last_context_debug or {})
                low = ctx.lower()
                is_hit = any(key in low for key in answer_keys)
                recall[budget] += 1
                hits[budget] += int(is_hit)
                # gold coverage by TEXT, per gold session: the eval's own
                # criterion says only "some gold turn is present", and a gold
                # turn can arrive through the tier-1 [EPISODE] block with no
                # session header at all (measured: instance #1 @1500). For a
                # breadth question the meaningful quantity is how many of the
                # gold SESSIONS actually delivered evidence.
                gold_cov = 0
                for sid in derived:
                    ks = [(t.get("content") or "")[:80].lower()
                          for si, sess in enumerate(inst["haystack_sessions"])
                          if inst["haystack_session_ids"][si] == sid
                          for t in sess if t.get("has_answer")]
                    if any(k in low for k in ks):
                        gold_cov += 1
                blocks, pre = session_blocks(ctx)
                total = max(1, len(ctx))
                per = defaultdict(int)
                for sid, c in blocks:
                    per[sid] += c
                present = set(per)
                top = max(per.values()) if per else 0
                # The char ceiling get_context actually enforced, read off the
                # debug field rather than recomputed here: one estimator (A10),
                # and this script must not become a second site that decides
                # what a margin is (tests/test_token_margins.py).
                cap = dbg.get("budget_chars") or 1
                rows.append({
                    "n": n, "budget": budget,
                    "sha": hashlib.sha256(ctx.encode("utf-8")).hexdigest(),
                    "qtype": inst["question_type"],
                    "route": dbg.get("route"),
                    "precision": bool(dbg.get("precision")),
                    "pref_pack": bool(dbg.get("pref_pack")),
                    "breadth_floor": dbg.get("breadth_floor"),
                    "chars": len(ctx), "cap": cap,
                    "saturated": len(ctx) >= 0.98 * cap,
                    "n_sessions": len(per),
                    "top_share": round(top / total, 4),
                    "n_gold": len(derived),
                    "gold_cov": gold_cov,
                    "gold_cov_all": bool(derived) and gold_cov == len(derived),
                    "gold_present": bool(derived & present),
                    "gold_all": bool(derived) and derived <= present,
                    "gold_missing": sorted(derived - present),
                    "hit": is_hit,
                    "sessions": [[sid, c] for sid, c in blocks],
                    "gold_sids": sorted(derived),
                    "dataset_gold": sorted(gold_sids),
                })
        except Exception as e:
            print(f"Error on instance {n}: {e}", file=sys.stderr)
        finally:
            shutil.rmtree(home, ignore_errors=True)
        if n % 10 == 0:
            say(f"  ...{n}/{len(data)}")

    dest = write_rows(rows, out)

    say(f"\nctx_eval parity check ({len(data)} instances)\n")
    for b in BUDGETS:
        h, nn = hits[b], recall[b]
        say(f"  token_budget={b:5d}:  {h}/{nn}  ({100.0*h/max(1,nn):6.1f}%)")
    say(f"\nwrote {len(rows)} rows to {dest}")


if __name__ == "__main__":
    main()
