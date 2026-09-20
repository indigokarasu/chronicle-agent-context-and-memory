"""
Chronicle — recall and compaction score importance with ONE model.

`engine/salience.py` is the extraction of what both sides already did: the
per-turn recall gate (which content words a message has, how many an item must
share, whether an inflection counts) and the context engine's keep/evict score
(recency, focus match, salience and criticality keywords). They were separate
code with no way to disagree loudly, so a rule fixed on one side -- a URL's
pieces are not content words, a short number is not either -- had to be
remembered on the other.

This pins both entry points against the values the pre-extraction code
produced, and pins the wiring: the gate names retrieval exports and the score
the context engine computes must BE the ones in salience, not copies. (The
extraction itself was accepted by replaying 34 real messages out of a copy of
the production store: recall blocks byte-identical, 204 keep scores
identical.)

Fixtures use obviously fake values.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import context as context_mod
from engine import retrieval as R
from engine import salience as S

WEIGHTS = {"relevance": 0.35, "recency": 0.20, "salience": 0.20, "criticality": 0.20}
FOCUS = {"topics": ["zorblax"], "entities": ["Pat Testley"], "task": "fix the gateway"}


class TestOneModelNotTwoCopies(unittest.TestCase):
    def test_the_gate_retrieval_uses_is_the_one_in_salience(self):
        for name in ("relevance_words", "shared_content_words", "shares_content_word",
                     "gate_needs", "gate_focus", "relevance_fts_match"):
            with self.subTest(name=name):
                self.assertIs(getattr(R, name), getattr(S, name))

    def test_the_score_the_context_engine_uses_is_the_one_in_salience(self):
        self.assertIs(context_mod._SALIENCE_RX, S._SALIENCE_RX)
        self.assertIs(context_mod._CRITICALITY_RX, S._CRITICALITY_RX)
        src = (Path(__file__).parent.parent / "context.py").read_text(encoding="utf-8")
        self.assertIn("_salience.keep_score(", src, "the engine must call salience, not re-implement it")


class TestTheKeepScore(unittest.TestCase):
    """Values from the pre-extraction implementation, kept to the digit."""

    def score(self, text, focus=FOCUS, recency=1.0):
        return round(S.keep_score(text, focus, recency, WEIGHTS), 6)

    def test_recency_alone(self):
        self.assertEqual(self.score("a quiet turn about nothing", recency=0.0), 0.0)
        self.assertEqual(self.score("a quiet turn about nothing", recency=0.5), 0.1)
        self.assertEqual(self.score("a quiet turn about nothing", recency=1.0), 0.2)

    def test_any_facet_earns_the_bump_once(self):
        self.assertEqual(self.score("the zorblax ledger"), 0.55)          # topic
        self.assertEqual(self.score("ask Pat Testley about it"), 0.55)    # entity
        self.assertEqual(self.score("time to fix the gateway"), 0.55)     # task
        self.assertEqual(self.score("zorblax and Pat Testley and fix the gateway"), 0.55)

    def test_salience_and_criticality_stack_and_clamp(self):
        self.assertEqual(self.score("remember this"), 0.4)                 # salience only
        self.assertEqual(self.score("this is urgent"), 0.4)                # criticality only
        self.assertEqual(self.score("important: remember it"), 0.6)        # both words are salient
        self.assertEqual(self.score("critical zorblax fix, must remember"), 0.95)
        self.assertEqual(self.score("critical must urgent important zorblax Pat Testley"), 0.95)

    def test_an_empty_focus_scores_recency_only(self):
        empty = {"topics": [], "entities": [], "task": None}
        self.assertEqual(round(S.keep_score("the zorblax ledger", empty, 1.0, WEIGHTS), 6), 0.2)

    def test_the_engine_and_the_module_agree(self):
        eng = context_mod.ChronicleContextEngine()
        for text in ("the zorblax ledger", "critical must fix", "a quiet turn"):
            for recency in (0.0, 0.5, 1.0):
                with self.subTest(text=text, recency=recency):
                    self.assertEqual(eng._keep_score({"role": "user", "content": text}, FOCUS, recency),
                                     S.keep_score(text, FOCUS, recency, {}))


class TestTheGateWords(unittest.TestCase):
    def test_what_counts_as_a_content_word(self):
        self.assertEqual(sorted(S.relevance_words("Is the Zorblax standup still on Thursdays?")),
                         ["standup", "thursday", "zorblax"])
        self.assertEqual(S.relevance_words("ok thanks, sounds good"), frozenset())
        self.assertNotIn("com", S.relevance_words("see https://www.fake-site.invalid/2026/report"))
        self.assertNotIn("2026", S.relevance_words("order 2026 of the Zorblax ledger"))

    def test_how_many_words_an_item_must_share(self):
        self.assertEqual(S.gate_needs(S.relevance_words("which izakaya in Riverton?")), 1)
        self.assertEqual(S.gate_needs(S.relevance_words(
            "which izakaya did we book in Riverton for the Zorblax dinner on Friday")), 2)

    def test_an_inflection_counts_and_a_prefix_does_not(self):
        words = S.relevance_words("the Zorblax standup")
        self.assertEqual(sorted(S.shared_content_words(words, "the zorblax standups moved")),
                         ["standup", "zorblax"])
        self.assertEqual(S.shared_content_words(S.relevance_words("repo"), "the report is late"), set())

    def test_is_relevant_asks_the_gates_own_question(self):
        words = S.relevance_words("is the Zorblax standup still on?")
        self.assertTrue(S.is_relevant(words, "the zorblax standup moved to Thursdays"))
        self.assertFalse(S.is_relevant(words, "the Acme Fake Co invoice is paid"))
        self.assertFalse(S.is_relevant(S.relevance_words("thanks!"), "anything at all"))


class TestRankingAnyUnit(unittest.TestCase):
    """The same score over turns, episodes or memories: what Phase B ranks."""

    def test_best_first_ties_keep_their_order(self):
        units = [S.Unit("a quiet turn", 0.1, ref="old"),
                 S.Unit("critical zorblax fix", 1.0, ref="hot"),
                 S.Unit("another quiet turn", 0.1, ref="old2")]
        ranked = S.rank(units, FOCUS, WEIGHTS)
        self.assertEqual([u.ref for _s, u in ranked], ["hot", "old", "old2"])
        self.assertEqual(round(ranked[0][0], 2), 0.95)


if __name__ == "__main__":
    unittest.main()
