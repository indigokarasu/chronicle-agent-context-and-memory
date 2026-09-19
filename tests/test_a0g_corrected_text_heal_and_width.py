"""
Chronicle — A0g: what a vector is MADE OF, and when a repair must refuse.

Three defects the independent GO/NO-GO review of the A0 chain found, each pinned
here through the REAL capture -> process -> curation pipeline rather than by
poking tables:

N2 (pre-existing since at least v5.6, and affecting production stores today).
  `reducer._on_corrected` calls `_insert_belief(kind, id, key, new_body, event)`
  and `_insert_belief` evaluated `vector_text("asserted", <the event's payload>)`.
  A `corrected` payload carries `new_body`, never `body`, so that expression read
  a payload with no body and no key and returned "" -- the belief was written with
  the vector of the EMPTY STRING while the projection stored the corrected text.
  Every fact a user explicitly fixed through `chronicle_correct` was therefore
  invisible to vector retrieval (0.576 cosine against its own text on live nomic).
  The text now comes from the `kind`/`key`/`body` being written, which is what
  `reducer.belief_vector_text` reads back, so write and repair are ONE expression.

N1. `store.enqueue_embed_job` clamped its payload to `text[:8000]` and
  `curation._task_embed` embedded that payload for `observed` and belief kinds --
  only `session` re-resolved. So the deferred/heal path embedded a DIFFERENT
  string from the write path for any item over 8000 characters, under the same
  canonical tag. It is NOT masked at production's `max_input_tokens: 650`, because
  production also sets `overflow: chunk_mean`, which sends every chunk of the input
  to the model: a 9,736-character note re-embedded from 8,017 wire characters is a
  different vector. `_task_embed` now re-resolves through the authority for every
  kind and the clamp is gone.

WIDTH GUARD. `healthcheck()` adopts the width the endpoint answers with, and every
  width decision is made against it -- so a server answering 384 for a 768-dim
  model name had migrate_vectors rewrite an entire store into a 384-dim geometry
  under the canonical tag. Where a width is STATED -- a declared
  `embeddings.dimensions`, or `embeddings.KNOWN_MODEL_DIMENSIONS` for the resolved
  canonical id -- a contradicting probe is now refused: nothing written, non-zero
  exit, expected-vs-reported named. An unknown model with nothing declared has no
  expectation and is never refused.

The endpoint here (`_RecordingEndpoint`) is the reviewer's deterministic loopback
server, in-process: the vector is a raw hash of the FULL wire input, so two blobs
are equal if and only if the texts that produced them were byte-identical. That is
what makes "the repair embedded the same text" a byte assertion rather than a
similarity one. Fixtures use obviously fake people and companies.
"""

import contextlib
import hashlib
import inspect
import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.migrate_vectors as MV
from engine import curation as C
from engine import embeddings as E
from engine import reducer as R
from engine.config import Config
from engine.core import ChronicleCore
from engine.embeddings import pack

WIRE_MODEL = "nomic-embed-text:latest"
CANON = "nomic-embed-text[prefixed]"
NEMO = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
DIMS = 768
PREFIX = "search_document: "
P = "assistant"

# Items deliberately longer than the 8000-character clamp N1 removed.
LONG_NOTE = " ".join("Note sentence %03d about the Acme widget press calibration and safety "
                     "interlocks." % i for i in range(120))
LONG_PROC = "Deploy the billing module: " + " ".join(
    "step %03d runs the smoke suite and then bumps the version tag." % i for i in range(150))
LONG_TURN = "\n".join("user: Bluebird launch note %03d, the sponsor is Dana Fictional and the "
                      "module is billing." % i for i in range(120))
LONG_PROJ = " ".join("Ledger row %03d: Acme Fake Co invoice for the billing module, paid."
                     % i for i in range(160))

ID_COLS = {"observed_vectors": ("event_id",), "memory_vectors": ("belief_id", "kind"),
           "session_index": ("session_id",), "projection_vectors": ("provider", "external_id"),
           "query_proxy_vectors": ("belief_id", "proxy_idx")}


