"""
Chronicle — moving a store and a git mirror left at an older release's paths.

Covers engine/migrate_paths.py rule by rule, each failure it must survive (a
store held by another process, another filesystem, no symlinks, a crash at
every step), and the wiring in ChronicleCore and GitMirror. Every check of a
failure ends the same way: the store at the returned path opens and holds
every event it held before.
"""

import json
import logging
import multiprocessing
import os
import sqlite3
import sys
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import has_yaml_parser, temp_home


from engine import migrate_paths as mp_mod
from engine import paths as paths_mod
from engine.core import ChronicleCore
from engine.gitmirror import GitMirror
from engine.migrate_paths import MARKER_NAME, settle_db_path, settle_git_repo
from engine.paths import DB_REL, GIT_REL
from engine.store import MemoryStore

_NEEDS_YAML = unittest.skipUnless(has_yaml_parser(), "no YAML parser (PyYAML or ruamel.yaml) in this Python")

HASHING = {"embeddings": {"model": "hashing"}}


def seed_store(path, n, pad=0):
    """A real Chronicle store at `path` holding `n` events."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    store = MemoryStore(path)
    conn = store._conn()
    filler = "x" * pad
    rows = [("ev_%064d" % i, i, "observed", json.dumps({"i": i, "pad": filler}), "[]",
             "user", "default", 2, "s1", "2026-01-01T00:00:00.000Z",
             "2026-01-01T00:00:00.000Z") for i in range(1, n + 1)]
    conn.executemany(
        "INSERT INTO events(event_id,seq,type,payload,parents,actor,owner,trust_level,"
        "session_id,occurred_at,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("UPDATE meta SET value=? WHERE key='event_seq'", (str(n),))
    conn.commit()
    store.close()
    return path


def event_count(path):
    """Events in the store at `path`, read the way a fresh opener reads it."""
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()


def store_opens_with(path, n):
    """The store at `path` opens as a MemoryStore and holds exactly `n` events."""
    with MemoryStore(path) as store:
        got = store.count_rows("events")
    return got == n


def _hold_open(path, ready, release):
    """Child process: hold the store open the way a running host does."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("SELECT COUNT(*) FROM events").fetchone()
    ready.set()
    release.wait(30)
    conn.close()


