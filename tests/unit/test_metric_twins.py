"""One measure, one approved definition (the user, 2026-10-08: "Why should we have duplicates?").

theLook held Return rate and Item Return Rate, and Gross Margin Percentage and Gross Margin Rate —
one figure each under two names — because the only check was on the name. These run the real
measurement on a DuckDB shop: two statements that differ as text and agree as figures are one
measure; a percent of the same share is too; a different measure over the same table is not.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from datetime import date, timedelta

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.semantic import metric_twins as T
from aughor.semantic.metrics import MetricDefinition

TODAY = date.today()


@pytest.fixture
def con():
    """One item a day for 200 days, every third returned two days later."""
    c = duckdb.connect()
    start = TODAY - timedelta(days=200)
    c.execute(f"""CREATE TABLE order_items AS
        SELECT row_number() OVER () AS id, d::TIMESTAMP + INTERVAL 9 HOUR AS created_at,
               CASE WHEN (row_number() OVER ()) % 3 = 0 THEN d::TIMESTAMP + INTERVAL 2 DAY END AS returned_at,
               CAST(10 + day(d) AS DOUBLE) AS sale_price
        FROM range(DATE '{start}', DATE '{TODAY}', INTERVAL 1 DAY) t(d)""")
    c.execute("CREATE TABLE users AS SELECT 1 AS id, TIMESTAMP '2026-01-01' AS created_at")
    yield c
    c.close()


def _runner(con):
    @contextlib.contextmanager
    def open_():
        def run_sql(sql):
            try:
                cur = con.execute(sql)
                return [d[0] for d in cur.description], cur.fetchall(), None
            except Exception as exc:  # noqa: BLE001
                return [], [], str(exc)
        yield run_sql, "duckdb"
    return open_


def _metric(name, sql, *, kind="cohort", status="approved", **kw):
    dates = ({"time_column": "order_items.created_at", "outcome_column": "order_items.returned_at"}
             if kind == "cohort" else {"time_column": "order_items.created_at"})
    return MetricDefinition(name=name, label=kw.pop("label", name.replace("_", " ").title()), sql=sql,
                            connection="c1", status=status, time_kind=kind, **{**dates, **kw})


RETURN_RATE = _metric("return_rate", "SELECT (SUM(CASE WHEN returned_at IS NOT NULL THEN 1.0 ELSE 0.0 END) "
                                     "/ NULLIF(COUNT(*), 0)) AS return_rate FROM order_items", label="Return rate")
ITEM_RETURN_RATE = _metric("item_return_rate", "SELECT CAST(COUNT(returned_at) AS DOUBLE) / NULLIF(COUNT(*), 0) "
                                               "AS item_return_rate FROM order_items", status="proposed")
RETURN_PCT = _metric("return_pct", "SELECT 100.0 * COUNT(returned_at) / NULLIF(COUNT(id), 0) FROM order_items",
                     status="proposed")
REVENUE = _metric("revenue", "SELECT SUM(sale_price) AS revenue FROM order_items", kind="flow")


def _twin(m, approved, con):
    with _runner(con)() as (run_sql, dialect):
        return T.twin_of(m, approved, run_sql=run_sql, dialect=dialect, today=TODAY)


def test_two_statements_that_agree_as_figures_are_one_measure(con):
    got = _twin(ITEM_RETURN_RATE, [RETURN_RATE, REVENUE], con)
    assert got["twin"] == {"name": "return_rate", "label": "Return rate"} and got["checked"]
    assert got["months"] == T.TWIN_MONTHS
    assert "measures exactly what Return rate measures" in T.said(ITEM_RETURN_RATE, got)


def test_a_share_written_as_a_percent_is_the_same_measure(con):
    assert _twin(RETURN_PCT, [RETURN_RATE], con)["twin"]["name"] == "return_rate"


def test_a_different_measure_over_the_same_table_is_not(con):
    gross = _metric("units", "SELECT COUNT(*) AS units FROM order_items", kind="flow", status="proposed")
    got = _twin(gross, [RETURN_RATE, REVENUE], con)
    assert got == {"twin": None, "months": 0, "checked": True, "why": ""}


def test_only_definitions_over_the_same_tables_are_measured(con):
    other = _metric("signups", "SELECT COUNT(*) FROM users", kind="flow")
    assert T.candidates(ITEM_RETURN_RATE, [other]) == []
    seen: list[str] = []

    @contextlib.contextmanager
    def counting():
        with _runner(con)() as (run_sql, d):
            yield (lambda sql: (seen.append(sql), run_sql(sql))[1]), d
    with counting() as (run_sql, dialect):
        assert T.twin_of(ITEM_RETURN_RATE, [other], run_sql=run_sql, dialect=dialect, today=TODAY)["twin"] is None
    assert seen == []


def test_too_few_months_are_never_called_one_measure():
    assert T.agree([0.3, 0.3, None, None, None, None], [0.3, 0.3, 0.1, None, None, None]) is False
    assert T.agree([0.3, 0.31, 0.32], [30.0, 31.0, 32.0]) is True
    assert T.agree([0.3, 0.31, 0.32], [0.3, 0.31, 0.33]) is False


def test_figures_that_cannot_be_read_are_said_not_taken_for_no_twin(con):
    undated = ITEM_RETURN_RATE.model_copy(update={"time_column": None})
    got = _twin(undated, [RETURN_RATE], con)
    assert got["checked"] is False and got["twin"] is None and got["why"] == "its dates are not set"


# ── the approval ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch, con):
    from aughor.knowledge import period_brief
    from aughor.semantic import metrics as m
    monkeypatch.setattr(m, "_DEFAULT_PATH", tmp_path / "metrics.json", raising=False)
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.json"))
    monkeypatch.setattr(period_brief, "connection_runner", lambda conn_id, **kw: _runner(con)())
    from aughor.api import app
    with TestClient(app) as c:
        yield c


def test_approving_a_second_definition_of_one_measure_is_refused_with_the_others_name(client):
    from aughor.semantic.metrics import save_metric
    conn = f"c{uuid.uuid4().hex[:6]}"
    save_metric(RETURN_RATE.model_copy(update={"connection": conn}))
    save_metric(ITEM_RETURN_RATE.model_copy(update={"connection": conn}))
    url = "/metrics/item_return_rate/transition"

    refused = client.post(url, json={"action": "approve", "connection": conn})
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["reason"] == "same_as_approved" and detail["twin"]["name"] == "return_rate"
    assert "measures exactly what Return rate measures" in detail["message"]
    stays = [x for x in client.get(f"/metrics?connection_id={conn}").json() if x["name"] == "item_return_rate"]
    assert stays[0]["status"] == "proposed"

    anyway = client.post(url, json={"action": "approve", "connection": conn, "approve_anyway": True})
    assert anyway.status_code == 200, anyway.text
    assert anyway.json()["metric"]["status"] == "approved"
    assert anyway.json()["audit"]["approved_though_same_as"] == "return_rate"


def test_a_measure_of_its_own_is_approved_without_asking(client):
    from aughor.semantic.metrics import save_metric
    conn = f"c{uuid.uuid4().hex[:6]}"
    save_metric(RETURN_RATE.model_copy(update={"connection": conn}))
    save_metric(_metric("units", "SELECT COUNT(*) AS units FROM order_items", kind="flow",
                        status="proposed").model_copy(update={"connection": conn}))
    ok = client.post("/metrics/units/transition", json={"action": "approve", "connection": conn})
    assert ok.status_code == 200, ok.text
    assert "approved_though_same_as" not in ok.json()["audit"]
    assert json.dumps(ok.json()["audit"]).count("not read") == 0
