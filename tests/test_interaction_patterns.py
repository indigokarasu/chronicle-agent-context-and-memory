import json
import unittest

from engine.interaction_patterns import InteractionPatternMiner


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def get_events_by_type(self, type_, since_seq=0):
        assert type_ == "observed"
        return [r for r in self.rows if r.get("seq", 0) > since_seq]

    def get_observed_user_events_since(
        self, since_seq=0, *, limit=None, before_seq=None
    ):
        rows = [
            r for r in self.rows
            if r.get("seq", 0) > since_seq and r.get("actor") == "user"
        ]
        if before_seq is not None:
            rows = [r for r in rows if r.get("seq", 0) < before_seq]
        rows.sort(key=lambda r: r.get("seq", 0), reverse=True)
        return rows if limit is None else rows[:limit]


def row(
    seq,
    event_id,
    text,
    *,
    actor="user",
    session="s1",
    occurred_at=None,
    chunk_index=0,
    chunk_count=1,
):
    return {
        "type": "observed",
        "seq": seq,
        "event_id": event_id,
        "actor": actor,
        "session_id": session,
        "occurred_at": occurred_at,
        "payload": json.dumps(
            {
                "source_type": "session_transcript",
                "source_ref": session,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
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
                    row(1, "e1", "Be concise.", chunk_index=0, chunk_count=2),
                    row(2, "e2", "Be concise.", chunk_index=1, chunk_count=2),
                ]
            )
        )
        self.assertEqual(miner.mine(min_support=2), [])

    def test_same_timestamp_distinct_turns_remain_distinct(self):
        stamp = "2026-09-27T01:00:00Z"
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Be concise.", occurred_at=stamp),
                    row(2, "e2", "Be concise.", occurred_at=stamp),
                ]
            )
        )
        brevity = next(
            p for p in miner.mine(min_support=2) if p["category"] == "brevity"
        )
        self.assertEqual(brevity["support"], 2)

    def test_ineligible_automation_does_not_displace_human_limit(self):
        rows = [
            row(1, "e1", "Be concise.", session="human-a"),
            row(2, "e2", "Be concise.", session="human-b"),
        ]
        rows.extend(
            row(i, f"cron-{i}", "Be concise.", session=f"cron_{i}")
            for i in range(3, 73)
        )
        miner = InteractionPatternMiner(FakeStore(rows))
        brevity = next(
            p for p in miner.mine(limit=2, min_support=2)
            if p["category"] == "brevity"
        )
        self.assertEqual(brevity["event_ids"], ["e1", "e2"])

    def test_exact_date_is_not_fidelity_correction(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "What is the exact date?", session="a"),
                    row(2, "e2", "Give me the exact date.", session="b"),
                ]
            )
        )
        self.assertFalse(
            any(p["category"] == "fidelity" for p in miner.mine(min_support=2))
        )

    def test_missing_from_question_is_not_fidelity_correction(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "What is missing from the package?", session="a"),
                    row(2, "e2", "What is missing from the package?", session="b"),
                ]
            )
        )
        self.assertFalse(
            any(p["category"] == "fidelity" for p in miner.mine(min_support=2))
        )

    def test_explicit_change_correction_is_fidelity_signal(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Do not alter the layout.", session="a"),
                    row(2, "e2", "You changed the layout again.", session="b"),
                ]
            )
        )
        fidelity = next(
            p for p in miner.mine(min_support=2) if p["category"] == "fidelity"
        )
        self.assertEqual(fidelity["support"], 2)

    def test_bare_repo_word_is_not_verification_signal(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Create a repo for this.", session="a"),
                    row(2, "e2", "That repo should be private.", session="b"),
                ]
            )
        )
        self.assertFalse(
            any(p["category"] == "verification" for p in miner.mine(min_support=2))
        )

    def test_word_substrings_do_not_trigger_patterns(self):
        miner = InteractionPatternMiner(
            FakeStore(
                [
                    row(1, "e1", "Run the debrief process.", session="a"),
                    row(2, "e2", "The debrief artifact exists.", session="b"),
                ]
            )
        )
        self.assertFalse(
            any(p["category"] == "brevity" for p in miner.mine(min_support=2))
        )

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
