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
    def __init__(self):
        self.context_length = 0
        self.threshold_tokens = 0
        self.compression_count = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0

    def on_session_reset(self) -> None: ...