class _Captured(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def at(self, level):
        return [r for r in self.records if r.levelno >= level]


class Base(unittest.TestCase):
    def setUp(self):
        mp_mod.reset_warnings()
        paths_mod.reset_warnings()
        self.root = temp_home()
        self.home = os.path.join(self.root, "profiles", "p")
        os.makedirs(self.home)
        self.legacy = os.path.join(self.home, DB_REL)
        self.new = os.path.join(self.root, "data", "p", "chronicle.db")
        self.log = _Captured()
        lg = logging.getLogger("chronicle")
        lg.addHandler(self.log)
        old_level = lg.level
        lg.setLevel(logging.DEBUG)
        self.addCleanup(lg.removeHandler, self.log)
        self.addCleanup(lg.setLevel, old_level)

    def settle(self):
        return settle_db_path(self.new, self.legacy, home=self.home)

    def marker(self):
        p = os.path.join(os.path.dirname(self.new), MARKER_NAME)
        if not os.path.exists(p):
            return None
        with open(p) as fh:
            return json.load(fh)


# --------------------------------------------------------------------------
# settle_db_path: the rules, in order
# --------------------------------------------------------------------------
class TestRules(Base):
    def test_rule1_same_file_through_a_symlinked_dir_is_none(self):
        seed_store(self.legacy, 3)
        alias = os.path.join(self.root, "alias")
        os.symlink(self.home, alias)
        r = settle_db_path(os.path.join(alias, DB_REL), self.legacy, home=self.home)
        self.assertEqual((r.action, r.path), ("none", os.path.join(alias, DB_REL)))
        self.assertFalse(os.path.islink(self.legacy))

    def test_rule2_no_data_at_legacy_is_none(self):
        r = self.settle()
        self.assertEqual((r.action, r.path), ("none", self.new))
        self.assertFalse(os.path.exists(self.legacy), "a check must never create the old store")
        seed_store(self.legacy, 0)
        self.assertEqual(self.settle().action, "none")

    def test_rule3_both_hold_data_is_conflict_and_warns_once(self):
        seed_store(self.legacy, 3)
        seed_store(self.new, 2)
        r1, r2 = self.settle(), self.settle()
        self.assertEqual((r1.action, r1.path), ("conflict", self.legacy))
        self.assertEqual(r2.action, "conflict")
        warns = self.log.at(logging.WARNING)
        self.assertEqual(len(warns), 1)
        self.assertIn(self.new, warns[0].getMessage())
        self.assertIn(self.legacy, warns[0].getMessage())
        self.assertEqual((event_count(self.legacy), event_count(self.new)), (3, 2))

    def _profile(self, name, text):
        h = os.path.join(self.root, "profiles", name) if name else self.root
        os.makedirs(h, exist_ok=True)
        with open(os.path.join(h, "config.yaml"), "w") as fh:
            fh.write(text)

    @_NEEDS_YAML
    def test_rule4_claimed_by_another_chronicle_profile_is_kept(self):
        seed_store(self.legacy, 3)
        self._profile("other", "memory:\n  provider: chronicle\n  db_path: %s\n" % self.legacy)
        r = self.settle()
        self.assertEqual((r.action, r.path), ("kept_legacy", self.legacy))
        self.assertEqual(len(self.log.at(logging.WARNING)), 1)
        self.assertFalse(os.path.islink(self.legacy))
        self.assertFalse(os.path.exists(self.new))

    @_NEEDS_YAML
    def test_rule4_context_engine_profile_and_default_profile_count(self):
        seed_store(self.legacy, 3)
        self._profile(None, "context:\n  engine: chronicle\nmemory:\n  db_path: %s\n" % self.legacy)
        self.assertEqual(self.settle().action, "kept_legacy")

    def test_rule4_a_profile_not_using_chronicle_does_not_count(self):
        seed_store(self.legacy, 3)
        self._profile("other", "memory:\n  provider: other\n  db_path: %s\n" % self.legacy)
        self._profile("third", "memory:\n  provider: chronicle\n")   # its own default path
        self.assertEqual(self.settle().action, "moved")

    def test_rule5_another_process_holding_it_defers(self):
        seed_store(self.legacy, 3)
        ctx = multiprocessing.get_context("spawn")
        ready, release = ctx.Event(), ctx.Event()
        child = ctx.Process(target=_hold_open, args=(self.legacy, ready, release))
        child.start()
        try:
            self.assertTrue(ready.wait(30), "child never opened the store")
            t0 = time.monotonic()
            r = self.settle()
            took = time.monotonic() - t0
        finally:
            release.set()
            child.join(30)
        self.assertEqual((r.action, r.path), ("deferred", self.legacy))
        self.assertLess(took, 5.0)
        self.assertFalse(os.path.exists(self.new))
        self.assertFalse(os.path.islink(self.legacy))
        self.assertTrue(any(r_.levelno == logging.INFO and "in use" in r_.getMessage()
                            for r_ in self.log.records))
        with closing(sqlite3.connect(self.legacy)) as c:
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertTrue(store_opens_with(self.legacy, 3))
        # Released: the next start moves it.
        self.assertEqual(self.settle().action, "moved")

    def test_rule5_held_in_this_process_defers(self):
        seed_store(self.legacy, 3)
        holder = MemoryStore(self.legacy)
        try:
            holder.count_rows("events")
            r = self.settle()
        finally:
            holder.close()
        self.assertEqual(r.action, "deferred")

    def test_rule5_begin_exclusive_failing_defers_and_restores_wal(self):
        seed_store(self.legacy, 3)
        real_connect = sqlite3.connect

        class Conn:
            def __init__(self, c):
                self.c = c

            def execute(self, sql, *a):
                if sql == "BEGIN EXCLUSIVE":
                    raise sqlite3.OperationalError("database is locked")
                return self.c.execute(sql, *a)

            def __getattr__(self, name):
                return getattr(self.c, name)

        def connect(path, *a, **kw):
            c = real_connect(path, *a, **kw)
            return Conn(c) if path == self.legacy else c

        with MemoryStore(self.legacy) as s:   # leave it in WAL mode, as a host does
            s.count_rows("events")
        with closing(sqlite3.connect(self.legacy)) as c:
            c.execute("PRAGMA journal_mode=WAL")
        with mock.patch.object(mp_mod.sqlite3, "connect", side_effect=connect):
            r = self.settle()
        self.assertEqual((r.action, r.path), ("deferred", self.legacy))
        with closing(sqlite3.connect(self.legacy)) as c:
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_rule6_an_empty_store_at_new_is_set_aside_with_its_sidecars(self):
        seed_store(self.legacy, 3)
        os.makedirs(os.path.dirname(self.new))
        empty = MemoryStore(self.new)       # an empty store, left open-shaped: -wal/-shm exist
        empty.count_rows("events")
        empty.close()
        with open(self.new + "-wal", "wb") as fh:
            fh.write(b"stale")              # must never be replayed into the moved store
        r = self.settle()
        self.assertEqual(r.action, "moved")
        asides = [f for f in os.listdir(os.path.dirname(self.new)) if ".empty-" in f]
        self.assertTrue(any(not f.endswith(("-wal", "-shm")) for f in asides))
        self.assertFalse(os.path.exists(self.new + "-wal"))
        self.assertTrue(store_opens_with(self.new, 3))

    def test_rule6_an_empty_store_at_new_in_use_defers(self):
        seed_store(self.legacy, 3)
        os.makedirs(os.path.dirname(self.new))
        holder = MemoryStore(self.new)
        try:
            holder.count_rows("events")
            r = self.settle()
        finally:
            holder.close()
        self.assertEqual((r.action, r.path), ("deferred", self.legacy))
        self.assertFalse(os.path.islink(self.legacy))
        self.assertTrue(store_opens_with(self.legacy, 3))

    def test_rule7_8_9_10_same_filesystem_moves_by_link_then_symlink(self):
        seed_store(self.legacy, 5)
        ino = os.stat(self.legacy).st_ino
        r = self.settle()
        self.assertEqual((r.action, r.path), ("moved", self.new))
        self.assertEqual(os.stat(self.new).st_ino, ino, "a same-filesystem move copies nothing")
        self.assertTrue(os.path.islink(self.legacy))
        self.assertEqual(os.readlink(self.legacy), self.new)
        self.assertEqual(os.stat(self.new).st_nlink, 1, "never two hard-link names for one store")
        self.assertFalse(os.path.exists(self.legacy + "-wal"))
        self.assertFalse(os.path.exists(self.legacy + "-shm"))
        # Step 9: the hold is released, so a writer can open the new name at once.
        conn = sqlite3.connect(self.new, timeout=0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("UPDATE meta SET value=value WHERE key='event_seq'")
        conn.commit()
        conn.close()
        self.assertTrue(store_opens_with(self.new, 5))
        rec = self.marker()
        self.assertEqual(len(rec), 1)
        self.assertEqual({k: rec[0][k] for k in ("from", "to", "action")},
                         {"from": self.legacy, "to": self.new, "action": "moved"})
        self.assertTrue(rec[0]["at"] and rec[0]["version"])
        self.assertTrue(any("moved the store" in x.getMessage() for x in self.log.records
                            if x.levelno == logging.INFO))
        # The old name now resolves to the new store: a second start does nothing.
        self.assertEqual(self.settle().action, "none")
        self.assertEqual(len(self.marker()), 1)

    def test_rule7_other_filesystem_copies_verifies_and_keeps_the_original(self):
        seed_store(self.legacy, 7)
        real = mp_mod._device
        legacy_dev = real(self.legacy)
        with mock.patch.object(mp_mod, "_device",
                               side_effect=lambda p: legacy_dev if p == self.legacy else legacy_dev + 1):
            r = self.settle()
        self.assertEqual((r.action, r.path), ("copied", self.new))
        self.assertTrue(os.path.islink(self.legacy))
        self.assertEqual(os.readlink(self.legacy), self.new)
        kept = [f for f in os.listdir(os.path.dirname(self.legacy)) if ".migrated-" in f]
        self.assertEqual(len(kept), 1)
        self.assertEqual(event_count(os.path.join(os.path.dirname(self.legacy), kept[0])), 7)
        self.assertNotEqual(os.stat(self.new).st_ino,
                            os.stat(os.path.join(os.path.dirname(self.legacy), kept[0])).st_ino)
        self.assertFalse(os.path.exists(self.new + ".partial"))
        self.assertTrue(store_opens_with(self.new, 7))
        self.assertEqual(self.marker()[0]["action"], "copied")

    def test_a_wal_store_whose_sidecars_are_gone_moves_too(self):
        # The shape a clean last close leaves on most builds: WAL mode in the
        # header, no -wal, no -shm. A read-only open cannot create the -shm.
        seed_store(self.legacy, 4)
        with closing(sqlite3.connect(self.legacy)) as c:
            c.execute("PRAGMA journal_mode=WAL")
        for suffix in ("-wal", "-shm"):
            if os.path.exists(self.legacy + suffix):
                os.unlink(self.legacy + suffix)
        self.assertEqual(self.settle().action, "moved")
        self.assertTrue(store_opens_with(self.new, 4))

    def test_a_store_closed_in_delete_mode_moves_too(self):
        seed_store(self.legacy, 2)       # MemoryStore.close() leaves journal_mode=DELETE
        with closing(sqlite3.connect(self.legacy)) as c:
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        self.assertEqual(self.settle().action, "moved")
        self.assertTrue(store_opens_with(self.new, 2))

    def test_uncheckpointed_wal_transactions_move_with_the_store(self):
        seed_store(self.legacy, 2)
        conn = sqlite3.connect(self.legacy)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("INSERT INTO events(event_id,seq,type,payload,parents,actor,owner,trust_level,"
                     "occurred_at,recorded_at) VALUES('ev_wal',99,'observed','{}','[]','user',"
                     "'default',2,'t','t')")
        conn.commit()
        self.assertGreater(os.path.getsize(self.legacy + "-wal"), 0)
        # Simulate a process that died with the WAL un-checkpointed: copy the
        # three files elsewhere (closing would checkpoint), then move that.
        import shutil
        dead = os.path.join(self.root, "dead", "p")
        os.makedirs(os.path.join(dead, os.path.dirname(DB_REL)))
        for suffix in ("", "-wal"):
            shutil.copyfile(self.legacy + suffix, os.path.join(dead, DB_REL) + suffix)
        conn.close()
        r = settle_db_path(self.new, os.path.join(dead, DB_REL), home=dead)
        self.assertEqual(r.action, "moved")
        self.assertTrue(store_opens_with(self.new, 3))

    def test_a_legacy_name_that_is_a_symlink_elsewhere_is_kept(self):
        real = seed_store(os.path.join(self.root, "elsewhere", "c.db"), 3)
        os.makedirs(os.path.dirname(self.legacy))
        os.symlink(real, self.legacy)
        r = self.settle()
        self.assertEqual((r.action, r.path), ("kept_legacy", self.legacy))
        self.assertFalse(os.path.exists(self.new))


# --------------------------------------------------------------------------
# Failure: symlinks unsupported, a crash at each step, an unexpected error
# --------------------------------------------------------------------------
class TestFailures(Base):
    def assert_intact(self, r, n):
        self.assertTrue(store_opens_with(r.path, n), "%s lost events" % r.path)
        nlinks = os.stat(r.path).st_nlink
        self.assertEqual(nlinks, 1, "two hard-link names left for one store")

    def test_symlink_unsupported_when_moved_drops_the_old_name(self):
        seed_store(self.legacy, 4)
        with mock.patch.object(mp_mod.os, "symlink", side_effect=NotImplementedError("no")):
            r = self.settle()
        self.assertEqual((r.action, r.path), ("moved", self.new))
        self.assertFalse(os.path.lexists(self.legacy))
        self.assert_intact(r, 4)

    def test_symlink_unsupported_when_copied_keeps_the_backup_and_warns(self):
        seed_store(self.legacy, 4)
        d = mp_mod._device(self.legacy)
        with mock.patch.object(mp_mod, "_device",
                               side_effect=lambda p: d if p == self.legacy else d + 1), \
                mock.patch.object(mp_mod.os, "symlink", side_effect=OSError("no symlinks")):
            r = self.settle()
        self.assertEqual((r.action, r.path), ("copied", self.new))
        self.assertFalse(os.path.lexists(self.legacy))
        kept = [f for f in os.listdir(os.path.dirname(self.legacy)) if ".migrated-" in f]
        self.assertEqual(len(kept), 1)
        self.assertTrue(any("symlink" in w.getMessage() for w in self.log.at(logging.WARNING)))
        self.assert_intact(r, 4)

    def _crash(self, target, attr, *, copied=False, when=None):
        """Run the move with `target.attr` raising (only when `when(args)` holds)."""
        seed_store(self.legacy, 6)
        real = getattr(target, attr)

        def boom(*a, **kw):
            if when is None or when(*a):
                raise OSError("simulated crash in %s" % attr)
            return real(*a, **kw)

        patches = [mock.patch.object(target, attr, side_effect=boom)]
        if copied:
            d = mp_mod._device(self.legacy)
            patches.append(mock.patch.object(
                mp_mod, "_device", side_effect=lambda p: d if p == self.legacy else d + 1))
        for p in patches:
            p.start()
        try:
            r = self.settle()
        finally:
            for p in reversed(patches):
                p.stop()
        return r

    def assert_rolled_back(self, r):
        self.assertEqual((r.action, r.path), ("kept_legacy", self.legacy))
        self.assertFalse(os.path.islink(self.legacy))
        self.assertFalse(os.path.lexists(self.new))
        self.assertFalse(os.path.exists(self.new + ".partial"))
        self.assertEqual([f for f in os.listdir(os.path.dirname(self.legacy)) if ".migrated-" in f], [])
        self.assert_intact(r, 6)
        self.assertIsNone(self.marker())
        # The next start, without the fault, finishes the move.
        self.assertIn(self.settle().action, ("moved", "copied"))
        self.assertTrue(store_opens_with(self.new, 6))

    def test_crash_at_mkdir(self):
        self.assert_rolled_back(self._crash(mp_mod.os, "makedirs"))

    def test_crash_at_link(self):
        self.assert_rolled_back(self._crash(mp_mod.os, "link"))

    def test_crash_at_symlink_replace(self):
        self.assert_rolled_back(self._crash(mp_mod.os, "replace",
                                            when=lambda src, dst: dst == self.legacy))

    def test_crash_at_backup(self):
        self.assert_rolled_back(self._crash(mp_mod, "_backup", copied=True))

    def test_crash_at_fsync(self):
        self.assert_rolled_back(self._crash(mp_mod, "_fsync_file", copied=True))

    def test_crash_at_partial_rename(self):
        self.assert_rolled_back(self._crash(mp_mod.os, "replace", copied=True,
                                            when=lambda src, dst: dst == self.new))

    def test_crash_at_keeping_the_original(self):
        self.assert_rolled_back(self._crash(mp_mod.os, "link", copied=True))

    def test_crash_at_copy_symlink_replace(self):
        self.assert_rolled_back(self._crash(mp_mod.os, "replace", copied=True,
                                            when=lambda src, dst: dst == self.legacy))

    def test_a_copy_missing_events_is_rejected(self):
        seed_store(self.legacy, 6)
        short = seed_store(os.path.join(self.root, "short.db"), 5)
        d = mp_mod._device(self.legacy)

        def bad_backup(src, dst):
            sqlite3.connect(short).backup(dst)

        with mock.patch.object(mp_mod, "_device", side_effect=lambda p: d if p == self.legacy else d + 1), \
                mock.patch.object(mp_mod, "_backup", side_effect=bad_backup):
            r = self.settle()
        self.assert_rolled_back(r)

    def test_a_crash_after_the_symlink_keeps_the_move(self):
        # Past step 8 the data is only reachable as `new`: undoing would lose it.
        r = self._crash(mp_mod, "_fsync_dir", when=lambda p: p == os.path.dirname(self.legacy))
        self.assertEqual((r.action, r.path), ("moved", self.new))
        self.assertTrue(os.path.islink(self.legacy))
        self.assert_intact(r, 6)

    def test_marker_write_failure_does_not_undo_the_move(self):
        r = self._crash(mp_mod, "_append_marker")
        self.assertEqual(r.action, "moved")
        self.assert_intact(r, 6)

    def test_process_death_between_link_and_symlink_is_finished_next_start(self):
        seed_store(self.legacy, 6)
        os.makedirs(os.path.dirname(self.new))
        os.link(self.legacy, self.new)           # the state a kill at step 8 leaves
        r = self.settle()
        self.assertEqual((r.action, r.path), ("moved", self.new))
        self.assertTrue(os.path.islink(self.legacy))
        self.assert_intact(r, 6)
        self.assertEqual(self.log.at(logging.WARNING), [], "an interrupted move is not a conflict")

    def test_process_death_mid_copy_leaves_a_partial_that_is_replaced(self):
        seed_store(self.legacy, 6)
        os.makedirs(os.path.dirname(self.new))
        with open(self.new + ".partial", "wb") as fh:
            fh.write(b"half a copy")
        d = mp_mod._device(self.legacy)
        with mock.patch.object(mp_mod, "_device", side_effect=lambda p: d if p == self.legacy else d + 1):
            r = self.settle()
        self.assertEqual(r.action, "copied")
        self.assert_intact(r, 6)

    def test_an_unexpected_error_keeps_legacy_and_never_raises(self):
        seed_store(self.legacy, 2)
        with mock.patch.object(mp_mod, "_settle_db", side_effect=RuntimeError("bug")):
            r = self.settle()
        self.assertEqual((r.action, r.path), ("kept_legacy", self.legacy))
        mp_mod.reset_warnings()
        with mock.patch.object(mp_mod, "_settle_db", side_effect=RuntimeError("bug")):
            r = settle_db_path(self.new, os.path.join(self.root, "none.db"), home=self.home)
        self.assertEqual((r.action, r.path), ("kept_legacy", self.new))


class TestTiming(Base):
    def test_a_50mb_store_moves_within_the_start_budget(self):
        seed_store(self.legacy, 10000, pad=5000)
        size_mb = os.path.getsize(self.legacy) / 1e6
        self.assertGreater(size_mb, 45)
        t0 = time.monotonic()
        self.assertEqual(self.settle().action, "moved")
        moved_s = time.monotonic() - t0

        legacy2 = os.path.join(self.root, "profiles", "q", DB_REL)
        seed_store(legacy2, 10000, pad=5000)
        new2 = os.path.join(self.root, "data", "q", "chronicle.db")
        d = mp_mod._device(legacy2)
        t0 = time.monotonic()
        with mock.patch.object(mp_mod, "_device", side_effect=lambda p: d if p == legacy2 else d + 1):
            r = settle_db_path(new2, legacy2, home=os.path.dirname(os.path.dirname(legacy2)))
        copied_s = time.monotonic() - t0
        self.assertEqual(r.action, "copied")
        sys.stderr.write("\n[timing] %.0f MB store: moved in %.3f s, copied in %.3f s\n"
                         % (size_mb, moved_s, copied_s))
        self.assertLess(moved_s, 5.0)
        self.assertLess(copied_s, 5.0)


# --------------------------------------------------------------------------
# settle_git_repo and the bounded flush
# --------------------------------------------------------------------------
class TestGit(Base):
    def setUp(self):
        super().setUp()
        self.store_path = seed_store(os.path.join(self.home, DB_REL), 25)
        self.store = MemoryStore(self.store_path)
        self.addCleanup(self.store.close)
        # Everything was mirrored to the old shared repo already.
        conn = self.store._conn()
        conn.execute("INSERT INTO git_queue(event_id, committed) SELECT event_id, 1 FROM events")
        conn.execute("INSERT INTO git_queue(event_id, committed) SELECT event_id, 0 FROM events "
                     "WHERE seq > 22")   # three still pending for the old one
        conn.commit()
        self.repo = os.path.join(self.home, GIT_REL)
        self.shared = os.path.join(self.root, "shared-git")
        os.makedirs(os.path.join(self.shared, "events"))
        with open(os.path.join(self.shared, "events", "other.jsonl"), "w") as fh:
            fh.write("{}\n")

    def settle_git(self, repo=None, store=None, home=None):
        return settle_git_repo(repo or self.repo, self.shared, store or self.store,
                               enabled=True, remote=None, home=home or self.home)

    def test_requeues_every_event_exactly_once_and_only_once(self):
        r = self.settle_git()
        self.assertEqual((r.action, r.path), ("copied", self.repo))
        self.assertEqual(self.store.git_lag(), 25)
        pending = self.store._conn().execute(
            "SELECT COUNT(DISTINCT event_id) FROM git_queue WHERE committed=0").fetchone()[0]
        self.assertEqual(pending, 25)
        self.assertEqual(self.store.get_meta("git_mirror_repo"), "home:" + GIT_REL)
        self.assertTrue(os.path.isdir(self.repo))
        warns = self.log.at(logging.WARNING)
        self.assertEqual(len(warns), 1)
        self.assertIn(self.shared, warns[0].getMessage())
        r2 = self.settle_git()
        self.assertEqual(r2.action, "none")
        self.assertEqual(self.store.git_lag(), 25)

    def test_the_marker_does_not_hold_where_the_home_is(self):
        # The same profile at another path (a restored home, a fresh temporary
        # home per run) must write the same store, and must not take its own
        # mirror for a new one and queue every event again.
        other_home = os.path.join(self.root, "restored", "p")
        other = MemoryStore(seed_store(os.path.join(other_home, DB_REL), 3))
        self.addCleanup(other.close)
        self.settle_git()
        self.settle_git(os.path.join(other_home, GIT_REL), other, other_home)
        self.assertEqual(other.get_meta("git_mirror_repo"), self.store.get_meta("git_mirror_repo"))
        self.assertNotIn(self.root, self.store.get_meta("git_mirror_repo"))

    def test_a_home_reached_through_a_symlink_is_the_same_mirror(self):
        self.settle_git()
        alias = os.path.join(self.root, "alias-home")
        os.symlink(self.home, alias)
        r = self.settle_git(os.path.join(alias, GIT_REL), home=alias)
        self.assertEqual(r.action, "none")
        self.assertEqual(self.store.git_lag(), 25)

    def test_a_mirror_outside_the_home_is_recorded_by_its_realpath(self):
        # A sibling whose name starts with the home's name is not inside it.
        for repo in (os.path.join(self.root, "mirrors", "p"), self.home + "-old/git"):
            r = self.settle_git(repo)
            self.assertEqual(r.path, repo)
            self.assertEqual(self.store.get_meta("git_mirror_repo"), os.path.realpath(repo))
            self.assertEqual(self.settle_git(repo).action, "none")

    def test_no_home_records_the_realpath(self):
        settle_git_repo(self.repo, self.shared, self.store, enabled=True, remote=None)
        self.assertEqual(self.store.get_meta("git_mirror_repo"), os.path.realpath(self.repo))

    def test_the_legacy_mirror_is_untouched(self):
        before = sorted(os.listdir(os.path.join(self.shared, "events")))
        settle_git_repo(self.repo, self.shared, self.store, enabled=True, remote=None)
        mirror = GitMirror(self.store, _Cfg({}), repo=self.repo)
        self.assertEqual(mirror.flush(), 25)
        self.assertEqual(sorted(os.listdir(os.path.join(self.shared, "events"))), before)
        self.assertFalse(os.path.exists(os.path.join(self.shared, ".git")))
        n = sum(len(open(os.path.join(dp, f)).read().splitlines())
                for dp, _, fs in os.walk(os.path.join(self.repo, "events")) for f in fs)
        self.assertEqual(n, 25)

    def test_remote_warns_that_history_differs(self):
        settle_git_repo(self.repo, self.shared, self.store, enabled=True, remote="git@example:x")
        self.assertTrue(any("remote" in w.getMessage() for w in self.log.at(logging.WARNING)))

    def test_disabled_or_same_repo_is_none(self):
        r = settle_git_repo(self.repo, self.shared, self.store, enabled=False, remote=None)
        self.assertEqual(r.action, "none")
        alias = os.path.join(self.root, "alias")
        os.makedirs(self.repo)
        os.symlink(self.repo, alias)
        r = settle_git_repo(self.repo, alias, self.store, enabled=True, remote=None)
        self.assertEqual(r.action, "none")
        self.assertEqual(self.store.git_lag(), 3)
        self.assertIsNone(self.store.get_meta("git_mirror_repo"))

    def test_never_raises(self):
        with mock.patch.object(self.store, "requeue_all_for_git", side_effect=RuntimeError("x")):
            r = settle_git_repo(self.repo, self.shared, self.store, enabled=True, remote=None)
        self.assertEqual(r.action, "kept_legacy")
        self.assertEqual(r.path, self.repo)

    def test_flush_is_bounded_per_call(self):
        settle_git_repo(self.repo, self.shared, self.store, enabled=True, remote=None)
        mirror = GitMirror(self.store, _Cfg({"git.max_commit_rows": 10,
                                             "git.max_flush_batches": 2}), repo=self.repo)
        self.assertEqual(mirror.flush(), 20)
        self.assertEqual(self.store.git_lag(), 5)
        self.assertEqual(mirror.flush(), 5)
        self.assertEqual(self.store.git_lag(), 0)
        self.assertEqual(mirror.flush(max_batches=1), 0)


class _Cfg:
    def __init__(self, d):
        self.d = d

    def get(self, key, default=None):
        return self.d.get(key, default)


# --------------------------------------------------------------------------
# ChronicleCore wiring
# --------------------------------------------------------------------------
class TestCoreWiring(Base):
    def _core(self, cfg):
        core = ChronicleCore(self.home, dict(HASHING, **cfg))
        self.addCleanup(core.close)
        return core

    def _old_store(self, n_turns=3, git=False):
        """A store where 5.11.1 put it for this profile, holding a few turns."""
        old = ChronicleCore(self.home, dict(HASHING, **{"git": {"enabled": git}}))
        for i in range(n_turns):
            old.capture.observe("turn %d about the garden" % i, "ok", session_id="s1",
                                occurred_at="2026-01-01T00:00:0%d.000Z" % i)
        n = old.store.count_rows("events")
        old.close()
        self.assertEqual(old.store.db_path, self.legacy)
        return n

    def test_absolute_db_path_ignored_by_5_11_1_is_moved_to(self):
        n = self._old_store()
        core = self._core({"db_path": self.new, "git": {"enabled": False}})
        self.assertEqual(core.store.db_path, self.new)
        self.assertEqual(core.store_migration.action, "moved")
        self.assertEqual(core.store.count_rows("events"), n)
        self.assertTrue(os.path.islink(self.legacy))
        self.assertEqual(os.readlink(self.legacy), self.new)
        rec = self.marker()
        self.assertEqual(rec[0]["from"], self.legacy)
        self.assertEqual(rec[0]["to"], self.new)
        # Still writable after the move.
        core.capture.observe("one more", "ok", session_id="s1",
                             occurred_at="2026-01-02T00:00:00.000Z")
        self.assertGreater(core.store.count_rows("events"), n)

    def test_symlinked_commons_moves_nothing_and_says_nothing(self):
        real = os.path.join(self.root, "real-commons")
        os.makedirs(real)
        os.symlink(real, os.path.join(self.home, "commons"))
        n = self._old_store()
        self.log.records.clear()
        configured = os.path.join(real, os.path.relpath(DB_REL, "commons"))
        core = self._core({"db_path": configured, "git": {"enabled": False}})
        self.assertEqual(core.store_migration.action, "none")
        self.assertEqual(core.store.count_rows("events"), n)
        self.assertFalse(os.path.islink(self.legacy))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(configured), MARKER_NAME)))
        self.assertEqual(self.log.at(logging.WARNING), [])

    def test_named_profile_gets_its_own_mirror_requeued_once(self):
        fake_user_home = os.path.join(self.root, "user")
        with mock.patch.dict(os.environ, {"HOME": fake_user_home}):
            shared = os.path.expanduser("~/.hermes/" + GIT_REL)
            os.makedirs(os.path.join(shared, "events"))
            with open(os.path.join(shared, "events", "other.jsonl"), "w") as fh:
                fh.write("{}\n")
            n = self._old_store(git=True)
            # 5.11.1 had no mirror key, and had flushed everything to the shared mirror.
            with closing(sqlite3.connect(self.legacy)) as c:
                c.execute("DELETE FROM meta WHERE key='git_mirror_repo'")
                c.execute("UPDATE git_queue SET committed=1")
                c.commit()
            core = self._core({"git": {"enabled": True}})
            own = os.path.join(self.home, GIT_REL)
            self.assertEqual(core.gitmirror.repo, own)
            self.assertEqual(core.git_migration.action, "copied")
            self.assertEqual(core.store.git_lag(), n)
            core.close()
            again = self._core({"git": {"enabled": True}})
            self.assertEqual(again.git_migration.action, "none")
            self.assertEqual(again.store.git_lag(), n)
            self.assertEqual(again.flush_git(), n)
            self.assertEqual(os.listdir(os.path.join(shared, "events")), ["other.jsonl"])
            self.assertFalse(os.path.exists(os.path.join(shared, ".git")))
            self.assertTrue(os.path.isdir(os.path.join(own, ".git")) or
                            os.path.isdir(os.path.join(own, "events")))

    def test_get_is_keyed_by_the_resolved_home(self):
        a = ChronicleCore.get(self.home, dict(HASHING, **{"git": {"enabled": False}}))
        self.addCleanup(a.close)
        self.assertIs(ChronicleCore.get(self.home + "/"), a)
        self.assertIs(ChronicleCore.get(os.path.join(self.home, ".", "")), a)
        self.assertEqual(a.hermes_home, os.path.abspath(self.home))


if __name__ == "__main__":
    unittest.main()
