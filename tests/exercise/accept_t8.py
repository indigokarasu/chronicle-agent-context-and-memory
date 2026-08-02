#!/usr/bin/env python3
"""Acceptance test for t8 (vector memory/compute optimization).

Synthetic soak: paged iteration, numpy fast path, memory efficiency, top-k
correctness, session-prefix exclusion (§27 embeddings.exclude_session_prefixes)
and the prune script (scripts/prune_vectors.py).
"""

import builtins
import importlib.util
import json
import os
import re
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time

# Add chronicle to path.
chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder, pack
from engine.retrieval import RetrievalEngine
from engine.store import MemoryStore

PRUNE_SCRIPT = os.path.join(chronicle_dir, "scripts", "prune_vectors.py")
ORACLE_PATH = os.environ.get("T8_ORACLE", "/private/tmp/claude-501/"
                             "-Users-evaluser-temp/3d6d860f-71ee-406d-9aef-b68dfd0642d1/"
                             "scratchpad/oracle.json")
LME_SCRIPT = os.environ.get("T8_HARNESS", "/private/tmp/claude-501/"
                            "-Users-evaluser-temp/3d6d860f-71ee-406d-9aef-b68dfd0642d1/"
                            "scratchpad/lme_recall.py")
# Stock SQLite's SQLITE_LIMIT_VARIABLE_NUMBER. This Mac's build allows ~250k,
# which is exactly why a bind-the-ids prune passes here and dies on Linux.
VAR_LIMIT = 32766


def measure_rss():
    """Return RSS in MB (ru_maxrss is KB on Linux, bytes on macOS)."""
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_maxrss / (1024.0 * 1024.0) if sys.platform == "darwin" else r.ru_maxrss / 1024.0


