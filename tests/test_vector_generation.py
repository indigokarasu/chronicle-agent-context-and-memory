"""Chronicle — the vector write generation counter (F3).

`MemoryStore.bump_vector_generation` / `get_vector_generation` give
ObservedVectorCache and ProjectionVectorCache (engine/vector_cache.py) a
signal that changes on an in-place `UPDATE` of a vector row, which row count
and max rowid do not: `scripts/writeback_vectors.py` rewrites a row's
`embedding`/`model` on its existing natural key, by design never inserting or
deleting, so a cache keyed on count and max rowid alone would keep serving the
pre-update vector forever.

This is deliberately narrow. `bump_vector_generation` must be called ONLY for
a same-rowid change to an existing row's embedding — never for an ordinary
insert, `INSERT OR REPLACE`, or delete, which the caches already tell apart
from count/max rowid/identity alone, and which is how most of the store's
vectors actually get written: server-side ops scripts (ops/embed_projections.py,
ops/enrich_embeddings.py, and others) issue raw SQL against the connection and
never call this at all. Bumping on an ordinary write would tell the caches
nothing new and would force a full rebuild after every one of those scripts'
batches instead of the cheap append the caches exist to provide — this was an
earlier draft's actual mistake, caught in review; see engine/store.py's
section comment above `bump_vector_generation` for the full reasoning.

These tests are the store-level primitive in isolation: it starts at zero, one
call advances it by exactly one, different tables are independent counters, a
bump made inside an already-open transaction is part of that same commit
rather than a separate one (the property `update_session_vector` — the one
in-place write path in engine/store.py — relies on), and the ordinary
insert/delete paths do NOT bump."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.store import MemoryStore  # noqa: E402


def _store():
    return MemoryStore(str(Path(tempfile.mkdtemp(prefix="vecgen-")) / "chronicle.db"))


class TestBumpVectorGeneration(unittest.TestCase):
    def test_starts_at_zero(self):
        store = _store()
        self.assertEqual(store.get_vector_generation("observed_vectors"), 0)
        self.assertEqual(store.get_vector_generation("a_table_never_bumped"), 0)

    def test_one_bump_advances_by_one(self):
        store = _store()
        store.bump_vector_generation("observed_vectors")
        self.assertEqual(store.get_vector_generation("observed_vectors"), 1)
        store.bump_vector_generation("observed_vectors")
        store.bump_vector_generation("observed_vectors")
        self.assertEqual(store.get_vector_generation("observed_vectors"), 3)

    def test_tables_are_independent_counters(self):
        store = _store()
        store.bump_vector_generation("observed_vectors")
        store.bump_vector_generation("observed_vectors")
        store.bump_vector_generation("projection_vectors")
        self.assertEqual(store.get_vector_generation("observed_vectors"), 2)
        self.assertEqual(store.get_vector_generation("projection_vectors"), 1)
        self.assertEqual(store.get_vector_generation("memory_vectors"), 0)

    def test_survives_a_reopen(self):
        path = str(Path(tempfile.mkdtemp(prefix="vecgen-")) / "chronicle.db")
        MemoryStore(path).bump_vector_generation("projection_vectors")
        reopened = MemoryStore(path)
        self.assertEqual(reopened.get_vector_generation("projection_vectors"), 1)

    def test_a_bump_inside_an_open_transaction_joins_that_commit(self):
        """`transaction()` is re-entrant (engine/store.py): a bump issued from
        inside an already-open `with store.transaction():` block must be part
        of THAT commit, not a second one of its own -- this is what lets every
        add_*/delete_* vector method in engine/store.py call
        bump_vector_generation() as a plain extra statement in its existing
        transaction. A rollback of the outer block must discard the bump too."""
        store = _store()
        with store.transaction() as conn:
            conn.execute("INSERT INTO meta(key,value) VALUES('probe','1')")
            store.bump_vector_generation("observed_vectors")
        self.assertEqual(store.get_vector_generation("observed_vectors"), 1)

        with self.assertRaises(RuntimeError):
            with store.transaction() as conn:
                store.bump_vector_generation("observed_vectors")
                raise RuntimeError("boom")
        self.assertEqual(store.get_vector_generation("observed_vectors"), 1,
                         "the bump inside a rolled-back transaction must not survive it")

    def test_ordinary_insert_and_delete_paths_do_not_bump(self):
        """A spot check against the real call sites rather than a re-typed
        list of them. `INSERT OR REPLACE` gives a changed row a NEW rowid and
        a plain DELETE removes it outright -- both already move count and/or
        max rowid, which is what the caches' own arithmetic (identity anchor,
        append-vs-delete counting) uses to detect them without any help from
        the generation. Bumping here too would tell a cache nothing it could
        not already see, and would make every one of these calls behave, from
        a live cache's point of view, exactly like the raw-SQL ops scripts
        that never call bump_vector_generation at all -- so if these bumped,
        the tests in tests/test_observed_vector_cache.py and
        tests/test_projection_vector_cache.py proving an ordinary append
        still takes the cheap path would be proving something this store
        does not actually do under those scripts."""
        store = _store()
        tables = ("observed_vectors", "memory_vectors", "projection_vectors",
                 "query_proxy_vectors", "session_index")
        before = {t: store.get_vector_generation(t) for t in tables}
        store.add_observed_vector("ev1", b"\x00" * 8, "hashing-v1", "assistant")
        store.add_observed_vector("ev1", b"\x01" * 8, "hashing-v1", "assistant")  # INSERT OR REPLACE
        store.add_memory_vector("b1", "fact", b"\x00" * 8, "hashing-v1")
        store.add_projection_vector("prov", "ext1", b"\x00" * 8, "hashing-v1", "assistant")
        store.add_query_proxy_vector("b1", 0, "fact", "q?", b"\x00" * 8, "hashing-v1")
        store.add_session_vector("s1", "summary", b"\x00" * 8, "assistant",
                                 "2026-01-01T00:00:00Z", model="hashing-v1")
        for t in tables:
            self.assertEqual(store.get_vector_generation(t), before[t],
                             "table %s: an ordinary insert must not bump" % t)

        store.delete_observed_vector("ev1")
        store.delete_memory_vector("b1")
        store.delete_projection_vectors("prov")
        store.delete_query_proxy_vectors("b1")
        for t in tables:
            self.assertEqual(store.get_vector_generation(t), before[t],
                             "table %s: a delete must not bump" % t)

    def test_the_one_in_place_write_path_bumps(self):
        """`update_session_vector` is the one place in engine/store.py, beside
        scripts/writeback_vectors.py, that rewrites a vector row on its
        EXISTING rowid: a plain `UPDATE ... WHERE session_id=?`, never an
        upsert. Confirmed by grep across engine/store.py at F3 rework time
        (see the section comment above bump_vector_generation) -- if a future
        write path does the same, it must bump here too, the same way this
        one does."""
        store = _store()
        store.add_session_vector("s1", "summary", b"\x00" * 8, "assistant",
                                 "2026-01-01T00:00:00Z", model="hashing-v1")
        before = store.get_vector_generation("session_index")
        self.assertTrue(store.update_session_vector("s1", b"\x01" * 8, "hashing-v2"))
        self.assertEqual(store.get_vector_generation("session_index"), before + 1)


if __name__ == "__main__":
    unittest.main()
