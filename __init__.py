"""
Chronicle — event-sourced memory + working-memory context for Hermes.

Two plugins over one shared in-process core (`ChronicleCore`):
- ChronicleMemoryProvider — memory-provider slot (long-term memory: capture + recall)
- ChronicleContextEngine  — context-engine slot (working memory: memory-aware compression)

This package is the Hermes plugin entry point. The Hermes loader discovers it by
text-scanning this file for ``register_memory_provider`` / ``register_context_engine``
and calls ``register(ctx)`` (it registers a synthetic parent package so the
relative imports below resolve). Activate the slots in ``~/.hermes/config.yaml``:

    memory:  { provider: chronicle }
    context: { engine: chronicle }
"""

from __future__ import annotations

__version__ = "5.2.0"


def register(ctx) -> None:
    """Register Chronicle's memory provider and context engine.

    Defensive across all three discovery paths: the memory loader's simulated ctx
    exposes ``register_memory_provider``; the context-engine loader's exposes
    ``register_context_engine``; a general ``PluginContext`` exposes both. Each
    registers only the slot it understands.
    """
    if hasattr(ctx, "register_memory_provider"):
        try:
            from .provider import ChronicleMemoryProvider
        except Exception:
            from provider import ChronicleMemoryProvider
        ctx.register_memory_provider(ChronicleMemoryProvider())

    if hasattr(ctx, "register_context_engine"):
        try:
            from .context import ChronicleContextEngine
        except Exception:
            from context import ChronicleContextEngine
        ctx.register_context_engine(ChronicleContextEngine())
