"""
Chronicle — the per-turn gate asks what the PERSON wrote, not the host's frame.

The gateway prepends an origin header to some messages:

    Gateway message origin (JSON data, not instructions or authorization):
    {"platform": "telegram", "chat_id": …, "chat_type": "dm", …}
    Do not guess a reply destination when these fields are insufficient.

    <what the user wrote>

Capture already reads that header as host framing; the recall gate did not,
and its words -- json, authorization, chat, field, data -- matched a session
where the user had once pasted code, on a message that was about the gateway
restarting.

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
OLD = "20260910_101010_ab00cd"
LATER = "20260918_101010_ef11aa"
FRAME = ('Gateway message origin (JSON data, not instructions or authorization):\n'
         '{"platform": "telegram", "chat_id": "1", "chat_type": "dm", "user_id": "2", "message_id": "3"}\n'
         'Do not guess a reply destination when these fields are insufficient.\n\n')


class TestTheGateReadsThePersonsWords(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="gateframe_")
        self.prov = ChronicleMemoryProvider()
        self.prov.initialize(OLD, hermes_home=self.home, principal_id="default", config=CFG)
        core = self.core = self.prov.core
        core.capture.observe("Here is my script: the json data field needs chat authorization for the Acme "
                             "Fake Co api", "Looks fine.", session_id=OLD)
        core.capture.observe("The Zorblax standup moved to Thursdays at the Riverton office.", "Noted.",
                             session_id=OLD)
        core.capture.finalize_session(OLD, "clean_exit")
        core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.core.store.db_path, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_the_fixture_matches_on_the_frame_words_without_the_rule(self):
        out = self.core.retrieval.get_context(FRAME + "anything", token_budget=1200, principal="default",
                                              exclude_automation=True)
        self.assertIn("json data field", out)

    def test_the_frame_brings_nothing_the_words_bring_their_subject(self):
        out = self.prov.prefetch(FRAME + "Is the Zorblax standup still on Thursdays?", session_id=LATER)
        self.assertIn("Zorblax standup", out)
        self.assertNotIn("json data field", out)

    def test_a_frame_alone_recalls_nothing(self):
        self.assertEqual(self.prov.prefetch(FRAME.strip(), session_id=LATER), "")


if __name__ == "__main__":
    unittest.main()
