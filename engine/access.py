"""
Chronicle — Access control logic (§15).

Pure ACL helpers shared by the reducer (grant/revoke) and every read path
(retrieval, context, reasoning). Default-allow within a user (I22); cross-user
isolation is absolute; restriction is explicit only (per-memory or per-agent).

read_acl encodings:
  - "user_agents"  : default — every one of the user's agents may read (I22)
  - "owner_only"   : only the owning principal
  - JSON object    : {"mode": "user_agents"|"owner_only", "allow": [...], "deny": [...]}

--------------------------------------------------------------------------
Principal topology (§15.8, issue #5)
--------------------------------------------------------------------------
Layered UNDER the per-memory ACL above: a declarative `principals:` config
section (users list + agents map) sets the CEILING can_read enforces before it
ever consults a memory's own read_acl. The per-memory ACL (grant/revoke/mode)
can only narrow within that ceiling — a runtime grant() can never widen a read
past what config declares (runtime tools narrow, never widen config-declared
edges). Cross-user reads are never implicit: the only way one user's principal
reads another user's data is an explicit config-declared `reads` edge.

Configured once from `principals:` config via configure_topology() (called by
ChronicleCore.__init__) into a module-level default so every existing
access.can_read call site — all ~15 of them across retrieval/derivation/
curation/tools/localdb/store — keeps working unchanged; the topology is
consulted at the one choke point. Tests can bypass the global entirely by
passing an explicit `topology=` (or `topology=None` for the pre-topology
legacy behavior).
"""

from __future__ import annotations

import json

DEFAULT_ACL = "user_agents"


class Topology:
    """A parsed `principals:` config section (§27, §15.8).

    principals:
      default_cross_agent_read: allow | deny   # posture for same-user peers
                                                  # with no explicit reads edge
      users: [user_id, ...]                    # optional explicit user roster
      agents:
        - id: agent_id
          user: user_id            # OR
          users: [user_id, ...]    #   (N:N — an agent shared by multiple users)
          reads: [principal_id, ...]  # explicit edges this agent may read FROM;
                                       # narrows the same-user default, and is
                                       # the ONLY way to declare an explicit
                                       # cross-user read (never implicit)
          sandbox: true|false      # true = no inbound reads ever, absolute veto
    """

    def __init__(self, principals_cfg: dict | None = None):
        cfg = principals_cfg or {}
        self.default_cross_agent_read = cfg.get("default_cross_agent_read", "allow")
        self.users: set = set(cfg.get("users") or [])
        self.agents: dict = {}
        for ag in cfg.get("agents") or []:
            aid = ag.get("id") or ag.get("principal_id")
            if not aid:
                continue
            users = set(ag.get("users") or ([ag["user"]] if ag.get("user") else []))
            self.users |= users
            reads = ag.get("reads")
            self.agents[aid] = {
                "users": users,
                "reads": set(reads) if reads is not None else None,
                "sandbox": bool(ag.get("sandbox", False)),
            }

    def users_of(self, principal: str) -> set:
        """Which user(s) `principal` belongs to. A config-declared agent uses
        its declared user/users; anything else falls back to the 'user:agent'
        namespace convention (user_of)."""
        ag = self.agents.get(principal)
        if ag and ag["users"]:
            return ag["users"]
        return {user_of(principal)}

    def is_sandboxed(self, principal: str) -> bool:
        ag = self.agents.get(principal)
        return bool(ag and ag["sandbox"])

    def declared_reads(self, principal: str):
        """The explicit `reads` edge set config declares for `principal`, or
        None if this principal declared none (falls through to the default
        same-user posture instead of being an authoritative — and possibly
        empty — ceiling)."""
        ag = self.agents.get(principal)
        return ag["reads"] if ag else None

    def explicit_edge(self, reader: str, target: str) -> bool:
        """True iff `reader`'s config-declared `reads` list explicitly names
        `target`. The only path to a cross-user grant; also narrows/widens
        within a user relative to the default posture."""
        reads = self.declared_reads(reader)
        return reads is not None and target in reads


# Module-level default, installed by ChronicleCore.__init__ from `principals:`
# config (configure_topology). None until configured == pre-topology legacy
# behavior (same-user allow, cross-user never), matching every existing
# can_read call site with zero changes required at the call site.
_ACTIVE_TOPOLOGY: "Topology | None" = None

# Sentinel so can_read can tell "topology not passed" (use the module default)
# apart from "topology=None passed explicitly" (force legacy/no-topology mode).
_UNSET = object()


