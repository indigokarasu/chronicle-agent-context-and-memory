import tempfile
import unittest
from engine.core import ChronicleCore
from context import ChronicleContextEngine


class TestDiagnosticsAndEnhancements(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.core = ChronicleCore.get(self.tmp_dir.name)
        self.core.initialize("test_session", principal_id="test_principal")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_core_diagnostics(self):
        diag = self.core.diagnostics()
        self.assertIn("active_principal", diag)
        self.assertEqual(diag["active_principal"], "test_principal")
        self.assertIn("database", diag)
        self.assertIn("events_count", diag["database"])
        self.assertIn("active_beliefs_count", diag["database"])
        self.assertIn("pending_curation_jobs", diag["database"])
        self.assertIn("vector_index", diag)
        self.assertIn("embedding", diag)

    def test_tool_diagnostics(self):
        res_raw = self.core.tools.dispatch("test_principal", "chronicle_diagnostics", {})
        import json
        res = json.loads(res_raw)
        self.assertIn("active_principal", res)
        self.assertIn("database", res)

    def test_tool_schemas_includes_diagnostics(self):
        schemas = self.core.tools.schemas()
        names = [s["name"] for s in schemas]
        self.assertIn("chronicle_diagnostics", names)

    def test_context_engine_status_includes_diagnostics(self):
        ce = ChronicleContextEngine()
        ce.on_session_start("test_session", hermes_home=self.tmp_dir.name)
        st = ce.context_status()
        self.assertEqual(st["mode"], "memory_aware")
        self.assertIn("diagnostics", st)
        self.assertIn("database", st["diagnostics"])


if __name__ == "__main__":
    unittest.main()
