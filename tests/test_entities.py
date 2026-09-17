"""
Chronicle — an entity is a person, a place, a thing, an event or an idea.

The junk in these tests is verbatim from a production store's entity table
(names and types shortened only where noted): 171 pronoun rows, 65 sentence
fragments, 1,003 rows named by another store's id, and free-text types with no
taxonomy. Fixture names that are not production junk are obviously fake.
"""

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine import entities as ent
from engine.core import ChronicleCore

# Verbatim from the production entity table.
PRODUCTION_JUNK_NAMES = (
    "This", "There", "Each one", "Rotating between them", "If this",
    "Per the dispatch skill this", "Let me check the state file pre-check shortcut first",
    "So any flow that needs a browser I hold but can't bridge to",
    "Since git-lfs is installed and this", "But when the listed journals are already",
    "indigo", "user",
)
PRODUCTION_REAL_NAMES = ("NVIDIA", "Databricks", "GIBS", "Graze", "Packaging", "AI")
PRODUCTION_JUNK_TYPES = (
    "no", "re", "one", "second", "valid", "typo", "real managed challenge",
    "dead end for getting a usable key into my environment",
    "separate vendor with its own credential", "source bug confirmed in the Forge SKILL",
)


class TestANameIsAProperNoun(unittest.TestCase):
    def test_production_junk_is_rejected(self):
        for name in PRODUCTION_JUNK_NAMES:
            with self.subTest(name=name):
                self.assertFalse(ent.plausible_name(name))

    def test_real_names_are_kept(self):
        for name in PRODUCTION_REAL_NAMES + ("Pat Testley", "Acme Fake Co", "E.K. Chung",
                                             "iPhone", "eBay", "Robin Placeholder",
                                             "Museum of Modern Art", "Sam Vimes"):
            with self.subTest(name=name):
                self.assertTrue(ent.plausible_name(name))

    def test_an_importers_subject_line_is_not_a_name(self):
        self.assertFalse(ent.plausible_name(
            'Ordered 1 item: Clothing | from "Acme Fake Co" | Sun, 6 Sep 2026'))

    def test_an_id_is_not_a_name(self):
        for i in ("5734393e-cc34-5920-a7a8-09951cf2ce0c",
                  "b_2136d856707c9b45031136d4d2f62a22d9c5d969065ef248610f2106b30a708e"):
            with self.subTest(id=i):
                self.assertTrue(ent.is_id_like(i))
                self.assertFalse(ent.plausible_name(i))


class TestATypeIsACategory(unittest.TestCase):
    def test_production_junk_types_are_rejected(self):
        for t in PRODUCTION_JUNK_TYPES:
            with self.subTest(type=t):
                self.assertFalse(ent.plausible_type(t))

    def test_categories_are_kept(self):
        for t in ("person", "organization", "animal", "nurse", "web browser",
                  "coffee shop", "city"):
            with self.subTest(type=t):
                self.assertTrue(ent.plausible_type(t))


class TestKinds(unittest.TestCase):
    def test_types_map_to_the_five_kinds(self):
        for t, kind in (("person", ent.PERSON), ("wife", ent.PERSON), ("nurse", ent.PERSON),
                        ("city", ent.PLACE), ("coffee shop", ent.PLACE),
                        ("organization", ent.THING), ("animal", ent.THING), ("laptop", ent.THING),
                        ("birthday", ent.EVENT), ("appointment", ent.EVENT), ("trip", ent.EVENT),
                        ("topic", ent.CONCEPT), ("allergy", ent.CONCEPT), ("project", ent.CONCEPT)):
            with self.subTest(type=t):
                self.assertEqual(ent.kind_for(t), kind)

    def test_an_occupation_is_a_person(self):
        for t in ("pediatrician", "radiologist", "psychiatrist", "photographer", "physical therapist"):
            with self.subTest(type=t):
                self.assertEqual(ent.kind_for(t), ent.PERSON)

    def test_a_lookalike_ending_is_not_a_person(self):
        for t in ("checklist", "computer", "register"):
            with self.subTest(type=t):
                self.assertNotEqual(ent.kind_for(t), ent.PERSON)

    def test_an_unknown_type_is_not_guessed(self):
        for t in ("", "separate vendor with its own credential", "distribution pattern", "duty"):
            with self.subTest(type=t):
                self.assertEqual(ent.kind_for(t), "")

    def test_predicates_answer_when_the_type_cannot(self):
        self.assertEqual(ent.kind_for("", ("birthday", "email")), ent.PERSON)
        self.assertEqual(ent.kind_for("", ("located_in",)), ent.PLACE)
        self.assertEqual(ent.kind_for("", ("is_a", "value")), "")

    def test_the_type_wins_over_the_predicates(self):
        self.assertEqual(ent.kind_for("city", ("birthday",)), ent.PLACE)


