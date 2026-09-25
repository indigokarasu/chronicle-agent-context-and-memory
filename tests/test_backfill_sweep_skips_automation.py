"""
Chronicle — backfill sweep marks automation sessions (F5).

The backfill_sweep task normally enqueues session_summarize for all ended
sessions lacking an index row. For automation sessions when
sessions.summarize_automation is False (the default), it writes an empty marker
row directly instead, avoiding queue traffic and stale job rows. This aligns
with the session_summarize handler's (S5) behavior for automation sessions.

The empty marker row lands in session_index so the session is not re-queued by
future backfill sweeps.

Fixtures use obviously fake values, same style as tests/test_skip_automation_embeds.py.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore

AUTOMATION = "cron_dispatch_20260924_000000"
USER = "20260924_161616_ff66aa"


class TestBackfillSweepMarksAutomationByDefault(unittest.TestCase):
    """The backfill sweep respects sessions.summarize_automation=False (the default)
    and marks automation sessions with an empty row instead of enqueueing."""

    def setUp(self):
        self.home = temp_home(prefix="backfill_auto_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_both_session_types_need_backfill(self):
        """Create two ended sessions with no index rows (simulating the backfill
        state).  Both should be returned by get_sessions_needing_index_backfill()."""
        # End both sessions: this creates a session in the sessions table but
        # does NOT create a session_index row for either.
        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "Zorblax dispatch run 1."},
                                 actor="user", session_id=AUTOMATION)
        self.core.capture.finalize_session(AUTOMATION, "clean_exit")

        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "We booked the Izakaya Nonesuch."},
                                 actor="user", session_id=USER)
        self.core.capture.finalize_session(USER, "clean_exit")

        # Both should need backfill (no index row yet).
        sids = self.core.store.get_sessions_needing_index_backfill(limit=200)
        self.assertIn(AUTOMATION, sids)
        self.assertIn(USER, sids)

    def test_backfill_sweep_marks_automation_enqueues_user(self):
        """The backfill sweep writes an empty marker for automation sessions
        and enqueues session_summarize only for user sessions."""
        # End both sessions.
        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "Zorblax dispatch run 2."},
                                 actor="user", session_id=AUTOMATION)
        self.core.capture.finalize_session(AUTOMATION, "clean_exit")

        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "We booked the Izakaya Nonesuch."},
                                 actor="user", session_id=USER)
        self.core.capture.finalize_session(USER, "clean_exit")

        # Manually invoke the backfill sweep.
        self.core.curation._task_backfill_sweep({})

        # Check which sessions got enqueued.
        conn = self.core.store._conn()
        jobs = conn.execute(
            "SELECT payload FROM curation_jobs WHERE task='session_summarize'").fetchall()
        enqueued_sids = [json.loads(j[0]).get("session_id") for j in jobs]

        # The user session should be enqueued.
        self.assertIn(USER, enqueued_sids)
        # The automation session should NOT be enqueued.
        self.assertNotIn(AUTOMATION, enqueued_sids)

        # The automation session should have an empty marker row.
        auto_row = self.core.store.get_session_vector(AUTOMATION)
        self.assertIsNotNone(auto_row, "automation session must have a marker row")
        self.assertEqual(auto_row["summary"], "")
        self.assertEqual(auto_row["embedding"], b"")
        self.assertIsNone(auto_row["model"])

    def test_second_sweep_does_not_requeue_marked_automation(self):
        """After the backfill sweep marks an automation session, a second
        sweep should not return it in candidates (it now has an index row)."""
        # End both sessions.
        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "Zorblax dispatch run 3."},
                                 actor="user", session_id=AUTOMATION)
        self.core.capture.finalize_session(AUTOMATION, "clean_exit")

        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "We booked the Izakaya Nonesuch."},
                                 actor="user", session_id=USER)
        self.core.capture.finalize_session(USER, "clean_exit")

        # First sweep.
        self.core.curation._task_backfill_sweep({})

        # Second sweep should not return the automation session (it now has a
        # session_index row from the marker).
        sids = self.core.store.get_sessions_needing_index_backfill(limit=200)
        self.assertNotIn(AUTOMATION, sids, "marked automation session must not be in backfill candidates")
        # The user session is still a candidate (it was enqueued, not marked).
        self.assertIn(USER, sids)


class TestBackfillSweepQueuesAutomationWhenConfigured(unittest.TestCase):
    """When sessions.summarize_automation is True, automation sessions are
    enqueued like any other."""

    def setUp(self):
        self.home = temp_home(prefix="backfill_auto_cfg_")
        self.core = ChronicleCore(self.home,
                                 {"embeddings": {"model": "hashing"},
                                  "sessions": {"summarize_automation": True}})

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_backfill_enqueues_automation_too_when_config_is_true(self):
        """With the override set, both session types are enqueued."""
        # End both sessions.
        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "Zorblax dispatch run 3."},
                                 actor="user", session_id=AUTOMATION)
        self.core.capture.finalize_session(AUTOMATION, "clean_exit")

        self.core.capture.append("observed",
                                 {"source_type": "session_transcript",
                                  "excerpt": "We booked the Izakaya Nonesuch."},
                                 actor="user", session_id=USER)
        self.core.capture.finalize_session(USER, "clean_exit")

        # Manually invoke the backfill sweep.
        self.core.curation._task_backfill_sweep({})

        # Check which sessions got enqueued.
        conn = self.core.store._conn()
        jobs = conn.execute(
            "SELECT payload FROM curation_jobs WHERE task='session_summarize'").fetchall()
        enqueued_sids = [json.loads(j[0]).get("session_id") for j in jobs]

        # Both should be enqueued.
        self.assertIn(USER, enqueued_sids)
        self.assertIn(AUTOMATION, enqueued_sids)


if __name__ == "__main__":
    unittest.main()
