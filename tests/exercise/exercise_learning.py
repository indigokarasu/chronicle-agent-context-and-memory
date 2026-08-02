"""
Chronicle — Learning-loop exercise (§u6.b).

Drives the intended loop synthetically against a real ChronicleCore and asserts
OBSERVABLE state — a policies row, a calibration_obs row, a utility value, a
fidelity transition, a confidence number — never a call graph. Where the loop
dead-ends, the test pins the exact dead-end rather than the intent.

Companion audit with file:line evidence: tests/exercise/WIRING-LEARNING.md.
Fixtures are deliberately fake (Pat Testley / Acme Fake Co / Fakeland).

Not collected by pytest (filename is not test_*). Run directly:
    /usr/bin/python3 tests/exercise/exercise_learning.py
"""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ.setdefault("CHRONICLE_EMBED_MODEL", "hashing")

from engine.core import ChronicleCore
from engine.errors import E_LEARN_BOUND

FINDINGS = []


def finding(tag, text):
    FINDINGS.append("FINDING %-4s %s" % (tag, text))


def _core(home, **cfg):
    base = {"embeddings": {"model": "hashing"}}
    base.update(cfg)
    core = ChronicleCore(home, base)
    core.initialize("s1", principal_id="assistant")
    return core


def _ingest_workplace(core):
    """Two ordinary sentences → 2 facts + 1 derived fact via the automatic path."""
    core.capture.observe("I work at Acme Fake Co", "ok", session_id="s1")
    core.capture.observe("My office is in downtown", "ok", session_id="s1")
    core.process_pending()


class _Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.core = _core(self.home)
        self.store = self.core.store

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)


# =============================================================================
# 1a. Credit assignment — retrieval_log → health recall gap
# =============================================================================

class ExerciseRetrievalLog(_Base):

    def test_retrieval_log_is_read_by_health_recall_gap(self):
        """retrieval_log IS queried: health._recall_gap counts it (health.py:54).

        Retracts the prior audit's "populated and never queried by anything" and the
        delete-the-table recommendation that followed from it."""
        for i in range(4):
            self.store.log_retrieval("q%d" % i, "*", top_score=0.5)
        self.store.log_miss("q-missed", "*", top_score=0.01)

        self.assertEqual(self.core.health._recall_gap(), 0.25)   # 1 miss / 4 retrievals
        results = self.core.health.run()
        self.assertEqual(results["extraction_recall_gap"], 0.25)

        # The denominator really is retrieval_log, not something else.
        self.store.log_retrieval("q4", "*", top_score=0.5)
        self.assertEqual(self.core.health._recall_gap(), 0.2)    # 1 / 5

    def test_recall_gap_is_not_a_rate(self):
        """DEFECT: numerator and denominator increment on disjoint answer() paths.

        log_miss (retrieval.py:367) fires on the Tier-2 *answered* return, which
        never calls log_retrieval — so misses can exceed retrievals and the
        "gap" exceeds 1.0."""
        _ingest_workplace(self.core)
        for q in ("Where do I work?", "What is the capital of Fakeland?", "Where is my office?"):
            self.core.retrieval.answer(q, principal="assistant")

        logged = self.store.count_rows("retrieval_log")
        misses = self.store.count_rows("search_misses")
        gap = self.core.health._recall_gap()
        self.assertGreater(misses, logged)
        self.assertGreater(gap, 1.0)
        finding("1a", "retrieval_log IS read  — health._recall_gap (health.py:54); "
                      "recall_gap=%s (>1: not a rate)" % gap)

    def test_health_run_has_no_production_trigger(self):
        """The reader exists; its trigger does not. Nothing enqueues a `health` job."""
        _ingest_workplace(self.core)
        for q in ("Where do I work?", "Who is Pat Testley?"):
            self.core.retrieval.answer(q, principal="assistant")
        self.core.curation.drain(500)

        self.assertEqual(self.store.count_rows("health_runs"), 0)
        self.assertEqual(self.store.count_rows("curation_jobs", "task='health'"), 0)
        finding("1a", "health.run() never triggered — health_runs rows after full "
                      "ingest+drain: %d" % self.store.count_rows("health_runs"))

        self.core.health.run()          # only an explicit call records one
        self.assertEqual(self.store.count_rows("health_runs"), 1)

    def test_retrieval_log_resolved_column_is_orphaned(self):
        """DEAD-END: nothing ever sets retrieval_log.resolved, and the search_misses
        resolve helpers (store.py:802/806) have zero callers anywhere."""
        self.store.log_retrieval("q", "*", top_score=0.9)
        rows = self.store._conn().execute("SELECT resolved FROM retrieval_log").fetchall()
        self.assertEqual([r["resolved"] for r in rows], [0])
        self.assertFalse(hasattr(self.store, "mark_retrieval_resolved"))


