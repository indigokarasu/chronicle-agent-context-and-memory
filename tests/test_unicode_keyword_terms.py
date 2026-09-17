"""
Chronicle — keyword paths tokenize words the way the FTS5 index does.

Every keyword path used an ASCII-only `[A-Za-z0-9]` token. FTS5's unicode61
tokenizer indexes Unicode letters, so the two disagreed on any non-English word:

  * the FTS query for "When did I move to Zürich?" searched for "rich", and
    "José" became "Jos": the keyword arm looked for words nobody wrote;
  * a Cyrillic or CJK question produced no query terms at all;
  * the focus support gate treats "no distinctive tokens" as "nothing to fail
    on", so a non-Latin question could never abstain and was answered from
    whatever unrelated memory ranked first.

Fixture names are obviously fake.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import remove_db, temp_home

from engine.core import ChronicleCore
from engine.retrieval import _content_tokens, hint_signature, query_tokens
from engine.store import MemoryStore, _fts_query


class TestFtsFindsNonAsciiWords(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)
        for eid, excerpt in (("ev_zurich", "Pat Testley moved to Zürich in March"),
                             ("ev_jose", "José Fictional recommended the Acme Fake Co café"),
                             ("ev_ru", "Анна Петрова живёт в Москве"),
                             ("ev_other", "Robin Placeholder likes kayaking")):
            self.store.fts_index_observed(eid, excerpt)

    def tearDown(self):
        self.store.close()
        remove_db(self.tmp.name)

    def _hits(self, query):
        return [r["event_id"] for r in self.store.fts_search_observed(query, limit=10)]

    def test_an_accented_name_is_searched_whole(self):
        self.assertIn('"Zürich"', _fts_query("When did I move to Zürich?"))
        self.assertNotIn('"rich"', _fts_query("When did I move to Zürich?"))
        self.assertEqual(self._hits("Zürich"), ["ev_zurich"])
        self.assertEqual(self._hits("José"), ["ev_jose"])

    def test_a_cyrillic_question_has_terms_and_finds_its_row(self):
        self.assertNotEqual(_fts_query("Где живёт Анна?"), "")
        self.assertEqual(self._hits("Где живёт Анна?"), ["ev_ru"])

    def test_a_single_cjk_character_is_a_word_not_noise(self):
        """Single ASCII letters are dropped as noise; one CJK character is a word."""
        self.store.fts_index_observed("ev_cat", "Pat Testley calls the cat 猫")
        self.assertEqual(_fts_query("猫"), '"猫"')
        self.assertEqual(self._hits("猫"), ["ev_cat"])

    def test_a_decomposed_spelling_is_one_word(self):
        """NFD "Zürich" (u + combining diaeresis) is one token to FTS5."""
        nfd = "Zu\u0308rich"
        self.assertEqual(_fts_query(nfd), '"Zürich"')
        self.assertEqual(self._hits(nfd), ["ev_zurich"])

    def test_unaccented_spelling_still_matches(self):
        """unicode61 removes diacritics at index and query time."""
        self.assertEqual(self._hits("Zurich"), ["ev_zurich"])


class TestTokenHelpersKeepNonAsciiWords(unittest.TestCase):
    def test_query_tokens(self):
        self.assertEqual(query_tokens("What did José recommend?"), ["josé", "recommend"])
        self.assertIn("анна", query_tokens("Где живёт Анна?"))

    def test_content_tokens(self):
        self.assertIn("álvarez", _content_tokens("José Álvarez lives in Sao Paulo"))

    def test_a_non_latin_query_files_a_hint_under_its_own_words(self):
        key, toks = hint_signature("Где живёт Анна Петрова?")
        self.assertTrue(key)
        self.assertIn("петрова", toks)

    def test_typographic_apostrophe_is_the_same_word(self):
        self.assertEqual(query_tokens("Pat doesn’t like kayaking"),
                         query_tokens("Pat doesn't like kayaking"))


class TestNonLatinQuestionsCanAbstain(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"},
                                              "retrieval": {"abstain_gate": "focus"}})
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _gate(self, question, excerpt):
        r = self.core.retrieval
        return r._support_gate([{"excerpt": excerpt, "score": 1.0}],
                               r.query_understanding(question))

    def test_unrelated_support_is_not_support(self):
        self.assertFalse(self._gate("Где живёт Анна Петрова?",
                                    "Robin Placeholder likes kayaking on weekends"))

    def test_matching_support_is_support(self):
        self.assertTrue(self._gate("Где живёт Анна Петрова?",
                                   "Анна Петрова живёт в Москве"))


if __name__ == "__main__":
    unittest.main()
