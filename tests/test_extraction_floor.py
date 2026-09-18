"""
Chronicle — the no-LLM heuristic extraction FLOOR (§16, audit A6).

`HeuristicExtractor` is the default extractor; `LLMExtractor` is opt-in and is
not enabled in any eval or in CI. So this file is what "Chronicle captured it"
means when no model is available, and its job is high-precision capture of
durable first-person facts plus correct classification of directives vs. mere
preferences vs. chatter. A better host model sharpens the floor later; it never
replaces it (I18).

WHAT THIS FILE IS
-----------------
The audit's measurement harness (`reports/_work/floor_measure.py`, 20 realistic
fake turns carrying 24 expected facts), committed in-tree so the floor has a
regression bar instead of a one-off number, and extended with the two things the
one-off did not report: PRECISION on the same fixture, and a negative corpus.

MEASURED, pre-A6 tree (c7ca775) vs. post-A6, same fixture, same matcher
(`.a6work/floor_ab.py` and `.a6work/corpus_ab.py`, /usr/bin/python3):

    metric                                    before      after
    ------------------------------------------------------------
    recall   (of 24 expected facts)           5  (20.8%)  24 (100%)
    precision(of durable items emitted)       5/8 (62.5%) 24/24 (100%)
    durable items on the 27 negatives         13          0
    norm notes / 9 800 real LME user turns    690         119
    preference-class facts, same 9 800 turns  0           72
    habit facts, same 9 800 turns             0           30
    total facts, same 9 800 turns             311         397

100% on the fixture is not a claim that the floor is solved: the audit named
these 24 facts and A6 wrote patterns for them, so the fixture is fitted and only
its FLOOR value (the audit's >= 70% bar) is meaningful as a bar. The numbers that
are not fitted are the negative corpus and the two LME corpus counts, and those
are the ones to watch.

The 119 norms that survive are mostly real standing instructions ("I want you to
act as ...", "Do not reply that ..."). Two residual classes are corpus artefacts
rather than pattern defects, and are recorded rather than tuned away: LongMemEval
stores some assistant-voiced turns under `role: "user"` ("Remember to taste as
you go"), which no text-only rule can re-attribute, and one 31 kB pasted video
transcript is hard-wrapped into timestamped fragments, so a clause like "don't
like stuck at a revenue level they" starts a line (28 of the 119 end without
terminal punctuation, which is the signature of that class). Chronicle's own
capture path writes "User: ...\nAssistant: ...", so `_role_lines` recovers the
speaker there; this corpus count feeds raw turn text with no prefix.

THE FOUR DEFECTS THIS PINS
--------------------------
1. `re.split(r"[\\n.!?]+", ...)` cut inside every email, URL, decimal and
   abbreviation, so `_EMAIL` could never match and the advertised `email`
   predicate was unreachable.
2. The directive regex fired on the trigger word ANYWHERE in a line, so "I don't
   like cilantro" became a `norm` note -> `always_inject=1` (reducer.py:923) ->
   `[DIRECTIVE]` in every context. That is the mechanism behind the L8 "~110
   active norm notes" flood and the reason `context.max_directives` had to be
   capped at 5. A preference is now a retrievable PREFERENCE-class fact
   (`prefers` / `likes` / `dislikes`); a norm requires imperative shape.
3. `_first_person_fact` returned after the FIRST match, so "My name is Pat
   Testley and I work at Acme Fake Co." yielded only the name.
4. "I'm Vegetarian" -> `name = Vegetarian`, and "My wife Robin Placeholder is a
   pediatrician" -> entity `my_wife_robin_placeholder` with predicate `is_a`.

THE PRECISION TRAP THIS REFUSES TO REINTRODUCE
----------------------------------------------
F3 §5.4 asked for `\\bi (like|love|prefer)\\b` preference patterns. F3's own
measurement is why they are fenced here: unfenced, they fire overwhelmingly on
politeness toward the ASSISTANT'S suggestions ("I like that idea", "I love how
you explained that"), which is not a durable fact about the user. Every
preference pattern below is paired with a negative case naming what it refuses.
Fixtures are obviously fake (Pat Testley, Acme Fake Co, Sam Vimes).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.criticality import classify  # noqa: E402
from engine.extraction import (  # noqa: E402
    HeuristicExtractor,
    is_standing_instruction,
    split_sentences,
)

# The audit's bar (AUDIT-2026-09.md §A6 "Acceptance"), and the pre-A6 tree's
# measured precision, which this must not fall below.
RECALL_BAR = 0.70
PRECISION_BAR = 5.0 / 8.0

# (excerpt, [(entity_id, predicate, value-substring)]) — "norm" as the entity
# means "a note_type='norm' note whose body contains this substring".
FIXTURE = [
    ("User: Hi! My name is Pat Testley and I work at Acme Fake Co.\n"
     "Assistant: Nice to meet you Pat.",
     [("user", "name", "Pat Testley"), ("user", "works_at", "Acme Fake Co")]),
    ("User: I live in Springfield now, moved last month.\nAssistant: Congrats on the move!",
     [("user", "lives_in", "Springfield")]),
    ("User: My wife Robin Placeholder is a pediatrician.\nAssistant: Great.",
     [("user", "spouse", "Robin Placeholder"),
      ("robin_placeholder", "occupation", "pediatrician")]),
    ("User: I'm allergic to penicillin, please remember that.\nAssistant: Noted.",
     [("user", "allergy", "penicillin")]),
    ("User: My birthday is March 3rd.\nAssistant: Happy early birthday!",
     [("user", "birthday", "March 3")]),
    ("User: I prefer window seats when I fly.\nAssistant: I'll keep that in mind.",
     [("user", "prefers", "window seats")]),
    ("User: I don't like cilantro.\nAssistant: Ok.",
     [("user", "dislikes", "cilantro")]),
    ("User: Sam Vimes is my manager at Acme Fake Co.\nAssistant: Got it.",
     [("sam_vimes", "role", "manager"), ("user", "manager", "Sam Vimes")]),
    ("User: We adopted a dog named Biscuit last week.\nAssistant: Cute!",
     [("user", "pet", "Biscuit")]),
    ("User: I moved to Portland from Springfield.\nAssistant: Nice.",
     [("user", "lives_in", "Portland")]),
    ("User: My email is pat.testley@example.com\nAssistant: Saved.",
     [("user", "email", "pat.testley@example.com")]),
    ("User: Always reply in British English.\nAssistant: Will do.",
     [("norm", "directive", "British English")]),
    ("User: My son Ollie starts kindergarten in September.\nAssistant: Exciting!",
     [("user", "child", "Ollie")]),
    ("User: I use a 2019 MacBook Pro for work.\nAssistant: Ok.",
     [("user", "device", "MacBook Pro")]),
    ("User: I'm vegetarian.\nAssistant: Noted.",
     [("user", "diet", "vegetarian")]),
    ("User: My office is in downtown Portland.\nAssistant: Ok.",
     [("user", "works_in", "downtown Portland")]),
    ("User: I take metformin 500mg twice a day.\nAssistant: Ok.",
     [("user", "medication", "metformin")]),
    ("User: I started a new job at Beta Fake Inc last week, left Acme.\nAssistant: Congrats.",
     [("user", "works_at", "Beta Fake Inc")]),
    ("User: My sister Jo lives in Denver.\nAssistant: Ok.",
     [("user", "sibling", "Jo"), ("jo", "lives_in", "Denver")]),
    ("User: I'm training for a half marathon in October.\nAssistant: Go you!",
     [("user", "goal", "half marathon")]),
]

# Every one of these must yield ZERO durable items (no fact, no note). Each names
# the pattern it fences. The first four are the F3 §5.4 precision trap.
NEGATIVES = [
    ("assistant-suggestion politeness",
     "Assistant: I'd suggest the aisle seat.\nUser: I like that idea, let's go with it."),
    ("assistant-suggestion politeness",
     "User: That sounds great, I prefer your second suggestion.\nAssistant: Great."),
    ("assistant-suggestion politeness",
     "User: I love how you explained that.\nAssistant: Thanks."),
    ("assistant-suggestion politeness",
     "User: I really like your approach here.\nAssistant: Glad it helps."),
    ("hypothetical", "User: If I lived in Paris, would I need a visa?\nAssistant: Probably."),
    ("hypothetical", "User: Suppose I moved to Denver — what would rent cost?\nAssistant: A lot."),
    ("hypothetical", "User: I might move to Portland next year.\nAssistant: Ok."),
    ("question", "User: Do you like cilantro?\nAssistant: I have no taste buds."),
    ("question", "User: Where do you work?\nAssistant: Nowhere."),
    ("question", "User: Don't they have enough talent to do both?\nAssistant: Maybe."),
    ("third person about the assistant",
     "Assistant: I am a large language model. My name is Claude.\nUser: Ok."),
    ("third person about the assistant",
     "Assistant: I work at a lab and I live in the cloud.\nUser: Funny."),
    ("third person about someone else",
     "User: My friend says he works at Acme Fake Co.\nAssistant: Ok."),
    ("state, not a name", "User: I am so tired today.\nAssistant: Rest up."),
    ("adverbial always/never", "User: They always make me laugh.\nAssistant: Nice."),
    ("adverbial always/never",
     "User: Wow, I never knew there were so many types of cruise ships.\nAssistant: Indeed."),
    ("adverbial always/never", "User: It's always nice to get some extra cash.\nAssistant: Sure."),
    ("adverbial always/never", "User: I've always been fascinated by Tuscany.\nAssistant: Lovely."),
    ("adverbial always/never",
     "User: I never realized how important recycling is.\nAssistant: True."),
    ("mid-line don't",
     "User: However, I don't see your company's diversity statement.\nAssistant: Sorry."),
    ("mid-line don't",
     "User: I bought it on June 1st, but I don't know the original price.\nAssistant: Ok."),
    ("mid-line must", "User: It must also be as brief as possible.\nAssistant: Understood."),
    ("no dose, so not a medication", "User: I take the bus to work every morning.\nAssistant: Ok."),
    ("pointer, not a habit", "User: I never do that.\nAssistant: Ok."),
    ("pointer, not a habit", "User: I always like your suggestions.\nAssistant: Thanks."),
    ("past tense, one-off", "User: I liked that movie we discussed.\nAssistant: Ok."),
    ("wish, not a preference", "User: I'd like to try meditation someday.\nAssistant: Nice."),
]


def durable(result):
    """The retrievable/injectable items: facts and notes.

    `entity` and `episode` items are structural companions to a fact (an entity
    row, a turn summary), not assertions about the user, so they are asserted
    separately rather than scored here.
    """
    return [it for it in result.items if it.get("kind") in ("fact", "note")]


def matches(item, entity, predicate, value):
    key = item.get("key") or {}
    body = (item.get("body") or "").lower()
    if entity == "norm":
        return (item.get("kind") == "note" and key.get("note_type") == "norm"
                and value.lower() in body)
    return (item.get("kind") == "fact"
            and key.get("entity_id") == entity
            and key.get("predicate_canonical") == predicate
            and value.lower() in body)


def score(extractor):
    """(recall, precision, misses, false_positives) over FIXTURE, strictly.

    An emission is correct iff it satisfies at least one expected tuple for its
    own case. A true-but-unlisted extra therefore counts AGAINST precision — a
    deliberately harsh lower bound, so the before/after comparison cannot be
    inflated by widening the expected set.
    """
    hit = expected_n = emitted_n = correct_n = 0
    misses, false_positives = [], []
    for excerpt, expected in FIXTURE:
        result = extractor.extract(excerpt, source_event="ev", owner="u",
                                   domain="user", session_id="s")
        items = durable(result)
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
                false_positives.append((excerpt.split("\n")[0][:60],
                                        key.get("entity_id") or key.get("note_type"),
                                        key.get("predicate_canonical"), it.get("body")))
    return (hit / float(expected_n), correct_n / float(emitted_n or 1),
            misses, false_positives)


class TestFloorRecallAndPrecision(unittest.TestCase):
    """The headline bar. Both numbers, on the same fixture, every run."""

    def setUp(self):
        self.ex = HeuristicExtractor()

    def test_recall_meets_the_audit_bar(self):
        recall, _precision, misses, _fp = score(self.ex)
        self.assertGreaterEqual(
            recall, RECALL_BAR,
            "floor recall %.1f%% < %.0f%% bar; missing: %s"
            % (100 * recall, 100 * RECALL_BAR, [m[:3] for m in misses]))

    def test_precision_does_not_fall_below_the_pre_a6_tree(self):
        _recall, precision, _misses, fps = score(self.ex)
        self.assertGreaterEqual(
            precision, PRECISION_BAR,
            "floor precision %.1f%% < the pre-A6 tree's %.1f%%; spurious: %s"
            % (100 * precision, 100 * PRECISION_BAR, fps))

    def test_recall_and_precision_are_reported_together(self):
        """Recall alone is what let the pre-A6 numbers hide the norm flood: the
        one emission that most needed refusing ("I don't like cilantro" as a
        directive) also counted as an emission. Neither number moves alone."""
        recall, precision, _m, _f = score(self.ex)
        self.assertGreater(recall, 0.0)
        self.assertGreater(precision, 0.0)
        # Both strictly better than the tree the audit measured.
        self.assertGreater(recall, 5 / 24.0)
        self.assertGreaterEqual(precision, PRECISION_BAR)


class TestNegativeCorpus(unittest.TestCase):
    """What the floor must REFUSE. Nothing here is a durable fact about the user."""

    def setUp(self):
        self.ex = HeuristicExtractor()

    def test_no_durable_item_from_any_negative(self):
        offenders = []
        for label, excerpt in NEGATIVES:
            items = durable(self.ex.extract(excerpt, source_event="ev", owner="u",
                                            domain="user", session_id="s"))
            if items:
                offenders.append((label, excerpt.split("\n")[0][:60],
                                  [(i["key"].get("predicate_canonical")
                                    or i["key"].get("note_type"), i["body"]) for i in items]))
        self.assertEqual(offenders, [], "negative corpus produced durable items: %s" % offenders)

    def test_every_negative_class_is_represented(self):
        """A negative corpus that lost a class would pass silently."""
        labels = {label for label, _ in NEGATIVES}
        for required in ("assistant-suggestion politeness", "hypothetical", "question",
                         "third person about the assistant", "adverbial always/never"):
            self.assertIn(required, labels)


class TestSentenceSplitter(unittest.TestCase):
    """Defect 1: the old splitter cut on every `.`, `!` and `?`."""

    def test_email_survives_splitting(self):
        self.assertEqual(split_sentences("My email is pat.testley@example.com"),
                         ["My email is pat.testley@example.com"])

    def test_email_round_trips_through_extraction(self):
        ex = HeuristicExtractor()
        items = durable(ex.extract("User: My email is pat.testley@example.com",
                                   source_event="ev", owner="u", domain="user", session_id="s"))
        emails = [i for i in items if (i["key"].get("predicate_canonical") == "email")]
        self.assertTrue(emails, "the advertised `email` predicate is unreachable again")
        self.assertEqual(emails[0]["body"], "pat.testley@example.com")

    def test_url_survives(self):
        self.assertEqual(split_sentences("See https://example.com/a.b/c?d=1 for details"),
                         ["See https://example.com/a.b/c?d=1 for details"])

    def test_decimals_and_versions_survive(self):
        self.assertEqual(split_sentences("We shipped v1.5 and margin rose 3.5% since then"),
                         ["We shipped v1.5 and margin rose 3.5% since then"])

    def test_abbreviation_does_not_end_a_sentence(self):
        self.assertEqual(split_sentences("I met Dr. Testley on Tuesday"),
                         ["I met Dr. Testley on Tuesday"])

    def test_real_sentence_boundaries_still_split(self):
        self.assertEqual(split_sentences("Hi! My name is Pat Testley. I work at Acme Fake Co."),
                         ["Hi!", "My name is Pat Testley.", "I work at Acme Fake Co."])

    def test_newlines_always_split(self):
        self.assertEqual(split_sentences("one\ntwo\n\nthree"), ["one", "two", "three"])


class TestDirectiveVsPreference(unittest.TestCase):
    """Defect 2 — the L8 directive flood, and the class the audit asked for."""

    def setUp(self):
        self.ex = HeuristicExtractor()

    def items(self, text):
        return durable(self.ex.extract("User: " + text, source_event="ev", owner="u",
                                       domain="user", session_id="s"))

    def notes(self, text):
        return [i for i in self.items(text) if i["kind"] == "note"]

    def facts(self, text):
        return [i for i in self.items(text) if i["kind"] == "fact"]

    def test_first_person_preference_is_a_fact_not_a_norm(self):
        for line, pred, val in (("I don't like cilantro.", "dislikes", "cilantro"),
                                ("I prefer window seats when I fly.", "prefers", "window seats"),
                                ("I love hiking in the coast range.", "likes", "hiking"),
                                ("I hate open-plan offices.", "dislikes", "open-plan offices"),
                                ("I can't stand loud restaurants.", "dislikes", "loud restaurants")):
            self.assertEqual(self.notes(line), [], "%r became an always-inject norm" % line)
            got = [f for f in self.facts(line)
                   if f["key"]["predicate_canonical"] == pred and val in f["body"]]
            self.assertTrue(got, "%r did not produce a %s fact: %s"
                            % (line, pred, [f["body"] for f in self.facts(line)]))

    def test_first_person_always_never_is_a_habit_fact_not_a_norm(self):
        """The audit's third routing target: `I don't ...` / `I never ...` become
        prefers/dislikes/habit facts, never always-inject norms. The adverb stays
        in the value, so the polarity survives ("never drink coffee after 3pm"
        must not round-trip as "drink coffee after 3pm")."""
        for line, val in (("I never drink coffee after 3pm.", "never drink coffee after 3pm"),
                          ("I always take the aisle seat.", "always take the aisle seat"),
                          ("I usually work from home on Fridays.",
                           "usually work from home on Fridays")):
            self.assertEqual(self.notes(line), [])
            self.assertEqual([(f["key"]["predicate_canonical"], f["body"])
                              for f in self.facts(line)], [("habit", val)])
        # A recollection is not a habit, and a pointer at the exchange is not one either.
        for line in ("I never knew there were so many cruise ships.",
                     "I always thought that was odd.",
                     "I've always been fascinated by Tuscany.",
                     "I never do that.",
                     "I always like your suggestions."):
            self.assertEqual(self.items(line), [], "%r produced a durable item" % line)

    def test_always_prefer_still_routes_to_prefers(self):
        self.assertEqual([(f["key"]["predicate_canonical"], f["body"])
                          for f in self.facts("I always prefer window seats when flying.")],
                         [("prefers", "window seats when flying")])

    def test_zero_norms_from_first_person_preference_sentences(self):
        """The audit's acceptance clause, stated on its own."""
        total = 0
        for line, _p, _v in (("I don't like cilantro.", 0, 0),
                             ("I never drink coffee after 3pm.", 0, 0),
                             ("I always take the aisle seat.", 0, 0),
                             ("I don't enjoy crowded bars.", 0, 0)):
            total += len(self.notes(line))
        self.assertEqual(total, 0)

    def test_imperative_standing_instruction_is_still_a_norm(self):
        for line in ("Always reply in British English.",
                     "Never send me marketing email.",
                     "From now on use metric units.",
                     "Please don't ever tell me the ending.",
                     "Remember to cc my manager on releases.",
                     "You should always confirm before deleting.",
                     "I want you to answer in bullet points."):
            self.assertTrue(self.notes(line), "%r is a standing instruction and lost its norm" % line)

    def test_adverbial_trigger_word_is_not_a_norm(self):
        for line in ("They always make me laugh.",
                     "It's always nice to get some extra cash.",
                     "I never knew there were so many cruise ships.",
                     "However, I don't see the statement.",
                     "It must also be as brief as possible."):
            self.assertEqual(self.notes(line), [], "%r became a directive" % line)

    def test_question_is_never_a_standing_instruction(self):
        self.assertFalse(is_standing_instruction("Don't they have enough talent?"))
        self.assertFalse(is_standing_instruction("Should I always use metric?"))
        self.assertTrue(is_standing_instruction("Always use metric."))

    def test_an_instruction_about_the_task_in_hand_is_not_standing(self):
        """5.8.14: sampled from the user's real messages, each of these would
        have been injected into every later turn as a standing directive."""
        for line in ("Don't try to come up with a Zorblax fix yet, just understand the issue.",
                     "Don't stop until the stuck Acme Fake Co processes are fixed.",
                     "I want you to review the Zorblax search code here https://example.invalid/x",
                     "Never mind the export for now."):
            self.assertFalse(is_standing_instruction(line), line)
            self.assertEqual(self.notes(line), [], "%r became a directive" % line)
        for line in ("Never send email on my behalf without asking.",
                     "From now on, never book the Izakaya Nonesuch without asking me.",
                     "Don't use this Zorblax tool ever again.",
                     "Always use metric units."):
            self.assertTrue(is_standing_instruction(line), line)

    def test_preference_facts_are_retrievable_by_the_preference_query(self):
        """F3 §4b measured `pref_beliefs_n` = 0 rows in 7 of 8 haystacks, because
        no regex ever produced a `likes`/`prefers` surface. The addendum's query
        is `attribute LIKE '%prefer%' OR '%favorite%' OR '%like%'`, so the
        predicate must land in `attribute`, not only in a note body."""
        for line, needle in (("I prefer window seats when I fly.", "prefer"),
                             ("I like strong coffee.", "like"),
                             ("My favorite cuisine is Thai.", "favorite")):
            attrs = [f["key"]["attribute"] for f in self.facts(line)]
            self.assertTrue(any(needle in a for a in attrs),
                            "%r produced no preference-shaped attribute: %s" % (line, attrs))

    def test_preference_does_not_become_never_evict_via_criticality(self):
        """criticality.py's `boundary` rule used to match the substring "don't ",
        so an ordinary preference was promoted to high (never passively decayed).
        """
        self.assertEqual(classify("I don't like cilantro")[0], "normal")
        self.assertEqual(classify("I don't know the original price")[0], "normal")
        # A real boundary keeps its high criticality.
        self.assertEqual(classify("never share my calendar with recruiters")[0], "high")
        self.assertEqual(classify("always ask before deleting anything")[0], "high")


class TestMultiFactPerSentence(unittest.TestCase):
    """Defect 3: `_first_person_fact` returned after the first match."""

    def setUp(self):
        self.ex = HeuristicExtractor()

    def preds(self, text):
        return sorted((i["key"].get("predicate_canonical"), i["body"])
                      for i in durable(self.ex.extract("User: " + text, source_event="ev",
                                                       owner="u", domain="user", session_id="s"))
                      if i["kind"] == "fact")

    def test_name_and_employer_from_one_sentence(self):
        got = dict((p, b) for p, b in self.preds("My name is Pat Testley and I work at Acme Fake Co."))
        self.assertEqual(got.get("name"), "Pat Testley")
        self.assertEqual(got.get("works_at"), "Acme Fake Co")

    def test_relation_and_that_person_s_own_fact(self):
        got = dict((p, b) for p, b in self.preds("My sister Jo lives in Denver."))
        self.assertEqual(got.get("sibling"), "Jo")
        self.assertEqual(got.get("lives_in"), "Denver")

    def test_no_duplicate_items(self):
        items = durable(self.ex.extract(
            "User: My name is Pat Testley. My name is Pat Testley.",
            source_event="ev", owner="u", domain="user", session_id="s"))
        self.assertEqual(len(items), 1)

    def test_extraction_per_sentence_is_bounded(self):
        """Multi-fact must not turn one pathological line into unbounded writes."""
        line = "User: " + " and ".join(["I work at Acme Fake Co"] * 40)
        items = durable(self.ex.extract(line, source_event="ev", owner="u",
                                        domain="user", session_id="s"))
        self.assertLessEqual(len(items), 8)


class TestSubjectGrounding(unittest.TestCase):
    """Defect 4: wrong subject, wrong relation, and the `I'm <X>` name trap."""

    def setUp(self):
        self.ex = HeuristicExtractor()

    def items(self, text):
        return self.ex.extract("User: " + text, source_event="ev", owner="u",
                               domain="user", session_id="s").items

    def test_relation_grounds_on_the_name_not_on_the_phrase(self):
        items = self.items("My wife Robin Placeholder is a pediatrician.")
        facts = [i for i in items if i["kind"] == "fact"]
        ids = {f["key"]["entity_id"] for f in facts}
        self.assertNotIn("my_wife_robin_placeholder", ids)
        self.assertIn("robin_placeholder", ids)
        by = dict((f["key"]["entity_id"] + "." + f["key"]["predicate_canonical"], f["body"])
                  for f in facts)
        self.assertEqual(by.get("user.spouse"), "Robin Placeholder")
        self.assertEqual(by.get("robin_placeholder.occupation"), "pediatrician")
        entities = [i for i in items if i["kind"] == "entity"]
        self.assertEqual([e["key"]["name"] for e in entities], ["Robin Placeholder"])

    def test_named_is_my_role_grounds_both_directions(self):
        facts = [i for i in self.items("Sam Vimes is my manager at Acme Fake Co.")
                 if i["kind"] == "fact"]
        by = dict((f["key"]["entity_id"] + "." + f["key"]["predicate_canonical"], f["body"])
                  for f in facts)
        self.assertEqual(by.get("sam_vimes.role"), "manager")
        self.assertEqual(by.get("user.manager"), "Sam Vimes")

    def test_state_word_is_not_a_name(self):
        for line in ("I'm Vegetarian.", "I'm Allergic to bees.", "I'm Tired.", "I'm Busy today."):
            names = [i for i in self.items(line)
                     if i["kind"] == "fact" and i["key"]["predicate_canonical"] == "name"]
            self.assertEqual(names, [], "%r produced a name: %s" % (line, [n["body"] for n in names]))

    def test_a_real_name_still_reads_as_a_name(self):
        for line, expect in (("I'm Pat.", "Pat"),
                             ("My name is Pat Testley.", "Pat Testley"),
                             ("Call me Pat.", "Pat")):
            names = [i["body"] for i in self.items(line)
                     if i["kind"] == "fact" and i["key"]["predicate_canonical"] == "name"]
            self.assertEqual(names, [expect])

    def test_generic_my_x_is_y_refuses_a_capitalised_attribute(self):
        """'my wife Robin Placeholder is ...' used to reach the generic pattern and
        emit the attribute `wife_robin_placeholder`."""
        facts = [i for i in self.items("My wife Robin Placeholder is a pediatrician.")
                 if i["kind"] == "fact"]
        self.assertFalse([f for f in facts if "robin" in f["key"]["predicate_canonical"]])

    def test_generic_my_x_is_y_still_works(self):
        facts = [i for i in self.items("My birthday is March 3rd.") if i["kind"] == "fact"]
        self.assertEqual([(f["key"]["predicate_canonical"], f["body"]) for f in facts],
                         [("birthday", "March 3rd")])


