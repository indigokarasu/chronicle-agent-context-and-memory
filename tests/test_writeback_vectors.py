"""
Chronicle — acceptance tests for scripts/writeback_vectors.py (A0 chain review
Step 8.3, W1-W8).

The migration runs on a COPY, on a fast host. This tool is the last step: it
carries the recomputed vectors back into the LIVE store while the gateway keeps
serving and writing. It is the only piece of the chain that writes to
production, so every test below is written as "what would a wrong write look
like, and does the tool refuse it".

  W1  the row deleted on live after the snapshot STAYS DELETED (a resurrection
      test, plus a source-level assertion that this module contains no INSERT);
  W2  compare-and-swap on the snapshot pre-image: a row the live path rewrote
      is skipped, not overwritten;
  W3  the reducer-authority text recomputed ON LIVE must still hash to the text
      the copy embedded; an edited belief and a grown session summary are
      skipped;
  W4  a pending or claimed `embed` job for the target skips the row — without
      this the write-back turns that job into a permanent no-op, because
      curation._task_embed's "already current" test is tag+width only;
  W5  a copy migrated onto a different width or tag REFUSES the whole run and
      writes nothing;
  W6  a row whose authority text is over the 8000-char job-payload clamp takes
      the at-risk path: W2 is bypassed, W1/W3/W4/W5 are not;
  W7  rows the migration did not change are never written;
  W8  batches are capped at 500, busy_timeout is >= 5s, the run is resumable
      from a persisted cursor, and the report names every bucket.

Plus: the manifest is a HARD requirement (no manifest, or a manifest built from
a different copy, is exit 1 with nothing written); --dry-run opens live
read-only and leaves db+wal+shm byte-identical; and the tool writes `embedding`
and `model` only, never a summary, owner or created_at.

Fixtures use only fake values (Pat Testley, Acme Fake Co) and an offline
hashing-backed embedder — no network, no paid API.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.migrate_vectors as MV
import scripts.writeback_vectors as WB
from engine import reducer as R
from engine.config import Config
from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder, embedder_model_tag, pack
from engine.store import MemoryStore

DIMS = 16
WIDTH = DIMS * 4
OLD_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
CANON = "nomic-embed-text[prefixed]"
LONG_BODY = "Pat Testley's runbook. " * 400          # 9,200 chars > the 8000 clamp


class _NomicLike:
    """Hashing-backed, nomic-NAMED embedder: the real E1 prefix + marker
    contract, deterministic offline vectors, no network. The same stand-in the
    A0b/A0e suites use, so no two suites can disagree about "the active tag"."""

    def __init__(self, model="nomic-embed-text", dimensions=DIMS):
        self.model = model
        self.dimensions = dimensions
        self._h = HashingEmbedder(dimensions=dimensions, model=model)

    def _doc(self, text):
        return self._h.embed("search_document: " + (text or ""))

    def embed(self, text):
        return self._h.embed(text)

    def embed_document(self, document):
        return self._doc(document)

    def embed_query(self, query):
        return self._h.embed("search_query: " + (query or ""))

    def embed_batch(self, texts, chunk=64):
        return [self._doc(t) for t in texts]

    def model_with_prefix_marker(self):
        return self.model + "[prefixed]"


def _sha(b):
    return None if b is None else hashlib.sha256(bytes(b)).hexdigest()


def _file_sha(path):
    """db + wal + shm, presence included — the p5 shape, so "wrote nothing"
    covers the journal files too and not just the main database."""
    h = hashlib.sha256()
    for ext in ("", "-wal", "-shm"):
        p = str(path) + ext
        if os.path.exists(p):
            h.update(ext.encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


class _WBCase(unittest.TestCase):
    """live store -> snapshot -> manifest -> migrate the copy -> write back."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="wb_")
        core = ChronicleCore(self.home, {"embeddings": {"model": "hashing",
                                                        "dimensions": DIMS}})
        core.initialize("s1", principal_id="assistant")
        core.capture.observe(
            "I am Pat Testley\n"
            "I work at Acme Fake Co\n"
            "I live in Springfield\n"
            "My manager is Dana Fictional", "", session_id="s1")
        core.capture.observe("I moved to Riverton\nI still work at Acme Fake Co",
                             "", session_id="s1")
        core.process_pending()
        core.curation.drain()
        store = core.store
        self.live = store.db_path
        # session_index + projection_vectors, so all five tables are exercised.
        store.add_session_vector("s1", "Pat Testley talked about Acme Fake Co.",
                                 pack([0.1] * DIMS), "default",
                                 "2026-09-01T00:00:00Z", model="hashing")
        store.enqueue_projection_embed("acme", "proj-1",
                                       "Acme Fake Co quarterly note", owner="default")
        store.add_projection_vector("acme", "proj-1", pack([0.2] * DIMS), "hashing",
                                    "default")
        # The projection's embed job has to SURVIVE (it is the only record of
        # what that vector means — reducer.projection_vector_text reads it) but
        # it must not be pending, or W4 would legitimately skip the row in every
        # test below. Drained, as it would be on a live store.
        with store.transaction() as conn:
            conn.execute("UPDATE curation_jobs SET status='done' WHERE task='embed'")
        # An N1 at-risk belief: a note whose body is over the 8000-char clamp
        # store.enqueue_embed_job applies. Inserted directly so the fixture pins
        # the LENGTH, which is the only property W6 turns on.
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO notes(belief_id, note_type, subject, body, owner) "
                "VALUES(?,?,?,?,?)", ("b_long", "belief", "runbook", LONG_BODY, "default"))
            conn.execute(
                "INSERT INTO memory_vectors(belief_id, kind, embedding, model, created_at) "
                "VALUES(?,?,?,?,?)",
                ("b_long", "note", pack([0.3] * DIMS), "hashing", "2026-09-01T00:00:00Z"))
        # Every vector is now in the ABANDONED geometry, which is the live
        # store's actual condition: 88% wrong-model, wrong-width.
        with store.transaction() as conn:
            for t in WB._TABLES:
                conn.execute("UPDATE %s SET model=?, embedding=?"
                             % t, (OLD_MODEL, pack([0.03] * (DIMS * 2))))
        core.close()

        # --- step 1: the snapshot (online backup API, as 8.6 step 1 requires)
        self.copy = os.path.join(self.home, "copy.db")
        src = sqlite3.connect(self.live)
        dst = sqlite3.connect(self.copy)
        src.backup(dst)
        dst.close()
        src.close()
        # --- step 2: the manifest, from the PRISTINE copy
        self.manifest = os.path.join(self.home, "snapshot.jsonl")
        WB.build_manifest(self.copy, self.manifest, live_db=self.live, verbose=False)
        # --- step 3: migrate the copy
        self.emb = _NomicLike()
        self.assertEqual(embedder_model_tag(self.emb), CANON)
        rc = MV.migrate(self.copy, cfg=Config({"embeddings": {"model": "hashing",
                                                              "dimensions": DIMS}}),
                        embedder=self.emb, verbose=False)
        self.assertIn(rc, (0, 2), "migration of the copy did not run")
        self.state = os.path.join(self.home, "wb.state.json")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def _run(self, **kw):
        kw.setdefault("manifest_path", self.manifest)
        kw.setdefault("state_path", self.state)
        kw.setdefault("expect_tag", CANON)
        kw.setdefault("expect_width", WIDTH)
        kw.setdefault("verbose", False)
        return WB.writeback(self.live, self.copy, **kw)

    def _run_counts(self, **kw):
        """rc plus the counters, by running the WriteBack object directly so a
        test can assert on the buckets rather than on printed text."""
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self._run(**kw)
        out = buf.getvalue()
        counts = {}
        for line in out.splitlines():
            for bucket in ("applied", "skipped-changed", "skipped-text", "skipped-job",
                           "skipped-missing", "refused"):
                if line.startswith(bucket):
                    try:
                        counts[bucket] = int(line.split(":", 1)[1].strip().split()[0])
                    except (IndexError, ValueError):
                        pass
        return rc, counts, out

    def _live(self):
        c = sqlite3.connect(self.live)
        c.row_factory = sqlite3.Row
        return c

    def _row(self, conn, table, key):
        where = " AND ".join("%s=?" % k for k in WB._KEYS[table])
        return conn.execute('SELECT * FROM "%s" WHERE %s' % (table, where), key).fetchone()

    def _copy_vec(self, table, key):
        c = sqlite3.connect(self.copy)
        where = " AND ".join("%s=?" % k for k in WB._KEYS[table])
        row = c.execute('SELECT model, embedding FROM "%s" WHERE %s' % (table, where),
                        key).fetchone()
        c.close()
        return row

    def _any_memory_key(self, exclude=("b_long",)):
        c = self._live()
        row = c.execute("SELECT belief_id, kind FROM memory_vectors "
                        "WHERE belief_id NOT IN (%s) AND kind='fact' LIMIT 1"
                        % ",".join("?" * len(exclude)), exclude).fetchone()
        c.close()
        self.assertIsNotNone(row, "fixture has no plain fact vector")
        return (row[0], row[1])


