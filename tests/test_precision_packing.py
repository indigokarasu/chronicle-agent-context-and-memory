"""
Chronicle — E12 precision packing: confidence-gated context budget
(§18.5, ladder-9 issue #8).

Measured basis: on single-evidence factual questions, a context that makes a
judged reader ABSTAIN at a 12k budget is answered correctly when cut to ~1k of
the SAME items' head. Abstention tracks context volume, not evidence quality —
so when the query routes factual AND retrieval has CONVERGED ON ONE SESSION
(the modal session of the top-5 raw candidates holds at least
context.precision_concentration of them, and the leading candidate is inside
it), get_context delivers that leading item, its immediate session neighbors,
and nothing else.

The gate is session concentration rather than the leader's score margin
because that is what measurement said separates the two populations: on the
six LongMemEval single-session-user questions this exists for, the leader's
margin is 0.02-0.16 — inside the range of the crowded multi-evidence questions
— while their top-5 piles into one session (0.6-1.0) and the crowded ones
spread (0.2-0.4).

Every test here is differential: it compares against the SAME store assembled
with the feature removed (`feature_off_context`, which stubs out the decision
exactly as a tree without E12 would behave) or with the config gate off, so a
pass means the feature caused the difference — not that the fixture happened to
look that way. Runs entirely under the offline hashing embedder, the mode the
recall/ctx_eval gate harnesses use.
"""
import inspect
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import Config
from engine.core import ChronicleCore
from engine.retrieval import _PRECISION_HEAD, _PRECISION_TIE_EPS, RetrievalEngine

# -- the dominant-hit fixture ------------------------------------------------
EVIDENCE = "Pat Testley works at Acme Fake Co as a veterinarian"
NEIGHBOR = "The clinic Pat works at is on Fake Street in Springfield"
NEIGHBOR2 = "Pat's shift there starts at seven in the morning"
DISTRACT = "Ash Fakeman works at the county animal shelter in Springfield as a volunteer"
DISTRACT2 = "The shelter on Ninth Avenue takes in about forty cats a month"
DIRECTIVE = "Always file the Acme Fake Co paperwork in folder number %d"
QUERY = "where does Pat Testley work as a veterinarian"
# Same fixture, same dominant candidate, a route that surveys rather than
# pinpoints — the (c) case.
AGG_QUERY = "how many times has Pat Testley been to the clinic as a veterinarian"
# Bulk, in the DOMINANT session: unrelated enough never to rank, long enough
# that the session's own window overflows the precision budget. Without it a
# "size within budget" assertion would pass on a fixture too small to test it.
BULK = ("On day %d the weather in Springfield was unremarkable and the errands "
        "were the usual ones: the hardware store for picture hooks, the market "
        "for onions and rice, then a long walk along the river path where the "
        "herons stand, and nothing else of any note happened at all that day.")


def make_core(cfg_overrides=None):
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    for k, v in (cfg_overrides or {}).items():
        cfg[k] = v
    core = ChronicleCore(home, cfg)
    core.initialize("s1", principal_id="assistant")
    return core, home


def seed_dominant(core):
    """One clearly-dominant evidence turn, its session neighbors, a distractor
    session that DOES reach the candidate pool, standing directives, and bulk."""
    core.capture.observe(EVIDENCE, "Noted.", session_id="s_evidence")
    core.capture.observe(NEIGHBOR, "Good to know.", session_id="s_evidence")
    core.capture.observe(NEIGHBOR2, "OK.", session_id="s_evidence")
    for i in range(12):
        core.capture.observe(BULK % i, "Sounds quiet.", session_id="s_evidence")
    core.capture.observe(DISTRACT, "Nice.", session_id="s_other")
    core.capture.observe(DISTRACT2, "Wow.", session_id="s_other")
    for i in range(4):
        core.capture.observe(DIRECTIVE % i, "Will do.", session_id="s_admin")
    core.process_pending()


SPREAD = ("Pat Testley works at Acme Fake Co %s and the veterinarian rota there "
          "is posted every Monday morning without fail")
SPREAD_TAILS = ("in the mornings", "on weekends", "as a veterinarian",
                "part time since April", "out of the downtown branch",
                "when the clinic is short handed", "on the late shift")


def seed_spread(core):
    """Seven near-identical claims in SEVEN sessions. A leader still exists —
    something has to sort first — but the head is one candidate per session, so
    retrieval converged on nothing. This is the ambiguous case the gate must
    refuse, and the shape the crowded ctx_eval questions actually have."""
    for i, tail in enumerate(SPREAD_TAILS):
        core.capture.observe(SPREAD % tail, "Noted.", session_id="s_%d" % i)
    core.process_pending()


def seed_short_pool(core):
    """Two sessions, two turns: a pool too short to measure concentration
    over."""
    core.capture.observe(EVIDENCE, "Noted.", session_id="s_a")
    core.capture.observe(NEIGHBOR, "Noted.", session_id="s_b")
    core.process_pending()


def seed_single_session(core):
    """The dominant fixture's evidence with NOTHING to converge away from:
    every candidate is in one session because the store has only one."""
    core.capture.observe(EVIDENCE, "Noted.", session_id="s_only")
    core.capture.observe(NEIGHBOR, "Good to know.", session_id="s_only")
    core.capture.observe(NEIGHBOR2, "OK.", session_id="s_only")
    for i in range(12):
        core.capture.observe(BULK % i, "Sounds quiet.", session_id="s_only")
    for i in range(4):
        core.capture.observe(DIRECTIVE % i, "Will do.", session_id="s_only")
    core.process_pending()


def feature_off_context(engine, *args, **kwargs):
    """The context a tree WITHOUT E12 would return for this call.

    `_precision_decision` is the feature's only entry point into get_context:
    with it stubbed to None the gate can never fire, `raw_probe` is discarded
    exactly like the pre-feature call it duplicates, and every later branch
    takes its pre-E12 arm. So this is the byte-for-byte reference the
    acceptance bar asks for, computed from the SAME store rather than from a
    second checkout that could differ for unrelated reasons.
    """
    original = engine._precision_decision
    engine._precision_decision = lambda *a, **k: None
    try:
        return engine.get_context(*args, **kwargs)
    finally:
        engine._precision_decision = original


