"""
Chronicle — E9 query routing via prototype centroids (§18.2, ladder-9 issue #8).

Covers the acceptance bar verbatim: "how many..." routes aggregation,
"when did..." routes temporal, "recommend..." routes preference (each
asserted via the debug field), and the factual path is byte-identical to
today whether or not routing is enabled. Runs entirely under the offline
hashing embedder (deterministic, no network) — the same mode the recall/
ctx_eval gate harnesses use.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from engine.embeddings import HashingEmbedder
from engine.retrieval import RetrievalEngine


def make_core(cfg_overrides=None):
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return ChronicleCore(home, cfg), home


class TestClassifyRoute(unittest.TestCase):
    """Nearest-centroid classification itself, in isolation."""

    def setUp(self):
        self.core, self.home = make_core()
        self.r = self.core.retrieval

    def test_aggregation_route(self):
        for q in ("how many times did I go kayaking",
                  "how many kayaking trips did I take"):
            info = self.r.classify_route(q)
            self.assertEqual(info["route"], "aggregation", q)
            self.assertTrue(info["enabled"])

    def test_temporal_route(self):
        for q in ("when did I go kayaking",
                  "when was my last trip to Sacramento"):
            info = self.r.classify_route(q)
            self.assertEqual(info["route"], "temporal", q)

    def test_preference_route(self):
        for q in ("recommend a restaurant for dinner",
                  "what do I prefer for breakfast"):
            info = self.r.classify_route(q)
            self.assertEqual(info["route"], "preference", q)

    def test_factual_route(self):
        for q in ("who is Pat Testley",
                  "where does Pat Testley work"):
            info = self.r.classify_route(q)
            self.assertEqual(info["route"], "factual", q)

    def test_debug_field_scores_present(self):
        info = self.r.classify_route("how many times did this happen")
        self.assertIn("scores", info)
        self.assertIn("aggregation", info["scores"])
        self.assertEqual(
            info["route"],
            max(info["scores"], key=lambda k: info["scores"][k]))

    def test_route_exposed_in_answer_debug_field(self):
        self.core.capture.observe("Pat Testley works at Acme Fake Co", "ok", session_id="s1")
        self.core.process_pending()
        ans = self.r.answer("how many times did I go kayaking")
        self.assertIn("debug", ans)
        self.assertEqual(ans["debug"]["route"], "aggregation")


class TestRoutingDisabledOrDegraded(unittest.TestCase):
    """Config-gated (retrieval.query_routing, default on) and must degrade to
    the factual/default route whenever there is no embedder — never an error."""

    def test_disabled_by_config_is_factual(self):
        core, home = make_core({"retrieval": {"query_routing": False}})
        info = core.retrieval.classify_route("how many times did this happen")
        self.assertEqual(info["route"], "factual")
        self.assertFalse(info["enabled"])

    def test_no_embedder_is_factual(self):
        eng = RetrievalEngine(None, None, embedder=None)
        info = eng.classify_route("how many times did this happen")
        self.assertEqual(info["route"], "factual")

    def test_embed_failure_is_factual_not_an_error(self):
        class BoomEmbedder:
            model = "boom"
            dimensions = 8

            def embed(self, text):
                raise RuntimeError("embedder is down")

        core, home = make_core()
        eng = RetrievalEngine(core.store, core.cfg, embedder=BoomEmbedder())
        info = eng.classify_route("how many times did this happen")
        self.assertEqual(info["route"], "factual")


class TestFactualPathByteIdentical(unittest.TestCase):
    """The acceptance bar: for a factual-classified hint, get_context's output
    with routing ON must be byte-identical to routing OFF (i.e. today)."""

    def test_get_context_byte_identical_on_vs_off(self):
        hint = "where does Pat Testley work"
        core_on, home_on = make_core({"retrieval": {"query_routing": True}})
        core_off, home_off = make_core({"retrieval": {"query_routing": False}})
        for core in (core_on, core_off):
            core.capture.observe("Pat Testley works at Acme Fake Co as a veterinarian",
                                  "ok", session_id="s1")
            core.capture.observe("I prefer window seats when flying", "ok", session_id="s1")
            core.process_pending()
        self.assertEqual(core_on.retrieval.classify_route(hint)["route"], "factual")
        ctx_on = core_on.retrieval.get_context(hint, token_budget=2000)
        ctx_off = core_off.retrieval.get_context(hint, token_budget=2000)
        self.assertEqual(ctx_on, ctx_off)

    def test_answer_byte_identical_on_vs_off_for_factual_query(self):
        # Same underlying store/events for both engines (only the config flag
        # differs) so this isolates the routing switch itself rather than
        # incidentally comparing two independently content-hashed event sets.
        query = "where does Pat Testley work"
        core, home = make_core()
        core.capture.observe("Pat Testley works at Acme Fake Co as a veterinarian",
                              "ok", session_id="s1")
        core.process_pending()
        from engine.config import Config
        eng_on = RetrievalEngine(core.store, Config({"retrieval": {"query_routing": True}}),
                                  embedder=core.embedder)
        eng_off = RetrievalEngine(core.store, Config({"retrieval": {"query_routing": False}}),
                                   embedder=core.embedder)
        ans_on = eng_on.answer(query)
        ans_off = eng_off.answer(query)
        ans_on.pop("debug", None)
        ans_off.pop("debug", None)
        self.assertEqual(ans_on, ans_off)


class TestAggregationRouteWidensPool(unittest.TestCase):
    """aggregation -> widen per-session candidate diversity (raise limit, cap
    per-session takes), purely additive/redistributive: never drops an
    excerpt phase 1 would otherwise have included."""

    def test_aggregation_spreads_across_sessions(self):
        core, home = make_core()
        for i in range(6):
            core.capture.observe(f"I went kayaking on trip number {i}", "ok",
                                  session_id="s{}".format(i))
        core.process_pending()
        ctx = core.retrieval.get_context("how many kayaking trips did I take",
                                          token_budget=4000)
        session_headers = {line for line in ctx.splitlines() if line.startswith("[SESSION")}
        # Every session should get a shot at representation rather than one
        # heavily-matching session crowding out the rest of a top-20 pool.
        self.assertGreaterEqual(len(session_headers), 4)


class TestTemporalRouteDatesShown(unittest.TestCase):
    """temporal -> chronological ordering emphasis, dates always shown."""

    def test_excerpts_carry_dates_and_are_chronological(self):
        core, home = make_core()
        core.capture.observe("I went kayaking in Sacramento last June", "ok", session_id="s1")
        core.capture.observe("I prefer window seats when flying", "ok", session_id="s1")
        core.process_pending()
        ctx = core.retrieval.get_context("when did I go kayaking", token_budget=2000)
        body_lines = [ln for ln in ctx.splitlines() if ln.strip().startswith("[20")]
        self.assertTrue(body_lines, "temporal route should date-prefix excerpt lines")
        self.assertEqual(body_lines, sorted(body_lines))


class TestPreferenceRouteIncludesBeliefs(unittest.TestCase):
    """preference -> include preference-tier beliefs.

    F5 changed HOW, and the change is a deletion, so this test is rewritten
    rather than dropped. E9 shipped an addendum that appended up to five
    `[PREFERENCE] <attribute>: <value>` lines selected with no relevance term
    and no ORDER BY — in rowid order. Measured over 250 real questions it fired
    0 times; measured over the 9 preference misses with F3 §5.4's proposed
    extraction patterns in place, the five lines it would inject contain 0/45
    facts from the answer session in rowid order and 3/45 ordered by date. It
    is gone (F5 item 4). Preference-tier beliefs now reach the reader as the
    user's own sentence, packed by `context.preference_packing` out of the
    sessions retrieval ranked for THIS question — see tests/test_pref_pack.py.

    What survives unchanged is the contract this class was written for: on the
    preference route, a preference the tier-1 fusion did not rank still has to
    arrive.
    """

    def test_preference_content_surfaced_without_the_addendum(self):
        core, home = make_core()
        for i in range(3):
            core.capture.observe("My favorite color is blue and I like bold colors",
                                 "ok " * 200, session_id="s%d" % i)
            core.capture.observe("Pat Testley works at Acme Fake Co", "ok " * 200,
                                 session_id="s%d" % i)
        core.process_pending()
        ctx = core.retrieval.get_context("recommend a color I would like",
                                          token_budget=2000)
        self.assertEqual(core.retrieval.last_context_debug["route"], "preference")
        self.assertIn("My favorite color is blue", ctx)
        self.assertNotIn("[PREFERENCE]", ctx)

    def test_a_preference_query_that_matches_nothing_gets_nothing(self):
        """The honest consequence of the excision, pinned rather than papered
        over. The original fixture for this class was a two-turn store in which
        BOTH tiers miss the query outright — `retrieve_raw` and `search` each
        return zero rows — and the only thing the reader ever received was the
        addendum's arbitrary `[PREFERENCE]` line. That line was not retrieval
        succeeding; it was a total retrieval miss reported as a preference. An
        empty context is the truthful answer, and the reader treats it as one."""
        core, home = make_core()
        core.capture.observe("My favorite color is blue", "ok", session_id="s1")
        core.capture.observe("Pat Testley works at Acme Fake Co", "ok", session_id="s1")
        core.process_pending()
        q = "recommend something I would like"
        self.assertEqual(core.retrieval.retrieve_raw(q, limit=20), [])
        self.assertEqual(core.retrieval.search(q, limit=10), [])
        self.assertEqual(core.retrieval.get_context(q, token_budget=2000), "")


class TestRouteMarginGate(unittest.TestCase):
    """Integration fix (L9 review, item H): departing the default `factual`
    route requires BEATING it by retrieval.query_routing_margin, not merely
    tying it.

    A bare argmax over the four prototype centroids over-routed badly -- 45 of
    60 real LongMemEval questions classified "aggregation", including plainly
    factual ones -- and every misroute then paid the aggregation route's
    per-session excerpt cap, which drops evidence. Measured cost:
    ctx_eval@4000 86.2% -> 82.8%, outside the integration tolerance.
    """

    def setUp(self):
        self.core, self.home = make_core()
        self.r = self.core.retrieval

    def test_ambiguous_factual_question_stays_factual(self):
        """THE reviewer's counterexample: a plainly factual question that the
        bare argmax sent to "aggregation"."""
        info = self.r.classify_route("What is my ethnicity?")
        self.assertEqual(info["route"], "factual")

    def test_confident_route_queries_still_clear_the_margin(self):
        """The margin trims the ambiguous middle only -- it must not disturb
        the acceptance classifications, which win by a wide band."""
        for q, expected in (("how many times did I go kayaking", "aggregation"),
                            ("when did I go kayaking", "temporal"),
                            ("recommend a restaurant for dinner", "preference")):
            self.assertEqual(self.r.classify_route(q)["route"], expected, q)

    def test_margin_zero_restores_the_bare_argmax(self):
        """The gate is a config dial, not a hardcode: at margin 0 the routing
        decision is exactly the pre-fix argmax."""
        core, _ = make_core({"retrieval": {"query_routing_margin": 0.0}})
        info = core.retrieval.classify_route("What is my ethnicity?")
        best = max(info["scores"], key=lambda k: info["scores"][k])
        self.assertEqual(info["route"], best)
        self.assertNotEqual(info["route"], "factual")   # discriminating: it DID misroute

    def test_scores_stay_inspectable_when_the_margin_demotes(self):
        """§E9 requires the decision be inspectable. Demoting to factual must
        report the UNCHANGED geometry, not a blanked-out debug field."""
        info = self.r.classify_route("What is my ethnicity?")
        self.assertEqual(info["route"], "factual")
        self.assertTrue(info["enabled"])
        self.assertEqual(set(info["scores"]), {"aggregation", "temporal", "preference", "factual"})

    def test_a_no_signal_query_scores_zero_against_every_centroid(self):
        """WHY the bare argmax failed, pinned so a future change to the phrase
        bank cannot quietly reintroduce it.

        This query shares no token with any prototype bank, so all four cosines
        are exactly 0.0. max() over an all-equal mapping returns whichever key
        sorts first in _ROUTE_KINDS -- "aggregation" -- so the pre-fix route was
        decided by TUPLE ORDER, not by similarity. The margin gate is what makes
        a tie fall back to the default route instead."""
        info = self.r.classify_route("What is my ethnicity?")
        self.assertEqual(set(info["scores"].values()), {0.0},
                         "expected a no-signal query; the phrase bank now overlaps it")
        # Tie, not a win: nothing here ever justified leaving the default route.
        self.assertEqual(max(info["scores"].values()), info["scores"]["factual"])
        self.assertEqual(info["route"], "factual")

    def test_a_high_margin_forces_every_unoverridden_query_factual(self):
        """F5 narrowed this contract, deliberately and visibly.

        `query_routing_margin` is now the DEFAULT for kinds that have no entry
        in `retrieval.query_routing_margins`; a kind that has one answers to
        that instead, in both directions, which is what "override" means and
        what makes the preference route reachable at all (F5 §1). So maxing the
        global knob still forces every un-overridden kind factual...
        """
        core, _ = make_core({"retrieval": {"query_routing_margin": 1.0}})
        for q in ("how many times did I go kayaking", "when did I go kayaking"):
            self.assertEqual(core.retrieval.classify_route(q)["route"], "factual", q)

    def test_a_high_global_margin_does_not_override_a_per_kind_entry(self):
        """...and a kind that HAS an entry keeps it, so `query_routing_margin:
        1.0` is not a way to switch routing off. `query_routing: false` is
        (asserted below), and raising the per-kind entry is the other."""
        core, _ = make_core({"retrieval": {"query_routing_margin": 1.0}})
        self.assertEqual(
            core.retrieval.classify_route("recommend a restaurant for dinner")["route"],
            "preference")

    def test_switching_routing_off_still_forces_every_query_factual(self):
        """The knob that actually disables routing, per-kind margins and all."""
        core, _ = make_core({"retrieval": {"query_routing": False}})
        for q in ("how many times did I go kayaking", "when did I go kayaking",
                  "recommend a restaurant for dinner"):
            info = core.retrieval.classify_route(q)
            self.assertEqual(info["route"], "factual", q)
            self.assertFalse(info["enabled"])


if __name__ == "__main__":
    unittest.main()
