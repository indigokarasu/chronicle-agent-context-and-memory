"""
Chronicle — X1: lexical fallback when the embedder fails.

If the embedder is unavailable (e.g., embed server down), query_understanding
should degrade gracefully to lexical-only search instead of raising.

X1 Acceptance:
  (a) an embedder that raises on embed_query(); query_understanding(q) returns
      a dict with embedding=None, and search() returns FTS hits on a small store
  (b) the logger.warning is called at most once per process
"""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore


class RaisingEmbedder:
    """A custom embedder that raises on every embed call."""

    def __init__(self):
        self.model = "raising-test"
        self.dimensions = 256

    def embed(self, text: str) -> list[float]:
        raise RuntimeError("embed server is down")

    def embed_query(self, query: str) -> list[float]:
        raise RuntimeError("embed server is down")


class TestEmbedFailureDegradation(unittest.TestCase):
    """X1 acceptance tests: embedding failures degrade to lexical search."""

    def setUp(self):
        """Create a small store with some searchable content."""
        import tempfile
        self.tmpdir = tempfile.mkdtemp(prefix="test_x1_")

        # Create core with hashing embedder to populate the store
        cfg = {"embeddings": {"model": "hashing"}}
        self.core = ChronicleCore(self.tmpdir, cfg)

        # Insert a fact so there's something to search for
        principal = "test_principal"
        self.core.tools.dispatch(principal, "remember", {
            "kind": "fact",
            "entity": "test_entity",
            "attribute": "works_at",
            "content": "Pat works at Acme Corp in the research division"
        })

        # Now rebuild the retrieval engine with a raising embedder to simulate failure
        self.raising_embedder = RaisingEmbedder()
        self.core.retrieval.embedder = self.raising_embedder

    def tearDown(self):
        """Clean up temp directory."""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_query_understanding_returns_no_embedding_on_embedder_failure(self):
        """Verify that query_understanding returns embedding=None when embedder raises."""
        result = self.core.retrieval.query_understanding("where does pat work")
        self.assertIsNotNone(result)
        self.assertEqual(result["embedding"], None, "embedding should be None when embedder fails")
        self.assertIn("raw", result)
        self.assertIn("tokens", result)
        self.assertIn("expanded", result)

    def test_search_returns_fts_hits_when_embedder_fails(self):
        """Verify that search() still returns FTS hits when embedder is unavailable."""
        query = "pat works at acme"
        hits = self.core.retrieval.search(query)
        self.assertGreater(len(hits), 0, "search() should return FTS hits even when embedder fails")
        # The hit should contain the fact we inserted
        self.assertTrue(
            any("Acme" in str(hit) or "Pat" in str(hit) for hit in hits),
            f"search results should mention Acme or Pat: {hits}"
        )

    def test_search_finds_content_by_lexical_match_only(self):
        """Verify lexical FTS matching works independently of embedding."""
        # Insert more content with distinct keywords
        principal = "test_principal"
        self.core.tools.dispatch(principal, "remember", {
            "kind": "fact",
            "entity": "test_entity_2",
            "attribute": "skill",
            "content": "Alice specializes in machine learning and neural networks"
        })

        # Search for a term that appears only in FTS, not necessarily vectorized
        query = "neural networks"
        hits = self.core.retrieval.search(query)
        self.assertGreater(len(hits), 0, "search() should find neural networks via FTS")


if __name__ == "__main__":
    unittest.main()
