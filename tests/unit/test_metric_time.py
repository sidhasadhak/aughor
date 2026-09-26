"""Arc BR-2 (ROADMAP §3.48) — a metric that knows its date.

The rules are fed theLook's own definitions (revenue, units sold, the return rate) and must set
the dates a person would; the compiler's figures must equal the same figures written by hand in
SQL on a DuckDB shop; a cohort counts its outcome only up to the window's as-of; a stock is a
level, not a sum.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pytest

from aughor.semantic import metric_time as mt
from aughor.semantic.metric_time import Window

def _cols(table: str, **dtypes) -> dict:
    """The profiler's real shape: columns keyed FLAT as "table.column" (theLook, 2026-09-26)."""
    return {f"{table}.{c}": {"table": table, "column": c, "dtype": d} for c, d in dtypes.items()}


PROFILE = {
    "tables": {"order_items": {"primary_timestamp": "created_at"},
               "inventory_items": {"primary_timestamp": "created_at"}},
    "columns": {**_cols("order_items", id="INT64", created_at="TIMESTAMP", returned_at="TIMESTAMP",
                        status="STRING", sale_price="FLOAT64"),
                **_cols("inventory_items", id="INT64", created_at="TIMESTAMP", sold_at="TIMESTAMP",
                        cost="FLOAT64")},
}

# theLook's definitions on this deployment (2026-09-26), the return rate as approved (§6 item 34(h))
REVENUE = {"name": "revenue", "sql": "SUM(sale_price)", "tables": ["order_items"],
           "filters": ["status <> 'Cancelled'"]}
UNITS_SOLD = {"name": "units_sold", "sql": "COUNT(id)", "tables": ["inventory_items"],
              "filters": ["sold_at IS NOT NULL"]}
RETURN_RATE = {"name": "return_rate", "tables": ["order_items"],
               "sql": "SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)",
               "filters": ["status NOT IN ('Cancelled', 'Processing')"]}
ON_HAND = {"name": "on_hand", "sql": "COUNT(id)", "tables": ["inventory_items"],
           "filters": ["sold_at IS NULL"]}


def _with(metric: dict, **fields) -> dict:
    return {**metric, **mt.infer(metric, PROFILE).fields, **fields}


def test_the_rules_set_the_dates_a_person_would():
    assert {k: v for k, v in mt.infer(REVENUE, PROFILE).fields.items() if k != "time_source"} == {
        "time_kind": "flow", "time_column": "created_at", "outcome_column": None, "until_column": None}
    units = mt.infer(UNITS_SOLD, PROFILE).fields
    assert (units["time_kind"], units["time_column"]) == ("flow", "sold_at")
    rr = mt.infer(RETURN_RATE, PROFILE).fields
    assert (rr["time_kind"], rr["time_column"], rr["outcome_column"]) == ("cohort", "created_at", "returned_at")
    assert "tied to created_at and completed by returned_at" in rr["time_source"]
    stock = mt.infer(ON_HAND, PROFILE).fields
    assert (stock["time_kind"], stock["time_column"], stock["until_column"]) == ("stock", "created_at", "sold_at")
    # A statement is read too (2026-09-26): its date is written as the grain, `table.column`.
    whole = mt.infer({**REVENUE, "sql": "SELECT SUM(sale_price) FROM order_items"}, PROFILE).fields
    assert (whole["time_kind"], whole["time_column"]) == ("flow", "order_items.created_at")


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE order_items (id INT, created_at TIMESTAMP, returned_at TIMESTAMP, "
              "status VARCHAR, sale_price DOUBLE)")
    rows = [
        (1, "2026-08-17 10:00", None, "Complete", 100.0),
        (2, "2026-08-20 10:00", "2026-09-02 09:00", "Returned", 50.0),
        (3, "2026-08-26 23:00", "2026-09-30 09:00", "Returned", 30.0),   # returned after the as-of
        (4, "2026-08-21 10:00", None, "Cancelled", 999.0),                # never counts
        (5, "2026-08-05 10:00", "2026-08-12 09:00", "Returned", 40.0),    # the comparison window
        (6, "2026-08-10 10:00", None, "Shipped", 60.0),
        (7, "2026-08-27 00:00", None, "Complete", 70.0),                  # the day after the range
    ]
    c.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", rows)
    c.execute("CREATE TABLE inventory_items (id INT, created_at TIMESTAMP, sold_at TIMESTAMP, cost DOUBLE)")
    c.executemany("INSERT INTO inventory_items VALUES (?, ?, ?, ?)", [
        (1, "2026-08-01", "2026-08-18", 10.0), (2, "2026-08-01", None, 10.0),
        (3, "2026-08-15", "2026-08-30", 10.0), (4, "2026-08-25", None, 10.0),
        (5, "2026-09-01", None, 10.0)])
    return c


def _run(con):
    def run(sql):
        cur = con.execute(sql)
        return [d[0] for d in cur.description], cur.fetchall(), None
    return run


RANGE = Window("current", date(2026, 8, 17), date(2026, 8, 27))
BEFORE = Window("previous", date(2026, 8, 3), date(2026, 8, 13))


def _values(rows):
    return {r["window"]: r["value"] for r in rows}


