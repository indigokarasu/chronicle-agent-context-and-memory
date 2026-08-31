"""
Chronicle — F5: per-kind routing margins + preference packing (§18.2, F3 report).

Three mechanisms, each pinned by a test that FAILS if the mechanism is removed:

  1. `retrieval.query_routing_margins` — a per-kind override of the single
     global margin gate. Deleting the override sends a preference question back
     to the factual route (TestPerKindRoutingMargin).
  2. `context.preference_packing` — get_context packs the leading (user)
     message of every ranked excerpt first, defers the assistant halves, and
     cuts to `context.preference_budget`. Turning it off restores the un-split
     full-budget fill (TestPreferencePacking).
  3. The two together are what makes E12's `route == "factual"` precision gate
     non-vacuous for this question kind: a preference question whose retrieval
     converges on the WRONG session must not be precision-packed onto it
     (TestE12DoesNotPrecisionPackPreference). On the merged ladder-9 tree that
     refusal has a SECOND, independent cause — F2X's true-argmax gate — so
     TestE12DoesNotPrecisionPackPreference disables the two layers one at a
     time; see its docstring.

Everything runs under the offline hashing embedder — deterministic, no network,
the same mode the recall/ctx_eval gate harnesses use — over fake fixtures.
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest import mock

from engine import capture as capture_mod
from engine import embeddings as embeddings_mod
from engine.config import DEFAULTS
from engine.core import ChronicleCore
from engine.retrieval import _MSG_START, _split_lead_message


def make_core(cfg_overrides=None):
    cfg = {"embeddings": {"model": "hashing"}}
    if cfg_overrides:
        cfg.update(cfg_overrides)
    return ChronicleCore(tempfile.mkdtemp(), cfg)


# -- fixture: the F3 report's `1d4e3b97` shape, in fake data ------------------
#
# A road-bike question whose evidence ("I replaced the old chain and cassette")
# lives in a two-turn session, against a five-turn decoy session about a spin
# studio that carries the question's own vocabulary ("bike", "Sunday"). That is
# the measured failure: E12 precision packing converged on the SoulCycle
# session, cut the context to 5 990 chars containing only it, and dropped the
# gold evidence that the pre-E12 tree had answered from.
_SPIN_SESSION = [
    ("I'm excited to try the spin studio, their Sunday bike class looks fun",
     "Indoor spin classes are a great workout on a stationary bike."),
    ("Do I need special shoes for the Sunday bike class?",
     "Most spin studios rent clip-in shoes for the stationary bike."),
    ("How hard is the Sunday bike class for a beginner?",
     "Sunday spin classes are beginner friendly, ride at your own resistance."),
    ("Should I book the Sunday bike class in advance?",
     "Yes, popular Sunday spin bike classes fill up fast."),
    ("What should I bring to the Sunday bike class?",
     "Water, a towel and shoes are all you need for the spin bike class."),
]
_GOLD_SESSION = [
    ("I replaced the old chain and cassette on February 1st before the group ride",
     "A fresh drivetrain makes a big difference to pedalling efficiency."),
    ("I also fitted a new Garmin cycling computer to the road frame",
     "A cycling computer helps you pace a group ride and track cadence."),
]
# Preference-shaped, and deliberately in the band the F3 sweep measured: its
# preference-over-factual lead is ~0.069, i.e. above F5's 0.05 override and
# below the shipped 0.20 global margin. A question that cleared 0.20 anyway
# would prove nothing about the override.
_BIKE_Q = "Can you suggest what to do about my bike on Sunday rides?"
_GOLD_EVIDENCE = "chain and cassette"


def build_bike_store(cfg_overrides=None):
    core = make_core(cfg_overrides)
    for user, assistant in _SPIN_SESSION:
        core.capture.observe(user, assistant, session_id="spin")
    for user, assistant in _GOLD_SESSION:
        core.capture.observe(user, assistant, session_id="gold")
    core.process_pending()
    return core


class TestPerKindRoutingMargin(unittest.TestCase):
    """`retrieval.query_routing_margins` overrides the global margin per kind.

    Why it exists (F3 §4a, measured over 250 real LongMemEval questions with
    real nomic embeddings): `preference` is the argmax on 15/15 preference
    questions and its lead over `factual` never exceeds 0.138, so at the
    shipped global 0.20 the route fired 0 times out of 250 — the E9 preference
    route and the E12 guard that depends on it were both dead code, while the
    aggregation route the 0.20 figure was calibrated against still fired.
    """

    def setUp(self):
        self.core = build_bike_store()

    def test_preference_clears_a_margin_the_global_gate_vetoes(self):
        """THE mechanism. This question's preference lead sits between the
        per-kind 0.05 and the global 0.20, so it routes preference only because
        the override exists."""
        info = self.core.retrieval.classify_route(_BIKE_Q)
        lead = info["scores"]["preference"] - info["scores"]["factual"]
        self.assertGreater(lead, 0.05, "fixture drift: lead must exceed the override")
        self.assertLess(lead, 0.20, "fixture drift: lead must NOT clear the global margin")
        self.assertEqual(info["route"], "preference")

    def test_deleting_the_override_sends_it_back_to_factual(self):
        """The discriminating half: with the per-kind entry removed from
        DEFAULTS entirely the global 0.20 applies and the same question is
        factual again — which is exactly the shipped behaviour F5 changes.

        Removed from DEFAULTS rather than overridden to `{}` in a config,
        because config merge is a DEEP merge: an empty dict leaves the default
        entry standing, and a test written that way would pass no matter what
        classify_route does."""
        retrieval_defaults = dict(DEFAULTS["retrieval"])
        retrieval_defaults.pop("query_routing_margins")
        with mock.patch.dict(DEFAULTS, {"retrieval": retrieval_defaults}):
            core = make_core()
            self.assertEqual(core.retrieval.classify_route(_BIKE_Q)["route"], "factual")

    def test_the_documented_kill_switch_makes_f5_inert(self):
        """`{"preference": 0.20}` is what the config comment offers as the way
        to restore pre-F5 routing, so it has to actually do that."""
        core = make_core({"retrieval": {"query_routing_margins": {"preference": 0.20}}})
        self.assertEqual(core.retrieval.classify_route(_BIKE_Q)["route"], "factual")

    def test_the_override_does_not_leak_to_other_kinds(self):
        """A per-kind knob that quietly loosened every kind would reintroduce
        the over-routing the margin gate was added to stop. `aggregation` and
        `temporal` are not in the map, so they still answer to the global
        margin — pinned on the reviewer's own counterexample."""
        r = self.core.retrieval
        self.assertEqual(r.classify_route("What is my ethnicity?")["route"], "factual")
        info = r.classify_route("What is my ethnicity?")
        for kind in ("aggregation", "temporal"):
            self.assertLess(info["scores"][kind] - info["scores"]["factual"], 0.20)

    def test_a_confident_non_preference_route_is_untouched(self):
        """The acceptance classifications must not move."""
        r = self.core.retrieval
        for q, expected in (("how many times did I go kayaking", "aggregation"),
                            ("when did I go kayaking", "temporal")):
            self.assertEqual(r.classify_route(q)["route"], expected, q)

    def test_an_unusable_override_falls_back_to_the_global_margin(self):
        """A bad value must not silently become 0.0 (i.e. the bare argmax the
        margin gate exists to prevent) — same fallback contract the clamp
        helpers already hold to."""
        for bad in (None, "abc", float("nan"), [0.05]):
            core = make_core({"retrieval": {"query_routing_margins": {"preference": bad}}})
            self.assertEqual(core.retrieval.classify_route(_BIKE_Q)["route"], "factual",
                             "override %r should fall back to the global 0.20" % (bad,))

    def test_an_out_of_range_override_is_clamped(self):
        core = make_core({"retrieval": {"query_routing_margins": {"preference": -5.0}}})
        self.assertEqual(core.retrieval.classify_route(_BIKE_Q)["route"], "preference")
        core = make_core({"retrieval": {"query_routing_margins": {"preference": 99.0}}})
        self.assertEqual(core.retrieval.classify_route(_BIKE_Q)["route"], "factual")

    def test_scores_stay_inspectable(self):
        """§E9 requires the raw geometry be reported unchanged whichever way
        the gate decides."""
        info = self.core.retrieval.classify_route(_BIKE_Q)
        self.assertEqual(set(info["scores"]),
                         {"aggregation", "temporal", "preference", "factual"})
        self.assertTrue(info["enabled"])


