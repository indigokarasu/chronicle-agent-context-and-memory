"""
Chronicle — A10 (one token estimator, whole-unit final trim) and A16 (drafts
are marked in emitted context).

A10. The tree carried TWO chars/token ratios: `get_context` budgeted
`token_budget * 4` while `estimate_tokens` — and therefore every consumer of
get_context's output, every checkpoint-digest cap and every budget test —
counted chars/3. `get_context(1500)` returned up to 6 000 chars, i.e. 2 000
tokens by the only estimator anything else used, and `last_context_debug`
reported the budget through a THIRD expression (`max_chars // 4`). On top of
that the Tier-1 belief block was explicitly unbudgeted and the final trim was
`ctx[:max_chars]` — a blind slice through whichever fact or excerpt straddled
the boundary, announced as the bare word "(truncated)".

A16. `_readable` admits `status in ("active", "draft", None)` and the
structured channel selects drafts by name, so the losing side of a
`flag_for_review` contradiction, a high-risk norm parked for review, and a
user-domain derived inference all reached search()/answer()/Tier-1 context
rendered as a plain `[FACT]`/`[NOTE]` — indistinguishable from confirmed
truth.

Every test here is written to be KILLED by reverting one specific line, and
says which in its docstring. Runs entirely under the offline hashing embedder.
"""
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
from engine.core import ChronicleCore  # noqa: E402
from engine.embeddings import _CHARS_PER_TOKEN, budget_chars, estimate_tokens  # noqa: E402
from engine.retrieval import _DRAFT_TAG, _OVER_BUDGET_NOTE, _fit_units  # noqa: E402

ROOT = Path(__file__).parent.parent

# -- fixtures ---------------------------------------------------------------
LONG = ("The quarterly maintenance report for the Springfield branch noted "
        "that the heating loop was rebalanced, the filters were replaced on "
        "schedule, and the night crew logged no faults of any kind during the "
        "entire reporting period, which is unusual for that time of year.")
QUERY = "what did the Springfield maintenance report say about the heating loop"


def make_core(cfg_overrides=None):
    home = tempfile.mkdtemp(dir=str(ROOT / "tests"))
    cfg = {"embeddings": {"model": "hashing"}}
    for k, v in (cfg_overrides or {}).items():
        cfg[k] = v
    core = ChronicleCore(home, cfg)
    core.initialize("s1", principal_id="assistant")
    return core, home


def seed_wide(core):
    """Several sessions of prose plus enough facts to fill a Tier-1 block —
    a store big enough that a small budget genuinely has to leave things out."""
    for s in range(4):
        for i in range(6):
            core.capture.observe("%s (session %d turn %d)" % (LONG, s, i),
                                 "Understood, logged for session %d." % s,
                                 session_id="s_%d" % s)
    core.capture.observe("My name is Pat Testley and I manage the Springfield branch",
                         "Noted.", session_id="s_0")
    core.capture.observe("The heating loop at Springfield was rebalanced in March",
                         "Noted.", session_id="s_0")
    core.process_pending()


SPREAD_TAILS = ("in the mornings", "on weekends", "as the duty lead",
                "part time since April", "out of the downtown branch",
                "when the crew is short handed", "on the late shift")
SPREAD_Q = "who manages the Springfield branch"
PREF_Q = "recommend a branch routine I would like"


def seed_spread(core):
    """The same claim in SEVEN sessions, so retrieval converges on none of
    them and E12 precision packing must refuse.

    Needed because the A16 marker lives on the Tier-1 belief render, and
    precision/preference packing SKIP that block by design — on the `seed_wide`
    store the factual query converges and takes the packing path, which emits
    raw transcript turns and no beliefs at all. This is the store where the
    evidence-forward arm actually runs.
    """
    for i, tail in enumerate(SPREAD_TAILS):
        core.capture.observe(
            "Pat Testley manages the Springfield branch %s and the maintenance "
            "rota there is posted every Monday" % tail,
            "Noted.", session_id="sp_%d" % i)
    core.process_pending()


def draft_all_beliefs(core):
    """Flip every extracted belief to `draft`. Returns their values.

    Flipping rather than synthesising: these are rows a real store produces
    (reducer's flag_for_review loser, curation's high-risk norm, derivation's
    user-domain inference all write exactly this status), and going through
    the store keeps the vector — `draft` is not in `_INACTIVE_STATUSES`, so
    the row stays retrievable on every channel, which is the whole premise of
    A16."""
    values = []
    for table in ("facts", "episodes", "notes"):
        for row in core.store.query_beliefs(table, "status='active'", (), 200):
            core.store.update_belief(table, row["belief_id"], status="draft")
            v = row.get("value") or row.get("body") or row.get("summary") or row.get("title")
            if v:
                values.append(v)
    return values


