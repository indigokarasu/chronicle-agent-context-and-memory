#!/usr/bin/env python3
"""Acceptance test for backfill_sweep (session-index backfill).

Tests that the batch job deterministically enqueues session_summarize tasks for
ended/reaped sessions lacking an index row, using a watermark for idempotent
pagination (<=200/run).
"""

import json
import os
import sqlite3
import sys
import tempfile

# Add chronicle to path.
chronicle_dir = os.environ.get("CHRONICLE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, chronicle_dir)

from engine.core import ChronicleCore
from engine.store import SCHEMA_VERSION, now_iso

# curation_jobs exactly as it shipped for schema_version 4 (task g4:
# 'federate_sweep' + federation_watermarks/link_candidates, BEFORE this task
# added 'backfill_sweep'). Used to prove the migration gate catches a missing
# 'backfill_sweep' independently of 'federate_sweep' already being present —
# same technique as accept_u2.py's v2 fixture / accept_t2.py's legacy fixture.
_V4_JOBS_DDL = """CREATE TABLE curation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT CHECK(task IN ('extract','route','criticality','canonicalize','consolidate',
        'contradiction','identity','derive','verify','decay','consistency','health','reextract',
        'journal_ingest','session_summarize','embed','digest','federate_sweep')),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT,
    run_after TEXT);"""


def test_backfill_sweep_basic():
    """Basic: backfill enqueues summarize for sessions lacking index, respects watermark."""
    print("\n=== Test: Basic Backfill Sweep ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        store = core.store

        # Create three ended sessions with observed events.
        for i in range(3):
            sid = f"s{i}"
            store.upsert_session({
                "session_id": sid,
                "status": "ended",
                "started_at": now_iso(),
                "ended_at": now_iso(),
            })
            store.append_event({
                "event_id": f"e{i}",
                "type": "observed",
                "payload": json.dumps({"excerpt": f"session {i} content"}),
                "actor": "user",
                "owner": "default",
                "session_id": sid,
                "occurred_at": now_iso(),
            })

        # Before backfill, no index rows.
        indexed = [s["session_id"] for s in store.iter_session_vectors()]
        print(f"Indexed sessions before backfill: {sorted(indexed)}")
        if indexed:
            print("FAIL: should have no indexed sessions initially")
            return False

        # Run backfill sweep.
        core.curation._task_backfill_sweep({})
        core.process_pending()

        # Verify session_summarize jobs were enqueued and processed.
        indexed = {s["session_id"] for s in store.iter_session_vectors()}
        print(f"Indexed sessions after backfill: {sorted(indexed)}")
        if indexed != {"s0", "s1", "s2"}:
            print(f"FAIL: expected all 3 sessions indexed, got {sorted(indexed)}")
            return False

        print("PASS: backfill indexed all sessions")
        return True


def test_backfill_sweep_watermark():
    """Watermark: subsequent runs are idempotent and don't reprocess."""
    print("\n=== Test: Watermark Idempotency ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        store = core.store

        # Create five ended sessions.
        for i in range(5):
            sid = f"s{i:02d}"
            store.upsert_session({
                "session_id": sid,
                "status": "ended",
                "started_at": now_iso(),
                "ended_at": now_iso(),
            })
            store.append_event({
                "event_id": f"e{i}",
                "type": "observed",
                "payload": json.dumps({"excerpt": f"content {i}"}),
                "actor": "user",
                "owner": "default",
                "session_id": sid,
                "occurred_at": now_iso(),
            })

        # First backfill run: enqueue all.
        sids_run1 = store.get_sessions_needing_index_backfill(limit=200)
        print(f"Run 1: {len(sids_run1)} sessions queued: {sorted(sids_run1)}")
        if len(sids_run1) != 5:
            print(f"FAIL: run 1 expected 5, got {len(sids_run1)}")
            return False

        # Process all pending jobs.
        for sid in sids_run1:
            core.curation._task_session_summarize({"session_id": sid})

        # Second backfill run: watermark prevents reprocessing.
        sids_run2 = store.get_sessions_needing_index_backfill(limit=200)
        print(f"Run 2: {len(sids_run2)} sessions queued: {sorted(sids_run2)}")
        if sids_run2:
            print(f"FAIL: run 2 should find 0 sessions (watermark), got {len(sids_run2)}")
            return False

        print("PASS: watermark prevents reprocessing")
        return True


def test_backfill_sweep_limit():
    """Limit: batch size capped at <=200 per run."""
    print("\n=== Test: Batch Size Limit ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        store = core.store

        # Create 250 ended sessions (more than the default limit).
        for i in range(250):
            sid = f"s{i:03d}"
            store.upsert_session({
                "session_id": sid,
                "status": "ended",
                "started_at": now_iso(),
                "ended_at": now_iso(),
            })
            store.append_event({
                "event_id": f"e{i}",
                "type": "observed",
                "payload": json.dumps({"excerpt": f"content {i}"}),
                "actor": "user",
                "owner": "default",
                "session_id": sid,
                "occurred_at": now_iso(),
            })

        # First batch: should be limited to <=200.
        batch1 = store.get_sessions_needing_index_backfill(limit=200)
        print(f"Batch 1: {len(batch1)} sessions (expected <= 200)")
        if len(batch1) > 200:
            print(f"FAIL: batch 1 exceeded limit: {len(batch1)} > 200")
            return False

        # Process batch 1 and get batch 2.
        for sid in batch1:
            core.curation._task_session_summarize({"session_id": sid})

        batch2 = store.get_sessions_needing_index_backfill(limit=200)
        print(f"Batch 2: {len(batch2)} sessions")

        # Batch 2 should get the remainder (250 - batch1).
        remaining = 250 - len(batch1)
        if len(batch2) != min(remaining, 200):
            print(f"FAIL: batch 2 expected min({remaining}, 200), got {len(batch2)}")
            return False

        # Process batch 2 and verify batch 3 exists if needed.
        for sid in batch2:
            core.curation._task_session_summarize({"session_id": sid})

        batch3 = store.get_sessions_needing_index_backfill(limit=200)
        total_batches = 1 + (1 if batch2 else 0) + (1 if batch3 else 0)
        total_processed = len(batch1) + len(batch2) + len(batch3)
        print(f"Total: {total_processed} sessions in {total_batches} batches")
        if total_processed != 250:
            print(f"FAIL: expected 250 total, got {total_processed}")
            return False

        print("PASS: batch size limit enforced")
        return True


def test_backfill_sweep_excludes_indexed():
    """Excludes: sessions already in session_index are not re-enqueued."""
    print("\n=== Test: Exclude Already-Indexed Sessions ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        store = core.store

        # Create three ended sessions.
        for i in range(3):
            sid = f"s{i}"
            store.upsert_session({
                "session_id": sid,
                "status": "ended",
                "started_at": now_iso(),
                "ended_at": now_iso(),
            })
            store.append_event({
                "event_id": f"e{i}",
                "type": "observed",
                "payload": json.dumps({"excerpt": f"content {i}"}),
                "actor": "user",
                "owner": "default",
                "session_id": sid,
                "occurred_at": now_iso(),
            })

        # Manually add s1 to session_index.
        store.add_session_vector("s1", "summary", b"", "default", now_iso())

        # Backfill should skip s1 and only queue s0, s2.
        candidates = store.get_sessions_needing_index_backfill(limit=200)
        print(f"Candidates for backfill: {sorted(candidates)}")
        if set(candidates) != {"s0", "s2"}:
            print(f"FAIL: expected {{s0, s2}}, got {set(candidates)}")
            return False

        print("PASS: already-indexed sessions excluded")
        return True


def test_backfill_sweep_active_sessions_skipped():
    """Skipped: active/idle sessions are not backfilled."""
    print("\n=== Test: Skip Active/Idle Sessions ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        store = core.store

        # Create sessions in different states.
        store.upsert_session({"session_id": "active", "status": "active", "started_at": now_iso()})
        store.upsert_session({"session_id": "idle", "status": "idle", "started_at": now_iso()})
        store.upsert_session({"session_id": "ended", "status": "ended", "started_at": now_iso(), "ended_at": now_iso()})

        # Only ended should be in backfill candidates.
        candidates = store.get_sessions_needing_index_backfill(limit=200)
        print(f"Backfill candidates: {sorted(candidates)}")
        if candidates != ["ended"]:
            print(f"FAIL: expected only [ended], got {candidates}")
            return False

        print("PASS: only ended sessions backfilled")
        return True


def test_backfill_sweep_migrates_existing_store():
    """A pre-existing store on the v4 schema (curation_jobs task CHECK has
    'federate_sweep' but not 'backfill_sweep') must migrate on open, not raise
    sqlite3.IntegrityError the moment a 'backfill_sweep' job is enqueued.

    Every acceptance test above only ever opens a FRESH tmpdir store, whose
    curation_jobs is created straight from the current _CURATION_JOBS_DDL (which
    already lists 'backfill_sweep') — so none of them ever exercises _migrate's
    `missing` probe at all. This is the population the feature exists to serve:
    every real deployment is an already-migrated store, not a fresh one."""
    print("\n=== Test: Migration From v4 Fixture ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore(hermes_home=tmpdir)
        db_path = core.store.db_path

        # Downgrade the freshly-created db to the exact v4 shape.
        conn = sqlite3.connect(db_path)
        conn.executescript(
            "DROP TABLE curation_jobs;\n" + _V4_JOBS_DDL +
            "\nINSERT INTO curation_jobs(task,payload,status,created_at) "
            "VALUES('health','{}','done','x');")
        conn.commit()
        sql_before = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='curation_jobs'").fetchone()[0]
        conn.close()
        if "'backfill_sweep'" in sql_before:
            print("FAIL: fixture is not actually missing 'backfill_sweep'")
            return False
        if "'federate_sweep'" not in sql_before:
            print("FAIL: fixture should already have 'federate_sweep' (this is v4, not v3)")
            return False

        # Reopen — _migrate must see the missing 'backfill_sweep' independently of
        # 'federate_sweep' already being present, and rebuild BEFORE anything
        # enqueues a 'backfill_sweep' job. Pre-fix, the enqueue_curation call
        # below raised sqlite3.IntegrityError straight out of its own txn.
        core2 = ChronicleCore(hermes_home=tmpdir)
        store2 = core2.store
        sid = "legacy_session"
        store2.upsert_session({
            "session_id": sid,
            "status": "ended",
            "started_at": now_iso(),
            "ended_at": now_iso(),
        })
        store2.append_event({
            "event_id": "legacy_e0",
            "type": "observed",
            "payload": json.dumps({"excerpt": "legacy session content"}),
            "actor": "user",
            "owner": "default",
            "session_id": sid,
            "occurred_at": now_iso(),
        })

        try:
            store2.enqueue_curation("backfill_sweep", {})
        except sqlite3.IntegrityError as e:
            print(f"FAIL: enqueue_curation('backfill_sweep', ...) raised on a v4 store: {e}")
            return False

        n_jobs = core2.curation.drain(max_jobs=100)
        if n_jobs <= 0:
            print(f"FAIL: no curation jobs ran after migration (n_jobs={n_jobs})")
            return False

        version = store2.get_meta("schema_version")
        # Compare against the live constant, not a literal: any later schema bump
        # still migrates the v4 fixture through the same path.
        if version != str(SCHEMA_VERSION):
            print(f"FAIL: meta.schema_version is {version!r}, expected {str(SCHEMA_VERSION)!r}")
            return False

        kept = store2.count_rows("curation_jobs", "task='health'")
        if kept != 1:
            print(f"FAIL: rebuild lost the pre-existing legacy job row (kept={kept})")
            return False

        indexed = {s["session_id"] for s in store2.iter_session_vectors()}
        if sid not in indexed:
            print(f"FAIL: legacy session was not indexed after migration+drain: {indexed}")
            return False

        print(f"PASS: v4 fixture migrates cleanly (schema_version={version}, "
              f"legacy rows kept={kept}, indexed={sorted(indexed)})")
        return True


def main():
    tests = [
        ("Basic Backfill Sweep", test_backfill_sweep_basic),
        ("Watermark Idempotency", test_backfill_sweep_watermark),
        ("Batch Size Limit", test_backfill_sweep_limit),
        ("Exclude Already-Indexed", test_backfill_sweep_excludes_indexed),
        ("Skip Active/Idle Sessions", test_backfill_sweep_active_sessions_skipped),
        ("Migration From v4 Fixture", test_backfill_sweep_migrates_existing_store),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n=== Summary ===")
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{name}: {status}")

    sys.exit(0 if all(p for _, p in results) else 1)


if __name__ == "__main__":
    main()
