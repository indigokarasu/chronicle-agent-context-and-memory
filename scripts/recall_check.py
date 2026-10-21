#!/usr/bin/env python3
"""
Chronicle recall check: where is my store, what is in it, and does Chronicle
alone remember things?

Two questions people ask when they set Chronicle up under a named Hermes profile:

  1. Where does this profile keep its store, and is anything in it?
     (default mode, read-only: it never creates a file or a directory)
  2. With Hermes' own MEMORY.md / USER.md switched off, does Chronicle by itself
     bring a fact back in a later session?          (--canary)

Report mode reads the profile's `config.yaml` the way Chronicle does, resolves
the store through `engine/paths.py`, and opens it read-only.

`--canary` makes a temporary Hermes home, runs the real provider and tools end
to end (capture a turn that holds a random fact, drain extraction, start a NEW
session on a freshly opened store, ask for the fact through `chronicle_answer`
and `chronicle_search`), then deletes the home. It uses the offline hashing
embedder and opens no network connection, unless `--live-embedder` is given.
Nothing in your own Hermes home is read or written.

Output is plain `key: value` lines and ends with `PASS` or `FAIL: <reason>`.
Exit code: 0 on PASS, 1 on FAIL (2 for a usage error). `--json` prints the same
as one JSON object.

Usage:
    python3 scripts/recall_check.py                    # the active profile
    python3 scripts/recall_check.py --profile NAME     # a named profile
    python3 scripts/recall_check.py --home PATH        # an explicit Hermes home
    python3 scripts/recall_check.py --canary
    (installed:  python3 <plugin dir>/scripts/recall_check.py --profile NAME)
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
import logging
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from engine.config import Config
from engine.core import ChronicleCore
from engine.embeddings import VECTOR_TABLES
from engine.migrate_paths import MARKER_NAME
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
from engine.store import BELIEF_TABLES
from engine.yaml_load import safe_load_file

# Stored vectors are packed float32 (engine/embeddings.pack): this many bytes a dimension.
_BYTES_PER_DIM = 4

# The only virtual-table module Chronicle's own schema uses. Any other virtual
# table in a store was made by an extension an older release loaded.
_OWN_VIRTUAL_MODULES = ("fts5",)

_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# What the canary asks, and the surface that makes the heuristic extractor keep
# the fact: a first-person "my <thing> is <value>" sentence.
_CANARY_QUESTION = "What is my locker code?"
_CANARY_SEARCH = "locker code"

# Environment the canary overrides and puts back. HOME is included so that a `~`
# in any default path lands in the temporary directory, not the user's own.
_CANARY_ENV = ("HERMES_HOME", "HOME", "CHRONICLE_EMBED_MODEL")


# -- output ------------------------------------------------------------------

class Rows:
    """Ordered `key: value` rows plus free-text notes, printed as text or JSON."""

    def __init__(self) -> None:
        self.rows: List[Tuple[str, Any, Optional[str]]] = []
        self.notes: List[str] = []

    def add(self, key: str, value: Any, text: Optional[str] = None) -> None:
        self.rows.append((key, value, text))

    def note(self, text: str) -> None:
        self.notes.append(text)

    def get(self, key: str, default: Any = None) -> Any:
        for k, v, _ in self.rows:
            if k == key:
                return v
        return default

    def render(self, result: str, as_json: bool) -> str:
        if as_json:
            out: Dict[str, Any] = {}
            for k, v, _ in self.rows:
                out[k] = v
            out["notes"] = list(self.notes)
            out["ok"] = result == "PASS"
            out["result"] = result
            return json.dumps(out, indent=2, default=str)
        lines = ["%s: %s" % (k, t if t is not None else _text(v)) for k, v, t in self.rows]
        lines += ["note: " + n for n in self.notes]
        lines.append(result)
        return "\n".join(lines)


def _text(value: Any) -> str:
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(v) for v in value) if value else "none"
    return str(value)


@contextlib.contextmanager
def _quiet_engine() -> Iterator[None]:
    """Keep the engine's own log lines off the output, then put the level back.

    The report and the canary print their own result. Restoring the level
    matters when this runs inside another program (the tests), where warnings
    from the same logger are asserted on.
    """
    log = logging.getLogger("chronicle")
    level = log.level
    log.setLevel(logging.ERROR)
    try:
        yield
    finally:
        log.setLevel(level)


# -- version, config -----------------------------------------------------------

def _version() -> str:
    """The release, from plugin.yaml (the one place the version literal lives)."""
    try:
        with open(_ROOT / "plugin.yaml", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("version:"):
                    value = line.split(":", 1)[1].split("#", 1)[0].strip().strip("\"'").strip()
                    if value:
                        return value
    except OSError:
        pass
    return "unknown"


def _read_host_config(home: str) -> Tuple[Optional[dict], str]:
    """The profile's whole `config.yaml` and a one-word-or-so status.

    (None, "absent") when there is no file, (None, "not readable: <why>") when
    there is one and it cannot be read. No YAML parser is in the standard
    library; `yaml_load` uses PyYAML or ruamel.yaml (what a host install has),
    and a Python with neither must degrade, not crash.
    """
    path = os.path.join(home, "config.yaml")
    if not os.path.isfile(path):
        return None, "absent"
    try:
        raw = safe_load_file(path) or {}
    except Exception as e:
        return None, "not readable: %s" % e
    if not isinstance(raw, dict):
        return None, "not readable: the top level is not a mapping"
    return raw, "read"


def _section(raw: Optional[dict], name: str) -> dict:
    value = (raw or {}).get(name)
    return value if isinstance(value, dict) else {}


# -- store, read-only ----------------------------------------------------------

def _open_ro(path: str) -> Tuple[Optional[sqlite3.Connection], str]:
    """A read-only connection to the store at `path`, or (None, why).

    Never creates anything: a missing or empty file is refused before SQLite
    sees it, and the URI says `mode=ro`.

    A store whose last connection closed cleanly has no `-wal` or `-shm`, and a
    read-only open cannot make the `-shm` it needs, so SQLite refuses it. With
    no `-wal` on disk the main file holds every committed transaction, and an
    `immutable` read of it is exact, so that is tried second.
    """
    p = os.path.abspath(path)
    try:
        if not os.path.isfile(p):
            return None, "no file"
        if os.path.getsize(p) <= 0:
            return None, "the file is empty"
    except OSError as e:
        return None, str(e)
    base = "file:" + quote(p, safe="/") + "?mode=ro"
    attempts = [base]
    if not os.path.lexists(p + "-wal"):
        attempts.append(base + "&immutable=1")
    first = ""
    for uri in attempts:
        conn = None
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=2)
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            return conn, ""
        except sqlite3.Error as e:
            first = first or str(e)
            if conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    conn.close()
    return None, first


def _holds_events(path: str) -> bool:
    """`has_data`, plus the cleanly closed WAL store it cannot read (see `_open_ro`)."""
    if has_data(path):
        return True
    conn, _ = _open_ro(path)
    if conn is None:
        return False
    try:
        return conn.execute("SELECT 1 FROM events LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _scalar(conn: sqlite3.Connection, sql: str) -> Any:
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _summarize(conn: sqlite3.Connection) -> Dict[str, Any]:
    """What is in the store. Every query is a read; a missing table counts as none."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out: Dict[str, Any] = {"has_events_table": "events" in tables}
    out["events"] = _scalar(conn, "SELECT COUNT(*) FROM events") if "events" in tables else 0
    out["last_event"] = (_scalar(conn, "SELECT MAX(recorded_at) FROM events")
                         if "events" in tables else None)
    beliefs: Dict[str, int] = {}
    for t in BELIEF_TABLES:
        if t not in tables:
            continue
        n = _scalar(conn, "SELECT COUNT(*) FROM %s WHERE status='active'" % t)
        if n is None:                       # a table with no status column: count it whole
            n = _scalar(conn, "SELECT COUNT(*) FROM %s" % t)
        beliefs[t] = int(n or 0)
    out["beliefs"] = beliefs
    widths: Dict[int, int] = {}
    for t in VECTOR_TABLES:
        if t not in tables:
            continue
        try:
            rows = conn.execute("SELECT length(embedding) / %d, COUNT(*) FROM %s "
                                "WHERE embedding IS NOT NULL GROUP BY 1" % (_BYTES_PER_DIM, t))
            for width, n in rows:
                widths[int(width)] = widths.get(int(width), 0) + int(n)
        except sqlite3.Error:
            continue
    out["vectors"] = dict(sorted(widths.items()))
    foreign: List[str] = []
    for name, sql in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' "
                                  "AND sql LIKE 'CREATE VIRTUAL TABLE%'"):
        m = re.search(r"USING\s+(\w+)", sql or "", re.I)
        module = m.group(1).lower() if m else "?"
        if module not in _OWN_VIRTUAL_MODULES:
            foreign.append("%s (module %s)" % (name, module))
    out["extension_tables"] = foreign
    return out


