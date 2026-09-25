"""Test X2: git_queue defaults to disabled unless explicitly enabled.

Why: scripts that construct MemoryStore directly bypass core.py, which normally
sets the queue_git flag from config. Defaulting to True caused an undrained queue
(800k rows). This test verifies:
- append_event with queue_git disabled -> git_queue stays at 0
- setting queue_git=True, append_event -> git_queue increments to 1
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from engine.store import MemoryStore


class TestGitQueueDefaultDisabled(unittest.TestCase):
    """Verify git_queue defaults to disabled (False) not enabled (True)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_x2_")
        self.db_path = os.path.join(self.temp_dir, "chronicle.db")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_event(self, event_id: str) -> dict:
        """Create a minimal valid event for append_event()."""
        return {
            "event_id": event_id,
            "type": "text",
            "payload": {"text": "test event"},
            "actor": "user",
            "owner": "test",
            "occurred_at": "2026-01-01T00:00:00Z",
        }

    def test_append_event_with_default_queue_git_false(self):
        """With queue_git defaulting to False, git_queue should not grow."""
        store = MemoryStore(self.db_path)
        try:
            # Initial state: git_queue is empty
            self.assertEqual(store.count_rows("git_queue"), 0)

            # Append an event with the default queue_git (False)
            event = self._make_event("event-1")
            store.append_event(event)

            # git_queue should still be 0 (not queued)
            self.assertEqual(
                store.count_rows("git_queue"),
                0,
                "event should not be queued when queue_git=False (default)"
            )
        finally:
            store.close()

    def test_append_event_with_queue_git_enabled(self):
        """When queue_git=True, git_queue should grow."""
        store = MemoryStore(self.db_path)
        try:
            # Initial state: git_queue is empty
            self.assertEqual(store.count_rows("git_queue"), 0)

            # Append first event with default (False) -> should not queue
            event1 = self._make_event("event-1")
            store.append_event(event1)
            self.assertEqual(store.count_rows("git_queue"), 0)

            # Enable git queueing
            store.queue_git = True

            # Append second event with queue_git=True -> should queue
            event2 = self._make_event("event-2")
            store.append_event(event2)

            # git_queue should now have 1 row
            self.assertEqual(
                store.count_rows("git_queue"),
                1,
                "event should be queued when queue_git=True"
            )
        finally:
            store.close()
