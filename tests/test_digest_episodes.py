"""
Chronicle — a folded unit can leave a distilled episode behind.

Recall returns raw turns. Asked about a piece of work it returns several of
them, each a fragment of it, because nothing in the store stands for the whole
span. The compaction already writes that unit: one line per folded unit saying
what was called and what came back. Behind `context_engine.digest_episodes`
(default off) that line is also kept as an episode, so a later recall can rank
one distilled unit instead of the turns it stands for.

Two things it is careful about, both learned:

* only a STEP becomes one. 5.8.1 removed digest episodes because the
  checkpoint digest's lines were the user's own requests restated, and the
  handoff quotes every folded request verbatim already.
* these describe the AGENT's work, not the user's life, so per-turn recall
  never injects them unasked -- the rule that removed ~4,800 characters of
  unasked memory from every turn. Explicit search and the engine's own
  rehydration still see them.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

import context as context_mod
from context import ChronicleContextEngine
from engine.core import ChronicleCore
from provider import ChronicleMemoryProvider

CFG = {"embeddings": {"model": "hashing"}, "curation": {"drain": {"per_turn": 0, "background": False}}}
SID = "20260918_120000_dig111"


def _session(turns):
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        msgs.append({"role": "user", "content": "turn %d: check the Zorblax ledger for Riverton %s"
                     % (i, "detail " * 30)})
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": "c%d" % i, "type": "function",
             "function": {"name": "terminal", "arguments": '{"command": "docker ps --filter name=zorblax"}'}}]})
        msgs.append({"role": "tool", "tool_call_id": "c%d" % i,
                     "content": "zorblax Up 3 days (healthy) on port 8688 %s" % ("row " * 40)})
        msgs.append({"role": "assistant", "content": "ledger %d reconciled for Acme Fake Co %s"
                     % (i, "note " * 30)})
    return msgs


class TestWritingThem(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="digest_")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def engine(self, on, sid=SID):
        eng = ChronicleContextEngine()
        eng.on_session_start(sid, hermes_home=self.home, principal_id="default",
                             config=dict(CFG, context_engine={"digest_episodes": on}))
        eng.update_model("fake-model", 4000)
        return eng

    def episodes(self, core):
        core.process_pending()
        return [r[0] for r in core.store._conn().execute(
            "SELECT summary FROM episodes WHERE status='active' AND "
            "json_extract(provenance,'$.source_type')='compaction_digest'")]

    def rows(self, core):
        core.process_pending()
        return [(r[0], r[1] or "") for r in core.store._conn().execute(
            "SELECT title, session_ref FROM episodes WHERE status='active' AND "
            "json_extract(provenance,'$.source_type')='compaction_digest'")]

    def test_off_by_default_nothing_is_written(self):
        eng = self.engine(False)
        eng.compress(_session(30))
        self.assertEqual(self.episodes(eng.core), [])

    def test_on_each_folded_step_leaves_one(self):
        eng = self.engine(True)
        eng.compress(_session(30))
        eps = self.episodes(eng.core)
        self.assertTrue(eps, "a compaction that folded steps wrote none")
        self.assertTrue(any("terminal(" in e or "called" in e for e in eps), eps[:3])

    def test_a_folded_request_does_not_become_one(self):
        """5.8.1: the handoff quotes every folded request already."""
        eng = self.engine(True)
        eng.compress(_session(30))
        for e in self.episodes(eng.core):
            self.assertNotIn("check the Zorblax ledger for Riverton", e)

    def test_a_pass_writes_at_most_the_cap(self):
        eng = self.engine(True)
        eng.compress(_session(120))
        self.assertLessEqual(len(self.episodes(eng.core)), context_mod._DIGEST_EPISODE_CAP)

    def test_the_cap_is_per_pass_not_per_session(self):
        """Each pass starts the count again, so a long conversation is not
        capped at 40 distilled episodes for its whole life."""
        eng = self.engine(True)
        eng.compress(_session(30))
        self.assertGreater(eng._digests_written, 0)
        wrote = eng._digests_written
        eng.compress(_session(30))
        self.assertLessEqual(eng._digests_written, wrote,
                             "the counter did not reset: it kept climbing across passes")

    def test_it_records_which_session_it_distilled(self):
        """Half an episode's natural key, and the column the recall half needs
        to prefer one distilled unit over that session's raw excerpts."""
        eng = self.engine(True)
        eng.compress(_session(30))
        rows = self.rows(eng.core)
        self.assertTrue(rows)
        self.assertEqual({sref for _t, sref in rows}, {SID})

    def test_two_sessions_folding_the_same_work_are_two_episodes(self):
        """Identical work in two conversations is two spans, not one. With the
        session out of the key they collide on title and one of them wins."""
        a = self.engine(True)
        a.compress(_session(30))
        other = "20260918_130000_dig222"
        b = self.engine(True, sid=other)
        b.compress(_session(30))
        by_title: dict = {}
        for title, sref in self.rows(b.core):
            by_title.setdefault(title, set()).add(sref)
        shared = [t for t, srefs in by_title.items() if srefs == {SID, other}]
        self.assertTrue(shared, sorted(by_title.items())[:3])

    def test_the_same_step_twice_is_one_episode(self):
        """A pass that folds the same work again confirms it; it does not
        write a second copy."""
        eng = self.engine(True)
        eng.compress(_session(30))
        first = self.episodes(eng.core)
        eng.compress(_session(30))
        self.assertEqual(sorted(self.episodes(eng.core)), sorted(first))


class TestReadingThem(unittest.TestCase):
    """They answer "what was done", not "what is this message about"."""

    def setUp(self):
        self.home = temp_home(prefix="digestread_")
        self.prov = ChronicleMemoryProvider()
        self.prov.initialize("20260919_090000_ff11aa", hermes_home=self.home, principal_id="default",
                             config=CFG)
        core = self.prov.core
        core.capture.append("asserted", {
            "kind": "episode", "key": {"title": "called terminal(docker ps) on the Zorblax box"},
            "body": "called terminal(docker ps --filter name=zorblax) → zorblax Up 3 days on port 8688",
            "confidence": 0.9, "source_event": "fold_ab12cd34ef56", "source_type": "compaction_digest",
            "session_ref": SID}, actor="agent", owner="default", trust_level=3)
        core.capture.observe("The Zorblax box needs a docker restart on Friday.", "Noted.",
                             session_id="20260910_101010_bb22cc")
        core.process_pending()

    def tearDown(self):
        ChronicleCore._instances.pop(self.prov.core.store.db_path, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_per_turn_recall_never_injects_one(self):
        out = self.prov.prefetch("what is happening with the Zorblax box docker container?")
        self.assertNotIn("called terminal", out)
        self.assertIn("needs a docker restart", out)      # the user's own words still do

    def test_explicit_search_finds_it(self):
        out = self.prov.core.retrieval.get_context("zorblax docker", token_budget=1200,
                                                   principal="default")
        self.assertIn("called terminal", out)


if __name__ == "__main__":
    unittest.main()
