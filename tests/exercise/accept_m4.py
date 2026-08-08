#!/usr/bin/env python3
"""
Acceptance - m4: version unification (single source of truth = plugin.yaml).

  (1) plugin.yaml carries a parseable top-level ``version:`` line.
  (2) ``__init__.__version__`` equals that string exactly, and is genuinely
      DERIVED from plugin.yaml (proved by re-reading against a mutated copy of
      the manifest, not just by comparing two constants that happen to agree).
  (3) dashboard/plugin_api.py reports the same version from GET /status - proved
      by actually calling ``get_status()`` against a throwaway HERMES_HOME, in
      BOTH load modes the module really sees (mounted by file path, and imported
      as a package submodule), so neither branch of ``_resolve_version()`` is
      dead code.
  (4) No stray hardcoded 5.3.x literal remains anywhere in the tree outside
      CHANGELOG / history / .bak backups. The scan self-tests first: the regex
      must match a known-positive control string AND the excluded set (the
      CHANGELOG's release history) must produce hits. A zero-stray result from a
      matcher that matches nothing would be fabricated reassurance.
  (5) The files that CANNOT read plugin.yaml at runtime - pyproject.toml,
      dashboard/manifest.json, README.md - carry literals equal to it, so the
      unification is real and drift is caught rather than merely renamed.

Run:  /usr/bin/python3 tests/exercise/accept_m4.py
"""

import collections
import importlib.util
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION_RE = re.compile(r"5\.3\.\d+")

SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "node_modules", "dist", ".venv"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _fail(check, msg):
    print("FAIL: %s - %s" % (check, msg))
    return False


def _parse_version(text):
    """The same one-line stdlib parse the production code uses, re-implemented
    here on purpose: the acceptance check must not inherit a bug from the code
    under test."""
    for line in text.splitlines():
        if not line.startswith("version:"):
            continue
        value = line.split(":", 1)[1].split("#", 1)[0].strip()
        value = value.strip("\"'").strip()
        if value:
            return value
    return None


def _plugin_yaml_version():
    return _parse_version((ROOT / "plugin.yaml").read_text(encoding="utf-8"))


def _ensure_fastapi_stub():
    """dashboard/plugin_api.py is mounted by the Hermes dashboard host, which
    supplies FastAPI at runtime; Chronicle itself is stdlib-only and does not
    depend on it (see pyproject.toml). Stub just enough of the surface that the
    real module body - and the real ``get_status()`` - can be executed here."""
    try:
        import fastapi  # noqa: F401
        return
    except ImportError:
        pass

    stub = types.ModuleType("fastapi")

    class _APIRouter(object):
        def get(self, *a, **k):
            return lambda fn: fn

        def post(self, *a, **k):
            return lambda fn: fn

    def _Query(default=None, **k):
        return default

    stub.APIRouter = _APIRouter
    stub.Query = _Query
    sys.modules["fastapi"] = stub


