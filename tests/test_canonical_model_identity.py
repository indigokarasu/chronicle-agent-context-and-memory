"""
Chronicle — acceptance tests for A0a: canonical embedder model identity.

The live defect: ONE model reports itself under three names depending on who
is asked (ollama "nomic-embed-text:latest", llama.cpp
"/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf", an explicit pin
"nomic-embed-text"), each with or without the E1 "[prefixed]" marker. Every
raw-string tag comparison in the engine therefore saw a permanent mismatch
between rows written by the SAME model.

Two things are checked here:
  (a) a table of real-world names -> canonical ids (including idempotence), and
      -- since A0fix/D1 -- that a VERSION is never stripped: an equivalence
      between two version-bearing names exists only where the project declares
      one in embeddings._MODEL_ALIASES,
  (b) that every vector-stamping site really goes through the ONE choke point:
      a full capture -> process flow under an embedder whose reported name is a
      gguf PATH must leave a store in which every stamped tag equals
      embedder_model_tag(embedder) -- scanned store-wide, not spot-checked.

Fixtures use only fake values (Pat Testley, Acme Fake Co).
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import (
    DegradedEmbedder,
    HashingEmbedder,
    OpenAICompatEmbedder,
    canonical_model_id,
    embedder_model_tag,
    expected_blob_len,
    make_model_tag,
    split_model_tag,
)

# The gguf PATH form llama.cpp --embedding reports for itself when
# `embeddings.model: auto` asks the server what it serves.
GGUF_PATH = "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf"

# name as reported/configured -> canonical id
CANONICAL_TABLE = [
    # -- the three live names of the ONE deployed model --------------------
    ("nomic-embed-text", "nomic-embed-text"),
    ("nomic-embed-text:latest", "nomic-embed-text"),
    (GGUF_PATH, "nomic-embed-text"),
    # same model, other quantizations / weight files
    ("/opt/llama-embed/nomic-embed-text-v1.5.f16.gguf", "nomic-embed-text"),
    ("/opt/llama-embed/nomic-embed-text-v1.5.Q4_K_M.gguf", "nomic-embed-text"),
    ("nomic-embed-text-v1.5", "nomic-embed-text"),
    ("nomic-embed-text-v1", "nomic-embed-text"),
    ("nomic-ai/nomic-embed-text-v1.5", "nomic-embed-text"),
    ("NOMIC-EMBED-TEXT:LATEST", "nomic-embed-text"),
    ("nomic-embed-text[prefixed]", "nomic-embed-text"),
    (r"C:\models\nomic-embed-text-v1.5.Q8_0.gguf", "nomic-embed-text"),
    # -- the OLD model 88% of the live store is tagged with ----------------
    # A0fix/D1: the version is KEPT. The provider prefix and the ":free" routing
    # tag are noise about WHERE the model was served; "-v2" is part of WHICH
    # model it is. An earlier build stripped any trailing "-vN", which made
    # `<model>-v1` and `<model>-v2` one identity -- and since the width clause
    # cannot separate two same-width versions, a store embedded under one and
    # read by the other was classified `retag` and re-labelled in place instead
    # of re-embedded. Version suffixes are identity; only _MODEL_ALIASES
    # declares an equivalence (today: nomic-embed-text v1/v1.5/bare).
    ("nvidia/llama-nemotron-embed-vl-1b-v2:free", "llama-nemotron-embed-vl-1b-v2"),
    ("llama-nemotron-embed-vl-1b-v2", "llama-nemotron-embed-vl-1b-v2"),
    # -- other real embedding models ---------------------------------------
    ("mxbai-embed-large:latest", "mxbai-embed-large"),
    ("mxbai-embed-large-v1", "mxbai-embed-large-v1"),     # v1 != a future v2
    ("BAAI/bge-m3", "bge-m3"),
    ("bge-large-en-v1.5", "bge-large-en-v1.5"),           # 1024-dim, and so is v1
    ("intfloat/multilingual-e5-large", "multilingual-e5-large"),
    ("text-embedding-3-small", "text-embedding-3-small"),   # "-small" is not a version
    ("text-embedding-3-large", "text-embedding-3-large"),
    ("snowflake-arctic-embed:335m", "snowflake-arctic-embed"),
    # -- offline hashing family --------------------------------------------
    ("hashing", "hashing-v1"),
    ("hashing-v1", "hashing-v1"),
    ("offline", "hashing-v1"),
    ("none", "hashing-v1"),
    ("hashing-v2", "hashing-v2"),      # a deliberate variant is NEVER folded into v1
    # -- placeholders, not identities --------------------------------------
    ("auto", "auto"),
    ("", "auto"),
    ("   ", "auto"),
    (None, "auto"),
    ("default", "auto"),
    ("local", "auto"),
]


class TestCanonicalModelIdTable(unittest.TestCase):
    def test_table(self):
        for name, expected in CANONICAL_TABLE:
            with self.subTest(name=name):
                self.assertEqual(canonical_model_id(name), expected)

    def test_idempotent(self):
        for name, _expected in CANONICAL_TABLE:
            once = canonical_model_id(name)
            self.assertEqual(canonical_model_id(once), once, name)

    def test_the_three_live_names_are_one_id(self):
        ids = {canonical_model_id(n) for n in
               ("nomic-embed-text", "nomic-embed-text:latest", GGUF_PATH)}
        self.assertEqual(len(ids), 1, ids)

    def test_different_families_stay_different(self):
        self.assertNotEqual(canonical_model_id(GGUF_PATH),
                            canonical_model_id("nvidia/llama-nemotron-embed-vl-1b-v2:free"))

    def test_unrecognizable_name_survives_rather_than_blanking(self):
        # Never return "" for a real name: an unknown model must stay
        # comparable to itself, or the mismatch rule can't classify it at all.
        self.assertEqual(canonical_model_id("Weird_Model_9000"), "weird_model_9000")

    def test_make_and_split_round_trip(self):
        tag = make_model_tag(GGUF_PATH, True)
        self.assertEqual(tag, "nomic-embed-text[prefixed]")
        self.assertEqual(split_model_tag(tag), ("nomic-embed-text", True))
        self.assertEqual(split_model_tag("nomic-embed-text"), ("nomic-embed-text", False))
        # A legacy raw tag classifies exactly like the canonical one.
        self.assertEqual(split_model_tag(GGUF_PATH + "[prefixed]"), ("nomic-embed-text", True))
        self.assertEqual(split_model_tag("nomic-embed-text:latest"), ("nomic-embed-text", False))


class TestEmbedderModelTag(unittest.TestCase):
    def test_openai_compat_keeps_raw_wire_name_but_canonical_tag(self):
        emb = OpenAICompatEmbedder("http://localhost:8080/v1", GGUF_PATH, 768)
        self.assertEqual(emb.model, GGUF_PATH)          # what goes on the wire
        self.assertTrue(emb.use_task_prefixes)          # nomic -> E1 prefixes on
        self.assertEqual(emb.model_tag(), "nomic-embed-text[prefixed]")
        self.assertEqual(emb.model_with_prefix_marker(), emb.model_tag())
        self.assertEqual(embedder_model_tag(emb), "nomic-embed-text[prefixed]")

    def test_ollama_and_llamacpp_names_agree_on_the_tag(self):
        a = OpenAICompatEmbedder("http://localhost:11434/v1", "nomic-embed-text:latest", 768)
        b = OpenAICompatEmbedder("http://127.0.0.1:8080/v1", GGUF_PATH, 768)
        self.assertEqual(a.model_tag(), b.model_tag())

    def test_prefixes_off_drops_the_marker(self):
        emb = OpenAICompatEmbedder("http://localhost:8080/v1", GGUF_PATH, 768, task_prefixes=False)
        self.assertEqual(emb.model_tag(), "nomic-embed-text")

    def test_hashing_tag_is_stable(self):
        self.assertEqual(HashingEmbedder().model_tag(), "hashing-v1")
        self.assertEqual(HashingEmbedder(model="offline").model_tag(), "hashing-v1")
        self.assertEqual(HashingEmbedder(model="hashing-v2").model_tag(), "hashing-v2")
        # A nomic-NAMED hashing embedder still never prefixes (E1).
        self.assertEqual(HashingEmbedder(model="nomic-embed-text").model_tag(), "nomic-embed-text")

    def test_degraded_tag(self):
        emb = DegradedEmbedder(model="auto", dimensions=768, base_url="http://127.0.0.1:9/v1")
        self.assertEqual(emb.model_tag(), "degraded")

    def test_choke_point_canonicalizes_a_duck_typed_embedder(self):
        """A third-party/legacy embedder that only implements the pre-A0
        method still cannot put a non-canonical tag into the store."""

        class _Legacy:
            model = GGUF_PATH
            dimensions = 8

            def model_with_prefix_marker(self):
                return GGUF_PATH + "[prefixed]"

        self.assertEqual(embedder_model_tag(_Legacy()), "nomic-embed-text[prefixed]")

        class _Ancient:            # predates E1 entirely: only .model
            model = "nomic-embed-text:latest"
            dimensions = 8

        self.assertEqual(embedder_model_tag(_Ancient()), "nomic-embed-text")
        self.assertEqual(embedder_model_tag(None), "")

    def test_expected_blob_len(self):
        self.assertEqual(expected_blob_len(HashingEmbedder(dimensions=256)), 1024)
        # A2: base_url must now be a real, on-host URL -- the placeholder "u"
        # this used to pass is refused as unresolvable (fail closed). The
        # assertion is about blob width, so a loopback URL preserves its intent.
        self.assertEqual(
            expected_blob_len(OpenAICompatEmbedder("http://127.0.0.1:11434/v1", "m", 768)), 3072)

        class _NoDims:
            pass

        self.assertEqual(expected_blob_len(_NoDims()), 0)


class _GgufNamedEmbedder:
    """Hashing-backed but reports itself as a gguf FILE PATH, exactly like the
    deployed llama.cpp server under `embeddings.model: auto`. Deliberately
    implements ONLY the pre-A0 duck-typed surface (no model_tag) so the test
    proves the choke point -- not the class -- is what canonicalizes."""

    def __init__(self, model=GGUF_PATH, dimensions=256):
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


class TestEveryStampSiteUsesTheChokePoint(unittest.TestCase):
    """Store-wide scan after a full capture -> process flow: no table may hold
    a tag other than embedder_model_tag(embedder)."""

    def test_store_wide_scan_after_capture_and_process(self):
        home = tempfile.mkdtemp(prefix="a0a_stamp_")
        try:
            core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
            emb = _GgufNamedEmbedder()
            core.embedder = emb
            core.reducer.embedder = emb
            core.retrieval.embedder = emb
            expected = embedder_model_tag(emb)
            self.assertEqual(expected, "nomic-embed-text[prefixed]")

            core.initialize("s1", principal_id="assistant")
            core.capture.observe(
                "I am Pat Testley\nI live in Springfield\nI work at Acme Fake Co\n"
                "My favorite tool is the Acme Fake Co widget press",
                "", session_id="s1")
            core.capture.observe(
                "I moved to Riverton last spring\nI still work at Acme Fake Co",
                "", session_id="s1")
            core.process_pending()
            core.curation.drain()

            conn = core.store._conn()
            scanned = {}
            for table, id_col in (("observed_vectors", "event_id"),
                                  ("memory_vectors", "belief_id"),
                                  ("query_proxy_vectors", "belief_id"),
                                  ("projection_vectors", "external_id"),
                                  ("entity_centroids", "entity_id")):
                rows = conn.execute(
                    "SELECT %s AS ident, model FROM %s" % (id_col, table)).fetchall()
                scanned[table] = len(rows)
                bad = [(r["ident"], r["model"]) for r in rows if r["model"] != expected]
                self.assertEqual(bad, [], "%s stamped a non-canonical tag: %r" % (table, bad))

            # The flow must actually have written vectors, or the scan proves
            # nothing (a store-wide scan over zero rows always passes).
            self.assertGreater(scanned["observed_vectors"], 0, scanned)
            self.assertGreater(scanned["memory_vectors"], 0, scanned)
            self.assertGreater(scanned["query_proxy_vectors"], 0, scanned)
            self.assertGreater(scanned["entity_centroids"], 0, scanned)

            # And the raw reported name must NOT appear anywhere as a tag.
            for table in ("observed_vectors", "memory_vectors", "query_proxy_vectors"):
                n = conn.execute("SELECT COUNT(*) FROM %s WHERE model LIKE '%%gguf%%'" % table
                                 ).fetchone()[0]
                self.assertEqual(n, 0, table)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_deferred_embed_job_stamps_the_same_tag(self):
        """The curation `embed` job is a SECOND writer into the same tables;
        it must agree with the reducer or the heal never converges."""
        home = tempfile.mkdtemp(prefix="a0a_job_")
        try:
            core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
            emb = _GgufNamedEmbedder()
            core.embedder = emb
            core.reducer.embedder = emb
            core.initialize("s1", principal_id="assistant")
            core.capture.observe("I am Pat Testley and I work at Acme Fake Co", "",
                                 session_id="s1")
            rows = core.store.iter_observed_vectors()
            self.assertGreaterEqual(len(rows), 1)
            eid = rows[0]["event_id"]
            # Wipe the tag to a legacy raw form, then let the queue rewrite it.
            core.store.add_observed_vector(eid, rows[0]["embedding"], GGUF_PATH, rows[0]["owner"])
            core.store.enqueue_embed_job(eid, "observed", "I am Pat Testley")
            core.curation.drain()
            self.assertEqual(core.store.get_observed_vector_model(eid),
                             embedder_model_tag(emb))
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
