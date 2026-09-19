"""
Chronicle — acceptance tests for A9: resumable, observably-bounded sweeps.

THE DEFECT. Every periodic sweep in the engine selected its work with
`query_beliefs(table, where, limit=5000)`. That call has no ORDER BY and no
cursor, so it returns *a* prefix — in practice the same prefix every run. Past
the cap the sweep processes the prefix, never reaches the rest, and returns
normally, so `health.run()` records a success. Measured on the live store
(108,581 memory vectors, 89,562 observed vectors, ~67k historical extract jobs)
that made decay, ghost-fact reporting, consistency, canonicalize, identity,
derivation fanout, backfill and reextract permanently partial, silently.

`reextract` was the worst of them and is the same shape as the A7 heal bug: it
loaded every observed event, sorted in Python, took the OLDEST 200 — which have
had an extraction at every version for years — enqueued nothing, and completed
successfully. Re-select the same prefix, find it already done, achieve nothing,
forever. `TestReextractReachesTheBacklog` is that story as a test.

WHAT IS ASSERTED HERE, in the order a reviewer should read it:

  1. Exactly-once coverage. 3x the budget of eligible rows; repeated runs
     process every row once and `remaining` falls monotonically to zero.
  2. Bounded runs SAY they are bounded — `bounded=True` with a nonzero
     `remaining`, in the sweep's own report and in the health snapshot.
  3. The cursor is load-bearing: disable it and coverage collapses back to the
     prefix. This is the mutation test for the actual bug.
  4. The bound is config, not a literal, and the keys are honored.
  5. Group-shaped sweeps page by GROUP, so a page boundary can never split an
     entity's facts and make a contradiction invisible.
  6. The one fold that must NOT be bounded — forbidden-content retraction —
     is complete past every old cap.
  7. Per-run cost stays bounded on a production-sized synthetic store.

Fixtures are synthetic throughout (Pat Testley, Acme Fake Co, hashing
embedder). Nothing here touches a network or a paid API.
"""

import datetime
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import sweeps
from engine.core import ChronicleCore
from engine.serialize import hash_str

CFG = {"embeddings": {"model": "hashing", "dimensions": 32}}

_FACT_COLS = ("belief_id", "entity_id", "attribute", "predicate_canonical", "value",
              "qualifiers_hash", "provenance", "owner", "domain", "status", "salience",
              "criticality", "confidence", "confirm_count", "fidelity",
              "created_at", "last_seen_at")


def _iso_days_ago(days):
    t = (datetime.datetime.now(datetime.timezone.utc)
         - datetime.timedelta(days=days))
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


class _SweepCase(unittest.TestCase):
    CFG = CFG

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a9_")
        self.core = ChronicleCore(self.home, self.CFG)
        self.store = self.core.store

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    # -- fixtures ----------------------------------------------------------

    def _facts(self, n, *, start=0, entity=lambda i: "e_%05d" % i,
               predicate=lambda i: "p_%05d" % i, value=lambda i: "v_%05d" % i,
               salience=lambda i: "normal", confidence=0.9, age_days=200,
               domain="general", confirm_count=0):
        """Insert `n` active facts directly.

        Bypassing capture/append is deliberate and load-bearing for these tests:
        they are about which rows a SELECT reaches, and building 6000 facts one
        event at a time would measure the write path instead — and take minutes."""
        ts = _iso_days_ago(age_days)
        prov = json.dumps({"source_type": "session_transcript"})
        rows = []
        for i in range(start, start + n):
            rows.append(("b_%05d" % i, entity(i), "attr", predicate(i), value(i), "",
                         prov, "user", domain, "active", salience(i), "normal",
                         confidence, confirm_count, "verbatim", ts, ts))
        with self.store.transaction() as c:
            c.executemany("INSERT INTO facts(%s) VALUES(%s)"
                          % (",".join(_FACT_COLS), ",".join("?" * len(_FACT_COLS))), rows)
        return ["b_%05d" % i for i in range(start, start + n)]

    def _resweep(self, **sweepcfg):
        """Reopen the SAME store under a different `sweeps.*` config.

        `Config` is deliberately immutable — there is no setter — so a test that
        needs a different pace rebuilds the core over the existing database file
        rather than mutating a live config object behind the engine's back."""
        self.core = ChronicleCore(self.home, dict(self.CFG, sweeps=sweepcfg))
        self.store = self.core.store
        return self.core

    def _justify(self, belief_ids):
        """Give each belief a justification.

        `health.run()` retracts active beliefs with none (I5) BEFORE the
        consistency sweep, so a fixture written straight to SQL would be
        retracted out from under the sweep it was meant to exercise."""
        for bid in belief_ids:
            self.store.add_justification(bid, "ev_fixture", "event")

    def _ghost_run(self):
        """One `_ghost_facts` run: (ids, report)."""
        gf = self.core.cfg.get("health.ghost_fact", {"confidence_min": 0.8})
        return self.core.health._ghost_facts(gf)