class _RecordingEndpoint(E.OpenAICompatEmbedder):
    """A real OpenAICompatEmbedder with the socket replaced, not a duck type.

    Everything that decides what goes ON THE WIRE -- the document/query task
    prefix, the max_input_tokens clamp, `truncate` vs `chunk_mean` chunking, the
    batch path -- is the shipping code. Only the HTTP call is swapped, for a
    deterministic hash of the FULL input, so blob equality IS wire-text equality
    and `wire` is the exact list of strings this process would have sent."""

    def __init__(self, dimensions=DIMS, model=WIRE_MODEL, max_input_tokens=2048,
                 overflow="truncate"):
        super().__init__("http://127.0.0.1:9/v1", model, dimensions,
                         max_input_tokens=max_input_tokens, overflow=overflow,
                         task_prefixes="auto")
        self._h = E.HashingEmbedder(dimensions=dimensions)
        self.wire = []

    def _embed_raw(self, text, timeout):
        self.wire.append(text or "")
        return self._h._embed_one(text or "")

    def _embed_raw_batch(self, texts, timeout):
        return [self._embed_raw(t, timeout) for t in texts]

    def blob_of(self, wire_text):
        """The bytes this endpoint answers for one exact wire input."""
        return pack(self._h._embed_one(wire_text))


def _core(home, emb, max_input_tokens=2048, overflow="truncate", declared_dims=None,
          excerpt_chars=16000):
    """A core running `emb`, with the width `declared_dims` (default: the
    embedder's own, so the width guard has nothing to object to)."""
    cfg = {"embeddings": {"model": "hashing",
                          "dimensions": emb.dimensions if declared_dims is None else declared_dims,
                          "max_input_tokens": max_input_tokens, "overflow": overflow},
           "capture": {"max_excerpt_chars": excerpt_chars}}
    core = ChronicleCore(home, cfg)
    core.embedder = emb
    core.reducer.embedder = emb
    core.retrieval.embedder = emb
    return core


def _seed(core):
    """One ordinary session: two observed turns, three remembered beliefs, a
    session summary and an external projection -- every vector-bearing table."""
    core.initialize("s1", principal_id="assistant")
    core.capture.observe("I am Pat Testley\nI work at Acme Fake Co\nI live in Springfield",
                         "Noted, Pat.", session_id="s1")
    core.capture.observe(LONG_TURN, "assistant reply", session_id="s1")
    core.process_pending()
    core.curation.drain()
    core.tools._t_remember(P, {"kind": "fact", "content": "tea over coffee", "entity": "user",
                               "attribute": "beverage_preference"})
    core.tools._t_remember(P, {"kind": "note", "content": LONG_NOTE})
    core.tools._t_remember(P, {"kind": "procedure", "content": LONG_PROC})
    core.tools._t_remember(P, {"kind": "reference", "content": "The Acme widget press manual "
                               "covers calibration and safety interlocks.",
                               "entity": "Acme widget press manual"})
    core.process_pending()
    core.curation.drain()
    core.store.enqueue_curation("session_summarize", {"session_id": "s1"})
    core.store.enqueue_projection_embed("fakedb", "row1", LONG_PROJ, owner="default")
    core.curation.drain()
    core.curation.drain()


def _correct_the_fact(core):
    """The user action this whole file is about: chronicle_correct."""
    conn = core.store._conn()
    old = conn.execute("SELECT belief_id FROM facts WHERE value='tea over coffee'").fetchone()[0]
    core.tools._t_correct(P, {"belief_id": old, "new_value": "coffee over tea",
                              "reason": "review"})
    core.process_pending()
    core.curation.drain()
    return conn.execute("SELECT belief_id FROM facts WHERE value='coffee over tea'").fetchone()[0]


def _snapshot(core):
    conn = core.store._conn()
    out = {}
    for table, cols in ID_COLS.items():
        for row in conn.execute("SELECT %s, embedding, model FROM %s"
                                % (", ".join(cols), table)).fetchall():
            out[(table,) + tuple(row[:len(cols)])] = row[len(cols)]
    return out


def _corrupt(core):
    """Every vector in the store lands in a foreign model's geometry -- the live
    condition the heal and the migration exist for."""
    with core.store.transaction() as c:
        for table in E.VECTOR_TABLES:
            c.execute("UPDATE %s SET model=?, embedding=?" % table,
                      (NEMO, pack([0.02] * 2048)))


