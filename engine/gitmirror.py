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

logger = logging.getLogger("chronicle.gitmirror")


class GitMirror:
    def __init__(self, store, cfg):
        self.store = store
        self.cfg = cfg
        self.repo = os.path.expanduser(cfg.get("git_repo", "~/.hermes/commons/db/chronicle/git"))
        self.remote = cfg.get("git_remote")
        self.enabled = cfg.get("git.enabled", True)
        self.max_rows = cfg.get("git.max_commit_rows", 1000)

    def _git(self, *args) -> bool:
        try:
            subprocess.run(["git", "-C", self.repo, *args], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def init_repo(self):
        if not self.enabled:
            return
        Path(self.repo).mkdir(parents=True, exist_ok=True)
        if not (Path(self.repo) / ".git").exists():
            self._git("init")
            self._git("config", "user.email", "chronicle@local")
            self._git("config", "user.name", "Chronicle")

    def flush(self) -> int:
        """Drain pending git_queue rows → events/YYYY-MM-DD/HHMMSS.jsonl → commit (§26)."""
        if not self.enabled:
            return 0
        flushed = 0
        while True:
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
                        fh.write(json.dumps({k: e[k] for k in (
                            "event_id", "seq", "type", "payload", "parents", "actor", "owner",
                            "trust_level", "session_id", "occurred_at", "recorded_at")},
                            ensure_ascii=False) + "\n")
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
                    ev = json.loads(line)
                    ev.setdefault("prev_head", None)
                    ev.setdefault("sig", None)
                    ev.setdefault("branch_id", ev.get("session_id"))
                    append_event(ev)
                    n += 1
        return n
