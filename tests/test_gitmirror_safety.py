"""
Chronicle — the git mirror commits only into a repository of its own.

`GitMirror.flush()` wrote `events/<day>/*.jsonl` and then ran `git -C <mirror>
add -A` and `git commit` without ever creating the mirror's repository. When
the mirror directory sat inside another work tree (a home kept in a dotfiles
repository), git walked up and committed THAT repository's whole working tree,
untracked secrets included, with its owner's identity. With no enclosing
repository nothing was ever committed.

Every test here runs real git under a temporary directory, with the global and
system git config shut out and a ceiling at the test's own directory, so no
command can reach a repository outside it.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

if shutil.which("git") is None:
    pytest.skip("git is not installed", allow_module_level=True)

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.gitmirror import GitMirror
from engine.paths import GIT_REL
from engine.store import MemoryStore

HASHING = {"embeddings": {"model": "hashing"}}
IDENTITY = "Chronicle <chronicle@local>"

#: Inherited variables that would point git at another repository or another
#: identity, for the test's own git commands as much as the engine's.
_GIT_ENV_OUT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
                "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
                "GIT_CONFIG_COUNT")


def git(cwd, *args):
    """Run git in `cwd` and return its stripped stdout; raise on failure."""
    return subprocess.run(["git", "-C", cwd] + list(args), check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def make_enclosing(path):
    """A repository standing in for a home kept in a dotfiles repository.

    It has a commit, an unstaged edit and untracked files, one of them a
    `.env`: everything `add -A` would have swept into a commit.
    """
    os.makedirs(path)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Enclosing Owner")
    git(path, "config", "user.email", "owner@example.invalid")
    write(os.path.join(path, "tracked.txt"), "one\n")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-q", "-m", "base")
    write(os.path.join(path, "tracked.txt"), "one\ntwo\n")
    write(os.path.join(path, ".env"), "EXAMPLE=1\n")
    write(os.path.join(path, "notes", "todo.txt"), "later\n")
    return path


def snapshot(path):
    """Everything about a repository a stray mirror commit could change."""
    with open(os.path.join(path, ".git", "config"), encoding="utf-8") as fh:
        config = fh.read()
    return {"head": git(path, "rev-parse", "HEAD"),
            "refs": git(path, "for-each-ref", "--format=%(refname) %(objectname)"),
            "index": git(path, "ls-files", "--stage"),
            "status": sorted(git(path, "status", "--porcelain").splitlines()),
            "config": config}


def assert_untouched(case, path, before, new_dir):
    """`path` is exactly as `before`, apart from `new_dir` now showing as untracked."""
    after = snapshot(path)
    for key in ("head", "refs", "index", "config"):
        case.assertEqual(after[key], before[key], key)
    want = sorted(set(before["status"]) | {"?? %s/" % new_dir})
    case.assertEqual(after["status"], want)


def add_events(store, first, n, day):
    """Append `n` events to `store` and queue each for the mirror, as capture does."""
    conn = store._conn()
    ids = []
    for i in range(first, first + n):
        # Distinct characters at [3:11]: the flush names its files by them.
        eid = "ev_%08d%056d" % (i, 0)
        ids.append(eid)
        stamp = "%sT10:00:%02d.000Z" % (day, i % 60)
        conn.execute(
            "INSERT INTO events(event_id,seq,type,payload,parents,actor,owner,trust_level,"
            "session_id,occurred_at,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (eid, i, "observed", '{"i": %d}' % i, "[]", "user", "default", 2, "s1",
             stamp, stamp))
        conn.execute("INSERT INTO git_queue(event_id, created_at) VALUES(?, ?)", (eid, stamp))
    conn.execute("UPDATE meta SET value=? WHERE key='event_seq'", (str(first + n - 1),))
    conn.commit()
    return ids


def queue_states(store):
    rows = store._conn().execute(
        "SELECT git_commit, COUNT(*) FROM git_queue GROUP BY git_commit").fetchall()
    return {r[0]: r[1] for r in rows}


def mirror_files(repo):
    """Every file under the mirror's `events/`, relative to the mirror."""
    root = os.path.join(repo, "events")
    out = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            out.append(os.path.relpath(os.path.join(dp, f), repo).replace(os.sep, "/"))
    return sorted(out)


def jsonl_ids(repo, paths):
    ids = []
    for p in paths:
        with open(os.path.join(repo, p), encoding="utf-8") as fh:
            ids.extend(json.loads(line)["event_id"] for line in fh if line.strip())
    return ids


class _Cfg:
    def __init__(self, d):
        self.d = d

    def get(self, key, default=None):
        return self.d.get(key, default)


