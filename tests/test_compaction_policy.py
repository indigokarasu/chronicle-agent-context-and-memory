"""
Chronicle — compaction follows the operator's compression settings.

The host never hands its compaction policy to a plugin engine ("External
engines own compaction policy -- the host threshold ... never reaches the
plugin", hermes-agent agent_init). Chronicle compacted at 75% of the window and
down to 55% whatever was configured; the production profile says `threshold:
0.5, target_ratio: 0.15, protect_first_n: 3, protect_last_n: 20`, which Hermes'
own compressor lands at ~10-15% of the window. A plugin that is to honour those
settings has to read them -- and has to re-read its own config once its core
exists, because the host calls update_model() before on_session_start().

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine
from engine.core import ChronicleCore

HOST = {"threshold": 0.5, "target_ratio": 0.15, "protect_first_n": 3, "protect_last_n": 20}


class _Engine(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="policy_")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def engine(self, host=None, config=None, update_first=True):
        eng = ChronicleContextEngine()
        eng._host_compression_cache = dict(host or {})
        if update_first:                      # the host's order: update_model, then start
            eng.update_model("fake-model", 200000)
        eng.on_session_start("s-policy", hermes_home=self.home, principal_id="pat",
                             config=config or {"embeddings": {"model": "hashing"}})
        if not update_first:
            eng.update_model("fake-model", 200000)
        return eng


class TestTheOperatorsSettings(_Engine):
    def test_without_a_host_the_defaults_stand(self):
        eng = self.engine()
        self.assertEqual((eng.high_watermark_percent, eng.low_watermark_percent), (0.75, 0.55))
        self.assertEqual((eng.protect_first_n, eng.protect_last_n), (3, 6))

    def test_the_host_threshold_and_target(self):
        eng = self.engine(HOST)
        self.assertEqual(eng.threshold_percent, 0.5)
        self.assertEqual(eng.threshold_tokens, 100000)
        self.assertAlmostEqual(eng.low_watermark_percent, 0.15)
        self.assertEqual(eng._target_budget(), 30000)
        self.assertEqual((eng.protect_first_n, eng.protect_last_n), (3, 20))
        self.assertTrue(eng.should_compress(100001))
        self.assertFalse(eng.should_compress(99999))

    def test_what_chronicle_is_told_wins(self):
        eng = self.engine(HOST, config={"embeddings": {"model": "hashing"},
                                        "context_engine": {"high_watermark_percent": 0.8,
                                                           "low_watermark_percent": 0.4}})
        self.assertEqual((eng.high_watermark_percent, eng.low_watermark_percent), (0.8, 0.4))

    def test_its_own_config_counts_even_when_the_model_came_first(self):
        """The host calls update_model() before on_session_start(); the core's
        config did not exist yet, and nothing re-read it."""
        eng = self.engine(config={"embeddings": {"model": "hashing"},
                                  "context_engine": {"high_watermark_percent": 0.6}})
        self.assertEqual(eng.threshold_tokens, 120000)

    def test_low_always_under_high(self):
        eng = self.engine({"threshold": 0.3, "target_ratio": 0.8})
        self.assertLess(eng.low_watermark_percent, eng.high_watermark_percent)

    def test_garbage_is_ignored(self):
        eng = self.engine({"threshold": "lots", "target_ratio": 7, "protect_last_n": -2})
        self.assertEqual((eng.high_watermark_percent, eng.low_watermark_percent), (0.75, 0.55))
        self.assertEqual(eng.protect_last_n, 6)


class TestTheMessageLimit(_Engine):
    """The gateway compacts at `hygiene_hard_message_limit` messages whatever
    the tokens, and when the compaction makes no progress it cuts the model's
    input to the newest `limit` messages -- head and all, no handoff. Chronicle,
    under its token budget, handed the transcript back unchanged."""

    LIMIT = dict(HOST, hygiene_hard_message_limit=60)

    def _chat(self, n):
        return [{"role": "system", "content": "sys"}] + [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": "short turn %d with Robin Placeholder" % i} for i in range(n)]

    def test_it_is_read(self):
        self.assertEqual(self.engine(self.LIMIT).max_messages, 60)
        self.assertIsNone(self.engine(HOST).max_messages)

    def test_over_the_limit_it_folds_down_to_half(self):
        eng = self.engine(self.LIMIT)
        msgs = self._chat(80)
        out = eng.compress(msgs)
        self.assertLessEqual(len(out), 30)
        self.assertEqual(out[-1], msgs[-1])
        self.assertTrue(any((m.get("content") or "").startswith("[CONTEXT COMPACTION") for m in out))

    def test_under_the_limit_nothing_changes(self):
        eng = self.engine(self.LIMIT)
        msgs = self._chat(50)
        self.assertEqual(eng.compress(msgs), msgs)

    def test_over_the_count_the_handoff_keeps_its_room(self):
        """Under the token budget but over the count: the recent turns that stay
        are large, and without the handoff's reserve they took all the room."""
        eng = self.engine(self.LIMIT)
        budget = eng._target_budget()
        msgs = self._chat(40)
        small = sum(eng._msg_cost(m) for m in msgs)
        per = (budget - small - 2000) // 22
        big = [{"role": "user" if i % 2 == 0 else "assistant",
                "content": "big turn %d " % i + "z" * (per * 3)} for i in range(22)]
        while sum(eng._msg_cost(x) for x in msgs + big) < budget - 60:   # to just under
            big[-1]["content"] += "z" * 8
        msgs += big
        total = sum(eng._msg_cost(m) for m in msgs)
        self.assertTrue(budget - 400 < total < budget, "setup: just under the token budget (%d)" % total)
        out = eng.compress(msgs)
        self.assertTrue(any((m.get("content") or "").startswith("[CONTEXT COMPACTION") for m in out))
        self.assertLessEqual(sum(eng._msg_cost(m) for m in out), budget)

    def test_a_long_settled_prefix_is_rebased_not_kept(self):
        eng = self.engine(self.LIMIT)
        out = eng.compress(self._chat(80))
        grown = out + self._chat(60)[1:]
        again = eng.compress(grown)
        self.assertLessEqual(len(again), 30)
        self.assertEqual(eng.last_pass, "rebase")


class TestReadingTheHost(unittest.TestCase):
    def test_outside_hermes_there_is_nothing_to_read(self):
        eng = ChronicleContextEngine()
        self.assertEqual(eng._host_compression(), {})

    def test_inside_hermes_it_reads_the_compression_section(self):
        import types
        from unittest import mock
        fake = types.ModuleType("hermes_cli.config")
        fake.load_config = lambda: {"compression": dict(HOST), "model": {"default": "x"}}
        pkg = types.ModuleType("hermes_cli")
        with mock.patch.dict(sys.modules, {"hermes_cli": pkg, "hermes_cli.config": fake}):
            eng = ChronicleContextEngine()
            self.assertEqual(eng._host_compression(), HOST)


if __name__ == "__main__":
    unittest.main()
