"""
Chronicle — the curation_jobs CHECK and the CurationWorker handlers agree.

Ladder-10 A13. Three defects of one shape were live at the same time, and each
one was individually invisible:

  * `route` and `criticality` were values in the curation_jobs task CHECK with
    no `_task_route` / `_task_criticality` anywhere. An enqueue PASSED the
    schema, sat in the queue, was claimed, found no handler and completed as
    `error='no_handler'`. Nothing failed loudly; the queue just did nothing.
  * `contradiction` was a second CHECK value whose handler called
    `health.consistency_sweep()` — the same call `_task_consistency` makes. Two
    names for one sweep, and a scheduler that wired both would run it twice.
  * `federated.enqueue_candidates_for_review` enqueued the task name
    `federated_identity_review`, which the CHECK did NOT admit and no handler
    implemented. That call could only ever raise IntegrityError — and, had it
    been reached from `append_event`'s durable-capture transaction, would have
    aborted the enclosing job (I12).

The first two are the CHECK admitting a name nothing can run. The third is a
PRODUCER naming a task the CHECK forbids. They are the two directions of one
invariant, so this file asserts both directions plus the static producer scan
that would have caught the third at the call site.

Everything here is derived — from the live schema, from `dir()` on the worker,
from the AST of the shipped source — so it fails on the NEXT instance of this
defect without anyone remembering to update a list.
"""

import ast
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.curation import CurationWorker
from engine.store import (CURATION_TASKS, RETIRED_CURATION_TASKS,
                          RETIRED_TASK_ALIASES, MemoryStore)

_ROOT = Path(__file__).parent.parent

# Every shipped .py file — the engine, the two plugin adapters, the scripts and
# the dashboard. Tests are excluded on purpose: a test may legitimately enqueue
# a bogus task name to prove the schema rejects it.
_SHIPPED = sorted(
    p for p in _ROOT.rglob("*.py")
    if "tests" not in p.parts and ".git" not in p.parts
    and "__pycache__" not in p.parts)


def _check_tasks(conn) -> set:
    """The task names the LIVE table's CHECK admits, parsed from its DDL."""
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='curation_jobs'"
    ).fetchone()[0]
    body = sql.split("task IN (")[1].split(")")[0]
    return {part.strip().strip("'") for part in body.split(",")}


def _handler_tasks() -> set:
    return {name[len("_task_"):] for name in dir(CurationWorker)
            if name.startswith("_task_") and callable(getattr(CurationWorker, name))}


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="a13-consistency-")
        self.path = os.path.join(self.dir, "chronicle.db")
        self.store = MemoryStore(self.path)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# (1) the two directions of the invariant
# ---------------------------------------------------------------------------
class TestCheckAndHandlersAgree(_StoreCase):
    def test_every_task_the_CHECK_admits_has_a_dispatchable_handler(self):
        """Direction 1 — the `route`/`criticality` defect.

        Dispatchable, not merely present: run_once() resolves the handler with
        getattr(self, "_task_%s" % task) and calls it, so the assertion is made
        the same way the worker makes it, on an INSTANCE."""
        worker = CurationWorker.__new__(CurationWorker)   # no core needed to look up
        missing = []
        for task in sorted(_check_tasks(self.store._conn())):
            handler = getattr(worker, "_task_%s" % task, None)
            if handler is None or not callable(handler):
                missing.append(task)
        self.assertEqual(missing, [],
                         "the task CHECK admits %s, which run_once() would complete as "
                         "error='no_handler' — a job that can be queued and can never "
                         "run" % missing)

    def test_every_handler_names_a_task_the_CHECK_admits(self):
        """Direction 2 — a handler the schema would reject on enqueue."""
        admitted = _check_tasks(self.store._conn())
        orphans = sorted(_handler_tasks() - admitted)
        self.assertEqual(orphans, [],
                         "_task_%s exists but the CHECK rejects that name: every enqueue "
                         "raises IntegrityError, and inside append_event's transaction "
                         "(I12) that aborts the enclosing job" % orphans)

    def test_the_constant_the_DDL_is_generated_from_matches_both(self):
        """CURATION_TASKS is the single source of truth, so it must equal both
        the live CHECK and the handler set — otherwise the DDL and the code have
        agreed with each other while disagreeing with the constant."""
        self.assertEqual(set(CURATION_TASKS), _check_tasks(self.store._conn()))
        self.assertEqual(set(CURATION_TASKS), _handler_tasks())
        self.assertEqual(len(CURATION_TASKS), len(set(CURATION_TASKS)),
                         "duplicate task name in CURATION_TASKS")


