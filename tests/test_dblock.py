"""Chronicle — a locked store may never cost the user their turn.

Chronicle's store is shared: the gateway writes to it and so do the cron
workers. A write inside compress() can therefore lose the race for the SQLite
lock, and on 2026-09-22 18:55:26 one did, inside the rescue side-write. Nothing
caught it, so `sqlite3.OperationalError: database is locked` left compress(),
passed through the conversation loop's preflight gate and reached the gateway's
generic handler, which replaced the assistant's reply with "Something went
wrong and I couldn't finish this reply."

compress() reaches four store writes, each its own way to lose a turn:

  rescue          a best-effort durability copy that does not even run when a
                  memory provider is live -> swallow it, keep compacting.
  the fold loop   what makes an evicted span durable (I17). A compressed window
                  here would drop messages with nothing to restore them from,
                  so abandon the pass and hand back the window untouched.
  _mark_clipped   archives a span before shortening it, reached through
                  _fit_required.
  the audit event observational, written after the window is decided.

The first three degrade on their own terms; `compress` itself is the net under
everything else, falling back to the storeless heuristic the engine already
uses when the core cannot be opened. The file already states the rule for its
digest write -- "a digest may never break a compaction" -- and these hold the
rest of compress() to it.
"""

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine
from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}}

LOCKED = sqlite3.OperationalError("database is locked")


def _boom(*a, **k):
    raise LOCKED


def _conversation(n):
    return ([{"role": "system", "content": "You are helping Pat Testley."}]
            + [{"role": "user" if i % 2 == 0 else "assistant",
                "content": ("Acme Fake Co turn %d: you must never ship on a Friday, and the "
                            "filler here is padded out to cost real tokens under the hashing "
                            "embedder so eviction actually has work to do." % i)}
               for i in range(n)])


class LockedStoreDoesNotFailTheTurn(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="ce_dblock_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("dblock-s1", hermes_home=self.home,
                                  principal_id="pat", config=CFG)
        self.eng.update_model("test-model", context_length=2000)
        # The production failure happened with no provider live -- its own init
        # had lost the same lock -- which is exactly when rescue runs at all.
        self.assertFalse(self.eng._provider_captures(),
                         "fixture must reproduce the standalone case")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_a_locked_rescue_write_still_returns_a_window(self):
        convo = _conversation(80)
        self.eng.core.capture.rescue = _boom
        out = self.eng.compress(convo)              # must not raise
        self.assertIsInstance(out, list)
        self.assertTrue(out, "compaction returned an empty window")
        # rescue is a side-write: the pass still did its job.
        self.assertLess(len(out), len(convo), "compaction did not compact")

    def test_a_locked_fold_abandons_the_pass_instead_of_evicting(self):
        convo = _conversation(80)
        asks, steps = len(self.eng._handoff_asks), len(self.eng._handoff_steps)
        # Isolate the fold loop. rescue() and _mark_clipped() write through the
        # same store and both run earlier in the pass, so leaving either live
        # fails this test several frames too early and proves nothing about the
        # loop. _ensure_durable IS the loop's durable write.
        self.eng.core.capture.rescue = lambda *a, **k: ([], "")
        self.eng._mark_clipped = lambda orig, clipped: clipped
        self.eng._ensure_durable = _boom
        out = self.eng.compress(convo)              # must not raise
        # Nothing was made durable, so nothing may be evicted: the caller gets
        # its own list back, not a shortened one.
        self.assertIs(out, convo)
        # ...and the handoff must not carry lines for units that never folded.
        self.assertEqual(len(self.eng._handoff_asks), asks)
        self.assertEqual(len(self.eng._handoff_steps), steps)

    def test_a_locked_clip_archive_still_returns_a_window(self):
        """compress -> _fit_required -> _mark_clipped: the fourth write."""
        convo = _conversation(80)
        self.eng.core.capture.rescue = lambda *a, **k: ([], "")
        self.eng._ensure_durable = _boom            # breaks _mark_clipped first
        out = self.eng.compress(convo)              # must not raise
        self.assertIsInstance(out, list)
        self.assertTrue(out, "compaction returned an empty window")

    def test_a_locked_audit_write_still_returns_a_window(self):
        convo = _conversation(80)
        real = self.eng.core.capture.append

        def only_the_audit_row(type_, *a, **k):
            if type_ == "compressed":
                raise LOCKED
            return real(type_, *a, **k)

        self.eng.core.capture.append = only_the_audit_row
        out = self.eng.compress(convo)              # must not raise
        self.assertIsInstance(out, list)
        self.assertTrue(out, "compaction returned an empty window")
        self.assertLess(len(out), len(convo), "compaction did not compact")

    def test_anything_else_degrades_to_the_storeless_heuristic(self):
        """The net: whatever else the store does, the host still gets a window."""
        convo = _conversation(80)
        self.eng._compress_with_store = _boom
        out = self.eng.compress(convo)              # must not raise
        self.assertIsInstance(out, list)
        self.assertLess(len(out), len(convo),
                        "heuristic fallback returned an uncompacted window")


if __name__ == "__main__":
    unittest.main(verbosity=2)
