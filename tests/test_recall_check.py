"""
Chronicle — scripts/recall_check.py: where a profile's store is, what is in it,
and whether Chronicle by itself recalls a fact.

Two things people could not check before. A named profile's store could sit
under a different home than the one they were looking at, and "does Chronicle
remember this, or is it Hermes' own MEMORY.md?" had no answer short of a live
conversation. The script answers both:

  * report mode is READ-ONLY. Every report below is run between two snapshots of
    the whole temp tree (names, bytes, modification times); any difference is a
    failure, so a report that creates a store, a directory or a sidecar fails
    whichever test happened to run it.
  * `--canary` runs the real provider and tool entry points in a temporary home
    and must go red when recall is broken, at capture or at retrieval.

Fixtures use obviously fake values; every path lives under a temp directory.
"""

import contextlib
import hashlib
import io
import importlib.util
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.embeddings import pack
from engine.store import MemoryStore, now_iso
from provider import ChronicleMemoryProvider

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "scripts" / "recall_check.py"

_FACT = "My locker code is 4 8 1 5 9 2."
_CODE = "4 8 1 5 9 2"

# A start that touches nothing outside the home it is given.
_QUIET = {"embeddings": {"model": "hashing"}, "git": {"enabled": False},
          "sources": {"ocas_journals": {"enabled": False}},
          "curation": {"drain": {"background": False}}}


