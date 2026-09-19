"""Chronicle — 5.8.32: the AI review threads on #20 and #23 that were real bugs.

One test class per thread, named for what it guarantees. The threads declined
with a reason are answered on the PRs, not here.
"""

import os
import sqlite3
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from _tmp_support import temp_home  # noqa: E402
from context import ChronicleContextEngine  # noqa: E402
from engine import substance as sub  # noqa: E402
from engine.core import ChronicleCore  # noqa: E402
from scripts import clean_entities  # noqa: E402
from scripts.migrate_vectors import Migrator  # noqa: E402
from scripts.writeback_vectors import Refused, _open_ro  # noqa: E402
from test_dashboard_tapestry import A  # noqa: E402  (tapestry_api, loaded as the host does)


def _db_with_hot_journal():
    """A rollback-journal database whose -journal is non-empty (hot)."""
    home = temp_home()
    path = os.path.join(home, "copy.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE t(x)")
    conn.commit()
    conn.close()
    with open(path + "-journal", "wb") as fh:
        fh.write(b"\xd9\xd5\x05\xf9\x20\xa1\x63\xd7" + b"\0" * 504)
    return path


class TestAHotJournalIsNeverReadImmutable(unittest.TestCase):
    """#20: immutable=1 skips rollback recovery, so a hot journal refuses."""

    def test_writeback_refuses_the_static_copy(self):
        import scripts.writeback_vectors as wb
        path = _db_with_hot_journal()
        opened = []
        real = wb._connect_probed

        def probed(uri):
            opened.append(uri)
            if "immutable" not in uri:
                raise sqlite3.OperationalError("simulated: read-only open failed")
            return real(uri)
        wb._connect_probed = probed
        try:
            with self.assertRaises(Refused) as cm:
                _open_ro(path, static=True)
        finally:
            wb._connect_probed = real
        self.assertIn("journal", str(cm.exception))
        self.assertFalse([u for u in opened if "immutable" in u], opened)

    def test_the_tapestry_reader_does_not_open_it_immutable(self):
        path = _db_with_hot_journal()
        opened = []
        real = sqlite3.connect

        def spy(target, *a, **k):
            opened.append(target)
            if "immutable" not in target:
                raise sqlite3.OperationalError("simulated: read-only open failed")
            return real(target, *a, **k)
        A.sqlite3.connect = spy
        try:
            with self.assertRaises(sqlite3.Error):
                A._connect(path)
        finally:
            A.sqlite3.connect = real
        self.assertFalse([u for u in opened if "immutable" in u], opened)


