"""
Minimal fallback bases for the Hermes plugin ABCs.

Under Hermes the real `agent.memory_provider.MemoryProvider` and
`agent.context_engine.ContextEngine` are imported. Offline (tests, CI) these
lightweight stand-ins let the adapters be imported and exercised without the
host. They define only what the adapters touch.
"""

from __future__ import annotations


class MemoryProvider:
    name = "base"

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs) -> None: ...

    def shutdown(self) -> None: ...

    # The real `agent.memory_provider.MemoryProvider` defines this as a no-op
    # default ("providers that do background prefetching should override this").
    # Chronicle does not do background prefetching, so it does NOT override it
    # (A13 removed an override whose body was a second copy of this no-op). It
    # is declared here so the offline stand-in answers a host call the same way
    # the real base would, instead of raising AttributeError.
    def queue_prefetch(self, query: str, *, session_id: str = "") -> None: ...


class ContextEngine:
    """Stand-in for `agent.context_engine.ContextEngine`.

    Where the real base has a DEFAULT BEHAVIOUR rather than a bare abstract
    method, this reproduces it — otherwise a test here passes against a no-op
    the production host does not have. `on_session_reset` was a bare `...` while
    the host zeroes the token counters, so a reset test could not tell whether
    Chronicle's override chained to the host at all."""

    def __init__(self):
        self.context_length = 0
        self.threshold_tokens = 0
        self.compression_count = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0

    def on_session_reset(self) -> None:
        # The host's default, verbatim in effect: 0 (not -1) is the documented
        # "no real usage yet" state.
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.compression_count = 0

    def prune_tool_results_only(self, messages, current_tokens=None):
        return messages, 0

    def has_content_to_compress(self, messages) -> bool:
        return True

    def should_defer_preflight_to_real_usage(self, rough_tokens) -> bool:
        return False

    def select_context(self, request_messages, *, conversation_messages=None,
                       incoming_message=None, budget_tokens=0):
        return None

    def on_turn_complete(self, messages, usage=None, **kwargs) -> None:
        return None
