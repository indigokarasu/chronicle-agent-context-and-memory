"""
Chronicle — temporal relative expressions (r3).

Unit tests for _parse_time_window with both absolute and relative date expressions.
Tests cover:
- Absolute expressions unchanged (ISO, MDY, DMY, month-year, year)
- Relative expressions with now provided (yesterday, today, N days/weeks/months ago, last/this week/month/year)
- Relative expressions without now return None
- Comprehensive coverage of >=8 relative cases with fixed now date
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.retrieval import _parse_time_window


class TestParseTimeWindowAbsolute(unittest.TestCase):
    """Verify absolute date expressions work unchanged (no now required)."""

    def test_iso_format_single_day(self):
        result = _parse_time_window("events on 2024-05-15")
        self.assertEqual(result, ("2024-05-15", "2024-05-15"))

    def test_iso_format_slash_delimiter(self):
        result = _parse_time_window("happened 2024/03/20")
        self.assertEqual(result, ("2024-03-20", "2024-03-20"))

    def test_mdy_format(self):
        result = _parse_time_window("May 15, 2024")
        self.assertEqual(result, ("2024-05-15", "2024-05-15"))

    def test_mdy_with_ordinal(self):
        result = _parse_time_window("March 2nd, 2023")
        self.assertEqual(result, ("2023-03-02", "2023-03-02"))

    def test_dmy_format(self):
        result = _parse_time_window("15 May 2024")
        self.assertEqual(result, ("2024-05-15", "2024-05-15"))

    def test_dmy_with_ordinal(self):
        result = _parse_time_window("2nd of March, 2023")
        self.assertEqual(result, ("2023-03-02", "2023-03-02"))

    def test_month_year_format(self):
        result = _parse_time_window("happened in May 2024")
        self.assertEqual(result, ("2024-05-01", "2024-05-31"))

    def test_month_year_short(self):
        result = _parse_time_window("Mar 2023")
        self.assertEqual(result, ("2023-03-01", "2023-03-31"))

    def test_year_only(self):
        result = _parse_time_window("back in 2023")
        self.assertEqual(result, ("2023-01-01", "2023-12-31"))

    def test_absolute_with_now_provided(self):
        """Absolute dates ignore now parameter."""
        result = _parse_time_window("2024-05-15", now="2025-01-01")
        self.assertEqual(result, ("2024-05-15", "2024-05-15"))

    def test_no_date_expression(self):
        result = _parse_time_window("what happened with the meeting")
        self.assertIsNone(result)


class TestParseTimeWindowRelativeWithNow(unittest.TestCase):
    """Test relative expressions with now reference point provided."""

    def setUp(self):
        # Fixed reference date: Wednesday, 2025-01-08
        self.now = "2025-01-08"

    def test_yesterday(self):
        result = _parse_time_window("what happened yesterday", now=self.now)
        self.assertEqual(result, ("2025-01-07", "2025-01-07"))

    def test_today(self):
        result = _parse_time_window("what happened today", now=self.now)
        self.assertEqual(result, ("2025-01-08", "2025-01-08"))

    def test_one_day_ago(self):
        result = _parse_time_window("1 day ago", now=self.now)
        self.assertEqual(result, ("2025-01-07", "2025-01-07"))

    def test_five_days_ago(self):
        result = _parse_time_window("5 days ago", now=self.now)
        self.assertEqual(result, ("2025-01-03", "2025-01-03"))

    def test_one_week_ago(self):
        result = _parse_time_window("1 week ago", now=self.now)
        self.assertEqual(result, ("2025-01-01", "2025-01-01"))

    def test_two_weeks_ago(self):
        result = _parse_time_window("2 weeks ago", now=self.now)
        self.assertEqual(result, ("2024-12-25", "2024-12-25"))

    def test_one_month_ago(self):
        result = _parse_time_window("1 month ago", now=self.now)
        # 2024-12-08
        self.assertEqual(result, ("2024-12-08", "2024-12-08"))

    def test_three_months_ago(self):
        result = _parse_time_window("3 months ago", now=self.now)
        # 2024-10-08
        self.assertEqual(result, ("2024-10-08", "2024-10-08"))

    def test_last_week(self):
        # now = 2025-01-08 (Wednesday)
        # last week = week starting 2025-01-01 (Wednesday)
        result = _parse_time_window("last week", now=self.now)
        # Week of 2024-12-30 (Monday) to 2025-01-05 (Sunday)
        self.assertEqual(result, ("2024-12-30", "2025-01-05"))

    def test_this_week(self):
        # now = 2025-01-08 (Wednesday)
        # this week = week of 2025-01-06 (Monday) to 2025-01-12 (Sunday)
        result = _parse_time_window("this week", now=self.now)
        self.assertEqual(result, ("2025-01-06", "2025-01-12"))

    def test_last_month(self):
        result = _parse_time_window("last month", now=self.now)
        # December 2024: 2024-12-01 to 2024-12-31
        self.assertEqual(result, ("2024-12-01", "2024-12-31"))

    def test_this_month(self):
        result = _parse_time_window("this month", now=self.now)
        # January 2025: 2025-01-01 to 2025-01-31
        self.assertEqual(result, ("2025-01-01", "2025-01-31"))

    def test_last_year(self):
        result = _parse_time_window("last year", now=self.now)
        # 2024: 2024-01-01 to 2024-12-31
        self.assertEqual(result, ("2024-01-01", "2024-12-31"))

    def test_multiple_relative_expressions_first_wins(self):
        # "yesterday" comes first in text, should match that
        result = _parse_time_window("yesterday or last week", now=self.now)
        self.assertEqual(result, ("2025-01-07", "2025-01-07"))

    def test_relative_case_insensitive(self):
        result = _parse_time_window("Yesterday", now=self.now)
        self.assertEqual(result, ("2025-01-07", "2025-01-07"))

    def test_plural_days(self):
        result = _parse_time_window("3 days ago", now=self.now)
        self.assertEqual(result, ("2025-01-05", "2025-01-05"))

    def test_plural_weeks(self):
        result = _parse_time_window("3 weeks ago", now=self.now)
        # 3 * 7 = 21 days: 2025-01-08 - 21 = 2024-12-18
        self.assertEqual(result, ("2024-12-18", "2024-12-18"))

    def test_plural_months(self):
        result = _parse_time_window("2 months ago", now=self.now)
        # 2025-01-08 minus 2 months = 2024-11-08
        self.assertEqual(result, ("2024-11-08", "2024-11-08"))

    # -- word-form numbers ("two months ago", not just "2 months ago") --

    def test_word_form_two_months_ago(self):
        result = _parse_time_window("What did I do two months ago?", now=self.now)
        self.assertEqual(result, ("2024-11-08", "2024-11-08"))

    def test_word_form_three_weeks_ago(self):
        result = _parse_time_window("I started writing again three weeks ago", now=self.now)
        # 3 * 7 = 21 days: 2025-01-08 - 21 = 2024-12-18
        self.assertEqual(result, ("2024-12-18", "2024-12-18"))

    def test_word_form_a_week_ago(self):
        result = _parse_time_window("Which book did I finish a week ago?", now=self.now)
        self.assertEqual(result, ("2025-01-01", "2025-01-01"))

    def test_word_form_a_month_ago(self):
        result = _parse_time_window("What charity event did I participate in a month ago?",
                                     now=self.now)
        self.assertEqual(result, ("2024-12-08", "2024-12-08"))

    def test_word_form_four_weeks_ago(self):
        result = _parse_time_window("What was the significant business milestone I mentioned "
                                     "four weeks ago?", now=self.now)
        # 4 * 7 = 28 days: 2025-01-08 - 28 = 2024-12-11
        self.assertEqual(result, ("2024-12-11", "2024-12-11"))

    def test_word_form_one_day_ago(self):
        result = _parse_time_window("one day ago", now=self.now)
        self.assertEqual(result, ("2025-01-07", "2025-01-07"))

    def test_word_form_ten_days_ago(self):
        result = _parse_time_window("ten days ago", now=self.now)
        self.assertEqual(result, ("2024-12-29", "2024-12-29"))

    def test_word_form_case_insensitive(self):
        result = _parse_time_window("Two Months Ago", now=self.now)
        self.assertEqual(result, ("2024-11-08", "2024-11-08"))

    def test_word_form_no_now_returns_none(self):
        """Word-form relative expressions still require now (never guess)."""
        result = _parse_time_window("two months ago")
        self.assertIsNone(result)

    def test_oracle_two_months_ago_museum(self):
        """Real oracle.json phrasing: 'I mentioned visiting a museum two months
        ago. Did I visit with a friend or not?' must resolve, not return None."""
        result = _parse_time_window(
            "I mentioned visiting a museum two months ago. Did I visit with a friend or not?",
            now=self.now)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("2024-11-08", "2024-11-08"))

    def test_oracle_two_months_ago_wednesday(self):
        """Real oracle.json phrasing: 'What did I do with Rachel on the
        Wednesday two months ago?' must resolve, not return None."""
        result = _parse_time_window(
            "What did I do with Rachel on the Wednesday two months ago?", now=self.now)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("2024-11-08", "2024-11-08"))


