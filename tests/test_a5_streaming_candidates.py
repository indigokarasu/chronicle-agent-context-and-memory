"""
Chronicle — A5: bounded vector candidate generation.

`_vector_beliefs`, `_vector_proxies` and `_observed_proxies` used to pull their
whole table into Python on every `search()` (`SELECT * FROM memory_vectors`
into a list of dicts, plus `query_proxy_vectors` twice). Measured at 100k rows
with production's width split: 975 ms and an 812 MB Python allocation peak per
query, 1178 MB process RSS. They now page by rowid and keep a bounded top-k.

A5 is an OPTIMISATION, so the bar is not "still reasonable" but "byte-identical
ranking". These tests hold that bar three ways:

  1. DIFFERENTIAL. The pre-change implementations live once, verbatim, in
     `scripts/bench_a5_vectors.py` (`ref_*`) — the same copies the benchmark
     times, so the reference cannot drift from what was measured. Every case
     below runs both and demands identical tuples, identical order, identical
     float bits (`repr`, not `assertAlmostEqual`).
  2. ADVERSARIAL INPUT. Ties, duplicate blobs, several proxies per belief,
     mixed widths, empty blobs, limits above and below the candidate count,
     and page sizes that divide the table evenly, unevenly, and not at all.
  3. ACL. Candidate generation reads vectors, which carry no ACL of their own;
     `search()`'s `add()` re-fetches the parent row and applies
     `_readable` (A1's choke point). The fast path must not become a way
     around that, so a sandboxed principal's belief is asserted to be RETURNED
     by the fast path and ABSENT from another principal's `search()` — a test
     that would fail both if the guard were removed and if the fast path
     started returning rows the old one did not.

Fake fixtures only: synthetic ids, values from a fixed word list, vectors from
the hashing embedder or a seeded PRNG. Nothing here reads a real store.
"""

import os
import random
import shutil
import struct
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from engine import access                                        # noqa: E402
from engine.config import Config                                 # noqa: E402
from engine.core import ChronicleCore                            # noqa: E402
from engine.embeddings import HashingEmbedder                    # noqa: E402
from engine.retrieval import VECTOR_SCAN_PAGE, RetrievalEngine   # noqa: E402
from engine.store import MemoryStore                             # noqa: E402

from bench_a5_vectors import (                                   # noqa: E402
    ref_observed_proxies, ref_vector_beliefs, ref_vector_proxies)

DIMS = 768                 # a real embedding width, not a toy one: the BLAS
FOREIGN_DIMS = 2048        # shape effect below is width-dependent (see
                           # _tail_merged), so the fixture uses production's
                           # own 768/2048 split (A0) rather than something
                           # small and fast that would not exercise it.
WORDS = ["acme", "fake", "coffee", "pat", "testley", "vega", "nairobi", "kestrel",
         "lantern", "otter", "quartz", "meridian", "tulip", "basalt", "nimbus"]


class _Blobs:
    """Deterministic unit-norm float32 blobs, one seeded source per fixture.

    numpy when present purely for seeding speed (5k x 768 pure-Python
    gaussians is seconds of test time); the fallback is equivalent in shape,
    and no assertion depends on which was used — without numpy `batch_cosine`
    degrades to scalar `cosine`, which has no shape effect at all and makes
    every case below trivially identical.
    """

    def __init__(self, seed_value, chunk=256):
        self.chunk, self._pools = chunk, {}
        try:
            import numpy as np
            self._np, self._rng = np, np.random.default_rng(seed_value)
        except Exception:
            self._np, self._py = None, random.Random(seed_value)

    def __call__(self, dims):
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


