#!/usr/bin/env python3
"""Acceptance test for g3 — the federated query channel.

Chronicle asks every database declared in `federation.local_dbs` one generic
question — "does any text column of any table LIKE any of these focus tokens?" —
and merges the matching rows into get_context as

    [FEDERATED <db>] <table>:<row_id> | col=val; col=val

after all of its own evidence, out of leftover budget only.

What is checked here:
  * the channel produces [FEDERATED …] blocks when it is on, and none when off;
  * a tiny budget starves it (raw session evidence keeps first claim, r1);
  * every block carries a pointer that identifies a ROW, not just a database;
  * a table named `order` with a column named `ship to` does not abort the rest
    of the database — the other tables still return rows;
  * the connection is read-only and a missing file is an error, never a
    silently-created empty database;
  * access.can_read gates every read (owner_only, cross-user);
  * nothing is auto-linked to a Chronicle entity: rows become review candidates;
  * the declared bounds (<=3 DBs, <=5 rows/table) hold.

Fixtures build their own SQLite files with obviously-fake data (Pat Testley,
Acme Fake Co, Testland). No real deployment database is referenced, here or in
engine/.
"""

import os
import sqlite3
import sys
import tempfile

chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore
from engine.config import Config
from engine.federated import FederatedChannel
from engine.localdb import LocalDBProvider, providers_from_config

QUERY = "who do I know in testland"
DB_NAME = "testdb"

_STATE = {}


# -- fixtures ---------------------------------------------------------------

