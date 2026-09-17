"""
Chronicle — the E5 duplicate merge is an EXACT-content decision.

A merge keeps the existing belief and discards the incoming body, so it may only
happen when that body carries nothing the existing row lacks. The previous rule
merged at cosine >= 0.95 within the same subject, and that failed three ways,
each measured before this change:

  1. It dropped real updates. On the production nomic model "Standup is at 9am"
     -> "10am" scores 0.9945, "allergic to peanuts" -> "not allergic" 0.9795 and
     "offsite in Denver" -> "Boston" 0.9547, while a pure paraphrase scores
     0.9948. No floor separates the two, so the update was merged away.
  2. It only ran when an inline embed succeeded. A timed-out or absent embedder
     skipped it, and every repeat became a new active row: one production
     scope held 25,054 active directive notes with only 2,696 distinct bodies.
  3. It made the projection depend on the embedder, so a rebuild (I3) under a
     different model, or with the embedder down, merged differently from the
     live store.

The fake embedders below make the old failure deterministic instead of relying
on a real model's geometry: `_EveryTextIdentical` puts every pair at cosine 1.0
(the worst case for a similarity rule), `_TimesOutAfterFirst` is a free-tier
embedder under load. Fixtures use obviously fake values (Pat Testley, Acme Fake
Co).
"""

import json
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder

DIMS = 16
DIRECTIVE = ("Never combine [SILENT] with content — either report your findings "
             "normally, or say [SILENT] and nothing else")
NORM_KEY = {"note_type": "norm", "subject": "directive", "risk_tier": "low"}


class _EveryTextIdentical:
    """Every text embeds to the same vector: cosine 1.0 between any two."""
    model = "every-text-identical"
    dimensions = DIMS

    def __init__(self):
        self.calls = 0

    def _v(self, _text):
        self.calls += 1
        return [0.25] * DIMS

    def embed(self, text):
        return self._v(text)

    def embed_document(self, text):
        return self._v(text)

    def embed_query(self, text):
        return self._v(text)

    def embed_batch(self, texts, chunk=64):
        return [self._v(t) for t in texts]


class _TimesOutAfterFirst(HashingEmbedder):
    """Answers once, then times out on every call."""

    def __init__(self):
        super().__init__(dimensions=DIMS, model="hashing")
        self.calls = 0

    def _tick(self):
        self.calls += 1
        if self.calls > 1:
            raise TimeoutError("embed timed out")

    def embed(self, text):
        self._tick()
        return super().embed(text)

    def embed_document(self, text):
        self._tick()
        return super().embed(text)

    def embed_batch(self, texts, chunk=64):
        self._tick()
        return [super().embed(t) for t in texts]


class _Case(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing",
                                                             "dimensions": DIMS}})
        self.core.initialize("s1", principal_id="assistant")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _note(self, body, src, key=None, actor="curator"):
        self.core.capture.append(
            "asserted", {"kind": "note", "key": key or NORM_KEY, "body": body,
                         "confidence": 0.7, "source_event": src,
                         "source_type": "rescue_extraction"},
            actor=actor, owner="default")
        self.core.process_pending()

    def _active_notes(self):
        c = sqlite3.connect(self.core.store.db_path)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "SELECT belief_id, body, status, occurrence_count, provenance, created_at "
            "FROM notes WHERE status='active' ORDER BY body")]
        c.close()
        return rows


class TestUpdatesAreNeverMergedAway(_Case):
    def test_a_changed_time_survives_even_at_cosine_one(self):
        self.core.reducer.embedder = _EveryTextIdentical()
        key = {"note_type": "belief", "subject": "acme standup"}
        self._note("Standup is at 9am on Mondays", "ev_old", key=key, actor="user")
        self._note("Standup is at 10am on Mondays", "ev_new", key=key, actor="user")
        bodies = [n["body"] for n in self._active_notes()]
        self.assertEqual(bodies, ["Standup is at 10am on Mondays",
                                  "Standup is at 9am on Mondays"],
                         "the update was merged into the old value")

    def test_a_negation_survives(self):
        self.core.reducer.embedder = _EveryTextIdentical()
        key = {"note_type": "belief", "subject": "pat allergies"}
        self._note("Pat Testley is allergic to peanuts", "ev_a", key=key, actor="user")
        self._note("Pat Testley is not allergic to peanuts", "ev_b", key=key, actor="user")
        self.assertEqual(len(self._active_notes()), 2)