def _load_script():
    """Import scripts/recall_check.py by path (scripts/ is not a package)."""
    chronicle_log = logging.getLogger("chronicle")
    level = chronicle_log.level
    try:
        spec = importlib.util.spec_from_file_location("recall_check_under_test", str(_SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        chronicle_log.setLevel(level)
    return mod


def _snapshot(root):
    """Everything under `root`: directories, links, and (hash, size, mtime) of files."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            if os.path.islink(path):
                out[rel] = ("link", os.readlink(path))
            elif os.path.isdir(path):
                out[rel] = ("dir",)
            else:
                with open(path, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
                st = os.stat(path)
                out[rel] = ("file", digest, st.st_size, st.st_mtime_ns)
    return out


def _stub_host(home):
    """A stand-in for the host's `hermes_constants`, answering with `home`."""
    mod = types.ModuleType("hermes_constants")
    mod.get_hermes_home = lambda: Path(home)
    return mod


def _settle_wal(path):
    """Leave `path` as a WAL-mode store looks after its last connection went away
    without leaving sidecars: everything in the main file, journal mode still
    WAL in the header, no `-wal`, no `-shm`. A plain read-only open refuses that
    state ("unable to open database file"), and `paths.has_data` calls it empty.
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL").fetchall()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path + suffix)
    with open(path, "rb") as fh:
        header = fh.read(20)
    assert header[18:20] == b"\x02\x02", "the fixture is not a WAL-mode file"


def _build_store(home, turns=(_FACT,), config=None):
    """A real Chronicle store under `home`, filled through the provider: one
    captured turn per entry of `turns`, extraction drained, closed cleanly."""
    cfg = dict(_QUIET)
    cfg.update(config or {})
    provider = ChronicleMemoryProvider()
    provider.initialize("fixture-session", hermes_home=home, principal_id="default", config=cfg)
    for text in turns:
        provider.sync_turn(text, "Noted.", session_id="fixture-session")
    provider.core.process_pending()
    provider.core.close()


def _db_files(root):
    return sorted(str(p) for p in Path(root).rglob("chronicle.db"))


def _write_config(home, text):
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "config.yaml"), "w") as fh:
        fh.write(text)


def _parse(output):
    """(pairs, notes, last line) of a report. Keys are unique; notes repeat."""
    lines = output.strip().splitlines()
    pairs, notes = {}, []
    for line in lines[:-1]:
        key, _, value = line.partition(": ")
        if key == "note":
            notes.append(value)
        else:
            pairs[key] = value
    return pairs, notes, lines[-1]


class _Case(unittest.TestCase):
    """A fake user home, a Hermes root with one named profile `p`, and a host that
    answers with the root. `self.run_script` runs `main` between two snapshots of
    the whole tree."""

    def setUp(self):
        self.tmp = os.path.realpath(temp_home(prefix="recall-check-"))
        self.user_home = os.path.join(self.tmp, "user")
        self.root = os.path.join(self.tmp, "hermes")
        self.profile = os.path.join(self.root, "profiles", "p")
        os.makedirs(self.user_home)
        os.makedirs(self.profile)
        env = mock.patch.dict(os.environ, {"HOME": self.user_home})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("HERMES_HOME", None)
        os.environ.pop("CHRONICLE_EMBED_MODEL", None)
        host = mock.patch.dict(sys.modules, {"hermes_constants": _stub_host(self.root)})
        host.start()
        self.addCleanup(host.stop)
        self.mod = _load_script()

    def run_script(self, *argv, snapshot=True):
        before = _snapshot(self.tmp) if snapshot else None
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.mod.main(list(argv))
            except SystemExit as e:
                code = e.code
        if snapshot:
            self.assertEqual(_snapshot(self.tmp), before,
                             "the script changed files it was only meant to read")
        return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------
# report mode
# --------------------------------------------------------------------------

class TestReportMode(_Case):
    def test_a_named_profile_is_reported_with_its_own_store(self):
        _write_config(self.profile, "memory:\n  provider: chronicle\n  memory_enabled: false\n"
                                    "  user_profile_enabled: false\ncontext:\n  engine: chronicle\n")
        _build_store(self.profile)
        # The root has a store of its own that must NOT be the one reported.
        _build_store(self.root, turns=("My favourite colour is green.",))
        code, out, _ = self.run_script("--profile", "p")
        pairs, notes, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(pairs["home"], self.profile)
        self.assertEqual(pairs["profile"], "p")
        self.assertEqual(pairs["db_path"], os.path.join(self.profile, "commons", "db", "chronicle",
                                                        "chronicle.db"))
        self.assertEqual(pairs["db_open"], pairs["db_path"])
        self.assertEqual(pairs["memory.provider"], "chronicle")
        self.assertEqual(pairs["context.engine"], "chronicle")
        self.assertEqual(pairs["memory.memory_enabled"], "false")
        self.assertEqual(pairs["memory.user_profile_enabled"], "false")
        self.assertGreater(int(pairs["events"]), 0)
        self.assertRegex(pairs["last_event"], r"^\d{4}-\d\d-\d\dT")
        self.assertIn("git_mirror", pairs)
        self.assertNotIn("extension_tables", pairs)
        # Both built-in flags are off, so the note about MEMORY.md must not appear.
        self.assertFalse([n for n in notes if "MEMORY.md" in n], notes)

    def test_default_means_the_root_and_no_argument_means_the_active_home(self):
        _build_store(self.root)
        code, out, _ = self.run_script("--profile", "default")
        pairs, _, result = _parse(out)
        self.assertEqual((code, result, pairs["home"]), (0, "PASS", self.root), out)
        code, out, _ = self.run_script()
        pairs, _, result = _parse(out)
        self.assertEqual((code, result, pairs["home"]), (0, "PASS", self.root), out)

    def test_an_explicit_home_is_used(self):
        other = os.path.join(self.tmp, "elsewhere")
        _build_store(other)
        code, out, _ = self.run_script("--home", other)
        pairs, _, result = _parse(out)
        self.assertEqual((code, result, pairs["home"]), (0, "PASS", other), out)

    def test_a_missing_profile_fails_and_is_not_created(self):
        code, out, _ = self.run_script("--profile", "nope")
        _, _, result = _parse(out)
        self.assertEqual(code, 1)
        self.assertRegex(result, r"^FAIL: .*does not exist")
        self.assertFalse(os.path.exists(os.path.join(self.root, "profiles", "nope")))

    def test_a_profile_with_no_store_fails_without_making_one(self):
        _write_config(self.profile, "memory:\n  provider: chronicle\n")
        code, out, _ = self.run_script("--profile", "p")
        pairs, _, result = _parse(out)
        self.assertEqual(code, 1)
        self.assertRegex(result, r"^FAIL: no Chronicle store at ")
        self.assertEqual(pairs["store"], "none")
        self.assertEqual(_db_files(self.tmp), [])

    def test_an_empty_store_file_fails_and_is_not_written_to(self):
        db = os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db")
        os.makedirs(os.path.dirname(db))
        open(db, "w").close()
        code, out, _ = self.run_script("--profile", "p")
        _, _, result = _parse(out)
        self.assertEqual(code, 1)
        self.assertRegex(result, r"^FAIL: cannot read the store .*empty")

    def test_a_store_with_no_events_fails(self):
        db = os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db")
        os.makedirs(os.path.dirname(db))
        MemoryStore(db).close()
        _settle_wal(db)
        code, out, _ = self.run_script("--profile", "p")
        pairs, _, result = _parse(out)
        self.assertEqual(code, 1)
        self.assertRegex(result, r"^FAIL: .*holds no events")
        self.assertEqual(pairs["events"], "0")

    def test_a_store_that_was_closed_cleanly_is_read(self):
        # No -wal and no -shm, as the last connection leaves a store. A plain
        # read-only open refuses it, and has_data then calls it empty.
        db = os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db")
        _build_store(self.profile)
        _settle_wal(db)
        self.assertEqual([f for f in os.listdir(os.path.dirname(db)) if f.startswith("chronicle.db-")], [])
        code, out, _ = self.run_script("--profile", "p")
        pairs, _, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertGreater(int(pairs["events"]), 0)

    def test_an_unmigrated_store_at_the_old_location_is_found(self):
        # 5.11.1 ignored an absolute db_path and wrote to the default location.
        _build_store(self.profile)
        configured = os.path.join(self.tmp, "chosen", "chronicle.db")
        _write_config(self.profile, "memory:\n  provider: chronicle\n  db_path: %s\n" % configured)
        legacy = os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db")
        _settle_wal(legacy)
        code, out, _ = self.run_script("--profile", "p")
        pairs, notes, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(pairs["db_configured"], configured)
        self.assertEqual(pairs["db_path"], configured)
        self.assertEqual(pairs["db_open"], legacy)
        self.assertIn("holds events, not moved yet", pairs["db_legacy_path"])
        self.assertEqual(pairs["migration_record"], "none")
        self.assertGreater(int(pairs["events"]), 0)
        self.assertTrue([n for n in notes if "old location" in n], notes)
        self.assertFalse(os.path.exists(configured))

    def test_every_connection_it_opens_is_read_only(self):
        # A store closed in a way that leaves no sidecars is rewritten by a
        # read-write open (SQLite recreates them), and an open of a missing file
        # makes one. Neither shows in a snapshot taken afterwards if SQLite tidies
        # up on close, so the open itself is what is checked.
        _build_store(self.profile)
        configured = os.path.join(self.tmp, "chosen", "chronicle.db")
        _write_config(self.profile, "memory:\n  db_path: %s\n" % configured)
        _settle_wal(os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db"))
        opened = []
        real = sqlite3.connect

        def spy(target, *args, **kwargs):
            opened.append(str(target))
            return real(target, *args, **kwargs)

        with mock.patch.object(sqlite3, "connect", spy):
            for argv in (["--profile", "p"], ["--profile", "p", "--db", configured],
                         ["--home", self.root]):
                self.run_script(*argv)
        self.assertTrue(opened)
        self.assertEqual([t for t in opened if "mode=ro" not in t], [])

    def test_a_migrated_store_shows_the_record_and_the_old_name_as_a_link(self):
        _build_store(self.profile)
        configured = os.path.join(self.tmp, "chosen", "chronicle.db")
        _write_config(self.profile, "memory:\n  provider: chronicle\n  db_path: %s\n" % configured)
        # The real migration: a start with the new setting moves the store.
        core = ChronicleCore(self.profile, dict(_QUIET, db_path=configured))
        self.assertEqual(core.store_migration.action, "moved")
        core.close()
        _settle_wal(configured)
        legacy = os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db")
        self.assertTrue(os.path.islink(legacy))
        code, out, _ = self.run_script("--profile", "p")
        pairs, notes, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(pairs["db_open"], configured)
        self.assertIn("symlink to db_path", pairs["db_legacy_path"])
        self.assertRegex(pairs["migration_record"], r"^moved .* -> .* at \d{8}T\d{6}Z")
        self.assertIn(configured, pairs["migration_record"])
        self.assertGreater(int(pairs["events"]), 0)
        self.assertFalse([n for n in notes if "old location" in n], notes)

    def test_two_stores_holding_events_are_called_out(self):
        _build_store(self.profile)
        configured = os.path.join(self.tmp, "chosen", "chronicle.db")
        os.makedirs(os.path.dirname(configured))
        _build_store(os.path.join(self.tmp, "other-home"), turns=("My favourite colour is green.",))
        shutil.copy(os.path.join(self.tmp, "other-home", "commons", "db", "chronicle",
                                 "chronicle.db"), configured)
        _settle_wal(configured)
        _settle_wal(os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db"))
        _write_config(self.profile, "memory:\n  db_path: %s\n" % configured)
        code, out, _ = self.run_script("--profile", "p")
        pairs, notes, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(pairs["db_open"], configured)
        self.assertTrue([n for n in notes if n.startswith("two stores hold events")], notes)

    def test_the_db_flag_replaces_the_configured_path(self):
        _build_store(self.profile)
        other = os.path.join(self.tmp, "flagged", "chronicle.db")
        os.makedirs(os.path.dirname(other))
        shutil.copy(os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db"), other)
        _settle_wal(other)
        code, out, _ = self.run_script("--profile", "p", "--db", other)
        pairs, _, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(pairs["db_path"], other)
        self.assertIn("[--db]", pairs["db_configured"])

    def test_a_config_that_names_the_profile_twice_resolves_into_the_profile(self):
        _write_config(self.profile, "memory:\n  db_path: ~/.hermes/profiles/p/custom/chronicle.db\n")
        code, out, _ = self.run_script("--profile", "p")
        pairs, _, _ = _parse(out)
        self.assertEqual(code, 1)
        self.assertEqual(pairs["db_path"], os.path.join(self.profile, "custom", "chronicle.db"))

    def test_an_unreadable_config_degrades_instead_of_crashing(self):
        # A bare system Python may not have PyYAML.
        _write_config(self.profile, "memory:\n  provider: chronicle\n")
        _build_store(self.profile)
        with mock.patch.dict(sys.modules, {"yaml": None}):
            code, out, _ = self.run_script("--profile", "p")
        pairs, notes, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertIn("not readable: PyYAML", pairs["config"])
        self.assertEqual(pairs["memory.provider"], "unset")
        self.assertTrue([n for n in notes if "could not be read" in n], notes)

    def test_a_config_with_broken_yaml_degrades_too(self):
        _write_config(self.profile, "memory: [unclosed\n")
        _build_store(self.profile)
        code, out, _ = self.run_script("--profile", "p")
        pairs, _, result = _parse(out)
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertIn("not readable", pairs["config"])

    def test_a_profile_that_does_not_use_chronicle_is_flagged(self):
        _write_config(self.profile, "memory:\n  provider: other\n")
        _build_store(self.profile)
        code, out, _ = self.run_script("--profile", "p")
        _, notes, _ = _parse(out)
        self.assertEqual(code, 0)
        self.assertTrue([n for n in notes if "neither" in n], notes)

    def test_builtin_memory_left_on_is_pointed_out(self):
        _write_config(self.profile, "memory:\n  provider: chronicle\n  memory_enabled: true\n")
        _build_store(self.profile)
        _, out, _ = self.run_script("--profile", "p")
        pairs, notes, _ = _parse(out)
        self.assertEqual(pairs["memory.memory_enabled"], "true")
        self.assertEqual(pairs["memory.user_profile_enabled"], "unset")
        self.assertTrue([n for n in notes if "MEMORY.md" in n], notes)

    def test_vectors_are_counted_by_width_and_a_foreign_table_is_named(self):
        db = os.path.join(self.profile, "commons", "db", "chronicle", "chronicle.db")
        os.makedirs(os.path.dirname(db))
        store = MemoryStore(db)
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO events(event_id, seq, type, payload, actor, owner, trust_level, "
                "session_id, occurred_at, recorded_at) "
                "VALUES('e0', 1, 'observed', '{}', 'user', 'default', 3, 's1', ?, ?)",
                (now_iso(), now_iso()))
            for i, width in enumerate((3, 3, 5)):
                conn.execute("INSERT INTO memory_vectors(belief_id, kind, embedding, model, "
                             "created_at) VALUES(?, 'fact', ?, 'fake', ?)",
                             ("b%d" % i, pack([0.5] * width), now_iso()))
            conn.execute("CREATE VIRTUAL TABLE leftover USING fts4(body)")
        store.close()
        _settle_wal(db)
        code, out, _ = self.run_script("--profile", "p", "--json")
        data = json.loads(out)
        self.assertEqual(code, 0, out)
        self.assertEqual(data["vectors"], {"3": 2, "5": 1})
        self.assertEqual(data["extension_tables"], ["leftover (module fts4)"])
        self.assertTrue([n for n in data["notes"] if "extension tables" in n], data["notes"])
        # And as text.
        _, out, _ = self.run_script("--profile", "p")
        pairs, _, _ = _parse(out)
        self.assertEqual(pairs["vectors"], "3 dims x 2, 5 dims x 1")
        self.assertEqual(pairs["extension_tables"], "leftover (module fts4)")

    def test_json_carries_the_same_facts(self):
        _build_store(self.profile)
        code, out, _ = self.run_script("--profile", "p", "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual((data["ok"], data["result"], data["mode"]), (True, "PASS", "report"))
        self.assertEqual(data["home"], self.profile)
        self.assertIsInstance(data["events"], int)
        code, out, _ = self.run_script("--profile", "nope", "--json")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(data["result"].startswith("FAIL: "))

    def test_it_reports_the_release(self):
        _build_store(self.profile)
        _, out, _ = self.run_script("--profile", "p")
        pairs, _, _ = _parse(out)
        manifest = (_ROOT / "plugin.yaml").read_text()
        expected = re.search(r"^version:\s*(\S+)", manifest, re.M).group(1)
        self.assertEqual(pairs["chronicle"], expected)


# --------------------------------------------------------------------------
# usage
# --------------------------------------------------------------------------

class TestUsage(_Case):
    def test_options_that_do_not_belong_together_are_refused(self):
        for argv in (["--canary", "--profile", "p"], ["--canary", "--home", self.root],
                     ["--canary", "--db", "x.db"], ["--profile", "p", "--home", self.root],
                     ["--live-embedder"], ["--profile", "../escape"], ["--profile", "a/b"]):
            code, out, err = self.run_script(*argv, snapshot=False)
            self.assertEqual(code, 2, argv)
            self.assertEqual(out, "", argv)
            self.assertTrue(err.strip(), argv)


# --------------------------------------------------------------------------
# --canary
# --------------------------------------------------------------------------

class _CanaryCase(unittest.TestCase):
    """No host stub and no pinned variable: the canary has to supply its own home."""

    def setUp(self):
        self.tmp = os.path.realpath(temp_home(prefix="recall-canary-"))
        self.user_home = os.path.join(self.tmp, "user")
        os.makedirs(self.user_home)
        env = mock.patch.dict(os.environ, {"HOME": self.user_home})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("HERMES_HOME", None)
        os.environ.pop("CHRONICLE_EMBED_MODEL", None)
        self.mod = _load_script()

    def run_canary(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.mod.main(["--canary"] + list(argv))
        pairs, notes, result = _parse(out.getvalue())
        return code, pairs, result, out.getvalue()


class TestCanary(_CanaryCase):
    def test_it_passes_end_to_end_and_cleans_up(self):
        before = dict(os.environ)
        code, pairs, result, out = self.run_canary()
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(pairs["mode"], "canary")
        self.assertEqual(pairs["embedder"], "HashingEmbedder")
        self.assertEqual(pairs["new_session"], "recall-check-2")
        self.assertRegex(pairs["answer"], r"locker_code: (\d ){5}\d")
        fact = re.search(r"((?:\d ){5}\d)", pairs["fact"]).group(1)
        self.assertIn(fact, pairs["answer"])
        self.assertEqual(pairs["cleanup"], "removed")
        home = pairs["home"].split(" ")[0]
        self.assertFalse(os.path.exists(home))
        self.assertFalse(os.path.exists(os.path.dirname(home)))
        self.assertEqual(dict(os.environ), before, "the canary left the environment changed")
        self.assertEqual(os.listdir(self.user_home), [], "the canary wrote under the user's home")

    def test_each_run_asks_about_a_fact_of_its_own(self):
        seen = set()
        for _ in range(3):
            _, pairs, result, _ = self.run_canary()
            self.assertEqual(result, "PASS")
            seen.add(pairs["fact"])
        self.assertGreater(len(seen), 1, "the same fact every time proves nothing")

    def test_it_uses_the_offline_embedder_whatever_the_environment_says(self):
        os.environ["CHRONICLE_EMBED_MODEL"] = "some-live-embedder"
        code, pairs, result, out = self.run_canary()
        self.assertEqual((code, result, pairs["embedder"]), (0, "PASS", "HashingEmbedder"), out)
        self.assertEqual(os.environ["CHRONICLE_EMBED_MODEL"], "some-live-embedder")

    def test_the_live_embedder_flag_leaves_the_configured_one_in_charge(self):
        from engine import core as core_mod
        real = core_mod.get_embedder
        seen = {}

        def spy(model, *args, **kw):
            seen["env"] = os.environ.get("CHRONICLE_EMBED_MODEL")
            seen["model"] = model
            return real("hashing")

        with mock.patch.object(core_mod, "get_embedder", spy):
            code, pairs, result, out = self.run_canary("--live-embedder")
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertIsNone(seen["env"], "the flag must not force the offline embedder")
        self.assertNotEqual(seen["model"], "hashing")

    def test_it_goes_red_when_retrieval_returns_nothing(self):
        from engine.retrieval import RetrievalEngine
        empty_answer = {"answer": "", "abstain": True, "sources": [], "confidence": 0.0,
                        "why": "nothing"}
        with mock.patch.object(RetrievalEngine, "answer", lambda self, *a, **k: dict(empty_answer)), \
                mock.patch.object(RetrievalEngine, "search", lambda self, *a, **k: []), \
                mock.patch.object(RetrievalEngine, "retrieve_raw", lambda self, *a, **k: []):
            code, pairs, result, out = self.run_canary()
        self.assertEqual(code, 1, out)
        self.assertTrue(result.startswith("FAIL: "), result)
        self.assertIn("chronicle_answer did not return the fact (it abstained)", result)
        self.assertIn("chronicle_search did not return the fact", result)
        self.assertEqual(pairs["cleanup"], "removed")

    def test_each_tool_is_checked_on_its_own(self):
        # chronicle_answer reads through the same search, so breaking retrieval
        # fails both; breaking one tool must fail exactly that tool's check.
        from engine.tools import Tools
        with mock.patch.object(Tools, "_t_search", lambda self, principal, a: {"results": [], "said": []}):
            code, _, result, _ = self.run_canary()
        self.assertEqual(code, 1)
        self.assertEqual(result, "FAIL: chronicle_search did not return the fact")
        with mock.patch.object(Tools, "_t_answer", lambda self, principal, a: {"answer": "", "abstain": True}):
            code, _, result, _ = self.run_canary()
        self.assertEqual(code, 1)
        self.assertEqual(result, "FAIL: chronicle_answer did not return the fact (it abstained)")

    def test_it_goes_red_when_nothing_is_captured(self):
        from engine.capture import CaptureEngine
        with mock.patch.object(CaptureEngine, "observe", lambda self, *a, **k: None):
            code, _, result, out = self.run_canary()
        self.assertEqual(code, 1, out)
        self.assertTrue(result.startswith("FAIL: "), result)

    def test_it_goes_red_and_cleans_up_when_a_step_raises(self):
        pairs_seen = {}
        with mock.patch.object(ChronicleMemoryProvider, "sync_turn",
                               side_effect=RuntimeError("disk full")):
            code, pairs_seen, result, out = self.run_canary()
        self.assertEqual(code, 1, out)
        self.assertIn("the canary raised RuntimeError: disk full", result)
        self.assertEqual(pairs_seen["cleanup"], "removed")
        self.assertEqual(os.environ.get("CHRONICLE_EMBED_MODEL"), None)

    def test_the_store_is_closed_and_opened_again_between_the_sessions(self):
        # A fact held only in memory by the first session must not pass.
        opened = []
        real_init = MemoryStore.__init__

        def spy(store, path, *a, **k):
            opened.append(path)
            return real_init(store, path, *a, **k)

        with mock.patch.object(MemoryStore, "__init__", spy):
            code, _, result, out = self.run_canary()
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[0], opened[1])

    def test_a_tilde_inside_the_canary_means_its_own_directory(self):
        seen = {}
        real = ChronicleMemoryProvider.initialize

        def spy(provider, *args, **kwargs):
            seen.setdefault("tilde", os.path.expanduser("~"))
            seen.setdefault("variable", os.environ.get("HERMES_HOME"))
            return real(provider, *args, **kwargs)

        with mock.patch.object(ChronicleMemoryProvider, "initialize", spy):
            code, _, result, out = self.run_canary()
        self.assertEqual((code, result), (0, "PASS"), out)
        scratch = os.path.dirname(seen["variable"])
        self.assertEqual(seen["tilde"], os.path.join(scratch, "user"))
        self.assertNotEqual(seen["tilde"], self.user_home)

    def test_it_never_reads_the_users_journals(self):
        from engine.curation import CurationWorker
        journals = os.path.join(self.user_home, ".hermes", "commons", "journals")
        os.makedirs(journals)
        with open(os.path.join(journals, "note.txt"), "w") as fh:
            fh.write("My locker code is 9 9 9 9 9 9.")
        calls = []
        real = CurationWorker._task_journal_ingest

        def spy(worker, payload):
            calls.append(worker._source_path("~/.hermes/commons/journals/"))
            return real(worker, payload)

        with mock.patch.object(CurationWorker, "_task_journal_ingest", spy):
            code, _, result, out = self.run_canary()
        self.assertEqual((code, result), (0, "PASS"), out)
        self.assertEqual(calls, [], "the canary ingested journals")


# --------------------------------------------------------------------------
# the script as a program
# --------------------------------------------------------------------------

class TestAsAProgram(unittest.TestCase):
    """Run by `/usr/bin/python3 scripts/recall_check.py`, from a checkout and from
    a copy of the plugin directory under a different working directory (an
    installed plugin)."""

    def _run(self, script, cwd, *argv):
        return subprocess.run([sys.executable, str(script)] + list(argv), cwd=str(cwd),
                              env=dict(os.environ), capture_output=True, text=True, timeout=120)

    def test_the_canary_passes_from_a_checkout(self):
        proc = self._run(_SCRIPT, _ROOT.parent, "--canary")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.strip().splitlines()[-1], "PASS")

    def test_the_canary_and_a_report_run_from_an_installed_plugin_directory(self):
        base = os.path.realpath(temp_home(prefix="recall-installed-"))
        plugin = os.path.join(base, "plugins", "chronicle")
        shutil.copytree(str(_ROOT), plugin, ignore=shutil.ignore_patterns(
            "tests", "__pycache__", ".git*", "docs", "assets", "*.md"))
        elsewhere = os.path.join(base, "elsewhere")
        os.makedirs(elsewhere)
        script = os.path.join(plugin, "scripts", "recall_check.py")
        proc = self._run(script, elsewhere, "--canary", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])
        home = os.path.join(base, "hermes", "profiles", "t")
        os.makedirs(home)
        proc = self._run(script, elsewhere, "--home", home)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertTrue(proc.stdout.strip().splitlines()[-1].startswith("FAIL: no Chronicle store"))
        self.assertEqual(os.listdir(home), [], "the report wrote into the profile")


if __name__ == "__main__":
    unittest.main()