# ---------------------------------------------------------------------------
# 1. Exactly-once coverage, and `remaining` that actually falls to zero
# ---------------------------------------------------------------------------
class TestEventuallyProcessesEverything(_SweepCase):
    CFG = dict(CFG, sweeps={"budgets": {"ghost_facts": 50}})

    def test_three_budgets_of_rows_are_each_processed_exactly_once(self):
        """The acceptance case: 3x the cap of eligible rows.

        Every row is seen once across the lap, no row is seen twice, and
        `remaining` decreases monotonically to zero. Before A9 the first 50
        would have been reprocessed on every run and the other 100 never
        touched, with `remaining` reported nowhere at all."""
        planted = set(self._facts(150))

        seen, remainings, laps = [], [], 0
        while True:
            ids, report = self._ghost_run()
            laps += 1
            seen.extend(ids)
            remainings.append(report["remaining"])
            self.assertLessEqual(report["processed"], 50,
                                 "a run exceeded its configured budget")
            if report["wrapped"]:
                break
            self.assertLess(laps, 10, "the sweep is not converging")

        self.assertEqual(laps, 3, "150 rows at a budget of 50 should take 3 runs")
        self.assertEqual(len(seen), len(set(seen)),
                         "a row was processed twice inside one lap")
        self.assertEqual(set(seen), planted, "the lap did not cover every eligible row")
        self.assertEqual(remainings, sorted(remainings, reverse=True),
                         "reported `remaining` did not decrease monotonically")
        self.assertEqual(remainings[-1], 0, "the lap ended without reaching zero")

    def test_a_bounded_run_says_bounded_with_a_nonzero_remaining(self):
        """Visible partiality. The FIRST run of a 150-row backlog is partial;
        the whole point of A9 is that it admits it rather than returning a
        plain list of ids that looks the same as a completed sweep."""
        self._facts(150)
        _ids, report = self._ghost_run()
        self.assertTrue(report["bounded"])
        self.assertEqual(report["processed"], 50)
        self.assertEqual(report["remaining"], 100)
        self.assertEqual(report["total"], 150)
        self.assertFalse(report["wrapped"])

    def test_a_complete_run_says_it_is_not_bounded(self):
        """The negative half: with work that fits, `bounded` is False and
        `remaining` is 0. Without this, `bounded=True` could be a constant."""
        self._facts(10)
        _ids, report = self._ghost_run()
        self.assertFalse(report["bounded"])
        self.assertEqual(report["remaining"], 0)
        self.assertEqual(report["processed"], 10)

    def test_the_lap_wraps_so_rows_behind_the_cursor_are_revisited(self):
        """A watermark that only moves forward goes quiet at the end of the
        table — which is exactly how `get_sessions_needing_index_backfill`
        shipped. After a lap completes the cursor resets, so a row that becomes
        eligible behind it is reached on the next lap."""
        self._facts(10)
        for _ in range(3):
            ids, report = self._ghost_run()
        self.assertTrue(report["wrapped"])
        self.assertEqual(self.store.get_sweep_state("ghost_facts")["cursor"], 0)
        ids, _r = self._ghost_run()
        self.assertEqual(len(ids), 10, "the sweep went quiet instead of wrapping")


