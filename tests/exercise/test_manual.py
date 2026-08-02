"""
Chronicle — Manual integration tests (§t3.c).

~20 direct test cases through core.tools.dispatch():
  - chronicle_correct: assert belief revised + corrections row
  - chronicle_forget: assert tombstone/inactive
  - ACL set/revoke: assert read blocked/allowed for right principal

Every assertion below checks REAL store state (a row's status/read_acl column, or
the belief's actual visibility through core.retrieval.search()) — not just the
JSON status string dispatch() returns. That distinction matters here: several of
these tools accept a `belief_id` argument, and `chronicle_remember`'s return value
is `{"status": "stored", "event": <event_id>}` — the id of the `asserted` EVENT,
not the belief_id the reducer computes for the projected row. Pass that event id
back into chronicle_correct/forget/grant_read/etc. and every one of them no-ops
silently: find_belief() returns None, the write is skipped, but dispatch() still
returns its optimistic {"status": "corrected"/"retracted"/...} because those
handlers report success unconditionally rather than on confirmed effect. Trusting
the status string alone would make every one of these tests pass unconditionally
even if the write path were entirely broken. So each test here looks up the real
belief_id first (via store.query_beliefs, mirroring how a real caller would have to
search for it), then checks the row Chronicle actually wrote.
"""

import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.core import ChronicleCore
from engine import access

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("test_manual")

# This module is a standalone runner (`python3 tests/exercise/test_manual.py`), not a
# pytest suite: the wrappers below SWALLOW AssertionError so the two intentional
# KNOWN-DEFECT cases can report FAIL without aborting the run. Under pytest that
# inverts the meaning — a swallowed assertion looks like a pass — so opt the whole
# module out of collection. `__test__ = False` is honored at module scope, which also
# keeps `case()` (previously named `test()`, which pytest collected as a test wanting a
# `name` fixture → collection ERROR, breaking `pytest tests/ -v` in ci.yml:31) out.
__test__ = False

TESTS_RUN = 0
TESTS_PASSED = 0
TESTS_FAILED = []


def case(name):
    """Decorator for a test case (see `__test__` note above — not a pytest test)."""
    def decorator(fn):
        def wrapper():
            global TESTS_RUN, TESTS_PASSED
            TESTS_RUN += 1
            try:
                fn()
                TESTS_PASSED += 1
                print(f"PASS {name}")
            except AssertionError as e:
                print(f"FAIL {name}: {e}")
                TESTS_FAILED.append(name)
        return wrapper
    return decorator


def new_core(session="test_session", principal="user"):
    tmpdir = tempfile.mkdtemp(prefix="chronicle_manual_")
    core = ChronicleCore.get(tmpdir)
    core.initialize(session, hermes_home=tmpdir, principal_id=principal)
    return core, tmpdir


def real_belief_id(core, table, where, params):
    """Look up the belief_id the reducer actually assigned — the projected row,
    not the asserted-event id chronicle_remember() hands back."""
    rows = core.store.query_beliefs(table, where, params, limit=1)
    return rows[0]["belief_id"] if rows else None


# ---------------------------------------------------------------------------
# remember / search / answer / read tools
# ---------------------------------------------------------------------------

@case("remember: stores a fact and returns an event id")
def test_remember_fact():
    core, tmpdir = new_core()
    try:
        result = json.loads(core.tools.dispatch("user", "remember", {
            "kind": "fact", "content": "My favorite color is blue",
            "entity": "user", "attribute": "favorite_color", "salience": "high"}))
        assert result.get("status") == "stored", f"expected status='stored', got {result}"
        assert result.get("event"), f"missing event id in {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("search: query the belief store")
def test_search():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "note", "content": "I love hiking in the mountains"})
        result = json.loads(core.tools.dispatch("user", "chronicle_search", {"query": "hiking", "limit": 10}))
        assert "results" in result, f"missing 'results' in {result}"
        assert any("hiking" in (r.get("value") or "") for r in result["results"]), \
            f"remembered note not found by search: {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("answer: retrieve answer from memory")
