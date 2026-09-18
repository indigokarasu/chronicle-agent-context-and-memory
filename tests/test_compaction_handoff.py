"""
Chronicle — the compaction handoff (5.8.0).

A compaction folds turns out of the window and leaves ONE message where they
were: "[CONTEXT COMPACTION — REFERENCE ONLY] Chronicle folded …", in a
conversation role, listing the user's folded requests verbatim, what the
folded steps did, the facts stated in them and memory recalled for the focus.
These tests pin the properties the replay of real sessions depends on:

  * the newest turn always survives, even when the protected spans alone are
    over budget (the old fit ran oldest-first and dropped the newest);
  * a protected span shortened for budget says so and stays recoverable;
  * a tool call and its results are kept or folded together -- never split;
  * identical folded turns are listed once, and a run of long requests cannot
    crowd the stated facts out of the handoff;
  * a restarted engine (no state, handoff already in the transcript) keeps
    what the earlier handoff said, and pre-5.8 artifacts are cleared.

Fixtures use obviously fake values.
"""

import json
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine
from engine.core import ChronicleCore
from engine.embeddings import estimate_tokens

CFG = {"embeddings": {"model": "hashing"}}
PREFIX = "[CONTEXT COMPACTION — REFERENCE ONLY]"


def _msg(role, text):
    return {"role": role, "content": text}


def _handoffs(out):
    return [m for m in out if (m.get("content") or "").startswith(PREFIX)]


def _orphans(msgs):
    calls = {c["id"] for m in msgs if m.get("role") == "assistant"
             for c in (m.get("tool_calls") or [])}
    answers = {m.get("tool_call_id") for m in msgs if m.get("role") == "tool"}
    return calls - answers, answers - calls


def _cost(eng, out):
    return sum(eng._msg_cost(m) for m in out)


class _Engine(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="handoff_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("s-handoff", hermes_home=self.home, principal_id="pat", config=CFG)
        self.assertIsNotNone(self.eng.core)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)


class TestTheNewestTurnWins(_Engine):
    def _over_budget(self):
        self.eng.update_model("fake-model", 1500)
        return [_msg("system", "sys")] + [
            _msg("user" if i % 2 == 0 else "assistant",
                 "turn %d about the Zorblax rota " % i + "w" * 600) for i in range(16)]

    def test_protected_spans_over_budget_keep_the_newest(self):
        msgs = self._over_budget()
        out = self.eng.compress(list(msgs))
        self.assertEqual(out[-1], msgs[-1], "the newest turn was dropped or shortened")
        self.assertIn(msgs[-2], out)
        self.assertLessEqual(_cost(self.eng, out), self.eng._target_budget())

    def test_when_the_head_is_folded_the_handoff_leads(self):
        out = self.eng.compress(list(self._over_budget()))
        self.assertEqual(out[0]["role"], "system")
        self.assertTrue(out[1]["content"].startswith(PREFIX), [m["content"][:30] for m in out])
        self.assertEqual(out[1]["role"], "user", "the first conversation message must be the user's")
        self.assertIn("turn 10 about the Zorblax rota", out[1]["content"], "the newest folded request")
        asks = out[1]["content"].split("Your earlier requests, newest first:")[1].split("\n\n")[0]
        order = [int(n) for n in re.findall(r"turn (\d+) about", asks)]
        self.assertEqual(order, sorted(order, reverse=True), "requests are listed newest first")

    def test_folds_are_recorded_in_conversation_order(self):
        """Middle units fold first and the dropped head/tail after them; noted
        in that order, "newest first" put the head's requests above the
        middle's."""
        self.eng.compress(list(self._over_budget()))
        order = [int(re.search(r"turn (\d+) about", a).group(1)) for a in self.eng._handoff_asks]
        self.assertGreater(len(order), 3)
        self.assertEqual(order, sorted(order))

    def test_the_handoff_alternates_with_the_turn_before_it(self):
        self.eng.update_model("fake-model", 3000)
        msgs = [_msg("system", "sys"), _msg("user", "u0"), _msg("assistant", "a0"), _msg("user", "u1")]
        msgs += [_msg("assistant" if i % 2 == 0 else "user", "chatter %d " % i + "q" * 500)
                 for i in range(30)]
        out = self.eng.compress(msgs)
        i = next(n for n, m in enumerate(out) if m["content"].startswith(PREFIX))
        self.assertEqual(out[i - 1]["content"], "u1", "setup: the handoff follows the head")
        self.assertEqual(out[i]["role"], "assistant")

    def test_a_shortened_span_says_so_and_can_be_restored(self):
        msgs = self._over_budget()
        out = self.eng.compress(list(msgs))
        short = [m for m in out if "[shortened; chronicle_expand(" in (m.get("content") or "")]
        self.assertTrue(short, "setup: something must have been shortened")
        span_id = re.search(r'chronicle_expand\("(fold_[0-9a-f]{12})"\)', short[0]["content"]).group(1)
        full = json.loads(self.eng.handle_tool_call("chronicle_expand", {"span_id": span_id}))
        self.assertIn(full["content"], [m["content"] for m in msgs])
        self.assertTrue(full["content"].startswith(short[0]["content"][:40]))


