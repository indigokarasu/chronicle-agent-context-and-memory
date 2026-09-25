"""Rebuild the mentions index and queue duplicate-entity candidates.

    build_mentions.py --config CONFIG.yaml --db CHRONICLE.db [--dry-run] [--bind-ids]

Reads every configured source read-only. Writes `entity_mentions` (each
provider's rows replaced atomically) and `identity_candidates` (idempotent).
--bind-ids also binds each entity to the record that carries its own id
(same id = same entity), through the event log like any adjudicated link.
"""
import argparse
import itertools
import os
import sqlite3
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import mentions          # noqa: E402
from engine.config import Config     # noqa: E402

SHARED_LIMIT = 5   # an identifier shared by more people than this is reported, not paired


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--home", default=os.environ.get("HERMES_HOME", ""))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bind-ids", action="store_true")
    a = ap.parse_args()
    with open(a.config) as f:
        mem = (yaml.safe_load(f) or {}).get("memory") or {}
    cfg = Config(mem)
    if not cfg.get("mentions.enabled", True):
        print("mentions disabled")
        return 0
    r = mentions.Resolver(cfg).load_entities()
    print(f"entities with identifiers: {r.entity_count}, distinct keys: {len(r.key_to_entities)}")

    conn = sqlite3.connect(a.db, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    if not a.dry_run:
        mentions.ensure_schema(conn)
    for prov, (n, amb) in r.rebuild_all(conn, dry_run=a.dry_run).items():
        print(f"  {prov:12s} {n:7d} links  ({amb} identifier hits shared by several entities, not linked)")

    dups = r.duplicates()
    # Places sharing an address are as often neighbours in one building as one
    # place twice; without names that is not a question worth queueing. Only
    # entities without a store prefix (people) become merge candidates.
    places = [(k, e) for k, e in dups if r._store(e[0])]
    dups = [(k, e) for k, e in dups if not r._store(e[0])]
    small = [(k, e) for k, e in dups if len(e) <= SHARED_LIMIT]
    big = [(k, e) for k, e in dups if len(e) > SHARED_LIMIT]
    print(f"duplicate evidence: {len(small)} identifiers shared by 2-{SHARED_LIMIT} people; "
          f"{len(big)} shared more widely (reported only); "
          f"{len(places)} shared within one place store (reported only)")
    for k, e in big[:10]:
        print(f"    widely shared {k}: {len(e)} entities")
    if not a.dry_run and small:
        from engine.store import MemoryStore
        store = MemoryStore(a.db)
        queued = 0
        for k, ents in small:
            for x, y in itertools.combinations(ents, 2):
                if store.enqueue_identity_candidate("merge", x, y, "shared " + k, 1.0):
                    queued += 1
        print(f"  queued {queued} new merge candidates (identity_candidates)")

    if not a.dry_run:
        stub_candidates(conn, a.db)
    if a.bind_ids and not a.dry_run:
        bind(cfg, a, conn)
    return 0


def stub_candidates(conn, db):
    """Same-name entities where one side carries no identity at all.

    A shared name is not an identity, so nothing here merges. But an entity
    with a name and nothing else -- no identifier, no linked record -- next to
    one that has both, is most often the same person left behind by an import.
    Each such stub is PROPOSED as a merge into the identified entity, with that
    evidence, for review. Stubs with no identified namesake are proposed among
    themselves at lower confidence.
    """
    from engine.store import MemoryStore
    rows = conn.execute(
        "SELECT e.normalized_name, e.belief_id, "
        "  (SELECT count(*) FROM entity_mentions m WHERE m.entity_id=e.belief_id) AS n "
        "FROM entities e WHERE e.merged_into IS NULL AND coalesce(e.normalized_name,'')<>'' "
        "  AND e.normalized_name IN (SELECT normalized_name FROM entities WHERE merged_into IS NULL "
        "                            GROUP BY normalized_name HAVING count(*) > 1)").fetchall()
    groups = {}
    for name, eid, n in rows:
        groups.setdefault(name, []).append((eid, n))
    store, queued = MemoryStore(db), 0
    for name, members in groups.items():
        known = [e for e, n in members if n > 0]
        stubs = [e for e, n in members if n == 0]
        if len(known) == 1:
            for s_ in stubs:
                if store.enqueue_identity_candidate("merge", known[0], s_,
                                                    "same name; the other has no identifiers or records", 0.9):
                    queued += 1
        elif not known:
            for x, y in itertools.combinations(sorted(stubs), 2):
                if store.enqueue_identity_candidate("merge", x, y, "same name; neither has identifiers", 0.6):
                    queued += 1
    print(f"  same-name groups: {len(groups)}; queued {queued} new stub-merge candidates")


def bind(cfg, a, conn):
    """Bind entity X to the record whose id is X, via link_adjudicated events."""
    sys.path.insert(0, "/root/.hermes/hermes-agent")
    from engine.core import ChronicleCore
    home = a.home or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(a.db))))
    core = ChronicleCore(home, cfg._explicit if hasattr(cfg, "_explicit") else {})
    n = 0
    for src in cfg.get("mentions.record_sources", []) or []:
        if "id" not in (src.get("fields") or {}).values():
            continue
        prov = src["provider"]
        rows = conn.execute(
            "SELECT e.belief_id FROM entities e JOIN entity_mentions m "
            "ON m.entity_id=e.belief_id AND m.provider=? AND m.method='id' "
            "WHERE e.merged_into IS NULL AND (e.external_ref IS NULL OR e.external_ref='')",
            (prov,)).fetchall()
        for (eid,) in rows:
            core.tools._emit("federated", {
                "source_type": "federation", "kind": "link_adjudicated", "decision": "link",
                "entity_id": eid, "provider": prov, "external_id": f"{prov}:{eid}",
                "candidate_id": "", "adjudicated_by": "rule:exact_id"}, "assistant")
            n += 1
    print(f"  bound {n} entities to their own record (rule:exact_id)")


if __name__ == "__main__":
    sys.exit(main())
