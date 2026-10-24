#!/usr/bin/env python3
"""Scan the lines a change adds for secrets and personal data (stdlib only).

Run by .github/workflows/scan.yml on every pull request and every push to main:

    python .github/scripts/scan_changes.py --base <sha>        # lines added since <sha>
    python .github/scripts/scan_changes.py --all               # every tracked file

Only added lines are checked, so the made-up keys that existing tests use do not
fail every run. A line that must contain a match (a test of the scanner itself, a
documented example) can carry the marker ``chronicle-scan: allow``.

Findings print the file, the line and a shortened excerpt, never the whole value.
Exit status: 0 clean, 1 findings, 2 usage or git error.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

ALLOW_MARK = "chronicle-scan: allow"

SECRET_PATTERNS = {
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "AWS access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "API key (sk-...)": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}"),
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "credentials in a URL": re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]{3,}@[^/\s]+"),
    "assigned secret": re.compile(
        r"""(?i)\b(?:secret|token|password|passwd|api[_-]?key)\b["']?\s*[:=]\s*["']([A-Za-z0-9+/_=-]{24,})["']"""),
}
# a value that says it is not a real secret
PLACEHOLDER = re.compile(r"(?i)test|example|placeholder|dummy|sentinel|fake|redacted")

IPV4_RE = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
DOC_NETS = ((192, 0, 2), (198, 51, 100), (203, 0, 113))
# well-known public resolvers: named in code as "an off-host address", identify no one
PUBLIC_RESOLVERS = {(8, 8, 8, 8), (8, 8, 4, 4), (1, 1, 1, 1), (1, 0, 0, 1), (9, 9, 9, 9)}

EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![A-Za-z0-9-])")
EMAIL_OK_DOMAIN = re.compile(
    r"(?i)(?:^|\.)(?:example\.(?:com|org|net)|[a-z0-9-]+\.(?:test|example|invalid|localhost|local))$"
    r"|^(?:example|test|invalid|localhost|local)$"
    r"|^users\.noreply\.github\.com$|^noreply\.github\.com$")

# Fixture directories: addresses and IPs there are test data by construction.
FIXTURE_PREFIXES = ("tests/",)


def ip_allowed(a: int, b: int, c: int, d: int) -> bool:
    if max(a, b, c, d) > 255:
        return True                                   # a version string, not an address
    if a in (0, 127, 255) or (a, b, c) in DOC_NETS or (a, b, c, d) in PUBLIC_RESOLVERS:
        return True
    if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 169 and b == 254):
        return True                                   # private and link-local ranges identify no one
    return a == 100 and 64 <= b <= 127                # carrier-grade NAT (shared address space)


def redact(s: str) -> str:
    return s if len(s) <= 12 else s[:6] + "...(%d chars)" % len(s)


def findings(path: str, line: str) -> list[tuple[str, str]]:
    if ALLOW_MARK in line:
        return []
    out = []
    for kind, rx in SECRET_PATTERNS.items():
        m = rx.search(line)
        if not m:
            continue
        value = m.group(1) if m.groups() else m.group(0)
        if PLACEHOLDER.search(value):
            continue
        out.append((kind, redact(m.group(0))))
    if path.startswith(FIXTURE_PREFIXES):
        return out
    for m in EMAIL_RE.finditer(line):
        if not EMAIL_OK_DOMAIN.search(m.group(1).rstrip(".")):
            out.append(("e-mail address", "<address at %s>" % m.group(1)[-40:]))
    for m in IPV4_RE.finditer(line):
        if not ip_allowed(*(int(x) for x in m.groups())):
            out.append(("IP address", m.group(0)))
    return out


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def added_lines(base: str):
    """(path, line number, text) for every line added since `base`."""
    diff = git("diff", "--unified=0", "--no-color", "--no-ext-diff", "--diff-filter=AMR", base, "HEAD")
    path, n = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            n = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            yield path, n, raw[1:]
            n += 1


def all_lines():
    for path in git("ls-files").splitlines():
        try:
            with open(path, encoding="utf-8") as fh:
                for n, text in enumerate(fh, 1):
                    yield path, n, text.rstrip("\n")
        except (UnicodeDecodeError, OSError):
            continue                                  # binary or unreadable: nothing to scan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--base", help="scan the lines added since this commit")
    g.add_argument("--all", action="store_true", help="scan every tracked file")
    args = ap.parse_args(argv)
    try:
        lines = all_lines() if args.all else added_lines(args.base)
        hits = [(p, n, k, e) for p, n, text in lines for k, e in findings(p, text)]
    except subprocess.CalledProcessError as e:
        print("scan: git failed: %s" % (e.stderr or e).strip(), file=sys.stderr)
        return 2
    for p, n, k, e in hits:
        print("%s:%d: %s: %s" % (p, n, k, e))
    if hits:
        print("\n%d finding(s). Remove the value, or mark a line that must keep it with `%s`."
              % (len(hits), ALLOW_MARK))
        return 1
    print("scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
