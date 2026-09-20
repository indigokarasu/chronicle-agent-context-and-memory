"""
Chronicle — what a masked value points AT (Phase E's resolver).

Masking leaves Hermes' sentinel with a pointer in it,
`«redacted:env:OPENROUTER_API_KEY»` or `«redacted:vault_ab12cd34ef56»`
(engine/credentials.py). Until now that pointer resolved through nothing: a
label copied out of the text that nobody could ask a question about. The
acceptance for this phase was "every pointer resolves correctly through
Hermes"; this is the half that makes that a question with an answer.

WHERE HERMES ACTUALLY KEEPS SECRETS — read off the live install, after
getting it wrong from a stale local copy of the source:

  * THE PROFILE ENV is the store with the values in it: `<HERMES_HOME>/.env`
    for the profile, the shared `.env` above it, optionally hydrated by
    `agent/secret_sources/` (bitwarden, command). Provider API keys live here.
    An `env:NAME` pointer names one of these.
  * THE VAULT (`agent/vault_backends/`) is for BROWSER LOGINS — what
    `browser_vault_fill` types into a page. Handles route across backends by
    prefix (`vault_…` local, `bw:…`, `op:…`) through `backend_for_handle`. A
    profile that does not save browser logins has an empty one, and that is
    not evidence about the profile's secrets.

The first version of this module looked only at the local vault, found it
empty, and reported that as the state of Hermes' secrets. It was reading the
browser-login store and calling it the secret store.

WHAT IT RETURNS, AND WHAT IT REFUSES TO RETURN. Names and metadata, never a
value. The host draws that boundary in three places of its own:
`VaultItemMeta` "never contains secret values"; `resolve_secret` is "for
server-side use ONLY. Callers must never place the returned values into tool
results, logs, exceptions, or any string that reaches the session DB"; and
`get_secret_source` is "Metadata only — never authorization to persist the raw
value." EVERY Chronicle surface — a belief, a recall block, a compaction
handoff, a tool result — reaches the session DB. So this reads key NAMES via
`secret_scope.load_env_file` and item METADATA via `get_meta`, and calls no
value accessor at all. Using a secret is the host's job, on a path that
registers it for redaction first; that path is not this one.

A pointer that does NOT resolve is the case worth having: a masked belief
naming something that is not there means the value behind it is gone and the
release that wrote the pointer implied otherwise. `audit()` finds those.

Where Hermes is not importable every lookup answers `resolves: False, reason:
"unavailable"` rather than raising, so a Chronicle that cannot see the host
degrades to "I cannot tell" instead of calling everything dangling.
"""

from __future__ import annotations

import os
import re

# The label inside Hermes' sentinel, as `credentials.SENTINEL` writes it.
_POINTER = re.compile(r"«redacted:([^»]+)»")
_ENV_REF = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")
# A vault HANDLE is not one shape -- `vault_…`, `bw:…`, `op:…` route across
# backends -- so this never pattern-matches one. Anything that is not `env:`
# and not a vendor ellipsis is offered to the host's own router, and the host
# decides whether a backend owns it.
_VENDOR_ELLIPSIS = "…"

VAULT, ENV, PREFIX, UNKNOWN = "vault", "env", "prefix", "unknown"


def pointers_in(text: str) -> list:
    """Every pointer label in `text`, in order, without duplicates."""
    return list(dict.fromkeys(_POINTER.findall(text or "")))


def form_of(pointer: str) -> str:
    """Which kind of reference this is. `env:` and the vendor ellipsis are
    decided here; everything else is a candidate handle only the host can
    route."""
    p = (pointer or "").strip()
    if _ENV_REF.match(p):
        return ENV
    if p.endswith(_VENDOR_ELLIPSIS):
        return PREFIX          # `ghp_…`: a vendor label, deliberately not a reference
    return VAULT if p else UNKNOWN


def _home():
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        return get_hermes_home()
    except Exception:
        return None


