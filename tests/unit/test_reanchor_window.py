"""Relative (re-anchoring) monitor windows.

A monitor built from a Briefing finding inherits a FROZEN absolute date window; this
slides every date literal forward by the gap to the data's live activity edge so the
window keeps its shape but tracks the latest data. Fallback-safe: returns the SQL
unchanged on any failure. See aughor/monitors/window.py.
"""
from datetime import datetime

from aughor.monitors.window import reanchor_trailing_window


class _Result:
    def __init__(self, rows, error=None):
        self.rows = rows
        self.error = error
        self.columns = []


class FakeDB:
    """Minimal stand-in for the connection API: execute(label, sql) -> QueryResult."""
    def __init__(self, max_date, dialect="duckdb", fail=False):
        self._max = max_date
        self.dialect = dialect
        self._fail = fail
        self.queries: list[str] = []

    def execute(self, _label, sql):
        self.queries.append(sql)
        if self._fail:
            return _Result([], error="boom")
        return _Result([(self._max,)])


def _dates_in(sql):
    import re
    return re.findall(r"\d{4}-\d{2}-\d{2}", sql)


def test_window_slides_to_live_edge_preserving_span():
    sql = ("SELECT COUNT(*) FROM ecommerce.orders AS o "
           "WHERE o.order_date >= '2023-12-31' AND o.order_date <= '2024-12-30'")
    out = reanchor_trailing_window(sql, FakeDB("2026-05-17"), "duckdb")
    ds = _dates_in(out)
    assert "2026-05-17" in ds          # upper bound now ends at the live edge
    assert "2024-12-30" not in ds      # stale upper gone
    assert "2023-12-31" not in ds      # stale lower gone
    # span preserved: the two literals are still ~365 days apart
    lo, hi = sorted(datetime.fromisoformat(d) for d in set(ds))
    assert 360 <= (hi - lo).days <= 367


def test_no_shift_when_data_not_newer():
    # live edge equals the window end → nothing to slide
    sql = "SELECT COUNT(*) FROM orders WHERE order_date >= '2023-12-31' AND order_date <= '2024-12-30'"
    out = reanchor_trailing_window(sql, FakeDB("2024-12-30"), "duckdb")
    assert "2024-12-30" in _dates_in(out) and "2023-12-31" in _dates_in(out)


def test_no_date_literals_unchanged():
    sql = "SELECT AVG(amount) FROM orders WHERE region = 'EU'"
    assert reanchor_trailing_window(sql, FakeDB("2026-01-01"), "duckdb") == sql


def test_unparseable_sql_unchanged():
    sql = "this is not valid sql ;;;"
    assert reanchor_trailing_window(sql, FakeDB("2026-01-01"), "duckdb") == sql


def test_max_query_failure_falls_back():
    sql = "SELECT COUNT(*) FROM orders WHERE order_date >= '2023-01-01' AND order_date <= '2023-12-31'"
    out = reanchor_trailing_window(sql, FakeDB("2026-01-01", fail=True), "duckdb")
    assert out == sql  # db error → unchanged


def test_bare_column_single_table_resolves():
    sql = "SELECT COUNT(*) FROM orders WHERE order_date >= '2023-01-01'"
    db = FakeDB("2026-01-01")
    out = reanchor_trailing_window(sql, db, "duckdb")
    assert "2026-01-01" in _dates_in(out) and "2023-01-01" not in _dates_in(out)
    assert db.queries and "MAX(order_date)" in db.queries[0] and "orders" in db.queries[0]


def test_ambiguous_bare_column_multi_table_unchanged():
    # bare column with two real tables → can't resolve which to MAX → unchanged
    sql = ("SELECT COUNT(*) FROM orders, customers "
           "WHERE order_date >= '2023-01-01' AND order_date <= '2023-12-31'")
    out = reanchor_trailing_window(sql, FakeDB("2026-01-01"), "duckdb")
    assert out == sql


def test_empty_sql_unchanged():
    assert reanchor_trailing_window("", FakeDB("2026-01-01"), "duckdb") == ""
