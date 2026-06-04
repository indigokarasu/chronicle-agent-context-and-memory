"""
Chronicle — Memory Provider Plugin.

Implements the Hermes MemoryProvider interface.
Provides persistent, cross-session knowledge via the Chronicle event-sourced core.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger("chronicle.provider")


class ChronicleMemoryProvider(MemoryProvider):
    """Chronicle Memory Provider for Hermes Agent.

    Implements the MemoryProvider ABC, delegating to ChronicleCore.
    """

    def __init__(self):
        self.core: Any = None
        self.scope: Any = None
        self._session_id: str = ""
        self._principal_id: str = "default"

    @property
    def name(self) -> str:
        return "chronicle"

    def is_available(self) -> bool:
        """Check if Chronicle is available (local-only, no network)."""
        try:
            from .engine.core import ChronicleCore
            return True
        except ImportError:
            return False

    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize Chronicle for a session."""
        hermes_home = kwargs.get("hermes_home", str(Path.home() / ".hermes"))
        principal_id = kwargs.get("principal_id", "default")

        from .engine.core import ChronicleCore
        self.core = ChronicleCore.get(hermes_home)
        self.core.has_memory_provider = True
        self.core.initialize(
            session_id,
            hermes_home=hermes_home,
            principal_id=principal_id,
            **kwargs,
        )
        self._session_id = session_id
        self._principal_id = principal_id
        self.scope = self.core.open_scope(session_id, principal_id)
        logger.info(f"Chronicle MemoryProvider initialized for session {session_id}")

    def system_prompt_block(self) -> str:
        """Return directives for the system prompt."""
        if not self.core:
            return ""
        return self.core.retrieval.get_directives()

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Recall relevant context for the upcoming turn."""
        if not self.core:
            return ""
        return self.core.retrieval.get_context(query)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Queue background recall for the next turn."""
        # No-op for now; could warm a semantic cache
        pass

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Persist a completed turn (durability anchor, I12)."""
        if not self.core:
            return
        sid = session_id or self._session_id
        self.core.capture.observe(
            user_content, assistant_content,
            session_id=sid,
            messages=messages,
        )

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        """Called at the start of each turn."""
        if self.core:
            self.core.capture._touch_session(self._session_id)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Called when a session ends."""
        if self.core:
            self.core.capture.finalize_session(self._session_id, "clean_exit")

    def on_session_switch(
        self,
        new_session_id: str,
        *,
        parent_session_id: str = "",
        reset: bool = False,
        rewound: bool = False,
        **kwargs,
    ) -> None:
        """Called when the agent switches session."""
        if self.core:
            self.scope = self.core.switch_scope(
                new_session_id, parent_session_id, reset, rewound,
                self._principal_id
            )
            self._session_id = new_session_id

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Called before context compression.

        Returns "" when the Chronicle Context Engine is active (it owns compression).
        Otherwise does rescue extraction.
        """
        if not self.core:
            return ""
        if self.core.has_context_engine:
            return ""  # Context Engine owns this
        _, summary = self.core.capture.rescue_extract(messages)
        return summary

    def on_delegation(self, task: str, result: str, *,
                      child_session_id: str = "", **kwargs) -> None:
        """Called when a subagent completes."""
        if self.core:
            self.core.capture.delegation(task, result, child_session_id=child_session_id)

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Called when the built-in memory tool writes an entry."""
        if self.core:
            self.core.capture.agent_explicit(action, target, content, metadata)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas for Chronicle tools."""
        if not self.core:
            return []
        return self.core.retrieval.get_tool_schemas()

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Handle a Chronicle tool call."""
        if not self.core:
            return json.dumps({"error": "Chronicle not initialized"})
        return self.core.retrieval.dispatch_tool(tool_name, args)

    def shutdown(self) -> None:
        """Clean shutdown."""
        if self.core:
            self.core.capture.finalize_session(self._session_id, "shutdown")
            logger.info("Chronicle MemoryProvider shut down")

    def get_config_schema(self) -> List[Dict[str, Any]]:
        """Return config fields Chronicle needs."""
        return [
            {
                "key": "db_path",
                "description": "Path to the Chronicle SQLite database",
                "default": "~/.hermes/commons/db/chronicle/chronicle.db",
                "required": False,
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        """Write non-secret config."""
        pass  # Config is read from the main config.yaml
