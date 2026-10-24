"""
Chronicle — .github/scripts/scan_changes.py, the CI scan for secrets and personal data.

Values are assembled at run time so this file never contains a match itself.
"""

import importlib.util
import os
import subprocess  # nosec B404
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "scan_changes.py"
_spec = importlib.util.spec_from_file_location("scan_changes", str(_PATH))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

GH = "gh" + "p_" + "Q7w" * 12
SK = "s" + "k-" + "Zr9" * 10
MAIL = "someone" + "@" + "realmail.org"


class TestFindings(unittest.TestCase):
    def kinds(self, line, path="engine/x.py"):
        return [k for k, _ in S.findings(path, line)]

    def test_real_looking_secrets_are_found(self):
        self.assertEqual(self.kinds("token = '%s'" % GH)[:1], ["GitHub token"])
        self.assertIn("API key (sk-...)", self.kinds("key: %s" % SK))

    def test_placeholders_pass(self):
        self.assertEqual(self.kinds("key = 's" + "k-FAKE" + "x" * 30 + "'"), [])

    def test_excerpt_never_echoes_the_value(self):
        (_, ex), = [f for f in S.findings("a.py", GH)]
        self.assertNotIn(GH, ex)

    def test_personal_data_outside_tests(self):
        self.assertEqual(self.kinds("mail " + MAIL), ["e-mail address"])
        self.assertEqual(self.kinds("host 93.184.216." + "34"), ["IP address"])

    def test_safe_addresses_pass(self):
        for line in ("a@" + "example.com", "x@users.noreply" + ".github.com", "10.0.0.1",
                     "192.168.1.1", "127.0.0.1", "8.8.8.8", "203.0.113.5", "version 1.2.3.400"):
            self.assertEqual(self.kinds(line), [], line)

    def test_tests_may_hold_fixture_addresses_but_not_secrets(self):
        self.assertEqual(self.kinds("mail " + MAIL, "tests/t.py"), [])
        self.assertEqual(self.kinds(GH, "tests/t.py"), ["GitHub token"])

    def test_allow_mark(self):
        self.assertEqual(self.kinds(GH + "  # " + S.ALLOW_MARK), [])


class TestAddedLinesOnly(unittest.TestCase):
    def test_only_new_lines_are_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["/usr/bin/git", *a], cwd=d, check=True, capture_output=True,  # nosec B603
                               env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})
            git("init", "-q")
            Path(d, "old.py").write_text("old = '%s'\n" % GH)
            git("add", "-A")
            git("commit", "-q", "-m", "base")
            base = subprocess.run(["/usr/bin/git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()  # nosec B603
            Path(d, "new.py").write_text("ok = 1\nmail = '%s'\n" % MAIL)
            git("add", "-A")
            git("commit", "-q", "-m", "change")
            cwd = os.getcwd()
            os.chdir(d)
            try:
                hits = list(S.added_lines(base))
            finally:
                os.chdir(cwd)
            self.assertEqual([(p, n) for p, n, _ in hits], [("new.py", 1), ("new.py", 2)])
            found = [(p, n) for p, n, t in hits if S.findings(p, t)]
            self.assertEqual(found, [("new.py", 2)])


if __name__ == "__main__":
    unittest.main()