class _Warnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextmanager
def warnings_from_the_mirror():
    log = logging.getLogger("chronicle.gitmirror")
    handler = _Warnings()
    log.addHandler(handler)
    try:
        yield handler.messages
    finally:
        log.removeHandler(handler)


class GitCase(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(temp_home("chronicle-gitmirror-"))
        env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OUT}
        env.update({
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            # No git command in this file may find a repository above the
            # test's own temporary directory.
            "GIT_CEILING_DIRECTORIES": os.path.dirname(self.root),
        })
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def store(self, name="store"):
        # Outside every repository the test builds.
        os.makedirs(os.path.join(self.root, name))
        store = MemoryStore(os.path.join(self.root, name, "chronicle.db"))
        self.addCleanup(store.close)
        return store

    def mirror(self, store, repo, **cfg):
        return GitMirror(store, _Cfg(cfg), repo=repo)

    def assert_own_repo(self, repo):
        self.assertTrue(os.path.isdir(os.path.join(repo, ".git")))
        self.assertEqual(os.path.realpath(git(repo, "rev-parse", "--show-toplevel")),
                         os.path.realpath(repo))

    def commits(self, repo):
        return git(repo, "rev-list", "--reverse", "HEAD").splitlines()

    def commit_files(self, repo, sha):
        return sorted(git(repo, "show", "--name-only", "--format=", sha).splitlines())

    def authors(self, repo):
        return set(git(repo, "log", "--format=%an <%ae>|%cn <%ce>").splitlines())


# --------------------------------------------------------------------------
# (a) a mirror inside another repository
# --------------------------------------------------------------------------
class TestInsideAnEnclosingRepository(GitCase):
    def test_flush_commits_only_into_a_repository_of_its_own(self):
        outer = make_enclosing(os.path.join(self.root, "outer"))
        before = snapshot(outer)
        store = self.store()
        ids = add_events(store, 1, 5, "2026-01-01")
        repo = os.path.join(outer, "data", "mirror")
        with warnings_from_the_mirror() as warns:
            self.assertEqual(self.mirror(store, repo).flush(), 5)
        self.assertEqual(warns, [])
        assert_untouched(self, outer, before, "data")
        self.assert_own_repo(repo)
        commits = self.commits(repo)
        self.assertEqual(len(commits), 1)
        self.assertEqual(self.authors(repo), {IDENTITY + "|" + IDENTITY})
        written = mirror_files(repo)
        self.assertEqual(self.commit_files(repo, commits[0]), written)
        self.assertEqual(sorted(jsonl_ids(repo, written)), ids)
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(queue_states(store), {"committed": 5})

    def test_an_exported_repository_or_identity_is_ignored(self):
        # A host started from a git hook inherits GIT_DIR and an author.
        outer = make_enclosing(os.path.join(self.root, "outer"))
        before = snapshot(outer)
        os.environ.update({"GIT_DIR": os.path.join(outer, ".git"), "GIT_WORK_TREE": outer,
                           "GIT_AUTHOR_NAME": "Hook Author",
                           "GIT_AUTHOR_EMAIL": "hook@example.invalid",
                           "GIT_COMMITTER_NAME": "Hook Author",
                           "GIT_COMMITTER_EMAIL": "hook@example.invalid"})
        store = self.store()
        add_events(store, 1, 2, "2026-01-01")
        repo = os.path.join(outer, "data", "mirror")
        self.assertEqual(self.mirror(store, repo).flush(), 2)
        for k in _GIT_ENV_OUT:
            os.environ.pop(k, None)
        assert_untouched(self, outer, before, "data")
        self.assert_own_repo(repo)
        self.assertEqual(len(self.commits(repo)), 1)
        self.assertEqual(self.authors(repo), {IDENTITY + "|" + IDENTITY})
        self.assertEqual(queue_states(store), {"committed": 2})

    def test_a_stale_dot_git_does_not_let_git_reach_the_enclosing_repository(self):
        # A `.git` that is not a repository: git would skip it and walk up.
        outer = make_enclosing(os.path.join(self.root, "outer"))
        repo = os.path.join(outer, "data", "mirror")
        os.makedirs(os.path.join(repo, ".git"))
        before = snapshot(outer)
        store = self.store()
        add_events(store, 1, 3, "2026-01-01")
        with warnings_from_the_mirror() as warns:
            self.assertEqual(self.mirror(store, repo).flush(), 3)
        self.assertEqual(len(warns), 1)
        self.assertIn(repo, warns[0])
        assert_untouched(self, outer, before, "data")
        self.assertEqual(len(mirror_files(repo)), 1)
        self.assertEqual(queue_states(store), {"uncommitted": 3})

    def test_a_repository_whose_work_tree_is_elsewhere_is_not_used(self):
        # The mirror's own `.git`, but its work tree is the enclosing one:
        # `add` would stage the enclosing tree into the mirror's history.
        outer = make_enclosing(os.path.join(self.root, "outer"))
        repo = os.path.join(outer, "data", "mirror")
        os.makedirs(repo)
        git(repo, "init", "-q")
        git(repo, "config", "core.worktree", outer)
        before = snapshot(outer)
        store = self.store()
        add_events(store, 1, 3, "2026-01-01")
        with warnings_from_the_mirror() as warns:
            self.assertEqual(self.mirror(store, repo).flush(), 3)
        self.assertEqual(len(warns), 1)
        self.assertIn(repo, warns[0])
        self.assertIn(outer, warns[0])
        self.assertFalse(os.path.exists(os.path.join(repo, ".git", "index")))
        self.assertEqual(git(repo, "rev-list", "--all"), "")
        assert_untouched(self, outer, before, "data")
        self.assertEqual(queue_states(store), {"uncommitted": 3})


