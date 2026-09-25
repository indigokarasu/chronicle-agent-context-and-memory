"""Chronicle — F10d: folder paths as containers (engine/passages.py).

A container normally only collapses hits that already exist — records sharing
an exact key (a thread id). A FOLDER is different: someone can ask about "the
Taxes 2026 Deductions folder" without any one file in it ever having scored on
its own projection vector. F10d adds a second thing a `container` with a
declared `path_separator` can do: match a query's focus tokens against path
SEGMENTS and answer with an aggregate card (path, file count, top file names)
read by path prefix at query time — generic, keyed on the declared
`path_separator`, never on a source's name. Every fixture here is synthetic.
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import passages as P  # noqa: E402
from engine.core import ChronicleCore  # noqa: E402
from engine.localdb import LocalDBProvider  # noqa: E402


# -- pure matching (no I/O) ---------------------------------------------------

class TestPathSegments(unittest.TestCase):
    def test_splits_and_drops_empty_pieces(self):
        self.assertEqual(P.path_segments("Home/Taxes/2026/", "/"), ["Home", "Taxes", "2026"])
        self.assertEqual(P.path_segments("/Home//Taxes", "/"), ["Home", "Taxes"])

    def test_no_separator_or_empty_path_is_no_segments(self):
        self.assertEqual(P.path_segments("Home/Taxes", ""), [])
        self.assertEqual(P.path_segments("", "/"), [])
        self.assertEqual(P.path_segments(None, "/"), [])


class TestYearToken(unittest.TestCase):
    def test_bare_four_digits_is_a_year_token(self):
        self.assertTrue(P.is_year_token("2026"))
        self.assertTrue(P.is_year_token("1999"))

    def test_other_shapes_are_not(self):
        for tok in ("202", "20260", "2026a", "", None, "taxes"):
            self.assertFalse(P.is_year_token(tok), tok)


class TestSegmentMatches(unittest.TestCase):
    def test_ordinary_token_matches_as_a_case_insensitive_substring(self):
        self.assertTrue(P.segment_matches("tax", "Taxes"))
        self.assertTrue(P.segment_matches("DEDUCTIONS", "deductions"))
        self.assertFalse(P.segment_matches("invoices", "Taxes"))

    def test_year_token_must_equal_the_segment_not_merely_appear_in_it(self):
        self.assertTrue(P.segment_matches("2026", "2026"))
        # A segment that CONTAINS the four digits but is not itself a year
        # (a form number, a filename fragment) must not count as a date hint.
        self.assertFalse(P.segment_matches("2026", "Form2026"))
        self.assertFalse(P.segment_matches("2026", "2026-Q1"))


class TestFolderMatches(unittest.TestCase):
    PATH = "Home/Taxes/2026/Deductions"

    def test_every_token_must_match_some_segment(self):
        self.assertTrue(P.folder_matches(self.PATH, ["taxes"], "/"))
        self.assertTrue(P.folder_matches(self.PATH, ["taxes", "2026"], "/"))
        self.assertTrue(P.folder_matches(self.PATH, ["taxes", "2026", "deductions"], "/"))

    def test_one_unmatched_token_fails_the_whole_path(self):
        # "invoices" names nothing in this path -- a partial match is not a
        # folder card: it would be a confident claim about the wrong folder.
        self.assertFalse(P.folder_matches(self.PATH, ["taxes", "invoices"], "/"))

    def test_year_token_rejects_a_path_with_no_year_segment(self):
        self.assertFalse(P.folder_matches("Home/Taxes/Deductions", ["taxes", "2026"], "/"))

    def test_no_tokens_or_no_path_is_never_a_match(self):
        self.assertFalse(P.folder_matches(self.PATH, [], "/"))
        self.assertFalse(P.folder_matches("", ["taxes"], "/"))


class TestBestFolderMatches(unittest.TestCase):
    def test_a_nested_match_is_dropped_in_favour_of_its_matched_ancestor(self):
        paths = ["Home/Taxes/2026", "Home/Taxes/2026/Deductions", "Home/Taxes/2026/Receipts"]
        # All three match ["taxes", "2026"]; the shallow one already covers the
        # other two by prefix, so keeping them too would double-count files.
        self.assertEqual(P.best_folder_matches(paths, ["taxes", "2026"], "/"),
                         ["Home/Taxes/2026"])

    def test_unrelated_matches_are_both_kept(self):
        paths = ["Home/Taxes/2026", "Work/Archive/2026"]
        self.assertEqual(P.best_folder_matches(paths, ["2026"], "/"),
                         ["Home/Taxes/2026", "Work/Archive/2026"])

    def test_non_matching_paths_are_excluded(self):
        paths = ["Home/Taxes/2026", "Home/Photos/2026"]
        self.assertEqual(P.best_folder_matches(paths, ["taxes", "2026"], "/"),
                         ["Home/Taxes/2026"])

    def test_deterministic_order_shallowest_then_lexicographic(self):
        paths = ["Home/B/2026", "Home/A/2026"]
        self.assertEqual(P.best_folder_matches(paths, ["2026"], "/"),
                         ["Home/A/2026", "Home/B/2026"])

    def test_no_tokens_or_no_separator_yields_nothing(self):
        self.assertEqual(P.best_folder_matches(["Home/Taxes/2026"], [], "/"), [])
        self.assertEqual(P.best_folder_matches(["Home/Taxes/2026"], ["2026"], ""), [])


# -- container_spec parses path_separator, backward compatible ---------------

class TestContainerSpecPathSeparator(unittest.TestCase):
    def test_path_separator_declared(self):
        spec = P.container_spec({"container": {"column": "folder", "label": "folder",
                                                "path_separator": "/"}})
        self.assertEqual(spec.column, "folder")
        self.assertEqual(spec.path_separator, "/")

    def test_default_is_empty_for_an_opaque_container(self):
        # A thread id (F11a's shape): no path_separator, so no folder-card
        # behaviour -- a container declared before F10d parses identically.
        spec = P.container_spec({"container": {"column": "thread_id", "label": "thread"}})
        self.assertEqual(spec.path_separator, "")

    def test_container_spec_ignores_other_unknown_keys_as_before(self):
        spec = P.container_spec({"container": {"column": "folder", "label": "folder",
                                                "path_separator": "/", "bogus": 1}})
        self.assertEqual(spec.column, "folder")


# -- LocalDBProvider: distinct_values / folder_card (engine/localdb.py) ------

def _documents_db(tmp_dir: str):
    """documents(id, name, folder, modified_at) — a Drive-shaped table with an
    obviously-fake folder tree, plus one row whose only relation to "2026" is
    its modified_at column (the "merely modified that year" case)."""
    path = str(Path(tmp_dir) / "documents.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, name TEXT, "
                "folder TEXT, modified_at TEXT)")
    conn.executemany("INSERT INTO documents (id, name, folder, modified_at) VALUES (?,?,?,?)", [
        (1, "W2.pdf", "Home/Taxes/2026/Deductions", "2025-11-02"),
        (2, "Receipt.pdf", "Home/Taxes/2026/Deductions", "2025-11-03"),
        (3, "Form1099.pdf", "Home/Taxes/2026", "2025-10-01"),
        (4, "Notes.txt", "Home/Other", "2026-03-05"),          # modified in 2026, wrong folder
        (5, "Unfiled.txt", "", "2025-01-01"),                  # no folder at all
    ])
    conn.commit()
    conn.close()
    return path


class TestLocalDBDistinctValues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = _documents_db(self.tmp)
        self.provider = LocalDBProvider("docs", self.db_path, table="documents")

    def test_returns_distinct_non_empty_values_sorted(self):
        vals = self.provider.distinct_values("documents", "folder")
        self.assertEqual(vals, sorted(set(vals)))
        self.assertIn("Home/Taxes/2026/Deductions", vals)
        self.assertNotIn("", vals)          # row 5's empty folder is excluded

    def test_unknown_column_returns_empty_and_never_raises(self):
        self.assertEqual(self.provider.distinct_values("documents", "no_such_column"), [])

    def test_acl_denies_a_foreign_principal(self):
        provider = LocalDBProvider("docs", self.db_path, table="documents", read_acl="owner_only")
        self.assertEqual(provider.distinct_values("documents", "folder",
                                                   owner="owner", principal="somebody_else"), [])


class TestLocalDBFolderCard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = _documents_db(self.tmp)
        self.provider = LocalDBProvider("docs", self.db_path, table="documents")

    def test_exact_and_nested_rows_are_counted_by_prefix(self):
        # "Home/Taxes/2026" itself (row 3) plus everything nested under it
        # (rows 1-2, "Home/Taxes/2026/Deductions") -- three files total.
        card = self.provider.folder_card("documents", "folder", "Home/Taxes/2026", "/",
                                         name_column="name")
        self.assertEqual(card["file_count"], 3)
        self.assertEqual(sorted(card["names"]), ["Form1099.pdf", "Receipt.pdf", "W2.pdf"])

    def test_a_similarly_named_sibling_is_not_pulled_in(self):
        # "Home/Taxes/2026" must not match "Home/Taxes/20260" or any other
        # folder that merely starts with the same characters.
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO documents (id, name, folder, modified_at) VALUES "
                    "(6, 'Sibling.pdf', 'Home/Taxes/20260/Oops', '2025-01-01')")
        conn.commit()
        conn.close()
        self.provider._schema = None            # force a fresh schema/manifest read
        card = self.provider.folder_card("documents", "folder", "Home/Taxes/2026", "/",
                                         name_column="name")
        self.assertEqual(card["file_count"], 3)
        self.assertNotIn("Sibling.pdf", card["names"])

    def test_no_name_column_gives_a_count_with_no_names(self):
        card = self.provider.folder_card("documents", "folder", "Home/Taxes/2026", "/")
        self.assertEqual(card["file_count"], 3)
        self.assertEqual(card["names"], [])

    def test_names_are_capped_at_max_names(self):
        card = self.provider.folder_card("documents", "folder", "Home/Taxes/2026", "/",
                                         name_column="name", max_names=2)
        self.assertEqual(len(card["names"]), 2)

    def test_no_match_is_a_zero_count_not_none(self):
        card = self.provider.folder_card("documents", "folder", "Nowhere/At/All", "/",
                                         name_column="name")
        self.assertEqual(card["file_count"], 0)

    def test_unknown_column_returns_none_and_never_raises(self):
        self.assertIsNone(self.provider.folder_card("documents", "no_such_column",
                                                     "Home/Taxes", "/"))
        self.assertIsNone(self.provider.folder_card("documents", "folder", "Home/Taxes", "/",
                                                     name_column="no_such_column"))

    def test_acl_denies_a_foreign_principal(self):
        provider = LocalDBProvider("docs", self.db_path, table="documents", read_acl="owner_only")
        card = provider.folder_card("documents", "folder", "Home/Taxes/2026", "/",
                                    name_column="name", owner="owner", principal="somebody_else")
        self.assertIsNone(card)


# -- end to end: RetrievalEngine._folder_hits, get_context, retrieve_raw -----

def _cfg(db_path, federated_channel=False, container=None, name_column="name"):
    entry = {"name": "docs", "path": db_path, "table": "documents", "id_column": "id",
             "name_column": name_column, "read_only": True,
             "container": container if container is not None else
                          {"column": "folder", "label": "folder", "path_separator": "/"}}
    return {"embeddings": {"model": "hashing"},
            "federation": {"local_dbs": [entry]},
            "retrieval": {"federated_channel": federated_channel}}


def _core(db_path, **cfg_kw):
    return ChronicleCore(tempfile.mkdtemp(), _cfg(db_path, **cfg_kw))


class TestFolderHitsMethod(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = _documents_db(self.tmp)
        self.core = _core(self.db_path)

    def test_matched_folder_returns_a_card(self):
        hits = self.core.retrieval._folder_hits(["taxes", "2026"], "default")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["provider"], "docs")
        self.assertEqual(hits[0]["path"], "Home/Taxes/2026")
        self.assertIn("3 files", hits[0]["block"])

    def test_no_focus_tokens_is_no_hits(self):
        self.assertEqual(self.core.retrieval._folder_hits([], "default"), [])

    def test_a_token_that_matches_nothing_yields_no_hits(self):
        self.assertEqual(self.core.retrieval._folder_hits(["invoices"], "default"), [])

    def test_container_with_no_path_separator_never_produces_a_folder_hit(self):
        # Same column, declared WITHOUT path_separator (an opaque group id,
        # as F11a's mail thread container is): the generic dispatch is keyed
        # on the declared path_separator, never on the source's name.
        core = _core(self.db_path, container={"column": "folder", "label": "folder"})
        self.assertEqual(core.retrieval._folder_hits(["taxes", "2026"], "default"), [])


class TestFolderCardInChronicleSearch(unittest.TestCase):
    """The tool path (`chronicle_search` -> retrieve_raw -> _retrieve_raw_inner):
    a folder card must surface even with the per-turn federated channel OFF and
    with no file's projection vector ever embedded -- an explicit search for a
    folder does not depend on either."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = _documents_db(self.tmp)
        self.core = _core(self.db_path, federated_channel=False)

    def test_retrieve_raw_carries_a_folder_entry_ranked_first(self):
        rows = self.core.retrieval.retrieve_raw("taxes 2026", principal="default",
                                                 include_folder_cards=True)
        folder_rows = [r for r in rows if r["event_id"].startswith("folder:")]
        self.assertEqual(len(folder_rows), 1)
        self.assertEqual(folder_rows[0]["event_id"], "folder:docs:Home/Taxes/2026")
        self.assertIn("[FOLDER docs]", folder_rows[0]["excerpt"])
        self.assertIn("3 files", folder_rows[0]["excerpt"])
        # A folder card is a specific, exact match -- it must rank ahead of
        # anything else `retrieve_raw` found for the same query.
        self.assertEqual(rows[0]["event_id"], folder_rows[0]["event_id"])

    def test_opt_in_default_is_off(self):
        # r1: a folder card is federated content and must never leak into a
        # caller that did not ask for it (get_context's Tier-2 raw evidence
        # is exactly such a caller -- see retrieve_raw's docstring).
        rows = self.core.retrieval.retrieve_raw("taxes 2026", principal="default")
        self.assertFalse(any(r["event_id"].startswith("folder:") for r in rows))

    def test_chronicle_search_tool_surfaces_the_card(self):
        from engine.tools import Tools
        out = Tools(self.core).dispatch("default", "search", {"query": "taxes 2026"})
        import json as _json
        payload = _json.loads(out) if isinstance(out, str) else out
        said_text = " ".join(s.get("excerpt", "") for s in payload.get("said", []))
        self.assertIn("[FOLDER docs] Home/Taxes/2026", said_text)


