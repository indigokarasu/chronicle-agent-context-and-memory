"""
Chronicle — L9 integration fixes for the doc2query proxy lifecycle.

`query_proxy_vectors` (E2) is the first derived vector table added since the
staleness/teardown machinery was written, and every one of those code paths was
built when there were exactly three vector tables. Each test here pins one place
the new table was missed — all four are integration defects, invisible to E2's
own suite because they only surface once E2 meets E1's model tagging, H1's
variable-length generation callback, or the store's projection rebuild.

Fixes covered (L9 review ledger):
  C — HealthEngine._embedder_mismatch_heal / requeue_hash_vectors.py never
      scanned query_proxy_vectors, so proxies stayed stale forever.
  D — _write_doc2query_proxies upserted without deleting, so a shrinking
      question count orphaned the higher-idx rows.
  E — MemoryStore.truncate_projection dropped every other derived vector table
      but left proxies behind.
  F — doc2query.generate_questions normalized the callback result OUTSIDE its
      try, so a wrong-typed element raised instead of falling back.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import doc2query
from engine.core import ChronicleCore
from engine.embeddings import pack


_FACT_KEY = {"entity_id": "ent_pat_testley", "entity_name": "Pat Testley",
             "predicate_canonical": "works_at", "attribute": "works_at",
             "qualifiers_hash": "", "qualifiers": {}}


def make_core(overrides=None):
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    if overrides:
        cfg.update(overrides)
    core = ChronicleCore(home, cfg)
    core.initialize("s1", principal_id="assistant")
    return core, home


def _seed_belief(core):
    """One asserted belief with doc2query proxies attached (same shape E2's own
    write-path suite uses -- a structured assertion, not heuristic extraction)."""
    core.capture.append("asserted", {
        "kind": "fact", "key": dict(_FACT_KEY), "body": "Acme Fake Co",
        "confidence": 0.9, "source_event": "src1", "source_type": "user_direct",
        "domain": "user"}, actor="user", trust_level=4, session_id="s1")
    return core.store.iter_query_proxy_vectors()


class TestHealDetectsStaleProxies(unittest.TestCase):
    """Fix C: the embedder-mismatch heal had a permanent blind spot."""

    def test_stale_proxy_detected_once_then_converges_to_zero(self):
        core, _ = make_core()
        rows = _seed_belief(core)
        self.assertTrue(rows, "fixture produced no proxies to make stale")
        bid = rows[0]["belief_id"]

        # Retag this belief's proxies with a bare/foreign model name, exactly
        # what an E1 task-prefix flip or a model swap leaves behind.
        with core.store.transaction() as conn:
            conn.execute("UPDATE query_proxy_vectors SET model='stale-fake-model' "
                         "WHERE belief_id=?", (bid,))
        stale_n = core.store.count_query_proxy_vectors(bid)
        self.assertGreater(stale_n, 0)

        first = core.health._embedder_mismatch_heal()["embedder_mismatch"]
        second = core.health._embedder_mismatch_heal()["embedder_mismatch"]

        # Detected on the first pass...
        self.assertGreaterEqual(first["mismatched"], stale_n)
        # ...and converged: nothing stale is left to find.
        self.assertEqual(second["mismatched"], 0)
        self.assertEqual(core.store.count_query_proxy_vectors(bid), 0)

    def test_heal_leaves_correctly_tagged_proxies_alone(self):
        """Discriminating partner: the scan must not delete healthy rows (an
        earlier form of this bug requeued correctly-tagged vectors forever)."""
        core, _ = make_core()
        rows = _seed_belief(core)
        bid = rows[0]["belief_id"]
        before = core.store.count_query_proxy_vectors(bid)
        self.assertGreater(before, 0)

        result = core.health._embedder_mismatch_heal()["embedder_mismatch"]

        self.assertEqual(result["mismatched"], 0)
        self.assertEqual(core.store.count_query_proxy_vectors(bid), before)


class TestProxyRegenerationDoesNotStrand(unittest.TestCase):
    """Fix D: (belief_id, proxy_idx) upsert leaves a stale tail when the
    generated count shrinks — which H1's callback does by design."""

    def test_four_proxies_then_two_leaves_exactly_two(self):
        core, _ = make_core()
        reducer = core.reducer
        b_id = "belief:fake-shrink-test"

        def gen(n):
            return lambda kind, key, body: ["fake question %d" % i for i in range(n)]

        reducer.doc2query_callback = gen(4)
        reducer._write_doc2query_proxies(b_id, "fact", {"subject": "Pat Testley"}, "body")
        self.assertEqual(core.store.count_query_proxy_vectors(b_id), 4)

        # Same belief, a generation that now yields fewer questions.
        reducer.doc2query_callback = gen(2)
        reducer._write_doc2query_proxies(b_id, "fact", {"subject": "Pat Testley"}, "body")
        self.assertEqual(core.store.count_query_proxy_vectors(b_id), 2)

        # And the survivors are the NEW generation, not two stale leftovers.
        qs = [r["question"] for r in core.store.iter_query_proxy_vectors()
              if r["belief_id"] == b_id]
        self.assertEqual(sorted(qs), ["fake question 0", "fake question 1"])


class TestTruncateProjectionDropsProxies(unittest.TestCase):
    """Fix E: proxies are derived state and must not survive a rebuild."""

    def test_truncate_projection_leaves_zero_proxy_rows(self):
        core, _ = make_core()
        self.assertTrue(_seed_belief(core), "fixture produced no proxies")

        core.store.truncate_projection()

        self.assertEqual(core.store.iter_query_proxy_vectors(), [])

    def test_truncate_projection_still_clears_the_other_vector_tables(self):
        """Guards the edit itself: the new entry must be an ADDITION to the
        teardown list, not a replacement of it."""
        core, _ = make_core()
        _seed_belief(core)
        core.store.truncate_projection()
        self.assertEqual(core.store.iter_memory_vectors(), [])
        self.assertEqual(core.store.iter_observed_vectors(), [])


class TestCallbackResultCoercion(unittest.TestCase):
    """Fix F: a wrong-typed callback result must fall back, not raise."""

    def test_non_string_callback_result_falls_back_to_templates(self):
        out = doc2query.generate_questions(
            "fact", dict(_FACT_KEY), "Acme Fake Co",
            callback=lambda kind, key, body: [123])
        # No exception, and the Tier-1 template path produced real questions.
        self.assertTrue(out)
        self.assertTrue(all(isinstance(q, str) for q in out))

    def test_raising_callback_still_falls_back(self):
        def boom(kind, key, body):
            raise RuntimeError("fake host model failure")

        out = doc2query.generate_questions(
            "fact", dict(_FACT_KEY), "Acme Fake Co",
            callback=boom)
        self.assertTrue(out)

    def test_a_good_callback_is_still_preferred_over_templates(self):
        """Discriminating partner: the coercion fix must not have turned the
        callback slot into a no-op."""
        out = doc2query.generate_questions(
            "fact", dict(_FACT_KEY), "Acme Fake Co",
            callback=lambda kind, key, body: ["only the callback question"])
        self.assertEqual(out, ["only the callback question"])


if __name__ == "__main__":
    unittest.main()