class TestE12DoesNotPrecisionPackPreference(unittest.TestCase):
    """E12's own docstring: "aggregation/temporal/preference questions are
    answered by surveying many items; cutting to one is the wrong move there by
    construction, so those routes never take this path."

    That guard was vacuous, because routing collapsed every preference question
    to `factual`. F3 measured the cost on `1d4e3b97`: precision packing fired,
    converged on a spin-class session, delivered 5 990 chars that did not
    contain the gold evidence at all, and turned a pass into a miss.

    INTEGRATION NOTE (ladder-9 merge, F5 x F2X). Two independently-derived
    layers now refuse this cut, and the tests below pin BOTH rather than
    letting one hide the other:

      * F5 (this work item): the per-kind margin makes the question route
        `preference`, so E12's `route == "factual"` precondition excludes it.
      * F2X (`_raw_route`, the true-argmax gate): even when the route STRING is
        `factual`, E12 additionally requires the raw score geometry to name
        factual — and on a preference question it names `preference`.

    F5 shipped a single discriminating test that restored the global 0.20
    margin and asserted the defect came back. Against the merged tree that
    assertion is false, and correctly so: neutralising F5 alone leaves F2X
    holding the gate. That is defence in depth working, not a lost fixture — so
    the discriminating half is stated as three cases that turn the layers off
    one at a time, which is the only way to show each is load-bearing on its
    own AND that the fixture still reproduces the original bug.
    """

    @staticmethod
    def _disable_f2x(engine):
        """Neutralise the true-argmax gate on one engine instance.

        Stubbed rather than config-gated because F2X is deliberately NOT a dial
        — it ships no knob (`_raw_route` is consulted unconditionally), which is
        itself part of its spec. Returning "factual" for every geometry is
        exactly the pre-F2X call site, so what remains standing is F5 and
        nothing else."""
        engine._raw_route = lambda scores: "factual"

    def test_preference_question_is_not_precision_packed(self):
        core = build_bike_store()
        ctx = core.retrieval.get_context(_BIKE_Q, token_budget=12000)
        debug = core.retrieval.last_context_debug
        self.assertEqual(debug["route"], "preference")
        self.assertFalse(debug["precision"], "E12 must not fire on the preference route")
        self.assertTrue(debug["pref_pack"])
        self.assertIn(_GOLD_EVIDENCE, ctx)

    def test_the_fixture_still_reproduces_the_measured_defect(self):
        """BOTH layers off: the SAME store + SAME question is routed factual,
        precision-packed onto the decoy session, and the gold evidence is gone.
        This is the bug F5 and F2X each independently prevent; if this test ever
        stops failing to find the evidence, the fixture has stopped reproducing
        it and the two tests below prove nothing."""
        core = build_bike_store(
            {"retrieval": {"query_routing_margins": {"preference": 0.20}}})
        self._disable_f2x(core.retrieval)
        ctx = core.retrieval.get_context(_BIKE_Q, token_budget=12000)
        debug = core.retrieval.last_context_debug
        self.assertEqual(debug["route"], "factual")
        self.assertTrue(debug["precision"])
        self.assertEqual(debug["precision_session"], "spin")
        self.assertNotIn(_GOLD_EVIDENCE, ctx)

    def test_f5_routing_alone_suffices(self):
        """F2X off, F5 shipped: the per-kind margin routes the question
        `preference`, which is what excludes it from E12 — the raw-argmax gate
        contributes nothing here because it has been stubbed to agree with the
        old call site."""
        core = build_bike_store()
        self._disable_f2x(core.retrieval)
        ctx = core.retrieval.get_context(_BIKE_Q, token_budget=12000)
        debug = core.retrieval.last_context_debug
        self.assertEqual(debug["route"], "preference")
        self.assertFalse(debug["precision"])
        self.assertTrue(debug["pref_pack"])
        self.assertIn(_GOLD_EVIDENCE, ctx)

    def test_f2x_argmax_alone_suffices(self):
        """F5 inert (its documented kill switch), F2X live: the route STRING is
        `factual` — i.e. F5 is contributing nothing — and the cut is refused
        anyway, because the raw geometry names `preference`. The evidence
        survives on the ordinary full-budget path, with no preference packing
        involved."""
        core = build_bike_store(
            {"retrieval": {"query_routing_margins": {"preference": 0.20}}})
        r = core.retrieval
        info = r.classify_route(_BIKE_Q)
        self.assertEqual(info["route"], "factual",
                         "fixture: F5 must be inert here, or this tests F5")
        self.assertEqual(r._raw_route(info["scores"]), "preference")
        ctx = r.get_context(_BIKE_Q, token_budget=12000)
        debug = r.last_context_debug
        self.assertEqual(debug["route"], "factual")
        self.assertFalse(debug["precision"], "F2X's true-argmax gate must refuse the cut")
        self.assertFalse(debug["pref_pack"])
        self.assertIn(_GOLD_EVIDENCE, ctx)