# ===========================================================================
# A10 — one estimator
# ===========================================================================
class TestSingleEstimator(unittest.TestCase):

    def test_no_second_chars_per_token_constant_survives(self):
        """THE grep, as a test: no budget arithmetic anywhere carries a
        chars/token ratio of its own.

        Scans CODE only -- comments and strings are stripped with `tokenize`,
        so the prose that explains the old defect cannot pass or fail this.
        Killed by restoring `max_chars = token_budget * 4`, `max_chars // 4`,
        `content[:remaining * 3]` or any other hand-written ratio, which is
        exactly how the two estimators diverged: each site was locally
        reasonable and nothing ever compared them.
        """
        pattern = re.compile(
            r"(?:token_)?budget\w*\s*[*]\s*[34]\b"           # budget * 3 / * 4
            r"|remaining\s*[*]\s*[34]\b"                      # remaining * 3
            r"|max_chars\s*(?://|/)\s*[34]\b"                 # max_chars // 4
            r"|len\([^)]*\)\s*//\s*[34]\b")                 # a rolled-own chars/N
        offenders = []
        for rel in ("engine/retrieval.py", "context.py", "engine/embeddings.py",
                    "provider.py", "engine/curation.py", "engine/reducer.py",
                    "engine/core.py", "scripts/ctx_eval.py"):
            src = (ROOT / rel).read_text()
            lines = {}
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL,
                                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                    continue
                lines.setdefault(tok.start[0], []).append(tok.string)
            for n, toks in lines.items():
                code = " ".join(toks)
                if pattern.search(code):
                    offenders.append("%s:%d: %s" % (rel, n, code))
        self.assertEqual(offenders, [], "second chars/token constant survives:\n"
                         + "\n".join(offenders))

    def test_budget_chars_is_the_exact_inverse_of_estimate_tokens(self):
        """`len(t) <= budget_chars(n)` iff `estimate_tokens(t) <= n`.

        Killed by changing either constant without the other — the failure
        mode A10 is about. Checked at the boundary in both directions rather
        than on a sample, because off-by-one is precisely where a ceiling
        division and a multiplication drift apart.
        """
        for n in (0, 1, 2, 3, 7, 100, 1499, 1500, 4000, 12000):
            cap = budget_chars(n)
            self.assertEqual(cap, n * _CHARS_PER_TOKEN)
            self.assertLessEqual(estimate_tokens("x" * cap), n)
            if cap:
                self.assertGreater(estimate_tokens("x" * (cap + 1)), n)
        self.assertEqual(budget_chars(-5), 0)
        self.assertEqual(budget_chars("nonsense"), 0)


