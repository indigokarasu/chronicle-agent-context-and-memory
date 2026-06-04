"""
Chronicle Memory System for Hermes Agent.

A local-first, crash-safe, self-improving, multi-agent memory system.
Provides persistent, cross-session knowledge with:
- Event-sourced architecture (append-only log + reducer → belief store)
- Dual-tier retrieval (belief layer + raw layer with read-and-answer)
- Truth maintenance & guarded derivation
- Multi-agent access control (default-allow within user)
- Context Engine (memory-aware compression)
- Bounded self-improvement (learning loop)

Two plugins, one core:
- ChronicleMemoryProvider (memory-provider slot)
- ChronicleContextEngine (context-engine slot)

Replaces: ocas-elephas skill
Version: 5.0.0
"""

__version__ = "5.0.0"