class TestPreferencePacking(unittest.TestCase):
    """`context.preference_packing`: user turns first, assistant halves last,
    at `context.preference_budget`.

    Measured basis (F3 §4c): 73-91% of a packed preference context is assistant
    prose, and only the user's half of an excerpt can carry a preference. On the
    one instance E12 had already cut to 1 500 tokens, 5 471 of 5 994 chars were
    a generic recipe list and 3 of the gold session's 9 user turns arrived; the
    9 user turns together are 1 223 chars.
    """

    # Four sessions of six user turns each, with assistant replies that dwarf
    # them — the ratio F3 measured (73-91% assistant prose). Each user turn is
    # distinct and ~115 chars, in the band the report measured for a real user
    # head (median 162-182, p90 344-394). Distinct matters: byte-identical
    # turns across sessions would be collapsed by get_context's final dedupe
    # and the test would be measuring the dedupe, not the packing.
    _DISHES = ("thai", "korean", "indian", "sichuan", "mexican", "ethiopian")
    LONG_REPLY = ("That is helpful to know. Here is a long and detailed reply about "
                  "restaurant options, menus, seasonal produce and reservation "
                  "advice that goes on at considerable length. ") * 12
    PREF_Q = "recommend a restaurant for dinner"

    @classmethod
    def user_turns(cls, session):
        return ["I love the spicy %s dish and I always order it with extra chilli "
                "when I eat out in the evening near session %d" % (dish, session)
                for dish in cls._DISHES]

    def all_user_turns(self, sessions=4):
        return [t for s in range(sessions) for t in self.user_turns(s)]

    def build(self, cfg_overrides=None, sessions=4):
        core = make_core(cfg_overrides)
        for s in range(sessions):
            for turn in self.user_turns(s):
                core.capture.observe(turn, self.LONG_REPLY, session_id="s%d" % s)
        core.process_pending()
        return core

    def test_route_and_flag(self):
        core = self.build()
        core.retrieval.get_context(self.PREF_Q, token_budget=12000)
        debug = core.retrieval.last_context_debug
        self.assertEqual(debug["route"], "preference")
        self.assertTrue(debug["pref_pack"])
        self.assertEqual(debug["token_budget"], 3000)

    def test_budget_is_cut_to_the_preference_budget(self):
        core = self.build()
        ctx = core.retrieval.get_context(self.PREF_Q, token_budget=12000)
        self.assertLessEqual(len(ctx), 3000 * 4)
        self.assertTrue(ctx.strip())

    def test_every_user_turn_of_every_session_survives(self):
        """THE mechanism, stated as the thing the reader actually receives.

        This is the F3 defect in one assertion. On `06f04340` the gold session
        DID get its own block in the shipped 48k context and that block carried
        1 of the session's 7 user turns — the wrong one. Here all 24 user turns
        of all 4 sessions arrive inside 1 500 tokens, and every session is
        represented: nothing is starved by an earlier session's share."""
        core = self.build()
        ctx = core.retrieval.get_context(self.PREF_Q, token_budget=12000)
        missing = [t for t in self.all_user_turns() if t not in ctx]
        self.assertEqual(missing, [], "user turns dropped: %d" % len(missing))
        for s in range(4):
            self.assertIn("[SESSION s%d" % s, ctx)

    def test_disabling_packing_restores_the_full_budget_fill(self):
        """The discriminating half: with `preference_packing: False` the same
        query on the same store gets the un-split fill at the caller's own
        budget, i.e. 8x the volume and mostly assistant prose — and it drops
        user turns this route is supposed to deliver."""
        core = self.build({"context": {"preference_packing": False}})
        ctx = core.retrieval.get_context(self.PREF_Q, token_budget=12000)
        debug = core.retrieval.last_context_debug
        self.assertEqual(debug["route"], "preference")
        self.assertFalse(debug["pref_pack"])
        self.assertEqual(debug["token_budget"], 12000)
        self.assertGreater(len(ctx), 3000 * 4)
        self.assertIn("reservation advice", ctx)

    def test_user_turns_are_reserved_before_any_assistant_half(self):
        """Ordering is the load-bearing half of the design. At a budget that
        cannot hold both, EVERY user turn still arrives and no assistant half
        does — a single streaming pass would instead spend session 0's whole
        share on its own assistant replies and never reach session 3."""
        core = self.build({"context": {"preference_budget": 800}})
        ctx = core.retrieval.get_context(self.PREF_Q, token_budget=12000)
        self.assertLessEqual(len(ctx), 800 * 4)
        self.assertNotIn("reservation advice", ctx)
        missing = [t for t in self.all_user_turns() if t not in ctx]
        self.assertEqual(missing, [], "user turns dropped: %d" % len(missing))

    def test_the_budget_is_never_more_than_the_caller_asked_for(self):
        """Preference packing is a REDUCTION: a caller who already asked for
        less than the preference budget keeps their own tighter budget."""
        core = self.build()
        ctx = core.retrieval.get_context(self.PREF_Q, token_budget=400)
        self.assertLessEqual(len(ctx), 400 * 4)
        self.assertEqual(core.retrieval.last_context_debug["token_budget"], 400)

    def test_assistant_halves_land_under_their_own_session_header(self):
        """A flat two-pass fill would append a deferred assistant half after
        whatever block was emitted last, silently attributing one session's
        reply to another. Per-session buffers are what prevent that, so pin it:
        every line of the context sits under the header of the session it came
        from."""
        core = make_core()
        core.capture.observe("I love spicy Thai food", "Reply about ALPHA cuisine.",
                             session_id="alpha")
        core.capture.observe("I prefer window seats", "Reply about BETA seating.",
                             session_id="beta")
        core.process_pending()
        ctx = core.retrieval.get_context(self.PREF_Q, token_budget=12000)
        current = None
        seen = set()
        for line in ctx.splitlines():
            m = re.match(r"\[SESSION ([^\]\s@]+)", line)
            if m:
                current = m.group(1)
                self.assertNotIn(current, seen, "session %s headed twice" % current)
                seen.add(current)
                continue
            if "ALPHA" in line:
                self.assertEqual(current, "alpha")
            if "BETA" in line:
                self.assertEqual(current, "beta")

    def test_a_single_message_excerpt_is_all_head(self):
        """`_split_lead_message` must never drop content: an excerpt with no
        role boundary is returned whole, not emptied."""
        self.assertEqual(_split_lead_message("no role boundary here"),
                         ("no role boundary here", ""))
        self.assertEqual(_split_lead_message(""), ("", ""))

    def test_the_split_is_role_agnostic(self):
        """Generic by design — it keeps the FIRST message whatever the roles
        are called, rather than special-casing "User:"/"Assistant:"."""
        head, tail = _split_lead_message("Alice: hello there\nBob: hi back")
        self.assertEqual(head, "Alice: hello there")
        self.assertEqual(tail, "Bob: hi back")

    def test_msg_start_matches_capture_and_embeddings(self):
        """Third copy of one regex; the other two exist for the same layering
        reason. This fails the moment they drift."""
        self.assertEqual(_MSG_START.pattern, capture_mod._MSG_START.pattern)
        self.assertEqual(_MSG_START.pattern, embeddings_mod._EMBED_MSG_START.pattern)


