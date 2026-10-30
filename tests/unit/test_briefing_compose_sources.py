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


# ── what the platform already knows ──────────────────────────────────────────────────────────

def test_the_explorers_confident_findings_are_read_a_synthesis_first_and_only_the_canvas_tables_in_a_canvas():
    by_domain = {
        "General": [{"id": "g1", "finding": "AOV is 387 EUR.", "confidence": 0.7, "impact": 0.5,
                     "signature": {"tables": ["orders"]}},
                    {"id": "g2", "finding": "Summing fiscal_year gives 133,524.", "confidence": 0.5, "impact": 0.1,
                     "signature": {"tables": ["events"]}}],
        "Synthesis": [{"id": "s1", "finding": "Repeat customers carry 95.0% of GMV.", "confidence": 0.8, "impact": 0.6,
                       "signature": {"tables": ["orders", "customers"]}}],
    }
    got = S.known_findings(by_domain)
    assert [s.facts["finding_id"] for s in got] == ["s1", "g1"]            # weak one out; the synthesis first
    assert got[0].kind == "finding" and got[0].id == "finding_1"
    assert [s.facts["finding_id"] for s in S.known_findings(by_domain, tables=("orders",))] == ["g1"]


def _runs():
    return [
        {"id": "a2", "connection_id": "c1", "kind": "investigation", "status": "complete", "completed_at": "2026-10-28",
         "question": "[Scheduled-run context — written by code, not inferred]\nweekly\n\nWhy did revenue rise in September?",
         "headline": "Revenue rose €93,820 on order volume"},
        {"id": "a1", "connection_id": "c1", "kind": "investigation", "status": "complete", "completed_at": "2026-10-20",
         "question": "Why did revenue rise in September?", "headline": "an older answer"},
        {"id": "x", "connection_id": "c2", "kind": "investigation", "status": "complete", "headline": "another dataset"},
        {"id": "c", "connection_id": "c1", "kind": "chat", "status": "complete", "headline": "a quick answer"},
        {"id": "r", "connection_id": "c1", "kind": "investigation", "status": "running", "headline": ""},
    ]


def _report(inv_id):
    return {"report": {"headline": "Revenue rose €93,820 on order volume", "executive_summary": "Orders rose 16.8%.",
                       "closing_summary": "Volume, not basket.", "confidence": "HIGH",
                       "causal_checks": {"licence": "causal"}, "recommendations": [{"action": "Watch Mytheresa"}]}}


def test_the_latest_finished_deep_analyses_are_read_one_per_question_with_their_licence():
    got = S.known_analyses("c1", list_runs=_runs, get_run=_report)
    assert [s.id for s in got] == ["analysis_a2"]                          # the question asked again: newest answer
    a = got[0]
    assert a.facts["question"] == "Why did revenue rise in September?"     # the scheduled preamble is not the question
    assert a.facts["licence"] == "causal" and a.facts["confidence"] == "HIGH" and a.status == "final"
    assert a.facts["recommendations"] == ["Watch Mytheresa"]


def test_decisions_in_force_in_the_range_are_read_once_each_and_an_approval_is_not_a_decision(week):
    rows = [
        {"id": "d_fee", "question": "A 9.90 EUR return fee", "chosen": "introduce it", "decided_at": "2026-08-01",
         "review_on": "2026-11-01", "source": {"kind": "declared"}},
        {"id": "d_fee2", "question": "A 9.90 EUR return fee", "chosen": "introduce it", "decided_at": "2026-08-01",
         "review_on": "2026-11-01", "source": {"kind": "declared"}},
        {"id": "d_old", "question": "Raise safety stock", "chosen": "raise it", "decided_at": "2025-03-01",
         "review_on": "2025-04-01", "outcome": "o1", "outcome_verdict": "cannot_tell", "source": {"kind": "declared"}},
        {"id": "d_later", "question": "Extend the edit", "chosen": "extend", "decided_at": "2026-10-27",
         "review_on": "2026-11-27", "source": {"kind": "declared"}},
        {"id": "d_ui", "question": "A dashboard of customer metrics", "chosen": "approve", "decided_at": "2026-10-20",
         "review_on": "2026-11-20", "source": {"kind": "approval"}},
    ]
    got = S.known_decisions("c1", week, list_fn=lambda: rows)
    assert [s.facts["decision_id"] for s in got] == ["d_fee"]              # once; not the closed one, the later one, a UI approval
    assert got[0].facts["state"] == "due for review 2026-11-01"


def test_a_started_deep_analysis_reads_as_running_until_it_finishes():
    src = S.started_analysis("analysis_started", "Why did refunds fall in September?", "briefing:k")
    assert src.status == "running"
    assert S.refreshed(src, runs_for=lambda s: [], get_run=_report) is src
    running = S.refreshed(src, runs_for=lambda s: [{"id": "n1", "status": "running"}], get_run=_report)
    assert running.status == "running" and running.facts["inv_id"] == "n1"
    done = S.refreshed(src, runs_for=lambda s: [{"id": "n1", "status": "complete", "completed_at": "2026-10-30",
                                                  "question": "Why did refunds fall?"}], get_run=_report)
    assert done.status == "final" and done.facts["headline"].startswith("Revenue rose") and done.facts["started_by_edition"]
