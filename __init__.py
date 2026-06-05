"""
Chronicle — event-sourced memory + working-memory context for Hermes.

Two plugins over one shared in-process core (`ChronicleCore`):
- ChronicleMemoryProvider — memory-provider slot (long-term memory: capture + recall)
- ChronicleContextEngine  — context-engine slot (working memory: memory-aware compression)

This package is the Hermes plugin entry point. Loaders discover it by text-scanning
this file for ``register_memory_provider`` / ``register_context_engine`` and either
call ``register(ctx)`` or scan the module for a ContextEngine/MemoryProvider
subclass. Both classes are therefore exposed at module top level (so the
subclass-fallback path works) AND wired in ``register(ctx)`` (so the register
path works). Activate the slots in ``~/.hermes/config.yaml``:

    memory:  { provider: chronicle }
    context: { engine: chronicle }
"""

from __future__ import annotations

import logging

__version__ = "5.3.3"

logger = logging.getLogger("chronicle.plugin")

# Expose the slot classes at module top level so a context-engine loader that
# only scans for a ContextEngine subclass (the subclass-fallback path) can find
# and instantiate ChronicleContextEngine even if register(ctx) is never called.
# Dual-mode import: relative under the loader's synthetic package, absolute for
# local dev/tests.
try:
    from .provider import ChronicleMemoryProvider
    from .context import ChronicleContextEngine
except Exception:  # pragma: no cover
    try:
        from provider import ChronicleMemoryProvider
        from context import ChronicleContextEngine
    except Exception:
        ChronicleMemoryProvider = None
        ChronicleContextEngine = None


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

    Defensive across every discovery path: the memory loader's ctx exposes
    ``register_memory_provider``; the context-engine loader's exposes
    ``register_context_engine``; the general ``PluginContext`` exposes both plus
    ``register_command``. EACH registration is independently guarded so a failure
    in one (e.g. a collector that rejects command registration) can never discard
    an already-registered engine.
    """
    mp_cls, ce_cls = ChronicleMemoryProvider, ChronicleContextEngine
    if mp_cls is None or ce_cls is None:  # top-level import was deferred — retry now
        try:
            from .provider import ChronicleMemoryProvider as mp_cls  # type: ignore
            from .context import ChronicleContextEngine as ce_cls  # type: ignore
        except Exception:
            try:
                from provider import ChronicleMemoryProvider as mp_cls  # type: ignore
                from context import ChronicleContextEngine as ce_cls  # type: ignore
            except Exception:
                pass

    if hasattr(ctx, "register_memory_provider") and mp_cls is not None:
        try:
            ctx.register_memory_provider(mp_cls())
        except Exception as e:
            logger.warning("Chronicle: register_memory_provider failed: %s", e)

    if hasattr(ctx, "register_context_engine") and ce_cls is not None:
        try:
            ctx.register_context_engine(ce_cls())
        except Exception as e:
            logger.warning("Chronicle: register_context_engine failed: %s", e)

    if hasattr(ctx, "register_command"):
        try:
            ctx.register_command(
                "chronicle", chronicle_status_command,
                description="Show Chronicle status: embedder (local model vs offline hashing) + store counts.")
        except Exception as e:
            logger.warning("Chronicle: register_command failed: %s", e)
