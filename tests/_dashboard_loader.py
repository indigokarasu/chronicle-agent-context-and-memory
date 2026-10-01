"""Load a dashboard module by path the way the Hermes dashboard host does."""

import importlib.util
import sys
import types

_MISSING = object()


def _load(name, path, routes=None):
    """Load a dashboard module by path, the way the dashboard host does.

    With `routes`, a recording fastapi stub is installed for the duration of the
    load whatever is already in sys.modules (a real fastapi, or another test's
    stub), and the previous module is restored afterwards; so route recording
    works in every collection order and on a machine that has fastapi. Without
    `routes`, a stub is installed only if fastapi is absent."""
    prev = sys.modules.get("fastapi", _MISSING)
    install = routes is not None or prev is _MISSING
    if install:
        stub = types.ModuleType("fastapi")

        class _Router:
            def get(self, p, *a, **k):
                if routes is not None:
                    routes.append(("GET", p))
                return lambda fn: fn

            def post(self, p, *a, **k):
                if routes is not None:
                    routes.append(("POST", p))
                return lambda fn: fn

        stub.APIRouter = _Router
        stub.Query = lambda default=None, **k: default
        sys.modules["fastapi"] = stub
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if install:
            if prev is _MISSING:
                sys.modules.pop("fastapi", None)
            else:
                sys.modules["fastapi"] = prev
    return mod
