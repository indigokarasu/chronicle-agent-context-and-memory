"""Chronicle test suite — hermetic harness (audit A11).

The suite used to inherit whatever the developer's shell happened to hold:
`CHRONICLE_EMBED_MODEL=hashing` (the documented CI setting) failed
`test_config_get_nested_path`, and *without* it every `ChronicleCore(...)` that
did not pass an explicit embeddings config ran `get_embedder("auto")`, which
opens TCP connections to localhost:1234 / :11434 / :8080 — real network I/O in
unit tests, and a different code path whenever a server happened to be up.

This file removes the ambient inputs. It pins the environment, sandboxes the
temp directory, denies socket connections, and can run the collected tests in
reverse order so order coupling shows up as a failure instead of luck.

Four supported ways to run the suite; all four must be green.

    # 1. default
    /usr/bin/python3 -m pytest tests/ -q --ignore=tests/exercise/test_manual.py

    # 2. with the documented CI env var set (must behave identically to 1)
    CHRONICLE_EMBED_MODEL=hashing /usr/bin/python3 -m pytest tests/ -q \
        --ignore=tests/exercise/test_manual.py

    # 3. with sockets disabled (strict: creating an AF_INET/AF_INET6 socket at
    #    all raises, not merely connecting)
    CHRONICLE_TEST_STRICT_SOCKETS=1 /usr/bin/python3 -m pytest tests/ -q \
        --ignore=tests/exercise/test_manual.py

    # 4. in reversed collection order
    CHRONICLE_TEST_ORDER=reverse /usr/bin/python3 -m pytest tests/ -q \
        --ignore=tests/exercise/test_manual.py

Knobs (all opt-in; the default is the hermetic configuration):

    CHRONICLE_TEST_ORDER=reverse|shuffle   reorder collected tests
    CHRONICLE_TEST_SEED=<int>              seed for CHRONICLE_TEST_ORDER=shuffle
    CHRONICLE_TEST_STRICT_SOCKETS=1        also deny INET socket *creation*
    CHRONICLE_TEST_ALLOW_NETWORK=1         lift the network guard entirely
    CHRONICLE_TEST_LIVE_EMBEDDER=1         run @pytest.mark.live_embedder tests
    CHRONICLE_TEST_KEEP_TMP=1              keep the session temp sandbox
    CHRONICLE_TEST_HASH_SEED=<int>|off     the PARENT interpreter's hash seed
                                           (default 0; `off` gives the gate back
                                           to the OS and is not reproducible)
    CHRONICLE_BASE_TREE=<path>             pre-H1 tree for test_host_model's
                                           byte-identical dump (skips if absent)

Markers:

    @pytest.mark.live_embedder  needs a real embedding server; skipped unless
                                CHRONICLE_TEST_LIVE_EMBEDDER=1
    @pytest.mark.allow_network  this test is expected to touch a socket
                                (nothing carries it today)

What is guaranteed, and by what:

  * hash seed — `_bind_parent_hash_seed()` RE-EXECS this interpreter under
    PYTHONHASHSEED=0 when it did not start with one. A process cannot change
    its own hash seed after startup, so pinning it for children (which this
    file always did) left the PARENT — the process that collects, orders and
    runs every test — on whatever seed the OS picked. That made the four-mode
    gate itself an experiment with an unrecorded input. See section 0 below.
  * env  — `_pin_environment()` runs at conftest import, which pytest performs
    before it imports any test module, and therefore before `engine.serialize`
    reads `CHRONICLE_REQUIRE_BLAKE3` at *import* time. Values are pinned, never
    read from the developer's shell.
  * network — `socket.socket.connect`, `.connect_ex`, `socket.create_connection`
    and non-local `socket.getaddrinfo` raise `NetworkAccessDisabled` *and*
    record the attempt. Recording matters because the engine's probe path
    swallows connection errors (`except Exception: continue`), so a raise alone
    would be invisible; the per-test fixture fails on any recorded attempt.
  * temp — `TMPDIR` and `tempfile.tempdir` point at one session sandbox that is
    removed at session end, so a run leaves the system temp directory exactly as
    it found it whatever an individual test forgets to clean up. The number of
    paths each test module left behind is reported in the terminal summary.
  * order — `ChronicleCore._instances` / `._active` and the process-wide ACL
    topology are reset after every test, so nothing carries into the next one.
"""

