"""A named profile keeps its own store when the host starts the engine again.

The host starts a session under a profile with
`on_session_start(sid, hermes_home=<root>/profiles/<name>, ...)`. After it
compresses the conversation it moves to a child session with a second
`on_session_start(child_sid, boundary_reason="compression", old_session_id=...,
session_db=..., platform=..., conversation_id=...)` that names no home at all.

The engine used to read that missing home as "the default": it resolved
`~/.hermes`, built a second core for the DEFAULT profile, and attached it. From
the first compression on, every capture, recall and audit event of the profile's
conversation went into another profile's store, and nothing reported it.

The memory provider had the sibling defect: a missing home skipped the host's
own `hermes_constants.get_hermes_home()` and went straight to `~/.hermes`, and
a `~` in an explicit home was never expanded, so the store was made relative to
the working directory.

Every test here keeps `HOME` and the working directory inside a temp dir, and
removes or replaces the host module, so nothing can reach a real home.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from context import ChronicleContextEngine, _default_hermes_home
from engine.core import ChronicleCore
from engine.paths import DB_REL, resolve_home
from provider import ChronicleMemoryProvider

# A config the engine needs no network for (the embedder is the offline one).
CFG = {"embeddings": {"model": "hashing"}}


def _stub_host(home):
    """A stand-in for the host's `hermes_constants` module."""
    mod = types.ModuleType("hermes_constants")
    mod.get_hermes_home = lambda: Path(home)
    return mod


class _ProfileCase(unittest.TestCase):
    """A temp user home with a default Hermes home and one named profile."""

    def setUp(self):
        self.tmp = os.path.realpath(temp_home(prefix="chronicle-reinit-"))
        self.user_home = os.path.join(self.tmp, "user")
        self.root = os.path.join(self.user_home, ".hermes")
        self.profile = os.path.join(self.root, "profiles", "p")
        os.makedirs(self.profile)
        env = mock.patch.dict(os.environ, {"HOME": self.user_home})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("HERMES_HOME", None)
        # An offline run by default: `None` in sys.modules makes the import
        # raise. A test that wants a host installs one with `_host`.
        mods = mock.patch.dict(sys.modules, {"hermes_constants": None})
        mods.start()
        self.addCleanup(mods.stop)
        # A home that is wrongly left relative lands in the working directory;
        # keep that inside the temp dir too.
        cwd = os.getcwd()
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.work)
        os.chdir(self.work)
        self.addCleanup(os.chdir, cwd)

    def _host(self, home):
        sys.modules["hermes_constants"] = _stub_host(home)

    def _homes_with_a_core(self):
        return {os.path.realpath(k) for k in ChronicleCore._instances}

    def _default_store(self):
        return os.path.join(self.root, DB_REL)


