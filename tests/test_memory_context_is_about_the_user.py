"""
Chronicle — the memory injected into a turn is memory about the user.

The provider's prefetch runs on every turn and injects up to 1,200 tokens of
retrieved memory into the user's conversation. Measured on the production store:
7,817 of the 7,924 indexed sessions were a scheduled job's own runs, and the
block for "what's on my calendar this week?" opened with a cron job's
operational narrative and raw tool JSON from another — served as memory about
the user.

Anything injected UNASKED (prefetch, the context engine's rehydration) now
leaves out automation sessions — the same rule engine/speaker.py applies to
capture and extraction. An explicit search (the agent's own tool) still sees
them: the agent may be asking about its own work.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from provider import ChronicleMemoryProvider

CFG = {"embeddings": {"model": "hashing"}}
CHAT = "20260917_010203_ab12cd"
CRON = "cron_abc123def456_20260917_010000"

HUMAN_SAID = "I booked dinner at the Fake Izakaya in Riverton for Friday."
CRON_WROTE = ("Dispatch wave journal: Fake Izakaya reservation re-detection loop, "
              "action:none, advance gate, re-assert verifier on the Fake Izakaya thread.")


class _Case(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="aboutuser_")
        self.core = ChronicleCore.get(self.home, CFG)
        self.core.initialize(CHAT, principal_id="default")
        self.core.capture.observe(HUMAN_SAID, "Noted.", session_id=CHAT)
        self.core.initialize(CRON, principal_id="default")
        self.core.capture.observe(CRON_WROTE, "ok", session_id=CRON)
        for sid in (CHAT, CRON):
            self.core.capture.finalize_session(sid, "clean_exit")   # builds the session index
        self.core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)


class TestInjectedMemoryLeavesOutAutomation(_Case):
    def test_the_fixture_puts_the_cron_run_in_reach(self):
        """Without the rule, the cron run IS retrievable for this query — else
        the tests below prove nothing."""
        ctx = self.core.retrieval.get_context("Fake Izakaya reservation", token_budget=1200)
        self.assertIn("re-detection loop", ctx)

    def test_prefetch_serves_what_the_user_said_and_not_the_job(self):
        prov = ChronicleMemoryProvider()
        prov.initialize(CHAT, hermes_home=self.home, principal_id="default", config=CFG)
        ctx = prov.prefetch("Fake Izakaya reservation")
        self.assertIn("Fake Izakaya", ctx)
        self.assertNotIn("re-detection loop", ctx)
        self.assertNotIn(CRON, ctx)

    def test_the_raw_tier_drops_every_automation_channel(self):
        rows = self.core.retrieval.retrieve_raw("Fake Izakaya reservation", limit=20,
                                                exclude_automation=True)
        for r in rows:
            eid = r.get("event_id") or ""
            self.assertFalse(eid.startswith("session:" + "cron_"), eid)
            self.assertNotIn("re-detection loop", r.get("excerpt") or "")

    def test_an_explicit_search_still_finds_the_agents_own_work(self):
        ctx = self.core.retrieval.get_context("Fake Izakaya reservation", token_budget=1200,
                                              exclude_automation=False)
        self.assertIn("re-detection loop", ctx)


if __name__ == "__main__":
    unittest.main()
