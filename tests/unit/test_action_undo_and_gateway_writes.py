"""The arc's close-out, C5 — the undo fired as an executable compensating action, and the integration
and MCP write paths booked as Action entries beside the declared actions' (`aughor/actions/authority.py`).

What these hold: the declared undo of an execution runs through the same governed pipeline, with its
parameters filled from the execution's by the declared templates, books its own entry naming the one it
compensates, and the original is restated as undone and counted; an undo is refused — with why — outside
its window, a second time, on an entry that was not executed, or when it names an action the connection
does not declare; an undo that could not run or whose verification failed demotes the original action;
every write the integration gateway or the MCP door performs is on the record with its status, saying it
declares no verification read and no undo; the doors serve both.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from aughor.actions import authority as A
from aughor.actions.executor import execute_kinetic_action
from aughor.kernel.ledger import Ledger
from aughor.ontology.models import ActionParameter, KineticAction, Undo, Verification


def _conn():
    return "conn-" + uuid.uuid4().hex[:6]


def _refund(**kw) -> KineticAction:
    base = dict(id="refund", kind="side_effect", params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
                risk="high", reversibility="compensable",
                verification=Verification(sql="SELECT 1 FROM refunds WHERE order_id = '{order_id}'", expects="rows"),
                undo=Undo(action_id="reverse_refund", window_hours=72, params={"order_id": "{order_id}", "reason": "undo"}))
    base.update(kw)
    return KineticAction(**base)


def _reverse() -> KineticAction:
    return KineticAction(id="reverse_refund", kind="side_effect", risk="high", reversibility="irreversible",
                         params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True),
                                 ActionParameter(name="reason", data_type="VARCHAR", required=False)],
                         verification=Verification(sql="SELECT 1 FROM reversals WHERE order_id = '{order_id}'", expects="rows"))


def _recorder():
    calls: list = []

    def d(action, params, scope=""):
        calls.append((action.id, dict(params)))
        return {"dispatched": True}
    d.calls = calls
    return d


@pytest.fixture(autouse=True)
def _approval_off(monkeypatch):
    monkeypatch.setenv("AUGHOR_ACTION_APPROVAL", "0")


def _warehouse(rows_for: dict):
    def run_sql_for(connection_id, **kw):
        def run_sql(sql):
            for key, rows in rows_for.items():
                if key in sql:
                    return (["one"], rows, None)
            return (["one"], [], None)
        return run_sql
    return run_sql_for


def test_the_declared_undo_is_fired_through_the_governed_pipeline_and_the_original_is_restated_undone(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"refunds": [[1]], "reversals": [[1]]}))
    rec = _recorder()
    r = execute_kinetic_action(_refund(), {"order_id": "8821"}, actor="user:ana", scope=conn, dispatch=rec, approved=True)
    assert r.ok and r.action_entry
    actions = {"refund": _refund(), "reverse_refund": _reverse()}
    out = A.undo(r.action_entry, by="user:bo", actions=actions, scope=conn, dispatch=rec)
    assert out["undone"] is True and out["status"] == "executed" and out["undo_action"] == "reverse_refund"
    assert out["params"] == {"order_id": "8821", "reason": "undo"} and rec.calls[-1] == ("reverse_refund", {"order_id": "8821", "reason": "undo"})
    assert out["verification"]["status"] == "passed" and out["window"]["open"] is True and "demoted" not in out
    undo_entry = Ledger.default().artifact_by_id(out["undo_entry"])
    assert undo_entry["payload"]["compensates"] == r.action_entry and undo_entry["payload"]["action_id"] == "reverse_refund"
    assert any(e["relation"] == "compensates" and e["ref"] == r.action_entry for e in Ledger.default().receipt_by_id(out["undo_entry"])["lineage"])
    original = Ledger.default().artifact_latest(Ledger.default().artifact_by_id(r.action_entry)["natural_key"])
    assert original["payload"]["undone"] is True and original["payload"]["undone_by"] == out["undo_entry"] and original["payload"]["undo_by"] == "user:bo"
    assert original["version"] == 2 and original["payload"]["status"] == "executed"
    rec_refund = A.record("refund", conn)
    assert rec_refund["executions"] == 1 and rec_refund["undone"] == 1 and rec_refund["verified"] == 1
    assert A.record("reverse_refund", conn)["executions"] == 1
    assert A._latest(A.DEMOTION_KIND, "refund", conn) is None
    events = Ledger.default().events(kind="action.undone", conn_id=conn)
    assert events and events[0]["payload"]["undone"] is True and events[0]["payload"]["undo_entry"] == out["undo_entry"]
    # a second undo is refused, and says by what it was undone
    again = A.undo(r.action_entry, by="user:bo", actions=actions, scope=conn, dispatch=rec)
    assert again["undone"] is False and again["status"] == "refused" and "already undone" in again["why"]


def test_an_undo_is_refused_outside_its_window_on_an_undeclared_action_or_another_scope(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"refunds": [[1]]}))
    rec = _recorder()
    r = execute_kinetic_action(_refund(), {"order_id": "1"}, actor="user:ana", scope=conn, dispatch=rec, approved=True)
    actions = {"refund": _refund(), "reverse_refund": _reverse()}
    late = datetime.now(timezone.utc) + timedelta(hours=73)
    closed = A.undo(r.action_entry, by="user:bo", actions=actions, scope=conn, dispatch=rec, now=late)
    assert closed["status"] == "refused" and "72-hour undo window closed" in closed["why"] and closed["window"]["open"] is False
    missing = A.undo(r.action_entry, by="user:bo", actions={"refund": _refund()}, scope=conn, dispatch=rec)
    assert missing["status"] == "refused" and "does not declare" in missing["why"]
    other = A.undo(r.action_entry, by="user:bo", actions=actions, scope=_conn(), dispatch=rec)
    assert other["status"] == "refused" and "another scope" in other["why"]
    assert A.undo("no-such-entry", by="user:bo", actions=actions, scope=conn)["status"] == "refused"
    assert A.undo_window({"undo": {"window_hours": 0}, "at": "2026-01-01T00:00:00+00:00"})["open"] is True
    assert A.undo_window({"undo": None})["open"] is False
    assert len(rec.calls) == 1                                           # none of the refusals dispatched anything
    # the door says 409 with the reason
    from fastapi import HTTPException
    from aughor.routers import authority as R
    monkeypatch.setattr(R, "_actions", lambda c, s: actions)
    with pytest.raises(HTTPException) as e:
        R.authority_undo("refund", r.action_entry, R.UndoBody(connection_id=_conn()), principal=None)
    assert e.value.status_code == 409 and e.value.detail["why"].startswith("the entry belongs")


def test_an_undo_that_fails_its_verification_or_cannot_run_demotes_the_original_action(monkeypatch):
    conn = _conn()
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"refunds": [[1]], "reversals": []}))   # the reversal is not visible
    rec = _recorder()
    r = execute_kinetic_action(_refund(), {"order_id": "77"}, actor="user:ana", scope=conn, dispatch=rec, approved=True)
    actions = {"refund": _refund(), "reverse_refund": _reverse()}
    out = A.undo(r.action_entry, by="user:bo", actions=actions, scope=conn, dispatch=rec)
    assert out["undone"] is False and out["status"] == "executed" and out["verification"]["status"] == "failed" and out["demoted"] is True
    demotion = A._latest(A.DEMOTION_KIND, "refund", conn)
    assert demotion is not None and "did not undo it" in demotion["why"] and demotion["evidence"]["undo_entry"] == out["undo_entry"]
    assert A.level_for(_refund(), conn)["level"] == 3 and "demoted on" in A.level_for(_refund(), conn)["why"]
    original = Ledger.default().artifact_latest(Ledger.default().artifact_by_id(r.action_entry)["natural_key"])
    assert original["payload"]["undone"] is False and original["payload"]["undone_status"] == "executed"
    # an undo whose templates name a parameter the execution never had cannot run: demoted too, nothing dispatched
    conn2 = _conn()
    monkeypatch.setattr("aughor.db.measure.run_sql_for", _warehouse({"refunds": [[1]], "reversals": [[1]]}))
    bad = _refund(undo=Undo(action_id="reverse_refund", window_hours=0, params={"order_id": "{order_id}", "reason": "{ticket}"}))
    r2 = execute_kinetic_action(bad, {"order_id": "5"}, actor="user:ana", scope=conn2, dispatch=rec, approved=True)
    before = len(rec.calls)
    out2 = A.undo(r2.action_entry, by="user:bo", actions={"refund": bad, "reverse_refund": _reverse()}, scope=conn2, dispatch=rec)
    assert out2["undone"] is False and out2["status"] == "invalid_params" and "ticket" in out2["message"] and len(rec.calls) == before
    assert A._latest(A.DEMOTION_KIND, "refund", conn2) is not None


def test_integration_and_mcp_writes_are_on_the_record_beside_the_declared_actions(monkeypatch):
    from aughor.integrations import call as callmod
    from aughor.integrations import store as istore
    from aughor.integrations.models import Connection
    gid = "ic_" + uuid.uuid4().hex[:6]
    istore.save_connection(Connection(id=gid, provider="slack", account="Acme", scopes="chat:write channels:read",
                                      access_token="at-slack", status="active", user_id="u_amit"))
    monkeypatch.setattr(callmod, "_request", lambda method, url, *, headers, query, body: (200, {"ok": True, "ts": "1.2", "channel": "C1"}))
    monkeypatch.setattr(callmod, "_fresh_token", lambda cid: "at-live")
    res = callmod.call_operation(gid, "slack.chat.postMessage", {"channel": "#x", "text": "hi"}, actor="automation:a1", approved=True)
    assert res.status == "executed"
    mine = [w for w in A.writes(door="integration") if w["scope"] == f"grant:{gid}"]
    assert len(mine) == 1 and mine[0]["action_id"] == "integration.slack.slack.chat.postMessage" and mine[0]["status"] == "executed"
    assert mine[0]["actor"] == "automation:a1" and mine[0]["under"] == "human accept" and mine[0]["kind"] == "write"
    assert mine[0]["verification"]["status"] == "not_declared" and "declares no verification read" in mine[0]["verification"]["why"]
    assert mine[0]["reversibility"] == "undeclared" and mine[0]["undo"] is None and mine[0]["params"]["text"] == "hi"
    assert mine[0]["outcome"]["http_status"] == 200 and "ts" in mine[0]["outcome"]["keys"]
    # a read performs no write: nothing booked
    istore.save_connection(Connection(id=gid + "g", provider="google", scopes="openid email https://www.googleapis.com/auth/gmail.readonly",
                                      access_token="at", status="active"))
    monkeypatch.setattr(callmod, "_request", lambda method, url, *, headers, query, body: (200, {"messages": []}))
    assert callmod.call_operation(gid + "g", "gmail.messages.list").status == "executed"
    assert not [w for w in A.writes() if w["scope"] == f"grant:{gid}g"]
    # the MCP door: a granted write is booked with its status, a read is not
    from types import SimpleNamespace
    from aughor.mcpservers import call as door
    server = SimpleNamespace(id="mcps_" + uuid.uuid4().hex[:6], name="Fixture", transport="stdio", url="")
    monkeypatch.setattr(door, "_through_the_seam", lambda s, t, a, ec, ob, *, writes: door.McpCallResult("executed", "", text="done", writes=writes))
    door._send(server, "delete_everything", {"target": "x"}, writes=True)
    door._send(server, "read_the_weather", {"city": "Lisbon"}, writes=False)
    mcp = [w for w in A.writes(door="mcp") if w["scope"] == f"server:{server.id}"]
    assert len(mcp) == 1 and mcp[0]["action_id"] == f"mcp.{server.id}.delete_everything" and mcp[0]["under"] == f"grant:{server.id}::delete_everything"
    assert mcp[0]["status"] == "executed" and mcp[0]["params"] == {"target": "x"}
    monkeypatch.setattr(door, "_through_the_seam", lambda s, t, a, ec, ob, *, writes: door.McpCallResult("uncertain", "the pipe closed", writes=True))
    door._send(server, "delete_everything", {"target": "y"}, writes=True)
    assert [w["status"] for w in A.writes(door="mcp") if w["scope"] == f"server:{server.id}"][0] == "uncertain"
    from aughor.routers import authority as R
    assert R.authority_writes(door="mcp")["count"] >= 2 and "not graduated" in R.authority_writes()["note"]
    from aughor.kernel.events import CATALOGUE
    assert "action.undone" in CATALOGUE