class TestDominantHitPacksSmall(unittest.TestCase):
    """(a) A dominant hit yields a small context: the evidence, its session
    neighbors, nothing else, under the precision budget."""

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        self.r = self.core.retrieval
        self.ctx = self.r.get_context(QUERY, token_budget=12000)
        # Captured HERE: last_context_debug describes the most recent call, and
        # the reference assembly below is itself a get_context call.
        self.debug = dict(self.r.last_context_debug)
        self.full = feature_off_context(self.r, QUERY, token_budget=12000)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_the_gate_fired_at_all(self):
        """Everything below is only meaningful if this fixture triggered it."""
        self.assertTrue(self.debug["precision"])
        self.assertEqual(self.debug["route"], "factual")
        self.assertGreaterEqual(self.debug["precision_concentration"], 0.6)
        self.assertEqual(self.debug["precision_session"], "s_evidence")

    def test_evidence_is_present_and_leads(self):
        """§L8 evidence-forward is preserved, not merely 'included somewhere':
        the dominant item is the first thing after its session header."""
        self.assertIn(EVIDENCE, self.ctx)
        lines = [ln for ln in self.ctx.split("\n") if ln.strip()]
        self.assertTrue(lines[0].startswith("[SESSION s_evidence"), lines[:2])
        self.assertIn(EVIDENCE, lines[1])

    def test_session_neighbors_are_present_for_grounding(self):
        """The item alone is a floating quote; its session is what dates it and
        says what else was going on."""
        self.assertIn(NEIGHBOR, self.ctx)
        self.assertIn(NEIGHBOR2, self.ctx)

    def test_unrelated_session_is_absent(self):
        """The distractor is IN the candidate pool and IN the full-budget
        context — so its absence here is the session cut doing work, not a
        retrieval accident."""
        self.assertIn(DISTRACT, self.full, "fixture: distractor must reach the full context")
        self.assertNotIn(DISTRACT, self.ctx)
        self.assertNotIn(DISTRACT2, self.ctx)

    def test_noise_tail_is_absent(self):
        self.assertIn("[DIRECTIVE]", self.full, "fixture: directives must reach the full context")
        self.assertNotIn("[DIRECTIVE]", self.ctx)

    def test_ranked_belief_block_is_absent(self):
        """The Tier-1 block is unbudgeted, so it is exactly the volume the
        measurement indicts. It leads the full-budget context and must be gone
        from this one."""
        self.assertTrue(self.full.startswith(("[EPISODE]", "[FACT]", "[NOTE]")),
                        "fixture: the full context must lead with ranked beliefs")
        for tag in ("[EPISODE]", "[FACT] ", "[NOTE] "):
            self.assertNotIn(tag, self.ctx)

    def test_size_is_below_the_precision_budget(self):
        """A 12k-token ask comes back at the 1500-token budget. The full-budget
        assembly on this same store is materially larger, so this measures the
        cut rather than a fixture that was small anyway."""
        self.assertLessEqual(len(self.ctx), 1500 * 4 + len("\n… (truncated)"))
        self.assertGreater(len(self.full), 1500 * 4)
        self.assertLess(len(self.ctx), len(self.full))

    def test_a_tighter_caller_budget_still_wins(self):
        """Precision packing is a REDUCTION. A caller who asked for less than
        the precision budget keeps their own number."""
        tight = self.r.get_context(QUERY, token_budget=200)
        self.assertTrue(self.r.last_context_debug["precision"])
        self.assertEqual(self.r.last_context_debug["token_budget"], 200)
        self.assertLessEqual(len(tight), 200 * 4 + len("\n… (truncated)"))

    def test_precision_budget_is_configurable(self):
        core, home = make_core({"context": {"precision_budget": 400}})
        try:
            seed_dominant(core)
            ctx = core.retrieval.get_context(QUERY, token_budget=12000)
            self.assertTrue(core.retrieval.last_context_debug["precision"])
            self.assertLessEqual(len(ctx), 400 * 4 + len("\n… (truncated)"))
            self.assertIn(EVIDENCE, ctx)
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestNoConvergenceKeepsFullBudget(unittest.TestCase):
    """(b) A head spread across sessions -> full budget, byte-identical to a
    tree without the feature."""

    def setUp(self):
        self.core, self.home = make_core()
        seed_spread(self.core)
        self.r = self.core.retrieval

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_the_fixture_is_eligible_in_every_way_except_concentration(self):
        """Otherwise "it did not fire" would prove nothing: this asserts
        CONCENTRATION is the only thing standing between this fixture and a
        firing."""
        cands = self.r.retrieve_raw(QUERY, limit=20)
        self.assertGreaterEqual(len(cands), 5, "pool must be able to fill the head")
        self.assertEqual(self.r.classify_route(QUERY)["route"], "factual")
        self.assertIsNotNone(self.r.embedder)
        sids = {self.core.store.get_event(c["event_id"]).get("session_id") for c in cands[:5]}
        self.assertGreaterEqual(len(sids), 4, "fixture: the head must be spread")
        self.assertIsNone(self.r._precision_decision(cands))
        # ... and with the concentration test opened right up, the very same
        # call fires — so nothing else about this fixture is disqualifying.
        restore = self.r.cfg._d["context"]["precision_concentration"]
        self.r.cfg._d["context"]["precision_concentration"] = 0.2
        try:
            self.assertIsNotNone(self.r._precision_decision(cands))
        finally:
            self.r.cfg._d["context"]["precision_concentration"] = restore

    def test_output_is_byte_identical_to_the_feature_being_absent(self):
        for budget in (1500, 4000, 12000):
            with_feature = self.r.get_context(QUERY, token_budget=budget)
            without = feature_off_context(self.r, QUERY, token_budget=budget)
            self.assertEqual(with_feature, without, "budget=%d" % budget)
            self.assertFalse(self.r.last_context_debug["precision"])

    def test_full_budget_content_survives(self):
        """Not merely equal — equal AND still the full-budget shape (many
        sessions present), so a bug that emptied both sides would not pass."""
        ctx = self.r.get_context(QUERY, token_budget=12000)
        headers = {ln for ln in ctx.splitlines() if ln.startswith("[SESSION ")}
        self.assertGreaterEqual(len(headers), 4)


class TestPoolShapesThatCannotBeMeasured(unittest.TestCase):
    """Two degenerate pools where concentration is arithmetic rather than
    evidence, and the gate must refuse both."""

    def test_a_pool_too_short_to_fill_the_head_is_refused(self):
        core, home = make_core()
        try:
            seed_short_pool(core)
            r = core.retrieval
            cands = r.retrieve_raw(QUERY, limit=20)
            self.assertLess(len(cands), 5, "fixture: a short pool")
            self.assertIsNone(r._precision_decision(cands))
            ctx = r.get_context(QUERY, token_budget=12000)
            self.assertFalse(r.last_context_debug["precision"])
            self.assertEqual(ctx, feature_off_context(r, QUERY, token_budget=12000))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_single_session_store_has_nothing_to_converge_away_from(self):
        """Concentration 1.0 that measures the STORE, not the query: with one
        session in the pool there was never a choice to make."""
        core, home = make_core()
        try:
            seed_single_session(core)
            r = core.retrieval
            cands = r.retrieve_raw(QUERY, limit=20)
            self.assertGreaterEqual(len(cands), 5)
            sids = {core.store.get_event(c["event_id"]).get("session_id") for c in cands}
            self.assertEqual(sids, {"s_only"}, "fixture: one session in the pool")
            self.assertIsNone(r._precision_decision(cands))
            ctx = r.get_context(QUERY, token_budget=12000)
            self.assertFalse(r.last_context_debug["precision"])
            self.assertEqual(ctx, feature_off_context(r, QUERY, token_budget=12000))
            self.assertIn("[DIRECTIVE]", ctx)
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestNonFactualRouteUnaffected(unittest.TestCase):
    """(c) A non-factual route never precision-packs, however dominant its top
    candidate is: aggregation/temporal/preference questions are answered by
    surveying many items."""

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        self.r = self.core.retrieval
        self.agg_q = AGG_QUERY

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_route_is_non_factual_and_dominance_would_otherwise_fire(self):
        self.assertNotEqual(self.r.classify_route(self.agg_q)["route"], "factual")
        cands = self.r.retrieve_raw(self.agg_q, limit=20)
        self.assertIsNotNone(self.r._precision_decision(cands),
                             "fixture: this query's top candidate DOES dominate")

    def test_output_is_byte_identical_to_the_feature_being_absent(self):
        for budget in (1500, 12000):
            with_feature = self.r.get_context(self.agg_q, token_budget=budget)
            without = feature_off_context(self.r, self.agg_q, token_budget=budget)
            self.assertEqual(with_feature, without, "budget=%d" % budget)
            self.assertFalse(self.r.last_context_debug["precision"])
            self.assertNotEqual(self.r.last_context_debug["route"], "factual")


