"""
Chronicle — Access control logic (§15).

Pure ACL helpers shared by the reducer (grant/revoke) and every read path
(retrieval, context, reasoning). Default-allow within a user (I22); cross-user
isolation is absolute; restriction is explicit only (per-memory or per-agent).

read_acl encodings:
  - "user_agents"  : default — every one of the user's agents may read (I22)
  - "owner_only"   : only the owning principal
  - JSON object    : {"mode": "user_agents"|"owner_only", "allow": [...], "deny": [...]}
"""

from __future__ import annotations

import json

DEFAULT_ACL = "user_agents"


def user_of(principal: str) -> str:
    """User a principal belongs to. Namespaced 'user:agent' supported; else the
    whole id (a single shared core = a single user, §15.7)."""
    return principal.split(":", 1)[0] if ":" in principal else "_user"


def parse_acl(read_acl) -> dict:
    if not read_acl or read_acl == DEFAULT_ACL:
        return {"mode": "user_agents", "allow": set(), "deny": set()}
    if read_acl == "owner_only":
        return {"mode": "owner_only", "allow": set(), "deny": set()}
    if isinstance(read_acl, str) and read_acl.startswith("{"):
        try:
            d = json.loads(read_acl)
            return {"mode": d.get("mode", "user_agents"),
                    "allow": set(d.get("allow", [])), "deny": set(d.get("deny", []))}
        except Exception:
            return {"mode": "user_agents", "allow": set(), "deny": set()}
    return {"mode": "user_agents", "allow": set(), "deny": set()}


def dump_acl(mode: str, allow: set[str], deny: set[str]) -> str:
    if mode == "user_agents" and not allow and not deny:
        return DEFAULT_ACL
    if mode == "owner_only" and not allow and not deny:
        return "owner_only"
    return json.dumps({"mode": mode, "allow": sorted(allow), "deny": sorted(deny)}, sort_keys=True)


def can_read(read_acl, owner: str, principal: str) -> bool:
    """I22 access rule: allow iff same user AND (user_agents ∨ owner ∨ allow[P]) AND ¬deny[P]."""
    if user_of(owner) != user_of(principal):
        return False  # cross-user never
    acl = parse_acl(read_acl)
    if principal in acl["deny"]:
        return False
    if owner == principal:
        return True
    if acl["mode"] == "user_agents":
        return True
    return principal in acl["allow"]


def grant(read_acl, principal: str) -> str:
    acl = parse_acl(read_acl)
    acl["allow"].add(principal)
    acl["deny"].discard(principal)
    return dump_acl(acl["mode"], acl["allow"], acl["deny"])


def revoke(read_acl, principal: str) -> str:
    acl = parse_acl(read_acl)
    acl["deny"].add(principal)
    acl["allow"].discard(principal)
    return dump_acl(acl["mode"], acl["allow"], acl["deny"])


def make_private(owner: str) -> str:
    return "owner_only"
