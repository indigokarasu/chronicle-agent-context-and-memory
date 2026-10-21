"""
Chronicle — read-side consumers and standalone scripts resolve paths through
engine/paths.py.

The dashboard, the cache-map writer, the curation worker's source paths and the
standalone scripts each worked out the Hermes home on their own. Four of them
read `$HERMES_HOME` and fell back to `~/.hermes`, which is the wrong store for a
named profile and for a shell that has no variable set. The dashboard also
expanded `~/.hermes` in a configured `db_path` by itself, so it could look at
a different file than the one the runtime wrote.

These tests build two homes under a temp directory,

    <tmp>/.hermes                       the Hermes root (the default profile)
    <tmp>/.hermes/profiles/p            a named profile

and a user home whose own `~/.hermes` is somewhere else (`<tmp>/user/.hermes`),
as it is on a package-managed install. They stand in for the host's
`hermes_constants`, leave `$HERMES_HOME` unset, and check that every consumer
lands in the profile. Anything left in `<tmp>/user/.hermes` is where the old
code looked, so a consumer that still looks there fails.

Fixtures use obviously fake values; every path lives under a temp directory.
"""

import contextlib
import importlib.util
import io
import logging
import os
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from _dashboard_loader import _load
from _tmp_support import has_yaml_parser, temp_home


from engine import cache_map, curation, localdb
from engine.config import Config
from engine.paths import DB_REL
from engine.store import MemoryStore, now_iso

_NEEDS_YAML = unittest.skipUnless(has_yaml_parser(), "no YAML parser (PyYAML or ruamel.yaml) in this Python")

_ROOT = Path(__file__).parent.parent
_PLUGIN_API = _ROOT / "dashboard" / "plugin_api.py"
_SCRIPTS = _ROOT / "scripts"

_CACHE_REL = "commons/data/chronicle/chronicle.cache.md"
_LEGACY_STORE_REL = "commons/db/chronicle.db"      # an older layout the dashboard still finds


def _stub_host(home):
    """A stand-in for the host's `hermes_constants`, answering with `home`."""
    mod = types.ModuleType("hermes_constants")
    mod.get_hermes_home = lambda: Path(home)
    return mod


def _make_db(path, rows=1):
    """A small SQLite file with an `events` table holding `rows` rows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE events (event_id TEXT PRIMARY KEY, body TEXT)")
        for i in range(rows):
            conn.execute("INSERT INTO events VALUES (?, ?)", ("e%d" % i, "fake body"))
        conn.commit()
    finally:
        conn.close()


def _make_store(path):
    """A real Chronicle store (full schema) holding one event."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    store = MemoryStore(path)
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO events(event_id, seq, type, payload, actor, owner, "
            "trust_level, session_id, occurred_at, recorded_at) "
            "VALUES('e0', 1, 'observed', '{}', 'user', 'default', 3, 's1', ?, ?)",
            (now_iso(), now_iso()))
    try:
        store.close()
    except Exception:
        pass


def _write_config(home, text):
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "config.yaml"), "w") as fh:
        fh.write(text)


def _load_script(name):
    """Import scripts/<name>.py by path (scripts/ is not a package).

    embedding_check lowers the level of the shared "chronicle" logger on import,
    which would silence the warnings other modules assert on, so it is put back."""
    chronicle_log = logging.getLogger("chronicle")
    level = chronicle_log.level
    try:
        spec = importlib.util.spec_from_file_location("readside_script_" + name,
                                                      str(_SCRIPTS / (name + ".py")))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        chronicle_log.setLevel(level)
    return mod


