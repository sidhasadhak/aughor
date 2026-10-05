"""Phase 7 of the 2027 study, P7-4 — the method interface (`aughor/record/methods.py`): a forecaster,
estimator or simulator registered with its backtest and run as a foreign MCP tool through the one door.

What these hold: a method without a backtest, with a built-in name, of an unknown kind or with an
adapter that would run inside the process is refused; a registered method is on the ladder's interface
and projects in the ladder's shape through `mcpservers.call`; a call the door refused or that answered
badly projects nothing and says the door's word; a prediction under it carries the method and its tier;
a withdrawn method is unknown again.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from aughor.record import claims as C
from aughor.record import methods as M
from aughor.record import scenario as S
from aughor.routers import ledger as R


def _method(name: str, **kw) -> M.Method:
    base = dict(name=name, kind="forecaster", backtest=M.Backtest(n=40, metric="orders", mape=0.08, coverage_stated=0.8, coverage_observed=0.78,
                                                                   measured_on=["acme-backtest-2026-09"]),
                adapter=M.Adapter(kind="mcp", server_id="acme-mcp", tool="forecast"), inputs=["metric", "horizon_days"])
    base.update(kw)
    return M.Method(**base)


def test_a_method_is_registered_with_its_backtest_or_refused():
    with pytest.raises(M.MethodRefused, match="built-in"):
        M.register(_method("history"), by="user:ana")
    with pytest.raises(M.MethodRefused, match="kind is one of"):
        M.register(_method("x-" + uuid.uuid4().hex[:4], kind="oracle"), by="user:ana")
    with pytest.raises(M.MethodRefused, match="nothing runs inside the process"):
        M.register(_method("x-" + uuid.uuid4().hex[:4], adapter=M.Adapter(kind="python", server_id="", tool="")), by="user:ana")
    with pytest.raises(M.MethodRefused, match="carries its backtest"):
        M.register(_method("x-" + uuid.uuid4().hex[:4], backtest=M.Backtest(n=0)), by="user:ana")
    with pytest.raises(M.MethodRefused, match="states an error"):
        M.register(_method("x-" + uuid.uuid4().hex[:4], backtest=M.Backtest(n=5, measured_on=["d"])), by="user:ana")
    name = "acme-forecast-" + uuid.uuid4().hex[:4]
    m = M.register(_method(name), by="user:ana")
    assert m.id and m.active and m.declared_by == "user:ana" and m.registered_at and M.get_method(name).name == name
    assert name in {x.name for x in M.list_methods()}
    door = R.read_methods()
    assert door["builtin"] == list(S.METHODS) and any(x["name"] == name for x in door["registered"])


def test_a_registered_method_projects_through_the_one_door_in_the_ladders_shape(monkeypatch):
    name = "acme-forecast-" + uuid.uuid4().hex[:4]
    M.register(_method(name), by="user:ana")
    calls: list = []

    def fake_call(server_id, tool, arguments):
        calls.append((server_id, tool, arguments))
        return SimpleNamespace(status="executed", message="", text=json.dumps({"value": 1200, "low": 1100, "high": 1300, "coverage": 0.8,
                                                                               "unit": "", "must_say": ["seasonal model, 2 years of history"]}))
    monkeypatch.setattr("aughor.mcpservers.call.call", fake_call)
    p = S.project(name, metric="orders", horizon_days=30, connection_id="c1", run_sql=lambda s: None)
    assert p.method == name and p.value == 1200 and (p.low, p.high) == (1100, 1300) and p.coverage == 0.8 and p.tier == "mined"
    assert calls == [("acme-mcp", "forecast", {"metric": "orders", "horizon_days": 30, "connection_id": "c1"})]
    assert p.backtest["n"] == 40 and p.must_say[0].startswith(f"forecaster {name}, registered by user:ana; backtest on orders: n=40, mape 0.08")
    assert "nothing of it runs inside the platform" in p.must_say[1] and p.must_say[-1] == "seasonal model, 2 years of history"
    pid = S.predict(metric="orders", projection=p, settles_on="2026-12-01", author=f"service:{name}", connection_id="c1", direction="up")
    pred = C.get(pid)
    assert pred.extra["method"] == name and pred.tier == "mined" and pred.extra["backtest"]["measured_on"] == ["acme-backtest-2026-09"]
    # the door's word, never a zero
    monkeypatch.setattr("aughor.mcpservers.call.call", lambda s, t, a: SimpleNamespace(status="refused", message="not on the allowlist", text=""))
    refused = S.project(name, metric="orders")
    assert refused.value is None and "was refused: not on the allowlist" in refused.note
    monkeypatch.setattr("aughor.mcpservers.call.call", lambda s, t, a: SimpleNamespace(status="executed", message="", text="not json"))
    assert "did not answer in the ladder's shape" in S.project(name, metric="orders").note
    monkeypatch.setattr("aughor.mcpservers.call.call", lambda s, t, a: SimpleNamespace(status="executed", message="", text=json.dumps({"low": 1})))
    assert "answered without a value" in S.project(name, metric="orders").note
    with pytest.raises(C.ClaimRefused, match="projected nothing"):
        S.predict(metric="orders", projection=refused, settles_on="2026-12-01", author="x")
    M.withdraw(name, by="user:ana")
    with pytest.raises(ValueError, match="no method named"):
        S.project(name, metric="orders")
    assert M.get_method(name) is None and M.get_method(name, active_only=False).active is False


def test_the_door_registers_and_withdraws():
    from fastapi import HTTPException
    name = "door-" + uuid.uuid4().hex[:4]
    out = R.register_method(R.MethodIn(name=name, kind="estimator", backtest=R.BacktestIn(n=12, mae=3.5, measured_on=["thelook"]),
                                       adapter=R.AdapterIn(server_id="s", tool="estimate")), principal=None)
    assert out["name"] == name and out["declared_by"] == "unidentified"
    with pytest.raises(HTTPException) as e:
        R.register_method(R.MethodIn(name="bad", kind="estimator", backtest=R.BacktestIn(n=0), adapter=R.AdapterIn(server_id="s", tool="t")), principal=None)
    assert e.value.status_code == 422
    assert R.withdraw_method(name, principal=None)["active"] is False