class TestUnreviewedContactsAreNotGuessedToBePeople(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(A._people_kind({"is_company": 1})[0], "thing")
        self.assertEqual(A._people_kind({"is_company": 0})[0], "person")
        kind, subtype = A._people_kind({"is_company": None})
        self.assertIsNone(kind)
        self.assertEqual(subtype, "contact (unreviewed)")


class TestAMergeCycleIsListedOnce(unittest.TestCase):
    def _map(self, pairs):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE entities(belief_id TEXT, merged_into TEXT)")
        conn.executemany("INSERT INTO entities VALUES(?,?)", pairs)
        return A._merge_map(conn)

    def test_a_two_cycle_keeps_one_representative(self):
        m = self._map([("ent_b", "ent_a"), ("ent_a", "ent_b")])
        self.assertEqual(m, {"ent_b": "ent_a"})    # ent_a is listed; ent_b folds into it

    def test_a_chain_into_a_cycle(self):
        m = self._map([("ent_c", "ent_b"), ("ent_b", "ent_a"), ("ent_a", "ent_b")])
        self.assertEqual(m, {"ent_c": "ent_a", "ent_b": "ent_a"})

    def test_a_plain_chain_is_unchanged(self):
        self.assertEqual(self._map([("ent_c", "ent_b"), ("ent_b", "ent_a")]),
                         {"ent_c": "ent_a", "ent_b": "ent_a"})


class TestAReplacementIsAfterWhatItReplaced(unittest.TestCase):
    def test_even_with_an_earlier_timestamp(self):
        rows = [("b_new", "Globex Fake Inc", "active", "2026-09-01T00:00:00Z", None, None, None),
                ("b_old", "Acme Fake Co", "superseded", "2026-09-02T00:00:00Z", None, None, "b_new")]
        self.assertEqual([r[1] for r in A._in_supersession_order(rows)],
                         ["Acme Fake Co", "Globex Fake Inc"])

    def test_unrelated_chains_keep_time_order(self):
        rows = [("a1", "a1", "superseded", "2020", None, None, "a2"),
                ("a2", "a2", "active", "2021", None, None, None),
                ("b1", "b1", "superseded", "2024", None, None, "b2"),
                ("b2", "b2", "superseded", "2025", None, None, "b3"),
                ("b3", "b3", "active", "2026", None, None, None)]
        self.assertEqual([r[1] for r in A._in_supersession_order(rows)],
                         ["a1", "a2", "b1", "b2", "b3"])


def _entities_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE entities(belief_id TEXT, type TEXT, name TEXT, normalized_name TEXT,
                              owner TEXT, domain TEXT, aliases TEXT, fact_count INTEGER);
        CREATE TABLE facts(belief_id TEXT, entity_id TEXT, status TEXT,
                           predicate_canonical TEXT, value TEXT);
        CREATE TABLE relationships(belief_id TEXT, source_id TEXT, target_id TEXT, status TEXT);
        CREATE TABLE justifications(belief_id TEXT, support TEXT);
    """)
    return conn


class TestEntityCleanupRespectsRelationships(unittest.TestCase):
    def test_an_entity_only_a_relationship_uses_is_not_dropped(self):
        conn = _entities_db()
        conn.execute("INSERT INTO entities VALUES('b_x1','', 'the stuff', 'the stuff','o','d','[]',0)")
        conn.execute("INSERT INTO relationships VALUES('r1','user','b_x1','active')")
        drops = [r for r in clean_entities.plan(conn) if r["action"] == "drop"]
        self.assertEqual(drops, [])

    def test_a_merge_moves_relationship_endpoints(self):
        conn = _entities_db()
        conn.execute("INSERT INTO entities VALUES('pat_testley','', 'Pat Testley','pat testley','o','d','[]',1)")
        conn.execute("INSERT INTO entities VALUES('b_dup','person','Pat Testley','pat testley','o','d','[]',0)")
        conn.execute("INSERT INTO relationships VALUES('r1','b_dup','user','active')")
        conn.execute("INSERT INTO relationships VALUES('r2','user','b_dup','active')")
        reps = clean_entities.plan(conn)
        self.assertIn(("merge", "b_dup", "pat_testley"),
                      [(r["action"], r["belief_id"], r.get("into")) for r in reps])
        clean_entities.apply(conn, reps)
        ends = conn.execute("SELECT source_id, target_id FROM relationships ORDER BY belief_id").fetchall()
        self.assertEqual([tuple(e) for e in ends], [("pat_testley", "user"), ("user", "pat_testley")])


class TestAPlainAccountIsKept(unittest.TestCase):
    """#23: a short lower-case account of what happened is a memory."""

    def test_kept(self):
        for v in ("bought dog food", "went to the gym", "picked up the car from the shop"):
            with self.subTest(v=v):
                self.assertTrue(sub.states_what_happened(v, "purchased"))

    def test_notifications_still_refused(self):
        for v in ("Your order has shipped!", "Payment received", "Delivery delayed",
                  "Your refund has been issued", "shipping notice for order 1234"):
            with self.subTest(v=v):
                self.assertFalse(sub.states_what_happened(v, "purchased"))


class TestStartupRecoveryIsRetriedAfterAFailure(unittest.TestCase):
    def test_retried(self):
        calls = []

        class Reaper:
            def startup_recovery(self):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("store busy")

        fake = types.SimpleNamespace(_startup_recovered=False, _startup_recovering=False,
                                     reaper_enabled=True, cfg={}, reaper=Reaper(),
                                     _drain_slice=lambda: None)
        with self.assertRaises(RuntimeError):
            ChronicleCore.on_startup_recovery(fake)
        self.assertFalse(fake._startup_recovered)
        ChronicleCore.on_startup_recovery(fake)
        self.assertTrue(fake._startup_recovered)
        ChronicleCore.on_startup_recovery(fake)          # and then only once
        self.assertEqual(len(calls), 2)


class TestAttachmentsFoldToDistinctIds(unittest.TestCase):
    def test_two_photos_one_caption(self):
        eng = ChronicleContextEngine()

        def photo(url):
            return {"role": "user", "content": [
                {"type": "text", "text": "look at this"},
                {"type": "image_url", "image_url": {"url": url}}]}
        a, _d, _s = eng._fold(photo("data:image/png;base64,AAAA"), [])
        b, _d, _s = eng._fold(photo("data:image/png;base64,BBBB"), [])
        self.assertNotEqual(a, b)

    def test_a_string_message_keeps_its_id(self):
        eng = ChronicleContextEngine()
        span, digest, _s = eng._fold({"role": "user", "content": "plain words"}, [])
        from engine.serialize import hash_str
        self.assertEqual(digest, hash_str("plain words"))


class TestPreflightLooksPastTheSettledPrefix(unittest.TestCase):
    def _eng(self, locked):
        eng = ChronicleContextEngine()
        eng._match_locked_prefix = lambda msgs: locked
        eng._target_budget = lambda: 10 ** 9
        eng.protect_last_n = 2
        return eng

    def _msgs(self, n):
        return [{"role": "user" if i % 2 == 0 else "assistant",
                 "content": "Acme Fake Co turn %d, nothing binding in it" % i} for i in range(n)]

    def test_only_settled_messages_means_nothing_to_compress(self):
        msgs = self._msgs(30)
        self.assertFalse(self._eng(locked=28).has_content_to_compress(msgs))

    def test_fresh_messages_beyond_the_tail_do_count(self):
        msgs = self._msgs(30)
        self.assertTrue(self._eng(locked=20).has_content_to_compress(msgs))


class TestAFramingOnlySessionIsNotUnrecoverable(unittest.TestCase):
    def test_empty_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE session_index(session_id TEXT, summary TEXT, embedding BLOB)")
        conn.executemany("INSERT INTO session_index VALUES(?,?,?)",
                         [("s_empty", None, None), ("s_text", "we talked", None),
                          ("s_vec", "", b"\x00" * 8)])
        self.assertTrue(Migrator._empty_session_row(conn, "s_empty"))
        self.assertFalse(Migrator._empty_session_row(conn, "s_text"))
        self.assertFalse(Migrator._empty_session_row(conn, "s_vec"))


if __name__ == "__main__":
    unittest.main()
