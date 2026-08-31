"""
Chronicle — topic-shift episode boundaries (E6).

Within a session, `session_episode_boundaries` compares consecutive observed-
event embeddings; a neighbor-cosine drop past `curation.topic_shift_threshold`
opens a new episode. `_task_session_summarize` consumes those boundaries to
emit one summary line per episode instead of one blob. No usable per-event
vectors (no embedder, hashing not yet run, everything still queued) falls
back to a single episode -- today's behavior, byte-identical.

Two test tiers:
  * Pure unit tests of `session_episode_boundaries` / `group_by_boundaries`
    against hand-built vectors -- deterministic, no embedder, no DB (same
    style as E3's `_rerank` tests).
  * Integration tests driving `_task_session_summarize` through a real
    ChronicleCore with the offline hashing embedder, on synthetic sessions
    using the project's standard fake fixtures (Pat Testley, Acme Fake Co,
    Sam Vimes).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import Config
from engine.core import ChronicleCore
from engine.curation import group_by_boundaries, session_episode_boundaries


# -- pure unit tests: session_episode_boundaries / group_by_boundaries -----

class TestSessionEpisodeBoundaries(unittest.TestCase):
    def test_empty_vectors_returns_empty(self):
        self.assertEqual(session_episode_boundaries([], 0.35), [])

    def test_single_vector_is_one_episode(self):
        self.assertEqual(session_episode_boundaries([[1.0, 0.0]], 0.35), [0])

    def test_all_none_is_one_episode(self):
        # No usable vectors at all -- nothing to compare, one episode (the
        # fallback _task_session_summarize itself also applies below 2 usable).
        self.assertEqual(session_episode_boundaries([None, None, None], 0.35), [0])

    def test_similar_neighbors_stay_one_episode(self):
        vectors = [[1.0, 0.0], [0.95, 0.05 ** 0.5], [0.9, (1 - 0.81) ** 0.5]]
        self.assertEqual(session_episode_boundaries(vectors, 0.35), [0])

    def test_dissimilar_neighbor_opens_new_episode(self):
        # Orthogonal vectors -> cosine 0.0, well below the 0.35 default.
        vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]
        self.assertEqual(session_episode_boundaries(vectors, 0.35), [0, 2])

    def test_multiple_shifts_yield_multiple_episodes(self):
        vectors = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
        self.assertEqual(session_episode_boundaries(vectors, 0.35), [0, 1, 2])

    def test_missing_vector_does_not_itself_trigger_a_boundary(self):
        # A None slot can't be compared -- it neither opens a boundary nor
        # resets the running "prev" until a real vector follows it. The
        # boundary between index 1 and 3 is judged on 1 vs 3 directly.
        vectors = [[1.0, 0.0], [1.0, 0.0], None, [0.0, 1.0]]
        self.assertEqual(session_episode_boundaries(vectors, 0.35), [0, 3])

    def test_leading_none_does_not_crash(self):
        vectors = [None, [1.0, 0.0], [1.0, 0.0]]
        self.assertEqual(session_episode_boundaries(vectors, 0.35), [0])

    def test_threshold_is_configurable(self):
        # cosine([1,0],[0.5, 0.75**0.5]) == 0.5 -- below a strict 0.6 floor,
        # above a permissive 0.2 floor.
        vectors = [[1.0, 0.0], [0.5, 0.75 ** 0.5]]
        self.assertEqual(session_episode_boundaries(vectors, 0.6), [0, 1])
        self.assertEqual(session_episode_boundaries(vectors, 0.2), [0])


class TestGroupByBoundaries(unittest.TestCase):
    def test_empty_items(self):
        self.assertEqual(group_by_boundaries([], [0]), [])

    def test_no_boundaries_is_one_group(self):
        self.assertEqual(group_by_boundaries(["a", "b", "c"], []), [["a", "b", "c"]])

    def test_splits_at_each_boundary(self):
        self.assertEqual(group_by_boundaries(["a", "b", "c", "d"], [0, 2]),
                         [["a", "b"], ["c", "d"]])

    def test_three_way_split(self):
        self.assertEqual(group_by_boundaries(["a", "b", "c"], [0, 1, 2]),
                         [["a"], ["b"], ["c"]])


class TestTopicShiftConfig(unittest.TestCase):
    def test_default_threshold_present_and_documented(self):
        self.assertEqual(Config({}).get("curation.topic_shift_threshold"), 0.35)

    def test_threshold_overridable(self):
        cfg = Config({"curation": {"topic_shift_threshold": 0.9}})
        self.assertEqual(cfg.get("curation.topic_shift_threshold"), 0.9)
        # Overriding one curation key must not clobber its siblings (deep merge).
        self.assertEqual(cfg.get("curation.identity_threshold"), 0.85)


# -- integration: _task_session_summarize through a real ChronicleCore -----

# Fixture texts: obviously-fake subjects (Pat Testley / Acme Fake Co, Sam
# Vimes), two vocabularies with zero shared content words so the offline
# hashing embedder places them near-orthogonal.
_TOPIC_JOB = [
    "Pat Testley started a new job at Acme Fake Co as a senior widget engineer.",
    "Pat Testley's new role at Acme Fake Co involves designing the next "
    "generation of widgets.",
    "At Acme Fake Co, Pat Testley now leads the widget engineering team.",
]
_TOPIC_HIKE = [
    "Sam Vimes went hiking in the Colorado mountains last weekend and saw a bear.",
    "During the Colorado hiking trip, Sam Vimes camped near a mountain lake "
    "overnight.",
    "Sam Vimes described the bear encounter on the Colorado trail to friends "
    "afterward.",
]


def _hashing_core(tmpdir, extra_cfg=None):
    cfg = {"embeddings": {"model": "hashing", "dimensions": 256}}
    if extra_cfg:
        cfg.update(extra_cfg)
    return ChronicleCore(hermes_home=tmpdir, config=cfg)


def _capture_turns(core, session_id, texts, start_minute=0):
    for i, text in enumerate(texts):
        core.capture.append(
            "observed", {"source_type": "session_transcript", "excerpt": text},
            actor="user", session_id=session_id,
            occurred_at=f"2026-01-01T00:{start_minute + i:02d}:00Z")


def _summary_for(core, session_id):
    core.curation._task_session_summarize({"session_id": session_id})
    rows = {s["session_id"]: s for s in core.store.iter_session_vectors()}
    return rows[session_id]["summary"]


class TestSessionSummarizeEpisodes(unittest.TestCase):
    def test_two_distinct_topics_yield_two_episodes(self):
        """E6 acceptance: a synthetic session with two clearly distinct
        topics yields 2 episodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core = _hashing_core(tmpdir)
            sid = "sess-two-topics"
            _capture_turns(core, sid, _TOPIC_JOB + _TOPIC_HIKE)
            summary = _summary_for(core, sid)
            lines = summary.split("\n")
            self.assertEqual(len(lines), 2,
                             f"expected 2 episode lines, got {len(lines)}: {lines!r}")
            self.assertIn("Acme Fake Co", lines[0])
            self.assertIn("Colorado", lines[1])

    def test_homogeneous_session_yields_one_episode(self):
        """E6 acceptance: a homogeneous session yields 1 episode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core = _hashing_core(tmpdir)
            sid = "sess-one-topic"
            _capture_turns(core, sid, _TOPIC_JOB + _TOPIC_JOB)
            summary = _summary_for(core, sid)
            lines = summary.split("\n")
            self.assertEqual(len(lines), 1,
                             f"expected 1 episode line, got {len(lines)}: {lines!r}")
            for text in _TOPIC_JOB:
                self.assertIn(text, summary)

    def test_no_usable_vectors_falls_back_to_single_blob(self):
        """No embedder is unreachable in these tests (hashing is offline and
        always succeeds), so the fallback is exercised by disabling inline
        reduce: events land with zero per-event vectors, exactly the shape
        DEGRADED mode leaves behind. The result must be byte-identical to
        the pre-E6 single-blob join."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core = _hashing_core(tmpdir)
            sid = "sess-no-vectors"
            core.store.reducer = None  # events append without inline embedding
            texts = _TOPIC_JOB + _TOPIC_HIKE
            for i, text in enumerate(texts):
                core.store.append_event({
                    "event_id": f"ev{i}", "type": "observed",
                    "payload": json.dumps({"excerpt": text}),
                    "actor": "user", "owner": "default", "session_id": sid,
                    "occurred_at": f"2026-01-01T00:{i:02d}:00Z"})
            self.assertEqual(core.store.iter_observed_vectors(), [])

            summary = _summary_for(core, sid)
            expected = " ".join(texts)[:1000]
            self.assertEqual(summary, expected)
            self.assertNotIn("\n", summary)

    def test_excluded_session_prefix_still_skips_entirely(self):
        """Pre-existing behavior (embeddings.exclude_session_prefixes) must
        be untouched by E6: an excluded session is never summarized at all."""
        with tempfile.TemporaryDirectory() as tmpdir:
            core = _hashing_core(
                tmpdir, {"embeddings": {"model": "hashing", "dimensions": 256,
                                        "exclude_session_prefixes": ["scratch-"]}})
            sid = "scratch-1"
            _capture_turns(core, sid, _TOPIC_JOB + _TOPIC_HIKE)
            core.curation._task_session_summarize({"session_id": sid})
            sess_ids = {s["session_id"] for s in core.store.iter_session_vectors()}
            self.assertNotIn(sid, sess_ids)


if __name__ == "__main__":
    unittest.main()
