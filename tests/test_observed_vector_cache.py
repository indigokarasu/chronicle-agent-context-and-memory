"""Chronicle — 5.8.33: the raw tier's in-memory float16 vector copy.

The claim is narrow: with the cache on, retrieve_raw returns what the paged
scan returns (same events, scores within float16 error), stays current as the
table changes underneath it, and steps aside whenever it cannot serve.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from engine.core import ChronicleCore  # noqa: E402

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:          # the cache needs numpy; without it the paged scan serves
    HAVE_NUMPY = False
_needs_numpy = unittest.skipUnless(HAVE_NUMPY, "the float16 cache needs numpy")

TOPICS = ("kayaking on Fake Lake", "the Acme Fake Co quarterly budget", "Pat Testley's birthday party",
          "a sourdough starter that will not rise", "renewing a Fakeland passport",
          "tuning the office Wi-Fi", "the Fake Izakaya reservation", "a squeaky bicycle chain")


def _core():
    core = ChronicleCore(tempfile.mkdtemp(), {"embeddings": {"model": "hashing"}})
    core.initialize(session_id="eval", principal_id="assistant")
    for i in range(48):
        topic = TOPICS[i % len(TOPICS)]
        core.capture.observe("Turn %d: let's talk about %s, detail %d." % (i, topic, i * 7),
                             "Noted: %s (%d)." % (topic, i), session_id="s%d" % (i % 6),
                             occurred_at="2026-03-%02dT10:00:00Z" % (1 + i % 28))
    core.process_pending()
    return core


def _run(core, query, cache_on, limit=8):
    core.cfg._d.setdefault("retrieval", {})["observed_vector_cache"] = cache_on
    rows = core.retrieval.retrieve_raw(query, limit=limit)
    return [(r.get("event_id") or r.get("ref") or r.get("id"), round(float(r.get("score", 0)), 2))
            for r in rows]


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = _core()

    def cache(self):
        return getattr(self.core.store, "_observed_vector_cache", None)


@_needs_numpy
class TestSameAnswerAsThePagedScan(_Case):
    def test_queries(self):
        for q in ("kayaking", "quarterly budget for Acme", "sourdough starter",
                  "bicycle chain squeak", "passport renewal"):
            with self.subTest(q=q):
                off = _run(self.core, q, False)
                on = _run(self.core, q, True)
                self.assertTrue(off, "no results: the comparison would be vacuous")
                self.assertEqual([e for e, _ in on], [e for e, _ in off])
                for (_e1, s1), (_e2, s2) in zip(on, off):
                    self.assertAlmostEqual(s1, s2, delta=0.02)
        self.assertIsNotNone(self.cache(), "the cache path never ran")
        self.assertGreaterEqual(self.cache().rebuilds, 1)


@_needs_numpy
class TestItStaysCurrent(_Case):
    def test_a_new_turn_is_found_without_a_rebuild(self):
        _run(self.core, "kayaking", True)
        before = self.cache().rebuilds
        self.core.capture.observe("A zebra-striped Fakeglider landed on the roof.", "Wow.",
                                  session_id="s_new", occurred_at="2026-04-01T10:00:00Z")
        self.core.process_pending()
        hits = _run(self.core, "zebra-striped Fakeglider on the roof", True)
        self.assertEqual(hits, _run(self.core, "zebra-striped Fakeglider on the roof", False))
        self.assertTrue(hits)
        self.assertEqual(self.cache().rebuilds, before)
        self.assertGreaterEqual(self.cache().appends, 1)

    def test_a_deleted_vector_is_gone(self):
        first = _run(self.core, "sourdough starter", True)
        self.assertTrue(first)
        victim = first[0][0]
        rebuilds = self.cache().rebuilds
        self.core.store.delete_observed_vector(victim)
        after_on = _run(self.core, "sourdough starter", True)
        after_off = _run(self.core, "sourdough starter", False)
        self.assertEqual(after_on, after_off)
        self.assertGreater(self.cache().rebuilds, rebuilds)


@_needs_numpy
class TestItStepsAside(_Case):
    def test_over_the_row_cap(self):
        _run(self.core, "kayaking", True)
        cache = self.cache()
        was = cache.max_rows
        cache.max_rows = 1
        try:
            width = self.core.store._conn().execute(
                "SELECT length(embedding) FROM observed_vectors LIMIT 1").fetchone()[0]
            self.assertIsNone(cache.scores([0.0] * (width // 4 - 1) + [1.0]))
            self.assertEqual(_run(self.core, "kayaking", True), _run(self.core, "kayaking", False))
        finally:
            cache.max_rows = was

    def test_off_by_config(self):
        self.core.cfg._d.setdefault("retrieval", {})["observed_vector_cache"] = False
        self.assertIsNone(self.core.retrieval._observed_cache())
        self.core.cfg._d["retrieval"]["observed_vector_cache"] = True


@_needs_numpy
class TestTheCachePathKeepsThePagedRules(unittest.TestCase):
    """_raw_from_cache alone, over a stub cache: the top-k fills to `limit`, and
    a row the principal cannot read never enters it."""

    def _run(self, can_read):
        import types
        import numpy as np
        import engine.retrieval as R
        ids = ["ev_%d" % i for i in range(6)]
        owners = ["pat", "pat", "other", "pat", "pat", "pat"]
        sims = np.array([0.9, 0.8, 0.95, 0.5, 0.4, 0.05], dtype=np.float32)
        cache = types.SimpleNamespace(scores=lambda q: (ids, owners, sims, {e: i for i, e in enumerate(ids)}))
        events = {e: {"event_id": e, "owner": o, "payload": '{"excerpt": "text of %s"}' % e,
                      "session_id": "s1"} for e, o in zip(ids, owners)}
        fake = types.SimpleNamespace(
            _vec_w=1.0, _observed_cache=lambda: cache,
            store=types.SimpleNamespace(get_event=events.get),
            _from_automation=lambda ev: False,
            _reader_excerpt=lambda ev, stored: stored)
        heap = []
        real = R.access.can_read
        R.access.can_read = can_read
        try:
            served = R.RetrievalEngine._raw_from_cache(fake, [1.0], {}, heap, 3, "pat", False)
        finally:
            R.access.can_read = real
        self.assertTrue(served)
        return sorted((e[2] for e in heap), key=ids.index)

    def test_fills_to_the_limit_best_first(self):
        self.assertEqual(self._run(lambda acl, owner, principal: True), ["ev_0", "ev_1", "ev_2"])

    def test_an_unreadable_row_never_enters(self):
        self.assertEqual(self._run(lambda acl, owner, principal: owner != "other"),
                         ["ev_0", "ev_1", "ev_3"])


class TestWithoutNumpyThePagedScanAnswers(_Case):
    """No numpy (a bare CI runner, a minimal venv): the cache declines and the
    paged scan gives the same answer it always did."""

    def test_fallback(self):
        import builtins
        real_import = builtins.__import__

        def no_numpy(name, *a, **k):
            if name == "numpy" or name.startswith("numpy."):
                raise ImportError("numpy hidden for this test")
            return real_import(name, *a, **k)
        want = _run(self.core, "kayaking", False)
        self.assertTrue(want)
        builtins.__import__ = no_numpy
        try:
            got = _run(self.core, "kayaking", True)
        finally:
            builtins.__import__ = real_import
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