from __future__ import annotations

import atexit
import os
import random
import shutil
import site
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 0. The PARENT interpreter's hash seed
#
# `PINNED_ENV["PYTHONHASHSEED"]` pins the seed of every CHILD the suite spawns.
# It cannot pin this one — CPython fixes a process's hash seed at interpreter
# start, before any Python code runs — so the parent ran under the OS's random
# seed and the four documented modes were not reproducible: every recorded
# "1700 passed" carried an unstated dependency on whichever seed the run drew.
#
# The only way to actually BIND it (rather than advise a developer to export
# it) is to hand the interpreter a correct environment and start again, so that
# is what `_bind_parent_hash_seed` does: `os.execve` replaces the process in
# place — same pid, same argv, same exit status — and nothing downstream can
# tell the difference except `sys.flags.hash_randomization`.
#
# WHERE it happens is load-bearing. The exec inherits fds 1 and 2, and pytest's
# DEFAULT capture (`--capture=fd`) has already pointed those at a temp file it
# alone knows how to drain. Exec from conftest import and the replacement
# process writes its entire run — dots, failures, summary — into a file that
# nobody ever reads: the suite reports NOTHING and exits 0. (Measured: that is
# exactly what the first cut of this did.) So the exec runs from
# `pytest_configure`, after `suspend_global_capture()` has restored the real
# fds, and before any test module is imported.
#
# `sys.flags.hash_randomization == 0` is the authoritative test for "started
# under PYTHONHASHSEED=0": it reads the flag the interpreter actually booted
# with, not an environment variable that anything (including `_pin_environment`
# fifty lines below) may have overwritten since. `_AMBIENT_SEED` snapshots the
# shell's value for the same reason, before this file touches it.
# ---------------------------------------------------------------------------

#: The parent's pinned seed. `off` returns the gate to the OS's random seed.
HASH_SEED = (os.environ.get("CHRONICLE_TEST_HASH_SEED") or "0").strip()

#: The environment as the SHELL handed it over, snapshotted before anything in
#: this file touches it. The re-exec starts the replacement process from THIS,
#: not from the pinned environment: `_pin_environment` has by then aimed
#: TMPDIR/HOME at a session sandbox that `_bind_parent_hash_seed` is about to
#: delete, and a child that inherits those starts by nesting a second sandbox
#: inside a directory that no longer exists. Same process, same inputs, one
#: variable changed — which is the only thing the re-exec is allowed to do.
_AMBIENT_ENV = dict(os.environ)

#: PYTHONHASHSEED as the SHELL had it, read before `_pin_environment` runs.
_AMBIENT_SEED = os.environ.get("PYTHONHASHSEED")

#: Set on the child of a re-exec, so a failed exec cannot loop. Read HERE,
#: before `_pin_environment` clears it: the mark is this process's one-shot
#: guard, and a nested pytest that inherited it would refuse to re-exec and
#: raise instead. Hence both — snapshot the flag, then clear the variable.
_REEXEC_MARK = "CHRONICLE_TEST_HASH_SEED_REEXEC"
_REEXECED = os.environ.get(_REEXEC_MARK) == "1"


def _hash_seed_is_bound() -> bool:
    """Did THIS interpreter START under the pinned seed?"""
    if HASH_SEED == "0":
        return sys.flags.hash_randomization == 0
    return _AMBIENT_SEED == HASH_SEED


#: True when the gate this process runs is reproducible. Read by the summary
#: line and by tests/test_harness_determinism.py.
HASH_SEED_BOUND = _hash_seed_is_bound()