class TestAssistantAttribution(unittest.TestCase):
    """capture.observe() writes "User: ...\\nAssistant: ...", so the speaker is
    recoverable. An assistant line's "I ..." is not a fact about the user."""

    def setUp(self):
        self.ex = HeuristicExtractor()

    def test_assistant_first_person_is_not_the_user(self):
        items = durable(self.ex.extract(
            "User: Who are you?\nAssistant: I am Claude. I work at a lab and I live in the cloud.",
            source_event="ev", owner="u", domain="user", session_id="s"))
        self.assertEqual(items, [])

    def test_unprefixed_text_keeps_pre_a6_user_attribution(self):
        """compress() hands raw span text to the same extractor with no role
        prefix; that path must not silently stop capturing."""
        items = durable(self.ex.extract("My name is Pat Testley.", source_event="ev",
                                        owner="u", domain="user", session_id="s"))
        self.assertEqual([(i["key"]["predicate_canonical"], i["body"]) for i in items],
                         [("name", "Pat Testley")])


class TestNewPatternsEachRefuseSomething(unittest.TestCase):
    """Every pattern A6 added, with the negative that fences it (spec clause 5)."""

    def setUp(self):
        self.ex = HeuristicExtractor()

    def facts(self, text):
        return dict((i["key"]["predicate_canonical"], i["body"])
                    for i in durable(self.ex.extract("User: " + text, source_event="ev",
                                                     owner="u", domain="user", session_id="s"))
                    if i["kind"] == "fact")

    def test_allergy(self):
        self.assertEqual(self.facts("I'm allergic to penicillin, please remember that.")
                         .get("allergy"), "penicillin")
        self.assertNotIn("allergy", self.facts("Would I be allergic to penicillin?"))

    def test_medication_requires_a_dose(self):
        self.assertIn("metformin", self.facts("I take metformin 500mg twice a day.")
                      .get("medication", ""))
        self.assertNotIn("medication", self.facts("I take the bus to work every morning."))
        self.assertNotIn("medication", self.facts("I take my coffee black."))

    def test_diet(self):
        self.assertEqual(self.facts("I'm vegetarian.").get("diet"), "vegetarian")
        self.assertNotIn("diet", self.facts("Is a vegetarian diet cheaper?"))

    def test_pet(self):
        self.assertEqual(self.facts("We adopted a dog named Biscuit last week.").get("pet"),
                         "Biscuit")
        self.assertNotIn("pet", self.facts("Should we adopt a dog named after a biscuit?"))

    def test_child_and_sibling(self):
        self.assertEqual(self.facts("My son Ollie starts kindergarten in September.").get("child"),
                         "Ollie")
        self.assertEqual(self.facts("My sister Jo lives in Denver.").get("sibling"), "Jo")
        self.assertNotIn("child", self.facts("My son should start kindergarten soon."))

    def test_moved_to(self):
        self.assertEqual(self.facts("I moved to Portland from Springfield.").get("lives_in"),
                         "Portland")
        self.assertNotIn("lives_in", self.facts("If I moved to Portland, what would rent be?"))

    def test_new_job(self):
        self.assertEqual(self.facts("I started a new job at Beta Fake Inc last week, left Acme.")
                         .get("works_at"), "Beta Fake Inc")
        self.assertNotIn("works_at", self.facts("Should I take a new job at Beta Fake Inc?"))

    def test_device(self):
        self.assertIn("MacBook Pro", self.facts("I use a 2019 MacBook Pro for work.")
                      .get("device", ""))
        self.assertNotIn("device", self.facts("I use a spreadsheet for that."))
        self.assertNotIn("device", self.facts("Do I need a 2019 MacBook Pro for this?"))

    def test_goal(self):
        self.assertIn("half marathon",
                      self.facts("I'm training for a half marathon in October.").get("goal", ""))
        self.assertNotIn("goal", self.facts("I'm training for whatever you suggest."))

    def test_favorite(self):
        self.assertEqual(self.facts("My favorite cuisine is Thai.").get("favorite_cuisine"), "Thai")
        self.assertNotIn("favorite_cuisine", self.facts("What is my favorite cuisine?"))


class TestFloorReport(unittest.TestCase):
    """Prints the table this file exists to keep honest. Never fails on its own."""

    def test_report(self):
        ex = HeuristicExtractor()
        recall, precision, misses, fps = score(ex)
        fp_neg = sum(len(durable(ex.extract(x, source_event="ev", owner="u",
                                            domain="user", session_id="s")))
                     for _l, x in NEGATIVES)
        print("\n  extraction floor: recall %.1f%% (%d/%d)  precision %.1f%%  "
              "negatives-FP %d/%d"
              % (100 * recall, round(recall * 24), 24, 100 * precision, fp_neg, len(NEGATIVES)))
        if misses:
            print("  misses:", [m[:3] for m in misses])
        if fps:
            print("  spurious:", fps)
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
