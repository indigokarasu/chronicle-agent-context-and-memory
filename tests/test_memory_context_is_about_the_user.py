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
        prov.initialize("20260918_090000_bb22cc", hermes_home=self.home, principal_id="default",
                        config=CFG)             # a later conversation, recalling CHAT
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


class TestAutomationIsReadFromTheTurnNotJustTheSessionName(unittest.TestCase):
    """Capture records a turn's user side as automation for a subagent, a
    background review, a non-primary agent or a bot author, in a session whose
    id says nothing. On the production store, cron prompts sat in sessions with
    no `cron_` prefix."""

    def setUp(self):
        self.home = temp_home(prefix="aboutuser_attr_")
        self.core = ChronicleCore.get(self.home, CFG)
        sid = "20260917_020304_cd34ef"
        self.core.initialize(sid, principal_id="default")
        self.core.capture.observe(
            "Summarise the Fake Izakaya reservation thread for the digest.", "Done.",
            session_id=sid, speaker_context={"agent_context": "subagent"})
        self.core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_left_out_of_unasked_memory(self):
        r = self.core.retrieval
        self.assertTrue(r.retrieve_raw("Fake Izakaya reservation digest", limit=20))
        self.assertFalse(r.retrieve_raw("Fake Izakaya reservation digest", limit=20,
                                        exclude_automation=True))


class TestLeftOutRowsDoNotCostRealOnesTheirPlace(unittest.TestCase):
    """Rows that turn out to be nothing but host framing are judged before they
    take a top-k slot, so a real turn ranked below them still arrives."""

    def setUp(self):
        from engine import speaker as spk
        self.home = temp_home(prefix="aboutuser_slots_")
        self.core = core = ChronicleCore.get(self.home, CFG)
        sid = "20260917_030405_ef56ab"
        core.initialize(sid, principal_id="default")
        for i in range(4):
            h = ("[CONTEXT COMPACTION — REFERENCE ONLY] Handoff %d: the Zorblax filing, the "
                 "Zorblax filing deadline, the Zorblax filing owner." % i)
            core.capture.append("observed", {
                "source_type": "context_eviction", "excerpt": h, "source_ref": sid,
                "speakers": [[0, len(h), spk.SYSTEM]],
                "attribution": {"user_side": spk.HUMAN, "role": "user"}},
                actor="system", session_id=sid)
        core.capture.observe("Did the Zorblax filing go out?", "Yes.", session_id=sid)
        core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_the_real_turn_arrives(self):
        rows = self.core.retrieval.retrieve_raw("Zorblax filing deadline owner", limit=2)
        text = "\n".join(r.get("excerpt") or "" for r in rows)
        self.assertIn("Did the Zorblax filing go out?", text)

    def test_the_real_turn_arrives_by_words_alone(self):
        """The FTS channel on its own (no embedder): it ranks the handoffs first."""
        from unittest import mock
        r = self.core.retrieval
        with mock.patch.object(r, "embedder", None):
            rows = r.retrieve_raw("Zorblax filing deadline owner", limit=2)
        text = "\n".join(x.get("excerpt") or "" for x in rows)
        self.assertIn("Did the Zorblax filing go out?", text)


if __name__ == "__main__":
    unittest.main()