def _relaunch_argv() -> list:
    """This process's command line, reconstructed so `-m` stays `-m`.

    `python -m pytest` leaves `sys.argv[0]` pointing at pytest's own
    `__main__.py`; re-running that path as a script would put the pytest
    PACKAGE directory on `sys.path[0]` instead of the cwd, which is a different
    import environment. `__main__.__spec__.parent` is the package `-m` named,
    and it is the one thing that survives the difference. (`sys.orig_argv`
    would be the direct answer, and is 3.10+; this tree is 3.9.)
    """
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    parent = getattr(spec, "parent", None) if spec is not None else None
    if parent:
        return [sys.executable, "-m", parent] + sys.argv[1:]
    return [sys.executable] + sys.argv


def _bind_parent_hash_seed(config) -> None:
    """Re-exec under the pinned seed unless this process already has it."""
    if HASH_SEED.lower() == "off" or HASH_SEED_BOUND:
        return
    if _REEXECED:
        # We already re-executed and the seed still did not take. Raising beats
        # looping, and beats running an unreproducible gate that reports green.
        raise RuntimeError(
            "re-exec under PYTHONHASHSEED=%s did not take "
            "(sys.flags.hash_randomization=%d). Run the suite with "
            "PYTHONHASHSEED=%s exported, or set CHRONICLE_TEST_HASH_SEED=off "
            "to accept a gate that is not reproducible."
            % (HASH_SEED, sys.flags.hash_randomization, HASH_SEED))
    env = dict(_AMBIENT_ENV)
    env["PYTHONHASHSEED"] = HASH_SEED
    env[_REEXEC_MARK] = "1"
    # Restore the real fds 1/2 (see the section comment) — without this the
    # replacement process's output goes into pytest's capture file and is lost.
    capman = config.pluginmanager.getplugin("capturemanager")
    if capman is not None:
        capman.suspend_global_capture(in_=False)
    # atexit handlers do not run across exec, so the sandbox this file made at
    # import time has to go now or every re-exec leaves one behind.
    _sweep_session_tmp()
    sys.stderr.write(
        "chronicle tests: re-exec under PYTHONHASHSEED=%s (was %s) "
        "so the gate is reproducible\n"
        % (HASH_SEED, _AMBIENT_SEED if _AMBIENT_SEED is not None else "unset/random"))
    sys.stderr.flush()
    os.execve(sys.executable, _relaunch_argv(), env)


# ---------------------------------------------------------------------------
# 0b. Import path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import _tmp_support  # noqa: E402  (needs tests/ on sys.path first)


# ---------------------------------------------------------------------------
# 1. Environment pinning (import time — before any test module is imported)
# ---------------------------------------------------------------------------

# Read the opt-in knobs from the real environment BEFORE anything is pinned.
ORDER = (os.environ.get("CHRONICLE_TEST_ORDER") or "").strip().lower()
ORDER_SEED = os.environ.get("CHRONICLE_TEST_SEED") or "0"
STRICT_SOCKETS = os.environ.get("CHRONICLE_TEST_STRICT_SOCKETS") == "1"
ALLOW_NETWORK = os.environ.get("CHRONICLE_TEST_ALLOW_NETWORK") == "1"
LIVE_EMBEDDER = os.environ.get("CHRONICLE_TEST_LIVE_EMBEDDER") == "1"
KEEP_TMP = os.environ.get("CHRONICLE_TEST_KEEP_TMP") == "1"

# Where THIS interpreter found its user site-packages, read BEFORE $HOME is
# pinned below. Pinning HOME moves `site.getuserbase()` for every CHILD process
# the suite spawns, and on macOS that is `~/Library/Python/3.9`, which is where
# numpy lives on this box. A child then silently loses numpy and takes
# `embeddings.batch_cosine_f64`'s documented scalar FALLBACK, while the parent
# takes the numpy path -- so a cross-process comparison of a stored float
# (E5 `novelty`) differs in the last bit and a determinism test fails for a
# reason that has nothing to do with determinism. Found by A4's
# TestCrossProcessStability the moment A11's harness governed it.
#
# Re-pinning PYTHONUSERBASE keeps every child's IMPORT environment identical to
# the parent's while leaving the HOME sandbox doing its actual job, which is
# keeping Chronicle's own `Path.home() / ".hermes"` defaults off the developer's
# real home directory.
_REAL_USER_BASE = os.environ.get("PYTHONUSERBASE") or site.getuserbase()

