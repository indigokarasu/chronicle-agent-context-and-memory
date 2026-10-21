"""
Chronicle — sqlite-vec support is gone; old configs and old stores keep working.

Vector search has one implementation: the in-memory float16 cache over the paged
brute-force scan (engine/vector_cache.py). The optional sqlite-vec backend mirrored
every NEW write into a `vec0` table that was never backfilled, so switching it on
over a populated store hid every vector already stored. It was removed rather than
fixed, and this file holds what removal must not break:

  (a) an old config that still says `vector_index.backend: sqlite-vec` loads,
      logs ONE warning, and retrieval still finds a stored vector;
  (b) the key is still declared, so the config-honesty guard accepts it;
  (c) a store that already holds a real `vec0` virtual table keeps working with
      the module absent: init, capture, retrieval, maintenance, a rebuild, the
      maintenance scripts, VACUUM, a backup, and the store move.

(c) needs a REAL vec0 table, so it needs `sqlite_vec` importable and an sqlite3
built with loadable-extension support. Apple's system Python is built without
it, so there (c) skips and says why. Run it under an interpreter that has both,
e.g. a throwaway venv:

    uv venv --python /opt/homebrew/bin/python3.13 /tmp/vec
    uv pip install --python /tmp/vec sqlite-vec pytest
    /tmp/vec/bin/python -m pytest tests/test_sqlite_vec_removed.py -q -p no:cacheprovider

Fixtures use obviously fake values.
"""

import contextlib
import io
import logging
import os
import re
import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _tmp_support import temp_home

from audit_config import audit, stale_dormant_declarations
from engine import migrate_paths as mp_mod
from engine.config import _DORMANT_WARNED, DECLARED_DORMANT, DEFAULTS, DORMANT, REFUSED_KEYS, Config
from engine.core import ChronicleCore
from engine.store import MemoryStore
from scripts.prune_vectors import main as prune_main
from scripts.prune_vectors import prune_orphans, prune_vectors
from scripts.requeue_hash_vectors import requeue

ROOT = Path(__file__).resolve().parent.parent

try:
    import sqlite_vec
except Exception:                      # not installed: (c) skips
    sqlite_vec = None

DIMS = 64
KEY = "vector_index.backend"
FACTS = ("The Acme Fake Co server room flooded on Tuesday.",
         "The backups were moved to the second rack.",
         "New dehumidifiers were ordered for the room.")
NEW_FACT = "The lobby was repainted in a shade of marmalade."


def _cfg(backend=None):
    cfg = {"embeddings": {"model": "hashing", "dimensions": DIMS}}
    if backend is not None:
        cfg["vector_index"] = {"backend": backend}
    return cfg


def _observe(core, text, session="s-vec"):
    core.capture.observe(text, "Understood.", session_id=session,
                         occurred_at="2026-01-01T00:00:00Z")


def _vector_only(core, query, limit=10):
    """retrieve_raw with full-text search switched off, so a hit can only have
    come from the vector scan."""
    with mock.patch.object(core.store, "fts_search_observed", return_value=[]):
        return core.retrieval.retrieve_raw(query, limit=limit)