# ---------------------------------------------------------------------------
# 2. The cursor is load-bearing (mutation test for the real bug)
# ---------------------------------------------------------------------------
class TestRemovingTheWatermarkReintroducesTheBug(_SweepCase):
    CFG = dict(CFG, sweeps={"budgets": {"ghost_facts": 50}})

    def test_without_the_persisted_cursor_the_sweep_never_leaves_the_prefix(self):
        """Delete the watermark and the pre-A9 behavior comes straight back.

        This is the mutation the task asks for, run as a test rather than
        asserted in prose: with `get_sweep_state` stubbed to forget, three runs
        of a 150-row backlog cover 50 rows — the same 50, three times — while
        every run still returns without an error. That is precisely the shape
        that let the production heal re-tag 60 vectors in 9 days."""
        planted = set(self._facts(150))
        self.store.get_sweep_state = lambda _name: {}      # the removed watermark

        seen = []
        for _ in range(3):
            ids, report = self._ghost_run()
            seen.extend(ids)
            self.assertTrue(report["bounded"], "the run still claims to be partial")

        self.assertEqual(len(set(seen)), 50,
                         "without a cursor the sweep should be stuck on the prefix")
        self.assertEqual(len(seen), 150, "and should have re-processed it every run")
        self.assertLess(len(set(seen)), len(planted),
                        "coverage without a cursor must be strictly partial")


# ---------------------------------------------------------------------------
# 3. The bound is configuration, not a literal
# ---------------------------------------------------------------------------
class TestBudgetsAreConfigDriven(_SweepCase):
    def test_per_sweep_budget_wins_over_the_shared_row_budget(self):
        cfg = self._resweep(row_budget=11, budgets={"ghost_facts": 7}).cfg
        self.assertEqual(sweeps.sweep_budget(cfg, "ghost_facts"), 7)
        self.assertEqual(sweeps.sweep_budget(cfg, "decay"), 11,
                         "a sweep with no override should take the shared budget")

    def test_the_configured_budget_is_what_a_run_actually_processes(self):
        """A key that parses but is never read is the other way to ship this
        bug, so assert the number reaches the SQL, not just the accessor."""
        self._facts(30)
        self._resweep(budgets={"ghost_facts": 7})
        _ids, report = self._ghost_run()
        self.assertEqual(report["processed"], 7)
        self.assertEqual(report["budget"], 7)
        self.assertEqual(report["remaining"], 23)

    def test_a_nonsense_budget_falls_back_instead_of_disabling_the_sweep(self):
        """A zero or unparseable budget must never become "process nothing and
        report success" — that is the defect wearing a different hat."""
        cfg = self._resweep(budgets={"ghost_facts": "not a number"}).cfg
        self.assertEqual(sweeps.sweep_budget(cfg, "ghost_facts"), sweeps.DEFAULT_ROW_BUDGET)
        cfg = self._resweep(budgets={"ghost_facts": 0}).cfg
        self.assertEqual(sweeps.sweep_budget(cfg, "ghost_facts"), 1)

    def test_page_rows_is_a_memory_bound_only(self):
        """`iter_all_rows` pages at `sweeps.page_rows` and still yields
        everything: shrinking the page must change round trips, never results."""
        self._facts(50)
        self._resweep(page_rows=7)
        rows = list(sweeps.iter_all_rows(self.store, self.core.cfg, "facts", "1=1", ()))
        self.assertEqual(len(rows), 50)
        self.assertEqual(sweeps.page_rows(None), sweeps.DEFAULT_PAGE_ROWS,
                         "a reducer built with cfg=None must still page")


# ---------------------------------------------------------------------------
# 4. Decay — the spec's own acceptance case
# ---------------------------------------------------------------------------
class TestDecayReachesPastTheOldCap(_SweepCase):
    def test_the_5001st_fact_is_decayed_within_two_sweeps(self):
        """AUDIT-2026-09 §A9, verbatim: "a 6000-fact fixture where the 5001st
        fact is the only decay-eligible one is decayed within two sweeps".

        Every other fact is pinned, so it is ineligible but still occupies a row
        the scan must walk past. Before A9 the 5001st row was unreachable: the
        sweep read an unordered 5000-row prefix on every run, forever."""
        target_ix = 5000
        self._facts(6000, salience=lambda i: "normal" if i == target_ix else "pinned")
        target = "b_%05d" % target_ix

        self.assertEqual(self.store.get_belief("facts", target)["fidelity"], "verbatim")
        first = self.core.forgetting.decay_sweep()
        self.assertTrue(first["bounded"], "run 1 of 6000 rows must report itself partial")
        self.assertEqual(self.store.get_belief("facts", target)["fidelity"], "verbatim",
                         "the target sits past the first budget; run 1 must not reach it")

        second = self.core.forgetting.decay_sweep()
        self.assertEqual(self.store.get_belief("facts", target)["fidelity"], "gist",
                         "run 2 did not reach the 5001st fact — the sweep is still "
                         "re-reading the prefix")
        self.assertEqual(second["decayed"], 1)

    def test_each_belief_table_carries_its_own_cursor(self):
        """facts, episodes and notes are swept independently; one shared cursor
        would let a short table's wrap reset a long table's progress."""
        self._facts(120, salience=lambda i: "pinned")
        self._resweep(budgets={"decay": 50})
        report = self.core.forgetting.decay_sweep()
        states = self.store.list_sweep_states()
        for table in ("facts", "episodes", "notes"):
            self.assertIn("decay:" + table, states)
        self.assertEqual(report["tables"]["facts"]["remaining"], 70)
        self.assertEqual(report["tables"]["notes"]["remaining"], 0)