# ===========================================================================
# A10 — the emitted block fits the stated budget
# ===========================================================================
class TestOutputFitsTokenBudget(unittest.TestCase):

    def setUp(self):
        self.core, self.home = make_core()
        seed_wide(self.core)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    BUDGETS = (40, 120, 400, 1500, 4000, 12000)
    HINTS = (QUERY,
             "who manages the Springfield branch",
             "how many maintenance reports mention the night crew",   # aggregation
             "when was the heating loop rebalanced",                  # temporal
             "recommend something I would like about maintenance")    # preference

    def test_emitted_length_never_exceeds_the_stated_budget(self):
        """A spread of budgets x a spread of query routes (so every packing
        path is exercised): the bytes handed back always estimate at or under
        what the caller asked for.

        Killed by `max_chars = token_budget * 4` (the pre-A10 line): at a 40-
        or 120-token budget that emits ~33% more text than the caller's own
        estimator will count, which is the defect stated as an assertion.
        """
        for hint in self.HINTS:
            for budget in self.BUDGETS:
                ctx = self.core.retrieval.get_context(hint, token_budget=budget)
                self.assertLessEqual(
                    len(ctx), budget_chars(budget),
                    "hint=%r budget=%d emitted %d chars > %d"
                    % (hint, budget, len(ctx), budget_chars(budget)))
                self.assertLessEqual(
                    estimate_tokens(ctx), budget,
                    "hint=%r budget=%d: %d estimated tokens > budget"
                    % (hint, budget, estimate_tokens(ctx)))

    def test_reported_used_matches_what_was_emitted(self):
        """`last_context_debug` describes THIS call's bytes, exactly.

        `used_tokens` is the emitted block measured with the same estimator
        the budget was built from, so the two are comparable with no fudge
        factor; `token_budget` is the budget that was enforced, not
        `max_chars // 4`. Killed by restoring either.
        """
        for budget in self.BUDGETS:
            ctx = self.core.retrieval.get_context(QUERY, token_budget=budget)
            dbg = self.core.retrieval.last_context_debug
            self.assertEqual(dbg["used_tokens"], estimate_tokens(ctx))
            self.assertEqual(dbg["used_chars"], len(ctx))
            self.assertLessEqual(dbg["used_tokens"], dbg["token_budget"])
            self.assertLessEqual(dbg["token_budget"], budget)

    def test_tier1_block_is_budgeted(self):
        """The ranked-belief block used to be the one section that spent
        budget without being checked against it (its own comment said so).

        A budget too small for even one belief line must produce a context
        inside the budget rather than an over-long one the final cut then
        bisects. Killed by removing the `tier1_chars` check in get_context.

        Runs on the `seed_spread` store, and that is load-bearing: on
        `seed_wide` the factual query CONVERGES, precision packing fires, and
        the Tier-1 block is skipped outright -- a version of this test written
        against that store passes with the check deleted, because the block it
        is about never runs.
        """
        core, home = make_core()
        try:
            seed_spread(core)
            self._assert_budgeted(core, SPREAD_Q)
        finally:
            shutil.rmtree(home, ignore_errors=True)
        # …and on the packing path too, where the budget is the caller's own.
        self._assert_budgeted(self.core, QUERY)

    def _assert_budgeted(self, core, hint):
        for budget in (5, 10, 20, 40, 120, 400, 1500, 4000, 12000):
            ctx = core.retrieval.get_context(hint, token_budget=budget)
            self.assertLessEqual(len(ctx), budget_chars(budget))
            self.assertNotIn("(truncated)", ctx)
            # The decisive one: every section checks the budget BEFORE it
            # appends, so the final trim never has to drop anything. Remove the
            # tier-1 check and the block overruns, `_fit_units` starts dropping,
            # and the output still FITS -- silently, by discarding ranked
            # evidence at the last step instead of never claiming it.
            dropped = core.retrieval.last_context_debug["dropped_units"]
            self.assertEqual(
                dropped, 0,
                "hint=%r budget=%d: the final trim had to drop %d unit(s) — a "
                "section overran instead of checking the budget first"
                % (hint, budget, dropped))


# ===========================================================================
# A10 — the final cut drops whole units
# ===========================================================================
class TestFinalCutDropsWholeUnits(unittest.TestCase):

    UNITS = ["[FACT] name: Pat Testley (conf 0.8)",
             "[SESSION s_0 @ 2026-01-01T09:00]",
             "User: the heating loop was rebalanced in March and logged clean",
             "Assistant: understood, filed under Springfield",
             "[DIRECTIVE] always file the maintenance report by Friday"]

    def test_every_surviving_line_is_a_whole_unit(self):
        """Across every budget from 0 to the full length, `_fit_units` never
        emits a fragment of a line — it emits a prefix of the line LIST.

        Killed by restoring `ctx[:max_chars]`, which at almost every one of
        these budgets returns a partial final line.
        """
        text = "\n".join(self.UNITS)
        for cap in range(0, len(text) + 2):
            fitted, dropped = _fit_units(text, cap)
            self.assertLessEqual(len(fitted), cap if cap else len(fitted) * 0 + cap,
                                 "cap=%d emitted %d chars" % (cap, len(fitted)))
            lines = fitted.split("\n") if fitted else []
            body = [ln for ln in lines if not ln.startswith("…")]
            self.assertEqual(body, self.UNITS[:len(body)],
                             "cap=%d body is not a whole-unit prefix: %r" % (cap, body))
            self.assertEqual(dropped, len(self.UNITS) - len(body) if fitted or cap == 0
                             else dropped)

    def test_the_drop_is_reported_and_counted(self):
        """It says how many units went, and the report itself is inside the
        budget — a notice that overran the budget to announce an overrun would
        be one more wrong number. Killed by the old bare "(truncated)".
        """
        text = "\n".join(self.UNITS)
        fitted, dropped = _fit_units(text, 90)
        self.assertGreater(dropped, 0)
        self.assertLessEqual(len(fitted), 90)
        self.assertIn("dropped", fitted)
        self.assertIn(str(dropped), fitted)
        self.assertNotIn("(truncated)", fitted)
        # Singular/plural, because a report that says "1 items" reads as a bug.
        keep, drop = "[FACT] a: b (conf 0.9)", "x" * 400
        one_short = keep + "\n" + drop
        cap = len(keep) + 1 + len(_OVER_BUDGET_NOTE.format(1, ""))
        fitted1, dropped1 = _fit_units(one_short, cap)
        self.assertEqual(dropped1, 1)
        self.assertIn("1 item dropped", fitted1)
        self.assertNotIn("1 items", fitted1)
        self.assertLessEqual(len(fitted1), cap)
        self.assertTrue(fitted1.startswith(keep))

    def test_text_already_inside_the_budget_is_returned_byte_identical(self):
        """The guard must be inert on the normal path — every section of
        get_context now checks the budget before appending, so `_fit_units`
        should be doing nothing at all almost always."""
        text = "\n".join(self.UNITS)
        self.assertEqual(_fit_units(text, len(text)), (text, 0))
        self.assertEqual(_fit_units(text, len(text) + 1000), (text, 0))


