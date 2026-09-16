"""
Chronicle — identity evidence: split/merge CANDIDATES (issue #8, E7).

The property under test is a NEGATIVE one first and a positive one second:
nothing in this feature may ever merge or split an entity, and within that
constraint it must still notice both risks. One real-world name can be two
people, and two different-looking records can be one person — so the code has to
raise both as QUESTIONS on an adjudication queue.

Fixtures are obviously fake (Sam Vimes, Pat Testley, Acme Fake Co) and the
embedder is the deterministic offline hashing one, whose geometry is checked
in-band by test_fixture_geometry_trips_the_shipped_thresholds so a threshold
change can never leave these tests passing vacuously.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine import identity
from engine.capture import CaptureEngine
from engine.config import Config
from engine.embeddings import HashingEmbedder, cosine, pack
from engine.reducer import Reducer
from engine.core import ChronicleCore
from engine.store import SCHEMA_VERSION, MemoryStore
from provider import ChronicleMemoryProvider

# One name, two starkly different lives (the split risk).
VIMES_BAKER = ("bakes sourdough loaves before dawn at the village bakery, "
               "dusting flour across wooden proving trays")
VIMES_ASTRONAUT = ("piloted the orbital docking module during a spacewalk, "
                   "monitoring thruster telemetry from mission control")
# Two differently-spelled records, one job (the merge risk).
TESTLEY_CONTEXT = ("coordinates logistics at Acme Fake Co from the Dublin office "
                   "and runs the Tuesday inventory review")


def _fact(cap, entity_id, pred, body, src, entity_name=None, domain="user"):
    key = {"entity_id": entity_id, "predicate_canonical": pred, "attribute": pred,
           "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": domain}
    if entity_name:
        key["entity_name"] = entity_name
    return cap.append("asserted",
                      {"kind": "fact", "key": key, "body": body, "confidence": 0.9,
                       "source_event": src, "source_type": "user_direct", "domain": domain},
                      actor="user", owner="default", trust_level=4)


class _Rig(unittest.TestCase):
    """Store + hashing-embedder reducer + capture, the way the real write path runs."""

    embedder = "hashing"

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.store = MemoryStore(self.path)
        emb = HashingEmbedder(dimensions=256) if self.embedder == "hashing" else None
        self.reducer = Reducer(self.store, emb, Config({}))
        self.store.reducer = self.reducer
        self.cap = CaptureEngine(self.store, self.reducer)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass

    # -- snapshots ---------------------------------------------------------

    def entities_dump(self):
        """Every column of every entity row — the thing that must not move."""
        return self.store._conn().execute(
            "SELECT * FROM entities ORDER BY belief_id").fetchall()

    def schema_dump(self):
        return self.store._conn().execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall()

    def candidates(self, **kw):
        return self.store.get_identity_candidates(**kw)


# ---------------------------------------------------------------------------
# Guard: the fixtures must actually reach the SHIPPED thresholds.
# ---------------------------------------------------------------------------
class TestFixtureGeometry(unittest.TestCase):
    def test_fixture_geometry_trips_the_shipped_thresholds(self):
        """Read the thresholds from config, not from a literal, so a default
        change fails HERE (loudly) instead of silently making every acceptance
        test below assert nothing."""
        cfg = Config({})
        emb = HashingEmbedder(dimensions=256)
        split_below = cfg.get("identity.split_below")
        merge_above = cfg.get("identity.merge_above")
        self.assertEqual((split_below, merge_above), (0.30, 0.90))

        diverges = cosine(emb.embed(VIMES_BAKER), emb.embed(VIMES_ASTRONAUT))
        self.assertLess(diverges, split_below,
                        "baker/astronaut fixture no longer trips identity.split_below")
        same = cosine(emb.embed(TESTLEY_CONTEXT), emb.embed(TESTLEY_CONTEXT))
        self.assertGreater(same, merge_above,
                           "Testley fixture no longer trips identity.merge_above")


# ---------------------------------------------------------------------------
# (a) split candidate + (c) entities untouched
# ---------------------------------------------------------------------------
class TestSplitCandidate(_Rig):
    def _two_lives(self):
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker",
              entity_name="Sam Vimes")
        before = self.entities_dump()
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")
        return before

    def test_two_starkly_different_contexts_raise_a_split_candidate(self):
        self._two_lives()
        cands = self.candidates()
        self.assertEqual(len(cands), 1, cands)
        c = cands[0]
        self.assertEqual(c["kind"], "split")
        self.assertEqual(c["entity_id"], "sam_vimes")
        self.assertEqual(c["status"], "pending")
        self.assertLess(c["similarity"], 0.30)
        # The mention is named, so a reviewer can see WHICH mention diverged.
        self.assertTrue(c["mention_ref"])
        self.assertIsNotNone(self.store.get_belief("facts", c["mention_ref"]))

    def test_first_mention_alone_raises_nothing(self):
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker")
        self.assertEqual(self.candidates(), [])       # nothing to be unlike yet
        self.assertEqual(self.store.get_entity_centroid("sam_vimes")["n"], 1)

    def test_a_split_candidate_does_not_split_the_entity(self):
        """(c) The entity rows are byte-stable across the divergent mention."""
        before = self._two_lives()
        after = self.entities_dump()
        # fact_count/last_seen_at move because a FACT was written; identity
        # evidence itself must move nothing, so compare the identity columns.
        self.assertEqual([r["belief_id"] for r in before], [r["belief_id"] for r in after])
        self.assertEqual(len(after), 1, "a split candidate must not create a second entity")
        self.assertIsNone(after[0]["merged_into"])
        self.assertEqual(after[0]["name"], "Sam Vimes")
        self.assertEqual(after[0]["aliases"], "[]")

    def test_observing_a_mention_mutates_no_entity_byte(self):
        """The identity module in isolation: same divergent vector, straight in,
        with no fact write to muddy it -> the entities table is byte-identical."""
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker",
              entity_name="Sam Vimes")
        before = self.entities_dump()
        emb = HashingEmbedder(dimensions=256)
        out = identity.observe_mention(self.store, Config({}), emb.model, "sam_vimes",
                                       "mention_direct", emb.embed(VIMES_ASTRONAUT),
                                       "2026-01-01T00:00:00.00Z")
        self.assertIsNotNone(out["split"])            # it did fire
        self.assertEqual(before, self.entities_dump())

    def test_the_divergent_mention_is_still_folded_in(self):
        """Withholding it would be ANSWERING the question the row exists to ask."""
        self._two_lives()
        self.assertEqual(self.store.get_entity_centroid("sam_vimes")["n"], 2)


# ---------------------------------------------------------------------------
# (b) merge candidate + (c) entities untouched
# ---------------------------------------------------------------------------
class TestMergeCandidate(_Rig):
    def _two_records(self):
        # Deliberately DIFFERENT names: an exact-name match has its own producer
        # (the curator's _task_identity, which since ladder-10 A8 queues a merge
        # CANDIDATE for one — see TestA8ExactNameIsACandidateNotAMerge), so the
        # interesting case HERE is two records that do not look alike but whose
        # mention contexts do.
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha",
              entity_name="Pat Testley")
        before = self.entities_dump()
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta",
              entity_name="P. Testley")
        return before

    def test_near_identical_contexts_raise_a_merge_candidate(self):
        self._two_records()
        cands = self.candidates()
        self.assertEqual(len(cands), 1, cands)
        c = cands[0]
        self.assertEqual(c["kind"], "merge")
        # Pair stored in canonical (sorted) order so (A,B) and (B,A) are ONE row.
        self.assertEqual([c["entity_id"], c["other_id"]], ["ent_pat_alpha", "ent_pat_beta"])
        self.assertEqual(c["mention_ref"], "")
        self.assertGreater(c["similarity"], 0.90)
        self.assertEqual(c["status"], "pending")

    def test_a_merge_candidate_does_not_merge_the_entities(self):
        """(c) Two rows in, two rows out, neither pointing at the other."""
        self._two_records()
        rows = self.entities_dump()
        ids = [r["belief_id"] for r in rows]
        self.assertEqual(ids, ["ent_pat_alpha", "ent_pat_beta"])
        self.assertTrue(all(r["merged_into"] is None for r in rows))
        self.assertEqual([r["name"] for r in rows], ["Pat Testley", "P. Testley"])

    def test_unrelated_entities_raise_nothing(self):
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker")
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha")
        self.assertEqual(self.candidates(), [])

    def test_an_already_merged_entity_is_not_re_proposed(self):
        self._two_records()
        self.store.update_belief("entities", "ent_pat_beta", merged_into="ent_pat_alpha")
        self.store._conn().execute("DELETE FROM identity_candidates")
        self.store._conn().commit()
        _fact(self.cap, "ent_pat_alpha", "shift", TESTLEY_CONTEXT, "ev_alpha2")
        self.assertEqual(self.candidates(), [])


# ---------------------------------------------------------------------------
# (c) nothing auto-applies, end to end
# ---------------------------------------------------------------------------
class TestNothingAutoApplies(_Rig):
    def test_entities_are_byte_stable_across_identity_processing(self):
        """Write everything, snapshot, then drive identity evidence again over
        the SAME entities. Candidates accumulate; entity rows do not move."""
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker",
              entity_name="Sam Vimes")
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha",
              entity_name="Pat Testley")
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta",
              entity_name="P. Testley")
        before = self.entities_dump()
        self.assertTrue(self.candidates())

        emb = HashingEmbedder(dimensions=256)
        cfg = Config({})
        for i, (eid, text) in enumerate([("sam_vimes", VIMES_ASTRONAUT),
                                         ("ent_pat_beta", TESTLEY_CONTEXT),
                                         ("ent_pat_alpha", TESTLEY_CONTEXT)]):
            identity.observe_mention(self.store, cfg, emb.model, eid, f"m{i}",
                                     emb.embed(text), "2026-01-02T00:00:00.00Z")

        self.assertEqual(before, self.entities_dump())
        self.assertTrue(all(r["merged_into"] is None for r in self.entities_dump()))

    def test_no_write_path_exists_that_applies_a_candidate(self):
        """There is no apply/accept surface anywhere: the store can record an
        outcome on a queue row, and that is the whole of it."""
        self.assertFalse(any(n.startswith(("apply_identity", "merge_entities",
                                           "split_entity", "apply_split", "apply_merge"))
                             for n in dir(self.store)))
        self.assertFalse(hasattr(identity, "apply_candidate"))

    def test_recording_an_outcome_still_moves_no_entity(self):
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha")
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta")
        cand = self.candidates()[0]
        before = self.entities_dump()
        self.store.resolve_identity_candidate(cand["id"], "merged")
        self.assertEqual(before, self.entities_dump())
        self.assertEqual(self.candidates(), [])                    # off the pending queue
        self.assertEqual(self.candidates(status="merged")[0]["id"], cand["id"])


# ---------------------------------------------------------------------------
# (d) queue listing API
# ---------------------------------------------------------------------------
class TestListingAPI(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.provider = ChronicleMemoryProvider()
        self.provider.initialize("s1", hermes_home=self.home, principal_id="default",
                                 config={"embeddings": {"model": "hashing", "dimensions": 256}})
        cap = self.provider.core.capture
        _fact(cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker", entity_name="Sam Vimes")
        _fact(cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")
        _fact(cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha",
              entity_name="Pat Testley")
        _fact(cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta",
              entity_name="P. Testley")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_provider_lists_both_kinds_with_similarities(self):
        rows = self.provider.list_identity_candidates()
        by_kind = {r["kind"]: r for r in rows}
        self.assertEqual(set(by_kind), {"split", "merge"}, rows)

        split = by_kind["split"]
        self.assertEqual(split["entity_ids"], ["sam_vimes"])
        self.assertEqual(split["entity_names"], ["Sam Vimes"])
        self.assertLess(split["similarity"], 0.30)
        self.assertTrue(split["mention_ref"])

        merge = by_kind["merge"]
        self.assertEqual(merge["entity_ids"], ["ent_pat_alpha", "ent_pat_beta"])
        self.assertEqual(merge["entity_names"], ["Pat Testley", "P. Testley"])
        self.assertGreater(merge["similarity"], 0.90)
        self.assertIsNone(merge["mention_ref"])
        self.assertTrue(all(r["status"] == "pending" for r in rows))

    def test_listing_filters_by_kind_and_status(self):
        self.assertEqual([r["kind"] for r in self.provider.list_identity_candidates(kind="merge")],
                         ["merge"])
        self.assertEqual(self.provider.list_identity_candidates(status="rejected"), [])
        cid = self.provider.list_identity_candidates(kind="split")[0]["candidate_id"]
        self.provider.core.store.resolve_identity_candidate(cid, "rejected")
        self.assertEqual([r["kind"] for r in self.provider.list_identity_candidates()], ["merge"])
        self.assertEqual([r["kind"] for r in
                          self.provider.list_identity_candidates(status="rejected")], ["split"])

    def test_tool_surface_lists_the_same_queue(self):
        import json
        out = json.loads(self.provider.handle_tool_call("chronicle_list_identity_candidates", {}))
        self.assertEqual(sorted(r["kind"] for r in out["identity_candidates"]),
                         ["merge", "split"])

    def test_listing_is_read_only(self):
        before = self.provider.core.store._conn().execute(
            "SELECT * FROM entities ORDER BY belief_id").fetchall()
        self.provider.list_identity_candidates()
        self.provider.handle_tool_call("chronicle_list_identity_candidates", {})
        after = self.provider.core.store._conn().execute(
            "SELECT * FROM entities ORDER BY belief_id").fetchall()
        self.assertEqual(before, after)

    def test_uninitialized_provider_returns_empty(self):
        self.assertEqual(ChronicleMemoryProvider().list_identity_candidates(), [])


# ---------------------------------------------------------------------------
# (e) dedupe
# ---------------------------------------------------------------------------
class TestDedupe(_Rig):
    def test_reprocessing_the_same_mention_does_not_duplicate_the_row(self):
        emb = HashingEmbedder(dimensions=256)
        cfg = Config({})
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker")
        for _ in range(3):
            identity.observe_mention(self.store, cfg, emb.model, "sam_vimes", "mention_astro",
                                     emb.embed(VIMES_ASTRONAUT), "2026-01-01T00:00:00.00Z")
        self.assertEqual(len(self.candidates()), 1)

    def test_meeting_the_same_pair_again_does_not_duplicate_the_row(self):
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha")
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta")
        self.assertEqual(len(self.candidates()), 1)
        _fact(self.cap, "ent_pat_alpha", "shift", TESTLEY_CONTEXT, "ev_alpha2")
        _fact(self.cap, "ent_pat_beta", "shift", TESTLEY_CONTEXT, "ev_beta2")
        self.assertEqual(len(self.candidates()), 1, "the pair must stay ONE question")

    def test_re_asserting_the_same_fact_adds_no_candidate(self):
        self._split_pair()
        first = self.candidates()
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")  # same key+src
        self.assertEqual(self.candidates(), first)

    def test_the_enqueue_is_idempotent_and_says_so(self):
        first = self.store.enqueue_identity_candidate("split", "sam_vimes", "", "m1", 0.1, "t")
        again = self.store.enqueue_identity_candidate("split", "sam_vimes", "", "m1", 0.1, "t")
        self.assertTrue(first)
        self.assertIsNone(again)
        self.assertEqual(len(self.candidates()), 1)

    def test_dedupe_does_not_resurrect_an_answered_question(self):
        self._split_pair()
        cand = self.candidates()[0]
        self.store.resolve_identity_candidate(cand["id"], "rejected")
        self.store.enqueue_identity_candidate("split", cand["entity_id"], "",
                                              cand["mention_ref"], cand["similarity"], "t")
        self.assertEqual(self.candidates(), [])
        self.assertEqual(len(self.candidates(status="rejected")), 1)

    def _split_pair(self):
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker")
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")


# ---------------------------------------------------------------------------
# (f) no embedder -> entirely inert
# ---------------------------------------------------------------------------
class TestNoEmbedderIsInert(_Rig):
    embedder = None

    def test_no_candidates_no_state_no_errors_schema_untouched(self):
        schema_before = self.schema_dump()
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker",
              entity_name="Sam Vimes")
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha")
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta")

        self.assertEqual(self.store.count_rows("identity_candidates"), 0)
        self.assertEqual(self.store.count_rows("entity_centroids"), 0)
        self.assertEqual(self.schema_dump(), schema_before)
        # …and the ordinary write path is untouched.
        self.assertEqual(self.store.count_rows("facts"), 4)
        self.assertEqual(self.store.count_rows("entities"), 3)

    def test_a_degraded_backend_is_equally_inert(self):
        """§24.4: no vector was written, so no mention context exists to fold —
        the same gate, reached from the other direction."""
        class _Degraded:
            model = "nomic-fake"
            dimensions = 768

            def embed(self, text):
                from engine.embeddings import EmbeddingsUnavailable
                raise EmbeddingsUnavailable("no backend")

        self.reducer.embedder = _Degraded()
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker")
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")
        self.assertEqual(self.store.count_rows("identity_candidates"), 0)
        self.assertEqual(self.store.count_rows("entity_centroids"), 0)
        self.assertGreater(self.store.count_rows("curation_jobs", "task='embed'"), 0)

    def test_disabled_by_config_is_inert(self):
        self.reducer.embedder = HashingEmbedder(dimensions=256)
        self.reducer.cfg = Config({"identity": {"enabled": False}})
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker")
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")
        self.assertEqual(self.store.count_rows("identity_candidates"), 0)
        self.assertEqual(self.store.count_rows("entity_centroids"), 0)


# ---------------------------------------------------------------------------
# Centroid state: incremental, bounded, model-keyed
# ---------------------------------------------------------------------------
class TestCentroidState(_Rig):
    def test_state_is_a_running_sum_plus_count(self):
        emb = HashingEmbedder(dimensions=256)
        for i in range(4):
            _fact(self.cap, "sam_vimes", f"p{i}", f"{VIMES_BAKER} number {i}", f"ev{i}")
        row = self.store.get_entity_centroid("sam_vimes")
        self.assertEqual(row["n"], 4)
        self.assertEqual(row["dims"], 256)
        self.assertEqual(row["model"], emb.model)
        self.assertEqual(len(row["sum_vec"]), 256 * 4)     # packed float32 sum, not a list

    def test_a_write_reads_one_centroid_row_not_every_mention(self):
        """The incremental contract: folding mention N+1 must not re-read the N
        mention vectors. Counted at the SQL layer."""
        for i in range(6):
            _fact(self.cap, "sam_vimes", f"p{i}", f"{VIMES_BAKER} number {i}", f"ev{i}")
        seen = []
        conn = self.store._conn()
        conn.set_trace_callback(seen.append)
        try:
            _fact(self.cap, "sam_vimes", "p_last", f"{VIMES_BAKER} number last", "ev_last")
        finally:
            conn.set_trace_callback(None)
        centroid_reads = [s for s in seen if "FROM entity_centroids" in s]
        self.assertEqual(len(centroid_reads), 2)          # own row + the bounded scan

    def test_the_identity_fold_itself_never_reads_a_vector_table(self):
        """E7's incremental claim, isolated to E7's own code.

        This assertion used to live in the write-path test above as "a fact
        write issues no SELECT against memory_vectors". That stopped being a
        statement about identity once E4 (supersede candidates) and E5
        (novelty / near-duplicate scan) landed: both legitimately read
        memory_vectors on a fact write, so the blanket form now fails for
        reasons that have nothing to do with the centroid fold.

        Asserted here against observe_mention directly, where nothing else
        runs, so it still fails if the fold ever starts re-reading mentions.
        """
        vec = [0.1] * 8
        for i in range(6):
            identity.observe_mention(self.store, Config({}), "m1", "sam_vimes",
                                     f"mention{i}", vec, "2026-01-0%dT00:00:00Z" % (i + 1))
        seen = []
        conn = self.store._conn()
        conn.set_trace_callback(seen.append)
        try:
            identity.observe_mention(self.store, Config({}), "m1", "sam_vimes",
                                     "mention_last", vec, "2026-01-08T00:00:00Z")
        finally:
            conn.set_trace_callback(None)
        self.assertFalse([s for s in seen if "memory_vectors" in s],
                         "the centroid fold must not read stored vectors")
        self.assertFalse([s for s in seen if "query_proxy_vectors" in s],
                         "E2 proxies must never reach the identity centroid")

    def test_the_merge_scan_is_bounded_by_config(self):
        cfg = Config({"identity": {"merge_scan_limit": 2}})
        self.reducer.cfg = cfg
        for i in range(6):
            _fact(self.cap, f"ent_{i}", "role", f"{TESTLEY_CONTEXT} {i}", f"ev{i}")
        seen = []
        conn = self.store._conn()
        conn.set_trace_callback(seen.append)
        try:
            _fact(self.cap, "ent_new", "role", TESTLEY_CONTEXT, "ev_new")
        finally:
            conn.set_trace_callback(None)
        scans = [s for s in seen if "FROM entity_centroids" in s and "LIMIT" in s]
        self.assertTrue(scans)
        # The bound is the LIMIT itself, not a post-filter: prove the store honours it.
        self.assertEqual(len(self.store.recent_entity_centroids(
            exclude_id="ent_new", model="hashing-v1", dims=256, limit=2)), 2)
        self.assertEqual(len(self.store.recent_entity_centroids(
            exclude_id="ent_new", model="hashing-v1", dims=256, limit=50)), 6)

    def test_a_model_change_resets_rather_than_mixes_geometries(self):
        cfg = Config({})
        emb = HashingEmbedder(dimensions=256)
        identity.observe_mention(self.store, cfg, "model-a", "sam_vimes", "m1",
                                 emb.embed(VIMES_BAKER), "t1")
        out = identity.observe_mention(self.store, cfg, "model-b", "sam_vimes", "m2",
                                       emb.embed(VIMES_ASTRONAUT), "t2")
        row = self.store.get_entity_centroid("sam_vimes")
        self.assertEqual(row["model"], "model-b")
        self.assertEqual(row["n"], 1)                      # reset, not 2
        self.assertIsNone(out["split"], "an incomparable prior must not be judged against")

    def test_scan_ignores_a_foreign_geometry(self):
        cfg = Config({})
        emb = HashingEmbedder(dimensions=256)
        identity.observe_mention(self.store, cfg, "model-a", "ent_pat_alpha", "m1",
                                 emb.embed(TESTLEY_CONTEXT), "t1")
        out = identity.observe_mention(self.store, cfg, "model-b", "ent_pat_beta", "m2",
                                       emb.embed(TESTLEY_CONTEXT), "t2")
        self.assertEqual(out["merges"], [])
        self.assertEqual(self.candidates(), [])

    def test_a_short_or_empty_vector_is_a_no_op(self):
        cfg = Config({})
        self.assertEqual(identity.observe_mention(self.store, cfg, "m", "e", "r", [], "t")["n"], 0)
        self.assertEqual(identity.observe_mention(self.store, cfg, "m", "", "r", [0.1], "t")["n"], 0)
        self.assertEqual(self.store.count_rows("entity_centroids"), 0)

    def test_a_broken_store_never_fails_the_capture(self):
        """I12: identity evidence is the last thing that may roll back a write."""
        class _Boom:
            def get_entity_centroid(self, *a, **kw):
                raise sqlite3.OperationalError("disk melted")

        out = identity.observe_mention(_Boom(), Config({}), "m", "e", "r", [1.0, 0.0], "t")
        self.assertEqual(out, {"split": None, "merges": [], "n": 0})


# ---------------------------------------------------------------------------
# Replay determinism (I3)
# ---------------------------------------------------------------------------
class TestReplay(_Rig):
    def test_rebuild_reproduces_identical_identity_state(self):
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker",
              entity_name="Sam Vimes")
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha")
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta")

        def dump():
            conn = self.store._conn()
            return (conn.execute("SELECT kind, entity_id, other_id, mention_ref, similarity, "
                                 "status, created_at FROM identity_candidates "
                                 "ORDER BY kind, entity_id, other_id, mention_ref").fetchall(),
                    conn.execute("SELECT entity_id, sum_vec, n, dims, model, updated_at "
                                 "FROM entity_centroids ORDER BY entity_id").fetchall())

        before = dump()
        self.assertTrue(before[0] and before[1])
        self.reducer.rebuild()
        self.assertEqual(before, dump(), "replay must reproduce identity state exactly")

    def test_a_rebuild_does_not_double_count_mentions(self):
        _fact(self.cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker")
        _fact(self.cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro")
        self.reducer.rebuild()
        self.assertEqual(self.store.get_entity_centroid("sam_vimes")["n"], 2)

    def test_adjudicated_outcome_survives_truncate_projection_and_replay(self):  # F4d
        """identity_candidates.status/resolved_at are projection state (§E7):
        truncate_projection wipes the table and a full replay re-derives
        fresh 'pending' rows from the SAME mention events, with no memory of
        what a reviewer already decided -- MemoryStore.resolve_identity_
        candidate (TestNothingAutoApplies.test_recording_an_outcome_still_
        moves_no_entity) is a direct projection write with nothing in the
        event log to replay. Resolving through a proper 'adjudicated' event
        instead -- keyed by the candidate's DEDUPE KEY -- must replay right
        back onto the row identity.py re-creates.

        Ladder 10 A4 note: this test used to assert the re-derived row had a
        BRAND NEW id, because the id was a uuid4 and that was the whole reason
        F4d had to address the outcome by dedupe key. The id is now derived
        FROM that dedupe key, so it is stable across a rebuild and the
        assertion is inverted. Re-derivation is still proved -- and proved more
        directly -- by truncating first and observing the table actually go
        empty before the replay refills it.
        """
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha")
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta")
        pending = self.candidates()
        self.assertEqual(len(pending), 1)
        merge = pending[0]
        self.assertEqual(merge["status"], "pending")
        old_id = merge["id"]

        self.cap.append("adjudicated", {
            "kind": merge["kind"], "entity_id": merge["entity_id"],
            "other_id": merge.get("other_id") or "", "mention_ref": merge.get("mention_ref") or "",
            "status": "merged"}, actor="user", owner="default")

        # Applied immediately (append_event reduces inline) -- off the
        # pending queue, on the resolved one, same row (same id).
        self.assertEqual(self.candidates(), [])
        resolved = self.candidates(status="merged")
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["id"], old_id)

        # Prove the row really is re-derived rather than re-found: empty the
        # projection first and check the queue is gone, THEN replay.
        self.store.truncate_projection()
        self.assertEqual(self.candidates(status=""), [],
                         "truncate_projection left identity_candidates rows behind -- "
                         "the replay below would prove nothing")
        self.reducer.rebuild()

        after_pending = self.candidates()
        after_resolved = self.candidates(status="merged")
        self.assertEqual(after_pending, [], "resolved candidate came back pending after rebuild")
        self.assertEqual(len(after_resolved), 1,
                         "the adjudicated outcome did not survive truncate_projection + replay")
        self.assertEqual(after_resolved[0]["id"], old_id,
                         "A4: the candidate id is derived from the dedupe key, so a "
                         "re-derived row must carry the SAME id")
        self.assertEqual(after_resolved[0]["kind"], merge["kind"])
        self.assertEqual(after_resolved[0]["entity_id"], merge["entity_id"])

    def test_an_unresolved_candidate_stays_pending_through_rebuild(self):  # F4d
        """The other half: rebuild must not invent a resolution either."""
        _fact(self.cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha")
        _fact(self.cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta")
        self.assertEqual(len(self.candidates()), 1)
        self.reducer.rebuild()
        after = self.candidates()
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["status"], "pending")
        self.assertIsNone(after[0]["resolved_at"])


# ---------------------------------------------------------------------------
# Migration from an old (pre-E7) store
# ---------------------------------------------------------------------------
# The projection tables an E7-less store had, reduced to what this test needs:
# a real entities row must survive, and schema_version must say 5.
_V5_SUBSET = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entities (
    belief_id TEXT PRIMARY KEY, type TEXT, name TEXT, normalized_name TEXT, aliases TEXT DEFAULT '[]',
    domain TEXT, owner TEXT, read_acl TEXT, merged_into TEXT,
    external_ref TEXT, external_provider TEXT, cache_ttl TEXT,
    fact_count INTEGER DEFAULT 0, relationship_count INTEGER DEFAULT 0,
    created_at TEXT, last_seen_at TEXT);
"""


