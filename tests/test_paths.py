"""
Chronicle — home and data-path resolution (engine/paths.py).

Before this module each consumer worked the paths out on its own: the store,
the git mirror, the dashboard and the scripts each had a copy of the rules, and
the copies disagreed. Under a profile home (`<root>/profiles/<name>`) a
`db_path` written as `~/.hermes/profiles/<name>/...` was doubled into
`.../profiles/<name>/profiles/<name>/...`, an absolute `db_path` was silently
ignored, and the git mirror never looked at the profile at all. These tests pin
the one set of rules every consumer now shares, plus exact copies of the old
rules, which the migration needs to find where an older release put the data.

Fixtures use obviously fake values; every path lives under a temp directory.
"""

import logging
import os
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine import paths
from engine.paths import (
    DB_REL,
    GIT_REL,
    expand_data_path,
    has_data,
    legacy_db_path,
    legacy_git_path,
    profile_root,
    readable_db_path,
    resolve_home,
)


def _v5111_db_path(value, hermes_home):
    """The 5.11.1 store-path expression, copied verbatim as the reference."""
    db_path = value or str(Path(hermes_home) / "commons/db/chronicle/chronicle.db")
    db_path = db_path.replace("~/.hermes", str(Path(hermes_home))) if db_path.startswith("~/.hermes") \
        else str(Path(hermes_home) / "commons/db/chronicle/chronicle.db")
    return db_path


def _v5111_git_path(cfg):
    """The 5.11.1 git-mirror path expression, copied verbatim as the reference."""
    return os.path.expanduser(cfg.get("git_repo", "~/.hermes/commons/db/chronicle/git"))


def _stub_host(get_hermes_home=None, *, raises=None):
    """A stand-in for the host's `hermes_constants` module."""
    mod = types.ModuleType("hermes_constants")
    if raises is not None:
        def _boom():
            raise raises
        mod.get_hermes_home = _boom
    elif get_hermes_home is not None:
        mod.get_hermes_home = get_hermes_home
    return mod


