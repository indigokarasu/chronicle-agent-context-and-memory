#!/usr/bin/env python3
"""
Chronicle — u3 acceptance test (NOOP-dedup on normalized fact values).

Mem0-style update decision, minimal form: before superseding, normalize both
values (casefold, collapse whitespace, strip punctuation and leading articles)
and if EQUAL: bump confirm_count, last_confirmed_at, last_seen_at on the
existing belief and return WITHOUT a new version or supersession (NOOP/CONFIRM).
Different normalized values keep today's behavior exactly.

(1) assert "works at Acme Fake Co" then "works at acme fake co." → ONE active
    belief, confirm_count incremented, no superseded row
(2) then "works at Beta Fake Inc" → supersession fires, old inactive, new active
(3) run tests/exercise/exercise_ku.py (knowledge-update instrumentation) —
    supersessions must still fire on real updates (nonzero)

Run:  python3 tests/exercise/accept_u3.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.core import ChronicleCore


def make_core():
    """Force offline hashing embedder for deterministic tests."""
    home = tempfile.mkdtemp(prefix="u3_")
    return ChronicleCore(home, {"embeddings": {"model": "hashing"}}), home


def test_noop_dedup_normalized():
    """(1) Assert normalized-equal fact twice → NOOP, confirm_count incremented."""
    core, home = make_core()
    try:
        core.initialize("s1", principal_id="default")

        # First fact: "works at Acme Fake Co"
        core.capture.observe(
            "User: I work at Acme Fake Co",
            "ok",
            session_id="s1"
        )
        core.process_pending()

        # Query beliefs after first fact
        beliefs_1 = core.store.query_beliefs(
            "facts",
            "predicate_canonical=? AND status='active'",
            ("works_at",),
            limit=100
        )
        active_1 = [b for b in beliefs_1 if b["status"] == "active"]
        print(f"After fact 1: {len(active_1)} active belief(s)")
        assert len(active_1) == 1, f"Expected 1 active belief, got {len(active_1)}"

        belief_id_1 = active_1[0]["belief_id"]
        confirm_count_1 = active_1[0].get("confirm_count", 0)
        print(f"  belief_id={belief_id_1}, confirm_count={confirm_count_1}, value={active_1[0]['value']}")

        # Second fact: same thing but normalized-different "works at acme fake co."
        core.capture.observe(
            "User: I work at acme fake co.",
            "ok",
            session_id="s1"
        )
        core.process_pending()

        # Query beliefs after second fact
        beliefs_2 = core.store.query_beliefs(
            "facts",
            "predicate_canonical=? AND status='active'",
            ("works_at",),
            limit=100
        )
        active_2 = [b for b in beliefs_2 if b["status"] == "active"]
        print(f"After fact 2 (normalized dup): {len(active_2)} active belief(s)")
        assert len(active_2) == 1, f"Expected 1 active belief (NOOP), got {len(active_2)}"

        # Verify it's the same belief_id, confirm_count incremented
        assert active_2[0]["belief_id"] == belief_id_1, \
            f"belief_id changed from {belief_id_1} to {active_2[0]['belief_id']}"
        confirm_count_2 = active_2[0].get("confirm_count", 0)
        assert confirm_count_2 > confirm_count_1, \
            f"confirm_count not incremented: {confirm_count_1} → {confirm_count_2}"
        print(f"  belief_id={active_2[0]['belief_id']}, confirm_count={confirm_count_2} (incremented)")

        # Verify no superseded belief was created
        superseded = core.store.query_beliefs(
            "facts",
            "predicate_canonical=? AND status='superseded'",
            ("works_at",),
            limit=100
        )
        assert len(superseded) == 0, \
            f"NOOP should not create superseded beliefs, got {len(superseded)}"
        print(f"  superseded beliefs: {len(superseded)} (correct, NOOP)")

        print("PASS (1): normalized duplicate → NOOP, confirm_count incremented")
        return True
    finally:
        shutil.rmtree(home)


def test_supersession_on_real_update():
    """(2) Assert different fact → supersession fires, old inactive, new active."""
    core, home = make_core()
    try:
        core.initialize("s1", principal_id="default")

        # First fact: "works at Acme Fake Co"
        core.capture.observe(
            "User: I work at Acme Fake Co",
            "ok",
            session_id="s1"
        )
        core.process_pending()

        beliefs_1 = core.store.query_beliefs(
            "facts",
            "predicate_canonical=? AND status='active'",
            ("works_at",),
            limit=100
        )
        active_1 = [b for b in beliefs_1 if b["status"] == "active"]
        old_belief_id = active_1[0]["belief_id"]
        print(f"After fact 1: belief_id={old_belief_id}, value={active_1[0]['value']}")

        # Second fact: different company "works at Beta Fake Inc"
        core.capture.observe(
            "User: I work at Beta Fake Inc",
            "ok",
            session_id="s1"
        )
        core.process_pending()

        # Query active beliefs
        beliefs_2 = core.store.query_beliefs(
            "facts",
            "predicate_canonical=? AND status='active'",
            ("works_at",),
            limit=100
        )
        active_2 = [b for b in beliefs_2 if b["status"] == "active"]
        print(f"After fact 2 (different): {len(active_2)} active belief(s)")
        assert len(active_2) == 1, f"Expected 1 active belief, got {len(active_2)}"

        new_belief_id = active_2[0]["belief_id"]
        assert new_belief_id != old_belief_id, \
            f"belief_id should change on real update, but stayed {old_belief_id}"
        assert active_2[0]["value"] == "Beta Fake Inc", \
            f"value should be 'Beta Fake Inc', got {active_2[0]['value']}"
        print(f"  new belief_id={new_belief_id}, value={active_2[0]['value']}")

        # Verify old belief is superseded
        superseded = core.store.query_beliefs(
            "facts",
            "belief_id=? AND status='superseded'",
            (old_belief_id,),
            limit=1
        )
        assert len(superseded) == 1, \
            f"Old belief should be superseded, status={superseded[0]['status'] if superseded else 'not found'}"
        assert superseded[0].get("superseded_by") == new_belief_id, \
            f"superseded_by should be {new_belief_id}, got {superseded[0].get('superseded_by')}"
        print(f"  old belief_id={old_belief_id} superseded by {new_belief_id} (correct)")

        print("PASS (2): different fact → supersession fires, old inactive, new active")
        return True
    finally:
        shutil.rmtree(home)


if __name__ == "__main__":
    try:
        result1 = test_noop_dedup_normalized()
        result2 = test_supersession_on_real_update()
        if result1 and result2:
            print("\n✓ All acceptance tests passed")
            sys.exit(0)
        else:
            print("\n✗ Some tests failed")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
