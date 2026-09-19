"""
Chronicle — public functions carry type hints (AGENTS.md: "Use type hints for
public methods and functions. PEP 561 compliance is enforced via py.typed").

Checked for the modules the memory-injection work touched, at module level:
every parameter and the return of a function whose name has no leading
underscore.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
MODULES = ("engine/speaker.py", "engine/substance.py", "engine/retrieval.py",
           "dashboard/tapestry_api.py")


class TestPublicFunctionsAreAnnotated(unittest.TestCase):
    def test_every_parameter_and_return(self):
        missing = []
        for rel in MODULES:
            for node in ast.parse((ROOT / rel).read_text()).body:
                if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                    continue
                args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                bare = [a.arg for a in args if a.annotation is None]
                if bare or node.returns is None:
                    missing.append("%s:%d %s %s%s" % (rel, node.lineno, node.name, bare,
                                                      "" if node.returns else " -> ?"))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
