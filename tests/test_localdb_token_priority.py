"""
Chronicle — F1: a federated LIKE search must not let a common word crowd a
proper noun out of the row cap (§g3).

`LocalDBProvider._search_table` (engine/localdb.py) answers one question per
declared table: "does any text column LIKE any of the query's focus tokens?"
— OR'd across every (column, token) pair, cut at `max_rows`. That query had no
ORDER BY, so when the query carried both a proper noun ("Amazon", from "what
did I buy at Amazon last week") and a short common word riding alongside it
("last"), a table where rows matching "last" merely happened to sort ahead of
the Amazon rows (by rowid) filled the whole row cap with "last" matches before
a single Amazon row was ever reached — the specific thing the query was about
never made it into the result at all. Measured on the production store: 199
matching rows, 0 injected. Nothing about this is specific to "Amazon" or to a
transactions-shaped table; any proper noun sharing a query with a short common
word, against any declared source, is the same shape of loss.

Fix: search the query's tokens LONGEST FIRST — one bounded subquery per token
(still every text column, still capped at `max_rows` each), unioned into a
single statement and re-capped at `max_rows` in Python — so a short common
word can never claim a row slot a longer, more specific token would have
filled. Still exactly one `conn.execute()` per table (§g3's "ONE statement per
table" bound is unchanged; see the module's own docstring).

Three pinned cases of the same shape (a proper noun that a short common word
outnumbers in the same table), against three differently-shaped declared
sources, plus the generic properties the fix must hold everywhere: a row that
matches more than one token is returned once, a query with nothing to crowd it
is unaffected, and the row cap is never exceeded.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.localdb import MAX_ROWS_PER_TABLE, LocalDBProvider


def _sqlite_db(tmp_dir: str, table: str, columns: list, rows: list) -> str:
    """A throwaway sqlite file: `table(id INTEGER PRIMARY KEY, <columns...>)`,
    one row per entry of `rows` (a tuple per declared column, in order)."""
    path = str(Path(tmp_dir) / ("%s.db" % table))
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE %s (id INTEGER PRIMARY KEY, %s)"
                 % (table, ", ".join("%s TEXT" % c for c in columns)))
    conn.executemany(
        "INSERT INTO %s (%s) VALUES (%s)"
        % (table, ", ".join(columns), ", ".join("?" for _ in columns)),
        rows)
    conn.commit()
    conn.close()
    return path


class _CrowdingCaseMixin:
    """`self.tmp` is a fresh TemporaryDirectory per test (unittest's own
    per-method setUp/tearDown, not shared across cases)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)


class TestTransactionsMerchantSurvivesCrowding(_CrowdingCaseMixin, unittest.TestCase):
    """Case 1 (pinned): a transactions-shaped table, "Amazon" crowded by
    "last" (from "what did I buy at Amazon last week") — the motivating case."""

    def test_amazon_reached_despite_generic_word_ahead_of_it_by_rowid(self):
        rows = [("Whole Foods Market, checked out at last minute", "Groceries")
                for _ in range(MAX_ROWS_PER_TABLE + 3)]
        rows.append(("Amazon", "Shopping"))
        db_path = _sqlite_db(self._tmp.name, "transactions", ["merchant_name", "category"], rows)
        provider = LocalDBProvider("transactions", db_path, table="transactions")

        hits = provider.search(["amazon", "last"], owner="default", principal="default")

        self.assertTrue(any("Amazon" in h["projection"] for h in hits),
                        "Amazon row never reached: %r" % hits)
        self.assertLessEqual(len(hits), MAX_ROWS_PER_TABLE)


class TestTransactionsSecondMerchantSurvivesCrowding(_CrowdingCaseMixin, unittest.TestCase):
    """Case 2 (pinned): a different transactions merchant, crowded by a
    different generic word ("next", from "what did I buy at Trader Joe's next
    time I'm low on groceries" / "next" riding along the same way "last" did)."""

    def test_second_merchant_reached_despite_crowding(self):
        rows = [("Local Cafe, pay next time", "Dining") for _ in range(MAX_ROWS_PER_TABLE + 3)]
        rows.append(("Trader Joe's", "Groceries"))
        db_path = _sqlite_db(self._tmp.name, "transactions", ["merchant_name", "category"], rows)
        provider = LocalDBProvider("transactions", db_path, table="transactions")

        hits = provider.search(["joe's", "next"], owner="default", principal="default")

        self.assertTrue(any("Trader Joe's" in h["projection"] for h in hits),
                        "Trader Joe's row never reached: %r" % hits)