class TestExactRepeatsMergeWhateverTheEmbedderDoes(_Case):
    def _assert_one_row_seen_three_times(self):
        notes = self._active_notes()
        self.assertEqual(len(notes), 1, "repeats became separate active rows")
        self.assertEqual(notes[0]["occurrence_count"], 3)
        prov = json.loads(notes[0]["provenance"])
        self.assertEqual(len(prov.get("provenances", [])), 3)

    def test_healthy_embedder(self):
        for i in range(3):
            self._note(DIRECTIVE, "ev_%d" % i)
        self._assert_one_row_seen_three_times()

    def test_embedder_that_times_out(self):
        self.core.reducer.embedder = _TimesOutAfterFirst()
        for i in range(3):
            self._note(DIRECTIVE, "ev_%d" % i)
        self._assert_one_row_seen_three_times()

    def test_no_embedder(self):
        self.core.reducer.embedder = None
        for i in range(3):
            self._note(DIRECTIVE, "ev_%d" % i)
        self._assert_one_row_seen_three_times()

    def test_a_repeat_is_not_embedded_at_all(self):
        emb = _EveryTextIdentical()
        self.core.reducer.embedder = emb
        self._note(DIRECTIVE, "ev_0")
        after_first = emb.calls
        self._note(DIRECTIVE, "ev_1")
        self._note(DIRECTIVE, "ev_2")
        self.assertEqual(emb.calls, after_first,
                         "a byte-identical repeat spent embed calls it cannot use")


class TestTheSurvivorIsTheOldestRow(_Case):
    def test_legacy_duplicates_fold_into_the_oldest(self):
        """Stores written before this change already hold identical active rows.
        The merge must pick one by (created_at, belief_id), not by rowid."""
        with self.core.store.transaction() as conn:
            for bid, created in (("b_newer_first_by_rowid", "2026-08-02T00:00:00Z"),
                                 ("b_older_second_by_rowid", "2026-08-01T00:00:00Z")):
                conn.execute(
                    "INSERT INTO notes(belief_id, note_type, subject, body, owner, domain, "
                    "status, created_at, provenance, occurrence_count) "
                    "VALUES(?, 'norm', 'directive', ?, 'default', 'general', 'active', ?, "
                    "'{\"source_type\": \"rescue_extraction\"}', 1)",
                    (bid, DIRECTIVE, created))
        self._note(DIRECTIVE, "ev_new")
        counts = {n["belief_id"]: n["occurrence_count"] for n in self._active_notes()}
        self.assertEqual(counts.get("b_older_second_by_rowid"), 2, counts)
        self.assertEqual(counts.get("b_newer_first_by_rowid"), 1, counts)


class TestReplayDoesNotDependOnTheEmbedder(_Case):
    """I3: rebuild() must reproduce the belief projection from the log alone."""

    def _beliefs(self):
        return [(n["body"], n["status"], n["occurrence_count"]) for n in self._active_notes()]

    def test_rebuild_under_another_model_or_none_is_identical(self):
        self.core.reducer.embedder = _EveryTextIdentical()
        key = {"note_type": "belief", "subject": "coffee"}
        self._note("Pat Testley takes oat milk in coffee", "ev_1", key=key, actor="user")
        self._note("Pat Testley switched to almond milk for coffee", "ev_2", key=key, actor="user")
        self._note(DIRECTIVE, "ev_3")
        self._note(DIRECTIVE, "ev_4")
        live = self._beliefs()
        self.assertEqual(len(live), 3)

        self.core.reducer.embedder = HashingEmbedder(dimensions=DIMS, model="hashing")
        self.core.reducer.rebuild()
        self.assertEqual(self._beliefs(), live, "rebuild under another model diverged")

        self.core.reducer.embedder = None
        self.core.reducer.rebuild()
        self.assertEqual(self._beliefs(), live, "rebuild with no embedder diverged")


class TestScopeStillBoundsTheMerge(_Case):
    def test_identical_body_under_another_subject_is_kept(self):
        self._note(DIRECTIVE, "ev_a")
        self._note(DIRECTIVE, "ev_b", key={"note_type": "norm", "subject": "other directive",
                                          "risk_tier": "low"})
        self.assertEqual(len(self._active_notes()), 2)

    def test_identical_body_for_another_owner_is_kept(self):
        self._note(DIRECTIVE, "ev_a")
        self.core.capture.append(
            "asserted", {"kind": "note", "key": NORM_KEY, "body": DIRECTIVE, "confidence": 0.7,
                         "source_event": "ev_b", "source_type": "rescue_extraction"},
            actor="curator", owner="someone_else")
        self.core.process_pending()
        c = sqlite3.connect(self.core.store.db_path)
        owners = sorted(r[0] for r in c.execute("SELECT owner FROM notes WHERE status='active'"))
        c.close()
        self.assertEqual(owners, ["default", "someone_else"])


if __name__ == "__main__":
    unittest.main()