# ==========================================================================
# the happy path, and what it is allowed to touch
# ==========================================================================
class TestAppliesTheMigratedVectors(_WBCase):
    def test_applies_and_touches_only_embedding_and_model(self):
        c = self._live()
        before = {t: [tuple(r) for r in c.execute(
            'SELECT * FROM "%s" ORDER BY rowid' % t).fetchall()] for t in WB._TABLES}
        sess_before = dict(self._row(c, "session_index", ("s1",)))
        c.close()

        rc, counts, out = self._run_counts()
        self.assertIn(rc, (0, 2), out)
        self.assertGreater(counts.get("applied", 0), 0, out)

        c = self._live()
        after = {t: [tuple(r) for r in c.execute(
            'SELECT * FROM "%s" ORDER BY rowid' % t).fetchall()] for t in WB._TABLES}
        # every applied row now carries the copy's vector, byte-for-byte
        for t in WB._TABLES:
            self.assertEqual(len(before[t]), len(after[t]), "%s changed row count" % t)
        for t in WB._TABLES:
            keys = WB._KEYS[t]
            for r in c.execute('SELECT %s, model, embedding FROM "%s"'
                               % (", ".join(keys), t)).fetchall():
                key = tuple(r[:len(keys)])
                live_model, live_blob = r[len(keys)], r[len(keys) + 1]
                cm, cb = self._copy_vec(t, key)
                if cm == CANON:
                    self.assertEqual(live_model, CANON, "%s %r not stamped" % (t, key))
                    self.assertEqual(_sha(live_blob), _sha(cb),
                                     "%s %r: live blob != copy blob" % (t, key))
        # …and NOTHING else moved: the summary, owner and occurred_at of the
        # session row are identical.
        sess_after = dict(self._row(c, "session_index", ("s1",)))
        c.close()
        for col in ("summary", "owner", "occurred_at"):
            self.assertEqual(sess_before[col], sess_after[col],
                             "write-back rewrote session_index.%s" % col)

    def test_second_run_is_a_noop(self):
        rc1, c1, _ = self._run_counts()
        applied = c1.get("applied", 0)
        self.assertGreater(applied, 0)
        rc2, c2, out2 = self._run_counts()
        self.assertEqual(c2.get("applied", 0), 0,
                         "a second pass re-applied rows it already wrote:\n" + out2)
        self.assertEqual(c2.get("skipped-changed", 0), 0,
                         "resumed run reported its own writes as conflicts:\n" + out2)


