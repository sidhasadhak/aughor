"""What a statement measures and how it is cut, in words, read from the statement alone
(`agent.analyst.statement_title`) — the line the SQL editor's recent runs print over each statement (the user,
2026-10-12). The fixtures are theLook's live editor history that day, read over HTTP: cockpit-shaped statements inside
the editor's own `SELECT * FROM (…) __q LIMIT n` wrappers, with generated aliases (`v0`, `x`, `s`) nobody reads."""
from __future__ import annotations

import pytest

from aughor.agent.analyst import statement_title

LIVE = [
    ('SELECT * FROM (SELECT * FROM ( SELECT u.country, ROUND(SUM(oi.sale_price), 2) AS sales FROM thelook.orders o JOIN thelook.users u ON u.id = o.user_id JOIN thelook.order_items oi ON oi.order_id = o.order_id WHERE o.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL :v_window DAY) GROUP BY 1 ORDER BY sales DESC LIMIT 5 ) AS q ORDER BY `q`.`sales` DESC LIMIT 201) __q LIMIT 202',
     'Sales by country · top 5'),
    ("SELECT * FROM (SELECT SUM(`q`.`sales`) AS v0 FROM ( SELECT oi.sale_price AS sales, o.order_id FROM thelook.orders o JOIN thelook.users u ON u.id = o.user_id JOIN thelook.order_items oi ON oi.order_id = o.order_id WHERE o.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL :v_window DAY) AND u.country = :v_country AND oi.status NOT IN ('Cancelled', 'Returned') ) AS q) __q LIMIT 3",
     'Total sales in orders, users and order items where status not in Cancelled, Returned'),
    ('SELECT * FROM (SELECT * FROM ( SELECT u.country, ROUND(SUM(oi.sale_price), 2) AS sales, COUNT(DISTINCT o.order_id) AS orders FROM thelook.orders o JOIN thelook.users u ON u.id = o.user_id JOIN thelook.order_items oi ON oi.order_id = o.order_id WHERE o.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL :v_window DAY) GROUP BY 1 ) AS q ORDER BY `q`.`sales` DESC LIMIT 201) __q LIMIT 202',
     'Sales and orders by country'),
    ('SELECT * FROM (SELECT DATE_TRUNC(`q`.`day`, DAY) AS x, `q`.`country` AS s, SUM(`q`.`sales`) AS v0 FROM ( SELECT DATE(o.created_at) AS day, u.country, SUM(oi.sale_price) AS sales FROM thelook.orders o JOIN thelook.users u ON u.id = o.user_id JOIN thelook.order_items oi ON oi.order_id = o.order_id WHERE o.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY) GROUP BY 1, 2 ) AS q GROUP BY 1, 2 ORDER BY 1 LIMIT 2001) __q LIMIT 2002',
     'Total sales by day and country'),
]


@pytest.mark.parametrize("sql,title", LIVE)
def test_the_live_history_reads_as_what_each_statement_measures(sql, title):
    assert statement_title(sql, "bigquery") == title


@pytest.mark.parametrize("sql,title", [
    ("SELECT country, SUM(sale_price) FROM order_items WHERE status = 'Complete' AND created_at >= '2026-07-01' "
     "AND created_at < '2026-08-01' GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
     "Total sale price by country where status = Complete — Jul 2026 · top 20"),
    ("SELECT * FROM (SELECT * FROM gold_governance.etl_load_log) AS __q LIMIT 501", "Every column of ETL load log"),
    ("SELECT id, email FROM users", "ID and email from users"),
    ("SELECT COUNT(*) FROM events", "Row count in events"),
    ("SELECT COUNT(DISTINCT user_id) AS buyers FROM orders", "Buyers in orders"),
    ("SELECT COUNT(DISTINCT user_id) FROM orders", "Distinct user ID count in orders"),
])
def test_shapes(sql, title):
    assert statement_title(sql, "duckdb") == title


@pytest.mark.parametrize("sql", ["DELETE FROM t", "not sql at all (((", "", "SELECT 1"])
def test_a_statement_that_does_not_say_gets_no_words_never_a_guess(sql):
    assert statement_title(sql, "duckdb") == ""


def test_the_door_reads_the_connections_own_dialect_so_a_bigquery_statement_gets_its_words(monkeypatch):
    """The tests above hand the dialect in; the door looks it up (`trust.lineage_edges.dialect_for_connection`). That
    lookup read the registry's `type`, which no row carries — the column is `conn_type` — so every connection parsed
    generically, BigQuery's backticks failed, and all seven of theLook's recent runs got no words (2026-10-13)."""
    from aughor.db import registry
    from aughor.trust.lineage_edges import dialect_for_connection
    monkeypatch.setattr(registry, "list_connections", lambda *a, **k: [
        {"id": "bq", "name": "theLook", "conn_type": "bigquery"},
        {"id": "pg", "name": "Lux", "conn_type": "postgres"},
        {"id": "dk", "name": "DuckDB", "conn_type": "duckdb"},
    ])
    assert (dialect_for_connection("bq"), dialect_for_connection("pg"), dialect_for_connection("dk")) == ("bigquery", "postgres", "duckdb")
    assert dialect_for_connection("gone") is None
    sql, title = LIVE[0]
    assert statement_title(sql, dialect_for_connection("bq")) == title
    assert statement_title(sql, None) == ""          # what the door produced before: no dialect, no words
