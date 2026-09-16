"""
Chronicle — A10b: ONE token estimate, EXPLICIT per-call-site safety margins.

A10 found two chars/token ratios (`get_context` budgeted `token_budget * 4`
while `estimate_tokens` counted chars/3) and unified them onto one. It set that
one ratio to 3, which is not an estimate: measured on both eval corpora the true
ratio is at most 4.63-4.76 chars/token, so chars/3 over-estimates tokens by
>= 1.54x. Every budget in the tree therefore under-delivered by about a third —
a 12 000-token caller received ~36 000 chars where ~48 000 fit — and A10's own
A/B measured the cost at -3.5 points of ctx_eval recall @12k.

It was kept at 3 because the SAME estimator clamps embedding input, where
under-estimating is catastrophic: a real incident (2048-token nomic server,
over-long request, HTTP 500, curation job permanently poisoned). Two purposes
with opposite failure modes were sharing one number.

A10b splits them: `estimate_tokens`/`budget_chars` report the best available
ESTIMATE, and each call site names a documented SafetyMargin sized for its own
failure mode. These tests pin that separation from both directions — every test
here is written to be killed by a specific mutation, named in its docstring.
"""
import ast
import io
import re
import shutil
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from context import ChronicleContextEngine  # noqa: E402
from engine import embeddings as emb  # noqa: E402
from engine.core import ChronicleCore  # noqa: E402
from engine.embeddings import (COMPRESSION_BUDGET, CONTEXT_BUDGET, EMBED_INPUT,  # noqa: E402
                               MARGINS, HashingEmbedder, OpenAICompatEmbedder,
                               SafetyMargin, _CHARS_PER_TOKEN, _cap_chars,
                               budget_chars, estimate_tokens)

ROOT = Path(__file__).parent.parent
ESTIMATOR_FUNCS = ("estimate_tokens", "budget_chars")

# The margin each production module is allowed to use. Changing a site's
# failure-mode story means changing this table, on purpose, in a review.
EXPECTED_SITES = {
    "engine/embeddings.py": {"EMBED_INPUT"},
    "engine/retrieval.py": {"CONTEXT_BUDGET"},
    "context.py": {"COMPRESSION_BUDGET"},
}


def production_files():
    """Every shipped .py file: excludes tests/ and any dot-directory (work-tree
    note dirs such as .a10logs/ hold stale COPIES of engine sources)."""
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if rel.parts[0] in ("tests", "__pycache__"):
            continue
        out.append((str(rel), p))
    return out


def code_lines(path):
    """`path`'s lines with comments and string literals removed, so prose that
    DESCRIBES the old ratios can never pass or fail a code scan."""
    src = path.read_text()
    lines = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                        tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            continue
        lines.setdefault(tok.start[0], []).append(tok.string)
    return {n: " ".join(t) for n, t in lines.items()}


