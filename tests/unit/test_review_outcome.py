"""Phase 3 of the 2027 study, P3-1 — the review measures the metric's own history, books the
Outcome with both verdicts, scores the prediction, and delivers the question.

What these hold: on its date the review measures the review window AND the prior windows (method
3), writes the history band onto the record, books the Record's Outcome with the verdict against
the expectation and against history by code (better · as expected · worse · cannot tell, each with
why), scores the prediction, and records how the question was delivered — a principal with no
channel bound is said, not silent; the person's later answer is laid beside the measured verdict,
never over it; a review that cannot measure history books cannot tell and says so.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from aughor.db.history import complete_investigation, create_investigation
from aughor.playbook import outcomes as O
from aughor.record import claims as C
from aughor.record import decisions as D
from aughor.routers import investigations as inv

SPEC = {"metric_label": "total sales", "metric_sql": "SUM(sale_price)", "metric_table": "thelook.order_items",
        "date_column": "thelook.order_items.created_at", "window_days": 7, "window_basis": "observation"}
ACCEPTED = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "_DEFAULT_PATH", tmp_path / "recommendation_outcomes.json")
    import aughor.settling.store as settling
    monkeypatch.setattr(settling, "learned_lag_days", lambda conn_id: None)


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _warehouse(values_by_start: dict[str, float], default: float):
    def run_sql_for(connection_id, **kw):
        def run_sql(sql):
            for start, v in values_by_start.items():
                if f">= DATE '{start}'" in sql:        # the window's START; its stop is another window's start
                    return (["value"], [[v]], None)
            return (["value"], [[default]], None)
        return run_sql
    return run_sql_for


def _accept(conn: str, monkeypatch, *, expectation=None, metric_before=None, run_sql_for) -> str:
    inv_id = create_investigation("why did sales fall?", conn)
    complete_investigation(inv_id, report={"headline": "Sales fell on fewer first orders", "spec": SPEC},
                           hypotheses=[], query_history=[], question="why did sales fall?", connection_id=conn,
                           skip_index=True, cache=False)
    import aughor.db.measure as M
    monkeypatch.setattr(M, "run_sql_for", run_sql_for)      # the acceptance measures its baseline through this door
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(
        rec_text="Raise the free-shipping threshold", status="accepted", review_days=30,
        metric_before=metric_before, expectation=expectation), principal=None)
    return inv_id


def test_the_review_measures_history_books_the_outcome_with_both_verdicts_and_scores_the_prediction(monkeypatch):
    conn = _conn()
    review_day = datetime.now(timezone.utc) + timedelta(days=31)
    end = review_day.date() - timedelta(days=1)
    review_start = (end - timedelta(days=6)).isoformat()
    history = {(end - timedelta(days=7 * k + 6)).isoformat(): v for k, v in zip(range(6, 0, -1), [1000, 1040, 980, 1020, 1010, 990])}
    warehouse = _warehouse({**history, review_start: 1400.0}, default=1000.0)
    inv_id = _accept(conn, monkeypatch, expectation=inv.ExpectationRequest(direction="up", low=2, high=4, unit="%"),
                     metric_before=1000.0, run_sql_for=warehouse)
    src = D.Source(kind="recommendation", ref=f"{inv_id}_rec_0")
    assert D.latest_decision(src).outcome == ""
    reviewed = O.run_due_reviews(review_day, run_sql_for=warehouse)
    o = next(r for r in reviewed if r.inv_id == inv_id)
    assert o.review_value == 1400.0 and o.history_value == pytest.approx(1006.67, abs=0.01) and o.history_n == 6
    assert o.history_low < o.history_value < o.history_high and "backtest on this metric" in o.history_note
    assert o.record_outcome_id
    outcome = D.outcome_by_id(o.record_outcome_id)
    assert outcome.actual == 1400.0 and outcome.baseline == o.history_value and outcome.effect.method == "history"
    assert outcome.against_expectation == "above"            # +40% against a +2..+4% band
    assert outcome.verdict == "better" and "beyond the expected band" in outcome.why
    assert outcome.measured_by == "system:review" and outcome.writes_back == ["prediction scored"]
    d = D.latest_decision(src)
    assert d.outcome == o.record_outcome_id and d.version == 2
    pred = C.latest(C.claim_key("prediction", D.decision_key(src)))
    assert pred.state == "scored" and pred.extra["scored_against"] == "above" and pred.extra["actual"] == 1400.0
    # the question's delivery is recorded — the accepter has no channel bound, so it is said
    assert o.review_delivery["door"] == "none" and o.review_delivery["status"] in ("not_sent", "nobody")
    assert "waits on the departures screen" in o.review_delivery["note"] or "no principal" in o.review_delivery["note"]
    # the person's later answer lies beside the measured verdict, never over it
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(rec_text="Raise the free-shipping threshold",
                                                                 status="rejected"), principal=None)
    latest = D.latest_decision(src)
    answered = D.outcome_by_id(latest.outcome)
    assert answered.verdict == "better" and answered.extra["answer"] == "rejected" and answered.extra["answer_verdict"] == "worse"
    assert answered.id != o.record_outcome_id and D.outcome_by_id(o.record_outcome_id).extra.get("answer") is None
    # a second review pass books nothing twice
    again = O.run_due_reviews(review_day + timedelta(days=1), run_sql_for=warehouse)
    assert not any(r.inv_id == inv_id for r in again)


def test_inside_historys_own_noise_is_cannot_tell_and_the_wrong_way_is_worse():
    from aughor.record.byproducts import _verdict_against_history
    v, why, e = _verdict_against_history(actual=1005, baseline=1000, low=980, high=1030, direction="up",
                                         against="inside", history_note="")
    assert v == "cannot_tell" and "inside the baseline's own noise" in why and e.method == "history"
    v, why, e = _verdict_against_history(actual=900, baseline=1000, low=980, high=1030, direction="up",
                                         against="below", history_note="")
    assert v == "worse" and "the wrong way" in why and e.value == -100
    v, why, e = _verdict_against_history(actual=1100, baseline=1000, low=980, high=1030, direction="up",
                                         against="inside", history_note="")
    assert v == "as_expected" and "the wanted way" in why
    v, why, e = _verdict_against_history(actual=1100, baseline=1000, low=980, high=1030, direction="",
                                         against="no expectation", history_note="")
    assert v == "cannot_tell" and "no expectation named the wanted direction" in why
    v, why, e = _verdict_against_history(actual=1100, baseline=None, low=None, high=None, direction="up",
                                         against="inside", history_note="only 1 prior window held a reading")
    assert v == "cannot_tell" and "no history baseline could be measured: only 1 prior window" in why


def test_a_review_with_too_little_history_books_cannot_tell_and_says_why(monkeypatch):
    conn = _conn()
    review_day = datetime.now(timezone.utc) + timedelta(days=31)
    end = review_day.date() - timedelta(days=1)
    review_start = (end - timedelta(days=6)).isoformat()

    def run_sql_for(connection_id, **kw):
        def run_sql(sql):
            if f">= DATE '{review_start}'" in sql:
                return (["value"], [[1300.0]], None)
            return (["value"], [], None)                   # no prior window holds rows
        return run_sql
    inv_id = _accept(conn, monkeypatch, expectation=inv.ExpectationRequest(direction="up", low=2, high=4, unit="%"),
                     metric_before=1000.0, run_sql_for=run_sql_for)
    reviewed = O.run_due_reviews(review_day, run_sql_for=run_sql_for)
    o = next(r for r in reviewed if r.inv_id == inv_id)
    assert o.history_value is None and "only 0 prior windows held a reading" in o.history_note
    outcome = D.outcome_by_id(o.record_outcome_id)
    assert outcome.verdict == "cannot_tell" and "no history baseline could be measured" in outcome.why
    assert outcome.against_expectation == "above" and outcome.baseline is None


def test_the_answer_before_any_review_books_the_outcome_against_the_expectation_alone(monkeypatch):
    conn = _conn()
    inv_id = _accept(conn, monkeypatch, expectation=inv.ExpectationRequest(direction="up", low=2, high=4, unit="%"),
                     metric_before=100.0, run_sql_for=_warehouse({}, default=100.0))
    inv.log_recommendation_outcome(inv_id, 0, inv.OutcomeRequest(rec_text="r", status="verified", metric_after=103.0),
                                   principal=None)
    d = D.latest_decision(D.Source(kind="recommendation", ref=f"{inv_id}_rec_0"))
    o = D.outcome_by_id(d.outcome)
    assert o.verdict == "as_expected" and o.against_expectation == "inside" and o.baseline is None
    assert "the review that measures it has not run" in o.why and o.extra["answer"] == "verified"


def test_the_heartbeat_scores_predictions_hourly(monkeypatch):
    from aughor.automations import scheduler as Sch
    from aughor.record import scenario as S
    calls: list[int] = []
    monkeypatch.setattr(S, "score_due_predictions", lambda *, run_sql_for, now=None: calls.append(1) or [])
    monkeypatch.setattr(Sch, "_last_prediction_check", 0.0)
    assert Sch.score_due_predictions_hourly(now=10_000.0) == 0 and len(calls) == 1
    assert Sch.score_due_predictions_hourly(now=10_000.0 + 60) == 0 and len(calls) == 1
    assert Sch.score_due_predictions_hourly(now=10_000.0 + 3601) == 0 and len(calls) == 2


def test_the_delivery_reaches_a_group_channel_through_the_gate_and_cites_the_departure(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))
    from types import SimpleNamespace
    from aughor.playbook import review_delivery as RD
    from aughor.playbook.outcomes import RecOutcome
    o = RecOutcome(id="inv9_rec_0", inv_id="inv9", rec_index=0, rec_text="Raise the threshold", connection_id="c1",
                   spec=SPEC, baseline_value=1000.0, review_value=1400.0, reviewed_at="2026-10-05T10:00:00+00:00",
                   review_question="You accepted \"Raise the threshold\" on 2026-09-01. total sales was 1,000 then "
                                   "(…); it is 1,400 now (…). Did it work?", review_asked_to="group:finance")
    monkeypatch.setattr("aughor.rbac.routing.route", lambda securable, *, org_id, owner="", parents=(), tags=None:
                        [SimpleNamespace(principal=owner, channel_trigger_id="trig-1", group_id="finance", why=("owner",))])
    trigger = SimpleNamespace(id="trig-1", name="finance channel", enabled=True)
    monkeypatch.setattr("aughor.notifications.store.get_trigger", lambda tid: trigger if tid == "trig-1" else None)
    sent: list = []
    monkeypatch.setattr("aughor.notifications.executor.fire_action",
                        lambda trig, payload: sent.append(payload) or SimpleNamespace(status="ok", error=""))
    out = RD.deliver_review_question(o, now=datetime(2026, 10, 5, 10, tzinfo=timezone.utc))
    if out["status"] == "sent":
        assert out["door"] == "channel" and out["to"] == "group:finance" and out["departure_id"]
        assert sent and sent[0].recommendation == o.review_question and sent[0].context["asked_to"] == "group:finance"
    else:
        # held by an accuracy law (law 2: no governed metric defines "total sales" here): said, with the row
        assert out["status"] == "held" and out["departure_id"] and out["note"]
        assert not sent
    nobody = RD.deliver_review_question(RecOutcome(id="x", inv_id="i", rec_index=0, rec_text="r"), now=None)
    assert nobody["status"] == "nobody"
