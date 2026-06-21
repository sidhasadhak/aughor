"""Fiscal-period bucketing helper (localization wiring).

fiscal_period_expr shifts QUARTER/YEAR boundaries for an org whose fiscal year starts in
month M≠1; it is a strict no-op at the January default and for non-shiftable grains, so
calendar-year orgs are byte-for-byte unchanged. See aughor/sql/fiscal.py.
"""
import duckdb
from aughor.sql.fiscal import fiscal_period_expr


def test_january_is_a_noop():
    assert fiscal_period_expr("quarter", "d", 1) == "date_trunc('quarter', d)"
    assert fiscal_period_expr("year", "d", None) == "date_trunc('year', d)"


def test_non_shiftable_grains_are_plain():
    for g in ("day", "week", "month"):
        assert fiscal_period_expr(g, "d", 4) == f"date_trunc('{g}', d)"


def test_non_duckdb_dialect_falls_back_to_plain():
    assert fiscal_period_expr("quarter", "d", 4, dialect="postgres") == "date_trunc('quarter', d)"


def test_fiscal_quarter_year_shift_is_correct_on_duckdb():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE t(d DATE)")
    con.execute("INSERT INTO t VALUES (DATE '2025-05-15'), (DATE '2025-02-15')")
    # April fiscal year (M=4)
    qexpr = fiscal_period_expr("quarter", "d", 4)
    yexpr = fiscal_period_expr("year", "d", 4)
    assert "INTERVAL 3 MONTH" in qexpr   # shifted by M-1 = 3
    rows = con.execute(f"SELECT d, {qexpr}::DATE AS fq, {yexpr}::DATE AS fy FROM t ORDER BY d").fetchall()
    by = {str(r[0]): (str(r[1]), str(r[2])) for r in rows}
    assert by["2025-05-15"] == ("2025-04-01", "2025-04-01")   # FY2025 Q1 (Apr–Jun)
    assert by["2025-02-15"] == ("2025-01-01", "2024-04-01")   # FY2024 Q4 (Jan–Mar), FY started Apr 2024