class TestNoEmbedderUnaffected(unittest.TestCase):
    """(d) No embedder -> no score signal -> no gate. Not a degraded gate: the
    cosine term that makes a raw score comparable is simply not there (I18)."""

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_same_store_fires_with_an_embedder_and_not_without(self):
        """Differential on ONE store: the embedder is the only difference."""
        cfg = Config({"embeddings": {"model": "hashing"}})
        with_emb = RetrievalEngine(self.core.store, cfg, embedder=self.core.embedder,
                                   active_principal="assistant")
        without = RetrievalEngine(self.core.store, cfg, embedder=None,
                                  active_principal="assistant")
        with_emb.get_context(QUERY, token_budget=12000)
        self.assertTrue(with_emb.last_context_debug["precision"])
        ctx = without.get_context(QUERY, token_budget=12000)
        self.assertFalse(without.last_context_debug["precision"])
        self.assertEqual(ctx, feature_off_context(without, QUERY, token_budget=12000))
        self.assertGreater(len(ctx), 1500 * 4, "no-embedder context keeps the full budget")

    def test_no_embedder_refuses_even_with_the_dominance_test_wide_open(self):
        """Isolates the embedder condition itself. At margin 0.0 ANY lead is
        dominance, and the FTS-only pool a vectorless engine returns does lead
        by a hair — so if the gate consulted those scores it would fire here.
        It must not: without a cosine term those numbers are rank crumbs, not a
        confidence signal."""
        cfg = Config({"embeddings": {"model": "hashing"},
                      "context": {"precision_margin": 0.0}})
        without = RetrievalEngine(self.core.store, cfg, embedder=None,
                                  active_principal="assistant")
        cands = without.retrieve_raw(QUERY, limit=20)
        self.assertGreaterEqual(len(cands), 2, "fixture: an FTS-only pool with a runner-up")
        self.assertIsNotNone(without._precision_decision(cands),
                             "fixture: at margin 0.0 that pool WOULD be called dominant")
        ctx = without.get_context(QUERY, token_budget=12000)
        self.assertFalse(without.last_context_debug["precision"])
        self.assertEqual(ctx, feature_off_context(without, QUERY, token_budget=12000))


class TestConfigGateOff(unittest.TestCase):
    """(e) context.precision_packing: false -> byte-identical everywhere,
    including on the fixture that otherwise fires hardest."""

    def test_dominant_fixture_is_untouched_when_the_flag_is_off(self):
        core, home = make_core({"context": {"precision_packing": False}})
        try:
            seed_dominant(core)
            r = core.retrieval
            for budget in (1500, 4000, 12000):
                off = r.get_context(QUERY, token_budget=budget)
                self.assertEqual(off, feature_off_context(r, QUERY, token_budget=budget),
                                 "budget=%d" % budget)
                self.assertFalse(r.last_context_debug["precision"])
            # Discriminating: the same fixture with the flag ON does fire, so
            # the equality above is the flag's doing.
            on_core, on_home = make_core()
            try:
                seed_dominant(on_core)
                on_core.retrieval.get_context(QUERY, token_budget=12000)
                self.assertTrue(on_core.retrieval.last_context_debug["precision"])
            finally:
                shutil.rmtree(on_home, ignore_errors=True)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_flag_off_keeps_the_noise_tail_and_the_other_sessions(self):
        core, home = make_core({"context": {"precision_packing": False}})
        try:
            seed_dominant(core)
            ctx = core.retrieval.get_context(QUERY, token_budget=12000)
            self.assertIn("[DIRECTIVE]", ctx)
            self.assertIn(DISTRACT, ctx)
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestGateDials(unittest.TestCase):
    """Both thresholds are config dials read at call time, not hardcodes."""

    def test_a_low_concentration_threshold_fires_on_the_spread_fixture(self):
        core, home = make_core({"context": {"precision_concentration": 0.2}})
        try:
            seed_spread(core)
            core.retrieval.get_context(QUERY, token_budget=12000)
            self.assertTrue(core.retrieval.last_context_debug["precision"])
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_demanding_unanimity_refuses_the_dominant_fixture(self):
        """conc 1.0 = "every one of the top five, or nothing". The dominant
        fixture's head is 4/5, so it must stop firing — the threshold is doing
        the work, not the fixture."""
        core, home = make_core({"context": {"precision_concentration": 1.0}})
        try:
            seed_dominant(core)
            ctx = core.retrieval.get_context(QUERY, token_budget=12000)
            self.assertFalse(core.retrieval.last_context_debug["precision"])
            self.assertEqual(ctx, feature_off_context(core.retrieval, QUERY, token_budget=12000))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_the_secondary_margin_dial_can_veto_a_converged_head(self):
        """context.precision_margin defaults to 0.0 (no extra requirement) but
        is live: raised above the leader's actual lead it refuses a head that
        concentration alone accepted."""
        core, home = make_core()
        try:
            seed_dominant(core)
            r = core.retrieval
            r.get_context(QUERY, token_budget=12000)
            self.assertTrue(r.last_context_debug["precision"])
            lead = r.last_context_debug["precision_margin"]
            r.cfg._d["context"]["precision_margin"] = min(1.0, lead + 0.05)
            ctx = r.get_context(QUERY, token_budget=12000)
            self.assertFalse(r.last_context_debug["precision"])
            self.assertEqual(ctx, feature_off_context(r, QUERY, token_budget=12000))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_unparseable_thresholds_fall_back_to_the_defaults(self):
        core, home = make_core({"context": {"precision_concentration": "not a number",
                                            "precision_margin": None}})
        try:
            self.assertEqual(core.retrieval._precision_concentration(), 0.60)
            self.assertEqual(core.retrieval._precision_margin(), 0.0)
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestConvergenceGateIsConservative(unittest.TestCase):
    """_precision_decision refuses every ambiguous shape (unit-level, so each
    refusal is pinned to its own reason rather than to a fixture accident)."""

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        self.r = self.core.retrieval
        self.cands = self.r.retrieve_raw(QUERY, limit=20)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _sid(self, cand):
        return (self.core.store.get_event(cand["event_id"]) or {}).get("session_id")

    def test_baseline_this_head_did_converge(self):
        d = self.r._precision_decision(self.cands)
        self.assertIsNotNone(d)
        self.assertEqual(d["sid"], "s_evidence")
        self.assertGreaterEqual(d["concentration"], 0.6)

    def test_a_pool_that_cannot_fill_the_head_is_refused(self):
        self.assertIsNone(self.r._precision_decision(self.cands[:4]))
        self.assertIsNone(self.r._precision_decision([]))

    def test_a_leader_outside_the_modal_session_is_refused(self):
        """The crowd says one session, the best hit says another: two claims on
        the answer, which is exactly the ambiguity the gate exists to catch.

        Same candidates; the foreign one is promoted to a genuine lead (top of
        the list AND top score), so nothing else about this pool disqualifies
        it — concentration still clears, and the margin is positive."""
        foreign = next(c for c in self.cands if self._sid(c) != "s_evidence")
        rows = [dict(foreign)] + [dict(c) for c in self.cands if c is not foreign]
        rows[0]["score"] = rows[1]["score"] * 1.5
        self.assertEqual(self._sid(rows[0]), "s_other")
        self.assertGreaterEqual(sum(1 for c in rows[:5] if self._sid(c) == "s_evidence"), 3)
        self.assertGreater(rows[0]["score"], rows[1]["score"])   # a real leader
        self.assertIsNone(self.r._precision_decision(rows))

    def test_a_session_summary_leader_is_refused(self):
        """`retrieve_raw` also returns `session:<id>` summary rows: a POINTER to
        a body of evidence, not a turn to lead a context with."""
        rows = [dict(c) for c in self.cands]
        rows[0]["event_id"] = "session:s_evidence"
        self.assertIsNone(self.r._precision_decision(rows))

    def test_a_projection_leader_is_refused(self):
        """Same for a `proj:<provider>:<id>` federated projection pointer."""
        rows = [dict(c) for c in self.cands]
        rows[0]["event_id"] = "proj:acme:42"
        self.assertIsNone(self.r._precision_decision(rows))

    def test_an_empty_excerpt_leader_is_refused(self):
        rows = [dict(c) for c in self.cands]
        rows[0]["excerpt"] = "   "
        self.assertIsNone(self.r._precision_decision(rows))

    def test_a_zero_scored_leader_is_refused(self):
        """A pool that scored nothing has no leader to believe.

        F1 changed how this shape is REACHED, not whether it is refused. The
        gate now re-sorts the pool itself (`_precision_order`), so "the leader"
        is by construction the highest-scoring row rather than whichever row
        the caller listed first — zeroing one row now demotes it instead of
        producing a zero-scored leader. The guard therefore fires on the pool
        this shape actually describes: one where nothing scored at all."""
        rows = [dict(c) for c in self.cands]
        for r in rows:
            r["score"] = 0.0
        self.assertIsNone(self.r._precision_decision(rows))

    def test_demoting_one_row_to_zero_is_not_a_zero_scored_leader(self):
        """The other half of the same statement: a single zeroed row is a
        demoted row, and the gate goes on reading the pool's real best hit.
        Pinned so the rewrite above cannot be read as "the guard got weaker"."""
        rows = [dict(c) for c in self.cands]
        rows[0]["score"] = 0.0
        d = self.r._precision_decision(rows)
        self.assertIsNotNone(d)
        self.assertNotEqual(d["event_id"], rows[0]["event_id"])

    def test_a_leader_the_store_cannot_resolve_is_refused(self):
        """No event row -> no session -> it cannot be the modal one."""
        rows = [dict(c) for c in self.cands]
        rows[0]["event_id"] = "ev_" + "0" * 64
        self.assertIsNone(self.r._precision_decision(rows))

    def test_concentration_is_measured_over_the_head_not_the_whole_pool(self):
        """A long tail from other sessions cannot dilute a converged head — and
        a converged TAIL cannot rescue a spread head. Pinned because measuring
        over the whole (limit=20) pool would do both.

        6 of 7 rather than the pre-F1 4 of 5: this fixture's ranks 5-7 are three
        bulk turns of the evidence session whose scores agree to better than a
        thousandth, so the tie-aware boundary counts all three (§F1). Still a
        HEAD measurement — the pool is twenty."""
        rows = [dict(c) for c in self.cands]
        d = self.r._precision_decision(rows)
        self.assertIsNotNone(d)
        self.assertAlmostEqual(d["concentration"], 6 / 7.0)
        self.assertLess(len(self.r._precision_head(self.r._precision_order(rows))),
                        len(rows))


