"""
Chronicle — acceptance tests for A0e: vector identity for session_index and
projection_vectors.

A0 unified vector identity across three tables. The schema defines FIVE that
hold a model-tagged embedding, and the two it left out were the two with the
worst numbers on the production store: `session_index` held 7,288 rows of which
6,753 (93%) were 8192-byte / 2048-dim blobs from an abandoned model while the
configured embedder is 768-dim, and NOTHING would ever have repaired them — the
heal did not scan the table and scripts/migrate_vectors.py did not either.
Worse, `session_index` had no `model` column at all, so staleness there was
undetectable by any tag check and visible only as a blob width: the honesty
guarantees A0 established did not hold for it. Session summaries are the
whole-conversation handle multi-session retrieval leans on, so that was a
materially degraded channel, not a cosmetic gap.

Checked here:
  (a) the new column exists, is stamped through the A0 choke point on every
      write, and an OLD store (no column, a legacy row) upgrades in place with
      the legacy row's model left NULL — the honest marker for "unknown";
  (b) NULL / non-canonical / wrong-width session rows are all classified STALE,
      and stale EXACTLY ONCE: repaired, then a re-run is a no-op;
  (c) the heal scans and COUNTS both new tables, per table;
  (d) migrate_vectors --dry-run classifies a mixed synthetic store correctly, a
      real run converges it, and a second run does nothing;
  (e) a wrong-width session or projection vector is never silently scored;
  (f) MUTATION GUARDS: removing either table from the shared scan set fails a
      test, and so does adding a sixth embedding-bearing table without covering
      it;
  (g) both new text sources go through the ONE reducer authority A0fix
      established — no parallel map;
  (h) a REAL embedder (loopback ollama, skipped when absent) stamps the
      canonical tag on a session_index write.

Fixtures use only fake values (Pat Testley, Acme Fake Co) and an offline
hashing-backed embedder — no network, no paid API.
"""

import contextlib
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.migrate_vectors as MV
import scripts.requeue_hash_vectors as RQ
from engine import embeddings as E
from engine.config import Config
from engine import health as H
from engine import reducer as R
from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder, embedder_model_tag, pack
from engine.health import HealthEngine
from engine.store import SCHEMA_VERSION, MemoryStore, _has_col

GGUF_PATH = "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf"
OLD_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
DIMS = 16

# The pre-A0e shape of session_index, restated verbatim so the "old DB" fixture
# is the shape a real upgrade meets rather than a paraphrase of it.
_PRE_A0E_SESSION_INDEX = (
    "CREATE TABLE session_index ("
    "session_id TEXT PRIMARY KEY, summary TEXT, embedding BLOB, owner TEXT, occurred_at TEXT)")