# =============================================================================
# 1b. Credit assignment — record_outcome → utility → decay
# =============================================================================

class ExerciseCreditAssignment(_Base):

    def test_utility_never_moves_in_production(self):
        """record_outcome has zero production callers, so utility stays at its default."""
        _ingest_workplace(self.core)
        for q in ("Where do I work?", "Where is my office?"):
            self.core.retrieval.answer(q, principal="assistant")
        self.core.curation.drain(500)

        seen = set()
        for table in ("facts", "episodes", "notes"):
            for row in self.store.query_beliefs(table, "1=1", (), limit=200):
                seen.add(row.get("utility"))
        self.assertEqual(sorted(seen), [0.0])
        finding("1b", "utility never written — distinct utility over a real corpus: %s"
                % sorted(seen))

    def test_record_outcome_ewma_is_correct_when_called_directly(self):
        """The arithmetic works; nothing calls it. utility = 0.8*prev + 0.2*signal."""
        self.store.upsert_belief("facts", {
            "belief_id": "b-fake-001", "entity_id": "pat-testley", "attribute": "employer",
            "predicate_canonical": "employer", "value": "Acme Fake Co", "status": "active",
            "domain": "user", "owner": "assistant", "confidence": 0.8, "utility": 0.5,
            "provenance": "{}", "qualifiers": "{}"})

        self.core.learning.record_outcome("b-fake-001", used=True, outcome=1.0)
        self.assertEqual(self.store.get_belief("facts", "b-fake-001")["utility"], 0.6)

        self.core.learning.record_outcome("b-fake-001", used=False)
        self.assertEqual(self.store.get_belief("facts", "b-fake-001")["utility"], 0.47)

        self.core.learning.record_outcome("no-such-belief", used=True)   # silent, no raise

    def test_utility_is_read_by_decay_with_an_inverted_sign(self):
        """DEFECT: forgetting.py:56 makes a USEFUL belief decay SOONER.

        utility_factor = max(0.25, 1.0 - utility) shrinks the decay threshold as
        utility rises, so wiring record_outcome today would forget the most-used
        beliefs up to 4x faster. Demonstrated through the real decay_sweep."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(days=20)).isoformat()
        for bid, util in (("b-idle", 0.0), ("b-useful", 0.9)):
            self.store.upsert_belief("facts", {
                "belief_id": bid, "entity_id": "pat-testley", "attribute": "employer",
                "predicate_canonical": "employer", "value": "Acme Fake Co", "status": "active",
                "domain": "general", "salience": "normal", "fidelity": "verbatim",
                "owner": "assistant", "confidence": 0.8, "utility": util,
                "created_at": old, "last_seen_at": old, "provenance": "{}", "qualifiers": "{}"})

        self.core.forgetting.decay_sweep(now=now)

        self.assertEqual(self.store.get_belief("facts", "b-idle")["fidelity"], "verbatim")
        self.assertEqual(self.store.get_belief("facts", "b-useful")["fidelity"], "gist")
        decayed = [json.loads(e["payload"])["belief_id"] for e in self.store._conn().execute(
            "SELECT payload FROM events WHERE type='decayed'").fetchall()]
        self.assertEqual(decayed, ["b-useful"])
        finding("1b", "decay sign inverted — utility=0.9 decays at 20d, utility=0.0 does not")

    def test_decay_has_no_production_trigger_either(self):
        """`decay` is a legal curation task with a handler that nothing enqueues."""
        _ingest_workplace(self.core)
        self.core.curation.drain(500)
        self.assertEqual(self.store.count_rows("curation_jobs", "task='decay'"), 0)


# =============================================================================
# 2. Calibration refit — the one wired loop, training backwards
# =============================================================================

class ExerciseCalibration(_Base):

    def _verify_all_active_facts(self, core):
        facts = core.store.query_beliefs("facts", "status='active'", (), limit=10)
        for f in facts:
            core.tools.dispatch("assistant", "chronicle_verify", {"belief_id": f["belief_id"]})
        core.curation.drain(100)
        return facts

    def test_verify_writes_calibration_obs(self):
        """The writer is reachable: chronicle_verify → _task_verify → bump_calibration."""
        _ingest_workplace(self.core)
        self.assertEqual(self.store.count_rows("calibration_obs"), 0)
        facts = self._verify_all_active_facts(self.core)
        self.assertTrue(facts)
        self.assertGreaterEqual(self.store.count_rows("calibration_obs"), 1)

    def test_verify_signal_is_pinned_refuted(self):
        """DEFECT: every correct belief verifies as `refuted`.

        _task_verify reads prov["source_event"] (curation.py:239), which
        reducer._insert_belief set to the belief's own `asserted` event
        (reducer.py:393). That payload has no `excerpt`, so the span check always
        fails. The excerpt is one hop away via get_justifications."""
        _ingest_workplace(self.core)
        facts = self._verify_all_active_facts(self.core)

        obs = [dict(r) for r in self.store._conn().execute("SELECT * FROM calibration_obs")]
        n = sum(o["n"] for o in obs)
        correct = sum(o["correct"] for o in obs)
        self.assertGreater(n, 0)
        self.assertEqual(correct, 0)

        statuses = {json.loads(e["payload"])["status"] for e in self.store._conn().execute(
            "SELECT payload FROM events WHERE type='verified'").fetchall()}
        self.assertEqual(statuses, {"refuted"})

        # …yet the value really is in the source text, reachable via the justification.
        for f in facts:
            support = (self.store.get_justifications(f["belief_id"]) or [{}])[0].get("support", "")
            ev = self.store.get_event(support)
            self.assertIsNotNone(ev, "belief has no justification event")
            self.assertEqual(ev["type"], "observed")
            payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
            self.assertIn(f["value"].lower(), payload.get("excerpt", "").lower())
        finding("2", "verify signal pinned — %d obs, %d correct, on facts whose value IS "
                     "in the excerpt" % (n, correct))

    def test_calibration_measurably_degrades_correct_answers(self):
        """The reader IS live: once min_obs is met, the pinned-refuted signal drags
        every answer's confidence down. Stock config except calibration.min_obs."""
        home = tempfile.mkdtemp()
        try:
            core = _core(home, calibration={"min_obs": 2})
            _ingest_workplace(core)
            before_cal = core.retrieval.calibrator.calibrate(0.75, "session_transcript")
            before_ans = core.retrieval.answer("Where do I work?", principal="assistant")["confidence"]

            self._verify_all_active_facts(core)

            after_cal = core.retrieval.calibrator.calibrate(0.75, "session_transcript")
            after_ans = core.retrieval.answer("Where do I work?", principal="assistant")["confidence"]

            self.assertEqual(before_cal, 0.75)          # identity below min_obs
            self.assertLess(after_cal, before_cal)      # …and a real remap above it
            self.assertLess(after_ans, before_ans)
            finding("2", "calibration IS live  — calibrate(0.75): %s -> %s; answer confidence "
                         "%s -> %s" % (before_cal, after_cal, before_ans, after_ans))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_refit_every_config_key_has_no_reader(self):
        """calibration.refit_every (config.py:138) is dead config — calibrate()
        recomputes from all observations on every call; no batched refit exists."""
        self.assertEqual(self.core.cfg.get("calibration.refit_every"), 100)
        self.assertFalse(hasattr(self.core.learning, "refit"))
        self.assertFalse(hasattr(self.core.retrieval.calibrator, "refit"))