class TestPackedSessionOrderInterleavesDistanceAndRank(unittest.TestCase):
    """Inside the packed session the order is LEADER, then an interleave of
    nearest-turn and best-ranked — neither alone, and never the session's own
    running order.

    Measured on the motivating set, both halves: the evidence for "Where do I
    take yoga classes?" was one turn away but fifth by score (rank order spent
    the whole budget above it), while the evidence for the animal-shelter
    question ranked first but sat three long turns away (distance order spent
    the whole budget on the turns in between). Alternating delivers both, and
    is what makes packing robust to which of two near-tied candidates happened
    to lead.

    The session is laid out so all three orderings disagree about slot one:
    running order would open with OPENER, distance with PRE (nearest, and the
    earlier of the two turns one step away), rank with RANKED_FAR.
    """

    OPENER = "Long before any of this the hedge needed cutting back again"
    PRE = "The porch light was left on again that whole evening"
    ADJACENT = "The kettle boiled over at noon and nobody noticed for a while"
    RANKED_FAR = ("Pat Testley the veterinarian at Acme Fake Co also covers the "
                  "Saturday clinic rota")
    # Two more ranked hits, far from the leader, so the modal session holds the
    # head without any of the NEAR turns having to score at all.
    RANKED_FAR2 = "Acme Fake Co asks Pat Testley the veterinarian to sign the rota"
    RANKED_FAR3 = "The veterinarian Pat Testley works Tuesdays at Acme Fake Co too"

    def setUp(self):
        # A budget that fits the leader and ONE more line, so which line gets
        # it is the whole measurement.
        self.core, self.home = make_core({"context": {"precision_budget": 60}})
        c = self.core.capture
        c.observe(self.OPENER, "Right.", session_id="s_evidence")       # seq-2
        c.observe(self.PRE, "Noted.", session_id="s_evidence")          # seq-1
        c.observe(EVIDENCE, "Noted.", session_id="s_evidence")          # leader
        c.observe(self.ADJACENT, "Oh dear.", session_id="s_evidence")   # seq+1
        c.observe(BULK % 1, "Quiet.", session_id="s_evidence")          # seq+2
        c.observe(self.RANKED_FAR, "Got it.", session_id="s_evidence")  # seq+3, high score
        c.observe(self.RANKED_FAR2, "Sure.", session_id="s_evidence")   # seq+4
        c.observe(self.RANKED_FAR3, "Right.", session_id="s_evidence")  # seq+5
        c.observe(DISTRACT, "Nice.", session_id="s_other")
        c.observe(DISTRACT2, "Wow.", session_id="s_other")
        self.core.process_pending()
        self.r = self.core.retrieval

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_fixture_ranks_the_far_turn_above_the_near_ones(self):
        """Without this, the packing assertions below prove nothing."""
        order = [(c.get("excerpt") or "") for c in self.r.retrieve_raw(QUERY, limit=20)]
        far = next(i for i, e in enumerate(order) if self.RANKED_FAR in e)
        near = [i for i, e in enumerate(order)
                if self.PRE in e or self.ADJACENT in e or self.OPENER in e]
        self.assertTrue(not near or far < near[0],
                        "fixture: the distant turn must outrank the near ones")

    def test_the_first_slot_goes_to_a_nearest_neighbour(self):
        """Distance takes slot one, so the turn the session happens to OPEN
        with is not delivered — which is what running order would have done."""
        ctx = self.r.get_context(QUERY, token_budget=12000)
        self.assertTrue(self.r.last_context_debug["precision"])
        self.assertIn(EVIDENCE, ctx)
        self.assertIn(self.PRE, ctx)
        self.assertNotIn(self.OPENER, ctx)
        self.assertNotIn(self.RANKED_FAR, ctx)
        self.assertLessEqual(len(ctx), 60 * 4 + len("\n… (truncated)"))

    def _best_ranked_neighbour(self):
        """The highest-scoring turn of the packed session that is not the
        leader — the rank stream's first pick, read off retrieval rather than
        hardcoded."""
        far = (self.RANKED_FAR, self.RANKED_FAR2, self.RANKED_FAR3)
        for c in self.r.retrieve_raw(QUERY, limit=20):
            for text in far:
                if text in (c.get("excerpt") or ""):
                    return text
        self.fail("fixture: no ranked far turn in the pool")

    def test_the_next_slot_goes_to_the_best_ranked_turn(self):
        """Slot two is the rank stream's, so the best-scoring turn — three or
        more turns away — lands ahead of a nearer one that scores nothing. A
        pure distance order would have put ADJACENT here; the session's own
        running order would have opened with OPENER."""
        best = self._best_ranked_neighbour()
        self.r.cfg._d["context"]["precision_budget"] = 400
        ctx = self.r.get_context(QUERY, token_budget=12000)
        self.assertTrue(self.r.last_context_debug["precision"])
        for text in (self.PRE, best, self.ADJACENT, self.OPENER):
            self.assertIn(text, ctx)
        self.assertLess(ctx.index(self.PRE), ctx.index(best))
        self.assertLess(ctx.index(best), ctx.index(self.ADJACENT))
        self.assertLess(ctx.index(self.ADJACENT), ctx.index(self.OPENER))

    def test_the_full_budget_path_still_orders_by_rank(self):
        """The interleave is precision-only: with the feature off, the same
        store still packs this session by relevance, then session order."""
        full = feature_off_context(self.r, QUERY, token_budget=12000)
        self.assertIn(self.RANKED_FAR, full)
        self.assertLess(full.index(self.RANKED_FAR), full.index(self.ADJACENT))