# ---------------------------------------------------------------------------
# 5. Group-shaped sweeps: a page boundary must never split a group
# ---------------------------------------------------------------------------
class TestGroupShapedSweepsPageByGroup(_SweepCase):
    def test_a_contradiction_is_seen_even_at_a_budget_of_one_entity(self):
        """The reason consistency does NOT page by rowid.

        `e_conflict` holds two active values for a single-cardinality predicate.
        Under rowid paging with a small budget those two rows land in different
        pages and each page sees ONE value — so the sweep concludes the store is
        consistent. A bounded sweep returning a WRONG answer is worse than the
        silent truncation being fixed, so the cursor runs over DISTINCT
        entity_id and each entity arrives whole."""
        self._facts(4, entity=lambda i: "e_a%d" % i, predicate=lambda i: "likes")
        self._facts(2, start=100, entity=lambda i: "e_conflict",
                    predicate=lambda i: "lives_in", value=lambda i: "city_%d" % i)
        self.store.upsert_predicate("lives_in", "lives_in", "single")
        self._resweep(budgets={"consistency": 1})

        for _ in range(8):
            report = self.core.health.consistency_sweep()
            if report["wrapped"]:
                break
        self.assertTrue(self.store.get_open_contradictions(),
                        "the conflicting entity's two values were never seen together")

    def test_consistency_reports_its_own_partiality(self):
        self._facts(30, entity=lambda i: "e_%03d" % i)
        self._resweep(budgets={"consistency": 10})
        report = self.core.health.consistency_sweep()
        self.assertEqual(report["processed"], 10)
        self.assertEqual(report["remaining"], 20)
        self.assertTrue(report["bounded"])

    def test_a_null_grouping_value_is_still_swept(self):
        """`normalized_name` and `predicate_canonical` are nullable, and
        `col > ?` is never true for NULL — so a plain comparison would make
        every NULL-keyed row permanently invisible: the same defect, one group
        wide. COALESCE puts them at the head of the lap instead."""
        with self.store.transaction() as c:
            c.execute("INSERT INTO facts(belief_id,entity_id,attribute,predicate_canonical,"
                      "value,provenance,owner,domain,status) VALUES"
                      "('b_null','e_null','attr',NULL,'v','{}','user','general','active')")
        vals = self.store.scan_distinct_after("facts", "predicate_canonical",
                                              "status='active'", (), None, 10)
        self.assertIn("", vals, "a NULL grouping value was skipped by the scan")
        rows = self.store.beliefs_for_values("facts", "predicate_canonical", [""],
                                             "status='active'", ())
        self.assertEqual([r["belief_id"] for r in rows], ["b_null"])

    def test_the_start_sentinel_is_none_and_not_the_empty_string(self):
        """The distinction that makes the line above work. `after=None` means
        "no lower bound"; `after=""` means "the ''-group is already done". If
        the start sentinel were "" the ''-group would be skipped on every run
        forever, because no string sorts before ''."""
        with self.store.transaction() as c:
            c.execute("INSERT INTO facts(belief_id,entity_id,attribute,predicate_canonical,"
                      "value,provenance,owner,domain,status) VALUES"
                      "('b_null','e_null','attr',NULL,'v','{}','user','general','active')")
        self._facts(2, predicate=lambda i: "p_%d" % i)
        self.assertEqual(self.store.count_distinct_after(
            "facts", "predicate_canonical", "status='active'", (), None), 3)
        self.assertEqual(self.store.count_distinct_after(
            "facts", "predicate_canonical", "status='active'", (), ""), 2)
        self.assertNotIn("", self.store.scan_distinct_after(
            "facts", "predicate_canonical", "status='active'", (), "", 10))

    def test_a_wrapped_group_sweep_resets_to_the_no_lower_bound_sentinel(self):
        """A finished lap must store None, not "", or the ''-group would be
        skipped on every lap after the first."""
        self._facts(3, entity=lambda i: "e_%d" % i)
        page = sweeps.next_distinct_page(self.store, self.core.cfg, "t_wrap",
                                         "facts", "entity_id", "status='active'", ())
        sweeps.commit(self.store, page)
        self.assertTrue(page.wrapped)
        self.assertIsNone(self.store.get_sweep_state("t_wrap")["cursor"])


