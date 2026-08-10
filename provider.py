"""
Chronicle — Memory Provider plugin (Hermes memory-provider slot).

Long-term memory: capture + recall. Subclasses `agent.memory_provider.MemoryProvider`
and delegates to the shared `ChronicleCore`. `sync_turn` is the non-blocking
durability anchor; `on_pre_compress` yields to the Context Engine when it is
active. Registered via `register(ctx)` in this package's `__init__.py`.

Imports are dual-mode: relative when loaded as a plugin package (the Hermes
loader registers a synthetic parent package), absolute when imported top-level
for local development and tests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

try:  # real Hermes base when present …
    from agent.memory_provider import MemoryProvider  # type: ignore
except Exception:  # … else a local stand-in (plugin-package or top-level)
    try:
        from ._base import MemoryProvider
    except Exception:  # pragma: no cover
        from _base import MemoryProvider

logger = logging.getLogger("chronicle.provider")


def _load_core():
    try:
        from .engine.core import ChronicleCore  # plugin-package context
    except Exception:
        from engine.core import ChronicleCore  # top-level (dev/tests)
    return ChronicleCore


def _op_markers():
    """The reducer's own operational-exhaust markers (§issue-7.1): reused rather
    than re-invented, so a tool result that would never be promoted out of an
    `observed` span is held to the exact same bar here, before it ever becomes a
    reference belief."""
    try:
        from .engine.reducer import _OP_MARKERS  # plugin-package context
    except Exception:
        from engine.reducer import _OP_MARKERS  # top-level (dev/tests)
    return _OP_MARKERS


# Tool names treated as "retrieval-ish" for automatic reference capture
# (issue #7.1): matched case-insensitively against post_tool_call's tool_name.
# Chronicle doesn't own the gateway's tool-naming, so this is deliberately a
# short, common-spelling allowlist, overridable via capture.tool_reference.allowlist.
# Chronicle's OWN tools (chronicle_*) are excluded unconditionally below — never
# by name here — so this list can't accidentally re-capture Chronicle's own writes.
_DEFAULT_RETRIEVAL_TOOLS = ("web_fetch", "webfetch", "fetch",
                           "web_search", "websearch",
                           "file_read", "read_file", "readfile", "read")

_DEFAULT_REFERENCE_TTL_DAYS = 30
_REFERENCE_SUMMARY_CAP = 2000  # cached_summary is a pointer + gist, not a mirror


def _tool_result_text(result) -> str:
    """Coerce a tool result of unknown shape (str / dict / list / other) into text."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        for key in ("text", "content", "summary", "body", "output"):
            v = result.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        try:
            return json.dumps(result, default=str).strip()
        except Exception:
            return str(result).strip()
    if isinstance(result, (list, tuple)):
        return "\n".join(t for t in (_tool_result_text(x) for x in result) if t)
    return str(result).strip()


def _looks_operational(text: str) -> bool:
    """True when `text` matches the reducer's run-log/dispatch-exhaust markers."""
    head = (text or "")[:400]
    if head.lstrip().lower().startswith("tool:"):
        return True
    return any(marker in head for marker in _op_markers())


def _summarize_tool_history(history) -> str:
    """`tool_call_history` (list of dicts or names) -> a compact "name×count,
    ..." summary, most-frequent order preserved as first-seen. Never raises on
    an unexpected shape — worst case every entry stringifies to itself."""
    if not history:
        return ""
    counts: dict = {}
    for entry in history:
        if isinstance(entry, dict):
            name = entry.get("tool") or entry.get("name") or entry.get("tool_name") or "?"
        else:
            name = entry
        name = str(name)
        counts[name] = counts.get(name, 0) + 1
    return ", ".join(f"{name}×{n}" if n > 1 else name for name, n in counts.items())


