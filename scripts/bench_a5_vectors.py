#!/usr/bin/env python3
"""A5 — old-vs-new benchmark for the vector candidate-generation read path.

WHAT IT MEASURES. `search()` used to call `store.iter_memory_vectors()` —
`SELECT * FROM memory_vectors` into a list of dicts — once per query, plus
`iter_query_proxy_vectors()` twice more for the two proxy readers. The audit
measured that at ~750 MB and ~0.7 s per query at 105k rows. This script seeds a
store shaped like production and reports, for the OLD (materialising) and NEW
(streaming, bounded top-k) implementations of the same three functions:

    per-query wall time  ·  tracemalloc peak (Python allocation high-water)
    ·  ru_maxrss (process peak RSS)

Each path runs in its OWN subprocess, because ru_maxrss is monotonic
process-wide: measuring both in one process would report the loser's peak for
the winner too. `--path both` is the driver that forks the two and prints the
table.

SHAPE OF THE SEEDED STORE (production, measured 2026-09):
  memory_vectors 108,581 · observed_vectors 89,562 · query_proxy_vectors 18,429
  · session_index 7,288, and ~88% of the vector rows are 8192 B (2048-dim
  nemotron) against a ~768-dim active embedder (A0). The seed reproduces that
  width split at `--rows` scale, because it is the whole reason the SQL width
  prefilter is worth having: those rows are scored a hard 0.0 by batch_cosine
  and discarded, after being copied into Python.

FAKE DATA ONLY — every vector is drawn from a seeded PRNG, every fact value is
synthetic. Nothing here touches a real store.

  /usr/bin/python3 scripts/bench_a5_vectors.py --rows 100000
"""

import argparse
import gc
import hashlib
import json
import os
import random
import resource
import struct
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Config                      # noqa: E402
from engine.embeddings import HashingEmbedder, batch_cosine  # noqa: E402
from engine.retrieval import RetrievalEngine          # noqa: E402
from engine.store import MemoryStore                  # noqa: E402

# Production width split (A0): the active embedder's width is the minority.
QUERY_DIMS = 768
FOREIGN_DIMS = 2048
MATCHING_FRACTION = 0.12
PROXY_FRACTION = 0.17          # 18,429 / 108,581
SESSION_FRACTION = 0.067       # 7,288 / 108,581


# ---------------------------------------------------------------------------
# The OLD path, verbatim from v560 + A1 (git f14aa99). Kept here as the single
# definition of the reference behaviour: tests/test_a5_streaming_candidates.py
# imports these to prove the new path ranks identically, and the benchmark
# times them. One copy, so the reference cannot drift from what is compared.
# ---------------------------------------------------------------------------

def ref_vector_beliefs(store, query_emb, limit):
    rows = store.iter_memory_vectors()
    sims = batch_cosine(query_emb, [v["embedding"] for v in rows])
    scored = [(rows[i]["belief_id"], rows[i]["kind"], sims[i])
              for i in range(len(rows)) if sims[i] > 0.1]
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:limit]


def ref_vector_proxies(store, query_emb, limit):
    rows = [r for r in store.iter_query_proxy_vectors() if r["kind"] != "observed"]
    sims = batch_cosine(query_emb, [v["embedding"] for v in rows])
    best = {}
    for i in range(len(rows)):
        if sims[i] <= 0.1:
            continue
        bid = rows[i]["belief_id"]
        cur = best.get(bid)
        if cur is None or sims[i] > cur[2]:
            best[bid] = (bid, rows[i]["kind"], sims[i])
    scored = list(best.values())
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:limit]


def ref_observed_proxies(store, query_emb, limit):
    rows = [r for r in store.iter_query_proxy_vectors() if r["kind"] == "observed"]
    if not rows:
        return []
    sims = batch_cosine(query_emb, [v["embedding"] for v in rows])
    best = {}
    for i in range(len(rows)):
        if sims[i] <= 0.1:
            continue
        eid = rows[i]["belief_id"]
        if sims[i] > best.get(eid, 0.0):
            best[eid] = sims[i]
    return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

