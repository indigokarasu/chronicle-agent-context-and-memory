"""
Chronicle — the dashboard plugin ships a UI, and that UI only calls routes that exist.

Two production defects this pins:

  * `dashboard/manifest.json` named `dist/index.js` as its entry while the repo
    held no `dist/` at all (it was gitignored and deployed by hand), so a
    deploy from the repo left the Chronicle tab with nothing to load;
  * the hand-deployed bundle kept POSTing `/process-embeddings` after A13
    renamed that route to `/enqueue-extractions`, so its one button failed.

The UI is built from `dashboard/web/src` into `dashboard/dist` (see
`dashboard/web/build.mjs`). These tests read the SOURCE for every
`API + "/…"` call and require each path to be a route `plugin_api.py` declares
when loaded the way the dashboard host loads it, and require the built bundles
to contain the same literals, so a source change that was never rebuilt fails
here instead of in the browser.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_dashboard_tapestry import _load  # the by-path loader with the fastapi stub

DASH = Path(__file__).parent.parent / "dashboard"
_CALL = re.compile(r'API \+ "(/[a-z0-9/_-]+)')


def _declared_routes():
    routes = []
    _load("chronicle_plugin_api_bundle", DASH / "plugin_api.py", routes)
    return {p for _m, p in routes}


class TestManifestPointsAtRealFiles(unittest.TestCase):
    def test_entry_and_css_exist(self):
        manifest = json.loads((DASH / "manifest.json").read_text(encoding="utf-8"))
        for key in ("entry", "css", "api"):
            if manifest.get(key):
                self.assertTrue((DASH / manifest[key]).is_file(),
                                "manifest %s %r does not exist in the plugin" % (key, manifest[key]))

    def test_the_lazy_tapestry_bundle_exists(self):
        self.assertTrue((DASH / "dist" / "tapestry.js").is_file())


class TestUiCallsOnlyDeclaredRoutes(unittest.TestCase):
    def _calls(self):
        calls = set()
        for f in (DASH / "web" / "src").rglob("*.js"):
            calls |= set(_CALL.findall(f.read_text(encoding="utf-8")))
        return calls

    def test_every_call_is_a_declared_route(self):
        declared = _declared_routes()
        calls = self._calls()
        self.assertIn("/tapestry/log/events", calls, "source scan found no Tapestry calls")
        self.assertEqual(sorted(calls - declared), [], "UI calls routes plugin_api does not declare")

    def test_the_built_bundles_carry_the_same_calls(self):
        built = (DASH / "dist" / "index.js").read_text(encoding="utf-8") + \
            (DASH / "dist" / "tapestry.js").read_text(encoding="utf-8")
        for path in self._calls():
            # assertTrue, not assertIn: a failing assertIn prints the whole bundle
            self.assertTrue('"%s' % path in built, "dist is stale: %s is not in the built bundles" % path)
        self.assertFalse("process-embeddings" in built, "a bundle still calls /process-embeddings")


if __name__ == "__main__":
    unittest.main()