_SYSTEM_TMP = tempfile.gettempdir()
SESSION_TMP = tempfile.mkdtemp(prefix="chronicle-tests-", dir=_SYSTEM_TMP)
SESSION_HOME = os.path.join(SESSION_TMP, "home")
os.makedirs(SESSION_HOME, exist_ok=True)

#: Pinned to a fixed value regardless of what the shell held.
PINNED_ENV = {
    # The documented CI setting. Pinning it here is what makes runs 1 and 2
    # identical, and it is what keeps `get_embedder` off the localhost probe:
    # every core built from config gets the deterministic offline embedder.
    "CHRONICLE_EMBED_MODEL": "hashing",
    # Chronicle's own tree, so a stray CHRONICLE_DIR cannot point a test
    # (or a child process) at some other checkout.
    "CHRONICLE_DIR": str(_REPO_ROOT),
    # Nothing may reach the developer's real $HOME / ~/.hermes. provider.py and
    # context.py default hermes_home to `Path.home() / ".hermes"`, which reads
    # $HOME, so this is load-bearing, not decorative.
    "HOME": SESSION_HOME,
    "HERMES_HOME": os.path.join(SESSION_HOME, ".hermes"),
    "XDG_CACHE_HOME": os.path.join(SESSION_HOME, ".cache"),
    "XDG_CONFIG_HOME": os.path.join(SESSION_HOME, ".config"),
    "XDG_DATA_HOME": os.path.join(SESSION_HOME, ".local", "share"),
    "XDG_STATE_HOME": os.path.join(SESSION_HOME, ".local", "state"),
    # One sandbox for every temp path, this process and its children.
    "TMPDIR": SESSION_TMP,
    "TMP": SESSION_TMP,
    "TEMP": SESSION_TMP,
    # Deterministic clock/locale for anything that formats or parses.
    "TZ": "UTC",
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
    "PYTHONIOENCODING": "utf-8",
    # The same seed section 0 bound the PARENT to, so a child and its parent
    # never disagree about hash order. The two tests that deliberately vary it
    # override this in their own subprocess env.
    "PYTHONHASHSEED": "0" if HASH_SEED.lower() == "off" else HASH_SEED,
    # See _REAL_USER_BASE above: children must import what the parent imports.
    "PYTHONUSERBASE": _REAL_USER_BASE,
}

#: Removed outright: if present they change behaviour, and no test wants them.
CLEARED_ENV = (
    _REEXEC_MARK,                 # this process's loop guard, not its children's
    "CHRONICLE_EMBED_BASE_URL",   # would aim the probe at a live server
    "CHRONICLE_REQUIRE_BLAKE3",   # =1 raises at engine.serialize import time
    "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID",
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
    "OLLAMA_HOST", "OLLAMA_BASE_URL",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
)


def _pin_environment() -> None:
    for key in CLEARED_ENV:
        os.environ.pop(key, None)
    os.environ.update(PINNED_ENV)
    for path in (PINNED_ENV["HERMES_HOME"], PINNED_ENV["XDG_CACHE_HOME"],
                 PINNED_ENV["XDG_CONFIG_HOME"], PINNED_ENV["XDG_DATA_HOME"],
                 PINNED_ENV["XDG_STATE_HOME"]):
        os.makedirs(path, exist_ok=True)
    # tempfile caches its directory on first use; set it explicitly so the
    # sandbox applies even though tempfile has already been imported above.
    tempfile.tempdir = SESSION_TMP
    if hasattr(time, "tzset"):
        time.tzset()