# ==========================================================================
# W1 — the resurrection test
# ==========================================================================
class TestTheAnnMirrorKeepsCorrectedRowsVisible(_WBCase):
    """A corrected row must be UPSERTED into the vec0 ANN mirror, never deleted.

    `MemoryStore.add_observed_vector` writes `observed_vectors` and its vec0
    mirror in ONE transaction; this tool writes raw SQL, so it keeps the mirror
    in step itself. The obvious move -- delete the stale mirror entry -- is wrong:
    `retrieve_raw` takes a nonempty KNN result INSTEAD of the paged scan, so a
    row missing from a partly-filled mirror is never a vector candidate unless
    full-text search finds it. Deleting would turn "ranked on a stale embedding"
    into "not found". An earlier revision of this tool did exactly that; this
    class exists so it cannot come back.

    Asserted as a contract on the call rather than on vec0: sqlite-vec cannot load
    under Apple's system Python, so a test needing a real vec0 would SKIP on the
    machine this suite is gated on.
    """

    def _observed(self):
        c = self._live()
        rows = {r[0]: r[1] for r in c.execute(
            'SELECT event_id, embedding FROM observed_vectors').fetchall()}
        c.close()
        return rows

    def test_every_corrected_observed_row_is_upserted_with_its_new_blob(self):
        before = self._observed()
        calls = []
        real = WB._vec0_upsert

        def spy(conn, event_id, embedding):
            calls.append((event_id, bytes(embedding)))
            return real(conn, event_id, embedding)

        with mock.patch.object(WB, "_vec0_upsert", spy):
            rc, counts, out = self._run_counts()
        self.assertIn(rc, (0, 2), out)
        self.assertGreater(counts.get("applied", 0), 0, out)

        after = self._observed()
        changed = {k for k, v in after.items() if before.get(k) != v}
        self.assertTrue(changed, "no observed_vectors row changed; nothing to assert about")
        self.assertEqual({eid for eid, _ in calls}, changed,
                         "the mirror must be told about exactly the corrected rows")
        self.assertEqual(len(calls), len(changed), "one mirror write per corrected row")
        for eid, blob in calls:
            self.assertEqual(blob, bytes(after[eid]),
                             "the mirror must receive the CORRECTED blob for %s, or it keeps "
                             "serving the pre-image" % eid)

    def test_refuses_and_writes_nothing_when_the_mirror_cannot_be_kept_in_step(self):
        """A vec0 mirror this Python cannot load sqlite-vec for must STOP the run.

        Warning and carrying on (an earlier revision) changed observed_vectors
        while upsert_observed() quietly returned 0, leaving the pre-image in a
        mirror that an extension-capable process trusts over the table. Refused
        before WriteBack is built, so the store is untouched; dry-run too."""
        before = self._observed()
        for dry in (False, True):
            with mock.patch.object(WB, "_vec0_unmaintainable", lambda conn: True):
                rc, counts, out = self._run_counts(dry_run=dry)
            self.assertEqual(rc, 1, "dry_run=%s did not refuse:\n%s" % (dry, out))
            self.assertIn("REFUSED", out)
            self.assertIn("Nothing was written to the live store.", out)
            self.assertEqual(self._observed(), before,
                             "a REFUSED run (dry_run=%s) still changed observed_vectors" % dry)

    def test_the_tool_never_deletes_from_the_mirror(self):
        self.assertFalse(hasattr(WB, "_vec0_delete"),
                         "writeback_vectors imports a vec0 DELETE again. A corrected row that "
                         "still exists must be upserted: a row missing from the mirror is "
                         "invisible to vector search, not merely slower")


class TestW1NeverResurrects(_WBCase):
    def test_row_deleted_on_live_stays_deleted(self):
        key = self._any_memory_key()
        c = self._live()
        c.execute("DELETE FROM memory_vectors WHERE belief_id=? AND kind=?", key)
        c.commit()
        n_before = c.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0]
        c.close()

        rc, counts, out = self._run_counts()
        c = self._live()
        self.assertIsNone(self._row(c, "memory_vectors", key),
                          "the write-back RESURRECTED a row deleted on live — an "
                          "INSERT OR REPLACE would do exactly this, and forgotten "
                          "content would come back")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()[0],
                         n_before, "row count grew: the write-back inserted")
        c.close()
        self.assertGreaterEqual(counts.get("skipped-missing", 0), 1, out)
        self.assertEqual(rc, 2, "a run with skips must not report success")

    def test_observed_row_deleted_stays_deleted(self):
        c = self._live()
        row = c.execute("SELECT event_id FROM observed_vectors LIMIT 1").fetchone()
        eid = row[0]
        c.execute("DELETE FROM observed_vectors WHERE event_id=?", (eid,))
        c.commit()
        c.close()
        self._run_counts()
        c = self._live()
        self.assertIsNone(self._row(c, "observed_vectors", (eid,)))
        c.close()

    def test_module_contains_no_insert(self):
        """A source-level guard, because W1 is a property of the SQL this module
        is allowed to contain. `INSERT OR REPLACE` is one keystroke away from
        `UPDATE`, and on a store where nothing happened to be deleted it would
        pass every behavioural test above.

        Every string literal that is not a docstring is checked, which is where
        SQL lives; prose about W1 in the docstrings is not mistaken for code."""
        import ast
        src = Path(WB.__file__).read_text()
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                body = getattr(node, "body", None) or []
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
        checked = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docstrings:
                checked += 1
                up = node.value.upper()
                for banned in ("INSERT ", "REPLACE INTO", "DELETE FROM", "DROP ",
                               "ALTER TABLE"):
                    self.assertNotIn(
                        banned, up,
                        "writeback_vectors.py builds SQL containing %r (%r). W1 "
                        "allows UPDATE on the natural key and nothing else."
                        % (banned, node.value[:80]))
        self.assertGreater(checked, 20, "the guard inspected almost nothing")


# ==========================================================================
# W2 — compare-and-swap
# ==========================================================================
class TestW2CompareAndSwap(_WBCase):
    def test_live_row_changed_since_snapshot_is_skipped(self):
        key = self._any_memory_key()
        fresh = pack([0.77] * DIMS)
        c = self._live()
        c.execute("UPDATE memory_vectors SET embedding=?, model=? "
                  "WHERE belief_id=? AND kind=?", (fresh, CANON) + key)
        c.commit()
        c.close()

        rc, counts, out = self._run_counts()
        c = self._live()
        row = self._row(c, "memory_vectors", key)
        c.close()
        self.assertEqual(_sha(row["embedding"]), _sha(fresh),
                         "the write-back overwrote a row the LIVE path had "
                         "rewritten since the snapshot")
        self.assertGreaterEqual(counts.get("skipped-changed", 0), 1, out)
        self.assertEqual(rc, 2)

    def test_model_only_change_is_still_a_conflict(self):
        """The CAS is on (model, sha256(embedding)) — both halves. A row whose
        tag moved but whose bytes did not is still a row the live path owns."""
        key = self._any_memory_key()
        c = self._live()
        c.execute("UPDATE memory_vectors SET model=? WHERE belief_id=? AND kind=?",
                  ("some-other-model[prefixed]",) + key)
        c.commit()
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        row = self._row(c, "memory_vectors", key)
        c.close()
        self.assertEqual(row["model"], "some-other-model[prefixed]", out)
        self.assertGreaterEqual(counts.get("skipped-changed", 0), 1, out)

    def test_missing_manifest_is_a_hard_refusal(self):
        rc = self._run(manifest_path=None)
        self.assertEqual(rc, 1, "a run with no pre-image must REFUSE, not skip W2")
        c = self._live()
        n = c.execute("SELECT COUNT(*) FROM memory_vectors WHERE model=?",
                      (CANON,)).fetchone()[0]
        c.close()
        self.assertEqual(n, 0, "rows were written without a manifest")

    def test_manifest_from_a_different_copy_is_refused(self):
        other = os.path.join(self.home, "other.jsonl")
        lines = open(self.manifest).read().splitlines()
        header = json.loads(lines[0])
        header["row_counts"] = dict((k, v + 1) for k, v in header["row_counts"].items())
        with open(other, "w") as fh:
            fh.write(json.dumps(header) + "\n")
            fh.write("\n".join(lines[1:]) + "\n")
        rc = self._run(manifest_path=other, state_path=self.state + ".2")
        self.assertEqual(rc, 1)
        c = self._live()
        n = c.execute("SELECT COUNT(*) FROM memory_vectors WHERE model=?",
                      (CANON,)).fetchone()[0]
        c.close()
        self.assertEqual(n, 0)

    def test_manifest_with_a_gap_is_refused(self):
        """A copy row with no manifest entry is not a row to skip — it is proof
        the manifest is not this copy's, and W2 cannot be evaluated for ANY of
        them on that evidence."""
        gapped = os.path.join(self.home, "gapped.jsonl")
        lines = open(self.manifest).read().splitlines()
        keep = [lines[0]] + [line for line in lines[1:]
                             if json.loads(line)["t"] != "memory_vectors"
                             or json.loads(line)["k"][0] != "b_long"]
        open(gapped, "w").write("\n".join(keep) + "\n")
        rc = self._run(manifest_path=gapped, state_path=self.state + ".3")
        self.assertEqual(rc, 1)


