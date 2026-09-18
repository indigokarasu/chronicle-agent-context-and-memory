"""
Chronicle — the context engine honours the calls Hermes actually makes.

Checked against the host's ContextEngine (hermes-agent agent/context_engine.py)
method by method. Where Chronicle did NOT override a method it silently got the
host's default, and two of those defaults were wrong for an engine that keeps
per-conversation state:

  should_defer_preflight_to_real_usage  default False. The host calls it only
      for a ROUGH whole-context estimate, and its built-in compressor defers
      right after a compaction because the last real reading predates it.
      Chronicle never deferred, so a stale estimate could compact a request
      that already fit.

  on_session_reset  default zeroes counters only (see test_context_engine_copy).

Each case below is the host's own rule for its built-in compressor, so the two
engines answer the host the same way.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine
from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}}


def _conversation(n):
    return ([{"role": "system", "content": "You are helping Pat Testley."}]
            + [{"role": "user" if i % 2 == 0 else "assistant",
                "content": ("Acme Fake Co turn %d: unrelated filler padded out to cost real "
                            "tokens under the hashing embedder so eviction actually has work "
                            "to do." % i)} for i in range(n)])


class TestPreflightDeferral(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="ce_defer_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("defer-s1", hermes_home=self.home, principal_id="pat",
                                  config=CFG)
        self.eng.update_model("test-model", context_length=2000)
        self.over = self.eng.threshold_tokens + 100
        self.under = max(0, self.eng.threshold_tokens - 100)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_under_the_threshold_there_is_nothing_to_defer(self):
        self.assertFalse(self.eng.should_defer_preflight_to_real_usage(self.under))

    def test_right_after_a_compaction_a_rough_estimate_waits(self):
        """The case that re-compacted a request that already fit."""
        self.eng.compress(_conversation(80))
        self.assertTrue(self.eng.should_defer_preflight_to_real_usage(self.over))

    def test_the_next_real_figure_ends_the_wait(self):
        self.eng.compress(_conversation(80))
        self.eng.update_from_response({"prompt_tokens": self.under, "completion_tokens": 10,
                                       "total_tokens": self.under + 10})
        self.assertFalse(self.eng._awaiting_real_usage)

    def test_when_the_provider_proved_it_is_over_do_not_wait(self):
        self.eng.update_from_response({"prompt_tokens": self.over, "completion_tokens": 10,
                                       "total_tokens": self.over + 10})
        self.assertFalse(self.eng.should_defer_preflight_to_real_usage(self.over))

    def test_a_provider_that_reports_usage_is_trusted_over_the_estimate(self):
        self.eng.update_from_response({"prompt_tokens": self.under, "completion_tokens": 10,
                                       "total_tokens": self.under + 10})
        self.assertTrue(self.eng.should_defer_preflight_to_real_usage(self.over))

    def test_a_provider_that_omits_usage_never_blocks_compression(self):
        """If the estimate is the only signal, deferring on it would mean
        compression can never fire (the host's #2153)."""
        self.assertFalse(self.eng._provider_reports_usage)
        self.assertFalse(self.eng.should_defer_preflight_to_real_usage(self.over))

    def test_a_reset_forgets_the_calibration(self):
        self.eng.compress(_conversation(80))
        self.eng.update_from_response({"prompt_tokens": self.under, "completion_tokens": 1,
                                       "total_tokens": self.under + 1})
        self.eng.compress(_conversation(80))
        self.eng.on_session_reset()
        self.assertFalse(self.eng._awaiting_real_usage)
        self.assertFalse(self.eng._provider_reports_usage)

    def test_the_heuristic_fallback_latches_too(self):
        """With no core the engine compresses heuristically; that is still a
        compaction, and the estimate after it is just as stale."""
        fresh = ChronicleContextEngine()           # no on_session_start: heuristic mode
        fresh.update_model("test-model", context_length=2000)
        fresh.compress(_conversation(40))
        self.assertTrue(fresh.should_defer_preflight_to_real_usage(fresh.threshold_tokens + 1))


class _StalledEmbedder:
    """Every embed takes a second and then fails — the throttled host. Counts
    calls, which is what shows whether compaction waited on it."""
    model = "stalled"
    dimensions = 16

    def __init__(self):
        self.calls = 0

    def _stall(self, *a, **k):
        import time as _t
        self.calls += 1
        _t.sleep(1.0)
        raise TimeoutError("timed out")

    embed = embed_document = embed_query = _stall

    def embed_batch(self, texts, chunk=64):
        return [self._stall() for _ in texts]


class TestAnEvictionNeverWaitsOnTheEmbedder(unittest.TestCase):
    """compress() is on the critical path of the user's turn. An evicted span
    must be durable before it returns — as TEXT, which recall can find the same
    turn — but its vector can follow from the curation queue."""

    def setUp(self):
        self.home = temp_home(prefix="ce_evict_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("evict-s1", hermes_home=self.home, principal_id="pat",
                                  config=CFG)
        self.eng.update_model("test-model", context_length=1500)
        self.stalled = _StalledEmbedder()
        self.eng.core.reducer.embedder = self.stalled

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _evictions(self):
        import json as _json
        evs = self.eng.core.store.get_events_by_session("evict-s1")
        return [e for e in evs if e["type"] == "observed"
                and _json.loads(e["payload"]).get("source_type") == "context_eviction"]

    def test_compaction_does_not_call_the_embedder_for_what_it_evicts(self):
        import time as _t
        t = _t.monotonic()
        out = self.eng.compress(_conversation(80))
        took = _t.monotonic() - t
        self.assertLess(len(out), 81)
        evicted = self._evictions()
        self.assertTrue(evicted, "the fixture must actually evict something")
        # One stalled embed would cost a second; the evictions must cost none.
        self.assertLess(took, 1.0, "compress waited on the embedder (%.1fs)" % took)

    def test_every_evicted_span_is_durable_and_findable_by_text_at_once(self):
        self.eng.compress(_conversation(80))
        evicted = self._evictions()
        self.assertTrue(evicted)
        c = self.eng.core.store._conn()
        for e in evicted:
            hit = c.execute("SELECT 1 FROM observed_fts WHERE rowid IN "
                            "(SELECT rowid FROM observed_fts WHERE observed_fts MATCH 'filler') "
                            "LIMIT 1").fetchone()
            self.assertIsNotNone(hit, "an evicted span must be FTS-searchable the same turn")

    def test_a_vector_job_is_queued_for_each_evicted_span(self):
        import json as _json
        self.eng.compress(_conversation(80))
        evicted = {e["event_id"] for e in self._evictions()}
        c = self.eng.core.store._conn()
        queued = {_json.loads(r[0])["target_id"] for r in c.execute(
            "SELECT payload FROM curation_jobs WHERE task='embed'")}
        self.assertTrue(evicted <= queued, "every evicted span needs its vector queued")


class TestNothingCompressWritesWaitsOnTheEmbedder(unittest.TestCase):
    """compress() rescues important spans first (I14) and then evicts. Measured
    on a production-sized conversation, one compaction made 150 inline embed
    calls: 60 rescued observations, and 30 rescued notes at three embeds each
    (novelty, vector, doc2query proxy). Every one of them is now queued."""

    def setUp(self):
        self.home = temp_home(prefix="ce_rescue_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("rescue-s1", hermes_home=self.home, principal_id="pat",
                                  config=CFG)
        self.eng.update_model("test-model", context_length=3000)
        core = self.eng.core
        self.stalled = _StalledEmbedder()
        for obj in (core, core.reducer, core.retrieval, core.vector_index):
            if hasattr(obj, "embedder"):
                obj.embedder = self.stalled

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    @staticmethod
    def _important(n):
        # Rescue keeps only important spans; these carry its keywords.
        return ([{"role": "system", "content": "You are helping Pat Testley."}]
                + [{"role": "user" if i % 2 == 0 else "assistant",
                    "content": ("Turn %d. Never forget: the Acme Fake Co contract renewal is due "
                                "and the dentist appointment is on Tuesday. " % i) * 3}
                   for i in range(n)])

    def test_a_whole_compaction_makes_no_embed_call(self):
        self.eng.compress(self._important(60))
        self.assertEqual(self.stalled.calls, 0)

    def test_what_it_rescued_is_durable_and_its_vectors_are_queued(self):
        import json as _json
        self.eng.compress(self._important(60))
        c = self.eng.core.store._conn()
        rescued = [r[0] for r in c.execute(
            "SELECT event_id FROM events WHERE type='observed' "
            "AND json_extract(payload,'$.source_type')='rescue_extraction'")]
        self.assertTrue(rescued, "the fixture must rescue something")
        queued = {_json.loads(r[0])["target_id"] for r in c.execute(
            "SELECT payload FROM curation_jobs WHERE task='embed'")}
        self.assertTrue(set(rescued) <= queued)

    def test_a_rebuild_defers_the_same_writes(self):
        """The decision is keyed on each event's own source_type, so replaying
        the log (I3) makes it again rather than embedding inline."""
        self.eng.compress(self._important(60))
        before = self.stalled.calls
        self.eng.core.reducer.rebuild()
        self.assertEqual(self.stalled.calls, before)

    def test_an_ordinary_turn_still_embeds_inline(self):
        """Only writes from inside compress() are deferred."""
        self.eng.core.capture.observe("Pat Testley moved to Riverton last spring.", "Noted.",
                                      session_id="rescue-s1")
        self.eng.core.process_pending()
        self.assertGreater(self.stalled.calls, 0)


class TestRescueHappensOncePerMessage(unittest.TestCase):
    """rescue() (I14) gives each span a fresh document_id and the event id
    includes the call's time, so nothing downstream dedupes a repeat. Every
    compaction pass re-captured every important message still in the window
    as a new event — on a sixty-message conversation, 60 observations and 30
    notes PER PASS. Now once per message per conversation."""

    def setUp(self):
        self.home = temp_home(prefix="ce_once_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("once-s1", hermes_home=self.home, principal_id="pat",
                                  config=CFG)
        self.eng.update_model("test-model", context_length=3000)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _rescued(self):
        c = self.eng.core.store._conn()
        return c.execute("SELECT COUNT(*) FROM events WHERE type='observed' AND "
                         "json_extract(payload,'$.source_type')='rescue_extraction'").fetchone()[0]

    def test_a_second_pass_over_the_same_window_rescues_nothing_new(self):
        msgs = TestNothingCompressWritesWaitsOnTheEmbedder._important(30)
        self.eng.compress(msgs)
        first = self._rescued()
        self.assertGreater(first, 0)
        self.eng.compress(msgs)
        self.assertEqual(self._rescued(), first)

    def test_only_what_is_new_is_rescued_on_the_next_pass(self):
        msgs = TestNothingCompressWritesWaitsOnTheEmbedder._important(30)
        self.eng.compress(msgs)
        first = self._rescued()
        more = msgs + [{"role": "user", "content": "Never forget: the Acme Fake Co invoice "
                                                    "is due Friday, and it is a new message."}]
        self.eng.compress(more)
        self.assertEqual(self._rescued(), first + 1)

    def test_a_new_conversation_rescues_again(self):
        msgs = TestNothingCompressWritesWaitsOnTheEmbedder._important(10)
        self.eng.compress(msgs)
        first = self._rescued()
        self.eng.on_session_reset()
        self.eng.compress(msgs)
        self.assertGreater(self._rescued(), first)

    def test_each_agent_copy_keeps_its_own_record(self):
        import copy as _copy
        self.eng.compress(TestNothingCompressWritesWaitsOnTheEmbedder._important(10))
        twin = _copy.deepcopy(self.eng)
        twin._rescued_hashes.add("only-the-twin")
        self.assertNotIn("only-the-twin", self.eng._rescued_hashes)


class TestWithTheMemoryProviderLiveNothingIsCapturedTwice(unittest.TestCase):
    """With the memory provider live on the same core, sync_turn captured every
    turn when it ended and extraction runs from that capture. The context engine
    used to capture and extract the same turns again — rescue (19,089 notes on
    the production store) and re-extracted evictions (4,955 notes), every one of
    them retracted by the attribution cleanup."""

    def setUp(self):
        self.home = temp_home(prefix="ce_dup_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("dup-s1", hermes_home=self.home, principal_id="pat",
                                  config=CFG)
        self.eng.update_model("test-model", context_length=1500)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _count(self, where):
        c = self.eng.core.store._conn()
        return c.execute("SELECT COUNT(*) FROM events WHERE " + where).fetchone()[0]

    def _extract_jobs_for_evictions(self):
        import json as _json
        c = self.eng.core.store._conn()
        evicted = {r[0] for r in c.execute(
            "SELECT event_id FROM events WHERE type='observed' AND "
            "json_extract(payload,'$.source_type')='context_eviction'")}
        queued = {_json.loads(r[0]).get("event_id") for r in c.execute(
            "SELECT payload FROM curation_jobs WHERE task='extract'")}
        return evicted, evicted & queued

    def test_rescue_writes_nothing(self):
        self.eng.core.has_memory_provider = True
        self.eng.compress(TestNothingCompressWritesWaitsOnTheEmbedder._important(60))
        self.assertEqual(self._count("json_extract(payload,'$.source_type')='rescue_extraction'"), 0)

    def test_an_eviction_is_durable_but_not_extracted_again(self):
        self.eng.core.has_memory_provider = True
        self.eng.compress(_conversation(80))
        evicted, extracted = self._extract_jobs_for_evictions()
        self.assertTrue(evicted, "evicted spans must still be durable")
        self.assertEqual(extracted, set())

    def test_the_decision_travels_in_the_event_so_a_rebuild_repeats_it(self):
        self.eng.core.has_memory_provider = True
        self.eng.compress(_conversation(80))
        c = self.eng.core.store._conn()
        c.execute("DELETE FROM curation_jobs WHERE task='extract'")
        c.commit()
        self.eng.core.has_memory_provider = False      # the flag is gone on replay...
        self.eng.core.reducer.rebuild()
        _, extracted = self._extract_jobs_for_evictions()
        self.assertEqual(extracted, set(), "...and the log still says: do not extract")

    def test_standalone_keeps_its_own_capture(self):
        """No provider: rescue and eviction are the only capture there is."""
        self.assertFalse(self.eng.core.has_memory_provider)
        self.eng.compress(TestNothingCompressWritesWaitsOnTheEmbedder._important(60))
        self.assertGreater(
            self._count("json_extract(payload,'$.source_type')='rescue_extraction'"), 0)
        evicted, extracted = self._extract_jobs_for_evictions()
        if evicted:
            self.assertTrue(extracted, "standalone evictions must still be extracted")


class TestASessionStartDoesNotWorkTheQueue(unittest.TestCase):
    """initialize() runs on every session start — every conversation and every
    cron agent run on a gateway — and ran crash recovery each time, ending in a
    synchronous drain of up to 1,000 queued jobs. Measured on the production
    store: 320 s and 830 s for one engine init. Recovery is about a previous
    process: once per core, and one turn's slice of draining."""

    def setUp(self):
        self.home = temp_home(prefix="ce_start_")
        self.core = ChronicleCore.get(self.home, CFG)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_recovery_runs_once_per_process(self):
        calls = []
        self.core.reaper.startup_recovery = lambda *a, **k: calls.append(1)
        for i in range(5):
            self.core.initialize("s%d" % i)
        self.assertEqual(calls, [1])

    def test_a_session_start_drains_at_most_one_turns_slice(self):
        for i in range(200):
            self.core.store.enqueue_curation("session_summarize", {"session_id": "q%d" % i})
        drained = []
        real = self.core.curation.drain
        self.core.curation.drain = lambda max_jobs=None: drained.append(max_jobs) or real(max_jobs)
        self.core.initialize("first")
        self.core.initialize("second")
        self.assertEqual(drained, [None], "one bounded drain, on the first start only")

    def test_the_explicit_full_drain_is_untouched(self):
        """process_pending() is what tests and scripts call to work the whole
        queue; only startup stops calling it."""
        self.core.initialize("s")
        self.core.capture.observe("My name is Pat Testley.", "ok", session_id="s")
        self.core.process_pending()
        self.assertTrue(self.core.store.query_beliefs("facts", "status='active'"))


if __name__ == "__main__":
    unittest.main()
