"""A period's last day, read whole (`sql.day_window`, `sql.executor._whole_days`).

theLook's live deep analysis (2026-10-09): the breakdown was written ``CAST(created_at AS DATE) <=
DATE '2025-12-31'``, failed to bind on another table's column, and the model that repaired it wrote
``created_at <= '2025-12-31'`` — on a TIMESTAMP, 31 December after midnight was dropped and 2025's revenue
from completed orders read 608,504.54 where the year reads 610,184.21. Every statement the guard battery
runs now has an inclusive bound on a bare day over a TIMESTAMP or DATETIME read through the whole day;
a DATE, a string, a cast to DATE, a literal with a time and a column whose type is unknown are left alone.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from aughor.agent.prompts import FIX_SQL_PROMPT
from aughor.db.connection import DuckDBConnection
from aughor.db.schema_render import parse_schema_column_types, parse_schema_tables
from aughor.kernel.registries.execution_hooks import collect_guard_receipts
from aughor.sql.day_window import read_last_days_whole
from aughor.sql.executor import execute_guarded

TYPES = {"thelook.order_items": {"id": "INT64", "created_at": "TIMESTAMP", "status": "STRING"},
         "thelook.users": {"id": "INT64", "traffic_source": "STRING", "created_at": "TIMESTAMP"},
         "orders": {"order_day": "DATE", "ym": "STRING", "placed_at": "DATETIME"}}


def test_the_schema_parser_keeps_each_columns_type_in_every_form_it_reads():
    text = ("TABLE: thelook.order_items\n  id  INT64\n  created_at  TIMESTAMP\n"
            "TABLE: orders (10 rows) [order_id INTEGER, created_at DATE]\n"
            "## thelook.users\n| Column | Type | Notes |\n|---|---|---|\n| id | INT64 | |\n| created_at | TIMESTAMP | |\n")
    assert parse_schema_column_types(text) == {
        "thelook.order_items": {"id": "INT64", "created_at": "TIMESTAMP"},
        "orders": {"order_id": "INTEGER", "created_at": "DATE"},
        "thelook.users": {"id": "INT64", "created_at": "TIMESTAMP"}}
    assert parse_schema_tables(text) == {"thelook.order_items": ["id", "created_at"],
                                         "orders": ["order_id", "created_at"], "thelook.users": ["id", "created_at"]}


@pytest.mark.parametrize("sql, dialect, where", [
    # the live run's repaired statement
    ("SELECT u.traffic_source, SUM(oi.sale_price) FROM order_items AS oi JOIN users AS u ON oi.user_id = u.id "
     "WHERE oi.created_at >= '2025-01-01' AND oi.created_at <= '2025-12-31' GROUP BY 1", "bigquery",
     "oi.created_at >= '2025-01-01' AND oi.created_at < '2026-01-01'"),
    ("SELECT COUNT(*) FROM order_items WHERE created_at BETWEEN '2025-01-01' AND '2025-12-31'", "duckdb",
     "(created_at >= '2025-01-01' AND created_at < '2026-01-01')"),
    ("SELECT COUNT(*) FROM order_items WHERE created_at NOT BETWEEN '2025-01-01' AND '2025-12-31'", "duckdb",
     "NOT (created_at >= '2025-01-01' AND created_at < '2026-01-01')"),
    ("SELECT COUNT(*) FROM order_items WHERE created_at <= DATE '2025-12-31'", "duckdb",
     "created_at < CAST('2026-01-01' AS DATE)"),
    ("SELECT COUNT(*) FROM order_items WHERE '2024-02-28' >= created_at", "duckdb", "'2024-02-29' > created_at"),
    ("SELECT COUNT(*) FROM orders WHERE placed_at <= '2025-12-31'", "duckdb", "placed_at < '2026-01-01'"),
    ("SELECT COUNT(*) FROM order_items AS oi WHERE oi.id IN (SELECT id FROM users WHERE created_at <= '2025-06-30')",
     "duckdb", "created_at < '2025-07-01'"),                              # a subquery's column is its own table's
])
def test_an_inclusive_bound_on_a_bare_day_over_a_timestamp_is_read_through_the_whole_day(sql, dialect, where):
    out, read = read_last_days_whole(sql, TYPES, dialect)
    assert where in out and len(read) == 1 and read[0]["type"] in ("TIMESTAMP", "DATETIME")


def test_a_bound_that_says_its_time_is_kept_beside_one_that_is_read_whole():
    out, read = read_last_days_whole("SELECT COUNT(*) FROM order_items WHERE created_at <= '2025-12-31 12:00:00' "
                                     "OR created_at BETWEEN '2025-01-01' AND '2025-01-31'", TYPES, "duckdb")
    assert "created_at <= '2025-12-31 12:00:00'" in out and "created_at < '2025-02-01'" in out
    assert [r["day"] for r in read] == ["2025-01-31"]


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM order_items WHERE CAST(created_at AS DATE) <= DATE '2025-12-31'",   # already whole days
    "SELECT COUNT(*) FROM orders WHERE order_day <= '2025-12-31'",                           # a DATE: the same rows
    "SELECT COUNT(*) FROM orders WHERE ym <= '2025-12-31'",                                  # a string: not ours
    "SELECT COUNT(*) FROM order_items WHERE created_at <= '2025-12-31 23:59:59'",            # a time is said
    "SELECT COUNT(*) FROM order_items WHERE created_at < '2026-01-01'",                      # half-open already
    "SELECT COUNT(*) FROM order_items JOIN users ON 1 = 1 WHERE created_at <= '2025-12-31'",  # which table's?
    "WITH x AS (SELECT created_at FROM order_items) SELECT COUNT(*) FROM x WHERE created_at <= '2025-12-31'",
    "SELECT COUNT(*) FROM events WHERE created_at <= '2025-12-31'",                          # a type nobody gave
])
def test_what_is_not_a_timestamp_read_to_a_bare_day_is_left_exactly_as_written(sql):
    assert read_last_days_whole(sql, TYPES, "duckdb") == (sql, [])


# ── the executor: every statement the battery runs ─────────────────────────────────────────────────────────────────

@pytest.fixture
def shop(tmp_path: Path):
    path = tmp_path / "shop.duckdb"
    raw = duckdb.connect(str(path))
    raw.execute("CREATE TABLE order_items (id INTEGER, created_at TIMESTAMP, sold_on DATE, sale_price DOUBLE)")
    raw.execute("INSERT INTO order_items VALUES (1, '2025-06-01 09:00', '2025-06-01', 100.0), "
                "(2, '2025-12-31 00:00', '2025-12-31', 10.0), (3, '2025-12-31 18:30', '2025-12-31', 5.0), "
                "(4, '2026-01-01 00:00', '2026-01-01', 1000.0)")
    raw.close()
    conn = DuckDBConnection(path, connection_id="day-window")
    yield conn
    conn.close()


YEAR = "SELECT SUM(sale_price) AS revenue FROM order_items WHERE created_at >= '2025-01-01' AND created_at <= '2025-12-31'"


def test_the_executor_reads_the_last_day_whole_and_says_so(shop):
    with collect_guard_receipts() as receipts:
        r = execute_guarded(shop, YEAR, query_id="answer")
    assert not r.error and float(r.rows[0][0]) == 115.0              # 18:30 on 31 December is in 2025
    assert "created_at < '2026-01-01'" in r.sql
    (said,) = [x for x in receipts if x["guard"] == "day_window"]
    assert said["action"] == "rewrote_sql" and "read through the whole of 2025-12-31" in said["detail"]
    assert "repaired:day-window" in r.doors


def test_a_date_column_and_a_statement_already_whole_run_exactly_as_written(shop):
    for sql in ("SELECT SUM(sale_price) FROM order_items WHERE sold_on <= '2025-12-31'",
                "SELECT SUM(sale_price) FROM order_items WHERE CAST(created_at AS DATE) <= DATE '2025-12-31'"):
        with collect_guard_receipts() as receipts:
            r = execute_guarded(shop, sql, query_id="answer")
        assert float(r.rows[0][0]) == 115.0 and "<=" in r.sql and "2026-01-01" not in r.sql
        assert not [x for x in receipts if x["guard"] == "day_window"] and "repaired:day-window" not in r.doors


def test_a_models_repair_is_read_whole_before_it_runs(shop):
    # The live shape: the statement fails, the model's fix closes the window on the day.
    class _Coder:
        def complete(self, *, system, user, response_model):
            return response_model(fixed_sql=YEAR, explanation="joined the table the column is on")

    r = execute_guarded(shop, "SELECT SUM(sale_price) FROM order_items WHERE no_such_column = 1", query_id="answer",
                        fix_prompt_template=FIX_SQL_PROMPT, provider_factory=lambda role: _Coder())
    assert not r.error and float(r.rows[0][0]) == 115.0 and "created_at < '2026-01-01'" in r.sql


def test_unread_when_no_statement_bounds_a_day(monkeypatch, shop):
    # The schema is read only for a statement that could close on a day.
    reads = []
    monkeypatch.setattr(shop, "get_schema", lambda: reads.append(1) or "")
    execute_guarded(shop, "SELECT SUM(sale_price) FROM order_items WHERE created_at < '2026-01-01'", query_id="a")
    assert reads == []