# ==========================================================================
# W3 — the source text
# ==========================================================================
class TestW3SourceTextUnchanged(_WBCase):
    def test_edited_belief_is_skipped(self):
        key = self._any_memory_key()
        c = self._live()
        c.execute("UPDATE facts SET value=? WHERE belief_id=?",
                  ("Riverton, actually", key[0]))
        c.commit()
        before = _sha(self._row(c, "memory_vectors", key)["embedding"])
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        after = _sha(self._row(c, "memory_vectors", key)["embedding"])
        c.close()
        self.assertEqual(before, after,
                         "a belief whose TEXT changed on live got the copy's vector "
                         "for the OLD text")
        self.assertGreaterEqual(counts.get("skipped-text", 0), 1, out)

    def test_growing_session_summary_is_skipped(self):
        """The legitimate case named in the review: an ACTIVE session's summary
        keeps growing, so its live text stops matching the snapshot's."""
        c = self._live()
        c.execute("UPDATE session_index SET summary=? WHERE session_id=?",
                  ("Pat Testley talked about Acme Fake Co. Then about Riverton.", "s1"))
        c.commit()
        before = _sha(self._row(c, "session_index", ("s1",))["embedding"])
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        after = _sha(self._row(c, "session_index", ("s1",))["embedding"])
        c.close()
        self.assertEqual(before, after, out)
        self.assertGreaterEqual(counts.get("skipped-text", 0), 1, out)

    def test_text_authority_is_the_reducer_not_a_local_map(self):
        """The A0fix rule: ONE answer to "what text was this vector made of".
        A parallel kind->column map here would re-create the procedure
        truncation in a new file."""
        src = Path(WB.__file__).read_text()
        self.assertIs(WB.belief_vector_text, R.belief_vector_text)
        self.assertIs(WB.observed_vector_text, R.observed_vector_text)
        self.assertIs(WB.session_vector_text, R.session_vector_text)
        self.assertIs(WB.projection_vector_text, R.projection_vector_text)
        self.assertNotIn("BELIEF_VECTOR_SOURCE", src,
                         "a second kind->column map appeared in the write-back")
        self.assertIs(MV.belief_vector_text, WB.belief_vector_text,
                      "migrate and write-back resolve belief text differently")

    def test_authority_accessors_are_actually_called(self):
        """Importing the reducer's accessors is not the same as USING them.

        The defect this kills: a local kind->column map inlined in
        `_authority_text` while the imports stay untouched — which is exactly
        the shape A0fix removed (`procedure` -> `procedures.name`, a 40-char
        truncation, re-embedded and stamped canonical). Each accessor is
        replaced by a spy and every table is resolved through it."""
        calls = []

        def spy(name, real):
            def f(*a, **kw):
                calls.append((name, a[1:]))
                return real(*a, **kw)
            return f

        originals = {}
        for name in ("belief_vector_text", "observed_vector_text",
                     "session_vector_text", "projection_vector_text"):
            originals[name] = getattr(WB, name)
            setattr(WB, name, spy(name, originals[name]))
        try:
            conn = sqlite3.connect(self.live)
            WB._authority_text(conn, "memory_vectors", ("b_long", "note"))
            WB._authority_text(conn, "observed_vectors", ("ev-x",))
            WB._authority_text(conn, "session_index", ("s1",))
            WB._authority_text(conn, "projection_vectors", ("acme", "proj-1"))
            text, ok = WB._authority_text(conn, "memory_vectors", ("b_long", "note"))
            conn.close()
        finally:
            for name, fn in originals.items():
                setattr(WB, name, fn)
        got = [c[0] for c in calls]
        for name in originals:
            self.assertIn(name, got,
                          "_authority_text resolved a table WITHOUT reducer.%s — a "
                          "second answer to 'what text was this vector made of' has "
                          "appeared" % name)
        self.assertEqual(text, LONG_BODY,
                         "the belief's authority text is not its body")
        self.assertTrue(ok)