class TestResolvingAnIdToAName(unittest.TestCase):
    def test_a_name_the_log_asserts_replaces_the_id(self):
        self.assertEqual(ent.resolve_name("5734393e-cc34-5920-a7a8-09951cf2ce0c", "Pat Testley"),
                         "Pat Testley")

    def test_a_readable_name_is_left_alone(self):
        self.assertEqual(ent.resolve_name("Acme Fake Co", "Something Else"), "Acme Fake Co")

    def test_nothing_to_resolve_to_keeps_the_id(self):
        for asserted in (None, "", "   ", "b_0107b9f5e2d4c6a8b0d2f4e6a8c0b2d4f6e8a0c2b4d6f8e0"):
            with self.subTest(asserted=asserted):
                self.assertEqual(ent.resolve_name("5734393e-cc34-5920-a7a8-09951cf2ce0c", asserted),
                                 "5734393e-cc34-5920-a7a8-09951cf2ce0c")

    def test_another_stores_name_is_taken_as_it_is(self):
        """The strict name rules decide what TEXT may create an entity; a people
        store legitimately holds these."""
        for asserted in ("Ramp 💳", "Laura schewel", "katie@example.invalid", "Ken @ Glass23"):
            with self.subTest(asserted=asserted):
                self.assertEqual(ent.resolve_name("5734393e-cc34-5920-a7a8-09951cf2ce0c", asserted),
                                 asserted)


class _Case(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.addCleanup(shutil.rmtree, self.home, True)
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing", "dimensions": 32}})
        self.core.initialize("s-ent", principal_id="assistant")

    def _rows(self, sql, params=()):
        c = sqlite3.connect(self.core.store.db_path)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute(sql, params)]
        finally:
            c.close()

    def _turn(self, text):
        self.core.capture.observe(text, "Noted.", session_id="s-ent")
        self.core.process_pending()

    def entities(self):
        return {r["name"]: r["type"] for r in self._rows("SELECT name, type FROM entities")}


class TestJunkNeverBecomesAnEntity(_Case):
    def test_a_sentence_the_user_wrote_is_not_an_entity(self):
        """Attribution stops the assistant's prose reaching here; this stops the
        pattern itself, so the same sentence typed by the user is refused too."""
        self._turn("This is a real managed challenge. Rotating between them is a distribution "
                   "pattern. Each one is a bounded task.")
        self.assertEqual(self.entities(), {})
        self.assertEqual([r["value"] for r in self._rows(
            "SELECT value FROM facts WHERE predicate_canonical='is_a'")], [])

    def test_a_real_subject_and_category_still_land(self):
        self._turn("Acme Fake Co is a company. Pat Testley is a pediatrician.")
        self.assertEqual(self.entities(), {"Acme Fake Co": "company", "Pat Testley": "pediatrician"})
        self.assertEqual(sorted(r["value"] for r in self._rows(
            "SELECT value FROM facts WHERE predicate_canonical='is_a'")), ["company", "pediatrician"])

    def test_the_boundary_refuses_it_even_when_the_extractor_does_not(self):
        """The same bar at the write boundary: an extractor (or a model) that
        emits a junk entity item does not get it into the log."""
        ev = self.core.capture.append("observed", {"source_type": "session_transcript",
                                                   "excerpt": "user: anything"},
                                      actor="user", session_id="s-ent")
        event = self.core.store.get_event(ev)
        item = {"type": "asserted", "kind": "entity",
                "key": {"entity_type": "real managed challenge", "type": "real managed challenge",
                        "name": "This", "normalized_name": "this", "owner": "default",
                        "domain": "user"},
                "body": "This", "confidence": 0.7, "source_event": ev,
                "source_type": "session_transcript", "route": "promote"}
        with self.assertLogs("chronicle.curation", level="WARNING"):
            self.core.curation._emit_item(item, event, "default", "user", "session_transcript",
                                          "extractor-v1")
        self.assertEqual(self.entities(), {})


class TestAnIdBecomesAName(_Case):
    UUID = "5734393e-cc34-5920-a7a8-09951cf2ce0c"

    def _fact(self, predicate, value):
        self.core.capture.append("asserted", {
            "kind": "fact", "key": {"entity_id": self.UUID, "predicate_canonical": predicate,
                                    "attribute": predicate, "qualifiers_hash": "", "qualifiers": {}},
            "body": value, "confidence": 0.9, "source_event": "weave:1",
            "source_type": "external_people_weave", "domain": "user"}, actor="system")
        self.core.process_pending()

    def test_the_name_the_log_asserts_replaces_the_id(self):
        self._fact("occupation", "designer")       # creates the row, named by the id
        self.assertEqual(self.entities(), {self.UUID: ""})
        self._fact("name", "Pat Testley")
        self.assertEqual(self.entities(), {"Pat Testley": ""})

    def test_a_rebuild_reproduces_it(self):
        self._fact("occupation", "designer")
        self._fact("name", "Pat Testley")
        self.core.reducer.rebuild()
        self.assertEqual(self.entities(), {"Pat Testley": ""})

    def test_a_name_fact_never_renames_a_named_entity(self):
        self.core.capture.observe("Acme Fake Co is a company.", "Noted.", session_id="s-ent")
        self.core.process_pending()
        self.core.capture.append("asserted", {
            "kind": "fact", "key": {"entity_id": "acme_fake_co", "predicate_canonical": "name",
                                    "attribute": "name", "qualifiers_hash": "", "qualifiers": {}},
            "body": "Something Else", "confidence": 0.9, "source_event": "weave:2",
            "source_type": "external_people_weave", "domain": "user"}, actor="system")
        self.core.process_pending()
        self.assertIn("Acme Fake Co", self.entities())


