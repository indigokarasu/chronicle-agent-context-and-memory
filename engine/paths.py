"""
Chronicle — Hermes home and data-path resolution.

Every consumer (the store, the git mirror, the dashboard, the scripts) used to
work out the Hermes home and the data paths on its own, and the copies
disagreed:

  * under a profile home (`<root>/profiles/<name>`), a `db_path` written as
    `~/.hermes/profiles/<name>/...` became `.../profiles/<name>/profiles/<name>/...`,
    because `~/.hermes` was replaced with the profile home and the profile was
    then named a second time;
  * an absolute `db_path` was ignored, so the store was written to the default
    location while the config named another;
  * the git mirror expanded `~` against the user's home and never looked at
    the profile, so every profile shared one mirror.

This module is now the only place those rules live. `legacy_db_path` and
`legacy_git_path` keep exact copies of the old rules, quirks included, because
the migration has to find the files where an older release really put them.

Stdlib only. The one host import is wrapped, so the module also works offline
(tests, scripts, a dashboard that cannot import the host).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional, Union
from urllib.parse import quote

logger = logging.getLogger("chronicle.paths")

#: The store, relative to the Hermes home.
DB_REL = "commons/db/chronicle/chronicle.db"
#: The git mirror, relative to the Hermes home.
GIT_REL = "commons/db/chronicle/git"

# The spellings of "the Hermes home" a configured path may start with.
_HOME_PREFIXES = ("~/.hermes", "$HERMES_HOME", "${HERMES_HOME}")

# Set after the first "profile named twice" warning. A config is read on every
# start of every component; a warning per read would bury everything else in
# the log, and one per process is enough to get the config fixed.
_profile_prefix_warned = False

PathLike = Union[str, "os.PathLike[str]"]


def reset_warnings() -> None:
    """Forget which once-only warnings were given (tests use this)."""
    global _profile_prefix_warned
    _profile_prefix_warned = False


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _host_home() -> str:
    """The host's own idea of the home, or "" when it cannot be had.

    Any failure means "no answer": the host package is absent offline, and a
    host that is present but not configured yet can raise from the call. Either
    way the next rule in `resolve_home` decides instead of the caller crashing.
    """
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        home = get_hermes_home()
    except Exception:
        return ""
    return str(home) if home else ""


def resolve_home(explicit: Optional[PathLike] = None) -> str:
    """The Hermes home, as an absolute, normalized path. First match wins:

    1. a non-empty `explicit` (with `~` and `$VARS` expanded);
    2. the host's `hermes_constants.get_hermes_home()`, when it can be had;
    3. a non-empty `$HERMES_HOME`;
    4. `~/.hermes`.

    The host comes before the environment variable because the host knows the
    active profile and the variable may be left over from another one.
    """
    if explicit:
        return _absolute(os.path.expandvars(os.fspath(explicit)))
    host = _host_home()
    if host:
        return _absolute(host)
    env = os.environ.get("HERMES_HOME")
    if env:
        return _absolute(env)
    return _absolute(str(Path.home() / ".hermes"))


def _is_profile_home(home: str) -> bool:
    return os.path.basename(os.path.dirname(home)) == "profiles"


def _strip_profile_prefix(rest: str, home: str, value: str) -> str:
    """Drop `profiles/<name>/` from `rest` when `home` is that very profile.

    `~/.hermes` already means the profile home under a profile, so
    `~/.hermes/profiles/<name>/x` names the profile twice. The old rules turned
    that into `<home>/profiles/<name>/x`, a second store nobody meant to make.
    """
    global _profile_prefix_warned
    h = os.path.normpath(home)
    if not _is_profile_home(h):
        return rest
    prefix = "profiles/" + os.path.basename(h) + "/"
    if not rest.startswith(prefix):
        return rest
    if not _profile_prefix_warned:
        _profile_prefix_warned = True
        logger.warning(
            "chronicle: the path %r names the profile twice: under this profile, "
            "'~/.hermes' already means %s. Reading it without the '%s' part. "
            "Remove that part from the config to silence this warning.",
            value, h, prefix)
    return rest[len(prefix):]


def expand_data_path(value: Optional[str], home: str, default_rel: str) -> str:
    """Where a configured data path points, given the resolved Hermes home.

    * empty: `<home>/<default_rel>`;
    * `~/.hermes`, `$HERMES_HOME` or `${HERMES_HOME}`, optionally followed by
      `/rest`: `<home>/rest` (or `home`), with a doubled profile removed;
    * any other `~...`: expanded against the user's home;
    * absolute: kept, normalized;
    * relative: under `home`.
    """
    v = str(value).strip() if value else ""
    if not v:
        return os.path.join(home, default_rel)
    for prefix in _HOME_PREFIXES:
        if v == prefix or v.startswith(prefix + "/"):
            # lstrip: `~/.hermes//x` must stay inside the home. Joined as is,
            # `/x` would be absolute and replace the home entirely.
            rest = v[len(prefix):].lstrip("/")
            rest = _strip_profile_prefix(rest, home, v)
            return os.path.join(home, rest) if rest else home
    if v.startswith("~"):
        return os.path.expanduser(v)
    if os.path.isabs(v):
        return os.path.normpath(v)
    return os.path.join(home, v)


def legacy_db_path(value: Optional[str], home: str) -> str:
    """Where 5.11.1 put the store for this `db_path` (its `core.py` rule, verbatim).

    Quirks kept on purpose: every `~/.hermes` in the value is replaced, not
    only the leading one; `~/.hermesX` counts as the prefix; an absolute,
    relative or other `~` path is ignored in favour of the default.
    """
    default = str(Path(home) / DB_REL)
    db = value or default
    return db.replace("~/.hermes", str(Path(home))) if db.startswith("~/.hermes") else default


def legacy_git_path(value: Optional[str]) -> str:
    """Where 5.11.1 put the git mirror for this `git_repo` (its `gitmirror.py` rule).

    Only `~` is expanded, against the user's home, so the default ignores the
    profile and a relative value stays relative to the working directory.
    """
    return os.path.expanduser(value or "~/.hermes/" + GIT_REL)


#: The first 16 bytes of every SQLite database file.
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _in_wal_mode(path: str) -> bool:
    """True when the file header says WAL mode (format versions 2 at bytes 18 and 19)."""
    with open(path, "rb") as fh:
        head = fh.read(20)
    return head[:16] == _SQLITE_MAGIC and head[18:20] == b"\x02\x02"


def connect_readonly(db_path: PathLike, timeout: float = 5.0) -> sqlite3.Connection:
    """A read-only connection to an existing, non-empty SQLite file that creates nothing.

    Raises OSError for a missing or empty file (a plain `sqlite3.connect` would
    make an empty database there) and sqlite3.Error when SQLite refuses the open.
    """
    p = os.path.abspath(os.fspath(db_path))
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    if os.path.getsize(p) <= 0:
        raise OSError("empty file: %s" % p)
    query = "?mode=ro"
    # A WAL store closed cleanly keeps no -wal or -shm on standard builds,
    # and a copy of the main file alone has none either. A read-only open
    # then fails where it may not create the -shm (macOS's system SQLite, a
    # read-only directory), so a probe said "no data" and the migration opened
    # an empty store at the new path; elsewhere (Linux, Homebrew) it worked but
    # left a -wal and a -shm behind. With no -wal the main file holds every
    # committed transaction, so `immutable` reads it exactly and creates nothing.
    # Only then: a -wal can hold rows the main file lacks, and a file in
    # rollback mode may be mid-write, which only the locked read waits out.
    if _in_wal_mode(p) and not os.path.lexists(p + "-wal"):
        query += "&immutable=1"
    # Quoted: `?`, `#` and `%` in a file name would otherwise be read as
    # URI syntax and the open would land on a different (new) file.
    uri = "file:" + quote(p, safe="/") + query
    return sqlite3.connect(uri, uri=True, timeout=timeout)


def has_data(db_path: PathLike) -> bool:
    """True only for a SQLite file whose `events` table holds at least one row.

    Never creates a file (see `connect_readonly`): an empty file at the new
    location would otherwise look like a store that is already there. Any
    error is False.
    """
    try:
        conn = connect_readonly(db_path)
    except Exception:
        return False
    try:
        if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone() is None:
            return False
        return conn.execute("SELECT 1 FROM events LIMIT 1").fetchone() is not None
    except Exception:
        return False
    finally:
        conn.close()


def readable_db_path(value: Optional[str], home: str) -> str:
    """The store a read-only consumer should open.

    The new location if it holds data, else the 5.11.1 location if that does,
    else the new location. A dashboard or script run before the store has been
    migrated then still shows the data instead of an empty store.
    """
    new = expand_data_path(value, home, DB_REL)
    if has_data(new):
        return new
    legacy = legacy_db_path(value, home)
    if legacy != new and has_data(legacy):
        return legacy
    return new


def profile_root(home: str) -> str:
    """The Hermes root that holds this home: `<root>` for `<root>/profiles/<name>`, else `home`."""
    h = os.path.normpath(home)
    return os.path.dirname(os.path.dirname(h)) if _is_profile_home(h) else home