class TestCanonicalizeAsksTheDatabaseForCardinality(_SweepCase):
    def test_the_multi_value_witness_is_exact_at_any_page_size(self):
        """The old sweep inferred cardinality by grouping only the rows it had
        read. With ANY paging that becomes actively wrong — a predicate's two
        values for one entity can land in different pages — and the mistake is
        permanent, because the upsert is guarded on the predicate being absent.

        The two halves are asserted side by side: a one-row page really does
        hold half the group (so the old page-local grouping would have answered
        "single"), and the witness query answers "multi" anyway because it asks
        the table, not the page."""
        self._facts(2, entity=lambda i: "e_one", predicate=lambda i: "pet",
                    value=lambda i: "pet_%d" % i)

        page = self.store.scan_beliefs_after("facts", "predicate_canonical='pet'", (), 0, 1)
        by_entity = {}
        for r in page:                       # exactly the old code's grouping
            by_entity.setdefault(r["entity_id"], set()).add(r["value"])
        self.assertEqual(len(page), 1, "the fixture page should hold half the group")
        self.assertFalse(any(len(v) > 1 for v in by_entity.values()),
                         "a page-local grouping should see a single value here")

        self.assertTrue(self.store.predicate_has_multi_value("pet"),
                        "the witness query must be exact regardless of paging")

    def test_predicates_past_the_old_cap_get_a_row(self):
        self._facts(120, predicate=lambda i: "p_%05d" % i)
        self._resweep(budgets={"canonicalize": 40})
        for _ in range(6):
            if self.core.curation._task_canonicalize({})["wrapped"]:
                break
        self.assertIsNotNone(self.store.get_predicate("p_00119"),
                             "the last predicate in the table was never canonicalized")


# ---------------------------------------------------------------------------
# 6. reextract — the A7-shaped "achieves nothing, forever" case
# ---------------------------------------------------------------------------
class TestReextractReachesTheBacklog(_SweepCase):
    def _observed(self, n):
        return [self.core.capture.append(
            "observed", {"excerpt": "User: turn %d\nAssistant: ok." % i,
                         "source_type": "session_transcript"},
            actor="user", session_id="s-a9") for i in range(n)]

    def test_events_whose_prefix_is_already_extracted_do_not_starve_the_rest(self):
        """The live failure. The oldest events have an extraction at every
        version, so the old handler's "sort ascending, take 200" selected 200
        rows it then filtered out entirely — it enqueued nothing, every run, on
        a store with a ~67k-event backlog, and completed successfully.

        Eligibility is a SQL predicate now, so the page is 200 events that NEED
        work rather than 200 that do not."""
        ids = self._observed(30)
        version = self.core.extractor.version
        for eid in ids[:25]:
            self.store.record_extraction(eid, version, {"n": 0}, 0, "skip")
        self._resweep(budgets={"reextract": 3})
        # The capture path enqueues its own `extract` job per observed event, so
        # clear the queue first: what remains afterwards is reextract's doing.
        with self.store.transaction() as c:
            c.execute("DELETE FROM curation_jobs")

        report = self.core.curation._task_reextract({})
        self.assertEqual(report["processed"], 3,
                         "the run selected already-extracted events and did nothing")
        self.assertEqual(report["total"], 5, "eligibility is not being asked in SQL")
        self.assertTrue(report["bounded"])
        queued = {json.loads(r["payload"])["event_id"] for r in self.store._conn().execute(
            "SELECT payload FROM curation_jobs WHERE task='extract'").fetchall()}
        self.assertTrue(queued.issubset(set(ids[25:])),
                        "an already-extracted event was queued for re-extraction")

    def test_successive_runs_cover_the_whole_backlog(self):
        self._observed(20)
        self._resweep(budgets={"reextract": 6})
        remainings, processed = [], 0
        for _ in range(6):
            report = self.core.curation._task_reextract({})
            remainings.append(report["remaining"])
            processed += report["processed"]
            if report["wrapped"]:
                break
        self.assertEqual(processed, 20, "the lap did not reach every stale event")
        self.assertEqual(remainings, sorted(remainings, reverse=True))
        self.assertEqual(remainings[-1], 0)

    def test_an_explicit_payload_limit_still_wins(self):
        self._observed(10)
        report = self.core.curation._task_reextract({"limit": 4})
        self.assertEqual(report["processed"], 4)
        self.assertEqual(report["budget"], 4)


