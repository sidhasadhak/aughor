"""Phase 5 of the 2027 study, P5-1 and P5-2 — the mission as a ledger kind written by people
(`aughor/record/mission.py`), triage's first term fed from it, the authority ceiling it sets, the
interruptions it is charged, and the report it is judged by.

What these hold: a mission written by an agent or the system is refused, one with no owner never
becomes active; the gate scores the mission term from the missions people wrote and writes the
mission on the departure's row; a mission's own interruptions a week are charged and the next one
is held, listed and named; the ladder caps an action at the ceiling an active mission set; the
report leads with the objective against the metric's own history and says "no measurable effect
yet" when that is so; a report is booked, the mission advanced, and an owner with no channel is
said; the heartbeat reports what is due.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from aughor.govern import attention as A
from aughor.govern.departure import HELD_BUDGET, gate_departure
from aughor.record import decisions as D
from aughor.record import mission as M
from aughor.routers import record as R

SPEC = {"metric_label": "gross margin", "metric_sql": "SUM(margin)", "metric_table": "shop.orders",
        "date_column": "shop.orders.created_at", "window_days": 30}


@pytest.fixture(autouse=True)
def _own_departures(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _mission(conn, **kw) -> M.Mission:
    base = dict(name="Protect gross margin " + uuid.uuid4().hex[:4],
                objective=M.Objective(metric="gross margin", direction="up", target=0.41, unit="%", spec=dict(SPEC)),
                constraints=[M.Constraint(metric="delivery promise kept", limit=0.92, bound="at_least")],
                scope=M.Scope(domain="EU", segment="apparel", connections=[conn]),
                owner="user:ana", budget=M.Budget(interruptions_per_week=3, authority_ceiling={"change_price": 3, "pause_promo": 4}),
                watches=[M.Watch(kind="monitor", ref="mon-1", label="returns rate")],
                review=M.Review(cadence="monthly"), state="active")
    base.update(kw)
    return M.Mission(**base)


# ── the door ───────────────────────────────────────────────────────────────────────────────

def test_people_write_missions_and_a_model_never_does():
    conn = _conn()
    with pytest.raises(M.MissionRefused, match="people write missions"):
        M.write_mission(_mission(conn), by="agent:analyst", by_kind="agent")
    with pytest.raises(M.MissionRefused, match="people write missions"):
        M.write_mission(_mission(conn), by="system", by_kind="system")
    with pytest.raises(M.MissionRefused, match="owner is a person"):
        M.write_mission(_mission(conn, owner="agent:explorer"), by="user:ana")
    m = M.write_mission(_mission(conn), by="user:ana")
    assert m.id and m.key.startswith(f"mission:{conn}:protect-gross-margin") and m.written_by == "user:ana"
    assert m.state == "active" and m.review.next_report_on and m.opened_at
    # an edit is a new version under the same key, the old kept, with the history line
    m2 = _mission(conn, name=m.name, key=m.key, budget=M.Budget(interruptions_per_week=5))
    booked = M.write_mission(m2, by="user:ana")
    assert booked.version == 2 and booked.budget.interruptions_per_week == 5 and booked.history[-1]["why"] == "edited"
    assert M.get_mission(m.id).budget.interruptions_per_week == 3    # the old version stands


def test_a_mission_without_an_owner_does_not_run():
    conn = _conn()
    with pytest.raises(M.MissionRefused, match="without an owner does not run"):
        M.write_mission(_mission(conn, owner="", state="active"), by="user:ana")
    proposed = M.write_mission(_mission(conn, owner="", state="proposed"), by="user:ana")
    assert proposed.state == "proposed" and M.active_missions(conn) == []
    with pytest.raises(M.MissionRefused, match="name an owner"):
        M.set_state(proposed.id, "active", by="user:ana")
    owned = M.write_mission(_mission(conn, name=proposed.name, key=proposed.key, owner="user:ana", state="proposed"), by="user:ana")
    active = M.set_state(owned.id, "active", by="user:ana", why="owner named")
    assert active.state == "active" and [m.id for m in M.active_missions(conn)] == [active.id]
    assert active.history[-1] == {**active.history[-1], "from": "proposed", "to": "active", "by": "user:ana"}
    paused = M.set_state(active.id, "paused", by="user:ana")
    assert paused.state == "paused" and M.active_missions(conn) == []
    with pytest.raises(M.MissionRefused, match="a person changes"):
        M.set_state(paused.id, "retired", by="agent:x")
    view = R.list_record_missions(connection_id=conn)
    assert view and view[0]["runs"] is False and "paused" in view[0]["runs_note"]


def test_the_door_refuses_what_it_cannot_keep():
    conn = _conn()
    with pytest.raises(M.MissionRefused, match="names the metric"):
        M.write_mission(_mission(conn, objective=M.Objective(metric="")), by="user:ana")
    with pytest.raises(M.MissionRefused, match="cadence"):
        M.write_mission(_mission(conn, review=M.Review(cadence="daily")), by="user:ana")
    with pytest.raises(M.MissionRefused, match="L0–L5"):
        M.write_mission(_mission(conn, budget=M.Budget(authority_ceiling={"x": 9})), by="user:ana")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        R.write_record_mission(R.MissionRequest(name="x", objective=R.ObjectiveIn(metric="m"), connections=[conn],
                                                budget=R.BudgetIn(authority_ceiling={"*": 7})), principal=None)
    assert e.value.status_code == 422


# ── what the loop reads ────────────────────────────────────────────────────────────────────

def test_triage_s_mission_term_reads_the_missions_people_wrote_and_the_row_carries_the_mission():
    conn = _conn()
    assert M.bearing(conn, metric="gross margin")["score"] == 0.0
    m = M.write_mission(_mission(conn), by="user:ana")
    b = M.bearing(conn, about="metric:gross margin")
    assert b["score"] == 1.0 and b["missions"][0]["mission"] == m.id and "objective" in b["why"]
    assert M.bearing(conn, metric="delivery promise kept")["score"] == 0.7
    assert M.bearing(conn, text="The returns rate climbed again this week.")["score"] == 0.5
    assert M.bearing(conn, text="Nothing about anything the mission follows.")["score"] == 0.0
    place = "#margin-" + uuid.uuid4().hex[:6]
    v = gate_departure(kind="analysis", org_id="default", conn_id=conn, text="Gross margin held at the usual level.",
                       target=place, about="metric:gross margin", automation_id="a1", automation_name="chain")
    assert v.state == "departed" and "mission 1.00" in v.checks["triage"] and v.checks["mission"] == m.id
    assert v.checks["mission_names"] == m.name and m.name in v.checks["attention"]
    other = gate_departure(kind="analysis", org_id="default", conn_id=conn, text="Signups were ordinary today.",
                           target=place, automation_id="a1", automation_name="chain")
    assert "mission 0.00" in other.checks["triage"] and "mission" not in other.checks
    # the published term says how it is read now
    assert "missions people wrote" in A.TERMS[0]["read_today"]


def test_a_mission_is_charged_for_every_interruption_and_a_spent_one_is_held_and_named():
    conn = _conn()
    m = M.write_mission(_mission(conn, budget=M.Budget(interruptions_per_week=2)), by="user:ana")
    place = "#ops-" + uuid.uuid4().hex[:6]
    A.set_slots(place, 50)                       # the place has room; the mission does not
    texts = ["Gross margin stayed flat this week.", "Gross margin dipped a little on Tuesday.", "Gross margin recovered by Friday."]
    verdicts = [gate_departure(kind="analysis", org_id="default", conn_id=conn, text=t, target=place,
                               about="metric:gross margin", automation_id="a1", automation_name="chain") for t in texts]
    assert [v.state for v in verdicts] == ["departed", "departed", HELD_BUDGET]
    assert M.interruptions_this_week(m.id) == 2
    held = verdicts[2]
    assert "mission budget" in held.reason_sentence() and m.name in held.reason_sentence() and "2 interruptions a week" in held.reason_sentence()
    assert held.checks["mission"] == m.id
    from aughor.govern.departure_store import held_bearing
    assert [h["id"] for h in held_bearing(m.id)] == [held.record_id]
    # a message that bears on nothing is not charged to the mission
    free = gate_departure(kind="analysis", org_id="default", conn_id=conn, text="Signups were ordinary.", target=place,
                          automation_id="a1", automation_name="chain")
    assert free.state == "departed" and M.interruptions_this_week(m.id) == 2
    assert R.get_record_mission(m.id)["interruptions_this_week"] == 2


def test_the_ladder_is_capped_at_the_ceiling_an_active_mission_set():
    from types import SimpleNamespace
    from aughor.actions import authority as AU
    from aughor.ontology.models import Undo, Verification
    conn = _conn()
    # the ladder reads a declaration's fields, so a declared side-effect action is its fields here
    action = SimpleNamespace(id="change_price", kind="side_effect", reversibility="compensable",
                             verification=Verification(sql="SELECT 1 FROM prices WHERE sku = '{sku}'", expects="rows"),
                             undo=Undo(action_id="revert_price", window_hours=24))
    assert M.ceiling_for("change_price", conn) is None
    before = AU.level_for(action, conn)
    assert before["level"] == 3 and before["ceiling"] == 4
    M.write_mission(_mission(conn, budget=M.Budget(authority_ceiling={"change_price": 2, "*": 4})), by="user:ana")
    assert M.ceiling_for("change_price", conn) == 2 and M.ceiling_for("pause_promo", conn) == 4 and M.ceiling_for("x", "other") is None
    capped = AU.level_for(action, conn)
    assert capped["level"] == 2 and capped["ceiling"] == 2 and any("mission on this scope caps it at L2" in n for n in capped["notes"])
    assert not any("unreachable until missions exist" in n for n in capped["notes"])


def test_an_inquiry_opened_from_a_signal_carries_the_mission_it_bears_on():
    from aughor.record import inquiry as I
    conn = _conn()
    m = M.write_mission(_mission(conn), by="user:ana")
    assert I.mission_for(conn, "gross margin") == m.id and I.mission_for(conn, "signups") == ""
    q = I.open_inquiry(question="Why did gross margin fall below its band?", connection_id=conn, opened_by="monitor:mon-1",
                       mission=I.mission_for(conn, "gross margin"))
    assert q.extra["mission"] == m.id


def test_a_decision_on_a_metric_a_mission_bears_on_carries_the_mission(monkeypatch):
    from aughor.playbook.outcomes import RecOutcome
    from aughor.record.byproducts import decision_from_recommendation
    conn = _conn()
    m = M.write_mission(_mission(conn), by="user:ana")
    o = RecOutcome(id="inv9_rec_0", inv_id="inv9", rec_index=0, rec_text="Raise prices on the slow sellers",
                   status="accepted", metric_name="gross margin")
    did = decision_from_recommendation(o, chosen="accept", decided_by="user:ana", connection_id=conn)
    assert D.get_decision(did).objective == m.id


# ── the report ─────────────────────────────────────────────────────────────────────────────

def _warehouse(values_by_start: dict[str, float], default: float):
    def run_sql_for(connection_id, **kw):
        def run_sql(sql):
            for start, v in values_by_start.items():
                if f">= DATE '{start}'" in sql:
                    return (["value"], [[v]], None)
            return (["value"], [[default]], None)
        return run_sql
    return run_sql_for


NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def _windows(now: datetime, days: int = 30) -> list[str]:
    end = now.date() - timedelta(days=1)
    return [(end - timedelta(days=days * k) - timedelta(days=days - 1)).isoformat() for k in range(1, 7)]


def test_the_report_leads_with_the_objective_against_its_own_history_and_says_no_effect_yet():
    conn = _conn()
    m = M.write_mission(_mission(conn), by="user:ana")
    # six prior windows around 0.38; the report window reads 0.385 — inside the history band
    prior = {start: v for start, v in zip(_windows(NOW), [0.38, 0.375, 0.385, 0.38, 0.39, 0.37])}
    report = M.compose_report(m, run_sql_for=_warehouse(prior, default=0.385), now=NOW)
    obj = report["objective"]
    assert obj["measurable"] and obj["actual"] == 0.385 and obj["baseline"] == pytest.approx(0.38, abs=1e-6)
    assert obj["against_baseline"] == "inside" and obj["verdict"] == "unmoved" and "no movement past the noise" in obj["why"]
    assert report["headline"].startswith("the objective did not move past its baseline's noise")
    assert "0 inquiries, 0 findings, 0 decisions, no measurable effect yet; 0 of 12 interruptions used." in report["headline"]
    assert report["cost"]["interruptions_budgeted"] == 12          # 3 a week over a 30-day period
    assert report["period"] == {"from": "2026-10-03", "to": "2026-11-01", "days": 30, "cadence": "monthly"}
    assert report["constraints"][0]["held"] is None and "cannot tell" in report["constraints"][0]["note"]
    assert report["watches"][0]["kind"] == "monitor" and report["cost"]["spend"]["note"].startswith("no spend budget")
    assert report["composed_by"].startswith("code")
    # the objective moved the wanted way, past the band, and the target is said
    moved = M.compose_report(m, run_sql_for=_warehouse(prior, default=0.43), now=NOW)["objective"]
    assert moved["verdict"] == "moved" and "the target is met" in moved["why"]
    against = M.compose_report(m, run_sql_for=_warehouse(prior, default=0.30), now=NOW)["objective"]
    assert against["verdict"] == "against" and "wrong way" in against["why"]


def test_a_report_with_nothing_measurable_says_so_and_counts_the_work_anyway():
    from aughor.record import inquiry as I
    conn = _conn()
    m = M.write_mission(_mission(conn, objective=M.Objective(metric="brand love", direction="up", spec=None),
                                 constraints=[]), by="user:ana")
    I.open_inquiry(question="Why did brand love fall?", connection_id=conn, opened_by=f"mission:{m.id}")
    report = M.compose_report(m, run_sql_for=_warehouse({}, default=1.0), now=NOW)
    assert report["objective"]["measurable"] is False and report["objective"]["verdict"] == "cannot_tell"
    assert "no measurable definition" in report["objective"]["why"]
    assert report["opened"]["inquiries"] == 1 and report["opened"]["by_state"] == {"open": 1}
    assert "1 inquiry, 0 findings" in report["headline"] and "could not be judged" in report["headline"]


def test_a_report_is_booked_the_mission_advanced_and_an_owner_with_no_channel_is_said(monkeypatch):
    conn = _conn()
    m = M.write_mission(_mission(conn), by="user:ana")
    prior = {start: v for start, v in zip(_windows(NOW), [0.38, 0.375, 0.385, 0.38, 0.39, 0.37])}
    import aughor.rbac.routing as routing
    monkeypatch.setattr(routing, "route", lambda securable, **kw: [])
    out = M.report_now(m, run_sql_for=_warehouse(prior, default=0.385), now=NOW)
    assert out["report_id"] and out["delivery"]["status"] == "not_sent" and "no channel bound" in out["delivery"]["note"]
    after = M.latest(m.key)
    assert after.review.last_report == out["report_id"] and after.review.reports == [out["report_id"]]
    assert after.review.next_report_on == "2026-12-02" and after.extra["last_report_headline"].startswith("the objective")
    assert M.get_report(out["report_id"])["mission"] == m.id and M.reports_for(after)[0]["id"] == out["report_id"]
    view = R.get_record_mission(m.id)
    assert view["reports"][0]["verdict"] == "unmoved"
    booked = R.get_record_mission_report(m.id)
    assert booked["booked"] and booked["report"]["id"] == out["report_id"]


def test_the_heartbeat_reports_the_missions_whose_date_has_come(monkeypatch):
    from aughor.automations import scheduler as S
    conn = _conn()
    due = M.write_mission(_mission(conn, review=M.Review(cadence="weekly", next_report_on="2026-10-01")), by="user:ana")
    M.write_mission(_mission(conn, name="Later " + uuid.uuid4().hex[:4],
                             review=M.Review(cadence="weekly", next_report_on="2099-01-01")), by="user:ana")
    assert [x.id for x in M.due_reports(NOW)] == [due.id]
    import aughor.rbac.routing as routing
    monkeypatch.setattr(routing, "route", lambda securable, **kw: [])
    import aughor.db.measure as measure
    monkeypatch.setattr(measure, "run_sql_for", _warehouse({}, default=0.4))
    monkeypatch.setattr(S, "_last_mission_check", 0.0)
    assert S.report_due_missions_hourly(now=1_900_000_000.0) >= 1
    assert S.report_due_missions_hourly(now=1_900_000_100.0) == 0          # the hour has not passed
    after = M.latest(due.key)
    assert after.review.last_report and after.review.next_report_on > date.today().isoformat()


def test_a_governed_metric_resolves_to_the_report_s_measurable_definition(monkeypatch):
    import aughor.semantic.metrics as SM
    from aughor.semantic.metrics import MetricDefinition
    gm = MetricDefinition(name="gross_margin", label="Gross margin", sql="SUM(margin) / SUM(revenue)",
                          tables=["shop.orders"], time_column="created_at", unit="%", status="approved")
    monkeypatch.setattr(SM, "get_metric", lambda name, path=None, connection_id=None: gm if name == "gross_margin" else None)
    monkeypatch.setattr(SM, "list_metrics", lambda *a, **k: [gm])
    spec = M.spec_for_metric("Gross margin", "c1")
    assert spec == {"metric_label": "Gross margin", "metric_name": "gross_margin", "metric_sql": "SUM(margin) / SUM(revenue)",
                    "metric_table": "shop.orders", "date_column": "shop.orders.created_at", "window_days": 30, "unit": "%"}
    assert M.spec_for_metric("brand love", "c1") is None
    conn = _conn()
    m = M.write_mission(_mission(conn, objective=M.Objective(metric="gross_margin", direction="up", spec=None)), by="user:ana")
    assert m.objective.spec["metric_table"] == "shop.orders"
