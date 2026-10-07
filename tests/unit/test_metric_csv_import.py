"""A metric file an organisation writes, imported into the Semantic Layer (the user, 2026-10-07: *"a
rich structure in which an organisation can build a CSV file … the formula, the name, the Date grain,
the caveats — the most critical fields required for a metric to be defined in our platform"*).

The columns are `mappers.METRIC_COLUMNS` — the template, the Import tab's reference and the mapper
all read that one list. A row lands as a PROPOSED definition in its dataset, its declared dates
confirmed by whoever imported it; a row the platform cannot take says why, by row.
"""
from __future__ import annotations

import csv
import io

import pytest

from aughor.intake import engine, mappers


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def test_the_template_is_the_format_every_column_of_it_is_read():
    headers, rows = mappers.read_tabular("t.csv", mappers.metric_template_csv().encode())
    sections, ignored, refused = mappers.map_dictionary_rows(headers, rows)
    assert ignored == [] and refused == []
    [m] = sections["metrics"]
    assert (m["name"], m["schema_name"], m["time_column"], m["time_kind"], m["time_grain"]) == \
        ("net_revenue", "sales", "sales.orders.ordered_at", "flow", "month")
    assert m["target_value"] == 1200000.0 and m["dimensions"] == ["region", "channel"]


def test_a_row_the_platform_cannot_take_says_why_by_row():
    data = _csv([
        {"name": "Net Revenue", "sql": "SELECT SUM(amount) FROM s.o", "date_grain": "Monthly",
         "filters": "status IN ('a', 'b'); region <> 'test'"},
        {"name": "aov", "sql": "SELECT AVG(amount) FROM s.o", "date_kind": "monthly"},
        {"name": "open_tickets", "sql": "SELECT COUNT(*) FROM s.t", "date_kind": "stock"},
        {"name": "target_bad", "sql": "SELECT 1", "target": "a lot"},
    ])
    sections, _ignored, refused = mappers.map_dictionary_rows(*mappers.read_tabular("m.csv", data))
    [ok] = sections["metrics"]
    assert ok["name"] == "net_revenue" and ok["time_grain"] == "month"
    assert ok["filters"] == ["status IN ('a', 'b')", "region <> 'test'"], "a filter's own commas split it"
    assert refused == [
        "row 3 (aov): date_kind 'monthly' is not one of flow, stock, cohort",
        "row 4 (open_tickets): a stock needs an until_column — the date a row stops counting",
        "row 5 (target_bad): target_value 'a lot' is not a number",
    ]


@pytest.fixture
def lane(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    monkeypatch.setattr("aughor.semantic.metric_checks.runs_on", lambda *a, **k: ("ok", ""))
    monkeypatch.setattr("aughor.semantic.metric_time.with_dates", lambda c, m: m)
    return "ws"


def test_an_imported_row_lands_proposed_in_its_dataset_with_its_dates_confirmed_by_the_importer(lane):
    from aughor.semantic.metrics import definition_at

    data = _csv([{"name": "rides", "label": "Completed rides", "dataset": "uber_ncr",
                  "sql": "SELECT COUNT(*) AS rides FROM uber_ncr.ncr_ride_bookings WHERE \"Booking Status\" = 'Completed'",
                  "date_column": "uber_ncr.ncr_ride_bookings.Date", "date_grain": "day", "unit": "count",
                  "description": "Rides that reached the drop-off.", "anti_patterns": "Never count cancelled rides"}])
    sections, _i, _r = mappers.map_dictionary_rows(*mappers.read_tabular("m.csv", data))
    cands, refused = engine.plan(lane, {"version": 1, "sections": sections})
    assert refused == [] and [c["verdict"] for c in cands] == ["new", "new"]   # the metric, and its definition
    metric = next(c for c in cands if c["kind"] == "metric")
    engine.apply_candidate(lane, "metric", metric["payload"], actor="ana@example.com", source="m.csv")

    m = definition_at("rides", lane, "uber_ncr")
    assert (m.status, m.proposed_by, m.schema_name) == ("proposed", "ana@example.com", "uber_ncr")
    assert (m.time_column, m.time_kind, m.time_grain) == ("uber_ncr.ncr_ride_bookings.Date", "flow", "day")
    assert m.time_confirmed_by == "ana@example.com"
    assert m.caveats == "Rides that reached the drop-off." and m.wrong_usage_examples == ["Never count cancelled rides"]


def test_a_formula_its_warehouse_cannot_run_is_said_at_plan_and_refused_at_accept(monkeypatch, tmp_path):
    monkeypatch.setenv("AUGHOR_METRICS_PATH", str(tmp_path / "metrics.instance.json"))
    monkeypatch.setattr("aughor.semantic.metric_checks.runs_on",
                        lambda *a, **k: ("refused", "ws cannot run that SQL: no column amount"))
    cands, _ = engine.plan("ws", {"version": 1, "sections": {"metrics": [
        {"name": "revenue", "sql": "SELECT SUM(amount) FROM s.o"}]}})
    assert "does not run here" in cands[0]["detail"]
    with pytest.raises(ValueError, match="no column amount"):
        engine.apply_candidate("ws", "metric", cands[0]["payload"], actor="ana", source="m.csv")
