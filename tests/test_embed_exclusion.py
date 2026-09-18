"""
Chronicle — `embeddings.exclude_session_prefixes` holds on every path.

On the production box the embedding server is the bottleneck (~7 s per 200
words while throttled) and ~98% of what it embedded was cron transcripts —
text that, since 5.7.2, never becomes the user's memory and that the per-turn
recall never reads. The write path already skipped excluded sessions; a job
queued before the prefix was excluded (or by an older build) still embedded
them from the curation queue.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore

CRON = "cron_abc123_20260917_000000"
CHAT = "20260917_161616_ff66aa"


class TestExcludedSessionsAreNotEmbedded(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="embex_")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing",
                                                             "exclude_session_prefixes": ["cron_"]}})

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _observe(self, sid, text):
        return self.core.capture.append("observed", {"source_type": "session_transcript",
                                                     "excerpt": text}, actor="user", session_id=sid)

    def test_the_write_path_skips_them(self):
        cron = self._observe(CRON, "Zorblax dispatch run 7: verifier re-asserted.")
        chat = self._observe(CHAT, "We booked the Izakaya Nonesuch for Friday.")
        self.assertFalse(self.core.store.has_observed_vector(cron))
        self.assertTrue(self.core.store.has_observed_vector(chat))

    def test_a_queued_job_does_not_embed_them_either(self):
        cron = self._observe(CRON, "Zorblax dispatch run 8: verifier re-asserted.")
        self.core.curation._task_embed({"target_id": cron, "kind": "observed",
                                        "text": "Zorblax dispatch run 8: verifier re-asserted."})
        self.assertFalse(self.core.store.has_observed_vector(cron))

    def test_a_queued_job_for_the_user_still_embeds(self):
        chat = self._observe(CHAT, "Robin Placeholder moved to Riverton.")
        self.core.store.delete_observed_vector(chat)
        self.assertFalse(self.core.store.has_observed_vector(chat))
        self.core.curation._task_embed({"target_id": chat, "kind": "observed",
                                        "text": "Robin Placeholder moved to Riverton."})
        self.assertTrue(self.core.store.has_observed_vector(chat))


if __name__ == "__main__":
    unittest.main()
