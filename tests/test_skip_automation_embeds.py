"""
Chronicle — automation-session observed events are never embedded (S5).

~97% of sessions are cron; on the production shape ~17.8k observed events land
a day and every read path already excludes automation text from recall
(retrieval's exclude_automation), so embedding it only spent the embedder --
and queue priority ahead of the user's own events -- on a transcript nothing
ever reads back. `embeddings.skip_automation` (default True) closes both
sides of that: the write path never defers an embed job for one in the first
place (engine/reducer.py `_on_observed`), and a job already queued -- from
before this flag existed, or from an embedder outage -- drains as a no-op in
the handler (engine/curation.py `_task_embed`) instead of spending the
embedder. The same mechanism keeps health's embedder-mismatch heal from
re-queuing an automation row it finds in the wrong geometry.

Modeled on tests/test_embed_exclusion.py, which exercises the sibling flag
`embeddings.exclude_session_prefixes` the same way: write path, then a
job that was already queued. Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.embeddings import DegradedEmbedder

CRON = "cron_daily_digest_20260924_040000"
CHAT = "20260924_161616_ff66aa"
DIMS = 8


class TestAutomationEventsAreNeverEmbedded(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="skipauto_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing", "dimensions": DIMS}})

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _observe(self, sid, text):
        return self.core.capture.append("observed", {"source_type": "session_transcript",
                                                     "excerpt": text}, actor="user", session_id=sid)

    def test_the_write_path_skips_a_cron_session_but_not_the_user(self):
        cron = self._observe(CRON, "Zorblax dispatch run 7: verifier re-asserted.")
        chat = self._observe(CHAT, "We booked the Izakaya Nonesuch for Friday.")
        self.assertFalse(self.core.store.has_observed_vector(cron))
        self.assertTrue(self.core.store.has_observed_vector(chat))

    def test_a_degraded_embedder_defers_for_the_user_not_for_automation(self):
        """`_on_observed` skips automation BEFORE the embedder is ever
        consulted, so an unreachable backend still defers a job for the user's
        own event but never queues one for the cron session at all."""
        deg = DegradedEmbedder(model="auto", dimensions=DIMS,
                               base_url="http://embedder.invalid/v1", recheck_seconds=0.0)
        self.core.embedder = deg
        self.core.reducer.embedder = deg
        cron = self._observe(CRON, "Zorblax dispatch run 9: verifier re-asserted.")
        chat = self._observe(CHAT, "Robin Placeholder moved to Riverton.")

        def job_count(eid):
            return self.core.store._conn().execute(
                "SELECT COUNT(*) FROM curation_jobs WHERE task='embed' AND instr(payload, ?)>0",
                (eid,)).fetchone()[0]

        self.assertEqual(job_count(cron), 0, "an automation session must not enqueue a deferred embed job")
        self.assertEqual(job_count(chat), 1)

    def test_drain_completes_the_cron_job_without_embedding_and_embeds_the_users(self):
        """The embed HANDLER: a job already queued for a cron session (queued
        before this flag existed, or during an outage) drains as a no-op
        instead of spending the embedder; the user's own queued job still
        embeds. Both jobs end up 'done' either way."""
        cron = self._observe(CRON, "Zorblax dispatch run 10: verifier re-asserted.")
        chat = self._observe(CHAT, "Robin Placeholder prefers the window seat.")
        self.core.store.delete_observed_vector(chat)
        cron_job = self.core.store.enqueue_embed_job(
            cron, "observed", "Zorblax dispatch run 10: verifier re-asserted.")
        chat_job = self.core.store.enqueue_embed_job(
            chat, "observed", "Robin Placeholder prefers the window seat.")
        self.assertIsNotNone(cron_job)
        self.assertIsNotNone(chat_job)

        drained = self.core.curation.drain(max_jobs=10)
        self.assertGreaterEqual(drained, 2)

        conn = self.core.store._conn()

        def status(job_id):
            return conn.execute("SELECT status FROM curation_jobs WHERE id=?", (job_id,)).fetchone()[0]

        self.assertEqual(status(cron_job), "done")
        self.assertEqual(status(chat_job), "done")
        self.assertFalse(self.core.store.has_observed_vector(cron),
                         "the embedder must not be called for an automation session")
        self.assertTrue(self.core.store.has_observed_vector(chat))


class TestTheFlagCanBeDisabled(unittest.TestCase):
    """Config-declared, off by exception rather than by default (§27):
    `embeddings.skip_automation: False` restores the pre-S5 behavior of
    embedding every observed event regardless of session."""

    def setUp(self):
        self.home = temp_home(prefix="skipauto_off_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing", "dimensions": DIMS,
                                                             "skip_automation": False}})

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_a_cron_session_is_embedded_when_the_flag_is_off(self):
        cron = self.core.capture.append(
            "observed", {"source_type": "session_transcript",
                        "excerpt": "Zorblax dispatch run 11: verifier re-asserted."},
            actor="user", session_id=CRON)
        self.assertTrue(self.core.store.has_observed_vector(cron))


if __name__ == "__main__":
    unittest.main()
