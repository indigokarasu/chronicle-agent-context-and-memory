"""
Chronicle — acceptance tests for E1 (nomic task prefixes, §27 embeddings.task_prefixes).

Covers the three spec'd acceptance checks (issue #8, E1):
  (a) exact task-prefixed "input" payload on the wire for query vs. document
      embeds against a nomic-named model;
  (b) hashing mode never prefixes, even given a nomic-like model name;
  (c) the embedder-mismatch requeue lifecycle actually converges: a legacy
      bare-tagged vector is detected and requeued once, and re-heals clean on
      the next pass once the requeue has drained.

Fixtures use only fake values (Pat Testley, Acme Fake Co), per the ladder-wide
constraint.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder, OpenAICompatEmbedder, pack


def make_core():
    # Force the offline hashing embedder at construction time so tests are
    # deterministic and never probe localhost embedding servers; individual
    # tests swap in a fake/real embedder afterward where they need to.
    home = tempfile.mkdtemp()
    return ChronicleCore(home, {"embeddings": {"model": "hashing"}}), home


class _FakeHTTPResponse:
    """Minimal stand-in for the urllib.response object _embed_raw reads."""

    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeNomicEmbedder:
    """Hashing-backed but nomic-NAMED: exercises the real task-prefix /
    marker-tagging contract (use_task_prefixes, model_with_prefix_marker())
    the same way OpenAICompatEmbedder does, but computes vectors with the
    deterministic offline HashingEmbedder so the requeue-lifecycle test needs
    no network or real model.
    """

    def __init__(self, model="nomic-embed-text"):
        self.model = model
        self.dimensions = 256
        self._h = HashingEmbedder(model=model)
        self.use_task_prefixes = "nomic" in model.lower()

    def embed(self, text):
        return self._h.embed(text)

    def embed_query(self, query):
        if self.use_task_prefixes:
            query = "search_query: " + (query or "")
        return self._h.embed(query)

    def embed_document(self, document):
        if self.use_task_prefixes:
            document = "search_document: " + (document or "")
        return self._h.embed(document)

    def model_with_prefix_marker(self):
        if self.use_task_prefixes:
            return f"{self.model}[prefixed]"
        return self.model


# ---------------------------------------------------------------------------
# (a) exact prefix in the embed request payload for nomic-named models
# ---------------------------------------------------------------------------
class TestNomicPrefixOnTheWire(unittest.TestCase):
    def _fake_urlopen(self, calls, dims=8):
        def _urlopen(req, timeout=None):
            calls.append(req)
            return _FakeHTTPResponse({"data": [{"embedding": [0.1] * dims, "index": 0}]})
        return _urlopen

    def _fake_urlopen_any(self, calls, dims=8):
        """Handles both the single-embed shape (`input`: str) and the batch
        shape (`input`: list[str]), so one fake server can back embed(),
        embed_query()/embed_document(), and embed_batch() alike."""
        def _urlopen(req, timeout=None):
            calls.append(req)
            body = json.loads(req.data.decode("utf-8"))
            inp = body["input"]
            if isinstance(inp, list):
                data = [{"embedding": [0.1] * dims, "index": i} for i in range(len(inp))]
            else:
                data = [{"embedding": [0.1] * dims, "index": 0}]
            return _FakeHTTPResponse({"data": data})
        return _urlopen

    def test_embed_query_sends_search_query_prefix(self):
        calls = []
        emb = OpenAICompatEmbedder("http://localhost:1234/v1", "nomic-embed-text", 8)
        self.assertTrue(emb.use_task_prefixes)  # auto-detected from model name
        with mock.patch("urllib.request.urlopen", side_effect=self._fake_urlopen(calls)):
            emb.embed_query("where does Pat Testley work")
        self.assertEqual(len(calls), 1)
        body = json.loads(calls[0].data.decode("utf-8"))
        self.assertEqual(body["input"], "search_query: where does Pat Testley work")

    def test_embed_document_sends_search_document_prefix(self):
        calls = []
        emb = OpenAICompatEmbedder("http://localhost:1234/v1", "nomic-embed-text", 8)
        with mock.patch("urllib.request.urlopen", side_effect=self._fake_urlopen(calls)):
            emb.embed_document("Pat Testley works at Acme Fake Co")
        self.assertEqual(len(calls), 1)
        body = json.loads(calls[0].data.decode("utf-8"))
        self.assertEqual(body["input"], "search_document: Pat Testley works at Acme Fake Co")

    def test_embed_batch_sends_search_document_prefix(self):
        calls = []
        emb = OpenAICompatEmbedder("http://localhost:1234/v1", "nomic-embed-text", 8)
        with mock.patch("urllib.request.urlopen", side_effect=self._fake_urlopen_any(calls)):
            emb.embed_batch(["Pat Testley works at Acme Fake Co", "Pat Testley lives in Springfield"])
        self.assertEqual(len(calls), 1)
        body = json.loads(calls[0].data.decode("utf-8"))
        self.assertEqual(body["input"], [
            "search_document: Pat Testley works at Acme Fake Co",
            "search_document: Pat Testley lives in Springfield",
        ])

    def test_embed_batch_over_cap_text_gets_exactly_one_prefix(self):
        """An oversized item is routed out of the batch through embed() on its
        own (§27 max_input_tokens/.overflow) -- it must still be prefixed
        exactly once, not double-prefixed by both the batch-level prepend and
        some second layer, and not left bare because it took the 'own call'
        path instead of the batch path."""
        calls = []
        emb = OpenAICompatEmbedder("http://localhost:1234/v1", "nomic-embed-text", 8,
                                   max_input_tokens=256)  # clamped floor; cap = 768 chars
        oversized = "Pat Testley works at Acme Fake Co. " * 40  # ~1440 chars, well past the cap
        with mock.patch("urllib.request.urlopen", side_effect=self._fake_urlopen_any(calls)):
            emb.embed_batch(["short fact about Pat Testley", oversized])
        bodies = [json.loads(c.data.decode("utf-8")) for c in calls]
        oversized_inputs = [b["input"] for b in bodies if isinstance(b["input"], str)]
        self.assertEqual(len(oversized_inputs), 1, "expected exactly one single-item call for the oversized text")
        sent = oversized_inputs[0]
        self.assertTrue(sent.startswith("search_document: "))
        self.assertEqual(sent.count("search_document: "), 1,
                         "oversized text was double-prefixed: %r" % sent[:40])


# ---------------------------------------------------------------------------
# (b) hashing mode never prefixes, even for a nomic-like model name
# ---------------------------------------------------------------------------
class TestHashingModeNeverPrefixes(unittest.TestCase):
    def test_hashing_embedder_ignores_nomic_like_name(self):
        emb = HashingEmbedder(model="nomic-embed-text")
        self.assertFalse(emb.use_task_prefixes)
        text = "Pat Testley lives in Springfield"
        v = emb.embed(text)
        vq = emb.embed_query(text)
        vd = emb.embed_document(text)
        # byte-identical, not just numerically close
        self.assertEqual(pack(v), pack(vq))
        self.assertEqual(pack(v), pack(vd))
        self.assertEqual(emb.model_with_prefix_marker(), "nomic-embed-text")  # no [prefixed] marker


# ---------------------------------------------------------------------------
# (c) embedder-mismatch requeue lifecycle actually converges
# ---------------------------------------------------------------------------
class TestEmbedderMismatchHealConverges(unittest.TestCase):
    def test_requeue_then_clean_on_second_pass(self):
        core, home = make_core()
        try:
            fake = _FakeNomicEmbedder()
            core.embedder = fake            # health._embedder_mismatch_heal + curation._task_embed read this
            core.reducer.embedder = fake    # reducer write paths read this
            core.initialize("s1", principal_id="assistant")

            core.capture.observe(
                "I am Pat Testley\nI live in Springfield\nI work at Acme Fake Co", "",
                session_id="s1")

            rows = core.store.iter_observed_vectors()
            self.assertGreaterEqual(len(rows), 1)
            row = rows[0]
            # The write path just wrote this with the marker-tagged model name.
            self.assertEqual(row["model"], "nomic-embed-text[prefixed]")

            # Simulate a legacy write: downgrade this one row to a bare tag,
            # same bytes, no marker -- exactly what a pre-E1 write left behind.
            core.store.add_observed_vector(row["event_id"], row["embedding"], "nomic-embed-text", row["owner"])
            self.assertEqual(core.store.get_observed_vector_model(row["event_id"]), "nomic-embed-text")

            # Run 1: the bare-tagged row is a real mismatch and gets requeued.
            result1 = core.health._embedder_mismatch_heal()
            summary1 = result1["embedder_mismatch"]
            self.assertGreaterEqual(summary1["mismatched"], 1)
            self.assertGreaterEqual(summary1["requeued"], 1)

            core.curation.drain()

            # The requeued job wrote the vector back with the current
            # marker-tagged model, so the row must no longer be bare.
            self.assertEqual(core.store.get_observed_vector_model(row["event_id"]), "nomic-embed-text[prefixed]")

            # Run 2: nothing left to heal -- this must NOT loop forever.
            result2 = core.health._embedder_mismatch_heal()
            summary2 = result2["embedder_mismatch"]
            self.assertEqual(summary2["mismatched"], 0)
            self.assertEqual(summary2["requeued"], 0)
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
