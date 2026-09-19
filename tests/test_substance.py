"""
Chronicle — a fact has to say WHAT happened.

The rule, in the owner's words: "an email that says 'something happened' but
doesn't say what happened is just noise." An importer had been asking a model
"is there anything in this email worth recording?" once per message and writing
whatever came back; 159 of the 272 facts it produced on a production store were
the email's SUBJECT LINE, recorded as things the user had done.

The cases below keep the SHAPE of those production values — a heading, a count
and a category, a composed sentence — with obviously fake names throughout: the
rule reads shape, never the particular clinic or medicine it was measured on.

Both directions are pinned, because the expensive failure is the second one: a
write boundary that refuses a real memory loses it silently, while a row that
gets through can be retracted by anyone who sees it.
"""

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine import substance as sub
from engine.core import ChronicleCore

# Verbatim from the production store: a notification announcing that something
# exists somewhere else.
NOISE = (
    "New Message",
    "New After Visit Summary Available",
    "New App Linked to Your Fakeclinic Portal Account",
    "Fakeclinic Mobile Number Updated",
    "Activate Your Fakeclinic Account",
    "Fakeclinic Portal Quarterly Newsletter",
    "Test Result Daily Digest",
    "Earlier Appointment Available",
    "You have a new balance",
    "Your order has shipped!",
    "Delivery delayed",
    # A count as the object: the store category after it is not a referent.
    "Delivered 1 item: Clothing",
    "Shipped: 3 Pet items",
    "Ordered 3 items: Appliances, Health Care, and more",
    "Ordered: \u206617\u2069 Lighting & Fans, Kitchen Tools, and other items",
    "Your Subscription Renewal",
)

# Also from the production store, or shaped exactly like what the calendar
# import writes: these name the thing.
FACTS = (
    "Placebocil 40mg prescription refill ordered via Acme Fake Pharmacy"
    " on 2026-08-28.",
    "Advance refund issued for Acme Fake Dental Powder",
    'Delivered: "Acme Fake Widget 10-Piece" set',
    "Appointment with Pat Testley — 2025-03-10 — 3195 Fake Street, San Francisco, CA",
    "Robin Placeholder's birthday — 2026-03-06",
    "Acme Fake Co Labs — 2025-06-06",
    "Sam Vimes just got you tickets to the Fake Dyeing Workshop",
    # Named first, counted after: the count is not the object.
    "Refund issued for Acme Fake 8-Port Switch... and 3 other items.",
    'Delivered: "Acme Fake Widget Bulb..." and 12 more items',
)


