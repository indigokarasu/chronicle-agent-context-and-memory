"""
Chronicle — u4 acceptance test (embedder-mismatch self-heal).

Build a store with hashing embedder + vectors; reopen with a fake embedder
of a different model; run health check; assert mismatch count > 0 and embed
jobs enqueued; running twice does not double-enqueue.
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.core import ChronicleCore


class FakeEmbedder:
    """Mock embedder with a different model name (not 'hashing')."""

    def __init__(self):
        self.model = "fake-test-model-xyz"
        self.dimensions = 768

    def embed(self, text):
        """Return a fake embedding vector."""
        return [0.1] * self.dimensions

    def embed_batch(self, texts):
        """Return fake embedding vectors."""
        return [[0.1] * self.dimensions for _ in texts]


def test_embedder_mismatch_self_heal():
    """Verify that mismatched embeddings are detected and requeued."""
    home = tempfile.mkdtemp()
    try:
        # Phase 1: Create a store with hashing embedder, write vectors.
        print("Phase 1: Create store with hashing embedder...")
        core1 = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        core1.initialize("s1", principal_id="default")

        # Ingest some observations (creates observed events + vectors).
        core1.capture.observe("My name is Pat Testley", "ok", session_id="s1")
        core1.capture.observe("I work at Acme Fake Co", "ok", session_id="s1")
        core1.capture.observe("I live in Springfield", "ok", session_id="s1")

        # Process pending to extract and vectorize.
        core1.process_pending()

        # Verify vectors were written.
        obs_vecs_1 = list(core1.store.iter_observed_vectors())
        mem_vecs_1 = list(core1.store.iter_memory_vectors())
        print(f"Phase 1 done: {len(obs_vecs_1)} observed vectors, {len(mem_vecs_1)} memory vectors")
        assert len(obs_vecs_1) > 0, "No observed vectors written"
        assert len(mem_vecs_1) > 0, "No memory vectors written"

        # Verify all vectors have model='hashing-v1' (the default hashing model).
        for v in obs_vecs_1:
            assert v["model"] == "hashing-v1", f"Expected hashing-v1, got {v['model']}"
        for v in mem_vecs_1:
            assert v["model"] == "hashing-v1", f"Expected hashing-v1, got {v['model']}"

        # Phase 2: Reopen with a fake embedder (different model).
        print("\nPhase 2: Reopen with fake embedder...")
        core1.store._conn().close()  # Close the connection

        core2 = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        # Replace embedder with fake one (different model).
        core2.embedder = FakeEmbedder()

        # Run health check — should detect mismatches and enqueue jobs.
        print("Running health check...")
        health_results = core2.health.run()
        print(f"Health results: {health_results}")

        # Assert mismatch detection.
        assert "embedder_mismatch" in health_results, "embedder_mismatch not in health results"
        mismatch_data = health_results["embedder_mismatch"]
        mismatched = mismatch_data["mismatched"]
        requeued = mismatch_data["requeued"]
        print(f"Mismatched: {mismatched}, Requeued: {requeued}")

        len(obs_vecs_1) + len(mem_vecs_1)
        assert mismatched > 0, f"Expected mismatched > 0, got {mismatched}"
        assert requeued > 0, f"Expected requeued > 0, got {requeued}"
        assert requeued <= mismatched, f"Requeued {requeued} > mismatched {mismatched}"

        # Get current embed job count.
        jobs_1 = core2.store.get_curation_jobs("task='embed' AND status='pending'")
        jobs_1_count = len(jobs_1)
        print(f"Embed jobs after 1st health check: {jobs_1_count}")
        assert jobs_1_count > 0, f"Expected pending embed jobs, got {jobs_1_count}"

        # Phase 3: Run health check again — should NOT double-enqueue (idempotent).
        print("\nPhase 3: Run health check again (idempotency test)...")
        health_results_2 = core2.health.run()
        print(f"Health results 2: {health_results_2}")

        mismatch_data_2 = health_results_2["embedder_mismatch"]
        mismatched_2 = mismatch_data_2["mismatched"]
        requeued_2 = mismatch_data_2["requeued"]
        print(f"Mismatched 2: {mismatched_2}, Requeued 2: {requeued_2}")

        # Mismatch count should still be > 0 (vectors not deleted).
        assert mismatched_2 > 0, f"Expected mismatched_2 > 0, got {mismatched_2}"

        # Requeued count should be 0 (already queued, deduped).
        assert requeued_2 == 0, f"Expected requeued_2 == 0 (dedup), got {requeued_2}"

        # Total jobs should not increase (dedup worked).
        jobs_2 = core2.store.get_curation_jobs("task='embed' AND status='pending'")
        jobs_2_count = len(jobs_2)
        print(f"Embed jobs after 2nd health check: {jobs_2_count}")
        assert jobs_2_count == jobs_1_count, \
            f"Expected same job count (dedup), got {jobs_1_count} → {jobs_2_count}"

        print("\nPASS: embedder-mismatch self-heal works correctly")

    finally:
        shutil.rmtree(home)


if __name__ == "__main__":
    test_embedder_mismatch_self_heal()
