"""
Chronicle — moving a store and a git mirror left at an older release's paths.

Before 5.12 the store path rule ignored an absolute `db_path` and named a
profile twice in `~/.hermes/profiles/<name>/...`, and the git mirror ignored the
profile entirely (see engine/paths.py). A store or mirror an older release put
in the wrong place has to end up at the path the config names, automatically,
and without ever losing an event or leaving two live copies of one store.

`settle_db_path` decides where the store is opened and, when it is safe, moves
it there first. `settle_git_repo` points a profile at its own mirror and queues
this store's events for it. Neither raises: a failed or unsafe move leaves the
store exactly where the older release used it, which is the behaviour that
release had, and logs what to do by hand.

The one property everything below protects: a SQLite store in WAL mode must be
opened through ONE name. Two names for one file (two hard links, or a copy and
an original both still written) give two `-wal` files for one database, and a
checkpoint from one side then overwrites pages the other side committed.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

try:
    from .paths import DB_REL, expand_data_path, has_data, profile_root
    from .yaml_load import safe_load_file
except Exception:  # standalone tooling / pytest from the repo root
    from paths import DB_REL, expand_data_path, has_data, profile_root
    from yaml_load import safe_load_file

logger = logging.getLogger("chronicle.migrate")

#: The journal the store moves are recorded in, next to the new store.
MARKER_NAME = "chronicle-migration.json"

#: Meta key naming the mirror this store's events were queued for (see
#: `_mirror_marker` for its two forms).
GIT_META_KEY = "git_mirror_repo"

#: Prefix of a mirror marker written relative to the profile home.
HOME_PREFIX = "home:"

#: How long to wait for another process to let go of the old store before
#: deferring. Start-up has a 5 s budget; this is the one wait the move adds.
LOCK_TIMEOUT_S = 2.0

ACTIONS = ("none", "moved", "copied", "deferred", "kept_legacy", "conflict")

# Warnings that a start-up repeats on every start of every component. One per
# process and pair of paths is enough to get the config fixed.
_warned = set()


def reset_warnings() -> None:
    """Forget which once-only warnings were given (tests use this)."""
    _warned.clear()


def _warn_once(key: tuple, msg: str, *args) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(msg, *args)


@dataclass
class MigrationResult:
    """What a settle call did. `path` is the store (or mirror) the caller MUST open."""
    action: str
    path: str
    detail: str = ""


# -- small seams (tests patch these to simulate a crash or another filesystem) --

def _utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _device(path: str) -> int:
    """The filesystem `path` lives on (a directory or a file)."""
    return os.stat(path).st_dev


def _backup(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    src.backup(dst)


def _fsync_file(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: str) -> None:
    # Makes a rename or link durable across power loss. Not every platform can
    # open a directory; the data is still correct there, only less durable.
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _version() -> str:
    """The release doing the move, read from plugin.yaml (the version's one home)."""
    try:
        manifest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "plugin.yaml")
        with open(manifest, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("version:"):
                    value = line.split(":", 1)[1].split("#", 1)[0].strip().strip("\"'").strip()
                    if value:
                        return value
    except Exception:
        pass
    return "unknown"


# -- helpers ----------------------------------------------------------------

def _same_real(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


def _same_inode(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _close(conn: Optional[sqlite3.Connection]) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def _remove(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _read_yaml(path: str) -> dict:
    try:
        data = safe_load_file(path) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        # A config that cannot be read cannot run Chronicle either, so it
        # cannot be a profile using the store.
        return {}


def _mirror_marker(repo: str, home: Optional[str]) -> str:
    """How the store records which mirror its events were queued for.

    A mirror inside the profile home is recorded relative to the home's
    realpath, as `home:<relative path>`; anywhere else, as its realpath. An
    absolute path to the home put the home's own location into the store, so
    the same profile at another path (a copied or restored home, or a fresh
    temporary home per run) wrote a different store, and every start there
    took the mirror for a new one and queued every event for it again.
    """
    target = os.path.realpath(repo)
    if home:
        base = os.path.realpath(home)
        if target.startswith(base.rstrip(os.sep) + os.sep):
            rel = target[len(base.rstrip(os.sep)) + 1:]
            return HOME_PREFIX + rel.replace(os.sep, "/")
    return target


def _claimed_by_other_profile(legacy: str, home: str) -> str:
    """The home of another Chronicle profile whose own store IS `legacy`, or "".

    Moving that file would take another profile's live store away from it, so
    such a store stays where it is.
    """
    root = profile_root(home)
    homes = [root]
    pdir = os.path.join(root, "profiles")
    try:
        homes += [os.path.join(pdir, d) for d in sorted(os.listdir(pdir))
                  if os.path.isdir(os.path.join(pdir, d))]
    except OSError:
        pass
    for h in homes:
        if _same_real(h, home):
            continue
        # The host's whole config file, not Chronicle's Config: its `memory`
        # and `context` sections say whether that profile runs Chronicle.
        host_yaml = _read_yaml(os.path.join(h, "config.yaml"))
        mem = host_yaml.get("memory") if isinstance(host_yaml.get("memory"), dict) else {}
        ctx = host_yaml.get("context") if isinstance(host_yaml.get("context"), dict) else {}
        if mem.get("provider") != "chronicle" and ctx.get("engine") != "chronicle":
            continue
        try:
            theirs = expand_data_path(mem.get("db_path"), os.path.abspath(h), DB_REL)
        except Exception:
            continue
        if _same_real(theirs, legacy):
            return h
    return ""


def _append_marker(new: str, record: dict) -> None:
    """Add one record to `<dir of new>/chronicle-migration.json` (a JSON list)."""
    marker = os.path.join(os.path.dirname(new), MARKER_NAME)
    records: list = []
    try:
        with open(marker, "r", encoding="utf-8") as fh:
            old = json.load(fh)
        if isinstance(old, list):
            records = old
    except (OSError, ValueError):
        pass
    records.append(record)
    tmp = marker + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, marker)


def _tidy_sidecars(path: str) -> None:
    """Remove the old name's empty `-wal` and its `-shm` once it is a symlink.

    SQLite follows the symlink, so every later open uses the new name's
    sidecars and these are dead. A `-wal` that is not empty is left alone: it
    cannot be (the move held the store exclusively and checkpointed it first),
    and if it ever is, deleting it would discard committed transactions.
    """
    wal = path + "-wal"
    try:
        if os.path.lexists(wal):
            if os.path.getsize(wal) > 0:
                return
            os.unlink(wal)
        _remove(path + "-shm")
    except OSError as e:
        logger.debug("leaving sidecars of %s: %s", path, e)


# -- the store --------------------------------------------------------------

def settle_db_path(new_path: str, legacy_path: str, *, home: str) -> MigrationResult:
    """Decide which store to open, moving an older release's store when safe.

    Never raises. On any unexpected error the result is `kept_legacy`, with the
    old store's path when it holds data and the new path otherwise.
    """
    try:
        new = os.path.abspath(os.fspath(new_path))
        legacy = os.path.abspath(os.fspath(legacy_path))
    except Exception as e:
        return MigrationResult("kept_legacy", str(new_path), "bad path: %s" % e)
    try:
        return _settle_db(new, legacy, os.path.abspath(home))
    except Exception as e:
        path = legacy if has_data(legacy) else new
        logger.warning("chronicle: could not check or move the store at %s (%s); "
                       "opening %s", legacy, e, path)
        return MigrationResult("kept_legacy", path, "error: %s" % e)


def _settle_db(new: str, legacy: str, home: str) -> MigrationResult:
    # 1. One file under two spellings (a symlinked directory, a finished move).
    if _same_real(new, legacy):
        return MigrationResult("none", new)
    # 2. Nothing to move.
    if not has_data(legacy):
        return MigrationResult("none", new)
    # A move interrupted between the link and the symlink leaves two hard-link
    # names for one store. That is the unsafe state, not a conflict: finish it.
    resume = (not os.path.islink(legacy)) and _same_inode(new, legacy)
    if not resume:
        # 3. Both hold data: which one is right is the user's call.
        if has_data(new):
            _warn_once(("conflict", new, legacy),
                       "chronicle: two stores hold data: %s (where the config points) and %s "
                       "(where releases before 5.12 put it). Opening %s, as before. To use "
                       "the configured one, stop Hermes, keep the store you want at %s, "
                       "move the other one aside, and start Hermes again.",
                       new, legacy, legacy, new)
            return MigrationResult("conflict", legacy, "both stores hold data")
        # The old name is a symlink to somewhere else: moving it would leave
        # the file it points at as a second name for the store.
        if os.path.islink(legacy):
            _warn_once(("symlink", legacy),
                       "chronicle: the store at %s is a symlink to %s; not moving it. To use "
                       "%s, stop Hermes, move %s there, and start Hermes again.",
                       legacy, os.path.realpath(legacy), new, os.path.realpath(legacy))
            return MigrationResult("kept_legacy", legacy, "legacy is a symlink")
        # 4. Another profile's own store: not ours to take.
        owner = _claimed_by_other_profile(legacy, home)
        if owner:
            _warn_once(("claimed", legacy),
                       "chronicle: the store at %s is also the configured store of the profile "
                       "at %s; not moving it. This profile keeps using it. To give this "
                       "profile its own store, copy %s to %s while Hermes is stopped.",
                       legacy, owner, legacy, new)
            return MigrationResult("kept_legacy", legacy, "claimed by %s" % owner)
    return _move(new, legacy, resume)


def _deferred(legacy: str, why: str) -> MigrationResult:
    logger.info("chronicle: the store at %s is in use by another process (%s); it stays "
                "there for now and the move will be retried at a later start.", legacy, why)
    return MigrationResult("deferred", legacy, why)


def _lock_exclusive(legacy: str):
    """Rule 5: an exclusive hold on the old store, or (None, reason).

    `journal_mode=DELETE` needs every other connection gone, including idle
    WAL readers in other processes, so it is the test for "nobody else has it
    open". It also checkpoints the WAL into the main file, so the file alone
    then holds every committed transaction. The WAL mode is put back, and
    `locking_mode=EXCLUSIVE` + `BEGIN EXCLUSIVE` keep everyone out until close.
    """
    try:
        conn = sqlite3.connect(legacy, timeout=LOCK_TIMEOUT_S, isolation_level=None)
    except sqlite3.OperationalError as e:
        return None, str(e)
    try:
        prev = (conn.execute("PRAGMA journal_mode").fetchone()[0] or "").lower()
        mode = (conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] or "").lower()
    except sqlite3.OperationalError as e:
        _close(conn)
        return None, str(e)
    if mode != "delete":
        _close(conn)
        return None, "journal_mode stayed %s" % mode
    try:
        if prev == "wal":
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
        conn.execute("PRAGMA locking_mode=EXCLUSIVE").fetchone()
        conn.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as e:
        try:
            if prev == "wal":
                conn.execute("PRAGMA journal_mode=WAL").fetchone()
        except Exception:
            pass
        _close(conn)
        return None, str(e)
    return conn, ""


def _release(conn: sqlite3.Connection, legacy: str) -> None:
    """Step 9: give up the hold BEFORE the caller opens the new name."""
    try:
        if conn.in_transaction:
            conn.execute("COMMIT")
        conn.execute("PRAGMA locking_mode=NORMAL").fetchone()
    except Exception as e:
        logger.debug("releasing %s: %s", legacy, e)
    _close(conn)


def _set_aside_empty(new: str, stamp: str, undo: List[Callable[[], None]]) -> Optional[str]:
    """Step 6: move a data-less file at `new` out of the way, or say why not.

    An empty store at the new name is what a start with no data to migrate
    leaves behind. It is renamed, never deleted, with its sidecars: a stale
    `-wal` left next to the new name would be replayed into the moved store.
    """
    if not os.path.lexists(new):
        return None
    if os.path.isfile(new) and not os.path.islink(new):
        try:
            probe = sqlite3.connect(new, timeout=LOCK_TIMEOUT_S, isolation_level=None)
        except sqlite3.OperationalError as e:
            return "the empty store at %s could not be opened: %s" % (new, e)
        try:
            mode = (probe.execute("PRAGMA journal_mode=DELETE").fetchone()[0] or "").lower()
            if mode != "delete":
                return "the empty store at %s is in use" % new
        except sqlite3.OperationalError as e:
            return "the empty store at %s is in use: %s" % (new, e)
        except sqlite3.DatabaseError:
            pass  # not a SQLite file: nothing can have it open as a store
        finally:
            _close(probe)
    aside = new + ".empty-" + stamp
    moved = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        if os.path.lexists(new + suffix):
            os.rename(new + suffix, aside + suffix)
            moved.append(suffix)

    def put_back():
        for suffix in reversed(moved):
            if not os.path.lexists(new + suffix):
                os.rename(aside + suffix, new + suffix)
    undo.append(put_back)
    return None


def _copy_verified(conn: sqlite3.Connection, new: str) -> None:
    """Step 7, other filesystem: a checked copy at `new`, renamed into place."""
    partial = new + ".partial"
    for suffix in ("", "-wal", "-shm", "-journal"):
        _remove(partial + suffix)
    want = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    # The backup reads through this connection; inside its own write
    # transaction it would wait on itself forever. locking_mode=EXCLUSIVE keeps
    # the lock after COMMIT, so other processes stay locked out throughout.
    conn.execute("COMMIT")
    dst = sqlite3.connect(partial, isolation_level=None)
    try:
        _backup(conn, dst)
        check = dst.execute("PRAGMA quick_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError("copy failed quick_check: %s" % check)
        got = dst.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if got != want:
            raise RuntimeError("copy has %d events, the store has %d" % (got, want))
        # A copy in DELETE mode is one file; nothing is left in a -wal.
        dst.execute("PRAGMA journal_mode=DELETE").fetchone()
    finally:
        _close(dst)
    conn.execute("BEGIN EXCLUSIVE")
    for suffix in ("-wal", "-shm", "-journal"):
        _remove(partial + suffix)
    _fsync_file(partial)
    os.replace(partial, new)
    _fsync_dir(os.path.dirname(new))


def _move(new: str, legacy: str, resume: bool) -> MigrationResult:
    conn, why = _lock_exclusive(legacy)
    if conn is None:
        return _deferred(legacy, why)
    stamp = _utc_stamp()
    undo: List[Callable[[], None]] = []
    action = "moved"
    committed = False
    try:
        os.makedirs(os.path.dirname(new), exist_ok=True)
        if not resume:
            busy = _set_aside_empty(new, stamp, undo)
            if busy:
                for step in reversed(undo):
                    step()
                _release(conn, legacy)
                return _deferred(legacy, busy)
            if _device(legacy) == _device(os.path.dirname(new)):
                os.link(legacy, new)
                undo.append(lambda: _remove(new))
            else:
                action = "copied"
                undo.append(lambda: [_remove(new + ".partial"), _remove(new)])
                _copy_verified(conn, new)
                kept = legacy + ".migrated-" + stamp
                os.link(legacy, kept)
                undo.append(lambda: _remove(kept))
            _fsync_dir(os.path.dirname(new))
        # 8. The old name becomes a symlink to the new one, atomically. From
        # here on the data is only reachable as `new`: nothing may be undone.
        tmp = legacy + ".symlink-tmp"
        _remove(tmp)
        symlink_error = None
        try:
            os.symlink(new, tmp)
            linked = True
        except (OSError, NotImplementedError, AttributeError) as e:
            linked = False
            symlink_error = e
        if linked:
            try:
                os.replace(tmp, legacy)
            except Exception:
                _remove(tmp)
                raise
            committed = True
        else:
            # No symlinks here: drop the old name rather than keep a second
            # name for a WAL store. The data is safe at `new`.
            os.unlink(legacy)
            committed = True
            if action == "copied":
                logger.warning("chronicle: moved the store to %s, but the old name %s could not "
                               "be made a symlink (%s); the original is kept at %s.",
                               new, legacy, symlink_error, legacy + ".migrated-" + stamp)
        _fsync_dir(os.path.dirname(legacy))
    except Exception as e:
        if committed:
            logger.warning("chronicle: the store moved to %s, then: %s", new, e)
        else:
            for step in reversed(undo):
                try:
                    step()
                except Exception as ue:  # pragma: no cover - best effort
                    logger.debug("undo step failed: %s", ue)
            _release(conn, legacy)
            logger.warning("chronicle: could not move the store from %s to %s (%s); it stays "
                           "at %s and the move will be retried at a later start.",
                           legacy, new, e, legacy)
            return MigrationResult("kept_legacy", legacy, "move failed: %s" % e)
    _release(conn, legacy)
    if os.path.islink(legacy):
        _tidy_sidecars(legacy)
    record = {"from": legacy, "to": new, "at": stamp, "action": action, "version": _version()}
    try:
        _append_marker(new, record)
    except Exception as e:
        logger.warning("chronicle: the store moved to %s, but the record of it could not be "
                       "written: %s", new, e)
    logger.info("chronicle: %s the store from %s to %s", action, legacy, new)
    return MigrationResult(action, new, "resumed an interrupted move" if resume else "")


# -- the git mirror -----------------------------------------------------------

def settle_git_repo(new_repo: str, legacy_repo: str, store, *, enabled: bool,
                    remote: Optional[str], home: Optional[str] = None) -> MigrationResult:
    """Point this store at its own mirror, queuing all of its events for it once.

    Never raises. The mirror is always used at `new_repo`; the old shared
    mirror is never touched, because it may hold other profiles' events.
    `home` is the profile home; a mirror inside it is recorded relative to it
    (see `_mirror_marker`).
    """
    try:
        new = os.path.abspath(os.fspath(new_repo))
        legacy = os.path.abspath(os.fspath(legacy_repo)) if legacy_repo else ""
        if not enabled or (legacy and _same_real(new, legacy)):
            return MigrationResult("none", new)
        target = _mirror_marker(new, home)
        if store.get_meta(GIT_META_KEY) == target:
            return MigrationResult("none", new)
        try:
            from .gitmirror import init_git_repo
        except Exception:
            from gitmirror import init_git_repo
        init_git_repo(new)
        n = store.requeue_all_for_git(GIT_META_KEY, target)
        # A store with no events never wrote to the old mirror.
        if n and legacy and os.path.lexists(legacy):
            _warn_once(("git-legacy", legacy, new),
                       "chronicle: this profile's git mirror is now %s. The old mirror at %s "
                       "is left in place: it may hold other profiles' events.", new, legacy)
        if remote:
            _warn_once(("git-remote", new),
                       "chronicle: the git mirror moved to %s, so its history no longer matches "
                       "the remote %s; pushes are rejected until the remote is reset or "
                       "changed.", new, remote)
        if n:
            logger.info("chronicle: queued %d events for the git mirror at %s", n, new)
            return MigrationResult("copied", new, "queued %d events" % n)
        return MigrationResult("none", new)
    except Exception as e:
        logger.warning("chronicle: could not set up the git mirror at %s: %s", new_repo, e)
        return MigrationResult("kept_legacy", os.fspath(new_repo), "error: %s" % e)