# ==========================================================================
# W4 — the queued embed job
# ==========================================================================
class TestW4QueuedJob(_WBCase):
    def _queue(self, target, kind, text, status="pending"):
        c = self._live()
        payload = json.dumps({"target_id": target, "kind": kind, "text": text},
                             sort_keys=True)
        c.execute("INSERT INTO curation_jobs(task,payload,status,created_at) "
                  "VALUES('embed',?,?,?)", (payload, status, "2026-09-02T00:00:00Z"))
        c.commit()
        c.close()

    def test_pending_job_skips_the_row(self):
        key = self._any_memory_key()
        self._queue(key[0], key[1], "whatever the reducer queued")
        c = self._live()
        before = _sha(self._row(c, "memory_vectors", key)["embedding"])
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        row = self._row(c, "memory_vectors", key)
        c.close()
        self.assertEqual(_sha(row["embedding"]), before,
                         "stamped canonical+width over a row with a QUEUED re-embed: "
                         "curation._task_embed's already-current test is tag+width "
                         "only, so that job is now a permanent no-op")
        self.assertNotEqual(row["model"], CANON)
        self.assertGreaterEqual(counts.get("skipped-job", 0), 1, out)

    def test_claimed_running_job_also_skips(self):
        key = self._any_memory_key()
        self._queue(key[0], key[1], "claimed by a worker", status="running")
        rc, counts, out = self._run_counts()
        self.assertGreaterEqual(counts.get("skipped-job", 0), 1, out)

    def test_done_job_does_not_skip(self):
        """Only pending/claimed work can be nullified. A finished job is history."""
        key = self._any_memory_key()
        self._queue(key[0], key[1], "already drained", status="done")
        rc, counts, out = self._run_counts()
        c = self._live()
        row = self._row(c, "memory_vectors", key)
        c.close()
        self.assertEqual(row["model"], CANON,
                         "a DONE job blocked a write it has no claim on:\n" + out)

    def test_projection_job_needle_is_the_namespaced_target(self):
        self._queue("proj:acme:proj-1", "projection", "Acme Fake Co quarterly note")
        rc, counts, out = self._run_counts()
        c = self._live()
        row = self._row(c, "projection_vectors", ("acme", "proj-1"))
        c.close()
        self.assertNotEqual(row["model"], CANON,
                            "the projection's queued job did not protect its row:\n" + out)


# ==========================================================================
# W5 — geometry
# ==========================================================================
class TestW5Geometry(_WBCase):
    def test_wrong_width_refuses_the_whole_run(self):
        rc = self._run(expect_width=WIDTH * 2)
        self.assertEqual(rc, 1, "a copy of the wrong width must REFUSE")
        c = self._live()
        n = c.execute("SELECT COUNT(*) FROM memory_vectors WHERE model=?",
                      (CANON,)).fetchone()[0]
        c.close()
        self.assertEqual(n, 0, "rows were written at a width live does not serve")

    def test_wrong_tag_refuses_the_whole_run(self):
        rc = self._run(expect_tag="nomic-embed-text-v9[prefixed]")
        self.assertEqual(rc, 1)
        c = self._live()
        n = c.execute("SELECT COUNT(*) FROM memory_vectors WHERE model=?",
                      (CANON,)).fetchone()[0]
        c.close()
        self.assertEqual(n, 0)

    def test_non_geometry_tag_refuses(self):
        for tag in ("degraded", "auto", ""):
            rc = self._run(expect_tag=tag)
            self.assertEqual(rc, 1, "tag %r was accepted as a geometry" % tag)

    def test_null_embedding_on_the_copy_is_refused_per_row(self):
        """The migration's retag pass legitimately rewrites `model` on a row
        whose embedding IS NULL. Carrying that back would BLANK a live vector to
        gain a tag, so the row is refused — and the rest of the run continues."""
        c = sqlite3.connect(self.copy)
        c.execute("UPDATE query_proxy_vectors SET embedding=NULL, model=? "
                  "WHERE rowid=(SELECT MIN(rowid) FROM query_proxy_vectors)", (CANON,))
        c.commit()
        c.close()
        rc, counts, out = self._run_counts()
        self.assertGreaterEqual(counts.get("refused", 0), 1, out)
        c = self._live()
        nulls = c.execute("SELECT COUNT(*) FROM query_proxy_vectors "
                          "WHERE embedding IS NULL").fetchone()[0]
        c.close()
        self.assertEqual(nulls, 0, "a live vector was blanked")


# ==========================================================================
# W6 — the N1 at-risk exception
# ==========================================================================
class TestW6AtRiskBypassesCAS(_WBCase):
    def test_long_text_row_is_written_even_though_live_re_embedded_it(self):
        """The N1 window. A live heal re-embeds the row from text[:8000] and
        stamps it canonical+width; the tag+width "already current" test then
        makes that truncation permanent. W6 says: for a row whose text is over
        the clamp and UNCHANGED, overwrite anyway."""
        key = ("b_long", "note")
        healed = pack([0.55] * DIMS)          # what the truncating heal would write
        c = self._live()
        c.execute("UPDATE memory_vectors SET embedding=?, model=? "
                  "WHERE belief_id=? AND kind=?", (healed, CANON) + key)
        c.commit()
        c.close()
        rc, counts, out = self._run_counts()
        cm, cb = self._copy_vec("memory_vectors", key)
        self.assertEqual(cm, CANON)
        c = self._live()
        row = self._row(c, "memory_vectors", key)
        c.close()
        self.assertEqual(_sha(row["embedding"]), _sha(cb),
                         "the at-risk row was NOT overwritten: without W6 the "
                         "truncating heal's vector is permanent\n" + out)
        self.assertGreaterEqual(counts.get("applied", 0), 1, out)
        self.assertIn("at-risk", out)

    def test_at_risk_row_still_obeys_w3(self):
        """W6 bypasses W2 ONLY. An at-risk row whose TEXT changed is still a row
        the live path owns."""
        c = self._live()
        c.execute("UPDATE notes SET body=? WHERE belief_id=?",
                  (LONG_BODY + " and one more line", "b_long"))
        c.commit()
        before = _sha(self._row(c, "memory_vectors", ("b_long", "note"))["embedding"])
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        after = _sha(self._row(c, "memory_vectors", ("b_long", "note"))["embedding"])
        c.close()
        self.assertEqual(before, after, out)
        self.assertGreaterEqual(counts.get("skipped-text", 0), 1, out)

    def test_at_risk_row_still_obeys_w4(self):
        c = self._live()
        c.execute("INSERT INTO curation_jobs(task,payload,status,created_at) "
                  "VALUES('embed',?,'pending',?)",
                  (json.dumps({"target_id": "b_long", "kind": "note", "text": "x"},
                              sort_keys=True), "2026-09-02T00:00:00Z"))
        c.commit()
        before = _sha(self._row(c, "memory_vectors", ("b_long", "note"))["embedding"])
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        after = _sha(self._row(c, "memory_vectors", ("b_long", "note"))["embedding"])
        c.close()
        self.assertEqual(before, after, out)
        self.assertGreaterEqual(counts.get("skipped-job", 0), 1, out)

    def test_short_text_row_does_not_get_the_exception(self):
        """The control: the same live rewrite on a SHORT row is a conflict."""
        key = self._any_memory_key()
        healed = pack([0.55] * DIMS)
        c = self._live()
        c.execute("UPDATE memory_vectors SET embedding=?, model=? "
                  "WHERE belief_id=? AND kind=?", (healed, CANON) + key)
        c.commit()
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        row = self._row(c, "memory_vectors", key)
        c.close()
        self.assertEqual(_sha(row["embedding"]), _sha(healed),
                         "W6 leaked to a row under the clamp:\n" + out)
        self.assertGreaterEqual(counts.get("skipped-changed", 0), 1, out)

    def test_the_engine_applies_no_independent_payload_clamp(self):
        """The successor to `test_clamp_constant_tracks_the_store`.

        WB was built on A11b, where `store.enqueue_embed_job` stored
        `(text or "")[:8000]` and `curation._task_embed` embedded that payload
        for belief/observed kinds -- so a heal of a long row wrote the vector of
        a truncation. W6 exists for those rows, and the original test read that
        literal back out of engine/store.py so W6's threshold could not drift
        away from the engine's.

        Ladder-10 A0g DELETED the clamp with no replacement: `_task_embed` now
        re-resolves the text through the reducer's authority for every kind, and
        the embedder's own clamp is the single authority on length. Grepping for
        a literal that no longer exists would fail forever and prove nothing, so
        this pins the property that actually matters NOW -- that
        enqueue_embed_job does not truncate the text it stores -- which is what
        makes a fresh v5.7.0 heal safe and W6 belt-and-braces for the rows an
        OLDER engine already truncated on disk.

        Asserted on BEHAVIOUR, not on source text, so it cannot be satisfied by
        a comment and cannot be broken by reformatting."""
        home = tempfile.mkdtemp(prefix="wb_clamp_")
        self.addCleanup(shutil.rmtree, home, True)
        store = MemoryStore(os.path.join(home, "chronicle.db"))
        long_text = "Pat Testley's runbook. " * 600        # ~13,800 chars
        self.assertGreater(len(long_text), WB._JOB_PAYLOAD_CLAMP * 1.5)
        jid = store.enqueue_embed_job("b_clamp_probe", "note", long_text)
        self.assertIsNotNone(jid, "the probe job was deduped away")
        row = store._conn().execute(
            "SELECT payload FROM curation_jobs WHERE id=?", (jid,)).fetchone()
        stored = json.loads(row["payload"])["text"]
        self.assertEqual(len(stored), len(long_text),
                         "engine/store.py truncated an embed-job payload at %d chars; "
                         "A0g removed that clamp, and a clamp here would make the live "
                         "heal and the write path embed different strings again"
                         % len(stored))
        self.assertEqual(stored, long_text)