class TestParseTimeWindowRelativeWithoutNow(unittest.TestCase):
    """Test that relative expressions return None when now is absent."""

    def test_yesterday_no_now(self):
        result = _parse_time_window("what happened yesterday")
        self.assertIsNone(result)

    def test_today_no_now(self):
        result = _parse_time_window("what happened today")
        self.assertIsNone(result)

    def test_days_ago_no_now(self):
        result = _parse_time_window("5 days ago")
        self.assertIsNone(result)

    def test_weeks_ago_no_now(self):
        result = _parse_time_window("2 weeks ago")
        self.assertIsNone(result)

    def test_months_ago_no_now(self):
        result = _parse_time_window("3 months ago")
        self.assertIsNone(result)

    def test_last_week_no_now(self):
        result = _parse_time_window("last week")
        self.assertIsNone(result)

    def test_this_week_no_now(self):
        result = _parse_time_window("this week")
        self.assertIsNone(result)

    def test_last_month_no_now(self):
        result = _parse_time_window("last month")
        self.assertIsNone(result)

    def test_this_month_no_now(self):
        result = _parse_time_window("this month")
        self.assertIsNone(result)

    def test_last_year_no_now(self):
        result = _parse_time_window("last year")
        self.assertIsNone(result)

    def test_word_form_months_ago_no_now(self):
        result = _parse_time_window("two months ago")
        self.assertIsNone(result)

    def test_word_form_weeks_ago_no_now(self):
        result = _parse_time_window("three weeks ago")
        self.assertIsNone(result)


class TestParseTimeWindowEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_invalid_now_format_returns_none(self):
        result = _parse_time_window("yesterday", now="not-a-date")
        self.assertIsNone(result)

    def test_month_boundary_31st_to_short_month(self):
        # Jan 31 minus 1 month should clamp to Feb 28 (in 2025)
        result = _parse_time_window("1 month ago", now="2025-01-31")
        # Dec 31: 2024-12-31
        self.assertEqual(result, ("2024-12-31", "2024-12-31"))

    def test_month_boundary_31st_to_february(self):
        # Mar 31 minus 1 month should clamp to Feb 28
        result = _parse_time_window("1 month ago", now="2025-03-31")
        # Feb 28: 2025-02-28
        self.assertEqual(result, ("2025-02-28", "2025-02-28"))

    def test_year_boundary_january_last_month(self):
        result = _parse_time_window("last month", now="2025-01-15")
        # December 2024
        self.assertEqual(result, ("2024-12-01", "2024-12-31"))

    def test_year_boundary_january_12_months_ago(self):
        result = _parse_time_window("12 months ago", now="2025-01-15")
        # 2024-01-15
        self.assertEqual(result, ("2024-01-15", "2024-01-15"))

    def test_leap_year_february(self):
        # 2024 is a leap year
        result = _parse_time_window("this month", now="2024-02-15")
        self.assertEqual(result, ("2024-02-01", "2024-02-29"))

    def test_non_leap_year_february(self):
        # 2025 is not a leap year
        result = _parse_time_window("this month", now="2025-02-15")
        self.assertEqual(result, ("2025-02-01", "2025-02-28"))

    def test_absolute_takes_precedence_over_relative(self):
        # If both absolute and relative are present, absolute should match first
        result = _parse_time_window("happened on 2024-05-15 yesterday", now="2025-01-08")
        self.assertEqual(result, ("2024-05-15", "2024-05-15"))

    def test_empty_string(self):
        result = _parse_time_window("", now="2025-01-08")
        self.assertIsNone(result)

    def test_large_number_days_ago(self):
        result = _parse_time_window("100 days ago", now="2025-01-08")
        # 2025-01-08 - 100 days = 2024-09-30
        self.assertEqual(result, ("2024-09-30", "2024-09-30"))

    def test_full_iso_datetime_now_accepted(self):
        """Callers (e.g. the LongMemEval harness) stamp `now` from a full
        ISO-8601 timestamp, not a bare date -- only the calendar date matters."""
        result = _parse_time_window("yesterday", now="2025-01-08T23:07:00Z")
        self.assertEqual(result, ("2025-01-07", "2025-01-07"))

    def test_full_iso_datetime_now_word_form(self):
        result = _parse_time_window("two months ago", now="2025-01-08T23:07:00Z")
        self.assertEqual(result, ("2024-11-08", "2024-11-08"))


class TestRetrievalEngineSignatures(unittest.TestCase):
    """Verify RetrievalEngine methods have now parameter (signature test)."""

    def test_search_signature_has_now(self):
        """Verify search() method accepts now keyword argument."""
        import inspect

        from engine.retrieval import RetrievalEngine
        sig = inspect.signature(RetrievalEngine.search)
        self.assertIn("now", sig.parameters)

    def test_retrieve_raw_signature_has_now(self):
        """Verify retrieve_raw() method accepts now keyword argument."""
        import inspect

        from engine.retrieval import RetrievalEngine
        sig = inspect.signature(RetrievalEngine.retrieve_raw)
        self.assertIn("now", sig.parameters)

    def test_answer_signature_has_now(self):
        """Verify answer() method accepts now keyword argument."""
        import inspect

        from engine.retrieval import RetrievalEngine
        sig = inspect.signature(RetrievalEngine.answer)
        self.assertIn("now", sig.parameters)

    def test_get_context_signature_has_now(self):
        """Verify get_context() method accepts now keyword argument."""
        import inspect

        from engine.retrieval import RetrievalEngine
        sig = inspect.signature(RetrievalEngine.get_context)
        self.assertIn("now", sig.parameters)


if __name__ == "__main__":
    unittest.main()
