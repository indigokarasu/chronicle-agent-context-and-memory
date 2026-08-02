#!/usr/bin/env python3
"""
Chronicle config audit — finds declared-but-unwired configuration flags.

Walks all leaf keys in DEFAULTS and scans engine/*.py source for textual
evidence that each key's dotted path (or, failing that, its final segment) is
actually read. Reports a WIRED / possibly-dormant table (§u1 audit).

This is a maintenance report, not a prover. Regex over source text cannot
distinguish "genuinely unread" from "read via a code shape this script
doesn't model" (a sub-dict fetched once and indexed later, a dynamic f-string
key, a coincidental leaf-name collision with an unrelated key). Read the
"evidence" column and verify anything surprising by hand before deleting a
flag or trusting a "WIRED" you didn't expect.

Usage:  python3 scripts/audit_config.py
Output: table of [path | status | evidence]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import DEFAULTS, DORMANT

# Config-object variable names actually used in engine/*.py: self.cfg, bare cfg
# (a function/constructor param), and a few call sites just say config/self.config.
_ACCESSOR = r"\b(?:self\.)?(?:cfg|config)\b"


def _leaf_keys(d: dict, prefix: str = "") -> list:
    """Recursively flatten dict to a list of (dotted path, leaf value) tuples."""
    result = []
    for k, v in (d or {}).items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.extend(_leaf_keys(v, full))
        else:
            result.append((full, v))
    return result


def _read_engine_source(engine_dir: Path) -> str:
    """Concatenate engine/*.py so each key is checked with one in-memory regex
    pass instead of one `grep` subprocess per key (the previous approach spawned
    up to 4 subprocesses per key and still missed most real call sites)."""
    chunks = []
    for f in sorted(engine_dir.glob("*.py")):
        chunks.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _quoted_get_or_index(name: str) -> re.Pattern:
    """`<accessor>.get("name"` / `<accessor>.get('name'` / `<accessor>["name"]` /
    `<accessor>['name']`, allowing whitespace after the open paren/bracket."""
    esc = re.escape(name)
    return re.compile(_ACCESSOR + r"\s*(?:\.get\(\s*|\[\s*)['\"]" + esc + r"['\"]")


def _dynamic_prefix(parent: str) -> re.Pattern:
    """`<accessor>.get(f"parent.{...` — the one dynamic-key style this codebase
    actually uses (engine/forgetting.py: `cfg.get(f"domains.{domain}", {})`)."""
    esc = re.escape(parent)
    return re.compile(_ACCESSOR + r"\s*\.get\(\s*f['\"]" + esc + r"\.\{")


def _evidence(source: str, path: str) -> str:
    """Classify wiring evidence for one dotted config path.

    "exact"       — the full dotted path appears quoted next to a get()/[] on
                     a config accessor. Strong evidence.
    "leaf"        — only the final segment matches that way. Weak evidence:
                     could be a sub-dict fetched by its parent key and indexed
                     later (real), or an unrelated key with the same leaf name
                     (false positive).
    "dynamic"     — the key's parent path is read via an f-string template
                     (`cfg.get(f"parent.{var}")`); this leaf is one of the
                     runtime values `var` can take. Moderate evidence.
    ""            — no textual evidence found at all.
    """
    if _quoted_get_or_index(path).search(source):
        return "exact"
    parent, _, leaf = path.rpartition(".")
    if parent and _dynamic_prefix(parent).search(source):
        return "dynamic"
    if _quoted_get_or_index(leaf).search(source):
        return "leaf"
    return ""


def main():
    engine_dir = Path(__file__).resolve().parent.parent / "engine"
    if not engine_dir.exists():
        print(f"Error: engine dir not found at {engine_dir}", file=sys.stderr)
        return 1

    source = _read_engine_source(engine_dir)
    keys = _leaf_keys(DEFAULTS)
    dormant_paths = {path for path, _, _ in DORMANT}

    rows = []  # (path, status, note)
    for path, _default_val in sorted(keys):
        hit = _evidence(source, path)
        known = path in dormant_paths
        if hit == "exact":
            status, note = "WIRED", ""
        elif hit == "dynamic":
            status, note = "WIRED", "[dynamic key template]"
        elif hit == "leaf":
            status, note = "possibly-wired", "[leaf-name match only — verify]"
        elif known:
            status, note = "DORMANT", "[known]"
        else:
            status, note = "possibly-dormant", "[no textual match — verify]"
        rows.append((path, status, note))

    print("Config Audit: Declared vs. Wired Flags")
    print("=" * 90)
    print(f"{'Path':<50} {'Status':<16} {'Evidence':<24}")
    print("-" * 90)
    for path, status, note in rows:
        print(f"{path:<50} {status:<16} {note:<24}")

    dormant_count = sum(1 for _, status, _ in rows if status == "DORMANT")
    known_dormant = sum(1 for _, status, note in rows if status == "DORMANT" and "[known]" in note)
    possibly_wired = sum(1 for _, status, _ in rows if status == "possibly-wired")
    possibly_dormant = sum(1 for _, status, _ in rows if status == "possibly-dormant")
    print("-" * 90)
    print(f"Total flags: {len(rows)}")
    print(f"WIRED: {sum(1 for _, status, _ in rows if status == 'WIRED')}")
    print(f"DORMANT (known): {known_dormant}")
    print(f"possibly-wired (leaf match only, unverified): {possibly_wired}")
    print(f"possibly-dormant (no textual match, unverified): {possibly_dormant}")
    print(f"Dormant total: {dormant_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