def _load_by_path(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_hermes_home(tmp):
    """A throwaway HERMES_HOME with an empty Chronicle DB, so get_status() takes
    its 'active' branch without ever touching a real database on this machine."""
    db = Path(tmp) / "commons" / "db" / "chronicle" / "chronicle.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(db)).close()
    return tmp


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def check1_plugin_yaml_parseable():
    v = _plugin_yaml_version()
    print("  plugin.yaml version = %r" % (v,))
    if not v or not re.match(r"^\d+\.\d+\.\d+$", v):
        return _fail("check1", "plugin.yaml version missing/unparseable: %r" % (v,))
    if VERSION_RE.match(v):
        return _fail("check1", "plugin.yaml is still on 5.3.x - nothing to unify")
    return True


def check2_init_version_matches():
    expected = _plugin_yaml_version()
    mod = _load_by_path("chronicle_root_m4", ROOT / "__init__.py")
    print("  __init__.__version__  = %r" % (mod.__version__,))
    if mod.__version__ != expected:
        return _fail("check2", "__version__ %r != plugin.yaml %r" % (mod.__version__, expected))

    ok = True

    # Prove __version__ is DERIVED, not coincidentally equal: stand up a copy of
    # __init__.py next to a manifest declaring a value that appears nowhere else
    # in the tree, load it, and confirm __version__ follows. A hardcoded literal
    # cannot pass this - it would still report the real version.
    tmp = tempfile.mkdtemp(prefix="m4_ver_")
    try:
        shutil.copy(str(ROOT / "__init__.py"), os.path.join(tmp, "__init__.py"))
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        Path(tmp, "plugin.yaml").write_text(
            manifest.replace("version: " + expected, "version: 9.9.9-probe"), encoding="utf-8")
        probe = _load_by_path("chronicle_root_m4_probe", Path(tmp) / "__init__.py")
        print("  against mutated manifest -> %r (expect '9.9.9-probe')" % (probe.__version__,))
        if probe.__version__ != "9.9.9-probe":
            ok = _fail("check2", "__version__ did not follow plugin.yaml; got %r"
                       % (probe.__version__,)) and ok
    finally:
        sys.modules.pop("chronicle_root_m4_probe", None)
        shutil.rmtree(tmp, ignore_errors=True)

    # And the spec'd fallback: with no manifest present, import must still
    # succeed and report the literal rather than raising.
    tmp = tempfile.mkdtemp(prefix="m4_nover_")
    try:
        shutil.copy(str(ROOT / "__init__.py"), os.path.join(tmp, "__init__.py"))
        probe = _load_by_path("chronicle_root_m4_nomanifest", Path(tmp) / "__init__.py")
        print("  with no plugin.yaml  -> %r (fallback literal)" % (probe.__version__,))
        if probe.__version__ != probe._VERSION_FALLBACK:
            ok = _fail("check2", "missing-manifest fallback returned %r, expected %r"
                       % (probe.__version__, probe._VERSION_FALLBACK)) and ok
        if probe._VERSION_FALLBACK != expected:
            ok = _fail("check2", "fallback literal %r has drifted from plugin.yaml %r"
                       % (probe._VERSION_FALLBACK, expected)) and ok
    finally:
        sys.modules.pop("chronicle_root_m4_nomanifest", None)
        shutil.rmtree(tmp, ignore_errors=True)

    return ok


def check3_dashboard_status_matches():
    expected = _plugin_yaml_version()
    _ensure_fastapi_stub()
    ok = True

    # --- mode A: mounted by file path (how the dashboard host loads it) -----
    # Importing this module must be side-effect free. In particular it must not
    # push the plugin root onto sys.path: the root holds generically named
    # top-level modules (context.py, provider.py, _base.py) that would then
    # shadow any same-named module for the entire dashboard process.
    path_before = list(sys.path)
    mod = _load_by_path("chronicle_plugin_api_m4", ROOT / "dashboard" / "plugin_api.py")
    print("  [path-mounted] _VERSION = %r" % (getattr(mod, "_VERSION", None),))
    if getattr(mod, "_VERSION", None) != expected:
        ok = _fail("check3", "path-mounted _VERSION %r != %r"
                   % (getattr(mod, "_VERSION", None), expected)) and ok
    if sys.path != path_before:
        # Multiset diff: re-inserting an entry that was already present is still
        # a mutation (it changes resolution order), so plain membership is not
        # enough to describe what happened.
        before_counts = collections.Counter(path_before)
        added = list((collections.Counter(sys.path) - before_counts).elements())
        ok = _fail("check3", "importing plugin_api mutated sys.path; added %r" % (added,)) and ok
    else:
        print("  [path-mounted] sys.path unchanged by import: OK")

    # Real call, real response body, throwaway HERMES_HOME.
    tmp = tempfile.mkdtemp(prefix="m4_home_")
    prev = os.environ.get("HERMES_HOME")
    try:
        os.environ["HERMES_HOME"] = _fake_hermes_home(tmp)
        status = mod.get_status()
        print("  get_status()['version'] = %r (status=%r)"
              % (status.get("version"), status.get("status")))
        if status.get("version") != expected:
            ok = _fail("check3", "GET /status version %r != %r"
                       % (status.get("version"), expected)) and ok
    finally:
        if prev is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = prev
        shutil.rmtree(tmp, ignore_errors=True)

    # --- mode B: imported as a package submodule ----------------------------
    # Exercises _resolve_version()'s first branch (``from .. import __version__``)
    # so it is proved reachable rather than left as decorative dead code. The
    # plugin root is exposed under a fixed package name via a symlink so this
    # does not depend on the checkout directory's name.
    tmp2 = tempfile.mkdtemp(prefix="m4_pkg_")
    pkg = "chronicle_pkg_m4"
    try:
        os.symlink(str(ROOT), os.path.join(tmp2, pkg))
        sys.path.insert(0, tmp2)
        import importlib
        sub = importlib.import_module(pkg + ".dashboard.plugin_api")
        print("  [package-imported] _VERSION = %r (package=%r)"
              % (getattr(sub, "_VERSION", None), sub.__package__))
        if sub.__package__ != pkg + ".dashboard":
            ok = _fail("check3", "package-mode import did not load as a submodule") and ok
        if getattr(sub, "_VERSION", None) != expected:
            ok = _fail("check3", "package-mode _VERSION %r != %r"
                       % (getattr(sub, "_VERSION", None), expected)) and ok
    except OSError as e:
        ok = _fail("check3", "could not set up package-mode import: %s" % (e,)) and ok
    finally:
        if tmp2 in sys.path:
            sys.path.remove(tmp2)
        for name in list(sys.modules):
            if name == pkg or name.startswith(pkg + "."):
                del sys.modules[name]
        shutil.rmtree(tmp2, ignore_errors=True)

    return ok


def _scan_tree():
    """Return (stray_hits, excluded_hits, files_scanned)."""
    stray, excluded, scanned = [], [], 0
    for dirpath, dirnames, filenames in os.walk(str(ROOT)):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            full = Path(dirpath) / fn
            try:
                if full.stat().st_size > 2 * 1024 * 1024:
                    continue
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            rel = str(full.relative_to(ROOT))
            low = rel.lower()
            is_excluded = ("changelog" in low or "history" in low or ".bak" in low)
            for i, line in enumerate(text.splitlines(), 1):
                if VERSION_RE.search(line):
                    (excluded if is_excluded else stray).append(
                        "%s:%d: %s" % (rel, i, line.strip()[:110]))
    return stray, excluded, scanned


def check4_no_stray_hardcodes():
    # Self-test 1: the matcher matches a known positive. Assembled at runtime so
    # this file does not itself become a hit in the scan below.
    control = 'STRAY_VERSION = "5.3.%d"' % 3
    if not VERSION_RE.search(control):
        return _fail("check4", "matcher is broken - it does not match %r" % (control,))
    stray, excluded, scanned = _scan_tree()
    print("  files scanned = %d" % scanned)
    # Self-test 2: the walk actually reaches content. The CHANGELOG's release
    # history is a guaranteed 5.3.x source; zero hits there means the scan is
    # not looking at anything and a zero-stray result would be meaningless.
    print("  hits inside CHANGELOG/history/.bak (expected > 0) = %d" % len(excluded))
    if not excluded:
        return _fail("check4", "scan found no 5.3.x even in CHANGELOG/history - scan is inert")
    print("  stray hits outside CHANGELOG/history/.bak = %d" % len(stray))
    for h in stray:
        print("    " + h)
    if stray:
        return _fail("check4", "%d stray hardcoded 5.3.x reference(s) remain" % len(stray))
    return True


def check5_static_literals_match():
    """pyproject.toml / manifest.json / README.md are read by tools that cannot
    execute Chronicle's version reader, so their literals must equal
    plugin.yaml. Anything else is a second source of truth waiting to drift."""
    expected = _plugin_yaml_version()
    targets = [
        ("pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
        ("dashboard/manifest.json", r'"version"\s*:\s*"([^"]+)"'),
        ("README.md", r'^Version:\s*([0-9][^\s]*?)\.?$'),
    ]
    ok = True
    for rel, pattern in targets:
        rx = re.compile(pattern, re.M)
        text = (ROOT / rel).read_text(encoding="utf-8")
        m = rx.search(text)
        got = m.group(1) if m else None
        print("  %-24s -> %r" % (rel, got))
        if got != expected:
            ok = _fail("check5", "%s declares %r, plugin.yaml says %r" % (rel, got, expected)) and ok
    return ok


def main():
    ok = True
    for fn in (check1_plugin_yaml_parseable,
               check2_init_version_matches,
               check3_dashboard_status_matches,
               check4_no_stray_hardcodes,
               check5_static_literals_match):
        print("\n[%s]" % fn.__name__)
        try:
            ok = fn() and ok
        except Exception as e:  # noqa: BLE001 - acceptance harness reports, never crashes
            import traceback
            traceback.print_exc()
            ok = _fail(fn.__name__, "raised %s: %s" % (type(e).__name__, e)) and ok
    print("\nRESULT: " + ("ALL CHECKS PASS" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
