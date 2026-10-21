"""
Chronicle — reading config.yaml with PyYAML, with ruamel.yaml, or with neither.

The host never passes a memory provider its config, so Chronicle reads the
profile's `config.yaml` itself. A fresh package-managed host install has
ruamel.yaml (a hard dependency of the host) and no PyYAML; the read used
`import yaml`, the ImportError was swallowed, and Chronicle ran on its defaults
while the config named another store. These tests cover each parser situation:

- PyYAML present: it is used.
- PyYAML absent, ruamel.yaml present: a stand-in ruamel module (the system
  Python the suite runs under may not have the real one) is used, its results
  are plain dict/list/scalars, and a representative `memory:` section reads
  back equal, type for type, to what PyYAML gives.
- Neither: `YamlUnavailable`, and the core says so at WARNING once and runs on
  its defaults instead of saying nothing.

When the real ruamel.yaml is importable, one more test checks it against
PyYAML directly, including the YAML 1.1 booleans PyYAML reads.
"""

import logging
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))


from _dashboard_loader import _load
from _tmp_support import temp_home

from engine import yaml_load
from engine.core import ChronicleCore
from engine.embeddings import NullProbe
from engine.paths import DB_REL

try:
    import yaml as _pyyaml  # hidden per test below; the stand-in ruamel parses with it
except ImportError:  # CI installs only pytest and the package: no PyYAML there
    _pyyaml = None
_NEEDS_PYYAML = unittest.skipIf(_pyyaml is None, "PyYAML is not installed for this Python")

_ROOT = Path(__file__).parent.parent

# A `memory:` section shaped like a real profile's: nested maps, lists, ints,
# floats, bools (including YAML 1.1 spellings), nulls and `${VAR}` references.
# Every value is a placeholder.
CONFIG = """\
model: placeholder/model
memory:
  provider: chronicle
  db_path: ~/.hermes/commons/db/chronicle/custom.db
  memory_enabled: false
  user_profile_enabled: yes
  embeddings:
    model: placeholder-embed
    dimensions: 768
    base_url: http://127.0.0.1:8080/v1
    api_key: ${CHRONICLE_TEST_PLACEHOLDER_KEY}
    allow_remote: true
    task_prefixes: {query: "search_query: ", document: "search_document: "}
  retrieval:
    k: 12
    weights: [0.5, 0.25, 0.25]
    off_switch: off
  git:
    enabled: true
    max_flush_batches: 4
    remote: null
  principals:
    agents:
      - id: helper
        default_visibility: shared
      - id: other
context:
  engine: chronicle
"""


# -- a stand-in for ruamel.yaml ------------------------------------------------
#
# It parses with PyYAML (captured above, before any test hides it) and then
# hands back the subclasses ruamel's other loaders build, so the test shows the
# loader turns them into plain types. A ScalarBoolean is an int, not a bool:
# left as it is, `cfg.get("git.enabled") is True` would be False.

class CommentedMap(dict):
    pass


class CommentedSeq(list):
    pass


class ScalarBoolean(int):
    pass


class ScalarInt(int):
    pass


class ScalarFloat(float):
    pass


class PlainScalarString(str):
    pass


def _ruamelish(value):
    if isinstance(value, dict):
        return CommentedMap((_ruamelish(k), _ruamelish(v)) for k, v in value.items())
    if isinstance(value, list):
        return CommentedSeq(_ruamelish(v) for v in value)
    if isinstance(value, bool):
        return ScalarBoolean(value)
    if isinstance(value, int):
        return ScalarInt(value)
    if isinstance(value, float):
        return ScalarFloat(value)
    if isinstance(value, str):
        return PlainScalarString(value)
    return value