class TestStyxPlaceSurvivesCrowding(_CrowdingCaseMixin, unittest.TestCase):
    """Case 3 (pinned): a styx-shaped (places/merchants) table — "Starbucks"
    crowded by "recent" (from "did I go to Starbucks recently")."""

    def test_place_reached_despite_crowding(self):
        rows = [("Corner Diner, a recent favorite", "123 Elm St")
                for _ in range(MAX_ROWS_PER_TABLE + 3)]
        rows.append(("Starbucks", "9 Main St"))
        db_path = _sqlite_db(self._tmp.name, "venues", ["venue_name", "address"], rows)
        provider = LocalDBProvider("styx", db_path, table="venues")

        hits = provider.search(["starbucks", "recent"], owner="default", principal="default")

        self.assertTrue(any("Starbucks" in h["projection"] for h in hits),
                        "Starbucks row never reached: %r" % hits)


class TestGenericProperties(_CrowdingCaseMixin, unittest.TestCase):
    """What the fix must hold for EVERY declared source, not just the three
    pinned cases above."""

    def test_a_single_distinctive_token_is_unaffected(self):
        """No second token to crowd it -- the plain case must behave exactly
        as before: the one matching row, once."""
        db_path = _sqlite_db(self._tmp.name, "transactions", ["merchant_name"],
                             [("Amazon",)])
        provider = LocalDBProvider("transactions", db_path, table="transactions")
        hits = provider.search(["amazon"], owner="default", principal="default")
        self.assertEqual(len(hits), 1)
        self.assertIn("Amazon", hits[0]["projection"])

    def test_a_row_matching_two_tokens_is_returned_once(self):
        """"Amazon last-minute order" matches BOTH "amazon" and "last" -- it
        must claim exactly one row slot, not two."""
        rows = [("Amazon last-minute order",)] + [("last-minute delivery %d" % i,)
                                                   for i in range(MAX_ROWS_PER_TABLE)]
        db_path = _sqlite_db(self._tmp.name, "transactions", ["merchant_name"], rows)
        provider = LocalDBProvider("transactions", db_path, table="transactions")

        hits = provider.search(["amazon", "last"], owner="default", principal="default")

        external_ids = [h["external_id"] for h in hits]
        self.assertEqual(len(external_ids), len(set(external_ids)), hits)
        self.assertLessEqual(len(hits), MAX_ROWS_PER_TABLE)

    def test_the_row_cap_is_never_exceeded(self):
        """Every token matches its own full `max_rows` worth of noise; the
        union must still be capped at `max_rows` overall, not per token."""
        rows = [("alpha row %d" % i,) for i in range(20)] + [("beta row %d" % i,) for i in range(20)]
        db_path = _sqlite_db(self._tmp.name, "t", ["name"], rows)
        provider = LocalDBProvider("t", db_path, table="t")

        hits = provider.search(["alpha", "beta"], owner="default", principal="default")

        self.assertLessEqual(len(hits), MAX_ROWS_PER_TABLE)

    def test_more_specific_token_wins_the_shared_slot(self):
        """A longer (more specific) token's matches are asked for FIRST, so
        when both tokens' matches would overflow the cap, the longer token's
        rows fill it before the shorter one's."""
        rows = [("shortword hit %d" % i,) for i in range(MAX_ROWS_PER_TABLE)]
        rows.append(("longerword hit",))
        db_path = _sqlite_db(self._tmp.name, "t", ["name"], rows)
        provider = LocalDBProvider("t", db_path, table="t")

        hits = provider.search(["shortword", "longerword"], owner="default", principal="default")

        self.assertTrue(any("longerword" in h["projection"] for h in hits), hits)


if __name__ == "__main__":
    unittest.main()