def test_answer():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My birthday is July 4",
                                                 "entity": "user", "attribute": "birthday"})
        result = json.loads(core.tools.dispatch("user", "chronicle_answer", {"query": "When is your birthday?"}))
        assert "answer" in result or "abstained" in result, f"expected 'answer' or 'abstained' in {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("ask_about: retrieve all facts about an entity")
def test_ask_about():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "I live in Seattle",
                                                 "entity": "user", "attribute": "location"})
        result = json.loads(core.tools.dispatch("user", "chronicle_ask_about", {"entity": "user"}))
        assert "facts" in result, f"missing 'facts' in {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("timeline: retrieve recent episodes")
def test_timeline():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "episode", "content": "Had lunch with a friend"})
        result = json.loads(core.tools.dispatch("user", "chronicle_timeline", {}))
        assert "timeline" in result, f"missing 'timeline' in {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# chronicle_correct — real belief_id, real state check (fixed §t3 triage #2)
# ---------------------------------------------------------------------------

@case("chronicle_correct: creates a corrections row for the real belief_id")
def test_correct_creates_row():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My age is 30",
                                                 "entity": "user", "attribute": "age"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?", ("user", "age", "user"))
        assert b_id, "remembered fact not found in facts table"

        result = json.loads(core.tools.dispatch("user", "chronicle_correct", {
            "belief_id": b_id, "new_value": "My age is 31", "reason": "birthday_passed"}))
        assert result.get("status") == "corrected", f"expected status='corrected', got {result}"

        rows = core.store._conn().execute(
            "SELECT * FROM corrections WHERE belief_id=?", (b_id,)).fetchall()
        assert len(rows) > 0, "no corrections row created for the real belief_id"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("chronicle_correct: the corrected belief's OWN status actually changes")
def test_correct_changes_real_belief_status():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My age is 30",
                                                 "entity": "user", "attribute": "age"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?", ("user", "age", "user"))
        assert b_id, "remembered fact not found in facts table"
        before = core.store.get_belief("facts", b_id)
        assert before["status"] == "active", f"fixture belief should start active, got {before['status']}"

        core.tools.dispatch("user", "chronicle_correct", {
            "belief_id": b_id, "new_value": "My age is 31", "reason": "birthday_passed"})

        after = core.store.get_belief("facts", b_id)
        assert after["status"] == "superseded", \
            f"reducer._on_corrected should mark the old belief superseded, got status={after['status']!r}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("chronicle_correct: KNOWN DEFECT — new_value is never persisted as a replacement belief")
def test_correct_new_value_is_discarded():
    """reducer._on_corrected (reducer.py:161-174) marks the OLD belief superseded but
    never calls _insert_belief for p['new_body'] the way _apply_fact_conflict does for
    ordinary extraction conflicts (reducer.py:313-317). The corrected VALUE the caller
    supplied is read only to pick the supersede-vs-retract branch, then thrown away.
    Net effect: 'correcting' a fact deletes it (no active belief for that key survives)
    instead of updating it. This test documents that behavior; it is expected to FAIL
    until the engine is fixed to insert a replacement belief on correction."""
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My age is 30",
                                                 "entity": "user", "attribute": "age"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?", ("user", "age", "user"))
        assert b_id

        core.tools.dispatch("user", "chronicle_correct", {
            "belief_id": b_id, "new_value": "My age is 31", "reason": "birthday_passed"})

        active = core.store.query_beliefs(
            "facts", "entity_id=? AND attribute=? AND owner=? AND status='active'", ("user", "age", "user"))
        assert any("31" in (r.get("value") or "") for r in active), (
            "chronicle_correct(new_value='My age is 31') left NO active belief with the "
            "corrected value -- the old belief is superseded and nothing replaces it "
            "(see reducer.py:161-174 vs. reducer.py:302-334's newer_wins/flag_for_review "
            "path, which DOES insert a replacement). This is a real engine defect, not a "
            "test bug.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("chronicle_correct: no new_value -> full retract branch actually retracts")
def test_correct_without_new_value_retracts():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "note", "content": "I used to smoke", "entity": "user"})
        b_id = real_belief_id(core, "notes", "subject=? AND owner=?", ("user", "user"))
        assert b_id

        core.tools.dispatch("user", "chronicle_correct", {"belief_id": b_id, "reason": "no_longer_true"})

        after = core.store.get_belief("notes", b_id)
        assert after["status"] == "retracted", \
            f"correct() with no new_value should fully retract (reducer.py:171-172), got {after['status']!r}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# chronicle_forget — real belief_id, real state check (fixed §t3 triage #2)