class TestPreferencePackingDegradesSafely(unittest.TestCase):
    """The two ways this must be a no-op rather than a regression."""

    def test_no_embedder_is_byte_identical(self):
        """No vector channel means no route classification at all, so nothing
        below the routing call can change (I18)."""
        def build(cfg):
            core = ChronicleCore(tempfile.mkdtemp(), cfg)
            core.capture.observe("I love spicy Thai food", "A long reply. " * 40,
                                 session_id="s1")
            core.capture.observe("I prefer window seats", "Another long reply. " * 40,
                                 session_id="s2")
            core.process_pending()
            return core
        off = {"embeddings": {"model": "none"}, "retrieval": {"query_routing": False}}
        on = {"embeddings": {"model": "none"}}
        a = build(off).retrieval.get_context("recommend a restaurant", token_budget=4000)
        b = build(on).retrieval.get_context("recommend a restaurant", token_budget=4000)
        self.assertEqual(a, b)

    def test_an_empty_raw_tier_leaves_the_belief_tier_intact(self):
        """Preference packing buys density by trading the tier-1 ranked
        beliefs away for the raw fill. If the raw fill is EMPTY that is not a
        trade, it is an empty context — and it is reachable: on the shipped E9
        fixture store `retrieve_raw` returns 0 rows for this query and the
        belief tier was the only thing the reader ever got. So the same top-20
        probe E12 makes gates this too."""
        q = "recommend something I would like"

        def build(cfg_overrides=None):
            core = make_core(cfg_overrides)
            core.capture.observe("My favorite color is blue", "ok", session_id="s1")
            core.process_pending()
            return core

        core = build()
        self.assertEqual(core.retrieval.retrieve_raw(q, limit=20), [],
                         "fixture drift: this store must have an empty raw tier")
        ctx = core.retrieval.get_context(q, token_budget=2000)
        debug = core.retrieval.last_context_debug
        self.assertEqual(debug["route"], "preference")
        self.assertFalse(debug["pref_pack"], "an empty raw tier must not trade the beliefs away")
        self.assertEqual(debug["token_budget"], 2000, "the budget must not be cut")
        # ...and the resulting context is what routing-off produces, byte for byte.
        unrouted = build({"retrieval": {"query_routing": False}})
        self.assertEqual(ctx, unrouted.retrieval.get_context(q, token_budget=2000))


