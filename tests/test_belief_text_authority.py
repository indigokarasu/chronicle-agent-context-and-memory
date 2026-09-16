"""
Chronicle — acceptance tests for A0fix: ONE belief-text authority, no version
laundering, honest convergence and counters.

A0 shipped six defects that all have the same shape: two pieces of code answering
the same question in two places, or a report making a claim wider than the work
it did. These tests pin the fixes so they cannot recur.

  D3 (silent corruption). `HealthEngine.BELIEF_TEXT` was a second, hand-written
     answer to "what text was this vector made of", maintained beside
     `reducer.vector_text` and imported by the heal, migrate_vectors and
     requeue_hash_vectors so the three "could not disagree". It had already
     drifted: it mapped `procedure` to `procedures.name`, which
     tools._t_remember sets to `content[:40]`, while the reducer embedded the
     full `body` — so every tool-written procedure over 40 characters was
     re-embedded from a truncation and stamped with the canonical tag that
     declares the vector correct. There is now exactly one function
     (`reducer.belief_vector_text`), a parity test over EVERY kind in
     `_VECTORED_KINDS`, and a refusal (`recoverable=False`) where the store
     cannot reconstruct the text.
  D1 (cross-model laundering). `canonical_model_id` stripped ANY trailing
     `-vN[.N]`, so `e5-large` == `e5-large-v2`, `bge-large-en` == `-v1.5`,
     MiniLM v1 == v2, arctic-embed-l == -v2.0 — same-width, different-geometry
     models classified `retag` and re-labelled in place. Version suffixes are
     part of the identity now; equivalences come only from `_MODEL_ALIASES`.
  D4 (never converges). A NULL-tagged right-width row classified `reembed`, but
     the walk predicate `model != ?` is NULL for a NULL tag and never selected
     it — the tool reported "remaining: 1, failed: 0" forever.
  D2 (false docstring). The first deferred embed job drained after a backend
     recovery stamped the pre-`recheck()` 'degraded' placeholder.
  D6 (false counter). An aborted batch rolls back but was still counted as
     re-embedded.
  D5-honesty. migrate printed "converged: 100% of vectors" over tables it never
     scanned.

Fixtures use only fake values (Pat Testley, Acme Fake Co) and a hashing
embedder — no network, no model, no paid API.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scripts.migrate_vectors as MV
import scripts.requeue_hash_vectors as RQ
from engine import reducer as R
from engine.config import Config
from engine.embeddings import (
    DegradedEmbedder,
    HashingEmbedder,
    canonical_model_id,
    is_usable_model_tag,
    make_model_tag,
    pack,
)
from engine.health import HealthEngine

DIMS = 16
WANT = DIMS * 4
CANON = "nomic-embed-text[prefixed]"
OTHER = "nvidia/llama-nemotron-embed-vl-1b-v2:free"


class _Fake:
    """A local llama.cpp/ollama stand-in: right-width deterministic vectors, a
    nomic name, `short_for` to make specific texts answer the wrong width."""

    model = "nomic-embed-text:latest"
    dimensions = DIMS
    use_task_prefixes = True
    base_url = "fake://"

    def __init__(self):
        self._h = HashingEmbedder(dimensions=DIMS)
        self.short_for = ()
        self.texts = []

    def _one(self, t):
        self.texts.append(t)
        if any(s in t for s in self.short_for):
            return [0.1] * (DIMS // 2)
        return self._h.embed(t)

    def embed(self, t):
        return self._one(t)

    def embed_document(self, t):
        return self._one("search_document: " + (t or ""))

    def embed_query(self, t):
        return self._one("search_query: " + (t or ""))

    def embed_batch(self, ts, chunk=64):
        return [self.embed_document(t) for t in ts]

    def model_tag(self):
        return make_model_tag(self.model, True)

    def model_with_prefix_marker(self):
        return self.model_tag()


def _expect(text):
    """The blob the reducer writes for `text` — the document side, prefixed."""
    return pack(HashingEmbedder(dimensions=DIMS).embed("search_document: " + (text or "")))


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a0fix_")
        from engine.core import ChronicleCore
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing",
                                                            "dimensions": DIMS}})
        self.emb = _Fake()
        self.core.embedder = self.emb
        self.core.reducer.embedder = self.emb
        self.core.retrieval.embedder = self.emb
        self.core.initialize("s1", principal_id="assistant")
        self.core.capture.observe("I am Pat Testley\nI work at Acme Fake Co\n"
                                  "I live in Springfield", "", session_id="s1")
        self.core.process_pending()
        self.core.curation.drain()
        self.conn = self.core.store._conn()
        self.cfg = Config({"embeddings": {"model": "hashing", "dimensions": DIMS}})

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _assert(self, kind, key, body):
        """Assert a belief through the real capture/reduce path and return its id."""
        self.core.capture.append("asserted",
                                 {"kind": kind, "key": key, "body": body, "confidence": 0.9,
                                  "source_event": "tool", "source_type": "agent_memory_write",
                                  "salience": "normal"},
                                 actor="agent", trust_level=3)
        self.core.process_pending()
        self.core.curation.drain()
        row = self.conn.execute(
            "SELECT belief_id FROM memory_vectors WHERE kind=? ORDER BY rowid DESC LIMIT 1",
            (kind,)).fetchone()
        self.assertIsNotNone(row, "no vector written for kind=%s" % kind)
        return row[0]

    def _migrate(self, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = MV.migrate(self.core.store.db_path, cfg=self.cfg, embedder=self.emb,
                            verbose=True, **kw)
        return rc, buf.getvalue()

    def _break_row(self, belief_id, kind):
        """Give a row a foreign tag and a foreign width so both the heal and the
        migration tool must repair it."""
        with self.core.store.transaction() as c:
            c.execute("UPDATE memory_vectors SET model=?, embedding=? "
                      "WHERE belief_id=? AND kind=?", (OTHER, pack([0.02] * 2048),
                                                       belief_id, kind))

    def _vec(self, belief_id, kind):
        return self.conn.execute(
            "SELECT embedding, model FROM memory_vectors WHERE belief_id=? AND kind=?",
            (belief_id, kind)).fetchone()


# ==========================================================================
# D3 — one belief-text authority
# ==========================================================================
class TestSingleBeliefTextAuthority(unittest.TestCase):
    """Structural: there is ONE function, and every re-embedding site uses it."""

    def test_the_second_map_is_gone(self):
        self.assertFalse(hasattr(HealthEngine, "BELIEF_TEXT"),
                         "HealthEngine.BELIEF_TEXT is back: a second, hand-maintained "
                         "answer to what text a vector was made of is exactly the defect")
        self.assertFalse(hasattr(MV, "_BELIEF_TEXT"))
        self.assertFalse(hasattr(RQ, "_BELIEF_TEXT"))
        self.assertFalse(hasattr(MV, "_belief_text"))
        self.assertFalse(hasattr(MV, "_observed_text"))

    def test_every_consumer_calls_the_same_function_object(self):
        import engine.health as H
        for mod in (H, MV, RQ):
            self.assertIs(mod.belief_vector_text, R.belief_vector_text,
                          "%s resolves belief text through a different function" % mod.__name__)
            self.assertIs(mod.observed_vector_text, R.observed_vector_text)

    def test_source_map_covers_every_vectored_kind(self):
        """A new vectored kind cannot be added without telling the authority where
        its text lives — the failure mode is a loud KeyError-shaped test failure,
        not a silent near-miss."""
        self.assertEqual(set(R.BELIEF_VECTOR_SOURCE), set(R._VECTORED_KINDS))

    def test_reducer_method_delegates_to_the_module_function(self):
        """The reducer's own write path and the module-level authority must be the
        same expression, not two copies of it."""
        payload = {"kind": "fact", "key": {"name": "n", "topic": "t"}, "body": "the body"}
        red = R.Reducer.__dict__["vector_text"]
        self.assertEqual(red(None, "asserted", payload), R.vector_text("asserted", payload))


class TestKindParity(_StoreCase):
    """The behavioural half of D3: for EVERY vectored kind, the text the authority
    recovers is byte-identical to the text the reducer embedded."""

    CASES = {
        "fact": ({"entity_id": "e1", "predicate": "employer", "subject": "Pat Testley"},
                 "Pat Testley works at Acme Fake Co, in the Springfield office"),
        "episode": ({"title": "Springfield trip"},
                    "Pat Testley visited the Acme Fake Co Springfield office for two days"),
        "note": ({"subject": "acme-notes", "note_type": "belief"},
                 "Acme Fake Co bills on the 1st; Pat Testley approves the invoice"),
        "reference": ({"topic": "Acme widget press manual",
                       "retrieval_url": "https://example.invalid/manual"},
                      "The Acme widget press manual covers calibration and the safety interlock"),
        # The defect's own shape: key.name is content[:40], body is the full text.
        "procedure": (None,
                      "Deploy the billing module: run the smoke suite, then bump the "
                      "version tag, then announce it in the ops channel"),
    }

    def test_every_kind_round_trips(self):
        for kind, (key, body) in self.CASES.items():
            with self.subTest(kind=kind):
                k = dict(key) if key else {}
                if kind == "procedure":
                    k = {"name": body[:40]}      # verbatim tools._t_remember
                bid = self._assert(kind, k, body)
                blob = self._vec(bid, kind)[0]
                self.assertEqual(blob, _expect(body),
                                 "reducer did not embed the body for kind=%s" % kind)
                text, recoverable = R.belief_vector_text(self.conn, kind, bid)
                self.assertTrue(recoverable, "authority refused a recoverable %s" % kind)
                self.assertEqual(text, body,
                                 "authority recovered DIFFERENT text than was embedded "
                                 "for kind=%s" % kind)
                self.assertEqual(pack(self.emb.embed_document(text)), blob)

    def test_reference_with_no_body_falls_back_to_topic_exactly_as_the_reducer_does(self):
        """`body or key.name or key.topic` is one expression, so the recovery side
        follows the same fallback instead of guessing which field was used."""
        bid = self._assert("reference", {"topic": "Acme widget press manual",
                                         "retrieval_url": "https://example.invalid/m"}, "")
        blob = self._vec(bid, "reference")[0]
        self.assertEqual(blob, _expect("Acme widget press manual"))
        text, recoverable = R.belief_vector_text(self.conn, "reference", bid)
        self.assertTrue(recoverable)
        self.assertEqual(text, "Acme widget press manual")

    def test_migrate_reembeds_a_procedure_from_its_body_not_its_name(self):
        """The exact silent corruption: a >40-char procedure, re-embedded."""
        body = self.CASES["procedure"][1]
        bid = self._assert("procedure", {"name": body[:40]}, body)
        name = self.conn.execute("SELECT name FROM procedures WHERE belief_id=?",
                                 (bid,)).fetchone()[0]
        self.assertEqual(name, body[:40])
        self.assertNotEqual(_expect(name), _expect(body))
        self._break_row(bid, "procedure")
        rc, _out = self._migrate()
        blob, tag = self._vec(bid, "procedure")
        self.assertEqual(rc, 0)
        self.assertEqual(tag, CANON)
        self.assertEqual(blob, _expect(body),
                         "migrate re-embedded a DIFFERENT text than the reducer did")
        self.assertNotEqual(blob, _expect(name))

    def test_heal_requeues_a_procedure_with_its_body_not_its_name(self):
        body = self.CASES["procedure"][1]
        bid = self._assert("procedure", {"name": body[:40]}, body)
        self._break_row(bid, "procedure")
        self.core.health._embedder_mismatch_heal()
        queued = [json.loads(r[0]) for r in self.conn.execute(
            "SELECT payload FROM curation_jobs WHERE task='embed'").fetchall()]
        texts = [j["text"] for j in queued if j.get("kind") == "procedure"]
        self.assertEqual(texts, [body], "the heal queued a truncated text")
        self.core.curation.drain()
        self.assertEqual(self._vec(bid, "procedure")[0], _expect(body))


class TestUnrecoverableIsRefusedNotGuessed(_StoreCase):
    """The storage-gap decision, stated as behaviour.

    `procedures.body` (schema_version 12) closes the gap for everything written
    from now on. A row that predates it holds NULL — an honest unknown — and is
    recovered from its source event when that event still corroborates the row,
    or REFUSED. It is never backfilled from `procedures.name`, because the name
    is the 40-char truncation that caused the defect."""

    def _make_pre_schema12(self, drop_event):
        body = ("Deploy the billing module: run the smoke suite, then bump the version "
                "tag, then announce it in the ops channel")
        bid = self._assert("procedure", {"name": body[:40]}, body)
        with self.core.store.transaction() as c:
            c.execute("UPDATE procedures SET body=NULL WHERE belief_id=?", (bid,))
            if drop_event:
                c.execute("DELETE FROM events WHERE event_id IN "
                          "(SELECT json_extract(provenance,'$.source_event') FROM procedures "
                          " WHERE belief_id=?)", (bid,))
        return bid, body

    def test_recovered_from_the_source_event_when_it_corroborates(self):
        bid, body = self._make_pre_schema12(drop_event=False)
        text, recoverable = R.belief_vector_text(self.conn, "procedure", bid)
        self.assertTrue(recoverable)
        self.assertEqual(text, body)

    def test_refused_when_the_event_is_gone(self):
        bid, body = self._make_pre_schema12(drop_event=True)
        text, recoverable = R.belief_vector_text(self.conn, "procedure", bid)
        self.assertFalse(recoverable, "guessed at a body the store does not hold")
        self.assertEqual(text, "")
        self.assertNotEqual(text, body[:40])

    def test_migrate_leaves_an_unrecoverable_row_exactly_as_it_was(self):
        bid, _body = self._make_pre_schema12(drop_event=True)
        self._break_row(bid, "procedure")
        before = self._vec(bid, "procedure")
        rc, out = self._migrate()
        after = self._vec(bid, "procedure")
        self.assertEqual(tuple(after), tuple(before),
                         "an unrecoverable row was rewritten instead of left alone")
        self.assertEqual(rc, 2)
        self.assertIn("failed     : 1", out)
        self.assertIn("procedure:" + bid, out)

    def test_heal_skips_an_unrecoverable_row_without_queueing_a_truncation(self):
        bid, body = self._make_pre_schema12(drop_event=True)
        self._break_row(bid, "procedure")
        self.core.health._embedder_mismatch_heal()
        queued = [json.loads(r[0]) for r in self.conn.execute(
            "SELECT payload FROM curation_jobs WHERE task='embed'").fetchall()]
        for job in queued:
            self.assertNotEqual(job.get("text"), body[:40],
                                "the heal queued the 40-char name as if it were the body")
            self.assertNotEqual(job.get("target_id"), bid)


# ==========================================================================
# D1 — no version laundering
# ==========================================================================
class TestNoVersionLaundering(unittest.TestCase):
    # The reviewer's collapse table: pairs that a generic `-vN` strip merged and
    # that the width clause CANNOT separate, because both members are the same
    # width. Each pair must stay two identities.
    DISTINCT_PAIRS = [
        ("e5-large", "e5-large-v2"),                                  # both 1024
        ("bge-large-en", "bge-large-en-v1.5"),                        # both 1024
        ("all-MiniLM-L6-v1", "all-MiniLM-L6-v2"),                     # both 384
        ("snowflake-arctic-embed-l", "snowflake-arctic-embed-l-v2.0"),
        ("gte-base", "gte-base-v1.5"),
        ("jina-embeddings-v2", "jina-embeddings-v3"),
    ]

    def test_same_width_different_model_is_not_collapsed(self):
        for a, b in self.DISTINCT_PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(canonical_model_id(a), canonical_model_id(b),
                                    "%r and %r collapsed to one identity: a store embedded "
                                    "by one and read by the other would be RETAGGED in "
                                    "place, not re-embedded" % (a, b))

    def test_a_version_bearing_name_is_not_mangled(self):
        """`jina-embeddings-v3` IS the model's name; the version is not a suffix
        that can be dropped without naming a model that does not exist."""
        self.assertEqual(canonical_model_id("jina-embeddings-v3"), "jina-embeddings-v3")
        self.assertEqual(canonical_model_id("e5-large-v2"), "e5-large-v2")
        self.assertEqual(canonical_model_id("bge-large-en-v1.5"), "bge-large-en-v1.5")

    def test_mismatch_classification_for_a_collapsed_pair(self):
        """End to end through `classify`: same width, different version -> reembed,
        never retag. `retag` is a promise that the BYTES are already right."""
        for a, b in self.DISTINCT_PAIRS:
            with self.subTest(pair=(a, b)):
                self.assertEqual(MV.classify(a, 4096, b, 4096), "reembed")

    # The builder's original table — the equivalences that must STILL hold, so
    # the fix for D1 does not become a regression of A0b.
    def test_the_declared_alias_family_still_converges(self):
        for name in ("nomic-embed-text",
                     "nomic-embed-text:latest",
                     "nomic-embed-text-v1",
                     "nomic-embed-text-v1.5",
                     "NOMIC-EMBED-TEXT",
                     "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf",
                     "/opt/models/nomic-embed-text-v1.5.f16.gguf",
                     "  nomic-embed-text  "):
            with self.subTest(name=name):
                self.assertEqual(canonical_model_id(name), "nomic-embed-text")

    def test_the_alias_table_is_closed_and_idempotent(self):
        """Every alias resolves in ONE hop — a table where a value is itself a key
        would make identity depend on how many times it was applied."""
        from engine.embeddings import _MODEL_ALIASES
        for src, dst in _MODEL_ALIASES.items():
            self.assertNotIn(dst, _MODEL_ALIASES, "alias %r chains through %r" % (src, dst))
            self.assertEqual(canonical_model_id(dst), dst)
            self.assertEqual(canonical_model_id(src), dst)

    def test_hashing_family_and_placeholders_unchanged(self):
        for name in ("hashing", "offline", "none", "hashing-v1", "Hashing:latest"):
            self.assertEqual(canonical_model_id(name), "hashing-v1")
        self.assertEqual(canonical_model_id("hashing-v2"), "hashing-v2")
        for name in ("auto", "", "local", "default", None):
            self.assertEqual(canonical_model_id(name), "auto")

    def test_usable_tag_predicate_is_identity_based(self):
        self.assertFalse(is_usable_model_tag("degraded"))
        self.assertFalse(is_usable_model_tag("degraded[prefixed]"))
        self.assertFalse(is_usable_model_tag("auto"))
        self.assertFalse(is_usable_model_tag(""))
        self.assertFalse(is_usable_model_tag(None))
        self.assertTrue(is_usable_model_tag(CANON))


# ==========================================================================
# D4 — a NULL model tag must converge
# ==========================================================================
class TestNullTagConverges(_StoreCase):
    def test_null_tag_right_width_row_is_repaired_in_one_run(self):
        eid = self.conn.execute("SELECT event_id FROM observed_vectors LIMIT 1").fetchone()[0]
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET model=NULL WHERE event_id=?", (eid,))
        plan = MV.survey(self.conn, CANON, WANT)
        actions = [a for rows in plan.values() for tag, _b, _c, a in rows if tag is None]
        self.assertEqual(actions, ["reembed"], "survey no longer classifies a NULL tag")

        rc, out = self._migrate()
        tag = self.conn.execute("SELECT model FROM observed_vectors WHERE event_id=?",
                                (eid,)).fetchone()[0]
        self.assertEqual(tag, CANON,
                         "the NULL-tagged row survived the run: the walk predicate is "
                         "selecting with `!=`, which is never true against NULL")
        self.assertEqual(rc, 0)
        self.assertIn("converged", out)

    def test_null_tag_wrong_width_row_is_repaired_too(self):
        eid = self.conn.execute("SELECT event_id FROM observed_vectors LIMIT 1").fetchone()[0]
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET model=NULL, embedding=? WHERE event_id=?",
                      (pack([0.02] * 2048), eid))
        rc, _out = self._migrate()
        row = self.conn.execute("SELECT model, length(embedding) FROM observed_vectors "
                                "WHERE event_id=?", (eid,)).fetchone()
        self.assertEqual((row[0], row[1]), (CANON, WANT))
        self.assertEqual(rc, 0)

    def test_retag_of_a_null_tag_group_actually_changes_rows(self):
        """`model = ?` is NULL against NULL, so the retag UPDATE matched nothing and
        the tool reported success having changed no row."""
        eid = self.conn.execute("SELECT event_id FROM observed_vectors LIMIT 1").fetchone()[0]
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET model=NULL WHERE event_id=?", (eid,))
        m = MV.Migrator(self.core.store, self.emb, verbose=False)
        m.retag({"observed_vectors": [(None, WANT, 1, "retag")]})
        self.assertEqual(m.retagged, 1)
        self.assertEqual(self.conn.execute(
            "SELECT model FROM observed_vectors WHERE event_id=?", (eid,)).fetchone()[0], CANON)


# ==========================================================================
# D2 — 'degraded' is never stamped
# ==========================================================================
class TestDegradedIsNeverStamped(unittest.TestCase):
    """`DegradedEmbedder.model_tag` says the placeholder is never stamped on a
    row. It was: `_task_embed` resolved the tag BEFORE `recheck()` adopted a live
    backend, so the first job drained after a recovery was written under
    'degraded' — a row claiming a geometry that does not exist."""

    def setUp(self):
        from engine import embeddings as E
        self.E = E
        self._probe = E._probe_endpoints
        self.home = tempfile.mkdtemp(prefix="a0fix_degraded_")

    def tearDown(self):
        self.E._probe_endpoints = self._probe
        shutil.rmtree(self.home, ignore_errors=True)

    def test_recovery_drain_stamps_the_live_tag(self):
        from engine.core import ChronicleCore
        core = ChronicleCore(self.home, {"embeddings": {"model": "hashing", "dimensions": DIMS}})
        core.initialize("s1", principal_id="assistant")
        # The "no backend" half is INJECTED, not dialled. This used to point
        # base_url at 127.0.0.1:9 (the discard port) and rely on the connection
        # failing -- which is a network call in a unit test, behaves differently
        # on a host that has something on port 9, and is exactly what A11's
        # hermetic harness forbids. `_probe_endpoints` returning None IS the
        # "nothing reachable" outcome, and it is the same seam the recovery half
        # below already uses, so both halves of this test are now controlled the
        # same way.
        self.E._probe_endpoints = lambda *a, **k: None
        deg = DegradedEmbedder(model="auto", dimensions=DIMS,
                               base_url="http://embedder.invalid/v1", recheck_seconds=0.0)
        core.embedder = deg
        core.reducer.embedder = deg
        core.retrieval.embedder = deg
        core.capture.observe("I am Pat Testley\nI work at Acme Fake Co", "", session_id="s1")
        core.process_pending()
        conn = core.store._conn()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM observed_vectors").fetchone()[0], 0,
                         "a degraded embedder wrote a vector")
        self.assertGreater(conn.execute(
            "SELECT COUNT(*) FROM curation_jobs WHERE task='embed' AND status='pending'"
        ).fetchone()[0], 0)

        self.E._probe_endpoints = lambda *a, **k: _Fake()
        with core.store.transaction() as c:
            c.execute("UPDATE curation_jobs SET run_after=NULL "
                      "WHERE task='embed' AND status='pending'")
        core.curation.drain()

        for table in ("observed_vectors", "memory_vectors", "query_proxy_vectors"):
            bad = conn.execute("SELECT COUNT(*) FROM %s WHERE model IN ('degraded','auto','')"
                               % table).fetchone()[0]
            self.assertEqual(bad, 0, "%s carries a placeholder tag" % table)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM observed_vectors WHERE model=?",
                                        (CANON,)).fetchone()[0], 0)


# ==========================================================================
# D6 — an aborted batch is not counted as re-embedded
# ==========================================================================
class TestAbortedBatchIsNotCounted(_StoreCase):
    def _clone_rows(self, n=40):
        ev = dict(self.conn.execute(
            "SELECT * FROM events WHERE type='observed' LIMIT 1").fetchone())
        with self.core.store.transaction() as c:
            maxseq = c.execute("SELECT MAX(seq) FROM events").fetchone()[0]
            for k in range(1, n + 1):
                p = json.loads(ev["payload"])
                p["excerpt"] = "clone text %02d" % k
                nid = "ev_clone_%02d" % k
                c.execute(
                    "INSERT INTO events(event_id,seq,order_key,type,payload,parents,actor,"
                    "owner,trust_level,session_id,branch_id,occurred_at,recorded_at,prev_head,"
                    "sig) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (nid, maxseq + k, ev["order_key"], ev["type"], json.dumps(p),
                     ev["parents"], ev["actor"], ev["owner"], ev["trust_level"],
                     ev["session_id"], ev["branch_id"], ev["occurred_at"], ev["recorded_at"],
                     ev["prev_head"], ev["sig"]))
                c.execute("INSERT INTO observed_vectors(event_id,embedding,model,owner,"
                          "created_at) VALUES(?,?,?,?,?)",
                          (nid, pack([0.02] * 2048), OTHER, "default", "2026-01-01T00:00:00Z"))
            c.execute("UPDATE meta SET value=(SELECT MAX(seq) FROM events) WHERE key='event_seq'")
            c.execute("UPDATE observed_vectors SET model=? WHERE event_id NOT LIKE 'ev_clone_%'",
                      (CANON,))

    def _noncanonical(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM observed_vectors WHERE model IS NOT ? "
            "OR length(embedding) IS NOT ?", (CANON, WANT)).fetchone()[0]

    def test_reported_count_never_exceeds_rows_actually_repaired(self):
        self._clone_rows()
        # Clones 10..19 answer the wrong width: 5 consecutive refusals abort the
        # run from INSIDE the batch transaction, which then rolls back.
        self.emb.short_for = tuple("clone text %02d" % k for k in range(10, 20))
        before = self._noncanonical()
        rc, out = self._migrate(batch=16)
        after = self._noncanonical()
        repaired = before - after
        reported = int([line for line in out.splitlines()
                        if line.startswith("re-embedded")][0].split(":")[1])
        self.assertEqual(rc, 2)
        self.assertIn("STOPPED", out)
        self.assertLessEqual(reported, repaired,
                             "summary claims %d re-embedded but only %d rows changed: the "
                             "rolled-back batch was still counted" % (reported, repaired))
        # And the store is still consistent: nothing half-written under the tag.
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM observed_vectors WHERE model=? AND length(embedding)!=?",
            (CANON, WANT)).fetchone()[0], 0)

    def test_a_committed_batch_is_counted(self):
        """The counter must still count — the fix is banking on commit, not
        refusing to count."""
        self._clone_rows(n=8)
        before = self._noncanonical()
        rc, out = self._migrate(batch=16)
        reported = int([line for line in out.splitlines()
                        if line.startswith("re-embedded")][0].split(":")[1])
        self.assertEqual(rc, 0)
        self.assertEqual(reported, before - self._noncanonical())
        self.assertGreater(reported, 0)


# ==========================================================================
# D5-honesty — the convergence claim covers only what was scanned
# ==========================================================================
class TestConvergenceClaimIsScoped(_StoreCase):
    """The scope claim, and the DISCOVERY that keeps it true.

    A0fix wrote these against a scan set of three tables, using `session_index`
    and `projection_vectors` as the "outside the scan" examples. A0e brought
    both INTO the scan set, and the point of discovering the boundary rather
    than listing it is that these tests then had to move with it: the tool now
    names five tables in its claim and the two former examples must have fallen
    out of the NOT-SCANNED list on their own. What is left outside is
    `entity_centroids.sum_vec` — an accumulated SUM of mention vectors, not an
    embedding of any recoverable text — so it is what stands in for "something
    this tool did not check" here.
    """

    OUTSIDE = "entity_centroids"

    def _wide_row_outside_the_scan(self):
        """A wrong-width blob in the one vector-bearing table nobody scans."""
        with self.core.store.transaction() as c:
            c.execute("INSERT OR REPLACE INTO entity_centroids(entity_id,sum_vec,n,dims,"
                      "model,updated_at) VALUES(?,?,?,?,?,?)",
                      ("ent_wide", pack([0.01] * 2048), 1, 2048, OTHER,
                       "2026-01-01T00:00:00Z"))

    def _work_inside_the_scan(self):
        """Real work in a table the tool DOES scan, so a run reaches the
        CONVERGED claim rather than the "nothing to do" short-circuit."""
        with self.core.store.transaction() as c:
            c.execute("UPDATE observed_vectors SET model=?, embedding=?",
                      (OTHER, pack([0.02] * 2048)))

    def test_unscanned_tables_are_discovered_and_named(self):
        found = {t for t, _r, _w, _e in MV.unscanned_vector_tables(self.conn)}
        self.assertIn(self.OUTSIDE, found)
        for t in MV._TABLES:
            self.assertNotIn(t, found)

    def test_bringing_a_table_into_the_scan_removes_it_from_the_disclaimer(self):
        """The A0e property, asserted directly: the two tables A0fix listed as
        NOT SCANNED are now scanned, and the disclaimer shrank by itself. If
        someone re-typed the discovery as a hand-written list, this fails."""
        found = {t for t, _r, _w, _e in MV.unscanned_vector_tables(self.conn)}
        self.assertNotIn("session_index", found)
        self.assertNotIn("projection_vectors", found)
        self.assertIn("session_index", MV._TABLES)
        self.assertIn("projection_vectors", MV._TABLES)

    def test_the_claim_names_the_tables_it_covers_and_lists_the_rest(self):
        self._wide_row_outside_the_scan()
        self._work_inside_the_scan()
        rc, out = self._migrate()
        self.assertIn("NOT SCANNED", out)
        self.assertIn(self.OUTSIDE, out)
        # The old claim was unqualified over a store this tool never fully saw.
        self.assertNotIn("converged: 100% of vectors carry", out)
        self.assertIn("converged: 100%% of vectors in %s" % ", ".join(MV._TABLES), out)
        # ...and the claim really does name all five now, session_index and
        # projection_vectors among them.
        self.assertIn("session_index", out)
        self.assertIn("projection_vectors", out)
        # The wrong-width row outside the scan is named, and the clean exit is
        # explicitly scoped rather than silently implying the whole store.
        self.assertIn("expected", out)
        self.assertIn("NOT repaired by it", out)
        self.assertEqual(rc, 0, "the exit code is the verdict on the work this tool DOES; "
                                "a table it never scans cannot be cleared by re-running it")

    def test_a_clean_store_still_exits_zero_and_says_converged(self):
        self._work_inside_the_scan()
        rc, out = self._migrate()
        self.assertEqual(rc, 0)
        self.assertIn("converged", out)
        self.assertNotIn("NOT repaired by it", out)

    def test_the_nothing_to_do_line_is_scoped_too(self):
        """The short-circuit makes the same claim as the converged path and must
        be scoped the same way."""
        rc, out = self._migrate()
        self.assertEqual(rc, 0)
        self.assertIn("nothing to do — every vector in %s is already canonical"
                      % ", ".join(MV._TABLES), out)

    def test_dry_run_reports_the_same_boundary(self):
        self._wide_row_outside_the_scan()
        rc, out = self._migrate(dry_run=True)
        self.assertEqual(rc, 0, "a dry run classifies; it must not take a verdict's exit code")
        self.assertIn("[dry-run] NOT SCANNED", out)
        self.assertIn(self.OUTSIDE, out)

    def test_a_blob_that_is_not_an_embedding_is_never_width_judged(self):
        """A BLOB with no expected width — a signature, a compressed payload —
        must still be LISTED (honesty) but never flagged for its length. Judging
        one would turn an honest boundary report into a false alarm that no
        re-run can clear.

        Asserted against a real table rather than by inspection, because the
        rule is a column-NAMING rule and only an actual non-embedding column
        exercises it."""
        with self.core.store.transaction() as c:
            c.execute("CREATE TABLE IF NOT EXISTS fake_signatures ("
                      "id TEXT PRIMARY KEY, sig BLOB)")
            c.execute("INSERT OR REPLACE INTO fake_signatures VALUES(?,?)",
                      ("sig1", b"\x01" * 999))
        rows = {t: (r, w, e) for t, r, w, e in MV.unscanned_vector_tables(self.conn)}
        self.assertIn("fake_signatures", rows, "a BLOB-bearing table went unlisted")
        _r, widths, is_emb = rows["fake_signatures"]
        self.assertFalse(is_emb, "a column named `sig` was treated as an embedding")
        self.assertEqual(widths, [999])
        # entity_centroids.sum_vec IS named like a vector, so it stays judgeable.
        self.assertTrue(rows[self.OUTSIDE][2])
        # And a 999-byte non-embedding never produces the wrong-width warning.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            MV.print_unscanned(MV.unscanned_vector_tables(self.conn), WANT)
        out = buf.getvalue()
        self.assertIn("fake_signatures", out)
        self.assertNotIn("999-byte blobs; expected", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