def _link_state(new: str, legacy: str) -> str:
    """How the 5.11.1 location relates to the configured one."""
    if legacy == new:
        return "same as db_path, nothing to move"
    if not os.path.lexists(legacy):
        return "absent"
    if os.path.realpath(legacy) == os.path.realpath(new):
        return ("symlink to db_path, the store was moved" if os.path.islink(legacy)
                else "the same file as db_path")
    return "holds events, not moved yet" if _holds_events(legacy) else "present, holds no events"


def _migration_record(new: str) -> Tuple[str, Optional[list]]:
    """(summary, records) from `chronicle-migration.json` next to the store."""
    marker = os.path.join(os.path.dirname(new), MARKER_NAME)
    if not os.path.isfile(marker):
        return "none", None
    try:
        with open(marker, "r", encoding="utf-8") as fh:
            records = json.load(fh)
    except (OSError, ValueError) as e:
        return "unreadable (%s)" % e, None
    if not isinstance(records, list) or not records:
        return "none", []
    last = records[-1] if isinstance(records[-1], dict) else {}
    text = "%s %s -> %s at %s (release %s)" % (
        last.get("action", "?"), last.get("from", "?"), last.get("to", "?"),
        last.get("at", "?"), last.get("version", "?"))
    if len(records) > 1:
        text += "; %d records in all" % len(records)
    return text, records


