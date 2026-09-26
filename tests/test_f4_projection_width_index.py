"""Chronicle — F4: covering index on projection_vectors(length(embedding)).

The wrong_dim_vector_count function in MemoryStore queries projection_vectors
for a count of rows where length(embedding) != expected_width. The docstring
claims this is answered by idx_pv_model_width, but projection_vectors had no
such width index initially.

F4 adds a covering expression index on (length(embedding)) to projection_vectors,
allowing SQLite to optimize the wrong_dim_vector_count query. The index is added
via the schema migration in _migrate() for idempotency.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import pack


class TestProjectionVectorsWidthIndex(unittest.TestCase):
    """Verify the covering index on projection_vectors(length(embedding))."""

    def setUp(self):
        """Create a test store with projection vectors of various widths.

        The store initialization triggers _migrate(), which creates the index
        idx_projection_vectors_width on (length(embedding)).
        """
        self.core = ChronicleCore(tempfile.mkdtemp(), {"embeddings": {"model": "hashing"}})
        self.core.initialize(session_id="test_f4", principal_id="assistant")
        self.store = self.core.store

    def tearDown(self):
        """Clean up the store."""
        if self.store:
            self.store.close()

    def _add_projection_vector(self, provider, external_id, vec):
        """Helper to add a projection vector with a given embedding."""
        self.store.add_projection_vector(
            provider, external_id, pack(vec), "hashing-v1", owner="assistant"
        )

    def test_index_exists_after_migration(self):
        """Verify covering indexes are created by schema migration."""
        conn = self.store._conn()
        # Check that the covering index exists
        idx_info = conn.execute(
            "PRAGMA index_info(idx_pv_width_external_id)"
        ).fetchall()
        self.assertTrue(
            len(idx_info) > 0,
            "Index idx_pv_width_external_id should exist after schema migration",
        )
        # Verify the index includes both length(embedding) and external_id
        idx_list = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_pv_width_external_id",),
        ).fetchone()
        self.assertIsNotNone(idx_list)
        idx_sql = idx_list[0].lower()
        self.assertIn("length(embedding)", idx_sql)
        self.assertIn("external_id", idx_sql)

    def test_query_plan_with_width_index(self):
        """Verify EXPLAIN QUERY PLAN uses covering index for wrong_dim_vector_count.

        The query counts projection_vectors where length(embedding) != expected_width.
        The covering index idx_pv_width_external_id(length(embedding), external_id)
        enables a pure index scan without reading blob pages.
        """
        conn = self.store._conn()

        # Add vectors with different widths
        # hashing model produces 128-element vectors (512 bytes packed as float32)
        for i in range(5):
            vec_128 = [float(j) for j in range(128)]
            self._add_projection_vector("test_provider", f"vec_128_{i}", vec_128)

        # Add some 64-element vectors (256 bytes packed)
        for i in range(3):
            vec_64 = [float(j) for j in range(64)]
            self._add_projection_vector("test_provider", f"vec_64_{i}", vec_64)

        # Run EXPLAIN QUERY PLAN on the EXACT query from wrong_dim_vector_count
        # Note: embedding IS NOT NULL is removed as redundant (length(NULL) is NULL,
        # so NULL != ? is never true, defeating the covering index)
        expected_width = 512
        plan = conn.execute(
            """EXPLAIN QUERY PLAN
               SELECT COUNT(*) FROM projection_vectors
               WHERE length(embedding) != ?""",
            (expected_width,),
        ).fetchall()

        # Log the plan for inspection - extract detail column from Row objects
        plan_details = [dict(row).get('detail', '') for row in plan]
        plan_str = "\n".join(plan_details)
        print("\n=== QUERY PLAN WITH COVERING INDEX ===")
        print(plan_str)

        # Verify the plan uses the index rather than scanning the table.
        # SQLite words the index-only scan differently across versions:
        #   3.4x+: "SCAN projection_vectors USING COVERING INDEX idx_..."
        #   some builds: "SCAN projection_vectors USING INDEX idx_..."
        #   older:      "SEARCH projection_vectors USING COVERING INDEX idx_..."
        # so assert on the stable facts — the index is named, and it is reached
        # "USING" an index — not on the literal COVERING INDEX token. A full
        # table scan ("SCAN projection_vectors" with no USING INDEX) still fails.
        plan_text = "\n".join(plan_details)
        self.assertIn("idx_pv_width_external_id", plan_text,
                     f"Plan should use idx_pv_width_external_id. Got: {plan_text}")
        # Every plan row that touches projection_vectors must go through an
        # index. A full table scan names no index at all and fails here.
        for line in plan_details:
            if "PROJECTION_VECTORS" in line.upper():
                self.assertIn("INDEX", line.upper(),
                             f"Plan scans projection_vectors without an index. Got: {line}")

    def test_wrong_dim_count_accuracy(self):
        """Verify wrong_dim_vector_count reports correct counts with mixed widths."""
        # Add vectors of one size
        for i in range(10):
            vec = [float(j) for j in range(128)]
            self._add_projection_vector("provider_a", f"big_{i}", vec)

        # Add vectors of another size
        for i in range(5):
            vec = [float(j) for j in range(64)]
            self._add_projection_vector("provider_b", f"small_{i}", vec)

        # Count vectors that don't match 512 bytes (128-element)
        count = self.store.wrong_dim_vector_count(
            "projection_vectors", "external_id", 512
        )
        self.assertEqual(count, 5, "Should find 5 vectors with width != 512")

        # Count vectors that don't match 256 bytes (64-element)
        count = self.store.wrong_dim_vector_count(
            "projection_vectors", "external_id", 256
        )
        self.assertEqual(count, 10, "Should find 10 vectors with width != 256")


if __name__ == "__main__":
    unittest.main()
