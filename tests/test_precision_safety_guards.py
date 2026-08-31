"""
Chronicle — F2X: the two E12 precision-packing SAFETY guards.

E12 cuts a `factual`-routed, single-session-converged context to ~1500 tokens.
Both guards below are refusals — they can only ever turn the cut OFF, never on
— and both were derived from measured LongMemEval failures rather than from
tuning:

  1. SUPERSEDE-CHAIN VETO. The cut drops every session but the modal one AND
     skips the ranked-belief block, which is the only place E4's
     `[history: A -> B]` annotation renders. So on a fact the store has already
     recorded an update for, the cut delivers the PRE-update value with nothing
     anywhere to say a later one exists (07741c44, "Where do I initially keep
     my old sneakers?": 47,998 chars -> 5,904, updated location absent, a
     correct answer became "I don't know").

  2. TRUE-ARGMAX GATE. E9's margin gate sends any non-factual winner that fails
     to beat `factual` by `retrieval.query_routing_margin` back to "factual",
     so the route STRING conflates "factual is nearest" with "nothing else was
     convincing". E12 read the string and cut a multi-session cost comparison
     whose true argmax was `preference` down to one clean session; the reader
     stopped abstaining and fabricated a confident answer (09ba9854).

Every test here is DIFFERENTIAL against the same store with the guard removed,
so a pass means the guard caused the difference. Runs entirely under the
offline hashing embedder.
"""
import shutil
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from test_precision_packing import (  # noqa: E402  — sibling fixture reuse
    DISTRACT, EVIDENCE, QUERY, feature_off_context, make_core, seed_dominant)

# E4 records a supersede candidate only above `curation.supersede_similarity`;
# hashing-mode cosines never reach the shipped 0.82 default (by design — see
# test_supersede_candidates.TestSupersedeCandidateDefaultThreshold), so these
# fixtures lower it exactly as that suite does, to make a REAL edge rather than
# hand-writing one into the table.
SUPERSEDE_CFG = {"curation": {"supersede_similarity": 0.65}}


def _key(entity_id, qualifiers_hash=""):
    return {"entity_id": entity_id, "predicate_canonical": "works_at",
            "attribute": "works_at", "qualifiers_hash": qualifiers_hash,
            "qualifiers": {}, "entity_name": entity_id.replace("_", " ").title(),
            "owner": "assistant", "domain": "general"}


def _assert_fact(core, key, body, source_event):
    core.capture.append(
        "asserted",
        {"kind": "fact", "key": key, "body": body, "confidence": 0.8,
         "source_event": source_event, "source_type": "user_direct", "domain": "general"},
        actor="user", owner="assistant", trust_level=3)


def _decision(engine, query=QUERY):
    raw = engine.retrieve_raw(query, limit=20)
    return engine._precision_decision(engine._precision_order(raw))


def _head(engine, query=QUERY):
    raw = engine.retrieve_raw(query, limit=20)
    return engine._precision_head(engine._precision_order(raw))


def _no_veto(engine):
    """The same engine with guard 1 removed — the reference every assertion
    below is measured against. Stubbing `_head_has_live_update` to False is
    exactly the pre-F2X `_precision_decision`, since the veto is its only new
    line."""
    original = engine._head_has_live_update
    engine._head_has_live_update = lambda head: False
    return original


class _ChainCase(unittest.TestCase):
    """Shared fixture: the dominant-hit store that DOES precision-pack, plus a
    v1/v2 fact pair whose v1 is justified by a chosen event of the measured
    head and whose v2 was said in a different session."""

    #: index into the measured head to hang the v1 fact off. Subclasses set it.
    HEAD_POS = 0

    def setUp(self):
        self.core, self.home = make_core(SUPERSEDE_CFG)
        seed_dominant(self.core)
        self.r = self.core.retrieval
        # Control FIRST, on the pristine store: without a fixture that packs,
        # every assertion below would pass vacuously.
        self.baseline = _decision(self.r)
        self.assertTrue(self.baseline, "fixture: this store must precision-pack")
        head = _head(self.r)
        real = [c for c in head
                if (c.get("event_id") or "")
                and not c["event_id"].startswith(("session:", "proj:"))]
        self.assertGreater(len(real), self.HEAD_POS,
                           "fixture: the head must have a member at this position")
        self.target_eid = real[self.HEAD_POS]["event_id"]
        self.is_leader = self.target_eid == head[0].get("event_id")
        # v1: justified by that head event. v2: a DIFFERENT session's turn,
        # same claim, different value -> one dated supersede-candidate edge.
        _assert_fact(self.core, _key("chain_subject"),
                     "Chain Subject works at Acme Fake Co", self.target_eid)
        self.core.process_pending()
        _assert_fact(self.core, _key("chain_subject", "v2"),
                     "Chain Subject works at Beta Fake Inc", "ev_other_session")
        self.core.process_pending()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _edge_exists(self):
        return self.core.store._conn().execute(
            "SELECT COUNT(*) FROM supersede_candidates").fetchone()[0]