class TestNoPartialWordAtTheBoundary(unittest.TestCase):

    def setUp(self):
        self.core, self.home = make_core()
        seed_wide(self.core)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_no_emitted_line_stops_mid_word(self):
        """End-to-end: for every budget, every emitted line that is a PREFIX
        of a longer source line stops at a word boundary in that source.

        This is the reader-facing form of the guarantee — `_truncate_at_boundary`
        already gave it to session excerpts, and the blind final cut took it
        away again at the last step. Killed by restoring `ctx[:max_chars]`.
        """
        sources = [r["value"] for r in
                   self.core.store.query_beliefs("facts", "1=1", (), 200)]
        sources += [(e.get("excerpt") or "") for e in
                    self.core.retrieval.retrieve_raw(QUERY, limit=40)]
        sources = [s for s in sources if s]
        for budget in (30, 60, 90, 150, 300, 700, 1500):
            ctx = self.core.retrieval.get_context(QUERY, token_budget=budget)
            for line in ctx.split("\n"):
                if not line or line.startswith("…"):
                    continue
                for src in sources:
                    if src.startswith(line) and len(src) > len(line):
                        self.assertTrue(
                            src[len(line)].isspace() or line[-1] in ".!?",
                            "budget=%d cut mid-word: ...%r | %r..."
                            % (budget, line[-25:], src[len(line):len(line) + 15]))


