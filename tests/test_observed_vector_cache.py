"""Chronicle — 5.8.33: the raw tier's in-memory float16 vector copy.

The claim is narrow: with the cache on, retrieve_raw returns what the paged
scan returns (same events, scores within float16 error), stays current as the
table changes underneath it, and steps aside whenever it cannot serve.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from engine.core import ChronicleCore  # noqa: E402

# The cache needs numpy; without it the paged scan serves.
HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
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


def _reembedded(core, text):
    """(embedding, model) a correctly-shaped, correctly-prefixed vector for
    `text` -- the same width, prefix and model tag `_on_observed` (reducer.py)
    would write for it -- via the core's own embedder rather than a second,
    possibly differently-configured one. No turn is captured, so nothing
    leaks into observed_fts: only the vector bytes and model tag come back,
    for the caller to UPDATE onto an existing row's natural key exactly as
    scripts/writeback_vectors.py does."""
    from engine.embeddings import embedder_model_tag, pack
    return pack(core.embedder.embed_document(text)), embedder_model_tag(core.embedder)


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

    def test_the_newest_row_deleted_and_reinserted_is_not_mistaken_for_no_change(self):
        """Curation deletes an event's observed vector when its source text
        changes and the backlog re-embeds it under a new event_id. When the
        deleted row held the table's max rowid, SQLite hands the reinsert
        that same rowid back: count and max rowid alone come back exactly as
        they were, so only the identity of the top row tells this apart from
        no change at all (precedent: ProjectionVectorCache's equivalent test
        in tests/test_projection_vector_cache.py)."""
        victim = self.core.capture.observe(
            "Turn alpha: a lighthouse keeper counts gulls over the harbor.",
            "Noted: lighthouse keeper counts gulls.",
            session_id="s_newest_a", occurred_at="2026-05-01T10:00:00Z")
        self.core.process_pending()
        first = _run(self.core, "lighthouse keeper counts gulls over the harbor", True)
        self.assertTrue(first)
        self.assertEqual(first[0][0], victim, "fixture: the query must rank its own event first")
        cache = self.cache()
        rebuilds = cache.rebuilds

        def _state():
            return tuple(self.core.store._conn().execute(
                "SELECT COUNT(*), MAX(rowid) FROM observed_vectors").fetchone())

        before = _state()
        self.core.store.delete_observed_vector(victim)
        # No word here overlaps `victim`'s text, so the lexical channel cannot
        # explain a hit on this query -- only the vector cache can.
        reinserted = self.core.capture.observe(
            "Turn beta: a marmot naps beside a mossy trailhead sign.",
            "Noted: marmot naps at the mossy trailhead.",
            session_id="s_newest_b", occurred_at="2026-05-02T10:00:00Z")
        self.core.process_pending()
        self.assertEqual(_state(), before, "fixture: the rowid was not reused")
        on = _run(self.core, "marmot naps beside a mossy trailhead sign", True)
        off = _run(self.core, "marmot naps beside a mossy trailhead sign", False)
        self.assertEqual(on, off)
        self.assertTrue(on)
        self.assertEqual(on[0][0], reinserted)
        self.assertNotIn(victim, [e for e, _ in on])
        self.assertGreater(cache.rebuilds, rebuilds)


@_needs_numpy
class TestGenerationTracksAnInPlaceUpdate(_Case):
    """F3: `scripts/writeback_vectors.py` UPDATEs a row's embedding IN PLACE
    on its existing event_id -- neither count, max rowid nor (unless the row
    happens to be the newest) the anchor identity moves. Only the generation
    counter (MemoryStore.bump_vector_generation) sees it.

    `bump_vector_generation` is called ONLY for that same-rowid case. An
    ordinary insert or `INSERT OR REPLACE` must NOT bump it -- most of this
    table's rows are written that way, by server-side ops scripts issuing raw
    SQL that never touch the generation at all -- so the append and
    id-collision arithmetic below must keep working with no help from it,
    exactly as it did before F3."""

    def test_an_inplace_update_of_a_non_anchor_row_is_seen(self):
        first = _run(self.core, "sourdough starter", True)
        self.assertTrue(first)
        victim = first[0][0]
        state_before = tuple(self.core.store._conn().execute(
            "SELECT COUNT(*), MAX(rowid) FROM observed_vectors").fetchone())
        # Not the newest row: an ordinary query keeps scoring it, so its
        # rowid is well below the table's current max.
        self.assertNotEqual(
            victim, self.core.store._conn().execute(
                "SELECT event_id FROM observed_vectors ORDER BY rowid DESC LIMIT 1"
            ).fetchone()[0])
        # Rewrite it to a vector of "zebra-striped Fakeglider" -- the same
        # shape scripts/writeback_vectors.py's `UPDATE ... WHERE event_id=?`
        # takes, on the row's OWN natural key.
        new_vec, new_model = _reembedded(self.core, "zebra-striped Fakeglider on the roof")
        with self.core.store.transaction() as conn:
            conn.execute("UPDATE observed_vectors SET embedding=?, model=? WHERE event_id=?",
                        (new_vec, new_model, victim))
            self.core.store.bump_vector_generation("observed_vectors")
        state_after = tuple(self.core.store._conn().execute(
            "SELECT COUNT(*), MAX(rowid) FROM observed_vectors").fetchone())
        self.assertEqual(state_before, state_after,
                         "fixture: an in-place UPDATE must not move count or max rowid")
        on = _run(self.core, "zebra-striped Fakeglider on the roof", True)
        off = _run(self.core, "zebra-striped Fakeglider on the roof", False)
        self.assertEqual(on, off)
        self.assertTrue(on)
        self.assertEqual(on[0][0], victim, "the cache must score the NEW vector, not the stale one")

    def test_a_raw_sql_insert_with_no_bump_still_takes_the_append_path(self):
        """ops/embed_projections.py, ops/enrich_embeddings.py and their
        siblings write new vectors via raw SQL directly against the store's
        connection -- never through MemoryStore's Python API, so they never
        call bump_vector_generation. The append path must keep working for
        them with the generation flat throughout: count/max rowid growing,
        with nothing at the old anchor changed, already proves a pure append
        on its own (this is the pre-F3 arithmetic, unmodified)."""
        _run(self.core, "kayaking", True)   # warm the cache
        cache = self.cache()
        rebuilds, appends = cache.rebuilds, cache.appends
        new_vec, new_model = _reembedded(self.core, "a raw SQL inserted turn about gliders")
        with self.core.store.transaction() as conn:
            conn.execute(
                "INSERT INTO observed_vectors(event_id,embedding,model,owner,created_at) "
                "VALUES(?,?,?,?,?)",
                ("ev_raw_sql_insert", new_vec, new_model, "assistant", "2026-07-01T00:00:00Z"))
            # deliberately no bump_vector_generation call: this simulates an
            # ops script's raw SQL write, which never makes one either.
        on = _run(self.core, "a raw SQL inserted turn about gliders", True)
        self.assertEqual(on, _run(self.core, "a raw SQL inserted turn about gliders", False))
        self.assertTrue(on)
        self.assertEqual(on[0][0], "ev_raw_sql_insert")
        self.assertEqual(cache.rebuilds, rebuilds, "a plain append must stay on the cheap path")
        self.assertEqual(cache.appends, appends + 1)

    def test_a_raw_sql_insert_or_replace_of_an_existing_key_still_rebuilds(self):
        """`INSERT OR REPLACE` on an event_id that already has a row deletes
        the old row and inserts a fresh one under a NEW rowid: the net row
        count does not grow (one out, one in), so the append branch's own
        `count > self._count` precondition already rules this out and it
        falls straight to a rebuild -- no generation involvement needed."""
        first = _run(self.core, "sourdough starter", True)
        self.assertTrue(first)
        victim = first[0][0]
        _run(self.core, "kayaking", True)   # warm the cache
        cache = self.cache()
        rebuilds = cache.rebuilds
        new_vec, new_model = _reembedded(self.core, "sourdough starter but replaced entirely")
        with self.core.store.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO observed_vectors(event_id,embedding,model,owner,created_at) "
                "VALUES(?,?,?,?,?)",
                (victim, new_vec, new_model, "assistant", "2026-07-01T00:00:00Z"))
        on = _run(self.core, "sourdough starter but replaced entirely", True)
        self.assertEqual(on, _run(self.core, "sourdough starter but replaced entirely", False))
        self.assertTrue(on)
        self.assertEqual(on[0][0], victim)
        self.assertGreater(cache.rebuilds, rebuilds)


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
        want = _run(self.core, "kayaking", False)
        self.assertTrue(want)
        with mock.patch.dict(sys.modules, {"numpy": None}):   # `import numpy` now raises
            got = _run(self.core, "kayaking", True)
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