class TestFolderCardPerTurnPriority(unittest.TestCase):
    """The per-turn path (get_context's federated block): a folder card is
    assembled BEFORE the generic per-column LIKE search, so a query naming a
    year claims budget with the folder match first -- not with row 4, whose
    only relation to "2026" is that its modified_at column contains it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = _documents_db(self.tmp)
        self.core = _core(self.db_path, federated_channel=True)

    def test_folder_line_present_and_ordered_before_the_modified_at_only_hit(self):
        ctx = self.core.retrieval.get_context("taxes 2026", token_budget=4000,
                                              principal="default")
        lines = ctx.split("\n")
        folder_lines = [i for i, ln in enumerate(lines) if ln.startswith("[FOLDER docs]")]
        # Exactly once: get_context's own Tier-2 raw evidence (retrieve_raw
        # with the default include_folder_cards=False) must not ALSO carry
        # one alongside the federated-tail injection below.
        self.assertEqual(len(folder_lines), 1, ctx)
        folder_idx = folder_lines[0]
        self.assertIn("Home/Taxes/2026", lines[folder_idx])
        modified_only_idx = next((i for i, ln in enumerate(lines)
                                  if ln.startswith("[FEDERATED docs]") and "documents:4" in ln), None)
        if modified_only_idx is not None:      # present whenever the budget fit it at all
            self.assertLess(folder_idx, modified_only_idx)

    def test_tight_budget_keeps_the_folder_card_over_the_generic_hits(self):
        # A budget wide enough for exactly one tail line: the folder card
        # (assembled first) claims it, and the generic per-column search is
        # left with nothing -- the concrete form of "prefers the folder".
        ctx = self.core.retrieval.get_context("taxes 2026", token_budget=40,
                                              principal="default")
        self.assertIn("[FOLDER docs] Home/Taxes/2026", ctx)
        self.assertNotIn("[FEDERATED docs]", ctx)

    def test_channel_off_means_no_folder_line_either(self):
        core = _core(self.db_path, federated_channel=False)
        ctx = core.retrieval.get_context("taxes 2026", token_budget=4000, principal="default")
        self.assertNotIn("[FOLDER", ctx)


if __name__ == "__main__":
    unittest.main()