class _SeededStore(unittest.TestCase):
    """A store built to make the two paths disagree if they can.

    ROWS is deliberately not a multiple of any page size tested, and the
    tie/duplicate structure is the point: equal cosines are where a heap and a
    stable sort part company if the tie-break is wrong, and duplicate blobs
    are the only way to manufacture equal cosines that survive float32.
    """

    ROWS = 5003          # > 3 pages of COMPARABLE rows at the shipping page
                         # size, so the tail merge is exercised there and not
                         # only at the smaller sweep values
    DUP_EVERY = 7          # every 7th belief reuses the previous blob -> exact ties
    FOREIGN_EVERY = 3      # every 3rd row is the wrong width -> hard 0.0

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="a5-diff-")
        cls.store = MemoryStore(os.path.join(cls.home, "a5.db"))
        cls.embedder = HashingEmbedder(dimensions=DIMS)
        cls.engine = RetrievalEngine(
            cls.store, Config({"embeddings": {"model": "hashing", "dimensions": DIMS}}),
            embedder=cls.embedder, vector_index=None)

        rng = random.Random(20260910)
        blob_of = _Blobs(20260910)
        conn = cls.store._conn()
        conn.execute("BEGIN")
        prev = None
        for i in range(cls.ROWS):
            foreign = (i % cls.FOREIGN_EVERY) == 0
            if foreign:
                blob = blob_of(FOREIGN_DIMS)
            elif prev is not None and (i % cls.DUP_EVERY) == 0:
                blob = prev                       # exact tie with an earlier row
            else:
                blob = blob_of(DIMS)
                prev = blob
            if i % 97 == 5:
                blob = b""                        # empty blob: 0.0 in both paths
            conn.execute(
                "INSERT INTO memory_vectors(belief_id,kind,embedding,model,created_at) "
                "VALUES(?,?,?,?,?)",
                ("b%05d" % i, "fact" if i % 4 else "note", blob,
                 "foreign-tag" if foreign else "nomic-embed-text", "2026-01-01T00:00:00Z"))

        # Proxies: several per belief (that is the whole reason
        # _vector_proxies reduces best-per-belief), split between the belief
        # tier (kind != 'observed') and the §H2.4 excerpt tier (kind ==
        # 'observed') that _observed_proxies owns.
        prev = None
        for i in range(cls.ROWS // 2):
            foreign = (i % cls.FOREIGN_EVERY) == 0
            if foreign:
                blob = blob_of(FOREIGN_DIMS)
            elif prev is not None and (i % cls.DUP_EVERY) == 0:
                blob = prev
            else:
                blob = blob_of(DIMS)
                prev = blob
            conn.execute(
                "INSERT INTO query_proxy_vectors"
                "(belief_id,proxy_idx,kind,question,embedding,model,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                ("b%05d" % (i % 40), i, "observed" if i % 5 == 0 else "fact",
                 "q?", blob, "m", "2026-01-01T00:00:00Z"))
        conn.execute("COMMIT")

        cls.queries = [cls.embedder.embed(" ".join(rng.choice(WORDS) for _ in range(4)))
                       for _ in range(12)]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def assertBitIdentical(self, old, new, msg=""):
        """Exact equality including float bits and order.

        `repr` rather than assertAlmostEqual on purpose: a tolerance would let
        exactly the class of drift this task forbids (a different summation
        order, an f32-vs-f64 accumulator) pass unnoticed.
        """
        self.assertEqual(len(old), len(new), "length differs: %s" % msg)
        self.assertEqual([tuple(repr(x) for x in row) for row in old],
                         [tuple(repr(x) for x in row) for row in new], msg)


