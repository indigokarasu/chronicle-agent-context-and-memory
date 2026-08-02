#!/usr/bin/env python3
"""Acceptance test for g5 (projection embedding + generic db_query tool).

Tests:
1. Projection vectors created via the EXISTING embed-job queue path (hashing
   embedder ok) -- never by calling store.add_projection_vector() directly.
2. Vector search surfaces projections for semantically-matching queries, and
   respects the real per-projection owner via access.can_read (not a
   hardcoded "system" bypass).
3. chronicle_db_query tool accepts SELECT, rejects non-SELECT/PRAGMA
   (including the pragma_table_info/pragma_database_list table-valued-function
   spellings that have no space after "pragma"), rejects multi-statement, and
   rejects unregistered dbs.
4. External databases are introspected via config federation.local_dbs --
   nothing here is a deployment-specific db name.
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore


def test_projection_vectors_via_queue():
    """Projection vectors are created by enqueuing an embed job and draining
    the curation queue -- the SAME deferred embed-job path every other vector
    channel uses -- never by calling store.add_projection_vector() directly."""
    with tempfile.TemporaryDirectory() as home:
        cfg = {"embeddings": {"model": "hashing", "dimensions": 256}}
        core = ChronicleCore(home, cfg)

        # Enqueue two projections from a fake provider (synthetic data only).
        job1 = core.store.enqueue_projection_embed(
            "acme_fake_people_db", "person_123", "Pat Testley, engineer at Acme Fake Co", owner="default")
        job2 = core.store.enqueue_projection_embed(
            "acme_fake_people_db", "person_456", "Sam Fakerson, manager at Acme Fake Co", owner="default")
        assert job1 is not None and job2 is not None, "enqueue_projection_embed should return job ids"

        # Nothing should exist yet -- the job is queued, not embedded inline.
        assert not core.store.has_projection_vector("acme_fake_people_db", "person_123")

        n = core.curation.drain(max_jobs=10)
        assert n >= 2, f"expected >=2 jobs drained, got {n}"

        # Now the vectors exist, written by the curation worker's 'embed' task.
        assert core.store.has_projection_vector("acme_fake_people_db", "person_123")
        assert core.store.has_projection_vector("acme_fake_people_db", "person_456")

        proj_ids = [("acme_fake_people_db", "person_123"), ("acme_fake_people_db", "person_456")]
        results = core.store.get_projection_vectors_by_ids(proj_ids)
        assert len(results) == 2, f"Expected 2 projections, got {len(results)}"
        assert "proj:acme_fake_people_db:person_123" in results
        assert "proj:acme_fake_people_db:person_456" in results
        assert results["proj:acme_fake_people_db:person_123"]["owner"] == "default"
        print("✓ Projection vectors created via job queue and retrieved")


def test_projection_vector_search():
    """Projection vectors surface in retrieve_raw for a semantically similar
    query, and are ACL-filtered by their real owner (not a hardcoded bypass).

    Owners/principals use the "user:agent" namespacing access.user_of()
    understands (§15.7) so the cross-user check below is a real test of
    isolation, not an artifact of two unnamespaced strings both collapsing to
    the same implicit "_user"."""
    with tempfile.TemporaryDirectory() as home:
        cfg = {"embeddings": {"model": "hashing", "dimensions": 256}}
        core = ChronicleCore(home, cfg)

        core.store.enqueue_projection_embed(
            "acme_fake_people_db", "person_001", "machine learning engineer at acme fake corp",
            owner="alice:agent1")
        core.store.enqueue_projection_embed(
            "acme_fake_people_db", "person_002", "product manager at globex fake ltd",
            owner="alice:agent1")
        core.store.enqueue_projection_embed(
            "acme_fake_people_db", "person_999", "unrelated finance text xyz",
            owner="alice:agent1")
        core.curation.drain(max_jobs=10)

        # Query for something semantically similar to person_001's projection,
        # as one of alice's OTHER agents (same user, default "user_agents" ACL
        # mode allows it, §15.7 I22).
        query = "engineer working on machine learning"
        results = core.retrieval.retrieve_raw(query, limit=20, principal="alice:agent2")

        proj_ids = [r["event_id"] for r in results if r["event_id"].startswith("proj:")]
        assert len(proj_ids) > 0, f"No projections found in results: {results}"
        assert "proj:acme_fake_people_db:person_001" in proj_ids or \
            "proj:acme_fake_people_db:person_002" in proj_ids
        print(f"✓ Projection vectors surfaced in retrieve_raw: {proj_ids}")

        # A DIFFERENT user's principal must never see alice's projections
        # (I22 cross-user isolation) -- same ACL gate as every other channel.
        other_results = core.retrieval.retrieve_raw(query, limit=20, principal="bob:agent1")
        other_proj_ids = [r["event_id"] for r in other_results if r["event_id"].startswith("proj:")]
        assert not other_proj_ids, f"cross-user principal saw projections it should not: {other_proj_ids}"
        print("✓ Projection vectors are ACL-filtered by real owner (cross-user isolation holds)")


def test_db_query_tool_select():
    """chronicle_db_query accepts SELECT and rejects other operations."""
    with tempfile.TemporaryDirectory() as home:
        # Synthetic fixture DB with obviously-fake data.
        test_db_path = Path(home) / "test.db"
        conn = sqlite3.connect(str(test_db_path))
        conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'Pat Testley'), (2, 'Sam Fakerson')")
        conn.commit()
        conn.close()

        cfg = {
            "embeddings": {"model": "hashing", "dimensions": 256},
            "federation": {
                "local_dbs": [
                    {"name": "test_db", "path": str(test_db_path), "read_only": True}
                ]
            }
        }
        core = ChronicleCore(home, cfg)
        tools = core.tools

        # Test valid SELECT
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "SELECT * FROM test"})
        result = json.loads(result)
        assert "rows" in result, f"Expected rows in result: {result}"
        assert len(result["rows"]) == 2, f"Expected 2 rows, got {len(result['rows'])}"
        assert "provenance" in result, f"Expected provenance header: {result}"
        print(f"✓ SELECT query succeeded: {result['count']} rows")

        # Test rejected INSERT
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "INSERT INTO test VALUES (3, 'Charlie')"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for INSERT, got: {result}"
        assert "INSERT" in result["error"] or "not allowed" in result["error"]
        print(f"✓ INSERT rejected: {result['error']}")

        # Test rejected UPDATE
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "UPDATE test SET name='Alice2' WHERE id=1"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for UPDATE, got: {result}"
        assert "UPDATE" in result["error"] or "not allowed" in result["error"]
        print(f"✓ UPDATE rejected: {result['error']}")

        # Test rejected DELETE
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "DELETE FROM test WHERE id=1"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for DELETE, got: {result}"
        assert "DELETE" in result["error"] or "not allowed" in result["error"]
        print(f"✓ DELETE rejected: {result['error']}")

        # Test rejected PRAGMA (statement form)
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "PRAGMA table_info(test)"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for PRAGMA, got: {result}"
        print(f"✓ PRAGMA rejected: {result['error']}")

        # Test rejected pragma_table_info(...) -- a SELECT-shaped query that
        # reads schema via SQLite's pragma table-valued function. No space
        # follows "pragma" here, which is exactly what broke the old
        # space-delimited " PRAGMA " substring check.
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "SELECT * FROM pragma_table_info('test')"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for pragma_table_info, got: {result}"
        print(f"✓ pragma_table_info() rejected: {result['error']}")

        # Test rejected pragma_database_list -- same family, no parens even.
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "SELECT * FROM pragma_database_list"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for pragma_database_list, got: {result}"
        print(f"✓ pragma_database_list rejected: {result['error']}")

        # Test rejected ATTACH
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "ATTACH DATABASE ':memory:' AS mem"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for ATTACH, got: {result}"
        print(f"✓ ATTACH rejected: {result['error']}")

        # Test multi-statement rejected
        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "test_db", "sql": "SELECT * FROM test; SELECT 1;"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for multi-statement, got: {result}"
        print(f"✓ Multi-statement rejected: {result['error']}")


def test_db_query_tool_unregistered_db():
    """chronicle_db_query rejects unregistered databases."""
    with tempfile.TemporaryDirectory() as home:
        cfg = {
            "embeddings": {"model": "hashing", "dimensions": 256},
            "federation": {"local_dbs": []}
        }
        core = ChronicleCore(home, cfg)
        tools = core.tools

        result = tools.dispatch("test_user", "chronicle_db_query",
                               {"db": "unknown_db", "sql": "SELECT 1"})
        result = json.loads(result)
        assert "error" in result, f"Expected error for unregistered db, got: {result}"
        assert "not registered" in result["error"] or "unknown" in result["error"]
        print(f"✓ Unregistered database rejected: {result['error']}")


if __name__ == "__main__":
    try:
        test_projection_vectors_via_queue()
        test_projection_vector_search()
        test_db_query_tool_select()
        test_db_query_tool_unregistered_db()
        print("\n✓✓✓ All g5 acceptance tests passed!")
    except Exception as e:
        print(f"\n✗✗✗ Test failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
