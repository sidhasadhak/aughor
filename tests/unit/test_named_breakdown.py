"""The breakdown the question named is computed, not requested.

Three fixes went into making the cross-sectional scan honour "give me route wise number
of flights", and each time the layer below declined:

  1. the run's FRAMING was patched          → the phase's own prompts still ranked others
  2. the dimension reached the INTAKE       → the priority sorter sank it, the cap cut it
  3. it outranked the SORTER                → the phase's SQL planner refused it outright,
                                              reporting "the dataset does not contain a
                                              unique route_id to route_name mapping"

That refusal is CORRECT for the instrument — the cross-sectional scan looks for where
value is weak, and a high-cardinality id column is a poor weakness dimension. It is the wrong
instrument for a question that asked to see a breakdown. So the breakdown stops being a
request to a model: one GROUP BY per named dimension, built in code and run through the
same guard battery as every other phase query.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent import investigate as I

_INTAKE = {
    "named_dimensions": ["main.flights.route_id"],
    "metric_sql": "COUNT(*)", "metric_table": "main.flights",
    "metric_label": "flight count", "date_column": "main.flights.flight_date",
    "observation_start": "2024-06-01", "observation_end": "2024-06-07",
}


@pytest.fixture
def executed(monkeypatch):
    """Capture the SQL the breakdown builds, and hand back a real-looking result."""
    seen = {}

    def _fake(conn, phase_id, sql, schema=None):
        seen["sql"] = sql
        seen["phase_id"] = phase_id
        return SimpleNamespace(sql=sql, columns=["route_id", "flight_count"],
                               rows=[["ZRH-LHR", 28], ["GVA-LHR", 42]], row_count=2,
                               error=None)

    monkeypatch.setattr(I, "_execute_safe", _fake)
    return seen


def test_the_named_cut_is_grouped_and_ranked(executed):
    out = I._named_breakdown_findings({"schema_context": ""}, None, _INTAKE)

    assert len(out) == 1
    assert out[0]["title"] == "flight count by route_id"
    assert out[0]["rows"] == [["ZRH-LHR", 28], ["GVA-LHR", 42]]
    sql = executed["sql"]
    assert "GROUP BY 1" in sql and "ORDER BY 2 DESC" in sql
    assert "route_id" in sql and "COUNT(*)" in sql


def test_the_observation_window_is_applied(executed):
    I._named_breakdown_findings({"schema_context": ""}, None, _INTAKE)
    assert "2024-06-01" in executed["sql"] and "2024-06-07" in executed["sql"]


def test_no_window_when_the_spec_has_no_date(executed):
    spec = {**_INTAKE, "date_column": "NONE"}
    I._named_breakdown_findings({"schema_context": ""}, None, spec)
    assert "WHERE" not in executed["sql"]


def test_it_runs_through_the_guard_battery(executed):
    """Not a raw cursor: the same `_execute_safe` every other phase query uses, so the
    repair loop, the caveats and the receipts all apply."""
    I._named_breakdown_findings({"schema_context": ""}, None, _INTAKE)
    assert executed["phase_id"].startswith("named_breakdown")


@pytest.mark.parametrize("spec, why", [
    ({**_INTAKE, "named_dimensions": []}, "the question named no cut"),
    ({**_INTAKE, "metric_sql": ""}, "no metric to aggregate"),
    ({**_INTAKE, "metric_table": ""}, "no table to read"),
])
def test_it_builds_nothing_without_the_parts(spec, why, executed):
    assert I._named_breakdown_findings({"schema_context": ""}, None, spec) == [], why


def test_an_erroring_query_yields_no_finding(monkeypatch):
    """A broken breakdown is not an exhibit — the scan's own findings still serve."""
    monkeypatch.setattr(I, "_execute_safe", lambda *a, **k: SimpleNamespace(
        sql="x", columns=[], rows=[], row_count=0, error="boom"))
    assert I._named_breakdown_findings({"schema_context": ""}, None, _INTAKE) == []


def test_the_alias_comes_from_the_helper_that_already_existed():
    """Caught by this test: the breakdown shipped with its own copy of `_safe_alias`,
    which the module's existing one silently overrode. One definition."""
    assert I._safe_alias("flight count") == "flight_count"
    assert I._safe_alias("Revenue (€)") == "revenue"
    assert I._safe_alias("") == "metric"