# ===========================================================================
# A16 — drafts are distinguishable
# ===========================================================================
class TestDraftsAreMarked(unittest.TestCase):
    """Runs on the `seed_spread` store, where the factual query does NOT
    converge and the evidence-forward arm therefore renders Tier-1 beliefs —
    the only path that puts a belief in front of a reader at all."""

    def setUp(self):
        self.core, self.home = make_core()
        seed_spread(self.core)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    @staticmethod
    def _draft_lines(ctx, values):
        """Lines of `ctx` that render one of `values` as a belief.

        Matched on the value's FIRST line: an episode value can itself contain
        newlines, and only its opening line can carry a leading tag."""
        keys = [v.split("\n")[0] for v in values if v]
        out = []
        for line in ctx.split("\n"):
            if not line.startswith(("[", _DRAFT_TAG)):
                continue
            if any(k and k in line for k in keys):
                out.append(line)
        return out

    def test_a_draft_reaches_tier1_context_marked(self):
        """The defect, stated directly: a draft belief that reaches the reader
        carries `[DRAFT]`.

        Killed by dropping the `prefix` in `_render` — the row still arrives
        (it always did), it just arrives looking like confirmed truth again.
        """
        values = draft_all_beliefs(self.core)
        self.assertTrue(values, "fixture produced no beliefs to draft")
        ctx = self.core.retrieval.get_context(SPREAD_Q, token_budget=4000)
        self.assertFalse(self.core.retrieval.last_context_debug["precision"],
                         "fixture converged; Tier-1 was skipped and nothing was tested")
        lines = self._draft_lines(ctx, values)
        self.assertTrue(lines, "no draft belief reached the context to test")
        for line in lines:
            self.assertTrue(line.startswith(_DRAFT_TAG),
                            "unmarked draft in context: %r" % line)

    def test_a_draft_reaches_answer_marked(self):
        """answer()'s text comes from `_answer_from_beliefs`, which renders
        through the same `_render`. Killed by the same revert."""
        values = draft_all_beliefs(self.core)
        ans = self.core.retrieval.answer(SPREAD_Q)
        lines = self._draft_lines(ans.get("answer") or "", values)
        self.assertTrue(lines, "no draft belief reached answer() to test")
        for line in lines:
            self.assertTrue(line.startswith(_DRAFT_TAG),
                            "unmarked draft in answer(): %r" % line)

    def test_the_confident_path_can_be_closed_to_drafts(self):
        """The OTHER direction of A16's reconciliation with upstream 7b83049.

        Upstream gated drafts out of answer()'s confident path and defaulted that
        gate ON; this tree keeps the gate but defaults it OFF, because
        `test_a_draft_reaches_answer_marked` above is a mutation-kill guard on
        the MARKING and an excluding default would make it vacuous rather than
        green (see engine/config.py:confident_answer_from_drafts). A kept option
        that nothing exercises is an unkept one, so this pins the option itself:
        with the gate closed, a store whose every belief is a draft must produce
        no belief-backed confident answer at all. Deleting the gate in
        `answer()` turns this red.
        """
        core, home = make_core({"retrieval": {"confident_answer_from_drafts": False}})
        try:
            seed_spread(core)
            values = draft_all_beliefs(core)
            ans = core.retrieval.answer(SPREAD_Q)
            self.assertEqual(
                self._draft_lines(ans.get("answer") or "", values), [],
                "a draft backed the confident answer while the gate was closed")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_no_packing_path_emits_an_unmarked_draft(self):
        """All three packing paths, driven over drafted stores, and none may
        render a draft as a plain belief line.

        Evidence-forward renders beliefs and must mark them. Precision and
        preference packing skip the Tier-1 block by design and emit raw
        transcript turns, which carry no belief status at all — this pins that
        they stay that way, so a future change that starts emitting beliefs on
        those arms cannot do it unmarked. The test asserts each path was
        ACTUALLY taken, so it cannot pass by never exercising one.
        """
        seen = {}
        cases = [(seed_spread, SPREAD_Q), (seed_wide, QUERY), (seed_wide, PREF_Q)]
        for seeder, hint in cases:
            core, home = make_core()
            try:
                seeder(core)
                values = draft_all_beliefs(core)
                for budget in (1500, 12000):
                    ctx = core.retrieval.get_context(hint, token_budget=budget)
                    dbg = core.retrieval.last_context_debug
                    path = ("precision" if dbg.get("precision")
                            else "pref_pack" if dbg.get("pref_pack") else "evidence")
                    seen[path] = seen.get(path, 0) + 1
                    for line in self._draft_lines(ctx, values):
                        self.assertTrue(
                            line.startswith(_DRAFT_TAG),
                            "%s path emitted unmarked draft: %r" % (path, line))
            finally:
                shutil.rmtree(home, ignore_errors=True)
        for path in ("evidence", "precision", "pref_pack"):
            self.assertIn(path, seen, "packing path never exercised: %s (saw %r)"
                          % (path, seen))

    def test_marking_does_not_break_the_budget(self):
        """The marker is text, and text costs budget. With every belief in the
        store drafted (the worst case), the A10 invariant still holds.

        Killed by adding the marker AFTER the budget check — the ordering
        mistake that would make A16 quietly reopen A10.
        """
        draft_all_beliefs(self.core)
        for budget in (40, 120, 400, 1500, 4000):
            ctx = self.core.retrieval.get_context(SPREAD_Q, token_budget=budget)
            self.assertLessEqual(len(ctx), budget_chars(budget))
            self.assertLessEqual(estimate_tokens(ctx), budget)
            self.assertEqual(self.core.retrieval.last_context_debug["used_tokens"],
                             estimate_tokens(ctx))

    def test_include_drafts_false_excludes_them_everywhere(self):
        """The config gate the audit asked for, and it is actually READ.

        One choke point (`_readable`), so turning it off removes drafts from
        search(), answer() and every get_context path at once. Killed by
        deleting the `_include_drafts` check in `_readable`.
        """
        values = draft_all_beliefs(self.core)
        core2, home2 = make_core({"retrieval": {"include_drafts": False}})
        try:
            seed_spread(core2)
            draft_all_beliefs(core2)
            hits = [b for b in core2.retrieval.search(SPREAD_Q, limit=20)
                    if b.get("status") == "draft"]
            self.assertEqual(hits, [], "draft survived include_drafts=false")
            ctx = core2.retrieval.get_context(SPREAD_Q, token_budget=4000)
            self.assertNotIn(_DRAFT_TAG, ctx)
            self.assertEqual(self._draft_lines(ctx, values), [])
        finally:
            shutil.rmtree(home2, ignore_errors=True)
        # …and the default is the honest-but-inclusive one: same query, same
        # shape of store, drafts PRESENT and labelled.
        ctx = self.core.retrieval.get_context(SPREAD_Q, token_budget=4000)
        self.assertTrue(self._draft_lines(ctx, values),
                        "default config dropped drafts instead of marking them")

    def test_default_is_include_and_mark(self):
        """State the chosen policy as a test so a silent flip of the default
        fails loudly rather than emptying a reader's context."""
        self.assertTrue(self.core.retrieval._include_drafts())
        self.assertTrue(self.core.cfg.get("retrieval.include_drafts", True))


