#!/usr/bin/env python3
"""Acceptance test for g2 (generic local-DB provider + registry, §14.1).

LocalDBProvider is a generic read-only capability provider for any declared
SQLite database file. It:
  1. Introspects schema via sqlite_master + PRAGMA table_info
  2. Exposes manifest() with table/column metadata + rowcounts
  3. Renders row projections as compact text (~400 chars, skipping binary/null)
  4. Routes external_id = "table:pk_value" pointers via federation.resolve()
  5. Respects ACL enforcement (access.can_read); degrades gracefully when file missing

Scenario 0: fixture DBs + schema introspection
Scenario 1: projection rendering
Scenario 2: pointer round-trip resolution
Scenario 3: missing-file degradation
Scenario 4: ACL filtering
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."
)
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore
from engine.localdb import LocalDBProvider

# Obviously-fake identities/orgs only
_PEOPLE = [
    {"id": 1, "name": "Pat Testley", "email": "pat@example.test", "company": "Acme Fake Co"},
    {"id": 2, "name": "Sam Rivera", "email": "sam@example.test", "company": "Globex Testing Ltd"},
    {"id": 3, "name": "Jordan Kwan", "email": "jordan@example.test", "company": "Initech Sample Inc"},
]

_ORGS = [
    {"id": 101, "name": "Acme Fake Co", "industry": "Test Automation", "headcount": 42},
    {"id": 102, "name": "Globex Testing Ltd", "industry": "QA Services", "headcount": 150},
    {"id": 103, "name": "Initech Sample Inc", "industry": "Fixture Data", "headcount": 300},
]

_STATE = {}


def _make_db(path: str):
    """Create a synthetic test database with people and orgs tables."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE people (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            company TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE orgs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            industry TEXT,
            headcount INTEGER
        )
    """)
    for person in _PEOPLE:
        conn.execute(
            "INSERT INTO people(id, name, email, company) VALUES(?, ?, ?, ?)",
            (person["id"], person["name"], person["email"], person["company"]),
        )
    for org in _ORGS:
        conn.execute(
            "INSERT INTO orgs(id, name, industry, headcount) VALUES(?, ?, ?, ?)",
            (org["id"], org["name"], org["industry"], org["headcount"]),
        )
    conn.commit()
    conn.close()


def setup_fixtures():
    """Create fixture DBs and ChronicleCore."""
    # Create two test databases
    tmpdir = tempfile.mkdtemp()
    people_db = os.path.join(tmpdir, "people.db")
    _make_db(people_db)

    missing_db = os.path.join(tmpdir, "missing.db")  # never created

    # Create a core with federation config pointing to these DBs
    home = tempfile.mkdtemp()
    cfg = {
        "embeddings": {"model": "hashing", "dimensions": 256},
        "federation": {
            "local_dbs": [
                {"name": "people", "path": people_db, "read_only": True},
                {"name": "missing", "path": missing_db, "read_only": True},
            ]
        },
    }
    core = ChronicleCore(home, cfg)
    core.bind_capabilities()
    _STATE.update(core=core, people_db=people_db, missing_db=missing_db, tmpdir=tmpdir)
    print(f"  fixture: created test DBs in {tmpdir}")


def test_manifest_introspection():
    """LocalDBProvider.manifest() returns correct schema."""
    core = _STATE["core"]
    provider = core.federation.providers.get("people")
    assert provider is not None, "people provider not registered"

    manifest = provider.manifest()
    assert "tables" in manifest, "manifest missing 'tables' key"

    tables = manifest["tables"]
    assert "people" in tables, "people table not in manifest"
    assert "orgs" in tables, "orgs table not in manifest"

    people_tbl = tables["people"]
    assert people_tbl["pk"] == "id", f"people PK should be 'id', got {people_tbl['pk']}"
    assert people_tbl["rowcount"] == len(_PEOPLE), f"people rowcount {people_tbl['rowcount']} != {len(_PEOPLE)}"

    cols = {c["name"]: c["type"] for c in people_tbl["columns"]}
    assert "name" in cols and "email" in cols and "company" in cols, "missing expected columns"

    orgs_tbl = tables["orgs"]
    assert orgs_tbl["rowcount"] == len(_ORGS), f"orgs rowcount {orgs_tbl['rowcount']} != {len(_ORGS)}"

    print(f"  PASS: manifest introspection correct for {len(tables)} tables")


def test_projection_rendering():
    """Projections render correctly: table: col=val; col=val; ... (~400 chars max)."""
    core = _STATE["core"]
    provider = core.federation.providers.get("people")
    assert provider is not None

    # Get a row and render it
    row = provider.get_row("people", 1)
    assert row is not None, "failed to get people row id=1"

    proj = provider.render_projection("people", row)
    assert proj.startswith("people:"), f"projection should start with 'people:', got {proj[:30]}"
    assert "Pat Testley" in proj, "projection should include name"
    assert "Acme Fake Co" in proj, "projection should include company"
    assert len(proj) < 500, f"projection too long: {len(proj)} >= 500"

    print(f"  PASS: projection rendering: {proj[:80]}...")


def test_pointer_resolution():
    """Pointers with external_id='table:pk_value' resolve correctly."""
    core = _STATE["core"]
    provider = core.federation.providers.get("people")
    assert provider is not None

    # Test resolve with "people:1" format
    resolved = provider.resolve("people:1")
    assert resolved, "resolve() returned empty dict"
    assert resolved.get("table") == "people", f"expected table=people, got {resolved.get('table')}"
    assert resolved.get("pk_value") == 1, f"expected pk_value=1, got {resolved.get('pk_value')}"
    assert "Pat Testley" in resolved.get("cached_projection", ""), "projection missing person name"

    # Test resolve with invalid format (should return empty)
    resolved_bad = provider.resolve("invalid_format")
    assert not resolved_bad, "resolve() should return empty for invalid format"

    # Test resolve with missing row (should return empty)
    resolved_missing = provider.resolve("people:99999")
    assert not resolved_missing, "resolve() should return empty for non-existent row"

    print(f"  PASS: pointer resolution correct")


def test_missing_file_degradation():
    """Provider with missing file degrades gracefully (unavailable, no crash)."""
    core = _STATE["core"]
    provider = core.federation.providers.get("missing")
    assert provider is not None, "missing provider not registered"

    # Should be unavailable
    assert not provider.is_available(), "missing file should report unavailable"

    # Manifest should return empty
    manifest = provider.manifest()
    assert manifest.get("tables") == {}, "manifest should be empty for unavailable provider"

    # iter_rows should return []
    rows = provider.iter_rows("anything")
    assert rows == [], "iter_rows should return [] for unavailable provider"

    # get_row should return None
    row = provider.get_row("anything", 1)
    assert row is None, "get_row should return None for unavailable provider"

    # resolve should return {}
    resolved = provider.resolve("anything:1")
    assert resolved == {}, "resolve should return {} for unavailable provider"

    print(f"  PASS: missing file degrades gracefully without crashing")


def test_acl_enforcement():
    """ACL enforcement via access.can_read is respected."""
    core = _STATE["core"]
    provider = core.federation.providers.get("people")
    assert provider is not None

    # Default principal=_user, owner=_user → allowed
    row = provider.get_row("people", 1, owner="_user", principal="_user")
    assert row is not None, "same-user read should be allowed"

    # Cross-user read denied (namespaced principals: alice:agent vs bob:agent)
    row = provider.get_row("people", 1, owner="alice:agent", principal="bob:agent")
    assert row is None, "cross-user read should be denied"

    # iter_rows cross-user denied
    rows = provider.iter_rows("people", owner="alice:agent", principal="bob:agent")
    assert rows == [], "cross-user iter_rows should return []"

    print(f"  PASS: ACL enforcement blocks cross-user reads")


def test_provider_in_federation_registry():
    """LocalDBProvider is registered in federation.providers dict."""
    core = _STATE["core"]

    # Check both providers are registered
    assert "people" in core.federation.providers, "people not in federation.providers"
    assert "missing" in core.federation.providers, "missing not in federation.providers"

    provider_people = core.federation.providers["people"]
    assert isinstance(provider_people, LocalDBProvider), "people provider is not LocalDBProvider"
    assert provider_people.name == "people", f"provider name should be 'people', got {provider_people.name}"

    print(f"  PASS: providers registered in federation: {list(core.federation.providers.keys())}")


if __name__ == "__main__":
    print("Running g2 acceptance tests (generic local-DB provider)...")

    print("\n0. Fixture setup:")
    setup_fixtures()

    print("\n1. Schema introspection:")
    test_manifest_introspection()

    print("\n2. Projection rendering:")
    test_projection_rendering()

    print("\n3. Pointer resolution:")
    test_pointer_resolution()

    print("\n4. Missing-file degradation:")
    test_missing_file_degradation()

    print("\n5. ACL enforcement:")
    test_acl_enforcement()

    print("\n6. Federation registry:")
    test_provider_in_federation_registry()

    print("\nAll acceptance tests passed.")