class TestExactlyOneEstimate(unittest.TestCase):
    """THE grep, as a test."""

    def test_only_one_chars_per_token_constant_exists_in_the_tree(self):
        """No module may keep a chars/token number of its own — not even one
        that currently agrees with the shared one.

        Killed by restoring context.py's `_FALLBACK_CHARS_PER_TOKEN = 3`, which
        is how A10 shipped it: a second constant that agreed on the day it was
        written and went stale the moment the real one was restated.
        """
        found = []
        for rel, path in production_files():
            for node in ast.walk(ast.parse(path.read_text())):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    targets = [node.target.id]
                for name in targets:
                    if re.search(r"chars?_?per_?token|token_?chars", name, re.I):
                        found.append("%s:%d: %s" % (rel, node.lineno, name))
        self.assertEqual(found, ["engine/embeddings.py:%d: _CHARS_PER_TOKEN" % _const_lineno()],
                         "chars/token constants outside the one estimator:\n" + "\n".join(found))

    def test_no_call_site_rolls_its_own_ratio(self):
        """No budget arithmetic anywhere carries a hand-written ratio.

        Killed by restoring `max_chars = token_budget * 4`, `max_chars // 4`,
        `content[:remaining * 3]` or any other local conversion — each of which
        was locally reasonable, which is exactly why nothing ever compared them.
        """
        pattern = re.compile(
            r"(?:token_)?budget\w*\s*[*]\s*[34]\b"
            r"|remaining\s*[*]\s*[34]\b"
            r"|max_chars\s*(?://|/)\s*[34]\b"
            r"|len\([^)]*\)\s*(?://|/)\s*[34](?:\.0)?\b"
            r"|tokens?\s*[*]\s*[34]\b")
        offenders = []
        for rel, path in production_files():
            for n, code in code_lines(path).items():
                if pattern.search(code):
                    offenders.append("%s:%d: %s" % (rel, n, code))
        self.assertEqual(offenders, [], "a second chars/token ratio survives:\n"
                         + "\n".join(offenders))

    def test_the_estimate_is_the_measured_one_and_is_an_integer(self):
        """chars/4: the largest integer strictly below the measured upper bound
        on true chars/token (4.63 oracle / 4.76 s_sample100, chars-per-atom).

        Integer, so estimate and inverse stay exact in integer arithmetic.
        Killed by returning to 3 (which over-estimates tokens by >= 1.54x and
        under-delivers every budget by a third) or by going to 5 (which exceeds
        the measured bound and would over-deliver).
        """
        self.assertIsInstance(_CHARS_PER_TOKEN, int)
        self.assertEqual(_CHARS_PER_TOKEN, 4)
        self.assertEqual(estimate_tokens("x" * 4000), 1000)
        self.assertEqual(estimate_tokens("x" * 4001), 1001)  # ceiling, never floor
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)

    def test_budget_chars_is_the_exact_inverse_under_every_margin(self):
        """`len(t) <= budget_chars(n, m)` iff `estimate_tokens(t, m) <= n`, for
        every registered margin, checked at the boundary in both directions.

        Killed by making a margin a float multiplier (rounding drift reopens
        exactly the off-by-one gap the two-estimator bug lived in).
        """
        for m in (None,) + tuple(MARGINS):
            for n in (0, 1, 2, 3, 7, 100, 1499, 1500, 4000, 12000):
                cap = budget_chars(n, margin=m)
                self.assertLessEqual(estimate_tokens("x" * cap, margin=m), n)
                if cap:
                    self.assertGreater(estimate_tokens("x" * (cap + 1), margin=m), n)
            self.assertEqual(budget_chars(-5, margin=m), 0)
            self.assertEqual(budget_chars("nonsense", margin=m), 0)


def _const_lineno():
    for n, code in code_lines(ROOT / "engine/embeddings.py").items():
        if code.startswith("_CHARS_PER_TOKEN ="):
            return n
    raise AssertionError("the one estimator constant is gone")


