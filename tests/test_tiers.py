"""
Chronicle — a cut for budget must not spend itself on the prose.

Compaction's one lossy step shortens a span that will not fit and leaves the
id that restores it. Cutting the head keeps whatever happens to be first: on
the user's own transcripts that is the sentence introducing the work, while
the port number, the path, the container id and the command that failed sit
further in and go. The store still has them; the reader does not, and cannot
tell that anything is missing.

`engine/tiers.py` classifies by shape and spends the same budget on the exact
literals first. `context_engine.keep_literals` is ON by default as of
2026-09-19 -- the only flag here that earned it by measurement, on two corpora
that share nothing. Turned off, compaction cuts exactly as every release up to
5.8.35 did.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine, _cut_text
from engine import tiers as T
from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}, "curation": {"drain": {"per_turn": 0, "background": False}}}

# The shape of a real tool result: prose, then everything a reader cannot guess.
SPAN = ("The deploy failed again on the media box. I ran docker compose up -d --force-recreate "
        "droppedneedle and the container came up with --host --port 8688, so uvicorn never bound "
        "to anything and every request hung. The config it read is at /srv/fake/dn/config.json "
        "and the run id was fold_ab12cd34ef56. Retried at 2026-09-11T23:16:04Z, exit code 124 "
        "after 45s, and the second attempt died the same way.")
LITERALS = ("docker compose up -d --force-recreate droppedneedle", "--host", "--port 8688",
            "/srv/fake/dn/config.json", "fold_ab12cd34ef56", "2026-09-11T23:16:04Z", "exit code 124", "45s")


class TestWhatCountsAsExact(unittest.TestCase):
    def test_the_literals_of_a_real_span(self):
        found = T.literals(SPAN)
        for lit in LITERALS:
            with self.subTest(literal=lit):
                self.assertIn(lit, found)

    def test_a_literal_does_not_swallow_the_sentence_punctuation(self):
        self.assertIn("/srv/fake/dn/config.json", T.literals("the file is at /srv/fake/dn/config.json."))
        self.assertNotIn("/srv/fake/dn/config.json.", T.literals("the file is at /srv/fake/dn/config.json."))

    def test_prose_has_none(self):
        self.assertEqual(T.literals("we talked about lunch and agreed to meet later"), [])

    def test_the_tiers(self):
        self.assertEqual(T.classify("the service died on port 8688"), T.INVOLATILE)
        self.assertEqual(T.classify("the plan is to move the library to the NAS"), T.CRITICAL)
        self.assertEqual(T.classify("we talked about lunch"), T.CONTEXT)
        self.assertEqual(T.classify("   "), T.POINTER)
        self.assertEqual(T.classify("we talked about lunch", required=True), T.CRITICAL)
        self.assertEqual(T.classify("we talked about lunch", directive=True), T.CRITICAL)


class TestSpendingTheBudgetOnThem(unittest.TestCase):
    def test_a_head_cut_loses_them_the_literal_cut_keeps_them(self):
        cap = 220
        head = SPAN[:cap]
        kept = T.shorten_keeping_literals(SPAN, cap)
        self.assertLessEqual(len(kept), cap + 4)                    # the trailing " …"
        in_head = sum(1 for lit in LITERALS if lit in head)
        in_kept = sum(1 for lit in LITERALS if lit in kept)
        self.assertGreater(in_kept, in_head, (in_kept, in_head, kept))
        self.assertGreaterEqual(in_kept, 5)

    def test_it_says_where_it_cut(self):
        self.assertIn("…", T.shorten_keeping_literals(SPAN, 220))

    def test_what_fits_is_returned_whole(self):
        self.assertEqual(T.shorten_keeping_literals(SPAN, len(SPAN) + 10), SPAN)
        self.assertEqual(T.shorten_keeping_literals("short", 100), "short")

    def test_prose_still_cuts_at_the_head(self):
        prose = "we talked about lunch and then about the weather for a while longer"
        self.assertEqual(T.shorten_keeping_literals(prose, 20), prose[:20])

    def test_a_credential_is_the_one_literal_that_does_not_survive(self):
        said = 'login: patfake password: zz9-Plural-Zalpha7 at https://fake.invalid/admin'
        out = T.masked_and_shortened(said, 60)
        self.assertNotIn("zz9-Plural", out)
        self.assertIn("https://fake.invalid/admin", out)


class TestTheFlag(unittest.TestCase):
    def test_the_helper_cuts_the_head_unless_told_otherwise(self):
        """`_cut_text`'s own parameter, not the config default: every caller
        passes the engine's answer explicitly."""
        self.assertEqual(_cut_text(SPAN, 100), SPAN[:100])
        self.assertEqual(_cut_text(SPAN, 100, keep_literals=False), SPAN[:100])

    def test_the_default_is_on_and_it_was_measured(self):
        """Measured over 3,000 real spans after the budget-fill fix below:
        98.1% of a 220-character cap spent and +117% exact literals on the
        page. The involatile keep-weight is NOT part of it -- re-run at 0.25
        the figures are byte-identical, so the whole effect is this flag."""
        from engine.config import DEFAULTS
        self.assertIs(DEFAULTS["context_engine"]["keep_literals"], True)
        self.assertEqual(DEFAULTS["context_engine"]["keep_weights"]["involatile"], 0.0)

    def test_on_it_keeps_the_literals(self):
        out = _cut_text(SPAN, 220, keep_literals=True)
        self.assertIn("2026-09-11T23:16:04Z", out)          # 300 characters in; a head cut loses it
        self.assertNotIn("2026-09-11T23:16:04Z", _cut_text(SPAN, 220))

    def test_the_engine_reads_the_flag(self):
        home = temp_home(prefix="tiers_")
        try:
            eng = ChronicleContextEngine()
            eng.on_session_start("s-tiers", hermes_home=home, principal_id="pat", config=CFG)
            self.assertTrue(eng._keep_literals())
            eng.core.cfg._d["context_engine"]["keep_literals"] = False
            self.assertFalse(eng._keep_literals())
            eng.core.cfg._d["context_engine"]["keep_literals"] = True
            big = {"role": "tool", "tool_call_id": "c1", "content": SPAN}
            eng.update_model("fake-model", 200000)
            on = eng._cap_tool_result(big, 60)["content"]
            eng.core.cfg._d["context_engine"]["keep_literals"] = False
            off = eng._cap_tool_result(big, 60)["content"]
            self.assertIn("chronicle_expand(", on)
            self.assertIn("chronicle_expand(", off)
            self.assertGreater(sum(lit in on for lit in LITERALS), sum(lit in off for lit in LITERALS),
                               (on, off))
        finally:
            ChronicleCore._instances.pop(home, None)
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