# ==========================================================================
# W7 / W8 — scope, batching, resumability, the report
# ==========================================================================
class TestW7W8(_WBCase):
    def test_unchanged_rows_are_never_written(self):
        """An unrecoverable row is left alone by the migration, so it must be
        left alone here too — the copy and live agree, and there is nothing to
        carry."""
        c = sqlite3.connect(self.copy)
        # restore one row on the copy to its pre-migration state
        key = self._any_memory_key()
        man = dict()
        for line in open(self.manifest).read().splitlines()[1:]:
            rec = json.loads(line)
            if rec["t"] == "memory_vectors" and tuple(rec["k"]) == key:
                man = rec
        old_blob = pack([0.03] * (DIMS * 2))
        self.assertEqual(_sha(old_blob), man["h"], "fixture drift")
        c.execute("UPDATE memory_vectors SET model=?, embedding=? "
                  "WHERE belief_id=? AND kind=?", (man["m"], old_blob) + key)
        c.commit()
        c.close()
        rc, counts, out = self._run_counts()
        c = self._live()
        row = self._row(c, "memory_vectors", key)
        c.close()
        self.assertEqual(row["model"], OLD_MODEL,
                         "a row the migration did not change was written anyway:\n" + out)
        self.assertIn("unchanged on copy", out)

    def test_batch_is_capped_at_500(self):
        wb = WB.WriteBack(None, None, {}, CANON, WIDTH, batch=100000)
        self.assertEqual(wb.batch, 500)
        wb = WB.WriteBack(None, None, {}, CANON, WIDTH, batch=0)
        self.assertEqual(wb.batch, 1)
        self.assertLessEqual(WB._MAX_BATCH, 500)

    def test_busy_timeout_is_at_least_five_seconds(self):
        self.assertGreaterEqual(WB._BUSY_TIMEOUT_MS, 5000)
        conn = WB._open_rw(self.live)
        try:
            self.assertGreaterEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0],
                                    5000)
        finally:
            conn.close()

    def test_limit_then_resume_never_redoes(self):
        rc1, c1, out1 = self._run_counts(limit=2, batch=1)
        self.assertEqual(rc1, 2, out1)
        self.assertLessEqual(c1.get("applied", 0), 2, out1)
        first = c1.get("applied", 0)
        state = json.loads(open(self.state).read())
        self.assertTrue(state["cursor"], "no cursor persisted")
        rc2, c2, out2 = self._run_counts()
        self.assertEqual(c2.get("skipped-changed", 0), 0,
                         "the resume re-processed rows it had already written and "
                         "counted its own writes as conflicts:\n" + out2)
        # everything converges: every copy row with the canonical tag is on live
        c = self._live()
        for t in WB._TABLES:
            keys = WB._KEYS[t]
            for r in sqlite3.connect(self.copy).execute(
                    'SELECT %s, model, embedding FROM "%s"' % (", ".join(keys), t)):
                key = tuple(r[:len(keys)])
                if r[len(keys)] != CANON:
                    continue
                live = self._row(c, t, key)
                self.assertEqual(_sha(live["embedding"]), _sha(r[len(keys) + 1]),
                                 "%s %r did not converge after resume" % (t, key))
        c.close()
        self.assertGreater(first + c2.get("applied", 0), 0)

    def test_state_file_is_bound_to_its_manifest(self):
        self._run_counts(limit=1, batch=1)
        other = os.path.join(self.home, "other.jsonl")
        shutil.copy(self.manifest, other)
        with open(other, "a") as fh:
            fh.write("\n")          # a different file => a different sha
        rc = self._run(manifest_path=other)
        self.assertEqual(rc, 1, "a cursor counted over one work-set was reused for "
                                "another")

    def test_report_names_every_bucket(self):
        rc, counts, out = self._run_counts()
        for bucket in ("applied", "skipped-changed", "skipped-text", "skipped-job",
                       "skipped-missing", "refused"):
            self.assertIn(bucket, out, "report omits %r" % bucket)

    def test_tables_filter(self):
        rc, counts, out = self._run_counts(tables=["session_index"])
        c = self._live()
        n_mem = c.execute("SELECT COUNT(*) FROM memory_vectors WHERE model=?",
                          (CANON,)).fetchone()[0]
        sess = self._row(c, "session_index", ("s1",))
        c.close()
        self.assertEqual(n_mem, 0, "--tables did not scope the run")
        self.assertEqual(sess["model"], CANON, out)