class TestMigration(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.path)
        conn.executescript(_V5_SUBSET)
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version','5')")
        conn.execute("INSERT INTO entities(belief_id, name, normalized_name, owner, domain, "
                     "fact_count) VALUES('ent_pat_alpha','Pat Testley','pat testley',"
                     "'default','user',7)")
        conn.commit()
        conn.close()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass

    def test_a_raw_v5_store_upgrades_cleanly(self):
        store = MemoryStore(self.path)                 # runs _SCHEMA + _migrate
        self.assertEqual(store.get_meta("schema_version"), str(SCHEMA_VERSION))
        # E7 claimed 6 when it was built against a v5 store; E5 (novelty=6,
        # occurrence_count=7) and H1 (host tables) claimed the same number, so
        # the ladder-9 integration sequenced them: identity is step 8, and the
        # store's CURRENT version is 9 (H1 landed after). What E7 owns is that
        # the identity tables exist and are usable after the upgrade, asserted
        # below -- not the ladder's final number, which any later step moves.
        self.assertGreaterEqual(SCHEMA_VERSION, 8)
        # New tables exist and are usable…
        self.assertEqual(store.get_identity_candidates(), [])
        self.assertIsNone(store.get_entity_centroid("ent_pat_alpha"))
        cid = store.enqueue_identity_candidate("split", "ent_pat_alpha", "", "m1", 0.11, "t")
        self.assertTrue(cid)
        self.assertEqual(len(store.get_identity_candidates()), 1)
        # …and the pre-existing projection row was not disturbed.
        ent = store.get_belief("entities", "ent_pat_alpha")
        self.assertEqual((ent["name"], ent["fact_count"]), ("Pat Testley", 7))

    def test_the_migration_probe_recreates_the_tables_on_its_own(self):
        """_migrate must be sufficient on the connection it is handed — the same
        contract every other step in it has (probe the live schema, then fix it),
        not merely a passenger of _SCHEMA having run first."""
        store = MemoryStore(self.path)
        conn = store._conn()
        conn.executescript("DROP TABLE identity_candidates; DROP TABLE entity_centroids;")
        conn.commit()
        store._migrate(conn)
        conn.commit()
        self.assertTrue(store.enqueue_identity_candidate("merge", "a", "b", "", 0.99, "t"))
        self.assertEqual(len(store.get_identity_candidates()), 1)

    def test_a_fresh_store_and_a_migrated_one_agree_on_shape(self):
        migrated = MemoryStore(self.path)
        fd, fresh_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            fresh = MemoryStore(fresh_path)

            def shape(store):
                return store._conn().execute(
                    "SELECT type, name, sql FROM sqlite_master WHERE "
                    "name LIKE '%identity%' OR name LIKE '%centroid%' ORDER BY type, name"
                ).fetchall()

            self.assertEqual(shape(migrated), shape(fresh))
            self.assertTrue(shape(fresh))
        finally:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(fresh_path + suffix)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Housekeeping the queue shares with the rest of the projection