class _NomicLike:
    """Hashing-backed, nomic-NAMED embedder: real E1 prefix + marker contract,
    deterministic offline vectors, no network. The same stand-in A0b's heal
    tests use, so the two suites cannot disagree about what "the active tag" is."""

    def __init__(self, model="nomic-embed-text", dimensions=DIMS):
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

    def embed_batch(self, texts, chunk=64):
        return [self.embed_document(t) for t in texts]

    def model_with_prefix_marker(self):
        return (self.model + "[prefixed]") if self.use_task_prefixes else self.model


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
class _A0eCase(unittest.TestCase):
    """A real store carrying a session vector and a projection vector, both
    written through their normal (queued) paths — never by poking the tables."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a0e_")
        # `dimensions` is DECLARED because this fixture's embedder is a 16-wide
        # stand-in wearing a nomic NAME, which is precisely the shape the A0g width
        # guard refuses: nomic-embed-text is a 768-dim model, so an endpoint
        # answering 16 for it is a contradiction unless the deployment says that is
        # what it means. Saying so here is the documented way (Config.explicit ->
        # embeddings.width_expectation) and leaves every assertion below unchanged.
        self.core = ChronicleCore(self.home,
                                  {"embeddings": {"model": "hashing", "dimensions": DIMS}})
        self.emb = _NomicLike()
        self.core.embedder = self.emb
        self.core.reducer.embedder = self.emb
        # The READ side too: RetrievalEngine holds its own reference, and
        # leaving it on the 768-dim default would make every 16-dim fixture row
        # "wrong width" — an artefact that would let the read-path tests below
        # pass for entirely the wrong reason.
        self.core.retrieval.embedder = self.emb
        self.core.initialize("s1", principal_id="assistant")
        self.core.capture.observe(
            "I am Pat Testley\nI work at Acme Fake Co\nI live in Springfield", "",
            session_id="s1")
        self.core.process_pending()
        self.core.curation.drain()
        self.store = self.core.store
        self.active = embedder_model_tag(self.emb)

        # Session vector, via the summarizer the session-end path enqueues.
        self.store.enqueue_curation("session_summarize", {"session_id": "s1"})
        # Projection vector, via the SAME deferred embed-job path §g5a uses.
        self.store.enqueue_projection_embed(
            "acme_fake_people_db", "person_1",
            "Pat Testley, engineer at Acme Fake Co", owner="default")
        self.core.curation.drain()

        self.assertEqual(self._count("session_index"), 1, "fixture wrote no session vector")
        self.assertEqual(self._count("projection_vectors"), 1,
                         "fixture wrote no projection vector")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ----------------------------------------------------------
    def _count(self, table):
        return self.store._conn().execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]

    def _tags(self, table):
        return sorted(
            (r[0] if r[0] is not None else "<NULL>")
            for r in self.store._conn().execute("SELECT DISTINCT model FROM %s" % table).fetchall())

    def _session_row(self, sid="s1"):
        return self.store.get_session_vector(sid)

    def _set_session(self, *, model=..., embedding=...):
        sets, params = [], []
        if model is not ...:
            sets.append("model=?")
            params.append(model)
        if embedding is not ...:
            sets.append("embedding=?")
            params.append(embedding)
        with self.store.transaction() as c:
            c.execute("UPDATE session_index SET %s" % ", ".join(sets), tuple(params))

    def _heal(self):
        return self.core.health._embedder_mismatch_heal()["embedder_mismatch"]


# ---------------------------------------------------------------------------
# (a) schema + stamping
# ---------------------------------------------------------------------------
class TestSessionIndexCarriesIdentity(_A0eCase):
    def test_the_summarizer_stamps_the_canonical_tag(self):
        row = self._session_row()
        self.assertTrue(row["embedding"], "fixture session row has no vector")
        self.assertEqual(row["model"], self.active)

    def test_the_tag_is_the_canonical_form_not_the_bare_model_name(self):
        """The choke point, not `embedder.model`. This embedder reports
        "nomic-embed-text" and uses E1 task prefixes, so the two differ — which
        is exactly the case a bare-name stamp gets wrong."""
        self.assertNotEqual(self.active, self.emb.model)
        self.assertEqual(self._session_row()["model"], "nomic-embed-text[prefixed]")

    def test_a_failed_embed_records_no_tag_at_all(self):
        """A tag next to bytes that do not exist would be a claim about a
        geometry nothing produced. NULL says what is true."""
        class _Dead:
            model = "nomic-embed-text"
            dimensions = DIMS

            def embed_document(self, text):
                raise RuntimeError("connection refused")

            def model_with_prefix_marker(self):
                return "nomic-embed-text[prefixed]"

        self.core.embedder = _Dead()
        self.store.enqueue_curation("session_summarize", {"session_id": "s1"})
        self.core.curation.drain()
        row = self._session_row()
        self.assertEqual(row["embedding"], b"")
        self.assertIsNone(row["model"])

    def test_add_session_vector_will_not_let_a_writer_forget_the_model(self):
        """`model` is keyword-only and REQUIRED. Defaulting it either way is a
        lie — the active tag would stamp a geometry the caller may not have
        produced, and NULL would let a writer silently omit the thing this
        column exists to record."""
        with self.assertRaises(TypeError):
            self.store.add_session_vector("s9", "text", b"", "default",
                                          "2026-01-01T00:00:00Z")

    def test_projection_writes_already_go_through_the_choke_point(self):
        """A0e's review half: projection_vectors already HAD a model column, so
        the only question was whether its write site stamps the CANONICAL tag
        rather than a bare name. It does — pinned here so it stays that way."""
        self.assertEqual(self._tags("projection_vectors"), [self.active])


class TestOldStoreUpgradesInPlace(unittest.TestCase):
    """A store as a pre-A0e build left it: session_index with no `model`, a real
    row in it, stamped one schema version back."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="a0e-mig-")
        self.path = str(Path(self.dir) / "chronicle.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make_old_db(self):
        MemoryStore(self.path)                       # fresh, current shape...
        conn = sqlite3.connect(self.path)
        conn.execute("DROP TABLE session_index")     # ...rebuilt one version back
        conn.execute(_PRE_A0E_SESSION_INDEX)
        conn.execute("INSERT INTO session_index(session_id,summary,embedding,owner,occurred_at) "
                     "VALUES('s-old','Pat Testley works at Acme Fake Co',?,'default',"
                     "'2026-01-01T00:00:00Z')", (pack([0.02] * 2048),))
        conn.execute("UPDATE meta SET value=? WHERE key='schema_version'",
                     (str(SCHEMA_VERSION - 1),))
        conn.commit()
        conn.close()

    def test_the_column_is_added_and_the_legacy_row_is_left_unknown(self):
        self._make_old_db()
        store = MemoryStore(self.path)               # reopen == migrate
        conn = store._conn()
        self.assertTrue(_has_col(conn, "session_index", "model"))
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        row = store.get_session_vector("s-old")
        # The row SURVIVED, content intact...
        self.assertEqual(row["summary"], "Pat Testley works at Acme Fake Co")
        self.assertEqual(len(row["embedding"]), 2048 * 4)
        # ...and its model is NULL, not a fabricated tag. Nothing on this box
        # knows which model wrote those bytes, and inventing an answer would
        # make an incomparable vector look canonical forever.
        self.assertIsNone(row["model"])

    def test_dry_run_on_an_un_upgraded_store_still_sees_the_rows(self):
        """--dry-run opens the database READ-ONLY, so it cannot migrate the
        column into existence. Reporting session_index as empty there would
        under-report exactly the rows the tool exists for (6,753 of them on the
        live store) on the very first command an operator runs. NULL is what the
        migration will find once the column lands, so NULL is what it says."""
        self._make_old_db()
        conn = sqlite3.connect("file:%s?mode=ro" % self.path, uri=True)
        try:
            plan = MV.survey(conn, "nomic-embed-text[prefixed]", 768 * 4)
        finally:
            conn.close()
        rows = plan["session_index"]
        self.assertEqual(len(rows), 1, "the un-upgraded table was not surveyed")
        tag, blen, cnt, action = rows[0]
        self.assertIsNone(tag)
        self.assertEqual(blen, 2048 * 4)
        self.assertEqual(cnt, 1)
        self.assertEqual(action, "reembed")

    def test_a_null_tag_renders_as_unknown_not_as_a_model_named_None(self):
        self.assertEqual(MV._ellipsize(None, 62), "(no model recorded)")

    def test_reopening_is_idempotent(self):
        self._make_old_db()
        first = MemoryStore(self.path)
        n = len(first._conn().execute("PRAGMA table_info(session_index)").fetchall())
        for _ in range(2):
            store = MemoryStore(self.path)
        self.assertEqual(
            len(store._conn().execute("PRAGMA table_info(session_index)").fetchall()), n,
            "a reopen added columns")

    def test_a_fresh_store_and_a_migrated_one_have_the_same_column_order(self):
        """`model` is declared LAST in _SCHEMA precisely so ALTER TABLE (which
        can only append) produces the identical shape. `SELECT *` has to mean
        the same thing on both."""
        self._make_old_db()
        migrated = [r[1] for r in MemoryStore(self.path)._conn().execute(
            "PRAGMA table_info(session_index)").fetchall()]
        fresh_dir = tempfile.mkdtemp(prefix="a0e-fresh-")
        try:
            fresh = [r[1] for r in MemoryStore(str(Path(fresh_dir) / "c.db"))._conn().execute(
                "PRAGMA table_info(session_index)").fetchall()]
        finally:
            shutil.rmtree(fresh_dir, ignore_errors=True)
        self.assertEqual(migrated, fresh)


# ---------------------------------------------------------------------------
# (b) + (c) the heal
# ---------------------------------------------------------------------------
class TestHealCoversBothTables(_A0eCase):
    def test_counters_report_every_vector_table_by_name(self):
        by_table = self._heal()["by_table"]
        self.assertEqual(set(by_table), set(HealthEngine.VECTOR_TABLES))
        # Reported even at zero: a silent table and a clean table must not look
        # the same. That indistinguishability IS the A0e bug.
        for table, counts in by_table.items():
            self.assertIn("total", counts)
            self.assertIn("mismatched", counts)
            self.assertIn("wrong_dim", counts)
        self.assertEqual(by_table["session_index"]["total"], 1)
        self.assertEqual(by_table["projection_vectors"]["total"], 1)

    def test_the_zero_summary_reports_every_table_too(self):
        """The no-embedder early return has to carry the same shape, or a
        dashboard reading `by_table` sees a store with no vector tables at all
        exactly when the embedder is missing."""
        self.core.embedder = None
        by_table = self._heal()["by_table"]
        self.assertEqual(set(by_table), set(HealthEngine.VECTOR_TABLES))

    def test_a_wrong_width_session_vector_is_counted_and_requeued(self):
        self._set_session(embedding=pack([0.02] * 2048))
        summary = self._heal()
        self.assertGreaterEqual(summary["mismatched"], 1)
        self.assertGreaterEqual(summary["wrong_dim"], 1)
        self.assertEqual(summary["by_table"]["session_index"]["wrong_dim"], 1)
        self.assertGreaterEqual(summary["requeued"], 1)

    def test_a_renamed_session_vector_is_retagged_not_reembedded(self):
        before = self._session_row()["embedding"]
        self._set_session(model=GGUF_PATH + "[prefixed]")
        summary = self._heal()
        self.assertGreaterEqual(summary["retagged"], 1)
        self.assertEqual(self._tags("session_index"), [self.active])
        self.assertEqual(self._session_row()["embedding"], before,
                         "a rename must never cost an embed")

    def test_a_null_model_row_is_stale_exactly_once(self):
        """The legacy case. NULL means unknown, unknown means stale — and after
        one repair it is canonical, so the SECOND run finds nothing. A rule that
        healed it forever would be the pre-A0 60-rows-in-9-days drip again."""
        self._set_session(model=None)
        first = self._heal()
        self.assertEqual(first["by_table"]["session_index"]["mismatched"], 1)
        self.assertGreaterEqual(first["requeued"], 1)

        self.core.curation.drain()                 # the requeued embed job runs
        self.assertEqual(self._tags("session_index"), [self.active])

        second = self._heal()
        self.assertEqual(second["by_table"]["session_index"]["mismatched"], 0)
        self.assertEqual(second["requeued"], 0)

    def test_the_repair_never_rewrites_the_summary_owner_or_timestamp(self):
        before = self._session_row()
        self._set_session(model=None, embedding=pack([0.02] * 2048))
        self._heal()
        self.core.curation.drain()
        after = self._session_row()
        self.assertEqual(after["summary"], before["summary"])
        self.assertEqual(after["owner"], before["owner"])
        self.assertEqual(after["occurred_at"], before["occurred_at"])
        self.assertEqual(after["model"], self.active)
        self.assertEqual(len(after["embedding"]), DIMS * 4)

    def test_the_repair_re_embeds_the_summary_the_row_holds(self):
        """Not the job payload's copy of it: the row is the thing the vector has
        to mean, and a repair that vectorised anything else would be a
        right-geometry vector of the wrong text — the undetectable failure."""
        self._set_session(model=None, embedding=pack([0.02] * 2048))
        self._heal()
        self.core.curation.drain()
        row = self._session_row()
        # Compared PACKED: unpack widens float32 back to Python floats, so a
        # list comparison would fail on representation rather than content.
        self.assertEqual(row["embedding"], pack(self.emb.embed_document(row["summary"])))

    def test_a_session_row_with_no_summary_is_left_untouched(self):
        """`recoverable` False, the A0fix refusal contract: there is nothing
        honest to re-embed FROM, so the row keeps its (wrong) vector rather than
        being blanked or filled from a guess. It stays findable."""
        self._set_session(model=None, embedding=pack([0.02] * 2048))
        with self.store.transaction() as c:
            c.execute("UPDATE session_index SET summary=''")
        before = self._session_row()["embedding"]
        summary = self._heal()
        self.core.curation.drain()
        self.assertEqual(self._session_row()["embedding"], before)
        self.assertIsNone(self._session_row()["model"])
        self.assertGreaterEqual(summary["outstanding"], 1)

    def test_a_stale_projection_is_requeued_from_its_own_job_text(self):
        self._set_session(model=None)              # noise: both tables at once
        with self.store.transaction() as c:
            c.execute("UPDATE projection_vectors SET model=?", (OLD_MODEL,))
        summary = self._heal()
        self.assertEqual(summary["by_table"]["projection_vectors"]["mismatched"], 1)
        self.core.curation.drain()
        self.assertEqual(self._tags("projection_vectors"), [self.active])

    def test_a_projection_with_no_recoverable_text_is_left_alone(self):
        """The one channel whose source text the store does not hold (§g5a
        renders it from an external database). With the job gone there is
        nothing honest to re-embed FROM, so the row stays exactly as it is and
        stays counted as outstanding — findable, not silently rewritten."""
        key = "proj:acme_fake_people_db:person_1"
        before = self.store.get_projection_vectors_by_ids(
            [("acme_fake_people_db", "person_1")])[key]
        with self.store.transaction() as c:
            c.execute("DELETE FROM curation_jobs WHERE task='embed'")
            c.execute("UPDATE projection_vectors SET model=?", (OLD_MODEL,))
        summary = self._heal()
        self.assertEqual(summary["by_table"]["projection_vectors"]["mismatched"], 1)
        self.assertGreaterEqual(summary["outstanding"], 1)
        after = self.store.get_projection_vectors_by_ids(
            [("acme_fake_people_db", "person_1")])[key]
        self.assertEqual(after["embedding"], before["embedding"])
        self.assertEqual(self._tags("projection_vectors"), [OLD_MODEL])


# ---------------------------------------------------------------------------
# (d) the migration tool
# ---------------------------------------------------------------------------
class TestMigrationCoversBothTables(_A0eCase):
    """A synthetic store with MIXED session widths and tags, migrated by the
    same tool A0d built, against an offline embedder (no network)."""

    def setUp(self):
        super().setUp()
        # Three session rows: one already canonical (the fixture's), one
        # legacy-NULL at the WRONG width, one same-model-renamed at the right
        # width.
        self.store.add_session_vector("s2", "Pat Testley moved to Riverton",
                                      pack([0.02] * 2048), "default",
                                      "2026-01-01T00:00:00Z", model=None)
        self.store.add_session_vector("s3", "Acme Fake Co opened a Fake City office",
                                      pack(self.emb.embed_document("x")), "default",
                                      "2026-01-01T00:00:00Z", model=GGUF_PATH + "[prefixed]")
        self.db = self.store.db_path

    def _survey(self):
        return MV.survey(self.store._conn(), self.active, DIMS * 4)

    def _actions(self, table):
        return {(tag, blen): action for tag, blen, _cnt, action in self._survey()[table]}

    def _migrate(self, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            # An explicit Config, not None: `cfg=None` makes the tool read
            # $HERMES_HOME/config.yaml off the developer's machine, and the width
            # this fixture's 16-wide nomic-named embedder is allowed to answer with
            # must be stated by the test, not inherited from whatever is on disk.
            rc = MV.migrate(self.db, cfg=Config({"embeddings": {"dimensions": DIMS}}),
                            embedder=self.emb, verbose=True, **kw)
        return rc, buf.getvalue()

    def test_dry_run_classifies_every_table_and_changes_nothing(self):
        before = self.store._conn().execute(
            "SELECT session_id, model, length(embedding) FROM session_index "
            "ORDER BY session_id").fetchall()
        rc, out = self._migrate(dry_run=True)
        self.assertEqual(rc, 0)
        after = self.store._conn().execute(
            "SELECT session_id, model, length(embedding) FROM session_index "
            "ORDER BY session_id").fetchall()
        self.assertEqual([tuple(r) for r in before], [tuple(r) for r in after])

        actions = self._actions("session_index")
        self.assertEqual(actions[(self.active, DIMS * 4)], "ok")
        self.assertEqual(actions[(None, 2048 * 4)], "reembed")
        self.assertEqual(actions[(GGUF_PATH + "[prefixed]", DIMS * 4)], "retag")
        # Both new tables are surveyed at all — the thing A0 did not do — and
        # the REPORT names them, so an operator sees the work exists.
        self.assertIn("session_index", self._survey())
        self.assertIn("projection_vectors", self._survey())
        self.assertIn("session_index:", out)
        self.assertIn("projection_vectors:", out)
        self.assertIn("(no model recorded)", out)

    def test_a_real_run_converges_and_a_re_run_is_a_no_op(self):
        rc, _out = self._migrate()
        self.assertEqual(rc, 0, "first run did not converge")
        for table in HealthEngine.VECTOR_TABLES:
            for tag, blen, _cnt, action in self._survey()[table]:
                self.assertEqual(action, "ok",
                                 "%s left %r/%r as %s" % (table, tag, blen, action))
        self.assertEqual(self._tags("session_index"), [self.active])

        # A no-op means no WORK, not merely no change: a second run that
        # re-embedded everything to identical bytes would also leave the tags
        # right, and would be the pre-A0 drip wearing a clean face. Counted by
        # wrapping the embedder, so the claim is about calls, not outcomes.
        calls = {"n": 0}
        real_doc, real_batch = self.emb.embed_document, self.emb.embed_batch

        def counted_doc(text):
            calls["n"] += 1
            return real_doc(text)

        def counted_batch(texts, chunk=64):
            texts = list(texts)
            calls["n"] += len(texts)
            return real_batch(texts, chunk)

        self.emb.embed_document, self.emb.embed_batch = counted_doc, counted_batch
        try:
            rc2, out2 = self._migrate()
        finally:
            self.emb.embed_document, self.emb.embed_batch = real_doc, real_batch
        self.assertEqual(rc2, 0)
        self.assertEqual(calls["n"], 0, "the second run re-embedded %d row(s)" % calls["n"])
        self.assertEqual(self._tags("session_index"), [self.active])
        self.assertIn("nothing to do", out2)

    def test_the_converged_claim_names_both_new_tables(self):
        """The scope line is the tool's honesty contract. Bringing these two
        into `_TABLES` has to WIDEN it, not leave a claim that still names
        three tables over a five-table scan."""
        _rc, out = self._migrate()
        self.assertIn("converged: 100%% of vectors in %s" % ", ".join(MV._TABLES), out)
        self.assertIn("session_index", out)
        self.assertIn("projection_vectors", out)

    def test_a_null_model_row_is_actually_WALKED_not_just_counted(self):
        """The null-safety bug this had to keep fixed: SQLite's `!=` propagates
        NULL, so `model != 'tag'` is NULL — not TRUE — for a legacy row, and the
        walk would skip exactly the rows the survey kept reporting. The run
        would then exit non-zero forever with nothing to do."""
        m = MV.Migrator(self.store, self.emb, verbose=False)
        walked = [r[1] for batch in m._walk("session_index", ["session_id"]) for r in batch]
        self.assertIn("s2", walked, "the NULL-model row was never walked")

    def test_the_migration_re_embeds_the_stored_summary_not_a_guess(self):
        self._migrate()
        row = self.store.get_session_vector("s2")
        self.assertEqual(row["summary"], "Pat Testley moved to Riverton")
        self.assertEqual(row["embedding"],
                         pack(self.emb.embed_document("Pat Testley moved to Riverton")))

    def test_the_migration_never_rewrites_a_summary_owner_or_timestamp(self):
        before = {r[0]: tuple(r) for r in self.store._conn().execute(
            "SELECT session_id, summary, owner, occurred_at FROM session_index").fetchall()}
        self._migrate()
        after = {r[0]: tuple(r) for r in self.store._conn().execute(
            "SELECT session_id, summary, owner, occurred_at FROM session_index").fetchall()}
        self.assertEqual(before, after)

    def test_an_unrecoverable_projection_is_counted_failed_and_exits_two(self):
        """The A0fix refusal contract, reused rather than re-invented: the row
        is left untouched, counted as failed, and the run exits 2 so a re-run
        retries it. It is never blanked and never re-embedded from a guess."""
        with self.store.transaction() as c:
            c.execute("DELETE FROM curation_jobs WHERE task='embed'")
            c.execute("UPDATE projection_vectors SET model=?", (OLD_MODEL,))
        before = self.store._conn().execute(
            "SELECT embedding, model FROM projection_vectors").fetchone()
        rc, out = self._migrate()
        self.assertEqual(rc, 2)
        self.assertIn("proj:acme_fake_people_db:person_1", out)
        after = self.store._conn().execute(
            "SELECT embedding, model FROM projection_vectors").fetchone()
        self.assertEqual(tuple(before), tuple(after), "the unrepairable row was touched")

    def test_a_session_row_with_no_summary_is_counted_failed_not_blanked(self):
        with self.store.transaction() as c:
            c.execute("UPDATE session_index SET summary='' WHERE session_id='s2'")
        before = self.store.get_session_vector("s2")["embedding"]
        rc, out = self._migrate()
        self.assertEqual(rc, 2)
        self.assertIn("session:s2", out)
        self.assertEqual(self.store.get_session_vector("s2")["embedding"], before)


# ---------------------------------------------------------------------------
# (e) the read path — A0c's loud refusal must already cover both channels
# ---------------------------------------------------------------------------
class TestWrongWidthIsNeverSilent(_A0eCase):
    def setUp(self):
        super().setUp()
        E.reset_wrong_dim_skipped()

    def test_a_wrong_width_session_vector_is_counted_on_read(self):
        self._set_session(embedding=pack([0.02] * 2048))
        before = E.wrong_dim_skipped()
        self.core.retrieval.retrieve_raw("where does Pat Testley work", limit=5,
                                         principal="assistant")
        self.assertGreater(E.wrong_dim_skipped(), before,
                           "a wrong-width session vector scored silently")

    def test_the_query_reports_the_skip_by_channel_and_identity(self):
        """Not just a count: the per-query set is keyed (channel, id), so the
        session channel is nameable. `search()` never touches session_index --
        the session/projection scan lives in retrieve_raw -- so this asserts on
        the tier that actually reads the table."""
        self._set_session(embedding=pack([0.02] * 2048))
        self.core.retrieval.retrieve_raw("where does Pat Testley work", limit=5,
                                         principal="assistant")
        self.assertGreaterEqual(self.core.retrieval.last_wrong_dim_skipped(), 1)
        self.assertIn(("session", "s1"), self.core.retrieval._wrong_dim_seen)

    def test_a_correctly_sized_session_vector_reports_nothing(self):
        before = E.wrong_dim_skipped()
        self.core.retrieval.retrieve_raw("where does Pat Testley work", limit=5,
                                         principal="assistant")
        self.assertEqual(E.wrong_dim_skipped(), before)
        self.assertEqual(self.core.retrieval.last_wrong_dim_skipped(), 0)

    def test_a_wrong_width_projection_vector_is_counted_too(self):
        with self.store.transaction() as c:
            c.execute("UPDATE projection_vectors SET embedding=?", (pack([0.02] * 2048),))
        self.core.retrieval.retrieve_raw("Pat Testley engineer", limit=5,
                                         principal="assistant")
        self.assertIn(("projection", "person_1"), self.core.retrieval._wrong_dim_seen)


# ---------------------------------------------------------------------------
# (f) mutation guards
# ---------------------------------------------------------------------------
class TestCoverageCannotBeSilentlyRemoved(_A0eCase):
    """Removing a table from the shared scan set must FAIL a test. Without
    these, A0e could be reverted table-by-table and every other test in the tree
    would stay green — which is precisely how the gap survived A0."""

    def _heal_without(self, table):
        original = HealthEngine.VECTOR_TABLES
        HealthEngine.VECTOR_TABLES = tuple(t for t in original if t != table)
        try:
            return self._heal()
        finally:
            HealthEngine.VECTOR_TABLES = original

    def test_dropping_session_index_from_the_heal_is_detected(self):
        self._set_session(model=None, embedding=pack([0.02] * 2048))
        self.assertEqual(self._heal()["by_table"]["session_index"]["mismatched"], 1)
        mutated = self._heal_without("session_index")
        self.assertNotIn("session_index", mutated["by_table"],
                         "the mutation did not actually remove the table")
        self.assertEqual(mutated["mismatched"], 0,
                         "with session_index dropped the store reports CLEAN while holding a "
                         "wrong-width, unknown-model vector — the exact A0e condition")

    def test_dropping_projection_vectors_from_the_heal_is_detected(self):
        with self.store.transaction() as c:
            c.execute("UPDATE projection_vectors SET model=?", (OLD_MODEL,))
        self.assertEqual(self._heal()["by_table"]["projection_vectors"]["mismatched"], 1)
        mutated = self._heal_without("projection_vectors")
        self.assertEqual(mutated["mismatched"], 0)

    def test_dropping_a_table_from_the_migration_is_detected(self):
        self._set_session(model=None, embedding=pack([0.02] * 2048))
        original = MV._TABLES
        MV._TABLES = tuple(t for t in original if t != "session_index")
        try:
            plan = MV.survey(self.store._conn(), self.active, DIMS * 4)
            self.assertNotIn("session_index", plan)
            remaining = sum(c for table in MV._TABLES
                            for _t, _b, c, a in (plan.get(table) or []) if a != "ok")
            self.assertEqual(remaining, 0,
                             "with session_index dropped the migration reports a converged "
                             "store while a wrong-width row remains")
        finally:
            MV._TABLES = original

    def test_there_is_exactly_ONE_scan_set_and_all_consumers_bind_it(self):
        """One list, not three. A0e's gap was three hand-typed copies that each
        covered three of the five tables with nothing comparing them. Asserted
        by OBJECT IDENTITY, so a copy that happens to agree today still fails."""
        self.assertIs(HealthEngine.VECTOR_TABLES, E.VECTOR_TABLES)
        self.assertIs(MV._TABLES, E.VECTOR_TABLES)
        self.assertIs(RQ._VECTOR_TABLES, E.VECTOR_TABLES)
        self.assertIn("session_index", E.VECTOR_TABLES)
        self.assertIn("projection_vectors", E.VECTOR_TABLES)

    def test_the_scan_set_and_the_discovered_boundary_partition_the_store(self):
        """`unscanned_vector_tables` DISCOVERS what is outside; bringing a table
        into the scan set must remove it from that list automatically. If the
        boundary were hand-written, this is where the two would drift."""
        found = {t for t, _r, _w, _e in MV.unscanned_vector_tables(self.store._conn())}
        for t in E.VECTOR_TABLES:
            self.assertNotIn(t, found,
                             "%s is both scanned and reported as not-scanned" % t)


class TestEveryEmbeddingBearingTableIsAccountedFor(_A0eCase):
    """The enumeration guard. A SIXTH table that stores a vector must either
    join the shared scan set or be listed as a deliberate exemption here — it
    may not simply appear and be scanned by nothing, which is how session_index
    spent A0 invisible."""

    # entity_centroids.sum_vec is an accumulated SUM of mention vectors, not an
    # embedding of any recoverable text, so "re-embed" is undefined for it. It
    # needs no heal because it already refuses to mix geometries: it carries
    # both `model` (stamped through embedder_model_tag) and an explicit `dims`,
    # every comparison is filtered `model=? AND dims=?`, and the accumulator
    # RESETS when either changes. It is also projection state a rebuild
    # regenerates from the event log.
    EXEMPT = {("entity_centroids", "sum_vec")}

    def test_no_vector_table_is_scanned_by_nothing(self):
        conn = self.store._conn()
        found = set()
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            for r in conn.execute("PRAGMA table_info(%s)" % name).fetchall():
                col, decl = r[1], (r[2] or "").upper()
                if decl == "BLOB" and ("embed" in col.lower() or "vec" in col.lower()):
                    found.add((name, col))
        self.assertTrue(found, "the probe found no vector columns at all")
        covered = {(t, "embedding") for t in E.VECTOR_TABLES}
        uncovered = found - covered - self.EXEMPT
        self.assertEqual(uncovered, set(),
                         "embedding-bearing column(s) covered by neither the scan set nor a "
                         "documented exemption: %s" % sorted(uncovered))
        # And the exemptions are real, not stale entries for dropped tables.
        for table, col in self.EXEMPT:
            self.assertIn((table, col), found,
                          "%s.%s is exempted but does not exist" % (table, col))
        # Every scanned table really does hold an `embedding` column, so the
        # `covered` set above is not passing by accident.
        for table in E.VECTOR_TABLES:
            self.assertIn((table, "embedding"), found,
                          "%s is in the scan set but has no embedding column" % table)

    def test_the_exempt_centroid_table_carries_its_own_identity(self):
        """What LICENSES the exemption: model AND dims, both non-null, on a real
        centroid written by the ordinary fact path."""
        rows = self.store._conn().execute(
            "SELECT model, dims FROM entity_centroids").fetchall()
        self.assertTrue(rows, "fixture wrote no centroid; the exemption would be vacuous")
        for model, dims in rows:
            self.assertEqual(model, self.active)
            self.assertEqual(int(dims), DIMS)

    def test_the_exempt_table_is_still_reported_as_unscanned(self):
        """Exempt from repair is not exempt from being NAMED. An operator has to
        be able to see the boundary of what the tool did."""
        found = {t for t, _r, _w, _e in MV.unscanned_vector_tables(self.store._conn())}
        for table, _col in self.EXEMPT:
            self.assertIn(table, found)


# ---------------------------------------------------------------------------
# (g) the single text authority — A0fix's rule, extended to the new channels
# ---------------------------------------------------------------------------
class TestTextSourcesJoinTheOneAuthority(_A0eCase):
    def test_every_consumer_calls_the_same_function_objects(self):
        for mod in (H, MV):
            self.assertIs(mod.session_vector_text, R.session_vector_text,
                          "%s resolves session text through a different function"
                          % mod.__name__)
            self.assertIs(mod.projection_vector_text, R.projection_vector_text,
                          "%s resolves projection text through a different function"
                          % mod.__name__)

    def test_no_parallel_map_reappeared(self):
        """A0fix removed HealthEngine.BELIEF_TEXT because a second, hand-kept
        answer to "what text was this vector made of" had already drifted.
        Adding session/projection coverage must not smuggle one back in under a
        new name."""
        for name in ("BELIEF_TEXT", "SESSION_TEXT", "PROJECTION_TEXT", "VECTOR_TEXT"):
            self.assertFalse(hasattr(HealthEngine, name),
                             "HealthEngine.%s is a second text map" % name)
        for name in ("_BELIEF_TEXT", "_SESSION_TEXT", "_session_text",
                     "_projection_text", "_belief_text", "_observed_text"):
            self.assertFalse(hasattr(MV, name), "migrate_vectors.%s is a second text map" % name)

    def test_the_session_authority_returns_exactly_what_the_summarizer_embedded(self):
        row = self._session_row()
        text, recoverable = R.session_vector_text(self.store._conn(), "s1")
        self.assertTrue(recoverable)
        self.assertEqual(text, row["summary"])
        self.assertEqual(pack(self.emb.embed_document(text)), row["embedding"])

    def test_the_session_authority_refuses_a_row_it_cannot_reconstruct(self):
        conn = self.store._conn()
        self.assertEqual(R.session_vector_text(conn, "no-such-session"), ("", False))
        with self.store.transaction() as c:
            c.execute("UPDATE session_index SET summary=NULL")
        self.assertEqual(R.session_vector_text(conn, "s1"), ("", False))

    def test_the_projection_authority_returns_the_text_the_job_recorded(self):
        text, recoverable = R.projection_vector_text(
            self.store._conn(), "acme_fake_people_db", "person_1")
        self.assertTrue(recoverable)
        self.assertEqual(text, "Pat Testley, engineer at Acme Fake Co")

    def test_the_projection_authority_refuses_when_no_job_survives(self):
        with self.store.transaction() as c:
            c.execute("DELETE FROM curation_jobs WHERE task='embed'")
        self.assertEqual(
            R.projection_vector_text(self.store._conn(), "acme_fake_people_db", "person_1"),
            ("", False))

    def test_a_wildcard_shaped_external_id_does_not_match_a_different_job(self):
        """`instr`, not LIKE: `%` and `_` are legal in a provider/external id and
        LIKE would read them as wildcards, so one projection could recover
        ANOTHER's text and be re-embedded to mean something else."""
        self.store.enqueue_projection_embed("acme_fake_people_db", "a%b_c",
                                            "Acme Fake Co wildcard row", owner="default")
        self.core.curation.drain()
        conn = self.store._conn()
        self.assertEqual(R.projection_vector_text(conn, "acme_fake_people_db", "a%b_c")[0],
                         "Acme Fake Co wildcard row")
        # A pattern that LIKE would have matched must find nothing of its own.
        self.assertEqual(R.projection_vector_text(conn, "acme_fake_people_db", "axbyc"),
                         ("", False))


class TestRequeueHashVectorsNamesItsScope(_A0eCase):
    """The third copy of the table list lived here. Detection now covers every
    vector table; the tables this tool does not REWRITE are named in its report
    with the tool that does, rather than being silently absent."""

    def test_a_hash_tagged_session_row_is_found_and_named(self):
        with self.store.transaction() as c:
            c.execute("UPDATE session_index SET model='hashing'")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = RQ.requeue(self.store.db_path, dry_run=True)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("NOT rewritten here", out)
        self.assertIn("session_index", out)
        self.assertIn("migrate_vectors.py", out)

    def test_a_clean_store_says_nothing_about_unhandled_tables(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            RQ.requeue(self.store.db_path, dry_run=True)
        self.assertNotIn("NOT rewritten here", buf.getvalue())

    def test_the_tables_it_rewrites_are_a_subset_of_the_tables_it_scans(self):
        for t in RQ._REWRITTEN_TABLES:
            self.assertIn(t, RQ._VECTOR_TABLES)


# ---------------------------------------------------------------------------
# (h) real embedder
# ---------------------------------------------------------------------------
def _loopback_embedder():
    """A REAL embedder against loopback ollama, or None when it is not there."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            models = json.loads(r.read().decode()).get("models") or []
    except Exception:
        return None
    names = [m.get("name") or "" for m in models]
    pick = next((n for n in names if "embed" in n.lower()), None)
    if not pick:
        return None
    return E.get_embedder(pick, 768, "http://localhost:11434/v1", "", None, None, None, False)


# A11's hermetic harness: this case dials a real loopback embedding server in
# setUp, so even when it SKIPS it records a network attempt and fails the
# per-test guard. The marker is what the harness provides for exactly this --
# it is deselected before setUp runs unless CHRONICLE_TEST_LIVE_EMBEDDER=1, so
# the test still exists and still runs where a server exists.
@pytest.mark.live_embedder
class TestRealEmbedderStampsTheCanonicalTag(unittest.TestCase):
    def setUp(self):
        self.emb = _loopback_embedder()
        if self.emb is None or not getattr(self.emb, "dimensions", 0):
            self.skipTest("no loopback embedding endpoint at http://localhost:11434")
        # A DegradedEmbedder also answers `dimensions`, and a silently-degraded
        # run would assert nothing about a REAL model. Prove the endpoint really
        # embeds before claiming this test exercised one.
        try:
            probe = self.emb.embed_document("Pat Testley")
        except Exception as e:
            self.skipTest("loopback endpoint did not embed: %s" % e)
        if len(probe) != int(self.emb.dimensions):
            self.skipTest("loopback endpoint returned %d dims, expected %d"
                          % (len(probe), self.emb.dimensions))
        self.home = tempfile.mkdtemp(prefix="a0e_real_")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_a_session_write_carries_the_canonical_tag_and_the_right_width(self):
        core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        core.embedder = self.emb
        core.reducer.embedder = self.emb
        core.initialize("s-real", principal_id="assistant")
        core.capture.observe("I am Pat Testley and I work at Acme Fake Co", "",
                             session_id="s-real")
        core.process_pending()
        core.store.enqueue_curation("session_summarize", {"session_id": "s-real"})
        core.curation.drain()

        row = core.store.get_session_vector("s-real")
        self.assertIsNotNone(row, "the summarizer wrote no session row")
        active = embedder_model_tag(self.emb)
        # The canonical tag, not the raw ollama ":latest" name the server reports.
        self.assertEqual(row["model"], active)
        self.assertNotIn(":latest", row["model"])
        self.assertEqual(len(row["embedding"]), int(self.emb.dimensions) * 4)
        # ...and the bytes came from the SERVER, not a fallback. Compared PACKED:
        # unpacking widens float32 back to Python floats, so a list comparison
        # would fail on representation rather than on content.
        self.assertEqual(row["embedding"], pack(self.emb.embed_document(row["summary"])))
        self.assertIn(":latest", str(self.emb.model))
        # And a heal over a REAL geometry finds nothing to do.
        summary = core.health._embedder_mismatch_heal()["embedder_mismatch"]
        self.assertEqual(summary["by_table"]["session_index"]["mismatched"], 0)


if __name__ == "__main__":
    unittest.main()