class TestToolUnits(_Engine):
    def _session(self, n=14, result_chars=900):
        msgs = [_msg("system", "sys"), _msg("user", "Please audit the SunFake 9000 logs.")]
        for i in range(n):
            cid = "call_%02d" % i
            msgs.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": cid, "type": "function",
                                         "function": {"name": "read_file",
                                                      "arguments": json.dumps({"path": "/fake/log%d" % i})}}]})
            msgs.append({"role": "tool", "tool_call_id": cid, "name": "read_file",
                         "content": "log %d: " % i + "entry " * (result_chars // 6)})
        msgs.append(_msg("assistant", "The logs show three restarts."))
        msgs.append(_msg("user", "And what caused them?"))
        return msgs

    def test_no_call_loses_its_result(self):
        self.eng.update_model("fake-model", 4000)
        for n in (6, 10, 14, 20):
            with self.subTest(n=n):
                out = self.eng.compress(self._session(n))
                self.assertEqual(_orphans(out), (set(), set()))

    def test_folded_steps_say_what_was_called(self):
        self.eng.update_model("fake-model", 4000)
        out = self.eng.compress(self._session(20))
        h = _handoffs(out)
        self.assertEqual(len(h), 1)
        self.assertIn("read_file", h[0]["content"])
        self.assertIn(_msg("user", "Please audit the SunFake 9000 logs."), out, "the head stays")
        self.assertNotEqual(h[0]["role"], "system")

    def test_each_folded_step_is_named_by_its_own_result(self):
        """A call with no text of its own hashes like every other one, so it
        cannot name its step: every step pointed at the same useless id."""
        self.eng.update_model("fake-model", 4000)
        out = self.eng.compress(self._session(20))
        steps = [line for line in _handoffs(out)[0]["content"].splitlines() if "called read_file" in line]
        ids = [re.match(r"- \[(fold_[0-9a-f]{12})\]", line).group(1) for line in steps]
        self.assertGreater(len(ids), 3)
        self.assertEqual(len(set(ids)), len(ids))
        got = json.loads(self.eng.handle_tool_call("chronicle_expand", {"span_id": ids[0]}))
        self.assertTrue(got["content"].startswith("log "), got)

    def test_archiving_is_batched(self):
        """One transaction per archived message was most of a large pass's time."""
        self.eng.update_model("fake-model", 4000)
        store = self.eng.core.store
        real, outer = store.transaction, [0]

        def counting():
            if getattr(store._local, "depth", 0) == 0:
                outer[0] += 1
            return real()
        store.transaction = counting
        try:
            msgs = self._session(60)
            before = len(store.get_events_by_session("s-handoff"))
            self.eng.compress(msgs)
            written = len(store.get_events_by_session("s-handoff")) - before
        finally:
            store.transaction = real
        self.assertGreater(written, 100, "setup: a large pass")
        self.assertLess(outer[0], written // 10)

    def test_a_large_tool_result_in_the_head_is_shortened_and_restorable(self):
        self.eng.update_model("fake-model", 200000)   # roomy: only the cap shortens it
        big = "SKILL DESCRIPTION for util-fake: " + "flag " * 12000
        self.assertLess(self.eng._msg_cost({"content": big}), self.eng._target_budget() // 4)
        msgs = [_msg("system", "sys"), _msg("user", "Fetch the Acme Fake Co spec."),
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "h1", "type": "function", "function": {"name": "skill_view", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "h1", "content": big}]
        msgs += self._session(20)[2:]
        out = self.eng.compress(msgs)
        head_tool = next(m for m in out if m.get("tool_call_id") == "h1")
        self.assertLess(len(head_tool["content"]), len(big) // 2)
        sid = re.search(r'chronicle_expand\("(fold_[0-9a-f]{12})"\)', head_tool["content"]).group(1)
        self.assertEqual(json.loads(self.eng.handle_tool_call("chronicle_expand", {"span_id": sid}))["content"], big)
        self.assertEqual(_orphans(out), (set(), set()))

    def test_a_small_tool_result_in_the_head_is_untouched(self):
        self.eng.update_model("fake-model", 6000)
        msgs = [_msg("system", "sys"), _msg("user", "Fetch the Acme Fake Co spec."),
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "h1", "type": "function", "function": {"name": "skill_view", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "h1", "content": "short spec"}]
        msgs += self._session(20)[2:]
        out = self.eng.compress(msgs)
        self.assertIn(msgs[3], out)

    def test_tool_call_arguments_are_counted(self):
        m = {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c", "function": {"name": "write_file",
                                                     "arguments": "x" * 4000}}]}
        self.assertGreater(self.eng._msg_cost(m), estimate_tokens("x" * 3000))


class TestTheHandoffsContents(_Engine):
    def test_identical_turns_are_listed_once(self):
        room = 2000
        asks = ["[fold_aaaaaaaaaaaa] book the Izakaya Nonesuch"] * 30
        text = self.eng._render_handoff(room, asks, [], [], [], None)
        self.assertEqual(text.count("book the Izakaya Nonesuch"), 1)

    def test_long_requests_cannot_crowd_out_the_facts(self):
        asks = ["[fold_%012x] %s" % (i, "plan the Zorblax offsite " * 40) for i in range(40)]
        known = ["- Pat Testley works_at Acme Fake Co"]
        text = self.eng._render_handoff(600, asks, [], known, [], None)
        self.assertIn("Stated in the folded turns:", text)
        self.assertIn("works_at Acme Fake Co", text)
        self.assertLessEqual(self.eng._msg_cost({"content": text}), 600)

    def test_what_does_not_fit_is_still_named(self):
        asks = ["[fold_%012x] %s" % (i, "remind Robin Placeholder " * 30) for i in range(30)]
        text = self.eng._render_handoff(500, asks, [], [], [], None)
        self.assertIn("older, not shown:", text)

    def test_the_newest_request_before_any_id_list(self):
        asks = ["[fold_%012x] %s" % (i, "ask Sam Vimes about shift %d " % i) for i in range(12)]
        text = self.eng._render_handoff(130, asks, [], [], [], None)
        self.assertIn("shift 11", text)
        self.assertLessEqual(self.eng._msg_cost({"content": text}), 130)

    def test_ids_carried_from_an_earlier_handoff_stay_named(self):
        earlier = ChronicleContextEngine()
        text = self.eng._render_handoff(
            400, ["[fold_%012x] %s" % (i, "ask about the Acme Fake Co audit " * 6) for i in range(20)],
            [], [], [], None)
        self.assertIn("older, not shown:", text)
        earlier._adopt_handoff(text)
        again = earlier._render_handoff(2000, earlier._handoff_asks, [], [], [], None)
        self.assertEqual(set(re.findall(r"fold_[0-9a-f]{12}", text)),
                         set(re.findall(r"fold_[0-9a-f]{12}", again)))

    def test_the_header_alone_or_nothing(self):
        self.assertEqual(self.eng._render_handoff(5, ["[fold_aaaaaaaaaaaa] x"], [], [], [], None), "")


class TestTheHostsMemoryContext(_Engine):
    """Hermes collects its memory providers' on_pre_compress() text and passes
    it to the engine as `memory_context` -- "provider text for the handoff".
    Chronicle dropped it."""

    def _msgs(self):
        self.eng.update_model("fake-model", 3000)
        return [_msg("system", "sys")] + [_msg("user" if i % 2 == 0 else "assistant",
                                               "chatter %d " % i + "q" * 500) for i in range(30)]

    def test_it_rides_in_the_handoff(self):
        out = self.eng.compress(self._msgs(), memory_context="Pat Testley prefers Izakaya Nonesuch.")
        self.assertIn("Pat Testley prefers Izakaya Nonesuch.", _handoffs(out)[0]["content"])

    def test_nothing_when_empty(self):
        out = self.eng.compress(self._msgs(), memory_context="   ")
        self.assertNotIn("Recalled from memory:", _handoffs(out)[0]["content"])


class TestAfterARestart(_Engine):
    def test_a_fresh_engine_keeps_what_the_earlier_handoff_said(self):
        self.eng.update_model("fake-model", 3000)
        first = [_msg("system", "sys"), _msg("user", "Remember the Zorblax budget is 40 fake credits.")]
        first += [_msg("user" if i % 2 == 0 else "assistant", "chatter %d " % i + "q" * 500)
                  for i in range(30)]
        out = self.eng.compress(first)
        self.assertEqual(len(_handoffs(out)), 1)

        fresh = ChronicleContextEngine()           # the gateway restarted
        fresh.on_session_start("s-handoff-2", hermes_home=self.home, principal_id="pat", config=CFG)
        fresh.update_model("fake-model", 3000)
        grown = out + [_msg("user" if i % 2 == 0 else "assistant", "later %d " % i + "r" * 500)
                       for i in range(30)]
        fresh.update_model("fake-model", 9000)     # room to show the older folds too
        again = fresh.compress(grown)
        hs = _handoffs(again)
        self.assertEqual(len(hs), 1, "one consolidated handoff, not a stack of them")
        before = set(re.findall(r"fold_[0-9a-f]{12}", _handoffs(out)[0]["content"]))
        carried = set(re.findall(r"fold_[0-9a-f]{12}", " ".join(fresh._handoff_asks + fresh._handoff_steps)))
        self.assertTrue(before)
        self.assertLessEqual(before, carried, "the restart lost folds the earlier handoff named")
        after = set(re.findall(r"fold_[0-9a-f]{12}", hs[0]["content"]))
        self.assertLessEqual(before, after, "the new handoff dropped folds the earlier one named")
        self.assertIn(_msg("user", "Remember the Zorblax budget is 40 fake credits."), again,
                      "the protected head survives the rebase")

    def test_pre_58_artifacts_are_cleared(self):
        self.eng.update_model("fake-model", 3000)
        msgs = [_msg("system", "sys"),
                _msg("system", "[Checkpoint: Pat Testley works_at Acme Fake Co]"),
                _msg("user", "[FOLD fold_0123456789ab 1a2b3c4d]"),
                _msg("system", "[Context pressure warning] Your context window is at 80%")]
        msgs += [_msg("user" if i % 2 == 0 else "assistant", "chatter %d " % i + "q" * 500)
                 for i in range(30)]
        out = self.eng.compress(msgs)
        joined = "\n".join(m.get("content") or "" for m in out)
        for legacy in ("[Checkpoint:", "[FOLD fold_", "[Context pressure warning]"):
            self.assertNotIn(legacy, joined)


if __name__ == "__main__":
    unittest.main()
