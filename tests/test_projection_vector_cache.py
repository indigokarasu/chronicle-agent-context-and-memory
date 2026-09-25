"""Chronicle — the projection tier's in-memory float16 vector copy (L11 S1).

The claim is exact, not approximate: with the cache on, retrieve_raw returns
what the paged projection scan returns -- the same ids in the same order, the
scores within float32 rounding (1e-6) -- because the copy only picks which rows
can reach the top-k and the tier re-reads and scores those rows' float32 blobs.
It stays current as the table changes (an append loads only the new rows, a
delete rebuilds, a query at another width gets its own copy) and steps aside
when it is switched off or the table is over its row cap.
"""

import importlib.util
import logging
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from engine import access  # noqa: E402
from engine.core import ChronicleCore  # noqa: E402
from engine.embeddings import pack  # noqa: E402

HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
_needs_numpy = unittest.skipUnless(HAVE_NUMPY, "the float16 cache needs numpy")

QUERIES = ("kayaking on Fake Lake", "the Acme Fake Co quarterly budget",
           "renewing a Fakeland passport", "a squeaky bicycle chain")


def _core():
    core = ChronicleCore(tempfile.mkdtemp(), {"embeddings": {"model": "hashing"}})
    core.initialize(session_id="eval", principal_id="assistant")
    return core


def _qvec(core, text):
    return list(core.retrieval.query_understanding(text)["embedding"])


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _add(core, provider, external_id, vec, owner="assistant"):
    core.store.add_projection_vector(provider, external_id, pack(vec), "hashing-v1", owner)


def _set(core, on):
    core.cfg._d.setdefault("retrieval", {}).setdefault("projection_cache", {})["enabled"] = on


def _run(core, query, on, limit=10):
    _set(core, on)
    return [(r["event_id"], float(r["score"])) for r in core.retrieval.retrieve_raw(query, limit=limit)]


def _seed(core, per_query=40, background=160, seed=11):
    """Rows scattered around each query's own vector (so every query has real
    competition for its top-k, all well above the 0.15 floor) plus background
    rows; a few owned by another principal for the ACL case."""
    import numpy as np
    rng = np.random.default_rng(seed)
    n = 0
    for qi, text in enumerate(QUERIES):
        q = np.asarray(_qvec(core, text), dtype=np.float64)
        for j in range(per_query):
            r = rng.standard_normal(q.shape[0])
            r /= np.linalg.norm(r)
            v = q + rng.uniform(0.2, 2.0) * r
            _add(core, "prov%d" % (n % 3), "row-%04d" % n, _unit(v.tolist()),
                 owner="other" if j % 7 == 3 else "assistant")
            n += 1
    d = len(_qvec(core, QUERIES[0]))
    for _ in range(background):
        r = rng.standard_normal(d)
        _add(core, "prov%d" % (n % 3), "row-%04d" % n, _unit(r.tolist()))
        n += 1
    return n


class _Case(unittest.TestCase):
    def assertSameAnswer(self, on, off):
        self.assertTrue(off, "no results: the comparison would be vacuous")
        self.assertEqual([e for e, _ in on], [e for e, _ in off])
        for (_e1, s1), (_e2, s2) in zip(on, off):
            self.assertAlmostEqual(s1, s2, delta=1e-6)

    def cache(self, core):
        return getattr(core.store, "_projection_vector_cache", None)


