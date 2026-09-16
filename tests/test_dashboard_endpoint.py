"""
Chronicle — the dashboard's one WRITE endpoint (A13).

`dashboard/plugin_api.py` is loaded BY FILE PATH by the dashboard plugin host,
so it cannot import the engine (there is no parent package, and putting the
plugin root on sys.path would shadow `context`, `provider` and `_base` for the
whole dashboard process). Every panel therefore reads the store with raw SQL,
which is fine for reads — a wrong number is visible.

One endpoint WRITES, and a write that only resembles the engine's write is not
fine. Before A13 it was POST /process-embeddings and it:

  * embedded nothing (it enqueues `extract`, which is a different task run by a
    different handler, one stage earlier in the pipeline);
  * wrote `payload` in a shape the engine's dedupe probe could not match, and
    deduped with `payload LIKE '%"<event_id>"%'` against PENDING rows only — so
    a job already claimed by the worker was enqueued a second time, and any
    event id that appeared as a substring of another payload was skipped;
  * stamped `created_at` with `datetime('now')` — "2026-09-10 12:34:56", a
    space instead of 'T', no milliseconds, no 'Z'. Rows are compared as TEXT, so
    such a job sorts before every job the engine ever wrote.

These tests pin the property that fixes all three at once: a row this endpoint
writes must be INDISTINGUISHABLE from one `store.enqueue_curation` writes.
"""

import ast
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.store import MemoryStore, now_iso

_PLUGIN_API = Path(__file__).parent.parent / "dashboard" / "plugin_api.py"

# now_iso()'s exact shape: RFC3339, UTC, millisecond precision, Z suffix (§5.4).
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _load_module():
    """Import plugin_api the way the dashboard host does — by path, with no
    parent package — recording the routes it declares.

    The fastapi stub is installed only if fastapi is genuinely absent, so this
    runs the same code on a machine that has it."""
    routes = []
    if "fastapi" not in sys.modules:
        try:
            import fastapi  # noqa: F401
        except Exception:
            stub = types.ModuleType("fastapi")

            class _APIRouter:
                def get(self, path, *a, **k):
                    routes.append(("GET", path))
                    return lambda fn: fn

                def post(self, path, *a, **k):
                    routes.append(("POST", path))
                    return lambda fn: fn

            stub.APIRouter = _APIRouter
            stub.Query = lambda default=None, **k: default
            sys.modules["fastapi"] = stub
    spec = importlib.util.spec_from_file_location("chronicle_plugin_api_a13", str(_PLUGIN_API))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, routes


class _DashboardCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="a13-dash-")
        db_dir = Path(self.dir) / "commons" / "db" / "chronicle"
        db_dir.mkdir(parents=True)
        self.db_path = str(db_dir / "chronicle.db")
        self.store = MemoryStore(self.db_path)
        self._prev_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = self.dir
        self.mod, self.routes = _load_module()

    def tearDown(self):
        if self._prev_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self._prev_home
        shutil.rmtree(self.dir, ignore_errors=True)

    def _observed(self, n):
        """`n` observed events with no extraction row — what the button finds."""
        with self.store.transaction() as conn:
            for i in range(n):
                conn.execute(
                    "INSERT INTO events(event_id, seq, type, payload, actor, owner, "
                    "trust_level, session_id, occurred_at, recorded_at) "
                    "VALUES(?,?,'observed','{}','user','default',3,'s1',?,?)",
                    ("e%d" % i, i + 1, now_iso(), now_iso()))

    def _jobs(self):
        return [dict(r) for r in self.store._conn().execute(
            "SELECT id, task, payload, status, created_at FROM curation_jobs ORDER BY id"
        ).fetchall()]


class TestTheEndpointIsNamedForWhatItDoes(_DashboardCase):
    def test_the_route_is_enqueue_extractions_and_the_old_name_is_gone(self):
        """Read off the decorators in the source rather than out of a router:
        whether fastapi is real or stubbed here depends on what else the suite
        imported first, and the route table must not."""
        paths = set()
        tree = ast.parse(_PLUGIN_API.read_text(encoding="utf-8"), filename=str(_PLUGIN_API))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.args and isinstance(dec.args[0], ast.Constant)):
                    paths.add((dec.func.attr.upper(), dec.args[0].value))
        self.assertIn(("POST", "/enqueue-extractions"), paths)
        self.assertNotIn("/process-embeddings", {p for _m, p in paths})

    def test_the_handler_that_embedded_nothing_is_gone(self):
        self.assertTrue(hasattr(self.mod, "enqueue_extractions"))
        self.assertFalse(hasattr(self.mod, "process_embeddings"))

    def test_the_status_panel_counts_exactly_what_the_button_acts_on(self):
        """A control whose preview number is computed differently from the
        control is a control an operator cannot trust."""
        self._observed(3)
        status = self.mod.get_status()
        self.assertEqual(status["store"]["enqueue_candidates"], 3)
        self.assertEqual(self.mod.enqueue_extractions()["enqueued"], 3)


