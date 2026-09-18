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

    def test_after_the_cooldown_it_probes_with_ONE_attempt(self):
        """Half-open: a single trial, not a fresh retry budget. Every agent turn
        drains curation jobs before the model is called, so a full budget here
        was up to a minute of a user's turn spent on a server that was down."""
        emb = _embedder(cooldown=0.05)
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("first")
        self.assertEqual(emb._embed_raw.calls, 3)
        time.sleep(0.08)
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("probe")
        self.assertEqual(emb._embed_raw.calls, 4, "past the cooldown: exactly one real try")

    def test_the_cooldown_doubles_while_the_server_stays_down(self):
        emb = _embedder(cooldown=0.05)
        lengths = []
        for _ in range(4):
            with self.assertRaises(E.EmbeddingsUnavailable):
                emb.embed_document("x")
            lengths.append(emb._open_until - time.monotonic())
            emb._open_until = 0.0            # skip the wait; keep the trip count
        self.assertEqual(emb._trips, 4)
        for a, b in zip(lengths, lengths[1:]):
            self.assertGreater(b, a * 1.5)

    def test_the_cooldown_is_capped(self):
        emb = _embedder(cooldown=30.0)
        emb._trips = 50
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("x")
        self.assertLessEqual(emb._open_until - time.monotonic(), emb._CIRCUIT_MAX_COOLDOWN + 1)

    def test_one_success_restores_the_full_budget(self):
        emb = _embedder(cooldown=0.0)
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("down")
        self.assertEqual(emb._trips, 1)
        emb._embed_raw = lambda text, timeout: [0.1] * 768
        emb.embed_document("back")
        self.assertEqual((emb._trips, emb._open_until), (0, 0.0))
        failing = _Timeouts()
        emb._embed_raw = failing
        with self.assertRaises(E.EmbeddingsUnavailable):
            emb.embed_document("down again")
        self.assertEqual(failing.calls, 3, "a fresh outage gets the whole budget again")

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


class TestATurnDoesNotWaitOnADownServer(unittest.TestCase):
    """Every agent turn drains curation jobs before the model is called
    (on_turn_start -> core.tick). With the embedding server down and embed jobs
    queued, what does a turn pay? It used to be a full retry budget each time
    the cooldown lapsed — about a minute of a user's turn."""

    def setUp(self):
        import shutil as _sh
        from _tmp_support import temp_home
        from engine.core import ChronicleCore
        self.home = temp_home(prefix="circuit_turn_")
        self.addCleanup(_sh.rmtree, self.home, ignore_errors=True)
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("turn-s1", principal_id="assistant")
        # REAL captured turns: the embed task re-resolves each job's text from
        # the store, so a job for an id that does not exist is a no-op.
        import json as _json
        ids = [self.core.capture.observe("Pat Testley note %d about the Acme Fake Co offsite." % i,
                                         "Noted.", session_id="turn-s1") for i in range(12)]
        self.core.store._conn().execute("DELETE FROM curation_jobs")
        self.core.store._conn().commit()
        for eid in ids:
            ex = _json.loads(self.core.store.get_event(eid)["payload"])["excerpt"]
            self.core.store.enqueue_embed_job(eid, "observed", ex)
        self.emb = _embedder(cooldown=0.05)
        self.core.embedder = self.emb

    def test_a_turn_costs_at_most_one_budget(self):
        self.core.tick()                         # first outage: the full budget, once
        self.assertEqual(self.emb._embed_raw.calls, 3, "one budget for the whole turn, not one per job")

    def test_the_next_turn_does_not_touch_the_server_at_all(self):
        """Two layers protect it: the breaker, and the queue backing off every
        job it deferred."""
        self.core.tick()
        first = self.emb._embed_raw.calls
        self.core.tick()
        self.assertEqual(self.emb._embed_raw.calls, first)

    def test_once_both_backoffs_lapse_a_turn_makes_one_try(self):
        self.core.tick()
        first = self.emb._embed_raw.calls
        c = self.core.store._conn()
        c.execute("UPDATE curation_jobs SET run_after=NULL WHERE task='embed'")   # job backoff over
        c.commit()
        time.sleep(0.08)                                                           # circuit cooldown over
        self.core.tick()
        self.assertEqual(self.emb._embed_raw.calls - first, 1, "half-open: exactly one real try")

    def test_the_jobs_stay_queued_for_when_it_is_back(self):
        self.core.tick()
        c = self.core.store._conn()
        failed = c.execute("SELECT COUNT(*) FROM curation_jobs WHERE task='embed' "
                           "AND status='failed'").fetchone()[0]
        self.assertEqual(failed, 0, "an outage defers vectors, it does not give up on them")


if __name__ == "__main__":
    unittest.main()
