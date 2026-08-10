"""
Chronicle — tests for structured focus + working-set rehydration (Ladder 7, R8).

Focus becomes {topics: [...], entities: [...], task: "..."} instead of one
opaque string. Two things are scoped tightly here, on top of what R0/R2 already
cover end-to-end:

  1. `_normalize_focus` accepts every pre-R8 and R8 call shape (None, a bare
     string, and the various dict forms) and always returns the same
     {topics, entities, task} shape, so the rest of compress() never branches
     on which one it got.
  2. Re-retrieval after eviction pulls PER FACET -- each topic, the task, and
     the focus entities as a group -- rather than one query against a
     flattened focus string, and a focus entity's digest joins the working
     set directly, by identity.

A bare-string `focus_topic` (the entire pre-R8 call shape) must keep behaving
exactly as before; test_compression_fidelity.py's focus_reinjection_present
and test_context_engine_watermarks.py already cover that end-to-end, so this
file adds the NEW shapes rather than re-proving the old one.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from context import ChronicleContextEngine  # noqa: E402

CFG = {"embeddings": {"model": "hashing"}}  # offline, deterministic


def _make_engine(tag: str):
    home = tempfile.mkdtemp(prefix=f"chronicle_r8_{tag}_")
    session_id = f"sess-{tag}"
    eng = ChronicleContextEngine()
    eng.on_session_start(session_id, hermes_home=home, principal_id="tester", config=CFG)
    assert eng.core is not None, "test setup: engine failed to initialize a real core"
    return eng, session_id, home


def _filler(i: int) -> str:
    return f"padding line {i} lorem ipsum dolor sit amet consectetur adipiscing elit"


def _body(n: int) -> list[dict]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": _filler(i)} for i in range(n)]


# -- _normalize_focus: every call shape -> one shape -------------------------

class TestNormalizeFocus(unittest.TestCase):
    def test_none_is_empty_focus(self):
        self.assertEqual(ChronicleContextEngine._normalize_focus(None),
                         {"topics": [], "entities": [], "task": None})

    def test_empty_string_is_empty_focus(self):
        self.assertEqual(ChronicleContextEngine._normalize_focus("   "),
                         {"topics": [], "entities": [], "task": None})

    def test_bare_string_becomes_task_only(self):
        """The entire pre-R8 call shape: a bare focus_topic string becomes the
        `task` facet, not `topics` -- this is what keeps _keep_score's old
        `focus.lower() in content` behavior and get_context's old single-query
        reinjection working unchanged for every existing caller."""
        out = ChronicleContextEngine._normalize_focus("vetappointment")
        self.assertEqual(out, {"topics": [], "entities": [], "task": "vetappointment"})

    def test_dict_topics_as_list(self):
        out = ChronicleContextEngine._normalize_focus({"topics": ["a", "b", ""]})
        self.assertEqual(out["topics"], ["a", "b"])
        self.assertEqual(out["entities"], [])
        self.assertIsNone(out["task"])

    def test_dict_topic_singular_shorthand(self):
        out = ChronicleContextEngine._normalize_focus({"topic": "roadmap"})
        self.assertEqual(out["topics"], ["roadmap"])

    def test_dict_entities_as_single_string(self):
        out = ChronicleContextEngine._normalize_focus({"entities": "Pat Testley"})
        self.assertEqual(out["entities"], ["Pat Testley"])

    def test_dict_entity_singular_shorthand(self):
        out = ChronicleContextEngine._normalize_focus({"entity": "Pat Testley"})
        self.assertEqual(out["entities"], ["Pat Testley"])

    def test_dict_full_shape(self):
        out = ChronicleContextEngine._normalize_focus(
            {"topics": ["billing"], "entities": ["Acme Fake Co"], "task": "renew the contract"})
        self.assertEqual(out, {"topics": ["billing"], "entities": ["Acme Fake Co"],
                               "task": "renew the contract"})

    def test_dict_task_blank_string_is_none(self):
        out = ChronicleContextEngine._normalize_focus({"task": "   "})
        self.assertIsNone(out["task"])

    def test_unknown_type_degrades_to_stringified_task(self):
        # Never crash the host: an unrecognized truthy shape still yields the
        # {topics, entities, task} contract instead of raising.
        out = ChronicleContextEngine._normalize_focus(12345)
        self.assertEqual(out, {"topics": [], "entities": [], "task": "12345"})


# -- chronicle_focus tool call ------------------------------------------------

class TestFocusToolCall(unittest.TestCase):
    def setUp(self):
        self.eng, _sid, self.home = _make_engine("tool")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_structured_call_sets_all_three_facets(self):
        import json
        resp = json.loads(self.eng.handle_tool_call(
            "chronicle_focus", {"topics": ["billing", "renewal"], "entities": ["Acme Fake Co"],
                                "task": "close the deal"}))
        self.assertEqual(resp["status"], "focus_set")
        self.assertEqual(self.eng.focus["topics"], ["billing", "renewal"])
        self.assertEqual(self.eng.focus["entities"], ["Acme Fake Co"])
        self.assertEqual(self.eng.focus["task"], "close the deal")
        # legacy mirror prefers task when one is set
        self.assertEqual(self.eng.focus_topic, "close the deal")

    def test_legacy_topic_field_still_works(self):
        import json
        resp = json.loads(self.eng.handle_tool_call("chronicle_focus", {"topic": "vet appointment"}))
        self.assertEqual(self.eng.focus["topics"], ["vet appointment"])
        self.assertEqual(self.eng.focus_topic, "vet appointment")
        self.assertEqual(resp["topic"], "vet appointment")

    def test_topic_and_topics_both_given_are_unioned(self):
        self.eng.handle_tool_call("chronicle_focus", {"topics": ["a"], "topic": "b"})
        self.assertEqual(sorted(self.eng.focus["topics"]), ["a", "b"])

    def test_focus_set_by_tool_call_is_used_by_compress(self):
        """compress() with no focus kwarg at all falls back to self.focus, the
        way it always fell back to self.focus_topic pre-R8."""
        self.eng.handle_tool_call("chronicle_focus", {"task": "quarterly-roadmap"})
        pad = "padding " * 20
        relevant = [{"role": "user", "content": "quarterly-roadmap item %d: %s" % (i, pad)} for i in range(6)]
        irrelevant = [{"role": "assistant", "content": "off topic filler %d: %s" % (i, pad)} for i in range(6)]
        middle = []
        for r, ir in zip(relevant, irrelevant):
            middle.append(ir)
            middle.append(r)
        messages = ([{"role": "system", "content": "sys"}]
                   + [{"role": "user", "content": "head %d" % i} for i in range(3)]
                   + middle
                   + [{"role": "assistant", "content": "tail %d" % i} for i in range(6)])
        self.eng.update_model("test-model", context_length=800)
        out = self.eng.compress(list(messages))  # no focus kwarg -- must use self.focus
        kept = {m.get("content") for m in out}
        kept_relevant = sum(1 for m in relevant if m["content"] in kept)
        kept_irrelevant = sum(1 for m in irrelevant if m["content"] in kept)
        self.assertGreater(kept_relevant, kept_irrelevant,
                           "self.focus (set via chronicle_focus) should drive _keep_score "
                           "exactly like self.focus_topic did pre-R8")


# -- _keep_score: any facet can earn the relevance bump -----------------------

class TestKeepScoreFacets(unittest.TestCase):
    def setUp(self):
        self.eng, _sid, self.home = _make_engine("score")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _score(self, content, focus_dict):
        return self.eng._keep_score({"role": "user", "content": content}, focus_dict)

    def test_no_facet_match_is_recency_baseline(self):
        focus = {"topics": ["billing"], "entities": ["Acme Fake Co"], "task": "renew"}
        self.assertAlmostEqual(self._score("nothing to see here", focus), 0.2)

    def test_topic_facet_matches(self):
        focus = {"topics": ["billing"], "entities": [], "task": None}
        self.assertGreater(self._score("the billing cycle changed", focus), 0.2)

    def test_task_facet_matches(self):
        focus = {"topics": [], "entities": [], "task": "renew the contract"}
        self.assertGreater(self._score("we should renew the contract soon", focus), 0.2)

    def test_entity_facet_matches(self):
        """An entity name alone (no topic, no task) is enough to earn the
        relevance bump -- entities are a first-class facet, not just something
        rehydration resolves after the fact."""
        focus = {"topics": [], "entities": ["Acme Fake Co"], "task": None}
        self.assertGreater(self._score("Acme Fake Co called about the invoice", focus), 0.2)

    def test_empty_focus_is_recency_baseline(self):
        focus = {"topics": [], "entities": [], "task": None}
        self.assertAlmostEqual(self._score("anything at all", focus), 0.2)


# -- working-set rehydration: per-facet + entity digests ----------------------

class TestWorkingSetRehydration(unittest.TestCase):
    def _seed_user_digest(self, eng, sid):
        """Three first-person facts -> curation's digest job fires for the
        'user' entity (curation._DIGEST_MIN_FACTS == 3), the same fixture
        tests/test_build.py's TestDigest uses."""
        eng.core.capture.observe("I am Pat Testley", "", session_id=sid)
        eng.core.capture.observe("I work at Acme Fake Co", "", session_id=sid)
        eng.core.capture.observe("I live in Springfield", "", session_id=sid)
        eng.core.process_pending()
        digests = eng.core.store.query_beliefs(
            "notes", "subject='digest:user' AND status='active'", (), 1)
        assert digests, "test setup: expected the 'user' digest to exist before exercising rehydration"
        return digests[0]

    def test_entity_digest_joins_working_set(self):
        eng, sid, home = _make_engine("digest")
        try:
            digest = self._seed_user_digest(eng, sid)
            body = _body(10)
            result = eng.compress(body, focus={"entities": ["user"]})
            joined = "\n".join(m.get("content") or "" for m in result
                               if m.get("role") == "system" and "[Entity working set]" in (m.get("content") or ""))
            self.assertTrue(joined, "expected an '[Entity working set]' system span in the compressed output")
            self.assertIn("Acme Fake Co", joined,
                          f"digest body {digest['body']!r} should have joined the working set verbatim")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_thin_entity_falls_back_to_top_facts_not_silence(self):
        """An entity below the digest threshold (fewer than _DIGEST_MIN_FACTS
        active facts) still contributes SOMETHING to the working set -- its
        top facts -- rather than the facet silently producing nothing."""
        eng, sid, home = _make_engine("thin")
        try:
            eng.core.capture.observe("I am Pat Testley", "", session_id=sid)
            eng.core.process_pending()  # only 1 fact: below the digest threshold
            digests = eng.core.store.query_beliefs(
                "notes", "subject='digest:user' AND status='active'", (), 1)
            self.assertEqual(digests, [], "test setup: entity must NOT have a digest yet")
            lines = eng._entity_digest_lines(["user"], token_budget=200)
            self.assertTrue(lines, "a thin entity should still yield a fallback fact line")
            self.assertIn("Pat Testley", "\n".join(lines))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_per_facet_retrieval_pulls_every_facet_not_just_one(self):
        """Two markers seeded under two DIFFERENT hints (one a topic, one the
        task) must both come back -- proof rehydration queries per facet
        rather than flattening focus into a single query string, which would
        only ever surface whichever hint the single query happened to be."""
        eng, sid, home = _make_engine("perfacet")
        try:
            eng.core.capture.append(
                "observed", {"source_type": "test_seed",
                            "excerpt": "Regarding topicalpha: MARKER-ALPHA-771 is the detail."},
                actor="user", session_id=sid)
            eng.core.capture.append(
                "observed", {"source_type": "test_seed",
                            "excerpt": "Regarding topicbeta: MARKER-BETA-992 is the detail."},
                actor="user", session_id=sid)
            body = _body(10)
            result = eng.compress(body, focus={"topics": ["topicalpha"], "task": "topicbeta"})
            blob = "\n".join(m.get("content") or "" for m in result if m.get("role") == "system")
            self.assertIn("MARKER-ALPHA-771", blob, "topics facet did not pull its own memory")
            self.assertIn("MARKER-BETA-992", blob, "task facet did not pull its own memory")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_rehydration_never_exceeds_the_reinject_budget(self):
        """Splitting the reinjection budget across facets must not let the
        combined injected content exceed what a single-facet call was already
        bounded to (§R2's compress()-output-<=-budget guarantee extends to
        the multi-facet case)."""
        from engine.embeddings import estimate_tokens
        eng, sid, home = _make_engine("budget")
        try:
            eng.core.capture.append(
                "observed", {"source_type": "test_seed", "excerpt": "topicone detail " * 200},
                actor="user", session_id=sid)
            eng.core.capture.append(
                "observed", {"source_type": "test_seed", "excerpt": "topictwo detail " * 200},
                actor="user", session_id=sid)
            eng.update_model("test-model", context_length=2000)  # small, real budget
            body = _body(10)
            result = eng.compress(body, focus={"topics": ["topicone", "topictwo"]})
            injected_tokens = sum(estimate_tokens(m.get("content"))
                                  for m in result if m.get("role") == "system"
                                  and "Relevant memory" in (m.get("content") or ""))
            budget = eng._target_budget()
            self.assertLessEqual(injected_tokens, budget,
                                 "multi-facet reinjection alone must not exceed the compress() budget")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_no_focus_content_skips_rehydration(self):
        """An empty focus (no topics, no entities, no task) must not call into
        retrieval at all -- same no-op as a falsy focus_topic pre-R8."""
        eng, sid, home = _make_engine("nofocus")
        try:
            called = []
            eng.core.retrieval.get_context = lambda *a, **k: (called.append(1), "")[1]
            body = _body(10)
            eng.compress(body, focus=None)
            self.assertEqual(called, [], "get_context must not be called with an empty focus")
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
