"""WCH-DS temporal guard — the deterministic half (CI-lockable).

The bug: the intake coverage-clamp computed the correct LITERAL observation/comparison
window and passed it to the phase prompt, but the coder ignored it and wrote
`DATE_SUB(CURRENT_DATE, INTERVAL '13 months')` — which on HISTORICAL data returns ZERO
rows (and isn't valid DuckDB). The baseline then hallucinated around the emptiness.

`_uses_relative_date` is the enforcement trigger: when a planned query anchors a window
to TODAY instead of the literal dates, the phase runner forces one corrective re-plan.
These pin the detector so the guard keeps firing (and never over-fires on legit SQL).
The full LLM-in-the-loop behavior is verified manually by evals/verify_clamp.py.
"""
from aughor.agent.investigate import _uses_relative_date


class TestFlagsRelativeDate:
    def test_date_sub_current_date(self):
        assert _uses_relative_date("WHERE d >= DATE_SUB(CURRENT_DATE, INTERVAL '13 months')")

    def test_bare_current_date(self):
        assert _uses_relative_date("WHERE d >= CURRENT_DATE - INTERVAL 1 YEAR")

    def test_current_timestamp(self):
        assert _uses_relative_date("SELECT CURRENT_TIMESTAMP")

    def test_now_function(self):
        assert _uses_relative_date("SELECT NOW()")

    def test_getdate_and_sysdate(self):
        assert _uses_relative_date("WHERE d < getdate()")
        assert _uses_relative_date("WHERE d < SYSDATE")

    def test_date_add_dateadd(self):
        assert _uses_relative_date("DATE_ADD(CURRENT_DATE, INTERVAL 1 DAY)")
        assert _uses_relative_date("DATEADD(month, -12, getdate())")

    def test_case_insensitive(self):
        assert _uses_relative_date("current_date")
        assert _uses_relative_date("Current_Date")


class TestIgnoresLiteralDates:
    def test_literal_date_window(self):
        assert not _uses_relative_date(
            "WHERE order_date >= DATE '2023-03-10' AND order_date < DATE '2024-03-10'")

    def test_now_as_column_substring(self):
        # 'now' inside an identifier is not the now() function
        assert not _uses_relative_date("SELECT snow_total, now_flag FROM t")

    def test_datediff_between_literals_is_fine(self):
        # comparing two columns/literals is legitimate; only TODAY-relative is the bug
        assert not _uses_relative_date("SELECT DATEDIFF('day', d1, d2) FROM t")

    def test_empty_and_none(self):
        assert not _uses_relative_date("")
        assert not _uses_relative_date(None)