def configure_topology(principals_cfg: dict | None) -> Topology:
    """Install the process-wide default topology from `principals:` config.
    Called once by ChronicleCore.__init__ — the one place config reaches the
    can_read choke point; no other call site changes."""
    global _ACTIVE_TOPOLOGY
    _ACTIVE_TOPOLOGY = Topology(principals_cfg)
    return _ACTIVE_TOPOLOGY


def reset_topology() -> None:
    """Test hook: drop back to no configured topology."""
    global _ACTIVE_TOPOLOGY
    _ACTIVE_TOPOLOGY = None


def active_topology() -> "Topology | None":
    return _ACTIVE_TOPOLOGY


def user_of(principal: str) -> str:
    """User a principal belongs to. Namespaced 'user:agent' supported; else the
    whole id (a single shared core = a single user, §15.7)."""
    return principal.split(":", 1)[0] if ":" in principal else "_user"


def _topology_ceiling(owner: str, principal: str, topology: "Topology | None") -> bool:
    """The declarative-config ceiling (§15.8): may `principal` read anything
    `owner` writes AT ALL, before the per-memory read_acl is even consulted?
    This is an absolute upper bound — per-memory ACL narrows within it, but a
    grant can never push a read past it. sandbox is an absolute veto that
    overrides even an explicit reads edge or default_cross_agent_read: allow.
    """
    if owner == principal:
        return True
    if topology is None:
        # No configured topology: legacy behavior, unchanged from before this
        # feature existed — allow within the same user, deny across users.
        return user_of(owner) == user_of(principal)
    if topology.is_sandboxed(owner):
        return False  # no inbound reads ever — absolute veto
    same_user = bool(topology.users_of(owner) & topology.users_of(principal))
    explicit = topology.explicit_edge(principal, owner)
    if not same_user:
        return explicit  # cross-user reads are never implicit — explicit edge only
    if explicit:
        return True
    declared = topology.declared_reads(principal)
    if declared is not None:
        # `principal` declared its own explicit reads list and owner isn't on
        # it — that list is authoritative and narrows away the same-user
        # default (a runtime widen elsewhere still can't cross this).
        return False
    return topology.default_cross_agent_read == "allow"


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


def can_read(read_acl, owner: str, principal: str, topology=_UNSET) -> bool:
    """I22 / §15.8 access rule.

    Ceiling first (declared topology: users/agents/reads/sandbox) — an
    absolute bound the per-memory ACL can only narrow, never widen. Then the
    familiar per-memory rule: allow iff (user_agents ∨ owner ∨ allow[P]) ∧
    ¬deny[P], evaluated only within whatever the ceiling already permitted.

    `topology` defaults to the module-configured active topology (set via
    configure_topology from `principals:` config); pass an explicit Topology
    to test in isolation, or `None` to force pre-topology legacy behavior.
    """
    topo = _ACTIVE_TOPOLOGY if topology is _UNSET else topology
    if not _topology_ceiling(owner, principal, topo):
        return False
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


# --------------------------------------------------------------------------
# Subject hygiene invariant (§15.8, issue #5)
# --------------------------------------------------------------------------

def validate_subject_grounding(entity_id: str, attribute: str) -> None:
    """A relational fact grounds on its own subject entity — works_at(person)
    — never smuggled onto another/generic subject as a `user.attr_*` composite
    key that packs the relation (and a hidden real subject) into the attribute
    name instead of using entity_id for the actual subject. Raises ValueError
    on violation; call it before a fact is durably logged (extraction /
    curation._emit_item) — never from the reducer's replay fold, which must
    stay a pure total function over whatever is already in the log (I3).
    """
    eid = (entity_id or "").strip()
    attr = (attribute or "").strip()
    if not attr:
        raise ValueError("fact attribute must not be empty")
    if "." in attr:
        raise ValueError(
            f"attribute {attr!r} is a dotted composite key; ground the fact on "
            f"its own subject entity_id instead of packing it onto "
            f"{entity_id!r}.{attr!r} (e.g. works_at(person), not "
            f"user.attr_works_at)")
    low = attr.lower()
    if low.startswith("attr_") or low.endswith("_attr") or "_attr_" in low:
        raise ValueError(
            f"attribute {attr!r} uses an 'attr_' escape-hatch composite key "
            f"instead of a plain subject-grounded predicate; ground it on its "
            f"own entity_id row instead of packing it onto entity_id={entity_id!r}")
    if "." in eid:
        raise ValueError(
            f"entity_id {entity_id!r} is a dotted composite key; the subject "
            f"must be its own entity, not a 'user.something' composite")
    if not eid:
        raise ValueError(f"relational fact {attr!r} has no subject entity_id to ground on")
