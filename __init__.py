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

__version__ = "5.3.2"


def _active_core():
    try:
        from .engine.core import ChronicleCore
    except Exception:
        from engine.core import ChronicleCore
    return ChronicleCore.active()


def chronicle_status_command(raw_args: str = "") -> str:
    """`/chronicle` — show status, including whether embeddings are live.

    Handler for the in-session slash command (signature ``fn(raw_args) -> str``)."""
    core = _active_core()
    if core is None:
        return "Chronicle is installed but not initialized in this session yet."
    lines = ["Chronicle v" + __version__]
    try:
        st = core.embedding_status()
        mark = "✅ local model" if st.get("supports_embeddings") else "⚠️ offline hashing"
        lines.append("Embeddings: " + mark + " — " + str(st.get("detail", "")))
        lines.append("  embedder={} model={} endpoint={} dim={}".format(
            st.get("embedder"), st.get("model"), st.get("endpoint"), st.get("dimensions")))
    except Exception as e:
        lines.append("Embeddings: status unavailable (%s)" % e)
    try:
        s = core.store
        ev = s.count_rows("events")
        fa = s.count_rows("facts", "status='active'")
        pj = s.count_rows("curation_jobs", "status='pending'")
        lines.append("Store: {} events · {} active facts · {} pending jobs".format(ev, fa, pj))
    except Exception:
        pass
    return "\n".join(lines)


def register(ctx) -> None:
    """Register Chronicle's memory provider, context engine, and `/chronicle` command.

    Defensive across all discovery paths: the memory loader's simulated ctx exposes
    ``register_memory_provider``; the context-engine loader's exposes
    ``register_context_engine``; the general ``PluginContext`` exposes both plus
    ``register_command``. Each registers only what it understands.
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

    if hasattr(ctx, "register_command"):
        ctx.register_command(
            "chronicle", chronicle_status_command,
            description="Show Chronicle status: embedder (local model vs offline hashing) + store counts.")
