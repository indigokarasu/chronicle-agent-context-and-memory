#!/usr/bin/env python3
"""Acceptance test for u5 (optional sqlite-vec ANN backend, §27 vector_index:).

Exercises the REAL production wiring: ChronicleCore builds exactly ONE
VectorIndex and hands it to both the store (writes: add/delete/prune) and the
retrieval engine (reads: KNN in retrieve_raw). Vectors are written through
`core.capture.observe()` -- the reducer's `_on_observed` embeds and calls
`store.add_observed_vector` itself, nested inside `append_event`'s single
re-entrant transaction (I7), which is the hardest case for the ANN mirror.

The bar: with backend="sqlite-vec" and the library loadable, retrieve_raw must
return the SAME top-k as the paged brute-force path -- swept over K in
{5,10,20,50}, exact event-id set equality at every K (the one documented
allowance, exact-score tie clusters straddling the cut, is fenced in by
`_compare_topk`), and score deltas under 1e-6 (float32 vec0 distance vs
float64/numpy dot; ~1e-7 in practice). No environment-limit escape hatch: this
file REFUSES to run on an interpreter whose sqlite3 lacks
`enable_load_extension`, because a brute-force-vs-brute-force comparison passes
trivially and proves nothing.

Scenario 0 is the regression guard for the defect this file was rewritten
around: the paged scan visits every row, so it credits `_vec_w * cos` to EVERY
FTS hit; a bounded KNN window reaches only its own top-k, so an FTS hit outside
that window silently lost its entire vector contribution and dropped out of the
results. The corpus deliberately contains lexical decoys (all query terms plus
a long unique-filler tail) that rank high on bm25 but land well outside the KNN
window with cosine still above the 0.1 floor -- exactly that shape. Scenario 0
asserts such cases actually occur, so scenario 1's parity check can never be
vacuously satisfied.
"""

import os
import sqlite3
import sys
import tempfile

chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore
from engine.embeddings import batch_cosine, pack

N_REGULAR = 460
N_DECOY = 40
N_QUERIES = 20
DIMS = 256
K_SWEEP = (5, 10, 20, 50)
SCORE_TOL = 1e-6
# Filler tokens per decoy: enough dilution that its normalized embedding falls
# outside the KNN window, not so much that cosine drops under retrieve_raw's
# 0.1 floor (below which BOTH paths agree by dropping it, and the case stops
# being a discriminator). Calibrated against the corpus below; scenario 0 fails
# loudly rather than silently if the calibration ever stops holding.
DECOY_FILLER = 40

# Obviously-fake identities/orgs only (never realistic personal facts).
_SUBJECTS = ["Pat Testley", "Sam Rivera", "Jordan Kwan", "Casey Okafor", "Riley Chen",
             "Morgan Diaz", "Taylor Novak", "Drew Alaoui", "Avery Lindqvist", "Quinn Osei"]
_ROLES = ["backend engineer", "product manager", "data scientist", "QA lead", "designer",
          "recruiter", "sales rep", "support engineer", "researcher", "founder"]
_ORGS = ["Acme Fake Co", "Globex Testing Ltd", "Initech Sample Inc", "Umbrella Mock Corp",
         "Wonka Fixture LLC", "Hooli Placeholder", "Stark Sample Industries",
         "Wayne Fixture Enterprises", "Soylent Test Group", "Aperture Fake Labs"]
_TOPICS = ["machine learning", "distributed systems", "user research", "quarterly planning",
           "on-call rotations", "hiring", "customer escalations", "roadmap review",
           "security audits", "performance tuning"]


def _make_queries(n):
    return [f"{_ROLES[i % len(_ROLES)]} working on {_TOPICS[(i * 3 + 1) % len(_TOPICS)]}"
            for i in range(n)]


