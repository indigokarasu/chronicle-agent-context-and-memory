"""
Chronicle — a skill-selection hint on the per-turn prefetch path (J1).

An external skill-selection router (see `ops/reference/` for the one this
integrates with -- read-only material, never imported by tests) can name the
one skill in the agent's roster most likely to help with the user's message.
Nothing called it automatically before this: `engine/suggest.py` now does, from
`provider.prefetch`, entirely opt-in (`suggest.enabled`, default False) and
fail-open. A disabled or unconfigured router, one that raises, or one that
simply takes too long must never add unbounded latency to a turn or break the
rest of prefetch's return.

Router modules here are plain stub `.py` files written to a temp directory for
each test -- never a path into `ops/reference/`, which is read-only reference
material the brief explicitly says not to deploy or import by path.

Fixtures use obviously fake values.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.config import Config
from engine.suggest import suggest
from provider import ChronicleMemoryProvider

CFG_EMB = {"embeddings": {"model": "hashing"}}

FIXED_ANSWER_ROUTER = """
def rank_wide(request, roster, timeout=60):
    return {"ranked": [("demo-skill", 0.91)], "gate": 1.0, "values": {}}
"""

SLOW_ROUTER = """
import time

def rank_wide(request, roster, timeout=60):
    time.sleep(2)
    return {"ranked": [("too-late", 0.91)]}
"""

RAISING_ROUTER = """
def rank_wide(request, roster, timeout=60):
    raise RuntimeError("router exploded")
"""


def _write_router(body: str, name: str = "router.py") -> str:
    d = temp_home(prefix="j1-router-")
    path = Path(d) / name
    path.write_text(body)
    return str(path)


class TestSuggestStandalone(unittest.TestCase):
    """`engine.suggest.suggest(query, cfg)` against the three stub shapes the
    brief specifies: a fixed answer, one that sleeps past the budget, one
    that raises. No network is touched (the suite's socket guard would fail
    the test if it were)."""

    def test_a_fixed_answer_router_yields_its_name(self):
        path = _write_router(FIXED_ANSWER_ROUTER)
        cfg = Config({"suggest": {"enabled": True, "module_path": path, "budget_ms": 800}})
        self.assertEqual(suggest("help me write a test", cfg), ["demo-skill"])

    def test_a_router_past_budget_yields_nothing_and_returns_promptly(self):
        path = _write_router(SLOW_ROUTER)
        cfg = Config({"suggest": {"enabled": True, "module_path": path, "budget_ms": 100}})
        started = time.monotonic()
        self.assertEqual(suggest("help me write a test", cfg), [])
        # The join must return at (approximately) the 100ms budget, never wait
        # out the router's own 2s sleep -- the whole point of the worker
        # thread + join(timeout) design instead of a plain call.
        self.assertLess(time.monotonic() - started, 1.5)

    def test_a_raising_router_yields_nothing(self):
        path = _write_router(RAISING_ROUTER)
        cfg = Config({"suggest": {"enabled": True, "module_path": path, "budget_ms": 800}})
        self.assertEqual(suggest("help me write a test", cfg), [])

    def test_disabled_yields_nothing_even_with_a_working_router(self):
        path = _write_router(FIXED_ANSWER_ROUTER)
        cfg = Config({"suggest": {"enabled": False, "module_path": path, "budget_ms": 800}})
        self.assertEqual(suggest("help me write a test", cfg), [])

    def test_no_module_path_yields_nothing_even_when_enabled(self):
        cfg = Config({"suggest": {"enabled": True, "module_path": "", "budget_ms": 800}})
        self.assertEqual(suggest("help me write a test", cfg), [])


class TestProviderPrefetchSkillSuggestion(unittest.TestCase):
    """The integration in `provider.prefetch`: a line prepended only when the
    router names something, the session is not automation's own, and the
    feature is enabled -- otherwise prefetch's existing behaviour is
    unchanged."""

    def _provider(self, session_id, suggest_cfg=None, extra_cfg=None):
        cfg = dict(CFG_EMB)
        if suggest_cfg is not None:
            cfg["suggest"] = suggest_cfg
        if extra_cfg:
            cfg.update(extra_cfg)
        prov = ChronicleMemoryProvider()
        prov.initialize(session_id, hermes_home=temp_home(prefix="j1-home-"),
                        principal_id="default", config=cfg)
        return prov

    def test_enabled_router_prepends_one_line_for_an_interactive_turn(self):
        path = _write_router(FIXED_ANSWER_ROUTER)
        prov = self._provider("20260918_120000_aa11bb",
                              {"enabled": True, "module_path": path, "budget_ms": 800})
        with self.assertLogs("chronicle.provider", level="INFO") as log:
            text = prov.prefetch("what should I use to write a test?")
        self.assertTrue(text.startswith("[SKILL SUGGESTION] consider: demo-skill"))
        # Logged with the session id so use can be scored later (J1 brief).
        joined = "\n".join(log.output)
        self.assertIn("demo-skill", joined)
        self.assertIn("20260918_120000_aa11bb", joined)

    def test_a_raising_router_leaves_prefetch_unchanged(self):
        path = _write_router(RAISING_ROUTER)
        prov = self._provider("20260918_130000_cc22dd",
                              {"enabled": True, "module_path": path, "budget_ms": 800})
        text = prov.prefetch("what should I use to write a test?")
        self.assertNotIn("[SKILL SUGGESTION]", text)

    def test_disabled_gets_no_suggestion(self):
        path = _write_router(FIXED_ANSWER_ROUTER)
        prov = self._provider("20260918_140000_ee33ff",
                              {"enabled": False, "module_path": path, "budget_ms": 800})
        text = prov.prefetch("what should I use to write a test?")
        self.assertNotIn("[SKILL SUGGESTION]", text)

    def test_automation_session_gets_no_suggestion_even_when_recall_runs(self):
        # `retrieval.prefetch_automation: True` so prefetch does not merely
        # short-circuit to "" for the UNRELATED reason of skipping recall for
        # automation turns -- this isolates the suggestion gate itself.
        path = _write_router(FIXED_ANSWER_ROUTER)
        prov = self._provider("cron_20260918_150000_aa11bb",
                              {"enabled": True, "module_path": path, "budget_ms": 800},
                              extra_cfg={"retrieval": {"prefetch_automation": True}})
        text = prov.prefetch("what should I use to write a test?")
        self.assertNotIn("[SKILL SUGGESTION]", text)


if __name__ == "__main__":
    unittest.main()