# =============================================================================
# 3. Rule precision auto-disable
# =============================================================================

class ExerciseRulePrecision(_Base):

    def test_precision_accrues_automatically_but_cannot_vary(self):
        """The writer is automatic (inline derive, curation.py:134-136) and the
        signal is a constant: _bump_precision's only call site (derivation.py:179)
        never passes correct=, and it defaults to True."""
        _ingest_workplace(self.core)
        rules = [r for r in self.store.get_derivation_rules(enabled_only=False)
                 if (r["precision_n"] or 0) > 0]
        self.assertTrue(rules, "no rule fired — the automatic derive path did not run")
        for r in rules:
            self.assertEqual(r["precision_correct"], r["precision_n"])

        rate = self.core.health._bad_derivation_rate()
        self.assertEqual(rate, 0.0)
        self.assertEqual(self.core.health.run()["bad_derivation_rate"], 0.0)
        finding("3", "precision pinned     — %s n=%d correct=%d; bad_derivation_rate=%s"
                % (rules[0]["rule_id"], rules[0]["precision_n"], rules[0]["precision_correct"], rate))

    def test_auto_disable_logic_is_correct_but_unreachable(self):
        """Hand-seed the input production can never produce: the reader works.
        That is why unit coverage never caught the pinned signal."""
        self.store.upsert_derivation_rule({
            "rule_id": "fake-rule-001", "name": "Fake test rule", "enabled": 1,
            "pattern": json.dumps(["works_at"]), "guards": "entity", "conclusion": "scoped",
            "scope": "reified", "materialize": "high_value",
            "precision_n": 15, "precision_correct": 3})

        self.core.learning.auto_disable_low_precision_rules()
        self.assertEqual(self.store.get_derivation_rule("fake-rule-001")["enabled"], 0)

        # …and the same call is a no-op on every rule the engine actually produces.
        _ingest_workplace(self.core)
        live = [r for r in self.store.get_derivation_rules(enabled_only=True)
                if (r["precision_n"] or 0) > 0]
        self.core.learning.auto_disable_low_precision_rules()
        for r in live:
            self.assertEqual(self.store.get_derivation_rule(r["rule_id"])["enabled"], 1)

    def test_auto_disable_has_no_production_caller(self):
        """Reader with zero callers — verified by source scan, not by grep prose."""
        root = Path(__file__).parent.parent.parent
        hits = []
        for path in sorted(list((root / "engine").glob("*.py")) +
                           [root / "provider.py", root / "context.py", root / "__init__.py"] +
                           sorted((root / "scripts").glob("*.py"))):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if "auto_disable_low_precision_rules" in line and "def " not in line:
                    hits.append("%s:%d" % (path.name, i))
        self.assertEqual(hits, [], "unexpected caller(s): %s" % hits)


