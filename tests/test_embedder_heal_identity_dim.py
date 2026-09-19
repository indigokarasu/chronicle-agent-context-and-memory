"""
Chronicle — acceptance tests for A0b: heal by identity + dimension.

The pre-A0 heal compared raw tag STRINGS, so one model reporting itself as
"nomic-embed-text", "nomic-embed-text:latest" and
"/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf" looked like three models. It
requeued rows that were already correct, re-embedded them to identical bytes,
wrote them back under whichever name that writer resolved, and found them
mismatched again next pass — the live 60-rows-in-9-days drip that converged on
nothing. Meanwhile a genuinely wrong-DIMENSION vector (2048-dim nemotron blobs
in a 768-dim nomic store) was not mismatched at all by that rule and was never
touched.

Checks here:
  (a) gguf-path-tagged and ollama-tagged rows of the SAME model converge by
      RE-TAGGING, with the stored bytes untouched and no embed job created;
  (b) wrong-dimension rows are requeued (and counted as wrong_dim);
  (c) a missing E1 prefix marker still requeues (pre-A0 behavior preserved);
  (d) heal twice → the second run finds zero;
  (e) the health counters surface the condition (a mismatched store no longer
      reports clean), and the requeue bound is respected;
  (f) a degraded embedder heals NOTHING rather than requeueing the corpus.

Fixtures use only fake values (Pat Testley, Acme Fake Co).
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import DegradedEmbedder, HashingEmbedder, embedder_model_tag, pack

GGUF_PATH = "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf"


class _NomicLike:
    """Hashing-backed, nomic-NAMED embedder: real E1 prefix + marker contract,
    deterministic offline vectors, no network."""

    def __init__(self, model="nomic-embed-text", dimensions=256):
        self.model = model
        self.dimensions = dimensions
        self._h = HashingEmbedder(dimensions=dimensions, model=model)
        self.use_task_prefixes = "nomic" in model.lower()

    def embed(self, text):
        return self._h.embed(text)

    def embed_query(self, query):
        return self._h.embed(("search_query: " + (query or "")) if self.use_task_prefixes else query)

    def embed_document(self, document):
        return self._h.embed(("search_document: " + (document or ""))
                             if self.use_task_prefixes else document)

    def model_with_prefix_marker(self):
        return (self.model + "[prefixed]") if self.use_task_prefixes else self.model


class _HealCase(unittest.TestCase):
    # `dimensions` is DECLARED: _NomicLike is 256 wide and wears a nomic NAME,
    # and nomic-embed-text is a 768-dim model, so without this the A0g width guard
    # would (correctly) refuse to heal a store whose endpoint contradicts the known
    # width of the model it claims to be. Declaring it is the documented way to say
    # "256 is what this deployment means".
    CFG = {"embeddings": {"model": "hashing", "dimensions": 256}}

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a0b_heal_")
        self.core = ChronicleCore(self.home, self.CFG)
        self.emb = _NomicLike()
        self.core.embedder = self.emb
        self.core.reducer.embedder = self.emb
        self.core.initialize("s1", principal_id="assistant")
        self.core.capture.observe(
            "I am Pat Testley\nI live in Springfield\nI work at Acme Fake Co", "",
            session_id="s1")
        self.core.process_pending()
        self.core.curation.drain()
        self.active = embedder_model_tag(self.emb)
        self.assertEqual(self.active, "nomic-embed-text[prefixed]")
        for table in ("observed_vectors", "memory_vectors", "query_proxy_vectors"):
            n = self.core.store._conn().execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            self.assertGreater(n, 0, "fixture wrote no %s" % table)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def _set_tag(self, table, tag):
        with self.core.store.transaction() as c:
            c.execute("UPDATE %s SET model=?" % table, (tag,))

    def _tags(self, table):
        return sorted(r[0] for r in self.core.store._conn().execute(
            "SELECT DISTINCT model FROM %s" % table).fetchall())

    def _blobs(self, table, id_col):
        return {r[0]: r[1] for r in self.core.store._conn().execute(
            "SELECT %s, embedding FROM %s" % (id_col, table)).fetchall()}

    def _pending_embed_jobs(self):
        return self.core.store._conn().execute(
            "SELECT COUNT(*) FROM curation_jobs WHERE task='embed'").fetchone()[0]


class TestSameModelDifferentNameRetags(_HealCase):
    def test_gguf_path_and_ollama_names_converge_without_reembedding(self):
        before = self._blobs("observed_vectors", "event_id")
        self.assertTrue(before)
        self._set_tag("observed_vectors", GGUF_PATH + "[prefixed]")
        self._set_tag("memory_vectors", "nomic-embed-text:latest[prefixed]")

        jobs_before = self._pending_embed_jobs()
        res = self.core.health._embedder_mismatch_heal()
        summary = res["embedder_mismatch"]

        self.assertGreater(summary["retagged"], 0)
        self.assertEqual(summary["requeued"], 0, "a rename must never cost an embed")
        self.assertEqual(summary["wrong_dim"], 0)
        self.assertEqual(self._pending_embed_jobs(), jobs_before,
                         "no embed job may be created for a pure rename")

        self.assertEqual(self._tags("observed_vectors"), [self.active])
        self.assertEqual(self._tags("memory_vectors"), [self.active])
        # The BYTES are untouched: this is a metadata repair, not a re-embed.
        self.assertEqual(self._blobs("observed_vectors", "event_id"), before)

    def test_proxies_are_retagged_not_dropped(self):
        n_before = self.core.store._conn().execute(
            "SELECT COUNT(*) FROM query_proxy_vectors").fetchone()[0]
        self.assertGreater(n_before, 0)
        self._set_tag("query_proxy_vectors", GGUF_PATH + "[prefixed]")
        self.core.health._embedder_mismatch_heal()
        n_after = self.core.store._conn().execute(
            "SELECT COUNT(*) FROM query_proxy_vectors").fetchone()[0]
        self.assertEqual(n_after, n_before,
                         "a renamed proxy set is still valid and must survive")
        self.assertEqual(self._tags("query_proxy_vectors"), [self.active])


class TestWrongDimensionRequeues(_HealCase):
    def test_wrong_dim_rows_are_requeued_and_counted(self):
        # Right tag, wrong width — the live nemotron case: 2048-dim blobs in a
        # store whose active embedder is narrower. The pre-A0 rule (tag string
        # equality) called these a MATCH and left them scoring 0.0 forever.
        rows = self.core.store.iter_observed_vectors()
        self.assertTrue(rows)
        eid = rows[0]["event_id"]
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET embedding=?, model=? WHERE event_id=?",
                      (pack([0.01] * 2048), self.active, eid))

        res = self.core.health._embedder_mismatch_heal()
        summary = res["embedder_mismatch"]
        self.assertGreaterEqual(summary["wrong_dim"], 1)
        self.assertGreaterEqual(summary["mismatched"], 1)
        self.assertGreaterEqual(summary["requeued"], 1)
        self.assertGreaterEqual(res["vectors_wrong_dim"], 1)

        self.core.curation.drain()
        blob = self.core.store._conn().execute(
            "SELECT embedding FROM observed_vectors WHERE event_id=?", (eid,)).fetchone()[0]
        self.assertEqual(len(blob), self.emb.dimensions * 4)

    def test_only_the_wrong_width_rows_with_the_active_tag_are_requeued(self):
        """The live nemotron shape: correct-looking tags on wrong-width blobs,
        side by side with healthy rows carrying the SAME tag. Selecting by tag
        alone would sweep the healthy rows into the requeue and spend the whole
        bound on rows that need nothing."""
        rows = self.core.store._conn().execute(
            "SELECT belief_id, kind FROM memory_vectors ORDER BY rowid").fetchall()
        self.assertGreaterEqual(len(rows), 3)
        broken = [(r[0], r[1]) for r in rows[:2]]
        with self.core.store.transaction() as c:
            for bid, kind in broken:
                c.execute("UPDATE memory_vectors SET embedding=? WHERE belief_id=? AND kind=?",
                          (pack([0.01] * 2048), bid, kind))
        res = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(res["mismatched"], len(broken), res)
        self.assertEqual(res["wrong_dim"], len(broken), res)
        self.assertLessEqual(res["requeued"], len(broken),
                             "healthy rows sharing the tag must not be requeued")
        queued = {json.loads(r[0])["target_id"] for r in self.core.store._conn().execute(
            "SELECT payload FROM curation_jobs WHERE task='embed'").fetchall()}
        self.assertTrue(queued <= {b for b, _k in broken}, queued)

    def test_wrong_dim_with_a_renamed_tag_is_reembedded_not_retagged(self):
        rows = self.core.store.iter_observed_vectors()
        eid = rows[0]["event_id"]
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET embedding=?, model=? WHERE event_id=?",
                      (pack([0.01] * 2048), GGUF_PATH + "[prefixed]", eid))
        res = self.core.health._embedder_mismatch_heal()
        # Same canonical id, but the geometry is wrong: re-tagging it would
        # LAUNDER a bad vector into a correct-looking row.
        self.assertGreaterEqual(res["embedder_mismatch"]["requeued"], 1)
        self.core.curation.drain()
        blob = self.core.store._conn().execute(
            "SELECT embedding FROM observed_vectors WHERE event_id=?", (eid,)).fetchone()[0]
        self.assertEqual(len(blob), self.emb.dimensions * 4)


class TestMarkerMismatchStillRequeues(_HealCase):
    def test_missing_prefix_marker_requeues(self):
        rows = self.core.store.iter_observed_vectors()
        eid = rows[0]["event_id"]
        # Bare tag, no marker: a pre-E1 write. Same model, same width, but the
        # vector was embedded WITHOUT "search_document: " — a real geometry
        # difference that a rename repair must not paper over.
        self.core.store.add_observed_vector(eid, rows[0]["embedding"],
                                            "nomic-embed-text", rows[0]["owner"])
        res = self.core.health._embedder_mismatch_heal()
        self.assertGreaterEqual(res["embedder_mismatch"]["requeued"], 1)
        self.core.curation.drain()
        self.assertEqual(self.core.store.get_observed_vector_model(eid), self.active)


class TestHealConverges(_HealCase):
    def test_second_pass_finds_zero(self):
        self._set_tag("observed_vectors", GGUF_PATH + "[prefixed]")
        self._set_tag("memory_vectors", "nomic-embed-text")          # marker missing
        self._set_tag("query_proxy_vectors", "nomic-embed-text:latest[prefixed]")

        first = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertGreater(first["mismatched"], 0)
        self.core.curation.drain()

        second = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(second["mismatched"], 0, second)
        self.assertEqual(second["requeued"], 0, second)
        self.assertEqual(second["retagged"], 0, second)

        third = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(third["mismatched"], 0, third)

    def test_clean_store_is_a_no_op(self):
        res = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual((res["mismatched"], res["requeued"], res["retagged"]), (0, 0, 0))


class TestCountersAreVisible(_HealCase):
    def test_health_run_surfaces_the_condition(self):
        self._set_tag("observed_vectors", "nvidia/llama-nemotron-embed-vl-1b-v2:free")
        results = self.core.health.run()
        self.assertIn("vectors_mismatched", results)
        self.assertGreater(results["vectors_mismatched"], 0)
        self.assertGreater(results["vectors_total"], 0)
        self.assertEqual(results["embedder_mismatch"]["active_tag"], self.active)
        # Recorded durably: health_runs rows are JSON, so a dashboard can read
        # the counter without knowing the heal exists.
        row = self.core.store._conn().execute(
            "SELECT results FROM health_runs ORDER BY rowid DESC LIMIT 1").fetchone()
        self.assertIn("vectors_mismatched", row[0])


class TestRequeueBound(_HealCase):
    CFG = {"embeddings": {"model": "hashing", "dimensions": 256},
           "health": {"self_heal": {"embedder_mismatch_max": 1}}}

    def test_requeue_bound_is_respected(self):
        self._set_tag("observed_vectors", "some-other-model")
        self._set_tag("memory_vectors", "some-other-model")
        res = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(res["requeued"], 1)
        self.assertGreater(res["mismatched"], 1)
        self.assertTrue(res["bounded"], "outstanding work must be reported, not hidden")


class TestDegradedEmbedderHealsNothing(_HealCase):
    def test_no_requeue_while_the_backend_is_down(self):
        self._set_tag("observed_vectors", "nomic-embed-text")
        self.core.embedder = DegradedEmbedder(model="auto", dimensions=768,
                                              base_url="http://127.0.0.1:9/v1")
        jobs_before = self._pending_embed_jobs()
        res = self.core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual((res["mismatched"], res["requeued"], res["retagged"]), (0, 0, 0))
        self.assertEqual(self._pending_embed_jobs(), jobs_before)


class TestRequeueHashVectorsMatchesByIdentity(unittest.TestCase):
    """scripts/requeue_hash_vectors.py used a hard-coded tag list, so a store
    written under any other spelling of the offline embedder kept its
    incomparable hash vectors forever."""

    def test_alias_spellings_are_all_found_and_cleared(self):
        home = tempfile.mkdtemp(prefix="a0b_requeue_")
        try:
            core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
            core.initialize("s1", principal_id="assistant")
            core.capture.observe("I am Pat Testley and I work at Acme Fake Co", "",
                                 session_id="s1")
            core.process_pending()
            db_path = core.store.db_path
            # Spellings the hard-coded list never covered.
            with core.store.transaction() as c:
                c.execute("UPDATE observed_vectors SET model='Hashing-v1'")
                c.execute("UPDATE memory_vectors SET model='hashing:latest'")

            import sqlite3 as _sq

            from scripts.requeue_hash_vectors import _hash_tags, requeue
            conn = _sq.connect(db_path)
            self.assertEqual(_hash_tags(conn), ("Hashing-v1", "hashing:latest"))
            conn.close()

            self.assertEqual(requeue(db_path), 0)
            conn = _sq.connect(db_path)
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM observed_vectors").fetchone()[0], 0)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0], 0)
                self.assertGreater(
                    conn.execute("SELECT COUNT(*) FROM curation_jobs WHERE task='embed'"
                                 ).fetchone()[0], 0)
            finally:
                conn.close()
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
