"""
Chronicle — the release's own version markers agree, and something runs the
check that says so.

WHY THIS FILE EXISTS. `tests/exercise/accept_m4.py` is the tree's version-
unification acceptance script. It is thorough: it proves `__version__` is
DERIVED from `plugin.yaml` rather than coincidentally equal (by loading a copy
next to a mutated manifest), it exercises the dashboard's `get_status()` in both
mount modes, and it compares every static literal in the tree. It also exits
non-zero when any of that fails.

Nothing ran it. The v5.7.0 pre-ship review found `plugin.yaml` at 5.5.0 and
`pyproject.toml`, `README.md` and `dashboard/manifest.json` at 5.4.1 in a tree
about to be tagged 5.7.0 — and `accept_m4.py` had been failing on exactly those
three comparisons the whole time, in a directory the suite deliberately skips
(`tests/exercise/` holds acceptance scripts, not unit tests). A check whose
result nobody reads is not a check.

So this module is the wire: one test that runs the script as a subprocess and
fails on a non-zero exit, plus direct assertions on the markers so a failure
here names the file that drifted rather than making you read a subprocess log.

Deliberately a subprocess, not an import: accept_m4.py loads `__init__.py` under
throwaway module names, stubs fastapi, mutates `os.environ["HERMES_HOME"]` and
`sys.modules`, and writes temp trees. In-process that is exactly the kind of
global-state residue `tests/README.md` forbids a test from leaving behind.
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: Every file that states the release version, and how to read it out. The point
#: of listing them here as well as in accept_m4.py is that a NEW marker file
#: should have to be added in one obvious place; `test_no_marker_is_unlisted`
#: below is the thing that notices when one appears.
MARKERS = {
    "plugin.yaml": r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)\s*$",
    "pyproject.toml": r"^version\s*=\s*\"([0-9]+\.[0-9]+\.[0-9]+)\"\s*$",
    "README.md": r"^Version:\s*([0-9]+\.[0-9]+\.[0-9]+)\.\s*$",
    "dashboard/manifest.json": r"\"version\":\s*\"([0-9]+\.[0-9]+\.[0-9]+)\"",
    "__init__.py": r"^_VERSION_FALLBACK\s*=\s*\"([0-9]+\.[0-9]+\.[0-9]+)\"\s*$",
}


def _read_marker(rel):
    pattern = re.compile(MARKERS[rel], re.M)
    m = pattern.search((ROOT / rel).read_text(encoding="utf-8"))
    return m.group(1) if m else None


class TestEveryVersionMarkerAgrees(unittest.TestCase):
    """plugin.yaml is the authority (`CHANGELOG.md` says so in its header)."""

    def test_plugin_yaml_declares_a_parseable_version(self):
        v = _read_marker("plugin.yaml")
        self.assertIsNotNone(v, "plugin.yaml has no parseable `version:`")
        self.assertRegex(v, r"^\d+\.\d+\.\d+$")

    def test_all_five_markers_agree_with_plugin_yaml(self):
        expected = _read_marker("plugin.yaml")
        found = {rel: _read_marker(rel) for rel in MARKERS}
        disagree = {k: v for k, v in found.items() if v != expected}
        self.assertEqual(disagree, {}, (
            "version markers disagree with plugin.yaml ({}): {}. A release whose "
            "packaging metadata names a different version than its manifest is "
            "not a release.".format(expected, disagree)))

    def test_the_declared_version_has_a_changelog_heading(self):
        """The fourth thing the review found: no `## 5.7.0` heading at all."""
        version = _read_marker("plugin.yaml")
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("\n## %s\n" % version, text, (
            "CHANGELOG.md has no `## {}` heading. Either name the section or "
            "the release is still unreleased.".format(version)))

    def test_nothing_is_still_parked_under_unreleased(self):
        """`## Unreleased` above a named version means the heading was added
        without moving the content under it."""
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertNotIn("\n## Unreleased\n", text)

    def test_the_changelog_title_is_the_first_heading(self):
        """A `## 5.4.0` section sat ABOVE the `# Changelog` title, so the file's
        own header was not its header."""
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        headings = re.findall(r"^#{1,2} .*$", text, re.M)
        self.assertTrue(headings)
        self.assertEqual(headings[0], "# Changelog")

    def test_the_manifest_json_is_valid_json(self):
        json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))

    def test_no_marker_is_unlisted(self):
        """MARKERS must stay complete: accept_m4.py checks four of these files
        and this module checks five (it added __init__._VERSION_FALLBACK, which
        accept_m4 compares but the review's list omitted). If a new packaging
        file starts declaring a version, it belongs in both."""
        for rel in MARKERS:
            self.assertTrue((ROOT / rel).exists(), rel)
            self.assertIsNotNone(_read_marker(rel),
                                 "%s no longer matches its marker pattern" % rel)


class TestTheAcceptanceScriptRuns(unittest.TestCase):
    """The wire. accept_m4.py is the deep check; this makes it a gate."""

    def test_accept_m4_exits_zero(self):
        script = ROOT / "tests" / "exercise" / "accept_m4.py"
        self.assertTrue(script.exists(), "accept_m4.py is gone; so is this gate")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              env=env, timeout=300)
        out = proc.stdout.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, (
            "tests/exercise/accept_m4.py failed (exit {}). It is the tree's own "
            "version-unification acceptance script; its output follows.\n\n{}"
            .format(proc.returncode, out[-4000:])))
        self.assertIn("ALL CHECKS PASS", out)


if __name__ == "__main__":
    unittest.main()
