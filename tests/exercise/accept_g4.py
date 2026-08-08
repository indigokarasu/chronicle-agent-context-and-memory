"""
Acceptance — g4: the federate_sweep curation job (§14).

Every fixture database here is synthetic and obviously fake (Pat Testley of Acme
Fake Co). Nothing in the engine knows any real deployment's schema: the tables
below exist only in this file, and the sweep learns about them exclusively
through `federation.local_dbs` config.

What is proved:
  1. a sweep turns rows into pointers + cached projections carrying content hashes
  2. an unchanged re-sweep writes nothing (same pointer id, no new events)
  3. MUTATING a row and re-sweeping WITH NO CURSOR HELP updates exactly that
     projection, its hash, and emits exactly one event — the sweep finds edits
     to already-ingested rows by itself, which a watermark alone cannot do
  4. a name collision is QUEUED for review and never auto-linked; an exact
     external_ref match refreshes its link instead
  5. adjudication (the only path to a link) survives a full projection rebuild
  6. the per-run row budget bounds the work and the watermark advances
  7. a name_column is genuinely optional
  8. an offline provider is skipped (job done); a bad table/column FAILS the job
  9. entities the sweeping principal may not read are neither linked nor proposed

Run: CHRONICLE_EMBED_MODEL=hashing /usr/bin/python3 tests/exercise/accept_g4.py
"""

import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import ChronicleCore

CONTACTS_SCHEMA = """
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT,
    org TEXT
);
"""

_HOMES = []


def _core():
    home = tempfile.mkdtemp(prefix="chronicle-g4-")
    _HOMES.append(home)
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
    core.set_active_principal("assistant")
    return core


def _fixture_db(rows):
    """A synthetic contacts DB. `rows` are (id, full_name, email, org) tuples."""
    path = tempfile.mktemp(prefix="acme-fake-", suffix=".db")
    conn = sqlite3.connect(path)
    conn.executescript(CONTACTS_SCHEMA)
    conn.executemany("INSERT INTO contacts(id, full_name, email, org) VALUES(?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return path


def _register(core, path, **overrides):
    spec = {"name": "fixture_contacts", "path": path, "table": "contacts", "id_column": "id",
            "name_column": "full_name", "content_columns": ["email", "org"],
            "capability": "contacts", "read_only": True}
    spec.update(overrides)
    core.cfg._d["federation"]["local_dbs"] = [spec]
    return spec


def _sweep(core):
    core.store.enqueue_curation("federate_sweep", {})
    core.curation.drain(max_jobs=10)


def _pointers(core, provider="fixture_contacts"):
    return {r["external_id"]: dict(r) for r in core.store._conn().execute(
        "SELECT * FROM pointers WHERE provider=?", (provider,)).fetchall()}


def _projection(ptr):
    return json.loads(ptr["cached_projection"])


def _events(core):
    return core.store.get_events_by_type("federated")


def _payload(ev):
    return json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]


def _job_rows(core):
    return core.store.get_curation_jobs("task='federate_sweep'")


def _new_entity(core, name, owner="assistant", read_acl="user_agents"):
    """A person entity created through the NORMAL capture/event path — an
    'asserted' event of kind='entity' — exactly like production entities. This
    matters because reducer.rebuild() truncates the projection and replays only
    logged events (I3): an entity that was never captured as an event has
    nothing to replay from and is correctly, legitimately gone after a rebuild.
    A raw INSERT into the entities table would be a fixture bypassing the log,
    not a case the engine needs to handle.

    read_acl is applied as a direct field set after creation (mirroring how
    chronicle_set_acl in tools.py works — itself not event-sourced) rather than
    threaded through the capture event, because entity capture always assigns
    access.DEFAULT_ACL (§15 identity facts are visible to all of the owner's
    agents by default) and no acceptance test here needs a non-default ACL to
    survive a rebuild — the ACL cases here (test 9) turn on cross-user
    isolation (different `owner`), which the capture path already honors.
    """
    key = {"entity_type": "person", "name": name, "normalized_name": name.lower()}
    source_event = "fixture-entity-%s" % uuid.uuid4().hex
    core.capture.append("asserted", {"kind": "entity", "key": key, "body": name,
                                     "source_event": source_event},
                        owner=owner, actor="user", trust_level=3)
    row = core.store.query_beliefs(
        "entities", "owner=? AND normalized_name=?", (owner, name.lower()), limit=1)[0]
    bid = row["belief_id"]
    if read_acl != "user_agents":
        core.store.update_belief("entities", bid, read_acl=read_acl)
    return bid


