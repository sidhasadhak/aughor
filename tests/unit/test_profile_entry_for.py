"""The profile that describes a statement's OWN tables, on a connection of several schemas.

Measured 2026-10-07 on the live workspace connection: the Uber rides (`uber_ncr`) were profiled at
21:50, the traffic data at 23:00, and from then on the metric editor proposed no date for an Uber
metric — "no date or timestamp column was profiled on uber_ncr.ncr_ride_bookings" — because it read
only the connection's NEWEST profile entry, which described the traffic data alone. The entries
below are shaped as the live ones are: one run writes bare table names, another schema-qualified.
"""
from __future__ import annotations

import pytest

from aughor.tools import profile_cache as pc


def _entry(table: str, columns: dict[str, str], primary: str = "") -> dict:
    return {"tables": {table: {"primary_timestamp": primary}},
            "columns": {f"{table}.{c}": {"table": table, "column": c, "dtype": d} for c, d in columns.items()}}


UBER_COLS = {"Date": "date", "Time": "time", "Booking ID": "varchar", "Booking Value": "varchar"}
TRAFFIC_COLS = {"CALENDAR_DATE": "date", "VISITS": "bigint"}


@pytest.fixture
def workspace():
    """Uber profiled first (bare, then qualified), traffic last — the live order, main dates as measured."""
    pc._store.invalidate_prefix("wsx:")
    pc._store.put("wsx:uber-bare", _entry("ncr_ride_bookings", UBER_COLS, "Date"))
    pc._store.put("wsx:uber-qualified", _entry("uber_ncr.ncr_ride_bookings", UBER_COLS, "Date"))
    pc._store.put("wsx:traffic-bare", _entry("all_dimesnsions_2", TRAFFIC_COLS, "CALENDAR_DATE"))
    pc._store.put("wsx:traffic-qualified", _entry("traffic.all_dimesnsions_2", TRAFFIC_COLS, "CALENDAR_DATE"))
    yield "wsx"
    pc._store.invalidate_prefix("wsx:")


def test_the_newest_entry_alone_describes_only_the_schema_profiled_last(workspace):
    """The defect, pinned: what the editor read."""
    assert list(pc.latest_profile_entry(workspace)["tables"]) == ["traffic.all_dimesnsions_2"]


def test_the_entry_for_a_statements_tables_is_the_newest_that_covers_them(workspace):
    entry = pc.profile_entry_for(workspace, ["uber_ncr.ncr_ride_bookings"])
    assert list(entry["tables"]) == ["uber_ncr.ncr_ride_bookings"]
    assert list(pc.profile_entry_for(workspace, ["ncr_ride_bookings"])["tables"]) == ["uber_ncr.ncr_ride_bookings"]


def test_with_no_entry_covering_them_all_the_newest_covering_any_is_read_then_the_newest(workspace):
    both = pc.profile_entry_for(workspace, ["uber_ncr.ncr_ride_bookings", "traffic.all_dimesnsions_2"])
    assert list(both["tables"]) == ["traffic.all_dimesnsions_2"]
    assert pc.profile_entry_for(workspace, ["nowhere.at_all"]) == pc.latest_profile_entry(workspace)
    assert pc.profile_entry_for(workspace, []) == pc.latest_profile_entry(workspace)


def test_the_editor_proposes_the_uber_dates_again(workspace):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from aughor.routers.metrics import router
    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).post("/metrics/proposals", json={
        "connection": workspace,
        "sql": 'SELECT COUNT(*) FILTER (WHERE "Booking Status" = \'Completed\') * 1.0 / COUNT(*) '
               "FROM uber_ncr.ncr_ride_bookings"}).json()
    assert [c["grain"] for c in body["candidates"]] == ["uber_ncr.ncr_ride_bookings.date",
                                                       "uber_ncr.ncr_ride_bookings.time"]
    assert body["note"] == ""


def test_the_date_rule_sets_an_uber_metrics_date_though_traffic_was_profiled_after_it(workspace, monkeypatch, tmp_path):
    """`ensure_dates` read ONE profile for the whole connection — the newest — so an approved metric on
    any other schema of it could not have its date set by rule. It now reads each metric's own tables."""
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    from aughor.semantic.metric_time import ensure_dates
    from aughor.semantic.metrics import MetricDefinition, get_metric, save_metric
    save_metric(MetricDefinition(name="rides", connection=workspace, label="Rides", sql="COUNT(*)",
                                 tables=["uber_ncr.ncr_ride_bookings"], status="approved", approved_by="test"))
    said = ensure_dates(workspace)
    m = get_metric("rides", connection_id=workspace)
    assert said["rides"] == "set automatically" and m.time_column == "date", (said, m.time_column)
    assert m.time_source.startswith("set automatically")
