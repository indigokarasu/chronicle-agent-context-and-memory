"""
Chronicle — reading YAML in whatever Python the host runs.

The host never hands a memory provider its config, so Chronicle reads the
profile's `config.yaml` itself. That read used `import yaml` (PyYAML), and a
fresh package-managed host install does not have PyYAML: it depends on
`ruamel.yaml` instead. The import failed, the failure was swallowed, and the
whole `memory:` section was ignored without a word, so Chronicle ran on its
defaults (a different store, embeddings off) while the config said otherwise.

Every YAML read in the engine, the dashboard and the scripts goes through here:
PyYAML when it is importable, else ruamel.yaml's pure-Python safe loader, else
`YamlUnavailable`, which says plainly that nothing could parse the file. This
module imports nothing from the plugin, so the dashboard can load it by path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["YamlUnavailable", "safe_load_text", "safe_load_file", "parser_name"]

_MISSING = ("PyYAML is not installed for this Python, and neither is ruamel.yaml; "
            "no YAML file can be read")


class YamlUnavailable(ImportError):
    """Neither PyYAML nor ruamel.yaml can be imported in this Python.

    An ImportError, so a caller that already treated "PyYAML is missing" as an
    ImportError keeps working; a caller that must not run on silent defaults
    catches this one by name and says so.
    """


def _pyyaml():
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    return yaml if callable(getattr(yaml, "safe_load", None)) else None


def _ruamel_class():
    try:
        from ruamel.yaml import YAML  # type: ignore
    except ImportError:
        return None
    return YAML


def parser_name() -> str:
    """Which parser a load would use now: "pyyaml", "ruamel" or "" (none)."""
    if _pyyaml() is not None:
        return "pyyaml"
    if _ruamel_class() is not None:
        return "ruamel"
    return ""


def _plain(value: Any) -> Any:
    """ruamel's result as the plain types PyYAML gives.

    Its safe loader already builds dict, list and plain scalars, but other
    ruamel loaders (and other releases) build subclasses: CommentedMap,
    CommentedSeq, ScalarInt, and ScalarBoolean, which is an int and not a bool,
    so a `flag is True` check would read a configured `true` as off. Making
    every value plain keeps the two parsers' results equal, type for type.
    """
    if isinstance(value, Mapping):
        return {_plain(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if type(value).__name__ == "ScalarBoolean":
        return bool(value)
    for base in (str, int, float):
        if isinstance(value, base) and type(value) is not base:
            return base(value)
    return value


def _ruamel_load(YAML, text: str) -> Any:
    loader = YAML(typ="safe", pure=True)
    # PyYAML reads YAML 1.1, where `yes`/`no`/`on`/`off` are booleans; ruamel
    # defaults to 1.2, where they are strings. A config written for (and
    # read by) PyYAML must mean the same thing here, so read it as 1.1.
    # One known difference is kept on purpose: a key repeated in one mapping
    # is an error here (PyYAML silently keeps the last value), which the
    # callers report rather than run on a value nobody chose.
    try:
        loader.version = (1, 1)
    except Exception:
        pass
    return _plain(loader.load(text))


def safe_load_text(text: str) -> Any:
    """Parse one YAML document, as `yaml.safe_load(text)` would.

    Raises YamlUnavailable when no parser is importable, and the parser's own
    error when the text is not valid YAML.
    """
    yaml = _pyyaml()
    if yaml is not None:
        return yaml.safe_load(text)
    YAML = _ruamel_class()
    if YAML is not None:
        return _ruamel_load(YAML, text)
    raise YamlUnavailable(_MISSING)


def safe_load_file(path) -> Any:
    """Parse the YAML file at `path` (str or Path), as `safe_load_text` does.

    The parser is looked up before the file is opened, so a missing parser is
    reported as that, not as whatever the file read would have raised.
    """
    if _pyyaml() is None and _ruamel_class() is None:
        raise YamlUnavailable(_MISSING)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return safe_load_text(text)
