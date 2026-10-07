"""A ratio over an empty range is not a figure (2026-10-07).

DuckDB answers `COUNT(...) * 1.0 / COUNT(...)` over no rows with NaN, not NULL. Uber's rides end
in 2024, so every recent range is empty, and Ride Completion Rate's NaN reached the Cockpit as a
measured figure: the response could not be written as JSON, the API answered 500, and the page
said only "Failed to fetch".
"""
from __future__ import annotations

import json
from datetime import date

from aughor.briefing import ranges
from aughor.semantic import metric_time as mt


def test_a_nan_from_the_warehouse_is_no_figure_and_the_range_still_answers(monkeypatch):
    class _Rate:
        name, label, status, connection = "ride_completion_rate", "Ride Completion Rate", "approved", "c"
        time_kind, tables, unit = "flow", [], "ratio 0-1"
        time_source, time_confirmed_by = "set by a person", "test"

    monkeypatch.setattr("aughor.semantic.metrics.list_metrics", lambda **k: [_Rate()])
    monkeypatch.setattr(mt, "ensure_dates", lambda *a, **k: {})
    monkeypatch.setattr(mt, "declared", lambda m: True)
    monkeypatch.setattr(mt, "measure_sql", lambda *a, **k: ("SELECT …", ""))
    # What DuckDB returns for the statement over a month with no rides: one row per window, NaN.
    rows = [("current", float("nan"), None, None, 0), ("previous", float("nan"), None, None, 0)]

    spec = ranges.RangeSpec(preset="custom", start=date(2026, 9, 1), end=date(2026, 10, 1),
                            previous_start=date(2026, 8, 1), previous_end=date(2026, 9, 1),
                            last_year_start=None, last_year_end=None, as_of=date(2026, 10, 7),
                            lag_days=1, lag_source="default", still_moving=[], period="month")
    out = ranges.measure_range("c", spec, run_sql=lambda s: (["window", "value", "first", "last", "n"], rows, ""),
                               dialect="duckdb")

    assert out["measured"] == []
    assert out["unmeasured"] == [{"name": "Ride Completion Rate", "reason": "its data has no rows in this range"}]
    json.dumps(out, allow_nan=False)  # what the API's response does — it raised on the NaN