# ---------------------------------------------------------------------------

@case("chronicle_forget: the real belief is retracted in the store")
def test_forget_marks_inactive():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "note", "content": "I like pizza", "entity": "user"})
        b_id = real_belief_id(core, "notes", "subject=? AND owner=?", ("user", "user"))
        assert b_id, "remembered note not found in notes table"
        assert core.store.get_belief("notes", b_id)["status"] == "active"

        result = json.loads(core.tools.dispatch("user", "chronicle_forget", {
            "belief_id": b_id, "reason": "no_longer_true"}))
        assert result.get("status") == "retracted", f"expected status='retracted', got {result}"

        after = core.store.get_belief("notes", b_id)
        assert after["status"] == "retracted", f"belief status was not actually updated: {after}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("chronicle_forget: forgotten belief drops out of real search results")
def test_forget_removes_from_search():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "note", "content": "I like anchovies", "entity": "user"})
        b_id = real_belief_id(core, "notes", "subject=? AND owner=?", ("user", "user"))
        assert b_id

        before = json.loads(core.tools.dispatch("user", "chronicle_search", {"query": "anchovies"}))
        assert any(r["belief_id"] == b_id for r in before["results"]), "fixture not visible before forget"

        core.tools.dispatch("user", "chronicle_forget", {"belief_id": b_id, "reason": "no_longer_true"})

        after = json.loads(core.tools.dispatch("user", "chronicle_search", {"query": "anchovies"}))
        assert not any(r["belief_id"] == b_id for r in after["results"]), \
            "retracted belief still returned by search — real read path did not honor the retraction"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("chronicle_withdraw_consent: unlearn tombstones + retracts the real belief")
def test_withdraw_consent_retracts():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My allergy is peanuts",
                                                 "entity": "user", "attribute": "allergy"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?",
                              ("user", "allergy", "user"))
        assert b_id

        result = json.loads(core.tools.dispatch("user", "chronicle_withdraw_consent", {"belief_id": b_id}))
        assert result.get("status") == "unlearned", f"expected status='unlearned', got {result}"

        after = core.store.get_belief("facts", b_id)
        assert after["status"] == "retracted", f"unlearn() should retract the belief, got {after['status']!r}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# ACL set/grant/revoke — real read_acl column + real search visibility
# (fixed §t3 triage #2: same real-state check applied here as chronicle_correct)
# ---------------------------------------------------------------------------

@case("set_acl(private): real read_acl column becomes owner_only")
def test_set_acl_private_column():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My SSN is secret",
                                                 "entity": "user", "attribute": "ssn"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?", ("user", "ssn", "user"))
        assert b_id

        result = json.loads(core.tools.dispatch("user", "chronicle_set_acl", {
            "belief_id": b_id, "visibility": "private"}))
        assert result.get("status") == "acl_set", f"expected status='acl_set', got {result}"

        after = core.store.get_belief("facts", b_id)
        assert after["read_acl"] == "owner_only", f"read_acl not actually updated: {after['read_acl']!r}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("set_acl(private): blocks another agent's real search, allows the owner's")