class TestTheFetchedWindowIsCentredOnTheEvidence(unittest.TestCase):
    """The session-window query itself is centred on the leading turn, not
    taken from the session's start.

    Ordering alone cannot fix this: `context.session_window_max_events` bounds
    what is FETCHED, so on a session longer than that bound a from-the-start
    read never sees the evidence's neighbours at all — it returns the opening
    of a conversation that may be hundreds of turns away from the answer.
    """

    EARLY = "Early housekeeping note number %d about the recycling schedule"
    LATE_NEIGHBOUR = "The clinic parking round the back fills up by nine"

    def setUp(self):
        self.core, self.home = make_core({"context": {"session_window_max_events": 6,
                                                      "precision_budget": 300}})
        c = self.core.capture
        for i in range(10):
            c.observe(self.EARLY % i, "Noted.", session_id="s_evidence")
        c.observe(EVIDENCE, "Noted.", session_id="s_evidence")            # the leader
        c.observe(self.LATE_NEIGHBOUR, "OK.", session_id="s_evidence")    # leader + 1
        c.observe("Pat Testley the veterinarian also does the Acme Fake Co rota",
                  "Sure.", session_id="s_evidence")
        c.observe("Acme Fake Co asks the veterinarian Pat Testley to sign it",
                  "Right.", session_id="s_evidence")
        c.observe("The veterinarian rota at Acme Fake Co lists Pat Testley for Fridays",
                  "Noted.", session_id="s_evidence")
        c.observe(DISTRACT, "Nice.", session_id="s_other")
        c.observe(DISTRACT2, "Wow.", session_id="s_other")
        self.core.process_pending()
        self.r = self.core.retrieval

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_fixture_session_is_longer_than_the_fetch_bound(self):
        evs = self.core.store.get_events_by_session("s_evidence", since_seq=0,
                                                    types=("observed",), limit=200)
        self.assertGreater(len(evs), 6, "fixture: the session must overflow the bound")

    def test_the_neighbour_is_delivered_and_the_session_opening_is_not(self):
        ctx = self.r.get_context(QUERY, token_budget=12000)
        self.assertTrue(self.r.last_context_debug["precision"])
        self.assertIn(EVIDENCE, ctx)
        self.assertIn(self.LATE_NEIGHBOUR, ctx)
        for i in range(6):
            self.assertNotIn(self.EARLY % i, ctx)


class TestDebugFieldDiscriminates(unittest.TestCase):
    """(f) The exposed decision distinguishes the cases an eval must attribute
    an answer to."""

    def tearDown(self):
        for home in getattr(self, "_homes", []):
            shutil.rmtree(home, ignore_errors=True)

    def _core(self, cfg=None):
        core, home = make_core(cfg)
        self._homes = getattr(self, "_homes", []) + [home]
        return core

    def test_flag_is_true_only_for_the_packed_case(self):
        packed = self._core()
        seed_dominant(packed)
        packed.retrieval.get_context(QUERY, token_budget=12000)
        self.assertEqual(packed.retrieval.last_context_debug["precision"], True)

        spread = self._core()
        seed_spread(spread)
        spread.retrieval.get_context(QUERY, token_budget=12000)
        self.assertEqual(spread.retrieval.last_context_debug["precision"], False)

    def test_route_and_budget_travel_with_the_flag(self):
        core = self._core()
        seed_dominant(core)
        core.retrieval.get_context(QUERY, token_budget=12000)
        d = core.retrieval.last_context_debug
        self.assertEqual(d["route"], "factual")
        self.assertEqual(d["token_budget"], 1500)        # what it actually packed
        self.assertIsNotNone(d["precision_event_id"])
        self.assertEqual(d["precision_session"], "s_evidence")

        core.retrieval.get_context(AGG_QUERY, token_budget=12000)
        d = core.retrieval.last_context_debug
        self.assertNotEqual(d["route"], "factual")
        self.assertFalse(d["precision"])
        self.assertEqual(d["token_budget"], 12000)       # full budget, as asked
        self.assertIsNone(d["precision_margin"])
        self.assertIsNone(d["precision_concentration"])

    def test_it_refreshes_per_call_and_never_goes_stale(self):
        core = self._core()
        seed_dominant(core)
        core.retrieval.get_context(QUERY, token_budget=12000)
        self.assertTrue(core.retrieval.last_context_debug["precision"])
        core.retrieval.get_context(AGG_QUERY, token_budget=12000)
        self.assertFalse(core.retrieval.last_context_debug["precision"])

    def test_it_is_defined_before_any_context_was_assembled(self):
        eng = RetrievalEngine(None, None, embedder=None)
        self.assertEqual(eng.last_context_debug, {})

    def test_the_tool_surface_carries_it(self):
        core = self._core()
        seed_dominant(core)
        out = json.loads(core.tools.dispatch("assistant", "get_context", {"hint": QUERY}))
        self.assertIn("context", out)
        self.assertIn("debug", out)
        self.assertIn("precision", out["debug"])
        self.assertEqual(out["debug"]["route"], "factual")


# ===========================================================================
# F1 — the gate's answer is a function of the evidence, not of arrival order
#
# Measured problem: E12 fired on 4 of its 6 motivating LongMemEval instances in
# one run and 5 in the next, with no code change between them.
#
# THE CAUSE WAS NOT FLOAT NOISE, though it looked exactly like it. Measured
# while chasing it: ollama/nomic returns bit-identical vectors for identical
# input, and two stores built from one instance inside a single process produce
# candidate pools that agree to the last float. What differed between runs was
# the QUERY: `query_understanding` joined a `set` into the text it embeds, and
# CPython randomises string hashing per process, so the same question was
# embedded as a different word order every time. See
# `TestTheEmbeddedQueryTextIsProcessStable`, which is the test for the actual
# defect, and note why the existing suite could never have caught it: every
# offline gate runs the hashing embedder, which is order-invariant.
#
# The other two guards below are about ties that are REAL — candidates whose
# scores genuinely agree — and they are what stops the gate answering a
# question the scores did not ask:
#   * `_precision_order` — the gate and its packing read the pool ordered by
#     tie bucket, then by event id, so equal-scoring candidates cannot be
#     ranked by the order `retrieve_raw` happened to fill its dict in.
#   * `_precision_head`  — the head boundary is drawn on the SAME buckets, so
#     every member of a tie at the cut is counted rather than whichever one
#     sorted fifth. (This suite's own dominant fixture has such a tie: its
#     ranks 5-7 are three bulk turns that agree to better than a thousandth,
#     and before F1 the head came out 5 long or 7 long from an identical pool.)
# ===========================================================================


class _pre_f1_gate:                                   # noqa: N801 — a helper, not a type
    """The pre-F1 gate, restored on exit: `retrieve_raw`'s raw score order and
    a hard `[:_PRECISION_HEAD]` boundary. Every F1 claim is stated against this
    reference, so a passing test means F1 caused the difference."""

    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        self.order = self.engine._precision_order
        self.head = self.engine._precision_head
        self.engine._precision_order = lambda c: sorted(
            c, key=lambda x: x["score"], reverse=True)
        self.engine._precision_head = lambda o: list(o[:_PRECISION_HEAD])
        return self

    def __exit__(self, *exc):
        self.engine._precision_order = self.order
        self.engine._precision_head = self.head
        return False


