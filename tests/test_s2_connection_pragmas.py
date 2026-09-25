"""
S2 — connection pragmas (cache_size, mmap_size, synchronous, journal_size_limit).

Why: SQLite defaults (cache_size -2000, no mmap, synchronous FULL, no journal
limit) were inefficient on a 2.26 GB database. This test verifies that
MemoryStore opens connections with the optimized PRAGMA values.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import DEFAULTS
from engine.store import (
    STORE_CACHE_KB, STORE_MMAP_BYTES, STORE_SYNCHRONOUS, STORE_JOURNAL_SIZE_LIMIT,
    MemoryStore,
)


class TestConnectionPragmas(unittest.TestCase):
    """Verify connection pragmas are set correctly."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.db"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_pragmas_default_values(self):
        """MemoryStore opens connections with optimized PRAGMA values.

        This is the core requirement: verify that cache_size, mmap_size,
        synchronous, and journal_size_limit are all set to optimized values
        from the module defaults (or config, if available).
        """
        store = MemoryStore(self.db_path)
        self.addCleanup(store.close)
        conn = store._conn()

        # Read the actual PRAGMA values set on the connection
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        cache_size = conn.execute("PRAGMA cache_size").fetchone()[0]
        mmap_size = conn.execute("PRAGMA mmap_size").fetchone()[0]
        journal_size_limit = conn.execute("PRAGMA journal_size_limit").fetchone()[0]

        # Verify all pragmas are set to optimized values
        # synchronous=1 is NORMAL (0=OFF, 1=NORMAL, 2=FULL)
        self.assertEqual(synchronous, 1,
            "synchronous should be NORMAL (1); WAL mode + NORMAL is safe")

        # cache_size is negative (KB specified), absolute value should be 65536
        # (upgraded from default 2 MB to 64 MB)
        self.assertEqual(cache_size, -STORE_CACHE_KB,
            f"cache_size should be -{STORE_CACHE_KB} (64 MB); defaults to 2 MB")

        # mmap_size should be 512 MB for efficient large scans
        self.assertEqual(mmap_size, STORE_MMAP_BYTES,
            f"mmap_size should be {STORE_MMAP_BYTES} (512 MB) for OS paging")

        # journal_size_limit should prevent unbounded WAL growth
        self.assertEqual(journal_size_limit, STORE_JOURNAL_SIZE_LIMIT,
            f"journal_size_limit should be {STORE_JOURNAL_SIZE_LIMIT} (64 MB)")

    def test_defaults_block_in_config(self):
        """DEFAULTS in config.py declares store pragmas."""
        store_config = DEFAULTS.get("store", {})

        # Verify all required keys exist
        self.assertIn("cache_kb", store_config,
            "store.cache_kb must be declared in DEFAULTS")
        self.assertIn("mmap_bytes", store_config,
            "store.mmap_bytes must be declared in DEFAULTS")
        self.assertIn("synchronous", store_config,
            "store.synchronous must be declared in DEFAULTS")
        self.assertIn("journal_size_limit", store_config,
            "store.journal_size_limit must be declared in DEFAULTS")

        # Verify values match the defaults
        self.assertEqual(store_config["cache_kb"], STORE_CACHE_KB)
        self.assertEqual(store_config["mmap_bytes"], STORE_MMAP_BYTES)
        self.assertEqual(store_config["synchronous"], STORE_SYNCHRONOUS)
        self.assertEqual(store_config["journal_size_limit"], STORE_JOURNAL_SIZE_LIMIT)


if __name__ == "__main__":
    unittest.main()