# -- 1. pointers + cached projections ------------------------------------------

def test_sweep_creates_pointers_and_projections():
    core = _core()
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co"),
                      (2, "Robin Placeholder", "robin@acme-fake.example", "Acme Fake Co"),
                      (3, "Sam Stand-In", "sam@acme-fake.example", "Fake Industries")])
    _register(core, db)
    _sweep(core)

    ptrs = _pointers(core)
    assert set(ptrs) == {"fixture_contacts:1", "fixture_contacts:2", "fixture_contacts:3"}, ptrs
    for ext_id, ptr in ptrs.items():
        proj = _projection(ptr)
        assert proj["content_hash"], "no content hash in %s" % ext_id
        assert proj["fields"]["email"].endswith(".example")
        assert ptr["capability"] == "contacts" and ptr["cache_ttl"]
    assert len(_events(core)) == 3, "one provenance event per ingested row"
    st = core.store.get_federation_state("fixture_contacts")
    assert st["last_row_id"] == 3, st
    print("PASS 1: 3 pointers + projections + hashes, watermark=%d" % st["last_row_id"])


# -- 2. unchanged re-sweep is a no-op ------------------------------------------

def test_unchanged_resweep_writes_nothing():
    core = _core()
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co")])
    _register(core, db)
    _sweep(core)
    before = _pointers(core)["fixture_contacts:1"]

    _sweep(core)
    after = _pointers(core)["fixture_contacts:1"]
    assert after["id"] == before["id"], "pointer id must be stable across sweeps"
    assert after["cached_projection"] == before["cached_projection"]
    assert len(_events(core)) == 1, "unchanged rows must not emit events"
    assert [j["status"] for j in _job_rows(core)] == ["done", "done"]
    print("PASS 2: unchanged re-sweep wrote nothing (1 event total)")


# -- 3. THE PROBE: mutate a row, re-sweep, no cursor help ----------------------

def test_mutation_is_found_without_touching_cursors():
    """The failure this test exists for: a sweep that only ever reads
    `id > watermark` can never see an edit, because an edited row keeps its id.
    Nothing below resets a watermark or a cursor."""
    core = _core()
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co"),
                      (2, "Robin Placeholder", "robin@acme-fake.example", "Acme Fake Co"),
                      (3, "Sam Stand-In", "sam@acme-fake.example", "Fake Industries")])
    _register(core, db)
    _sweep(core)
    before = {k: _projection(v) for k, v in _pointers(core).items()}
    before_ids = {k: v["id"] for k, v in _pointers(core).items()}
    events_before = len(_events(core))
    state_before = core.store.get_federation_state("fixture_contacts")

    conn = sqlite3.connect(db)
    conn.execute("UPDATE contacts SET email=? WHERE id=?", ("pat.testley@acme-fake.example", 1))
    conn.commit()
    conn.close()

    _sweep(core)                                   # no reset, no cursor surgery

    after = {k: _projection(v) for k, v in _pointers(core).items()}
    changed = [k for k in after if after[k]["content_hash"] != before[k]["content_hash"]]
    assert changed == ["fixture_contacts:1"], "expected only row 1 to change, got %s" % changed
    assert after["fixture_contacts:1"]["fields"]["email"] == "pat.testley@acme-fake.example"
    for k in after:
        if k != "fixture_contacts:1":
            assert after[k] == before[k], "untouched row %s was rewritten" % k
    assert _pointers(core)["fixture_contacts:1"]["id"] == before_ids["fixture_contacts:1"], \
        "refreshing a projection must not change the pointer id"
    assert len(_events(core)) == events_before + 1, \
        "expected exactly 1 new event, got %d" % (len(_events(core)) - events_before)
    payload = _payload(_events(core)[-1])
    assert payload["source_type"] == "federation" and payload["provider"] == "fixture_contacts"
    assert payload["content_hash"] == after["fixture_contacts:1"]["content_hash"], \
        "event hash must match the projection it describes"
    assert payload["pointer_id"] == before_ids["fixture_contacts:1"]
    assert core.store.get_federation_state("fixture_contacts")["last_row_id"] == \
        state_before["last_row_id"], "an edit must not move the ingest watermark"
    print("PASS 3: mutation found with no cursor help — 1 projection, 1 hash, 1 event")