_WORDS = ["acme", "fake", "coffee", "pat", "testley", "vega", "nairobi", "kestrel",
          "lantern", "otter", "quartz", "meridian", "tulip", "basalt", "nimbus",
          "harbor", "cinder", "willow", "gable", "junco"]


class _BlobSource:
    """Deterministic unit-norm float32 blobs, generated in numpy batches.

    Pure-Python `random.gauss` would need ~200M draws to seed 100k rows at
    production widths — minutes of pure seeding. numpy's seeded Generator is
    reproducible for a given seed and version, which is all the benchmark
    needs (the DIFFERENTIAL test does not use this; it builds its corpus
    through the real embedder)."""

    def __init__(self, seed_value, chunk=512):
        self.chunk = chunk
        self._pools = {}
        try:
            import numpy as np
            self._np = np
            self._rng = np.random.default_rng(seed_value)
        except Exception:
            self._np = None
            self._py = random.Random(seed_value)

    def blob(self, dims):
        if self._np is None:
            v = [self._py.gauss(0.0, 1.0) for _ in range(dims)]
            n = sum(x * x for x in v) ** 0.5 or 1.0
            return struct.pack("<%df" % dims, *[x / n for x in v])
        pool = self._pools.get(dims)
        if not pool:
            np = self._np
            m = self._rng.standard_normal((self.chunk, dims)).astype(np.float32)
            m /= np.linalg.norm(m, axis=1, keepdims=True)
            pool = [m[i].tobytes() for i in range(self.chunk)]
            self._pools[dims] = pool
        return pool.pop()


def seed(path, rows, seed_value=20260910):
    """Deterministic synthetic store. Idempotent: an existing file with the
    right row count is reused, so old and new measure the SAME bytes."""
    store = MemoryStore(path)
    have = store._conn().execute("SELECT COUNT(*) AS n FROM memory_vectors").fetchone()["n"]
    if have == rows:
        return store
    rng = random.Random(seed_value)
    blobs = _BlobSource(seed_value)
    n_proxy = int(rows * PROXY_FRACTION)
    n_sess = int(rows * SESSION_FRACTION)
    conn = store._conn()
    conn.execute("BEGIN")
    conn.execute("DELETE FROM memory_vectors")
    conn.execute("DELETE FROM query_proxy_vectors")
    conn.execute("DELETE FROM observed_vectors")
    conn.execute("DELETE FROM session_index")
    conn.execute("DELETE FROM facts")
    conn.execute("DELETE FROM entities")
    for i in range(rows):
        bid = "b%08d" % i
        matching = (i % 100) < int(MATCHING_FRACTION * 100)
        dims = QUERY_DIMS if matching else FOREIGN_DIMS
        tag = "nomic-embed-text" if matching else "nvidia/llama-nemotron-embed-vl-1b-v2:free"
        conn.execute("INSERT INTO memory_vectors(belief_id,kind,embedding,model,created_at) "
                     "VALUES(?,?,?,?,?)",
                     (bid, "fact", blobs.blob(dims), tag, "2026-01-01T00:00:00Z"))
        val = " ".join(rng.choice(_WORDS) for _ in range(6))
        conn.execute(
            "INSERT INTO facts(belief_id,entity_id,attribute,predicate_canonical,value,"
            "owner,domain,status,provenance,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (bid, "e%06d" % (i % 5000), rng.choice(_WORDS), rng.choice(_WORDS), val,
             "default", "personal", "active", "{}", "2026-01-01T00:00:00Z"))
    proxy_parents = max(1, n_proxy // 3)   # ~3 proxies per parent belief
    for i in range(n_proxy):
        # `n_proxy` is a FRACTION of `rows`, so `i % rows` was always `i` and
        # `i // rows` always 0: every belief got exactly one proxy at index 0 and
        # the comment claiming a fan-out was false. That made the benchmark time
        # `_vector_proxies` over a corpus that never exercises its best-per-belief
        # dedupe or the multi-proxy tail merge -- i.e. it measured the easy case
        # and reported it as the shape A5 has to handle.
        bid = "b%08d" % (i % proxy_parents)   # several proxies DO land on one belief
        dims = QUERY_DIMS if (i % 100) < int(MATCHING_FRACTION * 100) else FOREIGN_DIMS
        kind = "observed" if i % 5 == 0 else "fact"
        conn.execute("INSERT INTO query_proxy_vectors"
                     "(belief_id,proxy_idx,kind,question,embedding,model,created_at) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (bid, i // proxy_parents, kind, "q?", blobs.blob(dims),
                      "m", "2026-01-01T00:00:00Z"))
    for i in range(n_sess):
        dims = QUERY_DIMS if (i % 100) < int(MATCHING_FRACTION * 100) else FOREIGN_DIMS
        conn.execute("INSERT INTO session_index(session_id,summary,embedding,owner,occurred_at) "
                     "VALUES(?,?,?,?,?)",
                     ("s%06d" % i, "summary", blobs.blob(dims), "default",
                      "2026-01-01T00:00:00Z"))
    for i in range(5000):
        conn.execute("INSERT INTO entities(belief_id,type,name,normalized_name,domain,owner,"
                     "created_at) VALUES(?,?,?,?,?,?,?)",
                     ("e%06d" % i, "person", "N%d" % i,
                      " ".join(rng.choice(_WORDS) for _ in range(2)), "personal", "default",
                      "2026-01-01T00:00:00Z"))
    conn.execute("COMMIT")
    return store