_pin_environment()


# ---------------------------------------------------------------------------
# 2. Network guard
# ---------------------------------------------------------------------------

class NetworkAccessDisabled(RuntimeError):
    """Raised when a test tries to open a socket. Unit tests are offline."""


#: Every denied attempt, in order. Appended to even when the caller swallows
#: the exception — that is the whole point (engine/embeddings.py's probe loop
#: is `except Exception: continue`).
NETWORK_ATTEMPTS: list = []

_LOCAL_HOSTS = frozenset(("", "localhost", "localhost.", "127.0.0.1", "::1",
                          "0.0.0.0", "broadcasthost"))

_real_socket_class = socket.socket
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


def _deny(what: str, target) -> None:
    msg = "%s(%r) — network access is disabled in the Chronicle test suite" % (what, target)
    NETWORK_ATTEMPTS.append(msg)
    raise NetworkAccessDisabled(msg)


class _GuardedSocket(_real_socket_class):
    """A socket that records and refuses every outbound connection."""

    def __init__(self, family=-1, type=-1, proto=-1, fileno=None):  # noqa: A002
        if STRICT_SOCKETS and family in (socket.AF_INET, socket.AF_INET6, -1):
            _deny("socket.socket", family)
        super().__init__(family, type, proto, fileno)

    def connect(self, address):
        _deny("socket.connect", address)

    def connect_ex(self, address):
        _deny("socket.connect_ex", address)


def _guarded_create_connection(address, *args, **kwargs):
    _deny("socket.create_connection", address)


def _guarded_getaddrinfo(host, port, *args, **kwargs):
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host is not None and str(host).lower() not in _LOCAL_HOSTS:
        _deny("socket.getaddrinfo", host)
    return _real_getaddrinfo(host, port, *args, **kwargs)


def _install_network_guard() -> None:
    socket.socket = _GuardedSocket
    socket.create_connection = _guarded_create_connection
    socket.getaddrinfo = _guarded_getaddrinfo


def _remove_network_guard() -> None:
    socket.socket = _real_socket_class
    socket.create_connection = _real_create_connection
    socket.getaddrinfo = _real_getaddrinfo


if not ALLOW_NETWORK:
    _install_network_guard()


# ---------------------------------------------------------------------------
# 3. Temp sandbox bookkeeping
# ---------------------------------------------------------------------------

#: module nodeid -> number of temp paths that module left behind.
TEMP_LEAKS: dict = {}
_swept = False


def _live_temp_paths() -> set:
    try:
        return {n for n in os.listdir(SESSION_TMP) if n != "home"}
    except OSError:
        return set()


def _sweep_session_tmp() -> None:
    global _swept
    if _swept:
        return
    _swept = True
    tempfile.tempdir = _SYSTEM_TMP
    if KEEP_TMP:
        return
    shutil.rmtree(SESSION_TMP, ignore_errors=True)


atexit.register(_sweep_session_tmp)


# ---------------------------------------------------------------------------
# 4. pytest hooks
# ---------------------------------------------------------------------------

def pytest_configure(config):
    # First, and possibly last: this can replace the process (section 0).
    _bind_parent_hash_seed(config)
    config.addinivalue_line(
        "markers",
        "live_embedder: needs a reachable embedding server; skipped unless "
        "CHRONICLE_TEST_LIVE_EMBEDDER=1")
    config.addinivalue_line(
        "markers",
        "allow_network: this test is expected to open a socket")


def pytest_collection_modifyitems(config, items):
    if not LIVE_EMBEDDER:
        skip_live = pytest.mark.skip(
            reason="needs a live embedding server; set CHRONICLE_TEST_LIVE_EMBEDDER=1")
        for item in items:
            if item.get_closest_marker("live_embedder"):
                item.add_marker(skip_live)
    if ORDER == "reverse":
        items.reverse()
    elif ORDER == "shuffle":
        random.Random(ORDER_SEED).shuffle(items)


