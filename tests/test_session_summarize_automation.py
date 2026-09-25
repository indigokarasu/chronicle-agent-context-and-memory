"""
Chronicle — §R3: `session_summarize` is for interactive sessions only.

`session_index` held 324 rows for 12,143 sessions and only 147 of 952
INTERACTIVE sessions had a summary, while `session_summarize` (model-backed:
it embeds the session's summary text) was queued just the same for cron
sessions whose content retrieval never surfaces (`exclude_automation` drops
automation-session rows on every read path). Two changes, both gated by
`sessions.summarize_automation` (DEFAULTS default False):

  * `capture.finalize_session` skips the enqueue for an automation session
    (`speaker.is_automation_session`, the `cron_` prefix) instead of queuing
    a job nothing will read.
  * the `session_summarize` handler completes an automation session's job
    with an empty marker row -- no embed call -- so the existing backlog (and
    any job that still reaches it, e.g. via the backfill sweep) drains fast
    instead of paying for an embedding nobody will retrieve.

Fixtures use obviously fake values, same style as tests/test_embed_exclusion.py.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.config import Config
from engine.core import ChronicleCore

CRON = "cron_dispatch_20260917_000000"
CHAT = "20260917_161616_ff66aa"


def _jobs_by_session(core, sid=None):
    jobs = core.store.get_curation_jobs("task='session_summarize'", limit=100)
    if sid is None:
        return jobs
    return [j for j in jobs if json.loads(j["payload"]).get("session_id") == sid]


class TestSessionsConfigDefault(unittest.TestCase):
    def test_summarize_automation_defaults_false(self):
        self.assertFalse(Config({}).get("sessions.summarize_automation"))


class TestFinalizeSessionSkipsAutomationEnqueue(unittest.TestCase):
    """`capture.finalize_session` is the "on session end" producer of
    `session_summarize` jobs; an automation session must not feed one."""

    def setUp(self):
        self.home = temp_home(prefix="sessauto_enq_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _end(self, sid, text):
        self.core.capture.append("observed", {"source_type": "session_transcript", "excerpt": text},
                                 actor="user", session_id=sid)
        self.core.capture.finalize_session(sid, "clean_exit")

    def test_a_cron_session_ending_enqueues_nothing(self):
        self._end(CRON, "Zorblax dispatch run 9: verifier re-asserted.")
        self.assertEqual(_jobs_by_session(self.core, CRON), [])

    def test_a_normal_session_ending_still_enqueues_one(self):
        self._end(CHAT, "We booked the Izakaya Nonesuch for Friday.")
        self.assertEqual(len(_jobs_by_session(self.core, CHAT)), 1)


class TestSummarizeAutomationOverrideRestoresTheEnqueue(unittest.TestCase):
    def test_true_enqueues_for_a_cron_session_too(self):
        home = temp_home(prefix="sessauto_over_")
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"},
                                    "sessions": {"summarize_automation": True}})
        try:
            core.capture.append("observed", {"source_type": "session_transcript",
                                             "excerpt": "Zorblax dispatch run 10."},
                                actor="user", session_id=CRON)
            core.capture.finalize_session(CRON, "clean_exit")
            self.assertEqual(len(_jobs_by_session(core, CRON)), 1)
        finally:
            ChronicleCore._instances.pop(home, None)
            shutil.rmtree(home, ignore_errors=True)


class TestHandlerDrainsAutomationWithoutAModelCall(unittest.TestCase):
    """The backlog scenario: jobs already sit in the queue (as they do today
    on the live store) and the handler alone must decide what to do with
    them -- modeled on tests/test_embed_exclusion.py's queued-job checks."""

    def setUp(self):
        self.home = temp_home(prefix="sessauto_drain_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.capture.append("observed", {"source_type": "session_transcript",
                                              "excerpt": "Zorblax dispatch run 11: verifier re-asserted."},
                                 actor="user", session_id=CRON)
        self.core.capture.append("observed", {"source_type": "session_transcript",
                                              "excerpt": "We booked the Izakaya Nonesuch for Friday."},
                                 actor="user", session_id=CHAT)
        # Enqueued directly (not via finalize_session): the existing backlog
        # these jobs stand in for was queued before this change shipped.
        self.core.store.enqueue_curation("session_summarize", {"session_id": CRON})
        self.core.store.enqueue_curation("session_summarize", {"session_id": CHAT})
        self.core.curation.drain()

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_only_the_normal_session_gets_a_real_summary_and_vector(self):
        cron_row = self.core.store.get_session_vector(CRON)
        self.assertIsNotNone(cron_row, "the automation job must still leave a row (stops backfill re-queue)")
        self.assertEqual(cron_row["summary"], "")
        self.assertEqual(cron_row["embedding"], b"")
        self.assertIsNone(cron_row["model"])

        chat_row = self.core.store.get_session_vector(CHAT)
        self.assertIn("Izakaya Nonesuch", chat_row["summary"])
        self.assertTrue(chat_row["embedding"], "the normal session's summary must be embedded")
        self.assertIsNotNone(chat_row["model"])

    def test_both_jobs_end_done(self):
        cron_job = _jobs_by_session(self.core, CRON)[0]
        chat_job = _jobs_by_session(self.core, CHAT)[0]
        self.assertEqual(cron_job["status"], "done")
        self.assertEqual(chat_job["status"], "done")


if __name__ == "__main__":
    unittest.main()