@_needs_numpy
class TestSameAnswerAsThePagedScan(_Case):
    @classmethod
    def setUpClass(cls):
        cls.core = _core()
        cls.rows = _seed(cls.core)

    def test_every_query_and_limit(self):
        fetched = []
        real = self.core.store.get_projection_vectors_by_rowids

        def spy(rowids):
            fetched.append(len(rowids))
            return real(rowids)

        with mock.patch.object(self.core.store, "get_projection_vectors_by_rowids", side_effect=spy):
            for text in QUERIES:
                for limit in (1, 3, 10, 25):
                    with self.subTest(q=text, limit=limit):
                        off = _run(self.core, text, False, limit)
                        on = _run(self.core, text, True, limit)
                        self.assertSameAnswer(on, off)
                        self.assertTrue(all(e.startswith("proj:") for e, _ in on))
        self.assertIsNotNone(self.cache(self.core), "the cache path never ran")
        self.assertGreaterEqual(self.cache(self.core).served, len(QUERIES) * 4)
        # It narrowed: the tier re-read a shortlist, not the table.
        self.assertTrue(fetched)
        self.assertLess(max(fetched), self.rows)

    def test_the_acl_decides_the_same_rows(self):
        real = access.can_read

        def can_read(acl, owner, principal, *a, **k):
            return owner != "other" and real(acl, owner, principal, *a, **k)

        with mock.patch.object(access, "can_read", side_effect=can_read):
            for text in QUERIES:
                with self.subTest(q=text):
                    off = _run(self.core, text, False, 10)
                    on = _run(self.core, text, True, 10)
                    self.assertSameAnswer(on, off)
        # ...and the check is not vacuous: without it, "other" rows do rank.
        owners = dict(self.core.store._conn().execute(
            "SELECT 'proj:' || provider || ':' || external_id, owner FROM projection_vectors").fetchall())
        ranked = [e for t in QUERIES for e, _ in _run(self.core, t, True, 10)]
        self.assertIn("other", {owners[e] for e in ranked})

    def test_exact_ties_at_the_cutoff_keep_the_same_rows(self):
        """Six rows tie exactly at the heap's cutoff. Which of them survive
        depends on the streaming heap's history (a later equal score never
        displaces, an eviction takes the earliest), so this pins that the rows
        the cache leaves out cannot change that history's outcome."""
        core = _core()
        d = len(_qvec(core, "anything"))
        q = [1.0] + [0.0] * (d - 1)
        # Dyadic first components: the float16 copy and the float32 dot product
        # are both EXACT here, so the ties are real ties on every path.
        for i, c in enumerate((0.5, 0.25, 0.5, 0.75, 0.5, 0.5, 0.75, 0.5, 0.125, 0.25, 0.5, 0.875)):
            v = [c, math.sqrt(1.0 - c * c)] + [0.0] * (d - 2)
            _add(core, "tie", "t%02d" % (11 - i), v)   # ids descend as rowids ascend
        orig = core.retrieval.query_understanding

        def qu(query, **kw):
            out = dict(orig(query, **kw))
            out["embedding"] = list(q)
            return out

        with mock.patch.object(core.retrieval, "query_understanding", side_effect=qu):
            for limit in range(1, 12):
                with self.subTest(limit=limit):
                    off = _run(core, "tie query", False, limit)
                    on = _run(core, "tie query", True, limit)
                    self.assertSameAnswer(on, off)
                    self.assertEqual(on, off)       # exact arithmetic: bit-equal
        self.assertGreaterEqual(self.cache(core).served, 11)

    def test_float16_rounding_that_inverts_two_rows_does_not_change_the_answer(self):
        """Rounding each component to float16 can reorder two rows whose exact
        scores are closer than float16 can resolve. Here row A outscores row B
        exactly, but A's components round down and B's round up, so their
        float16 scores come out the other way round. The shortlist's margin is
        what keeps A: a top-k taken on the float16 scores alone returns B."""
        import numpy as np
        core = _core()
        d = len(_qvec(core, "anything"))
        q = [0.5, 0.5] + [0.0] * (d - 2)
        a = [0.25011, 0.25011] + [0.0] * (d - 2)
        b = [0.25013, 0.25] + [0.0] * (d - 2)
        _add(core, "inv", "b", b)
        _add(core, "inv", "a", a)
        for i, c in enumerate((0.2, 0.21, 0.22)):
            _add(core, "inv", "low%d" % i, [c, c] + [0.0] * (d - 2))
        exact = [float(np.dot(np.float32(q), np.float32(v))) for v in (a, b)]
        rounded = [float(np.dot(np.float32(q), np.float16(v).astype(np.float32))) for v in (a, b)]
        self.assertGreater(exact[0], exact[1], "fixture: A must outscore B exactly")
        self.assertLess(rounded[0], rounded[1], "fixture: float16 must invert A and B")
        orig = core.retrieval.query_understanding

        def qu(query, **kw):
            out = dict(orig(query, **kw))
            out["embedding"] = list(q)
            return out

        with mock.patch.object(core.retrieval, "query_understanding", side_effect=qu):
            for limit in (1, 2, 3):
                with self.subTest(limit=limit):
                    off = _run(core, "inversion", False, limit)
                    on = _run(core, "inversion", True, limit)
                    self.assertSameAnswer(on, off)
                    self.assertEqual(on[0][0], "proj:inv:a")
        self.assertGreaterEqual(self.cache(core).served, 3)


