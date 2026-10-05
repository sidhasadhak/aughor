"""Phase 3 of the 2027 study, P3-2 and P3-3 — the scenario ladder's first three methods behind one
interface (`aughor/record/scenario.py`), predictions scored by code, coverage counted by method, and
law 5 narrowed so a forecast departs only on a scored method.

What these hold: identity is exact arithmetic over named inputs and refuses anything else, saying
what it held fixed; a declared assumption is a claim at tier `declared` in a person's name and is
refused without one; history projects from the metric's own prior windows with its band and its
backtest on this metric, and projects nothing — saying why — below three windows; an unknown method
is refused by name; a prediction carries its method and band and is scored by the settle tick when
its range is Final, from its own spec; calibration counts coverage by method, metric and author;
and the departure gate holds a forecast that cites no scored prediction and departs one that does.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from aughor.record import claims as C
from aughor.record import scenario as S

SPEC = {"metric_label": "total sales", "metric_sql": "SUM(sale_price)", "metric_table": "thelook.order_items",
        "date_column": "thelook.order_items.created_at", "window_days": 7, "window_basis": "observation"}


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _run_sql_by_window(values_by_start: dict[str, float], default=None):
    """A fake warehouse: the window's start date (in the SQL) picks the value."""
    calls: list[str] = []

    def run_sql(sql):
        calls.append(sql)
        for start, v in values_by_start.items():
            if f">= DATE '{start}'" in sql:            # the window's START; its stop is another window's start
                return (["value"], [[v]], None)
        return (["value"], [[default]] if default is not None else [], None)
    run_sql.calls = calls
    return run_sql


# ── the three methods ──────────────────────────────────────────────────────────────────────

def test_identity_is_exact_arithmetic_over_named_inputs_and_says_what_is_held_fixed():
    p = S.identity("price * units", {"price": 12.5, "units": 400}, unit="EUR", varied=["price"])
    assert p.method == "identity" and p.value == 5000.0 and p.low == p.high == 5000.0 and p.coverage == 1.0
    assert p.must_say[0] == "held fixed: units"
    with pytest.raises(S.FormulaRefused, match="names 'tax'"):
        S.identity("price * units - tax", {"price": 1, "units": 1})
    with pytest.raises(S.FormulaRefused, match="not arithmetic"):
        S.identity("__import__('os').system('x')", {})
    with pytest.raises(S.FormulaRefused, match="division by zero"):
        S.identity("a / b", {"a": 1, "b": 0})


def test_a_declared_assumption_is_a_claim_in_a_persons_name_and_is_refused_without_one():
    conn = _conn()
    p = S.declared(variable="elasticity", value=-1.8, by="user:ana", text="demand falls 1.8% per 1% price rise",
                   connection_id=conn)
    assert p.method == "declared" and p.value == -1.8 and p.claim
    claim = C.get(p.claim)
    assert claim.tier == "declared" and claim.author == "user:ana" and claim.author_kind == "person"
    assert claim.statement.text.startswith("assumption: demand falls") and claim.extra["method"] == "declared"
    assert p.must_say[0] == "user:ana's assumption, not a measurement"
    with pytest.raises(C.ClaimRefused, match="name of the person"):
        S.declared(variable="x", value=1, by="")


def test_history_projects_from_the_metrics_own_prior_windows_with_its_band_and_backtest():
    end = date(2026, 10, 4)                                    # the review window ends here; windows are 7 days
    starts = [(end - timedelta(days=7 * k + 6)).isoformat() for k in range(6, 0, -1)]
    values = [1000, 1040, 980, 1020, 1010, 990]
    run_sql = _run_sql_by_window(dict(zip(starts, values)))
    p = S.history(SPEC, run_sql, end_day=end)
    assert p.method == "history" and p.value == pytest.approx(1006.667, abs=0.01)
    assert p.low < p.value < p.high and p.coverage == 0.8
    assert p.backtest["n"] == 6 and p.backtest["cases"] == 4 and p.backtest["mae"] is not None
    assert 0 <= p.backtest["coverage_observed"] <= 1 and p.backtest["coverage_stated"] == 0.8
    assert "6 prior windows of 7 days" in p.must_say[0] and "backtest on this metric" in p.must_say[1]
    assert len(run_sql.calls) == 6 and p.inputs["windows"][0].startswith(starts[0])