def test_set_acl_private_blocks_other_principal():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My SSN is 555-secret",
                                                 "entity": "user", "attribute": "ssn"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?", ("user", "ssn", "user"))
        assert b_id

        # Default ACL (user_agents) — every one of the user's agents may read it.
        baseline = json.loads(core.tools.dispatch("agent_a", "chronicle_search", {"query": "secret"}))
        assert any(r["belief_id"] == b_id for r in baseline["results"]), \
            "default ACL should let another agent read it before set_acl(private)"

        core.tools.dispatch("user", "chronicle_set_acl", {"belief_id": b_id, "visibility": "private"})

        blocked = json.loads(core.tools.dispatch("agent_a", "chronicle_search", {"query": "secret"}))
        assert not any(r["belief_id"] == b_id for r in blocked["results"]), \
            "chronicle_set_acl(private) did not actually block another principal's read"

        allowed = json.loads(core.tools.dispatch("user", "chronicle_search", {"query": "secret"}))
        assert any(r["belief_id"] == b_id for r in allowed["results"]), \
            "owner should still be able to read their own private belief"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("grant_read: real read_acl allows the granted principal's search")
def test_grant_read_allows_real_search():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My doctor is Dr. Smith",
                                                 "entity": "user", "attribute": "doctor"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?", ("user", "doctor", "user"))
        assert b_id
        core.tools.dispatch("user", "chronicle_set_acl", {"belief_id": b_id, "visibility": "private"})

        blocked = json.loads(core.tools.dispatch("doctor", "chronicle_search", {"query": "Smith"}))
        assert not any(r["belief_id"] == b_id for r in blocked["results"]), "should be private before grant"

        result = json.loads(core.tools.dispatch("user", "chronicle_grant_read", {
            "belief_id": b_id, "principal": "doctor"}))
        assert result.get("status") == "granted", f"expected status='granted', got {result}"

        acl = core.store.get_belief("facts", b_id)["read_acl"]
        assert "doctor" in acl, f"granted principal not present in the real read_acl: {acl!r}"

        allowed = json.loads(core.tools.dispatch("doctor", "chronicle_search", {"query": "Smith"}))
        assert any(r["belief_id"] == b_id for r in allowed["results"]), \
            "grant_read did not actually open real search access for the granted principal"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("revoke_read: real read_acl blocks the revoked principal's search again")
def test_revoke_read_blocks_real_search():
    core, tmpdir = new_core()
    try:
        core.tools.dispatch("user", "remember", {"kind": "fact", "content": "My address is 123 Main St",
                                                 "entity": "user", "attribute": "address"})
        b_id = real_belief_id(core, "facts", "entity_id=? AND attribute=? AND owner=?",
                              ("user", "address", "user"))
        assert b_id
        core.tools.dispatch("user", "chronicle_set_acl", {"belief_id": b_id, "visibility": "private"})
        core.tools.dispatch("user", "chronicle_grant_read", {"belief_id": b_id, "principal": "agent_a"})

        granted = json.loads(core.tools.dispatch("agent_a", "chronicle_search", {"query": "Main St"}))
        assert any(r["belief_id"] == b_id for r in granted["results"]), "grant should have worked first"

        result = json.loads(core.tools.dispatch("user", "chronicle_revoke_read", {
            "belief_id": b_id, "principal": "agent_a"}))
        assert result.get("status") == "revoked", f"expected status='revoked', got {result}"

        acl = core.store.get_belief("facts", b_id)["read_acl"]
        assert access.can_read(acl, "user", "agent_a") is False, \
            f"access.can_read still True for revoked principal against real read_acl {acl!r}"

        revoked = json.loads(core.tools.dispatch("agent_a", "chronicle_search", {"query": "Main St"}))
        assert not any(r["belief_id"] == b_id for r in revoked["results"]), \
            "revoke_read did not actually close real search access for the revoked principal"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# contradictions / corrections / reflections / user_knowledge (§t3.a corroboration)
# ---------------------------------------------------------------------------