# ==========================================================================
# the live SCHEMA is never touched
# ==========================================================================
class TestLiveSchemaIsInert(_WBCase):
    def test_schema_and_version_unchanged_by_a_real_run(self):
        """A write-back must not ALTER a 2.9 GB production store as a side
        effect of opening it. Constructing a MemoryStore would: `_migrate` runs
        on open and adds columns/tables. This tool uses a plain sqlite3
        connection, and here is the property that says so."""
        c = self._live()
        ddl_before = [tuple(r) for r in c.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()]
        ver_before = c.execute("SELECT value FROM meta WHERE key='schema_version'"
                               ).fetchone()
        c.close()
        self._run_counts()
        c = self._live()
        ddl_after = [tuple(r) for r in c.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()]
        ver_after = c.execute("SELECT value FROM meta WHERE key='schema_version'"
                              ).fetchone()
        c.close()
        self.assertEqual(ddl_before, ddl_after, "the write-back changed the live schema")
        self.assertEqual(tuple(ver_before or ()), tuple(ver_after or ()),
                         "the write-back bumped the live schema_version")

    def test_module_does_not_construct_a_memorystore(self):
        """Named in CODE, not in prose: the docstring explains why MemoryStore is
        avoided, so the check is on the AST rather than on the text."""
        import ast
        tree = ast.parse(Path(WB.__file__).read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    names.add(a.name.split(".")[-1])
                    if a.asname:
                        names.add(a.asname)
        self.assertNotIn("MemoryStore", names,
                         "writeback_vectors.py constructs or imports MemoryStore; "
                         "_migrate then runs against the LIVE store")
        self.assertFalse(names & {"executescript"},
                         "writeback_vectors.py runs executescript on a live store")

    def test_refuses_a_live_table_with_no_model_column(self):
        """The pre-A0e shape: session_index with nowhere to record a geometry.
        The tool says so and refuses rather than ALTERing production."""
        c = self._live()
        c.executescript(
            "CREATE TABLE si_new (session_id TEXT PRIMARY KEY, summary TEXT, "
            "embedding BLOB, owner TEXT, occurred_at TEXT);"
            "INSERT INTO si_new SELECT session_id, summary, embedding, owner, "
            "occurred_at FROM session_index;"
            "DROP TABLE session_index;"
            "ALTER TABLE si_new RENAME TO session_index;")
        c.commit()
        c.close()
        rc = self._run(tables=["session_index"])
        self.assertEqual(rc, 1)


# ==========================================================================
# --dry-run
# ==========================================================================
class TestDryRun(_WBCase):
    def test_writes_nothing_at_all(self):
        h0 = _file_sha(self.live)
        rc, counts, out = self._run_counts(dry_run=True)
        h1 = _file_sha(self.live)
        self.assertEqual(h0, h1, "--dry-run changed live db/wal/shm bytes")
        self.assertEqual(rc, 0, out)
        self.assertGreater(counts.get("applied", 0), 0,
                           "--dry-run reported no work on a store full of it")
        self.assertFalse(os.path.exists(self.state), "--dry-run wrote a state file")
        c = self._live()
        n = c.execute("SELECT COUNT(*) FROM memory_vectors WHERE model=?",
                      (CANON,)).fetchone()[0]
        c.close()
        self.assertEqual(n, 0)

    def test_dry_run_predicts_the_real_run(self):
        _rc, dry, _o = self._run_counts(dry_run=True)
        _rc2, real, _o2 = self._run_counts()
        self.assertEqual(dry.get("applied"), real.get("applied"),
                         "--dry-run's applied count did not match the real run's")

    def test_dry_run_refuses_without_a_manifest_too(self):
        self.assertEqual(self._run(dry_run=True, manifest_path=None), 1)


# ==========================================================================
# the manifest itself
# ==========================================================================
class TestManifest(_WBCase):
    def test_records_the_pre_migration_pre_image(self):
        recs = [json.loads(line) for line in open(self.manifest).read().splitlines()[1:]]
        self.assertTrue(recs)
        by_table = {}
        for r in recs:
            by_table.setdefault(r["t"], 0)
            by_table[r["t"]] += 1
        for t in ("observed_vectors", "memory_vectors", "session_index",
                  "projection_vectors", "query_proxy_vectors"):
            self.assertIn(t, by_table, "manifest missed %s" % t)
        old_blob_sha = _sha(pack([0.03] * (DIMS * 2)))
        mem = [r for r in recs if r["t"] == "memory_vectors"]
        self.assertTrue(all(r["m"] == OLD_MODEL for r in mem))
        self.assertTrue(all(r["h"] == old_blob_sha for r in mem))

    def test_records_the_authority_text_hash(self):
        recs = [json.loads(line) for line in open(self.manifest).read().splitlines()[1:]]
        long_rec = [r for r in recs
                    if r["t"] == "memory_vectors" and r["k"] == ["b_long", "note"]][0]
        self.assertEqual(long_rec["x"], hashlib.sha256(LONG_BODY.encode()).hexdigest())
        self.assertEqual(long_rec["n"], len(LONG_BODY))
        self.assertGreater(long_rec["n"], WB._JOB_PAYLOAD_CLAMP)

    def test_header_binds_the_copy(self):
        header = json.loads(open(self.manifest).read().splitlines()[0])
        self.assertEqual(header["_manifest"], WB.MANIFEST_KIND)
        self.assertIn("row_counts", header)
        c = sqlite3.connect(self.copy)
        for t, n in header["row_counts"].items():
            self.assertEqual(c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0], n)
        c.close()

    def test_not_a_manifest_is_refused(self):
        junk = os.path.join(self.home, "junk.jsonl")
        open(junk, "w").write(json.dumps({"hello": "world"}) + "\n")
        self.assertEqual(self._run(manifest_path=junk), 1)


