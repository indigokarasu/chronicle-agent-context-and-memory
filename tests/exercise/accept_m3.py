#!/usr/bin/env python3
"""Acceptance test for m3 (context-engine init resilience).

Live defect, VPS 2026-08-02: ChronicleContextEngine.on_session_start hit
"database is locked" while another process was mid-migration, caught it, and
latched the heuristic fallback FOR PROCESS LIFE. One busy moment permanently
removed the memory-aware half of the plugin.

The scenarios below pin the three parts of the fix, and the two ways the fix
itself can go wrong:

  1. locked-db init degrades cleanly AND is bounded by the START-UP busy
     timeout (not the 30s steady-state one)
  2. the fallback does NOT latch: a later compress() re-inits the real engine
     once the lock is gone
  3. chronicle_context_status names the active mode and the reason
  4. retries are budgeted -- a permanently locked store must not turn every
     compression into a core rebuild
  5. a HALF-INITIALIZED core is never attached. ChronicleCore.get() returns a
     warm singleton without touching SQLite, so the lock usually fires inside
     initialize(); attaching that core would make status say "real engine"
     while every compress() raised OperationalError into the host.

Every scenario pre-warms the singleton first, precisely so the lock is met
inside initialize() rather than in the store constructor.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."
)
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore          # noqa: E402
from engine.store import BUSY_TIMEOUT_MS, INIT_BUSY_TIMEOUT_MS  # noqa: E402
from context import ChronicleContextEngine, _RETRY_MAX_PER_HOUR  # noqa: E402

CFG = {"embeddings": {"model": "hashing"}}     # offline, deterministic

# Obviously-fake conversation fixture. Every turn mentions the focus topic, so
# the memory-aware path scores them all above the keep threshold and returns
# them; the heuristic path keeps a fixed system + first-3 + last-6 window. The
# two modes therefore have different, unmistakable output sizes.
MESSAGES = (
    [{"role": "system", "content": "You are helping Pat Testley at Acme Fake Co."}]
    + [{"role": "user" if i % 2 == 0 else "assistant",
        "content": "Acme Fake Co turn %d: routine scheduling chatter." % i}
       for i in range(24)]
)
FOCUS = "scheduling"
HEURISTIC_LEN = 1 + 3 + 6      # what _heuristic() emits for MESSAGES

_STATE = {}


def _mode_of(out):
    """Which branch compress() actually took, read off its output."""
    return "heuristic_fallback" if len(out) == HEURISTIC_LEN else "memory_aware"


def _home():
    home = tempfile.mkdtemp(prefix="m3_")
    _STATE.setdefault("homes", []).append(home)
    return home


def _db_path(home):
    return str(Path(home) / "commons/db/chronicle/chronicle.db")


def _warm(home):
    """Build the singleton cleanly, BEFORE any lock exists."""
    core = ChronicleCore.get(home, CFG)
    assert home in ChronicleCore._instances, "singleton not registered"
    return core


class _WriteLock:
    """Hold the SQLite write lock from a separate connection, like a concurrent
    migration in another process would."""

    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, timeout=5)
        self.conn.execute("PRAGMA journal_mode=WAL")

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('m3_lock','held')")
        return self

    def release(self):
        if self.conn is not None:
            self.conn.rollback()
            self.conn.close()
            self.conn = None

    def __exit__(self, *exc):
        self.release()
        return False


def test_locked_init_degrades_and_is_bounded():
    """1. Init under a held write lock falls back instead of raising, gives up
    after the START-UP timeout rather than the steady-state one, and keeps
    serving fallback per-call while the lock is still there."""
    home = _home()
    warm = _warm(home)
    eng = ChronicleContextEngine()

    lock = _WriteLock(_db_path(home)).__enter__()
    try:
        t0 = time.time()
        eng.on_session_start("m3-s1", hermes_home=home, principal_id="pat", config=CFG)
        elapsed = time.time() - t0

        assert eng.core is None, "fallback must not attach a core (got %r)" % (eng.core,)
        assert ChronicleCore._instances.get(home) is warm, \
            "the warm singleton should still exist -- the engine just must not use it"
        lo, hi = INIT_BUSY_TIMEOUT_MS / 1000.0, BUSY_TIMEOUT_MS / 1000.0
        assert elapsed >= lo * 0.5, \
            "init returned in %.2fs -- did it really hit the lock?" % elapsed
        assert elapsed < hi, \
            "init waited %.2fs; the start-up path must be bounded by %.0fs, not %.0fs" % (
                elapsed, lo, hi)

        # Still locked: the retry is attempted and fails again, and the call is
        # served from the fallback rather than raising OperationalError.
        out = eng.compress(list(MESSAGES), focus_topic=FOCUS)
        assert _mode_of(out) == "heuristic_fallback", \
            "expected the heuristic window, got %d messages" % len(out)
        assert eng._init_attempts == 2, \
            "the next compress() should have retried; attempts=%d" % eng._init_attempts
        assert eng.core is None and eng.context_status()["mode"] == "heuristic_fallback"
    finally:
        lock.release()

    _STATE["s1"] = (home, eng, warm)
    print("  PASS: locked init -> fallback in %.2fs (bound %.0fs, not %.0fs); "
          "still fallback on the next call" % (elapsed, lo, hi))


def test_fallback_does_not_latch():
    """2. THE defect. Once the lock is gone, a later compress() re-inits the
    real engine instead of serving the heuristic for the rest of the process."""
    home, eng, warm = _STATE["s1"]
    assert eng.core is None and eng._consecutive_failures == 2

    due = eng._retry_due_in()
    assert due is not None, "retries must still be on the table"
    time.sleep(due + 0.05)
    out = eng.compress(list(MESSAGES), focus_topic=FOCUS)

    assert eng.core is not None, "engine stayed latched in fallback after the lock cleared"
    assert eng.core is warm, "re-init should adopt the singleton, not a second core"
    assert eng._consecutive_failures == 0 and eng._recoveries == 1
    assert _mode_of(out) == "memory_aware", \
        "compress() still took the heuristic branch (%d messages)" % len(out)
    print("  PASS: re-init on call %d; memory-aware compression restored (%d messages)"
          % (eng._init_attempts, len(out)))


def test_status_surface_reports_mode_and_reason():
    """3. chronicle_context_status states which mode is active and why, and
    never disagrees with the branch compress() actually takes."""
    eng = _STATE["s1"][1]
    st = eng.context_status()
    assert st["mode"] == "memory_aware", st
    assert "re-initialized" in st["reason"], st
    assert st["recoveries"] == 1 and st["last_error"], \
        "the recovered engine should still say what went wrong: %r" % (st,)
    assert eng.get_status()["mode"] == "memory_aware"

    tool = json.loads(eng.handle_tool_call("chronicle_context_status", {}))
    assert tool["mode"] == st["mode"], (tool, st)
    assert any(t["name"] == "chronicle_context_status" for t in eng.get_tool_schemas()), \
        "status tool missing from the schema list"

    down = ChronicleContextEngine()
    down._init_started = True
    down._last_error = "OperationalError: database is locked"
    down._consecutive_failures = 1
    down._attempt_times = [time.time()]
    dst = down.context_status()
    assert dst["mode"] == "heuristic_fallback" and "locked" in dst["reason"], dst

    # The invariant the previous attempt broke: mode is derived from the core,
    # so "real engine" can never be reported while compress() would fall back.
    for e in (eng, down):
        live = e.context_status()["mode"] == "memory_aware"
        assert live == (e.core is not None), "status/mode disagree with self.core: %r" % (e,)
    print("  PASS: status names mode+reason; mode <=> (self.core is not None)")


def test_retry_budget_caps_attempts_per_hour():
    """4. A store that is locked forever must not be retried forever."""
    eng = ChronicleContextEngine()
    eng._init_started = True
    eng._init_args = {"hermes_home": _home(), "config": CFG}
    eng._consecutive_failures = 3
    now = time.time()
    eng._attempt_times = [now - i for i in range(_RETRY_MAX_PER_HOUR)]
    eng._init_attempts = _RETRY_MAX_PER_HOUR

    assert eng._retry_due_in() is None, "budget of %d/hour not enforced" % _RETRY_MAX_PER_HOUR
    out = eng.compress(list(MESSAGES), focus_topic=FOCUS)
    assert eng._init_attempts == _RETRY_MAX_PER_HOUR, "attempted past the hourly budget"
    assert _mode_of(out) == "heuristic_fallback", "still has to serve a fallback"
    st = eng.context_status()
    assert st["retry_budget_spent"] is True and st["mode"] == "heuristic_fallback", st

    # Backoff grows with consecutive failures, so the budget is not the only brake.
    eng._attempt_times = [now]
    eng._consecutive_failures = 1
    first = eng._retry_due_in()
    eng._consecutive_failures = 4
    later = eng._retry_due_in()
    assert later > first > 0, "backoff should grow: %r -> %r" % (first, later)
    print("  PASS: %d attempts/hour cap holds; backoff %.1fs -> %.1fs"
          % (_RETRY_MAX_PER_HOUR, first, later))


def test_half_initialized_core_is_never_attached():
    """5. The regression guard. ChronicleCore.get() returns a WARM singleton
    without touching SQLite; if initialize() then dies on the lock, the engine
    must not keep that core. HEAD degrades cleanly and so must we."""
    home = _home()
    warm = _warm(home)
    eng = ChronicleContextEngine()

    with _WriteLock(_db_path(home)):
        eng.on_session_start("m3-s5", hermes_home=home, principal_id="pat", config=CFG)
        assert eng.core is None, "half-initialized core attached: %r" % (eng.core,)
        assert eng.context_status()["mode"] == "heuristic_fallback"
        # The host calls these on a degraded engine too; none may raise, and
        # none may reach the store behind the engine's back.
        assert _mode_of(eng.compress(list(MESSAGES), focus_topic=FOCUS)) == "heuristic_fallback"
        eng.on_session_end("m3-s5", list(MESSAGES))
        eng.handle_tool_call("chronicle_pin_context", {"content": "Pat Testley prefers mornings"})
        eng.handle_tool_call("chronicle_context_status", {})
        eng.get_status()

    time.sleep((eng._retry_due_in() or 0.0) + 0.05)
    out = eng.compress(list(MESSAGES), focus_topic=FOCUS)
    assert eng.core is warm, "engine did not recover once the lock cleared"
    assert _mode_of(out) == "memory_aware"
    print("  PASS: no half-initialized core; degraded engine survives the full host API")


def _cleanup():
    for home in _STATE.get("homes", []):
        ChronicleCore._instances.pop(home, None)
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    print("Running m3 acceptance tests (context-engine init resilience)...")
    try:
        print("\n1. Locked-db init degrades cleanly and is bounded:")
        test_locked_init_degrades_and_is_bounded()

        print("\n2. Fallback does not latch:")
        test_fallback_does_not_latch()

        print("\n3. Status surface:")
        test_status_surface_reports_mode_and_reason()

        print("\n4. Retry budget:")
        test_retry_budget_caps_attempts_per_hour()

        print("\n5. No half-initialized core:")
        test_half_initialized_core_is_never_attached()
    finally:
        _cleanup()

    print("\nAll acceptance tests passed.")