# -- 4. name collision → review queue; exact ref → refresh ---------------------

def test_name_collision_queues_candidate_and_never_links():
    core = _core()
    ent = _new_entity(core, "Pat Testley")
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co"),
                      (2, "Nobody Here", "nobody@acme-fake.example", "Fake Industries")])
    _register(core, db)
    _sweep(core)

    row = core.store.get_belief("entities", ent)
    assert not row.get("external_ref"), "entity was AUTO-LINKED: %r" % row.get("external_ref")
    assert not row.get("external_provider"), "entity was auto-linked to a provider"

    cands = core.store.get_link_candidates()
    assert [(c["entity_id"], c["external_ref"]) for c in cands] == [(ent, "fixture_contacts:1")], cands
    assert cands[0]["candidate_reason"] == "name_collision"
    assert cands[0]["provider"] == "fixture_contacts"

    _sweep(core)                                   # rescan sees the same collision
    assert len(core.store.get_link_candidates()) == 1, "candidate must not be duplicated"

    # The review queue is readable through the tool surface, ACL-filtered.
    listed = json.loads(core.tools.dispatch("assistant", "chronicle_list_link_candidates", {}))
    assert [c["entity_id"] for c in listed["link_candidates"]] == [ent], listed
    print("PASS 4: collision queued once, entity untouched, visible for review")


def test_exact_external_ref_refreshes_link():
    core = _core()
    ent = _new_entity(core, "Pat Testley")
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co")])
    _register(core, db)
    _sweep(core)

    cand = core.store.get_link_candidates()[0]
    out = json.loads(core.tools.dispatch("assistant", "chronicle_review_link_candidate",
                                         {"candidate_id": cand["id"], "decision": "link"}))
    assert out.get("event_id"), out
    row = core.store.get_belief("entities", ent)
    assert row["external_ref"] == "fixture_contacts:1" and row["external_provider"] == "fixture_contacts"
    assert core.store.get_link_candidates() == [], "adjudicated candidate should leave the queue"

    conn = sqlite3.connect(db)
    conn.execute("UPDATE contacts SET org=? WHERE id=?", ("Fake Industries", 1))
    conn.commit()
    conn.close()
    _sweep(core)

    payload = _payload(_events(core)[-1])
    assert payload["linked_entities"] == [ent], "exact-ref match must refresh the link: %s" % payload
    assert core.store.get_link_candidates() == [], "a linked row must not also be proposed"
    print("PASS 4b: exact external_ref refreshed the link, no new candidate")


# -- 5. adjudicated link survives a rebuild ------------------------------------

def test_adjudicated_link_survives_rebuild():
    core = _core()
    ent = _new_entity(core, "Pat Testley")
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co")])
    _register(core, db)
    _sweep(core)
    cand = core.store.get_link_candidates()[0]
    core.tools.dispatch("assistant", "chronicle_review_link_candidate",
                        {"candidate_id": cand["id"], "decision": "link"})

    core.reducer.rebuild()
    row = core.store.get_belief("entities", ent)
    assert row and row["external_ref"] == "fixture_contacts:1", \
        "the decision must replay from the log, got %r" % (row or {}).get("external_ref")
    print("PASS 5: adjudicated link replayed from the event log")


# -- 6. bounded work per run ----------------------------------------------------