class ChronicleMemoryProvider(MemoryProvider):
    name = "chronicle"

    def __init__(self):
        self.core = None
        self.scope = None
        self._session_id = ""
        self._principal_id = "default"

    # -- lifecycle ---------------------------------------------------------

    def is_available(self) -> bool:
        return self.core.local_ok() if self.core else True  # no network

    def initialize(self, session_id, *, hermes_home=None, principal_id="default", config=None, **kw):
        ChronicleCore = _load_core()
        hermes_home = hermes_home or str(Path.home() / ".hermes")
        self.core = ChronicleCore.get(hermes_home, config)
        self.core.has_memory_provider = True
        self._session_id = session_id
        self._principal_id = principal_id
        self.scope = self.core.initialize(session_id, hermes_home=hermes_home, principal_id=principal_id)
        logger.info("Chronicle MemoryProvider ready (session %s, principal %s)", session_id, principal_id)

    def shutdown(self):
        if self.core:
            self.core.capture.flush_best_effort()
            self.core.flush_git()

    # -- config (setup wizard) --------------------------------------------

    def get_config_schema(self):
        return [
            {"key": "db_path", "description": "SQLite database location",
             "default": "~/.hermes/commons/db/chronicle/chronicle.db", "secret": False, "required": False},
            {"key": "git_repo", "description": "Git mirror directory for the event log",
             "default": "~/.hermes/commons/db/chronicle/git", "secret": False, "required": False},
            {"key": "embeddings_model",
             "description": "'auto' detects a running local OpenAI-compatible server (LM Studio :1234, "
                            "Ollama :11434, llama.cpp :8080) and uses whatever embedding model it serves — "
                            "no model id assumed. Or pin a specific model id. If none is reachable it runs "
                            "degraded — no vectors written, embeds queued and retried — rather than "
                            "silently hashing; set 'hashing' to choose the offline embedder.",
             "default": "auto", "secret": False, "required": False},
            {"key": "embeddings_base_url",
             "description": "Embeddings endpoint base URL (e.g. http://localhost:1234/v1). Leave blank to "
                            "auto-detect a local server or use $CHRONICLE_EMBED_BASE_URL.",
             "default": "", "secret": False, "required": False},
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        cfg_path = Path(hermes_home) / "chronicle.json"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(values, indent=2))

    # -- capture -----------------------------------------------------------

    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None):
        if self.core:  # MUST be non-blocking — one local append, no network
            self.core.capture.observe(user_content, assistant_content,
                                      session_id=session_id or self._session_id, messages=messages)

    def on_pre_compress(self, messages) -> str:
        if not self.core:
            return ""
        if self.core.has_context_engine:
            return ""  # the Context Engine owns compression when active
        _, summary = self.core.capture.rescue(messages, session_id=self._session_id)
        return summary

    def on_session_end(self, messages):
        if self.core:
            self.core.capture.finalize_session(self._session_id, "clean_exit")

    def on_memory_write(self, action, target, content, metadata=None):
        if self.core:
            self.core.capture.agent_explicit(action, target, content, metadata)
            self.core.tick()

    def post_tool_call(self, tool_name, args=None, result=None, *, session_id="", **kw):
        """Gateway hook (issue #7.1): after ANY tool call completes, allowlisted
        retrieval-ish tools (web fetch/search, file read) get their result
        written as a reference-kind belief (topic, retrieval_url, cached_summary,
        ttl_days) through the normal assert path — the exact same
        `capture.append("asserted", ...)` `chronicle_remember` itself uses. Turns
        the previously designed-but-dead `refs` table into a working
        external-knowledge cache instead of a second copy of `chronicle_remember`.

        Guarded three ways: (1) an explicit allowlist — everything else, INCLUDING
        Chronicle's own `chronicle_*` tools, passes through untouched, so this can
        never recursively capture Chronicle's own writes; (2) a failed call (an
        `error`/`success=False` kwarg, if the host supplies one) is skipped — a
        failure has nothing worth caching; (3) the operational guard — content
        matching the reducer's own run-log/dispatch-exhaust markers is never
        promoted, same bar as ordinary observed spans.
        """
        if not self.core or not tool_name:
            return
        name = str(tool_name).strip()
        if not name or name.lower().startswith("chronicle"):
            return  # never re-capture Chronicle's own tool surface
        allowlist = {str(t).strip().lower() for t in
                    self.core.cfg.get("capture.tool_reference.allowlist", _DEFAULT_RETRIEVAL_TOOLS)}
        if name.lower() not in allowlist:
            return
        if kw.get("error") or kw.get("success") is False:
            return  # a failed call has nothing worth caching
        summary = _tool_result_text(result)[:_REFERENCE_SUMMARY_CAP]
        if not summary or _looks_operational(summary):
            return  # nothing to cache, or run-log/operational exhaust (§_is_operational parity)

        args = args if isinstance(args, dict) else {}
        topic = str(args.get("topic") or args.get("query") or args.get("q") or args.get("url")
                    or args.get("path") or args.get("file_path") or name)[:200]
        retrieval_url = args.get("url") or args.get("uri")
        if not retrieval_url:
            path = args.get("path") or args.get("file_path")
            if path:
                retrieval_url = f"file://{path}"
        ttl_days = self.core.cfg.get("capture.tool_reference.ttl_days", _DEFAULT_REFERENCE_TTL_DAYS)

        payload = {
            "kind": "reference",
            "key": {"topic": topic, "retrieval_url": retrieval_url, "ttl_days": ttl_days},
            "body": summary,
            "source_event": f"post_tool_call:{name}",  # stable per (tool, topic): a re-fetch
                                                        # refreshes the SAME belief_id/row instead
                                                        # of piling up duplicates (mirrors
                                                        # tools.py's _t_remember non-fact convention)
            "source_type": "web_retrieval",
        }
        self.core.capture.append("asserted", payload, actor="agent", owner=self._principal_id,
                                 trust_level=2, session_id=session_id or self._session_id or None)

    def on_delegation(self, task, result, *, child_session_id="", **kw):
        if self.core:
            self.core.capture.delegation(task, result, child_session_id=child_session_id)

    def subagent_stop(self, task="", result="", *, child_session_id="", child_status="",
                      tool_call_history=None, duration_ms=None, **kw):
        """Gateway hook (issue #7.2): richer delegation episode capture.

        `on_delegation` only ever sees (task, result) strings. `subagent_stop`
        carries the child's terminal status, its tool-call history, and wall-clock
        duration — this folds all of that into ONE observed delegation episode
        (status + duration as qualifiers, tool names summarized) instead of the
        bare "Task/Result" excerpt, for better episodic recall of what a child
        agent actually did. Independent of `on_delegation` (same `observed`
        capture mechanism, just a richer payload) — hosts that only fire the
        plain hook are unaffected.
        """
        if not self.core:
            return
        task = task or kw.get("task") or kw.get("prompt") or ""
        result = result or kw.get("output") or kw.get("summary") or ""
        tools_used = _summarize_tool_history(tool_call_history)

        lines = [f"Task: {task}", f"Result: {result}"]
        if child_status:
            lines.append(f"Status: {child_status}")
        if duration_ms is not None:
            lines.append(f"Duration: {duration_ms}ms")
        if tools_used:
            lines.append(f"Tools used: {tools_used}")

        payload = {
            "source_type": "delegation", "excerpt": "\n".join(lines),
            "task": task, "result": result, "child_session_id": child_session_id,
            "child_status": child_status, "duration_ms": duration_ms,
            "tool_call_count": len(tool_call_history) if tool_call_history else 0,
            "tools_used": tools_used,
        }
        self.core.capture.append("observed", payload, actor="agent",
                                 session_id=child_session_id or self._session_id or None)

    def on_turn_start(self, turn_number, message, **kw):
        if self.core:
            self.core.capture._touch_session(self._session_id)
            self.core.tick()

    def on_session_switch(self, new_session_id, *, parent_session_id="", reset=False, rewound=False, **kw):
        if self.core:
            self.scope = self.core.switch_scope(new_session_id, parent_session_id, reset, rewound,
                                                self._principal_id)
            self._session_id = new_session_id

    # -- recall ------------------------------------------------------------

    def prefetch(self, query, *, session_id="") -> str:
        if not self.core:
            return ""
        return self.core.retrieval.get_context(
            query, token_budget=self.core.cfg.get("retrieval.prefetch_budget", 1200),
            principal=self._principal_id, epistemic=self.core.epistemic)

    def queue_prefetch(self, query, *, session_id=""):
        pass  # predictive warm-cache hook; no-op in the local build

    def system_prompt_block(self) -> str:
        return self.core.retrieval.static_block(self._principal_id) if self.core else ""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return self.core.tools.schemas() if self.core else []

    def handle_tool_call(self, tool_name, args, **kw) -> str:
        if not self.core:
            return json.dumps({"error": "Chronicle not initialized"})
        return self.core.tools.dispatch(self._principal_id, tool_name, args)
