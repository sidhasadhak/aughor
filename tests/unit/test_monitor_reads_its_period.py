"""A monitor over a dated metric reads the metric's period, not all history (the Olist study, §Next item 5).

"Monthly GMV floor" warned below R$900,000 over Olist's approved GMV. August 2018, its last full month, is
R$848,860.10 — below the line — but the check read the metric's statement as written, over all history, and said
"read 13,494,400.74": an all-time total against a monthly line, so it could never fire. A single-value check over a
metric whose dates are set now reads the newest settled period of the metric's grain — month unless a person set
another, as the metric editor says — measured by the metric's own compiler, and says which period it read.

The compiled SQL runs on a real DuckDB here: green on a fake that returns a number would prove only the wording.
"""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from aughor.briefing import ranges as R
from aughor.monitors import runner
from aughor.monitors.models import Monitor
from aughor.semantic import metric_time as mt
from aughor.semantic.metrics import MetricDefinition

#: Olist's GMV as it is approved live: a statement over items joined to their orders, dated by the purchase.
GMV = ("SELECT SUM(oi.price) AS gmv_brl FROM olist.olist_order_items_dataset oi JOIN olist.olist_orders_dataset o "
       "ON o.order_id = oi.order_id WHERE o.order_status NOT IN ('canceled','unavailable')")
#: The data's month ends: July 2018, August 2018 (848.6 kept, 500 canceled), September 2018.
ORDERS = [("o1", "2018-07-10", "delivered", 950.0), ("o2", "2018-08-03", "delivered", 600.0),
          ("o3", "2018-08-30", "delivered", 248.6), ("o4", "2018-08-12", "canceled", 500.0),
          ("o5", "2018-09-02", "delivered", 11_695.4)]
ALL_HISTORY = 950.0 + 600.0 + 248.6 + 11_695.4


@pytest.fixture
def warehouse():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA olist")
    con.execute("CREATE TABLE olist.olist_orders_dataset (order_id VARCHAR, order_purchase_timestamp TIMESTAMP, "
                "order_status VARCHAR)")
    con.execute("CREATE TABLE olist.olist_order_items_dataset (order_id VARCHAR, price DOUBLE)")
    for oid, day, status, price in ORDERS:
        con.execute("INSERT INTO olist.olist_orders_dataset VALUES (?, ?, ?)", [oid, day, status])
        con.execute("INSERT INTO olist.olist_order_items_dataset VALUES (?, ?)", [oid, price])
    ran: list[tuple[str, str]] = []

    def scalar(sql, *, label, cast, sql_dialect, strict):
        ran.append((sql, sql_dialect))
        row = con.execute(sql).fetchone()
        return cast(row[0]) if row and row[0] is not None else None

    yield SimpleNamespace(scalar=scalar, dialect="duckdb", ran=ran)
    con.close()


def _gmv(**kw) -> MetricDefinition:
    fields = dict(name="gross_merchandise_value_item_price", connection="workspace", schema_name="olist",
                  label="Gross Merchandise Value (item price)", sql=GMV,
                  tables=["olist_order_items_dataset", "olist_orders_dataset"], status="approved",
                  time_column="olist.olist_orders_dataset.order_purchase_timestamp", time_kind="flow")
    fields.update(kw)
    return MetricDefinition(**fields)


def _floor(**kw) -> Monitor:
    return Monitor(conn_id="workspace", name="Monthly GMV floor", metric_name="gross_merchandise_value_item_price",
                   alert_on="threshold_cross", threshold_direction="below", warning_threshold=900.0,
                   critical_threshold=800.0, **kw)


@pytest.fixture
def asked(monkeypatch):
    """The metric the monitor names, and the ranges it asks for — the Briefing's own resolution, its clock and the
    data's edge pinned (the data runs to 2018-09-02; the newest settled month is August)."""
    calls: list[dict] = []
    state = {"metric": _gmv(), "today": date(2018, 9, 15)}

    def resolve_for(conn_id, preset=None, *, today=None, schema=None, **kw):
        calls.append({"conn_id": conn_id, "preset": preset, "schema": schema})
        return R.resolve_range(preset, today=state["today"], lag_days=1, lag_source="test", **kw)

    monkeypatch.setattr(R, "resolve_for", resolve_for)
    monkeypatch.setattr(runner, "_metric_of", lambda monitor: state["metric"])
    monkeypatch.setattr(runner, "_last_alert_value", lambda mid: None)
    monkeypatch.setattr(runner, "_guard_caveats", lambda m, db: None)
    return SimpleNamespace(calls=calls, state=state)


