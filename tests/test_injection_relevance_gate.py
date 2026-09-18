"""
Chronicle — memory injected into a turn unasked must be about that turn.

The provider's prefetch puts up to 1,200 tokens of memory into every user turn.
Measured on the production store (after automation sessions were already left
out): every turn got the full ~4,800-char block whether or not anything in
memory concerned the message. Ranked retrieval always returns something -- FTS
ORs every word of the message, and a vector channel has a nearest neighbour for
any query -- and the session-window expansion then fills the rest of the budget
with the other turns of whatever session matched.

get_context(relevance_gate=True), which prefetch now passes, keeps an item only
if it shares a content word with the message; a message with no content words
("thanks!") gets nothing. Explicit retrieval (the agent's own search, the
context engine's rehydration, benchmarks) never sets the flag.

Fixtures use obviously fake values.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.retrieval import relevance_words, shares_content_word
from provider import ChronicleMemoryProvider

CFG = {"embeddings": {"model": "hashing"}}
CHAT = "20260917_010203_ab12cd"
CHAT2 = "20260916_090000_ef34ab"
CHAT3 = "20260915_070000_9f8e7d"
CHAT4 = "20260914_060000_1a2b3c"
# A tool result longer than one stored chunk: its tail -- with a word nothing
# else says -- opens a later chunk, with no label to say whose text it is.
LONG_TOOL = " ".join("Row %d of the export is unremarkable." % i for i in range(160)) + \
    " The last row names Quibblewick as the owner."
TOOL_OUT = '{"content": "41|  \\"notes\\": \\"Quibbleton calendar sync, no changes made\\""}'

IZAKAYA = "I booked dinner at Izakaya Nonesuch in Riverton for Friday."
SOLAR = [
    "My SunFake 9000 inverter keeps tripping its breaker again.",
    "The SunFake 9000 installer said the warranty covers the inverter.",
    "Remind me that the SunFake 9000 panels need cleaning in spring.",
]


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = temp_home(prefix="relgate_")
        cls.core = core = ChronicleCore.get(cls.home, CFG)
        core.initialize(CHAT, principal_id="default")
        core.capture.observe(IZAKAYA, "Noted, Friday at Izakaya Nonesuch.", session_id=CHAT)
        for line in SOLAR:       # same session: the session window would carry these
            core.capture.observe(line, "Got it.", session_id=CHAT)
        core.initialize(CHAT2, principal_id="default")
        core.capture.observe("I replaced the SunFake 9000 fuse myself, my hands still hurt.",
                             "Glad it worked.", session_id=CHAT2)
        core.capture.observe("Always file the Acme Fake Co paperwork in the blue folder",
                             "", session_id=CHAT2)
        core.capture.append("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "predicate_canonical": "allergy", "attribute": "allergy",
                    "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"},
            "body": "penicillin allergy", "confidence": 0.9, "source_event": "x",
            "source_type": "user_direct", "domain": "user"},
            actor="user", owner="default", trust_level=4)
        core.capture.append("asserted", {
            "kind": "fact",
            "key": {"entity_id": "e_robin_placeholder", "entity_name": "Robin Placeholder",
                    "predicate_canonical": "favorite_food", "attribute": "favorite_food",
                    "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"},
            "body": "tonkotsu ramen", "confidence": 0.9, "source_event": "x",
            "source_type": "user_direct", "domain": "user"},
            actor="user", owner="default", trust_level=4)
        # "calendar" appears in this session ONLY inside a tool's output.
        core.initialize(CHAT3, principal_id="default")
        core.capture.observe("Please tidy the tracker file for me.", "Done, tidied it.",
                             session_id=CHAT3, messages=[
            {"role": "user", "content": "Please tidy the tracker file for me."},
            {"role": "assistant", "content": "Reading it first."},
            {"role": "tool", "content": TOOL_OUT},
            {"role": "assistant", "content": "Done, tidied it."}])
        # A relevant turn WITH tool output in it: the words go in, the output not.
        core.capture.observe("Also add the tracker due dates for Friday.", "Added them.",
                             session_id=CHAT3, messages=[
            {"role": "user", "content": "Also add the tracker due dates for Friday."},
            {"role": "assistant", "content": "Reading the dates."},
            {"role": "tool", "content": '{"rows": "Quibbleton due-date export"}'},
            {"role": "assistant", "content": "Added them."}])
        core.initialize(CHAT4, principal_id="default")
        core.capture.observe("Export the Friday tracker rows please.", "Done with the Friday tracker.",
                             session_id=CHAT4, messages=[
            {"role": "user", "content": "Export the Friday tracker rows please."},
            {"role": "assistant", "content": "Exporting."},
            {"role": "tool", "content": LONG_TOOL},
            {"role": "assistant", "content": "Done with the Friday tracker."}])
        # The compressor's durable copy of one of the user's own messages: a
        # single message, no label, spans saying it is the user's.
        said = "I moved the Glimmerfen planning meeting to Thursday."
        core.capture.append("observed", {
            "source_type": "context_eviction", "excerpt": said, "source_ref": CHAT,
            "speakers": [[0, len(said), "human"]],
            "attribution": {"user_side": "human", "role": "user"}},
            actor="user", session_id=CHAT)
        # The compressor's copy of an evicted TOOL result: bare text, and only
        # its spans say it was a tool's.
        out = "Quibblequartz export: 14 rows written to the tracker."
        core.capture.append("observed", {
            "source_type": "context_eviction", "excerpt": out, "source_ref": CHAT,
            "speakers": [[0, len(out), "tool"]],
            "attribution": {"user_side": "human", "role": "tool"}},
            actor="agent", session_id=CHAT)
        # The agent's own memory tool, mirrored by on_memory_write.
        core.capture.agent_explicit(
            "add", "memory", "Izakaya Nonesuch dispatch loop: re-assert the verifier, "
            "action none, advance the gate on the Izakaya Nonesuch thread.")
        for sid in (CHAT, CHAT2, CHAT3, CHAT4):
            core.capture.finalize_session(sid, "clean_exit")
        core.process_pending()
        cls.prov = ChronicleMemoryProvider()
        cls.prov.initialize(CHAT, hermes_home=cls.home, principal_id="default", config=CFG)

    @classmethod
    def tearDownClass(cls):
        ChronicleCore._instances.pop(cls.home, None)
        shutil.rmtree(cls.home, ignore_errors=True)

    def ctx(self, q, gate):
        return self.core.retrieval.get_context(q, token_budget=1200, principal="default",
                                               exclude_automation=True, relevance_gate=gate)


class TestTheWordsOfAMessage(unittest.TestCase):
    def test_small_talk_has_no_content_words(self):
        for q in ("thanks!", "ok do it", "can you help me with that?", "yes please",
                  "what does this do?"):
            self.assertEqual(relevance_words(q), frozenset(), q)

    def test_the_topic_survives(self):
        self.assertEqual(relevance_words("what's on my calendar this week?"), {"calendar"})
        self.assertEqual(relevance_words("Does Robin's dog like the Fake Izakaya?"),
                         {"robin", "dog", "fake", "izakaya"})

    def test_plurals_possessives_and_short_inflections_match(self):
        w = relevance_words("restaurants in Riverton")
        self.assertTrue(shares_content_word(w, "We tried the restaurant."))
        self.assertTrue(shares_content_word(relevance_words("book it"), "I booked it"))
        self.assertTrue(shares_content_word(relevance_words("Robin"), "Robin's birthday"))

    def test_a_short_word_is_not_a_prefix_of_everything(self):
        self.assertFalse(shares_content_word(relevance_words("car"), "a birthday card"))
        self.assertFalse(shares_content_word(relevance_words("art"), "the artist"))
        self.assertTrue(shares_content_word(relevance_words("art"), "modern art"))

    def test_a_negation_is_not_a_word(self):
        self.assertEqual(relevance_words("don't"), frozenset())


class TestTheInjection(_Case):
    def test_the_fixture_puts_the_noise_in_reach(self):
        """Ungated, the SunFake chat and the unrelated tail DO reach the block --
        otherwise the tests below prove nothing."""
        ctx = self.core.retrieval.get_context("Is the Izakaya Nonesuch booking still on?",
                                              token_budget=6000, principal="default",
                                              exclude_automation=True)
        self.assertIn("Izakaya Nonesuch", ctx)
        self.assertIn("SunFake 9000", ctx)
        self.assertIn("penicillin", ctx)

    def test_only_what_is_about_the_message(self):
        ctx = self.prov.prefetch("Is the Izakaya Nonesuch booking still on?")
        self.assertIn("Izakaya Nonesuch", ctx)
        self.assertNotIn("SunFake 9000", ctx)      # same session, different subject
        self.assertNotIn("penicillin", ctx)      # critical, but not this subject
        self.assertNotIn("blue folder", ctx)     # a directive, but not this subject

    def test_small_talk_gets_nothing(self):
        self.assertEqual(self.prov.prefetch("thanks!"), "")
        dbg = self.core.retrieval.last_context_debug
        self.assertEqual(dbg["relevance_gate"]["words"], [])
        self.assertEqual(dbg["used_tokens"], 0)

    def test_small_talk_costs_no_retrieval(self):
        """Prefetch runs on EVERY turn and live retrieval takes seconds; a
        message that can match nothing must not pay for it."""
        from unittest import mock
        r = self.core.retrieval
        boom = mock.Mock(side_effect=AssertionError("retrieval ran for small talk"))
        with mock.patch.object(r, "search", boom), mock.patch.object(r, "retrieve_raw", boom), \
                mock.patch.object(r, "classify_route", boom):
            self.assertEqual(self.prov.prefetch("ok thanks, sounds good"), "")

    def test_nothing_on_the_subject_gets_nothing(self):
        self.assertNotEqual(self.ctx("what's on my calendar this week?", gate=False), "")
        self.assertEqual(self.prov.prefetch("what's on my calendar this week?"), "")

    def test_a_tools_output_is_not_memory_about_the_user(self):
        """Explicit recall still finds the tool's output -- the agent may be
        asking about its own work -- but it is not put into the user's turn."""
        q = "Quibbleton calendar sync"
        self.assertIn("Quibbleton calendar", self.ctx(q, gate=False))
        self.assertNotIn("Quibbleton calendar", self.prov.prefetch(q))

    def test_a_turn_keeps_its_words_and_loses_its_tool_output(self):
        ctx = self.prov.prefetch("add the tracker due dates")
        self.assertIn("tracker due dates", ctx)
        self.assertNotIn("Quibbleton", ctx)

    def test_the_session_window_carries_the_gated_text(self):
        """Phase 1 finds only the first turn; the session window brings the
        second, and it arrives without its tool output."""
        from unittest import mock
        r = self.core.retrieval
        real = r.retrieve_raw

        def first_turn_only(*a, **k):
            return [x for x in real(*a, **k) if "tidy the tracker" in (x.get("excerpt") or "")]
        with mock.patch.object(r, "retrieve_raw", side_effect=first_turn_only):
            ctx = self.prov.prefetch("the tracker due dates")
        self.assertIn("tidy the tracker", ctx)
        self.assertIn("tracker due dates", ctx)      # arrived through the window
        self.assertNotIn("Quibbleton", ctx)

    def test_preference_packing_carries_the_gated_text(self):
        """_pref_pack_fill widens a group with its session's other turns; under
        the gate each turn arrives as the gate's text, not the stored one."""
        from engine import speaker as spk
        r = self.core.retrieval
        groups = [{"sid": CHAT3, "date": "", "excerpts": [], "tails": []}]
        parts: list = []

        def keep(row):
            said = spk.strip_framing(row.get("excerpt") or "", drop_tools=True)
            return said if said.strip() else None
        r._pref_pack_fill(groups, parts, {}, set(), 6000, principal="default",
                          route="preference", keep=keep)
        text = "\n".join(parts)
        self.assertIn("tidy the tracker", text)
        self.assertNotIn("Quibbleton", text)

    def test_a_fact_is_found_by_the_name_of_who_it_is_about(self):
        """A fact renders `favorite_food: tonkotsu ramen`; the NAME is what the
        message says."""
        ctx = self.prov.prefetch("What does Robin Placeholder like to eat?")
        self.assertIn("tonkotsu ramen", ctx)

    def test_a_directive_on_the_subject_still_arrives(self):
        ctx = self.prov.prefetch("where does the Acme Fake Co paperwork go?")
        self.assertIn("blue folder", ctx)
        self.assertEqual(ctx.count("[DIRECTIVE] Always file"), 0 if "[NOTE] Always file" in ctx
                         else 1)   # once on the page, not once per tier

    def test_the_fixture_splits_the_long_turn(self):
        chunks = [json.loads(e["payload"]) for e in self.core.store.get_events_by_session(CHAT4)
                  if e["type"] == "observed"]
        later = [c for c in chunks if (c.get("chunk_index") or 0) > 0
                 and "Quibblewick" in c["excerpt"]]
        self.assertTrue(later)
        self.assertFalse(later[0]["excerpt"].lstrip().lower().startswith(("tool:", "user:",
                                                                         "assistant:")))

    def test_a_later_chunk_does_not_open_with_words_nobody_can_attribute(self):
        q = "Quibblewick owner"
        self.assertIn("Quibblewick", self.ctx(q, gate=False))
        self.assertNotIn("Quibblewick", self.prov.prefetch(q))

    def test_a_single_stored_message_of_the_users_is_injected(self):
        """Unlabelled is not the same as unattributable: a copy of one message
        says whose it is."""
        self.assertIn("Glimmerfen planning meeting", self.prov.prefetch("the Glimmerfen meeting"))

    def test_an_evicted_tool_result_is_not_memory_about_the_user(self):
        q = "Quibblequartz export"
        self.assertIn("Quibblequartz", self.ctx(q, gate=False))
        self.assertNotIn("Quibblequartz", self.prov.prefetch(q))

    def test_a_later_chunk_keeps_its_labelled_messages(self):
        self.assertIn("Done with the Friday tracker", self.prov.prefetch("the Friday tracker"))

    def test_the_agents_own_memory_is_not_memory_about_the_user(self):
        """Hermes puts the agent's current memory into every system prompt
        itself; Chronicle's older copy of it stays out of the user's turn."""
        q = "Is the Izakaya Nonesuch booking still on?"
        self.assertIn("dispatch loop", self.ctx(q, gate=False))
        ctx = self.prov.prefetch(q)
        self.assertIn("Izakaya Nonesuch", ctx)
        self.assertNotIn("dispatch loop", ctx)

    def test_the_debug_field_says_what_was_left_out(self):
        self.prov.prefetch("Is the Izakaya Nonesuch booking still on?")
        g = self.core.retrieval.last_context_debug["relevance_gate"]
        self.assertIn("izakaya", g["words"])
        self.assertGreater(g["excerpts"] + g["beliefs"] + g["tail"], 0)

    def test_explicit_retrieval_is_unchanged(self):
        q = "Is the Izakaya Nonesuch booking still on?"
        default = self.core.retrieval.get_context(q, token_budget=1200, principal="default",
                                                  exclude_automation=True)
        self.assertEqual(default, self.ctx(q, gate=False))
        self.assertNotIn("relevance_gate", self.core.retrieval.last_context_debug)

    def test_the_switch_turns_it_off(self):
        q = "Is the Izakaya Nonesuch booking still on?"
        from unittest import mock
        real = self.core.cfg.get

        def off(path, default=None):
            return False if path == "retrieval.prefetch_relevance_gate" else real(path, default)

        with mock.patch.object(self.core.cfg, "get", side_effect=off):
            self.assertEqual(self.prov.prefetch(q), self.ctx(q, gate=False))


if __name__ == "__main__":
    unittest.main()
