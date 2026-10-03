"""Two keys read from one stored column are one domain: their overlap is what the filters select.

theLook's repeat-rate query (2026-10-01) joins its 2025 cohorts to every customer's repeat orders,
both read from `orders.user_id` through the statement's CTEs. They shared 13% of sampled values —
the repeat rate itself, the number the query exists to measure — and the join guard called the join
unreliable on a correct answer.
"""
from __future__ import annotations

from types import SimpleNamespace

import sqlglot

from aughor.sql.join_guard import _join_sides, _one_domain, join_domain_check

#: The statement as the Agent ran it on BigQuery.
COHORTS = """
WITH first_orders AS (
  SELECT user_id, MIN(created_at) AS first_order_date FROM orders GROUP BY 1
),
monthly_cohorts AS (
  SELECT user_id, DATE_TRUNC(DATE(first_order_date), MONTH) AS cohort_month
  FROM first_orders
  WHERE first_order_date >= '2025-01-01' AND first_order_date < '2026-01-01'
),
repeat_orders AS (
  SELECT o.user_id, o.created_at AS repeat_order_date
  FROM orders o
  JOIN first_orders fo ON o.user_id = fo.user_id
  WHERE o.created_at > fo.first_order_date
    AND o.created_at <= TIMESTAMP_ADD(fo.first_order_date, INTERVAL 90 DAY)
)
SELECT mc.cohort_month, COUNT(DISTINCT mc.user_id) AS first_time_buyers,
       COUNT(DISTINCT ro.user_id) AS repeaters,
       SAFE_DIVIDE(COUNT(DISTINCT ro.user_id), COUNT(DISTINCT mc.user_id)) AS repeat_rate
FROM monthly_cohorts mc
LEFT JOIN repeat_orders ro ON mc.user_id = ro.user_id
GROUP BY 1 ORDER BY 1
"""


class _Conn:
    """A BigQuery connection whose every overlap probe reads 13 of 100 — what theLook's did."""
    dialect = "bigquery"
    writes_native_sql = True

    def __init__(self):
        self.probes: list[str] = []

    def execute(self, label, sql, *, sql_dialect=None, internal=False):
        self.probes.append(sql)
        return SimpleNamespace(error=None, rows=[[100, 13]])


def test_both_joins_of_the_cohort_query_read_one_column():
    tree = sqlglot.parse_one(COHORTS, read="bigquery")
    pairs, _ = _join_sides(tree, "bigquery")
    assert len(pairs) == 2 and all(_one_domain(tree, a, b) for a, b in pairs)


def test_no_warning_and_no_probe_for_a_join_within_one_domain():
    conn = _Conn()
    run = join_domain_check(conn, COHORTS)
    assert run.findings == [] and run.unchecked == []
    assert conn.probes == []                     # two BigQuery scans per join, not spent


def test_keys_read_from_different_columns_are_still_probed_and_flagged():
    sql = ("WITH a AS (SELECT user_id FROM orders WHERE status = 'Complete'), "
           "b AS (SELECT order_id FROM orders) "
           "SELECT COUNT(*) AS n FROM a JOIN b ON a.user_id = b.order_id")
    conn = _Conn()
    run = join_domain_check(conn, sql)
    assert conn.probes and [(w.overlap) for w in run.findings] == [0.13]


def test_a_computed_key_breaks_the_trail_and_is_probed():
    sql = ("WITH a AS (SELECT user_id FROM orders), "
           "b AS (SELECT CAST(user_id AS STRING) AS user_id FROM orders) "
           "SELECT COUNT(*) AS n FROM a JOIN b ON a.user_id = b.user_id")
    tree = sqlglot.parse_one(sql, read="bigquery")
    [(a, b)], _ = _join_sides(tree, "bigquery")
    assert not _one_domain(tree, a, b)
    both = ("WITH a AS (SELECT CAST(user_id AS STRING) AS k FROM orders), "
            "b AS (SELECT CAST(order_id AS STRING) AS k FROM orders) "
            "SELECT COUNT(*) AS n FROM a JOIN b ON a.k = b.k")
    tree = sqlglot.parse_one(both, read="bigquery")
    [(a, b)], _ = _join_sides(tree, "bigquery")
    assert not _one_domain(tree, a, b)            # two computed keys: no trail, so no verdict of "one"