def test_a_flow_for_the_users_range_equals_the_hand_written_sql(con):
    rows, why = mt.run_measure(_with(REVENUE), [RANGE, BEFORE], _run(con))
    assert why == ""
    hand = con.execute("SELECT SUM(sale_price) FROM order_items WHERE status <> 'Cancelled' AND "
                       "CAST(created_at AS DATE) >= DATE '2026-08-17' AND "
                       "CAST(created_at AS DATE) < DATE '2026-08-27'").fetchone()[0]
    assert _values(rows) == {"current": hand, "previous": 100.0} == {"current": 180.0, "previous": 100.0}
    cur = next(r for r in rows if r["window"] == "current")
    assert (cur["first"], cur["last"]) == (date(2026, 8, 17), date(2026, 8, 26))


def test_a_cohort_counts_its_outcome_only_up_to_the_as_of(con):
    """Asked on 26 September, the 30 September return has not happened yet."""
    rr = _with(RETURN_RATE)
    rows, _ = mt.run_measure(rr, [Window("current", RANGE.start, RANGE.end, as_of=date(2026, 9, 26))], _run(con))
    assert _values(rows) == {"current": pytest.approx(1 / 3)}   # lines 1, 2, 3: only line 2 back by then
    rows, _ = mt.run_measure(rr, [RANGE], _run(con))              # as known now: both returns
    assert _values(rows) == {"current": pytest.approx(2 / 3)}


def test_a_stock_is_a_level_at_the_windows_end_not_a_sum(con):
    on_hand = _with(ON_HAND)
    rows, _ = mt.run_measure(on_hand, [Window("current", date(2026, 8, 17), date(2026, 8, 27)),
                                       Window("previous", date(2026, 8, 3), date(2026, 8, 13))], _run(con))
    # on 27 Aug: items 2, 3 (sold 30 Aug), 4 — item 1 sold 18 Aug, item 5 not yet received
    assert _values(rows) == {"current": 3.0, "previous": 2.0}


def test_a_breakdown_groups_every_window(con):
    rows, _ = mt.run_measure(_with(REVENUE), [RANGE], _run(con), by="status")
    assert {(r["group"], r["value"]) for r in rows} == {("Complete", 100.0), ("Returned", 80.0)}


def test_an_outcome_used_some_other_way_is_refused_not_approximated():
    import sqlglot
    expr = sqlglot.parse_one("MAX(returned_at) - MIN(created_at)")
    out, why = mt.bound_outcome(expr, "returned_at", date(2026, 9, 26))
    assert out is None and "cannot rewrite" in why


def test_the_same_definition_compiles_for_bigquery():
    sql, why = mt.measure_sql(_with(RETURN_RATE), [Window("current", RANGE.start, RANGE.end,
                                                            as_of=date(2026, 9, 26))], dialect="bigquery")
    assert why == "" and "UNION" not in sql
    assert "CAST(returned_at AS DATE) < CAST('2026-09-26' AS DATE)" in sql
    assert "NOT status IN ('Cancelled', 'Processing')" in sql


@pytest.mark.parametrize("kind, maturity, as_of, status", [
    ("flow", None, date(2026, 9, 26), "final"),            # 31 days past its last day, lag 13
    ("flow", None, date(2026, 9, 5), "provisional"),       # 10 days: not settled
    ("flow", None, date(2026, 8, 20), "to_date"),          # the range is still under way
    ("cohort", 60, date(2026, 9, 26), "provisional"),      # returns arrive for 60 days
    ("cohort", None, date(2026, 12, 1), "provisional"),    # nobody measured when they stop
    ("cohort", 20, date(2026, 9, 26), "final"),
])
def test_a_figure_says_whether_it_is_final(kind, maturity, as_of, status):
    metric = {"time_kind": kind, "settles_after_days": maturity}
    assert mt.figure_status(metric, RANGE, as_of=as_of, lag_days=13) == status


def test_a_cohorts_maturity_is_measured_from_its_own_rows(con):
    con.execute("DELETE FROM order_items")
    rows = [(i, f"2026-0{3 + i % 3}-10 10:00", f"2026-0{3 + i % 3}-{10 + (i % 20):02d} 10:00",
             "Returned", 10.0) for i in range(40)]
    con.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", rows)
    days, how = mt.measure_maturity(_with(RETURN_RATE), _run(con), dialect="duckdb", today=date(2026, 9, 26))
    assert days == 18 and "95% of returned_at arrived within 18 days of created_at" in how
    few, why = mt.measure_maturity(_with(RETURN_RATE), _run(con), dialect="duckdb", today=date(2025, 1, 1))
    assert few is None and "too few" in why


def test_an_edit_that_does_not_send_the_dates_keeps_them_and_a_sent_one_is_a_persons():
    existing = {**_with(REVENUE), "time_confirmed_by": None}
    kept = mt.merge_time_edit(existing, {})
    assert kept["time_column"] == "created_at" and kept["time_source"].startswith("set automatically")
    fixed = mt.merge_time_edit(existing, {"time_column": "shipped_at", "time_confirmed_by": "Ana"})
    assert fixed["time_column"] == "shipped_at" and fixed["time_source"] == "set by Ana in the metric editor"
    ok = mt.merge_time_edit(existing, {"time_confirmed_by": "Ana"})
    assert ok["time_source"].startswith("set automatically") and ok["time_source"].endswith("; confirmed by Ana")
    with pytest.raises(ValueError):
        mt.merge_time_edit(existing, {"time_kind": "sometimes"})
