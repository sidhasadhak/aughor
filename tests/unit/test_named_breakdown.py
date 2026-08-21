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


# ── Fix 5: the breakdown must not depend on the planner succeeding ──────────────
# Live defect. The named breakdown was computed AFTER the scan's results were assembled,
# so `if not _run.ok: return ...error_phase` short-circuited past it: a question whose
# answer we can compute outright in one GROUP BY shipped a "Skipped" card because a model
# call further up failed. The breakdown is deterministic SQL — it is now computed BEFORE
# the run and survives its failure.

def test_a_failed_scan_still_ships_the_named_breakdown(monkeypatch):
    monkeypatch.setattr(I, "_execute_safe", lambda *a, **k: SimpleNamespace(
        sql="SELECT route_id, COUNT(*) ...", columns=["route_id", "flight_count"],
        rows=[["ZRH-LHR", 28]], row_count=1, error=None))
    # The planner dies — the scan can produce nothing of its own.
    monkeypatch.setattr(I, "run_analysis_phase", lambda *a, **k: I._PhaseRun(
        ok=False, error_phase=I._phase_result(
            "cross_section", "Cross-Sectional Scan", "🧭", "error",
            "Cross-sectional planning failed.",
            [I._skipped_finding("cross_section", "planner exploded")])))

    state = {
        "question": "give me route wise number of flights",
        "schema_context": "", "connection_id": "c", "investigation_phases": [],
        "_ada_intake": {**_INTAKE, "descriptive_only": True,
                        "dimensions": ["main.flights.market"]},
    }
    phases = I.ada_cross_section(state, None)["investigation_phases"]

    assert len(phases) == 1
    titles = [f["title"] for f in phases[0]["findings"]]
    assert "flight count by route_id" in titles, (
        "a planner failure buried a breakdown the code had already computed")
    assert not any("skip" in t.lower() for t in titles)


def test_a_clean_scan_leads_with_the_named_breakdown(monkeypatch):
    """And on the happy path it still LEADS, ahead of the scan's own dimensions."""
    monkeypatch.setattr(I, "_execute_safe", lambda *a, **k: SimpleNamespace(
        sql="SELECT route_id, COUNT(*) ...", columns=["route_id", "flight_count"],
        rows=[["ZRH-LHR", 28]], row_count=1, error=None))
    _own = SimpleNamespace(columns=["market", "flight_count"], rows=[["EU", 60]],
                           row_count=1, error=None, sql="SELECT market, COUNT(*) ...")
    monkeypatch.setattr(I, "run_analysis_phase", lambda *a, **k: I._PhaseRun(
        ok=True, results=[(SimpleNamespace(title="flight count by market",
                                           chart_type="magnitude", sql=_own.sql), _own)],
        results_text="", interpretation=None))

    state = {
        "question": "give me route wise number of flights",
        "schema_context": "", "connection_id": "c", "investigation_phases": [],
        "_ada_intake": {**_INTAKE, "descriptive_only": True,
                        "dimensions": ["main.flights.market"]},
    }
    phases = I.ada_cross_section(state, None)["investigation_phases"]
    titles = [f["title"] for f in phases[0]["findings"]]
    assert titles[0] == "flight count by route_id", titles


# ── Fix 4: a date column that does not live on the metric table ────────────────
# The rendered schema warned "⚠ No date/timestamp columns in flights" while the intake
# still carried a date_column from a joined table. The WHERE named an unreachable column,
# the query errored, and `if error: continue` dropped the breakdown in silence.

def test_an_unreachable_date_column_is_not_filtered_on(executed):
    spec = {**_INTAKE, "date_column": "main.bookings.booked_at"}
    out = I._named_breakdown_findings({"schema_context": ""}, None, spec)
    assert out, "the breakdown must still run when the date lives on another table"
    assert "booked_at" not in executed["sql"]


def test_a_windowed_query_that_returns_nothing_retries_unwindowed(monkeypatch):
    """Belt and braces: if the window itself empties the result, fall back to the
    unwindowed cut rather than shipping no breakdown at all."""
    calls = []

    def _fake(conn, phase_id, sql, schema=None):
        calls.append(sql)
        if "WHERE" in sql:
            return SimpleNamespace(sql=sql, columns=[], rows=[], row_count=0, error=None)
        return SimpleNamespace(sql=sql, columns=["route_id", "flight_count"],
                               rows=[["ZRH-LHR", 28]], row_count=1, error=None)

    monkeypatch.setattr(I, "_execute_safe", _fake)
    out = I._named_breakdown_findings({"schema_context": ""}, None, _INTAKE)
    assert len(out) == 1 and out[0]["rows"] == [["ZRH-LHR", 28]]
    assert len(calls) == 2 and "WHERE" in calls[0] and "WHERE" not in calls[1]