# -- report mode ---------------------------------------------------------------

def _target_home(profile: Optional[str], home: Optional[str]) -> Tuple[str, str]:
    """(home, label): the Hermes home to report on and what to call it."""
    if home:
        return resolve_home(home), ""
    current = resolve_home(None)
    if not profile:
        return current, ""
    root = profile_root(current)
    if profile == "default":
        return root, "default"
    return os.path.join(root, "profiles", profile), profile


def report(profile: Optional[str] = None, home: Optional[str] = None,
           db: Optional[str] = None) -> Tuple[Rows, str]:
    """Where the store is and what is in it. Read-only. Returns (rows, result)."""
    rows = Rows()
    home_dir, label = _target_home(profile, home)
    rows.add("mode", "report")
    rows.add("chronicle", _version())
    rows.add("home", home_dir)
    if not label and os.path.basename(os.path.dirname(home_dir)) == "profiles":
        label = os.path.basename(home_dir)
    rows.add("profile", label or None, label or "(none)")
    if not os.path.isdir(home_dir):
        rows.add("home_exists", False)
        return rows, "FAIL: the Hermes home %s does not exist" % home_dir

    # -- what Hermes is configured to use ---------------------------------------
    raw, status = _read_host_config(home_dir)
    config_path = os.path.join(home_dir, "config.yaml")
    rows.add("config", config_path, "%s [%s]" % (config_path, status))
    memory, context = _section(raw, "memory"), _section(raw, "context")
    provider = memory.get("provider")
    engine = context.get("engine")
    rows.add("memory.provider", provider)
    rows.add("context.engine", engine)
    rows.add("memory.memory_enabled", memory.get("memory_enabled"))
    rows.add("memory.user_profile_enabled", memory.get("user_profile_enabled"))
    if raw is None and status != "absent":
        rows.note("config.yaml could not be read, so the paths below are the defaults and may "
                  "differ from what Hermes is using")
    if raw is not None and provider != "chronicle" and engine != "chronicle":
        rows.note("this profile uses neither memory.provider nor context.engine 'chronicle'")
    if memory.get("memory_enabled") is not False or memory.get("user_profile_enabled") is not False:
        rows.note("Hermes keeps its own MEMORY.md and USER.md unless memory.memory_enabled and "
                  "memory.user_profile_enabled are both false; run --canary to see Chronicle "
                  "recall a fact without them")

    # -- paths, resolved the way ChronicleCore resolves them --------------------
    chronicle_cfg = {}
    if raw is not None:
        chronicle_cfg = ChronicleCore._load_memory_config(home_dir)
    try:
        cfg = Config(chronicle_cfg)
    except Exception as e:
        rows.note("the memory: section was rejected (%s); defaults are used below" % e)
        cfg = Config({})
    if db:
        db_cfg: Optional[str] = db
        rows.add("db_configured", db, "%s [--db]" % db)
    else:
        db_cfg = cfg.get("db_path")
        rows.add("db_configured", chronicle_cfg.get("db_path"),
                 _text(chronicle_cfg["db_path"]) if chronicle_cfg.get("db_path")
                 else "(not set, so the default)")
    new = expand_data_path(db_cfg, home_dir, DB_REL)
    legacy = legacy_db_path(db_cfg, home_dir)
    rows.add("db_path", new)
    rows.add("db_legacy_path", legacy, "%s [%s]" % (legacy, _link_state(new, legacy)))
    summary, _records = _migration_record(new)
    rows.add("migration_record", summary)
    backups = sorted(glob.glob(glob.escape(legacy) + ".migrated-*"))
    if backups:
        rows.add("db_backups", backups)

    git_cfg = cfg.get("git_repo")
    git_new = expand_data_path(git_cfg, home_dir, GIT_REL)
    git_old = legacy_git_path(git_cfg)
    rows.add("git_enabled", bool(cfg.get("git.enabled", True)))
    rows.add("git_mirror", git_new, "%s [%s]" % (git_new, "present" if os.path.isdir(git_new)
                                                 else "absent"))
    if os.path.normpath(git_old) != os.path.normpath(git_new):
        rows.add("git_mirror_legacy", git_old, "%s [%s]" % (
            git_old, "present, shared by profiles of older releases" if os.path.isdir(git_old)
            else "absent"))

    # -- the store a read-only consumer opens, and what is in it ----------------
    open_path = readable_db_path(db_cfg, home_dir)
    new_has = _holds_events(new)
    old_has = (legacy != new and os.path.realpath(legacy) != os.path.realpath(new)
               and _holds_events(legacy))
    if open_path == new and not new_has and old_has:
        # readable_db_path reads a cleanly closed WAL store as empty (see _open_ro).
        open_path = legacy
    rows.add("db_open", open_path)
    conn, why = _open_ro(open_path)
    if conn is None:
        if not os.path.isfile(open_path):
            rows.add("store", "none")
            return rows, "FAIL: no Chronicle store at %s" % new
        rows.add("store", "empty file" if os.path.getsize(open_path) <= 0 else "unreadable")
        return rows, "FAIL: cannot read the store at %s: %s" % (open_path, why)
    try:
        info = _summarize(conn)
    except sqlite3.Error as e:
        return rows, "FAIL: cannot read the store at %s: %s" % (open_path, e)
    finally:
        conn.close()

    rows.add("events", info["events"])
    beliefs = info["beliefs"]
    kinds = ", ".join("%s %d" % kv for kv in beliefs.items() if kv[1])
    rows.add("beliefs_active", sum(beliefs.values()),
             "%d (%s)" % (sum(beliefs.values()), kinds) if kinds else "0")
    vectors = info["vectors"]
    rows.add("vectors", vectors, ", ".join("%d dims x %d" % kv for kv in vectors.items())
             if vectors else "none")
    rows.add("last_event", info["last_event"])
    if info["extension_tables"]:
        rows.add("extension_tables", info["extension_tables"])
        rows.note("extension tables were left in the file by an older release; Chronicle never "
                  "queries them")

    if new_has and old_has:
        rows.note("two stores hold events: %s and %s. Chronicle opens the old one until one is "
                  "moved aside (the Hermes log has the details); the counts above are for %s"
                  % (new, legacy, open_path))
    elif old_has and open_path == legacy:
        rows.note("the data is at the old location. Chronicle moves it to db_path at its next "
                  "start when nothing else has it open")
    if not info["has_events_table"] or not info["events"]:
        return rows, "FAIL: the store at %s holds no events" % open_path
    return rows, "PASS"


