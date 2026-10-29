"""Arc BC-1 (ROADMAP §3.67) — what a block may read.

A breakdown is compiled, never written: each segment against its own usual range, the one that carries the move
first, a segment of a few rows too few to call. A model's SELECT goes through the Data Canvas's guarded door with
room for a table's rows; a refusal is kept with its repair and never read as an empty answer.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import duckdb
import pytest

from aughor.briefing import edition as E
from aughor.briefing import guide as G
from aughor.briefing import ranges
from aughor.briefing.compose import sources as S

OCT29 = date(2026, 10, 29)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE orders AS
        WITH days AS (SELECT d::DATE AS d FROM range(DATE '2026-06-01', DATE '2026-10-29', INTERVAL 1 DAY) t(d))
        SELECT d AS order_date, 'A' AS platform, i < 8 AS is_top,
               CASE WHEN d BETWEEN DATE '2026-10-19' AND DATE '2026-10-25' AND i < 8 THEN 400.0
                    ELSE 100.0 + (EXTRACT(week FROM d) % 3) * 4 END AS gmv
        FROM days, range(30) k(i)
        UNION ALL SELECT d, 'B', false, 50.0 + (EXTRACT(week FROM d) % 2) * 2 FROM days, range(10) k(i)
        UNION ALL SELECT d, 'tiny', false, 75.0 FROM days""")
    yield c
    c.close()


def _run(con):
    def run(sql):
        try:
            cur = con.execute(sql)
            return [d[0] for d in cur.description], cur.fetchall(), None
        except Exception as exc:  # noqa: BLE001
            return [], [], str(exc)
    return run


@pytest.fixture
def week():
    spec, why = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="learned")
    assert spec is not None, why
    return spec


SALES = {"name": "sales", "sql": "SUM(gmv)", "tables": ["orders"], "filters": [], "time_column": "orders.order_date",
         "time_kind": "flow"}


def test_a_breakdown_puts_the_segment_that_carries_the_move_first_and_a_tiny_one_last(con, week):
    src = S.breakdown("sales_by_platform", "Sales by storefront", SALES, "platform", week, usual_n=8,
                      run_sql=_run(con), dialect="duckdb", unit="EUR", better="up")
    assert src.columns == S.BREAKDOWN_COLUMNS and src.kind == "breakdown" and not src.error
    first, last = src.rows[0], src.rows[-1]
    assert first[0] == "A" and first[3] > 0                      # A carries the week's rise
    assert last[0] == "tiny" and last[6] is True                 # 7 rows: too few to call, listed last
    assert "SELECT" in src.sql.upper() and "usual" in src.note


def test_a_breakdown_by_any_column_of_the_dated_table_not_only_a_declared_one(con, week):
    src = S.breakdown("sales_by_top", "Sales by top client", SALES, "is_top", week, usual_n=8,
                      run_sql=_run(con), dialect="duckdb")
    by = {r[0]: r for r in src.rows}
    assert by[True][3] > 0 and abs(by[False][3]) < by[True][3]   # the top clients carried it


def test_a_breakdown_that_cannot_be_measured_is_refused_and_said(con, week):
    bad = S.breakdown("x", "X", SALES, "no_such_column", week, usual_n=8, run_sql=_run(con), dialect="duckdb")
    assert bad.status == "refused" and "query failed" in bad.error and bad.rows == []
    worse = S.breakdown("y", "Y", SALES, "platform; DROP TABLE orders", week, usual_n=8, run_sql=_run(con),
                        dialect="duckdb")
    assert worse.status == "refused" and "not a column name" in worse.error


def test_a_measured_check_reads_as_a_source(con, week, monkeypatch):
    monkeypatch.setattr(ranges, "governed_metrics", lambda *a, **k: [])
    check = G.Check(id="aov", label="Average order", sql="AVG(gmv)", tables=["orders"],
                    time_column="orders.order_date", unit="EUR", better="up")
    fig, why = E.measure_check(check, E.measurable(check, {})[0], week, guide=G.BriefingGuide(), published=False,
                               run_sql=_run(con), dialect="duckdb", currency="")
    assert fig, why
    src = S.from_check(fig, period_word="week")
    assert src.kind == "check" and src.rows[-1][2] is True and len(src.rows) == 9
    assert src.facts["usual_low"] < src.facts["usual_high"] < src.facts["current"]
    assert "8 weeks before" in src.note


def test_a_model_select_goes_through_the_guarded_door_with_room_for_a_table():
    asked = {}

    def run(conn_id, args, *, user_question, schema_scope, max_rows):
        asked.update(conn_id=conn_id, sql=args["sql"], q=user_question, schema=schema_scope, max_rows=max_rows)
        return {"columns": ["order_id", "day", "value"], "rows": [("O1", date(2026, 10, 23), Decimal("3459.10"))],
                "guard_receipts": [{"guard": "fanout", "verdict": "clean"}], "caveats": [], "truncated": False}

    src = S.query("top_orders", "The largest orders", "c1", "SELECT order_id, order_date, gmv_eur FROM orders",
                  purpose="the week's largest orders", schema="lux", run=run)
    assert asked == {"conn_id": "c1", "sql": "SELECT order_id, order_date, gmv_eur FROM orders",
                     "q": "the week's largest orders", "schema": "lux", "max_rows": S.MAX_ROWS}
    assert src.rows == [["O1", "2026-10-23", 3459.1]]            # JSON-safe, once
    assert src.receipts and src.status == "final"


def test_a_refused_select_is_kept_with_its_repair_never_read_as_empty():
    def run(conn_id, args, **kw):
        return {"error": "[EXCLUDED] price_history is turned off for analysis",
                "repair": {"kind": "excluded", "instruction": "use another table"}, "guard_receipts": []}

    src = S.query("q", "Markdowns", "c1", "SELECT * FROM price_history", purpose="markdowns", run=run)
    assert src.status == "refused" and "turned off" in src.error and src.rows == []
    seen = S.for_model(src)
    assert seen["error"] and seen["repair"] == "use another table" and "rows" not in seen


def test_the_model_is_shown_a_trimmed_source():
    src = S.Source(id="s", label="S", kind="query", columns=["a"], rows=[[i] for i in range(40)],
                   facts={"current": 1.0, "current_text": "1"})
    seen = S.for_model(src)
    assert len(seen["rows"]) == 25 and seen["rows_not_shown"] == 15 and "current_text" not in seen["facts"]


def test_numbers_the_guarded_door_returns_as_text_become_numbers_but_an_id_stays_text():
    rows = S.typed(["wk", "orders", "aov", "order_id", "zip_code"],
                   [["2026-10-19", "259", "645.2", "00123", "02134"], ["2026-10-12", "255", "623", "00124", "NULL"]])
    assert rows[0][1:3] == [259, 645.2] and rows[1][1:3] == [255, 623]
    assert rows[0][0] == "2026-10-19" and rows[0][3] == "00123" and rows[0][4] == "02134"


def test_a_query_source_carries_typed_numbers():
    def run(conn_id, args, **kw):
        return {"columns": ["platform", "orders"], "rows": [("Mytheresa", "72"), ("YOOX", "100")], "guard_receipts": []}
    src = S.query("q", "Q", "c1", "SELECT 1", purpose="p", run=run)
    assert src.rows == [["Mytheresa", 72], ["YOOX", 100]]
