"""
Acceptance test for u2 (entity consolidation digests).

Tests that digests are created for entities with >=3 active facts, stored as
notes with stable belief_id, and are not duplicated on re-digesting — including
re-digesting after new content actually changes the digest line (the case a
content-derived belief_id key gets wrong, since a stable key would only be
exercised by a no-op re-drain). Also verifies a real v2 fixture db (curation_jobs
missing 'digest' from its task CHECK) migrates cleanly instead of raising
IntegrityError out of the enclosing extract job (§u2 triage).
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from engine.core import ChronicleCore

# curation_jobs exactly as it shipped for schema_version 2 (task t2: run_after +
# 'embed', BEFORE this task added 'digest'). Used to prove the migration gate
# catches a missing 'digest' independently of 'embed' already being present.
_V2_JOBS_DDL = """CREATE TABLE curation_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT CHECK(task IN ('extract','route','criticality','canonicalize','consolidate',
        'contradiction','identity','derive','verify','decay','consistency','health','reextract',
        'journal_ingest','session_summarize','embed')),
    payload TEXT, depends_on INTEGER REFERENCES curation_jobs(id),
    status TEXT CHECK(status IN ('pending','running','done','failed')) DEFAULT 'pending',
    attempts INTEGER DEFAULT 0, created_at TEXT, started_at TEXT, finished_at TEXT, error TEXT,
    run_after TEXT);"""


def test_digest_created_on_3_facts():
    """Digesting an entity with 3+ active facts creates exactly one digest note."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    # Ingest 4 facts about a synthetic entity (using "I" to reference the user).
    session_id = "test_session_1"
    core.capture.observe("I am Pat Testley", "", session_id=session_id, occurred_at="2024-01-01T00:00:00Z")
    core.capture.observe("I work at Acme Fake Co", "", session_id=session_id, occurred_at="2024-01-02T00:00:00Z")
    core.capture.observe("I live in Springfield", "", session_id=session_id, occurred_at="2024-01-03T00:00:00Z")
    core.capture.observe("My phone is 555-1234", "", session_id=session_id, occurred_at="2024-01-04T00:00:00Z")

    # Drain curation pipeline to extract facts and create digest.
    n_jobs = core.curation.drain(max_jobs=100)
    assert n_jobs > 0, "No curation jobs ran"

    # Query for digest notes about Pat Testley (assumed entity_id derived from name).
    digest_notes = core.store.query_beliefs(
        "notes",
        "subject LIKE 'digest:%' AND note_type='belief' AND status='active'",
        (), limit=10)

    assert len(digest_notes) >= 1, f"Expected at least 1 digest note, got {len(digest_notes)}"
    digest = digest_notes[0]
    digest_body = digest.get("body", "")

    # Verify digest contains multiple attributes.
    assert digest_body, "Digest note has empty body"
    attr_count = digest_body.count("=")
    assert attr_count >= 3, f"Expected 3+ attributes in digest, got {attr_count} in: {digest_body}"
    assert "(episodes:" in digest_body, f"Missing episode count in digest: {digest_body}"
    print(f"PASS: Digest created with {attr_count} attributes: {digest_body}")


