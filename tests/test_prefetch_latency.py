"""
Chronicle — the per-turn prefetch asks the store only for what it can use.

Profiled on the production store (5.7.12, one gated prefetch, 4.3 s): the raw
FTS channel was 2.3 s -- three calls, because it ORed every word of the message
("which", "did" and "I" included) over a transcript table that is ~98% cron
runs, then filtered the cron rows afterwards and had to widen and re-run the
ranked match to find enough left -- and the standing-directive lookup was
0.8 s: its index on always_inject alone walked 40,444 retracted directives
for five active ones. The gated path now asks FTS for the message's content
words (what the gate keeps anyway), drops automation rows inside the query,
and the directive lookup has an index on both columns it filters by.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.retrieval import relevance_fts_match

CFG = {"embeddings": {"model": "hashing"}}
CHAT = "20260917_161616_ff66aa"


class TestTheMatchIsTheContentWords(unittest.TestCase):
    def test_content_words_as_written_and_folded_as_prefixes(self):
        self.assertEqual(relevance_fts_match("which restaurants did I book in Hawaii?"),
                         '"book"* OR "hawaii"* OR "restaurant"* OR "restaurants"*')

    def test_small_talk_has_no_match(self):
        self.assertEqual(relevance_fts_match("ok thanks, sounds good"), "")


def _reference_shares(words, text):
    """shares_content_word as it was before the substring pre-check."""
    from engine.retrieval import _gate_stem, _gate_words
    if not words:
        return False
    long_words = [w for w in words if len(w) >= 4]
    for t in map(_gate_stem, _gate_words(text)):
        if t in words:
            return True
        if len(t) >= 4:
            for w in long_words:
                if abs(len(t) - len(w)) <= 3 and (t.startswith(w) or w.startswith(t)):
                    return True
    return False


class TestTheFastMatcherIsTheSameMatcher(unittest.TestCase):
    """The pre-check only skips work: over every pair below it answers exactly
    what the token loop alone answers."""

    VOCAB = ["fly", "flies", "city", "cities", "company", "companies", "dog", "dogs", "eat",
             "eaten", "art", "party", "artist", "book", "booked", "booking", "plan", "planned",
             "planet", "restaurant", "restaurants", "robin", "robin's", "zu\u0308rich",
             "z\u00fcrich", "bus", "gas", "pies", "cry", "cries", "tracker", "hawaii", "don't",
             "reilly", "o'reilly", "'reilly", "rock'n'roll", "roll", "robin\u2019s", "foo_bar",
             "bar", "BOOKED", "Hawaii's", "x2024", "2024", "don", "Don", "doesn't", "does", "don\u2019t"]

    def test_every_pair(self):
        from engine.retrieval import relevance_words, shares_content_word
        for q in self.VOCAB:
            words = relevance_words(q)
            for t in self.VOCAB + ["the %s list" % v for v in self.VOCAB]:
                with self.subTest(q=q, t=t):
                    self.assertEqual(shares_content_word(words, t), _reference_shares(words, t))

    def test_the_cases_the_probe_had_to_allow_for(self):
        from engine.retrieval import relevance_words, shares_content_word
        self.assertTrue(shares_content_word(relevance_words("fly"), "the flies"))
        self.assertTrue(shares_content_word(relevance_words("city"), "two cities"))
        self.assertTrue(shares_content_word(relevance_words("z\u00fcrich"), "in zu\u0308rich"))


class _Store(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="latency_")
        self.core = core = ChronicleCore.get(self.home, CFG)
        core.initialize(CHAT, principal_id="default")
        core.capture.observe("We booked two restaurants in Riverton for the Zorblax trip.",
                             "Noted.", session_id=CHAT)
        for i in range(30):
            sid = "cron_abc%03d_20260917_000000" % i
            core.initialize(sid, principal_id="default")
            core.capture.observe("Zorblax restaurant dispatch run %d: re-assert verifier." % i,
                                 "ok", session_id=sid)
        core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)


class TestTheStore(_Store):
    def test_automation_rows_are_dropped_inside_the_query(self):
        rows = self.core.store.fts_search_observed("", limit=5, match='"zorblax"*',
                                                   exclude_session_prefixes=("cron_",))
        self.assertEqual(len(rows), 1)
        self.assertIn("booked two restaurants", rows[0]["excerpt"])

    def test_without_prefixes_it_is_the_ordinary_query(self):
        rows = self.core.store.fts_search_observed("Zorblax restaurant", limit=50)
        self.assertEqual(len(rows), 31)

    def test_the_directive_lookup_uses_its_index(self):
        plan = " ".join(str(tuple(r)) for r in self.core.store._conn().execute(
            "EXPLAIN QUERY PLAN SELECT * FROM notes WHERE always_inject=1 AND status='active'"))
        self.assertIn("idx_notes_directive_active", plan)


class TestTheGatedPath(_Store):
    def _spy(self):
        return mock.patch.object(self.core.store, "fts_search_observed",
                                 wraps=self.core.store.fts_search_observed)

    def test_it_asks_fts_for_the_content_words_once(self):
        r = self.core.retrieval
        with self._spy() as spy:
            ctx = r.get_context("which restaurants did we book for the Zorblax trip?",
                                token_budget=1200, principal="default",
                                exclude_automation=True, relevance_gate=True)
        self.assertIn("booked two restaurants", ctx)
        self.assertNotIn("dispatch run", ctx)
        self.assertEqual(spy.call_count, 1, "no widening: the cron rows never ranked")
        kw = spy.call_args.kwargs
        self.assertIn('"restaurant"*', kw["match"])
        self.assertNotIn('"which"', kw["match"])
        self.assertEqual(kw["exclude_session_prefixes"], ("cron_",))

    def test_the_belief_channel_asks_for_the_content_words_too(self):
        r = self.core.retrieval
        with mock.patch.object(self.core.store, "fts_search_beliefs",
                               wraps=self.core.store.fts_search_beliefs) as spy:
            r.get_context("which restaurants did we book for the Zorblax trip?",
                          token_budget=1200, principal="default",
                          exclude_automation=True, relevance_gate=True)
        self.assertIn('"zorblax"*', spy.call_args.kwargs["match"])

    def test_the_turn_makes_no_embedding_call(self):
        """The per-turn path is lexical: no query embed, no route classification
        (which embeds the message too). Measured live, the vector channels
        changed no line of a gated block and cost 1-5 s a turn."""
        r = self.core.retrieval
        # Counted, not raised: query_understanding swallows an embedder error
        # (the vector channel just drops out), so a raising stub proves nothing.
        emb = mock.Mock(return_value=[0.0] * 8)
        route = mock.Mock(side_effect=AssertionError("routed inside the turn"))
        with mock.patch.object(r.embedder, "embed_query", emb), \
                mock.patch.object(r.embedder, "embed", emb), \
                mock.patch.object(r, "classify_route", route):
            ctx = r.get_context("which restaurants did we book for the Zorblax trip?",
                                token_budget=1200, principal="default",
                                exclude_automation=True, relevance_gate=True)
        self.assertIn("booked two restaurants", ctx)
        self.assertEqual(emb.call_count, 0, "embedded inside the turn")

    def test_explicit_retrieval_still_embeds(self):
        r = self.core.retrieval
        with mock.patch.object(self.core.embedder, "embed_query",
                               wraps=self.core.embedder.embed_query) as spy:
            r.get_context("which restaurants did we book?", token_budget=1200,
                          principal="default")
        self.assertGreater(spy.call_count, 0)

    def test_the_structured_scan_is_the_content_words(self):
        r = self.core.retrieval
        with mock.patch.object(self.core.store, "query_beliefs",
                               wraps=self.core.store.query_beliefs) as spy:
            r.get_context("which restaurants did we book for the Zorblax trip?",
                          token_budget=1200, principal="default",
                          exclude_automation=True, relevance_gate=True)
        likes = [a for c in spy.call_args_list for a in (c.args[2] if len(c.args) > 2 else ())
                 if isinstance(a, str) and a.startswith("%")]
        self.assertTrue(likes, "the structured channel ran no scan at all")
        self.assertNotIn("%which%", likes)

    def test_explicit_retrieval_asks_the_ordinary_query(self):
        r = self.core.retrieval
        with self._spy() as spy:
            r.get_context("which restaurants did we book?", token_budget=1200,
                          principal="default")
        kw = spy.call_args.kwargs
        self.assertEqual(set(kw), {"limit"}, "the store is called exactly as before")


if __name__ == "__main__":
    unittest.main()