def _queries(n, embedder):
    rng = random.Random(4242)
    return [embedder.embed(" ".join(rng.choice(_WORDS) for _ in range(4))) for _ in range(n)]


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def _rss_mb():
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return ru / (1024.0 * 1024.0) if sys.platform == "darwin" else ru / 1024.0


def run_path(which, path, rows, nq, limit):
    store = seed(path, rows)
    cfg = Config({"embeddings": {"model": "hashing", "dimensions": QUERY_DIMS}})
    embedder = HashingEmbedder(dimensions=QUERY_DIMS)
    engine = RetrievalEngine(store, cfg, embedder=embedder, vector_index=None)
    qs = _queries(nq, embedder)

    if which == "old":
        fns = [("_vector_beliefs", lambda e: ref_vector_beliefs(store, e, limit)),
               ("_vector_proxies", lambda e: ref_vector_proxies(store, e, limit)),
               ("_observed_proxies", lambda e: ref_observed_proxies(store, e, limit))]
    else:
        fns = [("_vector_beliefs", lambda e: engine._vector_beliefs(e, limit)),
               ("_vector_proxies", lambda e: engine._vector_proxies(e, limit)),
               ("_observed_proxies", lambda e: engine._observed_proxies(e, limit))]

    out = {"path": which, "rows": rows, "per_fn": {}}
    for name, fn in fns:
        fn(qs[0])                                   # warm the page cache
        gc.collect()
        tracemalloc.start()
        t0 = time.perf_counter()
        for e in qs:
            fn(e)
        elapsed = (time.perf_counter() - t0) / len(qs)
        _cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        out["per_fn"][name] = {"ms": elapsed * 1000.0, "peak_mb": peak / (1024.0 * 1024.0)}

    # End-to-end search(): the number that actually reaches a caller.
    if which == "new":
        gc.collect()
        tracemalloc.start()
        t0 = time.perf_counter()
        for i in range(min(nq, 5)):
            engine.search(" ".join(_WORDS[i:i + 3]), limit=10)
        out["search_ms"] = (time.perf_counter() - t0) / min(nq, 5) * 1000.0
        _cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        out["search_peak_mb"] = peak / (1024.0 * 1024.0)

    # Differential AT SCALE. tests/test_a5_streaming_candidates.py proves
    # ranking identity on a 5k-row fixture; this repeats it on the 100k-row
    # benchmark corpus, where the tail merge and the multi-page scan are what
    # they will be in production. Each child hashes its own results; the
    # driver below refuses to print a table whose two halves disagree, so a
    # speedup can never be reported for a path that answers differently.
    h = hashlib.sha256()
    for name, fn in fns:
        for e in qs:
            h.update(repr(fn(e)).encode())
    out["results_sha256"] = h.hexdigest()
    out["rss_mb"] = _rss_mb()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100000)
    ap.add_argument("--queries", type=int, default=5)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--path", choices=("old", "new", "both"), default="both")
    # Relative to the repo, never an absolute path from whoever wrote this:
    # a hardcoded home directory is a real username published in a public repo,
    # and it also makes the bench unrunnable for everyone else. Override with
    # A5_BENCH_STORE or --store.
    ap.add_argument("--store", default=os.environ.get(
        "A5_BENCH_STORE",
        str(Path(__file__).resolve().parent.parent / ".a5bench" / "bench.db")))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    Path(a.store).parent.mkdir(parents=True, exist_ok=True)

    if a.path != "both":
        r = run_path(a.path, a.store, a.rows, a.queries, a.limit)
        print(json.dumps(r))
        return 0

    seed(a.store, a.rows)                            # once, shared by both children
    results = {}
    for which in ("old", "new"):
        cp = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--path", which,
             "--rows", str(a.rows), "--queries", str(a.queries),
             "--limit", str(a.limit), "--store", a.store],
            capture_output=True, text=True)
        if cp.returncode != 0:
            sys.stderr.write(cp.stderr)
            return 1
        results[which] = json.loads(cp.stdout.strip().splitlines()[-1])

    if results["old"]["results_sha256"] != results["new"]["results_sha256"]:
        sys.stderr.write(
            "RANKING DIVERGED at %d rows: old %s != new %s\n"
            "The paths do not agree, so there is no benchmark to report.\n"
            % (a.rows, results["old"]["results_sha256"][:16],
               results["new"]["results_sha256"][:16]))
        return 2

    if a.json:
        print(json.dumps(results, indent=2))
        return 0

    print("A5 vector candidate generation — %d memory_vectors, %d proxies, "
          "%d session rows" % (a.rows, int(a.rows * PROXY_FRACTION),
                               int(a.rows * SESSION_FRACTION)))
    print("query width %d dims (%d B); %d%% of rows match, %d%% are %d-dim (A0 split)"
          % (QUERY_DIMS, QUERY_DIMS * 4, int(MATCHING_FRACTION * 100),
             100 - int(MATCHING_FRACTION * 100), FOREIGN_DIMS))
    print()
    hdr = "%-20s %12s %12s %12s %12s" % ("function", "old ms", "new ms",
                                         "old peak MB", "new peak MB")
    print(hdr)
    print("-" * len(hdr))
    for name in ("_vector_beliefs", "_vector_proxies", "_observed_proxies"):
        o, n = results["old"]["per_fn"][name], results["new"]["per_fn"][name]
        print("%-20s %12.1f %12.1f %12.1f %12.2f"
              % (name, o["ms"], n["ms"], o["peak_mb"], n["peak_mb"]))
    to = sum(results["old"]["per_fn"][n]["ms"] for n in results["old"]["per_fn"])
    tn = sum(results["new"]["per_fn"][n]["ms"] for n in results["new"]["per_fn"])
    po = max(results["old"]["per_fn"][n]["peak_mb"] for n in results["old"]["per_fn"])
    pn = max(results["new"]["per_fn"][n]["peak_mb"] for n in results["new"]["per_fn"])
    print("-" * len(hdr))
    print("%-20s %12.1f %12.1f %12.1f %12.2f" % ("total / max peak", to, tn, po, pn))
    print()
    print("results sha256 (old == new): %s" % results["old"]["results_sha256"][:16])
    print("process peak RSS:  old %.0f MB   new %.0f MB"
          % (results["old"]["rss_mb"], results["new"]["rss_mb"]))
    if "search_ms" in results["new"]:
        print("end-to-end search() on the new path: %.1f ms, tracemalloc peak %.1f MB"
              % (results["new"]["search_ms"], results["new"]["search_peak_mb"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
