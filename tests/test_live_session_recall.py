"""
Chronicle — per-turn recall does not repeat the conversation in progress.

The provider captures every turn as it happens, so a follow-up ("is the
Izakaya booking still on?") found the user's own message from minutes earlier
and injected it again -- a turn the model already has in its window. Measured
on the production store: of 101 real messages, 10 got an excerpt of their own
conversation from before them, ~22,000 characters, about 44% of all recalled
text. Prefetch now leaves out the live session's turns, except the copies the
context engine wrote when it folded messages OUT of the window: those are
exactly what the window no longer has.

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
OLD = "20260910_101010_aa00bb"
LIVE = "20260918_121212_cc11dd"
ASK = "Is the Izakaya Nonesuch booking still on?"


class TestTheLiveSession(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="livesess_")
        self.prov = ChronicleMemoryProvider()
        self.prov.initialize(OLD, hermes_home=self.home, principal_id="default", config=CFG)
        core = self.core = self.prov.core
        core.capture.observe("The Izakaya Nonesuch closes early on Sundays in Riverton.", "Noted.",
                             session_id=OLD)
        core.capture.finalize_session(OLD, "clean_exit")
        core.initialize(LIVE, principal_id="default")
        core.capture.observe("I booked the Izakaya Nonesuch for Friday at seven.", "Great.", session_id=LIVE)
        core.capture.observe("The Izakaya Nonesuch deposit is paid by Pat Testley.", "Got it.",
                             session_id=LIVE)
        core.process_pending()
        self.prov.on_session_switch(LIVE)

    def tearDown(self):
        ChronicleCore._instances.pop(self.core.store.db_path, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def fold(self, said):
        """What the context engine writes when it folds a user message out."""
        self.core.capture.append("observed", {
            "source_type": "context_eviction", "excerpt": said, "source_ref": LIVE,
            "speakers": [[0, len(said), "human"]], "attribution": {"user_side": "human", "role": "user"}},
            actor="user", session_id=LIVE)
        self.core.process_pending()

    def test_the_fixture_puts_both_conversations_in_reach(self):
        ctx = self.prov.prefetch(ASK, session_id="20260919_000000_ee22ff")
        self.assertIn("closes early", ctx)
        self.assertIn("for Friday", ctx)

    def test_an_earlier_conversation_is_recalled_the_live_one_is_not(self):
        ctx = self.prov.prefetch(ASK, session_id=LIVE)
        self.assertIn("closes early", ctx)
        self.assertNotIn("for Friday", ctx)
        self.assertNotIn("deposit is paid", ctx)
        self.assertGreater(self.core.retrieval.last_context_debug["relevance_gate"]["live_session"], 0)

    def test_the_provider_knows_its_session_when_the_host_does_not_say(self):
        self.assertNotIn("for Friday", self.prov.prefetch(ASK))

    def test_what_compaction_folded_out_is_recalled_and_nothing_else_of_it(self):
        self.fold("I booked the Izakaya Nonesuch for Friday at seven.")
        ctx = self.prov.prefetch(ASK, session_id=LIVE)
        self.assertIn("for Friday", ctx)          # the folded copy
        self.assertNotIn("deposit is paid", ctx)  # still in the window: not pulled in with it

    def test_explicit_search_is_not_narrowed(self):
        ctx = self.core.retrieval.get_context(ASK, token_budget=1200, principal="default",
                                              exclude_automation=True)
        self.assertIn("for Friday", ctx)


if __name__ == "__main__":
    unittest.main()