class TestDraftInSupersessionChain(unittest.TestCase):

    def test_a_draft_chain_point_is_marked(self):
        """`[history: A (date) -> B (date)]` renders bare values, and the
        chain walk exists partly to surface still-draft rows (its own
        comment). "latest wins" on a chain whose last point is an unconfirmed
        draft is the wrong rule, so the point says so.

        Killed by reverting `_chain_point` to the inline `"{} ({})".format`.
        """
        from engine.retrieval import RetrievalEngine
        point = {"value": "Acme Fake Co", "created_at": "2026-03-04T10:00:00", "status": "draft"}
        self.assertTrue(RetrievalEngine._chain_point(point).startswith(_DRAFT_TAG))
        point["status"] = "active"
        self.assertFalse(RetrievalEngine._chain_point(point).startswith(_DRAFT_TAG))
        self.assertEqual(RetrievalEngine._chain_point(point), "Acme Fake Co (2026-03-04)")


# ===========================================================================
# A10 — the compress() side of the same estimator
# ===========================================================================
class TestRehydrationUsesOneEstimator(unittest.TestCase):

    def setUp(self):
        self.core, self.home = make_core()
        seed_wide(self.core)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_rehydrated_spans_fit_their_budget_without_being_sliced(self):
        """`_rehydrate_working_set` asked get_context for N tokens, wrapped the
        answer in a header, and then hard-cut the result at `remaining * 3`
        chars — over-fetch, then a slice through whatever evidence line landed
        on the boundary. It now pays for the header up front, so the span fits
        by construction and a span that still does not fit is OMITTED WHOLE.

        Killed by restoring the `content[:remaining * 3]` clip: at a tight
        budget the emitted span exceeds it or ends mid-word.
        """
        eng = ChronicleContextEngine()
        eng.on_session_start("s1", hermes_home=self.home, principal_id="assistant",
                             config={"embeddings": {"model": "hashing"}})
        self.assertIsNotNone(eng.core, "test setup expected the real engine")
        # ONE facet, so `share == inject_budget == remaining` and the old
        # code's `content[:remaining * 3]` clip fires on every call: it asked
        # get_context for `facet_budget` tokens (4x that many chars, under the
        # old private ratio), added a header, then sliced the result back to
        # `remaining * 3` chars — a cut a quarter of the way into the body,
        # landing mid-word essentially always.
        focus = {"topics": ["the Springfield heating loop maintenance report"],
                 "entities": [], "task": None}
        sources = [(e.get("excerpt") or "") for e in
                   self.core.retrieval.retrieve_raw(QUERY, limit=40)]
        sources += [r["value"] for r in
                    self.core.store.query_beliefs("facts", "1=1", (), 200)]
        sources = [x for x in sources if x]
        # A10b units restatement: the same char sizes under the restated
        # estimate -- 20/60/200/800 tok x 3 chars = 60/180/600/2400 chars
        # = 15/45/150/600 tok x 4 chars.
        for budget in (15, 45, 150, 600):
            spans, used = eng._rehydrate_working_set(focus, budget, 0)
            total = sum(estimate_tokens(s["content"]) for s in spans)
            self.assertLessEqual(total, budget,
                                 "budget=%d rehydrated %d tokens" % (budget, total))
            self.assertEqual(used, total)
            for sp in spans:
                for line in sp["content"].split("\n"):
                    if not line or line.startswith(("[Relevant memory", "…")):
                        continue
                    for src in sources:
                        if src.startswith(line) and len(src) > len(line):
                            self.assertTrue(
                                src[len(line)].isspace() or line[-1] in ".!?",
                                "budget=%d rehydration cut mid-word: ...%r | %r..."
                                % (budget, line[-25:], src[len(line):len(line) + 15]))


if __name__ == "__main__":
    unittest.main()
