"""A18 A/B: compare two `ctx_eval_probe.py` runs.

  /usr/bin/python3 scripts/a18_ab.py PRE.jsonl POST.jsonl

Prints, per budget tier: the ctx_eval hit rate, the breadth actually delivered
(distinct sessions, share of the raw-evidence fill claimed by the largest one),
gold-session coverage, and the BYTE-IDENTITY proof the A18 hard constraint
requires -- every context whose route is one the breadth floor does not cover
must hash the same in both trees.

Both inputs are `ctx_eval_probe.py --out` files.
"""
import json
import statistics
import sys

BUD = (1500, 4000, 12000)
COVERED = ("aggregation", "temporal")


def load(p):
    """One probe run, keyed by (instance, budget).

    A non-JSON line is reported by file and line number rather than raised. The
    reason is a specific, repeated mistake: ctx_eval_probe.py used to print its
    summary to stdout while writing its rows to a file, so redirecting stdout
    produced a plausible-looking .jsonl full of table text, and the only symptom
    was a bare JSONDecodeError naming neither the file nor the cause."""
    out = {}
    try:
        with open(p) as f:
            for i, ln in enumerate(f, 1):
                if not ln.strip():
                    continue
                try:
                    r = json.loads(ln)
                except ValueError as e:
                    sys.exit(
                        "a18_ab: %s line %d is not JSON (%s)\n"
                        "  first 60 chars: %r\n"
                        "  This is what a redirected summary looks like. Regenerate with\n"
                        "  ctx_eval_probe.py CORPUS.json --out %s"
                        % (p, i, e, ln[:60], p))
                out[(r["n"], r["budget"])] = r
    except OSError as e:
        sys.exit("a18_ab: cannot read %s (%s)" % (p, e))
    if not out:
        sys.exit("a18_ab: %s has no rows" % p)
    return out


def fill_share(r):
    tot = sum(c for _, c in r["sessions"])
    return (max(c for _, c in r["sessions"]) / tot) if tot else 0.0


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: a18_ab.py PRE.jsonl POST.jsonl  "
                 "(both from ctx_eval_probe.py --out)")
    pre, post = load(sys.argv[1]), load(sys.argv[2])
    keys = sorted(set(pre) & set(post))
    print("rows compared: %d (pre %d, post %d)\n" % (len(keys), len(pre), len(post)))

    print("== ctx_eval hit rate ==")
    for b in BUD:
        k = [x for x in keys if x[1] == b]
        a = sum(pre[x]["hit"] for x in k)
        c = sum(post[x]["hit"] for x in k)
        print("  @%5d  %2d/%d (%5.1f%%) -> %2d/%d (%5.1f%%)  %+d"
              % (b, a, len(k), 100.0 * a / len(k), c, len(k), 100.0 * c / len(k), c - a))

    print("\n== breadth delivered / gold coverage (cohort = instances the floor can touch) ==")
    print("  %-6s %-22s %4s %14s %14s %14s %14s"
          % ("budget", "cohort", "n", "sessions", "largest-of-fill", "gold sess cov", "hit"))
    for b in BUD:
        for name, sel in (("ALL", lambda x: True),
                          ("covered route", lambda x: post[x]["route"] in COVERED),
                          ("multi-gold (>=2)", lambda x: post[x]["n_gold"] > 1),
                          ("factual route", lambda x: post[x]["route"] == "factual")):
            k = [x for x in keys if x[1] == b and sel(x)]
            if not k:
                continue
            def f(d, fn, k=k):
                return sum(fn(d[x]) for x in k) / len(k)

            def cov(d, k=k):
                return sum(d[x]["gold_cov"] for x in k) / sum(d[x]["n_gold"] for x in k)

            print("  %-6d %-22s %4d  %5.2f -> %5.2f  %5.0f%% -> %5.0f%%  %5.0f%% -> %5.0f%%  %5.0f%% -> %5.0f%%"
                  % (b, name, len(k),
                     f(pre, lambda r: r["n_sessions"]), f(post, lambda r: r["n_sessions"]),
                     100 * statistics.median([fill_share(pre[x]) for x in k]),
                     100 * statistics.median([fill_share(post[x]) for x in k]),
                     100 * cov(pre), 100 * cov(post),
                     100 * f(pre, lambda r: r["hit"]), 100 * f(post, lambda r: r["hit"])))
        print()

    print("== budget still saturated (chars emitted / char ceiling) ==")
    for b in BUD:
        k = [x for x in keys if x[1] == b]
        print("  @%5d  pre %5.1f%%  post %5.1f%%"
              % (b, 100 * sum(pre[x]["chars"] / pre[x]["cap"] for x in k) / len(k),
                 100 * sum(post[x]["chars"] / post[x]["cap"] for x in k) / len(k)))

    print("\n== BYTE IDENTITY on routes the floor does not cover ==")
    bad = [x for x in keys if pre[x]["route"] not in COVERED and pre[x]["sha"] != post[x]["sha"]]
    n_un = sum(1 for x in keys if pre[x]["route"] not in COVERED)
    print("  uncovered-route contexts: %d   differing: %d" % (n_un, len(bad)))
    for x in bad[:20]:
        print("    #%d @%d route=%s" % (x[0], x[1], pre[x]["route"]))
    moved = [x for x in keys if pre[x]["sha"] != post[x]["sha"]]
    print("  contexts changed at all: %d, every one on a covered route: %s"
          % (len(moved), all(pre[x]["route"] in COVERED for x in moved)))
    print("\n== per-instance movement (hit flips) ==")
    for b in BUD:
        won = sorted(x[0] for x in keys if x[1] == b and post[x]["hit"] and not pre[x]["hit"])
        lost = sorted(x[0] for x in keys if x[1] == b and pre[x]["hit"] and not post[x]["hit"])
        print("  @%5d  gained %s  lost %s" % (b, won, lost))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
