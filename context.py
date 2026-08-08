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
import threading
import time
from contextlib import nullcontext
from typing import Any

try:  # real Hermes base when present …
    from agent.context_engine import ContextEngine  # type: ignore
except Exception:  # … else a local stand-in (plugin-package or top-level)
    try:
        from ._base import ContextEngine
    except Exception:  # pragma: no cover
        from _base import ContextEngine

logger = logging.getLogger("chronicle.context_engine")

_NEVER_EVICT_KW = ["always", "never", "must not", "do not", "don't", "[directive]"]

# Lazy re-init policy. An init failure is a moment, not a verdict: on 2026-08-02
# a concurrent migration held the SQLite write lock for one session start, and
# the heuristic fallback stayed latched for the rest of the process — the
# memory-aware half of the plugin was gone until someone restarted the host.
# So a failed init only decides THIS call; the next compress() retries, with
# exponential backoff and a hard budget per rolling hour so a genuinely broken
# store cannot turn every compression into a core rebuild.
_RETRY_BASE_SEC = 1.0            # delay after the 1st consecutive failure
_RETRY_MAX_SEC = 300.0           # backoff ceiling
_RETRY_MAX_PER_HOUR = 12         # attempts allowed in any rolling hour
_RETRY_WINDOW_SEC = 3600.0


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
        # Required class attributes the host expects a context engine to maintain.
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.threshold_tokens = 0
        self.context_length = 0
        self.compression_count = 0
        # -- init resilience state (see _RETRY_* above) ---------------------
        # INVARIANT: `self.core is None` <=> the heuristic fallback is active.
        # Nothing may attach a core it did not finish initializing.
        self._init_started = False       # on_session_start has run at least once
        self._init_args = None           # replayed by a lazy retry
        self._consecutive_failures = 0   # drives the backoff; 0 once healthy
        self._init_attempts = 0          # total, all time
        self._attempt_times = []         # rolling-hour window, for the budget
        self._recoveries = 0             # successful re-inits after a failure
        self._recovered_after = 0        # failures the last recovery came back from
        self._last_error = ""            # last init error, kept after recovery
        self._retry_lock = threading.Lock()

    # lifecycle
    def on_session_start(self, session_id, *, hermes_home="~/.hermes", principal_id="default", config=None, **kw):
        self._session_id = session_id
        self._principal_id = principal_id
        self._init_args = {"hermes_home": hermes_home, "config": config}
        self._init_started = True
        self._try_init()
        # One greppable line per session start. Which half of the plugin is live
        # is exactly what went unnoticed for a whole process life on 2026-08-02,
        # so it gets stated every time rather than only when it changes.
        self.log_context_status()

    def _try_init(self) -> bool:
        """One init attempt. Returns True iff the real engine is live afterwards.

        Never raises: standalone degradation must not crash the host.
        """
        args = self._init_args or {"hermes_home": "~/.hermes", "config": None}
        self._init_attempts += 1
        self._attempt_times.append(time.time())
        try:
            try:
                from .engine.core import ChronicleCore
            except Exception:
                from engine.core import ChronicleCore
            core = ChronicleCore.get(args["hermes_home"], args["config"])
            core.has_context_engine = True
            with self._init_lock_budget(core):
                core.initialize(self._session_id, hermes_home=args["hermes_home"],
                                principal_id=self._principal_id)
        except Exception as e:
            # Drop the core even though ChronicleCore.get() may have handed back a
            # perfectly good WARM singleton: the lock is just as likely to fire
            # INSIDE initialize(), and keeping a half-initialized core attached
            # would report "real engine" while every compress() re-raised
            # OperationalError into the host. `core is None` is the fallback flag.
            was_fallback = self.core is None and self._consecutive_failures > 0
            self.core = None
            self._consecutive_failures += 1
            self._last_error = "%s: %s" % (type(e).__name__, e)
            if not was_fallback:  # log the transition, not every attempt
                logger.warning("Chronicle context engine: init failed, serving heuristic "
                               "fallback until re-init succeeds: %s", e)
            else:
                logger.debug("Chronicle context engine: re-init attempt %d failed: %s",
                             self._consecutive_failures, e)
            return False
        if self._consecutive_failures:
            self._recoveries += 1
            self._recovered_after = self._consecutive_failures
            logger.warning("Chronicle context engine: re-initialized after %d failed "
                           "attempt(s); memory-aware compression active again",
                           self._consecutive_failures)
        self._consecutive_failures = 0
        self.core = core
        return True

    @staticmethod
    def _init_lock_budget(core):
        """Bound how long initialize() waits on the SQLite write lock.

        The store owns the timeout; a core without one (a stub, a test double)
        just runs unbounded, exactly as before.
        """
        store = getattr(core, "store", None)
        ctx = getattr(store, "init_busy_timeout", None)
        return ctx() if callable(ctx) else nullcontext()

    def _retry_delay(self) -> float:
        """Exponential backoff on consecutive failures, capped at _RETRY_MAX_SEC."""
        n = max(0, min(self._consecutive_failures - 1, 16))
        return min(_RETRY_MAX_SEC, _RETRY_BASE_SEC * (2 ** n))

    def _retry_due_in(self, now=None):
        """Seconds until the next re-init attempt is allowed.

        0.0 = due now, None = not applicable (healthy, never started, or the
        hourly budget is spent).
        """
        if self.core is not None or not self._init_started:
            return None
        now = time.time() if now is None else now
        window = [t for t in self._attempt_times if now - t < _RETRY_WINDOW_SEC]
        self._attempt_times = window
        if len(window) >= _RETRY_MAX_PER_HOUR:
            return None
        if not window:
            return 0.0
        return max(0.0, self._retry_delay() - (now - window[-1]))

    def _maybe_retry_init(self):
        """Re-init if one is due. Serialized: concurrent compress() calls must
        not each build their own core while the first one is still trying."""
        if self._retry_due_in() != 0.0:
            return
        if not self._retry_lock.acquire(False):
            return  # another thread is already on it; this call falls back
        try:
            if self._retry_due_in() == 0.0:
                self._try_init()
        finally:
            self._retry_lock.release()

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
    def compress(self, messages, current_tokens=None, focus_topic=None, force=False, **kwargs) -> list[dict[str, Any]]:
        focus_topic = focus_topic or self.focus_topic
        if self.core is None and self._init_started:
            self._maybe_retry_init()   # a busy moment at start-up must not be permanent
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
        # Normalize chat-role to a valid Chronicle actor (CHECK constraint allows
        # only 'user','agent','curator','system'). "assistant" is not a valid actor.
        role = m.get("role", "system")
        actor = role if role in ("user", "agent", "curator", "system") else "agent"
        self.core.capture.append("observed", {"source_type": "context_eviction",
                                              "excerpt": content[:4000], "source_ref": self._session_id},
                                 actor=actor,
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
            {"name": "chronicle_context_status",
             "description": "Report which compression mode the context engine is in "
                            "(memory-aware or heuristic fallback) and why.",
             "parameters": {"type": "object", "properties": {}, "required": []}},
        ]

    def handle_tool_call(self, name, args, **kw) -> str:
        if name == "chronicle_pin_context" and self.core:
            self.core.capture.agent_explicit("pin", "context", args.get("content", ""))
            return json.dumps({"status": "pinned"})
        if name == "chronicle_focus":
            self.focus_topic = args.get("topic")
            return json.dumps({"status": "focus_set", "topic": self.focus_topic})
        if name == "chronicle_context_status":
            return json.dumps(self.context_status())
        return json.dumps({"error": f"unknown tool: {name}"})

    def context_status(self) -> dict:
        """Which compression mode is live, and why (chronicle_context_status).

        Read-only by design — asking what mode you are in must not itself trigger
        a core rebuild. Mode is derived from `self.core`, the one thing that
        actually decides which branch compress() takes, so the report cannot
        disagree with the behaviour.
        """
        live = self.core is not None
        if live:
            reason = ("re-initialized after %d failed attempt(s)" % self._recovered_after
                      if self._recoveries else "initialized at session start")
        elif not self._init_started:
            reason = "not initialized yet (no session start)"
        else:
            reason = "init failed: %s" % (self._last_error or "unknown")
        due = self._retry_due_in()
        return {
            "engine": self.name,
            "mode": "memory_aware" if live else "heuristic_fallback",
            "reason": reason,
            "init_attempts": self._init_attempts,
            "consecutive_failures": self._consecutive_failures,
            "recoveries": self._recoveries,
            "last_error": self._last_error,
            "retry_due_in_sec": due,
            "retry_budget_spent": (not live and self._init_started and due is None),
            "attempts_this_hour": len(self._attempt_times),
        }

    def log_context_status(self):
        """Emit the status as one operator-readable line.

        WARNING while degraded: a silently heuristic context engine is the whole
        defect, and INFO is filtered out on the box where it happened.
        """
        st = self.context_status()
        log = logger.info if self.core is not None else logger.warning
        log("chronicle_context_status: mode=%s reason=%s attempts=%d recoveries=%d",
            st["mode"], st["reason"], st["init_attempts"], st["recoveries"])
        return st

    # status
    def should_compress_preflight(self, messages) -> bool:
        return False  # Chronicle compresses reactively on token threshold, not preflight

    def get_status(self) -> dict:
        st = self.context_status()
        return {
            "engine": self.name,
            "mode": st["mode"],
            "mode_reason": st["reason"],
            "context_length": self.context_length,
            "threshold_tokens": self.threshold_tokens,
            "last_prompt_tokens": self.last_prompt_tokens,
            "last_total_tokens": self.last_total_tokens,
            "compression_count": self.compression_count,
        }