class _SyntheticPoolCase(unittest.TestCase):
    """The dominant fixture's real store plus hand-built candidate pools.

    The scores here are synthetic on purpose: the shapes under test are score
    RELATIONSHIPS a couple of parts in ten thousand wide, which no fixture can
    be relied on to produce by accident. Every row still points at a real
    observed event of a real session, so every store lookup the gate makes
    (session of a candidate, excerpt of the leader, seq of the leader) resolves
    exactly as it would in production.
    """

    E = "s_evidence"
    O = "s_other"          # noqa: E741 — reads as a session, not an ell

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        # The distractor session ships with two turns; these pools want up to
        # four DISTINCT ones, and a candidate row has to point at a real event
        # or the store lookups the gate makes cannot resolve it.
        for i in range(4):
            self.core.capture.observe(
                "The shelter rota for week %d is pinned by the back door" % i,
                "Noted.", session_id=self.O)
        self.core.process_pending()
        self.r = self.core.retrieval
        self._unused: dict = {}

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _turn(self, sid):
        """A distinct real observed turn of `sid`, as a candidate row."""
        if sid not in self._unused:
            self._unused[sid] = list(
                self.core.store.get_events_by_session(sid, types=("observed",)))
        ev = self._unused[sid].pop(0)
        p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else (ev["payload"] or {})
        return {"event_id": ev["event_id"], "excerpt": p.get("excerpt") or "", "score": 0.0}

    def _pool(self, spec):
        """[(session_id, score), ...] -> candidate rows, score order."""
        rows = []
        for sid, score in spec:
            row = self._turn(sid)
            row["score"] = score
            rows.append(row)
        return rows

    @staticmethod
    def _swap_scores(rows, i, j):
        """The same pool with two candidates' scores exchanged. Two candidates
        inside one tie bucket are, to the gate, the same score in either
        assignment — so the decision must not notice."""
        out = [dict(r) for r in rows]
        out[i]["score"], out[j]["score"] = out[j]["score"], out[i]["score"]
        return out

    def _pre_f1(self):
        """Context manager: the gate as it was BEFORE F1 — raw score order and
        a hard `[:_PRECISION_HEAD]` cut. (Plain functions, not staticmethods:
        an instance attribute is not run through the descriptor protocol, so
        `self._precision_order(rows)` calls these with `rows` alone.)"""
        return _pre_f1_gate(self.r)


class TestTieAwareHeadBoundary(_SyntheticPoolCase):
    """(a) Two candidates the scores cannot separate are both inside the head.

    A pair inside one `_PRECISION_TIE_EPS` bucket (1e-3 relative — two orders
    below the 0.02-0.16 margins the gate is meant to read) is a pair retrieval
    did not rank, and a boundary that has to pick one of them is picking by
    lottery. Extending the head over the bucket makes the modal share the same
    number whichever way the pair falls.
    """

    # Two scores in ONE tie bucket (0.6004 and 0.6001 against a pool best of
    # 1.0: 600.4 and 600.1 snap to bucket 600), i.e. tied by the only relation
    # the gate has — see `_precision_tie_buckets`. `OUT` is the nearest score
    # that is NOT tied with them.
    HI, LO, OUT = 0.6004, 0.6001, 0.5993

    def _straddle(self, boundary_sessions, above=(None, None, None, None)):
        """Ranks 1-4 from `above` (defaulting to the evidence session), then the
        tied pair at ranks 5 and 6, one per entry of `boundary_sessions`."""
        spec = [(s or self.E, sc) for s, sc in zip(above, (1.0, 0.9, 0.8, 0.7))]
        spec.append((boundary_sessions[0], self.HI))
        spec.append((boundary_sessions[1], self.LO))
        return self._pool(spec)

    def test_the_fixture_pair_really_is_tied_and_the_third_score_is_not(self):
        """Without this the tests below could pass on a pool that never
        straddled the boundary at all."""
        rows = [{"score": s, "event_id": "ev%d" % i}
                for i, s in enumerate((1.0, self.HI, self.LO, self.OUT))]
        b = self.r._precision_tie_buckets(rows)
        self.assertEqual(b[1], b[2], "HI and LO must share a bucket")
        self.assertNotEqual(b[2], b[3], "OUT must be in a lower bucket")
        self.assertLess((self.HI - self.LO) / self.HI, _PRECISION_TIE_EPS)
        self.assertGreater((self.LO - self.OUT) / self.LO, _PRECISION_TIE_EPS)

    def test_the_measured_share_does_not_move_when_the_pair_swaps(self):
        """Four evidence turns then a tied {evidence, other} pair: a hard cut
        measures 5/5 one way and 4/5 the other. Tie-aware it is 5/6 both ways —
        and every other field of the decision is identical too, because the
        leader and its two scores never moved."""
        rows = self._straddle((self.E, self.O))
        a = self.r._precision_decision(rows)
        b = self.r._precision_decision(self._swap_scores(rows, 4, 5))
        self.assertIsNotNone(a)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["concentration"], 5 / 6.0)
        # The lottery this replaced, and the shape of the replacement: the two
        # draws were 1.00 and 0.80, and the tie-closed measurement is 0.83 —
        # BETWEEN them. Extending the head is not "be more conservative", it is
        # "stop rolling a die"; pinned because the opposite is an easy thing to
        # assume from the refusal in the test below.
        with self._pre_f1():
            pre_a = self.r._precision_decision(rows)
            pre_b = self.r._precision_decision(self._swap_scores(rows, 4, 5))
        self.assertEqual({pre_a["concentration"], pre_b["concentration"]}, {1.0, 0.8})
        self.assertLess(pre_b["concentration"], a["concentration"])
        self.assertLess(a["concentration"], pre_a["concentration"])

    def test_the_gate_outcome_cannot_flip_when_the_pair_swaps(self):
        """The harder half: a head split 2/2 above the boundary, so which of the
        tied pair is counted decides WHO THE MODAL SESSION IS — fire one way,
        refuse the other. Tie-aware, both are counted, the share is 3/6 = 0.5,
        and the gate refuses in both orders — the correct resolution of a head
        that is genuinely 50/50 about where the answer lives. (Refusal is not
        the extension's general direction; see
        `test_the_measured_share_does_not_move_when_the_pair_swaps`, where it
        settles above one of the two lottery outcomes and below the other.)"""
        rows = self._straddle((self.E, self.O), above=(self.E, self.E, self.O, self.O))
        a = self.r._precision_decision(rows)
        b = self.r._precision_decision(self._swap_scores(rows, 4, 5))
        self.assertIsNone(a)
        self.assertIsNone(b)

    def test_without_the_extension_that_same_pool_flips(self):
        """The differential proof that the fixture above straddles the boundary
        at all: run the SAME pool through the pre-F1 gate and it fires on one
        ordering and refuses on the other."""
        rows = self._straddle((self.E, self.O), above=(self.E, self.E, self.O, self.O))
        with self._pre_f1():
            a = self.r._precision_decision(rows)
            b = self.r._precision_decision(self._swap_scores(rows, 4, 5))
        self.assertIsNotNone(a)
        self.assertIsNone(b)

    def test_a_candidate_outside_the_epsilon_stays_outside_the_head(self):
        """The extension is a tie rule, not a wider head. A rank 6 that is
        genuinely below the head (0.5 against 0.6 — 17% down, 200x the epsilon)
        is not counted, and the share stays a five-candidate measurement."""
        rows = self._pool([(self.E, 1.0), (self.E, 0.9), (self.E, 0.8),
                           (self.E, 0.7), (self.E, 0.6), (self.O, 0.5)])
        d = self.r._precision_decision(rows)
        self.assertIsNotNone(d)
        self.assertEqual(d["concentration"], 1.0)

    def test_the_extension_stops_at_the_first_untied_candidate(self):
        """The head grows over the boundary tie and no further. Asserted on
        `_precision_head` directly, which is the level the property lives at:
        it is a pure function of an already-ordered list.

        Bucket equality cannot chain — a ladder of small steps each inside the
        epsilon of the last would walk a raw-epsilon rule all the way down a
        twenty-candidate pool, and then the "share of the head" would be a
        measurement of the tail."""
        scores = (1.0, 0.9, 0.8, 0.7, self.HI, self.LO, self.OUT)
        head = self.r._precision_head([{"score": s, "event_id": "ev%d" % i}
                                       for i, s in enumerate(scores)])
        self.assertEqual([c["score"] for c in head], list(scores[:6]))

    def test_the_head_never_extends_past_the_pool(self):
        """A pool that is exactly the head, every score identical: the run of
        ties has nothing left to walk into."""
        head = self.r._precision_head([{"score": 0.5, "event_id": "ev%d" % i}
                                       for i in range(_PRECISION_HEAD)])
        self.assertEqual(len(head), _PRECISION_HEAD)

    def test_a_pool_too_short_to_fill_the_head_is_still_refused(self):
        """The extension may only ever ADD to a full head; it cannot rescue one
        that never filled."""
        rows = self._pool([(self.E, 1.0), (self.E, 0.9997), (self.E, 0.9995),
                           (self.O, 0.9993)])
        self.assertIsNone(self.r._precision_decision(rows))