class TestVectorBeliefsDifferential(_SeededStore):
    def test_identical_across_queries_and_limits(self):
        for qi, emb in enumerate(self.queries):
            for limit in (1, 3, 10, 40, 500, 5000):
                self.assertBitIdentical(
                    ref_vector_beliefs(self.store, emb, limit),
                    self.engine._vector_beliefs(emb, limit),
                    "_vector_beliefs q=%d limit=%d" % (qi, limit))

    def test_identical_at_every_page_size(self):
        """Paging must be invisible: pages that divide the table evenly, that
        leave a remainder, that are 1 row, and that exceed the table.

        The sweep starts at 128 — the measured BLAS crossover at this
        fixture's 768-dim width, see
        `_tail_merged` — not at 1. Below the crossover bit-identity is not
        achievable at all (test_sub_crossover_pages_drift_by_one_ulp pins what
        happens there instead); at and above it, `_tail_merged` is what keeps
        the short FINAL page from dropping under. 1000 is what ships; the
        others prove the property is not an accident of that one value.
        """
        import engine.retrieval as R
        saved = R.VECTOR_SCAN_PAGE
        try:
            for page in (128, 256, 400, 700, 1000, 100000):
                R.VECTOR_SCAN_PAGE = page
                for emb in self.queries[:4]:
                    self.assertBitIdentical(
                        ref_vector_beliefs(self.store, emb, 25),
                        self.engine._vector_beliefs(emb, 25),
                        "page=%d" % page)
                    self.assertBitIdentical(
                        ref_vector_proxies(self.store, emb, 25),
                        self.engine._vector_proxies(emb, 25),
                        "proxies page=%d" % page)
                    self.assertBitIdentical(
                        ref_observed_proxies(self.store, emb, 25),
                        self.engine._observed_proxies(emb, 25),
                        "observed proxies page=%d" % page)
        finally:
            R.VECTOR_SCAN_PAGE = saved

    def test_sub_crossover_pages_drift_by_one_ulp(self):
        """The honest boundary of the bit-identity claim, pinned rather than
        hidden.

        Below the BLAS crossover the streamed scores are NOT bit-identical —
        `batch_cosine` gets a different gemv kernel. What survives is what
        matters: the same beliefs, in the same order, with scores that differ
        by ~1e-8. This test exists so that a future reader who sets
        VECTOR_SCAN_PAGE to 32 finds a stated consequence instead of a
        mysterious eval wobble, and so that a change which turned that 1e-8
        into something that reorders results fails here.
        """
        import engine.retrieval as R
        saved = R.VECTOR_SCAN_PAGE
        emb = self.queries[0]
        old = ref_vector_beliefs(self.store, emb, 25)
        try:
            worst = 0.0
            for page in (1, 2, 16, 64):
                R.VECTOR_SCAN_PAGE = page
                new = self.engine._vector_beliefs(emb, 25)
                self.assertEqual([(b, k) for b, k, _s in old],
                                 [(b, k) for b, k, _s in new],
                                 "sub-crossover paging REORDERED results at page=%d — "
                                 "that is a behaviour change, not a rounding artifact" % page)
                worst = max(worst, max(abs(a[2] - b[2]) for a, b in zip(old, new)))
            self.assertLess(worst, 1e-6, "drift is larger than a float32 ULP: %r" % worst)
        finally:
            R.VECTOR_SCAN_PAGE = saved

    def test_tail_merge_never_emits_a_short_batch(self):
        """The invariant `_tail_merged` sells: every batch it yields is at
        least `page_size` long, unless the whole scan was one short batch."""
        from engine.retrieval import _tail_merged
        for total in (0, 1, 5, 617, 1000, 1001, 2500):
            for page in (1, 7, 256, 1000):
                pages = [list(range(i, min(i + page, total)))
                         for i in range(0, total, page)]
                out = list(_tail_merged(iter(pages), page))
                self.assertEqual([x for b in out for x in b], list(range(total)),
                                 "rows lost/reordered total=%d page=%d" % (total, page))
                if len(out) > 1:
                    for b in out:
                        self.assertGreaterEqual(len(b), page,
                                                "short batch survived: total=%d page=%d"
                                                % (total, page))

    def test_ties_break_first_seen_in_both_paths(self):
        """The fixture manufactures exact ties; assert they actually occur and
        that both paths order them identically. Without this the differential
        above could be green on a corpus that never exercises the heap's
        `-pos` tie-break at all."""
        emb = self.queries[0]
        old = ref_vector_beliefs(self.store, emb, 5000)
        scores = [s for _b, _k, s in old]
        self.assertLess(len(set(scores)), len(scores), "fixture produced no ties")
        self.assertBitIdentical(old, self.engine._vector_beliefs(emb, 5000))

    def test_wrong_width_rows_are_invisible_before_and_after(self):
        """The SQL `length(embedding) = ?` prefilter restates batch_cosine's own
        rule. Wrong-width and empty blobs scored a hard 0.0 and were dropped by
        the `> 0.1` floor before; they are not read at all now. Either way they
        never reach a caller — which is what makes the prefilter an
        optimisation rather than a behaviour change."""
        foreign = {r["belief_id"] for r in self.store.iter_memory_vectors()
                   if len(r["embedding"] or b"") != DIMS * 4}
        self.assertGreater(len(foreign), 100, "fixture has no wrong-width rows")
        for emb in self.queries[:4]:
            old_ids = {b for b, _k, _s in ref_vector_beliefs(self.store, emb, 5000)}
            new_ids = {b for b, _k, _s in self.engine._vector_beliefs(emb, 5000)}
            self.assertEqual(old_ids, new_ids)
            self.assertFalse(old_ids & foreign, "reference surfaced a wrong-width row")
            self.assertFalse(new_ids & foreign, "streaming path surfaced a wrong-width row")

    def test_degenerate_inputs_match(self):
        emb = self.queries[0]
        self.assertEqual(self.engine._vector_beliefs(emb, 0), [])
        self.assertEqual(ref_vector_beliefs(self.store, emb, 0), [])
        self.assertEqual(self.engine._vector_beliefs([], 10), [])
        self.assertEqual(ref_vector_beliefs(self.store, [], 10), [])
        self.assertEqual(self.engine._vector_beliefs(None, 10), [])


