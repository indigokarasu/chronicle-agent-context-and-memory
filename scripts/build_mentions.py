"""Rebuild the mentions index and queue duplicate-entity candidates.

    build_mentions.py [--config CONFIG.yaml] [--db CHRONICLE.db] [--home HERMES_HOME]
                      [--dry-run] [--bind-ids]

Left out, the home is the active Hermes home, the config is its config.yaml and
the store is the one that home's runtime uses (see engine/paths.py).

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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import mentions          # noqa: E402
from engine.config import Config     # noqa: E402
from engine.paths import readable_db_path, resolve_home   # noqa: E402
from engine.yaml_load import safe_load_file   # noqa: E402

SHARED_LIMIT = 5   # an identifier shared by more people than this is reported, not paired


def parse_args():
    """The command line, with the home, the config and the store filled in.

    Anything given wins. Left out: the home is the active Hermes home, the config
    is that home's config.yaml, and the store is the one its runtime uses (or the
    one an older release left, while it has not been moved yet).
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None, help="default: the home's config.yaml")
    ap.add_argument("--db", default=None, help="default: the home's store")
    ap.add_argument("--home", default="", help="the Hermes home; default: the active one")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bind-ids", action="store_true")
    a = ap.parse_args()
    a.home = resolve_home(a.home or None)
    config_path = a.config or os.path.join(a.home, "config.yaml")
    a.memory = {}
    # A config that was named must exist. The home's own may be absent (a fresh
    # install has none yet), and the defaults then apply.
    if a.config or os.path.exists(config_path):
        a.memory = (safe_load_file(config_path) or {}).get("memory") or {}
    a.config = config_path
    if not a.db:
        a.db = readable_db_path(Config(a.memory).get("db_path"), a.home)
    return a


def main() -> int:
    a = parse_args()
    cfg = Config(a.memory)
    if not cfg.get("mentions.enabled", True):
        print("mentions disabled")
        return 0
    if not os.path.isfile(a.db):
        print(f"no database at {a.db}", file=sys.stderr)
        return 2
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


def bind_core(cfg, a):
    """A core whose store is exactly the one that was read (`a.db`).

    The entity ids come from `a.db`, so the events that bind them must land in
    `a.db`: in any other store they name entities it does not hold, and an
    appended event cannot be taken back. `db_path` is `a.db`, absolute, and
    every other value of the config is kept.

    The core's home is `a.db` too, not a Hermes home. For an absolute
    `db_path`, a core takes the standard store of its home
    (`<home>/commons/db/chronicle/chronicle.db`) for the place a release
    before 5.12 kept it. When that file holds events, the core opens it
    instead of `db_path` (both hold events) or moves it onto `db_path` (`a.db`
    holds none yet). Under a real home that file is the home's own store: the
    events then landed in it, or it was taken from its profile. Under a file
    no store can be.

    Such a home gives no place for the git mirror, and setting up a mirror
    queues every event of the store for it. So this core sets up no mirror;
    that is for the store's own runtime, under its own home. The events it
    appends are still queued for the mirror when the config enables one.
    """
    from engine.core import ChronicleCore
    db = os.path.abspath(a.db)
    explicit = dict(cfg._explicit) if hasattr(cfg, "_explicit") else {}
    explicit["db_path"] = db
    git = explicit.get("git")
    explicit["git"] = dict(git if isinstance(git, dict) else {}, enabled=False)
    core = ChronicleCore(db, explicit)
    core.store.queue_git = bool(cfg.get("git.enabled", True))
    return core


def bind(cfg, a, conn):
    """Bind entity X to the record whose id is X, via link_adjudicated events."""
    core = bind_core(cfg, a)
    try:
        _bind_all(core, cfg, conn)
    finally:
        core.close()


def _bind_all(core, cfg, conn):
    """Emit one link_adjudicated event per entity a record names by its own id."""
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