# ---------------------------------------------------------------------------
# 7. backfill and derivation fanout
# ---------------------------------------------------------------------------
class TestBackfillWrapsAndReports(_SweepCase):
    def _sessions(self, n):
        rows = [("s_%04d" % i, "general", "ended", _iso_days_ago(5)) for i in range(n)]
        with self.store.transaction() as c:
            c.executemany("INSERT INTO sessions(session_id,domain,status,started_at) "
                          "VALUES(?,?,?,?)", rows)
        return ["s_%04d" % i for i in range(n)]

    def test_the_watermark_wraps_instead_of_going_quiet_forever(self):
        """Before A9 the watermark only ever moved forward, so once it passed
        the highest session id this sweep returned an empty list for the life of
        the store — including for a session that lost its index row later."""
        sids = self._sessions(12)
        self._resweep(budgets={"backfill": 5})
        seen = []
        for _ in range(4):
            page = self.store.get_sessions_needing_index_backfill(limit=5)
            seen.extend(page)
            if self.store.get_sweep_state("backfill").get("wrapped"):
                break
        self.assertEqual(sorted(seen), sorted(sids))
        # Cursor wrapped: the next run starts over rather than returning nothing.
        self.assertEqual(len(self.store.get_sessions_needing_index_backfill(limit=5)), 5)

    def test_the_curation_task_reports_remaining(self):
        self._sessions(12)
        self._resweep(budgets={"backfill": 5})
        report = self.core.curation._task_backfill_sweep({})
        self.assertEqual(report["processed"], 5)
        self.assertEqual(report["remaining"], 7)
        self.assertTrue(report["bounded"])


class TestDerivationFanoutIsResumable(_SweepCase):
    def _antecedent_predicate(self):
        preds = set()
        for r in self.core.derivation.enabled_rules():
            preds.update(r.antecedent_predicates())
        self.assertTrue(preds, "no enabled rule has an antecedent to fan out over")
        return sorted(preds)[0]

    def test_successive_runs_advance_over_distinct_subjects(self):
        """One `query_beliefs(..., limit=500)` PER antecedent predicate, with no
        cursor, meant the same head of `facts` was derived over on every run and
        entities past it were never derived at all."""
        pred = self._antecedent_predicate()
        self._facts(30, entity=lambda i: "e_%03d" % i, predicate=lambda i: pred)
        self._resweep(budgets={"derive_subjects": 10})

        seen = []
        for _ in range(5):
            page = self.core.derivation._affected_subjects_page()
            seen.extend(page.rows)
            sweeps.commit(self.store, page)
            if page.wrapped:
                break
        self.assertEqual(len(seen), len(set(seen)), "a subject was derived twice in a lap")
        self.assertEqual(len(set(seen)), 30, "the lap missed subjects")

    def test_an_explicit_max_subjects_still_wins(self):
        pred = self._antecedent_predicate()
        self._facts(30, entity=lambda i: "e_%03d" % i, predicate=lambda i: pred)
        self._resweep(budgets={"derive_subjects": 10})
        page = self.core.derivation._affected_subjects_page(4)
        self.assertEqual(page.budget, 4)
        self.assertEqual(len(page.rows), 4)

    def test_no_enabled_rules_means_an_empty_page_not_a_full_scan(self):
        self._facts(30, entity=lambda i: "e_%03d" % i)
        self.core.derivation.enabled_rules = lambda: []
        page = self.core.derivation._affected_subjects_page()
        self.assertEqual(list(page.rows), [])
        self.assertFalse(page.bounded)