def test_row_budget_bounds_each_run():
    core = _core()
    rows = [(i, "Contact %d" % i, "c%d@acme-fake.example" % i, "Acme Fake Co")
            for i in range(1, 461)]
    db = _fixture_db(rows)
    _register(core, db, name_column="")            # names are noise here
    _sweep(core)
    assert len(_pointers(core)) == 200, len(_pointers(core))
    st = core.store.get_federation_state("fixture_contacts")
    assert (st["last_row_id"], st["rescan_cursor"]) == (200, 0), st

    _sweep(core)
    assert len(_pointers(core)) == 400
    st = core.store.get_federation_state("fixture_contacts")
    assert (st["last_row_id"], st["rescan_cursor"]) == (400, 0), st

    _sweep(core)                                   # 60 new + 140 rescanned
    assert len(_pointers(core)) == 460
    st = core.store.get_federation_state("fixture_contacts")
    assert st["last_row_id"] == 460, st
    assert st["rescan_cursor"] == 140, "rescan should have used the leftover budget: %s" % st
    assert len(_events(core)) == 460, "no row should be ingested twice"
    print("PASS 6: 200-row budget honored per run (200 -> 400 -> 460, cursor at 140)")


# -- 7. name_column is optional -------------------------------------------------

def test_name_column_optional():
    core = _core()
    _new_entity(core, "Pat Testley")
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co")])
    _register(core, db, name_column="")
    _sweep(core)
    assert [j["status"] for j in _job_rows(core)] == ["done"], _job_rows(core)
    proj = _projection(_pointers(core)["fixture_contacts:1"])
    assert proj["display"] == "" and proj["fields"]["email"]
    assert core.store.get_link_candidates() == [], "no name column -> nothing to propose"
    print("PASS 7: sweep runs with no name_column configured")


# -- 8. offline provider skips; broken config fails -----------------------------

def test_offline_provider_is_skipped():
    core = _core()
    _register(core, "/nonexistent/acme-fake/contacts.db")
    _sweep(core)
    jobs = _job_rows(core)
    assert [j["status"] for j in jobs] == ["done"], jobs
    assert not jobs[0]["error"], jobs[0]["error"]
    print("PASS 8: offline provider skipped, job done")


def test_bad_config_fails_the_job():
    core = _core()
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co")])
    _register(core, db, table="no_such_table")
    _sweep(core)
    jobs = _job_rows(core)
    assert [j["status"] for j in jobs] == ["failed"], jobs
    assert "no_such_table" in (jobs[0]["error"] or "")

    core2 = _core()
    _register(core2, db, content_columns=["email", "no_such_column"])
    _sweep(core2)
    jobs2 = _job_rows(core2)
    assert [j["status"] for j in jobs2] == ["failed"], jobs2
    assert "no_such_column" in (jobs2[0]["error"] or "")
    print("PASS 8b: unrunnable config fails the job (table + column)")


# -- 9. ACL ---------------------------------------------------------------------

def test_unreadable_entities_are_not_proposed():
    core = _core()
    mine = _new_entity(core, "Pat Testley", owner="assistant")
    _new_entity(core, "Pat Testley", owner="otheruser:agent", read_acl="owner_only")
    db = _fixture_db([(1, "Pat Testley", "pat@acme-fake.example", "Acme Fake Co")])
    _register(core, db)
    _sweep(core)
    cands = core.store.get_link_candidates()
    assert [c["entity_id"] for c in cands] == [mine], \
        "only entities the sweeping principal can read may be proposed: %s" % cands
    print("PASS 9: cross-principal entity neither linked nor proposed")


def main():
    tests = [test_sweep_creates_pointers_and_projections,
             test_unchanged_resweep_writes_nothing,
             test_mutation_is_found_without_touching_cursors,
             test_name_collision_queues_candidate_and_never_links,
             test_exact_external_ref_refreshes_link,
             test_adjudicated_link_survives_rebuild,
             test_row_budget_bounds_each_run,
             test_name_column_optional,
             test_offline_provider_is_skipped,
             test_bad_config_fails_the_job,
             test_unreadable_entities_are_not_proposed]
    try:
        for t in tests:
            t()
    finally:
        for home in _HOMES:
            shutil.rmtree(home, ignore_errors=True)
    print("\nAll g4 acceptance tests passed (%d)." % len(tests))


if __name__ == "__main__":
    main()