class TestPreferenceAddendumIsGone(unittest.TestCase):
    """F5 item 4, resolved by EXCISION rather than repair — pinned so it cannot
    be reintroduced by reflex.

    E9's addendum appended up to five `[PREFERENCE] <attribute>: <value>` lines
    fetched with no relevance term and no ORDER BY, i.e. in rowid order. It was
    dead three times over (route never fired; HeuristicExtractor emits no
    preference-shaped facts, so the query returned 0 rows in 7 of 8 probed
    haystacks; and its `len(ctx) < max_chars` guard cannot fire against a raw
    fill that spends the budget to the last byte).

    It was not repaired, because repairing it was measured and does not work.
    Adding F3 §5.4's first-person patterns to the extractor yields 211
    preference facts across the 9 miss haystacks of which 8 (3.8%) come from
    the gold session and 5 from a has_answer turn, and NO ordering rescues the
    five lines it would inject: rowid 0/45 from the gold session, created_at
    DESC 3/45, created_at ASC 0/45. The patterns also fire on politeness about
    the assistant's own suggestions ("I like the sound of the Spa-Inspired
    Retreat"), which would become confidence-0.85 user facts on the write path
    for all 250 questions. Preference packing delivers the same content from
    the primary source — the user's own sentence, from the sessions retrieval
    ranked for THIS question — so the addendum had nothing left to add that was
    not both lossier and less relevant.
    """

    def test_no_preference_addendum_lines(self):
        core = build_bike_store()
        ctx = core.retrieval.get_context(_BIKE_Q, token_budget=12000)
        self.assertNotIn("[PREFERENCE]", ctx)

    def test_the_dead_config_knob_is_gone_too(self):
        from engine.config import DEFAULTS
        self.assertNotIn("query_routing_preference_cap", DEFAULTS["retrieval"])

    def test_preference_content_still_reaches_the_reader(self):
        """Excision is only defensible because the content still arrives. The
        E9 fixture's preference is delivered as the user's own words."""
        core = make_core()
        for i in range(3):
            core.capture.observe("My favorite color is blue and I like bold colours",
                                 "A long reply about colour palettes. " * 20,
                                 session_id="s%d" % i)
        core.process_pending()
        ctx = core.retrieval.get_context("recommend a colour I would like",
                                         token_budget=12000)
        self.assertTrue(core.retrieval.last_context_debug["pref_pack"])
        self.assertIn("My favorite color is blue", ctx)


if __name__ == "__main__":
    unittest.main()