# -- canary mode ---------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(str(text).split())


def _canary_fact(rng: random.Random) -> str:
    return " ".join(str(rng.randrange(10)) for _ in range(6))


def canary(live_embedder: bool = False, rng: Optional[random.Random] = None) -> Tuple[Rows, str]:
    """Capture a fact, start a new session, and ask for it back. Returns (rows, result).

    The provider and tool entry points are the ones Hermes calls. The store is
    CLOSED between the two sessions and opened again from disk, so a fact that
    only lived in memory cannot pass.
    """
    # Local import: the provider is a plugin adapter at the plugin root.
    from provider import ChronicleMemoryProvider

    rng = rng or random.SystemRandom()
    code = _canary_fact(rng)
    sentence = "My locker code is %s." % code
    rows = Rows()
    rows.add("mode", "canary")
    rows.add("chronicle", _version())
    failures: List[str] = []
    saved = {k: os.environ.get(k) for k in _CANARY_ENV}
    tmp = tempfile.mkdtemp(prefix="chronicle-recall-check-")
    providers: List[Any] = []
    try:
        home = os.path.join(tmp, "hermes")
        os.makedirs(home)
        os.makedirs(os.path.join(tmp, "user"))
        os.environ["HERMES_HOME"] = home
        os.environ["HOME"] = os.path.join(tmp, "user")
        if not live_embedder:
            os.environ["CHRONICLE_EMBED_MODEL"] = "hashing"
        rows.add("home", home, "%s (temporary, removed afterwards)" % home)
        # Everything that could reach outside the temporary home is off: the
        # journal source defaults to a directory under the user's own home, and
        # the git mirror needs the git program, which recall does not. The drain
        # stays on this thread: a background one could still be extracting when
        # the store is closed between the two sessions, and the fact would be
        # lost for a reason that has nothing to do with recall.
        config: Dict[str, Any] = {"sources": {"ocas_journals": {"enabled": False}},
                                  "git": {"enabled": False},
                                  "curation": {"drain": {"background": False}}}
        if not live_embedder:
            config["embeddings"] = {"model": "hashing"}

        # Session 1: the turn is captured and its extraction drained.
        first = ChronicleMemoryProvider()
        providers.append(first)
        first.initialize("recall-check-1", hermes_home=home, principal_id="default", config=config)
        rows.add("embedder", type(first.core.embedder).__name__)
        rows.add("fact", sentence)
        first.sync_turn(sentence, "Noted.", session_id="recall-check-1")
        drained = first.core.process_pending()
        rows.add("drained_jobs", drained)
        first.on_session_end([])
        first.shutdown()
        first.core.close()

        # Session 2: a new session on a store opened again from disk.
        second = ChronicleMemoryProvider()
        providers.append(second)
        second.initialize("recall-check-2", hermes_home=home, principal_id="default", config=config)
        rows.add("new_session", "recall-check-2")

        answer = json.loads(second.handle_tool_call("chronicle_answer", {"query": _CANARY_QUESTION}))
        answer_text = str(answer.get("answer") or "")
        rows.add("answer", answer_text or answer.get("error") or "(empty)")
        if _norm(code) not in _norm(answer_text):
            failures.append("chronicle_answer did not return the fact%s" % (
                " (it abstained)" if answer.get("abstain") else
                " (%s)" % answer["error"] if answer.get("error") else ""))

        found = json.loads(second.handle_tool_call("chronicle_search", {"query": _CANARY_SEARCH}))
        beliefs = [str(r.get("value") or "") for r in found.get("results") or []]
        said = [str(s.get("excerpt") or "") for s in found.get("said") or []]
        rows.add("search", {"beliefs": len(beliefs), "said": len(said)},
                 "%d from beliefs, %d from past conversations" % (len(beliefs), len(said)))
        if not any(_norm(code) in _norm(t) for t in beliefs + said):
            failures.append("chronicle_search did not return the fact%s" % (
                " (%s)" % found["error"] if found.get("error") else ""))
        rows.add("builtin_memory", False,
                 "not used (the temporary home has no MEMORY.md or USER.md)")
    except Exception as e:
        failures.append("the canary raised %s: %s" % (type(e).__name__, e))
    finally:
        for p in providers:
            core = getattr(p, "core", None)
            if core is not None:
                with contextlib.suppress(Exception):
                    core.close()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    rows.add("cleanup", not os.path.exists(tmp),
             "removed" if not os.path.exists(tmp) else "could not remove %s" % tmp)
    return rows, ("FAIL: " + "; ".join(failures)) if failures else "PASS"


