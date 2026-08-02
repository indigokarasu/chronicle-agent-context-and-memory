"""
Acceptance test for t5 (occurred_at passthrough).

Tests that occurred_at parameter flows through observe(), agent_explicit(), and
delegation() to stored events.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.core import ChronicleCore


def test_observe_with_occurred_at():
    """observe() with explicit occurred_at stores the exact value."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    occurred_at = "2020-01-05T00:00:00Z"
    eid = core.capture.observe("test fact", "noted", session_id="s1", occurred_at=occurred_at)

    event = core.store.get_event(eid)
    assert event is not None, "Event not found"
    assert event["occurred_at"] == occurred_at, f"Expected {occurred_at}, got {event['occurred_at']}"
    print("PASS: observe() with occurred_at stores exact value")


def test_observe_without_occurred_at():
    """observe() without occurred_at stores a recent ISO timestamp."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    eid = core.capture.observe("test fact", "noted", session_id="s1")

    event = core.store.get_event(eid)
    assert event is not None, "Event not found"
    assert event["occurred_at"].startswith("20"), f"Expected ISO timestamp starting with '20', got {event['occurred_at']}"
    print("PASS: observe() without occurred_at stores recent ISO timestamp")


def test_agent_explicit_with_occurred_at():
    """agent_explicit() with explicit occurred_at stores the exact value."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    occurred_at = "2021-06-15T14:30:00Z"
    eid = core.capture.agent_explicit("write", "memory", "important fact", occurred_at=occurred_at)

    event = core.store.get_event(eid)
    assert event is not None, "Event not found"
    assert event["occurred_at"] == occurred_at, f"Expected {occurred_at}, got {event['occurred_at']}"
    print("PASS: agent_explicit() with occurred_at stores exact value")


def test_agent_explicit_without_occurred_at():
    """agent_explicit() without occurred_at stores a recent ISO timestamp."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    eid = core.capture.agent_explicit("write", "memory", "important fact")

    event = core.store.get_event(eid)
    assert event is not None, "Event not found"
    assert event["occurred_at"].startswith("20"), f"Expected ISO timestamp starting with '20', got {event['occurred_at']}"
    print("PASS: agent_explicit() without occurred_at stores recent ISO timestamp")


def test_delegation_with_occurred_at():
    """delegation() with explicit occurred_at stores the exact value."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    occurred_at = "2022-03-10T09:15:00Z"
    eid = core.capture.delegation("fetch data", "got 100 records", occurred_at=occurred_at)

    event = core.store.get_event(eid)
    assert event is not None, "Event not found"
    assert event["occurred_at"] == occurred_at, f"Expected {occurred_at}, got {event['occurred_at']}"
    print("PASS: delegation() with occurred_at stores exact value")


def test_delegation_without_occurred_at():
    """delegation() without occurred_at stores a recent ISO timestamp."""
    home = tempfile.mkdtemp()
    core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})

    eid = core.capture.delegation("fetch data", "got 100 records")

    event = core.store.get_event(eid)
    assert event is not None, "Event not found"
    assert event["occurred_at"].startswith("20"), f"Expected ISO timestamp starting with '20', got {event['occurred_at']}"
    print("PASS: delegation() without occurred_at stores recent ISO timestamp")


if __name__ == "__main__":
    test_observe_with_occurred_at()
    test_observe_without_occurred_at()
    test_agent_explicit_with_occurred_at()
    test_agent_explicit_without_occurred_at()
    test_delegation_with_occurred_at()
    test_delegation_without_occurred_at()
    print("\nAll acceptance tests passed.")