def _mutant(func, edits):
    """`func` recompiled with each `(old, new)` applied, in its own module globals.

    A mutation test is only worth anything if it mutates the REAL source, and only
    honest if it fails loudly when an anchor it edits no longer exists -- an anchor
    that silently stops matching turns the guard into a test that passes because it
    changed nothing. Anchors are matched against the DEDENTED source, so they are
    written at method-body indentation."""
    src = textwrap.dedent(inspect.getsource(func))
    module = sys.modules[func.__module__]
    for old, new in edits:
        assert old in src, ("mutation anchor is gone from %s.%s; this guard would be "
                            "vacuous:\n%r" % (module.__name__, func.__name__, old))
        src = src.replace(old, new)
    ns = dict(module.__dict__)
    exec(compile(src, module.__file__, "exec"), ns)
    return ns[func.__name__]


def _sha_db(db_path):
    """db + -wal + -shm, so "nothing was written" covers the sidecars too."""
    h = hashlib.sha256()
    for ext in ("", "-wal", "-shm"):
        p = db_path + ext
        if os.path.exists(p):
            h.update(ext.encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


# ===========================================================================
# N2 — a corrected belief embeds the text the projection stores
# ===========================================================================
class TestCorrectedBeliefEmbedsItsRealText(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a0g_n2_")
        self.emb = _RecordingEndpoint()
        self.core = _core(self.home, self.emb)
        _seed(self.core)
        self.corrected = _correct_the_fact(self.core)
        self.conn = self.core.store._conn()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _blob(self, belief_id, kind="fact"):
        row = self.conn.execute("SELECT embedding FROM memory_vectors WHERE belief_id=? AND kind=?",
                                (belief_id, kind)).fetchone()
        return row[0] if row else None

    def test_the_stored_vector_is_the_corrected_text(self):
        stored = self._blob(self.corrected)
        self.assertIsNotNone(stored, "the corrected belief got no vector at all")
        self.assertEqual(stored, self.emb.blob_of(PREFIX + "coffee over tea"),
                         "the corrected belief's vector is not the vector of its own text")
        self.assertIn(PREFIX + "coffee over tea", self.emb.wire,
                      "the corrected text never went on the wire")

    def test_it_is_not_the_vector_of_the_empty_string(self):
        """The defect's own bytes, named explicitly: this is what every corrected
        belief in an existing store carries."""
        self.assertNotEqual(self._blob(self.corrected), self.emb.blob_of(PREFIX),
                            "the corrected belief still carries the empty-string vector")

    def test_the_write_side_and_the_text_authority_agree_byte_for_byte(self):
        text, recoverable = R.belief_vector_text(self.conn, "fact", self.corrected)
        self.assertTrue(recoverable)
        self.assertEqual(text, "coffee over tea")
        self.assertEqual(self._blob(self.corrected), pack(self.emb.embed_document(text)),
                         "what the repair paths would write differs from what the write "
                         "path wrote -- that IS the D3 class")

    def test_every_belief_vector_in_the_store_is_recoverable_byte_for_byte(self):
        """The audit, executed rather than argued: after a session that exercises
        `asserted` (extraction AND tool writes), `derived`, a fact-conflict
        supersession and `corrected`, EVERY memory vector equals the embedding of
        the text the authority recovers for it."""
        core, conn = self.core, self.conn
        fact_id = conn.execute("SELECT belief_id FROM facts WHERE value='coffee over tea'"
                               ).fetchone()[0]
        core.capture.append("derived", {"kind": "note",
                                        "key": {"note_type": "belief", "subject": "derived"},
                                        "body": "Derived: Pat prefers coffee, so offer coffee.",
                                        "rule_id": "r_a0g", "premises": [fact_id],
                                        "confidence": 0.6, "status": "active"}, actor="curator")
        # A second assertion of a fact key that already exists: _apply_fact_conflict
        # supersedes and re-inserts through _insert_belief on an `asserted` event.
        core.capture.append("asserted", {"kind": "fact",
                                         "key": {"entity_id": "user", "attribute": "city",
                                                 "predicate_canonical": "lives_in",
                                                 "qualifiers_hash": "", "qualifiers": {},
                                                 "owner": P, "domain": "user"},
                                         "body": "Riverton", "confidence": 0.9,
                                         "source_event": "tool",
                                         "source_type": "agent_memory_write"},
                            actor="agent", trust_level=3)
        core.process_pending()
        core.curation.drain()
        rows = conn.execute("SELECT belief_id, kind, embedding FROM memory_vectors").fetchall()
        self.assertGreater(len(rows), 4)
        bad = []
        for belief_id, kind, blob in rows:
            text, recoverable = R.belief_vector_text(conn, kind, belief_id)
            if not recoverable or blob != pack(self.emb.embed_document(text)):
                bad.append((kind, belief_id, recoverable, (text or "")[:40]))
        self.assertEqual(bad, [], "belief vectors whose stored bytes are not the embedding of "
                                  "the text the authority recovers: %r" % (bad,))

    def test_a_belief_with_no_text_writes_no_vector(self):
        """"" is not a weak text, it is no text: `belief_vector_text` reports it
        UNRECOVERABLE, so a vector written from it could never be repaired and
        would sit in every migration's `failed` list forever."""
        self.core.capture.append("asserted", {"kind": "note",
                                              "key": {"note_type": "belief", "subject": "empty"},
                                              "body": "", "confidence": 0.9,
                                              "source_event": "tool",
                                              "source_type": "agent_memory_write"},
                                 actor="agent", trust_level=3)
        self.core.process_pending()
        self.core.curation.drain()
        empty = self.conn.execute("SELECT belief_id FROM notes WHERE subject='empty'").fetchone()
        self.assertIsNotNone(empty, "the belief itself must still be stored")
        self.assertIsNone(self._blob(empty[0], "note"),
                          "a vector was written for a belief whose text is unrecoverable")

    def test_mutation_restoring_the_payload_read_brings_the_defect_back(self):
        """The guard on the assertions above: with `_insert_belief` reading the
        event payload again, the corrected belief IS the empty-string vector."""
        # Both halves of the pre-A0g write: the payload read AND the unconditional
        # write of whatever it produced. Restoring only the read would write no
        # vector at all (the empty-text gate), which is a different bug from the
        # one that is in production stores today.
        mutant = _mutant(R.Reducer._insert_belief, [
            ('self.vector_text("asserted", {"kind": kind, "key": key, "body": body})',
             'self.vector_text("asserted", p)'),
            (" if text_to_embed else None", ""),
        ])
        home = tempfile.mkdtemp(prefix="a0g_n2_mut_")
        try:
            emb = _RecordingEndpoint()
            with unittest.mock.patch.object(R.Reducer, "_insert_belief", mutant):
                core = _core(home, emb)
                _seed(core)
                corrected = _correct_the_fact(core)
                blob = core.store._conn().execute(
                    "SELECT embedding FROM memory_vectors WHERE belief_id=? AND kind='fact'",
                    (corrected,)).fetchone()[0]
            self.assertEqual(blob, emb.blob_of(PREFIX),
                             "the mutant did not reproduce the defect, so the tests above "
                             "are not actually pinning it")
            self.assertNotEqual(blob, emb.blob_of(PREFIX + "coffee over tea"))
        finally:
            shutil.rmtree(home, ignore_errors=True)


# ===========================================================================
# N1 — the heal re-embeds what the write path embedded, for every kind
# ===========================================================================
class TestHealReproducesTheWritePath(unittest.TestCase):
    def setUp(self):
        self.homes = []

    def tearDown(self):
        for home in self.homes:
            shutil.rmtree(home, ignore_errors=True)

    def _build(self, max_tok, overflow):
        home = tempfile.mkdtemp(prefix="a0g_n1_")
        self.homes.append(home)
        emb = _RecordingEndpoint(max_input_tokens=max_tok, overflow=overflow)
        core = _core(home, emb, max_input_tokens=max_tok, overflow=overflow)
        _seed(core)
        _correct_the_fact(core)
        return core, emb

    def _heal_and_drain(self, core):
        summary = core.health._embedder_mismatch_heal()["embedder_mismatch"]
        for _ in range(3):
            core.curation.drain()
        return summary

    def _assert_round_trip(self, max_tok, overflow):
        self.assertGreater(len(LONG_NOTE), 8000, "fixture no longer exceeds the old clamp")
        self.assertGreater(len(LONG_PROC), 8000, "fixture no longer exceeds the old clamp")
        self.assertGreater(len(LONG_PROJ), 8000, "fixture no longer exceeds the old clamp")
        core, _emb = self._build(max_tok, overflow)
        before = _snapshot(core)
        long_rows = [k for k, v in before.items() if k[0] == "observed_vectors"]
        self.assertTrue(long_rows, "no observed vector was written")
        _corrupt(core)
        summary = self._heal_and_drain(core)
        self.assertGreater(summary["requeued"], 0, "the heal queued no repair at all")
        after = _snapshot(core)
        diverged, missing = [], []
        for key, blob in before.items():
            if key[0] == "query_proxy_vectors":
                continue          # dropped by the heal by design, not re-embedded
            if key not in after:
                missing.append(key)
            elif after[key] != blob:
                diverged.append(key)
        self.assertEqual(missing, [], "rows the heal lost: %r" % (missing,))
        self.assertEqual(diverged, [],
                         "heal+drain re-embedded a DIFFERENT text than the write path for: %r"
                         % (diverged,))

    def test_at_max_input_tokens_8192_truncate(self):
        """Above 2666 tokens the old 8000-char payload clamp bit under `truncate`."""
        self._assert_round_trip(8192, "truncate")

    def test_at_the_production_shape_650_chunk_mean(self):
        """Production is `max_input_tokens: 650, overflow: chunk_mean`. chunk_mean
        sends EVERY chunk of the input, so the clamp changed the vector there too --
        the small token cap never masked it."""
        self._assert_round_trip(650, "chunk_mean")

    def test_the_queued_payload_is_not_clamped(self):
        core, _emb = self._build(650, "chunk_mean")
        core.store.enqueue_embed_job("ev_clamp_probe", "observed", LONG_PROJ)
        payloads = [r[0] for r in core.store._conn().execute(
            "SELECT payload FROM curation_jobs WHERE task='embed'").fetchall()]
        stored = [p for p in payloads if "ev_clamp_probe" in p]
        self.assertEqual(len(stored), 1)
        import json as _json
        self.assertEqual(len(_json.loads(stored[0])["text"]), len(LONG_PROJ),
                         "the embed job still truncates the text it was given")

    def test_mutation_restoring_the_payload_embed_diverges(self):
        """With `_task_embed` embedding its clamped payload again, the long note
        comes back as a different vector -- so the round-trip assertions above are
        really pinning N1."""
        mutant = _mutant(C.CurationWorker._task_embed, [
            ("        text, recoverable = belief_vector_text(self.store._conn(), kind, target)\n"
             "        if not recoverable:\n"
             "            return\n",
             '        text = (text or "")[:8000]\n'),
        ])
        core, _emb = self._build(650, "chunk_mean")
        conn = core.store._conn()
        note_id = conn.execute("SELECT belief_id FROM notes WHERE body=?", (LONG_NOTE,)).fetchone()[0]
        before = conn.execute("SELECT embedding FROM memory_vectors WHERE belief_id=? AND kind='note'",
                              (note_id,)).fetchone()[0]
        _corrupt(core)
        with unittest.mock.patch.object(C.CurationWorker, "_task_embed", mutant):
            self._heal_and_drain(core)
        after = conn.execute("SELECT embedding FROM memory_vectors WHERE belief_id=? AND kind='note'",
                             (note_id,)).fetchone()[0]
        self.assertNotEqual(after, before,
                            "the mutant did not diverge, so the round-trip tests above are "
                            "not pinning the payload read")


# ===========================================================================
# THE WIDTH GUARD
# ===========================================================================
class TestKnownWidths(unittest.TestCase):
    def test_the_table_answers_through_canonical_identity(self):
        for name in ("nomic-embed-text", "nomic-embed-text:latest",
                     "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf",
                     "nomic-embed-text[prefixed]"):
            self.assertEqual(E.known_model_dimensions(name), 768, name)

    def test_an_unlisted_model_has_no_opinion(self):
        self.assertEqual(E.known_model_dimensions("acme-embed-xl"), 0)
        self.assertEqual(E.known_model_dimensions(None), 0)

    def test_every_entry_is_a_canonical_id(self):
        for name in E.KNOWN_MODEL_DIMENSIONS:
            self.assertEqual(E.canonical_model_id(name), name,
                             "%r is not the canonical form, so no lookup can ever hit it" % name)

    def test_the_default_dimensions_value_is_not_a_declaration(self):
        """`Config.get` cannot tell 768-because-DEFAULTS from 768-because-declared,
        and treating the default as an expectation would refuse every unlisted
        model of another width."""
        self.assertEqual(Config({}).get("embeddings.dimensions"), 768)
        self.assertIsNone(Config({}).explicit("embeddings.dimensions"))
        self.assertEqual(Config({"embeddings": {"dimensions": 768}})
                         .explicit("embeddings.dimensions"), 768)

    def test_precedence_and_refusal(self):
        emb384 = _RecordingEndpoint(dimensions=384)
        emb768 = _RecordingEndpoint(dimensions=768)
        unknown = _RecordingEndpoint(dimensions=1024, model="acme-embed-xl")
        declared768 = Config({"embeddings": {"dimensions": 768}})
        nothing = Config({"embeddings": {"model": "auto"}})
        self.assertIn("expects 768", E.width_contradiction(emb384, declared768))
        self.assertIn("expects 768", E.width_contradiction(emb384, nothing))   # table
        self.assertEqual(E.width_contradiction(emb768, declared768), "")
        self.assertEqual(E.width_contradiction(emb768, nothing), "")
        self.assertEqual(E.width_contradiction(unknown, nothing), "",
                         "an unknown model must be no expectation, never a refusal")
        self.assertEqual(E.width_contradiction(unknown, Config({})), "",
                         "the DEFAULTS width must not gate an unlisted model")
        self.assertEqual(E.width_contradiction(emb384, declared768, override=384), "",
                         "--expect-dims must be able to state a new geometry")
        self.assertIn("expects 768", E.width_contradiction(emb384, nothing, override=768),
                      "an override still refuses a width the endpoint does not answer")


class _WidthCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a0g_w_")
        self.emb = _RecordingEndpoint()
        self.core = _core(self.home, self.emb)
        _seed(self.core)
        self.db = self.core.store.db_path
        self.before = _snapshot(self.core)
        _corrupt(self.core)
        self.core.store._conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _migrate(self, embedder, cfg, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = MV.migrate(self.db, cfg=cfg, embedder=embedder, verbose=True, **kw)
        return rc, buf.getvalue()


class TestMigrationRefusesAContradictedWidth(_WidthCase):
    def test_a_384_answer_for_a_768_model_is_refused_and_writes_nothing(self):
        sha_before = _sha_db(self.db)
        rc, out = self._migrate(_RecordingEndpoint(dimensions=384),
                                Config({"embeddings": {"dimensions": 768}}))
        self.assertEqual(rc, 1, out[-400:])
        self.assertIn("REFUSED", out)
        self.assertIn("384", out)
        self.assertIn("768", out)
        self.assertEqual(_sha_db(self.db), sha_before,
                         "the store (or its -wal/-shm) changed during a refusal")

    def test_the_known_dimensions_table_refuses_when_config_declares_nothing(self):
        rc, out = self._migrate(_RecordingEndpoint(dimensions=384),
                                Config({"embeddings": {"model": "auto"}}))
        self.assertEqual(rc, 1)
        self.assertIn("known-dimensions table", out)

    def test_the_right_width_proceeds_and_reproduces_the_write_path(self):
        rc, out = self._migrate(self.emb, Config({"embeddings": {"dimensions": 768}}))
        self.assertEqual(rc, 0, out[-400:])
        after = _snapshot(self.core)
        diverged = [k for k, v in self.before.items() if after.get(k) != v]
        self.assertEqual(diverged, [], "migration wrote a different text for: %r" % (diverged,))

    def test_an_unknown_model_is_not_gated(self):
        rc, out = self._migrate(_RecordingEndpoint(dimensions=1024, model="acme-embed-xl"),
                                Config({"embeddings": {"model": "acme-embed-xl"}}))
        self.assertEqual(rc, 0, out[-400:])
        widths = {r[0] for r in self.core.store._conn().execute(
            "SELECT DISTINCT length(embedding) FROM memory_vectors").fetchall()}
        self.assertEqual(widths, {1024 * 4})

    def test_expect_dims_states_a_new_geometry_for_one_run(self):
        rc, out = self._migrate(_RecordingEndpoint(dimensions=384),
                                Config({"embeddings": {"dimensions": 768}}), expect_dims=384)
        self.assertEqual(rc, 0, out[-400:])

    def test_a_dry_run_refuses_too(self):
        sha_before = _sha_db(self.db)
        rc, out = self._migrate(_RecordingEndpoint(dimensions=384),
                                Config({"embeddings": {"dimensions": 768}}), dry_run=True)
        self.assertEqual(rc, 1, "a dry-run that surveys against the wrong width would tell an "
                                "operator to go ahead")
        self.assertEqual(_sha_db(self.db), sha_before)


class TestHealRefusesAContradictedWidth(_WidthCase):
    def test_nothing_is_retagged_requeued_or_dropped(self):
        self.core.embedder = _RecordingEndpoint(dimensions=384)
        conn = self.core.store._conn()
        tags_before = sorted(r[0] for r in conn.execute("SELECT DISTINCT model FROM memory_vectors"))
        jobs_before = conn.execute("SELECT COUNT(*) FROM curation_jobs WHERE task='embed'").fetchone()[0]
        proxies_before = conn.execute("SELECT COUNT(*) FROM query_proxy_vectors").fetchone()[0]
        full = self.core.health._embedder_mismatch_heal()
        res = full["embedder_mismatch"]
        self.assertEqual(full["vectors_width_refused"], 1,
                         "a refused heal reports the same flat counters as a clean store, so "
                         "nothing watching them would ever see the condition")
        self.assertIn("width_refused", res)
        self.assertIn("384", res["width_refused"])
        self.assertEqual((res["requeued"], res["retagged"], res["mismatched"]), (0, 0, 0))
        self.assertEqual(sorted(r[0] for r in conn.execute(
            "SELECT DISTINCT model FROM memory_vectors")), tags_before)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM curation_jobs WHERE task='embed'"
                                      ).fetchone()[0], jobs_before)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM query_proxy_vectors").fetchone()[0],
                         proxies_before, "a refused heal still dropped the proxies")

    def test_the_declared_width_lets_the_heal_run(self):
        full = self.core.health._embedder_mismatch_heal()
        res = full["embedder_mismatch"]
        self.assertEqual(full["vectors_width_refused"], 0)
        self.assertNotIn("width_refused", res)
        self.assertGreater(res["requeued"], 0)


