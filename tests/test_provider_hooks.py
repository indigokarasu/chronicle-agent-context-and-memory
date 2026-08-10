"""
Chronicle — tests for provider.py's gateway hooks (issue #7):

  1. post_tool_call: allowlisted retrieval-ish tool results -> reference-kind
     beliefs through the normal assert path (topic, retrieval_url,
     cached_summary, ttl_days), with an operational guard against run-log noise.
  2. subagent_stop: richer delegation episode capture (status + duration as
     qualifiers, tool names summarized) layered on top of on_delegation.

Also covers the small, purely-additive engine/reducer.py wiring these hooks
depend on: retrieval_url / retrieved_at / stale_after on the "reference" kind
(previously declared in the refs table schema but never populated).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from provider import (
    ChronicleMemoryProvider,
    _looks_operational,
    _summarize_tool_history,
    _tool_result_text,
)


# ---------------------------------------------------------------------------
# Pure helper functions — no store, no core.
# ---------------------------------------------------------------------------
class TestToolResultText(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_tool_result_text(None), "")

    def test_plain_string(self):
        self.assertEqual(_tool_result_text("  hello  "), "hello")

    def test_dict_prefers_text_field(self):
        self.assertEqual(_tool_result_text({"text": "hi", "other": "x"}), "hi")

    def test_dict_falls_back_to_content(self):
        self.assertEqual(_tool_result_text({"content": "body here"}), "body here")

    def test_dict_with_no_known_field_serializes(self):
        out = _tool_result_text({"weird": "shape"})
        self.assertIn("weird", out)

    def test_list_joins_pieces(self):
        out = _tool_result_text(["a", "b"])
        self.assertEqual(out, "a\nb")

    def test_number_stringifies(self):
        self.assertEqual(_tool_result_text(42), "42")


class TestLooksOperational(unittest.TestCase):
    def test_tool_prefix_is_operational(self):
        self.assertTrue(_looks_operational("tool: some raw dump"))

    def test_run_id_marker_is_operational(self):
        self.assertTrue(_looks_operational('{"run_id": "abc123", "ok": true}'))

    def test_schema_marker_is_operational(self):
        self.assertTrue(_looks_operational('{"schema": "v1"}'))

    def test_ordinary_prose_is_not_operational(self):
        self.assertFalse(_looks_operational("Acme Fake Co is a widget maker founded in 2019."))

    def test_empty_is_not_operational(self):
        self.assertFalse(_looks_operational(""))


class TestSummarizeToolHistory(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_summarize_tool_history(None), "")
        self.assertEqual(_summarize_tool_history([]), "")

    def test_counts_repeats(self):
        out = _summarize_tool_history([{"tool": "read_file"}, {"tool": "read_file"}, {"tool": "web_search"}])
        self.assertIn("read_file×2", out)
        self.assertIn("web_search", out)
        self.assertNotIn("web_search×", out)  # singleton: no ×1 suffix

    def test_accepts_bare_strings(self):
        out = _summarize_tool_history(["fetch", "fetch"])
        self.assertIn("fetch×2", out)

    def test_unknown_shape_falls_back_to_placeholder(self):
        out = _summarize_tool_history([{"nope": "no name key"}])
        self.assertIn("?", out)


# ---------------------------------------------------------------------------
# post_tool_call -> reference-kind beliefs
# ---------------------------------------------------------------------------
class TestPostToolCallReferenceCapture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.provider = ChronicleMemoryProvider()
        self.provider.initialize("s1", hermes_home=self.home, principal_id="assistant",
                                 config={"embeddings": {"model": "hashing"}})

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _refs(self):
        return self.provider.core.store.query_beliefs("refs", "1=1", (), 50)

    def test_allowlisted_web_fetch_writes_reference_belief(self):
        self.provider.post_tool_call(
            "web_fetch",
            {"url": "https://example.test/acme", "query": "Acme Fake Co overview"},
            "Acme Fake Co is a fictional company used in Chronicle's fixtures.")
        rows = self._refs()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["topic"], "Acme Fake Co overview")
        self.assertEqual(row["retrieval_url"], "https://example.test/acme")
        self.assertEqual(row["cached_summary"],
                         "Acme Fake Co is a fictional company used in Chronicle's fixtures.")
        self.assertEqual(row["ttl_days"], 30)
        self.assertTrue(row["retrieved_at"])
        self.assertTrue(row["stale_after"])
        self.assertGreater(row["stale_after"], row["retrieved_at"])  # 30 days out, string-orderable
        self.assertEqual(row["owner"], "assistant")
        self.assertAlmostEqual(row["confidence"], 0.40, places=2)  # base_confidence("web_retrieval")

    def test_case_insensitive_tool_name_match(self):
        self.provider.post_tool_call("WebFetch", {"url": "https://example.test/x", "query": "q"}, "content body")
        self.assertEqual(len(self._refs()), 1)

    def test_unlisted_tool_not_captured(self):
        self.provider.post_tool_call("run_shell_command", {"cmd": "ls"}, "file1\nfile2")
        self.assertEqual(self._refs(), [])

    def test_chronicles_own_tool_never_captured_even_if_allowlisted(self):
        # Explicit guard must win even when an operator misconfigures the allowlist.
        home2 = tempfile.mkdtemp()
        try:
            p2 = ChronicleMemoryProvider()
            p2.initialize("s1", hermes_home=home2, principal_id="assistant",
                          config={"embeddings": {"model": "hashing"},
                                  "capture": {"tool_reference": {"allowlist": ["chronicle_search", "web_fetch"]}}})
            p2.post_tool_call("chronicle_search", {"query": "x"}, "some result text")
            self.assertEqual(p2.core.store.query_beliefs("refs", "1=1", (), 50), [])
        finally:
            shutil.rmtree(home2, ignore_errors=True)

    def test_failed_call_not_captured_via_error_kwarg(self):
        self.provider.post_tool_call("web_search", {"query": "x"}, "should not be stored", error=True)
        self.assertEqual(self._refs(), [])

    def test_failed_call_not_captured_via_success_false(self):
        self.provider.post_tool_call("web_search", {"query": "x"}, "should not be stored", success=False)
        self.assertEqual(self._refs(), [])

    def test_operational_noise_not_captured(self):
        self.provider.post_tool_call("web_fetch", {"url": "https://x"}, '{"run_id": "abc123", "schema": "v1"}')
        self.assertEqual(self._refs(), [])

    def test_empty_result_not_captured(self):
        self.provider.post_tool_call("web_fetch", {"url": "https://x"}, "")
        self.provider.post_tool_call("web_fetch", {"url": "https://x"}, None)
        self.assertEqual(self._refs(), [])

    def test_repeated_fetch_of_same_topic_refreshes_one_row(self):
        args = {"url": "https://example.test/acme", "query": "Acme overview"}
        self.provider.post_tool_call("web_fetch", args, "First summary.")
        self.provider.post_tool_call("web_fetch", args, "Second, refreshed summary.")
        rows = self._refs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cached_summary"], "Second, refreshed summary.")

    def test_different_topics_create_distinct_rows(self):
        self.provider.post_tool_call("web_fetch", {"url": "https://a.test", "query": "A"}, "About A.")
        self.provider.post_tool_call("web_fetch", {"url": "https://b.test", "query": "B"}, "About B.")
        self.assertEqual(len(self._refs()), 2)

    def test_file_read_synthesizes_file_url_and_topic(self):
        self.provider.post_tool_call("read_file", {"path": "/tmp/notes.txt"},
                                     "Notes about Pat Testley, a fixture persona.")
        rows = self._refs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["retrieval_url"], "file:///tmp/notes.txt")
        self.assertEqual(rows[0]["topic"], "/tmp/notes.txt")

    def test_dict_result_extracts_text_field(self):
        self.provider.post_tool_call("web_search", {"query": "pat testley"},
                                     {"text": "Pat Testley result text."})
        rows = self._refs()
        self.assertEqual(rows[0]["cached_summary"], "Pat Testley result text.")

    def test_custom_allowlist_and_ttl_from_config(self):
        home3 = tempfile.mkdtemp()
        try:
            p3 = ChronicleMemoryProvider()
            p3.initialize("s1", hermes_home=home3, principal_id="assistant",
                          config={"embeddings": {"model": "hashing"},
                                  "capture": {"tool_reference": {"allowlist": ["custom_tool"], "ttl_days": 7}}})
            p3.post_tool_call("custom_tool", {"query": "q"}, "a custom tool's result text")
            rows = p3.core.store.query_beliefs("refs", "1=1", (), 50)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["ttl_days"], 7)

            # web_fetch is no longer allowlisted once the config overrides the default set.
            p3.post_tool_call("web_fetch", {"url": "https://x", "query": "q"}, "content")
            self.assertEqual(len(p3.core.store.query_beliefs("refs", "1=1", (), 50)), 1)
        finally:
            shutil.rmtree(home3, ignore_errors=True)

    def test_missing_tool_name_is_a_noop(self):
        self.provider.post_tool_call("", {"query": "x"}, "content")
        self.provider.post_tool_call(None, {"query": "x"}, "content")
        self.assertEqual(self._refs(), [])

    def test_noop_before_initialize(self):
        p = ChronicleMemoryProvider()  # never initialized -> self.core is None
        p.post_tool_call("web_fetch", {"url": "https://x"}, "content")  # must not raise


# ---------------------------------------------------------------------------
# subagent_stop -> richer delegation episode
# ---------------------------------------------------------------------------
class TestSubagentStopDelegationEpisode(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.provider = ChronicleMemoryProvider()
        self.provider.initialize("s1", hermes_home=self.home, principal_id="assistant",
                                 config={"embeddings": {"model": "hashing"}})

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _delegation_payloads(self):
        out = []
        for ev in self.provider.core.store.get_events_since(0):
            if ev["type"] != "observed":
                continue
            p = ev["payload"]
            if isinstance(p, str):
                p = json.loads(p)
            if p.get("source_type") == "delegation":
                out.append(p)
        return out

    def test_captures_status_duration_and_tool_summary(self):
        self.provider.subagent_stop(
            "Summarize the Acme fixtures", "Done, wrote 3 files.",
            child_session_id="child-1", child_status="completed",
            tool_call_history=[{"tool": "read_file"}, {"tool": "read_file"}, {"tool": "web_search"}],
            duration_ms=4200)
        payloads = self._delegation_payloads()
        self.assertEqual(len(payloads), 1)
        p = payloads[0]
        self.assertEqual(p["task"], "Summarize the Acme fixtures")
        self.assertEqual(p["result"], "Done, wrote 3 files.")
        self.assertEqual(p["child_session_id"], "child-1")
        self.assertEqual(p["child_status"], "completed")
        self.assertEqual(p["duration_ms"], 4200)
        self.assertEqual(p["tool_call_count"], 3)
        self.assertIn("read_file×2", p["tools_used"])
        self.assertIn("web_search", p["tools_used"])
        self.assertIn("Status: completed", p["excerpt"])
        self.assertIn("Duration: 4200ms", p["excerpt"])
        self.assertIn("Tools used:", p["excerpt"])

    def test_no_tool_history_omits_tools_line(self):
        self.provider.subagent_stop("task", "result", child_status="failed", duration_ms=100)
        p = self._delegation_payloads()[-1]
        self.assertEqual(p["tool_call_count"], 0)
        self.assertEqual(p["tools_used"], "")
        self.assertNotIn("Tools used", p["excerpt"])

    def test_on_delegation_still_works_unmodified(self):
        self.provider.on_delegation("task A", "result A", child_session_id="c1")
        payloads = self._delegation_payloads()
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["task"], "task A")
        self.assertNotIn("child_status", payloads[0])  # on_delegation's plain payload shape, unchanged

    def test_both_hooks_write_independent_episodes(self):
        self.provider.on_delegation("task A", "result A", child_session_id="c1")
        self.provider.subagent_stop("task A", "result A", child_session_id="c1",
                                    child_status="completed", duration_ms=10)
        self.assertEqual(len(self._delegation_payloads()), 2)

    def test_noop_before_initialize(self):
        p = ChronicleMemoryProvider()
        p.subagent_stop("task", "result", child_status="completed")  # must not raise


if __name__ == "__main__":
    unittest.main()