def env_names() -> frozenset:
    """Every key NAME Hermes' env store defines here, never a value.

    The profile `.env`, the shared `.env` above it, and what the running
    process actually has. Read with `secret_scope.load_env_file`, the same
    tokenizer that installs profile scopes, so a key this sees is a key the
    host sees."""
    names = set(os.environ)
    home = _home()
    if home is None:
        return frozenset(names)
    try:
        from pathlib import Path

        from agent.secret_scope import load_env_file  # type: ignore
    except Exception:
        return frozenset(names)
    home = Path(str(home))
    for path in (home / ".env", home.parent.parent / ".env"):
        try:
            if path.exists():
                names |= set(load_env_file(path))
        except Exception:      # a store we cannot read is not a store we guess at
            continue
    return frozenset(names)


def _source_of(name: str):
    """Which external source supplied `name` ("bitwarden" …), or None for a
    plain .env/shell key. The host documents this accessor as metadata only."""
    try:
        from hermes_cli.env_loader import get_secret_source  # type: ignore
        return get_secret_source(name)
    except Exception:
        return None


def _backend(handle: str):
    """The backend that owns `handle`, or None.

    `backend_for_handle` is Hermes' own router across local / Bitwarden /
    1Password, so Chronicle never has to know the handle grammar or which
    backends a profile enabled. The fallback covers a Hermes predating the
    vault_backends package."""
    try:
        from agent.vault_backends import backend_for_handle  # type: ignore
        return backend_for_handle(handle)
    except Exception:
        pass
    try:
        from agent.vault_store import get_vault_store  # type: ignore
        store = get_vault_store()
        return store if hasattr(store, "get_meta") else None
    except Exception:
        return None


def backends_live() -> list:
    """Which login backends this profile has enabled, for a reader who wants
    to know where a handle would even be looked up."""
    try:
        from agent.vault_backends import enabled_backends  # type: ignore
        return [type(b).__name__ for b in (enabled_backends() or ())]
    except Exception:
        return []


def resolve(pointer: str) -> dict:
    """What `pointer` names. METADATA ONLY — never a secret value.

    `resolves` is the whole point: False means a masked belief is pointing at
    something that is not there."""
    p = (pointer or "").strip()
    form = form_of(p)
    out = {"pointer": p, "form": form, "resolves": False}

    if form == ENV:
        name = _ENV_REF.match(p).group(1)
        out["name"] = name
        # Defined-ness only. The value is never read, returned or logged.
        out["resolves"] = name in env_names()
        src = _source_of(name)
        if src:
            out["source"] = src
        if not out["resolves"]:
            out["reason"] = "not defined in this profile's env store or the process"
        return out

    if form == PREFIX:
        out["reason"] = "a vendor prefix says what KIND of credential it was, not which one"
        return out

    if form != VAULT:
        out["reason"] = "not a reference Chronicle knows how to resolve"
        return out

    store = _backend(p)
    if store is None:
        out["reason"] = "unavailable"          # cannot tell, not "dangling"
        return out
    out["backend"] = type(store).__name__
    try:
        meta = store.get_meta(p)
    except Exception as e:     # noqa: BLE001 -- a lookup may never raise out of here
        # A locked external manager raises rather than answering; that is
        # "cannot tell", not "this handle is dead".
        locked = type(e).__name__ == "UnlockRequired"
        out["reason"] = "unavailable" if locked else "lookup failed: %s" % type(e).__name__
        return out
    if meta is None:
        out["reason"] = "no vault item with that handle"
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
        src = r.get("source")
        return "%s -> defined%s" % (r["pointer"], " (via %s)" % src if src else "")
    bits = [b for b in (r.get("kind"), r.get("label"), r.get("identifier"), r.get("origin")) if b]
    return "%s -> %s" % (r["pointer"], ", ".join(bits) or "a vault item")


def audit(texts) -> dict:
    """Every pointer across `texts`, split by whether it resolves.

    The dangling list is the one that matters: a masked belief pointing at
    something that is not there is a value nobody can recover, and the release
    that wrote the pointer implied otherwise."""
    seen, resolved, dangling, undecidable = [], [], [], []
    for text in texts or ():
        for p in pointers_in(text):
            if p in seen:
                continue
            seen.append(p)
            r = resolve(p)
            if r["resolves"]:
                resolved.append(p)
            elif r.get("reason") == "unavailable":
                undecidable.append(p)
            else:
                dangling.append((p, r.get("reason", "")))
    return {"pointers": len(seen), "resolved": resolved,
            "dangling": dangling, "undecidable": undecidable}
