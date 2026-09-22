"""CB-2 — decide when to ask whether a recommendation worked, at the moment it is accepted.

Measured before this wave: the outcome record had `metric_before`/`metric_after`, filled only by
the request that logged the outcome; the inbox sends neither; nothing measured a baseline, nothing
scheduled a second measurement, nothing asked anyone — and `data/recommendation_outcomes.json` had
never been written on the live deployment. The loop ran and nobody had used it.

Now acceptance records the answer's own measurable definition (`report.spec`), the metric's value
then, and a review date; the heartbeat measures again on that date and asks the metric's owner
(the user's call) or, until one is linked, the person who accepted. These tests pin: the spec is
what the report carries; a baseline is measured with a same-length window ending yesterday and
refuses a definition it cannot measure alone; acceptance decides the date; a review runs once, on
its date, writes the second number and the question, and goes to the right person; and a later
answer (verified / rejected) keeps everything the acceptance and review recorded.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from aughor.agent.investigate import _measurable_spec
from aughor.playbook import outcomes as O

SPEC = {"metric_label": "total sales", "metric_sql": "SUM(sale_price)", "metric_table": "thelook.order_items",
        "date_column": "thelook.order_items.created_at", "window_days": 14}
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _run_sql_returning(value):
    calls: list[str] = []

    def run_sql(sql):
        calls.append(sql)
        return (["value"], [[value]], None)
    run_sql.calls = calls
    return run_sql


@pytest.fixture()
def path(tmp_path):
    return tmp_path / "recommendation_outcomes.json"


class TestTheReportCarriesItsDefinition:
    def test_the_spec_is_the_intakes_measurable_definition(self):
        spec = _measurable_spec({"metric_label": "total sales", "metric_sql": "SUM(sale_price)",
                                 "metric_table": "thelook.order_items", "date_column": "thelook.order_items.created_at",
                                 "observation_start": "2026-09-08", "observation_end": "2026-09-21"})
        assert spec == SPEC

    def test_no_metric_means_no_spec_not_a_guess(self):
        assert _measurable_spec({"metric_label": "x"}) is None
        assert _measurable_spec({}) is None

    def test_both_report_assemblers_carry_it(self):
        import inspect
        from aughor.agent import investigate
        src = inspect.getsource(investigate)
        assert src.count("spec=_measurable_spec(intake_data),") == 2


class TestTheBaselineIsMeasuredWithTheAnswersOwnDefinition:
    def test_the_window_is_the_same_length_ending_on_the_given_day(self):
        sql, label, why = O.measurement_sql(SPEC, end_day=date(2026, 9, 21))
        assert why == "" and label == "2026-09-08 → 2026-09-21 (14 days)"
        assert sql == ("SELECT SUM(sale_price) AS value FROM thelook.order_items WHERE "
                       "CAST(created_at AS DATE) >= DATE '2026-09-08' AND CAST(created_at AS DATE) < DATE '2026-09-22'")

    def test_a_metric_that_spans_tables_is_refused_not_guessed(self):
        spec = dict(SPEC, metric_sql="AVG(DATEDIFF('day', luxexperience.orders.order_date, luxexperience.shipments.ship_date))",
                    metric_table="luxexperience.shipments")
        sql, _label, why = O.measurement_sql(spec, end_day=date(2026, 9, 21))
        assert sql is None and "spans tables" in why

    def test_a_date_column_on_another_table_is_refused(self):
        sql, _l, why = O.measurement_sql(dict(SPEC, date_column="thelook.orders.created_at"), end_day=date(2026, 9, 21))
        assert sql is None and "not on" in why

    def test_measure_reads_the_number_and_reports_why_not(self):
        assert O.measure_spec(SPEC, _run_sql_returning(12.5), end_day=date(2026, 9, 21))[0] == 12.5
        assert O.measure_spec(SPEC, lambda s: ([], [], "boom"), end_day=date(2026, 9, 21))[2].startswith("measurement failed")
        assert O.measure_spec(SPEC, lambda s: ([], [], None), end_day=date(2026, 9, 21))[2] == "the window holds no rows"
        assert O.measure_spec(SPEC, lambda s: ([], [["abc"]], None), end_day=date(2026, 9, 21))[2].startswith("the metric did not read")


class TestAcceptanceDecidesTheReview:
    def test_accepting_records_baseline_and_date(self, path):
        o = O.log_outcome("inv1", 0, "Pause the other pilots", "accepted", path=path)
        run_sql = _run_sql_returning(1000.0)
        o = O.record_acceptance(o, spec=SPEC, connection_id="c1", accepted_by="user:ana", run_sql=run_sql, now=NOW, path=path)
        assert o.baseline_value == 1000.0 and o.metric_before == 1000.0 and o.metric_name == "total sales"
        assert o.baseline_window == "2026-09-08 → 2026-09-21 (14 days)"      # ends yesterday, same length
        assert o.review_days == 30 and o.review_at == (NOW + timedelta(days=30)).isoformat()
        assert o.accepted_by == "user:ana" and o.connection_id == "c1" and o.review_note == ""
        assert "DATE '2026-09-08'" in run_sql.calls[0]

    def test_a_custom_review_horizon_and_an_unmeasurable_answer(self, path):
        o = O.log_outcome("inv2", 0, "x", "accepted", path=path)
        o = O.record_acceptance(o, spec=None, connection_id="c1", accepted_by="u", run_sql=_run_sql_returning(1),
                                review_days=7, now=NOW, path=path)
        assert o.review_days == 7 and o.baseline_value is None
        assert "no measurable definition" in o.review_note

    def test_the_answer_to_the_question_keeps_what_acceptance_recorded(self, path):
        o = O.log_outcome("inv3", 0, "x", "accepted", path=path)
        O.record_acceptance(o, spec=SPEC, connection_id="c1", accepted_by="u", run_sql=_run_sql_returning(10.0), now=NOW, path=path)
        later = O.log_outcome("inv3", 0, "x", "verified", path=path)       # the inbox sends no numbers
        assert later.status == "verified" and later.baseline_value == 10.0 and later.spec == SPEC
        assert later.metric_before == 10.0 and later.review_at and later.accepted_by == "u"


class TestTheReviewRunsOnceOnItsDate:
    def _accepted(self, path, *, spec=SPEC, accepted_by="user:ana", inv="inv1"):
        o = O.log_outcome(inv, 0, "Pause the other pilots", "accepted", path=path)
        return O.record_acceptance(o, spec=spec, connection_id="c1", accepted_by=accepted_by,
                                   run_sql=_run_sql_returning(1000.0), now=NOW, path=path)

    def test_not_due_means_not_asked(self, path):
        self._accepted(path)
        assert O.due_reviews(NOW + timedelta(days=29), path) == []
        assert O.run_due_reviews(NOW + timedelta(days=29), run_sql_for=lambda c: _run_sql_returning(1), path=path) == []

    def test_due_means_measured_again_and_asked_once(self, path, monkeypatch):
        self._accepted(path)
        run = O.run_due_reviews(NOW + timedelta(days=30), run_sql_for=lambda c: _run_sql_returning(1200.0), path=path)
        assert len(run) == 1
        o = run[0]
        assert o.review_value == 1200.0 and o.metric_after == 1200.0 and o.reviewed_at
        assert o.review_window == "2026-10-08 → 2026-10-21 (14 days)"
        assert o.review_asked_to == "user:ana" and o.review_asked_at
        assert o.review_question == ('You accepted "Pause the other pilots" on 2026-09-22. total sales was 1000 then '
                                     '(2026-09-08 → 2026-09-21 (14 days)); it is 1200 now (2026-10-08 → 2026-10-21 (14 days)). Did it work?')
        again = O.run_due_reviews(NOW + timedelta(days=31), run_sql_for=lambda c: _run_sql_returning(1300.0), path=path)
        assert again == []                                              # asked once
        assert O.load_all_outcomes(path)[0].review_value == 1200.0

    def test_an_answered_recommendation_is_never_asked(self, path):
        self._accepted(path)
        O.log_outcome("inv1", 0, "Pause the other pilots", "rejected", path=path)
        assert O.due_reviews(NOW + timedelta(days=40), path) == []

    def test_the_metrics_owner_is_asked_when_the_catalog_can_route_one(self, path, monkeypatch):
        from types import SimpleNamespace
        import aughor.semantic.metrics as M
        monkeypatch.setattr(M, "get_metric", lambda name, path=None, connection_id=None: SimpleNamespace(owner="user:finance-lead"))
        self._accepted(path)
        run = O.run_due_reviews(NOW + timedelta(days=30), run_sql_for=lambda c: _run_sql_returning(1200.0), path=path)
        assert run[0].review_asked_to == "user:finance-lead"

    def test_a_free_text_owner_does_not_route_so_the_accepter_is_asked(self, path, monkeypatch):
        from types import SimpleNamespace
        import aughor.semantic.metrics as M
        monkeypatch.setattr(M, "get_metric", lambda name, path=None, connection_id=None: SimpleNamespace(owner="Ana (logistics)"))
        self._accepted(path)
        run = O.run_due_reviews(NOW + timedelta(days=30), run_sql_for=lambda c: _run_sql_returning(1200.0), path=path)
        assert run[0].review_asked_to == "user:ana"

    def test_a_measurement_that_fails_still_asks_with_the_failure_on_the_record(self, path):
        self._accepted(path)

        def broken(_c):
            raise RuntimeError("warehouse down")
        run = O.run_due_reviews(NOW + timedelta(days=30), run_sql_for=broken, path=path)
        assert run[0].review_value is None and "warehouse down" in run[0].review_note
        assert run[0].review_question.endswith("it could not be measured now. Did it work?")


class TestTheHeartbeatAsksHourly:
    def test_once_an_hour_and_forceable(self, monkeypatch):
        from aughor.automations import scheduler as S
        calls: list[int] = []
        monkeypatch.setattr(O, "run_due_reviews", lambda now=None, *, run_sql_for, path=None: calls.append(1) or [])
        monkeypatch.setattr(S, "_last_review_check", 0.0)
        assert S.run_due_reviews_hourly(now=10_000.0) == 0 and len(calls) == 1
        assert S.run_due_reviews_hourly(now=10_000.0 + 60) == 0 and len(calls) == 1      # a minute later: no
        assert S.run_due_reviews_hourly(now=10_000.0 + 3601) == 0 and len(calls) == 2    # an hour later: yes
        S.run_due_reviews_hourly(now=10_000.0 + 3602, force=True)
        assert len(calls) == 3

    def test_the_tick_counts_reviews(self, monkeypatch):
        from aughor.automations import scheduler as S
        monkeypatch.setattr(S, "run_due_reviews_hourly", lambda **k: 2)
        monkeypatch.setattr("aughor.automations.store.list_automations", lambda enabled_only=True: [])
        monkeypatch.setattr("aughor.automations.adopt.list_adopted_automations", lambda: [])
        monkeypatch.setattr("aughor.automations.engine.resume_parked_runs", lambda: 0)
        assert S.tick_once()["reviews"] == 2


class TestTheDoorMeasuresOnAccept:
    def test_accepting_through_the_door_records_the_baseline(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(O, "_DEFAULT_PATH", tmp_path / "outcomes.json")
        import aughor.routers.investigations as R
        monkeypatch.setattr(R, "get_investigation", lambda inv_id: {"id": inv_id, "connection_id": "fixture",
                                                                       "report": {"spec": SPEC}})
        monkeypatch.setattr("aughor.db.measure.run_sql_for", lambda cid: _run_sql_returning(42.0))
        r = client.post("/investigations/invX/recommendations/0/outcome",
                        json={"rec_text": "Do the thing", "status": "accepted", "review_days": 14})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["baseline_value"] == 42.0 and body["review_days"] == 14 and body["review_at"]
        assert body["connection_id"] == "fixture" and body["spec"] == SPEC

    def test_a_status_change_does_not_measure(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(O, "_DEFAULT_PATH", tmp_path / "outcomes.json")
        import aughor.routers.investigations as R
        called = []
        monkeypatch.setattr(R, "_record_acceptance", lambda *a, **k: called.append(1))
        r = client.post("/investigations/invY/recommendations/0/outcome", json={"rec_text": "x", "status": "dismissed"})
        assert r.status_code == 201 and called == []
