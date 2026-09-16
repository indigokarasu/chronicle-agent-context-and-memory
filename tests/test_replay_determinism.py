"""
Chronicle — Ladder 10 A4: the projection is a pure function of the event log.

The premise (I3, §7.3) is that raw events are the truth and every projection
table is derived: `truncate_projection()` + a full replay must put the store
back exactly as it was, byte for byte. It did not. Four side tables minted a
`uuid4()` row id and read the wall clock inside handlers the REDUCER runs —
`contradictions`, `corrections`, `supersede_candidates`, `identity_candidates`
— and three vector tables (`observed_vectors`, `memory_vectors`,
`query_proxy_vectors`) stamped `created_at` from `now_iso()` on the same path.
So a rebuild produced an equivalent projection, never an identical one, and
nothing downstream could reference one of those rows by id across a rebuild
(which is exactly why F4d had to address an adjudication by dedupe key).

What makes this file different from the tests that were already here: it pins
NOTHING. `tests/h1_store_dump.py` monkeypatches `uuid.uuid4` and every module's
`now_iso` before it dumps a store, and `test_build.test_rebuild_identical`
snapshots five belief columns. Between them, the defect was invisible: a test
that pins the source of nondeterminism it is meant to detect cannot detect it.
Here the real clock and the real `uuid4` are in play for the whole run, the
snapshot is EVERY column of EVERY table `truncate_projection` empties (blobs
included, digested only so the failure output stays readable), and the
mutation test at the bottom re-introduces `uuid4` to prove the assertion is
load-bearing.

Fixtures are obviously fake (Sam Vimes, Pat Testley, Acme Fake Co) per the
shared Ladder 9/10 fixture rule, and every event carries an explicit 2026-01
`occurred_at` so "did this timestamp come from the log or from the clock?" is
answerable by looking at the value.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from engine import store as store_mod
from engine.capture import CaptureEngine
from engine.config import Config
from engine.embeddings import HashingEmbedder
from engine.reducer import Reducer
from engine.store import PROJECTION_TABLES, MemoryStore

# The five-hash-seed subprocess harness already exists in this tree: ladder 9
# F1 established it in tests/test_precision_packing.py after a `set` join made
# the embedded query text per-process. Its seed set is imported rather than
# re-typed, so the two cross-process checks cannot drift apart, and so "five
# seeds" means the same five everywhere.
# (imported as a MODULE, not `from ... import TheClass`: pytest collects any
# unittest.TestCase it finds in a module's namespace whatever it is named, so
# importing the class itself would silently re-run F1's two tests here.)
import test_precision_packing as _f1

HASH_SEEDS = _f1.TestTheEmbeddedQueryTextIsProcessStable.SEEDS

# One name, two starkly different lives (the split risk) -- borrowed verbatim
# from tests/test_identity_evidence.py, where the hashing embedder's geometry
# against these strings is asserted in band.
VIMES_BAKER = ("bakes sourdough loaves before dawn at the village bakery, "
               "dusting flour across wooden proving trays")
VIMES_ASTRONAUT = ("piloted the orbital docking module during a spacewalk, "
                   "monitoring thruster telemetry from mission control")
# Two differently-spelled records, one job (the merge risk).
TESTLEY_CONTEXT = ("coordinates logistics at Acme Fake Co from the Dublin office "
                   "and runs the Tuesday inventory review")

# Every event's occurred_at is fixed and in the past. `recorded_at`, by
# contrast, IS a wall-clock reading -- taken once, by capture, and written
# durably into the event. That distinction is the whole point: a timestamp read
# at CAPTURE time is part of the log and a replay reproduces it; a timestamp
# read at REDUCE time is not, and a replay cannot. So the check below is "is
# this value in the log", not "is this value old".
def _at(day: int, hour: int) -> str:
    return "2026-01-%02dT%02d:00:00.00Z" % (day, hour)


def log_timestamps(store) -> frozenset:
    """Every timestamp the event log itself carries."""
    out = set()
    for e in store.iter_events_since(0):
        for field in ("occurred_at", "recorded_at"):
            if e.get(field):
                out.add(e[field])
    return frozenset(out)

# The four tables A4 is about, and the id prefix each now derives.
SIDE_TABLES = {
    "contradictions": "con_",
    "corrections": "cor_",
    "supersede_candidates": "sup_",
    "identity_candidates": "idc_",
}


def install_lying_clock():
    """Replace `now_iso` EVERYWHERE with a clock that returns a different,
    obviously-wrong value on every call; returns the undo callable.

    Patching `engine.store.now_iso` alone would not do it: seven engine modules
    do `from .store import now_iso`, so each holds its own binding — reducer.py
    has eight call sites of its own. A mutation that only reached store.py
    would leave every reduce-time clock read in the reducer untested, which is
    the half A4 is about. So the patch sweeps module bindings the same way
    tests/h1_store_dump.py does, in the opposite direction: that one freezes
    the clock to hide time, this one makes it scream.
    """
    stamps = iter(["2099-%02d-%02dT%02d:00:00.00Z" % ((i % 12) + 1, (i % 28) + 1, i % 24)
                   for i in range(200000)])

    def _liar():
        return next(stamps)

    patched = []
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "") or ""
        if not (name == "provider" or name == "context" or name.startswith("engine")):
            continue
        if hasattr(module, "now_iso"):
            patched.append((module, module.now_iso))
            module.now_iso = _liar

    def _undo():
        for module, original in patched:
            module.now_iso = original

    assert len(patched) >= 5, "the lying clock patched almost nothing: %d" % len(patched)
    return _undo


def _fact(cap, entity_id, pred, body, src, at, *, name="", domain="user"):
    key = {"entity_id": entity_id, "predicate_canonical": pred, "attribute": pred,
           "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": domain}
    if name:
        key["entity_name"] = name
    return cap.append("asserted",
                      {"kind": "fact", "key": key, "body": body, "confidence": 0.9,
                       "source_event": src, "source_type": "user_direct", "domain": domain},
                      actor="user", owner="default", trust_level=4, occurred_at=at)


def build_log(cap, store):
    """Drive one capture flow that populates ALL FOUR side tables.

    Deliberately not a "typical" transcript: each step exists because it is the
    only path to one of the tables under test, and a determinism test over a
    fixture that leaves three of them empty proves nothing about them.
    """
    # observed -> observed_vectors, observed_fts
    cap.observe("My name is Pat Testley and I work at Acme Fake Co.", "Noted, Pat.",
                session_id="s-a4", occurred_at=_at(1, 1))

    # identity_candidates(split): one entity, two incompatible mention contexts
    _fact(cap, "sam_vimes", "day_work", VIMES_BAKER, "ev_baker", _at(1, 2), name="Sam Vimes")
    _fact(cap, "sam_vimes", "night_work", VIMES_ASTRONAUT, "ev_astro", _at(1, 3))
    # identity_candidates(merge): two entities, one shared mention context
    _fact(cap, "ent_pat_alpha", "role", TESTLEY_CONTEXT, "ev_alpha", _at(2, 1))
    _fact(cap, "ent_pat_beta", "role", TESTLEY_CONTEXT, "ev_beta", _at(2, 2))

    # contradictions: same key, different value, domain='user' -> flag_for_review.
    # entity_name + a templated attribute also gives query_proxy_vectors rows.
    _fact(cap, "pat_testley", "works_at", "Acme Fake Co", "ev_w1", _at(3, 1),
          name="Pat Testley")
    _fact(cap, "pat_testley", "works_at", "Beta Fake Inc", "ev_w2", _at(3, 2),
          name="Pat Testley")

    # supersede_candidates: same subject, near-identical text, different value
    # (the rig lowers curation.supersede_similarity -- 0.82 is dormant under
    # the hashing embedder, see the ctx_eval note in CHANGELOG F2X).
    _fact(cap, "acme_corp", "hq", "the head office sits beside the canal in Dublin",
          "ev_h1", _at(4, 1), name="Acme Fake Co")
    _fact(cap, "acme_corp", "hq_note", "the head office sits beside the canal in Cork",
          "ev_h2", _at(4, 2), name="Acme Fake Co")

    # corrections, path 1: an explicit `corrected` event
    day_work = store.query_beliefs("facts", "predicate_canonical='day_work'")[0]
    cap.append("corrected", {"belief_id": day_work["belief_id"], "reason": "user_fixed",
                             "new_body": "bakes rye loaves at the village bakery",
                             "source_ref": "ev_fix"},
               actor="user", owner="default", occurred_at=_at(5, 1))

    # corrections, path 2: the revision cascade -- a derived belief loses its
    # premise, which is the recursive `_cascade` write path.
    premise = store.query_beliefs("facts", "predicate_canonical='hq'")[0]["belief_id"]
    cap.append("derived", {"kind": "note", "key": {"note_type": "belief", "subject": "acme_corp"},
                           "body": "Acme Fake Co is canal-side", "rule_id": "r_canal",
                           "premises": [premise], "confidence": 0.6, "status": "active"},
               actor="agent", owner="default", occurred_at=_at(5, 2))
    cap.append("retracted", {"belief_id": premise, "reason": "premise withdrawn"},
               actor="user", owner="default", occurred_at=_at(5, 3))

    # contradictions, path 2: the explicit `contradicted` event
    works_at = store.query_beliefs("facts", "predicate_canonical='works_at' AND status='active'")[0]
    cap.append("contradicted", {"belief_id": works_at["belief_id"],
                                "conflicting_event": "ev_rumour", "detail": "reported elsewhere"},
               actor="agent", owner="default", occurred_at=_at(6, 1))


def snapshot(store) -> str:
    """Every column of every table `truncate_projection` empties, canonically.

    Rows are sorted as rendered text rather than by a chosen key, so a table
    with no id column (memory_vectors, entity_centroids) is covered too, and
    blobs are digested — their exact bytes are still compared, just not printed.
    """
    conn = store._conn()
    lines = []
    for table in PROJECTION_TABLES:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]
        rendered = []
        for row in conn.execute("SELECT * FROM %s" % table).fetchall():
            cells = []
            for i in range(len(cols)):
                v = row[i]
                if isinstance(v, (bytes, bytearray)):
                    v = "blob:" + hashlib.sha256(bytes(v)).hexdigest()[:32]
                cells.append("%s=%r" % (cols[i], v))
            rendered.append(" | ".join(cells))
        for line in sorted(rendered):
            lines.append(table + "\t" + line)
    return "\n".join(lines)


class _Rig(unittest.TestCase):
    """Store + hashing embedder + capture — the real write path, unpinned.

    No frozen clock, no fake uuid4, no PYTHONHASHSEED control. Whatever the
    production code reads from the environment, it reads here.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="a4-replay-")
        self.store, self.reducer, self.cap = self._open("chronicle.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _open(self, name):
        store = MemoryStore(os.path.join(self.dir, name))
        # 0.82 (the shipped default) never fires under the hashing embedder, so
        # supersede_candidates would be empty and this test would silently stop
        # covering one of the four tables.
        cfg = Config({"curation": {"supersede_similarity": 0.3}})
        reducer = Reducer(store, HashingEmbedder(dimensions=256), cfg)
        store.reducer = reducer
        return store, reducer, CaptureEngine(store, reducer)

    def _populated(self):
        build_log(self.cap, self.store)
        counts = {t: self.store._conn().execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                  for t in SIDE_TABLES}
        for table, n in counts.items():
            self.assertGreater(n, 0, "fixture wrote no %s rows -- this test would pass "
                                     "vacuously for that table" % table)
        return counts


class TestReplayIsByteIdentical(_Rig):

    def test_truncate_and_replay_reproduces_every_projection_byte(self):
        """The acceptance property, with nothing pinned."""
        self._populated()
        before = snapshot(self.store)
        self.assertTrue(before.strip())

        self.store.truncate_projection()
        self.assertEqual(snapshot(self.store).strip(), "",
                         "truncate_projection left rows behind; the replay below "
                         "would be comparing survivors, not re-derivations")
        self.reducer.rebuild()

        after = snapshot(self.store)
        if before != after:
            b, a = before.split("\n"), after.split("\n")
            diff = [("-%s\n+%s" % (x, y)) for x, y in zip(b, a) if x != y][:6]
            self.fail("replay is not byte-identical (%d/%d lines differ)\n%s"
                      % (sum(1 for x, y in zip(b, a) if x != y), len(b), "\n".join(diff)))

    def test_a_second_replay_changes_nothing_either(self):
        """Idempotence, not just single-rebuild agreement: a projection that is
        a pure function of the log cannot drift on the third derivation."""
        self._populated()
        self.reducer.rebuild()
        once = snapshot(self.store)
        self.reducer.rebuild()
        self.assertEqual(once, snapshot(self.store))


class TestIdsAreDerivedNotMinted(_Rig):

    def test_side_table_ids_are_content_hashes(self):
        """Every id in the four tables is `<prefix>_<64 hex>` and parses as no
        UUID. This is the direct mutation guard: swap any of them back to
        `uuid4()` and this fails on shape alone, before byte-identity even
        gets a chance to."""
        self._populated()
        for table, prefix in SIDE_TABLES.items():
            rows = self.store._conn().execute("SELECT id FROM %s" % table).fetchall()
            self.assertTrue(rows)
            for row in rows:
                rid = row["id"]
                self.assertTrue(rid.startswith(prefix),
                                "%s.id %r is not a derived id" % (table, rid))
                digest = rid[len(prefix):]
                self.assertEqual(len(digest), 64, "%s.id %r is not a content hash" % (table, rid))
                self.assertTrue(all(c in "0123456789abcdef" for c in digest))
                with self.assertRaises(ValueError, msg="%s.id %r parses as a uuid" % (table, rid)):
                    uuid.UUID(rid)

    def test_projection_timestamps_come_from_the_event_log(self):
        """No `created_at` in the four side tables, or in the three vector
        tables the reducer writes, may be a wall-clock reading. Each must be
        one of the fixture's own event timestamps.

        This is the half that byte-identity alone would miss: `now_iso()` has
        10 ms resolution, so a truncate+replay fast enough to land in the same
        centisecond would agree by luck. Checking the VALUE does not depend on
        how long the replay took.
        """
        self._populated()
        conn = self.store._conn()
        known = log_timestamps(self.store)
        checked = 0
        for table in list(SIDE_TABLES) + ["observed_vectors", "memory_vectors",
                                          "query_proxy_vectors"]:
            for row in conn.execute("SELECT created_at FROM %s" % table).fetchall():
                self.assertIn(row["created_at"], known,
                              "%s.created_at %r is in no event -- the reducer read the "
                              "clock" % (table, row["created_at"]))
                checked += 1
        self.assertGreater(checked, 10)

    def test_two_independent_stores_from_one_log_agree(self):
        """Cross-store equality: replay the SAME events into a second, freshly
        created database and every projection byte — ids included — matches.

        A within-store rebuild can only prove the reducer is repeatable in one
        process against one file. This is the property a distributed or
        re-hydrated store actually needs: the id of a contradiction is a fact
        about the log, not about which machine folded it.
        """
        self._populated()
        first = snapshot(self.store)

        other_store, other_reducer, _ = self._open("second.db")
        for event in self.store.iter_events_since(0):
            other_store.append_event(dict(event))
        self.assertEqual(first, snapshot(other_store),
                         "a second store built from the same log differs")
        # And it survives its own rebuild, from a log it did not itself capture.
        other_reducer.rebuild()
        self.assertEqual(first, snapshot(other_store))


class TestTheAssertionIsLoadBearing(_Rig):
    """Mutation tests. Each re-introduces the exact defect A4 removed and
    asserts the byte-identity check above goes RED — because a determinism
    test that would pass with the bug back in is not a test."""

    def _replay_snapshots(self):
        self._populated()
        before = snapshot(self.store)
        self.reducer.rebuild()
        return before, snapshot(self.store)

    def test_uuid4_ids_break_byte_identity(self):
        real = store_mod.projection_row_id
        store_mod.projection_row_id = lambda prefix, key: "%s_%s" % (prefix, uuid.uuid4().hex)
        try:
            before, after = self._replay_snapshots()
        finally:
            store_mod.projection_row_id = real
        self.assertNotEqual(before, after,
                            "re-introducing uuid4 row ids did NOT fail the replay check -- "
                            "the check is vacuous")

    def test_replay_under_a_lying_clock_is_still_byte_identical(self):
        """The clock half. Capture runs on the real clock (its readings become
        part of the log, legitimately); the REPLAY then runs with `now_iso`
        replaced by a clock that returns a different, obviously-wrong value on
        every call. Any reducer path that still reads the wall clock shows up
        as a changed byte immediately, instead of hiding behind now_iso()'s
        10 ms resolution and a fast rebuild."""
        self._populated()
        before = snapshot(self.store)

        undo = install_lying_clock()
        try:
            self.reducer.rebuild()
        finally:
            undo()
        self.assertEqual(before, snapshot(self.store),
                         "the replay read the wall clock: a projection row moved when "
                         "now_iso() started lying")

    def test_the_lying_clock_would_catch_the_old_behaviour(self):
        """...and the same lying clock DOES move a row when the pre-A4 write
        path is put back, so the test above is not passing because the clock
        patch is inert."""
        self._populated()
        before = snapshot(self.store)

        # Pre-A4 shape: the reducer's created_at argument is discarded and the
        # clock is read inside the handler instead.
        original_open = store_mod.MemoryStore.open_contradiction

        def _pre_a4_open(self_, belief_a, belief_b, detail="", source="", created_at=""):
            return original_open(self_, belief_a, belief_b, detail, source="",
                                 created_at=store_mod.now_iso())

        store_mod.MemoryStore.open_contradiction = _pre_a4_open
        undo = install_lying_clock()
        try:
            self.reducer.rebuild()
        finally:
            undo()
            store_mod.MemoryStore.open_contradiction = original_open
        self.assertNotEqual(before, snapshot(self.store),
                            "restoring the reduce-time clock read did NOT move the "
                            "snapshot -- the lying-clock mutation is inert")


class TestCrossProcessStability(_Rig):
    """The PYTHONHASHSEED sibling (A15). ONE captured log, replayed in two
    fresh processes under two different hash seeds: the projection digest must
    match. Set iteration order and dict-key hashing are per-process in CPython
    (the ladder-9 F1 bug), so a projection id that depended on either would be
    invisible to every in-process check above.

    The log is captured ONCE, by this process, and the subprocesses only
    truncate + replay it. Letting each subprocess capture its own log would
    compare two DIFFERENT logs -- `recorded_at` is a genuine wall-clock reading
    taken at capture time -- and the comparison would fail for a reason that
    has nothing to do with determinism.
    """

    REPLAY = (
        "import sys, hashlib, os;"
        "sys.path[:0] = [%r, %r];"
        "from test_replay_determinism import snapshot;"
        "from engine.config import Config;"
        "from engine.embeddings import HashingEmbedder;"
        "from engine.reducer import Reducer;"
        "from engine.store import MemoryStore;"
        "st = MemoryStore(sys.argv[1]);"
        "rd = Reducer(st, HashingEmbedder(dimensions=256),"
        " Config({'curation': {'supersede_similarity': 0.3}}));"
        "setattr(st, 'reducer', rd);"
        "rd.rebuild();"
        "print(hashlib.sha256(snapshot(st).encode()).hexdigest())"
    )

    def _digest_after_replay(self, seed):
        db = os.path.join(self.dir, "seed-%s.db" % seed)
        # The store runs in WAL mode, so the committed events may still live in
        # chronicle.db-wal. Copy the sidecars too or the subprocess opens an
        # empty database and "agrees" with every other seed about nothing.
        src = os.path.join(self.dir, "chronicle.db")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(src + suffix):
                shutil.copyfile(src + suffix, db + suffix)
        code = self.REPLAY % (str(Path(__file__).parent.parent), str(Path(__file__).parent))
        env = dict(os.environ, PYTHONHASHSEED=str(seed))
        proc = subprocess.run([sys.executable, "-c", code, db], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode()[-2000:])
        return proc.stdout.decode().strip().splitlines()[-1]

    def test_same_projection_digest_under_different_hash_seeds(self):
        self._populated()
        mine = hashlib.sha256(snapshot(self.store).encode()).hexdigest()
        digests = [self._digest_after_replay(seed) for seed in HASH_SEEDS]
        self.assertEqual(len(HASH_SEEDS), 5)
        self.assertEqual(len(set(digests)), 1,
                         "the projection depends on PYTHONHASHSEED: %s" % digests)
        self.assertEqual(digests[0], mine,
                         "a replayed store differs from the store that captured the log")


if __name__ == "__main__":
    unittest.main()
