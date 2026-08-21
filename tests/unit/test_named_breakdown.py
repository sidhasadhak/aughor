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
# Two tests stood here asserting that the weakness scan carried the named breakdown
# through a planner failure and led with it on the happy path. Both are gone, and
# deliberately: with a breakdown ROUTE (Fix 6, below) a descriptive question never
# enters the weakness scan at all, so those assertions described a path that no longer
# exists. What they were protecting — that a model call failing upstream must not cost
# a breakdown we can compute outright — is now
# TestTheBreakdownPhase::test_a_dead_narrator_costs_the_prose_not_the_exhibit.


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


# ── Fix 6: the breakdown is a ROUTE, not a patch on the weakness scan ───────────
# Five successive fixes tried to make the weakness scan behave descriptively, and each
# was declined by the layer beneath it — the framing, then the intake, then the priority
# sorter, then the SQL planner. That is the signature of a missing route. A listing is
# neither "why did X change" nor "where is X weakest", so it now has its own instrument.

def _descriptive_state(**over):
    return {
        "question": "give me route wise number of flights",
        "schema_context": "", "connection_id": "c", "investigation_phases": [],
        "_ada_intake": {**_INTAKE, "descriptive_only": True,
                        "dimensions": ["main.flights.market"], **over},
    }


class TestTheRoute:
    def test_a_descriptive_question_gets_the_breakdown(self):
        assert I.route_after_intake(_descriptive_state()) == "deep_breakdown"

    def test_descriptive_outranks_cross_sectional(self):
        """A listing is usually ALSO cross_sectional (no time axis). The descriptive
        verdict has to win, or the question lands back in the weakness scan."""
        st = _descriptive_state()
        st["_ada_intake"]["cross_sectional"] = True
        assert I.route_after_intake(st) == "deep_breakdown"

    def test_a_diagnostic_question_still_scans(self):
        st = _descriptive_state()
        st["_ada_intake"]["descriptive_only"] = False
        st["_ada_intake"]["cross_sectional"] = True
        assert I.route_after_intake(st) == "ada_cross_section"

    def test_a_temporal_question_still_takes_the_baseline(self):
        st = _descriptive_state()
        st["_ada_intake"]["descriptive_only"] = False
        st["_ada_intake"]["cross_sectional"] = False
        assert I.route_after_intake(st) == "ada_baseline"

    def test_the_graph_can_reach_the_new_node(self):
        """A route string with no edge in the map is a runtime error, not a test failure —
        so assert the wiring, not just the router."""
        import inspect

        from aughor.agent import graph as G
        src = inspect.getsource(G._compile)
        assert '"deep_breakdown": "deep_breakdown"' in src, "route target missing from an edge map"
        assert src.count('"deep_breakdown": "deep_breakdown"') == 2, (
            "both the intake and the clarify gate must be able to reach it")
        assert 'graph.add_edge("deep_breakdown", "ada_synthesize")' in src


class TestTheBreakdownPhase:
    def _run(self, monkeypatch, *, rows=None, narrate=True):
        monkeypatch.setattr(I, "_execute_safe", lambda *a, **k: SimpleNamespace(
            sql="SELECT route_id, COUNT(*) ...", columns=["route_id", "flight_count"],
            rows=rows if rows is not None else [["ZRH-LHR", 28], ["GVA-DEL", 12]],
            row_count=2, error=None))
        if narrate:
            monkeypatch.setattr(I, "_provider", lambda *a, **k: SimpleNamespace(
                complete=lambda **kw: SimpleNamespace(
                    phase_summary="Flights by route across the window.",
                    findings=[SimpleNamespace(
                        title="Flights by route", interpretation="ZRH-LHR carries 28 of the 40.",
                        key_numbers=[], chart_type="auto", stat_note=None,
                        is_significant=False, claim=None)])))
        else:
            monkeypatch.setattr(I, "_provider", lambda *a, **k: SimpleNamespace(
                complete=lambda **kw: (_ for _ in ()).throw(RuntimeError("narrator down"))))
        return I.deep_breakdown(_descriptive_state(), None)["investigation_phases"]

    def test_it_ships_the_named_cut(self, monkeypatch):
        phases = self._run(monkeypatch)
        assert len(phases) == 1 and phases[0]["phase_id"] == "breakdown"
        assert phases[0]["status"] == "complete"
        titles = [f["title"] for f in phases[0]["findings"]]
        assert any("route" in t.lower() for t in titles), titles

    def test_a_dead_narrator_costs_the_prose_not_the_exhibit(self, monkeypatch):
        """The rows are already on the page; a failed model call must not take them."""
        phases = self._run(monkeypatch, narrate=False)
        assert phases[0]["status"] == "complete"
        f = phases[0]["findings"][0]
        assert f["rows"] == [["ZRH-LHR", 28], ["GVA-DEL", 12]]

    def test_nothing_groupable_says_so(self, monkeypatch):
        monkeypatch.setattr(I, "_execute_safe", lambda *a, **k: SimpleNamespace(
            sql="x", columns=[], rows=[], row_count=0, error="no such column"))
        phases = I.deep_breakdown(_descriptive_state(), None)["investigation_phases"]
        assert phases[0]["status"] == "skipped"
        assert "breakdown" in (phases[0]["skipped_reason"] or "").lower()

    def test_it_falls_back_to_the_intake_dimensions(self, monkeypatch):
        """When the question named no cut, the phase still has to produce one."""
        seen = {}
        monkeypatch.setattr(I, "_execute_safe", lambda c, pid, sql, **k: seen.setdefault("sql", sql) and None
                            or SimpleNamespace(sql=sql, columns=["market", "n"],
                                               rows=[["EU", 60]], row_count=1, error=None))
        monkeypatch.setattr(I, "_provider", lambda *a, **k: SimpleNamespace(
            complete=lambda **kw: SimpleNamespace(phase_summary="", findings=[])))
        st = _descriptive_state()
        st["_ada_intake"]["named_dimensions"] = []
        phases = I.deep_breakdown(st, None)["investigation_phases"]
        assert phases[0]["status"] == "complete"
        assert "market" in seen["sql"], seen["sql"]


def test_the_weakness_scan_no_longer_owns_a_breakdown():
    """One owner. The hook that used to bolt a named breakdown onto the weakness scan is
    gone — with the route in place it was a second answer to the same question."""
    import inspect
    src = inspect.getsource(I.ada_cross_section)
    assert "_named_breakdown_findings" not in src
    assert "descriptive_only" not in src