def _stub_ruamel():
    """`ruamel` and `ruamel.yaml` modules whose YAML class records how it was made."""
    made = []

    class YAML:
        def __init__(self, typ=None, pure=False):
            self.typ, self.pure, self.version = typ, pure, None
            made.append(self)

        def load(self, text):
            return _ruamelish(_pyyaml.safe_load(text))

    pkg = types.ModuleType("ruamel")
    pkg.__path__ = []
    mod = types.ModuleType("ruamel.yaml")
    mod.YAML = YAML
    pkg.yaml = mod
    return {"ruamel": pkg, "ruamel.yaml": mod}, made


def _only_ruamel():
    modules, made = _stub_ruamel()
    modules["yaml"] = None
    return mock.patch.dict(sys.modules, modules), made


def _no_parser():
    return mock.patch.dict(sys.modules, {"yaml": None, "ruamel": None, "ruamel.yaml": None})


def _shape(value):
    """`value` with every type spelled out, so True and 1 do not compare equal."""
    if isinstance(value, dict):
        return ("dict", tuple(sorted((_shape(k), _shape(v)) for k, v in value.items())))
    if isinstance(value, list):
        return ("list", tuple(_shape(v) for v in value))
    return (type(value).__name__, repr(value))


def _real_ruamel():
    try:
        from ruamel.yaml import YAML  # noqa: F401
        return True
    except ImportError:
        return False


class _Home(unittest.TestCase):
    def setUp(self):
        self.home = os.path.realpath(temp_home(prefix="yaml-load-"))
        self.config = os.path.join(self.home, "config.yaml")
        with open(self.config, "w", encoding="utf-8") as fh:
            fh.write(CONFIG)


@_NEEDS_PYYAML
class TestPyYamlPresent(_Home):
    def test_pyyaml_is_used_and_reads_like_safe_load(self):
        self.assertEqual(yaml_load.parser_name(), "pyyaml")
        self.assertEqual(yaml_load.safe_load_text(CONFIG), _pyyaml.safe_load(CONFIG))
        self.assertEqual(yaml_load.safe_load_file(self.config), _pyyaml.safe_load(CONFIG))
        self.assertEqual(yaml_load.safe_load_file(Path(self.config)), _pyyaml.safe_load(CONFIG))

    def test_pyyaml_is_preferred_over_ruamel(self):
        modules, made = _stub_ruamel()
        with mock.patch.dict(sys.modules, modules):
            self.assertEqual(yaml_load.parser_name(), "pyyaml")
            yaml_load.safe_load_text(CONFIG)
        self.assertEqual(made, [])

    def test_invalid_yaml_raises_the_parsers_error(self):
        with self.assertRaises(_pyyaml.YAMLError):
            yaml_load.safe_load_text("memory: [unclosed\n")

    def test_an_empty_document_is_none(self):
        self.assertIsNone(yaml_load.safe_load_text(""))


