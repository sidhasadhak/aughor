"""Recent-window re-anchoring for KPI trend chart_sql.

The bug a user caught from the missimi briefing: trend chart_sql written as
`... ORDER BY <bucket> LIMIT 12` (ascending) returns the OLDEST 12 buckets, so on a
2022→2025 dataset the KPI sparkline + delta + expand chart freeze on Jan–Dec 2022.
`recent_window` flips such a trend to the MOST RECENT N buckets, ascending for display.

High-precision contract: it must ONLY rewrite a provably-ascending LIMITed time trend —
never a top-N category breakdown, a no-LIMIT query, or an already-DESC trend.
See aughor/sql/trend_window.py.
"""
import duckdb
import pytest

from aughor.sql.trend_window import recent_window


# ── Rewrites: provably-ascending LIMITed time trends ──────────────────────────

MONTHLY_TREND = (
    "SELECT date_trunc('month', o.order_purchase_ts)::DATE AS month, "
    "ROUND(AVG(o.order_value), 2) AS aov FROM orders o GROUP BY 1 ORDER BY 1 LIMIT 12"
)
WEEKLY_TREND = (
    "SELECT date_trunc('week', week)::DATE AS week, SUM(spend) AS s "
    "FROM mk GROUP BY 1 ORDER BY 1 LIMIT 12"
)
ALIAS_ORDER_TREND = (  # ORDER BY <alias> rather than ordinal
    "SELECT month, rate FROM monthly ORDER BY month LIMIT 6"
)
CTE_TREND = (
    "WITH m AS (SELECT date_trunc('month', ts) AS month, COUNT(*) c FROM t GROUP BY 1) "
    "SELECT month, c FROM m ORDER BY month LIMIT 6"
)


DESC_TREND = (  # already most-recent-first → normalised to ascending-for-display
    "SELECT date_trunc('month', ts)::DATE AS month, AVG(x) FROM t GROUP BY 1 ORDER BY 1 DESC LIMIT 12"
)


@pytest.mark.parametrize("sql", [MONTHLY_TREND, WEEKLY_TREND, ALIAS_ORDER_TREND, CTE_TREND, DESC_TREND])
def test_limited_time_trend_is_rewritten(sql):
    out = recent_window(sql)
    assert out != sql
    low = out.lower()
    assert "_recent" in low            # wrapped in a recent-window subquery
    assert "desc" in low               # inner order is most-recent-first
    assert low.rstrip().rstrip(";").endswith("order by month") or "order by week" in low


@pytest.mark.parametrize("sql", [MONTHLY_TREND, WEEKLY_TREND, ALIAS_ORDER_TREND, CTE_TREND, DESC_TREND])
def test_rewrite_is_idempotent(sql):
    once = recent_window(sql)
    assert recent_window(once) == once


# ── Left untouched: not a provably-ascending LIMITed time trend ────────────────

TOPN_BREAKDOWN = "SELECT channel, SUM(rev) r FROM mk GROUP BY 1 ORDER BY r DESC LIMIT 10"
NO_LIMIT_TREND = "SELECT date_trunc('month', ts)::DATE AS month, AVG(x) FROM t GROUP BY 1 ORDER BY 1"
ORDINAL_DIST = "SELECT review_score, COUNT(*) FROM r GROUP BY 1 ORDER BY 1"  # no limit, not a date
MEASURE_ORDER = "SELECT month, rate FROM m ORDER BY rate DESC LIMIT 6"       # ordered by the measure


@pytest.mark.parametrize("sql", [TOPN_BREAKDOWN, NO_LIMIT_TREND, ORDINAL_DIST, MEASURE_ORDER])
def test_non_trend_is_left_unchanged(sql):
    assert recent_window(sql) == sql


@pytest.mark.parametrize("junk", ["", "   ", "not sql at all", "DELETE FROM t"])
def test_fail_open_on_unparseable(junk):
    # never raises; returns the input (a DELETE isn't a SELECT trend, so unchanged)
    assert recent_window(junk) == junk


# ── Behavioral: the rewrite actually returns the most-recent window ascending ──

def test_returns_most_recent_buckets_ascending():
    con = duckdb.connect()
    # 48 monthly buckets spanning 2022-01 .. 2025-12, value = the month index.
    con.execute("""
        CREATE TABLE t AS
        SELECT (DATE '2022-01-01' + INTERVAL (g) MONTH) AS ts, g AS v
        FROM range(0, 48) AS r(g)
    """)
    sql = "SELECT date_trunc('month', ts)::DATE AS month, AVG(v) AS v FROM t GROUP BY 1 ORDER BY 1 LIMIT 12"

    original = con.execute(sql).fetchall()
    assert str(original[0][0]).startswith("2022")          # the bug: oldest 12 months
    assert str(original[-1][0]).startswith("2022")

    rewritten = con.execute(recent_window(sql)).fetchall()
    assert len(rewritten) == 12
    assert str(rewritten[0][0]) == "2025-01-01"            # most-recent 12 months …
    assert str(rewritten[-1][0]) == "2025-12-01"           # … ascending for display
    # strictly ascending
    months = [r[0] for r in rewritten]
    assert months == sorted(months)

    # A DESC-written trend (recent but newest-first) normalises to the SAME result.
    desc_sql = "SELECT date_trunc('month', ts)::DATE AS month, AVG(v) AS v FROM t GROUP BY 1 ORDER BY 1 DESC LIMIT 12"
    from_desc = con.execute(recent_window(desc_sql)).fetchall()
    assert [r[0] for r in from_desc] == months
