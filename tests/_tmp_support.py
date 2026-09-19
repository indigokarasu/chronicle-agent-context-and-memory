"""Temp-file cleanup helpers shared by the test suite (audit A11).

`MemoryStore` opens its SQLite connection in WAL mode and never closes it —
connections are thread-local and the engine has no `close()`. So a test that
does `tempfile.NamedTemporaryFile(suffix=".db", delete=False)` and then
`os.unlink(path)` in tearDown removes one file and leaves two behind:
`<path>-wal` and `<path>-shm`. Multiplied across the suite that was ~100 stray
files per run, plus ~200 `mkdtemp()` homes nobody removed at all.

Use `remove_db(path)` wherever a bare `os.unlink` on a store path is written,
and `rm_tree(path)` for a home directory. Both are idempotent and never raise,
so they are safe in `tearDown` and in `addCleanup`.
"""

from __future__ import annotations

import os
import shutil
import tempfile

#: The files SQLite can leave next to a database in WAL mode.
DB_SIDECARS = ("-wal", "-shm", "-journal")

#: Directories handed out by `temp_home()` since the last `collect_tracked()`.
#: conftest's per-test fixture drains this and removes whatever is left, so a
#: module-level helper such as `make_core()` — which has no test instance to
#: hang an addCleanup on, and is where most of the ~200 leaked directories per
#: run came from — no longer has to be rewritten to take one.
_TRACKED: list = []


def temp_home(prefix: str = "chronicle-test-") -> str:
    """`tempfile.mkdtemp()` whose result the harness will remove after the test."""
    path = tempfile.mkdtemp(prefix=prefix)
    _TRACKED.append(path)
    return path


def collect_tracked() -> list:
    """Return and forget every directory `temp_home()` has handed out."""
    out = list(_TRACKED)
    del _TRACKED[:]
    return out


def remove_db(path: str) -> None:
    """Remove a SQLite database and every sidecar it may have left."""
    for candidate in (path,) + tuple(path + s for s in DB_SIDECARS):
        try:
            os.unlink(candidate)
        except OSError:
            pass


def rm_tree(path: str) -> None:
    """Remove a temp directory tree; never raises."""
    shutil.rmtree(path, ignore_errors=True)