def _build_fixture_db(path):
    """A deliberately awkward foreign schema, built with obviously-fake data.

    - contacts     : ordinary INTEGER PRIMARY KEY table (the pointer happy path)
    - order        : RESERVED WORD table name, with a column named `ship to`
                     and a quote in a value — the case that aborts naive
                     introspection and takes the whole database with it
    - no_key_log   : no primary key at all (pointer falls back to rowid)
    - wor_pairs    : WITHOUT ROWID + composite key (no addressable row id)
    """
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE contacts (
                       id INTEGER PRIMARY KEY, full_name TEXT, employer TEXT,
                       residence TEXT, avatar BLOB)""")
    cur.executemany(
        "INSERT INTO contacts (id, full_name, employer, residence, avatar) VALUES (?,?,?,?,?)",
        [(1, "Pat Testley", "Acme Fake Co", "Testland", b"\x00\x01binary"),
         (2, "Sam Rivera", "Globex Testing Ltd", "Fakeville", None),
         (3, "Jordan Kwan", "Initech Sample Inc", "Testland", None),
         (4, "Casey Okafor", "Acme Fake Co", "Mockshire", None),
         (5, "Riley Chen", "Globex Testing Ltd", "Testland", None),
         (6, "Alex Nobody", "Acme Fake Co", "Testland", None),
         (7, "Robin Placeholder", "Acme Fake Co", "Testland", None)])

    cur.execute('CREATE TABLE "order" (id INTEGER PRIMARY KEY, "ship to" TEXT, memo TEXT)')
    cur.executemany('INSERT INTO "order" (id, "ship to", memo) VALUES (?,?,?)',
                    [(10, "Testland", 'crate marked "fragile"'),
                     (11, "Mockshire", "no memo")])

    cur.execute("CREATE TABLE no_key_log (line TEXT)")
    cur.executemany("INSERT INTO no_key_log (line) VALUES (?)",
                    [("shipment reached Testland",), ("unrelated line",)])

    cur.execute("CREATE TABLE wor_pairs (a TEXT, b TEXT, PRIMARY KEY (a, b)) WITHOUT ROWID")
    cur.executemany("INSERT INTO wor_pairs (a, b) VALUES (?,?)",
                    [("Testland", "depot"), ("elsewhere", "depot")])
    conn.commit()
    conn.close()


def _cfg(db_path, enabled, extra_dbs=(), read_acl=None):
    entry = {"name": DB_NAME, "path": db_path, "read_only": True}
    if read_acl:
        entry["read_acl"] = read_acl
    dbs = [entry] + list(extra_dbs)
    return {"embeddings": {"model": "hashing", "dimensions": 256},
            "federation": {"local_dbs": dbs},
            "retrieval": {"federated_channel": enabled}}


def _core(db_path, enabled):
    core = ChronicleCore(tempfile.mkdtemp(), _cfg(db_path, enabled))
    for i in range(3):
        core.capture.observe("Discussed contacts in Testland region (session turn %d)" % i,
                             "noted", session_id="s1", occurred_at="2026-01-01T00:00:00Z")
    return core


def setup_stores():
    db_path = os.path.join(tempfile.mkdtemp(), "fixture.db")
    _build_fixture_db(db_path)
    _STATE["db_path"] = db_path
    _STATE["core_on"] = _core(db_path, True)
    _STATE["core_off"] = _core(db_path, False)
    print("  PASS: fixture db built (contacts / order / no_key_log / wor_pairs)")


def _fed_lines(ctx):
    return [ln for ln in ctx.split("\n") if ln.startswith("[FEDERATED ")]


# -- 1. channel on / off ----------------------------------------------------

def test_channel_enabled():
    ctx = _STATE["core_on"].retrieval.get_context(QUERY, token_budget=4000, principal="default")
    lines = _fed_lines(ctx)
    assert lines, "expected [FEDERATED …] blocks with the channel on; got:\n%s" % ctx[:600]
    assert all(ln.startswith("[FEDERATED %s] " % DB_NAME) for ln in lines), lines
    assert "Pat Testley" in ctx, "the Testland row should be projected; got:\n%s" % ctx[:600]
    assert "Testland" in ctx
    print("  PASS: %d [FEDERATED %s] block(s); e.g. %s" % (len(lines), DB_NAME, lines[0][:110]))


def test_channel_disabled():
    ctx = _STATE["core_off"].retrieval.get_context(QUERY, token_budget=4000, principal="default")
    assert not _fed_lines(ctx), "channel is off; got:\n%s" % ctx[:600]
    assert "Pat Testley" not in ctx
    assert _STATE["core_off"].retrieval.federated is None
    print("  PASS: no federated blocks and no channel object when disabled")


# -- 2. budget starvation (r1: raw evidence first) --------------------------

def test_budget_starvation():
    core = _STATE["core_on"]
    ctx = core.retrieval.get_context(QUERY, token_budget=60, principal="default")
    assert not _fed_lines(ctx), "tiny budget must starve the channel; got:\n%s" % ctx
    assert "[SESSION" in ctx or "Discussed" in ctx, \
        "raw session evidence should hold the budget; got:\n%s" % ctx
    # …and the same query with room to spare does emit, so the assertion above
    # is about starvation and not about a channel that never fires.
    assert _fed_lines(core.retrieval.get_context(QUERY, token_budget=4000, principal="default"))
    print("  PASS: token_budget=60 -> raw evidence only (%d chars); 4000 -> federated blocks"
          % len(ctx))


# -- 3. pointer provenance --------------------------------------------------

def test_pointer_provenance():
    core = _STATE["core_on"]
    hits = core.retrieval.federated.query(["testland"], "default", "default")
    assert hits, "expected hits for 'testland'"
    by_table = {}
    for h in hits:
        by_table.setdefault(h["table"], []).append(h)

    for h in by_table["contacts"]:
        assert h["external_id"] == "contacts:%s" % h["row_id"], h
        assert h["block"].startswith("contacts:%s | " % h["row_id"]), h["block"]
    # A pointer must be readable back to the row it names.
    provider = core.retrieval.federated.providers[0]
    one = by_table["contacts"][0]
    resolved = provider.resolve(one["external_id"])
    assert resolved.get("table") == "contacts" and resolved.get("columns"), resolved
    assert str(one["row_id"]) in str(resolved["pk_value"])

    # A table with no primary key still identifies its row (implicit rowid),
    # labelled so nobody mistakes it for a declared key.
    for h in by_table.get("no_key_log", []):
        assert h["external_id"].startswith("no_key_log:rowid="), h
        assert h["row_id"] is not None
    print("  PASS: pointers are %s and %s" % (by_table["contacts"][0]["external_id"],
                                              by_table.get("no_key_log", [{}])[0]
                                              .get("external_id")))


# -- 4. hostile schema: reserved word + spaced column ------------------------

def test_reserved_word_table_does_not_abort_db():
    """`order` is a reserved word and `ship to` needs quoting.

    Unquoted interpolation raises a syntax error mid-introspection; if that
    error is not scoped to the table, the whole database yields nothing. Both
    halves are asserted: the awkward table itself returns its row, AND the
    ordinary tables still return theirs.
    """
    core = _STATE["core_on"]
    hits = core.retrieval.federated.query(["testland"], "default", "default")
    tables = set(h["table"] for h in hits)
    assert "contacts" in tables, "ordinary tables must still return rows; got %s" % tables
    assert "order" in tables, "reserved-word table must be searched; got %s" % tables
    assert "no_key_log" in tables, tables
    order_hit = next(h for h in hits if h["table"] == "order")
    assert "ship to=Testland" in order_hit["projection"], order_hit
    # A quote inside a value survives projection (values are bound, not spliced).
    assert 'fragile' in order_hit["projection"]
    # WITHOUT ROWID + composite key: no addressable row, but no crash either.
    wor = [h for h in hits if h["table"] == "wor_pairs"]
    assert wor and wor[0]["external_id"] is None and wor[0]["projection"], wor
    print("  PASS: tables searched = %s (reserved word and spaced column included)"
          % sorted(tables))


# -- 5. read-only, and a missing file is an error ---------------------------

def test_read_only_and_missing_path():
    path = _STATE["db_path"]
    before = (os.path.getsize(path), os.path.getmtime(path))
    provider = LocalDBProvider(DB_NAME, path)
    provider.search(["testland"], owner="default", principal="default")
    assert (os.path.getsize(path), os.path.getmtime(path)) == before, "db file was modified"
    try:
        provider._connect().execute("CREATE TABLE nope (x)")
        raise AssertionError("write succeeded on a read-only connection")
    except sqlite3.OperationalError as e:
        assert "readonly" in str(e).lower(), e

    missing = os.path.join(tempfile.mkdtemp(), "absent.db")
    absent = LocalDBProvider("absent", missing)
    assert absent.is_available() is False
    try:
        absent._connect()
        raise AssertionError("connecting to a missing db should raise")
    except sqlite3.OperationalError as e:
        assert "no such file" in str(e), e
    assert absent.search(["testland"]) == []
    assert not os.path.exists(missing), "a missing db path must never be created"
    print("  PASS: connection is mode=ro; missing path raises and creates nothing")


# -- 6. ACL enforcement -----------------------------------------------------

def test_acl():
    path = _STATE["db_path"]
    shared = LocalDBProvider(DB_NAME, path)
    assert shared.search(["testland"], owner="default", principal="default")
    # cross-user: never, regardless of acl (§15.7)
    assert shared.search(["testland"], owner="default", principal="otheruser:agent") == []

    private = LocalDBProvider(DB_NAME, path, read_acl="owner_only")
    assert private.search(["testland"], owner="default", principal="default")
    assert private.search(["testland"], owner="default", principal="sidekick") == []
    assert private.get_row("contacts", 1, owner="default", principal="sidekick") is None
    assert private.iter_rows("contacts", owner="default", principal="sidekick") == []

    # …and the acl travels from config into the channel.
    cfg = Config(_cfg(path, True, read_acl="owner_only"))
    chan = FederatedChannel(cfg)
    assert chan.query(["testland"], "sidekick", "default") == []
    assert chan.query(["testland"], "default", "default")
    print("  PASS: cross-user denied; owner_only denied for a sibling principal")


# -- 7. identity is adjudicated, never inferred -----------------------------

def test_no_auto_link():
    core = _STATE["core_on"]
    core.retrieval.get_context(QUERY, token_budget=4000, principal="default")
    core.curation.drain(200)
    for table in ("entities", "facts", "notes", "relationships"):
        for row in core.store.query_beliefs(table, "1=1", (), 500):
            blob = " ".join(str(v) for v in row.values())
            assert "Pat Testley" not in blob, "%s absorbed an external row: %s" % (table, row)
            assert (row.get("external_provider") or "") != DB_NAME, row
    candidates = core.retrieval.federated.pending_candidates
    assert candidates, "matched rows should be queued as review candidates"
    for c in candidates:
        assert c["entity_id"] is None and c["status"] == "pending_review", c
        assert c["provider"] == DB_NAME and c["cached_projection"]
    print("  PASS: 0 external attributes in facts/entities; %d candidate(s) pending review"
          % len(candidates))


# -- 8. declared bounds -----------------------------------------------------

def test_bounds():
    path = _STATE["db_path"]
    extra = [{"name": "db%d" % i, "path": path, "read_only": True} for i in range(2, 7)]
    chan = FederatedChannel(Config(_cfg(path, True, extra_dbs=extra)))
    assert len(chan.providers) == 3, len(chan.providers)
    hits = chan.query(["testland"], "default", "default")
    per_table = {}
    for h in hits:
        per_table[(h["provider"], h["table"])] = per_table.get((h["provider"], h["table"]), 0) + 1
    assert max(per_table.values()) <= 5, per_table
    assert per_table[(DB_NAME, "contacts")] == 5, "5 of 5 matching contacts rows expected"
    assert len(set(p for p, _t in per_table)) <= 3

    # read_only: false is refused rather than silently downgraded.
    refused = providers_from_config(Config({"federation": {"local_dbs": [
        {"name": "rw", "path": path, "read_only": False}]}}))
    assert refused == [], refused
    print("  PASS: <=3 dbs, <=5 rows/table (7 Testland contacts -> 5); read_only=false refused")


if __name__ == "__main__":
    print("Running g3 acceptance tests (federated query channel)…")
    print("\n0. Fixtures:")
    setup_stores()
    print("\n1. Channel enabled:")
    test_channel_enabled()
    print("\n2. Channel disabled (control):")
    test_channel_disabled()
    print("\n3. Budget starvation (r1: raw evidence first):")
    test_budget_starvation()
    print("\n4. Pointer provenance (a pointer names a row):")
    test_pointer_provenance()
    print("\n5. Hostile schema (reserved word table, spaced column):")
    test_reserved_word_table_does_not_abort_db()
    print("\n6. Read-only connection, missing path:")
    test_read_only_and_missing_path()
    print("\n7. ACL enforcement:")
    test_acl()
    print("\n8. Identity adjudicated, never inferred:")
    test_no_auto_link()
    print("\n9. Declared bounds:")
    test_bounds()
    print("\nAll acceptance tests passed.")
