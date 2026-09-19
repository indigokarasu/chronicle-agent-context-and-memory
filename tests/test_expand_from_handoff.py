"""
Chronicle — the handoff's own instruction works.

Every compaction note says "chronicle_expand(span_id) restores a folded turn
by its [fold_…] id". Taken literally, through the host's call shape
(`handle_tool_call(name, args, messages=…)`), with the id as the note shows it
-- brackets included -- or bare, the folded turn comes back. The tool's
description names the same id format the note shows (it used to point at a
"[FOLD" stub that no longer exists).

Fixtures use obviously fake values.
"""

import json
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine
from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}, "curation": {"drain": {"per_turn": 0, "background": False}}}


class TestExpandWhatTheHandoffNames(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="expand_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("s-expand", hermes_home=self.home, principal_id="pat", config=CFG)
        self.eng.update_model("fake-model", 4000)
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(40):
            msgs.append({"role": "user", "content": "turn %d: reconcile the Zorblax ledger for Pat Testley %s"
                         % (i, "detail " * 40)})
            msgs.append({"role": "assistant", "content": "done %d for Acme Fake Co %s" % (i, "note " * 40)})
        self.msgs = msgs
        self.out = self.eng.compress(list(msgs))
        hand = [m for m in self.out if str(m.get("content") or "").startswith("[CONTEXT COMPACTION")]
        self.assertEqual(len(hand), 1, "setup: one handoff")
        self.ids = re.findall(r"\[(fold_[0-9a-f]{12})\]", hand[0]["content"])
        self.assertTrue(self.ids, "setup: the handoff names folded turns")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def expand(self, span_id):
        return json.loads(self.eng.handle_tool_call("chronicle_expand", {"span_id": span_id},
                                                    messages=self.out))

    def test_the_id_as_the_note_shows_it(self):
        got = self.expand("[%s]" % self.ids[0])
        self.assertNotIn("error", got, got)
        self.assertIn("Zorblax", got["content"])

    def test_the_bare_id(self):
        self.assertNotIn("error", self.expand(self.ids[0]))

    def test_an_unknown_id_says_so(self):
        self.assertIn("error", self.expand("fold_000000000000"))

    def test_the_description_names_the_format_the_note_uses(self):
        desc = next(s["description"] for s in self.eng.get_tool_schemas() if s["name"] == "chronicle_expand")
        self.assertIn("[fold_", desc)
        self.assertNotIn("[FOLD", desc)


if __name__ == "__main__":
    unittest.main()