@case("list_contradictions: shape check (read path)")
def test_list_contradictions():
    core, tmpdir = new_core()
    try:
        result = json.loads(core.tools.dispatch("user", "chronicle_list_contradictions", {}))
        assert "contradictions" in result and isinstance(result["contradictions"], list), \
            f"malformed response: {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("chronicle_remember: conflicting facts supersede + open a linked contradiction (fixed r5)")
def test_contradiction_from_conflicting_facts():
    """Was: KNOWN DEFECT — conflicting facts silently dropped, not flagged. Root cause was
    two-fold in `_t_remember` (tools.py): (1) it only ever set `key["domain"]="user"` --
    nested inside the key dict used for identity lookups -- and never a TOP-LEVEL `domain`
    on the asserted-event payload, so reducer.py's `event.get("domain") or p.get("domain",
    "general")` always resolved to 'general' -> policy 'refetch', whose conflict handler
    doesn't even supersede: it just bumps `last_seen_at` on the OLD row and discards the new
    value outright. (2) it hardcoded a literal `"source_event": "tool"` for every call, so
    `compute_belief_id(kind, key, [source_event])` collapsed every conflicting remember for
    the same key onto the SAME belief_id -- an in-place overwrite that would have destroyed
    the losing value and self-linked a contradiction to its own replacement (belief_a ==
    belief_b), rather than the genuine two-row supersession `history()`/`superseded_by`
    chain-walking depends on elsewhere in the engine.

    Fixed: `_t_remember` now sets a top-level `domain='user'` on fact payloads (routing into
    DOMAIN_POLICY['user'] = 'flag_for_review', reducer.py) and a per-call-unique
    `source_event` (so the new belief gets its own distinct belief_id instead of colliding
    with the existing one). Asserting two different values for the same (entity, attribute)
    now supersedes the old belief as its OWN row (value preserved, status='superseded'),
    inserts the new value as a distinct active row, opens a contradictions row linking the
    two distinct belief_ids, and the tool's reply states the conflict explicitly
    (status='conflict_recorded'). Verified directly against the store below."""
    core, tmpdir = new_core()
    try:
        r1 = json.loads(core.tools.dispatch("user", "remember", {
            "kind": "fact", "content": "My favorite color is blue",
            "entity": "user", "attribute": "favorite_color"}))
        assert r1.get("status") == "stored", f"expected first remember to be a plain store, got {r1}"

        r2 = json.loads(core.tools.dispatch("user", "remember", {
            "kind": "fact", "content": "My favorite color is green",
            "entity": "user", "attribute": "favorite_color"}))
        assert r2.get("status") == "conflict_recorded", (
            f"expected the tool reply to state the conflict explicitly, got {r2}")

        rows = core.store.query_beliefs(
            "facts", "entity_id=? AND attribute=? AND owner=?", ("user", "favorite_color", "user"))
        active_rows = [r for r in rows if r["status"] == "active"]
        superseded_rows = [r for r in rows if r["status"] == "superseded"]
        assert len(active_rows) == 1 and "green" in active_rows[0]["value"], (
            f"expected the second remember() to be the current active value 'green', "
            f"got {[(r['value'], r['status'], r['domain']) for r in rows]}"
        )
        assert len(superseded_rows) == 1 and "blue" in superseded_rows[0]["value"], (
            f"expected the FIRST remember()'s value to survive as its own superseded row "
            f"(not be destroyed by an in-place overwrite), got "
            f"{[(r['value'], r['status'], r['domain']) for r in rows]}"
        )
        assert active_rows[0]["belief_id"] != superseded_rows[0]["belief_id"], (
            "the new belief must be a distinct row from the old one, not a self-referential "
            "collapse onto the same belief_id"
        )

        contradictions = core.store.get_open_contradictions(50)
        assert len(contradictions) > 0, \
            "conflicting facts should have opened a contradictions row (they did not)"
        assert any(c["belief_a"] != c["belief_b"] for c in contradictions), (
            "the contradiction row must link two DISTINCT beliefs (belief_a != belief_b), "
            "not a self-referential one"
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("reflect: writes a real reflections row (not just a dispatch status)")
def test_reflect_writes_row():
    core, tmpdir = new_core()
    try:
        result = json.loads(core.tools.dispatch("user", "chronicle_reflect", {
            "situation": "Tried a new recipe", "action": "Added extra spices",
            "outcome": "Dish tasted better", "lesson": "Don't be afraid to experiment with cooking"}))
        assert result.get("status") == "reflected", f"expected status='reflected', got {result}"
        rid = result.get("id")
        assert rid, "missing reflection id"

        row = core.store._conn().execute("SELECT * FROM reflections WHERE id=?", (rid,)).fetchone()
        assert row is not None, (
            "chronicle_reflect returned status='reflected' but no reflections row exists -- "
            "corroborates production count=0 for this subsystem")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("note_informed: writes a real user_knowledge row (not just a dispatch status)")
def test_note_informed_writes_row():
    core, tmpdir = new_core()
    try:
        proposition = "You have 3 important meetings tomorrow"
        result = json.loads(core.tools.dispatch("user", "chronicle_note_informed", {"proposition": proposition}))
        assert result.get("status") == "noted", f"expected status='noted', got {result}"

        rows = core.store.query_user_knowledge("proposition=?", (proposition,), limit=1)
        assert rows, (
            "chronicle_note_informed returned status='noted' but no user_knowledge row exists -- "
            "corroborates production count=0 for this subsystem")
        assert rows[0]["state"] == "told", f"unexpected state: {rows[0]['state']!r}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("remember_goal: adds a standing goal")
def test_remember_goal():
    core, tmpdir = new_core()
    try:
        result = json.loads(core.tools.dispatch("user", "chronicle_remember_goal", {
            "goal": "Exercise 3 times per week"}))
        assert result.get("status") == "ok", f"expected status='ok', got {result}"
        goals = [g["goal"] for g in core.store.get_active_goals()]
        assert "Exercise 3 times per week" in goals, f"goal not actually persisted: {goals}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# misc read tools
# ---------------------------------------------------------------------------

@case("list_principals: lists all principals")
def test_list_principals():
    core, tmpdir = new_core()
    try:
        result = json.loads(core.tools.dispatch("user", "chronicle_list_principals", {}))
        assert "principals" in result, f"missing 'principals' in {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("list_derivation_rules: lists all derivation rules")
def test_list_derivation_rules():
    core, tmpdir = new_core()
    try:
        result = json.loads(core.tools.dispatch("user", "chronicle_list_derivation_rules", {}))
        assert "rules" in result, f"missing 'rules' in {result}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@case("embedding_status: reports embedder status")
def test_embedding_status():
    core, tmpdir = new_core()
    try:
        result = json.loads(core.tools.dispatch("user", "chronicle_embedding_status", {}))
        assert len(result) > 0, "expected a non-empty embedding status dict"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


ALL_TESTS = [
    test_remember_fact, test_search, test_answer, test_ask_about, test_timeline,
    test_correct_creates_row, test_correct_changes_real_belief_status,
    test_correct_new_value_is_discarded, test_correct_without_new_value_retracts,
    test_forget_marks_inactive, test_forget_removes_from_search, test_withdraw_consent_retracts,
    test_set_acl_private_column, test_set_acl_private_blocks_other_principal,
    test_grant_read_allows_real_search, test_revoke_read_blocks_real_search,
    test_list_contradictions, test_contradiction_from_conflicting_facts,
    test_reflect_writes_row, test_note_informed_writes_row, test_remember_goal,
    test_list_principals, test_list_derivation_rules, test_embedding_status,
]


def main():
    print("\n=== Manual Integration Tests (§t3.c) ===\n")
    for t in ALL_TESTS:
        t()

    print()
    print("=== Summary ===")
    print(f"Passed: {TESTS_PASSED}/{TESTS_RUN}")
    if TESTS_FAILED:
        print(f"Failed: {len(TESTS_FAILED)}")
        for name in TESTS_FAILED:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