@_needs_numpy
class TestItStaysCurrent(_Case):
    def setUp(self):
        self.core = _core()
        _seed(self.core, per_query=15, background=40, seed=5)
        self.q = QUERIES[1]

    def _state(self):
        return tuple(self.core.store._conn().execute(
            "SELECT COUNT(*), MAX(rowid) FROM projection_vectors").fetchone())

    def test_an_append_loads_only_the_new_rows(self):
        _run(self.core, self.q, True)
        cache = self.cache(self.core)
        rebuilds, appends = cache.rebuilds, cache.appends
        _add(self.core, "prov9", "fresh", _qvec(self.core, self.q))   # a perfect match
        on = _run(self.core, self.q, True)
        self.assertSameAnswer(on, _run(self.core, self.q, False))
        self.assertEqual(on[0][0], "proj:prov9:fresh")
        self.assertEqual(cache.rebuilds, rebuilds)
        self.assertEqual(cache.appends, appends + 1)

    def test_a_delete_rebuilds(self):
        first = _run(self.core, self.q, True)
        cache = self.cache(self.core)
        rebuilds = cache.rebuilds
        _p, provider, external_id = first[0][0].split(":", 2)
        with self.core.store.transaction() as conn:
            conn.execute("DELETE FROM projection_vectors WHERE provider=? AND external_id=?",
                         (provider, external_id))
        on = _run(self.core, self.q, True)
        self.assertSameAnswer(on, _run(self.core, self.q, False))
        self.assertNotIn(first[0][0], [e for e, _ in on])
        self.assertGreater(cache.rebuilds, rebuilds)

    def test_a_delete_hidden_behind_appends_still_rebuilds(self):
        """One old row deleted and two appended before the next query: count
        and max rowid both grew, as for a pure append. Only the count of the
        new rows (two, not one) shows the delete."""
        first = _run(self.core, self.q, True)
        cache = self.cache(self.core)
        rebuilds, appends = cache.rebuilds, cache.appends
        _p, provider, external_id = first[0][0].split(":", 2)
        with self.core.store.transaction() as conn:
            conn.execute("DELETE FROM projection_vectors WHERE provider=? AND external_id=?",
                         (provider, external_id))
        d = len(_qvec(self.core, self.q))
        _add(self.core, "prov9", "x1", _unit([1.0] + [0.0] * (d - 1)))
        _add(self.core, "prov9", "x2", _unit([0.0, 1.0] + [0.0] * (d - 2)))
        on = _run(self.core, self.q, True)
        self.assertEqual((cache.rebuilds, cache.appends), (rebuilds + 1, appends),
                         "a delete behind appends was taken for an append")
        self.assertSameAnswer(on, _run(self.core, self.q, False))
        self.assertNotIn(first[0][0], [e for e, _ in on])

    def test_the_newest_row_deleted_and_reembedded_is_not_mistaken_for_no_change(self):
        """The federation path deletes a row's vector when its text changes and
        the backlog re-embeds it. When that row was the newest, SQLite reuses
        its rowid: count and max rowid come back exactly as they were."""
        _add(self.core, "prov9", "newest", _unit([1.0] * len(_qvec(self.core, self.q))))
        _run(self.core, self.q, True)
        cache = self.cache(self.core)
        rebuilds = cache.rebuilds
        before = self._state()
        with self.core.store.transaction() as conn:
            conn.execute("DELETE FROM projection_vectors WHERE provider='prov9' AND external_id='newest'")
        _add(self.core, "prov9", "newest", _qvec(self.core, self.q))     # the new text: a perfect match
        self.assertEqual(self._state(), before, "fixture: the rowid was not reused")
        on = _run(self.core, self.q, True)
        self.assertSameAnswer(on, _run(self.core, self.q, False))
        self.assertEqual(on[0][0], "proj:prov9:newest")
        self.assertGreater(cache.rebuilds, rebuilds)

    def test_an_inplace_update_of_a_non_newest_row_is_seen(self):
        """F3: `scripts/writeback_vectors.py` UPDATEs a row's embedding IN
        PLACE on its existing (provider, external_id) -- when that row is
        neither the newest nor deleted, count, max rowid AND the anchor's
        identity all come back exactly as they were. Only the generation
        counter (MemoryStore.bump_vector_generation) shows it. That counter is
        bumped ONLY for this same-rowid case -- the two tests below prove an
        ordinary raw-SQL insert (the shape ops/embed_projections.py and its
        siblings actually write in) still takes the cheap pre-F3 path with no
        help from it at all."""
        first = _run(self.core, self.q, True)
        _p, provider, external_id = first[0][0].split(":", 2)
        before = self._state()
        new_vec = pack(_qvec(self.core, QUERIES[3]))   # now a perfect match for a DIFFERENT query
        with self.core.store.transaction() as conn:
            conn.execute("UPDATE projection_vectors SET embedding=? WHERE provider=? AND external_id=?",
                        (new_vec, provider, external_id))
            self.core.store.bump_vector_generation("projection_vectors")
        self.assertEqual(self._state(), before,
                         "fixture: an in-place UPDATE must not move count or max rowid")
        on = _run(self.core, QUERIES[3], True)
        self.assertSameAnswer(on, _run(self.core, QUERIES[3], False))
        self.assertEqual(on[0][0], first[0][0], "the cache must score the NEW vector, not the stale one")

    def test_a_raw_sql_insert_with_no_bump_still_takes_the_append_path(self):
        """ops/embed_projections.py and its siblings write new projection
        vectors via raw SQL directly against the connection -- never through
        MemoryStore's Python API, so they never call bump_vector_generation.
        The append path must keep working for them with the generation flat
        throughout: this is the pre-F3 arithmetic, unmodified -- count/max
        rowid growing, with nothing at the old anchor changed, already proves
        a pure append on its own."""
        _run(self.core, self.q, True)   # warm the cache
        cache = self.cache(self.core)
        rebuilds, appends = cache.rebuilds, cache.appends
        new_vec = pack(_qvec(self.core, self.q))   # a perfect match
        with self.core.store.transaction() as conn:
            conn.execute(
                "INSERT INTO projection_vectors(provider,external_id,embedding,model,owner,created_at) "
                "VALUES(?,?,?,?,?,?)",
                ("prov9", "raw-sql-insert", new_vec, "hashing-v1", "assistant", "2026-07-01T00:00:00Z"))
            # deliberately no bump_vector_generation call: this simulates an
            # ops script's raw SQL write, which never makes one either.
        on = _run(self.core, self.q, True)
        self.assertSameAnswer(on, _run(self.core, self.q, False))
        self.assertEqual(on[0][0], "proj:prov9:raw-sql-insert")
        self.assertEqual(cache.rebuilds, rebuilds, "a plain append must stay on the cheap path")
        self.assertEqual(cache.appends, appends + 1)

    def test_a_raw_sql_insert_or_replace_of_an_existing_key_still_rebuilds(self):
        """`INSERT OR REPLACE` on a (provider, external_id) that already has
        a row deletes the old row and inserts a fresh one under a NEW rowid:
        net row count does not grow (one out, one in), so the append
        branch's own `count > copy.count` precondition already rules this
        out and it falls straight to a rebuild -- no generation involvement
        needed."""
        first = _run(self.core, self.q, True)
        _p, provider, external_id = first[0][0].split(":", 2)
        _run(self.core, self.q, True)   # warm the cache
        cache = self.cache(self.core)
        rebuilds = cache.rebuilds
        new_vec = pack(_qvec(self.core, QUERIES[3]))
        with self.core.store.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projection_vectors"
                "(provider,external_id,embedding,model,owner,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (provider, external_id, new_vec, "hashing-v1", "assistant", "2026-07-01T00:00:00Z"))
        on = _run(self.core, QUERIES[3], True)
        self.assertSameAnswer(on, _run(self.core, QUERIES[3], False))
        self.assertEqual(on[0][0], first[0][0])
        self.assertGreater(cache.rebuilds, rebuilds)

    def test_a_query_at_another_width_gets_its_own_copy(self):
        _run(self.core, self.q, True)
        cache = self.cache(self.core)
        width = len(_qvec(self.core, self.q)) * 4
        self.assertEqual(sorted(cache._copies), [width])
        rebuilds = cache.rebuilds
        # A handful of rows written by a narrower model.
        small = 8
        for i in range(6):
            v = [0.0] * small
            v[i % small] = 1.0
            v[(i + 1) % small] = 0.5
            _add(self.core, "narrow", "n%d" % i, _unit(v))
        q_small = _unit([1.0, 0.5] + [0.0] * (small - 2))
        orig = self.core.retrieval.query_understanding

        def qu(query, **kw):
            out = dict(orig(query, **kw))
            out["embedding"] = list(q_small)
            return out

        with mock.patch.object(self.core.retrieval, "query_understanding", side_effect=qu):
            off = _run(self.core, "narrow query", False, 4)
            on = _run(self.core, "narrow query", True, 4)
        self.assertSameAnswer(on, off)
        self.assertEqual(sorted(cache._copies), sorted([width, small * 4]))
        self.assertEqual(cache._copies[small * 4].mat.shape, (6, small))
        self.assertEqual(cache.rebuilds, rebuilds + 1, "only the new width was built")
        # The first width's copy saw the narrow rows as appends at another
        # width -- nothing of its own to add, and no rebuild.
        self.assertSameAnswer(_run(self.core, self.q, True), _run(self.core, self.q, False))
        self.assertEqual(cache.rebuilds, rebuilds + 1)
        self.assertEqual(cache._copies[width].mat.shape[1], width // 4)


@_needs_numpy
class TestItStepsAside(_Case):
    @classmethod
    def setUpClass(cls):
        cls.core = _core()
        _seed(cls.core, per_query=10, background=20, seed=3)

    def _paged_calls(self, on):
        calls = []
        real = type(self.core.store).iter_projection_vectors_paged

        def spy(store, *a, **k):
            calls.append(k.get("width"))
            return real(store, *a, **k)

        with mock.patch.object(type(self.core.store), "iter_projection_vectors_paged", spy):
            rows = _run(self.core, QUERIES[0], on)
        return calls, rows

    def test_disabled_by_config_pages_the_table(self):
        calls_off, off = self._paged_calls(False)
        self.assertIsNone(self.core.retrieval._projection_cache())
        self.assertEqual(len(calls_off), 1, "the paged scan did not run with the cache off")
        calls_on, on = self._paged_calls(True)
        self.assertEqual(calls_on, [], "the paged scan ran although the cache could serve")
        self.assertSameAnswer(on, off)
        _set(self.core, True)

    def test_over_the_row_cap_pages_with_one_warning(self):
        _run(self.core, QUERIES[0], True)
        cache = self.cache(self.core)
        was = cache.max_rows
        cache.max_rows = 1
        try:
            with self.assertLogs("chronicle.vector_cache", level=logging.WARNING) as logs:
                calls, capped = self._paged_calls(True)
                self._paged_calls(True)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len([m for m in logs.output if "max_rows" in m]), 1)
            self.assertEqual(cache._copies, {}, "memory it cannot use is released")
            self.assertSameAnswer(capped, _run(self.core, QUERIES[0], False))
        finally:
            cache.max_rows = was

    def test_the_keys_are_declared(self):
        from engine.config import DEFAULTS
        self.assertIs(DEFAULTS["retrieval"]["projection_cache"]["enabled"], True)
        self.assertEqual(DEFAULTS["retrieval"]["projection_cache"]["max_rows"], 400000)


if __name__ == "__main__":
    unittest.main()