def _make_db(path, *, events_table=True, rows=0, wal=False):
    """Build a small SQLite file; returns nothing, closes its connection."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        if events_table:
            conn.execute("CREATE TABLE events (event_id TEXT PRIMARY KEY, body TEXT)")
            for i in range(rows):
                conn.execute("INSERT INTO events VALUES (?, ?)", ("e%d" % i, "fake body"))
        else:
            conn.execute("CREATE TABLE other (x INTEGER)")
            conn.execute("INSERT INTO other VALUES (1)")
        conn.commit()
    finally:
        conn.close()


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class _HomeCase(unittest.TestCase):
    """A fake user home and a fake Hermes home (plain and profile shapes)."""

    def setUp(self):
        self.tmp = os.path.realpath(temp_home())
        self.user_home = os.path.join(self.tmp, "user")
        self.root = os.path.join(self.user_home, ".hermes")
        self.profile = os.path.join(self.root, "profiles", "coder")
        os.makedirs(self.profile)
        env = mock.patch.dict(os.environ, {"HOME": self.user_home})
        env.start()
        self.addCleanup(env.stop)
        paths.reset_warnings()
        self.addCleanup(paths.reset_warnings)
        self.cap = _Capture()
        log = logging.getLogger("chronicle.paths")
        log.addHandler(self.cap)
        self.addCleanup(log.removeHandler, self.cap)

    def warnings(self):
        return [r for r in self.cap.records if r.levelno >= logging.WARNING]


# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_relative_locations(self):
        self.assertEqual(DB_REL, "commons/db/chronicle/chronicle.db")
        self.assertEqual(GIT_REL, "commons/db/chronicle/git")


# --------------------------------------------------------------------------
# resolve_home
# --------------------------------------------------------------------------

class TestResolveHome(_HomeCase):
    """Precedence: explicit > host constant > $HERMES_HOME > ~/.hermes."""

    def setUp(self):
        super().setUp()
        self.host_home = os.path.join(self.tmp, "host-home")
        self.env_home = os.path.join(self.tmp, "env-home")
        # No host module unless a test installs one: `None` in sys.modules
        # makes the import raise, which is what an offline run looks like.
        mods = mock.patch.dict(sys.modules, {"hermes_constants": None})
        mods.start()
        self.addCleanup(mods.stop)

    def _host(self, mod):
        sys.modules["hermes_constants"] = mod

    def _env(self, value):
        if value is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = value

    # 1. explicit
    def test_explicit_wins_over_host_and_env(self):
        self._host(_stub_host(lambda: Path(self.host_home)))
        self._env(self.env_home)
        explicit = os.path.join(self.tmp, "explicit")
        self.assertEqual(resolve_home(explicit), explicit)

    def test_explicit_expands_user(self):
        self._env(self.env_home)
        self.assertEqual(resolve_home("~/hh"), os.path.join(self.user_home, "hh"))

    def test_explicit_expands_vars(self):
        self._env(self.env_home)
        with mock.patch.dict(os.environ, {"CHRONICLE_TEST_HOME_DIR": self.tmp}):
            self.assertEqual(resolve_home("$CHRONICLE_TEST_HOME_DIR/h"),
                             os.path.join(self.tmp, "h"))
            self.assertEqual(resolve_home("${CHRONICLE_TEST_HOME_DIR}/h"),
                             os.path.join(self.tmp, "h"))

    def test_explicit_var_that_holds_a_tilde(self):
        self._env(self.env_home)
        with mock.patch.dict(os.environ, {"CHRONICLE_TEST_HOME_DIR": "~/via-var"}):
            self.assertEqual(resolve_home("$CHRONICLE_TEST_HOME_DIR"),
                             os.path.join(self.user_home, "via-var"))

    def test_explicit_is_normalized_and_absolute(self):
        self._env(self.env_home)
        messy = self.tmp + "/a/./b/../c/"
        self.assertEqual(resolve_home(messy), os.path.join(self.tmp, "a", "c"))
        rel = resolve_home("relative-home")
        self.assertTrue(os.path.isabs(rel))
        self.assertEqual(rel, os.path.join(os.getcwd(), "relative-home"))

    def test_explicit_accepts_a_path_object(self):
        self._env(None)
        self.assertEqual(resolve_home(Path(self.tmp) / "p"), os.path.join(self.tmp, "p"))

    def test_empty_explicit_falls_through(self):
        self._host(_stub_host(lambda: Path(self.host_home)))
        self._env(self.env_home)
        self.assertEqual(resolve_home(""), self.host_home)
        self.assertEqual(resolve_home(None), self.host_home)
        self.assertEqual(resolve_home(), self.host_home)

    # 2. host constant
    def test_host_override_wins_over_env(self):
        self._host(_stub_host(lambda: Path(self.host_home)))
        self._env(self.env_home)
        self.assertEqual(resolve_home(), self.host_home)

    def test_host_returning_a_string(self):
        self._host(_stub_host(lambda: self.host_home + "/"))
        self._env(None)
        self.assertEqual(resolve_home(), self.host_home)

    def test_host_raising_skips_to_env(self):
        self._host(_stub_host(raises=RuntimeError("host not configured")))
        self._env(self.env_home)
        self.assertEqual(resolve_home(), self.env_home)

    def test_host_missing_function_skips_to_env(self):
        self._host(types.ModuleType("hermes_constants"))
        self._env(self.env_home)
        self.assertEqual(resolve_home(), self.env_home)

    def test_host_import_failing_skips_to_env(self):
        # setUp already made the import raise.
        self._env(self.env_home)
        self.assertEqual(resolve_home(), self.env_home)

    def test_host_returning_nothing_skips_to_env(self):
        self._host(_stub_host(lambda: None))
        self._env(self.env_home)
        self.assertEqual(resolve_home(), self.env_home)

    # 3. $HERMES_HOME
    def test_env_is_normalized_and_expanded(self):
        self._env(self.env_home + "//")
        self.assertEqual(resolve_home(), self.env_home)
        self._env("~/from-env")
        self.assertEqual(resolve_home(), os.path.join(self.user_home, "from-env"))

    def test_env_relative_becomes_absolute(self):
        self._env("rel-env")
        self.assertEqual(resolve_home(), os.path.join(os.getcwd(), "rel-env"))

    # 4. ~/.hermes
    def test_env_unset_gives_dot_hermes(self):
        self._env(None)
        self.assertEqual(resolve_home(), self.root)

    def test_env_empty_gives_dot_hermes(self):
        self._env("")
        self.assertEqual(resolve_home(), self.root)

    def test_host_failing_and_env_unset_gives_dot_hermes(self):
        self._host(_stub_host(raises=OSError("no home")))
        self._env(None)
        self.assertEqual(resolve_home(), self.root)


# --------------------------------------------------------------------------
# expand_data_path
# --------------------------------------------------------------------------

class TestExpandDataPath(_HomeCase):
    def test_empty_gives_default(self):
        for value in (None, "", "   ", "\n"):
            with self.subTest(value=value):
                self.assertEqual(expand_data_path(value, self.root, DB_REL),
                                 os.path.join(self.root, DB_REL))
        self.assertEqual(expand_data_path(None, self.profile, GIT_REL),
                         os.path.join(self.profile, GIT_REL))

    def test_home_prefix_alone_is_the_home(self):
        for value in ("~/.hermes", "$HERMES_HOME", "${HERMES_HOME}",
                      "~/.hermes/", "$HERMES_HOME/", "${HERMES_HOME}/", "  ~/.hermes  "):
            with self.subTest(value=value):
                self.assertEqual(expand_data_path(value, self.profile, DB_REL), self.profile)

    def test_home_prefix_with_rest(self):
        want = os.path.join(self.profile, "commons/x/chronicle.db")
        for value in ("~/.hermes/commons/x/chronicle.db",
                      "$HERMES_HOME/commons/x/chronicle.db",
                      "${HERMES_HOME}/commons/x/chronicle.db",
                      "  ~/.hermes/commons/x/chronicle.db\t"):
            with self.subTest(value=value):
                self.assertEqual(expand_data_path(value, self.profile, DB_REL), want)

    def test_home_prefix_means_the_resolved_home_not_the_env(self):
        # `$HERMES_HOME` in a value names the home we were handed, whatever the
        # environment variable happens to hold in this process.
        with mock.patch.dict(os.environ, {"HERMES_HOME": os.path.join(self.tmp, "elsewhere")}):
            self.assertEqual(expand_data_path("$HERMES_HOME/x.db", self.profile, DB_REL),
                             os.path.join(self.profile, "x.db"))

    def test_doubled_slash_after_prefix_stays_inside_home(self):
        self.assertEqual(expand_data_path("~/.hermes//x.db", self.profile, DB_REL),
                         os.path.join(self.profile, "x.db"))

    def test_prefix_needs_a_separator(self):
        # `~/.hermesX` is some other directory under the user's home.
        self.assertEqual(expand_data_path("~/.hermesX/x.db", self.profile, DB_REL),
                         os.path.join(self.user_home, ".hermesX/x.db"))

    def test_profile_prefix_is_stripped_once_with_a_warning(self):
        for value in ("~/.hermes/profiles/coder/commons/db/chronicle/chronicle.db",
                      "$HERMES_HOME/profiles/coder/commons/db/chronicle/chronicle.db",
                      "${HERMES_HOME}/profiles/coder/commons/db/chronicle/chronicle.db"):
            with self.subTest(value=value):
                paths.reset_warnings()
                self.cap.records.clear()
                self.assertEqual(expand_data_path(value, self.profile, DB_REL),
                                 os.path.join(self.profile, DB_REL))
                self.assertEqual(len(self.warnings()), 1)
                self.assertEqual(self.warnings()[0].name, "chronicle.paths")

    def test_profile_prefix_to_the_home_itself(self):
        self.assertEqual(expand_data_path("~/.hermes/profiles/coder/", self.profile, DB_REL),
                         self.profile)

    def test_warning_is_emitted_once_until_reset(self):
        value = "~/.hermes/profiles/coder/commons/db/chronicle/chronicle.db"
        expand_data_path(value, self.profile, DB_REL)
        expand_data_path(value, self.profile, DB_REL)
        expand_data_path("~/.hermes/profiles/coder/commons/db/chronicle/git", self.profile, GIT_REL)
        self.assertEqual(len(self.warnings()), 1)
        paths.reset_warnings()
        expand_data_path(value, self.profile, DB_REL)
        self.assertEqual(len(self.warnings()), 2)

    def test_profile_prefix_is_stripped_only_once(self):
        value = "~/.hermes/profiles/coder/profiles/coder/x.db"
        self.assertEqual(expand_data_path(value, self.profile, DB_REL),
                         os.path.join(self.profile, "profiles/coder/x.db"))

    def test_profile_prefix_kept_when_home_is_not_a_profile(self):
        value = "~/.hermes/profiles/coder/x.db"
        self.assertEqual(expand_data_path(value, self.root, DB_REL),
                         os.path.join(self.root, "profiles/coder/x.db"))
        self.assertEqual(self.warnings(), [])

    def test_profile_prefix_kept_for_another_profile(self):
        value = "~/.hermes/profiles/writer/x.db"
        self.assertEqual(expand_data_path(value, self.profile, DB_REL),
                         os.path.join(self.profile, "profiles/writer/x.db"))
        self.assertEqual(self.warnings(), [])

    def test_profile_prefix_needs_its_trailing_separator(self):
        value = "~/.hermes/profiles/coderX/x.db"
        self.assertEqual(expand_data_path(value, self.profile, DB_REL),
                         os.path.join(self.profile, "profiles/coderX/x.db"))
        self.assertEqual(self.warnings(), [])

    def test_profile_check_tolerates_a_trailing_slash_on_home(self):
        value = "~/.hermes/profiles/coder/x.db"
        got = expand_data_path(value, self.profile + "/", DB_REL)
        self.assertEqual(os.path.normpath(got), os.path.join(self.profile, "x.db"))

    def test_relative_profiles_path_is_not_stripped(self):
        # Only a home-prefixed value is read as "the profile spelled out twice".
        self.assertEqual(expand_data_path("profiles/coder/x.db", self.profile, DB_REL),
                         os.path.join(self.profile, "profiles/coder/x.db"))
        self.assertEqual(self.warnings(), [])

    def test_other_tilde_paths_expand_against_the_user_home(self):
        self.assertEqual(expand_data_path("~/other/x.db", self.profile, DB_REL),
                         os.path.join(self.user_home, "other/x.db"))
        self.assertEqual(expand_data_path("~", self.profile, DB_REL), self.user_home)

    def test_absolute_is_normalized_and_kept(self):
        self.assertEqual(expand_data_path(self.tmp + "/data/../store//x.db", self.profile, DB_REL),
                         os.path.join(self.tmp, "store", "x.db"))
        self.assertEqual(self.warnings(), [])

    def test_relative_joins_the_home(self):
        self.assertEqual(expand_data_path("data/x.db", self.profile, DB_REL),
                         os.path.join(self.profile, "data/x.db"))
        # An unknown variable is not expanded; it is a relative name like any other.
        self.assertEqual(expand_data_path("$HERMES_HOMEX/x.db", self.profile, DB_REL),
                         os.path.join(self.profile, "$HERMES_HOMEX/x.db"))


# --------------------------------------------------------------------------
# legacy_db_path / legacy_git_path
# --------------------------------------------------------------------------

class TestLegacyDbPath(_HomeCase):
    def test_default(self):
        for value in (None, ""):
            with self.subTest(value=value):
                self.assertEqual(legacy_db_path(value, self.profile),
                                 os.path.join(self.profile, DB_REL))

    def test_prefix_is_replaced(self):
        self.assertEqual(legacy_db_path("~/.hermes/data/x.db", self.root),
                         os.path.join(self.root, "data/x.db"))

    def test_profile_spelled_out_is_doubled(self):
        # The bug the migration exists for: this is where 5.11.1 really wrote.
        value = "~/.hermes/profiles/coder/" + DB_REL
        self.assertEqual(legacy_db_path(value, self.profile),
                         os.path.join(self.profile, "profiles/coder", DB_REL))

    def test_replace_hits_every_occurrence(self):
        value = "~/.hermes/a/~/.hermes/b.db"
        self.assertEqual(legacy_db_path(value, self.root),
                         self.root + "/a/" + self.root + "/b.db")

    def test_prefix_without_separator_is_still_replaced(self):
        self.assertEqual(legacy_db_path("~/.hermesX/x.db", self.root), self.root + "X/x.db")

    def test_absolute_path_is_ignored(self):
        self.assertEqual(legacy_db_path(self.tmp + "/store/x.db", self.profile),
                         os.path.join(self.profile, DB_REL))

    def test_relative_and_other_tilde_paths_are_ignored(self):
        for value in ("data/x.db", "~/other/x.db", "$HERMES_HOME/x.db", " ~/.hermes/x.db"):
            with self.subTest(value=value):
                self.assertEqual(legacy_db_path(value, self.profile),
                                 os.path.join(self.profile, DB_REL))

    def test_matches_the_5_11_1_expression(self):
        homes = (self.root, self.profile, self.profile + "/", self.tmp + "//odd//home")
        values = (None, "", "~/.hermes", "~/.hermes/", "~/.hermes/x.db",
                  "~/.hermes//x.db", "~/.hermes/profiles/coder/" + DB_REL,
                  "~/.hermes/a/~/.hermes/b.db", "~/.hermesX/x.db", "/abs/x.db",
                  "rel/x.db", "~/other/x.db", "$HERMES_HOME/x.db", "${HERMES_HOME}/x.db",
                  " ~/.hermes/x.db")
        for home in homes:
            for value in values:
                with self.subTest(home=home, value=value):
                    self.assertEqual(legacy_db_path(value, home), _v5111_db_path(value, home))


class TestLegacyGitPath(_HomeCase):
    def test_default_ignores_the_profile(self):
        # 5.11.1 never looked at the profile for the mirror: it is always under
        # the user's own ~/.hermes.
        self.assertEqual(legacy_git_path(None), os.path.join(self.root, GIT_REL))
        self.assertEqual(legacy_git_path(""), os.path.join(self.root, GIT_REL))

    def test_expanduser_is_the_only_expansion(self):
        self.assertEqual(legacy_git_path("~/.hermes/profiles/coder/git"),
                         os.path.join(self.root, "profiles/coder/git"))
        self.assertEqual(legacy_git_path("~/other/git"), os.path.join(self.user_home, "other/git"))
        self.assertEqual(legacy_git_path("$HERMES_HOME/git"), "$HERMES_HOME/git")
        self.assertEqual(legacy_git_path("rel/git"), "rel/git")
        self.assertEqual(legacy_git_path(self.tmp + "//a/../git"), self.tmp + "//a/../git")

    def test_matches_the_5_11_1_expression(self):
        for value in ("~/.hermes/x", "~/other/git", "rel/git", "/abs//git", "$HERMES_HOME/git", "~"):
            with self.subTest(value=value):
                self.assertEqual(legacy_git_path(value), _v5111_git_path({"git_repo": value}))
        self.assertEqual(legacy_git_path(None), _v5111_git_path({}))


# --------------------------------------------------------------------------
# has_data
# --------------------------------------------------------------------------

class TestHasData(_HomeCase):
    def _db(self, name="chronicle.db"):
        return os.path.join(self.tmp, "dbs", name)

    def _assert_untouched(self, path):
        self.assertFalse(os.path.exists(path))
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(os.path.exists(path + suffix))

    def test_missing_file_is_false_and_not_created(self):
        path = self._db()
        self.assertFalse(has_data(path))
        self._assert_untouched(path)
        self.assertFalse(os.path.exists(os.path.dirname(path)))

    def test_missing_file_in_existing_dir_is_not_created(self):
        path = os.path.join(self.tmp, "absent.db")
        self.assertFalse(has_data(path))
        self._assert_untouched(path)

    def test_empty_file_is_false_and_stays_empty(self):
        path = self._db()
        os.makedirs(os.path.dirname(path))
        open(path, "wb").close()
        self.assertFalse(has_data(path))
        self.assertEqual(os.path.getsize(path), 0)

    def test_not_a_database_is_false(self):
        path = self._db()
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            f.write(b"this is not a database file" * 100)
        self.assertFalse(has_data(path))

    def test_directory_is_false(self):
        self.assertFalse(has_data(self.tmp))

    def test_no_events_table_is_false(self):
        path = self._db()
        _make_db(path, events_table=False)
        self.assertFalse(has_data(path))

    def test_empty_events_is_false(self):
        path = self._db()
        _make_db(path, rows=0)
        self.assertFalse(has_data(path))

    def test_one_row_is_true(self):
        path = self._db()
        _make_db(path, rows=1)
        self.assertTrue(has_data(path))

    def test_read_only_open_does_not_write(self):
        path = self._db()
        _make_db(path, rows=3)
        before = (os.path.getsize(path), os.stat(path).st_mtime_ns)
        self.assertTrue(has_data(path))
        self.assertEqual((os.path.getsize(path), os.stat(path).st_mtime_ns), before)

    def test_awkward_file_names(self):
        # `?`, `#` and `%` mean something inside a SQLite URI. Unquoted, the
        # read-only open lands on some other name (and, with `mode=ro` cut off
        # as part of the name, may even create it).
        for i, name in enumerate(("with space.db", "what?.db", "hash#.db", "pct%20.db")):
            with self.subTest(name=name):
                path = os.path.join(self.tmp, "awkward%d" % i, name)
                _make_db(path, rows=1)
                self.assertTrue(has_data(path))
                self.assertEqual(os.listdir(os.path.dirname(path)), [name])

    def test_rows_still_in_the_wal_are_seen(self):
        path = self._db()
        _make_db(path, rows=0, wal=True)
        writer = sqlite3.connect(path)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO events VALUES ('e1', 'fake body')")
        writer.commit()
        self.assertTrue(os.path.exists(path + "-wal"))
        self.assertTrue(has_data(path))

    def test_accepts_a_path_object(self):
        path = self._db()
        _make_db(path, rows=1)
        self.assertTrue(has_data(Path(path)))


# --------------------------------------------------------------------------
# readable_db_path
# --------------------------------------------------------------------------

class TestReadableDbPath(_HomeCase):
    """A read-only consumer finds the data wherever it actually is."""

    VALUE = "~/.hermes/profiles/coder/" + DB_REL

    def setUp(self):
        super().setUp()
        self.new = os.path.join(self.profile, DB_REL)
        self.legacy = os.path.join(self.profile, "profiles/coder", DB_REL)
        self.assertEqual(expand_data_path(self.VALUE, self.profile, DB_REL), self.new)
        self.assertEqual(legacy_db_path(self.VALUE, self.profile), self.legacy)

    def test_new_has_data(self):
        _make_db(self.new, rows=1)
        self.assertEqual(readable_db_path(self.VALUE, self.profile), self.new)

    def test_both_have_data_prefers_new(self):
        _make_db(self.new, rows=1)
        _make_db(self.legacy, rows=1)
        self.assertEqual(readable_db_path(self.VALUE, self.profile), self.new)

    def test_only_legacy_has_data(self):
        _make_db(self.new, rows=0)
        _make_db(self.legacy, rows=2)
        self.assertEqual(readable_db_path(self.VALUE, self.profile), self.legacy)

    def test_only_legacy_exists(self):
        _make_db(self.legacy, rows=1)
        self.assertEqual(readable_db_path(self.VALUE, self.profile), self.legacy)
        self.assertFalse(os.path.exists(self.new))

    def test_neither_has_data_gives_new(self):
        _make_db(self.legacy, rows=0)
        self.assertEqual(readable_db_path(self.VALUE, self.profile), self.new)

    def test_nothing_on_disk_gives_new_and_creates_nothing(self):
        self.assertEqual(readable_db_path(self.VALUE, self.profile), self.new)
        self.assertFalse(os.path.exists(self.new))
        self.assertFalse(os.path.exists(self.legacy))
        self.assertFalse(os.path.exists(os.path.join(self.profile, "commons")))

    def test_absolute_value_falls_back_to_the_legacy_default(self):
        # 5.11.1 ignored an absolute db_path and wrote to the default instead.
        value = os.path.join(self.tmp, "store", "x.db")
        legacy = os.path.join(self.profile, DB_REL)
        _make_db(legacy, rows=1)
        self.assertEqual(readable_db_path(value, self.profile), legacy)
        _make_db(value, rows=1)
        self.assertEqual(readable_db_path(value, self.profile), value)

    def test_default_value_is_the_same_path_either_way(self):
        path = os.path.join(self.root, DB_REL)
        self.assertEqual(readable_db_path(None, self.root), path)
        _make_db(path, rows=1)
        self.assertEqual(readable_db_path(None, self.root), path)


# --------------------------------------------------------------------------
# profile_root
# --------------------------------------------------------------------------

class TestProfileRoot(_HomeCase):
    def test_profile_home_gives_the_root(self):
        self.assertEqual(profile_root(self.profile), self.root)

    def test_profile_home_with_trailing_slash(self):
        self.assertEqual(profile_root(self.profile + "/"), self.root)

    def test_plain_home_is_its_own_root(self):
        self.assertEqual(profile_root(self.root), self.root)

    def test_a_directory_named_profiles_is_not_a_profile_home(self):
        home = os.path.join(self.tmp, "profiles")
        self.assertEqual(profile_root(home), home)


if __name__ == "__main__":
    unittest.main()