# ---------------------------------------------------------------------------
class TestQueueHygiene(_Rig):
    def test_the_dedupe_index_rejects_a_duplicate_at_the_sql_layer(self):
        self.store.enqueue_identity_candidate("merge", "a", "b", "", 0.95, "t")
        conn = self.store._conn()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO identity_candidates(id, kind, entity_id, other_id, "
                         "mention_ref, similarity, status, created_at) "
                         "VALUES('x','merge','a','b','',0.95,'pending','t')")
        conn.rollback()

    def test_an_unknown_kind_is_rejected(self):
        conn = self.store._conn()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO identity_candidates(id, kind, entity_id, created_at) "
                         "VALUES('x','rename','a','t')")
        conn.rollback()

    def test_packed_sums_round_trip(self):
        self.store.put_entity_centroid("e", pack([1.0, 2.0]), 2, 2, "m", "t")
        row = self.store.get_entity_centroid("e")
        self.assertEqual((row["n"], row["dims"], row["model"]), (2, 2, "m"))



# ---------------------------------------------------------------------------
# Ladder-10 A8 — an exact name match is EVIDENCE, and evidence is a question
# ---------------------------------------------------------------------------
#
# The `identity` curation task used to merge every entity pair sharing
# (normalized_name, owner, domain), stamping `evidence: exact_name_match` on a
# `merged` event. That is the premise violation this whole module exists to
# prevent, pointed at the harder direction: "Robin Placeholder" is one person
# recorded twice (a split risk), but two DIFFERENT people are both named
# "Pat Testley" (a merge risk), and an exact name match is exactly the second case.
#
# The fixture is two different people who share a name and nothing else: Sam
# Vimes who bakes before dawn, and Sam Vimes who piloted the docking module.
# Their mention contexts diverge below identity.split_below, which is the point
# — the geometry says "different", the name says "same", and the only correct
# output is a question.
class _CoreRig(unittest.TestCase):
    """A real core, so the sweep runs where it actually runs: through the
    curation worker, on the store's own write path."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a8-")
        self.core = ChronicleCore(self.home, {"embeddings": {"model": "hashing"}})
        self.core.initialize("s-a8", principal_id="assistant")
        self.store = self.core.store
        self.cap = self.core.capture

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def two_sam_vimeses(self):
        """Two entity rows, one name. Distinguishable only by their mentions."""
        _fact(self.cap, "ent_vimes_baker", "day_work", VIMES_BAKER, "ev_baker",
              entity_name="Sam Vimes")
        _fact(self.cap, "ent_vimes_astronaut", "day_work", VIMES_ASTRONAUT, "ev_astro",
              entity_name="Sam Vimes")

    def entities_dump(self):
        return self.store._conn().execute(
            "SELECT * FROM entities ORDER BY belief_id").fetchall()

    def sweep(self):
        self.core.curation._task_identity({})

    def merge_candidates(self, status="pending"):
        return self.store.get_identity_candidates(status=status, kind="merge")

    def plain_entity(self, belief_id, name="Sam Vimes"):
        """An entity row with no mention vector behind it — so the ONLY thing
        that can propose a merge for it is the name sweep, not E7's centroid
        path (16 identical contexts would otherwise raise 100 centroid
        candidates and drown the thing under test)."""
        self.store.upsert_belief("entities", {
            "belief_id": belief_id, "type": "", "name": name,
            "normalized_name": name.lower(), "aliases": "[]", "domain": "user",
            "owner": "default", "read_acl": '["*"]', "fact_count": 1,
            "relationship_count": 0, "created_at": "2026-01-01T00:00:00.00Z",
            "last_seen_at": "2026-01-01T00:00:00.00Z"})

    def merged_events(self):
        return self.store.get_events_by_type("merged")


class TestA8ExactNameIsACandidateNotAMerge(_CoreRig):
    def test_the_fixture_really_is_two_different_people(self):
        """Guard against a vacuous acceptance: the two records must share a
        normalized_name (so the sweep sees a collision) while their mention
        contexts must NOT look alike (so nothing but the name is arguing for a
        merge). Read from config, so a threshold change fails here."""
        self.two_sam_vimeses()
        names = {r["normalized_name"] for r in self.entities_dump()}
        self.assertEqual(names, {"sam vimes"})
        self.assertEqual(len(self.entities_dump()), 2)

        emb = HashingEmbedder(dimensions=256)
        sim = cosine(emb.embed(VIMES_BAKER), emb.embed(VIMES_ASTRONAUT))
        self.assertLess(sim, Config({}).get("identity.merge_above"),
                        "the two lives look alike; the name is no longer the only "
                        "thing proposing a merge and this fixture proves nothing")

    def test_two_same_name_people_stay_two_entities_and_raise_one_question(self):
        """The acceptance: two entities remain distinct AND a merge candidate is
        queued. Entity rows are compared column-for-column across the pass."""
        self.two_sam_vimeses()
        before = self.entities_dump()
        self.sweep()

        self.assertEqual(before, self.entities_dump(), "the sweep moved an entity row")
        self.assertTrue(all(r["merged_into"] is None for r in self.entities_dump()))
        self.assertEqual(self.merged_events(), [], "the sweep emitted a `merged` event")

        cands = self.merge_candidates()
        self.assertEqual(len(cands), 1, cands)
        c = cands[0]
        self.assertEqual(c["status"], "pending")
        # Canonical sorted pair, so the queue key does not depend on scan order.
        self.assertEqual([c["entity_id"], c["other_id"]],
                         sorted(["ent_vimes_baker", "ent_vimes_astronaut"]))
        self.assertEqual(c["mention_ref"], "")
        self.assertEqual(c["similarity"], 1.0)   # the NAMES are identical

    def test_reprocessing_does_not_duplicate_the_candidate(self):
        """E7's dedupe key (kind, entity_id, other_id, mention_ref) is reused
        rather than a parallel one being built, so a sweep on a cadence asks the
        same question once, not once per run."""
        self.two_sam_vimeses()
        self.sweep()
        first = self.merge_candidates()[0]["id"]
        for _ in range(4):
            self.sweep()
        cands = self.merge_candidates()
        self.assertEqual(len(cands), 1, cands)
        self.assertEqual(cands[0]["id"], first, "the candidate row was replaced")

    def test_an_answered_question_is_not_reopened_by_the_next_sweep(self):
        """INSERT OR IGNORE keeps the decision already on the row. A sweep that
        re-queued a rejected pair every night would be the auto-merge again,
        wearing the reviewer down instead of the entity."""
        self.two_sam_vimeses()
        self.sweep()
        cand = self.merge_candidates()[0]
        self.store.resolve_identity_candidate(cand["id"], "rejected")
        self.sweep()
        self.assertEqual(self.merge_candidates(status="pending"), [])
        self.assertEqual(len(self.store.get_identity_candidates(status="rejected")), 1)

    def test_a_lone_name_proposes_nothing(self):
        _fact(self.cap, "ent_vimes_baker", "day_work", VIMES_BAKER, "ev_baker",
              entity_name="Sam Vimes")
        self.sweep()
        self.assertEqual(self.merge_candidates(), [])

    def test_a_name_shared_by_many_is_capped_like_the_noise_it_is(self):
        """A name matching hundreds of entities is not evidence; a queue of
        hundreds of questions nobody can answer is not adjudication."""
        from engine.curation import _IDENTITY_MAX_CANDIDATES_PER_NAME as CAP
        for i in range(CAP + 6):
            self.plain_entity("ent_vimes_%02d" % i)
        self.sweep()
        self.assertEqual(len(self.merge_candidates()), CAP)
        self.assertEqual(self.merged_events(), [])


class TestA8TheLegitimateMergePathSurvives(_CoreRig):
    def test_an_explicit_merged_event_still_merges(self):
        """Only the INFERRED path is gone. A `merged` event records a decision a
        principal made, and reducer._on_merged still applies it."""
        self.two_sam_vimeses()
        self.cap.append("merged", {"from_entity": "ent_vimes_astronaut",
                                   "into_entity": "ent_vimes_baker",
                                   "evidence": "adjudicated_by_reviewer"},
                        actor="curator", owner="default")
        self.assertEqual(
            self.store.get_belief("entities", "ent_vimes_astronaut")["merged_into"],
            "ent_vimes_baker")

    def test_the_sweep_skips_an_already_merged_entity(self):
        self.two_sam_vimeses()
        self.cap.append("merged", {"from_entity": "ent_vimes_astronaut",
                                   "into_entity": "ent_vimes_baker",
                                   "evidence": "adjudicated_by_reviewer"},
                        actor="curator", owner="default")
        self.sweep()
        self.assertEqual(self.merge_candidates(), [])


class TestA8ThroughTheRealWorker(_CoreRig):
    def test_the_queued_job_completes_and_merges_nothing(self):
        self.two_sam_vimeses()
        before = self.entities_dump()
        self.store.enqueue_curation("identity", {})
        self.core.process_pending()
        row = [j for j in self.store.get_curation_jobs(limit=200)
               if j["task"] == "identity"][0]
        self.assertEqual(row["status"], "done", row)
        self.assertEqual(before, self.entities_dump())
        self.assertEqual(self.merged_events(), [])
        self.assertEqual(len(self.merge_candidates()), 1)

    def test_the_task_is_on_the_schedule_and_out_of_UNSCHEDULED(self):
        """A8's other half: the handler no longer infers, so A3's `identity`
        maintenance task is schedulable."""
        from engine.scheduler import UNSCHEDULED
        self.assertNotIn("identity", UNSCHEDULED)
        self.assertIn("identity", {e.task for e in self.core.scheduler.entries()})

    def test_the_historical_inferred_merges_are_counted_not_reversed(self):
        """Stores that already ran the old sweep keep their merges — un-merging
        in bulk would be inference in reverse. The count is surfaced instead."""
        self.two_sam_vimeses()
        self.cap.append("merged", {"from_entity": "ent_vimes_astronaut",
                                   "into_entity": "ent_vimes_baker",
                                   "evidence": "exact_name_match"},
                        actor="curator", owner="default")
        self.assertEqual(self.store.count_inferred_entity_merges(), 1)
        self.assertEqual(self.core.health.run()["inferred_entity_merges"], 1)
        # Still merged: nothing reversed it.
        self.assertEqual(
            self.store.get_belief("entities", "ent_vimes_astronaut")["merged_into"],
            "ent_vimes_baker")

    def test_an_adjudicated_merge_is_not_counted_as_inferred(self):
        self.two_sam_vimeses()
        self.cap.append("merged", {"from_entity": "ent_vimes_astronaut",
                                   "into_entity": "ent_vimes_baker",
                                   "evidence": "adjudicated_by_reviewer"},
                        actor="curator", owner="default")
        self.assertEqual(self.store.count_inferred_entity_merges(), 0)


if __name__ == "__main__":
    unittest.main()