class TestOrderingIsStableUnderJitter(_SyntheticPoolCase):
    """The pool order the gate reads is a function of the scores' MAGNITUDES
    and the candidates' ids, never of the order the pool arrived in.

    Python's sort is stable, so before F1 a pair of equal scores kept whatever
    order `retrieve_raw`'s dict iteration produced — which is insertion order of
    a dict filled by an FTS pass and a heap drain, i.e. an implementation
    detail that a re-embedded store reshuffles.
    """

    def _tied_leaders(self):
        """Two exactly-equal top scores in DIFFERENT sessions, over three more
        evidence turns. Which one leads decides the gate outright: the leader
        must agree with the modal session, and only one of them does."""
        return self._pool([(self.E, 1.0), (self.O, 1.0), (self.E, 0.5),
                           (self.E, 0.4), (self.E, 0.3), (self.O, 0.2)])

    def test_an_equal_scored_pair_decides_the_same_way_in_either_arrival_order(self):
        rows = self._tied_leaders()
        swapped = [rows[1], rows[0]] + [dict(r) for r in rows[2:]]
        self.assertEqual(self.r._precision_decision(rows),
                         self.r._precision_decision(swapped))

    def test_without_the_id_tiebreak_that_same_pair_flips(self):
        """Differential: pre-F1 the arrival order WAS the answer."""
        rows = self._tied_leaders()
        swapped = [rows[1], rows[0]] + [dict(r) for r in rows[2:]]
        with self._pre_f1():
            a = self.r._precision_decision(rows)
            b = self.r._precision_decision(swapped)
        self.assertIsNotNone(a)
        self.assertIsNone(b)

    def test_the_order_is_still_by_score_when_scores_differ(self):
        """The quantization is a tie rule, not a flattening: candidates a
        bucket or more apart keep their score order whatever their ids are."""
        rows = self._pool([(self.E, 0.2), (self.O, 0.9), (self.E, 0.5)])
        got = [r["score"] for r in self.r._precision_order(rows)]
        self.assertEqual(got, [0.9, 0.5, 0.2])

    def test_an_all_zero_pool_still_orders_deterministically(self):
        """No positive score means no relative grid to quantize against. The
        gate refuses such a pool anyway, but the ordering must not depend on
        arrival order on the way to refusing it."""
        rows = self._pool([(self.E, 0.0), (self.O, 0.0), (self.E, 0.0)])
        forward = [r["event_id"] for r in self.r._precision_order(rows)]
        backward = [r["event_id"] for r in self.r._precision_order(list(reversed(rows)))]
        self.assertEqual(forward, backward)
        self.assertIsNone(self.r._precision_decision(rows))

    def test_a_tied_runner_up_never_reports_a_negative_margin(self):
        """Inside one bucket the id decides the order, so the runner-up's RAW
        score can sit a hair above the leader's. Reported unfloored that is a
        negative lead — and `context.precision_margin` defaults to 0.0, so
        `margin < threshold` would refuse the query on the strength of a
        rounding difference."""
        rows = self._pool([(self.E, 1.0), (self.E, 1.0000004), (self.E, 0.5),
                           (self.E, 0.4), (self.E, 0.3), (self.O, 0.2)])
        d = self.r._precision_decision(rows)
        self.assertIsNotNone(d)
        self.assertGreaterEqual(d["margin"], 0.0)


class TestJitterChangesNoByteOfThePackedContext(unittest.TestCase):
    """(b) ±1e-5 relative noise on every candidate score leaves the decision and
    the packed context byte-for-byte identical.

    No such noise was found in this pipeline (see the section header), so this
    is a guard against a future where there is some — a different embedding
    backend, a GPU kernel that reorders a reduction, a float32 store. What it
    pins is that the gate's answer is stable to perturbations far smaller than
    any separation it claims to measure.

    The pool is synthetic for the reason `_SyntheticPoolCase` gives, and it
    carries a tie in the two places that matter: at the LEADER (which item the
    context opens with, and which turn the session window is centred on) and at
    the HEAD BOUNDARY (the modal share). `test_..._pre_f1_...` below is the
    proof that this pool is not vacuous: the same perturbation through the
    pre-F1 gate does move the output.
    """

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        self.r = self.core.retrieval
        evidence = self.core.store.get_events_by_session("s_evidence", types=("observed",))
        other = self.core.store.get_events_by_session("s_other", types=("observed",))

        def row(ev, score):
            p = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else (ev["payload"] or {})
            return {"event_id": ev["event_id"], "excerpt": p.get("excerpt") or "",
                    "score": score}

        #                    leader pair (4e-7 apart)      head boundary (3.3e-4 apart)
        scores = (1.0, 0.9999996, 0.8, 0.7, 0.6003)
        self.pool = [row(ev, s) for ev, s in zip(evidence, scores)]
        self.pool.append(row(other[0], 0.6001))
        self.pool.append(row(other[1], 0.30))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _jitter(self, seed):
        """Every score multiplied by 1 ± up to 1e-5, then re-sorted the way
        `retrieve_raw` would have returned it."""
        rnd = random.Random(seed)
        out = [dict(r) for r in self.pool]
        for r in out:
            r["score"] *= 1.0 + rnd.uniform(-1e-5, 1e-5)
        out.sort(key=lambda r: r["score"], reverse=True)
        return out

    def _assemble(self, rows):
        """get_context over exactly `rows`, whatever retrieval would have
        found. Returns (context, decision debug)."""
        original = self.r.retrieve_raw
        self.r.retrieve_raw = lambda *a, **k: [dict(r) for r in rows]
        try:
            ctx = self.r.get_context(QUERY, token_budget=12000)
        finally:
            self.r.retrieve_raw = original
        return ctx, dict(self.r.last_context_debug)

    def test_the_unjittered_pool_fires(self):
        """Everything below is a comparison against this."""
        _, debug = self._assemble(self.pool)
        self.assertTrue(debug["precision"])

    def test_the_decision_and_the_context_survive_every_jittered_draw(self):
        base_ctx, base = self._assemble(self.pool)
        self.assertTrue(base["precision"])
        for seed in range(12):
            with self.subTest(seed=seed):
                ctx, debug = self._assemble(self._jitter(seed))
                self.assertEqual(ctx, base_ctx)           # byte-identical
                self.assertTrue(debug["precision"])
                self.assertEqual(debug["precision_session"], base["precision_session"])
                self.assertEqual(debug["precision_event_id"], base["precision_event_id"])
                self.assertEqual(debug["precision_concentration"],
                                 base["precision_concentration"])
                # The margin is a MEASUREMENT of the winning lead, not a
                # decision — it is reported, and it moves with the scores it is
                # computed from. What must not move is which side of the
                # threshold it lands on, which the equality of the contexts
                # above already establishes.
                self.assertAlmostEqual(debug["precision_margin"],
                                       base["precision_margin"], places=4)

    def test_the_same_jitter_through_the_pre_f1_gate_does_move_the_output(self):
        """Non-vacuity. Pre-F1 — raw score order, hard head cut — at least one
        of these draws packs a different context, because the leader pair and
        the boundary pair both change places under the noise."""
        with _pre_f1_gate(self.r):
            base_ctx, _ = self._assemble(self.pool)
            drifted = [self._assemble(self._jitter(seed))[0] for seed in range(12)]
        self.assertTrue(any(ctx != base_ctx for ctx in drifted),
                        "fixture is vacuous: the pre-F1 gate was stable on it too")