@pytest.fixture(autouse=True)
def _hermetic_test(request):
    """Per-test isolation: no sockets, no leaked temp dirs, no state carry-over."""
    before = len(NETWORK_ATTEMPTS)
    _tmp_support.collect_tracked()      # anything pending is not this test's
    live_before = _live_temp_paths()
    yield
    _reset_process_state()
    for path in _tmp_support.collect_tracked():
        _tmp_support.rm_tree(path)
    leaked = _live_temp_paths() - live_before
    if leaked:
        key = request.node.nodeid.split("::")[0]
        TEMP_LEAKS[key] = TEMP_LEAKS.get(key, 0) + len(leaked)
    attempts = NETWORK_ATTEMPTS[before:]
    if attempts and not request.node.get_closest_marker("allow_network"):
        pytest.fail("test attempted network access (%d attempt(s)); the first was:\n  %s\n"
                    "Unit tests must inject the failure (patch urllib.request.urlopen) "
                    "instead of relying on a closed port."
                    % (len(attempts), attempts[0]), pytrace=False)


@pytest.fixture(autouse=True)
def _hosts_drain_where_they_are_called(request, monkeypatch):
    """In production a host (the provider, the context engine) moves a core's
    per-turn curation drain onto one background thread
    (`ChronicleCore.drain_in_background`, `curation.drain.background`): Hermes
    calls on_turn_start inside the user's turn. Assertions here read the store
    right after a turn, which a drain running beside the test would race, so in
    the suite a host drains where it is called -- unless the test class sets
    `background_drain = True`, which is how the worker itself is tested."""
    if getattr(request.cls, "background_drain", False):
        yield
        return
    try:
        from engine.core import ChronicleCore
    except Exception:                    # a test that never imports the engine
        yield
        return
    monkeypatch.setattr(ChronicleCore, "drain_in_background", lambda self: None)
    yield


def _reset_process_state() -> None:
    """Undo the process-wide state a core construction installs.

    `ChronicleCore.__init__` stores itself in `_instances`/`_active` and calls
    `access.configure_topology(...)`, all of which are class/module globals. Left
    alone they make a later test see an earlier test's core and ACL — the exact
    coupling that reversed-order runs expose.
    """
    core_mod = sys.modules.get("engine.core")
    if core_mod is not None:
        try:
            core_mod.ChronicleCore._instances.clear()
            core_mod.ChronicleCore._active = None
        except Exception:
            pass
    access_mod = sys.modules.get("engine.access")
    if access_mod is not None:
        try:
            access_mod.configure_topology(None)
        except Exception:
            pass


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    lines = ["hermetic: env pinned, hash seed %s, network %s, tmp sandbox %s"
             % ("%s (parent and children)" % HASH_SEED if HASH_SEED_BOUND
                else "NOT PINNED (CHRONICLE_TEST_HASH_SEED=off) — this run is not reproducible",
                "ALLOWED (CHRONICLE_TEST_ALLOW_NETWORK=1)" if ALLOW_NETWORK
                else ("denied, strict" if STRICT_SOCKETS else "denied"),
                SESSION_TMP)]
    if NETWORK_ATTEMPTS:
        lines.append("  network attempts recorded: %d" % len(NETWORK_ATTEMPTS))
    leftover = len(_live_temp_paths())
    if leftover:
        by_module = sorted(TEMP_LEAKS.items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append("  temp paths left inside the sandbox: %d (removed at exit)" % leftover)
        for name, count in by_module:
            lines.append("    %-58s %d" % (name, count))
    terminalreporter.write_line("\n".join(lines))


def pytest_unconfigure(config):
    # Not pytest_sessionfinish: the terminal summary is written from inside the
    # session-finish hook, and hook order across plugins is not guaranteed —
    # sweeping there can erase the sandbox before the summary counts it.
    _sweep_session_tmp()
    if not ALLOW_NETWORK:
        _remove_network_guard()