def test_digest_idempotent():
    """Re-digesting the same entity does not duplicate the digest note."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    session_id = "test_session_2"
    core.capture.observe("I am Pat Testley", "", session_id=session_id, occurred_at="2024-01-01T00:00:00Z")
    core.capture.observe("I work at Acme Fake Co", "", session_id=session_id, occurred_at="2024-01-02T00:00:00Z")
    core.capture.observe("I live in Springfield", "", session_id=session_id, occurred_at="2024-01-03T00:00:00Z")

    # First drain.
    core.curation.drain(max_jobs=100)
    digests_1 = core.store.query_beliefs(
        "notes",
        "subject LIKE 'digest:%' AND note_type='belief' AND status='active'",
        (), limit=10)
    count_1 = len(digests_1)

    # Second drain (should not create more digests).
    core.curation.drain(max_jobs=100)
    digests_2 = core.store.query_beliefs(
        "notes",
        "subject LIKE 'digest:%' AND note_type='belief' AND status='active'",
        (), limit=10)
    count_2 = len(digests_2)

    assert count_1 == count_2, \
        f"Digest count changed after re-drain: {count_1} → {count_2}"
    print(f"PASS: Digest is idempotent ({count_1} digest notes after 2 drains)")


def test_ask_about_includes_digest():
    """ask_about() prepends digest line for an entity."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    session_id = "test_session_3"
    core.capture.observe("I am Pat Testley", "", session_id=session_id, occurred_at="2024-01-01T00:00:00Z")
    core.capture.observe("I work at Acme Fake Co", "", session_id=session_id, occurred_at="2024-01-02T00:00:00Z")
    core.capture.observe("I live in Springfield", "", session_id=session_id, occurred_at="2024-01-03T00:00:00Z")

    # Drain to extract facts and create digest.
    core.curation.drain(max_jobs=100)

    # Find a digest note to get the entity_id.
    digest_notes = core.store.query_beliefs(
        "notes",
        "subject LIKE 'digest:%' AND status='active' AND note_type='belief'",
        (), limit=1)
    assert len(digest_notes) > 0, "No digest notes found"
    # Extract entity_id from subject "digest:<entity_id>"
    subject = digest_notes[0]["subject"]
    entity_id = subject.replace("digest:", "")

    # Call ask_about.
    results = core.retrieval.ask_about(entity_id)
    assert len(results) > 0, "ask_about returned no results"

    # Check for digest line (should be first if present).
    has_digest = any("digest_line" in r for r in results)
    assert has_digest, f"No digest line in ask_about results: {results}"
    print(f"PASS: ask_about includes digest ({len(results)} total items)")


def test_digest_replaces_on_new_fact():
    """Re-digesting after a NEW fact changes the digest content must replace the
    existing note in place, never leave the stale one behind as a second active
    row. A no-op re-drain (content unchanged) can't distinguish a stable key from
    one that folds in content — this is the regression this task's review caught.
    """
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    session_id = "test_session_4"
    core.capture.observe("I am Pat Testley", "", session_id=session_id, occurred_at="2024-01-01T00:00:00Z")
    core.capture.observe("I work at Acme Fake Co", "", session_id=session_id, occurred_at="2024-01-02T00:00:00Z")
    core.capture.observe("I live in Springfield", "", session_id=session_id, occurred_at="2024-01-03T00:00:00Z")
    core.curation.drain(max_jobs=100)

    def _active_digests():
        return core.store.query_beliefs(
            "notes", "subject LIKE 'digest:%' AND note_type='belief' AND status='active'",
            (), limit=10)

    before = _active_digests()
    assert len(before) == 1, f"Expected exactly 1 digest note before new fact, got {len(before)}"
    belief_id_before = before[0]["belief_id"]
    body_before = before[0]["body"]

    # New fact changes the rendered digest line — this is the case that broke.
    core.capture.observe("My phone is 555-1234", "", session_id=session_id, occurred_at="2024-01-04T00:00:00Z")
    core.curation.drain(max_jobs=100)

    after = _active_digests()
    assert len(after) == 1, f"Expected exactly 1 active digest note after new fact, got {len(after)}: " \
                            f"{[d['body'] for d in after]}"
    assert after[0]["belief_id"] == belief_id_before, \
        f"belief_id changed across re-digest ({belief_id_before} -> {after[0]['belief_id']}); " \
        f"content-derived key would duplicate instead of upserting"
    assert after[0]["body"] != body_before, "digest body did not pick up the new fact"
    assert after[0]["body"].count("=") >= 4, f"Expected 4+ attributes after new fact: {after[0]['body']}"
    print(f"PASS: re-digest after new fact replaces in place: {after[0]['body']}")