def _p50(latencies_ms):
    s = sorted(latencies_ms)
    return s[len(s) // 2]


def _no_numpy():
    """Context manager that forces `import numpy` to fail, exercising the
    pure-python fallback in batch_cosine without needing numpy uninstalled."""
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("numpy blocked for pure-python path exercise")
        return real_import(name, *args, **kwargs)

    class _Guard:
        def __enter__(self):
            builtins.__import__ = mock_import
            return self

        def __exit__(self, *exc):
            builtins.__import__ = real_import

    return _Guard()


def _observed(eid, sid, excerpt):
    return {"event_id": eid, "type": "observed", "payload": json.dumps({"excerpt": excerpt}),
            "actor": "user", "owner": "default", "session_id": sid,
            "occurred_at": "2026-01-01T00:00:00Z"}


def test_paged_iteration_memory():
    """Insert 30000 vectors, run retrieve_raw 50x on both the numpy and
    pure-python paths, verify RSS growth stays bounded regardless of corpus
    size (the whole point of paging + streaming top-k)."""
    print("\n=== Test: Paged Iteration Memory ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        store = core.store

        embedder = HashingEmbedder(dimensions=256)
        rss_before = measure_rss()
        print(f"RSS before inserts: {rss_before:.1f} MB")

        for i in range(30000):
            payload = {"excerpt": f"test document {i} with some content"}
            event = {
                "event_id": f"e{i}",
                "type": "observed",
                "payload": json.dumps(payload),
                "actor": "user",
                "owner": "default",
                "session_id": f"s{i % 100}",  # 100 sessions
                "occurred_at": "2026-01-01T00:00:00Z",
            }
            store.append_event(event)
            blob = pack(embedder.embed(payload["excerpt"]))
            store.add_observed_vector(f"e{i}", blob, "hashing-v1", "default")
            if (i + 1) % 10000 == 0:
                print(f"  Inserted {i + 1} vectors...")

        rss_after_insert = measure_rss()
        print(f"RSS after inserts: {rss_after_insert:.1f} MB (delta: {rss_after_insert - rss_before:.1f} MB)")

        retrieval = RetrievalEngine(store, core.cfg, embedder)
        query = "test document sample query"

        # Numpy path (numpy is present on this box; this is the default fast path).
        np_latencies = []
        for _ in range(50):
            t0 = time.time()
            results = retrieval.retrieve_raw(query, limit=20)
            np_latencies.append((time.time() - t0) * 1000)
        rss_after_numpy = measure_rss()
        print(f"[numpy]        p50 latency: {_p50(np_latencies):.2f} ms  "
              f"(RSS after: {rss_after_numpy:.1f} MB, delta from post-insert: "
              f"{rss_after_numpy - rss_after_insert:.1f} MB)")

        # Pure-python fallback path, forced via monkeypatched import (numpy stays
        # installed; this only proves the fallback is exercised and correct/bounded).
        with _no_numpy():
            py_latencies = []
            for _ in range(50):
                t0 = time.time()
                retrieval.retrieve_raw(query, limit=20)
                py_latencies.append((time.time() - t0) * 1000)
        rss_after_queries = measure_rss()
        print(f"[pure-python]  p50 latency: {_p50(py_latencies):.2f} ms  "
              f"(RSS after: {rss_after_queries:.1f} MB, delta from post-insert: "
              f"{rss_after_queries - rss_after_insert:.1f} MB)")

        rss_delta = rss_after_queries - rss_after_insert
        print(f"RSS after 100 queries (both paths): {rss_after_queries:.1f} MB (delta: {rss_delta:.1f} MB)")
        print(f"Sample results (first numpy-path query): {results[:3]}")

        if rss_delta >= 200:
            print(f"FAIL: RSS delta {rss_delta:.1f} MB >= 200 MB")
            return False

        print("PASS: RSS delta < 200 MB across both paths")
        return True


def test_numpy_vs_pure_python():
    """Verify numpy fast path and pure-python fallback give identical results."""
    print("\n=== Test: NumPy vs Pure-Python Equivalence ===")

    embedder = HashingEmbedder(dimensions=128)
    query = embedder.embed("test query")
    docs = [pack(embedder.embed(f"document {i}")) for i in range(100)]

    from engine.embeddings import batch_cosine
    results_np = batch_cosine(query, docs)
    with _no_numpy():
        results_py = batch_cosine(query, docs)

    diffs = [abs(a - b) for a, b in zip(results_np, results_py)]
    max_diff = max(diffs) if diffs else 0
    print(f"Max difference between numpy and pure-python: {max_diff:.2e}")

    if max_diff > 1e-6:
        print(f"FAIL: Results differ by {max_diff:.2e} (threshold 1e-6)")
        return False

    print("PASS: Results equivalent (tolerance 1e-6)")
    return True


def test_topk_correctness():
    """Verify paged retrieve_raw gives the same top-k as a full, unpaged scan."""
    print("\n=== Test: Top-K Correctness (Paged vs Full Scan) ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        store = core.store
        embedder = HashingEmbedder(dimensions=256)

        for i in range(2000):
            payload = {"excerpt": f"doc {i}"}
            event = {
                "event_id": f"e{i}",
                "type": "observed",
                "payload": json.dumps(payload),
                "actor": "user",
                "owner": "default",
                "session_id": f"s{i % 50}",
                "occurred_at": "2026-01-01T00:00:00Z",
            }
            store.append_event(event)
            blob = pack(embedder.embed(payload["excerpt"]))
            store.add_observed_vector(f"e{i}", blob, "hashing-v1", "default")

        retrieval = RetrievalEngine(store, core.cfg, embedder)
        query = "test query"

        paged_results = retrieval.retrieve_raw(query, limit=20)
        paged_ids = {r["event_id"] for r in paged_results}

        # Reference: old-style unpaged full scan, reimplemented inline.
        from engine.embeddings import batch_cosine
        q = retrieval.query_understanding(query)
        ov = store.iter_observed_vectors()  # full load, only safe here (2000 rows)
        osims = batch_cosine(q["embedding"], [v["embedding"] for v in ov])
        ref_scored = {}
        for i, v in enumerate(ov):
            if osims[i] <= 0.1:
                continue
            ref_scored.setdefault(v["event_id"], {"score": 0.0})["score"] += osims[i] * 0.6
        ref_out = sorted(ref_scored.items(), key=lambda x: x[1]["score"], reverse=True)
        ref_ids = {k for k, _ in ref_out[:20]}

        if paged_ids != ref_ids:
            diff = paged_ids.symmetric_difference(ref_ids)
            print(f"FAIL: Paged and reference differ on {len(diff)} event IDs: {diff}")
            return False

        # Same at other depths, by score (tie-breaking among equal scores is not
        # specified), plus the degenerate limit the streaming top-k must not trip on.
        for k in (1, 5, 20):
            got = [round(r["score"], 9) for r in retrieval.retrieve_raw(query, limit=k)]
            want = [round(s["score"], 9) for _, s in ref_out[:k]]
            if got != want:
                print(f"FAIL: limit={k} scores {got} != full-scan {want}")
                return False
        if retrieval.retrieve_raw(query, limit=0) != []:
            print("FAIL: limit=0 must return [] (baseline out[:0]), not raise or return rows")
            return False

        print("PASS: Paged and reference full-scan agree on top-20 event IDs, "
              "on top-k scores for k=1/5/20, and limit=0 returns []")
        return True


# -- (c) embeddings.exclude_session_prefixes -------------------------------

def test_exclude_session_prefixes():
    """Events in an excluded session are still FTS-indexed (recall floor intact)
    but never vector-indexed, and their session summary is never embedded;
    with no prefixes configured everything is indexed as before."""
    print("\n=== Test: exclude_session_prefixes (c) ===")

    ok = True
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {"embeddings": {"model": "hashing", "dimensions": 256,
                              "exclude_session_prefixes": ["scratch-", "tmp-"]}}
        core = ChronicleCore(hermes_home=tmpdir, config=cfg)
        core.store.append_event(_observed("keep1", "keep-1", "widget report alpha"))
        core.store.append_event(_observed("scr1", "scratch-1", "widget report beta"))
        core.store.append_event(_observed("tmp1", "tmp-9", "widget report gamma"))

        vec_ids = {v["event_id"] for v in core.store.iter_observed_vectors()}
        print(f"vectors written (excluded config): {sorted(vec_ids)}")
        if vec_ids != {"keep1"}:
            print(f"FAIL: expected only 'keep1' vector-indexed, got {sorted(vec_ids)}")
            ok = False

        fts_ids = {r["event_id"] for r in core.store.fts_search_observed("widget", limit=10)}
        print(f"FTS-indexed (must include the excluded events): {sorted(fts_ids)}")
        if fts_ids != {"keep1", "scr1", "tmp1"}:
            print(f"FAIL: exclusion must skip vectors only, FTS has {sorted(fts_ids)}")
            ok = False

        for sid in ("keep-1", "scratch-1", "tmp-9"):
            core.curation._task_session_summarize({"session_id": sid})
        sess_ids = {s["session_id"] for s in core.store.iter_session_vectors()}
        print(f"session summaries embedded: {sorted(sess_ids)}")
        if sess_ids != {"keep-1"}:
            print(f"FAIL: expected only 'keep-1' session-indexed, got {sorted(sess_ids)}")
            ok = False

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {"embeddings": {"model": "hashing", "dimensions": 256}}  # default: [] prefixes
        core = ChronicleCore(hermes_home=tmpdir, config=cfg)
        core.store.append_event(_observed("keep1", "keep-1", "widget report alpha"))
        core.store.append_event(_observed("scr1", "scratch-1", "widget report beta"))
        core.curation._task_session_summarize({"session_id": "scratch-1"})
        vec_ids = {v["event_id"] for v in core.store.iter_observed_vectors()}
        sess_ids = {s["session_id"] for s in core.store.iter_session_vectors()}
        print(f"vectors written (default config): {sorted(vec_ids)}, sessions: {sorted(sess_ids)}")
        if vec_ids != {"keep1", "scr1"} or sess_ids != {"scratch-1"}:
            print("FAIL: default config must index everything (no exclusion by default)")
            ok = False

    print("PASS: exclusion skips vectors only, and is off by default" if ok
          else "FAIL: exclude_session_prefixes behaviour wrong")
    return ok


# -- (d) scripts/prune_vectors.py ------------------------------------------

def _seed_vector_db(db_path, sessions):
    """Real chronicle schema + bulk observed events/vectors. `sessions` maps
    session_id -> event count. Bulk SQL (not append_event) keeps the 33k-row
    variable-limit case fast; the prune only cares about events/observed_vectors."""
    store = MemoryStore(db_path)
    conn = store._conn()
    rows, vecs, seq = [], [], 0
    for sid, n in sessions.items():
        for i in range(n):
            seq += 1
            eid = f"{sid}:{i}"
            rows.append((eid, seq, "observed", json.dumps({"excerpt": eid}), "[]", "user",
                         "default", 2, sid, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"))
            vecs.append((eid, b"\x00" * 16, "hashing-v1", "default", "2026-01-01T00:00:00Z"))
    conn.executemany("INSERT INTO events(event_id,seq,type,payload,parents,actor,owner,trust_level,"
                     "session_id,occurred_at,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.executemany("INSERT INTO observed_vectors(event_id,embedding,model,owner,created_at) "
                     "VALUES(?,?,?,?,?)", vecs)
    conn.commit()
    return store


def _run_prune(db_path, prefixes, dry_run=False):
    cmd = [sys.executable, PRUNE_SCRIPT, "--db", db_path]
    for p in prefixes:
        cmd += ["--session-prefix", p]
    if dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _counts(store):
    return store.count_rows("observed_vectors"), store.count_rows("events")


def test_prune_script():
    """--dry-run reports without deleting; a real run deletes exactly the
    matching sessions' vectors, leaves other sessions and the event log alone,
    and is idempotent. No prefix is a usage error, not a silent no-op."""
    print("\n=== Test: prune_vectors.py (d) ===")

    ok = True
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "chronicle.db")
        store = _seed_vector_db(db, {"scratch-a": 40, "scratch-b": 25, "keep-1": 30})

        r = _run_prune(db, ["scratch-"], dry_run=True)
        print(f"[dry-run] rc={r.returncode} out={r.stdout.strip()!r}")
        vec, ev = _counts(store)
        if r.returncode != 0 or "65" not in r.stdout or (vec, ev) != (95, 95):
            print(f"FAIL: dry-run must report 65 and delete nothing (vectors={vec}, events={ev})")
            ok = False

        r = _run_prune(db, ["scratch-"])
        print(f"[delete]  rc={r.returncode} out={r.stdout.strip()!r}")
        vec, ev = _counts(store)
        left = {v["event_id"].split(":")[0] for v in store.iter_observed_vectors()}
        if r.returncode != 0 or (vec, ev) != (30, 95) or left != {"keep-1"}:
            print(f"FAIL: expected 30 keep-1 vectors and 95 events left, got {vec}/{ev} {left}")
            ok = False

        r = _run_prune(db, ["scratch-"])
        if r.returncode != 0 or store.count_rows("observed_vectors") != 30:
            print("FAIL: re-running the prune must be a no-op")
            ok = False

        r = _run_prune(db, [])
        print(f"[no prefix] rc={r.returncode} err={r.stderr.strip()!r}")
        if r.returncode == 0 or store.count_rows("observed_vectors") != 30:
            print("FAIL: a missing --session-prefix must be a usage error, not a no-op")
            ok = False

        r = _run_prune(db, ["keep-1", "nothing-matches-"])
        if r.returncode != 0 or store.count_rows("observed_vectors") != 0:
            print("FAIL: repeated --session-prefix must prune each prefix")
            ok = False

    print("PASS: prune dry-run/delete/idempotence/multi-prefix all correct" if ok
          else "FAIL: prune script behaviour wrong")
    return ok


class _CappedConnection(sqlite3.Connection):
    """Emulates a stock SQLITE_LIMIT_VARIABLE_NUMBER build (this Mac's allows ~250k)."""

    def execute(self, sql, parameters=()):
        if len(parameters) > VAR_LIMIT:
            raise sqlite3.OperationalError("too many SQL variables")
        return sqlite3.Connection.execute(self, sql, parameters)


def test_prune_variable_limit():
    """A prefix matching more than SQLITE_LIMIT_VARIABLE_NUMBER events must still
    prune: the delete joins to events in SQL and never binds matched ids as
    parameters. Run in-process against a connection capped at the stock limit,
    so the check holds on this box's ~250k-variable SQLite too."""
    print("\n=== Test: prune under stock SQLite variable limit (d) ===")

    n_big = VAR_LIMIT + 234  # 33000 — one bind per id would exceed the cap
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "chronicle.db")
        store = _seed_vector_db(db, {"big-": n_big, "keep-1": 10})

        spec = importlib.util.spec_from_file_location("prune_vectors", PRUNE_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        real_connect = sqlite3.connect

        def capped_connect(path, *a, **kw):
            kw.setdefault("factory", _CappedConnection)
            return real_connect(path, *a, **kw)

        sqlite3.connect = capped_connect
        try:
            deleted = mod.prune_vectors(db, ["big-"], dry_run=False)
        except sqlite3.OperationalError as e:
            print(f"FAIL: prune bound matched ids as parameters ({e})")
            return False
        finally:
            sqlite3.connect = real_connect

        remaining = store.count_rows("observed_vectors")
        print(f"deleted {deleted} of {n_big + 10} vectors under a {VAR_LIMIT}-variable cap; "
              f"{remaining} left")
        if deleted != n_big or remaining != 10:
            print(f"FAIL: expected {n_big} deleted / 10 left, got {deleted}/{remaining}")
            return False

    print("PASS: prune survives a prefix matching > SQLITE_LIMIT_VARIABLE_NUMBER events")
    return True


def test_regression_harness():
    """Run the regression harness and check recall is within 3 points of baseline."""
    print("\n=== Test: Regression Harness ===")

    if not os.path.exists(ORACLE_PATH) or not os.path.exists(LME_SCRIPT):
        print(f"FAIL: harness or oracle not found ({LME_SCRIPT}, {ORACLE_PATH})")
        return False

    result = subprocess.run(
        [sys.executable, LME_SCRIPT, ORACLE_PATH],
        env={**os.environ, "CHRONICLE_DIR": chronicle_dir},
        capture_output=True, text=True, timeout=600)

    print("Harness output:")
    print(result.stdout)
    if result.stderr:
        print("Stderr:", result.stderr)

    # The harness prints two separate tables ("SESSION-LEVEL RECALL@k" and
    # "TURN-LEVEL RECALL@k"), each with belief/raw/union rows and k=1,3,5,10
    # columns, followed on its own line by "ABSTENTION ..." — union@1 and
    # ABSTENTION never appear on the same line, so we parse the TURN-LEVEL
    # table's union row directly instead of grep'ing for both substrings.
    lines = result.stdout.split("\n")
    turn_idx = next((i for i, l in enumerate(lines) if "TURN-LEVEL RECALL@k" in l), None)
    if turn_idx is None:
        print("FAIL: Could not find TURN-LEVEL RECALL@k table in harness output")
        return False

    union_line = next((l for l in lines[turn_idx:turn_idx + 10] if l.strip().startswith("union")), None)
    if not union_line:
        print("FAIL: Could not find union row in TURN-LEVEL RECALL@k table")
        return False

    nums = re.findall(r"([\d.]+)%", union_line)  # columns are k=1,3,5,10 in order
    if not nums:
        print(f"FAIL: Could not extract recall from '{union_line}'")
        return False

    recall = float(nums[0])
    baseline_union_at_1 = 65.0
    delta = abs(recall - baseline_union_at_1)

    print(f"Baseline recall (turn-level union@1): {baseline_union_at_1}%")
    print(f"Observed recall (turn-level union@1): {recall}%")
    print(f"Delta: {delta:.1f} points")

    if delta <= 3.0:
        print("PASS: Recall within 3 points of baseline")
        return True
    print(f"FAIL: Recall delta {delta:.1f} > 3.0 points")
    return False


def main():
    tests = [
        ("Paged Iteration Memory", test_paged_iteration_memory),
        ("NumPy vs Pure-Python", test_numpy_vs_pure_python),
        ("Top-K Correctness", test_topk_correctness),
        ("Exclude Session Prefixes", test_exclude_session_prefixes),
        ("Prune Script", test_prune_script),
        ("Prune Variable Limit", test_prune_variable_limit),
        ("Regression Harness", test_regression_harness),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n=== Summary ===")
    for name, passed in results:
        print(f"{name}: {'PASS' if passed else 'FAIL'}")

    sys.exit(0 if all(p for _, p in results) else 1)


if __name__ == "__main__":
    main()
