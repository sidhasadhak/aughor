"""The arc's close-out, C6 — spend attributed to a mission, and L5: the agent that chooses among declared
actions toward a mission inside its budget (`aughor/record/mission.mission_spend`, `aughor/actions/authority.
evaluate_l5` / `grant_l5`, `aughor/actions/autonomy.py`).

What these hold: the mission report counts the metered cost of the runs its inquiries ran — tokens from
their receipts, a dollar floor from the session log with the unpriced calls said — and compares it to the
budget only in the budget's own unit; L5 is earned on a long L4 record (graduated, twenty verified
executions, no failed verification, an undo declared) inside a mission whose ceiling sets it, booked by a
person on a receipt, and lost on a demotion; the L5 agent chooses among the declared actions at L5 by the
measured effect past decisions had on the objective (method 4, Outcome entries only), runs the chosen one
with the parameters the mission's owner wrote through the governed pipeline, books the decision with its
expectation, acts once per review period, says why when nothing is choosable, and is held — never forced —
when no standing grant covers the written parameters.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from aughor.actions import authority as A
from aughor.actions import autonomy as AU
from aughor.actions.executor import execute_kinetic_action
from aughor.kernel.ledger import Ledger
from aughor.ontology.models import ActionParameter, KineticAction, Undo, Verification
from aughor.record import decisions as D
from aughor.record import inquiry as I
from aughor.record import mission as M

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
SPEC = {"metric_label": "gross margin", "metric_sql": "SUM(margin)", "metric_table": "shop.orders",
        "date_column": "shop.orders.created_at", "window_days": 30}


@pytest.fixture(autouse=True)
def _own_departures(tmp_path, monkeypatch):
    monkeypatch.setenv("AUGHOR_DEPARTURES_DB", str(tmp_path / "departures.db"))
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _mission(conn, **kw) -> M.Mission:
    base = dict(name="Protect gross margin " + uuid.uuid4().hex[:4],
                objective=M.Objective(metric="gross margin", direction="up", target=0.41, unit="%", spec=dict(SPEC)),
                scope=M.Scope(domain="EU", connections=[conn]), owner="user:ana",
                budget=M.Budget(interruptions_per_week=3), review=M.Review(cadence="monthly"), state="active")
    base.update(kw)
    return M.Mission(**base)


def _warehouse(default: float):
    def run_sql_for(connection_id, **kw):
        return lambda sql: (["value"], [[default]], None)
    return run_sql_for


# ── spend ──────────────────────────────────────────────────────────────────────────────────

def test_the_report_counts_what_the_missions_runs_cost_from_their_receipts_and_a_dollar_floor(monkeypatch):
    conn = _conn()
    m = M.write_mission(_mission(conn, budget=M.Budget(spend_per_month=50.0, spend_unit="USD")), by="user:ana")
    q = I.open_inquiry(question="Why did gross margin fall?", connection_id=conn, opened_by=f"mission:{m.id}", now=NOW - timedelta(days=3))
    for rid, tokens in (("run-a", 12_000), ("run-b", 8_000)):
        Ledger.default().artifact_write("ada_report", f"ada:{conn}:{rid}", {"headline": "x", "cost": {"total_tokens": tokens, "llm_calls": 4, "query_count": 6}}, conn_id=conn)
        q.runs.append(I.RunNote(run=rid, verdict="answered", why="done", at=(NOW - timedelta(days=2)).isoformat()))
    q.runs.append(I.RunNote(run="run-old", verdict="answered", why="before the period", at=(NOW - timedelta(days=90)).isoformat()))
    q.runs.append(I.RunNote(run="run-noreceipt", verdict="tool_failed", why="x", at=(NOW - timedelta(days=1)).isoformat()))
    I._book(q)
    monkeypatch.setattr("aughor.obs.session_log.recent_sessions",
                        lambda **kw: [{"investigation_id": "run-a", "cost_usd": 0.31, "unpriced_calls": 0, "llm_calls": 4},
                                      {"investigation_id": "run-b", "cost_usd": 0.20, "unpriced_calls": 1, "llm_calls": 4},
                                      {"investigation_id": "elsewhere", "cost_usd": 9.0, "unpriced_calls": 0, "llm_calls": 1}])
    report = M.compose_report(M.latest(m.key), run_sql_for=_warehouse(0.4), now=NOW)
    spend = report["cost"]["spend"]
    assert spend["runs"] == 3 and spend["runs_with_receipt"] == 2 and spend["tokens"] == 20_000 and spend["llm_calls"] == 8 and spend["queries"] == 12
    assert spend["amount"] == 0.31 and spend["unit"] == "USD" and spend["priced_runs"] == 1 and spend["unpriced_calls"] == 1
    assert spend["against_budget"] == "0.31 of 50 USD a month, as a floor" and "3 runs" in spend["note"] and "1 model calls unpriced" in spend["note"]
    # a budget in another unit is said, not compared; no runs is said
    other = M.write_mission(_mission(conn, budget=M.Budget(spend_per_month=200.0, spend_unit="credits")), by="user:ana")
    s2 = M.compose_report(other, run_sql_for=_warehouse(0.4), now=NOW)["cost"]["spend"]
    assert s2["runs"] == 0 and s2["amount"] is None and s2["unit"] == "credits" and s2["note"].startswith("no run was spent")
    assert "stated in credits" in s2["against_budget"]
    assert report["autonomy"]["acted"] == [] and "ran no action" in report["autonomy"]["note"]


# ── L5 ─────────────────────────────────────────────────────────────────────────────────────

def _refund(**kw) -> KineticAction:
    base = dict(id="refund", kind="side_effect", params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
                risk="high", reversibility="compensable",
                verification=Verification(sql="SELECT 1 FROM refunds WHERE order_id = '{order_id}'", expects="rows"),
                undo=Undo(action_id="reverse_refund", window_hours=72, params={"order_id": "{order_id}"}))
    base.update(kw)
    return KineticAction(**base)


def _recorder():
    calls: list = []

    def d(action, params, scope=""):
        calls.append((action.id, dict(params)))
        return {"dispatched": True}
    d.calls = calls
    return d


def _passing_warehouse(monkeypatch):
    def run_sql_for(connection_id, **kw):
        return lambda sql: (["one"], [[1]], None)
    monkeypatch.setattr("aughor.db.measure.run_sql_for", run_sql_for)


def _earn_l4(action, conn, monkeypatch, *, runs: int):
    _passing_warehouse(monkeypatch)
    for i in range(runs):
        r = execute_kinetic_action(action, {"order_id": str(1000 + i)}, actor="user:ana", scope=conn, dispatch=_recorder(), approved=True)
        assert r.verification["status"] == "passed"
    did = D.book_decision(D.Decision(question=f"refund order {uuid.uuid4().hex[:4]}?", chosen="approve", decided_by="user:ana", actions=[action.id],
                                     connection_id=conn, source=D.Source(kind="approval", ref=uuid.uuid4().hex[:8])),
                          expectation=D.Expectation(metric="gross margin", direction="up", low=0.5, high=1.5, unit="%"))
    D.book_outcome(D.Outcome(of=did, measured_on="2026-10-20", actual=0.41, baseline=0.40, verdict="as_expected", against_expectation="inside",
                             effect=D.Effect(value=1.0, method="history")))
    return A.graduate(action, conn, by="user:ana")


def _past_cases(action_id: str, conn: str, effects: list[float]):
    for e in effects:
        did = D.book_decision(D.Decision(question=f"run {action_id} {uuid.uuid4().hex[:4]}?", chosen="yes", decided_by="user:ana", actions=[action_id],
                                         connection_id=conn, source=D.Source(kind="approval", ref=uuid.uuid4().hex[:8])),
                              expectation=D.Expectation(metric="gross margin", direction="up", low=0.0, high=2.0, unit="%"))
        D.book_outcome(D.Outcome(of=did, measured_on="2026-10-21", actual=0.41, baseline=0.40, verdict="as_expected" if e > 0 else "worse",
                                 against_expectation="inside", effect=D.Effect(value=e, method="history")))


def test_l5_is_earned_on_a_long_l4_record_inside_a_mission_booked_by_a_person_and_lost_on_a_demotion(monkeypatch):
    conn = _conn()
    action = _refund()
    check = A.evaluate_l5(action, conn)
    assert not check["can_grant"] and "L4 is the floor of L5" in check["reasons"][0] and "0 of 20 verified executions" in check["reasons"][1]
    assert "no active mission on this scope sets this action's ceiling at L5" in check["reasons"]
    _earn_l4(action, conn, monkeypatch, runs=20)
    assert A.level_for(action, conn)["level"] == 4
    check = A.evaluate_l5(action, conn)
    assert check["reasons"] == ["no active mission on this scope sets this action's ceiling at L5"]
    with pytest.raises(ValueError, match="not earned"):
        A.grant_l5(action, conn, by="user:ana")
    m = M.write_mission(_mission(conn, budget=M.Budget(authority_ceiling={"refund": 5})), by="user:ana")
    low = M.write_mission(_mission(conn, name="Lower " + uuid.uuid4().hex[:4], budget=M.Budget(authority_ceiling={"refund": 3})), by="user:ana")
    assert "an active mission on this scope caps it at L3" in A.evaluate_l5(action, conn)["reasons"]
    M.set_state(low.id, "paused", by="user:ana", why="test")
    check = A.evaluate_l5(action, conn)
    assert check["can_grant"] and check["missions"] == [m.id]
    with pytest.raises(ValueError, match="does not set this action's ceiling"):
        A.grant_l5(action, conn, by="user:ana", mission="not-a-mission")
    receipt = A.grant_l5(action, conn, by="user:ana")
    assert receipt["level"] == 5 and receipt["mission"] == m.id and receipt["id"]
    lv = A.level_for(action, conn)
    assert lv["level"] == 5 and lv["label"] == "autonomous" and lv["l5"] == receipt["id"] and lv["ceiling"] == 5 and "L5 on receipt" in lv["why"]
    assert any("L5 is granted only on an L5 receipt" in n for n in lv["notes"])
    events = Ledger.default().events(kind="authority.graduated", conn_id=conn)
    assert any(e["payload"].get("level") == 5 and e["payload"]["mission"] == m.id for e in events)
    # without a mission's ceiling the same record stays at L4; an irreversible action never passes L3
    assert A.level_for(action, conn, ceiling=4)["level"] == 4
    assert A.level_for(_refund(undo=None, reversibility="irreversible"), conn)["ceiling"] == 3
    # a demotion takes L5 away like every other level
    A.demote("refund", conn, why="a drill", by="user:ana")
    after = A.level_for(action, conn)
    assert after["level"] == 3 and "demoted on" in after["why"] and "L4 is the floor" in A.evaluate_l5(action, conn)["reasons"][0]


def test_the_l5_agent_chooses_by_the_measured_effect_runs_once_a_period_with_the_written_parameters_and_says_why_not(monkeypatch):
    conn = _conn()
    refund, discount = _refund(), _refund(id="discount", undo=Undo(action_id="undiscount", window_hours=24, params={"order_id": "{order_id}"}))
    _earn_l4(refund, conn, monkeypatch, runs=20)
    _earn_l4(discount, conn, monkeypatch, runs=20)
    m = M.write_mission(_mission(conn, budget=M.Budget(authority_ceiling={"*": 5}),
                                 extra={"autonomy": {"params": {"refund": {"order_id": "77"}, "discount": {"order_id": "78"}}}}), by="user:ana")
    A.grant_l5(refund, conn, by="user:ana")
    A.grant_l5(discount, conn, by="user:ana")
    actions = [refund, discount, KineticAction(id="note", kind="annotate", params=[])]
    # no measured effect yet: nothing is choosable, and each reason is said
    none = AU.act(m, actions, now=NOW, dispatch=_recorder())
    assert none["acted"] is False and "no declared action is choosable" in none["why"]
    by_id = {c["action_id"]: c for c in none["candidates"]}
    assert by_id["note"]["level"] < 5 and any("not L5" in r for r in by_id["note"]["reasons"])
    assert any("past decision" in r for r in by_id["refund"]["reasons"]) and by_id["refund"]["projection"]["n"] == 1
    # past decisions: refunds moved the margin up by ~1.5, discounts moved it down — refund is chosen
    _past_cases("refund", conn, [1.4, 1.6, 1.5])
    _past_cases("discount", conn, [-0.5, -0.7, -0.6])
    choice = AU.choose(M.latest(m.key), actions, now=NOW)
    assert choice["chosen"] == "refund" and "largest among 1 choosable" in choice["why"]
    disc = next(c for c in choice["candidates"] if c["action_id"] == "discount")
    assert disc["choosable"] is False and any("wrong way" in r for r in disc["reasons"]) and disc["toward"] < 0
    rec = _recorder()
    out = AU.act(M.latest(m.key), actions, now=NOW, dispatch=rec)
    assert out["acted"] is True and out["action_id"] == "refund" and out["status"] == "executed" and out["params"] == {"order_id": "77"}
    assert rec.calls == [("refund", {"order_id": "77"})]
    d = D.get_decision(out["decision"])
    assert d.source.kind == "autonomy" and d.decided_by == "agent:autonomy" and d.objective == m.id and d.actions == ["refund"] and d.chosen == "refund"
    assert {o.id for o in d.options} == {"refund", "discount", "note"} and d.expectation_claim and d.extra["level"] == 5
    from aughor.record import claims as C
    pred = C.get(d.expectation_claim)
    assert pred.kind == "prediction" and pred.statement.metric == "gross margin" and pred.extra["low"] is not None
    entry = Ledger.default().artifact_by_id(out["entry"])["payload"]
    assert entry["actor"] == "agent:autonomy" and entry["status"] == "executed"
    after = M.latest(m.key)
    assert after.extra["autonomy"]["last_acted_on"] == NOW.date().isoformat() and after.extra["autonomy"]["acted"][-1]["decision"] == out["decision"]
    assert Ledger.default().events(kind="action.autonomous", conn_id=conn)[0]["payload"]["acted"] is True
    # one autonomous action per review period
    again = AU.act(after, actions, now=NOW + timedelta(days=3), dispatch=rec)
    assert again["acted"] is False and "already acted on" in again["why"] and len(rec.calls) == 1
    # the next report lists what it did, and the cadence runs the agent's turn after the report
    report = M.compose_report(after, run_sql_for=_warehouse(0.4), now=NOW + timedelta(days=1))
    assert report["autonomy"]["l5_actions"] == ["*"] and report["autonomy"]["acted"][0]["action"] == "refund"
    assert report["autonomy"]["acted"][0]["outcome"] == "not yet reviewed"
    from aughor.record import mission as MM
    assert "act_for_mission" in __import__("inspect").getsource(MM.report_due_missions)
    # a mission with no L5 ceiling has nothing to choose; a paused mission does not act
    plain = M.write_mission(_mission(conn, name="Plain " + uuid.uuid4().hex[:4]), by="user:ana")
    assert AU.act_for_mission(plain, now=NOW)["why"] == "the mission sets no action's ceiling at L5"
    paused = M.set_state(after.id, "paused", by="user:ana", why="test")
    assert "only while active" in AU.act(paused, actions, now=NOW + timedelta(days=40))["why"]


def test_the_l5_agent_is_held_at_the_gate_without_a_standing_grant_and_runs_under_one(monkeypatch):
    conn = _conn()
    refund = _refund()
    _earn_l4(refund, conn, monkeypatch, runs=20)
    m = M.write_mission(_mission(conn, budget=M.Budget(authority_ceiling={"refund": 5}), extra={"autonomy": {"params": {"refund": {"order_id": "90"}}}}),
                        by="user:ana")
    A.grant_l5(refund, conn, by="user:ana")
    _past_cases("refund", conn, [1.0, 1.2, 0.8])
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "1")                        # the gate is on
    rec = _recorder()
    held = AU.act(M.latest(m.key), [refund], now=NOW, dispatch=rec)
    assert held["acted"] is False and held["status"] == "approval_required" and "held at the approval gate" in held["why"]
    assert rec.calls == [] and D.get_decision(held["decision"]) is not None     # the decision is booked, the act is not
    assert "last_acted_on" not in M.latest(m.key).extra["autonomy"]            # a held attempt does not spend the period
    # a person widens a policy grant for the written parameters: the next turn runs under it
    g = A.widen(refund, conn, target_value="90", by="user:ana", expires_days=30, max_uses=3)
    out = AU.act(M.latest(m.key), [refund], now=NOW, dispatch=rec)
    assert out["acted"] is True and rec.calls == [("refund", {"order_id": "90"})]
    assert Ledger.default().artifact_by_id(out["entry"])["payload"]["grant_id"] == g.id
    # the doors
    from aughor.routers import authority as RA
    from aughor.routers import record as RR
    monkeypatch.setattr(RA, "_actions", lambda c, s: {"refund": refund})
    assert RA.authority_l5_check("refund", connection_id=conn)["can_grant"] is True
    assert RA.authority_table(connection_id=conn)["l5_n"] == A.L5_N
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology", lambda c, s: type("G", (), {"declared_actions": lambda self: [refund]})())
    turn = RR.act_record_mission(m.id)
    assert turn["acted"] is False and "already acted on" in turn["why"]
