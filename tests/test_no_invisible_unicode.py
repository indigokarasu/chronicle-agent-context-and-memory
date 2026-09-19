"""Chronicle — no invisible or bidi-control characters in source.

A zero-width or direction-control character in code or docs is invisible in
review and can make source read differently from what runs ("Trojan Source").
Where Chronicle needs one (stripping Gmail's bidi isolates, engine/substance.py)
it is written as a `\\u` escape. The Hermes plugin scanner flags literal ones.
"""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVISIBLE = {chr(c) for c in list(range(0x200B, 0x2010)) + list(range(0x202A, 0x202F))
             + list(range(0x2060, 0x206A)) + [0xFEFF]}
SKIP_PREFIXES = ("dashboard/dist/", "dashboard/web/node_modules/")
TEXT_SUFFIXES = (".py", ".md", ".js", ".mjs", ".yaml", ".yml", ".toml", ".json", ".txt", ".sh")


class TestNoInvisibleUnicodeInSource(unittest.TestCase):
    def test_tracked_text_files(self):
        try:
            files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                                   text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        hits = []
        for rel in files:
            if rel.startswith(SKIP_PREFIXES) or not rel.endswith(TEXT_SUFFIXES):
                continue
            try:
                text = (ROOT / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                found = sorted({hex(ord(ch)) for ch in line if ch in INVISIBLE})
                if found:
                    hits.append("%s:%d %s" % (rel, n, found))
        self.assertEqual(hits, [], "write these as \\u escapes:\n" + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
