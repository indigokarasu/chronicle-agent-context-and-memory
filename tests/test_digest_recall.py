"""
Chronicle — one distilled unit instead of the turns it stands for.

Phase C's second half. A compaction can leave one line per folded unit behind
as an episode (`context_engine.digest_episodes`, tested next door). This is
what recall then does with it: when such an episode ranks into the block, the
raw fill below it skips that SAME session's individual turns, because those
turns are what the episode was distilled from.

Off by default (`retrieval.prefer_digest_episodes`) and inert without the
generation flag: a store with no `compaction_digest` episode has nothing to
prefer. Three things it is careful about:

* a digest that was RANKED but did not survive the Tier-1 budget prefers
  nothing -- otherwise the reader loses the episode and the turns both.
* per-turn recall never sees these episodes at all (`_NOT_UNASKED`), so what
  it injects is the same with the flag on or off.
* only the session the episode names. Another conversation's turns are
  ordinary evidence and are untouched.

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
WORKED = "20260912_090000_aa11bb"       # the session a compaction distilled
OTHER = "20260913_090000_cc22dd"        # a different conversation, same topic
LIVE = "20260919_120000_ee33ff"
ASK = "what happened with the zorblax ledger reconciliation?"


def worked_block():
    """The header of the distilled session's RAW block -- what this phase
    replaces. The turns themselves are also extracted into one belief each, and
    those are ranked Tier-1 evidence like any other: this phase decides how the
    raw fill spends the budget, not which beliefs rank."""
    return "[SESSION %s" % WORKED


DIGEST = ("called terminal(docker ps --filter name=zorblax) → zorblax Up 3 days (healthy) on "
          "port 8688, then reconciled the Riverton ledger for Acme Fake Co")


class TestPreferringIt(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="digestrecall_")
        self.prov = ChronicleMemoryProvider()
        self.prov.initialize(LIVE, hermes_home=self.home, principal_id="default", config=CFG)
        core = self.core = self.prov.core
        for i in range(6):
            core.capture.observe(
                "the zorblax ledger reconciliation step %d for Riverton needs a docker restart" % i,
                "ok", session_id=WORKED)
        core.capture.observe("the zorblax ledger in the other conversation was for Pat Testley",
                             "noted", session_id=OTHER)
        core.capture.append("asserted", {
            "kind": "episode", "key": {"title": DIGEST[:60], "session_ref": WORKED},
            "body": DIGEST, "confidence": 0.9, "source_event": "fold_ab12cd34ef56",
            "source_type": "compaction_digest"}, actor="agent", owner="default", trust_level=3)
        core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.core.store.db_path, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def ctx(self, on, budget=1200, keep=None):
        self.core.cfg._d["retrieval"]["prefer_digest_episodes"] = bool(on)
        if keep is not None:
            self.core.cfg._d["retrieval"]["digest_session_excerpts"] = keep
        return self.core.retrieval.get_context(ASK, token_budget=budget, principal="default")

    def turns(self, out):
        """Raw transcript turns of the distilled session on the page. Its
        individual turns were ALSO extracted into one belief each, and those
        rank Tier-1 like any other belief -- this phase decides how the raw
        fill spends the budget, not which beliefs rank."""
        return sum(1 for line in out.splitlines()
                   if line.startswith("User:") and "reconciliation step" in line)

    def test_the_fixture_puts_both_in_reach(self):
        out = self.ctx(False)
        self.assertIn("called terminal", out)
        self.assertIn(worked_block(), out)

    def test_on_the_episode_stands_in_for_the_rest_of_that_session_s_turns(self):
        """A few turns stay beside the distilled line. Measured
        (deploy570/digest_measure.py): keeping none saves 43% of the
        characters and costs 9 points of answer-word coverage -- the wrong
        trade, which is why the default keeps as many as it does."""
        off, on = self.ctx(False), self.ctx(True, keep=2)
        self.assertIn("called terminal", on)
        self.assertLess(self.turns(on), self.turns(off))
        self.assertGreater(self.turns(on), 0)

    def test_the_default_is_the_measured_one(self):
        """8: the most it saves at which answer-word coverage does not fall."""
        from engine.config import DEFAULTS
        self.assertEqual(DEFAULTS["retrieval"]["digest_session_excerpts"], 8)
        self.assertIs(DEFAULTS["retrieval"]["prefer_digest_episodes"], False)

    def test_the_cap_is_what_it_says(self):
        for keep in (0, 1, 2):
            with self.subTest(keep=keep):
                self.assertEqual(self.turns(self.ctx(True, keep=keep)), keep)

    def test_at_zero_it_costs_fewer_characters(self):
        self.assertLess(len(self.ctx(True, keep=0)), len(self.ctx(False)))

    def test_another_conversation_is_untouched(self):
        self.assertIn("other conversation", self.ctx(True))

    def test_a_digest_that_did_not_fit_prefers_nothing(self):
        """Ranked but cut by the Tier-1 budget: the reader must still get the
        turns, or preferring the episode costs them both."""
        out = self.ctx(True, budget=60, keep=0)
        self.assertNotIn("called terminal", out)
        self.assertIn(worked_block(), out)

    def test_it_says_how_many_it_skipped(self):
        self.ctx(True, keep=0)
        self.assertGreater((self.core.retrieval.last_context_debug or {}).get("digest_preferred", 0), 0)
        self.ctx(False)
        self.assertEqual((self.core.retrieval.last_context_debug or {}).get("digest_preferred", 0), 0)


class TestPerTurnRecallIsUnchanged(TestPreferringIt):
    """The same store, asked the way a turn asks: these episodes describe the
    agent's own work, so recall leaves them out unasked and there is nothing
    to prefer -- with the flag on or off."""

    def ctx(self, on, budget=1200, keep=None):
        self.core.cfg._d["retrieval"]["prefer_digest_episodes"] = bool(on)
        if keep is not None:
            self.core.cfg._d["retrieval"]["digest_session_excerpts"] = keep
        return self.prov.prefetch(ASK, session_id=LIVE)

    def test_the_fixture_puts_both_in_reach(self):
        self.assertIn(worked_block(), self.ctx(False))

    def test_on_the_episode_stands_in_for_the_rest_of_that_session_s_turns(self):
        out = self.ctx(True, keep=0)
        self.assertNotIn("called terminal", out)
        self.assertEqual(self.turns(out), self.turns(self.ctx(False)))

    def test_the_default_is_the_measured_one(self):
        from engine.config import DEFAULTS
        self.assertEqual(DEFAULTS["retrieval"]["digest_session_excerpts"], 8)
        self.assertIs(DEFAULTS["retrieval"]["prefer_digest_episodes"], False)

    def test_the_cap_is_what_it_says(self):
        for keep in (0, 1, 2):
            with self.subTest(keep=keep):
                self.assertEqual(self.turns(self.ctx(True, keep=keep)),
                                 self.turns(self.ctx(False)))

    def test_at_zero_it_costs_fewer_characters(self):
        self.assertEqual(len(self.ctx(True, keep=0)), len(self.ctx(False)))

    def test_a_digest_that_did_not_fit_prefers_nothing(self):
        self.assertIn(worked_block(), self.ctx(True))

    def test_it_says_how_many_it_skipped(self):
        self.ctx(True, keep=0)
        self.assertEqual((self.core.retrieval.last_context_debug or {}).get("digest_preferred", 0), 0)


if __name__ == "__main__":
    unittest.main()