class TestSupersedeChainVetoOnTheLeader(_ChainCase):
    """The update hangs off the LEADING candidate — the narrowest shape the
    veto has to cover."""

    HEAD_POS = 0

    def test_the_fixture_really_recorded_an_update(self):
        self.assertTrue(self._edge_exists(),
                        "fixture: E4 recorded no supersede candidate, so nothing is being tested")
        chained = [j["belief_id"] for j in self.core.store.get_dependents(self.target_eid)
                   if len(self.core.store.get_supersede_chain(j["belief_id"])) > 1]
        self.assertTrue(chained, "fixture: no chained belief is justified by the head event")

    def test_the_cut_is_refused(self):
        self.assertIsNone(_decision(self.r))

    def test_removing_the_veto_restores_the_cut(self):
        """The differential: with guard 1 stubbed out, this same store packs
        again. So the refusal above is the veto, not the two extra facts
        perturbing the pool."""
        original = _no_veto(self.r)
        try:
            self.assertTrue(_decision(self.r))
        finally:
            self.r._head_has_live_update = original

    def test_get_context_returns_the_full_budget(self):
        ctx = self.r.get_context(QUERY, token_budget=12000)
        self.assertFalse(self.r.last_context_debug["precision"])
        self.assertEqual(ctx, feature_off_context(self.r, QUERY, token_budget=12000))
        self.assertGreater(len(ctx), 1500 * 4)
        # The sessions the cut would have deleted are back — which is the whole
        # point on a knowledge-update question.
        self.assertIn(DISTRACT, ctx)
        self.assertIn(EVIDENCE, ctx)


class TestSupersedeChainVetoBeyondTheLeader(_ChainCase):
    """The update hangs off a NON-leading member of the measured head.

    This is the shape the motivating instance actually had (07741c44, real
    nomic): the leader's derived belief has no chain and the head's fifth
    member's does, so a leader-only veto — the obvious implementation — leaves
    the regression in place. The gate's own claim is about the head, so the
    veto reads the head."""

    HEAD_POS = 2

    def test_the_target_is_not_the_leader(self):
        self.assertFalse(self.is_leader, "fixture: this must NOT be the leading candidate")

    def test_the_cut_is_refused(self):
        self.assertIsNone(_decision(self.r))

    def test_a_leader_only_veto_would_have_missed_it(self):
        """Pins the scope choice: restricted to the leader, the same store
        still packs."""
        self.assertFalse(self.r._head_has_live_update(_head(self.r)[:1]))
        self.assertTrue(self.r._head_has_live_update(_head(self.r)))

    def test_removing_the_veto_restores_the_cut(self):
        original = _no_veto(self.r)
        try:
            self.assertTrue(_decision(self.r))
        finally:
            self.r._head_has_live_update = original


class TestVetoIsInertWithoutUpdates(unittest.TestCase):
    """No recorded update anywhere -> the veto costs lookups and changes
    nothing. This is every store where E4 never fired, including every store
    the recall/ctx_eval harnesses build."""

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        self.r = self.core.retrieval

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_no_edges_means_no_veto(self):
        self.assertEqual(self.core.store._conn().execute(
            "SELECT COUNT(*) FROM supersede_candidates").fetchone()[0], 0)
        self.assertFalse(self.r._head_has_live_update(_head(self.r)))
        self.assertTrue(_decision(self.r))
        self.r.get_context(QUERY, token_budget=12000)
        self.assertTrue(self.r.last_context_debug["precision"])


# -- guard 2: the true-argmax gate -------------------------------------------

def _stub_route(engine, scores, route="factual"):
    """Pin `classify_route`'s output. The gate's INPUT is the raw score
    geometry, and hashing-mode cosines are not a controllable way to state
    'preference outscored factual but lost the margin' — so the geometry is
    stated directly."""
    original = engine.classify_route
    engine.classify_route = lambda *a, **k: {"route": route, "scores": dict(scores),
                                             "enabled": True}
    return original