class TestProxyDifferential(_SeededStore):
    def test_vector_proxies_identical(self):
        for qi, emb in enumerate(self.queries):
            for limit in (1, 5, 30, 500):
                self.assertBitIdentical(
                    ref_vector_proxies(self.store, emb, limit),
                    self.engine._vector_proxies(emb, limit),
                    "_vector_proxies q=%d limit=%d" % (qi, limit))

    def test_observed_proxies_identical(self):
        for qi, emb in enumerate(self.queries):
            for limit in (1, 5, 30, 500):
                self.assertBitIdentical(
                    ref_observed_proxies(self.store, emb, limit),
                    self.engine._observed_proxies(emb, limit),
                    "_observed_proxies q=%d limit=%d" % (qi, limit))

    def test_the_two_readers_partition_the_table(self):
        """The kind filter moved from a Python list comprehension over a full
        copy into SQL. Assert the split is still exhaustive and disjoint —
        a `kind !=` that silently dropped NULLs would lose rows here."""
        all_rows = self.store.iter_query_proxy_vectors()
        obs = sum(1 for r in all_rows if r["kind"] == "observed")
        belief = len(all_rows) - obs
        self.assertGreater(obs, 0)
        self.assertGreater(belief, 0)
        streamed_obs = sum(len(b) for b in self.store.iter_query_proxy_vectors_paged(
            batch_size=13, kind="observed"))
        streamed_belief = sum(len(b) for b in self.store.iter_query_proxy_vectors_paged(
            batch_size=13, exclude_kind="observed"))
        self.assertEqual((streamed_obs, streamed_belief), (obs, belief))

    def test_best_per_belief_reduction_survives(self):
        """Several proxies map to one belief; the result must carry each belief
        at most once, at its best score, in both paths."""
        emb = self.queries[1]
        out = self.engine._vector_proxies(emb, 500)
        ids = [b for b, _k, _s in out]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertBitIdentical(ref_vector_proxies(self.store, emb, 500), out)


class TestPagedScanContract(_SeededStore):
    def test_paged_scan_yields_every_row_in_rowid_order(self):
        rows = self.store.iter_memory_vectors()
        for page in (1, 7, 617, 5000):
            streamed = [r for b in self.store.iter_memory_vectors_paged(batch_size=page)
                        for r in b]
            self.assertEqual([r["belief_id"] for r in streamed],
                             [r["belief_id"] for r in rows], "page=%d" % page)

    def test_width_filter_selects_exactly_the_comparable_rows(self):
        want = [r["belief_id"] for r in self.store.iter_memory_vectors()
                if len(r["embedding"] or b"") == DIMS * 4]
        got = [r["belief_id"] for b in self.store.iter_memory_vectors_paged(
            batch_size=50, width=DIMS * 4) for r in b]
        self.assertEqual(got, want)
        self.assertLess(len(want), self.ROWS)

    def test_page_size_is_the_memory_bound(self):
        """The claim A5 rests on: resident vector bytes track VECTOR_SCAN_PAGE,
        not the row count. Raising the page to the table size walks the peak
        back to the materialising path's — which is the negative control that
        stops this test from passing for the wrong reason."""
        import engine.retrieval as R
        emb = self.queries[0]
        saved = R.VECTOR_SCAN_PAGE
        peaks = {}
        try:
            for page in (16, 100000):
                R.VECTOR_SCAN_PAGE = page
                self.engine._vector_beliefs(emb, 25)      # warm caches
                tracemalloc.start()
                self.engine._vector_beliefs(emb, 25)
                peaks[page] = tracemalloc.get_traced_memory()[1]
                tracemalloc.stop()
        finally:
            R.VECTOR_SCAN_PAGE = saved
        self.assertLess(peaks[16], peaks[100000],
                        "page size is not bounding anything: %r" % (peaks,))

    def test_the_fixture_actually_pages_at_the_shipping_page_size(self):
        """Guard against the differential going vacuous.

        If the fixture ever shrinks below one page of COMPARABLE rows, every
        assertion above still passes — on a single-batch scan that exercises
        no paging at all. Pin the shape: more than two full pages plus a short
        tail that the merge folds into the last batch.
        """
        from engine.retrieval import _tail_merged
        pages = self.store.iter_memory_vectors_paged(batch_size=VECTOR_SCAN_PAGE,
                                                     width=DIMS * 4)
        sizes = [len(b) for b in _tail_merged(pages, VECTOR_SCAN_PAGE)]
        self.assertGreaterEqual(len(sizes), 3, "fixture no longer multi-page: %r" % sizes)
        self.assertGreater(sizes[-1], VECTOR_SCAN_PAGE,
                           "no short tail was merged; the merge path is untested: %r" % sizes)

    def test_default_page_is_sane(self):
        self.assertGreaterEqual(VECTOR_SCAN_PAGE, 1)
        self.assertLessEqual(VECTOR_SCAN_PAGE, 100000)