class TestSessionWindowDedupesByEventId(unittest.TestCase):
    """F1 review nit: the leader is excluded from its own session window by
    IDENTITY, not by exact excerpt-string equality.

    The excerpt set is the text the caller PACKED, which is not always the text
    the store holds — the temporal route prefixes a date onto it, a budget
    boundary truncates it, a future caller may decorate it some other way. Any
    of those makes the leading turn read as a new neighbour and get re-printed
    directly beneath itself, and it also breaks the interleave's first-slot
    argument (the leader would head both streams and waste the first pair).
    """

    def setUp(self):
        self.core, self.home = make_core()
        seed_dominant(self.core)
        self.r = self.core.retrieval
        self.turns = self.core.store.get_events_by_session("s_evidence", types=("observed",))
        self.first = self.turns[0]

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def _expand(self, excerpts=None, ids=None):
        got = self.r._expand_session_window("s_evidence", "assistant",
                                            set() if excerpts is None else set(excerpts),
                                            limit=60, existing_event_ids=ids)
        return [e["event_id"] for e in got]

    def test_an_id_the_caller_already_packed_is_not_returned(self):
        self.assertIn(self.first["event_id"], self._expand())          # baseline
        self.assertNotIn(self.first["event_id"],
                         self._expand(ids={self.first["event_id"]}))

    def test_the_excerpt_set_alone_would_have_missed_a_decorated_leader(self):
        """The concrete failure: the caller holds `[date] text`, the store holds
        `text`, and string equality says they are different turns."""
        p = json.loads(self.first["payload"])
        decorated = "[2023-04-10 09:00] " + p["excerpt"]
        self.assertIn(self.first["event_id"], self._expand(excerpts=[decorated]))
        self.assertNotIn(self.first["event_id"],
                         self._expand(excerpts=[decorated], ids={self.first["event_id"]}))

    def test_it_records_what_it_expanded_so_a_later_call_cannot_repeat_it(self):
        """The set is carried across get_context's per-session loop, so it has
        to be written to as well as read."""
        ids: set = set()
        first_call = self.r._expand_session_window("s_evidence", "assistant", set(),
                                                   limit=60, existing_event_ids=ids)
        self.assertTrue(first_call)
        second = self.r._expand_session_window("s_evidence", "assistant", set(),
                                               limit=60, existing_event_ids=ids)
        self.assertEqual(second, [])

    def test_precision_packing_hands_the_leader_id_down(self):
        seen = {}
        original = self.r._expand_session_window

        def spy(sid, principal, excerpts, **kw):
            seen.setdefault("ids", kw.get("existing_event_ids"))
            return original(sid, principal, excerpts, **kw)

        self.r._expand_session_window = spy
        try:
            ctx = self.r.get_context(QUERY, token_budget=12000)
        finally:
            self.r._expand_session_window = original
        self.assertTrue(self.r.last_context_debug["precision"])
        self.assertIsNotNone(seen["ids"])
        self.assertIn(self.r.last_context_debug["precision_event_id"], seen["ids"])
        self.assertEqual(ctx.count(EVIDENCE), 1)

    def test_the_full_budget_path_is_deliberately_left_alone(self):
        """Scoped to the precision path on purpose. `retrieve_raw` can hand
        phase 1 an FTS row whose excerpt is not the payload's, so id-dedupe
        there would drop turns excerpt-dedupe keeps — and that path's
        acceptance bar is byte-identity with a tree that has no E12 at all."""
        seen = {}
        original = self.r._expand_session_window

        def spy(sid, principal, excerpts, **kw):
            seen.setdefault("ids", kw.get("existing_event_ids"))
            return original(sid, principal, excerpts, **kw)

        self.r._expand_session_window = spy
        try:
            self.r.get_context(AGG_QUERY, token_budget=12000)
        finally:
            self.r._expand_session_window = original
        self.assertFalse(self.r.last_context_debug["precision"])
        self.assertIsNone(seen["ids"])


QUERY_TEXT_SCRIPT = """
import sys
sys.path.insert(0, %r)
from engine.retrieval import RetrievalEngine


class FakeStore:
    def predicate_synonyms(self, canonical):
        # Returned in an order the caller must not depend on.
        return {"discount": ["rebate", "markdown"], "plan": ["tier"]}.get(canonical, [])


e = RetrievalEngine(FakeStore(), None, embedder=None)
q = e.query_understanding("what discount did the vendor give me on the annual plan")
print(" ".join(q["expanded"]))
"""


class TestTheEmbeddedQueryTextIsProcessStable(unittest.TestCase):
    """F1 root cause: the text handed to the embedder must not depend on
    PYTHONHASHSEED.

    `query_understanding` composes the embedded text by joining the query's
    tokens and their predicate synonyms. That collection used to be a `set`,
    and CPython randomises string hashing per process, so the SAME question was
    embedded as a different permutation of the same words in every process. A
    semantic embedder is word-order sensitive, so the query vector — and with
    it the whole candidate pool, its top five, and the E12 gate's answer —
    changed from one run to the next on the same store.

    This is the defect the F1 stability check actually measures, and it lives
    here rather than in a retrieval test file because it is the E12 firing
    shuffle: measured with real nomic, the six motivating LongMemEval instances
    moved their leading raw score by up to 6.5% relative between processes,
    while ollama returned bit-identical vectors for identical input and two
    stores built inside one process produced identical pools to the last float.

    Every offline gate runs the hashing embedder, which is a bag of hashed
    tokens and so cannot see word order at all — which is exactly why nothing
    in the existing suite caught this and why a cross-process test is the only
    kind that can.
    """

    SEEDS = ("0", "1", "42", "1234", "99999")

    def _text_under(self, seed):
        import subprocess
        env = dict(os.environ, PYTHONHASHSEED=seed)
        env.pop("CHRONICLE_EMBED_MODEL", None)
        script = QUERY_TEXT_SCRIPT % str(Path(__file__).parent.parent)
        proc = subprocess.run([sys.executable, "-c", script], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[-2000:])
        return proc.stdout.decode().strip()

    def test_five_hash_seeds_compose_the_same_query_text(self):
        texts = {self._text_under(s) for s in self.SEEDS}
        self.assertEqual(len(texts), 1,
                         "the embedded query text depends on PYTHONHASHSEED: %r" % texts)

    def test_it_is_the_question_in_its_own_word_order_then_the_synonyms(self):
        """Not merely stable — stable at the right value. Alphabetising would
        also be deterministic, and would hand a word-order-sensitive model a
        sentence nobody asked."""
        text = self._text_under("0")
        # `query_tokens` has already dropped the stopwords; what is left is the
        # question's content words IN THE ORDER THEY WERE ASKED.
        self.assertTrue(text.startswith("discount vendor give annual plan"), text)
        # Synonyms follow the question's own words, deduped, in a fixed order.
        self.assertTrue(text.endswith("markdown rebate tier"), text)


class TestPrecisionDecisionSignature(unittest.TestCase):
    """F1 review nit: `_precision_decision` no longer advertises a `principal`
    it never used.

    Every candidate in the pool was cleared for the calling principal by
    `retrieve_raw` before it was returned — that is why the decision needs no
    ACL re-check, and it is also why the parameter was dead. A parameter only a
    comment reads is a claim the signature makes that the code does not keep;
    the claim now lives where it is true, in the docstring.
    """

    def test_it_takes_the_candidates_and_nothing_else(self):
        params = list(inspect.signature(RetrievalEngine._precision_decision).parameters)
        self.assertEqual(params, ["self", "candidates"])

    def test_the_acl_argument_is_still_written_down(self):
        self.assertIn("cleared every candidate in this pool",
                      RetrievalEngine._precision_decision.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
