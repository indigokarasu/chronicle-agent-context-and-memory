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

try:
    from .paths import GIT_REL, expand_data_path, resolve_home
except Exception:  # standalone tooling / pytest from the repo root
    from paths import GIT_REL, expand_data_path, resolve_home

logger = logging.getLogger("chronicle.gitmirror")

#: Batches one `flush()` drains when neither the caller nor the config says.
DEFAULT_MAX_FLUSH_BATCHES = 10


def _run_git(repo: str, *args) -> bool:
    try:
        subprocess.run(["git", "-C", repo, *args], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def init_git_repo(repo: str) -> None:
    """Create `repo` and make it a git repository of its own, if it is not one.

    Without its own `.git`, `git -C <repo> add -A` would act on whatever
    repository encloses the directory, or fail. Without git installed the
    directory still receives the JSONL files; they are just not committed.
    """
    Path(repo).mkdir(parents=True, exist_ok=True)
    if not (Path(repo) / ".git").exists():
        _run_git(repo, "init")
        _run_git(repo, "config", "user.email", "chronicle@local")
        _run_git(repo, "config", "user.name", "Chronicle")


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

    def init_repo(self):
        if not self.enabled:
            return
        init_git_repo(self.repo)

    def flush(self, max_batches=None) -> int:
        """Drain pending git_queue rows → events/YYYY-MM-DD/HHMMSS.jsonl → commit (§26).

        At most `max_batches` commits of `max_commit_rows` each per call
        (default `git.max_flush_batches`); the rest waits for the next call. A
        profile that gets its own mirror queues its whole store at once, and
        draining that in one call would hold the host's shutdown for minutes.
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
        while batches < limit:
            batches += 1
            rows = self.store.get_unflushed_git_events(limit=self.max_rows)
            if not rows:
                break
            by_day = {}
            for r in rows:
                day = (r.get("recorded_at") or "")[:10] or "unknown"
                by_day.setdefault(day, []).append(r)
            gids = []
            for day, evs in by_day.items():
                d = Path(self.repo) / "events" / day
                d.mkdir(parents=True, exist_ok=True)
                stamp = (evs[0].get("recorded_at") or "0").replace(":", "").replace(".", "")[:15]
                fp = d / f"{stamp}-{evs[0]['event_id'][3:11]}.jsonl"
                with open(fp, "a", encoding="utf-8") as fh:
                    for e in evs:
                        line_raw = json.dumps({k: e[k] for k in (
                            "event_id", "seq", "type", "payload", "parents", "actor", "owner",
                            "trust_level", "session_id", "occurred_at", "recorded_at")},
                            ensure_ascii=False)
                        fh.write(self._encrypt_payload(line_raw) + "\n")
                        gids.append(e["gid"])
            commit = "uncommitted"
            if self._git("add", "-A") and self._git("commit", "-m", f"chronicle: {len(gids)} events"):
                commit = "committed"
                if self.remote:
                    self._git("push", "origin", "HEAD")
            self.store.mark_git_flushed(gids, commit)
            flushed += len(gids)
            if len(rows) < self.max_rows:
                break
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