class TestTheScoringScansStayWidthFiltered(_SeededStore):
    """The guard for "the one thing that silently reverts A5".

    WHY THIS EXISTS. The A0 x A5 cancellation is protected in ONE direction
    only. `RetrievalEngine._note_wrong_dim_table` — the ID-only complement that
    keeps a present-but-incomparable vector loud once A5's `length(embedding)=?`
    predicate hides it from the scan — is pinned by five tests in
    `tests/test_wrong_dim_read_refusal.py`: delete it and they go red.

    The other direction was pinned by nothing. Dropping `width=` from a scoring
    scan is, in that method's own docstring, "the one thing that silently
    reverts A5, so it is never done here" — and until this class, nothing
    checked. Correctness would survive the revert (the unfiltered scan sees the
    rows itself, `_note_wrong_dim_rows` still reports them, and `_wrong_dim_seen`
    is idempotent by (channel, id)), which is exactly what makes it dangerous:
    A5's memory bound would be gone with no failing test and no wrong answer.
    Measured cost of the revert at the shipping shape: 812 MB of Python
    allocation per query instead of a bounded top-k, and `embeddings`'
    process-wide counter raised TWICE for the same rows.

    Two independent checks, because each misses what the other catches:

      * BEHAVIOUR (`test_every_scan_the_engine_actually_runs_is_width_filtered`)
        spies on the store and watches real queries. It cannot be fooled by a
        rename or by moving a call, but it only sees the call sites the queries
        below happen to reach.
      * SOURCE (`test_every_scan_call_site_passes_a_width`) reads every
        `iter_*_paged` call in engine/retrieval.py with `ast`. It reaches sites
        no test exercises, and `test_the_source_check_is_not_inert` proves it
        can fail.
    """

    SCAN_METHODS = ("iter_memory_vectors_paged", "iter_query_proxy_vectors_paged",
                    "iter_observed_vectors_paged", "iter_projection_vectors_paged",
                    "iter_session_vectors_paged")

    # -- source ------------------------------------------------------------
    @staticmethod
    def _scan_calls(source):
        """(lineno, method, width_kwarg_node_or_MISSING) per `iter_*_paged` call."""
        import ast
        MISSING = object()
        out = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            if not (fn.attr.startswith("iter_") and fn.attr.endswith("_paged")):
                continue
            width = MISSING
            for kw in node.keywords:
                if kw.arg == "width":
                    width = kw.value
                elif kw.arg is None:          # **kwargs — cannot be read statically
                    width = None
            out.append((node.lineno, fn.attr, width, MISSING))
        return out

    @classmethod
    def _offenders(cls, source):
        import ast
        bad = []
        for lineno, name, width, missing in cls._scan_calls(source):
            if width is missing:
                bad.append((lineno, name, "no width= at all"))
            elif isinstance(width, ast.Constant) and width.value is None:
                bad.append((lineno, name, "width=None"))
            elif width is None:
                bad.append((lineno, name, "width passed via **kwargs"))
        return bad

    def _retrieval_source(self):
        return (Path(__file__).resolve().parent.parent
                / "engine" / "retrieval.py").read_text(encoding="utf-8")

    def test_every_scan_call_site_passes_a_width(self):
        self.assertEqual(self._offenders(self._retrieval_source()), [], (
            "a scoring scan in engine/retrieval.py is no longer width-filtered. "
            "That is the silent A5 revert: nothing returns a wrong answer, and "
            "the whole table comes back into Python again. If the scan really "
            "must be unfiltered, it must ALSO stop calling _note_wrong_dim_table "
            "(see that method's docstring) or every skipped row is counted twice."))

    def test_the_source_check_can_still_see_the_call_sites(self):
        """Anti-inertness: a matcher that matches nothing passes vacuously."""
        calls = self._scan_calls(self._retrieval_source())
        self.assertGreaterEqual(len(calls), 6,
                                "found %d paged-scan call sites; the A5 scoring "
                                "paths alone are six" % len(calls))
        seen = {name for _l, name, _w, _m in calls}
        self.assertTrue(seen <= set(self.SCAN_METHODS),
                        "unknown paged-scan method(s): %s" % (seen - set(self.SCAN_METHODS)))

    def test_the_source_check_is_not_inert(self):
        """MUTATION: plant each revert shape and prove the checker flags it."""
        for planted, why in (
                ("x = self.store.iter_memory_vectors_paged(batch_size=1000)\n",
                 "no width= at all"),
                ("x = self.store.iter_memory_vectors_paged(batch_size=1000, width=None)\n",
                 "width=None")):
            found = self._offenders(planted)
            self.assertEqual(len(found), 1, planted)
            self.assertEqual(found[0][2], why)
        # …and that a correct call is NOT flagged, so it is not just always-red.
        self.assertEqual(
            self._offenders("x = self.store.iter_memory_vectors_paged(width=len(e) * 4)\n"), [])

    def test_each_width_filtered_scan_is_paired_with_the_complement(self):
        """The two halves have to stay in step: every width-filtered scoring
        scan needs exactly one `_note_wrong_dim_table` beside it, or the rows
        the predicate hides go unreported (the A0 x A5 cancellation)."""
        source = self._retrieval_source()
        scans = len(self._scan_calls(source))
        complements = source.count("self._note_wrong_dim_table(")
        self.assertEqual(complements, scans, (
            "{} width-filtered scan(s) but {} _note_wrong_dim_table call(s). "
            "Unpaired either way is a defect: a scan without one hides its "
            "skipped rows, a second one on the same scan double-reports."
            .format(scans, complements)))
        # The non-width-filtered path (the explicit id fetch) uses the row-level
        # reporter instead, and must still exist.
        self.assertIn("self._note_wrong_dim_rows(", source)

    # -- behaviour ---------------------------------------------------------
    def test_every_scan_the_engine_actually_runs_is_width_filtered(self):
        """The half a rename cannot defeat: watch the store during real calls."""
        seen = []
        originals = {}
        try:
            for name in self.SCAN_METHODS:
                orig = getattr(type(self.store), name)
                originals[name] = orig

                def spy(inner_self, *a, _n=name, _o=orig, **kw):
                    seen.append((_n, kw.get("width", "MISSING"), a))
                    return _o(inner_self, *a, **kw)

                setattr(type(self.store), name, spy)
            emb = self.queries[0]
            self.engine._vector_beliefs(emb, 25)
            self.engine._vector_proxies(emb, 25)
            self.engine._observed_proxies(emb, 25)
        finally:
            for name, orig in originals.items():
                setattr(type(self.store), name, orig)

        self.assertTrue(seen, "no paged scan ran at all; the spy proves nothing")
        want = len(emb) * 4
        for name, width, positional in seen:
            self.assertNotEqual(width, "MISSING",
                                "%s ran without width=" % name)
            self.assertIsNotNone(width, "%s ran with width=None" % name)
            self.assertEqual(width, want,
                             "%s ran with width=%r, expected %d bytes for a "
                             "%d-dim query" % (name, width, want, len(emb)))
            self.assertFalse(positional, "%s got a positional arg; the spy reads "
                                         "width from kwargs only" % name)

    def test_the_width_filter_is_what_bounds_the_scan(self):
        """The property behind the flag, measured on this fixture rather than
        asserted: the filtered scan visits only the comparable rows."""
        emb = self.queries[0]
        want = len(emb) * 4
        filtered = sum(len(b) for b in self.store.iter_memory_vectors_paged(
            batch_size=VECTOR_SCAN_PAGE, width=want))
        unfiltered = sum(len(b) for b in self.store.iter_memory_vectors_paged(
            batch_size=VECTOR_SCAN_PAGE))
        self.assertLess(filtered, unfiltered)
        comparable = self.store._conn().execute(
            "SELECT COUNT(*) FROM memory_vectors WHERE length(embedding)=?",
            (want,)).fetchone()[0]
        self.assertEqual(filtered, comparable)


