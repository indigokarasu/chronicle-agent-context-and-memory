"""
Chronicle — the context engine survives the host's per-agent copy.

The host (hermes-agent agent_init._select_context_engine) gives every agent its
OWN `copy.deepcopy()` of the registered context engine, so that a child's
update_model() cannot move the parent's token budget. When the copy raises, the
host falls back to its built-in compressor for that agent and logs one warning.

A plain deepcopy of this engine raised — "cannot pickle '_thread.lock' object",
from `_retry_lock` — so on a production gateway Chronicle was configured as the
context engine and never once compressed a conversation: 38 fallbacks in one
day. The built-in compressor it fell back to was pointed at a provider with no
API key, so the user saw "Shortening the conversation history failed" instead.

The copy must SHARE the core (the process-wide ChronicleCore singleton with the
store, its connections and the vector index — duplicating that per agent is the
shape of the leak that last grew the gateway by ~850 MB/min) and OWN everything
else. Both halves are pinned here, plus the exact statement the host runs.
"""

import copy
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine
from engine.core import ChronicleCore

CFG = {"embeddings": {"model": "hashing"}}  # offline, deterministic


class TestACopyIsPossible(unittest.TestCase):
    def test_a_fresh_engine_copies(self):
        copy.deepcopy(ChronicleContextEngine())

    def test_the_hosts_own_statement_succeeds(self):
        """What agent_init does, verbatim in effect: deepcopy the shared
        candidate, and fall back to the built-in compressor only on an
        exception. There must be no exception."""
        candidate = ChronicleContextEngine()
        try:
            selected = copy.deepcopy(candidate)
        except Exception as e:           # this is the host's fallback trigger
            self.fail("the host would fall back to its built-in compressor: %s" % e)
        self.assertEqual(selected.name, "chronicle")


class TestACopyOfALiveEngine(unittest.TestCase):
    """The copy that matters is of an engine with a real core attached — that is
    what the gateway's registered singleton is after its first session."""

    def setUp(self):
        self.home = temp_home(prefix="ce_copy_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("copy-s1", hermes_home=self.home, principal_id="pat",
                                  config=CFG)
        self.assertIsNotNone(self.eng.core, "expected the real engine, not the heuristic one")

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_it_copies(self):
        copy.deepcopy(self.eng)

    def test_the_core_is_shared_not_duplicated(self):
        twin = copy.deepcopy(self.eng)
        self.assertIs(twin.core, self.eng.core,
                      "a copied core duplicates the store and vector index per agent")
        self.assertIs(twin.core.store, self.eng.core.store)

    def test_each_copy_owns_its_own_lock(self):
        twin = copy.deepcopy(self.eng)
        self.assertIsNot(twin._retry_lock, self.eng._retry_lock)
        with twin._retry_lock:           # usable, and independent of the original
            self.assertTrue(self.eng._retry_lock.acquire(blocking=False))
            self.eng._retry_lock.release()

    def test_the_budget_is_the_copys_own(self):
        """The reason the host copies at all: a child's budget must not move
        the parent's."""
        twin = copy.deepcopy(self.eng)
        twin.update_model("child-model", context_length=4000)
        twin.last_prompt_tokens = 1234
        twin._locked_prefix.append({"role": "user", "content": "the child's turn"})
        twin._pinned_content_hashes.add("child")
        self.assertNotEqual(self.eng.context_length, 4000)
        self.assertEqual(self.eng.last_prompt_tokens, 0)
        self.assertEqual(self.eng._locked_prefix, [])
        self.assertNotIn("child", self.eng._pinned_content_hashes)

    def test_a_copy_can_compress(self):
        """A copy is only worth having if it does the job: the real engine,
        not the heuristic fallback, on the shared core."""
        twin = copy.deepcopy(self.eng)
        twin.update_model("test-model", context_length=1500)
        messages = ([{"role": "system", "content": "You are helping Pat Testley."}]
                    + [{"role": "user" if i % 2 == 0 else "assistant",
                        "content": ("Acme Fake Co turn %d: unrelated filler padded out to cost "
                                    "real tokens under the hashing embedder so eviction "
                                    "actually has work to do." % i)}
                       for i in range(80)])
        out = twin.compress(messages)
        self.assertIsInstance(out, list)
        self.assertLess(len(out), len(messages), "a copy that cannot evict is not an engine")
        self.assertIsNotNone(twin.core)

    def test_many_agents_share_one_core(self):
        """Ten agents, one core — never ten."""
        twins = [copy.deepcopy(self.eng) for _ in range(10)]
        self.assertEqual({id(t.core) for t in twins}, {id(self.eng.core)})


class TestAResetForgetsTheOldConversation(unittest.TestCase):
    """`/new` and `/reset` call on_session_reset. The host's default only zeroes
    the token counters; this engine also holds per-conversation state, and all
    of it describes messages the user just discarded."""

    def setUp(self):
        self.home = temp_home(prefix="ce_reset_")
        self.eng = ChronicleContextEngine()
        self.eng.on_session_start("reset-s1", hermes_home=self.home, principal_id="pat",
                                  config=CFG)

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _dirty(self):
        e = self.eng
        e.last_prompt_tokens, e.compression_count = 900, 3
        e._locked_prefix = [{"role": "user", "content": "the old conversation"}]
        e._checkpoint_lines = ["- folded: the old conversation"]
        e._pinned_content_hashes = {"old-pin"}
        e._pressure_warning_injected = True
        e.focus = {"topics": ["the old topic"], "entities": [], "task": ""}
        e.focus_topic = "the old topic"

    def test_every_piece_of_the_old_conversation_is_gone(self):
        self._dirty()
        self.eng.on_session_reset()
        e = self.eng
        self.assertEqual(e._locked_prefix, [], "the new conversation would be cut against the old prefix")
        self.assertEqual(e._checkpoint_lines, [])
        self.assertEqual(e._pinned_content_hashes, set())
        self.assertFalse(e._pressure_warning_injected)
        self.assertIsNone(e.focus)
        self.assertIsNone(e.focus_topic)

    def test_it_chains_to_the_hosts_counter_reset(self):
        self._dirty()
        self.eng.on_session_reset()
        self.assertEqual(self.eng.last_prompt_tokens, 0)   # 0, not -1: "no real usage yet"
        self.assertEqual(self.eng.compression_count, 0)

    def test_the_store_survives_a_reset(self):
        core = self.eng.core
        self.eng.on_session_reset()
        self.assertIs(self.eng.core, core, "a reset clears conversation state, not the store")


if __name__ == "__main__":
    unittest.main()
