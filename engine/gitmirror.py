"""
Chronicle — Git mirror & recovery (§26).

A flusher streams pending `git_queue` rows to per-day JSONL files, commits, marks
them flushed, and (optionally) pushes. Because the git_queue row commits inside
the write transaction (I7), only events newer than the last flush
(≤ max_lag_minutes) can ever be lost. Recovery: belief-store loss → rebuild();
SQLite-file loss → replay events/*.jsonl then rebuild().
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

try:
    from .paths import GIT_REL, expand_data_path, resolve_home
except Exception:  # standalone tooling / pytest from the repo root
    from paths import GIT_REL, expand_data_path, resolve_home

logger = logging.getLogger("chronicle.gitmirror")

#: Batches one `flush()` drains when neither the caller nor the config says.
DEFAULT_MAX_FLUSH_BATCHES = 10


#: The identity of every mirror commit. It lives in the mirror's own config.
MIRROR_NAME = "Chronicle"
MIRROR_EMAIL = "chronicle@local"

#: Inherited variables that would make git act on a repository other than the
#: one `-C` names, or commit as someone other than the mirror. A host started
#: from a git hook, or with GIT_DIR exported, would otherwise send every mirror
#: command to that repository, and the top-level check below would pass.
_SCRUBBED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
                 "GIT_PREFIX", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
                 "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                 "GIT_COMMITTER_EMAIL")


def _git_env(repo: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
    real = os.path.realpath(repo)
    parent = os.path.dirname(real)
    if parent and parent != real:
        # git never looks above the mirror directory for a repository: a
        # mirror without one of its own fails instead of finding, and
        # committing into, whatever repository encloses it.
        env["GIT_CEILING_DIRECTORIES"] = parent
    # The paths handed to `add` and `commit` are file names, never patterns.
    env["GIT_LITERAL_PATHSPECS"] = "1"
    return env


def _invoke(repo: str, args, capture: bool):
    try:
        proc = subprocess.run(["git", "-C", repo, *args], check=True,
                              stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, env=_git_env(repo))
    except (subprocess.CalledProcessError, OSError):
        return None
    return proc.stdout if capture else b""


def _run_git(repo: str, *args) -> bool:
    return _invoke(repo, args, False) is not None


def _git_stdout(repo: str, *args) -> Optional[str]:
    out = _invoke(repo, args, True)
    return None if out is None else out.decode("utf-8", "surrogateescape").strip()


def _same_dir(a: str, b: str) -> bool:
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)      # case-insensitive filesystems
    except OSError:
        return False


def init_git_repo(repo: str, git=None) -> bool:
    """Create `repo` and make it a git repository of its own unless it has a `.git`.

    The one place a mirror repository is created: `GitMirror.init_repo` (on
    every flush that has rows) and the profile-path migration both call it.
    `git(*args)` runs one git command in `repo` and says whether it worked;
    the default runs git. Returns whether `repo` now has a `.git`.

    The identity goes into the repository's own config, so mirror commits
    never carry the identity of whoever runs the host. A failed `init` stops
    here: `git config` in a directory that is not a repository writes to the
    config of the repository that encloses it, if any.
    """
    run = git or (lambda *a: _run_git(repo, *a))
    Path(repo).mkdir(parents=True, exist_ok=True)
    if (Path(repo) / ".git").exists():
        return True
    return bool(run("init") and run("config", "user.email", MIRROR_EMAIL)
                and run("config", "user.name", MIRROR_NAME))


class GitMirror:
    def __init__(self, store, cfg, repo=None):
        """`repo` is the mirror directory; ChronicleCore passes the profile's own.

        Without it the path is worked out the same way (the configured
        `git_repo` under the resolved Hermes home). Before 5.12 `~` was
        expanded against the user's home, so every profile shared one mirror.
        """
        self.store = store
        self.cfg = cfg
        self.repo = repo or expand_data_path(cfg.get("git_repo"), resolve_home(None), GIT_REL)
        self.remote = cfg.get("git_remote")
        self.enabled = cfg.get("git.enabled", True)
        self.max_rows = cfg.get("git.max_commit_rows", 1000)
        self.max_batches = cfg.get("git.max_flush_batches", DEFAULT_MAX_FLUSH_BATCHES)
        self.encryption_key = os.environ.get("CHRONICLE_GIT_ENCRYPTION_KEY") or cfg.get("git.encryption_key")

    def _encrypt_payload(self, text: str) -> str:
        """Client-side symmetric payload encryption for git mirror files if key is set."""
        if not self.encryption_key:
            return text
        import base64
        import hashlib
        key_bytes = hashlib.blake2b(self.encryption_key.encode("utf-8"), digest_size=32).digest()
        raw = text.encode("utf-8")
        cipher = bytearray(len(raw))
        for i in range(len(raw)):
            cipher[i] = raw[i] ^ key_bytes[i % len(key_bytes)]
        return "ENC:" + base64.b64encode(cipher).decode("utf-8")

    def _decrypt_payload(self, text: str) -> str:
        """Client-side symmetric payload decryption for git mirror files if encrypted."""
        if not text.startswith("ENC:"):
            return text
        if not self.encryption_key:
            logger.warning("Encrypted mirror log found but no encryption_key configured")
            return text
        import base64
        import hashlib
        key_bytes = hashlib.blake2b(self.encryption_key.encode("utf-8"), digest_size=32).digest()
        raw = base64.b64decode(text[4:].encode("utf-8"))
        plain = bytearray(len(raw))
        for i in range(len(raw)):
            plain[i] = raw[i] ^ key_bytes[i % len(key_bytes)]
        return plain.decode("utf-8")

    def _git(self, *args) -> bool:
        return _run_git(self.repo, *args)

    def _git_out(self, *args) -> Optional[str]:
        return _git_stdout(self.repo, *args)

    def init_repo(self) -> bool:
        """Make the mirror directory a repository of its own; True if it is one."""
        if not self.enabled:
            return False
        return init_git_repo(self.repo, git=self._git)

    def _repo_ready(self) -> bool:
        """Whether this flush may run git: the mirror is a repository whose top
        level is the mirror directory itself. Logs one WARNING when it is not.

        Nothing used to create the repository, so git walked up from a mirror
        inside another work tree (a home kept in a dotfiles repository) and
        `add -A` committed that whole tree, with its owner's identity.
        """
        try:
            if not self.init_repo():
                logger.warning("chronicle: could not make the git mirror %s a git repository; "
                               "its events are written there but not committed.", self.repo)
                return False
            top = self._git_out("rev-parse", "--show-toplevel")
        except Exception as e:  # noqa: BLE001 -- the mirror must never fail a flush
            logger.warning("chronicle: could not set up the git mirror %s (%s); its events "
                           "are written there but not committed.", self.repo, e)
            return False
        if not top:
            logger.warning("chronicle: git cannot read the repository of the git mirror %s; "
                           "its events are written there but not committed.", self.repo)
            return False
        if not _same_dir(top, self.repo):
            logger.warning("chronicle: the git mirror %s is not a repository of its own: git "
                           "resolves it to %s. Its events are written there but not "
                           "committed.", self.repo, top)
            return False
        return True

    def _write_batch(self, rows):
        """Append `rows` to their day's JSONL files; return (gids, paths written).

        The paths are relative to the mirror and are the only ones a commit
        stages.
        """
        by_day = {}
        for r in rows:
            day = (r.get("recorded_at") or "")[:10] or "unknown"
            by_day.setdefault(day, []).append(r)
        gids = []
        written = []
        for day, evs in by_day.items():
            d = Path(self.repo) / "events" / day
            d.mkdir(parents=True, exist_ok=True)
            stamp = (evs[0].get("recorded_at") or "0").replace(":", "").replace(".", "")[:15]
            name = f"{stamp}-{evs[0]['event_id'][3:11]}.jsonl"
            with open(d / name, "a", encoding="utf-8") as fh:
                for e in evs:
                    line_raw = json.dumps({k: e[k] for k in (
                        "event_id", "seq", "type", "payload", "parents", "actor", "owner",
                        "trust_level", "session_id", "occurred_at", "recorded_at")},
                        ensure_ascii=False)
                    fh.write(self._encrypt_payload(line_raw) + "\n")
                    gids.append(e["gid"])
            rel = "events/%s/%s" % (day, name)
            if rel not in written:
                written.append(rel)
        return gids, written

    def flush(self, max_batches=None) -> int:
        """Drain pending git_queue rows → events/YYYY-MM-DD/HHMMSS.jsonl → commit (§26).

        At most `max_batches` commits of `max_commit_rows` each per call
        (default `git.max_flush_batches`); the rest waits for the next call. A
        profile that gets its own mirror queues its whole store at once, and
        draining that in one call would hold the host's shutdown for minutes.

        The JSONL is always written. git runs only when the mirror is a
        repository of its own (created here when it has no `.git`); otherwise,
        or when any git command fails, the flush logs one WARNING, runs no
        more git, and marks its rows "uncommitted".

        A commit stages exactly the files this flush wrote. Files already in
        the mirror directory, such as those of older releases that never
        created the repository, stay untracked.
        """
        if not self.enabled:
            return 0
        limit = self.max_batches if max_batches is None else max_batches
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = DEFAULT_MAX_FLUSH_BATCHES
        flushed = 0
        batches = 0
        usable = None          # checked once, at the first batch that has rows
        committed = False
        while batches < limit:
            batches += 1
            rows = self.store.get_unflushed_git_events(limit=self.max_rows)
            if not rows:
                break
            gids, written = self._write_batch(rows)
            if usable is None:
                usable = self._repo_ready()
            commit = "uncommitted"
            if usable:
                message = f"chronicle: {len(gids)} events"
                # Never `add -A` or `.`: those would stage files this flush did
                # not write. The paths on `commit` also leave out anything else
                # that happens to be staged in the mirror.
                if (self._git("add", "--", *written)
                        and self._git("commit", "-q", "-m", message, "--", *written)):
                    commit = "committed"
                    committed = True
                else:
                    usable = False
                    logger.warning("chronicle: git could not commit to the git mirror %s; "
                                   "its events are written there but not committed.", self.repo)
            self.store.mark_git_flushed(gids, commit)
            flushed += len(gids)
            if len(rows) < self.max_rows:
                break
        # One push carries every commit of this flush. A failed push loses
        # nothing: the commits stay local and a later push carries them.
        if committed and self.remote and not self._git("push", "origin", "HEAD"):
            logger.warning("chronicle: could not push the git mirror %s; its commits are kept "
                           "locally.", self.repo)
        return flushed

    def replay_from_disk(self, append_event):
        """Recovery: replay events/*.jsonl into a fresh store (then rebuild)."""
        root = Path(self.repo) / "events"
        if not root.exists():
            return 0
        n = 0
        for day in sorted(root.iterdir()):
            for fp in sorted(day.glob("*.jsonl")):
                for line in open(fp, "r", encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    line = self._decrypt_payload(line)
                    ev = json.loads(line)
                    ev.setdefault("prev_head", None)
                    ev.setdefault("sig", None)
                    ev.setdefault("branch_id", ev.get("session_id"))
                    append_event(ev)
                    n += 1
        return n