# ===========================================================================
# --tables ordering (optional extra)
# ===========================================================================
class TestTableOrdering(unittest.TestCase):
    def test_default_order_is_unchanged(self):
        self.assertEqual(MV._table_order(None), tuple(E.VECTOR_TABLES))

    def test_named_tables_come_first_and_nothing_is_dropped(self):
        order = MV._table_order("memory_vectors")
        self.assertEqual(order[0], "memory_vectors")
        self.assertEqual(sorted(order), sorted(E.VECTOR_TABLES),
                         "--tables is a priority order, never a filter: a clean exit must "
                         "keep covering every table")

    def test_unknown_table_is_rejected(self):
        with self.assertRaises(ValueError):
            MV._table_order("memory_vectors,not_a_table")


class TestOrderingRunsMemoryFirst(_WidthCase):
    def test_memory_vectors_is_repaired_before_the_others(self):
        rc, out = self._migrate(self.emb, Config({"embeddings": {"dimensions": 768}}),
                                tables="memory_vectors", batch=2)
        self.assertEqual(rc, 0, out[-400:])
        progress = [line.strip()[3:].split(":")[0] for line in out.splitlines()
                    if line.strip().startswith("...")]
        self.assertTrue(progress, out[-400:])
        self.assertEqual(progress[0], "memory_vectors",
                         "--tables memory_vectors did not put belief recall first: %r" % (progress,))
        self.assertIn("observed_vectors", progress,
                      "a re-ordered run stopped walking the other tables")
        self.assertTrue(set(progress) <= set(E.VECTOR_TABLES), progress)


# ===========================================================================
# ONE text authority (extends A0fix's structural test to the drain)
# ===========================================================================
class TestTheDrainUsesTheSameAuthority(unittest.TestCase):
    def test_curation_binds_the_reducer_function_objects(self):
        for name in ("belief_vector_text", "observed_vector_text", "session_vector_text",
                     "projection_vector_text"):
            self.assertIs(getattr(C, name), getattr(R, name),
                          "curation resolves %s through a different function object" % name)

    def test_no_second_clamp_survives_in_the_enqueue_path(self):
        import engine.store as S
        src = inspect.getsource(S.MemoryStore.enqueue_embed_job)
        # Comments are allowed to NAME the clamp that was removed; code is not.
        src = "\n".join(line for line in src.splitlines()
                        if not line.strip().startswith("#"))
        self.assertNotIn("[:8000]", src,
                         "an independent clamp is back in the enqueue path: the drain and the "
                         "write path can disagree again")


if __name__ == "__main__":
    unittest.main()