class TestIdentitySweepIsResumable(_SweepCase):
    def _entities(self, names):
        rows = [("ent_%03d" % i, "person", n, n.lower(), "general", "user")
                for i, n in enumerate(names)]
        with self.store.transaction() as c:
            c.executemany("INSERT INTO entities(belief_id,type,name,normalized_name,"
                          "domain,owner) VALUES(?,?,?,?,?,?)", rows)

    def test_a_duplicate_past_the_first_page_is_still_reached(self):
        """A9's claim is REACHABILITY: a collision sitting past the first page
        must still be found once the cursor gets there.

        A9 measured that by counting merges, because at the time `_task_identity`
        merged. Ladder-10 A8 replaced the merge with a proposal into E7's
        adjudication queue -- an exact name match is evidence, not identity, and
        two different people really are both called "Pat Testley". So the
        same claim is now measured on `identity_candidates`, and the assertion
        that nothing was MERGED is kept alongside it: a bounded sweep that
        merged left a wrong, irreversible write on the rows it did reach, and
        the composed behaviour is the one worth pinning."""
        names = ["Unique %03d" % i for i in range(20)] + ["Pat Testley", "Pat Testley"]
        self._entities(names)
        self._resweep(budgets={"identity": 5})
        for _ in range(8):
            report = self.core.curation._task_identity({})
            if report["wrapped"]:
                break
        conn = self.store._conn()
        candidates = conn.execute(
            "SELECT COUNT(*) FROM identity_candidates WHERE kind='merge'").fetchone()[0]
        self.assertEqual(candidates, 1,
                         "the duplicate pair sat past the first page and was never seen")
        merged = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE merged_into IS NOT NULL").fetchone()[0]
        self.assertEqual(merged, 0, "A8: an exact name match must never auto-merge")


# ---------------------------------------------------------------------------
# 8. The fold that must NOT be bounded
# ---------------------------------------------------------------------------
class TestForbiddenContentRetractionIsComplete(_SweepCase):
    def test_a_match_past_the_old_cap_is_still_retracted(self):
        """A bound on a redaction is not a pace, it is a leak.

        `_beliefs_matching_hash` capped notes at 1000 and facts at 5000, so a
        `forbidden` event on a larger store retracted a prefix of the matching
        beliefs and left the rest active and readable — while the event log
        recorded that the content was forbidden."""
        self._facts(5200, value=lambda i: "v_%05d" % i)
        needle = "v_05199"
        found = self.core.reducer._beliefs_matching_hash(hash_str(needle))
        self.assertIn("b_05199", found,
                      "a forbidden fact past the old 5000-row cap was left live")

    def test_iter_all_rows_never_truncates(self):
        self._facts(2500)
        self._resweep(page_rows=100)
        rows = list(sweeps.iter_all_rows(self.store, self.core.cfg, "facts", "1=1", ()))
        self.assertEqual(len(rows), 2500)
        self.assertEqual(len({r["belief_id"] for r in rows}), 2500)