def _make_corpus():
    """Deterministic corpus: ordinary records plus lexical decoys (see module
    docstring / scenario 0). Returned in one list so both stores see
    byte-identical input in byte-identical order."""
    out = []
    for i in range(N_REGULAR):
        subj = _SUBJECTS[i % len(_SUBJECTS)]
        role = _ROLES[(i // len(_SUBJECTS)) % len(_ROLES)]
        org = _ORGS[(i // (len(_SUBJECTS) * len(_ROLES))) % len(_ORGS)]
        topic = _TOPICS[i % len(_TOPICS)]
        out.append(f"{subj} is a {role} at {org} working on {topic} (item #{i})")
    queries = _make_queries(N_QUERIES)
    for d in range(N_DECOY):
        q = queries[d % len(queries)]
        filler = " ".join("zz%dfiller%d" % (d, j) for j in range(DECOY_FILLER))
        out.append(f"Pat Testley logged a memo mentioning {q} at Acme Fake Co "
                   f"(decoy #{d}) {filler}")
    return out


def _build_core(backend, home):
    cfg = {
        "embeddings": {"model": "hashing", "dimensions": DIMS},
        "vector_index": {"backend": backend, "bruteforce_ceiling": 100000},
    }
    return ChronicleCore(home, cfg)


def _populate(core, texts):
    for i, text in enumerate(texts):
        core.capture.observe(text, "noted", session_id=f"s{i % 20}",
                             occurred_at="2026-01-01T00:00:00Z")


def _require_loadable_extensions():
    """Hard gate. A run without loadable-extension support can only compare
    brute force against itself, so it is refused outright rather than reported
    as a pass."""
    missing = []
    if not hasattr(sqlite3.Connection, "enable_load_extension"):
        missing.append(f"{sys.executable} has no sqlite3.Connection.enable_load_extension "
                       "(Apple's macOS system Python is built with SQLITE_OMIT_LOAD_EXTENSION)")
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        missing.append(f"sqlite_vec is not importable by {sys.executable} "
                       "(pip install --user sqlite-vec)")
    if missing:
        print("REFUSING TO RUN -- the sqlite-vec fast path is unreachable here, and a "
              "brute-force-vs-brute-force comparison would pass without proving anything:")
        for m in missing:
            print("  - " + m)
        print("Re-run under an interpreter with loadable-extension support, e.g.\n"
              "  /opt/homebrew/bin/python3.11 tests/exercise/accept_u5.py")
        sys.exit(2)
    print(f"  interpreter: {sys.executable} (sqlite3 {sqlite3.sqlite_version}, "
          f"enable_load_extension present, sqlite_vec importable)")


# -- fixtures shared by scenarios 0 and 1 ---------------------------------

_STATE = {}


def setup_stores():
    texts = _make_corpus()
    core_knn = _build_core("sqlite-vec", tempfile.mkdtemp())
    _populate(core_knn, texts)
    assert core_knn.vector_index.probe(), "sqlite-vec must be usable after the hard gate above"

    core_bf = _build_core("bruteforce", tempfile.mkdtemp())
    _populate(core_bf, texts)
    assert not core_bf.vector_index.is_enabled(), "bruteforce config must never engage the ANN path"

    n_obs = core_knn.store.count_rows("observed_vectors")
    n_vec = core_knn.store._conn().execute("SELECT count(*) FROM vec0").fetchone()[0]
    assert n_vec == n_obs and n_vec > 0, \
        f"vec0 mirror is incomplete: {n_vec} rows vs observed_vectors {n_obs}"
    print(f"  PASS: vec0 mirror populated through capture.observe() -> reducer -> "
          f"store.add_observed_vector: {n_vec} rows == observed_vectors {n_obs}")
    _STATE.update(core_knn=core_knn, core_bf=core_bf, queries=_make_queries(N_QUERIES))


def test_fts_hits_fall_outside_the_knn_window():
    """Non-vacuity guard: prove the corpus really contains FTS hits that the KNN
    window does NOT reach and whose cosine clears the 0.1 floor -- the exact
    shape that lost its whole vector contribution before the by-id credit."""
    core = _STATE["core_knn"]
    vi, store, retr = core.vector_index, core.store, core.retrieval
    per_k = {}
    total = 0
    for k in K_SWEEP:
        n = 0
        for query in _STATE["queries"]:
            emb = retr.query_understanding(query)["embedding"]
            fts_ids = [r["event_id"] for r in store.fts_search_observed(query, limit=k)]
            knn_ids = {eid for eid, _s in vi.retrieve_knn(pack(emb), k * 2)}
            outside = [e for e in fts_ids if e not in knn_ids]
            vrows = store.get_observed_vectors_by_ids(outside)
            sims = batch_cosine(emb, [vrows[e]["embedding"] for e in outside if e in vrows])
            n += sum(1 for s in sims if s > 0.1)
        per_k[k] = n
        total += n
    print(f"  FTS hits outside the KNN window with cosine > 0.1, by K: {per_k}")
    assert total > 0, (
        "corpus produced NO FTS hit outside the KNN window above the 0.1 floor -- the "
        "parity check below would be vacuous for the defect this test exists to catch; "
        "retune DECOY_FILLER")
    print(f"  PASS: {total} such cases across the sweep -- parity below is a real test")


def _compare_topk(bf, knn, k, query):
    """Compare one query's two top-k results. Returns (max score delta, number
    of boundary-tie substitutions); raises AssertionError on real divergence.

    Set equality is asserted EXACTLY everywhere except inside an exact-score tie
    cluster that straddles the cut -- with a bag-of-tokens embedder over a
    templated corpus, many records share a token multiset and therefore an
    identical cosine, so which members of a 4-way tie at rank k survive is
    arbitrary in BOTH paths. That allowance is kept from hiding anything by two
    tighter checks it cannot absorb:
      * the two score SEQUENCES must agree position by position within
        SCORE_TOL -- a lost `_vec_w * cos` contribution (the u5 defect: ~0.19,
        five orders of magnitude above tolerance) changes the numbers, tie or
        no tie, so it cannot be dressed up as a reordering; and
      * every id scoring strictly above the cut must match exactly, so a
        substitution is only ever tolerated among genuinely equal scores.
    """
    assert len(bf) == len(knn), (
        f"K={k}: {len(bf)} brute-force results vs {len(knn)} KNN results for {query!r}")
    worst = 0.0
    for i, (a, b) in enumerate(zip(bf, knn)):
        d = abs(a["score"] - b["score"])
        assert d < SCORE_TOL, (
            f"K={k}: score sequences diverge at rank {i} for {query!r}: brute-force "
            f"{a['score']:.12f} ({a['event_id']}) vs KNN {b['score']:.12f} ({b['event_id']}), "
            f"delta {d:.3e} >= {SCORE_TOL:.0e}")
        worst = max(worst, d)
    if not bf:
        return worst, 0
    cut = bf[-1]["score"]
    strict_bf = {r["event_id"] for r in bf if r["score"] > cut + SCORE_TOL}
    strict_knn = {r["event_id"] for r in knn if r["score"] > cut + SCORE_TOL}
    assert strict_bf == strict_knn, (
        f"K={k}: ids scoring strictly above the rank-{k} cut differ for {query!r} "
        f"(missing from KNN: {sorted(strict_bf - strict_knn)}; "
        f"extra in KNN: {sorted(strict_knn - strict_bf)})")
    scores = {r["event_id"]: r["score"] for r in bf}
    scores.update((r["event_id"], r["score"]) for r in knn)
    diff = {r["event_id"] for r in bf} ^ {r["event_id"] for r in knn}
    for eid in diff:
        assert abs(scores[eid] - cut) < SCORE_TOL, (
            f"K={k}: {eid} appears in only one path for {query!r} at score "
            f"{scores[eid]:.12f}, which is NOT tied with the rank-{k} cut {cut:.12f} -- "
            f"a real recall difference, not a tie reordering")
    return worst, len(diff) // 2


def test_knn_matches_bruteforce_across_k_sweep():
    core_knn, core_bf = _STATE["core_knn"], _STATE["core_bf"]
    worst_overall = 0.0
    for k in K_SWEEP:
        worst = 0.0
        ties = 0
        for query in _STATE["queries"]:
            bf = core_bf.retrieval.retrieve_raw(query, limit=k)
            knn = core_knn.retrieval.retrieve_raw(query, limit=k)
            d, t = _compare_topk(bf, knn, k, query)
            worst = max(worst, d)
            ties += t
        worst_overall = max(worst_overall, worst)
        print(f"  PASS K={k:2d}: top-{k} identical for all {N_QUERIES} queries "
              f"({ties} exact-score tie substitutions at the rank-{k} cut, 0 real differences); "
              f"max |score_knn - score_bruteforce| = {worst:.3e} (< {SCORE_TOL:.0e})")
    print(f"  PASS: {len(K_SWEEP)} K values swept over {N_REGULAR + N_DECOY} vectors; "
          f"worst score delta anywhere = {worst_overall:.3e}")


def test_delete_removes_the_mirror_row():
    core = _STATE["core_knn"]
    eid = core.store._conn().execute("SELECT event_id FROM observed_vectors LIMIT 1").fetchone()[0]
    core.store.delete_observed_vector(eid)
    left = core.store._conn().execute("SELECT count(*) FROM vec0 WHERE event_id=?", (eid,)).fetchone()[0]
    assert left == 0, "delete_observed_vector left the vec0 mirror row behind"
    assert not core.store.has_observed_vector(eid)
    print(f"  PASS: delete_observed_vector dropped {eid} from observed_vectors AND vec0")


def test_acl_pruned_window_widens():
    """The other way a bounded window under-reaches: the top of it is entirely
    unreadable. `retrieve_raw` filters KNN candidates by ACL exactly as the
    paged scan does, so a store whose best matches belong to ANOTHER user hands
    the heap nothing until the window is widened past them. Here the top ~60 by
    cosine are unreadable, which buries the readable tier well beyond the
    initial 2*limit rows."""
    hot = [f"backend engineer working on machine learning update {i}" for i in range(60)]
    cool = [f"{_SUBJECTS[i % len(_SUBJECTS)]} is a backend engineer at Acme Fake Co "
            f"filing {_TOPICS[i % len(_TOPICS)]} paperwork (row {i})" for i in range(200)]
    query = "backend engineer working on machine learning"

    def build(backend):
        core = _build_core(backend, tempfile.mkdtemp())
        core.capture.owner = "otheruser:bot"        # not readable by principal "default"
        _populate(core, hot)
        core.capture.owner = "default"
        _populate(core, cool)
        return core

    core_knn, core_bf = build("sqlite-vec"), build("bruteforce")
    assert core_knn.vector_index.probe()
    bf = core_bf.retrieval.retrieve_raw(query, limit=10, principal="default")
    knn = core_knn.retrieval.retrieve_raw(query, limit=10, principal="default")
    assert len(bf) == 10, f"fixture is wrong: brute force found only {len(bf)} readable results"
    for r in bf + knn:
        ev = (core_bf if r in bf else core_knn).store.get_event(r["event_id"])
        assert ev["owner"] == "default", f"{r['event_id']} leaked across users (owner {ev['owner']!r})"
    d, ties = _compare_topk(bf, knn, 10, query)
    print(f"  PASS: 60 unreadable top-cosine rows did not starve the KNN heap -- "
          f"top-10 matches brute force ({ties} tie substitutions), max delta {d:.3e}")


def test_fallback_when_sqlite_vec_not_importable():
    """"Library not installed": flip the module-level guard every VectorIndex
    method reads. `_SQLITE_VEC_AVAILABLE` is set once by a `try: import
    sqlite_vec` that already ran at import time, so patching builtins.__import__
    now would not touch it."""
    import engine.vector_index as vi
    saved = vi._SQLITE_VEC_AVAILABLE
    vi._SQLITE_VEC_AVAILABLE = False
    try:
        core = _build_core("sqlite-vec", tempfile.mkdtemp())
        assert not core.vector_index.is_enabled(), "is_enabled() must be False with the lib unavailable"
        _populate(core, _make_corpus()[:40])
        no_vec0 = core.store._conn().execute(
            "SELECT count(*) FROM sqlite_master WHERE name='vec0'").fetchone()[0] == 0
        assert no_vec0, "vec0 must never be created when sqlite_vec is unavailable"
        results = core.retrieval.retrieve_raw("backend engineer working on hiring", limit=10)
        assert results, "fallback retrieval returned no results"
        print(f"  PASS: no vec0 created; paged brute-force answered with {len(results)} results")
    finally:
        vi._SQLITE_VEC_AVAILABLE = saved


def test_default_bruteforce_backend_untouched():
    core = _build_core("bruteforce", tempfile.mkdtemp())
    assert not core.vector_index.is_enabled()
    _populate(core, _make_corpus()[:40])
    no_vec0 = core.store._conn().execute(
        "SELECT count(*) FROM sqlite_master WHERE name='vec0'").fetchone()[0] == 0
    assert no_vec0, "the default backend must never create vec0"
    results = core.retrieval.retrieve_raw("designer working on roadmap review", limit=10)
    assert results, "brute-force retrieval returned no results"
    print(f"  PASS: default backend never touched sqlite-vec; {len(results)} results")


if __name__ == "__main__":
    print("Running u5 acceptance tests...")
    _require_loadable_extensions()

    print(f"\n0. Fixtures + non-vacuity guard ({N_REGULAR + N_DECOY} vectors via capture.observe):")
    setup_stores()
    test_fts_hits_fall_outside_the_knn_window()

    print(f"\n1. KNN vs brute-force parity, K sweep {list(K_SWEEP)} x {N_QUERIES} queries:")
    test_knn_matches_bruteforce_across_k_sweep()

    print("\n2. Deletes propagate to the vec0 mirror:")
    test_delete_removes_the_mirror_row()

    print("\n3. KNN window widens when ACL filtering prunes its top:")
    test_acl_pruned_window_widens()

    print("\n4. Fallback when sqlite_vec is not importable:")
    test_fallback_when_sqlite_vec_not_importable()

    print("\n5. Default bruteforce backend untouched:")
    test_default_bruteforce_backend_untouched()

    print("\nAll acceptance tests passed.")