# =============================================================================
# 4. Policy champion/challenger
# =============================================================================

class ExercisePolicy(_Base):

    def test_propose_policy_persists_an_inactive_challenger(self):
        version = self.core.learning.propose_policy(
            "rrf_weights", {"fts": 0.05, "vector": 0.10}, parent_version="baseline-fake-001")
        row = self.store.get_policy(version)
        self.assertTrue(version.startswith("rrf_weights-"))
        self.assertEqual(row["active"], 0)
        self.assertEqual(row["kind"], "rrf_weights")
        self.assertEqual(json.loads(row["params"]), {"fts": 0.05, "vector": 0.10})
        self.assertEqual(row["parent_version"], "baseline-fake-001")

    def test_bounds_are_enforced(self):
        with self.assertRaises(E_LEARN_BOUND) as ctx:
            self.core.learning.propose_policy("rrf_weights", {"fts": 0.99})
        self.assertIn("exceeds magnitude cap", str(ctx.exception))

        with self.assertRaises(E_LEARN_BOUND) as ctx:
            self.core.learning.propose_policy("nonexistent_dim", {"x": 0.1})
        self.assertIn("not in mutable set", str(ctx.exception))

        v = self.core.learning.propose_policy("rrf_weights", {"fts": 0.1})
        with self.assertRaises(E_LEARN_BOUND) as ctx:
            self.core.learning.activate_policy(v, beats_champion=False)
        self.assertIn("did not beat champion", str(ctx.exception))

    def test_activate_policy_preserves_the_challenger(self):
        """Regression for the one engine fix in this pass: activation used to pass
        kind=""/params="{}"/parent_version="" to upsert_policy, whose ON CONFLICT
        clause is built from the keys handed to it — so activating a policy blanked
        its own record."""
        version = self.core.learning.propose_policy(
            "rrf_weights", {"fts": 0.1}, parent_version="baseline-fake-001")
        self.core.learning.activate_policy(version, beats_champion=True)

        row = self.store.get_policy(version)
        self.assertEqual(row["active"], 1)
        self.assertEqual(row["kind"], "rrf_weights")
        self.assertEqual(json.loads(row["params"]), {"fts": 0.1})
        self.assertEqual(row["parent_version"], "baseline-fake-001")

    def test_activate_unknown_version_is_rejected(self):
        with self.assertRaises(E_LEARN_BOUND) as ctx:
            self.core.learning.activate_policy("rrf_weights-deadbeef", beats_champion=True)
        self.assertIn("no such challenger", str(ctx.exception))
        self.assertEqual(self.store.count_active_policies(), 0)

    def test_max_active_deltas_cap(self):
        for i in range(8):
            v = self.core.learning.propose_policy("rrf_weights", {"fts": 0.01 * (i + 1)})
            self.core.learning.activate_policy(v, beats_champion=True)
        self.assertEqual(self.store.count_active_policies(), 8)

        v9 = self.core.learning.propose_policy("rrf_weights", {"fts": 0.09})
        with self.assertRaises(E_LEARN_BOUND) as ctx:
            self.core.learning.activate_policy(v9, beats_champion=True)
        self.assertIn("max active deltas exceeded", str(ctx.exception))

    def test_active_policy_has_zero_runtime_effect(self):
        """DEAD-END: store.get_active_policy has no callers, so an active delta at
        the magnitude cap changes nothing observable about retrieval."""
        _ingest_workplace(self.core)
        query = "Where do I work?"

        def ranked():
            return [(r["belief_id"], round(r["score"], 6))
                    for r in self.core.retrieval.search(query, limit=10, principal="assistant")]

        before = ranked()
        version = self.core.learning.propose_policy(
            "rrf_weights", {"fts": 0.15, "vector": -0.15})     # at the cap, both directions
        self.core.learning.activate_policy(version, beats_champion=True)
        self.assertIsNotNone(self.store.get_active_policy("rrf_weights"))

        after = ranked()
        self.assertTrue(before, "search returned nothing — test would be vacuous")
        self.assertEqual(before, after)
        finding("4", "policies inert       — activating an rrf_weights delta leaves "
                     "search() identical")


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    print("\n" + "=" * 78)
    for line in FINDINGS:
        print(line)
    print("=" * 78)
    print("See tests/exercise/WIRING-LEARNING.md for the file:line audit.")
    sys.exit(0 if result.wasSuccessful() else 1)