def test_history_projects_nothing_below_three_windows_and_says_why():
    end = date(2026, 10, 4)
    only_two = {(end - timedelta(days=7 * k + 6)).isoformat(): 1000 for k in (1, 2)}
    p = S.history(SPEC, _run_sql_by_window(only_two), end_day=end)
    assert p.value is None and "only 2 prior windows held a reading" in p.note
    unmeasurable = S.history({"metric_label": "x"}, _run_sql_by_window({}), end_day=end)
    assert unmeasurable.value is None and "no measurable definition" in unmeasurable.note
    with pytest.raises(C.ClaimRefused, match="projected nothing"):
        S.predict(metric="total sales", projection=p, settles_on="2026-11-01", author="system")


def test_an_unknown_method_is_refused_by_name():
    with pytest.raises(ValueError, match="no method named 'learned'"):
        S.project("learned", spec=SPEC, run_sql=lambda s: ([], [], None))


# ── predictions scored by code ─────────────────────────────────────────────────────────────

def test_a_prediction_carries_its_method_and_is_scored_when_its_range_is_final():
    conn = _conn()
    end = date(2026, 9, 30)
    starts = {(end - timedelta(days=7 * k + 6)).isoformat(): v for k, v in zip(range(6, 0, -1), [100, 110, 90, 105, 95, 100])}
    proj = S.history(SPEC, _run_sql_by_window(starts), end_day=end)
    pid = S.predict(metric="total sales", projection=proj, settles_on="2026-09-30", author="system",
                    connection_id=conn, direction="up", spec=SPEC, for_ref="decision-x")
    pred = C.get(pid)
    assert pred.kind == "prediction" and pred.tier == "mined" and pred.state == "open"
    assert pred.extra["method"] == "history" and pred.extra["backtest"]["n"] == 6 and pred.extra["spec"] == SPEC
    assert pred.statement.text.startswith("expected: total sales") and "(history)" in pred.statement.text
    assert any(c.id == pid for c in S.due_predictions(datetime(2026, 10, 5, tzinfo=timezone.utc)))
    # the tick measures the settle window and scores: the review window's start is 2026-09-24
    actual_by_window = {"2026-09-24": 180.0}
    scored = S.score_due_predictions(run_sql_for=lambda c, **kw: _run_sql_by_window(actual_by_window),
                                     now=datetime(2026, 10, 5, tzinfo=timezone.utc))
    assert scored and C.get(scored[0]).key == pred.key
    now = C.latest(pred.key)
    assert now.state == "scored" and now.extra["scored_against"] == "above" and now.extra["actual"] == 180.0
    assert not any(c.key == pred.key for c in S.due_predictions(datetime(2026, 10, 5, tzinfo=timezone.utc)))
    # the class is counted
    rows = [g for g in S.calibration(conn_id=conn) if g["metric"] == "total sales"]
    assert rows and rows[0]["n"] == 1 and rows[0]["above"] == 1 and rows[0]["coverage_observed"] == 0.0
    assert rows[0]["method"] == "history" and rows[0]["coverage_stated"] == 0.8 and rows[0]["signed_error"] == 1.0


def test_against_band_reads_relative_bands_against_before_and_says_cannot_tell_without_one():
    assert S.against_band(103, low=2, high=4, unit="%", before=100) == "inside"
    assert S.against_band(110, low=2, high=4, unit="%", before=100) == "above"
    assert S.against_band(103, low=2, high=4, unit="%", before=None) == "cannot_tell"
    assert S.against_band(90, low=95, high=105) == "below" and S.against_band(None, low=1, high=2) == "cannot_tell"
    assert S.against_band(5, low=None, high=None) == "no expectation"