# -- command line ----------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="recall_check.py",
        description="Show where Chronicle keeps a profile's store and what is in it, or (--canary) "
                    "check that Chronicle by itself recalls a fact in a later session.")
    p.add_argument("--profile", metavar="NAME",
                   help="report on this Hermes profile ('default' is the root)")
    p.add_argument("--home", metavar="PATH", help="report on this Hermes home")
    p.add_argument("--db", metavar="PATH",
                   help="use this as memory.db_path instead of the configured one")
    p.add_argument("--canary", action="store_true",
                   help="capture a fact, start a new session and recall it, in a temporary home")
    p.add_argument("--live-embedder", action="store_true",
                   help="with --canary: use the configured embedding server, not the offline one")
    p.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.profile and args.home:
        parser.error("--profile and --home cannot be used together")
    if args.profile and not _PROFILE_NAME.match(args.profile):
        parser.error("--profile must be a profile name, not a path")
    if args.canary and (args.profile or args.home or args.db):
        parser.error("--canary works in a temporary home; --profile, --home and --db do not apply")
    if args.live_embedder and not args.canary:
        parser.error("--live-embedder only applies with --canary")
    with _quiet_engine():
        if args.canary:
            rows, result = canary(live_embedder=args.live_embedder)
        else:
            rows, result = report(args.profile, args.home, args.db)
    print(rows.render(result, args.json))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