class TestFastPathRespectsACL(unittest.TestCase):
    """A1's choke point must survive A5.

    Candidate generation reads `memory_vectors`, which carries no owner and no
    read_acl — the ACL lives on the parent belief and is applied in
    `search()`'s `add()` via `_readable`. So the meaningful assertion is a
    pincer: the fast path DOES hand back the sandboxed principal's belief_id
    (otherwise the test proves nothing about the guard), and `search()` for
    another principal does NOT contain it.
    """

    PRINCIPALS = {
        "default_cross_agent_read": "allow",
        "users": ["u1", "u2"],
        "agents": [
            {"id": "u1:agentA", "user": "u1"},
            {"id": "u1:peer", "user": "u1"},
            {"id": "u2:agentB", "user": "u2"},
            {"id": "u1:sandbox", "user": "u1", "sandbox": True},
        ],
    }
    A, PEER, B, S = "u1:agentA", "u1:peer", "u2:agentB", "u1:sandbox"
    SECRET = "Zarquon Fake Holdings"

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="a5-acl-")
        cls.core = ChronicleCore(cls.home, {"embeddings": {"model": "hashing"},
                                            "principals": cls.PRINCIPALS})
        cls.core.tools.dispatch(cls.S, "chronicle_remember",
                                {"kind": "fact", "content": cls.SECRET,
                                 "entity": "pat_sandbox", "attribute": "works_at"})
        cls.core.tools.dispatch(cls.A, "chronicle_remember",
                                {"kind": "fact", "content": "Acme Fake Co",
                                 "entity": "pat_a", "attribute": "works_at"})
        cls.core.process_pending()
        cls.secret_id = None
        for row in cls.core.store.query_beliefs("facts", "1=1", (), 100):
            if row["value"] == cls.SECRET:
                cls.secret_id = row["belief_id"]

    @classmethod
    def tearDownClass(cls):
        access.reset_topology()
        ChronicleCore._instances.pop(cls.home, None)
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        access.configure_topology(self.PRINCIPALS)

    def test_fast_path_really_does_return_the_sandboxed_belief(self):
        """Negative control for the two tests below: if candidate generation
        stopped emitting this id, they would pass while proving nothing."""
        self.assertIsNotNone(self.secret_id, "fixture fact was not stored")
        emb = self.core.retrieval.embedder.embed(self.SECRET)
        ids = {b for b, _k, _s in self.core.retrieval._vector_beliefs(emb, 200)}
        self.assertIn(self.secret_id, ids,
                      "the streaming fast path did not surface the sandboxed vector "
                      "at all -- the ACL assertions below would be vacuous")

    def test_sandboxed_vector_never_reaches_another_principal_via_search(self):
        for reader in (self.A, self.PEER, self.B):
            hits = self.core.retrieval.search(self.SECRET, limit=50, principal=reader)
            bodies = repr(hits)
            self.assertNotIn(self.SECRET, bodies,
                             "sandboxed value leaked into search() for %s" % reader)
            self.assertNotIn(self.secret_id, bodies,
                             "sandboxed belief_id leaked into search() for %s" % reader)

    def test_sandboxed_vector_never_reaches_another_principal_via_get_context(self):
        for reader in (self.A, self.PEER, self.B):
            ctx = self.core.retrieval.get_context(self.SECRET, principal=reader)
            self.assertNotIn(self.SECRET, ctx,
                             "sandboxed value leaked into get_context for %s" % reader)

    def test_the_sandbox_still_reads_its_own_vector_hit(self):
        hits = self.core.retrieval.search(self.SECRET, limit=50, principal=self.S)
        self.assertIn(self.SECRET, repr(hits))


if __name__ == "__main__":
    unittest.main()