class _ProfileCase(unittest.TestCase):
    """Fake user home, a Hermes root and a profile home; the host answers `profile`
    and `$HERMES_HOME` is unset (a shell that never exported it)."""

    def setUp(self):
        self.tmp = os.path.realpath(temp_home())
        self.user_home = os.path.join(self.tmp, "user")
        # What `~/.hermes` means to the old code. Not the Hermes root.
        self.user_hermes = os.path.join(self.user_home, ".hermes")
        self.root = os.path.join(self.tmp, ".hermes")
        self.profile = os.path.join(self.root, "profiles", "p")
        os.makedirs(self.profile)
        env = mock.patch.dict(os.environ, {"HOME": self.user_home})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("HERMES_HOME", None)
        self.host_as(self.profile)

    def host_as(self, home):
        """The host reports `home` as the Hermes home from now on."""
        patcher = mock.patch.dict(sys.modules, {"hermes_constants": _stub_host(home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def dashboard(self):
        return _load("readside_plugin_api", _PLUGIN_API)


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

class TestDashboardHome(_ProfileCase):
    def test_home_follows_the_host_when_the_variable_is_unset(self):
        self.host_as(self.root)
        mod = self.dashboard()
        self.assertEqual(mod._profile_home("p"), Path(self.profile))

    def test_a_host_that_reports_a_profile_still_finds_the_root_and_its_siblings(self):
        # The dashboard can be started as a profile; `profile=` then selects among
        # the profiles of the SAME root, not under the profile's own directory.
        os.makedirs(os.path.join(self.root, "profiles", "q"))
        mod = self.dashboard()
        self.assertEqual(mod._profile_home("q"), Path(self.root, "profiles", "q"))
        self.assertEqual(mod._profile_home("default"), Path(self.root))
        self.assertEqual(mod._profile_home(None), Path(self.root))

    def test_an_unknown_profile_falls_back_to_the_root(self):
        mod = self.dashboard()
        self.assertEqual(mod._profile_home("nope"), Path(self.root))

    def test_explicit_environment_is_used_when_the_host_is_absent(self):
        # The offline harness (no hermes_constants) still works through the variable.
        with mock.patch.dict(sys.modules, {"hermes_constants": None}):
            os.environ["HERMES_HOME"] = self.root
            mod = self.dashboard()
            self.assertEqual(mod._profile_home("p"), Path(self.profile))


@_NEEDS_YAML
class TestDashboardStore(_ProfileCase):
    def test_picks_the_profiles_store_not_the_roots(self):
        _make_db(os.path.join(self.root, DB_REL), rows=3)
        _make_db(os.path.join(self.profile, DB_REL), rows=1)
        mod = self.dashboard()
        self.assertEqual(mod._get_db_path("p"), Path(self.profile, DB_REL))
        self.assertEqual(mod._get_db_path(None), Path(self.root, DB_REL))

    def test_a_db_path_that_names_the_profile_twice_still_finds_the_profile_store(self):
        # What a config written for the root looks like once copied to a profile.
        # The old expansion looked in `<profile>/profiles/p/...`, which is empty.
        _write_config(self.profile, "memory:\n  db_path: ~/.hermes/profiles/p/custom/chronicle.db\n")
        _make_db(os.path.join(self.profile, "custom", "chronicle.db"))
        _make_db(os.path.join(self.root, DB_REL))
        self.assertEqual(self.dashboard()._get_db_path("p"),
                         Path(self.profile, "custom", "chronicle.db"))

    def test_an_absolute_db_path_is_honoured(self):
        elsewhere = os.path.join(self.tmp, "elsewhere", "chronicle.db")
        _make_db(elsewhere)
        _write_config(self.profile, "memory:\n  db_path: %s\n" % elsewhere)
        self.assertEqual(self.dashboard()._get_db_path("p"), Path(elsewhere))

    def test_a_store_still_at_the_old_default_is_found_before_it_is_migrated(self):
        # 5.11.1 ignored an absolute `db_path` and wrote to the default location.
        # Until the store is moved, that old file is the one with the data.
        elsewhere = os.path.join(self.tmp, "elsewhere", "chronicle.db")
        _write_config(self.profile, "memory:\n  db_path: %s\n" % elsewhere)
        _make_db(os.path.join(self.profile, DB_REL), rows=4)
        self.assertEqual(self.dashboard()._get_db_path("p"), Path(self.profile, DB_REL))

    def test_an_empty_new_store_does_not_hide_the_old_one_with_data(self):
        new = os.path.join(self.tmp, "new-place", "chronicle.db")
        _make_db(new, rows=0)
        _make_db(os.path.join(self.profile, DB_REL), rows=2)
        _write_config(self.profile, "memory:\n  db_path: %s\n" % new)
        self.assertEqual(self.dashboard()._get_db_path("p"), Path(self.profile, DB_REL))

    def test_the_new_store_wins_once_it_holds_data(self):
        new = os.path.join(self.tmp, "new-place", "chronicle.db")
        _make_db(new, rows=1)
        _make_db(os.path.join(self.profile, DB_REL), rows=9)
        _write_config(self.profile, "memory:\n  db_path: %s\n" % new)
        self.assertEqual(self.dashboard()._get_db_path("p"), Path(new))

    def test_the_older_layouts_are_still_searched(self):
        _make_db(os.path.join(self.profile, _LEGACY_STORE_REL))
        self.assertEqual(self.dashboard()._get_db_path("p"),
                         Path(self.profile, _LEGACY_STORE_REL))

    def test_no_store_anywhere_is_none(self):
        self.assertIsNone(self.dashboard()._get_db_path("p"))

    def test_an_unreadable_config_does_not_hide_the_default_store(self):
        _write_config(self.profile, "memory: [this is: not valid\n")
        _make_db(os.path.join(self.profile, DB_REL))
        self.assertEqual(self.dashboard()._get_db_path("p"), Path(self.profile, DB_REL))


# --------------------------------------------------------------------------
# cache map
# --------------------------------------------------------------------------

class TestCacheMapPath(_ProfileCase):
    def cfg(self, path=None):
        return Config({"cache_map": {"path": path}} if path is not None else {})

    def test_default_lands_under_the_profile(self):
        self.assertEqual(cache_map.resolve_path(self.profile, self.cfg()),
                         os.path.join(self.profile, _CACHE_REL))

    def test_a_home_prefixed_path_follows_the_profile(self):
        got = cache_map.resolve_path(self.profile, self.cfg("~/.hermes/commons/data/x.md"))
        self.assertEqual(got, os.path.join(self.profile, "commons/data/x.md"))

    def test_a_path_that_names_the_profile_twice_is_not_doubled(self):
        got = cache_map.resolve_path(
            self.profile, self.cfg("~/.hermes/profiles/p/commons/data/x.md"))
        self.assertEqual(got, os.path.join(self.profile, "commons/data/x.md"))

    def test_an_environment_style_path_follows_the_profile(self):
        got = cache_map.resolve_path(self.profile, self.cfg("$HERMES_HOME/commons/data/x.md"))
        self.assertEqual(got, os.path.join(self.profile, "commons/data/x.md"))

    def test_absolute_and_other_home_paths_keep_their_meaning(self):
        self.assertEqual(
            cache_map.resolve_path(self.profile, self.cfg(os.path.join(self.tmp, "x.md"))),
            os.path.join(self.tmp, "x.md"))
        self.assertEqual(
            cache_map.resolve_path(self.profile, self.cfg("~/notes/x.md")),
            os.path.join(self.user_home, "notes", "x.md"))

    def test_a_relative_path_is_under_the_home_not_the_working_directory(self):
        self.assertEqual(cache_map.resolve_path(self.profile, self.cfg("maps/x.md")),
                         os.path.join(self.profile, "maps", "x.md"))

    def test_no_home_means_the_resolved_home_not_the_working_directory(self):
        self.assertEqual(cache_map.resolve_path("", self.cfg()),
                         os.path.join(self.profile, _CACHE_REL))
        self.assertEqual(cache_map.resolve_path(None, None),
                         os.path.join(self.profile, _CACHE_REL))


# --------------------------------------------------------------------------
# curation: journal and federation source paths
# --------------------------------------------------------------------------

class _Capture:
    def __init__(self):
        self.calls = []

    def append(self, kind, payload, **kw):
        self.calls.append((kind, payload, kw))


class _Reached(Exception):
    """Raised by the stand-in for `_open_local_db` so the test sees the path and stops."""


def _worker(home, cfg):
    worker = curation.CurationWorker.__new__(curation.CurationWorker)
    worker.core = types.SimpleNamespace(hermes_home=home, capture=_Capture())
    worker.cfg = cfg
    worker.store = None
    return worker


def _journal_cfg(*paths):
    return Config({"sources": {"ocas_journals": {"paths": list(paths)}}})


class TestCurationSourcePaths(_ProfileCase):
    def _write(self, directory, name="entry.txt", text="fixture entry"):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, name), "w") as fh:
            fh.write(text)

    def refs(self, worker):
        return [c[1]["source_ref"] for c in worker.core.capture.calls]

    def test_a_home_prefixed_journal_path_lands_under_the_profile(self):
        self._write(os.path.join(self.profile, "journals"))
        self._write(os.path.join(self.user_hermes, "journals"), text="the old meaning's entry")
        worker = _worker(self.profile, _journal_cfg("~/.hermes/journals"))
        worker._task_journal_ingest({})
        self.assertEqual(self.refs(worker),
                         [os.path.join(self.profile, "journals", "entry.txt")])

    def test_a_path_that_names_the_profile_twice_is_not_doubled(self):
        self._write(os.path.join(self.profile, "journals"))
        worker = _worker(self.profile, _journal_cfg("~/.hermes/profiles/p/journals"))
        worker._task_journal_ingest({})
        self.assertEqual(self.refs(worker),
                         [os.path.join(self.profile, "journals", "entry.txt")])

    def test_the_default_journal_path_keeps_its_old_meaning_until_the_profile_has_its_own(self):
        # 5.11.1 expanded `~` against the user's home, so the default
        # `~/.hermes/commons/journals/` was the user's directory even under a
        # profile. Skipping it now would silently stop the ingest.
        self._write(os.path.join(self.user_hermes, "commons", "journals"))
        worker = _worker(self.profile, Config({}))
        worker._task_journal_ingest({})
        self.assertEqual(self.refs(worker),
                         [os.path.join(self.user_hermes, "commons", "journals", "entry.txt")])

    def test_the_profiles_own_default_journal_directory_wins_when_it_exists(self):
        self._write(os.path.join(self.user_hermes, "commons", "journals"), text="old meaning")
        self._write(os.path.join(self.profile, "commons", "journals"), name="mine.txt")
        worker = _worker(self.profile, Config({}))
        worker._task_journal_ingest({})
        self.assertEqual(self.refs(worker),
                         [os.path.join(self.profile, "commons", "journals", "mine.txt")])

    def test_an_empty_entry_is_skipped_not_read_as_the_home(self):
        self._write(self.profile, name="config-like.txt")
        worker = _worker(self.profile, _journal_cfg("", "   "))
        worker._task_journal_ingest({})
        self.assertEqual(worker.core.capture.calls, [])

    def test_a_core_without_a_home_uses_the_resolved_home(self):
        self._write(os.path.join(self.profile, "journals"))
        worker = _worker(None, _journal_cfg("~/.hermes/journals"))
        worker._task_journal_ingest({})
        self.assertEqual(self.refs(worker),
                         [os.path.join(self.profile, "journals", "entry.txt")])

    def _federate(self, worker, path):
        spec = {"name": "src", "path": path, "table": "t", "content_columns": ["c"]}

        def reached(p, read_only=True):
            raise _Reached(p)

        with mock.patch.object(curation.CurationWorker, "_open_local_db", staticmethod(reached)):
            with self.assertRaises(_Reached) as caught:
                worker._federate_db(spec)
        return str(caught.exception)

    def test_a_federated_database_is_swept_where_the_query_side_reads_it(self):
        # `federation.local_dbs[].path` has two readers: this sweep, which projects
        # the rows into pointers, and `localdb.providers_from_config`, which serves
        # them at query time. If they resolve `~/.hermes/...` differently, a
        # profile that has its own copy of the file projects ids from one database
        # and answers from the other, so a record carries another database's content.
        self._write(os.path.join(self.profile, "data"), name="src.db", text="")
        self._write(os.path.join(self.user_hermes, "data"), name="src.db", text="")
        entry = {"name": "src", "path": "~/.hermes/data/src.db", "table": "t",
                 "content_columns": ["c"]}
        served = localdb.providers_from_config(
            Config({"federation": {"local_dbs": [entry]}}))[0].db_path
        worker = _worker(self.profile, Config({}))
        swept = self._federate(worker, entry["path"])
        self.assertEqual(swept, served)
        self.assertEqual(swept, os.path.join(self.user_hermes, "data", "src.db"))

    def test_a_missing_federated_database_is_reported_where_the_query_side_would_look(self):
        worker = _worker(self.profile, Config({}))
        spec = {"name": "src", "path": "~/.hermes/data/src.db", "table": "t",
                "content_columns": ["c"]}
        with self.assertRaises(curation._ProviderOffline) as caught:
            worker._federate_db(spec)
        self.assertIn(os.path.join(self.user_hermes, "data", "src.db"), str(caught.exception))


# --------------------------------------------------------------------------
# scripts
# --------------------------------------------------------------------------

class _ScriptCase(_ProfileCase):
    """A profile with its own config and store. The Hermes root has its own, and
    the user's `~/.hermes` (where the old code looked) holds a decoy config."""

    def setUp(self):
        super().setUp()
        _write_config(self.profile, "memory:\n  cache_map:\n    max_chars: 1234\n")
        _write_config(self.root, "memory:\n  cache_map:\n    max_chars: 5555\n")
        _write_config(self.user_hermes, "memory:\n  cache_map:\n    max_chars: 9999\n")
        self.profile_db = os.path.join(self.profile, DB_REL)
        self.root_db = os.path.join(self.root, DB_REL)

    def run_main(self, mod, *argv):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", [mod.__name__] + list(argv)):
            with contextlib.redirect_stdout(out):
                rc = mod.main()
        return rc, out.getvalue()


@_NEEDS_YAML
class TestScriptConfigHome(_ScriptCase):
    """`load_config` reads the host's home, with HERMES_HOME unset."""

    def test_embedding_check(self):
        cfg = _load_script("embedding_check")._load_config()
        self.assertEqual(cfg.get("cache_map.max_chars"), 1234)

    def test_migrate_vectors(self):
        self.assertEqual(_load_script("migrate_vectors").load_config().get("cache_map.max_chars"), 1234)

    def test_writeback_vectors(self):
        self.assertEqual(_load_script("writeback_vectors").load_config().get("cache_map.max_chars"), 1234)

    def test_the_variable_is_still_honoured_without_a_host(self):
        with mock.patch.dict(sys.modules, {"hermes_constants": None}):
            os.environ["HERMES_HOME"] = self.root
            self.assertEqual(
                _load_script("migrate_vectors").load_config().get("cache_map.max_chars"), 5555)


class TestMigrateVectorsStore(_ScriptCase):
    def run_with_recorder(self, *argv):
        mod = _load_script("migrate_vectors")
        seen = {}

        def fake_migrate(db_path, **kw):
            seen["db"] = db_path
            return 0

        with mock.patch.object(mod, "migrate", fake_migrate):
            rc, out = self.run_main(mod, *argv)
        return rc, seen.get("db"), out

    def test_no_argument_uses_the_stores_of_the_active_home(self):
        _make_db(self.profile_db)
        _make_db(self.root_db)
        rc, db, _ = self.run_with_recorder()
        self.assertEqual((rc, db), (0, self.profile_db))

    def test_a_store_still_at_the_old_location_is_used(self):
        elsewhere = os.path.join(self.tmp, "elsewhere", "chronicle.db")
        _write_config(self.profile, "memory:\n  db_path: %s\n" % elsewhere)
        _make_db(self.profile_db)
        rc, db, _ = self.run_with_recorder()
        self.assertEqual((rc, db), (0, self.profile_db))

    def test_an_explicit_database_wins(self):
        _make_db(self.profile_db)
        rc, db, _ = self.run_with_recorder("/explicit/chronicle.db")
        self.assertEqual((rc, db), (0, "/explicit/chronicle.db"))

    def test_no_store_anywhere_is_an_error_not_an_empty_database(self):
        rc, out = self.run_main(_load_script("migrate_vectors"))
        self.assertEqual(rc, 1)
        self.assertIn(self.profile_db, out)
        self.assertFalse(os.path.exists(self.profile_db))


@_NEEDS_YAML
class TestBuildCacheMap(_ScriptCase):
    def test_no_arguments_builds_the_active_homes_map(self):
        _make_store(self.profile_db)
        rc, out = self.run_main(_load_script("build_cache_map"))
        self.assertEqual(rc, 0, out)
        written = os.path.join(self.profile, _CACHE_REL)
        self.assertTrue(os.path.isfile(written), out)
        self.assertFalse(os.path.exists(os.path.join(self.root, _CACHE_REL)))

    def test_the_database_is_the_one_the_config_names(self):
        custom = os.path.join(self.profile, "custom", "chronicle.db")
        _write_config(self.profile, "memory:\n  db_path: ~/.hermes/custom/chronicle.db\n")
        _make_store(custom)
        rc, out = self.run_main(_load_script("build_cache_map"))
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.profile, _CACHE_REL)), out)

    def test_a_store_still_where_an_old_release_wrote_it_is_used(self):
        # 5.11.1 turned a `db_path` that names the profile twice into
        # `<profile>/profiles/p/...` and wrote the store there.
        _write_config(self.profile,
                      "memory:\n  db_path: ~/.hermes/profiles/p/custom/chronicle.db\n")
        _make_store(os.path.join(self.profile, "profiles", "p", "custom", "chronicle.db"))
        rc, out = self.run_main(_load_script("build_cache_map"))
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.profile, _CACHE_REL)), out)

    def test_explicit_home_config_and_db_win(self):
        other = os.path.join(self.tmp, "other-home")
        decoy_db = os.path.join(self.tmp, "explicit", "chronicle.db")
        _make_store(decoy_db)
        config = os.path.join(self.tmp, "explicit.yaml")
        with open(config, "w") as fh:
            fh.write("memory: {}\n")
        rc, out = self.run_main(_load_script("build_cache_map"),
                                "--home", other, "--config", config, "--db", decoy_db)
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(other, _CACHE_REL)), out)
        self.assertFalse(os.path.exists(os.path.join(self.profile, _CACHE_REL)))

    def test_a_home_without_a_config_uses_the_defaults(self):
        os.unlink(os.path.join(self.profile, "config.yaml"))
        _make_store(self.profile_db)
        rc, out = self.run_main(_load_script("build_cache_map"))
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.profile, _CACHE_REL)), out)

    def test_a_config_that_was_named_must_exist(self):
        _make_store(self.profile_db)
        with self.assertRaises(FileNotFoundError):
            self.run_main(_load_script("build_cache_map"),
                          "--config", os.path.join(self.tmp, "missing.yaml"))

    def test_no_store_is_an_error_not_an_empty_map(self):
        rc, out = self.run_main(_load_script("build_cache_map"))
        self.assertNotEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(self.profile, _CACHE_REL)))