def test_migration_from_v2_fixture():
    """A real v2 db (curation_jobs task CHECK has 'embed' but not 'digest') must
    migrate on open, not raise IntegrityError the first time an extract job
    enqueues a 'digest' job inside its own transaction (§u2 triage: store.py
    previously only ever checked for 'embed', so a v2 db never rebuilt)."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
    db_path = core.store.db_path

    # Downgrade the freshly-created db to the exact v2 shape (has 'embed', no
    # 'digest'), same technique as accept_t2.py's legacy-schema fixture.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "DROP TABLE curation_jobs;\n" + _V2_JOBS_DDL +
        "\nINSERT INTO curation_jobs(task,payload,status,created_at) "
        "VALUES('health','{}','done','x');")
    conn.commit()
    sql_before = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='curation_jobs'").fetchone()[0]
    conn.close()
    assert "'digest'" not in sql_before, "fixture is not actually missing 'digest'"
    assert "'embed'" in sql_before, "fixture should already have 'embed' (this is v2, not pre-t2)"

    # Reopen — _migrate must see the missing 'digest' independently of 'embed'
    # already being present, and rebuild before any digest job is enqueued.
    core2 = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
    session_id = "test_session_5"
    core2.capture.observe("I am Pat Testley", "", session_id=session_id, occurred_at="2024-01-01T00:00:00Z")
    core2.capture.observe("I work at Acme Fake Co", "", session_id=session_id, occurred_at="2024-01-02T00:00:00Z")
    core2.capture.observe("I live in Springfield", "", session_id=session_id, occurred_at="2024-01-03T00:00:00Z")
    n_jobs = core2.curation.drain(max_jobs=100)  # would raise IntegrityError pre-fix
    assert n_jobs > 0, "no curation jobs ran after migration"

    version = core2.store.get_meta("schema_version")
    assert version == "3", f"meta.schema_version is {version!r}, expected '3'"
    kept = core2.store.count_rows("curation_jobs", "task='health'")
    assert kept == 1, f"rebuild lost the pre-existing legacy job row (kept={kept})"
    digests = core2.store.query_beliefs(
        "notes", "subject LIKE 'digest:%' AND note_type='belief' AND status='active'",
        (), limit=10)
    assert len(digests) == 1, f"expected 1 digest note after migration+drain, got {len(digests)}"
    print(f"PASS: v2 fixture migrates cleanly (schema_version={version}, "
          f"legacy rows kept={kept}, digest notes={len(digests)})")


def test_get_context_surfaces_digest():
    """get_context() carries the digest for an entity the graph channel seeds on,
    and only while the budget has room left over for it (§u2)."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    session_id = "test_session_6"
    for i, text in enumerate(["I am Pat Testley", "I work at Acme Fake Co",
                              "I live in Springfield", "My phone is 555-1234"]):
        core.capture.observe(text, "", session_id=session_id,
                             occurred_at="2024-01-0%dT00:00:00Z" % (i + 1))
    core.curation.drain(max_jobs=100)

    hint = "what do we know about the user"
    ctx = core.retrieval.get_context(hint)
    digest_lines = [l for l in ctx.split("\n") if l.startswith("[DIGEST]")]
    assert len(digest_lines) == 1, f"expected 1 digest line in context, got {digest_lines}"
    assert "=" in digest_lines[0], f"digest line carries no attributes: {digest_lines[0]}"

    tight = core.retrieval.get_context(hint, token_budget=20)
    assert "[DIGEST]" not in tight, f"digest ignored the budget gate: {tight!r}"
    print(f"PASS: get_context surfaces digest, budget-gated: {digest_lines[0][:70]}…")


if __name__ == "__main__":
    test_digest_created_on_3_facts()
    test_digest_idempotent()
    test_ask_about_includes_digest()
    test_digest_replaces_on_new_fact()
    test_get_context_surfaces_digest()
    test_migration_from_v2_fixture()
    print("\nAll acceptance tests passed.")