# ==========================================================================
# an unreadable or empty source is a refusal, never an empty success
# ==========================================================================
def _to_sidecarless_wal(path):
    """Put `path` in the state a `.backup` of the production store is in: a WAL
    header and no -wal/-shm. The fixture's store closes in rollback-journal mode,
    which `mode=ro` opens fine, and that is how an empty-manifest bug survived
    every test here while failing on the first real copy."""
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    for ext in ("-wal", "-shm"):        # Apple's SQLite keeps them; Linux's removes them
        p = path + ext
        if os.path.exists(p):
            assert ext == "-shm" or os.path.getsize(p) == 0, "uncheckpointed frames"
            os.remove(p)
    assert open(path, "rb").read(20)[18:20] == b"\x02\x02", "not a WAL header"


class TestUnreadableOrEmptySourceRefuses(_WBCase):
    def _require_ro_fails(self, path):
        probe = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            probe.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.Error:
            return
        finally:
            probe.close()
        self.skipTest("this SQLite opens a sidecar-less WAL database read-only")

    def _counts_then(self):
        return json.loads(open(self.manifest).readline())["row_counts"]

    def test_sidecarless_wal_copy_builds_the_full_manifest(self):
        _to_sidecarless_wal(self.copy)
        self._require_ro_fails(self.copy)
        before = _file_sha(self.copy)
        out = os.path.join(self.home, "wal.jsonl")
        n = WB.build_manifest(self.copy, out, live_db=self.live, verbose=False)
        header = json.loads(open(out).readline())
        self.assertEqual(header["row_counts"], self._counts_then())
        self.assertEqual(n, sum(self._counts_then().values()))
        self.assertGreater(n, 0)
        self.assertEqual(_file_sha(self.copy), before, "reading the copy changed it")

    def test_writeback_reads_a_sidecarless_wal_copy(self):
        _to_sidecarless_wal(self.copy)
        self._require_ro_fails(self.copy)
        rc, counts, out = self._run_counts()
        self.assertNotIn("REFUSED", out)
        self.assertIn(rc, (0, 2))
        self.assertGreater(counts.get("applied", 0), 0)

    def test_live_is_never_opened_immutable(self):
        _to_sidecarless_wal(self.copy)
        self._require_ro_fails(self.copy)
        with self.assertRaises(WB.Refused):
            WB._open_ro(self.copy)

    def test_a_copy_whose_wal_holds_frames_is_never_read_immutable(self):
        """immutable=1 ignores the -wal: here it would not even see the table."""
        db = os.path.join(self.home, "framed.db")
        c = sqlite3.connect(db)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")
        c.execute("CREATE TABLE memory_vectors(belief_id, kind, embedding, model)")
        c.execute("INSERT INTO memory_vectors VALUES('b_1', 'fact', x'00', 'm')")
        c.commit()
        frozen = os.path.join(self.home, "frozen.db")
        shutil.copy(db, frozen)
        shutil.copy(db + "-wal", frozen + "-wal")
        c.close()
        self.assertGreater(os.path.getsize(frozen + "-wal"), 0)
        real_connect = sqlite3.connect
        missing = os.path.join(self.home, "no-such-dir", "x.db")

        def connect(target, *a, **kw):
            if "immutable=1" not in str(target):
                target = "file:%s?mode=ro" % missing        # the read-only open fails
            return real_connect(target, *a, **kw)

        with mock.patch.object(WB.sqlite3, "connect", connect):
            with self.assertRaises(WB.Refused) as ctx:
                WB._open_ro(frozen, static=True)
        self.assertIn("-wal holds frames", str(ctx.exception))

    def test_unreadable_copy_writes_no_manifest(self):
        import io
        import contextlib
        junk = os.path.join(self.home, "junk.db")
        open(junk, "wb").write(b"Acme Fake Co is not a database. " * 200)
        out = os.path.join(self.home, "junk.jsonl")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = WB.main([self.live, junk, "--build-manifest", out])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(out))

    def test_schema_read_failure_is_not_absence(self):
        conn = sqlite3.connect(self.copy)
        conn.close()
        with self.assertRaises(WB.Refused):
            WB._has_table(conn, "memory_vectors")

    def test_a_count_that_fails_does_not_drop_the_table(self):
        real = sqlite3.connect(self.copy)

        class Flaky:
            def execute(self, sql, *a):
                if sql.startswith("SELECT COUNT(*)"):
                    raise sqlite3.OperationalError("disk I/O error")
                return real.execute(sql, *a)

        try:
            with self.assertRaises(WB.Refused):
                WB._row_counts(Flaky(), ["memory_vectors"])
        finally:
            real.close()

    def _empty_the_copy(self):
        c = sqlite3.connect(self.copy)
        with c:
            for t in WB._TABLES:
                c.execute('DELETE FROM "%s"' % t)
        c.close()

    def test_a_copy_with_no_vector_rows_refuses_to_build(self):
        self._empty_the_copy()
        out = os.path.join(self.home, "none.jsonl")
        with self.assertRaises(WB.Refused):
            WB.build_manifest(self.copy, out, verbose=False)
        self.assertFalse(os.path.exists(out))

    def test_the_empty_manifest_the_old_build_wrote_is_refused(self):
        header = json.loads(open(self.manifest).readline())
        header["row_counts"] = {}
        empty = os.path.join(self.home, "old-empty.jsonl")
        open(empty, "w").write(json.dumps(header) + "\n")
        rc, _counts, out = self._run_counts(manifest_path=empty, state_path=self.state + ".e")
        self.assertEqual(rc, 1)
        self.assertIn("Nothing was written", out)

    def test_a_zero_row_manifest_is_refused_even_when_it_matches_the_copy(self):
        self._empty_the_copy()
        header = json.loads(open(self.manifest).readline())
        header["row_counts"] = dict((t, 0) for t in header["row_counts"])
        zero = os.path.join(self.home, "zero.jsonl")
        open(zero, "w").write(json.dumps(header) + "\n")
        rc, _counts, out = self._run_counts(manifest_path=zero, state_path=self.state + ".z")
        self.assertEqual(rc, 1)
        self.assertIn("records 0 rows", out)

    def test_a_table_the_copy_lost_is_refused(self):
        c = sqlite3.connect(self.copy)
        c.execute("DROP TABLE projection_vectors")
        c.commit()
        c.close()
        rc, _counts, out = self._run_counts()
        self.assertEqual(rc, 1)
        self.assertIn("projection_vectors is in the manifest", out)
        self.assertIn("Nothing was written", out)


if __name__ == "__main__":
    unittest.main()