def test_a_scenario_is_booked_for_a_decision_through_the_door():
    from aughor.record import decisions as D
    from aughor.routers import record as R
    conn = _conn()
    did = D.book_decision(D.Decision(question="raise the price 7%?", chosen="yes", decided_by="user:ana",
                                     connection_id=conn, source=D.Source(kind="declared", ref=uuid.uuid4().hex[:8])))
    out = R.book_record_scenario(did, R.ScenarioRequest(method="identity", metric="revenue", formula="price * units",
                                                        inputs={"price": 10.7, "units": 1000}, varied=["price"],
                                                        unit="EUR", direction="up"), principal=None)
    assert out["projection"]["value"] == 10700.0 and out["projection"]["must_say"][0] == "held fixed: units"
    assert out["prediction"]["extra"]["method"] == "identity" and out["prediction"]["extra"]["for"] == did
    assert out["scenario"]["for_id"] == did and out["scenario"]["tier"] == "identity"
    assert S.scenarios_for(did)[0].predictions == [out["prediction"]["id"]]
    declared = R.book_record_scenario(did, R.ScenarioRequest(
        method="declared", metric="units", direction="down",
        assumption=R.AssumptionIn(variable="elasticity", value=-1.8, by="user:ana", low=-2.5, high=-1.0, unit="%")),
        principal=None)
    assert declared["prediction"]["tier"] == "declared" and declared["scenario"]["assumptions"][0]["claim"]
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        R.book_record_scenario(did, R.ScenarioRequest(method="learned", metric="x"), principal=None)
    assert exc.value.status_code == 422 and "no method named" in exc.value.detail
    assert R.record_calibration(connection_id=conn) == []


# ── law 5, narrowed ────────────────────────────────────────────────────────────────────────

def test_an_unscored_forecast_is_held_and_a_forecast_citing_a_scored_prediction_departs(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))
    from aughor.govern.departure import gate_departure
    conn = _conn()
    text = "Total sales are projected to reach 1,200 next week."
    held = gate_departure(kind="slack_post", org_id="default", conn_id=conn, text=text, automation_id="a1",
                         automation_name="t", target="#ops")
    assert held.state == "held" and "an unscored forecast never departs" in held.reason_sentence()
    assert "no prediction cited" in held.reason_sentence()
    # a declared prediction with no backtest and no scored class is unscored too
    unscored = S.predict(metric="total sales", projection=S.declared(variable="total sales", value=1200, by="user:ana",
                                                                    connection_id=conn),
                         settles_on="2026-10-12", author="user:ana", connection_id=conn)
    still = gate_departure(kind="slack_post", org_id="default", conn_id=conn, text=text, automation_id="a1",
                          automation_name="t", target="#ops", predictions=[unscored])
    assert still.state == "held" and "the cited predictions are unscored" in still.reason_sentence()
    # a history prediction carries its backtest, so the forecast departs — and the receipt says on what
    end = date(2026, 10, 4)
    starts = {(end - timedelta(days=7 * k + 6)).isoformat(): v for k, v in zip(range(6, 0, -1), [1000, 1040, 980, 1020, 1010, 990])}
    proj = S.history(SPEC, _run_sql_by_window(starts), end_day=end)
    scored = S.predict(metric="total sales", projection=proj, settles_on="2026-10-11", author="system", connection_id=conn)
    from aughor.govern.departure import Measurement
    from aughor.util.time import now_iso_z
    projected = Measurement(source=f"prediction {scored} (history)", values=[1200.0], measured_at=now_iso_z())
    ok = gate_departure(kind="slack_post", org_id="default", conn_id=conn, text=text, automation_id="a1",
                        automation_name="t", target="#ops-" + uuid.uuid4().hex[:4], predictions=[scored],
                        measurement=projected)
    assert ok.state == "departed", ok.reason_sentence()
    assert ok.guards["claims"] == "passed" and "backtest on total sales" in ok.checks["claims"]
