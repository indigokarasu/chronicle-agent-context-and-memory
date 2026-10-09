"""
Chronicle — Japanese extraction (i18n).

The heuristic floor is the default extractor (`extraction.backend: heuristic`),
deterministic and offline, and its job is high-precision capture of durable
first-person facts. Every pattern in `engine/extraction.py` is ASCII-first:
sentence boundaries need `.?!` + whitespace + capital, facts are keyed on
English predicates, and `entities.plausible_name` needs a capital. A Japanese
turn therefore extracts ZERO durable items, so `answer()` on a Japanese store
abstains on every question even though the raw tier (FTS + embeddings) does
retrieve.

This file pins the same contract the English floor already has, for Japanese:
durable first-person facts are captured, and questions / hypotheticals /
third-person / states are refused.

Fixture names are obviously fake. Expected values are high-precision forms only
(`私の名前は…です`), matching the English floor's fenced design.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.extraction import HeuristicExtractor, split_sentences  # noqa: E402


# (excerpt, [(entity_id, predicate, value-substring)])
FIXTURE = [
    ("User: こんにちは。私の名前は牧野亮です。\nAssistant: よろしくお願いします。",
     [("user", "name", "牧野亮")]),
    ("User: アレルギーはそばです。\nAssistant: 承知しました。",
     [("user", "allergy", "そば")]),
    ("User: そばアレルギーがあります。\nAssistant: メモしました。",
     [("user", "allergy", "そば")]),
    ("User: 猫の名前はミケです。\nAssistant: かわいいですね。",
     [("user", "pet", "ミケ")]),
    ("User: 私は東京に住んでいます。\nAssistant: いいところですね。",
     [("user", "lives_in", "東京")]),
    ("User: コーヒーが好きです。\nAssistant: なるほど。",
     [("user", "likes", "コーヒー")]),
    ("User: 椎茸が嫌いです。\nAssistant: そうですか。",
     [("user", "dislikes", "椎茸")]),
    ("User: 私の妻は花子です。\nAssistant: 素敵ですね。",
     [("user", "spouse", "花子")]),
    ("User: 会社で働いています。\nAssistant: お疲れさまです。",
     []),  # no location -> nothing durable, but must not crash
]

# Every one of these must yield ZERO durable items (no fact, no note).
NEGATIVES = [
    ("question", "User: 猫の名前は？\nAssistant: ミケですか？"),
    ("question", "User: 明日の天気は晴れですか？\nAssistant: 知りません。"),
    ("question to the agent", "User: あなたは何が好きですか？\nAssistant: 味覚はありません。"),
    ("hypothetical", "User: もし東京に住んだら家賃はいくら？\nAssistant: 高いですよ。"),
    ("state, not a name", "User: 今日はとても疲れています。\nAssistant: 休んでください。"),
    ("third person", "User: 友人は東京に住んでいます。\nAssistant: そうなんですね。"),
]


def durable(result):
    return [it for it in result.items if it.get("kind") in ("fact", "note")]


def matches(item, entity, predicate, value):
    key = item.get("key") or {}
    body = (item.get("body") or "").lower()
    return (item.get("kind") == "fact"
            and key.get("entity_id") == entity
            and key.get("predicate_canonical") == predicate
            and value.lower() in body)


class TestJapaneseSentenceSplit(unittest.TestCase):
    """A Japanese sentence ends at 。！？ with no trailing space or capital."""

    def test_splits_on_japanese_full_stop(self):
        self.assertEqual(split_sentences("私の名前は牧野亮です。猫の名前はミケです。"),
                         ["私の名前は牧野亮です。", "猫の名前はミケです。"])

    def test_splits_on_question_and_exclamation(self):
        self.assertEqual(split_sentences("元気ですか？元気です！そうですか。"),
                         ["元気ですか？", "元気です！", "そうですか。"])

    def test_does_not_split_decimal_or_latin_period(self):
        # The ASCII rule must be unchanged: a latin sentence still needs
        # whitespace + a capital, and "3.14" is never cut.
        self.assertEqual(split_sentences("It is 3.14 today. So there."),
                         ["It is 3.14 today.", "So there."])


class TestJapaneseExtraction(unittest.TestCase):
    def setUp(self):
        self.ex = HeuristicExtractor()

    def _items(self, excerpt):
        return durable(self.ex.extract(excerpt, source_event="ev", owner="u",
                                       domain="user", session_id="s"))

    def test_recall_and_precision(self):
        hit = expected_n = emitted_n = correct_n = 0
        misses, fps = [], []
        for excerpt, expected in FIXTURE:
            items = self._items(excerpt)
            emitted_n += len(items)
            for ent, pred, val in expected:
                expected_n += 1
                if any(matches(it, ent, pred, val) for it in items):
                    hit += 1
                else:
                    misses.append((ent, pred, val, [it.get("body") for it in items]))
            for it in items:
                if any(matches(it, e, p, v) for e, p, v in expected):
                    correct_n += 1
                else:
                    key = it.get("key") or {}
                    fps.append((key.get("entity_id"), key.get("predicate_canonical"),
                                it.get("body")))
        self.assertGreaterEqual(hit / float(expected_n or 1), 0.99,
                                "misses: %r" % (misses,))
        self.assertGreaterEqual(correct_n / float(emitted_n or 1), 0.99,
                                "false positives: %r" % (fps,))

    def test_negatives_are_refused(self):
        for label, excerpt in NEGATIVES:
            with self.subTest(label=label):
                self.assertEqual(self._items(excerpt), [],
                                 "leaked: %r" % (label,))

    def test_english_is_unchanged(self):
        # A smoke check that the Japanese work did not touch the English floor.
        items = self._items("User: My name is Pat Testley and I work at Acme Fake Co.\n"
                            "Assistant: Nice to meet you Pat.")
        self.assertTrue(any(matches(it, "user", "name", "Pat Testley") for it in items))
        self.assertTrue(any(matches(it, "user", "works_at", "Acme Fake Co") for it in items))


class TestJapaneseSupportGate(unittest.TestCase):
    """The focus support gate must recognise a Japanese question as supported by
    the sentence that answers it. `word_tokens` keeps a CJK run glued, so the
    query "私の名前は？" and the span "私の名前は牧野亮です" share no WHOLE token —
    the gate compares character bigrams instead. This mirrors
    test_unicode_keyword_terms.TestNonLatinQuestionsCanAbstain for Japanese."""

    def setUp(self):
        import shutil
        sys.path.insert(0, str(Path(__file__).parent))
        from _tmp_support import temp_home
        from engine.core import ChronicleCore
        self.shutil = shutil
        self.home = temp_home()
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"},
                                              "retrieval": {"abstain_gate": "focus"}})
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        self.shutil.rmtree(self.home, ignore_errors=True)

    def _gate(self, question, excerpt):
        r = self.core.retrieval
        return r._support_gate([{"excerpt": excerpt, "score": 1.0}],
                               r.query_understanding(question))

    def test_a_japanese_question_is_supported_by_its_answer(self):
        for q, span in [("私の名前は？", "User: 私の名前は牧野亮です。"),
                        ("アレルギーは何？", "User: アレルギーはそばです。"),
                        ("猫の名前は？", "User: 猫の名前はミケです。"),
                        ("どこに住んでいますか？", "User: 私は東京に住んでいます。"),
                        ("コーヒーは好きですか？", "User: コーヒーが好きです。")]:
            with self.subTest(q=q):
                self.assertTrue(self._gate(q, span))

    def test_unrelated_japanese_support_is_not_support(self):
        self.assertFalse(self._gate("明日の東京の天気は？", "User: 私は東京に住んでいます。"))
        self.assertFalse(self._gate("彼の電話番号は？", "User: 私は東京に住んでいます。"))

    def test_english_gate_is_unchanged(self):
        # Latin tokens are pass-through: the gate result for an English pair is
        # exactly what the whole-token path produced before.
        self.assertTrue(self._gate("Where does Pat Testley work?",
                                   "Pat Testley works at Acme Fake Co"))
        self.assertFalse(self._gate("Where does Pat Testley work?",
                                    "Robin Placeholder likes kayaking on weekends"))


if __name__ == "__main__":
    unittest.main()
