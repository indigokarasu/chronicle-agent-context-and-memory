"""
A1 read-surface probe — a deterministic, tree-agnostic dump of every read path
A1 puts behind the ACL choke point, rendered for the DEFAULT single-principal
case (no `principals:` config, so access.can_read's ceiling is the legacy
same-user allow).

The claim it exists to test: adding the choke point to the directive block,
get_directives()/static_block(), chronicle_list_directives, history(), as_of(),
explain() and the contradiction listings changes NOTHING for the deployment
that has no ACL topology configured. Byte-identical output against the
pre-change tree is the claim; anything else is a regression, wherever it came
from. (tests/test_acl_topology.py runs this against both trees and diffs.)

Same shape and the same freezing discipline as h1_store_dump.py: the clock and
uuid4 are pinned before the engine runs, because occurred_at feeds event_id
which feeds belief_id, and every surface below prints belief ids.

Every call here uses the PRE-A1 call signature (no principal argument) so the
identical script runs against the old tree and the new one — which is also the
back-compat check: A1's new parameters are keyword-only with defaults, so a
caller that never heard of them keeps working.

Usage:  python3 tests/a1_surface_dump.py <tree_dir>
"""

import json
import os
import shutil
import sys
import tempfile

FROZEN_NOW = "2026-01-02T03:04:05.00Z"
FROZEN_LATER = "2026-01-02T03:14:05.00Z"

# Obviously fake people and companies, per the fixture rule. Shaped to produce
# every surface this probe renders: a directive (norm note), facts that
# supersede each other (a history chain), and a derived belief (explain).
TURNS = (
    ("My name is Pat Testley and I work at Acme Fake Co.", "Noted, Pat."),
    ("My office is in Fake City.", "Got it — Fake City."),
    ("Always use metric units when you answer me.", "Understood, metric from now on."),
    ("Never send email on my behalf without asking.", "Understood."),
    ("Actually I moved — my office is in Other Fake City now.", "Updated."),
)


def _freeze_clock():
    """Pin the two sources of run-to-run variance: the clock and uuid4. See
    h1_store_dump._freeze_clock — this is that function, verbatim in effect."""
    import uuid

    counter = [0]

    def _fake_uuid4():
        counter[0] += 1
        return uuid.UUID(int=counter[0])

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


def dump_surfaces(core, provider) -> str:
    """Render every A1 read surface, for the default principal, as text."""
    principal = core.active_principal
    lines = []

    def emit(label, value):
        lines.append("%s\t%s" % (label, value if isinstance(value, str) else _j(value)))

    # 1. get_context's unconditional [DIRECTIVE] block (and the whole block it
    #    sits in — contradictions and criticals share its budget ledger).
    for hint in ("what units should you use", "where is my office", "email"):
        emit("get_context[%s]" % hint,
             core.retrieval.get_context(hint, principal=principal))

    # 2. get_directives() -> 3. static_block() -> the system prompt itself.
    emit("get_directives", core.retrieval.get_directives())
    emit("static_block", core.retrieval.static_block(principal))
    emit("system_prompt_block", provider.system_prompt_block())

    # 4. the chronicle_list_directives tool surface (and its neighbours).
    for tool in ("list_directives", "list_contradictions"):
        emit("tool[%s]" % tool, core.tools.dispatch(principal, "chronicle_" + tool, {}))

    # 5/6/7. history / as_of / changes_since / explain, over every belief id in
    #        the store so the probe cannot miss the one row that differs.
    bids = []
    for table in ("facts", "notes", "episodes", "relationships", "procedures", "refs"):
        for row in core.store.query_beliefs(table, "1=1", (), 200, order="belief_id"):
            bids.append(row["belief_id"])
    emit("belief_ids", sorted(bids))
    for bid in sorted(bids):
        emit("history[%s]" % bid, core.retrieval.history(bid))
        emit("explain[%s]" % bid, core.derivation.explain(bid))
        emit("tool_history[%s]" % bid,
             core.tools.dispatch(principal, "chronicle_history", {"belief_id": bid}))
        emit("tool_explain[%s]" % bid,
             core.tools.dispatch(principal, "chronicle_explain", {"belief_id": bid}))
    emit("as_of", sorted(_j(r) for r in core.retrieval.as_of()))
    emit("as_of_world", sorted(_j(r) for r in core.retrieval.as_of(world=FROZEN_LATER)))
    emit("changes_since", core.retrieval.changes_since("2020-01-01T00:00:00Z"))
    emit("open_contradictions_raw", core.store.get_open_contradictions(50))

    # The neighbouring surfaces the A1 sweep also touched.
    emit("tool[plan_context]", core.tools.dispatch(
        principal, "chronicle_plan_context", {"goal": "book a flight"}))
    emit("tool[what_user_knows]", core.tools.dispatch(
        principal, "chronicle_what_user_knows", {"topic": "office"}))
    emit("tool[set_acl_missing]", core.tools.dispatch(
        principal, "chronicle_set_acl", {"belief_id": "b_nope", "visibility": "private"}))

    return "\n".join(lines)


def run_flow(home: str) -> str:
    """One end-to-end flow at DEFAULT config, then the surface dump."""
    import engine.core  # noqa: F401  (import before freezing — see h1_store_dump)
    from provider import ChronicleMemoryProvider

    _freeze_clock()
    prov = ChronicleMemoryProvider()
    prov.initialize("s-a1-probe", hermes_home=home, principal_id="assistant",
                    config={"embeddings": {"model": "hashing"}})
    for user, assistant in TURNS:
        prov.sync_turn(user, assistant, session_id="s-a1-probe")
        prov.core.process_pending()
    prov.on_session_end([])
    prov.core.process_pending()
    # A contradiction to list: two conflicting single-valued facts, recorded
    # through the tool surface the way a real agent would create one.
    for value in ("Fake City", "Third Fake City"):
        prov.core.tools.dispatch("assistant", "chronicle_remember",
                                 {"kind": "fact", "content": value,
                                  "entity": "user", "attribute": "office_location"})
    prov.core.process_pending()
    return dump_surfaces(prov.core, prov)


def main() -> int:
    tree = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
    sys.path.insert(0, tree)
    os.environ["CHRONICLE_EMBED_MODEL"] = "hashing"
    home = tempfile.mkdtemp(prefix="a1probe-")
    try:
        sys.stdout.write(run_flow(home))
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
