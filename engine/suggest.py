"""Skill-suggestion router integration (advisory, fail-open).

An external skill-selection router (in production, a stdio MCP server) can
rank the agent's installed skill roster against the user's message and name
the one most likely to apply. Chronicle does not ship or run that router --
it is configured by filesystem path (`suggest.module_path`) and is entirely
optional (`suggest.enabled`, default False). When configured, `suggest()` is
Chronicle's only contact with it: one call, off the happy path, that can only
ever ADD one advisory line to the turn's prefetch text (see
`provider.prefetch`) -- never withhold or delay it.

Why a worker thread + join instead of a plain call: the router this was built
against defaults its own remote ranking call to a 30-90s timeout -- far
longer than a turn should ever wait for a "consider this skill" hint.
Running it on a background thread and joining with `suggest.budget_ms` means
a slow or hung router adds AT MOST that many milliseconds to the turn; the
thread is daemonized and left running, and whatever it eventually returns is
discarded.
"""
from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("chronicle.suggest")

# One warning per process, not one per turn -- a misconfigured or unreachable
# router would otherwise log on every single prefetch.
_WARNED = False

# Loaded router modules, keyed by their configured path, so a configured
# router is imported once per process rather than re-parsed on every turn.
_MODULE_CACHE: dict[str, Any] = {}


def _warn_once(msg: str, *args: Any) -> None:
    global _WARNED
    if not _WARNED:
        logger.warning(msg, *args)
        _WARNED = True


def _load_router_module(module_path: str) -> Any:
    """Import the router from a filesystem path.

    The router lives outside this package (an ops/ script, or an external
    skill's directory) rather than being installed as a Python package, so it
    is loaded by path with importlib rather than by dotted module name.
    """
    cached = _MODULE_CACHE.get(module_path)
    if cached is not None:
        return cached
    p = Path(module_path).expanduser()
    spec = importlib.util.spec_from_file_location(f"chronicle_suggest_router_{p.stem}", p)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load router module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE_CACHE[module_path] = module
    return module


def _extract_names(result: Any) -> list:
    """Normalize whatever shape the router returned into a list of names.

    Covers the reference router's two return shapes -- `{"suggestion": (...)}`
    from its local-fallback wrapper, and `{"ranked": [(name, score), ...]}`
    from its bare, remote-only `rank_wide` -- plus a bare name or a plain
    list of names, so a simpler router does not need to match either shape.
    """
    if not result:
        return []
    if isinstance(result, str):
        return [result]
    if isinstance(result, dict):
        suggestion = result.get("suggestion")
        if suggestion:
            return [n for n in suggestion if n]
        ranked = result.get("ranked")
        if ranked:
            top = ranked[0]
            name = top[0] if isinstance(top, (list, tuple)) else top
            return [name] if name else []
        return []
    if isinstance(result, (list, tuple)):
        names = []
        for item in result:
            if isinstance(item, (list, tuple)) and item:
                names.append(item[0])
            elif isinstance(item, str):
                names.append(item)
        return names
    return []


def _call_router(module: Any, query: str, budget_ms: int) -> Any:
    """Invoke whichever entry point the router module exposes.

    Prefers a local-fallback-capable entry point (the reference router's
    `suggest_with_local_fallback`, which tries the remote call and degrades
    to its own offline classifier) over the bare `rank_wide` ranking call,
    which is remote-only and returns nothing useful once that call fails.
    Either way this runs inside the caller's worker thread, under the same
    budget passed through as the router's own request timeout.
    """
    local_fallback = getattr(module, "suggest_with_local_fallback", None)
    if callable(local_fallback):
        return local_fallback(query)
    rank_wide = getattr(module, "rank_wide", None)
    if callable(rank_wide):
        load_roster = getattr(module, "_load_roster", None)
        roster = load_roster() if callable(load_roster) else []
        return rank_wide(query, roster, timeout=budget_ms / 1000.0)
    raise AttributeError(
        "router module exposes neither suggest_with_local_fallback nor rank_wide")


def suggest(query: str, cfg: Any) -> list:
    """At most a few skill names the router thinks apply to `query`, or [].

    Fails open on every path -- disabled, unconfigured, import error, a
    raised exception, or a call that outran `suggest.budget_ms` -- because
    this is advisory only (`provider.prefetch` prepends one line when the
    result is non-empty) and must never be able to block or break a turn.
    """
    if not cfg.get("suggest.enabled", False):
        return []
    module_path = str(cfg.get("suggest.module_path", "") or "")
    if not module_path:
        return []
    budget_ms = int(cfg.get("suggest.budget_ms", 800))

    outcome: dict[str, Any] = {}

    def _run() -> None:
        try:
            module = _load_router_module(module_path)
            outcome["result"] = _call_router(module, query, budget_ms)
        except Exception as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(budget_ms / 1000.0)

    if thread.is_alive():
        # Still running past budget (e.g. blocked in the router's own remote
        # HTTP call). Stop waiting -- the thread is a daemon and will not
        # hold the process open -- and never use its result if it lands late.
        _warn_once("chronicle.suggest: router timed out after %dms (module=%s)",
                   budget_ms, module_path)
        return []

    if "error" in outcome:
        _warn_once("chronicle.suggest: router failed: %s", outcome["error"])
        return []

    try:
        return _extract_names(outcome.get("result"))
    except Exception as exc:
        _warn_once("chronicle.suggest: router returned an unusable result: %s", exc)
        return []