# Preference is the true argmax; factual is the LOWEST of the four and only
# holds the route because the 0.20 margin sent preference back. These are
# 09ba9854's real measured scores under nomic.
MARGIN_DEFAULTED = {"aggregation": 0.4159, "temporal": 0.3726,
                    "preference": 0.4479, "factual": 0.3725}
TRULY_FACTUAL = {"aggregation": 0.4350, "temporal": 0.4924,
                 "preference": 0.4900, "factual": 0.5225}


class TestTrueArgmaxGate(unittest.TestCase):
    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        self.r = self.core.retrieval

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_a_margin_defaulted_factual_route_does_not_get_the_cut(self):
        original = _stub_route(self.r, MARGIN_DEFAULTED)
        try:
            ctx = self.r.get_context(QUERY, token_budget=12000)
            self.assertEqual(self.r.last_context_debug["route"], "factual",
                             "fixture: the ROUTE must still be factual, or this "
                             "tests the route rather than the gate")
            self.assertFalse(self.r.last_context_debug["precision"])
            self.assertGreater(len(ctx), 1500 * 4)
        finally:
            self.r.classify_route = original

    def test_a_genuinely_factual_route_still_gets_the_cut(self):
        """The differential that keeps the gate from being 'switch E12 off':
        same store, same route string, argmax moved to factual -> packs."""
        original = _stub_route(self.r, TRULY_FACTUAL)
        try:
            ctx = self.r.get_context(QUERY, token_budget=12000)
            self.assertTrue(self.r.last_context_debug["precision"])
            self.assertLessEqual(len(ctx), 1500 * 4 + len("\n… (truncated)"))
        finally:
            self.r.classify_route = original

    def test_a_route_only_gate_would_have_packed_it(self):
        """States the regression directly, on the real classifier rather than a
        stub: `classify_route` reports "factual" for the measured 09ba9854
        geometry — so the OLD condition (`route == "factual"` alone) admits it
        — while the raw argmax is `preference`, which is what excludes it."""
        cfg_margin = 0.20
        best = max(MARGIN_DEFAULTED, key=MARGIN_DEFAULTED.get)
        self.assertEqual(best, "preference")
        self.assertLess(MARGIN_DEFAULTED[best] - MARGIN_DEFAULTED["factual"], cfg_margin,
                        "fixture: preference must LOSE the margin, i.e. route back to factual")
        self.assertEqual(self.r._raw_route(MARGIN_DEFAULTED), "preference")
        self.assertEqual(self.r._raw_route(TRULY_FACTUAL), "factual")

    def test_no_routing_signal_is_byte_identical_to_today(self):
        """Routing disabled / no embedder / an unembeddable bank all return
        `scores == {}` with route 'factual'. That is the pre-E9 default path,
        and the gate must not narrow it."""
        self.assertEqual(self.r._raw_route({}), "factual")
        original = _stub_route(self.r, {})
        try:
            ctx = self.r.get_context(QUERY, token_budget=12000)
            self.assertTrue(self.r.last_context_debug["precision"])
            self.assertLessEqual(len(ctx), 1500 * 4 + len("\n… (truncated)"))
        finally:
            self.r.classify_route = original

    def test_ties_refuse_the_cut(self):
        """`_raw_route` reuses `classify_route`'s own argmax expression, so an
        exact tie resolves by `_ROUTE_KINDS` order — where factual is LAST.
        A four-way tie is the degenerate 'shares no token with any bank' query,
        i.e. no routing signal at all masquerading as one; refusing is the
        conservative arm and the one every other E12 ambiguity takes."""
        self.assertEqual(self.r._raw_route({"aggregation": 0.0, "temporal": 0.0,
                                            "preference": 0.0, "factual": 0.0}),
                         "aggregation")
        original = _stub_route(self.r, {"preference": 0.5, "factual": 0.5})
        try:
            self.r.get_context(QUERY, token_budget=12000)
            self.assertFalse(self.r.last_context_debug["precision"])
        finally:
            self.r.classify_route = original

    def test_the_gate_reads_scores_not_the_margin(self):
        """Merge contract: the guard must survive a change to HOW the margin is
        applied (per-kind margins are a sibling work item). `_raw_route` takes
        `scores` and nothing else — no config read, no engine state."""
        self.assertEqual(self.r._raw_route(MARGIN_DEFAULTED), "preference")
        core2, home2 = make_core({"retrieval": {"query_routing_margin": 0.0}})
        try:
            self.assertEqual(core2.retrieval._raw_route(MARGIN_DEFAULTED), "preference")
        finally:
            shutil.rmtree(home2, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
