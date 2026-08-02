#!/usr/bin/env python3
"""
Acceptance — u1: config honesty audit at boot.

  (1) Booting a ChronicleCore with retrieval.query_understanding.hyde=True logs
      a warning from the chronicle.config logger identifying the dormant flag.
  (1b) Booting with hyde=False logs ZERO hyde warnings — regression guard for
       the sonnet-1 bug where `current_val != True` fired on False too, so the
       "off" setting warned "is enabled".
  (1c) Booting twice with hyde=True logs the warning exactly once (per-process
       de-dup), not once per Config()/ChronicleCore() instantiation.
  (2) scripts/audit_config.py runs without error and reports >=4 known-dormant
      keys, naming all four confirmed-dormant flags.
  (3) Full regression harness unchanged (run separately by the harness script).

Run:  python3 tests/exercise/accept_u1.py
"""

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import ChronicleCore
from engine import config as config_mod


def _fail(check, msg):
    print(f"FAIL: {check} — {msg}")
    return False


class _Collector(logging.Handler):
    """Collects formatted log records without printing them (no stray
    StreamHandler left attached to the shared 'chronicle.config' logger —
    the sonnet-1 version leaked one of those on every call)."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(self.format(record))


def _boot_and_collect(config, home=None):
    """Boot a ChronicleCore under `config`, return (messages, cleanup_fn)."""
    home = home or tempfile.mkdtemp(prefix="u1_")
    log = logging.getLogger("chronicle.config")
    collector = _Collector()
    prior_level = log.level
    log.addHandler(collector)
    log.setLevel(logging.WARNING)

    def cleanup():
        log.removeHandler(collector)
        log.setLevel(prior_level)
        shutil.rmtree(home, ignore_errors=True)

    ChronicleCore(home, config)
    return collector.messages, cleanup


def check1_hyde_enabled_warns():
    """Boot with hyde=True; a warning naming 'hyde' must be logged."""
    config_mod._DORMANT_WARNED.clear()
    messages, cleanup = _boot_and_collect(
        {"retrieval": {"query_understanding": {"hyde": True}}})
    try:
        hyde_warns = [m for m in messages if "hyde" in m.lower()]
        if not hyde_warns:
            return _fail("check1", f"no warnings logged when hyde=True; got {messages}")
        print("PASS: check1 — hyde=True logs dormant-flag warning")
        for msg in hyde_warns:
            print(f"      {msg}")
        return True
    finally:
        cleanup()


def check1b_hyde_disabled_silent():
    """Boot with hyde=False (and the other two booleans off); must log zero
    warnings mentioning hyde/expand_synonyms/decompose — regression guard for
    the `!= True` comparison bug that warned regardless of the actual value."""
    config_mod._DORMANT_WARNED.clear()
    messages, cleanup = _boot_and_collect({
        "retrieval": {"query_understanding": {
            "hyde": False, "expand_synonyms": False, "decompose": False}}})
    try:
        bad = [m for m in messages
               if any(name in m.lower() for name in ("hyde", "expand_synonyms", "decompose"))]
        if bad:
            return _fail("check1b", f"flags set to False still warned: {bad}")
        print("PASS: check1b — hyde/expand_synonyms/decompose=False logs zero warnings")
        return True
    finally:
        cleanup()


def check1c_dedup_across_boots():
    """Booting twice with hyde=True must warn exactly once (per-process de-dup),
    not once per Config()/ChronicleCore() instantiation."""
    config_mod._DORMANT_WARNED.clear()
    cfg = {"retrieval": {"query_understanding": {"hyde": True}}}
    home_a = tempfile.mkdtemp(prefix="u1_dedup_a_")
    home_b = tempfile.mkdtemp(prefix="u1_dedup_b_")
    log = logging.getLogger("chronicle.config")
    collector = _Collector()
    prior_level = log.level
    log.addHandler(collector)
    log.setLevel(logging.WARNING)
    try:
        ChronicleCore(home_a, cfg)
        ChronicleCore(home_b, cfg)
        hyde_warns = [m for m in collector.messages if "hyde" in m.lower()]
        if len(hyde_warns) != 1:
            return _fail("check1c",
                         f"expected exactly 1 hyde warning across 2 boots, got {len(hyde_warns)}: {hyde_warns}")
        print("PASS: check1c — two boots with hyde=True log exactly one warning (de-duped)")
        return True
    finally:
        log.removeHandler(collector)
        log.setLevel(prior_level)
        shutil.rmtree(home_a, ignore_errors=True)
        shutil.rmtree(home_b, ignore_errors=True)


def check2_audit_script():
    """Run audit_config.py and verify it reports >=4 known-dormant keys."""
    script = ROOT / "scripts/audit_config.py"
    if not script.exists():
        return _fail("check2", f"audit script not found at {script}")

    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        return _fail("check2", "audit script timed out")
    except Exception as e:
        return _fail("check2", f"audit script raised {type(e).__name__}: {e}")

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", "replace")
        return _fail("check2", f"audit script exited {result.returncode}: {err}")

    output = result.stdout.decode("utf-8", "replace")

    known_count = output.count("[known]")
    if known_count < 4:
        print(f"Output:\n{output}")
        return _fail("check2", f"expected >=4 known-dormant, got {known_count}")

    expected_keys = ["hyde", "expand_synonyms", "decompose", "reranker_version"]
    found = [k for k in expected_keys if k in output]
    if len(found) < len(expected_keys):
        missing = [k for k in expected_keys if k not in output]
        return _fail("check2", f"audit missing expected keys: {missing}")

    print(f"PASS: check2 — audit script reports {known_count} known-dormant flags")
    for key in expected_keys:
        for line in output.splitlines():
            if key in line:
                print(f"      {line.strip()}")
                break
    return True


def main():
    ok = True
    for fn in (check1_hyde_enabled_warns, check1b_hyde_disabled_silent,
               check1c_dedup_across_boots, check2_audit_script):
        ChronicleCore._instances.clear()
        try:
            ok = fn() and ok
        except Exception as e:
            import traceback
            traceback.print_exc()
            ok = _fail(fn.__name__, f"raised {type(e).__name__}: {e}") and ok

    print("\nRESULT: " + ("ALL CHECKS PASS" if ok else "FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