@_NEEDS_YAML
class TestBuildMentions(_ScriptCase):
    def test_no_arguments_reads_the_active_homes_store(self):
        _make_store(self.profile_db)
        rc, out = self.run_main(_load_script("build_mentions"), "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("entities with identifiers", out)

    def test_the_home_default_is_the_resolved_home(self):
        mod = _load_script("build_mentions")
        with mock.patch.object(sys, "argv", ["build_mentions.py", "--dry-run"]):
            args = mod.parse_args()
        self.assertEqual(args.home, self.profile)
        self.assertEqual(args.db, self.profile_db)

    def test_the_default_database_follows_the_config_and_the_old_location(self):
        mod = _load_script("build_mentions")

        def db_for(config_text):
            _write_config(self.profile, config_text)
            with mock.patch.object(sys, "argv", ["build_mentions.py", "--dry-run"]):
                return mod.parse_args().db

        custom = os.path.join(self.profile, "custom", "chronicle.db")
        _make_db(custom)
        self.assertEqual(db_for("memory:\n  db_path: ~/.hermes/custom/chronicle.db\n"), custom)
        # named twice: a store written by an old release is at the doubled path
        doubled = os.path.join(self.profile, "profiles", "p", "twice", "chronicle.db")
        _make_db(doubled)
        self.assertEqual(
            db_for("memory:\n  db_path: ~/.hermes/profiles/p/twice/chronicle.db\n"), doubled)

    def test_explicit_home_and_db_win(self):
        mod = _load_script("build_mentions")
        argv = ["build_mentions.py", "--home", self.tmp, "--db", "/explicit/c.db", "--dry-run"]
        with mock.patch.object(sys, "argv", argv):
            args = mod.parse_args()
        self.assertEqual((args.home, args.db), (self.tmp, "/explicit/c.db"))

    def test_bind_events_go_to_the_store_that_was_read(self):
        mod = _load_script("build_mentions")
        other = os.path.join(self.tmp, "other-home")
        decoy = os.path.join(self.tmp, "decoy-home")

        def args(*argv):
            with mock.patch.object(sys, "argv", ["build_mentions.py"] + list(argv)):
                return mod.parse_args()

        # a store at the standard place and no --home: that store's own home
        self.assertEqual(mod.bind_home(args("--db", os.path.join(other, DB_REL))), other)
        # --home wins
        self.assertEqual(
            mod.bind_home(args("--db", os.path.join(other, DB_REL), "--home", decoy)), decoy)
        # a store somewhere else cannot say which home it belongs to
        self.assertEqual(mod.bind_home(args("--db", os.path.join(other, "c.db"))), self.profile)
        # no --db: the active home
        self.assertEqual(mod.bind_home(args()), self.profile)

    def test_no_store_is_an_error_not_an_empty_database(self):
        rc, out = self.run_main(_load_script("build_mentions"))
        self.assertNotEqual(rc, 0)
        self.assertFalse(os.path.exists(self.profile_db))


@_NEEDS_YAML
class TestPrefetchEval(_ScriptCase):
    def test_a_bare_run_evaluates_the_active_home(self):
        mod = _load_script("prefetch_eval")
        _write_config(self.profile, "memory:\n  cache_map:\n    max_chars: 1234\n")
        _make_db(self.profile_db)
        seen = {}

        def fake_engine(config_path, store_path, with_embedder=False):
            seen["args"] = (config_path, store_path)
            return object()

        with mock.patch.object(mod, "_engine_for", fake_engine), \
                mock.patch.object(mod, "evaluate", lambda core, questions: None):
            rc = mod.main([])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["args"],
                         (os.path.join(self.profile, "config.yaml"), self.profile_db))

    def test_the_default_store_follows_the_config(self):
        mod = _load_script("prefetch_eval")
        custom = os.path.join(self.profile, "custom", "chronicle.db")
        _write_config(self.profile, "memory:\n  db_path: ~/.hermes/custom/chronicle.db\n")
        _make_db(custom)
        seen = {}

        def fake_engine(config_path, store_path, with_embedder=False):
            seen["store"] = store_path
            return object()

        with mock.patch.object(mod, "_engine_for", fake_engine), \
                mock.patch.object(mod, "evaluate", lambda core, questions: None):
            self.assertEqual(mod.main([]), 0)
        self.assertEqual(seen["store"], custom)

    def test_a_bare_run_without_a_store_says_so(self):
        mod = _load_script("prefetch_eval")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(mod.main([]), 2)
        self.assertIn(self.profile_db, err.getvalue())

    def test_home_flag_picks_the_home_for_the_defaults(self):
        mod = _load_script("prefetch_eval")
        other = os.path.join(self.tmp, "other-home")
        other_db = os.path.join(other, DB_REL)
        _write_config(other, "memory: {}\n")
        _make_db(other_db)
        seen = {}

        def fake_engine(config_path, store_path, with_embedder=False):
            seen["args"] = (config_path, store_path)
            return object()

        with mock.patch.object(mod, "_engine_for", fake_engine), \
                mock.patch.object(mod, "evaluate", lambda core, questions: None):
            rc = mod.main(["--home", other])
        self.assertEqual((rc, seen["args"]), (0, (os.path.join(other, "config.yaml"), other_db)))

    def test_explicit_paths_win(self):
        mod = _load_script("prefetch_eval")
        seen = {}

        def fake_engine(config_path, store_path, with_embedder=False):
            seen["args"] = (config_path, store_path)
            return object()

        with mock.patch.object(mod, "_engine_for", fake_engine), \
                mock.patch.object(mod, "evaluate", lambda core, questions: None):
            rc = mod.main(["c.yaml", "s.db"])
        self.assertEqual((rc, seen["args"]), (0, ("c.yaml", "s.db")))

    def test_one_path_alone_is_a_usage_error(self):
        mod = _load_script("prefetch_eval")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mod.main(["c.yaml"]), 2)

    def test_the_evaluation_never_mirrors_to_git(self):
        # The store path is passed as the core's home (see `_engine_for`), so the
        # git mirror would resolve to a directory inside a file and, worse, queue
        # the evaluated store for export. An evaluation writes nothing.
        mod = _load_script("prefetch_eval")
        cfg_file = os.path.join(self.tmp, "eval.yaml")
        with open(cfg_file, "w") as fh:
            fh.write("memory:\n  git:\n    enabled: true\n    max_commit_rows: 7\n")
        seen = {}

        def fake_get(home, cfg, embedder_probe=None):
            seen["home"], seen["cfg"] = home, cfg
            return object()

        with mock.patch.object(mod.ChronicleCore, "get", staticmethod(fake_get)):
            mod._engine_for(cfg_file, "/some/store.db")
        self.assertEqual(seen["home"], "/some/store.db")
        self.assertEqual(seen["cfg"]["db_path"], "~/.hermes")
        self.assertIs(seen["cfg"]["git"]["enabled"], False)
        self.assertEqual(seen["cfg"]["git"]["max_commit_rows"], 7)


# --------------------------------------------------------------------------
# no consumer reads the variable itself
# --------------------------------------------------------------------------

class TestNoDirectEnvironmentReads(unittest.TestCase):
    """The variable is read in one place (engine/paths.py). A copy elsewhere is
    how a profile ended up with the root's store."""

    def test_no_consumer_reads_hermes_home_from_the_environment(self):
        needle = 'environ.get("HERMES_HOME"'
        offenders = []
        for sub in ("dashboard", "engine", "scripts"):
            for path in sorted((_ROOT / sub).rglob("*.py")):
                rel = path.relative_to(_ROOT).as_posix()
                if rel == "engine/paths.py" or "node_modules" in rel:
                    continue
                if needle in path.read_text(encoding="utf-8"):
                    offenders.append(rel)
        self.assertEqual(offenders, [])


class TestNoServerPathsInScripts(unittest.TestCase):
    """The scripts ship in a public repository and run from a checkout anywhere.
    A path to one machine's install does nothing on any other and names a host
    layout that is not the project's to publish."""

    def test_no_script_names_an_absolute_install_path(self):
        offenders = []
        for path in sorted(_SCRIPTS.glob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if '"/root' in line or "'/root" in line:
                    offenders.append("%s:%d" % (path.name, number))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
