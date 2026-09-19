"""
Chronicle — a request is not something that happened, and a wanted state is
not a fact.

Sampled on the user's real messages (the shapes kept, the words faked):

    "Yes, and once everything is correctly backed up … run genie again"
        -> an EPISODE: the command follows a leading clause with no comma;
    "Same rules apply, don't out yourself, use the vibes skill on any prose."
        -> an EPISODE: the commands come after commas (what is left when they
           go, "Same rules apply", is too short to be one);
    "Fix is so that my library is a folder slskd can see"
        -> a FACT, library = "folder slskd can see": a state asked for, in a
           sentence that is a command.

The narrative around them must still land: "When I was in Riverton I would
run every morning before work" is not a command to run, and "My library is a
folder on the NAS" is a fact.

Fixtures use obviously fake values.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import speaker as spk
from engine.extraction import HeuristicExtractor


def extract(said):
    lines = list(spk.parse_labeled("User: " + said, spk.HUMAN, spk.HUMAN))
    return [(i["kind"], i.get("body") or "")
            for i in HeuristicExtractor().extract("User: " + said, source_event="t", lines=lines).items]


class TestARequestIsNotAnEpisode(unittest.TestCase):
    def test_a_command_after_a_clause_with_no_comma(self):
        self.assertEqual(extract("Yes, and once everything is correctly backed up and verified run "
                                 "the Zorblax export again"), [])

    def test_a_command_after_a_comma(self):
        self.assertEqual(extract("Same rules apply for the Acme Fake Co repo, don't mention me, "
                                 "use the plain style on any prose."), [])

    def test_the_account_stays_when_a_command_follows_it(self):
        eps = [b for k, b in extract("There isn't enough space on the Zorblax box to use it for storage, other "
                                     "than a brief cache, so that isn't a viable path, figure out something "
                                     "that works on Acme Fake Co") if k == "episode"]
        self.assertEqual(len(eps), 1, eps)
        self.assertIn("isn't a viable path", eps[0])
        self.assertNotIn("figure out", eps[0])

    def test_narrative_with_an_open_clause_still_lands(self):
        for said in ("When I was in Riverton I would run every morning before work and it was great.",
                     "After work we went to the Zorblax market and bought far too many pears for the weekend.",
                     "Once the kids were asleep we finally watched the Zorblax documentary and loved it a lot.",
                     "We got home late, checked the mail, and made dinner for Pat Testley and Robin Placeholder."):
            with self.subTest(said=said):
                self.assertIn("episode", [k for k, _b in extract(said)])


class TestAWantedStateIsNotAFact(unittest.TestCase):
    def test_a_state_asked_for_in_a_command(self):
        self.assertFalse([b for k, b in extract("Fix is so that my library is a folder Zorblax can see")
                          if k == "fact"])

    def test_a_state_asked_for_without_a_command(self):
        self.assertFalse([b for k, b in extract("It should be set up so that my library is a folder "
                                                 "Zorblax can see") if k == "fact"])

    def test_a_command_that_mentions_my_x_is_y(self):
        self.assertFalse([b for k, b in extract("Check whether my backup is running on the Acme Fake Co NAS")
                          if k == "fact"])

    def test_a_stated_one_still_is(self):
        facts = [b for k, b in extract("My library is a folder on the Acme Fake Co NAS in the basement.")
                 if k == "fact"]
        self.assertTrue(any("Acme Fake Co NAS" in b for b in facts), facts)


if __name__ == "__main__":
    unittest.main()