# --------------------------------------------------------------------------
# (b) files already in the mirror directory
# --------------------------------------------------------------------------
class TestUnrelatedFiles(GitCase):
    def test_files_already_in_the_mirror_are_never_committed(self):
        repo = os.path.join(self.root, "mirror")
        old = ["events/2025-12-31/2025-12-31T0000-00000000.jsonl", "notes.txt", ".env"]
        for rel in old:
            write(os.path.join(repo, rel), "older release\n")
        store = self.store()
        ids = add_events(store, 1, 4, "2026-01-01")
        self.assertEqual(self.mirror(store, repo).flush(), 4)
        self.assert_own_repo(repo)
        commits = self.commits(repo)
        self.assertEqual(len(commits), 1)
        written = [p for p in mirror_files(repo) if p not in old]
        self.assertEqual(self.commit_files(repo, commits[0]), written)
        self.assertEqual(sorted(jsonl_ids(repo, written)), ids)
        self.assertEqual(sorted(git(repo, "status", "--porcelain").splitlines()),
                         ["?? .env", "?? events/2025-12-31/", "?? notes.txt"])
        self.assertEqual(git(repo, "ls-files"), "\n".join(written))


# --------------------------------------------------------------------------
# (c) git init fails
# --------------------------------------------------------------------------
class TestInitFails(GitCase):
    def test_no_git_runs_one_warning_and_the_rows_are_uncommitted(self):
        outer = make_enclosing(os.path.join(self.root, "outer"))
        before = snapshot(outer)
        store = self.store()
        ids = add_events(store, 1, 5, "2026-01-01")
        repo = os.path.join(outer, "data", "mirror")
        mirror = self.mirror(store, repo)
        real_git = mirror._git
        calls = []

        def failing_init(*args):
            calls.append(args[0] if args else "")
            if args and args[0] == "init":
                return False
            return real_git(*args)

        with mock.patch.object(mirror, "_git", side_effect=failing_init), \
                mock.patch("subprocess.run", wraps=subprocess.run) as run, \
                warnings_from_the_mirror() as warns:
            self.assertEqual(mirror.flush(), 5)
        self.assertEqual(calls, ["init"])
        self.assertEqual(run.call_count, 0)      # no git process ran at all
        self.assertEqual(len(warns), 1)
        self.assertIn(repo, warns[0])
        written = mirror_files(repo)
        self.assertEqual(len(written), 1)
        self.assertEqual(sorted(jsonl_ids(repo, written)), ids)
        self.assertFalse(os.path.exists(os.path.join(repo, ".git")))
        self.assertEqual(queue_states(store), {"uncommitted": 5})
        self.assertEqual(store.git_lag(), 0)
        assert_untouched(self, outer, before, "data")

    def test_a_failed_commit_is_treated_the_same(self):
        repo = os.path.join(self.root, "mirror")
        store = self.store()
        add_events(store, 1, 2, "2026-01-01")
        add_events(store, 3, 2, "2026-01-02")
        mirror = self.mirror(store, repo, **{"git.max_commit_rows": 2})
        real_git = mirror._git
        calls = []

        def failing_commit(*args):
            calls.append(args[0])
            if args[0] == "commit":
                return False
            return real_git(*args)

        with mock.patch.object(mirror, "_git", side_effect=failing_commit), \
                warnings_from_the_mirror() as warns:
            self.assertEqual(mirror.flush(), 4)
        # The second batch runs no git once the first one failed.
        self.assertEqual(calls, ["init", "config", "config", "add", "commit"])
        self.assertEqual(len(warns), 1)
        self.assertEqual(len(mirror_files(repo)), 2)
        self.assertEqual(queue_states(store), {"uncommitted": 4})