def test_a_monthly_floor_reads_the_month_and_warns_where_all_history_never_could(warehouse, asked):
    run = runner.check_monitor(_floor(), warehouse, suppress=False)
    assert run.reading == pytest.approx(848.6)               # August's kept orders, not the 13,494.0 of all history
    assert run.alert is not None and run.alert.severity == "warning"
    assert "848.6 for August 2018" in run.alert.message
    assert runner.reading_words(_floor(), run) == (
        "read 848.6 for August 2018 (warning below 900; critical below 800)")
    # the Briefing's own range, for the metric's dataset — the data's edge is read per dataset
    assert asked.calls == [{"conn_id": "workspace", "preset": "last_month", "schema": "olist"}]
    sql, dialect = warehouse.ran[-1]
    assert dialect == "duckdb" and "2018-08-01" in sql and "2018-09-01" in sql


def test_the_metric_grain_sets_the_period_and_an_unset_one_is_the_editor_month(warehouse, asked):
    asked.state["metric"] = _gmv(time_grain="week")
    runner.check_monitor(_floor(), warehouse, suppress=False)
    assert asked.calls[-1]["preset"] == "last_week"
    assert mt.reported_grain(_gmv()) == "month" == mt.DEFAULT_GRAIN
    # the editor shows an unset grain as this default — one word for it on both sides
    panel = Path(__file__).resolve().parents[2] / "web" / "components" / "MetricsPanel.tsx"
    assert f"{mt.DEFAULT_GRAIN} (the default)" in panel.read_text()


def test_a_metric_with_no_date_is_read_over_all_history_and_says_so(warehouse, asked):
    asked.state["metric"] = _gmv(time_column=None, time_kind=None)
    run = runner.check_monitor(_floor(), warehouse, suppress=False)
    assert run.alert is None and run.reading == pytest.approx(ALL_HISTORY)
    assert runner.reading_words(_floor(), run) == (
        "read 13,494 over all history — Gross Merchandise Value (item price) has no date set, so no period of it "
        "can be read (warning below 900; critical below 800)")
    assert asked.calls == []                                  # no period was asked for


def test_a_period_with_no_rows_is_no_figure_and_says_it_read_none(warehouse, asked):
    asked.state["today"] = date(2018, 12, 10)                 # the newest settled month is November: no orders
    run = runner.check_monitor(_floor(), warehouse, suppress=False)
    assert run.alert is None and run.reading is None
    assert runner.reading_words(_floor(), run) == (
        "read no value for November 2018: it holds no rows")


def test_a_period_that_cannot_be_read_is_a_failed_run_never_an_all_history_read(warehouse, asked, monkeypatch):
    monkeypatch.setattr(R, "resolve_for", lambda *a, **k: (None, "the connection could not be read"))
    run = runner.check_monitor(_floor(), warehouse, suppress=False)
    assert run.failed and "no settled month of Gross Merchandise Value (item price)" in run.failed
    assert run.reading is None and warehouse.ran == []        # nothing was read in its place

    asked.state["metric"] = _gmv(sql="SELECT 1 AS one")       # a statement the compiler cannot measure by its date
    monkeypatch.setattr(R, "resolve_for", lambda *a, **k: R.resolve_range("last_month", today=date(2018, 9, 15)))
    run = runner.check_monitor(_floor(), warehouse, suppress=False)
    assert run.failed.startswith("Gross Merchandise Value (item price) could not be measured for a month")
    assert warehouse.ran == []


def test_a_monitor_with_its_own_sql_is_read_as_written(warehouse, asked):
    own = Monitor(conn_id="workspace", name="All-time GMV", custom_sql="SELECT SUM(price) FROM olist.olist_order_items_dataset",
                  alert_on="threshold_cross", threshold_direction="below", warning_threshold=900.0)
    run = runner.check_monitor(own, warehouse, suppress=False)
    assert run.reading == pytest.approx(ALL_HISTORY + 500.0) and run.covered == ""
    assert runner.reading_words(own, run) == "read 13,994 (warning below 900)"
    assert asked.calls == []