# ---------------------------------------------------------------------------
# 9. Visibility: the health snapshot answers "is any sweep permanently behind?"
# ---------------------------------------------------------------------------
class TestHealthSnapshotSurfacesPartiality(_SweepCase):
    CFG = dict(CFG, sweeps={"budgets": {"ghost_facts": 5, "consistency": 5}})

    def test_a_bounded_sweep_is_named_in_the_snapshot(self):
        self._justify(self._facts(60, entity=lambda i: "e_%03d" % i))
        results = self.core.health.run()

        self.assertIn("sweeps", results)
        self.assertIn("ghost_facts", results["sweeps"])
        self.assertTrue(results["ghost_facts_sweep"]["bounded"])
        self.assertEqual(results["ghost_facts_sweep"]["remaining"], 55)
        self.assertIn("ghost_facts", results["sweeps_bounded"])
        self.assertIn("consistency", results["sweeps_bounded"])

    def test_a_caught_up_store_names_no_bounded_sweep(self):
        """The negative half — otherwise `sweeps_bounded` could be a constant."""
        self._justify(self._facts(3, entity=lambda i: "e_%03d" % i))
        results = self.core.health.run()
        self.assertEqual(results["sweeps_bounded"], [])

    def test_the_snapshot_is_persisted_with_the_run(self):
        self._justify(self._facts(60, entity=lambda i: "e_%03d" % i))
        self.core.health.run()
        row = self.store._conn().execute(
            "SELECT results FROM health_runs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIn("ghost_facts", json.loads(row["results"])["sweeps"])


# ---------------------------------------------------------------------------
# 10. Per-run cost on a production-sized store
# ---------------------------------------------------------------------------
class TestPerRunCostIsBounded(_SweepCase):
    def test_a_sweep_run_on_a_100k_row_store_stays_bounded(self):
        """The bound has to hold at the size that produced the bug report, not
        just on a 150-row fixture. 100k active facts, one run of the default
        budget: the run must process exactly its budget and finish in well under
        a second, which a full-table materialisation cannot do."""
        self._facts(100000)
        self._resweep(budgets={"ghost_facts": 5000})
        t0 = time.time()
        ids, report = self._ghost_run()
        elapsed = time.time() - t0
        self.assertEqual(report["processed"], 5000)
        self.assertEqual(report["remaining"], 95000)
        self.assertEqual(report["total"], 100000)
        self.assertLess(elapsed, 5.0,
                        "one bounded run took %.2fs — it is reading the whole table"
                        % elapsed)


# ---------------------------------------------------------------------------
# 11. The H1 inertness exclusion stays narrow
# ---------------------------------------------------------------------------
class TestH1DumpExclusionIsNarrow(unittest.TestCase):
    """`tests/h1_store_dump.py` skips `meta` rows prefixed `sweep:`. That is a
    row the store really does gain, so the exclusion has to be justified rather
    than assumed — the probe exists to catch exactly this kind of new row.

    Three halves, really: the skip actually fires (a store with sweep state
    dumps no `sweep:` line), the sweep the H1 fixture flow runs really does
    write such a row (so the exclusion is exercised, not decorative), and every
    excluded row is pure telemetry — a fixed key set with no belief, event,
    session or entity identifier in it, so nothing memory-bearing can hide
    behind the skip."""

    TELEMETRY_KEYS = {"sweep", "processed", "remaining", "bounded",
                      "budget", "wrapped", "total", "cursor", "at"}

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="a9_h1_")
        self.core = ChronicleCore(self.home, CFG)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_canonicalize_writes_a_row_under_the_excluded_prefix(self):
        """`canonicalize` is the sweep the H1 fixture flow reaches, and it is
        why the dump gained a line at all. If it stopped writing sweep state the
        exclusion would be dead code silently guarding nothing."""
        sys.path.insert(0, str(Path(__file__).parent))
        from h1_store_dump import SWEEP_META_PREFIX
        self.core.curation._task_canonicalize({})
        keys = [k for (k,) in self.core.store._conn().execute(
            "SELECT key FROM meta WHERE key LIKE ?", (SWEEP_META_PREFIX + "%",)).fetchall()]
        self.assertTrue(keys, "nothing is being excluded; the skip is decorative")

    def test_the_dump_really_omits_the_excluded_rows(self):
        """The skip itself, exercised: sweep state exists in `meta`, and the
        canonical dump contains no line for it — while still containing the
        `meta` rows that are not sweep state."""
        sys.path.insert(0, str(Path(__file__).parent))
        from h1_store_dump import SWEEP_META_PREFIX, dump_store
        self.core.curation._task_canonicalize({})
        self.assertTrue(self.core.store.list_sweep_states(), "no sweep state to hide")
        lines = dump_store(self.core.store).splitlines()
        self.assertFalse([ln for ln in lines if SWEEP_META_PREFIX in ln],
                         "a sweep: row reached the byte-identity dump")
        self.assertTrue([ln for ln in lines if ln.startswith("meta\t")],
                        "the meta table vanished entirely — the skip is too wide")

    def test_every_excluded_row_is_telemetry_and_nothing_else(self):
        self.core.curation._task_canonicalize({})
        self.core.health.consistency_sweep()
        states = self.core.store.list_sweep_states()
        self.assertTrue(states)
        for name, state in states.items():
            self.assertEqual(set(state), self.TELEMETRY_KEYS,
                             "sweep state %r carries fields the exclusion never vetted" % name)
            blob = json.dumps(state)
            for marker in ("b_", "ev_", "ent_", "s_"):
                self.assertNotIn('"%s' % marker, blob,
                                 "sweep state %r looks like it carries an identifier" % name)


if __name__ == "__main__":
    unittest.main()
