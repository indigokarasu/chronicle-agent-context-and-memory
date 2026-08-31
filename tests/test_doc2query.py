"""
Chronicle — tests for E2 doc2query (question-prediction embeddings).

Ladder 9, issue #8 E2: at write time, generate the questions an item can
answer and embed those alongside the content vector (`query_proxy_vectors`,
linked back to the parent belief/event) so a question-shaped query matches a
question-shaped proxy instead of only ever matching the item's own prose.

Covers: pure Tier-1 template generation + the H1 callback slot + its volume
bound (engine/doc2query.py); the write path (engine/reducer.py, config-gated,
never fails a capture); and the read path (engine/retrieval.py) — a proxy hit
resolves to the PARENT belief's own content/provenance and never surfaces the
generated question text as an answer.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import doc2query
from engine.config import Config
from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder
from engine.reducer import Reducer
from engine.store import MemoryStore


def make_core(overrides=None):
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    if overrides:
        cfg = _merge(cfg, overrides)
    return ChronicleCore(home, cfg), home


def _merge(a, b):
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------
# Tier-1 template generation (pure functions, no DB/embedder)
# --------------------------------------------------------------------------
class TestGenerateQuestions(unittest.TestCase):
    def test_works_at_template(self):
        qs = doc2query.generate_questions(
            "fact", {"entity_name": "Pat Testley", "attribute": "works_at",
                    "predicate_canonical": "works_at"}, "Acme Fake Co")
        self.assertTrue(qs)
        self.assertLessEqual(len(qs), doc2query.MAX_PROXIES)
        joined = " | ".join(qs).lower()
        self.assertIn("pat testley", joined)
        self.assertTrue(any("work" in q.lower() for q in qs))

    def test_attribute_outside_curated_templates_yields_no_questions(self):
        """No catch-all fallback (§ctx_eval regression fix): a generic
        'what is X's <attribute>' question for an uncurated attribute is
        near-content-free noise on a bag-of-words embedder, so uncurated
        attributes simply get no proxy rather than a weak one."""
        qs = doc2query.generate_questions(
            "fact", {"entity_name": "Sam Vimes", "attribute": "favorite_color",
                    "predicate_canonical": "favorite_color"}, "blue")
        self.assertEqual(qs, [])

    def test_no_entity_name_yields_no_questions(self):
        qs = doc2query.generate_questions(
            "fact", {"attribute": "works_at", "predicate_canonical": "works_at"}, "Acme Fake Co")
        self.assertEqual(qs, [])

    def test_note_template(self):
        qs = doc2query.generate_questions("note", {"subject": "travel plans"}, "flying to Denver")
        self.assertTrue(qs)
        self.assertTrue(all("travel plans" in q.lower() for q in qs))

    def test_unknown_kind_yields_no_questions(self):
        self.assertEqual(doc2query.generate_questions("entity", {"name": "Acme Fake Co"}, ""), [])

    def test_excerpt_simple_transform(self):
        qs = doc2query.generate_questions(
            "observed", {}, "I went to the Acme Fake Co office. Then I left.")
        self.assertEqual(len(qs), 1)
        self.assertTrue(qs[0].lower().startswith("what happened:"))
        self.assertIn("acme fake co office", qs[0].lower())

    def test_excerpt_empty_yields_no_questions(self):
        self.assertEqual(doc2query.generate_questions("observed", {}, "   "), [])

    # -- volume bound (§E2 acceptance: "≤4 proxies per item") --------------

    def test_volume_bound_enforced_via_callback(self):
        def callback(kind, key, body):
            return [f"question number {i}" for i in range(10)]
        qs = doc2query.generate_questions("fact", {"entity_name": "Pat Testley",
                                                    "attribute": "works_at"}, "Acme Fake Co",
                                          callback=callback)
        self.assertEqual(len(qs), doc2query.MAX_PROXIES)
        self.assertEqual(qs, [f"question number {i}" for i in range(doc2query.MAX_PROXIES)])

    def test_volume_bound_enforced_on_templates(self):
        for kind, key, body in (
            ("fact", {"entity_name": "Pat Testley", "attribute": "works_at"}, "Acme Fake Co"),
            ("note", {"subject": "x"}, "y"),
            ("episode", {"title": "x"}, "y"),
            ("procedure", {"name": "deploy"}, ""),
            ("reference", {"topic": "x"}, ""),
        ):
            self.assertLessEqual(len(doc2query.generate_questions(kind, key, body)), doc2query.MAX_PROXIES)

    # -- H1 host-model callback slot -----------------------------------------

    def test_callback_result_used_verbatim_when_valid(self):
        qs = doc2query.generate_questions(
            "fact", {"entity_name": "Pat Testley", "attribute": "works_at"}, "Acme Fake Co",
            callback=lambda kind, key, body: ["host generated question"])
        self.assertEqual(qs, ["host generated question"])

    def test_callback_exception_falls_back_to_template(self):
        def broken(kind, key, body):
            raise RuntimeError("host model unavailable")
        qs = doc2query.generate_questions(
            "fact", {"entity_name": "Pat Testley", "attribute": "works_at"}, "Acme Fake Co",
            callback=broken)
        self.assertTrue(qs)
        self.assertIn("pat testley", " ".join(qs).lower())

    def test_callback_falsy_result_falls_back_to_template(self):
        for bad in (None, [], ""):
            qs = doc2query.generate_questions(
                "fact", {"entity_name": "Pat Testley", "attribute": "works_at"}, "Acme Fake Co",
                callback=lambda kind, key, body, _bad=bad: _bad)
            self.assertTrue(qs, f"callback returning {bad!r} should fall back to template")

    def test_callback_never_called_for_unknown_kind_when_it_returns_nothing(self):
        # A callback covering a kind Tier-1 doesn't template for still works.
        qs = doc2query.generate_questions(
            "entity", {"name": "Acme Fake Co"}, "",
            callback=lambda kind, key, body: ["what is Acme Fake Co"])
        self.assertEqual(qs, ["what is Acme Fake Co"])


# --------------------------------------------------------------------------
# Store layer
# --------------------------------------------------------------------------
class TestQueryProxyVectorStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = MemoryStore(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_add_and_iter(self):
        self.store.add_query_proxy_vector("b1", 0, "fact", "where does Pat Testley work",
                                          b"\x00" * 4, "hashing-v1")
        self.store.add_query_proxy_vector("b1", 1, "fact", "who does Pat Testley work for",
                                          b"\x00" * 4, "hashing-v1")
        rows = self.store.iter_query_proxy_vectors()
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.store.count_query_proxy_vectors("b1"), 2)

    def test_replace_same_idx_does_not_duplicate(self):
        self.store.add_query_proxy_vector("b1", 0, "fact", "q1", b"\x00" * 4, "m1")
        self.store.add_query_proxy_vector("b1", 0, "fact", "q1-updated", b"\x01" * 4, "m1")
        rows = self.store.iter_query_proxy_vectors()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "q1-updated")

    def test_delete(self):
        self.store.add_query_proxy_vector("b1", 0, "fact", "q1", b"\x00" * 4, "m1")
        self.store.add_query_proxy_vector("b2", 0, "fact", "q2", b"\x00" * 4, "m1")
        self.store.delete_query_proxy_vectors("b1")
        rows = self.store.iter_query_proxy_vectors()
        self.assertEqual([r["belief_id"] for r in rows], ["b2"])


# --------------------------------------------------------------------------
# Write path (Reducer) — config gating, volume bound, cleanup
# --------------------------------------------------------------------------
class TestDoc2QueryWritePath(unittest.TestCase):
    def _core(self, overrides=None):
        core, home = make_core(overrides)
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        core.initialize("s1", principal_id="assistant")
        return core

    def _assert_pat_works_at_acme(self, core):
        payload = {
            "kind": "fact",
            "key": {"entity_id": "ent_pat_testley", "entity_name": "Pat Testley",
                    "predicate_canonical": "works_at", "attribute": "works_at",
                    "qualifiers_hash": "", "qualifiers": {}},
            "body": "Acme Fake Co", "confidence": 0.9, "source_event": "src1",
            "source_type": "user_direct", "domain": "user",
        }
        core.capture.append("asserted", payload, actor="user", trust_level=4, session_id="s1")
        return core.store.query_beliefs(
            "facts", "predicate_canonical='works_at' AND status='active'")[0]

    def test_belief_write_creates_proxy_vectors_by_default(self):
        core = self._core()
        f = self._assert_pat_works_at_acme(core)
        n = core.store.count_query_proxy_vectors(f["belief_id"])
        self.assertGreater(n, 0)
        self.assertLessEqual(n, doc2query.MAX_PROXIES)
        rows = [r for r in core.store.iter_query_proxy_vectors() if r["belief_id"] == f["belief_id"]]
        self.assertTrue(all(r["kind"] == "fact" for r in rows))
        self.assertTrue(all(r["model"] == core.embedder.model for r in rows))
        self.assertTrue(any("pat testley" in r["question"].lower() for r in rows))

    def test_beliefs_flag_off_disables_proxy_writes(self):
        core = self._core({"embeddings": {"doc2query": {"beliefs": False}}})
        f = self._assert_pat_works_at_acme(core)
        self.assertEqual(core.store.count_query_proxy_vectors(f["belief_id"]), 0)
        # the belief's own content vector is unaffected by the doc2query flag
        self.assertTrue(core.store.has_memory_vector(f["belief_id"], "fact"))

    def test_volume_bound_enforced_end_to_end(self):
        core = self._core()
        core.reducer.doc2query_callback = lambda kind, key, body: [f"q{i}" for i in range(9)]
        f = self._assert_pat_works_at_acme(core)
        self.assertEqual(core.store.count_query_proxy_vectors(f["belief_id"]), doc2query.MAX_PROXIES)

    def test_retract_cleans_up_proxy_vectors(self):
        core = self._core()
        f = self._assert_pat_works_at_acme(core)
        self.assertGreater(core.store.count_query_proxy_vectors(f["belief_id"]), 0)
        core.capture.append("retracted", {"belief_id": f["belief_id"], "reason": "test"},
                            actor="user", owner="assistant")
        self.assertEqual(core.store.count_query_proxy_vectors(f["belief_id"]), 0)

    def test_digest_notes_are_not_proxied(self):
        """u2 digest notes carry subject='digest:<entity_id>' -- an internal id,
        not a topic a user would ask about -- and are already excluded from
        search()'s vector channel outright; doc2query must not manufacture
        nonsense questions about them either."""
        core = self._core()
        qs = core.reducer.doc2query_text(
            "asserted", {"kind": "note", "key": {"subject": "digest:abc123"}, "body": "x"})
        self.assertEqual(qs, [])

    def test_excerpts_off_by_default(self):
        core = self._core()
        core.capture.observe("I went to the Acme Fake Co office today", "", session_id="s1")
        rows = [r for r in core.store.iter_query_proxy_vectors() if r["kind"] == "observed"]
        self.assertEqual(rows, [])

    def test_excerpts_enabled_writes_a_proxy(self):
        core = self._core({"embeddings": {"doc2query": {"excerpts": True}}})
        core.capture.observe("I went to the Acme Fake Co office today", "", session_id="s1")
        rows = [r for r in core.store.iter_query_proxy_vectors() if r["kind"] == "observed"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["question"].lower().startswith("what happened:"))

    def test_no_embedder_is_a_noop(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            store = MemoryStore(tmp.name)
            reducer = Reducer(store)  # no embedder
            from engine.capture import CaptureEngine
            cap = CaptureEngine(store, reducer)
            payload = {
                "kind": "fact",
                "key": {"entity_id": "e1", "entity_name": "Pat Testley",
                        "predicate_canonical": "works_at", "attribute": "works_at",
                        "qualifiers_hash": "", "qualifiers": {}},
                "body": "Acme Fake Co", "confidence": 0.9, "source_event": "src1",
                "source_type": "user_direct", "domain": "user",
            }
            cap.append("asserted", payload, actor="user", owner="default", trust_level=4)
            self.assertEqual(store.iter_query_proxy_vectors(), [])
        finally:
            os.unlink(tmp.name)


# --------------------------------------------------------------------------
# Read path (RetrievalEngine) — the E2 acceptance fixture
# --------------------------------------------------------------------------
class TestDoc2QueryRetrieval(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        self.core.initialize("s1", principal_id="assistant")
        payload = {
            "kind": "fact",
            "key": {"entity_id": "ent_pat_testley", "entity_name": "Pat Testley",
                    "predicate_canonical": "works_at", "attribute": "works_at",
                    "qualifiers_hash": "", "qualifiers": {}},
            "body": "Acme Fake Co", "confidence": 0.9, "source_event": "src1",
            "source_type": "user_direct", "domain": "user",
        }
        self.core.capture.append("asserted", payload, actor="user", trust_level=4, session_id="s1")
        self.fact = self.core.store.query_beliefs(
            "facts", "predicate_canonical='works_at' AND status='active'")[0]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.home, ignore_errors=True)

    def test_content_vector_alone_does_not_match_the_question(self):
        """Sanity/isolation check: the fact's own content vector is built from
        its VALUE ('Acme Fake Co'), which shares no tokens with a question
        about the subject's name -- so, absent doc2query, this fixture would
        NOT be reachable via the vector channel at all. Confirms the
        acceptance test below actually exercises the proxy path."""
        q = self.core.retrieval.query_understanding("where does Pat Testley work")
        direct = [bid for bid, _kind, _s in
                 self.core.retrieval._vector_beliefs(q["embedding"], 50)]
        self.assertNotIn(self.fact["belief_id"], direct)

    def test_proxy_vector_matches_the_question(self):
        q = self.core.retrieval.query_understanding("where does Pat Testley work")
        proxied = [bid for bid, _kind, _s in
                  self.core.retrieval._vector_proxies(q["embedding"], 50)]
        self.assertIn(self.fact["belief_id"], proxied)

    def test_search_retrieves_fixture_via_proxy_path(self):  # §E2 acceptance
        hits = self.core.retrieval.search("where does Pat Testley work", limit=20)
        by_id = {h["belief_id"]: h for h in hits}
        self.assertIn(self.fact["belief_id"], by_id)
        hit = by_id[self.fact["belief_id"]]
        self.assertIn("vector_proxy", hit["channels"])

    def test_proxy_resolves_to_parent_content_and_provenance(self):
        """A retrieval hit on a proxy must resolve to the PARENT belief's own
        value/provenance -- the generated question text is never surfaced."""
        hits = self.core.retrieval.search("where does Pat Testley work", limit=20)
        hit = next(h for h in hits if h["belief_id"] == self.fact["belief_id"])
        self.assertEqual(hit["value"], "Acme Fake Co")
        proxy_questions = {r["question"].lower() for r in self.core.store.iter_query_proxy_vectors()
                           if r["belief_id"] == self.fact["belief_id"]}
        self.assertTrue(proxy_questions)
        for h in hits:
            self.assertNotIn((h.get("value") or "").lower(), proxy_questions)
        self.assertEqual(hit["source_type"], "user_direct")  # the parent's own provenance


if __name__ == "__main__":
    unittest.main()
