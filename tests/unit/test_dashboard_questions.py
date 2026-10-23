"""A Question on a dashboard (PENDING 54; design-mockups/dashboard-questions.html, approved 2026-10-23).

A person keeps a question on a dashboard; the agent the Data Canvas uses answers it on a rhythm — weekly by default —
or only when asked; the dashboard shows the latest answer as the Data Canvas shows one, with every earlier answer, and
never asks on open. No new store: the rhythm is an automation (the machinery theLook's daily question runs on), and
every answer is filed under the question's own session and read back by it.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from aughor.automations.store import get_automation
from aughor.dashboards import questions as Q
from aughor.db import history as H
from aughor.kernel.flags import flag_overrides

CONN = "thelook-q"

REPORT = {
    "headline": "Revenue rose $774.33 on 15 Oct to $16,907.77; Outerwear & Coats led the gain",
    "executive_summary": "Revenue on 15 Oct was $16,907.77 on 279 orders, up $774.33 on the day before.",
    "figures": [{"label": "Revenue, 15 Oct", "value": "$16,907.77", "note": "279 orders"},
                {"label": "Outerwear & Coats", "value": "+$1,314.50", "note": "$1,199.63 to $2,514.13"}],
    "phases": [{"phase_id": "decomposition", "findings": [
        {"claim": "Orders rose to 279 from 257 while average order value slipped to $60.60 from $62.78"},
        {"claim": "Outerwear & Coats at +$1,314.50 is the largest contributor"}]},
        {"phase_id": "baseline", "findings": [{"claim": "a baseline claim the why never shows"}]}],
    "attribution_waterfall": [],
    "gaps": "Why Outerwear rose was not tested.",
    "confidence": "MEDIUM", "observation_period": "2026-10-15", "comparison_basis": "2026-10-14 (previous day)",
}


@pytest.fixture
def on():
    with flag_overrides({"dashboard.composed": True, "dashboard.questions": True}):
        yield


@pytest.fixture(scope="module")
def client():
    from aughor.api import app
    return TestClient(app)


def _answered(question: str, *, session: str = "", report: dict | None = None) -> str:
    inv = H.create_investigation(question, CONN, session_id=session)
    H.complete_investigation(inv, report=report or REPORT, hypotheses=[], query_history=[], question=question,
                             connection_id=CONN)
    return inv


# ── off ────────────────────────────────────────────────────────────────────────────────────

def test_off_the_question_routes_answer_404_and_keep_nothing(client):
    with flag_overrides({"dashboard.composed": True, "dashboard.questions": False}):
        r = client.post("/dashboards/questions", params={"connection_id": CONN}, json={"question": "Why?"})
        assert r.status_code == 404 and "dashboard.questions" in r.json()["detail"]
        assert client.get("/dashboards/questions/abc").status_code == 404


def test_a_run_with_no_session_is_filed_exactly_as_before():
    from aughor.runners.investigation import InvestigationRequest, _ask_request
    plain = _ask_request(InvestigationRequest(question="q", connection_id=CONN))
    tagged = _ask_request(InvestigationRequest(question="q", connection_id=CONN, session_id="question:abc"))
    assert plain.session_id == "" and tagged.session_id == "question:abc"


# ── keeping one ────────────────────────────────────────────────────────────────────────────

def test_kept_weekly_by_default_on_mondays_and_its_answers_filed_under_its_own_session(client, on):
    r = client.post("/dashboards/questions", params={"connection_id": CONN},
                    json={"question": "How did sales change week over week, and why?"})
    assert r.status_code == 201, r.text
    out = r.json()
    a = get_automation(out["automation_id"])
    assert out["rhythm"] == "weekly" and Q.rhythm_of(a) == "weekly"
    assert [(c.kind, c.config) for c in a.conditions] == [("schedule", {"cron": "0 9 * * mon"})]
    [step] = a.effects
    assert step.kind == "investigate"
    assert step.config == {"question": "How did sales change week over week, and why?", "session_id": out["session"]}
    assert out["session"].startswith("question:")


def test_only_when_asked_never_fires_on_its_own(on):
    out = Q.keep(connection_id=CONN, question="What changed?", rhythm="ask")
    a = get_automation(out["automation_id"])
    assert [c.kind for c in a.conditions] == ["webhook"] and Q.next_at(a) is None


@pytest.mark.parametrize("kw, said", [
    ({"question": "   "}, "a question needs its words"),
    ({"question": "x" * 501}, "at most 500 characters"),
    ({"question": "Why?", "rhythm": "hourly"}, "daily, weekly, monthly or only when asked"),
    ({"question": "Why?", "first_run": "nope0000"}, "no answer 'nope0000' to start from"),
])
def test_what_cannot_be_kept_says_why(on, kw, said):
    with pytest.raises(Q.QuestionRefused, match=said):
        Q.keep(connection_id=CONN, **kw)


def test_an_answer_from_another_connection_is_not_a_start(on):
    inv = H.create_investigation("q", "another-conn")
    H.complete_investigation(inv, report=REPORT, hypotheses=[], query_history=[], question="q",
                             connection_id="another-conn")
    with pytest.raises(Q.QuestionRefused, match="another connection"):
        Q.keep(connection_id=CONN, question="q", first_run=inv)


# ── reading it ─────────────────────────────────────────────────────────────────────────────

def test_it_reads_its_own_answers_newest_first_and_the_latest_in_full(client, on):
    first = _answered("Why did revenue change last month?")                       # kept from the Data Canvas
    out = Q.keep(connection_id=CONN, question="Why did revenue change last month?", rhythm="monthly", first_run=first)
    later = _answered("Why did revenue change last month?", session=out["session"],
                      report={**REPORT, "headline": "A later answer"})
    _answered("Why did revenue change last month?")                               # same words, not this question's
    r = client.get(f"/dashboards/questions/{out['automation_id']}", params={"first": first})
    assert r.status_code == 200, r.text
    got = r.json()
    assert [a["id"] for a in got["answers"]] == [later, first]
    assert got["latest"]["id"] == later and got["latest"]["headline"] == "A later answer"
    assert got["latest"]["figures"][0] == {"label": "Revenue, 15 Oct", "value": "$16,907.77", "note": "279 orders"}
    assert got["latest"]["why"] == {"drivers": [], "lines": [
        "Orders rose to 279 from 257 while average order value slipped to $60.60 from $62.78",
        "Outerwear & Coats at +$1,314.50 is the largest contributor"]}
    assert got["latest"]["gaps"] == "Why Outerwear rose was not tested."
    assert (got["latest"]["period"], got["latest"]["confidence"]) == ("2026-10-15", "MEDIUM")
    assert got["rhythm"] == "monthly" and got["next_at"].endswith("09:00:00+00:00")
    assert "minutes" in got["cost"] and "from" in got["cost"]


def test_a_weekly_question_is_next_asked_on_a_monday_at_nine(on):
    a = get_automation(Q.keep(connection_id=CONN, question="Week over week?")["automation_id"])
    nxt = datetime.fromisoformat(Q.next_at(a, now=datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)))
    assert (nxt.date().isoformat(), nxt.hour, nxt.weekday()) == ("2026-10-26", 9, 0)


def test_an_automation_that_is_not_a_question_is_no_question(client, on):
    from aughor.automations.models import Automation
    from aughor.automations.store import upsert_automation
    other = upsert_automation(Automation(conn_id=CONN, name="a chain", conditions=[{"kind": "webhook", "config": {}}],
                                         effects=[{"kind": "investigate", "config": {"question": "q"}}]))
    assert client.get(f"/dashboards/questions/{other.id}").status_code == 404


# ── changing and asking ────────────────────────────────────────────────────────────────────

def test_its_rhythm_changes_its_trigger_and_nothing_else(client, on):
    out = Q.keep(connection_id=CONN, question="Week over week?")
    before = get_automation(out["automation_id"])
    r = client.put(f"/dashboards/questions/{out['automation_id']}/rhythm", json={"rhythm": "daily"})
    assert r.status_code == 200 and r.json()["rhythm"] == "daily"
    after = get_automation(out["automation_id"])
    assert after.conditions[0].config == {"cron": "0 9 * * *"} and after.effects == before.effects


def test_asking_now_goes_through_the_same_gates_the_schedule_uses(client, on, monkeypatch):
    out = Q.keep(connection_id=CONN, question="Week over week?")
    seen = {}

    def fake_trigger(automation_id, run_id=None, via="hand"):
        from aughor.automations.models import AutomationRun, EffectOutcome
        seen["id"], seen["via"] = automation_id, via
        return AutomationRun(automation_id=automation_id, outcome="fired",
                             effects=[EffectOutcome(kind="investigate", target="q", status="executed")])
    monkeypatch.setattr("aughor.automations.scheduler.trigger_now", fake_trigger)
    r = client.post(f"/dashboards/questions/{out['automation_id']}/ask")
    assert r.status_code == 200 and r.json()["asked"] is True
    assert seen == {"id": out["automation_id"], "via": "hand"}


def test_a_scheduled_step_files_its_run_under_the_question_s_session(monkeypatch, on):
    from aughor.automations import engine
    from aughor.runners.investigation import InvestigationRun
    out = Q.keep(connection_id=CONN, question="Week over week?")
    a = get_automation(out["automation_id"])
    seen = {}

    def fake_run(req, **kw):
        seen["session"] = req.session_id
        return InvestigationRun("submitted", "")
    monkeypatch.setattr("aughor.runners.run_investigation", fake_run)       # the name the dispatch imports
    engine._dispatch_investigate(a.effects[0], a)
    assert seen["session"] == out["session"]


def test_the_cost_is_said_before_a_question_is_kept(client, on):
    r = client.get("/dashboards/questions/cost", params={"connection_id": CONN})
    assert r.status_code == 200, r.text
    assert {"minutes", "tokens", "usd_floor", "from", "ceiling"} <= set(r.json())


# ── held to the rules when a dashboard is kept ────────────────────────────────────────────

from tests.unit.test_dashboard_routes import Desk, needs_rules  # noqa: E402 — the route tests' own dashboard-to-be


def _with_question(spec: dict, automation: str, key: str = "question1") -> dict:
    s = {**spec, "elements": dict(spec["elements"])}
    section = next(k for k, el in s["elements"].items() if el.get("type") == "Section")
    s["elements"][section] = {**s["elements"][section], "children": [*s["elements"][section]["children"], key]}
    s["elements"][key] = {"type": "Question", "props": {"automation": automation}, "children": []}
    return s


@needs_rules
def test_a_dashboard_keeps_a_question_a_person_kept_on_its_connection(client, on):
    desk = Desk()
    out = Q.keep(connection_id=desk.connection, question="How did sales change week over week, and why?")
    r = client.put(desk.path, params=desk.q, json={"spec": _with_question(desk.spec, out["automation_id"])})
    assert r.status_code == 200, r.text
    from aughor.dashboards import versions
    assert versions.latest(desk.home)["spec"]["elements"]["question1"] == {
        "type": "Question", "props": {"automation": out["automation_id"]}, "children": []}


@needs_rules
def test_a_question_is_refused_while_questions_are_off_and_when_it_names_none(client):
    desk = Desk()
    with flag_overrides({"dashboard.composed": True, "dashboard.questions": True}):
        out = Q.keep(connection_id=desk.connection, question="Week over week?")
        unknown = client.put(desk.path, params=desk.q, json={"spec": _with_question(desk.spec, "ffffffff-0000-0000")})
        assert unknown.status_code != 200 and "names no question that was kept" in unknown.text
        elsewhere = Q.keep(connection_id="another-conn", question="Week over week?")
        other = client.put(desk.path, params=desk.q, json={"spec": _with_question(desk.spec, elsewhere["automation_id"])})
        assert other.status_code != 200 and "another connection" in other.text
    with flag_overrides({"dashboard.composed": True, "dashboard.questions": False}):
        off = client.put(desk.path, params=desk.q, json={"spec": _with_question(desk.spec, out["automation_id"])})
        assert off.status_code != 200 and "questions on a dashboard are off" in off.text


def test_a_model_never_adds_a_question_or_changes_one_and_may_move_one():
    bare = Desk(with_cards=False).spec
    spec = _with_question(bare, "a1b2c3d4")
    assert "A new dashboard holds none" in Q.written(None, spec, new=True)[0]
    assert "The edit adds the question" in Q.written(bare, spec, new=False)[0]
    other = _with_question(bare, "e5f6a7b8")
    assert "changes which question" in Q.written(spec, other, new=False)[0]
    moved = {**spec, "elements": {**spec["elements"],
                                  "question1": {**spec["elements"]["question1"], "props": {"automation": "a1b2c3d4", "w": 8}}}}
    assert Q.written(spec, moved, new=False) == []


@needs_rules
def test_a_question_taken_off_stops_being_asked_and_put_back_is_asked_again(client, on):
    desk = Desk()
    out = Q.keep(connection_id=desk.connection, question="Week over week?")
    aid = out["automation_id"]
    assert client.put(desk.path, params=desk.q, json={"spec": _with_question(desk.spec, aid)}).status_code == 200
    assert get_automation(aid).enabled is True
    assert client.put(desk.path, params=desk.q, json={"spec": desk.spec}).status_code == 200      # taken off
    assert get_automation(aid).enabled is False                                                    # disabled, not deleted
    assert client.put(desk.path, params=desk.q, json={"spec": _with_question(desk.spec, aid)}).status_code == 200
    assert get_automation(aid).enabled is True                                                     # put back


@needs_rules
def test_a_retired_dashboard_s_questions_stop_and_a_paused_one_stays_paused_across_an_edit(client, on):
    from aughor.automations.store import set_automation_enabled
    desk = Desk()
    aid = Q.keep(connection_id=desk.connection, question="Week over week?")["automation_id"]
    with_q = _with_question(desk.spec, aid)
    client.put(desk.path, params=desk.q, json={"spec": with_q})
    set_automation_enabled(aid, False)                                       # a person paused it, in Automations
    root = with_q["root"]
    renamed = {**with_q, "elements": {**with_q["elements"], root: {**with_q["elements"][root],
                                                                   "props": {"title": "Returns, weekly"}}}}
    assert client.put(desk.path, params=desk.q, json={"spec": renamed}).status_code == 200
    assert get_automation(aid).enabled is False                               # an unrelated edit leaves it paused
    set_automation_enabled(aid, True)
    assert client.post(f"{desk.path}/retire", params=desk.q, json={}).status_code == 200
    assert get_automation(aid).enabled is False
