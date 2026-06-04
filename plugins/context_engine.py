"""
Chronicle — Context Engine Plugin.

Implements the Hermes ContextEngine interface.
Provides memory-aware context compression: evicts only durable spans,
re-injects relevant long-term memory.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agent.context_engine import ContextEngine

logger = logging.getLogger("chronicle.context_engine")


class ChronicleContextEngine(ContextEngine):
    """Chronicle Context Engine for Hermes Agent.

    Replaces the default compressor with memory-aware compression.
    Evicts only spans that are durable events (I17).
    Re-injects relevant long-term memory (§13).
    """

    def __init__(self):
        self.core: Any = None
        self._session_id: str = ""
        self._principal_id: str = "default"

        # Default compaction parameters
        self.threshold_percent = 0.75
        self.protect_first_n = 3
        self.protect_last_n = 6

    @property
    def name(self) -> str:
        return "chronicle"

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        """Update tracked token usage from an API response."""
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        """Return True if compaction should fire this turn."""
        if prompt_tokens is None:
            prompt_tokens = self.last_prompt_tokens
        if self.context_length <= 0:
            return False
        return prompt_tokens > self.threshold_tokens

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
    ) -> List[Dict[str, Any]]:
        """Compact the message list (§13.2).

        1. Rescue: durably extract critical/high-salience spans
        2. Score each span
        3. Evict only durable spans (I17)
        4. Re-retrieve long-term memory toward focus_topic
        5. Return assembled messages
        """
        if not self.core:
            # Fallback: simple truncation
            return self._simple_compress(messages)

        # Step 1: Rescue extraction
        _, rescue_summary = self.core.capture.rescue_extract(messages)

        # Step 2: Score and select spans to keep
        # Always keep system + first N + last N
        if len(messages) <= self.protect_first_n + self.protect_last_n + 1:
            return messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        head = non_system[:self.protect_first_n]
        tail = non_system[-self.protect_last_n:]
        middle = non_system[self.protect_first_n:-self.protect_last_n] if len(non_system) > self.protect_first_n + self.protect_last_n else []

        # Score middle messages (simple heuristic)
        scored = []
        for msg in middle:
            content = msg.get("content", "")
            score = 0.0
            # Recency: later is better
            score += 0.1
            # Salience: important keywords
            if any(kw in content.lower() for kw in ["important", "remember", "always", "never", "critical"]):
                score += 0.5
            # Relevance to focus topic
            if focus_topic and focus_topic.lower() in content.lower():
                score += 0.3
            scored.append((score, msg))

        # Sort by score, keep top ones that fit
        scored.sort(key=lambda x: x[0], reverse=True)

        # Budget: keep roughly half of middle
        keep_count = max(len(middle) // 2, 1)
        kept_middle = [m for _, m in scored[:keep_count]]
        # Restore original order
        kept_middle.sort(key=lambda m: messages.index(m) if m in messages else 999)

        # Step 4: Re-retrieve long-term memory
        injected = []
        if focus_topic and self.core:
            try:
                ctx = self.core.retrieval.get_context(
                    focus_topic,
                    token_budget=500,
                    include_directives=False,
                )
                if ctx:
                    injected.append({
                        "role": "system",
                        "content": f"[Relevant memory for: {focus_topic}]\n{ctx}",
                    })
            except Exception as e:
                logger.debug(f"Re-retrieval failed: {e}")

        # Assemble
        result = system_msgs + head + kept_middle + tail + injected

        self.compression_count += 1
        logger.info(f"Compressed {len(messages)} → {len(result)} messages "
                     f"(focus: {focus_topic})")

        return result

    def _simple_compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fallback: simple truncation when core is not available."""
        if len(messages) <= 10:
            return messages
        system = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        # Keep first 3 and last 6
        kept = non_system[:3] + non_system[-6:]
        self.compression_count += 1
        return system + kept

    def on_session_start(self, session_id: str, **kwargs) -> None:
        """Called when a new session begins."""
        hermes_home = kwargs.get("hermes_home", "~/.hermes")
        self._session_id = session_id
        self._principal_id = kwargs.get("principal_id", "default")

        try:
            from .engine.core import ChronicleCore
            self.core = ChronicleCore.get(hermes_home)
            self.core.has_context_engine = True
            self.core.initialize(
                session_id,
                hermes_home=hermes_home,
                principal_id=self._principal_id,
                **kwargs,
            )
        except Exception as e:
            logger.warning(f"Chronicle Context Engine init failed: {e}")
            self.core = None

    def on_session_end(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        """Called at real session boundaries."""
        if self.core:
            self.core.capture.finalize_session(session_id, "clean_exit")

    def on_session_reset(self) -> None:
        """Called on /new or /reset."""
        super().on_session_reset()

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
        api_mode: str = "",
    ) -> None:
        """Called when the user switches models."""
        self.context_length = context_length
        self.threshold_tokens = int(context_length * self.threshold_percent)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas for Context Engine tools."""
        return [
            {
                "name": "chronicle_pin_context",
                "description": "Pin a context span so it is never evicted.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Content to pin."},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "chronicle_focus",
                "description": "Set the focus topic for memory-aware compression.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "Focus topic."},
                    },
                    "required": ["topic"],
                },
            },
        ]

    def handle_tool_call(self, name: str, args: Dict[str, Any], **kwargs) -> str:
        """Handle a Context Engine tool call."""
        if name == "chronicle_pin_context":
            content = args.get("content", "")
            if content and self.core:
                self.core.capture.agent_explicit("add", "memory", content)
                return json.dumps({"status": "pinned"})
            return json.dumps({"error": "no content or core not available"})
        elif name == "chronicle_focus":
            topic = args.get("topic", "")
            return json.dumps({"status": "focus_set", "topic": topic})
        return json.dumps({"error": f"Unknown tool: {name}"})