# ---------------------------------------------------------------------------
# (2) the producer side — the federated_identity_review defect
# ---------------------------------------------------------------------------
class TestNoProducerNamesAnUnknownTask(unittest.TestCase):
    def _literal_enqueues(self):
        """Every `*.enqueue_curation("<literal>", ...)` in shipped source."""
        found = []
        for path in _SHIPPED:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name != "enqueue_curation" or not node.args:
                    continue
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((path.relative_to(_ROOT).as_posix(), node.lineno, arg.value))
        return found

    def test_the_scan_finds_the_real_call_sites(self):
        """A scan that matches nothing would pass vacuously forever."""
        calls = self._literal_enqueues()
        self.assertGreaterEqual(len(calls), 6, calls)
        self.assertIn("extract", {t for _f, _l, t in calls})

    def test_no_shipped_enqueue_names_a_task_the_schema_forbids(self):
        bad = [c for c in self._literal_enqueues() if c[2] not in CURATION_TASKS]
        self.assertEqual(bad, [],
                         "a producer enqueues a task the curation_jobs CHECK rejects: %s"
                         % bad)

    def test_the_defect_this_scan_was_written_for_is_gone(self):
        """`federated_identity_review` had no CHECK entry and no handler; the
        method that enqueued it had no caller either. Named explicitly so a
        re-introduction fails here with the reason attached."""
        self.assertNotIn("federated_identity_review", CURATION_TASKS)
        self.assertFalse(hasattr(CurationWorker, "_task_federated_identity_review"))
        import engine.federated as federated
        self.assertFalse(hasattr(federated.FederatedChannel, "enqueue_candidates_for_review"))
        # …and no shipped module still carries it as a live string. Docstrings
        # and comments are excluded deliberately: A13's own note in
        # engine/federated.py explains why the method is gone, and prose that
        # records a removal is not the removal failing.
        live = []
        for path in _SHIPPED:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)) and node.body:
                    first = node.body[0]
                    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                            and isinstance(first.value.value, str)):
                        docstrings.add(id(first.value))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings
                        and "federated_identity_review" in node.value):
                    live.append((path.relative_to(_ROOT).as_posix(), node.lineno))
        self.assertEqual(live, [], "the task name is still a live string: %s" % live)


# ---------------------------------------------------------------------------
# (3) the retired names really are refused, end to end
# ---------------------------------------------------------------------------
class TestRetiredTasksAreRefused(_StoreCase):
    def test_retired_names_are_not_live_names(self):
        self.assertEqual(set(RETIRED_CURATION_TASKS) & set(CURATION_TASKS), set())
        for task in RETIRED_CURATION_TASKS:
            self.assertFalse(hasattr(CurationWorker, "_task_%s" % task), task)

    def test_the_schema_now_rejects_an_enqueue_of_a_retired_task(self):
        """Before A13 this INSERT succeeded and the job completed as
        'no_handler'. The failure has moved from the drain (silent) to the
        enqueue (loud), which is the point of the change."""
        for task in RETIRED_CURATION_TASKS:
            with self.assertRaises(sqlite3.IntegrityError, msg=task):
                with self.store.transaction() as conn:
                    conn.execute(
                        "INSERT INTO curation_jobs(task,payload,created_at) "
                        "VALUES(?,'{}','2026-09-10T00:00:00.00Z')", (task,))

    def test_each_alias_target_is_itself_a_live_task(self):
        """A rename that pointed at a name the CHECK rejects would turn the
        migration into the very defect it repairs."""
        for old, new in RETIRED_TASK_ALIASES.items():
            self.assertIn(old, RETIRED_CURATION_TASKS)
            self.assertIn(new, CURATION_TASKS)
            self.assertTrue(hasattr(CurationWorker, "_task_%s" % new))


# ---------------------------------------------------------------------------
# (4) the same invariant, observed through the worker rather than the schema
# ---------------------------------------------------------------------------
class TestNoHandlerIsUnreachable(_StoreCase):
    def test_the_no_handler_branch_can_no_longer_be_reached_by_a_valid_row(self):
        """run_once()'s `no_handler` completion is the symptom A13 removes. It
        stays in the code as a guard, but no row the schema accepts can now
        reach it: enqueue every admitted task and assert none completes that
        way. (The handlers themselves are stubbed — this is about DISPATCH, not
        about what each task does.)"""
        worker = CurationWorker.__new__(CurationWorker)
        worker.store = self.store
        called = []
        for task in CURATION_TASKS:
            setattr(worker, "_task_%s" % task,
                    (lambda t: (lambda payload: called.append(t)))(task))
            self.store.enqueue_curation(task, {"probe": task})
        for _ in range(len(CURATION_TASKS)):
            self.assertTrue(worker.run_once())
        rows = self.store._conn().execute(
            "SELECT task, status, error FROM curation_jobs ORDER BY id").fetchall()
        self.assertEqual(len(rows), len(CURATION_TASKS))
        self.assertEqual([r["error"] for r in rows if r["error"]], [])
        self.assertEqual(sorted(called), sorted(CURATION_TASKS))


if __name__ == "__main__":
    unittest.main()
