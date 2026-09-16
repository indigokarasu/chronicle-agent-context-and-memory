"""
A1b read-surface probe — a deterministic, tree-agnostic dump of the two read
paths A1b puts behind the ACL choke point (goals and reflections), rendered for
the DEFAULT single-principal case (no `principals:` config).

The claim it exists to test: adding `owner`/`read_acl` to the goals and
reflections tables, stamping them on every write, and filtering
active_goals()/recall_similar_situations() through access.can_read changes
NOTHING for the deployment that has no ACL topology configured. Byte-identical
output against the pre-change tree (L10_A1, HEAD f14aa99) is the claim.

What is deliberately NOT in this dump, and why: the raw `goals`/`reflections`
ROWS. They legitimately gain two columns at schema_version 13, so comparing
them would be comparing the change to itself. The migration is asserted
directly instead (test_acl_topology.TestA1bLegacyRows,
TestA1bOldStoreUpgrade). Everything a CALLER can see is here, and it must not
move — which is also why the read surfaces project the two ACL columns back out
(ReasoningLayer._public) rather than letting them widen the returned dicts.

Same shape and the same freezing discipline as a1_surface_dump.py /
h1_store_dump.py: the clock and uuid4 are pinned before the engine runs,
because occurred_at feeds event_id which feeds belief_id, and because goal and
reflection ids are uuid4-derived and printed here.

Every call uses the PRE-A1b signature (no principal argument), so the identical
script runs against the old tree and the new one — which doubles as the
back-compat check: A1b's new parameters are trailing with defaults, so a caller
that never heard of them keeps working.

Usage:  python3 tests/a1b_surface_dump.py <tree_dir>
"""

import json
import os
import shutil
import sys
import tempfile

FROZEN_NOW = "2026-01-02T03:04:05.00Z"
FROZEN_LATER = "2026-01-02T03:14:05.00Z"

# Obviously fake people and companies, per the fixture rule.
TURNS = (
    ("My name is Pat Testley and I work at Acme Fake Co.", "Noted, Pat."),
    ("My office is in Fake City.", "Got it — Fake City."),
    ("Always use metric units when you answer me.", "Understood, metric from now on."),
)

GOALS = (
    "Ship the Fake City migration",
    "Keep the Acme Fake Co ledger reconciled",
    "Learn to sail",
)

# (situation, action, outcome, lesson, applicability)
REFLECTIONS = (
    ("Fake City migration rollback", "reverted the schema step",
     "recovered in ten minutes",
     "Always take a store snapshot before a schema step", "migrations"),
    ("Acme Fake Co ledger mismatch", "recounted from the journal",
     "found a duplicated entry",
     "Reconcile against the journal, never against the summary", "accounting"),
)


def _freeze_clock():
    """Pin the two sources of run-to-run variance: the clock and uuid4. See
    h1_store_dump._freeze_clock — this is that function, verbatim in effect."""
    import uuid

    counter = [0]

    def _fake_uuid4():
        # Shifted into the HIGH bits, unlike h1/a1_surface_dump's plain
        # UUID(int=n): goal and reflection ids are uuid4().hex[:12], and the
        # low-bit form zero-pads on the left, so every id in this probe would
        # collide on "000000000000" -- one goal row and one reflection row,
        # each overwriting the last. Deterministic either way; this one is also
        # distinct.
        counter[0] += 1
        return uuid.UUID(int=counter[0] << 96)

    uuid.uuid4 = _fake_uuid4
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "") or ""
        if not (name == "provider" or name == "context" or name.startswith("engine")):
            continue
        if hasattr(module, "now_iso"):
            setattr(module, "now_iso", lambda: FROZEN_NOW)
        if hasattr(module, "_iso_in"):
            setattr(module, "_iso_in", lambda *a, **kw: FROZEN_LATER)
        if hasattr(module, "uuid4"):
            setattr(module, "uuid4", _fake_uuid4)


def _j(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def dump_surfaces(core) -> str:
    """Render every A1b read surface, for the default principal, as text."""
    principal = core.active_principal
    reasoning = core.reasoning
    lines = []

    def emit(label, value):
        lines.append("%s\t%s" % (label, value if isinstance(value, str) else _j(value)))

    # 1. active_goals() — direct, and through the tool that renders it.
    emit("active_goals", reasoning.active_goals())
    emit("tool[active_goals]", core.tools.dispatch(principal, "chronicle_active_goals", {}))

    # 2. recall_similar_situations() — every fixture reflection, plus a query
    #    that matches nothing, plus one that matches both.
    for query in ("Fake City migration", "ledger", "sail", "nothing matches this"):
        emit("recall[%s]" % query, reasoning.recall_similar_situations(query))
        emit("recall_l1[%s]" % query, reasoning.recall_similar_situations(query, 1))

    # 3. plan_context() — where a reflection reaches user-visible output.
    for goal in GOALS + ("Fake City migration", "where is my office"):
        emit("plan_context[%s]" % goal, reasoning.plan_context(goal))
        emit("tool[plan_context][%s]" % goal,
             core.tools.dispatch(principal, "chronicle_plan_context", {"goal": goal}))

    return "\n".join(lines)


def run_flow(home: str) -> str:
    """One end-to-end flow at DEFAULT config, then the surface dump."""
    import engine.core  # noqa: F401  (import before freezing — see h1_store_dump)
    from provider import ChronicleMemoryProvider

    _freeze_clock()
    prov = ChronicleMemoryProvider()
    prov.initialize("s-a1b-probe", hermes_home=home, principal_id="assistant",
                    config={"embeddings": {"model": "hashing"}})
    for user, assistant in TURNS:
        prov.sync_turn(user, assistant, session_id="s-a1b-probe")
        prov.core.process_pending()
    core = prov.core

    # Goals: two through the tool surface (where a real agent creates them),
    # one through the direct API, and one status flip through update_goal.
    for goal in GOALS[:2]:
        core.tools.dispatch("assistant", "chronicle_remember_goal", {"goal": goal})
    gid = core.reasoning.remember_goal(GOALS[2])
    core.reasoning.update_goal(gid, "done")
    # ...and one update naming an id that does not exist, which upsert_goal
    # inserts. Pre-A1b that minted a row with no owner at all.
    core.reasoning.update_goal("goal_does_not_exist", "abandoned")

    # Reflections: one through the tool, one direct.
    s, a, o, lesson, app = REFLECTIONS[0]
    core.tools.dispatch("assistant", "chronicle_reflect",
                        {"situation": s, "action": a, "outcome": o,
                         "lesson": lesson, "applicability": app})
    core.reasoning.reflect(*REFLECTIONS[1])
    core.process_pending()
    return dump_surfaces(core)


def main() -> int:
    tree = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
    sys.path.insert(0, tree)
    os.environ["CHRONICLE_EMBED_MODEL"] = "hashing"
    home = tempfile.mkdtemp(prefix="a1bprobe-")
    try:
        sys.stdout.write(run_flow(home))
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
