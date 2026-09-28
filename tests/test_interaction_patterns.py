import json
import unittest

from engine.interaction_patterns import InteractionPatternMiner


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def get_events_by_type(self, type_, since_seq=0):
        self_type = type_
        assert self_type == "observed"
        return [r for r in self.rows if r.get("seq", 0) > since_seq]


def row(seq, event_id, text, *, actor="user", session="s1", occurred_at=None):
    return {
        "seq": seq,
        "event_id": event_id,
        "actor": actor,
        "session_id": session,
        "occurred_at": occurred_at,
        "payload": json.dumps(
            {
                "source_type": "session_transcript",
                "excerpt": f"User: {text}\nAssistant: acknowledged",
            }
        ),
    }


class InteractionPatternTests(unittest.TestCase):
    def test_repeated_human_signal_emits_descriptive_pattern(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Stop asking me before obvious next steps.", session="a"),
                    row(2, "e2", "Don't ask again, just do it.", session="b"),
                ]
            )
        )
        patterns = miner.mine(min_support=2)
        initiative = next(p for p in patterns if p["category"] == "initiative")
        self.assertEqual(initiative["scope"], "descriptive_only")
        self.assertEqual(initiative["support"], 2)
        self.assertEqual(set(initiative["event_ids"]), {"e1", "e2"})
        self.assertEqual(initiative["distinct_sessions"], 2)

    def test_automation_is_not_user_evidence(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Just do it.", actor="system"),
                    row(2, "e2", "Just do it.", actor="system"),
                ]
            )
        )
        self.assertEqual(miner.mine(min_support=1), [])

    def test_single_signal_does_not_become_pattern_by_default(self):
        miner = InteractionPatternMiner(FakeStore([row(1, "e1", "Be concise.")]))
        self.assertEqual(miner.mine(), [])

    def test_chunked_turn_counts_once(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Be concise.", occurred_at="2026-09-27T01:00:00Z"),
                    row(2, "e2", "Be concise.", occurred_at="2026-09-27T01:00:00Z"),
                ]
            )
        )
        self.assertEqual(miner.mine(min_support=2), [])

    def test_bare_repo_word_is_not_verification_signal(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Create a repo for this.", session="a"),
                    row(2, "e2", "That repo should be private.", session="b"),
                ]
            )
        )
        self.assertFalse(any(p["category"] == "verification" for p in miner.mine(min_support=2)))

    def test_since_seq_is_respected(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Be concise."),
                    row(2, "e2", "Be concise."),
                    row(3, "e3", "Be concise."),
                ]
            )
        )
        patterns = miner.mine(since_seq=1, min_support=2)
        brevity = next(p for p in patterns if p["category"] == "brevity")
        self.assertEqual(brevity["event_ids"], ["e2", "e3"])


if __name__ == "__main__":
    unittest.main()
