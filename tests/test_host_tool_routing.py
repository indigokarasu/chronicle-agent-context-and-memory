"""
Chronicle — every tool the model is offered can be called.

Hermes routes a memory provider's tools by the list it takes at
`add_provider()`, which runs BEFORE the provider's `initialize()`; the list
the MODEL sees is asked for again later. Chronicle answered the first call
with nothing (its tools lived on a core that did not exist yet), so the
production log read "Memory provider 'chronicle' registered (0 tools)" on
every start, and the model -- shown chronicle_search, chronicle_remember and
the rest -- got "Unknown tool" on all 77 calls it made between 2026-09-03 and
2026-09-17.

`HostMemoryManager` below is the routing half of Hermes' MemoryManager
(agent/memory_manager.py: add_provider, has_tool, handle_tool_call), in the
order the host calls it.

Fixtures use obviously fake values.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from provider import ChronicleMemoryProvider

CFG = {"embeddings": {"model": "hashing"}}
SID = "20260918_101010_aa11bb"


class HostMemoryManager:
    def __init__(self):
        self.route = {}

    def add_provider(self, provider):                  # snapshot, as the host does
        for schema in provider.get_tool_schemas():
            self.route.setdefault(schema["name"], provider)

    def has_tool(self, name):
        return name in self.route

    def handle_tool_call(self, name, args):
        provider = self.route.get(name)
        if provider is None:
            return json.dumps({"error": "Unknown tool: %s" % name})
        return provider.handle_tool_call(name, args)


class TestToolsRouteFromTheStart(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="toolroute_")
        self.prov = ChronicleMemoryProvider()
        self.host = HostMemoryManager()
        self.host.add_provider(self.prov)              # before initialize(), as in agent_init
        self.prov.initialize(SID, hermes_home=self.home, principal_id="default", config=CFG)

    def tearDown(self):
        ChronicleCore._instances.pop(self.prov.core.store.db_path, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def test_every_tool_the_model_sees_is_routable(self):
        offered = [s["name"] for s in self.prov.get_tool_schemas()]   # asked again, after init
        self.assertGreater(len(offered), 10)
        self.assertEqual([n for n in offered if not self.host.has_tool(n)], [])

    def test_the_schemas_do_not_change_across_initialize(self):
        before = ChronicleMemoryProvider().get_tool_schemas()
        self.assertEqual(before, self.prov.get_tool_schemas())

    def test_remember_then_search_through_the_host(self):
        out = json.loads(self.host.handle_tool_call(
            "chronicle_remember", {"kind": "note", "content": "The Zorblax filing is due on Fridays."}))
        self.assertNotIn("error", out)
        self.prov.core.process_pending()
        found = self.host.handle_tool_call("chronicle_search", {"query": "Zorblax filing"})
        self.assertNotIn("Unknown tool", found)
        self.assertIn("Zorblax", found)

    def test_search_finds_what_the_user_said(self):
        """The schema promises both tiers; beliefs alone missed everything a
        user only ever said."""
        self.prov.core.capture.observe("We moved the Zorblax standup to Thursdays at the Riverton office.",
                                       "Noted.", session_id=SID)
        self.prov.core.process_pending()
        found = json.loads(self.host.handle_tool_call("chronicle_search", {"query": "Zorblax standup"}))
        said = found.get("said") or []
        self.assertTrue(any("Thursdays" in s["excerpt"] for s in said), found)
        self.assertTrue(all(s["session_id"] == SID and s["when"] for s in said if "Thursdays" in s["excerpt"]))

    def test_a_call_before_initialize_says_so(self):
        early = ChronicleMemoryProvider()
        self.assertIn("not initialized", early.handle_tool_call("chronicle_search", {"query": "x"}))


if __name__ == "__main__":
    unittest.main()
