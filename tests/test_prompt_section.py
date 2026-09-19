"""
Chronicle — one copy of the static block in the system prompt, under one rule.

The plugin also registers a system-prompt section ("chronicle.memory-guidelines")
that renders the static block. Hermes renders it AND puts the memory provider's
own `system_prompt_block()` into the prompt, so with Chronicle as the memory
provider the block went in twice -- and the section's copy did not leave out
the agent's own notes (the host injects its current memory file itself):
612 characters of stale copies in every production system prompt, one cut off
mid-sentence, after 5.8.16 had removed them from the provider's copy.

Fixtures use obviously fake values.
"""

import importlib.util
import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore

ROOT = Path(__file__).parent.parent
P = "default"


def _plugin():
    spec = importlib.util.spec_from_file_location("chronicle_plugin_under_test", ROOT / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeCtx:
    def __init__(self):
        self.sections = {}

    def register_system_prompt_section(self, sid, factory, **_kw):
        self.sections[sid] = factory


def _host(memory):
    fake = types.ModuleType("hermes_cli.config")
    fake.load_config = lambda: {"memory": memory}
    return mock.patch.dict(sys.modules, {"hermes_cli": types.ModuleType("hermes_cli"), "hermes_cli.config": fake})


class TestTheSection(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="section_")
        self.core = ChronicleCore.get(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("s-section", principal_id=P)
        for body, source, actor, event in (
                ("Always sign Zorblax reports as the assistant.", "agent_memory_write", "agent", "tool"),
                ("Never book the Izakaya Nonesuch without asking me.", "user_direct", "user", "turn")):
            self.core.capture.append("asserted", {
                "kind": "note", "key": {"note_type": "norm", "subject": "directive"}, "body": body,
                "confidence": 0.9, "source_event": event, "source_type": source}, actor=actor, trust_level=3)
        self.core.process_pending()
        ctx = FakeCtx()
        _plugin().register(ctx)
        self.section = ctx.sections["chronicle.memory-guidelines"]

    def tearDown(self):
        ChronicleCore._instances.pop(self.home, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def render(self, memory=None):
        with mock.patch.object(ChronicleCore, "active", return_value=self.core):
            if memory is None:
                return self.section({"principal_id": P})
            with _host(memory):
                return self.section({"principal_id": P})

    def test_nothing_when_the_provider_already_carries_it(self):
        self.assertEqual(self.render({"provider": "chronicle", "memory_enabled": True}), "")

    def test_context_engine_only_leaves_out_what_the_host_injects(self):
        out = self.render({"provider": "someone_else", "memory_enabled": True})
        self.assertIn("Izakaya Nonesuch", out)
        self.assertNotIn("Zorblax reports", out)

    def test_outside_hermes_it_is_the_only_copy(self):
        out = self.render()
        self.assertIn("Izakaya Nonesuch", out)
        self.assertIn("Zorblax reports", out)


if __name__ == "__main__":
    unittest.main()
