"""
Chronicle — t4 acceptance test (asserted-event parents).

Fresh temp home, ingest ~6 observe() turns, process_pending(), then verify:
- all asserted events have non-empty parents
- all parent ids exist as observed events
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
    home = tempfile.mkdtemp()
    return ChronicleCore(home, {"embeddings": {"model": "hashing"}}), home


def test_asserted_parents_forward_only():
    """Verify that asserted events created from observed events have parents set."""
    core, home = make_core()
    try:
        # Initialize with a session
        core.initialize("s1", principal_id="default")

        # Ingest ~6 observe turns (creates 6 observed events)
        core.capture.observe("My name is Pat", "ok", session_id="s1")
        core.capture.observe("I live in Denver", "ok", session_id="s1")
        core.capture.observe("I work at Acme Fake Co", "ok", session_id="s1")
        core.capture.observe("My office is downtown", "ok", session_id="s1")
        core.capture.observe("I like coffee", "ok", session_id="s1")
        core.capture.observe("I have a cat named Whiskers", "ok", session_id="s1")

        # Process pending (extract/curate)
        core.process_pending()

        # Query observed and asserted events
        observed_events_list = core.store.get_events_by_type("observed")
        asserted_events = core.store.get_events_by_type("asserted")

        # Index observed events by id
        observed_events = {ev["event_id"]: ev for ev in observed_events_list}

        # Verify asserted events have parents
        asserted_total = len(asserted_events)
        asserted_with_parents = 0
        parent_ids = 0
        parents_resolve = 0

        for ev in asserted_events:
            parents = ev.get("parents")
            if parents:
                # Parse parents if it's a JSON string
                if isinstance(parents, str):
                    try:
                        parents_list = json.loads(parents)
                    except (json.JSONDecodeError, TypeError):
                        parents_list = []
                else:
                    parents_list = parents if isinstance(parents, list) else []

                if parents_list:
                    asserted_with_parents += 1
                    # Check that all parent ids exist in observed events
                    for parent_id in parents_list:
                        parent_ids += 1
                        if parent_id in observed_events:
                            parents_resolve += 1

        # Print results
        print(f"asserted total: {asserted_total}")
        print(f"asserted with-parents: {asserted_with_parents}")
        print(f"parent ids: {parent_ids}")
        print(f"asserted parents-resolve: {parents_resolve}")

        # PASS only if every asserted event has parents and every parent resolves.
        # The resolve check counts PARENT IDS, not events: it used to be compared
        # against asserted_with_parents, which silently assumed exactly one parent
        # per asserted event. u2's consolidation digest carries one parent per
        # observed turn it summarizes, so that shortcut no longer holds — the
        # docstring invariant ("all parent ids exist as observed events") does.
        if asserted_total > 0:
            assert asserted_total == asserted_with_parents, \
                f"Not all asserted events have parents: {asserted_with_parents}/{asserted_total}"
            assert parents_resolve == parent_ids, \
                f"Not all parents resolve: {parents_resolve}/{parent_ids}"
            print("PASS")
        else:
            print("WARN: No asserted events created")
    finally:
        shutil.rmtree(home)


if __name__ == "__main__":
    test_asserted_parents_forward_only()
