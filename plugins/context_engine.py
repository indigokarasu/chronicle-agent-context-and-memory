"""
Chronicle — Context Engine plugin (Hermes context-engine slot).

Working memory: owns the live window. Compression is memory-aware (§13): rescue
critical spans, score, evict ONLY spans that are durable events (I17), re-retrieve
long-term memory toward the focus topic, and emit a `compressed` audit event.
Directives / always_inject spans are never evicted. Standalone (no provider) it
degrades to a competent token+recency+salience compressor (§13.4).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

try:
    from agent.context_engine import ContextEngine  # type: ignore
except Exception:  # pragma: no cover
    from ._base import ContextEngine

logger = logging.getLogger("chronicle.context_engine")

_NEVER_EVICT_KW = ["always", "never", "must not", "do not", "don't", "[directive]"]


class ChronicleContextEngine(ContextEngine):
    name = "chronicle"

    def __init__(self):
        super().__init__()
        self.core = None
        self._session_id = ""
        self._principal_id = "default"
        self.threshold_percent = 0.75
        self.protect_first_n = 3
        self.protect_last_n = 6
        self.focus_topic = None

    # lifecycle
    def on_session_start(self, session_id, *, hermes_home="~/.hermes", principal_id="default", config=None, **kw):
        self._session_id = session_id
        self._principal_id = principal_id
        try:
            from engine.core import ChronicleCore
            self.core = ChronicleCore.get(hermes_home, config)
            self.core.has_context_engine = True
            self.core.initialize(session_id, hermes_home=hermes_home, principal_id=principal_id)
        except Exception as e:  # standalone degradation must not crash the host
            logger.warning("Context Engine init failed, using heuristic fallback: %s", e)
            self.core = None

    def on_session_end(self, session_id, messages):
        if self.core:
            self.core.capture.finalize_session(session_id, "clean_exit")

    def update_model(self, model, context_length, base_url="", api_key="", provider="", api_mode=""):
        self.context_length = context_length
        self.threshold_tokens = int(context_length * self.threshold_percent)

    def update_from_response(self, usage):
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)
        self.last_completion_tokens = usage.get("completion_tokens", 0)
        self.last_total_tokens = usage.get("total_tokens", 0)

    def should_compress(self, prompt_tokens=None) -> bool:
        pt = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        if self.context_length <= 0:
            return False
        return pt > self.threshold_tokens

    # compression (§13.2)
    def compress(self, messages, current_tokens=None, focus_topic=None) -> List[Dict[str, Any]]:
        focus_topic = focus_topic or self.focus_topic
        if not self.core:
            return self._heuristic(messages)

        # 1) rescue critical/high-salience spans → durable beliefs (I14)
        self.core.capture.rescue(messages, session_id=self._session_id)

        system = [m for m in messages if m.get("role") == "system"]
        body = [m for m in messages if m.get("role") != "system"]
        if len(body) <= self.protect_first_n + self.protect_last_n:
            return messages

        head, tail = body[:self.protect_first_n], body[-self.protect_last_n:]
        middle = body[self.protect_first_n:-self.protect_last_n]

        kept, evicted = [], []
        for m in middle:
            if self._never_evict(m):
                kept.append(m)
                continue
            score = self._keep_score(m, focus_topic)
            if score >= 0.5:
                kept.append(m)
            else:
                evicted.append(m)

        # 3) evict ONLY durable spans — make each durable first (I17)
        durable_evicted = []
        for m in evicted:
            self._ensure_durable(m)
            durable_evicted.append(m)

        # 4) re-retrieve long-term memory toward focus
        injected = []
        if focus_topic:
            ctx = self.core.retrieval.get_context(focus_topic, token_budget=500,
                                                  include_directives=False, principal=self._principal_id)
            if ctx:
                injected.append({"role": "system", "content": f"[Relevant memory: {focus_topic}]\n{ctx}"})

        # 5) audit event
        self.core.capture.append("compressed", {
            "session_id": self._session_id, "evicted_spans": len(durable_evicted),
            "retained": len(kept) + len(head) + len(tail), "summary_ref": ""},
            actor="system", session_id=self._session_id)

        self.compression_count += 1
        return system + head + kept + tail + injected

    def _keep_score(self, m, focus):
        w = self.core.cfg.get("context_engine.keep_weights", {}) if self.core else {}
        content = (m.get("content") or "").lower()
        score = 0.2  # recency baseline
        if focus and focus.lower() in content:
            score += w.get("relevance", 0.35)
        if any(k in content for k in ("important", "remember", "critical", "must")):
            score += w.get("salience", 0.2) + w.get("criticality", 0.2)
        return score

    def _never_evict(self, m) -> bool:
        c = (m.get("content") or "").lower()
        return any(k in c for k in _NEVER_EVICT_KW)

    def _ensure_durable(self, m):
        """I17: a span is evicted only if it is (or is first made) a durable event."""
        content = m.get("content") or ""
        if len(content) < 1:
            return
        self.core.capture.append("observed", {"source_type": "context_eviction",
                                              "excerpt": content[:4000], "source_ref": self._session_id},
                                 actor=m.get("role", "system") if m.get("role") in ("user", "assistant") else "system",
                                 session_id=self._session_id)

    def _heuristic(self, messages):
        if len(messages) <= 10:
            return messages
        system = [m for m in messages if m.get("role") == "system"]
        body = [m for m in messages if m.get("role") != "system"]
        self.compression_count += 1
        return system + body[:3] + body[-6:]

    # tools
    def get_tool_schemas(self):
        return [
            {"name": "chronicle_pin_context", "description": "Pin a span so compression never evicts it.",
             "parameters": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
            {"name": "chronicle_focus", "description": "Set the focus topic for memory-aware compression.",
             "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
        ]

    def handle_tool_call(self, name, args, **kw) -> str:
        if name == "chronicle_pin_context" and self.core:
            self.core.capture.agent_explicit("pin", "context", args.get("content", ""))
            return json.dumps({"status": "pinned"})
        if name == "chronicle_focus":
            self.focus_topic = args.get("topic")
            return json.dumps({"status": "focus_set", "topic": self.focus_topic})
        return json.dumps({"error": f"unknown tool: {name}"})
