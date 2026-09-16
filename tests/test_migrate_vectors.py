"""
Chronicle — acceptance tests for A0d: scripts/migrate_vectors.py.

The health heal is a trickle, bounded so a daily self-repair cannot stall the
box. A wholesale model change is not drift: on the live store 88% of ~193k
vectors were written by a 2048-dim model while the configured embedder is
768-dim, which the heal alone would take most of a year to work through. This
tool does the same corpus in one bounded, resumable pass.

Checks here, against a synthetic store with mixed tags and widths and a FAKE
OpenAI-compatible endpoint (no network, no model):
  (a) --dry-run counts are exact, per (tag, dims) -> action, and change nothing;
  (b) a real run converges the store to 100% canonical tag AND width;
  (c) a second run is a no-op;
  (d) a row that fails to embed is left EXACTLY as it was — never blanked,
      never written short, never re-tagged to look healthy;
  (e) a dead endpoint stops the run with a non-zero exit and a resumable
      summary, and the rows it did repair stay repaired;
  (f) renamed-but-correct rows are re-tagged without any embed call at all.

Fixtures use only fake values (Pat Testley, Acme Fake Co).
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import Config
from engine.embeddings import HashingEmbedder, embedder_model_tag, pack
from engine.store import MemoryStore
from scripts.migrate_vectors import Migrator, classify, migrate, survey

GGUF_PATH = "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf"
DIMS = 16
OLD_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"


class _FakeEndpointEmbedder:
    """Stands in for a local OpenAI-compatible server: deterministic vectors of
    the right width, a reported name that is a gguf PATH (llama.cpp's actual
    self-report), and a `dead` switch plus a `poison` set so endpoint failure
    and single-row failure can each be exercised without a network."""

    def __init__(self, dimensions=DIMS, model=GGUF_PATH):
        self.model = model
        self.dimensions = dimensions
        self.use_task_prefixes = "nomic" in model.lower()
        self._h = HashingEmbedder(dimensions=dimensions, model=model)
        self.dead = False
        self.poison = set()          # texts that always fail
        self.calls = 0
        self.short = False           # return a WRONG-width vector

    def _one(self, text):
        self.calls += 1
        if self.dead:
            raise RuntimeError("connection refused")
        for p in self.poison:
            if p in (text or ""):
                raise RuntimeError("model rejected input")
        if self.short:
            return [0.1] * (self.dimensions // 2)
        return self._h.embed(text)

    def embed(self, text):
        return self._one(text)

    def embed_query(self, query):
        return self._one(("search_query: " + (query or "")) if self.use_task_prefixes else query)

    def embed_document(self, document):
        return self._one(("search_document: " + (document or ""))
                         if self.use_task_prefixes else document)

    def embed_batch(self, texts, chunk=64):
        return [self.embed_document(t) for t in texts]

    def model_with_prefix_marker(self):
        return (self.model + "[prefixed]") if self.use_task_prefixes else self.model


def _seed_store(home):
    """A store with real events/beliefs/proxies, then deliberately corrupted
    into a mixture of tag forms and widths."""
    from engine.core import ChronicleCore
    core = ChronicleCore(home, {"embeddings": {"model": "hashing", "dimensions": DIMS}})
    core.initialize("s1", principal_id="assistant")
    core.capture.observe(
        "I am Pat Testley\n"
        "I work at Acme Fake Co\n"
        "I live in Springfield\n"
        "My manager is Dana Fictional", "", session_id="s1")
    core.capture.observe(
        "I moved to Riverton\nI still work at Acme Fake Co", "", session_id="s1")
    core.process_pending()
    core.curation.drain()
    return core


class _MigrateCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a0d_")
        self.core = _seed_store(self.home)
        self.db = self.core.store.db_path
        self.emb = _FakeEndpointEmbedder()
        self.active = embedder_model_tag(self.emb)
        self.assertEqual(self.active, "nomic-embed-text[prefixed]")
        self.cfg = Config({"embeddings": {"model": "hashing", "dimensions": DIMS}})

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- corruption helpers -------------------------------------------------
    def _corrupt(self):
        """Three groups, one per action:
             observed_vectors     -> OLD model, WRONG width  (re-embed)
             memory_vectors       -> gguf path name, right width (retag)
             query_proxy_vectors  -> ollama name, right width  (retag)
        """
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET model=?, embedding=?",
                      (OLD_MODEL, pack([0.03] * 2048)))
            c.execute("UPDATE memory_vectors SET model=?", (GGUF_PATH + "[prefixed]",))
            c.execute("UPDATE query_proxy_vectors SET model=?",
                      ("nomic-embed-text:latest[prefixed]",))

    def _counts(self):
        conn = self.core.store._conn()
        return {t: conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                for t in ("observed_vectors", "memory_vectors", "query_proxy_vectors")}

    def _all_rows(self, table):
        return [dict(r) for r in self.core.store._conn().execute(
            "SELECT * FROM %s ORDER BY rowid" % table).fetchall()]

    def _assert_all_canonical(self):
        conn = self.core.store._conn()
        for t in ("observed_vectors", "memory_vectors", "query_proxy_vectors"):
            bad = conn.execute(
                "SELECT COUNT(*) FROM %s WHERE model != ? OR length(embedding) != ?" % t,
                (self.active, DIMS * 4)).fetchone()[0]
            self.assertEqual(bad, 0, "%s still holds non-canonical rows" % t)

    def _migrate(self, **kw):
        return migrate(self.db, cfg=self.cfg, embedder=self.emb, verbose=False, **kw)


class TestClassification(unittest.TestCase):
    def test_actions(self):
        active = "nomic-embed-text[prefixed]"
        n = DIMS * 4
        self.assertEqual(classify(active, n, active, n), "ok")
        self.assertEqual(classify(GGUF_PATH + "[prefixed]", n, active, n), "retag")
        self.assertEqual(classify("nomic-embed-text:latest[prefixed]", n, active, n), "retag")
        self.assertEqual(classify("nomic-embed-text", n, active, n), "reembed")   # marker gone
        self.assertEqual(classify(active, 8192, active, n), "reembed")            # wrong width
        self.assertEqual(classify(OLD_MODEL, n, active, n), "reembed")            # other model
        self.assertEqual(classify(active, None, active, n), "reembed")            # null blob


class TestDryRun(_MigrateCase):
    def test_counts_are_exact_and_nothing_changes(self):
        self._corrupt()
        before = self._all_rows("observed_vectors") + self._all_rows("memory_vectors")
        conn = self.core.store._conn()
        plan = survey(conn, self.active, DIMS * 4)

        actions = {}
        for table in plan:
            for _tag, _blen, cnt, action in plan[table]:
                actions[action] = actions.get(action, 0) + cnt
        counts = self._counts()
        self.assertEqual(actions.get("reembed", 0), counts["observed_vectors"])
        self.assertEqual(actions.get("retag", 0),
                         counts["memory_vectors"] + counts["query_proxy_vectors"])
        self.assertEqual(actions.get("ok", 0), 0)

        self.assertEqual(self._migrate(dry_run=True), 0)
        self.assertEqual(self.emb.calls, 0, "--dry-run must never embed")
        self.assertEqual(self._all_rows("observed_vectors") + self._all_rows("memory_vectors"),
                         before, "--dry-run must not write")


class TestConvergence(_MigrateCase):
    def test_real_run_converges_and_rerun_is_a_noop(self):
        self._corrupt()
        counts = self._counts()
        self.assertEqual(self._migrate(batch=2), 0)
        self._assert_all_canonical()
        # Nothing was lost: every row is still there, repaired in place.
        self.assertEqual(self._counts(), counts)

        calls = self.emb.calls
        self.assertEqual(self._migrate(batch=2), 0)
        self.assertEqual(self.emb.calls, calls, "a converged store must cost zero embeds")
        self._assert_all_canonical()

    def test_renames_cost_no_embeds(self):
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET model=?", (GGUF_PATH + "[prefixed]",))
            c.execute("UPDATE memory_vectors SET model=?", ("nomic-embed-text:latest[prefixed]",))
            c.execute("UPDATE query_proxy_vectors SET model=?", (GGUF_PATH,))
        blobs_before = [r["embedding"] for r in self._all_rows("observed_vectors")]
        self.assertEqual(self._migrate(batch=4), 0)
        self._assert_all_canonical()
        self.assertEqual([r["embedding"] for r in self._all_rows("observed_vectors")],
                         blobs_before, "a rename must not rewrite the bytes")
        # query_proxy_vectors lost its [prefixed] marker, so those DO re-embed;
        # the two right-marker tables must not have.
        self.assertLessEqual(self.emb.calls, self._counts()["query_proxy_vectors"])

    def test_proxies_are_rebuilt_not_dropped(self):
        """The heal drops stale proxies (the embed queue cannot express a
        variable-length proxy set). This tool has the question text in hand, so
        a migration keeps the doc2query tier."""
        self._corrupt()
        with self.core.store.transaction() as c:
            c.execute("UPDATE query_proxy_vectors SET model=?, embedding=?",
                      (OLD_MODEL, pack([0.05] * 2048)))
        n_before = self._counts()["query_proxy_vectors"]
        questions_before = sorted(r["question"] for r in self._all_rows("query_proxy_vectors"))
        self.assertEqual(self._migrate(batch=3), 0)
        self.assertEqual(self._counts()["query_proxy_vectors"], n_before)
        self.assertEqual(sorted(r["question"] for r in self._all_rows("query_proxy_vectors")),
                         questions_before)
        self._assert_all_canonical()


class TestFailuresLeaveRowsUntouched(_MigrateCase):
    def test_a_row_that_fails_to_embed_is_not_written(self):
        self._corrupt()
        # Poison exactly one belief's text.
        row = self.core.store._conn().execute(
            "SELECT belief_id, kind FROM memory_vectors LIMIT 1").fetchone()
        with self.core.store.transaction() as c:
            c.execute("UPDATE memory_vectors SET model=?, embedding=? "
                      "WHERE belief_id=? AND kind=?",
                      (OLD_MODEL, pack([0.07] * 2048), row[0], row[1]))
        before = self.core.store._conn().execute(
            "SELECT model, embedding FROM memory_vectors WHERE belief_id=? AND kind=?",
            (row[0], row[1])).fetchone()
        text = self.core.store._conn().execute(
            "SELECT value FROM facts WHERE belief_id=?", (row[0],)).fetchone()
        self.emb.poison = {text[0]} if text and text[0] else {"Acme Fake Co"}

        rc = self._migrate(batch=1)
        self.assertEqual(rc, 2, "unrepaired rows must be reported by a non-zero exit")
        after = self.core.store._conn().execute(
            "SELECT model, embedding FROM memory_vectors WHERE belief_id=? AND kind=?",
            (row[0], row[1])).fetchone()
        self.assertEqual(after[0], before[0], "a failed row must keep its tag, not be relabelled")
        self.assertEqual(after[1], before[1], "a failed row must keep its bytes, not be blanked")
        self.assertIsNotNone(after[1])

    def test_a_wrong_width_answer_is_refused(self):
        """If the endpoint returns a vector of the wrong width, that is not the
        model we think it is. Writing it would put fresh garbage in the store
        under a canonical tag."""
        self._corrupt()
        self.emb.short = True
        rc = self._migrate(batch=2)
        self.assertEqual(rc, 2)
        conn = self.core.store._conn()
        widths = {r[0] for r in conn.execute(
            "SELECT DISTINCT length(embedding) FROM observed_vectors").fetchall()}
        self.assertNotIn(DIMS * 4 // 2, widths, "a short vector must never be written")


class TestDeadEndpointStopsCleanly(_MigrateCase):
    def test_stops_nonzero_and_keeps_what_it_repaired(self):
        self._corrupt()
        self.emb.dead = True
        rc = self._migrate(batch=2)
        self.assertEqual(rc, 2)
        # The re-tag pass runs BEFORE any embed, so those repairs survive an
        # endpoint that was never reachable.
        conn = self.core.store._conn()
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM memory_vectors WHERE model != ?",
                         (self.active,)).fetchone()[0], 0)
        # …and nothing was written for the rows that needed an embed.
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM observed_vectors WHERE model = ?",
                         (OLD_MODEL,)).fetchone()[0], self._counts()["observed_vectors"])

        # Bring it back: the SAME command resumes and converges.
        self.emb.dead = False
        self.assertEqual(self._migrate(batch=2), 0)
        self._assert_all_canonical()


class TestRefusesAnUnusableEmbedder(_MigrateCase):
    def test_degraded_embedder_migrates_nothing(self):
        from engine.embeddings import DegradedEmbedder
        self._corrupt()
        before = self._all_rows("memory_vectors")
        rc = migrate(self.db, cfg=self.cfg, verbose=False,
                     embedder=DegradedEmbedder(model="auto", dimensions=DIMS,
                                               base_url="http://127.0.0.1:9/v1"))
        self.assertEqual(rc, 1)
        self.assertEqual(self._all_rows("memory_vectors"), before)


class TestResumability(_MigrateCase):
    def test_interrupted_run_resumes_from_what_is_left(self):
        self._corrupt()
        n_obs = self._counts()["observed_vectors"]
        self.assertGreater(n_obs, 1)

        # Repair exactly one batch, then stop by killing the endpoint.
        store = MemoryStore(self.db)
        m = Migrator(store, self.emb, batch=1, verbose=False)
        plan = survey(store._conn(), self.active, DIMS * 4)
        m.retag(plan)
        gen = m._walk("observed_vectors", ["event_id", "owner"])
        rows = next(gen)
        conn = store._conn()
        eid, owner = rows[0][1], rows[0][2]
        payload = conn.execute("SELECT payload FROM events WHERE event_id=?", (eid,)).fetchone()[0]
        text = (json.loads(payload) or {}).get("excerpt", "")
        store.add_observed_vector(eid, pack(self.emb.embed_document(text)), self.active,
                                  owner or "default")

        left = conn.execute(
            "SELECT COUNT(*) FROM observed_vectors WHERE model != ? OR length(embedding) != ?",
            (self.active, DIMS * 4)).fetchone()[0]
        self.assertEqual(left, n_obs - 1, "exactly one row should be repaired so far")

        self.assertEqual(self._migrate(batch=2), 0)
        self._assert_all_canonical()


if __name__ == "__main__":
    unittest.main(verbosity=2)
