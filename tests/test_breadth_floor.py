"""
Chronicle — A18: the route-aware BREADTH FLOOR in get_context's raw fill.

WHAT WAS MEASURED (scripts/ctx_eval_probe.py over the 58-instance ctx_eval
corpus, hashing embedder, three budget tiers). Per instance it records the E9
route, the number of DISTINCT sessions in the emitted context, the share of the
raw-evidence fill claimed by the largest one, whether the gold session arrived,
and whether the instance passed:

  budget | aggregation route      | multi-gold instances   | fill saturated
   1 500 |  1.6 sessions, top  99% |  1.6 sessions, top 100% | 100%
   4 000 |  4.0 sessions, top  56% |  3.6 sessions, top  58% | 100%
  12 000 | 12.2 sessions, top  19% | 11.4 sessions, top  19% | 100%

At 1 500 tokens the raw fill is ONE session in 13 of 28 aggregation-route
instances and the largest session claims ~100% of it, while the budget is fully
saturated; 13 of 33 multi-gold instances carry no gold session at all, 12 of
those with <= 2 sessions emitted. At 12 000 the effect is gone. The motivating
instance (#16, "How many plants did I acquire in the last month?") is therefore
representative of a tight-budget PROPERTY of the packer, not an outlier.

THE FIX: group i of the first N gets `remaining // (N - i)` chars of the
ranked-excerpt fill, so no session can spend the budget before the next has
been offered its share, and a session that underspends hands the surplus
straight to the next divisor. Only on the routes whose answer is spread across
sessions (aggregation, temporal); the session-window EXPANSION that follows is
not rationed, because by then every group has already had its turn.

N was read off a sweep of the same corpus rather than chosen
(scripts/ctx_eval_probe.py with A18_FLOOR=n): see MEASUREMENTS.md.

The factual route is excluded BY CONSTRUCTION, and that is the hard constraint
this file guards in two directions: the same fixture must KEEP the second
session's evidence under the breadth route and LOSE it under the factual one,
and a factual context must be byte-identical with the floor on and off.

Fixtures use obviously-fake content (kayaking trips).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import ChronicleCore
from test_precision_packing import assert_one_answer_across_seeds

BREADTH_Q = "how many kayaking trips did I take"
FACTUAL_Q = "what kayaking trips did I take"
TEMPORAL_Q = "when did I go kayaking"

# The answer to the breadth question lives HERE, in the session that ranks
# second. Distinctive enough that its presence in a context is unambiguous.
MARKER = "I have now been on eleven kayaking trips in total this year"

# One heavily-matching session's worth of long, on-topic turns. Long enough
# that three of them alone overrun a tight budget -- which is the whole point:
# E9's aggregation route already caps this session at 3 EXCERPTS, and an
# excerpt runs to capture.max_excerpt_chars = 4000, so a cap in items does not
# bound a cap in chars.
FILLER = ("I went on another kayaking trip and the kayaking was excellent. "
          "The kayak handled well on the kayaking route we took. " * 12)
# The answer turn is the same LENGTH as one of those (so it is not favoured for
# being short) and thinner on the query's own words (so it ranks below them).
# It must rank second, not first: a fixture whose gold session already leads is
# not a test of anything this change does.
DILUTE = ("We also repotted the tomatoes and fixed the shed door that weekend, "
          "then spent an afternoon sorting the garage shelves. " * 3)


def block_of(ctx, sid):
    """The lines emitted under `[SESSION <sid> ...]`, and nothing else.

    Needed rather than a plain `in ctx` test because the tier-1 belief block
    renders the same turns as `[EPISODE]` lines: on this fixture the answer
    turn reaches the reader through tier-1 whether or not the raw fill ever
    packs its session, so "the marker is somewhere in the context" is true even
    when the packer dropped the session entirely. What the breadth floor
    decides is whether the SESSION -- header, date, neighbouring turns -- is
    represented in the fill, so that is what these tests read.
    """
    out, on = [], False
    for line in ctx.split("\n"):
        if line.startswith("[SESSION "):
            on = line.startswith("[SESSION %s" % sid)
            continue
        if on:
            out.append(line)
    return "\n".join(out)


def make_core(cfg_overrides=None):
    """A store with one dominant session and one second-best session that
    holds the answer, plus distractors."""
    cfg = {"embeddings": {"model": "hashing"}}
    if cfg_overrides:
        for k, v in cfg_overrides.items():
            cfg.setdefault(k, {}).update(v) if isinstance(v, dict) else cfg.update({k: v})
    core = ChronicleCore(tempfile.mkdtemp(), cfg)
    core.initialize(session_id="eval", principal_id="assistant")
    # s_dominant: five long on-topic turns -- the session retrieval converges on.
    for i in range(5):
        core.capture.observe("Tell me about kayaking trip %d. %s" % (i, FILLER),
                             "Sure: %s" % FILLER, session_id="s_dominant",
                             occurred_at="2026-03-0%dT10:00:00Z" % (i + 1))
    # s_answer: ONE on-topic turn carrying the count. Ranks below s_dominant.
    core.capture.observe("%s. %s" % (MARKER, DILUTE),
                         "Noted, that is a kayaking milestone. %s" % DILUTE,
                         session_id="s_answer", occurred_at="2026-03-06T10:00:00Z")
    # Two more sessions so the group list is not two items long.
    for j, sid in enumerate(("s_third", "s_fourth")):
        core.capture.observe("A passing mention of a kayaking trip number %d. %s" % (j, DILUTE),
                             "Noted. %s" % DILUTE, session_id=sid,
                             occurred_at="2026-03-1%dT10:00:00Z" % j)
    core.process_pending()
    return core


class TestTheGoldEvidenceInTheSecondSession(unittest.TestCase):
    """The acceptance fixture: gold evidence in the SECOND-best session at a
    tight budget survives packing under the breadth-needing route and does not
    under the factual route."""

    # 1 500 tokens = 6 000 chars, of which this fixture's tier-1 belief block
    # claims ~3 200: the raw fill gets ~2 800 and one of s_dominant's five
    # 2 887-char turns alone overruns it. That is the regime the corpus
    # measurement indicts, reproduced in miniature.
    BUDGET = 1500

    def setUp(self):
        self.core = make_core()

    def test_the_fixture_puts_the_gold_in_the_SECOND_best_session(self):
        """Positive control. A fixture whose gold session already leads is not
        a test of anything this change does."""
        order = []
        for raw in self.core.retrieval.retrieve_raw(BREADTH_Q, limit=20):
            ev = self.core.store.get_event(raw.get("event_id") or "") or {}
            sid = ev.get("session_id")
            if sid and sid not in order:
                order.append(sid)
        self.assertEqual(order[:2], ["s_dominant", "s_answer"], order)

    def test_the_breadth_route_keeps_the_second_session(self):
        ctx = self.core.retrieval.get_context(BREADTH_Q, token_budget=self.BUDGET)
        self.assertEqual(self.core.retrieval.last_context_debug["route"], "aggregation")
        self.assertIn("[SESSION s_answer", ctx)
        self.assertIn(MARKER, block_of(ctx, "s_answer"))

    def test_the_factual_route_does_not(self):
        """Same store, same evidence, a question whose answer is ONE session.
        Depth there is correct for it, and E12 precision packing depends on
        being allowed to concentrate -- so the ceiling must not fire."""
        ctx = self.core.retrieval.get_context(FACTUAL_Q, token_budget=self.BUDGET)
        self.assertEqual(self.core.retrieval.last_context_debug["route"], "factual")
        self.assertIsNone(self.core.retrieval.last_context_debug["breadth_floor"])
        self.assertNotIn("[SESSION s_answer", ctx)

    def test_removing_the_floor_loses_it_again(self):
        """THE MUTATION GUARD. `context.breadth_floor: False` takes the same
        `room = remaining_chars` path a tree without this feature takes, so
        `test_the_breadth_route_keeps_the_second_session` must fail on it --
        verified directly by editing that line out of engine/retrieval.py: one
        failure, exactly that test."""
        off = make_core({"context": {"breadth_floor": False}})
        ctx = off.retrieval.get_context(BREADTH_Q, token_budget=self.BUDGET)
        self.assertEqual(off.retrieval.last_context_debug["route"], "aggregation")
        self.assertIsNone(off.retrieval.last_context_debug["breadth_floor"])
        self.assertNotIn("[SESSION s_answer", ctx)

    def test_one_reserved_session_is_the_pre_change_behaviour(self):
        """N=1 is "reserve room for one session", i.e. no floor at all. It has
        to be byte-identical to the flag being off, or the knob has an off-by-
        one at its own boundary."""
        one = make_core({"context": {"breadth_floor_sessions": 1}})
        off = make_core({"context": {"breadth_floor": False}})
        self.assertEqual(one.retrieval.get_context(BREADTH_Q, token_budget=self.BUDGET),
                         off.retrieval.get_context(BREADTH_Q, token_budget=self.BUDGET))

    def test_the_temporal_route_gets_it_too(self):
        """E9's temporal route orders events ACROSS sessions -- same shape, same
        reservation. (It is in the default `breadth_floor_routes`; see the
        config note on how thin the corpus evidence for it is.)"""
        self.core.retrieval.get_context(TEMPORAL_Q, token_budget=self.BUDGET)
        self.assertEqual(self.core.retrieval.last_context_debug["route"], "temporal")
        self.assertIsNotNone(self.core.retrieval.last_context_debug["breadth_floor"])

    def test_the_route_set_is_configurable(self):
        """Config-gated, not hardcoded: naming no routes is the same as off."""
        none_ = make_core({"context": {"breadth_floor_routes": ["preference"]}})
        ctx = none_.retrieval.get_context(BREADTH_Q, token_budget=self.BUDGET)
        self.assertIsNone(none_.retrieval.last_context_debug["breadth_floor"])
        self.assertNotIn("[SESSION s_answer", ctx)


class TestTheDecisionIsExposed(unittest.TestCase):
    """§E12 "expose the decision in the debug field" -- so an eval can attribute
    a moved instance to the floor rather than to the estimator or the route."""

    def setUp(self):
        self.core = make_core()

    def test_it_reports_route_sessions_share_and_group_count(self):
        self.core.retrieval.get_context(BREADTH_Q, token_budget=1500)
        bf = self.core.retrieval.last_context_debug["breadth_floor"]
        self.assertEqual(bf["route"], "aggregation")
        self.assertEqual(bf["sessions"], 4)   # 4 groups, floor of 5 -> clamped
        self.assertGreaterEqual(bf["groups"], 4)
        self.assertGreater(bf["share_chars"], 0)
        # A SHARE of what the fill had left, not a constant: it must be well
        # under the whole budget, and it must move with the budget.
        dbg = self.core.retrieval.last_context_debug
        self.assertLess(bf["share_chars"], dbg["budget_chars"] // 2)
        self.core.retrieval.get_context(BREADTH_Q, token_budget=4000)
        self.assertGreater(
            self.core.retrieval.last_context_debug["breadth_floor"]["share_chars"],
            bf["share_chars"])

    def test_it_is_none_when_the_floor_does_not_apply(self):
        self.core.retrieval.get_context(FACTUAL_Q, token_budget=1500)
        self.assertIsNone(self.core.retrieval.last_context_debug["breadth_floor"])

    def test_it_is_none_when_everything_grouped_into_one_session(self):
        """A floor of N over 1 group is not a floor. Reserving shares for
        sessions that do not exist is exactly how a breadth floor turns into
        budget that is held back and then wasted."""
        core = ChronicleCore(tempfile.mkdtemp(), {"embeddings": {"model": "hashing"}})
        core.initialize(session_id="eval", principal_id="assistant")
        core.capture.observe("I went on a kayaking trip. %s" % FILLER, "ok",
                             session_id="only")
        core.process_pending()
        core.retrieval.get_context(BREADTH_Q, token_budget=1500)
        self.assertIsNone(core.retrieval.last_context_debug["breadth_floor"])


class TestItDoesNotHoldBudgetBack(unittest.TestCase):
    """"Depth is bought only with what breadth does not need" -- the converse
    also has to hold: breadth must not reserve chars it then fails to spend.

    Two things make that true. The divisor is `N - offered`, recomputed against
    what is ACTUALLY left rather than fixed at `remaining/N`, so a group that
    takes less than its share hands the surplus straight to the next one and
    the Nth group's divisor is 1, i.e. no ceiling at all. And the session-
    window expansion is not rationed, so a store whose only long session is the
    first one still spends the rest of the budget on it once the others have
    had their turn."""

    def test_the_floor_context_still_saturates_its_budget(self):
        """Corpus evidence (scripts/a18_ab.py): mean chars-emitted over char-
        ceiling across all 58 ctx_eval instances is 99.9 / 99.9 / 100.0 % at
        the three tiers WITH the floor, against 99.9 / 97.6 / 94.6 % without
        it, and zero of the 29 covered-route contexts came back more than 200
        chars shorter than its unfloored twin. The floor spends MORE of the
        budget, not less: breadth reaches content that depth in one session had
        already run out of."""
        core = make_core()
        off = make_core({"context": {"breadth_floor": False}})
        for budget in (1200, 1500, 2000, 3000):
            ctx = core.retrieval.get_context(BREADTH_Q, token_budget=budget)
            dbg = core.retrieval.last_context_debug
            self.assertIsNotNone(dbg["breadth_floor"], budget)
            self.assertGreaterEqual(len(ctx), 0.97 * dbg["budget_chars"],
                                    "floor under-spent at %d: %d of %d"
                                    % (budget, len(ctx), dbg["budget_chars"]))
            off_ctx = off.retrieval.get_context(BREADTH_Q, token_budget=budget)
            self.assertGreaterEqual(len(ctx), len(off_ctx) - 100, budget)

    def test_the_one_shape_that_under_spends_is_named_and_bounded(self):
        """Characterization, not an aspiration -- so it cannot get worse quietly.

        A group's ranked excerpts go into `seen_excerpts` when the groups are
        BUILT, not when they are emitted, so an excerpt phase 1 declines to
        emit under its share is one the session-window expansion will not
        re-offer either. That costs nothing on the corpus (the numbers in the
        test above), because a real store always has another session with
        content. It does bite on the shape this fixture is: FOUR sessions, only
        one of them long, and its five near-identical turns already thinned to
        three by the aggregation route's own per-session excerpt cap. At a
        16 000-char budget that store has ~14 700 chars of reachable text under
        the floor and ~16 000 without it.

        Left as-is deliberately rather than fixed by un-seeing those excerpts:
        `retrieve_raw` can hand phase 1 an FTS snippet rather than the payload
        text, so dropping them from `seen_excerpts` would let the expansion
        re-emit a near-duplicate of a turn already in the context -- a worse
        failure than spending 92% of a budget on a store that has no more to
        say."""
        core = make_core()
        off = make_core({"context": {"breadth_floor": False}})
        ctx = core.retrieval.get_context(BREADTH_Q, token_budget=4000)
        off_ctx = off.retrieval.get_context(BREADTH_Q, token_budget=4000)
        cap = core.retrieval.last_context_debug["budget_chars"]
        self.assertLess(len(ctx), len(off_ctx))          # it really does under-spend
        # ...and only ever slightly. (84% since 5.8.12: this fixture's turns
        # open with a request -- "Tell me about kayaking trip 3." -- which an
        # episode no longer includes, so the store simply holds less text.)
        self.assertGreater(len(ctx), 0.80 * cap)

    def test_the_budget_contract_still_holds_exactly(self):
        """A10's invariant: nothing the floor does may push the emitted block
        past the budget, and the final trim must still never have to drop a
        whole unit to make it fit."""
        core = make_core()
        for budget in (300, 600, 900, 1500, 2000, 4000, 12000):
            core.retrieval.get_context(BREADTH_Q, token_budget=budget)
            dbg = core.retrieval.last_context_debug
            self.assertLessEqual(dbg["used_chars"], dbg["budget_chars"], budget)
            self.assertEqual(dbg["dropped_units"], 0, budget)


class TestTheFactualPathIsByteIdentical(unittest.TestCase):
    """THE HARD CONSTRAINT. The corpus-wide proof is a hash comparison over all
    58 ctx_eval instances x 3 budgets (scripts/a18_ab.py; 87 factual/preference
    contexts, 0 differing). This is its in-suite twin: on a store built to make
    the floor fire, every route it does NOT cover must produce the same bytes
    with the feature on as with it off, at every budget."""

    def test_factual_and_preference_contexts_are_unchanged(self):
        on = make_core()
        off = make_core({"context": {"breadth_floor": False}})
        for q in (FACTUAL_Q, "where do I store the kayak",
                  "recommend a kayaking trip for me"):
            for budget in (300, 900, 1500, 4000, 12000):
                a = on.retrieval.get_context(q, token_budget=budget)
                self.assertNotEqual(on.retrieval.last_context_debug["route"],
                                    "aggregation", q)
                b = off.retrieval.get_context(q, token_budget=budget)
                self.assertEqual(a, b, "%r @%d changed" % (q, budget))


# --------------------------------------------------------------------------
# Determinism: the same five-PYTHONHASHSEED subprocess harness every other
# guard in this tree uses (tests/test_precision_packing.py). Imported, not
# reimplemented -- two harnesses that could drift about what "the same" means
# is the failure this one exists to prevent.
# --------------------------------------------------------------------------
BREADTH_SCRIPT = '''
import logging, sys, tempfile
logging.disable(logging.CRITICAL)
sys.path.insert(0, __REPO_ROOT__)
sys.path.insert(0, __REPO_ROOT__ + "/tests")
from test_breadth_floor import make_core, BREADTH_Q
core = make_core()
ctx = core.retrieval.get_context(BREADTH_Q, token_budget=1500)
bf = core.retrieval.last_context_debug["breadth_floor"]
print(repr(sorted((bf or {}).items())))
print(ctx)
'''


class TestTheFloorIsProcessStable(unittest.TestCase):
    """The ceiling is derived from `remaining_chars` and a COUNT of groups, and
    the groups are walked in insertion order -- but `by_sid` is a dict and
    `seen_excerpts` a set, so "stable" is a claim only a cross-process test can
    check (see the A15/F1 harness note)."""

    def test_five_hash_seeds_pack_the_same_breadth_context(self):
        assert_one_answer_across_seeds(self, BREADTH_SCRIPT,
                                       "the A18 breadth-floor context")


if __name__ == "__main__":
    unittest.main()
