"""
Chronicle — a slow embedding server costs one timeout, not one per call.

Measured on a production host whose local embedding server answered
`/v1/models` in 0.1 s and then timed out on real work. Two defects:

1. EVERY CALL RESTARTED THE RETRY BUDGET. One context compaction evicting twenty
   spans made twenty inline embeds, each spending the full five-attempt budget
   before giving up: over six minutes and 26 timeouts, still inside its FIRST
   pass. That is a user's turn, frozen. A circuit breaker now opens after an
   exhausted budget: calls inside the cooldown fail at once, the first call
   after it probes again, and a success closes the circuit.

2. A TIMEOUT DROPPED THE VECTOR FOR GOOD. The exhausted loop re-raised the raw
   `socket.timeout`. Every caller treats EmbeddingsUnavailable as "the backend is
   down, try later" — `_safe_vec` queues a deferred embed job on it — but a raw
   timeout reached the generic handler, which logged at DEBUG and returned None.
   The warning printed just before promised "embed retried on the next
   operation". It was not.

The failure is injected as `socket.timeout`, the exception the throttled server
actually produced — a refused connection would fail fast and hide both defects.
"""

import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import embeddings as E
from engine.reducer import Reducer


class _Timeouts:
    """Stands in for the throttled server: every request times out, with the
    exception the real one raised (`socket.timeout`). The suite is hermetic —
    no socket may open, loopback included — so the failure is injected at the
    one method that does I/O, and every real attempt is COUNTED. Counting, not
    timing, is what proves a call did or did not spend a retry budget."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise socket.timeout("timed out")


def _embedder(cooldown=30.0):
    emb = E.OpenAICompatEmbedder("http://127.0.0.1:8080/v1", "nomic-embed-text", 768,
                                 timeout=0.2, max_attempts=3, backoff_base=0.0,
                                 backoff_cap=0.0, circuit_cooldown=cooldown)
    emb._embed_raw = _Timeouts()
    emb._embed_raw_batch = _Timeouts()
    return emb


class _Queue:
    def __init__(self):
        self.jobs = []

    def enqueue_embed_job(self, target_id, kind, text, **kw):
        self.jobs.append((target_id, kind))


class TestAnExhaustedBudget(unittest.TestCase):
    def setUp(self):
        self.emb = _embedder()

    def test_it_raises_the_try_later_exception(self):
        with self.assertRaises(E.EmbeddingsUnavailable):
            self.emb.embed_document("hello")

    def test_the_original_error_is_kept_as_the_cause(self):
        try:
            self.emb.embed_document("hello")
        except E.EmbeddingsUnavailable as e:
            self.assertIsNotNone(e.__cause__, "the socket error must survive for debugging")

    def test_the_vector_is_queued_not_dropped(self):
        """The data-loss half: `_safe_vec` queues a deferred embed only for
        EmbeddingsUnavailable, and a raw timeout used to skip it."""
        r = Reducer.__new__(Reducer)
        r.embedder, r.store, r._vec_cache = self.emb, _Queue(), {}
        self.assertIsNone(r._safe_vec("hello", target_id="ev_x", kind="observed"))
        self.assertEqual(r.store.jobs, [("ev_x", "observed")])


class TestTheCircuit(unittest.TestCase):
    def test_the_first_call_spends_the_whole_budget(self):
        emb = _embedder()
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("first")
        self.assertEqual(emb._embed_raw.calls, 3)

    def test_calls_inside_the_cooldown_fail_at_once(self):
        """The compaction that evicted twenty spans: one budget, not twenty."""
        emb = _embedder()
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("first")
        for i in range(20):
            with self.assertRaises(E.EmbeddingsUnavailable):
                emb.embed_document("span %d" % i)
        self.assertEqual(emb._embed_raw.calls, 3, "twenty more calls must not reach the server")

    def test_a_batch_is_covered_too(self):
        emb = _embedder()
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_batch(["a", "b"])
        first = emb._embed_raw_batch.calls
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_batch(["c", "d"])
        self.assertEqual(emb._embed_raw_batch.calls, first)

    def test_one_circuit_serves_both_paths(self):
        """A single endpoint: a batch that tripped it makes a single fail fast."""
        emb = _embedder()
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_batch(["a", "b"])
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("single")
        self.assertEqual(emb._embed_raw.calls, 0)

    def test_after_the_cooldown_it_probes_again(self):
        emb = _embedder(cooldown=0.05)
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("first")
        time.sleep(0.08)
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("probe")
        self.assertEqual(emb._embed_raw.calls, 6, "past the cooldown it must really try again")

    def test_a_success_closes_the_circuit(self):
        emb = _embedder()
        emb._open_until = time.monotonic() + 30
        emb._embed_raw = lambda text, timeout: [0.1] * 768      # the server recovered
        emb._open_until = 0.0                                    # cooldown over
        self.assertEqual(len(emb.embed_document("hello")), 768)
        self.assertEqual(emb._open_until, 0.0)

    def test_an_auth_failure_is_still_terminal_and_does_not_trip_it(self):
        """A bad key will not fix itself; that stays a hard error, and it must
        not make the endpoint look down for everyone else."""
        emb = _embedder()

        class _Auth(Exception):
            code = 401

        def _raise(text, timeout):
            raise _Auth("unauthorized")
        emb._embed_raw = _raise
        with self.assertRaises(_Auth):
            emb.embed_document("hello")
        self.assertEqual(emb._open_until, 0.0)

    def test_a_healthy_server_never_trips_it(self):
        emb = _embedder()
        emb._embed_raw = lambda text, timeout: [0.1] * 768
        for i in range(50):
            emb.embed_document("span %d" % i)
        self.assertEqual(emb._open_until, 0.0)


if __name__ == "__main__":
    unittest.main()