# --------------------------------------------------------------------------
# (d) a standalone mirror
# --------------------------------------------------------------------------
class TestStandaloneMirror(GitCase):
    def test_two_flushes_give_two_commits(self):
        repo = os.path.join(self.root, "mirror")
        store = self.store()
        mirror = self.mirror(store, repo)
        first = add_events(store, 1, 3, "2026-01-01")
        self.assertEqual(mirror.flush(), 3)
        files_1 = mirror_files(repo)
        second = add_events(store, 4, 2, "2026-01-02")
        with warnings_from_the_mirror() as warns:
            self.assertEqual(mirror.flush(), 2)
        self.assertEqual(warns, [])
        self.assert_own_repo(repo)
        commits = self.commits(repo)
        self.assertEqual(len(commits), 2)
        files_2 = [p for p in mirror_files(repo) if p not in files_1]
        self.assertEqual(self.commit_files(repo, commits[0]), files_1)
        self.assertEqual(self.commit_files(repo, commits[1]), files_2)
        self.assertEqual(sorted(jsonl_ids(repo, files_1)), first)
        self.assertEqual(sorted(jsonl_ids(repo, files_2)), second)
        self.assertEqual(self.authors(repo), {IDENTITY + "|" + IDENTITY})
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.assertEqual(queue_states(store), {"committed": 5})
        self.assertEqual(mirror.flush(), 0)
        self.assertEqual(len(self.commits(repo)), 2)

    def test_push_runs_once_per_flush_and_its_failure_keeps_the_commits(self):
        repo = os.path.join(self.root, "mirror")
        remote = os.path.join(self.root, "remote.git")
        os.makedirs(remote)
        git(remote, "init", "-q", "--bare")
        store = self.store()
        add_events(store, 1, 2, "2026-01-01")
        add_events(store, 3, 2, "2026-01-02")
        mirror = self.mirror(store, repo, git_remote=remote, **{"git.max_commit_rows": 2})
        self.assertTrue(mirror.init_repo())
        git(repo, "remote", "add", "origin", remote)
        real_git = mirror._git
        with mock.patch.object(mirror, "_git", side_effect=real_git) as spy:
            self.assertEqual(mirror.flush(), 4)
        self.assertEqual([c.args[0] for c in spy.call_args_list].count("push"), 1)
        self.assertEqual(git(remote, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD"))
        # No `origin`: the push fails, the local commit stands.
        git(repo, "remote", "remove", "origin")
        add_events(store, 5, 1, "2026-01-03")
        with warnings_from_the_mirror() as warns:
            self.assertEqual(mirror.flush(), 1)
        self.assertEqual(len(warns), 1)
        self.assertIn("push", warns[0])
        self.assertEqual(len(self.commits(repo)), 3)
        self.assertEqual(queue_states(store), {"committed": 5})


# --------------------------------------------------------------------------
# (e) two profiles
# --------------------------------------------------------------------------
class TestTwoProfiles(GitCase):
    def test_each_profile_gets_its_own_repository(self):
        # The user's home is itself a repository, and holds the default
        # profile and a named one.
        user_home = make_enclosing(os.path.join(self.root, "user"))
        os.environ["HOME"] = user_home
        homes = [os.path.join(user_home, ".hermes"),
                 os.path.join(user_home, ".hermes", "profiles", "work")]
        cores = []
        for n, home in enumerate(homes):
            core = ChronicleCore(home, dict(HASHING))
            self.addCleanup(core.close)
            for i in range(2):
                core.capture.observe("profile %d turn %d about the garden" % (n, i), "ok",
                                     session_id="s%d" % n,
                                     occurred_at="2026-01-0%dT00:00:0%d.000Z" % (n + 1, i))
            cores.append(core)
        before = snapshot(user_home)
        for core in cores:
            self.assertGreater(core.flush_git(), 0)
        assert_untouched(self, user_home, before, ".hermes")
        seen = []
        for home, core in zip(homes, cores):
            repo = os.path.join(home, GIT_REL)
            self.assertEqual(core.gitmirror.repo, repo)
            self.assert_own_repo(repo)
            self.assertEqual(self.authors(repo), {IDENTITY + "|" + IDENTITY})
            written = mirror_files(repo)
            self.assertEqual(sorted(git(repo, "ls-files").splitlines()), written)
            store_ids = sorted(r[0] for r in core.store._conn().execute(
                "SELECT event_id FROM events").fetchall())
            self.assertEqual(sorted(jsonl_ids(repo, written)), store_ids)
            seen.append(set(store_ids))
        self.assertEqual(seen[0] & seen[1], set())
        self.assertNotEqual(os.path.join(homes[0], GIT_REL), os.path.join(homes[1], GIT_REL))


if __name__ == "__main__":
    unittest.main()
