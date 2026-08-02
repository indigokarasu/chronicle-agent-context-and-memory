"""
Chronicle — Sources & capability federation (§14).

Anything declaring "use me for X" becomes capability X's source of record;
Chronicle references it (a pointer + a thin TTL cache) and keeps only the
genuinely-Chronicle part — the belief *about* it (I20). The registry updates live
on plugin/MCP connect & disconnect; pointers stay valid across a provider's
absence and degrade to cache/stub. With no providers, Chronicle uses internal
entity stubs and is fully functional (I18).
"""

from __future__ import annotations

import json
import logging

from .errors import E_AUTHORITY_UNAVAILABLE

logger = logging.getLogger("chronicle.federation")

# Default predicate → capability routing. Config pins override.
PREDICATE_CAPABILITY = {
    "phone": "contacts", "email": "contacts", "address": "contacts",
    "birthday": "contacts", "calendar": "calendar", "event": "calendar",
    "preference": "preferences", "prefers": "preferences", "likes": "preferences",
}


class CapabilityProvider:
    """Interface for an external authoritative store (Weave, Taste, an MCP, …)."""
    name = ""
    capability = ""

    def is_available(self) -> bool:
        return True

    def resolve(self, ref):
        raise NotImplementedError

    def query(self, params) -> list[dict]:
        return []


class CapabilityRegistry:
    def __init__(self, store, cfg):
        self.store = store
        self.cfg = cfg
        self.providers: dict[str, CapabilityProvider] = {}

    # -- discovery / lifecycle --------------------------------------------

    def bind(self):
        """Discover providers at init and seed config pins (§14.2)."""
        for cap, provider in (self.cfg.get("federation.pins", {}) or {}).items():
            self.store.upsert_capability_provider(
                {"capability": cap, "provider": provider, "declared_by": "config", "precedence": 100,
                 "status": "active" if cap in self.providers else "unavailable"})

    def register(self, provider: CapabilityProvider, *, declared_by="runtime", precedence=10):
        self.providers[provider.capability] = provider
        self.store.upsert_capability_provider(
            {"capability": provider.capability, "provider": provider.name, "declared_by": declared_by,
             "precedence": precedence, "status": "active" if provider.is_available() else "unavailable"})
        logger.info("capability %s ← %s", provider.capability, provider.name)

    def unregister(self, capability: str):
        """Plugin/MCP disconnect: pointers stay valid; mark unavailable (§14.2)."""
        self.providers.pop(capability, None)
        if self.store.get_capability_provider(capability):
            self.store.set_capability_status(capability, "unavailable")

    def on_change(self):
        for cap, row in ((c["capability"], c) for c in self.store.get_capability_providers()):
            avail = cap in self.providers and self.providers[cap].is_available()
            self.store.set_capability_status(cap, "active" if avail else "unavailable")

    # -- routing ----------------------------------------------------------

    def capability_for_predicate(self, predicate: str) -> str | None:
        cap = PREDICATE_CAPABILITY.get(predicate)
        if not cap:
            return None
        # Only delegate when a provider claims it (else Chronicle keeps the belief).
        row = self.store.get_capability_provider(cap)
        return cap if row else None

    def route_delegate(self, *, capability, entity_id, predicate, value, owner):
        """Create a pointer + a belief-about, not an owned fact (§14.2, I20)."""
        row = self.store.get_capability_provider(capability)
        provider = (row or {}).get("provider", "unknown")
        pid = self.store.upsert_pointer({"capability": capability, "provider": provider,
                                         "external_id": f"{entity_id}:{predicate}",
                                         "cached_projection": json.dumps({"value": value}),
                                         "cache_ttl": self.cfg.get("federation.cache_ttl", "24h")})
        # Link the entity to the pointer (belief about it).
        ent = self.store.get_belief("entities", entity_id)
        if ent:
            self.store.update_belief("entities", entity_id, external_provider=provider, external_ref=pid)
        return pid

    def resolve(self, capability: str, ref):
        """Read from the provider on demand; degrade to cache/stub if absent (§14.2)."""
        prov = self.providers.get(capability)
        if prov and prov.is_available():
            try:
                return prov.resolve(ref)
            except Exception as e:
                logger.warning("provider %s resolve failed: %s", capability, e)
        ptr = self.store.get_pointer(ref) if isinstance(ref, str) else None
        if ptr and ptr.get("cached_projection"):
            return json.loads(ptr["cached_projection"])
        raise E_AUTHORITY_UNAVAILABLE(f"no active provider for {capability}", capability=capability)

    def list_capabilities(self) -> list[dict]:
        return self.store.get_capability_providers()
