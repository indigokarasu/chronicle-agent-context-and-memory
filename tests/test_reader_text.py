"""
Chronicle — recalled text is what was said, not the host's framing around it.

Capture stores an excerpt byte-for-byte and marks the host framing inside it
with speaker spans, which is what keeps a compaction handoff or a system note
out of extraction. Retrieval handed the stored text to a reader unchanged, so
recall could serve an earlier compaction's summary, a system note or a
<memory-context> block (Chronicle's own previous injection) back as if it were
the conversation. And the session summary, built from every observed event in
the session including the compressor's eviction copies, carried the same
frames into the session vector: 24 of the 107 interactive session summaries on
the production store held a "[CONTEXT COMPACTION — REFERENCE ONLY]" handoff.

Fixtures use obviously fake values.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine import speaker as spk
from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}}
CHAT = "20260917_101010_aa11bb"

HANDOFF = ("[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into "
           "the summary below. Pat Testley discussed the Zorblax quarterly filing.")


class TestTheReadersCopy(unittest.TestCase):
    def test_nothing_to_remove_is_the_stored_text_itself(self):
        plain = "User: I booked dinner at Izakaya Nonesuch.\nAssistant: Noted."
        self.assertIs(spk.strip_framing(plain), plain)
        self.assertIs(spk.reader_text({"source_type": "session_transcript", "excerpt": plain}),
                      plain)

    def test_a_handoff_message_goes_with_its_label(self):
        ex = "User: %s\nAssistant: ok\nUser: What time is it?\nAssistant: Noon." % HANDOFF
        self.assertEqual(spk.strip_framing(ex),
                         "Assistant: ok\nUser: What time is it?\nAssistant: Noon.")

    def test_a_recalled_memory_block_is_not_the_user(self):
        ex = ("User: what's my plan for Friday?\n<memory-context>\n[FACT] plan: Zorblax "
              "review\n</memory-context>\nAssistant: Your plan is the review.")
        self.assertEqual(spk.strip_framing(ex),
                         "User: what's my plan for Friday?\nAssistant: Your plan is the review.")

    def test_a_system_row_is_framing(self):
        self.assertEqual(spk.strip_framing("system: You are a helpful agent.\nUser: hello there"),
                         "User: hello there")

    def test_the_assistants_words_are_never_edited(self):
        ex = "Assistant: [System note: I am quoting a note here]\nUser: thanks"
        self.assertIs(spk.strip_framing(ex), ex)

    def test_a_single_stored_message_is_read_by_its_spans(self):
        span_all = {"source_type": "context_eviction", "excerpt": HANDOFF,
                    "speakers": [[0, len(HANDOFF), spk.SYSTEM]]}
        self.assertEqual(spk.reader_text(span_all, actor="system"), "")

    def test_an_older_eviction_is_read_by_its_actor(self):
        self.assertEqual(spk.reader_text({"source_type": "context_eviction", "excerpt": HANDOFF},
                                         actor="user"), "")
        tool = '{"status": "ok", "rows": 3}'
        self.assertIs(spk.reader_text({"source_type": "context_eviction", "excerpt": tool},
                                      actor="system"), tool)


TURN = ("User: %s\nAssistant: Understood.\nUser: Did the Zorblax filing go out before the "
        "Friday deadline?\nAssistant: Yes, it went out on Tuesday." % HANDOFF)


class TestExtraction(unittest.TestCase):
    def episodes(self, excerpt):
        from engine.extraction import HeuristicExtractor
        return [i for i in HeuristicExtractor().extract(excerpt, source_event="ev1").items
                if i["kind"] == "episode"]

    def test_an_episode_is_not_about_the_handoff(self):
        (ep,) = self.episodes(TURN)
        self.assertIn("Did the Zorblax filing go out before", ep["body"])
        self.assertNotIn("CONTEXT COMPACTION", ep["body"] + ep["key"]["title"])

    def test_a_turn_without_framing_keeps_its_episode(self):
        from engine.extraction import _strip_roles
        plain = ("User: Did the Zorblax filing go out before the Friday deadline?\n"
                 "Assistant: Yes, on Tuesday.")
        (ep,) = self.episodes(plain)
        self.assertEqual(ep["body"], _strip_roles(plain)[:400])

    def test_the_model_is_not_asked_to_summarise_the_handoff(self):
        from engine.extraction import LLMExtractor
        x = LLMExtractor("http://127.0.0.1:9", "fake-model")
        sent = []
        x._chat = lambda prompt: (sent.append(prompt), "{}")[1]
        x.extract(TURN, source_event="ev1")
        self.assertIn("Did the Zorblax filing go out before", sent[0])
        self.assertNotIn("CONTEXT COMPACTION", sent[0])


FILE_READ = ('{"content": "41|  \\"notes\\": \\"Zorblax calendar sync, no changes made\\",\\n'
             '42|  \\"resolution\\": \\"passed\\""}')
TOOL_TURN = ("User: Can you check whether the Zorblax filing deadline moved?\n"
             "Assistant: Checking the tracker file.\n"
             "tool: %s\n"
             "Assistant: The Zorblax deadline is still Friday." % FILE_READ)


class TestToolOutputIsNotWhatWasSaid(unittest.TestCase):
    def test_left_in_by_default(self):
        self.assertIs(spk.strip_framing(TOOL_TURN), TOOL_TURN)

    def test_dropped_on_request_label_and_body(self):
        said = spk.strip_framing(TOOL_TURN, drop_tools=True)
        self.assertNotIn("calendar sync", said)
        self.assertNotIn("tool:", said)
        self.assertIn("Assistant: The Zorblax deadline is still Friday.", said)

    def test_a_stored_tool_span_is_dropped_on_request(self):
        msg = "Result: " + FILE_READ
        p = {"source_type": "context_eviction", "excerpt": msg,
             "speakers": [[0, len(msg), spk.TOOL]]}
        self.assertIs(spk.reader_text(p, actor="agent"), msg)
        self.assertEqual(spk.reader_text(p, actor="agent", drop_tools=True), "")

    def test_an_episode_is_not_the_file_it_read(self):
        from engine.extraction import HeuristicExtractor
        (ep,) = [i for i in HeuristicExtractor().extract(TOOL_TURN, source_event="ev1").items
                 if i["kind"] == "episode"]
        self.assertNotIn("calendar sync", ep["body"])
        self.assertIn("deadline is still Friday", ep["body"])

    def test_the_model_is_not_sent_the_file(self):
        from engine.extraction import LLMExtractor
        x = LLMExtractor("http://127.0.0.1:9", "fake-model")
        sent = []
        x._chat = lambda prompt: (sent.append(prompt), "{}")[1]
        x.extract(TOOL_TURN, source_event="ev1")
        self.assertNotIn("calendar sync", sent[0])
        self.assertIn("deadline is still Friday", sent[0])


class _Store(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="readertext_")
        self.core = core = ChronicleCore.get(self.home, CFG)
        core.initialize(CHAT, principal_id="default")
        # The host's compaction handoff arrives as a user-role row, followed by
        # the user's real next message, in one captured turn.
        core.capture.observe("Did the Zorblax filing go out?", "Yes, on Tuesday.",
                             session_id=CHAT, messages=[
            {"role": "user", "content": HANDOFF},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Did the Zorblax filing go out?"},
            {"role": "assistant", "content": "Yes, on Tuesday."},
        ])
        # The compressor's durable copy of the evicted handoff.
        core.capture.append("observed", {
            "source_type": "context_eviction", "excerpt": HANDOFF, "source_ref": CHAT,
            "speakers": [[0, len(HANDOFF), spk.SYSTEM]],
            "attribution": {"user_side": spk.HUMAN, "role": "user"}},
            actor="system", session_id=CHAT)
        # ...and of a real message the transcript above already holds.
        said = "Did the Zorblax filing go out?"
        core.capture.append("observed", {
            "source_type": "context_eviction", "excerpt": said, "source_ref": CHAT,
            "speakers": [[0, len(said), spk.HUMAN]],
            "attribution": {"user_side": spk.HUMAN, "role": "user"}},
            actor="user", session_id=CHAT)
        core.capture.finalize_session(CHAT, "clean_exit")
        core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)


class TestRecall(_Store):
    def test_the_fixture_stores_the_handoff(self):
        """Stored byte-for-byte -- otherwise the tests below prove nothing."""
        stored = [json.loads(e["payload"])["excerpt"]
                  for e in self.core.store.get_events_by_session(CHAT) if e["type"] == "observed"]
        self.assertTrue(any("CONTEXT COMPACTION" in s for s in stored))

    def test_raw_recall_serves_the_conversation_not_the_handoff(self):
        rows = self.core.retrieval.retrieve_raw("Zorblax filing", limit=20)
        text = "\n".join(r.get("excerpt") or "" for r in rows)
        self.assertIn("Did the Zorblax filing go out?", text)
        self.assertNotIn("CONTEXT COMPACTION", text)
        self.assertNotIn("quarterly filing", text)     # the handoff's own summary

    def test_a_row_that_was_only_framing_is_not_recalled(self):
        rows = self.core.retrieval.retrieve_raw("Zorblax quarterly filing", limit=20)
        self.assertFalse([r for r in rows if not (r.get("excerpt") or "").strip()
                          and not (r.get("event_id") or "").startswith("session:")])

    def test_the_context_block_carries_no_handoff(self):
        ctx = self.core.retrieval.get_context("Zorblax filing", token_budget=1200)
        self.assertIn("Did the Zorblax filing go out?", ctx)
        self.assertNotIn("CONTEXT COMPACTION", ctx)

    def test_the_session_summary_carries_no_handoff(self):
        row = self.core.store.get_session_vector(CHAT) or {}
        self.assertIn("Zorblax filing go out", row.get("summary") or "")
        self.assertNotIn("CONTEXT COMPACTION", row.get("summary") or "")

    def test_the_session_summary_is_not_tool_output(self):
        sid = "20260917_121212_cc22dd"
        self.core.initialize(sid, principal_id="default")
        self.core.capture.observe("Can you check whether the Zorblax filing deadline moved?",
                                  "The Zorblax deadline is still Friday.", session_id=sid,
                                  messages=[
            {"role": "user", "content": "Can you check whether the Zorblax filing deadline moved?"},
            {"role": "assistant", "content": "Checking the tracker file."},
            {"role": "tool", "content": FILE_READ},
            {"role": "assistant", "content": "The Zorblax deadline is still Friday."}])
        self.core.capture.finalize_session(sid, "clean_exit")
        self.core.process_pending()
        summary = (self.core.store.get_session_vector(sid) or {}).get("summary") or ""
        self.assertIn("deadline is still Friday", summary)
        self.assertNotIn("calendar sync", summary)

    def test_the_session_summary_is_the_transcript_not_its_copies(self):
        summary = (self.core.store.get_session_vector(CHAT) or {}).get("summary") or ""
        self.assertEqual(summary.count("Zorblax filing go out"), 1, summary)


if __name__ == "__main__":
    unittest.main()