class TestMarginRegistry(unittest.TestCase):

    def test_every_margin_is_named_documented_and_at_least_one(self):
        """A margin below 1 would make a cap UNDER-count — the one thing no
        call site can want. A margin with no `why` is an anonymous fudge
        factor, which is what this whole task exists to remove."""
        self.assertEqual(len(MARGINS), len({m.name for m in MARGINS}))
        for m in MARGINS:
            self.assertIsInstance(m, SafetyMargin)
            self.assertIs(getattr(emb, m.name), m, "margin %r is not exported under its own name" % m.name)
            self.assertGreaterEqual(m.num, m.den, "%s is below 1: it would under-count" % m.name)
            self.assertGreaterEqual(m.den, 1)
            self.assertGreater(len(m.why), 120, "%s has no real justification" % m.name)

    def test_embed_input_margin_is_the_incident_tested_ratio(self):
        """The embedding clamp keeps its conservative margin, and keeps the
        EXACT ceiling that has held since the incident: 4/3 of chars/4 is
        chars/3, byte for byte, in both directions.

        Killed by removing the margin at the clamp (see the behavioural test
        below) or by "simplifying" 4/3 to 1 — either silently lets a request
        that used to be split reach a 2048-token server whole, which is the
        HTTP 500 that poisoned a curation job.
        """
        self.assertEqual((EMBED_INPUT.num, EMBED_INPUT.den), (4, 3))
        for length in range(0, 5000):
            self.assertEqual(estimate_tokens("x" * length, margin=EMBED_INPUT),
                             -(-length // 3), "length=%d" % length)
        for n in range(0, 5000):
            self.assertEqual(budget_chars(n, margin=EMBED_INPUT), 3 * n)
        self.assertEqual(_cap_chars(2048), 6144)   # the incident's server, unchanged
        self.assertEqual(_cap_chars(1), 3)         # floor: one token's worth, not ""

    def test_budget_margins_add_no_hidden_headroom(self):
        """Budget accounting uses the ESTIMATE. Headroom at these sites is
        stated in the open elsewhere (the caller's own N; the low watermark),
        so charging a second, invisible one here is double-counting — and it
        is precisely how A10 lost a third of every context budget.

        Killed by giving either budget margin the conservative ratio: this is
        the "using the conservative margin for context budget fails" direction,
        stated as an arithmetic fact rather than an outcome.
        """
        for m in (CONTEXT_BUDGET, COMPRESSION_BUDGET):
            self.assertEqual((m.num, m.den), (1, 1), "%s must be the bare estimate" % m.name)
            self.assertEqual(budget_chars(12000, margin=m), 48000)
        # 12k tokens: 48 000 chars under the estimate vs 36 000 under chars/3 —
        # the ~a-third-of-every-budget this task is about.
        self.assertEqual(budget_chars(12000, margin=EMBED_INPUT), 36000)

    def test_compression_margin_is_never_looser_than_the_context_margin(self):
        """A coupling the code cannot express locally: compress() asks
        `get_context` for N tokens (converted under CONTEXT_BUDGET) and then
        charges the answer against its own budget under COMPRESSION_BUDGET. If
        compression were ever the STRICTER of the two, a span that get_context
        sized to fit would be charged as over-budget and dropped whole by
        `_rehydrate_working_set`'s guard — rehydration would quietly stop
        delivering, with every test still green.
        """
        self.assertLessEqual(COMPRESSION_BUDGET.num * CONTEXT_BUDGET.den,
                             CONTEXT_BUDGET.num * COMPRESSION_BUDGET.den)


class TestEveryConsumerNamesItsMargin(unittest.TestCase):
    """The requirement that no call site may silently use a different number."""

    @staticmethod
    def _calls(path):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in ESTIMATOR_FUNCS:
                yield node

    def test_every_production_call_names_a_registered_margin(self):
        """Killed by dropping `margin=` at any call site, or by passing an
        inline/ad-hoc margin instead of one from the registry — a margin that
        is not in MARGINS is not documented and not reviewable.
        """
        names = {m.name for m in MARGINS}
        offenders = []
        for rel, path in production_files():
            for call in self._calls(path):
                kw = [k for k in call.keywords if k.arg == "margin"]
                if not kw:
                    offenders.append("%s:%d: %s() with no margin" % (rel, call.lineno, call.func.id))
                    continue
                val = kw[0].value
                ident = val.id if isinstance(val, ast.Name) else (
                    val.attr if isinstance(val, ast.Attribute) else None)
                if ident not in names:
                    offenders.append("%s:%d: margin is not a registered one (%r)"
                                     % (rel, call.lineno, ast.dump(val)[:60]))
        self.assertEqual(offenders, [], "unnamed or ad-hoc margins:\n" + "\n".join(offenders))

    def test_the_estimator_is_never_passed_around_as_a_value(self):
        """A bare reference (`f = estimate_tokens`, `partial(estimate_tokens)`)
        would move the margin decision somewhere this scan cannot see it."""
        offenders = []
        for rel, path in production_files():
            if rel == "engine/embeddings.py":
                continue  # where they are defined
            tree = ast.parse(path.read_text())
            called = {id(n.func) for n in ast.walk(tree)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                      and n.func.id in ESTIMATOR_FUNCS}
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in ESTIMATOR_FUNCS \
                        and isinstance(node.ctx, ast.Load) and id(node) not in called:
                    offenders.append("%s:%d: bare reference to %s" % (rel, node.lineno, node.id))
        self.assertEqual(offenders, [], "estimator used as a value:\n" + "\n".join(offenders))

    def test_each_module_uses_only_the_margin_its_failure_mode_calls_for(self):
        """The per-site table, as a test: the embed clamp is conservative, the
        two budget sites are not, and nothing else converts tokens at all.

        Killed in BOTH directions the acceptance asks for: give the embed clamp
        CONTEXT_BUDGET, or give retrieval/compression EMBED_INPUT, and the site
        table no longer matches.
        """
        actual = {}
        for rel, path in production_files():
            for call in self._calls(path):
                for k in call.keywords:
                    if k.arg == "margin" and isinstance(k.value, ast.Name):
                        actual.setdefault(rel, set()).add(k.value.id)
        self.assertEqual(actual, EXPECTED_SITES)


class TestEmbedClampKeepsItsMargin(unittest.TestCase):
    """The incident site: behaviour, not just arithmetic.

    Fixture shape for every test here: `max_input_tokens=256` (the clamp floor)
    and a 1000-char text. 1000 chars is 250 tokens by the ESTIMATE — inside the
    cap — and 334 under the margin, i.e. over it. So a clamp that forgot its
    margin would send all 1000 chars to a 256-token model, and one that keeps it
    sends at most 768. The gap between those two numbers is the whole incident.
    """

    CAP = 256
    TEXT = "word " * 200  # 1000 chars

    def test_the_fixture_really_straddles_the_margin(self):
        self.assertEqual(len(self.TEXT), 1000)
        self.assertLessEqual(estimate_tokens(self.TEXT), self.CAP)
        self.assertGreater(estimate_tokens(self.TEXT, margin=EMBED_INPUT), self.CAP)

    def test_hashing_embedder_clamps_under_the_margin(self):
        """Killed by `margin=CONTEXT_BUDGET` (or no margin) at HashingEmbedder.embed."""
        e = HashingEmbedder(dimensions=8, max_input_tokens=self.CAP)
        seen = []
        e._embed_one = lambda t, _o=e._embed_one: (seen.append(t), _o(t))[1]
        e.embed(self.TEXT)
        self.assertTrue(seen)
        for chunk in seen:
            self.assertLessEqual(len(chunk), budget_chars(self.CAP, margin=EMBED_INPUT))

    def test_openai_compat_embedder_clamps_under_the_margin(self):
        """Same clamp on the path that actually reaches a model. Killed by the
        same mutation at OpenAICompatEmbedder.embed — which is the exact line
        whose absence returned HTTP 500 and poisoned the curation job."""
        for overflow in ("truncate", "chunk_mean"):
            e = OpenAICompatEmbedder("http://127.0.0.1:9/v1", "fake-model", 8,
                                     max_input_tokens=self.CAP, overflow=overflow)
            seen = []
            e._embed_raw = lambda t, timeout=None: (seen.append(t), [0.1] * 8)[1]
            e.embed(self.TEXT)
            self.assertTrue(seen, "nothing was sent (overflow=%s)" % overflow)
            for payload in seen:
                self.assertLessEqual(len(payload), budget_chars(self.CAP, margin=EMBED_INPUT),
                                     "overflow=%s sent %d chars to a %d-token model"
                                     % (overflow, len(payload), self.CAP))

    def test_batch_path_never_mixes_an_oversized_text_into_a_request(self):
        """Killed by `margin=CONTEXT_BUDGET` at the embed_batch size check: the
        oversized text would ride into a raw batch payload and 500 the whole
        batch instead of being routed through its own clamped call."""
        e = OpenAICompatEmbedder("http://127.0.0.1:9/v1", "fake-model", 8,
                                 max_input_tokens=self.CAP)
        batched, single = [], []
        e._embed_raw_batch = lambda texts, timeout=None: (batched.extend(texts),
                                                          [[0.1] * 8 for _ in texts])[1]
        e._embed_raw = lambda t, timeout=None: (single.append(t), [0.1] * 8)[1]
        e.embed_batch(["short text", self.TEXT, "another short one"])
        self.assertNotIn(self.TEXT, batched, "oversized text went into a batch request whole")
        for payload in batched + single:
            self.assertLessEqual(len(payload), budget_chars(self.CAP, margin=EMBED_INPUT))

    def test_chunking_covers_the_whole_input_losslessly(self):
        """The margin decides the cap; `_split_for_cap` must still be lossless
        at that cap, or a conservative clamp would silently drop content."""
        chunks = emb._split_for_cap(self.TEXT, self.CAP)
        self.assertEqual("".join(chunks), self.TEXT)
        for c in chunks:
            self.assertLessEqual(len(c), _cap_chars(self.CAP))


LONG = ("The quarterly maintenance report for the Springfield branch noted "
        "that the heating loop was rebalanced, the filters were replaced on "
        "schedule, and the night crew logged no faults of any kind during the "
        "entire reporting period, which is unusual for that time of year.")
# A15b: two more sentences of the same report, so one turn runs ~580 chars
# rather than ~270. Not padding — see `TestContextBudgetGetsTheWholeEstimate`'s
# "WHY THE TURNS ARE THIS LONG": at ~270 chars the 20-candidate raw pool ran
# OUT before a 16 000-char budget did, and the delivered byte count was then
# decided by which sessions the tie-break happened to reach.
DETAIL = ("The branch logbook for the same period records the boiler pressure "
          "checks, the weekly fire-door inspection, the lift service visit, and "
          "the two deliveries that arrived outside the booked window. "
          "None of those items required an escalation to the regional office, "
          "and the duty roster was posted on the usual Thursday.")
QUERY = "what did the Springfield maintenance report say about the heating loop"


class TestContextBudgetGetsTheWholeEstimate(unittest.TestCase):
    """The under-delivery this task exists to fix, stated as a test.

    The store is deliberately a NON-CONVERGING one (the same claim spread over
    25 sessions): on a store where retrieval converges, E12 precision packing
    cuts the budget to its own smaller one and the assembly never approaches
    the caller's budget at all, so a version of this test written against that
    store would pass with the margin restored — it would simply never fill up.

    A15b — THE FLAKE, AND WHAT IT WAS NOT. This class's saturation test failed
    about one run in twelve, and the failure was reported as PYTHONHASHSEED-
    dependent because conftest pins the seed for child processes only. It is
    not the seed. Measured three ways:

      * ONE store, queried in 8 separate interpreters under 8 seeds, 12
        contexts each (4 budgets x 3 queries) -> one sha256. The read path
        does not see hash order.
      * the fixture built with the CLOCK FROZEN, under the five seeds
        `test_precision_packing.HASH_SEEDS` uses -> ONE store dump, byte for
        byte (403 617 bytes each). The write path does not see it either.
      * the fixture built 40 times at ONE FIXED seed -> five distinct answers
        at token_budget=4 000: 11 703, 11 706, 12 863, 12 866, 14 023 chars.
        7 of the 40 sit below the 12 000-char floor the saturation test
        asserts. Same seed, same code, different bytes.

    So the moving input was the WALL CLOCK. 75 turns that differ only in a site
    number left most of the ranked pool exactly score-tied — 11 of the top 20,
    in two tie groups of 8 and 3, at the turn length the fixture had then;
    `retrieve_raw` breaks those ties on `event_id` (`_rank_key`, A15), and
    `event_id` is a content hash that INCLUDES `occurred_at`
    (serialize.event_id, §5.3). Left to `observe()`, that is a millisecond
    wall-clock reading, so every build drew a fresh permutation of the tied
    bucket, a different cut at `limit=20`, and a different set of sessions with
    turns left over for the session-window expansion to spend budget on.

    THE CLOCK IS PINNED (`_stamp`) for that reason — same technique and same
    reason as `test_precision_packing.FREEZE_PREAMBLE` ("the wall clock —
    occurred_at feeds event_id feeds belief_id"), and
    `test_the_fixture_is_clock_pinned_so_two_builds_agree` is its guard.

    WHY THE TURNS ARE THIS LONG (`LONG` + `DETAIL`, ~580 chars). Pinning the
    clock alone makes the answer repeatable without making it MEAN anything:
    it freezes one draw out of the same distribution. Measured over eight
    plausible pinned stamp schemes (one per minute / second / hour / day,
    session-per-day, reversed, and the one in `_stamp`) with ~270-char turns,
    the delivered byte count still ranged 11 706 - 14 023 and ONE of the eight
    landed under the 12 000 floor. The reason is that at that turn length the
    caller's budget was never the binding constraint: `retrieve_raw` returns 20
    candidates, 20 x ~370 chars is ~7.5k, and everything else reachable is the
    belief block plus whatever turns the session-window expansion finds in the
    sessions those 20 came from — a whole reachable set of 11.7-14.0k against a
    16 000-char budget that therefore never filled. So what the assertion
    measured was how many sessions the tie order happened to leave leftovers
    in, which is not this file's subject.

    At ~580 chars a turn the same 20 candidates carry 13 755 chars, the
    expansion tops the fill up to 15 094 of the 16 000 (the 906 left over are
    one whole excerpt that does not fit — the packer appends whole units,
    §18.5), and the pool comes back with TWENTY DISTINCT SCORES: there is no
    tie left for an id to break, so the delivered count is a function of the
    text and nothing else. Six stamp schemes, six different sets of event ids,
    one byte count — `test_the_delivered_bytes_do_not_depend_on_the_event_ids`
    is that check, standing. The tie-break's own cross-process guard lives
    where a tied pool still exists —
    `test_precision_packing.py::test_the_packed_context_is_byte_identical_across_hash_seeds`.
    """

    SPREAD = ("in the mornings", "on weekends", "as the duty lead",
              "part time since April", "out of the downtown branch",
              "when the crew is short handed", "on the late shift",
              "since the refit", "under the new rota", "with the relief team")
    Q = "who manages the Springfield branch"
    # 25 sessions x 3 turns of ~580 chars: enough evidence to overflow a 4 000-
    # token budget (16 000 chars) THROUGH A 20-CANDIDATE POOL (see "WHY THE
    # TURNS ARE THIS LONG"), spread thinly enough that no single session takes
    # the 60% of the top-5 raw candidates E12's concentration gate needs.
    # Piling more turns into fewer sessions DOES converge, and then precision
    # packing caps the budget at its own and this test measures nothing.
    SESSIONS, TURNS = 25, 3

    @staticmethod
    def _stamp(n):
        """The nth turn's `occurred_at` — fixed, distinct, and ascending, so
        the store keeps a real chronology and only the wall clock is gone."""
        return "2026-01-%02dT%02d:%02d:00.000Z" % (1 + n // 288, (n // 12) % 24, (n % 12) * 5)

    @classmethod
    def build(cls, home):
        """The fixture store, as a function of `home` alone."""
        core = ChronicleCore(home, {"embeddings": {"model": "hashing"}})
        core.initialize("s1", principal_id="assistant")
        n = 0
        for i in range(cls.SESSIONS):
            tail = "%s (site %d)" % (cls.SPREAD[i % len(cls.SPREAD)], i)
            for j in range(cls.TURNS):
                core.capture.observe(
                    "%s %s Pat Testley manages the Springfield branch %s (note %d)"
                    % (LONG, DETAIL, tail, j),
                    "Noted.", session_id="sp_%02d" % i, occurred_at=cls._stamp(n))
                n += 1
        core.process_pending()
        return core

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(dir=str(ROOT / "tests"))
        cls.core = cls.build(cls.home)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def test_the_enforced_char_budget_is_the_full_estimate(self):
        """Whatever budget `get_context` settles on — the caller's, or a
        packing budget below it — the chars it enforces are that budget under
        NO margin.

        Killed by `margin=EMBED_INPUT` in get_context: every enforced budget
        drops to 3N chars, which is A10's behaviour and the defect.
        """
        for hint in (self.Q, "what did the Springfield maintenance report say",
                     "recommend a branch routine I would like"):
            for budget in (400, 1500, 4000, 12000):
                self.core.retrieval.get_context(hint, token_budget=budget)
                dbg = self.core.retrieval.last_context_debug
                self.assertEqual(dbg["budget_chars"],
                                 budget_chars(dbg["token_budget"], margin=CONTEXT_BUDGET))
                self.assertEqual(dbg["budget_chars"], 4 * dbg["token_budget"])
                self.assertLessEqual(dbg["token_budget"], budget)

    def test_a_saturating_caller_actually_receives_the_extra_third(self):
        """End-to-end, with more evidence in the store than the budget holds:
        the bytes delivered exceed everything the conservative margin would
        have allowed. The arithmetic test above can be satisfied while assembly
        still stops early; this one cannot.
        """
        for budget in (1500, 4000):
            ctx = self.core.retrieval.get_context(self.Q, token_budget=budget)
            dbg = self.core.retrieval.last_context_debug
            self.assertFalse(dbg["precision"] or dbg["pref_pack"],
                             "fixture converged; the caller's budget was never the binding one")
            self.assertGreater(
                len(ctx), budget_chars(budget, margin=EMBED_INPUT),
                "budget=%d delivered %d chars — no more than chars/3 would have"
                % (budget, len(ctx)))
            # …and still never more than the caller asked for (A10's invariant).
            self.assertLessEqual(len(ctx), budget_chars(budget, margin=CONTEXT_BUDGET))
            self.assertLessEqual(estimate_tokens(ctx, margin=CONTEXT_BUDGET), budget)


    def test_the_fixture_is_clock_pinned_so_two_builds_agree(self):
        """Build the SAME fixture a second time and require the same store.

        Killed by dropping `occurred_at=` from `build()`: `capture.observe`
        then stamps `now_iso()` at millisecond resolution, 75 turns take longer
        than a millisecond, so the second build gets different stamps and
        different content hashes (serialize.event_id §5.3 hashes
        `occurred_at`).

        Asserted on ids AND on the delivered context: the ids are the
        mechanism and the context is what the sibling tests measure.
        """
        other = tempfile.mkdtemp(dir=str(ROOT / "tests"))
        try:
            twin = self.build(other)
            mine = [r["event_id"] for r in self.core.retrieval.retrieve_raw(self.Q, limit=20)]
            theirs = [r["event_id"] for r in twin.retrieval.retrieve_raw(self.Q, limit=20)]
            self.assertEqual(mine, theirs,
                             "two builds of one fixture ranked differently — the "
                             "store's event ids are a function of the wall clock")
            for budget in (1500, 4000):
                self.assertEqual(self.core.retrieval.get_context(self.Q, token_budget=budget),
                                 twin.retrieval.get_context(self.Q, token_budget=budget),
                                 "two builds of one fixture packed differently")
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_the_delivered_bytes_do_not_depend_on_the_event_ids(self):
        """The stronger property, and the one the saturation test rests on:
        rebuild the fixture on a DIFFERENT pinned chronology and the same
        number of bytes comes out.

        Different stamps mean different content hashes (§5.3) mean a different
        `_rank_key` tie order over the same pool — so this varies the ordering
        input directly, which pinning the clock only freezes.

        Killed by shortening a turn back to `LONG` alone (drop `DETAIL` from
        `build`): the 20-candidate pool then runs out before a 16 000-char
        budget does, the byte count goes back to being decided by which
        sessions the tie order left leftovers in, and these two chronologies
        deliver 12 866 and 12 863 (verified — that is the failure this test
        prints). Three bytes is enough to fail it, and it is the same mechanism
        that puts a whole 1 160-byte session in or out: see this class's
        docstring for the eight-scheme sweep, one of whose schemes lands under
        the 12 000-char floor
        `test_a_saturating_caller_actually_receives_the_extra_third` asserts.
        """
        original = self.__class__._stamp
        other = tempfile.mkdtemp(dir=str(ROOT / "tests"))
        try:
            # One turn per DAY, against `_stamp`'s five-minute grid: the same
            # 75 turns in the same order, on a chronology that shares no
            # timestamp with the fixture's.
            self.__class__._stamp = staticmethod(
                lambda n: "2026-%02d-%02dT00:00:00.000Z" % (1 + n // 28, 1 + n % 28))
            twin = self.build(other)
            self.assertNotEqual(
                [r["event_id"] for r in self.core.retrieval.retrieve_raw(self.Q, limit=20)],
                [r["event_id"] for r in twin.retrieval.retrieve_raw(self.Q, limit=20)],
                "the two chronologies produced the same ids; this guard varies nothing")
            for budget in (1500, 4000):
                self.assertEqual(
                    len(self.core.retrieval.get_context(self.Q, token_budget=budget)),
                    len(twin.retrieval.get_context(self.Q, token_budget=budget)),
                    "budget=%d delivered a different number of bytes on a store "
                    "that differs only in its timestamps — the packed size "
                    "depends on the tie-break again" % budget)
        finally:
            self.__class__._stamp = original
            shutil.rmtree(other, ignore_errors=True)

    def test_the_final_trim_is_still_wired_up(self):
        """`_emit` — the ONE exit from get_context — must actually apply the
        whole-unit trim to whatever it is handed.

        Found by mutation testing this change: because every section now checks
        the budget BEFORE appending, `_fit_units` is inert on every real path
        (`dropped_units == 0` always), so deleting the call to it at `_emit`
        passed the entire suite. A10 tests `_fit_units` itself and tests that
        real contexts fit; neither notices if the backstop stops being called.
        This drives `_emit` directly, which is the only way to observe it.
        """
        over = "\n".join("[FACT] line %d: %s" % (i, "x" * 40) for i in range(10))
        text = self.core.retrieval._emit(over, 120, 30)
        self.assertLessEqual(len(text), 120)
        self.assertGreater(self.core.retrieval.last_context_debug["dropped_units"], 0)
        self.assertLessEqual(estimate_tokens(text, margin=CONTEXT_BUDGET), 30)


class TestCompressionBudgetGetsTheWholeEstimate(unittest.TestCase):

    def test_a_span_worth_exactly_the_budget_is_kept_whole(self):
        """`_fit_within_budget` charges spans at the estimate, so a span of
        exactly `budget_chars(B)` chars fits untouched.

        Killed by `margin=EMBED_INPUT` in context.py: the same span is charged
        4/3 of its cost and gets clipped to three quarters of itself — the
        compression-side form of the same under-delivery.
        """
        budget = 100
        content = "x" * budget_chars(budget, margin=COMPRESSION_BUDGET)
        kept, used, dropped = ChronicleContextEngine._fit_within_budget(
            [(0, {"role": "user", "content": content})], budget)
        self.assertEqual(dropped, [])
        self.assertEqual(kept[0][1]["content"], content, "a span that fits was clipped anyway")
        self.assertEqual(used, budget)

    def test_a_window_worth_exactly_the_budget_survives_compression(self):
        """The same, end to end: nothing is evicted from a window that fits."""
        home = tempfile.mkdtemp(dir=str(ROOT / "tests"))
        try:
            cfg = {"embeddings": {"model": "hashing"},
                   "context": {"default_token_budget": 400}}
            eng = ChronicleContextEngine()
            eng.on_session_start("m1", hermes_home=home, principal_id="pat", config=cfg)
            self.assertIsNotNone(eng.core)
            per = budget_chars(400, margin=COMPRESSION_BUDGET) // 20
            body = [{"role": "user" if i % 2 == 0 else "assistant",
                     "content": ("filler span %02d " % i).ljust(per, "z")} for i in range(20)]
            out = eng.compress([dict(m) for m in body])
            self.assertEqual([m.get("content") for m in out], [m["content"] for m in body],
                             "a window that fits the budget exactly was compressed anyway")
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