@_NEEDS_PYYAML
class TestRuamelOnly(_Home):
    def test_ruamel_is_used_with_the_safe_pure_loader_reading_yaml_1_1(self):
        patch, made = _only_ruamel()
        with patch:
            self.assertEqual(yaml_load.parser_name(), "ruamel")
            yaml_load.safe_load_text(CONFIG)
        self.assertEqual(len(made), 1)
        self.assertEqual((made[0].typ, made[0].pure, made[0].version), ("safe", True, (1, 1)))

    def test_the_result_is_plain_and_equal_to_pyyaml_type_for_type(self):
        want = _pyyaml.safe_load(CONFIG)
        patch, _ = _only_ruamel()
        with patch:
            got = yaml_load.safe_load_file(self.config)
        self.assertEqual(_shape(got), _shape(want))
        self.assertIs(got["memory"]["git"]["enabled"], True)
        self.assertIs(got["memory"]["user_profile_enabled"], True)
        self.assertIs(type(got["memory"]), dict)
        self.assertIs(type(got["memory"]["principals"]["agents"]), list)

    def test_the_core_reads_the_same_memory_section_through_ruamel(self):
        env = {"CHRONICLE_TEST_PLACEHOLDER_KEY": "placeholder-value"}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("CHRONICLE_EMBED_API_KEY", None)
            want = ChronicleCore._load_memory_config(self.home)
            patch, made = _only_ruamel()
            with patch:
                got = ChronicleCore._load_memory_config(self.home)
        self.assertEqual(len(made), 1)
        self.assertEqual(_shape(got), _shape(want))
        self.assertEqual(got["embeddings"]["api_key"], "placeholder-value")
        self.assertEqual(got["db_path"], "~/.hermes/commons/db/chronicle/custom.db")

    def test_the_dashboard_finds_the_configured_store_through_ruamel(self):
        custom = os.path.join(self.home, "custom", "chronicle.db")
        os.makedirs(os.path.dirname(custom))
        open(custom, "wb").close()
        with open(self.config, "w", encoding="utf-8") as fh:
            fh.write("memory:\n  db_path: %s\n" % custom)
        default = os.path.join(self.home, DB_REL)
        os.makedirs(os.path.dirname(default))
        open(default, "wb").close()
        host = types.ModuleType("hermes_constants")
        host.get_hermes_home = lambda: Path(self.home)
        with mock.patch.dict(sys.modules, {"hermes_constants": host}):
            mod = _load("yaml_load_plugin_api", _ROOT / "dashboard" / "plugin_api.py")
            patch, made = _only_ruamel()
            with patch:
                found = mod._get_db_path(None)
        self.assertEqual(len(made), 1)
        self.assertEqual(found, Path(custom))


class TestNoParser(_Home):
    def test_both_absent_raises_yaml_unavailable(self):
        with _no_parser():
            self.assertEqual(yaml_load.parser_name(), "")
            with self.assertRaises(yaml_load.YamlUnavailable) as cm:
                yaml_load.safe_load_text(CONFIG)
            # Before the file is opened: a missing parser is reported as that.
            with self.assertRaises(yaml_load.YamlUnavailable):
                yaml_load.safe_load_file(os.path.join(self.home, "missing.yaml"))
        self.assertIsInstance(cm.exception, ImportError)
        self.assertIn("PyYAML", str(cm.exception))
        self.assertIn("ruamel.yaml", str(cm.exception))

    def test_the_core_warns_once_and_runs_on_its_defaults(self):
        records = []

        class _Keep(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _Keep(logging.DEBUG)
        log = logging.getLogger("chronicle")
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        with _no_parser():
            core = ChronicleCore.get(self.home, embedder_probe=NullProbe())
        self.addCleanup(core.close)
        # Every warning about the config file (other warnings, such as the
        # defaults' own dormant flags, are not this test's business).
        warned = [r for r in records
                  if r.levelno >= logging.WARNING and "config.yaml" in r.getMessage()]
        self.assertEqual(len(warned), 1, [r.getMessage() for r in warned])
        msg = warned[0].getMessage()
        self.assertEqual(warned[0].name, "chronicle.core")
        self.assertIn("cannot read %s" % self.config, msg)
        self.assertIn("no YAML parser in this Python", msg)
        self.assertIn("running on its defaults", msg)
        # The defaults, not the configured store.
        self.assertEqual(core.store.db_path, os.path.join(self.home, DB_REL))
        self.assertFalse(os.path.exists(os.path.join(self.home, "commons", "db", "chronicle",
                                                     "custom.db")))


@_NEEDS_PYYAML
@unittest.skipUnless(_real_ruamel(), "ruamel.yaml is not installed for this Python")
class TestRealRuamel(_Home):
    def test_real_ruamel_reads_the_profile_config_as_pyyaml_does(self):
        want = _pyyaml.safe_load(CONFIG)
        with mock.patch.dict(sys.modules, {"yaml": None}):
            self.assertEqual(yaml_load.parser_name(), "ruamel")
            got = yaml_load.safe_load_file(self.config)
        self.assertEqual(_shape(got), _shape(want))
        self.assertIs(got["memory"]["retrieval"]["off_switch"], False)


if __name__ == "__main__":
    unittest.main()