class TestContextEngineKeepsProfileAcrossCompression(_ProfileCase):
    """The compression child's on_session_start must not move the engine."""

    def _start(self):
        eng = ChronicleContextEngine()
        eng.on_session_start("s-parent", hermes_home=self.profile,
                             principal_id="tester", config=CFG,
                             platform="cli", conversation_id="conv-1")
        self.assertIsNotNone(eng.core, "setup: the engine did not build a real core")
        self.assertEqual(os.path.realpath(eng.core.hermes_home), self.profile)
        return eng

    def _compression_child(self, eng):
        # The exact call shape of the host's compression-child adoption: no
        # hermes_home, no config, no principal.
        eng.on_session_start("s-child", boundary_reason="compression",
                             old_session_id="s-parent", session_db=object(),
                             platform="cli", conversation_id="conv-1")

    def _assert_still_on_profile(self, eng):
        self.assertIsNotNone(eng.core, "the child session fell back to the heuristic")
        self.assertEqual(os.path.realpath(eng.core.hermes_home), self.profile)
        self.assertEqual(self._homes_with_a_core(), {self.profile},
                         "a core was built for a home other than the profile's")
        self.assertFalse(os.path.exists(self._default_store()),
                         "the default profile's store was created")
        self.assertEqual(eng._session_id, "s-child")

    def test_offline_no_env(self):
        # Nothing names a home: the old fallback was HOME/.hermes.
        eng = self._start()
        self._compression_child(eng)
        self._assert_still_on_profile(eng)

    def test_env_names_the_default_home(self):
        # A HERMES_HOME left over from the default profile.
        eng = self._start()
        os.environ["HERMES_HOME"] = self.root
        self._compression_child(eng)
        self._assert_still_on_profile(eng)

    def test_host_names_the_default_home(self):
        # A process whose host-wide home is the default profile while this
        # engine serves a named one: the home the session started with wins.
        eng = self._start()
        self._host(self.root)
        self._compression_child(eng)
        self._assert_still_on_profile(eng)

    def test_two_compressions(self):
        eng = self._start()
        self._compression_child(eng)
        eng.on_session_start("s-grandchild", boundary_reason="compression",
                             old_session_id="s-child", session_db=object(),
                             platform="cli", conversation_id="conv-1")
        self.assertEqual(os.path.realpath(eng.core.hermes_home), self.profile)
        self.assertEqual(self._homes_with_a_core(), {self.profile})

    def test_retry_after_a_failed_first_init_uses_the_profile(self):
        # The first init loses the SQLite write lock; the child session's
        # start is then the retry, and it must rebuild the PROFILE's core.
        real_get = ChronicleCore.get.__func__
        calls = []

        def flaky_get(cls, hermes_home, config=None, embedder_probe=None):
            calls.append(hermes_home)
            if len(calls) == 1:
                raise sqlite3.OperationalError("database is locked")
            return real_get(cls, hermes_home, config, embedder_probe)

        # A config value nothing else would produce, to see which config the
        # rebuilt core got: the one the session started with, not defaults.
        cfg = {"embeddings": {"model": "hashing"},
               "context": {"default_token_budget": 1234}}
        with mock.patch.object(ChronicleCore, "get", classmethod(flaky_get)):
            eng = ChronicleContextEngine()
            eng.on_session_start("s-parent", hermes_home=self.profile,
                                 principal_id="tester", config=cfg)
            self.assertIsNone(eng.core, "setup: the first init should have failed")
            self._compression_child(eng)
        self.assertEqual([os.path.realpath(h) for h in calls], [self.profile] * 2)
        self._assert_still_on_profile(eng)
        self.assertEqual(eng.core.cfg.get("context.default_token_budget"), 1234)

    def test_an_explicit_new_home_still_moves_the_engine(self):
        # Reuse is only for a call that names no home; a named one is obeyed.
        eng = self._start()
        other = os.path.join(self.root, "profiles", "q")
        os.makedirs(other)
        eng.on_session_start("s-other", hermes_home=other, config=CFG)
        self.assertEqual(os.path.realpath(eng.core.hermes_home), other)

    def test_first_start_without_a_home_asks_the_host(self):
        # No earlier home to reuse: the shared resolver decides.
        self._host(self.profile)
        os.environ["HERMES_HOME"] = self.root
        self.assertEqual(_default_hermes_home(), self.profile)
        eng = ChronicleContextEngine()
        eng.on_session_start("s-1", config=CFG)
        self.assertEqual(os.path.realpath(eng.core.hermes_home), self.profile)
        self.assertEqual(self._homes_with_a_core(), {self.profile})

    def test_first_start_with_a_tilde_home_is_absolute(self):
        eng = ChronicleContextEngine()
        eng.on_session_start("s-1", hermes_home="~/.hermes/profiles/p", config=CFG)
        self.assertEqual(eng.core.hermes_home, self.profile)
        self.assertFalse(os.path.exists(os.path.join(self.work, "~")),
                         "a store was made relative to the working directory")


class TestProviderResolvesTheHome(_ProfileCase):
    """provider.initialize uses the same resolver as everything else."""

    def test_missing_home_uses_the_host_override(self):
        # HERMES_HOME unset; the host knows the active profile.
        self._host(self.profile)
        prov = ChronicleMemoryProvider()
        prov.initialize("s-1", hermes_home=None, config=CFG)
        self.assertEqual(os.path.realpath(prov.core.hermes_home), self.profile)
        self.assertEqual(self._homes_with_a_core(), {self.profile})
        self.assertFalse(os.path.exists(self._default_store()),
                         "the default profile's store was created")

    def test_missing_home_matches_resolve_home(self):
        os.environ["HERMES_HOME"] = self.profile
        prov = ChronicleMemoryProvider()
        prov.initialize("s-1", config=CFG)
        self.assertEqual(prov.core.hermes_home, resolve_home(None))
        self.assertEqual(prov.core.hermes_home, self.profile)

    def test_tilde_home_is_expanded(self):
        prov = ChronicleMemoryProvider()
        prov.initialize("s-1", hermes_home="~/.hermes/profiles/p", config=CFG)
        self.assertEqual(prov.core.hermes_home, self.profile)
        self.assertFalse(os.path.exists(os.path.join(self.work, "~")),
                         "a store was made relative to the working directory")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