def _warnings_about_sqlite_vec(build):
    """Run `build()` and return the WARNING records that name sqlite-vec."""
    records = []

    class _Catch(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Catch(level=logging.WARNING)
    log = logging.getLogger("chronicle")
    log.addHandler(handler)
    try:
        out = build()
    finally:
        log.removeHandler(handler)
    return out, [r for r in records
                 if r.levelno >= logging.WARNING and "sqlite-vec" in r.getMessage()]


# ==========================================================================
# nothing of it is left to load
# ==========================================================================

class TestNothingOfItRemains(unittest.TestCase):
    def test_the_module_is_gone(self):
        self.assertFalse((ROOT / "engine" / "vector_index.py").exists())
        with self.assertRaises(ImportError):
            import engine.vector_index  # noqa: F401

    def test_no_engine_or_script_loads_an_sqlite_extension(self):
        """The one way to bring it back is a line that loads the extension."""
        pattern = re.compile(r"import sqlite_vec|from sqlite_vec|enable_load_extension|\bVectorIndex\b")
        found = []
        for sub in ("engine", "scripts", "dashboard"):
            for path in (ROOT / sub).rglob("*.py"):
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if pattern.search(line):
                        found.append("%s:%d" % (path.relative_to(ROOT), n))
        for name in ("context.py", "provider.py", "__init__.py"):
            path = ROOT / name
            if path.exists() and pattern.search(path.read_text(encoding="utf-8")):
                found.append(name)
        self.assertEqual(found, [])

    def test_the_wiring_is_gone_from_the_objects(self):
        home = temp_home(prefix="vec-gone-")
        self.addCleanup(shutil.rmtree, home, True)
        core = ChronicleCore(home, _cfg())
        self.addCleanup(core.close)
        for obj in (core, core.store, core.retrieval):
            self.assertFalse(hasattr(obj, "vector_index"), type(obj).__name__)

    def test_diagnostics_reports_the_real_vector_count(self):
        home = temp_home(prefix="vec-diag-")
        self.addCleanup(shutil.rmtree, home, True)
        core = ChronicleCore(home, _cfg())
        self.addCleanup(core.close)
        core.initialize("s-vec", principal_id="tester")
        _observe(core, FACTS[0])
        info = core.diagnostics()["vector_index"]
        self.assertEqual(info, {"backend": "bruteforce", "total_vectors": 1})


# ==========================================================================
# (a) an old config that names it
# ==========================================================================

class TestAnOldConfigStillNamingSqliteVec(unittest.TestCase):
    def setUp(self):
        _DORMANT_WARNED.discard(KEY)       # the warning is once per process
        self.addCleanup(_DORMANT_WARNED.discard, KEY)
        self.home = temp_home(prefix="vec-cfg-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def _core(self, home=None, backend="sqlite-vec"):
        core = ChronicleCore(home or self.home, _cfg(backend))
        self.addCleanup(core.close)
        return core

    def test_init_logs_exactly_one_warning(self):
        core, hits = _warnings_about_sqlite_vec(self._core)
        self.assertEqual(len(hits), 1, [h.getMessage() for h in hits])
        self.assertEqual(hits[0].levelno, logging.WARNING)
        self.assertIn(KEY, hits[0].getMessage())
        # The rest of a session does not repeat it, nor does a second core.
        _, more = _warnings_about_sqlite_vec(lambda: (
            core.initialize("s-vec", principal_id="tester"),
            _observe(core, FACTS[0]),
            self._core(temp_home(prefix="vec-cfg2-"))))
        self.assertEqual(more, [])

    def test_the_default_and_bruteforce_do_not_warn(self):
        for backend in (None, "bruteforce"):
            _DORMANT_WARNED.discard(KEY)
            _, hits = _warnings_about_sqlite_vec(
                lambda b=backend: self._core(temp_home(prefix="vec-quiet-"), b))
            self.assertEqual(hits, [], backend)

    def test_retrieval_still_finds_a_stored_vector(self):
        core = self._core()
        core.initialize("s-vec", principal_id="tester")
        for text in FACTS:
            _observe(core, text)
        self.assertEqual(core.store.count_rows("observed_vectors"), len(FACTS))
        hits = _vector_only(core, "backups moved to the second rack")
        self.assertTrue(hits, "the vector scan found nothing")
        self.assertIn("backups", hits[0]["excerpt"])

    def test_the_setting_changes_nothing_about_what_retrieval_returns(self):
        """Not 'does not crash': the same answers, score for score, as the
        default config over the same events."""
        results = []
        for backend in ("sqlite-vec", None):
            core = self._core(temp_home(prefix="vec-same-"), backend)
            core.initialize("s-vec", principal_id="tester")
            for text in FACTS:
                _observe(core, text)
            results.append([(h["excerpt"], round(h["score"], 9))
                            for h in _vector_only(core, "dehumidifiers for the server room")])
        self.assertTrue(results[0])
        self.assertEqual(results[0], results[1])


# ==========================================================================
# (b) the config-honesty guard still accepts the key
# ==========================================================================

class TestTheKeyIsStillAcceptedByTheHonestyGuard(unittest.TestCase):
    def test_it_is_declared_and_declared_inert(self):
        self.assertEqual(DEFAULTS["vector_index"], {"backend": "bruteforce"})
        self.assertIn(KEY, DECLARED_DORMANT)
        self.assertGreaterEqual(len(DECLARED_DORMANT[KEY].strip()), 20)

    def test_the_audit_reports_it_dormant_not_unread(self):
        rows = audit()
        self.assertEqual(rows[KEY][0], "DORMANT")
        self.assertEqual(sorted(k for k, v in rows.items() if v[0] == "UNREAD"), [])

    def test_the_declaration_is_not_stale(self):
        """Nothing reads the key, so declaring it dormant is true. If an engine
        module ever reads it again, the declaration has to go."""
        self.assertNotIn(KEY, stale_dormant_declarations())

    def test_it_is_not_a_refused_key(self):
        self.assertNotIn(KEY, REFUSED_KEYS)
        cfg = Config({"vector_index": {"backend": "sqlite-vec"}})
        self.assertEqual(cfg.get(KEY), "sqlite-vec")

    def test_it_is_in_the_runtime_warning_list_for_the_removed_value_only(self):
        entries = {k: pred for k, pred, _why in DORMANT}
        self.assertIn(KEY, entries)
        self.assertTrue(entries[KEY]("sqlite-vec"))
        self.assertTrue(entries[KEY](" SQLite-Vec "))
        self.assertFalse(entries[KEY]("bruteforce"))


# ==========================================================================
# (c) a store that already holds a real vec0 table
# ==========================================================================

def _can_build_a_vec0_table():
    if sqlite_vec is None:
        return "sqlite_vec is not importable by this interpreter"
    if not hasattr(sqlite3.Connection, "enable_load_extension"):
        return "this interpreter's sqlite3 was built without loadable-extension support"
    return None


def _open_with_the_module(path):
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _build_a_store_with_vec0(home):
    """A Chronicle store holding FACTS whose observed vectors are mirrored into a
    real vec0 table, the way the removed backend left them. Returns its path."""
    core = ChronicleCore(home, _cfg())
    core.initialize("s-vec", principal_id="tester")
    for text in FACTS:
        _observe(core, text)
    core.process_pending()
    db = core.store.db_path
    core.close()
    conn = _open_with_the_module(db)
    try:
        conn.execute("CREATE VIRTUAL TABLE vec0 USING vec0("
                     "event_id TEXT PRIMARY KEY, embedding FLOAT[%d])" % DIMS)
        rows = conn.execute("SELECT event_id, embedding FROM observed_vectors").fetchall()
        conn.executemany("INSERT INTO vec0(event_id, embedding) VALUES(?, ?)", rows)
        conn.commit()
    finally:
        conn.close()
    return db


_SKIP = _can_build_a_vec0_table()


@unittest.skipIf(_SKIP, _SKIP or "")
class TestAStoreThatStillHoldsAVec0Table(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="vec-store-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.db = _build_a_store_with_vec0(self.home)
        # The fixture is a real vec0 table, and the module really is absent
        # from every connection the engine opens.
        conn = _open_with_the_module(self.db)
        try:
            self.mirrored = conn.execute("SELECT COUNT(*) FROM vec0").fetchone()[0]
            sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='vec0'").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(self.mirrored, len(FACTS))
        self.assertIn("VIRTUAL TABLE", sql.upper())

    def _core(self, backend=None):
        core = ChronicleCore(self.home, _cfg(backend))
        self.addCleanup(core.close)
        core.initialize("s-vec", principal_id="tester")
        return core

    def _vec0_rows(self):
        conn = _open_with_the_module(self.db)
        try:
            return conn.execute("SELECT COUNT(*) FROM vec0").fetchone()[0]
        finally:
            conn.close()

    def _assert_the_module_is_absent(self, core):
        with self.assertRaisesRegex(sqlite3.OperationalError, "no such module"):
            core.store._conn().execute("SELECT COUNT(*) FROM vec0").fetchone()

    # -- init, capture, retrieval ----------------------------------------

    def test_init_capture_and_retrieval_work_and_never_touch_it(self):
        for backend in (None, "sqlite-vec"):
            core = self._core(backend)
            self._assert_the_module_is_absent(core)
            _observe(core, NEW_FACT)
            core.process_pending()
            old = _vector_only(core, "backups moved to the second rack")
            new = _vector_only(core, "lobby repainted in marmalade")
            self.assertTrue(old and "backups" in old[0]["excerpt"], backend)
            self.assertTrue(new and "lobby" in new[0]["excerpt"], backend)
            core.close()
        # Nothing wrote to the table and nothing failed on it.
        self.assertEqual(self._vec0_rows(), self.mirrored)

    def test_an_unlearned_event_leaves_the_vector_table_alone(self):
        core = self._core()
        eid = core.store._conn().execute(
            "SELECT event_id FROM observed_vectors LIMIT 1").fetchone()[0]
        core.store.delete_observed_vector(eid)
        gone = core.store._conn().execute(
            "SELECT COUNT(*) FROM observed_vectors WHERE event_id=?", (eid,)).fetchone()[0]
        self.assertEqual(gone, 0)
        self.assertEqual(self._vec0_rows(), self.mirrored)

    # -- maintenance -------------------------------------------------------

    def test_maintenance_and_a_full_rebuild_work(self):
        core = self._core()
        core.process_pending()
        core.tick()
        core.health.run()
        core.store.truncate_projection()
        core.reducer.rebuild()
        core.process_pending()
        self.assertEqual(core.store.count_rows("observed_vectors"), len(FACTS))
        hits = _vector_only(core, "dehumidifiers for the server room")
        self.assertTrue(hits and "dehumidifiers" in hits[0]["excerpt"])
        self.assertEqual(self._vec0_rows(), self.mirrored)

    def test_prune_vectors_works_on_it(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("INSERT INTO observed_vectors(event_id, embedding, model, owner, created_at) "
                         "VALUES('ev_orphan', ?, 'hashing', 'tester', '')", (b"\0" * (4 * DIMS),))
            conn.commit()
        finally:
            conn.close()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(prune_orphans(self.db, dry_run=True), 1)
            self.assertEqual(prune_orphans(self.db), 1)
            self.assertEqual(prune_vectors(self.db, ["s-vec"], dry_run=True), len(FACTS))
            self.assertEqual(prune_main(["--db", self.db, "--session-prefix", "s-vec"]), 0)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM observed_vectors").fetchone()[0], 0)
        finally:
            conn.close()
        self.assertEqual(self._vec0_rows(), self.mirrored)

    def test_requeue_hash_vectors_works_on_it(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(requeue(self.db, dry_run=True), 0)
            self.assertEqual(requeue(self.db), 0)
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM observed_vectors").fetchone()[0], 0)
        finally:
            conn.close()
        self.assertEqual(self._vec0_rows(), self.mirrored)

    # -- VACUUM and backup paths ------------------------------------------

    def test_vacuum_checks_and_backup_work_without_the_module(self):
        core = self._core()
        core.close()
        copy = self.db + ".copy"
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            conn.execute("VACUUM")
            conn.execute("VACUUM INTO ?", (copy,))
            dst = sqlite3.connect(self.db + ".backup")
            try:
                conn.backup(dst)
                self.assertEqual(dst.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                                 conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            finally:
                dst.close()
        finally:
            conn.close()
        for path in (copy, self.db + ".backup", self.db):
            check = _open_with_the_module(path)
            try:
                self.assertEqual(check.execute("SELECT COUNT(*) FROM vec0").fetchone()[0],
                                 self.mirrored, path)
            finally:
                check.close()

    def test_a_store_move_carries_it_along(self):
        """engine/migrate_paths.py moves a store left at an older release's
        path: by hard link on one filesystem, by a checked backup copy across
        two. Both must hand back a store that opens and holds every event."""
        for cross_device in (False, True):
            base = temp_home(prefix="vec-move-")
            self.addCleanup(shutil.rmtree, base, True)
            legacy = os.path.join(base, "legacy", "chronicle.db")
            new = os.path.join(base, "profile", "chronicle.db")
            os.makedirs(os.path.dirname(legacy))
            shutil.copyfile(self.db, legacy)
            want = sqlite3.connect(legacy).execute("SELECT COUNT(*) FROM events").fetchone()[0]
            if cross_device:
                dev = mp_mod._device(legacy)
                seam = mock.patch.object(
                    mp_mod, "_device", side_effect=lambda p: dev if p == legacy else dev + 1)
            else:
                seam = contextlib.nullcontext()
            with seam:
                res = mp_mod.settle_db_path(new, legacy, home=os.path.join(base, "profile"))
            self.assertEqual(res.action, "copied" if cross_device else "moved", res)
            self.assertEqual(os.path.realpath(res.path), os.path.realpath(new))
            store = MemoryStore(res.path)
            try:
                self.assertEqual(store.count_rows("events"), want)
            finally:
                store.close()
            check = _open_with_the_module(res.path)
            try:
                self.assertEqual(check.execute("SELECT COUNT(*) FROM vec0").fetchone()[0],
                                 self.mirrored)
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
