"""
Chronicle — what a masked value points AT (Phase E's resolver).

Masking leaves Hermes' sentinel with a pointer in it, `«redacted:vault_ab12cd34ef56»`
or `«redacted:env:OPENROUTER_API_KEY»` (engine/credentials.py). Until now that
pointer resolved through nothing: it was a label copied out of the text, and
nobody could ask whether it named anything real. The acceptance for this phase
was "every pointer resolves correctly through Hermes", and this is the half
that makes that a question with an answer.

WHAT IT RETURNS, AND WHAT IT REFUSES TO RETURN. The vault has two reads:

  * `get_meta(item_id)` -> VaultItemMeta, whose own docstring says "Never
    contains secret values", and for a login "the identifier (email/username)
    is metadata, not a secret: the agent may see it and type it itself. Only
    the password is vault-secret."
  * `resolve_secret(item_id)` -> the decrypted payload, whose docstring says
    "for server-side use ONLY. Callers must never place the returned values
    into tool results, logs, exceptions, or any string that reaches the
    session DB."

EVERY Chronicle output surface reaches the session DB -- a belief, a recall
block, a compaction handoff, a tool result. So this module calls `get_meta`
and NEVER `resolve_secret`. Resolving a pointer here answers "does this name a
real item, and what is it?" -- a Zoom login for jared@example, created in
August -- and never "what is the password". Using the value is the host's vault
fill path, which registers it for redaction before it is typed; that is a
different code path with different rules, and it is not this one.

A pointer that does NOT resolve is the interesting case: it means a masked
belief is pointing at something that no longer exists, or never did, and the
value behind it is gone. `audit()` finds those.

Offline (tests, a checkout with no Hermes on the path) every lookup answers
`resolves: False, reason: "vault unavailable"` rather than raising, so a
Chronicle that cannot see a vault degrades to "I cannot tell" instead of
falsely reporting a dangling pointer.
"""

from __future__ import annotations

import os
import re

# The label inside Hermes' sentinel. `credentials.SENTINEL` writes it.
_POINTER = re.compile(r"«redacted:([^»]+)»")
_VAULT_ID = re.compile(r"^vault_[0-9a-f]{12}$")
_ENV_REF = re.compile(r"^env:([A-Z][A-Z0-9_]*)$")

VAULT, ENV, PREFIX, UNKNOWN = "vault", "env", "prefix", "unknown"


def pointers_in(text: str) -> list:
    """Every pointer label in `text`, in order, without duplicates."""
    return list(dict.fromkeys(_POINTER.findall(text or "")))


def form_of(pointer: str) -> str:
    """Which kind of reference this is, by shape alone."""
    p = (pointer or "").strip()
    if _VAULT_ID.match(p):
        return VAULT
    if _ENV_REF.match(p):
        return ENV
    if p.endswith("…"):
        return PREFIX          # `ghp_…`: a vendor label, deliberately not a reference
    return UNKNOWN


def _vault():
    """Hermes' vault store, or None when Hermes is not importable."""
    try:                                    # the host's own convention (context.py)
        from agent.vault_store import get_vault_store  # type: ignore
    except Exception:
        return None
    try:
        return get_vault_store()
    except Exception:
        return None


def resolve(pointer: str) -> dict:
    """What `pointer` names. METADATA ONLY -- never a secret value.

    `resolves` is the whole point: False means a masked belief is pointing at
    something that is not there."""
    p = (pointer or "").strip()
    form = form_of(p)
    out = {"pointer": p, "form": form, "resolves": False}

    if form == ENV:
        name = _ENV_REF.match(p).group(1)
        out["name"] = name
        # Set-ness only. The value is not read, not returned, not logged.
        out["resolves"] = name in os.environ
        if not out["resolves"]:
            out["reason"] = "no environment variable of that name in this process"
        return out

    if form == PREFIX:
        out["reason"] = "a vendor prefix says what KIND of credential it was, not which one"
        return out

    if form != VAULT:
        out["reason"] = "not a reference Chronicle knows how to resolve"
        return out

    store = _vault()
    if store is None:
        out["reason"] = "vault unavailable"        # cannot tell, not "dangling"
        return out
    try:
        meta = store.get_meta(p)
    except Exception as e:                          # noqa: BLE001 -- a lookup may never raise out
        out["reason"] = "vault lookup failed: %s" % type(e).__name__
        return out
    if meta is None:
        out["reason"] = "no vault item with that id"
        return out

    # Every field here is from VaultItemMeta, which is metadata by construction.
    out.update({
        "resolves": True,
        "kind": getattr(meta, "kind", ""),
        "label": getattr(meta, "label", ""),
        "origin": getattr(meta, "origin", None),
        "created_at": getattr(meta, "created_at", ""),
        "identifier_type": getattr(meta, "identifier_type", None),
        "identifier": getattr(meta, "identifier", None),
        "has_otp": bool(getattr(meta, "has_otp", False)),
    })
    return out


def describe(pointer: str) -> str:
    """One line a reader can act on, or one saying why they cannot."""
    r = resolve(pointer)
    if not r["resolves"]:
        return "%s -> does not resolve (%s)" % (r["pointer"], r.get("reason", "unknown"))
    if r["form"] == ENV:
        return "%s -> set in this process" % r["pointer"]
    bits = [b for b in (r.get("kind"), r.get("label"), r.get("identifier"), r.get("origin")) if b]
    return "%s -> %s" % (r["pointer"], ", ".join(bits) or "a vault item")


def audit(texts) -> dict:
    """Every pointer across `texts`, split by whether it resolves.

    The dangling list is the one that matters: a masked belief pointing at
    something that is not there is a value nobody can recover, and the phase
    that wrote the pointer claimed otherwise."""
    seen, resolved, dangling, undecidable = [], [], [], []
    for text in texts or ():
        for p in pointers_in(text):
            if p in seen:
                continue
            seen.append(p)
            r = resolve(p)
            if r["resolves"]:
                resolved.append(p)
            elif r.get("reason") == "vault unavailable":
                undecidable.append(p)
            else:
                dangling.append((p, r.get("reason", "")))
    return {"pointers": len(seen), "resolved": resolved,
            "dangling": dangling, "undecidable": undecidable}
