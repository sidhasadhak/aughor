"""A metric's SQL is a statement, and its grain is `schema.table.column` (2026-09-26).

Pinned: a statement is recognised and an expression is wrapped exactly as the value path
always wrapped it; the tables a statement reads are found with its CTEs excluded; a
statement is cut to a range by substituting the grain's table, so a CTE'd statement and the
expression it replaces measure the SAME number on the same rows, cohort bound included; what
a statement cannot have is said; the rule sets a statement's dates as the grain; the doors
refuse a new bare aggregate but keep an old one until its formula changes; the proposals
door offers the runnable statement for an expression and the dates on the statement's OWN
tables only, the main date first.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.semantic import metric_statement as ms
from aughor.semantic import metric_time as mt

client = TestClient(app)

PROFILE = {
    "tables": {"order_items": {"primary_timestamp": "created_at"},
               "inventory_items": {"primary_timestamp": "created_at"}},
    "columns": {
        "order_items.id": {"table": "order_items", "column": "id", "dtype": "INT64"},
        "order_items.created_at": {"table": "order_items", "column": "created_at", "dtype": "TIMESTAMP"},
        "order_items.returned_at": {"table": "order_items", "column": "returned_at", "dtype": "TIMESTAMP"},
        "order_items.status": {"table": "order_items", "column": "status", "dtype": "STRING"},
        "inventory_items.created_at": {"table": "inventory_items", "column": "created_at", "dtype": "TIMESTAMP"},
        "inventory_items.sold_at": {"table": "inventory_items", "column": "sold_at", "dtype": "TIMESTAMP"},
        "inventory_items.cost": {"table": "inventory_items", "column": "cost", "dtype": "FLOAT64"},
    },
}


# ── the words ─────────────────────────────────────────────────────────────────────────

def test_a_statement_is_a_select_or_a_with_and_an_expression_is_wrapped_as_before():
    assert ms.is_statement("SELECT 1") and ms.is_statement("  with x as (select 1) select * from x")
    assert not ms.is_statement("SUM(amount)") and not ms.is_statement("")
    assert ms.as_statement("SUM(amount)", ["orders"], ["status = 'active'"], "revenue") == \
        "SELECT (SUM(amount)) AS revenue FROM orders WHERE status = 'active'"
    assert ms.as_statement("SELECT SUM(x) FROM t", ["orders"], ["a=1"], "n") == "SELECT SUM(x) FROM t"
    assert ms.as_statement("COUNT(*)", [], [], "Return Rate") == "SELECT (COUNT(*)) AS return_rate"
    assert ms.as_statement("COUNT(*)", [], [], "_v") == "SELECT (COUNT(*)) AS _v"


def test_split_grain_and_statement_tables():
    assert ms.split_grain("ecommerce.order_items.created_at") == ("ecommerce.order_items", "created_at")
    assert ms.split_grain("created_at") == (None, "created_at")
    assert ms.split_grain(None) == (None, "")
    sql = ("WITH ok AS (SELECT * FROM shop.order_items WHERE status <> 'Cancelled'), "
           "u AS (SELECT * FROM users) SELECT SUM(sale_price) FROM ok JOIN u ON ok.user_id = u.id")
    assert ms.statement_tables(sql) == ["shop.order_items", "users"]      # CTE names are not tables
    assert ms.statement_tables("not sql at all (") == []


def test_scoped_statement_substitutes_the_grains_table_and_says_when_it_is_absent():
    from sqlglot import exp
    when = exp.condition("status = 'x'")
    sql = "WITH ok AS (SELECT * FROM order_items o WHERE o.id > 0) SELECT COUNT(*) FROM ok"
    out, why, n = ms.scoped_statement(sql, "order_items", when)
    assert n == 1 and why == ""
    assert "(SELECT * FROM order_items WHERE status = 'x') AS o" in out    # the alias survives
    assert "FROM ok" in out                                                # the CTE is untouched
    out, why, n = ms.scoped_statement(sql, "customers", when)
    assert out is None and n == 0 and "does not read customers" in why


# ── the range cut: a statement measures what its expression measured ─────────────────

@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE order_items (id INT, created_at TIMESTAMP, returned_at TIMESTAMP, "
              "status VARCHAR, sale_price DOUBLE)")
    c.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", [
        (1, "2026-08-17 10:00", None, "Complete", 100.0),
        (2, "2026-08-20 10:00", "2026-09-02 09:00", "Returned", 50.0),
        (3, "2026-08-26 23:00", "2026-09-30 09:00", "Returned", 30.0),   # returned after the as-of
        (4, "2026-08-21 10:00", None, "Cancelled", 999.0),                # never counts
        (5, "2026-08-05 10:00", "2026-08-12 09:00", "Returned", 40.0),    # the comparison window
        (6, "2026-08-10 10:00", None, "Shipped", 60.0),
        (7, "2026-08-27 00:00", None, "Complete", 70.0),                  # the day after the range
    ])
    return c


def _runner(con):
    def run_sql(sql):
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchall(), None
        except Exception as exc:  # noqa: BLE001
            return [], [], str(exc)
    return run_sql


WINDOWS = [mt.Window("current", date(2026, 8, 17), date(2026, 8, 27), as_of=date(2026, 9, 26)),
           mt.Window("previous", date(2026, 8, 7), date(2026, 8, 17), as_of=date(2026, 9, 26))]

REVENUE_EXPR = {"name": "revenue", "sql": "SUM(sale_price)", "tables": ["order_items"],
                "filters": ["status <> 'Cancelled'"], "time_kind": "flow", "time_column": "created_at"}
REVENUE_STMT = {"name": "revenue", "tables": [], "filters": [], "time_kind": "flow",
                "time_column": "order_items.created_at",
                "sql": ("WITH ok AS (SELECT * FROM order_items WHERE status <> 'Cancelled') "
                        "SELECT SUM(sale_price) AS revenue FROM ok")}
RR_EXPR = {"name": "return_rate", "tables": ["order_items"],
           "sql": "SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)",
           "filters": ["status NOT IN ('Cancelled', 'Processing')"], "time_kind": "cohort",
           "time_column": "created_at", "outcome_column": "returned_at", "settles_after_days": 30}
RR_STMT = {**RR_EXPR, "tables": [], "filters": [], "time_column": "order_items.created_at",
           "outcome_column": "order_items.returned_at",
           "sql": ("SELECT SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0) "
                   "AS return_rate FROM order_items WHERE status NOT IN ('Cancelled', 'Processing')")}


def _values(rows):
    return {r["window"]: (r["value"], r["first"], r["last"], r["n"]) for r in rows}


def test_a_cted_statement_measures_the_same_number_as_its_expression(con):
    run = _runner(con)
    expr, why_e = mt.run_measure(REVENUE_EXPR, WINDOWS, run)
    stmt, why_s = mt.run_measure(REVENUE_STMT, WINDOWS, run)
    assert why_e == "" and why_s == ""
    assert _values(expr)["current"][0] == 180.0 == _values(stmt)["current"][0]   # 100 + 50 + 30
    assert _values(expr)["previous"][0] == 60.0 == _values(stmt)["previous"][0]   # row 6 alone
    # the days behind the figure are read from the grain table under the same filter
    assert _values(stmt)["current"][1:3] == (date(2026, 8, 17), date(2026, 8, 26))


def test_a_cohort_statement_takes_the_as_of_bound_like_its_expression(con):
    run = _runner(con)
    expr, _ = mt.run_measure(RR_EXPR, WINDOWS, run)
    stmt, why = mt.run_measure(RR_STMT, WINDOWS, run)
    assert why == ""
    # rows 1, 2, 3 in the window; only row 2 returned before the as-of → 1/3
    assert round(_values(expr)["current"][0], 4) == round(1 / 3, 4) == round(_values(stmt)["current"][0], 4)


def test_what_a_statement_cannot_have_is_said(con):
    assert mt.measure_sql(REVENUE_STMT, WINDOWS, by="status") == (None, "a whole query cannot be cut by a segment — its segments are its own")
    sql, why = mt.measure_sql({**REVENUE_STMT, "time_column": "customers.created_at"}, WINDOWS)
    assert sql is None and "does not read customers" in why
    sql, why = mt.measure_sql({**REVENUE_STMT, "time_column": "created_at"}, WINDOWS)
    assert sql is None and "names no table" in why           # a bare column on a statement with no tables
    sql, why = mt.measure_sql({**REVENUE_STMT, "time_column": "created_at", "tables": ["order_items"]}, WINDOWS)
    assert sql and why == ""                                  # the definition's first table serves


# ── the rule reads a statement, and writes the grain ─────────────────────────────────

def test_the_rule_sets_a_statements_dates_as_its_grain():
    flow = mt.infer({"sql": "SELECT COUNT(id) AS units FROM inventory_items WHERE sold_at IS NOT NULL",
                     "tables": []}, PROFILE).fields
    assert (flow["time_kind"], flow["time_column"]) == ("flow", "inventory_items.sold_at")
    rr = mt.infer(RR_STMT, PROFILE).fields
    assert (rr["time_kind"], rr["time_column"], rr["outcome_column"]) == \
        ("cohort", "order_items.created_at", "order_items.returned_at")
    plain = mt.infer({"sql": "SELECT SUM(sale_price) FROM order_items", "tables": []}, PROFILE).fields
    assert (plain["time_kind"], plain["time_column"]) == ("flow", "order_items.created_at")   # the main date
    said = mt.infer({"sql": "SELECT 1 AS x", "tables": []}, PROFILE)
    assert said.fields is None and "reads no table" in said.reason
    # an expression's date stays bare, as every reader has always read it
    expr = mt.infer({"sql": "COUNT(id)", "tables": ["inventory_items"], "filters": ["sold_at IS NOT NULL"]}, PROFILE).fields
    assert expr["time_column"] == "sold_at"


# ── the proposals ─────────────────────────────────────────────────────────────────────

def test_date_candidates_come_from_the_statements_own_tables_only():
    out = ms.date_candidates(RR_STMT["sql"], [], PROFILE)
    assert [c["grain"] for c in out] == ["order_items.created_at", "order_items.returned_at"]
    assert out[0]["primary"] is True and out[1]["type"] == "timestamp"
    both = ms.date_candidates("SELECT 1", ["inventory_items", "shop.order_items"], PROFILE)
    assert [c["grain"] for c in both] == ["inventory_items.created_at", "inventory_items.sold_at",
                                          "shop.order_items.created_at", "shop.order_items.returned_at"]
    assert ms.date_candidates("SELECT 1", [], {}) == []
    # No table anywhere (theLook's draft return_rate): NOTHING is proposed — the user, 2026-09-26:
    # only the dates of "the table proposed in the SQL statement"; a first cut listed every
    # profiled table's main date here and was corrected.
    assert ms.date_candidates("SUM(CASE WHEN returned_at IS NOT NULL THEN 1 ELSE 0 END)", [], PROFILE) == []


def test_the_platform_proposes_the_runnable_statement_for_an_expression():
    rr = "SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)"
    # A statement as written proposes nothing: it is one.
    assert ms.proposed_statements(RR_STMT["sql"], [], [], "return_rate", PROFILE) == ([], "")
    # An expression over a declared table is wrapped as the value path runs it — one proposal.
    one, note = ms.proposed_statements("SUM(cost)", ["inventory_items"], ["sold_at IS NOT NULL"], "cogs", PROFILE)
    assert note == "" and [o["table"] for o in one] == ["inventory_items"]
    assert one[0]["statement"] == "SELECT (SUM(cost)) AS cogs FROM inventory_items WHERE sold_at IS NOT NULL"
    assert one[0]["why"] == "the stored expression over inventory_items with its filters"
    # No table declared: the profiled table carrying every referenced column — one carrier, one proposal.
    one, note = ms.proposed_statements(rr, [], [], "return_rate", PROFILE)
    assert note == "" and [o["table"] for o in one] == ["order_items"]
    assert one[0]["statement"].startswith("SELECT (SUM(CASE WHEN returned_at") and one[0]["statement"].endswith("FROM order_items")
    assert one[0]["why"] == "returned_at is a column of order_items"
    # Two carriers (theLook: `orders` carries returned_at too): two proposals and the note says to pick.
    # The largest table first (the finer grain): the field is filled with it, the other is offered.
    two_tables = {"tables": {"order_items": {"primary_timestamp": "created_at", "row_count": 181000},
                             "orders": {"primary_timestamp": "created_at", "row_count": 125000}},
                  "columns": {**PROFILE["columns"],
                              "orders.returned_at": {"table": "orders", "column": "returned_at", "dtype": "TIMESTAMP"}}}
    two, note = ms.proposed_statements(rr, [], [], "return_rate", two_tables)
    assert [o["table"] for o in two] == ["order_items", "orders"]
    assert note == ("returned_at is carried by order_items and orders — each table is a different metric; "
                    "proposed over order_items, the largest — switch if that is the wrong one")
    two_tables["tables"]["orders"]["row_count"] = 999999
    assert [o["table"] for o in ms.proposed_statements(rr, [], [], "return_rate", two_tables)[0]] == ["orders", "order_items"]
    # What cannot be proposed is said, never guessed.
    assert ms.proposed_statements("COUNT(*)", [], [], "n", PROFILE)[0] == []
    assert "names no column" in ms.proposed_statements("COUNT(*)", [], [], "n", PROFILE)[1]
    assert "no profiled table carries margin" in ms.proposed_statements("SUM(margin)", [], [], "m", PROFILE)[1]
    assert "no profile yet" in ms.proposed_statements("SUM(margin)", [], [], "m", {})[1]


def test_the_proposals_door_offers_statements_and_dates_or_says_why_not(monkeypatch):
    monkeypatch.setattr("aughor.tools.profile_cache.latest_profile_entry", lambda cid: PROFILE if cid == "c1" else {})
    door = "/metrics/proposals"
    body = client.post(door, json={"connection": "c1", "sql": RR_STMT["sql"], "name": "return_rate"}).json()
    assert body["statements"] == [] and body["statement_note"] == ""
    assert [c["grain"] for c in body["candidates"]] == ["order_items.created_at", "order_items.returned_at"]
    assert body["note"] == ""
    body = client.post(door, json={"connection": "never", "sql": "SELECT 1"}).json()
    assert body["candidates"] == [] and "no profile yet" in body["note"] and "no profile yet" in body["statement_note"]
    # theLook's draft: an expression with no table — the statement is proposed, and there is no date
    # until the FROM is written (the dates come from the statement's own table, never from elsewhere).
    rr = "SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) / NULLIF(COUNT(*), 0)"
    body = client.post(door, json={"connection": "c1", "sql": rr, "name": "return_rate"}).json()
    assert [o["table"] for o in body["statements"]] == ["order_items"]
    assert body["candidates"] == [] and body["note"].startswith("the statement names no table")
    # A statement over a table with no date: said.
    body = client.post(door, json={"connection": "c1", "sql": "SELECT COUNT(*) AS n FROM products"}).json()
    assert body["candidates"] == [] and body["note"] == "no date or timestamp column was profiled on products"


# ── the doors ─────────────────────────────────────────────────────────────────────────

def test_the_doors_require_a_statement_for_a_new_formula_and_keep_an_old_expression():
    res = client.post("/metrics", json={"name": "stmt_rule_bare", "label": "Bare", "sql": "SUM(amount)",
                                        "tables": ["orders"], "connection": "stmt-conn"})
    assert res.status_code == 422 and "whole SELECT statement" in res.json()["detail"]
    res = client.post("/metrics", json={"name": "stmt_rule_ok", "label": "Ok", "connection": "stmt-conn",
                                        "sql": "WITH o AS (SELECT * FROM orders) SELECT SUM(amount) AS revenue FROM o"})
    assert res.status_code == 201, res.text
    # A row written before the rule (seeded straight into the store) keeps its expression
    # while its dates are confirmed, and is refused only when the formula itself changes.
    from aughor.semantic.metrics import MetricDefinition, save_metric
    save_metric(MetricDefinition(name="stmt_rule_old", label="Old", sql="COUNT(*)", tables=["orders"],
                                 connection="stmt-conn"))
    old = client.get("/metrics?connection_id=stmt-conn").json()
    row = next(m for m in old if m["name"] == "stmt_rule_old")
    res = client.put("/metrics/stmt_rule_old", json={**row, "time_kind": "flow", "time_column": "orders.created_at",
                                                     "time_confirmed_by": "User1"})
    assert res.status_code == 200 and res.json()["time_column"] == "orders.created_at"
    res = client.put("/metrics/stmt_rule_old", json={**row, "sql": "COUNT(id)"})
    assert res.status_code == 422
    res = client.put("/metrics/stmt_rule_old", json={**row, "sql": "SELECT COUNT(id) AS n FROM orders"})
    assert res.status_code == 200


def test_the_value_path_still_wraps_an_old_expression_the_same_way():
    from aughor.semantic.metrics import MetricDefinition, value_query
    m = MetricDefinition(name="rev", label="Rev", sql="SUM(amount)", tables=["orders"], filters=["a = 1"])
    assert value_query(m) == "SELECT (SUM(amount)) AS _v FROM orders WHERE a = 1"
    s = MetricDefinition(name="rev", label="Rev", sql="SELECT SUM(amount) AS rev FROM orders", tables=[])
    assert value_query(s) == "SELECT SUM(amount) AS rev FROM orders"