class TestTheRule(unittest.TestCase):
    def test_an_announcement_is_not_a_memory(self):
        for value in NOISE:
            with self.subTest(value=value):
                self.assertFalse(sub.states_what_happened(value, "purchased"))
                self.assertTrue(sub.refusal(value, "purchased"))

    def test_a_fact_that_names_the_thing_is_kept(self):
        for value in FACTS:
            with self.subTest(value=value):
                self.assertTrue(sub.states_what_happened(value, "purchased"), value)
                self.assertEqual(sub.refusal(value, "purchased"), "")

    def test_a_quoted_title_or_a_date_outranks_the_shape(self):
        """"Appointment with Pat Testley — 2025-03-10 — 3195 Fake Street" is
        Title Cased like a subject line and is still a fact."""
        self.assertFalse(sub.states_what_happened("Delivered Two Items Today", "purchased"))
        self.assertTrue(sub.states_what_happened('Delivered "Acme Fake Widget"', "purchased"))
        self.assertTrue(sub.states_what_happened("Delivered Two Items 2026-03-06", "purchased"))

    def test_the_question_is_not_asked_of_an_attribute(self):
        """`phone` or `birthday` has a value that IS the attribute; "does it say
        what happened" is not a question about it, and asking would delete it."""
        for value, pred in (("555-0100", "phone"), ("SVP, Global Head of Design", "occupation"),
                            ("2025-03-06", "birthday"), ("Pat Testley", "name"),
                            ("Riverton", "lives_in")):
            with self.subTest(predicate=pred):
                self.assertTrue(sub.states_what_happened(value, pred))

    def test_an_unknown_predicate_is_left_alone(self):
        self.assertTrue(sub.states_what_happened("New Message", "something_new"))

    def test_bidi_marks_do_not_hide_the_text(self):
        """Gmail wraps subject fragments in bidi isolates. Without stripping
        them the patterns below see nothing and everything is accepted."""
        self.assertFalse(sub.states_what_happened("\u2066New Message\u2069", "purchased"))

    def test_where_a_value_came_from_does_not_say_what_happened(self):
        """An email importer appended the sender and the sent-time to every
        value. A quoted sender passed the quoted-title test and the sent-time
        the explicit-date test, so every subject line it wrote was kept."""
        tail = ' | from "Acme Fake Co" | Sun, 6 Sep 2026 07:04:28 +0000'
        for value in ("Delivered 1 item: Clothing", "Your Subscription Renewal",
                      "Your return drop off confirmation"):
            with self.subTest(value=value):
                self.assertFalse(sub.states_what_happened(value + tail, "purchased"))
        self.assertFalse(sub.states_what_happened(
            "Your Subscription Renewal | from Acme Fake Co | Sun, 6 Sep 2026 07:04:28 +0000 (GMT)",
            "purchased"))
        self.assertTrue(sub.states_what_happened(
            "Advance refund issued for Acme Fake Dental Powder" + tail, "purchased"))

    def test_an_event_date_is_content_not_provenance(self):
        self.assertTrue(sub.states_what_happened("Dinner at Fake Izakaya | 2026-09-12", "dined_at"))
        self.assertTrue(sub.states_what_happened("Fake Dyeing Workshop | Sun, 6 Sep 2026", "attended_event"))

    def test_an_empty_value_is_not_a_memory(self):
        self.assertFalse(sub.states_what_happened("", "purchased"))
        self.assertFalse(sub.states_what_happened("   ", "purchased"))


class TestTheFoldRefusesIt(unittest.TestCase):
    """In the fold, not only at the write boundary: the log already holds the
    events an importer wrote, and a rebuild must not bring them back (I3)."""

    def setUp(self):
        self.home = temp_home(prefix="substance-")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("20260917_010203_ab12cd", principal_id="assistant")

    def _assert(self, predicate, value):
        self.core.capture.append("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "predicate_canonical": predicate,
                    "attribute": predicate, "qualifiers_hash": "", "qualifiers": {}},
            "body": value, "confidence": 0.9, "source_event": "ev_mail",
            "source_type": "external_dispatch:email", "domain": "user"},
            actor="user", owner="default")
        self.core.process_pending()

    def _values(self):
        c = sqlite3.connect(self.core.store.db_path)
        rows = [r[0] for r in c.execute("SELECT value FROM facts WHERE status='active'")]
        c.close()
        return rows

    def test_an_imported_subject_line_never_becomes_a_fact(self):
        for value in NOISE:
            self._assert("purchased", value)
        self.assertEqual(self._values(), [])

    def test_the_real_ones_from_the_same_importer_land(self):
        self._assert("health_event", FACTS[0])
        self._assert("purchased", FACTS[1])
        self.assertEqual(len(self._values()), 2)

    def test_a_refused_fact_leaves_no_orphan_justification(self):
        """I5: no justification without a belief."""
        self._assert("purchased", "New Message")
        c = sqlite3.connect(self.core.store.db_path)
        n = c.execute("SELECT COUNT(*) FROM justifications").fetchone()[0]
        c.close()
        self.assertEqual(n, 0)

    def test_a_rebuild_does_not_resurrect_them(self):
        self._assert("purchased", "New Message")
        self._assert("purchased", FACTS[1])
        self.core.reducer.embedder = None
        self.core.reducer.rebuild()
        self.assertEqual(self._values(), [FACTS[1]])


if __name__ == "__main__":
    unittest.main()
