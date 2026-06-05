"""
Chronicle — Memory Provider plugin (Hermes memory-provider slot).

Long-term memory: capture + recall. Methods map 1:1 to the §12.3 hook table and
delegate to the shared `ChronicleCore`. `sync_turn` is the durability anchor
(I12); `on_pre_compress` yields to the Context Engine when it is active (§13.4).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

try:  # real Hermes base when present, else a local stand-in
    from agent.memory_provider import MemoryProvider  # type: ignore
except Exception:  # pragma: no cover
    from ._base import MemoryProvider

logger = logging.getLogger("chronicle.provider")


class ChronicleMemoryProvider(MemoryProvider):
    name = "chronicle"

    def __init__(self):
        self.core = None
        self.scope = None
        self._session_id = ""
        self._principal_id = "default"

    def is_available(self) -> bool:
        return self.core.local_ok() if self.core else True

    def initialize(self, session_id, *, hermes_home=None, principal_id="default", config=None, **kw):
        from engine.core import ChronicleCore
        hermes_home = hermes_home or str(Path.home() / ".hermes")
        self.core = ChronicleCore.get(hermes_home, config)
        self.core.has_memory_provider = True
        self._session_id = session_id
        self._principal_id = principal_id
        self.scope = self.core.initialize(session_id, hermes_home=hermes_home, principal_id=principal_id)
        logger.info("Chronicle MemoryProvider ready (session %s, principal %s)", session_id, principal_id)

    # capture (§12.3)
    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None):
        if self.core:
            self.core.capture.observe(user_content, assistant_content,
                                      session_id=session_id or self._session_id, messages=messages)

    def on_pre_compress(self, messages) -> str:
        if not self.core:
            return ""
        if self.core.has_context_engine:
            return ""  # the Context Engine owns compression (§13.4)
        _, summary = self.core.capture.rescue(messages, session_id=self._session_id)
        return summary

    def on_session_end(self, messages):
        if self.core:
            self.core.capture.finalize_session(self._session_id, "clean_exit")

    def on_memory_write(self, action, target, content, metadata=None):
        if self.core:
            self.core.capture.agent_explicit(action, target, content, metadata)
            self.core.tick()

    def on_delegation(self, task, result, *, child_session_id="", **kw):
        if self.core:
            self.core.capture.delegation(task, result, child_session_id=child_session_id)

    def on_turn_start(self, turn_number, message, **kw):
        if self.core:
            self.core.capture._touch_session(self._session_id)
            self.core.tick()

    def on_session_switch(self, new_session_id, *, parent_session_id="", reset=False, rewound=False, **kw):
        if self.core:
            self.scope = self.core.switch_scope(new_session_id, parent_session_id, reset, rewound,
                                                self._principal_id)
            self._session_id = new_session_id

    # recall (§12.3)
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

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return self.core.tools.schemas() if self.core else []

    def handle_tool_call(self, tool_name, args, **kw) -> str:
        if not self.core:
            return json.dumps({"error": "Chronicle not initialized"})
        return self.core.tools.dispatch(self._principal_id, tool_name, args)

    def shutdown(self):
        if self.core:
            self.core.capture.flush_best_effort()
            self.core.flush_git()