class TestTheRowsAreIndistinguishableFromTheEngines(_DashboardCase):
    def test_the_payload_is_the_canonical_json_the_engine_writes(self):
        self._observed(1)
        self.assertEqual(self.mod.enqueue_extractions(), {"ok": True, "enqueued": 1})
        dash = self._jobs()[0]

        other = MemoryStore(self.db_path)
        other.enqueue_curation("extract", {"event_id": "e0", "session_id": "s1"})
        self.assertEqual(len(self._jobs()), 1,
                         "the engine did not recognise the dashboard's row as a duplicate: "
                         "payload %r" % dash["payload"])

    def test_the_engine_dedupes_against_a_dashboard_row_and_vice_versa(self):
        """Both directions, because the guard is the (task, payload) probe both
        sides run and the partial index that serves it."""
        self._observed(2)
        store = MemoryStore(self.db_path)
        self.assertIsNotNone(store.enqueue_curation(
            "extract", {"event_id": "e0", "session_id": "s1"}))
        # …now the dashboard finds e0 already queued and only adds e1.
        self.assertEqual(self.mod.enqueue_extractions()["enqueued"], 1)
        self.assertEqual(len(self._jobs()), 2)
        # …and a second press adds nothing at all.
        self.assertEqual(self.mod.enqueue_extractions()["enqueued"], 0)
        self.assertEqual(len(self._jobs()), 2)

    def test_it_dedupes_against_a_RUNNING_job_not_only_a_pending_one(self):
        """The old LIKE probe checked status='pending' only, so a job the worker
        had already claimed was queued a second time."""
        self._observed(1)
        store = MemoryStore(self.db_path)
        store.enqueue_curation("extract", {"event_id": "e0", "session_id": "s1"})
        claimed = store.claim_curation_job()
        self.assertEqual(self.store._conn().execute(
            "SELECT status FROM curation_jobs WHERE id=?", (claimed["id"],)
        ).fetchone()["status"], "running")
        self.assertEqual(self.mod.enqueue_extractions()["enqueued"], 0)
        self.assertEqual(len(self._jobs()), 1)

    def test_a_substring_collision_no_longer_suppresses_a_real_job(self):
        """`payload LIKE '%"e1"%'` also matched a payload mentioning e1 for any
        other reason. Exact-match dedupe cannot."""
        self._observed(2)
        store = MemoryStore(self.db_path)
        store.enqueue_curation("canonicalize", {"subjects": ["e0", "e1"]})
        self.assertEqual(self.mod.enqueue_extractions()["enqueued"], 2)

    def test_created_at_is_now_iso_not_sqlite_datetime_now(self):
        self._observed(1)
        self.mod.enqueue_extractions()
        stamp = self._jobs()[0]["created_at"]
        self.assertRegex(stamp, _ISO)
        self.assertEqual(len(stamp), len(now_iso()))
        self.assertNotIn(" ", stamp)

    def test_the_dashboards_stamp_orders_with_the_engines(self):
        """The reason the format matters: rows are compared as TEXT."""
        self._observed(1)
        before = now_iso()
        self.mod.enqueue_extractions()
        stamp = self._jobs()[0]["created_at"]
        self.assertGreaterEqual(stamp, before)
        self.assertLessEqual(stamp, now_iso())


class TestTheRowsActuallyRun(_DashboardCase):
    def test_a_dashboard_written_job_is_claimable_and_dispatchable(self):
        """The end of the chain: the worker claims it and resolves a handler, so
        it can never complete as 'no_handler' (A13's other half)."""
        from engine.curation import CurationWorker
        self._observed(1)
        self.mod.enqueue_extractions()
        store = MemoryStore(self.db_path)
        job = store.claim_curation_job()
        self.assertIsNotNone(job, "the dashboard's row was not claimable")
        self.assertEqual(job["task"], "extract")
        worker = CurationWorker.__new__(CurationWorker)
        self.assertTrue(callable(getattr(worker, "_task_%s" % job["task"], None)))

    def test_the_limit_is_bounded_and_respected(self):
        self._observed(5)
        self.assertEqual(self.mod.enqueue_extractions(limit=2)["enqueued"], 2)
        self.assertEqual(len(self._jobs()), 2)

    def test_no_database_is_reported_not_raised(self):
        os.environ["HERMES_HOME"] = os.path.join(self.dir, "nowhere")
        self.assertEqual(self.mod.enqueue_extractions(), {"ok": False, "error": "no_database"})


if __name__ == "__main__":
    unittest.main()