class TestARebuildDoesNotResurrectJunk(_Case):
    def test_entity_events_from_before_the_rule_project_to_nothing(self):
        """The log holds years of these; the fold, not just the writer, refuses
        them, so a rebuild reproduces the clean projection (I3)."""
        for name, etype in (("This", "real managed challenge"), ("Each one", "bounded task"),
                            ("Acme Fake Co", "company")):
            self.core.capture.append("asserted", {
                "kind": "entity",
                "key": {"entity_type": etype, "type": etype, "name": name,
                        "normalized_name": name.lower(), "owner": "default", "domain": "user"},
                "body": name, "confidence": 0.7, "source_event": "ev_old",
                "source_type": "session_transcript"}, actor="curator")
        self.core.process_pending()
        self.assertEqual(self.entities(), {"Acme Fake Co": "company"})
        self.core.reducer.rebuild()
        self.assertEqual(self.entities(), {"Acme Fake Co": "company"})

    def test_a_dropped_entity_leaves_no_justification_behind(self):
        """I5: every justification supports a real belief."""
        self.core.capture.append("asserted", {
            "kind": "entity", "key": {"entity_type": "no", "type": "no", "name": "This",
                                      "normalized_name": "this", "owner": "default", "domain": "user"},
            "body": "This", "confidence": 0.7, "source_event": "ev_old",
            "source_type": "session_transcript"}, actor="curator")
        self.core.process_pending()
        orphans = self._rows("SELECT belief_id FROM justifications WHERE belief_id NOT IN "
                             "(SELECT belief_id FROM entities UNION SELECT belief_id FROM facts "
                             "UNION SELECT belief_id FROM notes UNION SELECT belief_id FROM episodes)")
        self.assertEqual(orphans, [])


class TestARetractionClosesItsContradictions(_Case):
    """A contradiction is two beliefs the store cannot both hold. Retract one and
    there is nothing left to reconcile — 1,550 open rows naming retracted
    beliefs is a queue of questions nobody can answer."""

    def _fact(self, predicate, value, src):
        self.core.capture.append("asserted", {
            "kind": "fact", "key": {"entity_id": "pat_testley", "predicate_canonical": predicate,
                                    "attribute": predicate, "qualifiers_hash": "", "qualifiers": {}},
            "body": value, "confidence": 0.8, "source_event": src,
            "source_type": "user_direct", "domain": "user"}, actor="user", session_id="s-ent")
        self.core.process_pending()

    def _open(self):
        return self._rows("SELECT id, belief_a, belief_b, status FROM contradictions "
                          "WHERE status='open'")

    def test_retracting_either_side_resolves_it(self):
        self._fact("lives_in", "Fake City", "ev_a")
        self._fact("lives_in", "Other Fake City", "ev_b")
        open_rows = self._open()
        self.assertTrue(open_rows, "the fixture opened no contradiction")
        side = open_rows[0]["belief_a"]
        self.core.capture.append("retracted", {"belief_id": side, "reason": "misattributed"},
                                 actor="curator")
        self.core.process_pending()
        self.assertEqual(self._open(), [])
        # The row is resolved, not deleted: its detail and date are the record.
        self.assertEqual([r["status"] for r in self._rows(
            "SELECT status FROM contradictions")], ["resolved"])

    def test_a_batch_retraction_closes_them_too(self):
        self._fact("lives_in", "Fake City", "ev_a")
        self._fact("lives_in", "Other Fake City", "ev_b")
        ids = [self._open()[0]["belief_a"], self._open()[0]["belief_b"]]
        self.core.capture.append("retracted", {"belief_ids": ids, "reason": "misattributed"},
                                 actor="curator")
        self.core.process_pending()
        self.assertEqual(self._open(), [])


class TestKindsOverTheProjection(_Case):
    def test_an_entitys_kind_comes_from_its_type_then_its_facts(self):
        self._turn("Pat Testley is a pediatrician. Fake City is a city.")
        rows = {r["name"]: r["type"] for r in self._rows("SELECT name, type FROM entities")}
        self.assertEqual(ent.kind_for(rows["Pat Testley"]), ent.PERSON)
        self.assertEqual(ent.kind_for(rows["Fake City"]), ent.PLACE)


if __name__ == "__main__":
    unittest.main()
