"""Automations API (Wave A) — the flag gate and the CRUD contract.

Two things worth locking at the HTTP boundary: with ``automations.engine`` off the whole surface
404s (so the default install is byte-identical), and a malformed condition/effect is rejected with
a 422 at CREATE — never stored, so a broken automation cannot sit in the DB looking schedulable.

``GET /automations/{id}/runs`` gets its own test because it is the endpoint the subsystem exists
for: the monitor API has no equivalent, since ``monitor_alerts`` records only the ticks that fired.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.automations.models import AutomationRun
from aughor.automations.store import append_run

client = TestClient(app)

BODY = {
    "conn_id": "conn-api",
    "name": "Refund watch",
    "conditions": [{"kind": "schedule", "config": {"cron": "0 8 * * 1"}}],
    "effects": [{"kind": "notify", "config": {"trigger_id": "trig-1"}}],
}


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.engine")


def test_every_route_404s_with_the_flag_off(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    assert client.get("/automations").status_code == 404
    assert client.post("/automations", json=BODY).status_code == 404
    assert client.get("/automations/whatever").status_code == 404
    assert client.get("/automations/whatever/runs").status_code == 404


def test_create_list_get_delete_round_trip(flag_on):
    created = client.post("/automations", json=BODY)
    assert created.status_code == 200
    aid = created.json()["id"]
    assert created.json()["name"] == "Refund watch"

    listed = client.get("/automations", params={"conn_id": "conn-api"})
    assert aid in [a["id"] for a in listed.json()["automations"]]

    assert client.get(f"/automations/{aid}").json()["conn_id"] == "conn-api"
    assert client.delete(f"/automations/{aid}").status_code == 200
    assert client.get(f"/automations/{aid}").status_code == 404


@pytest.mark.parametrize("patch", [
    {"conditions": [{"kind": "schedule", "config": {}}]},                    # cron missing
    {"effects": [{"kind": "kinetic_action", "config": {"params": {}}}]},     # action_id missing
    {"conditions": []},                                                      # none at all
])
def test_a_malformed_automation_is_rejected_at_create_and_never_stored(flag_on, patch):
    body = {**BODY, **patch}
    resp = client.post("/automations", json=body)
    assert resp.status_code == 422
    # Nothing was persisted by the rejected call.
    listed = client.get("/automations", params={"conn_id": "conn-api"}).json()["automations"]
    assert all(a["name"] != "Refund watch" or a["conditions"] for a in listed)


def test_pause_and_enable_toggles(flag_on):
    aid = client.post("/automations", json={**BODY, "conn_id": "conn-api-toggle"}).json()["id"]

    paused = client.post(f"/automations/{aid}/pause", json={"until": "2027-01-01T00:00:00Z"})
    assert paused.json()["paused_until"] == "2027-01-01T00:00:00Z"
    assert client.post(f"/automations/{aid}/pause", json={"until": None}).json()["paused_until"] is None

    assert client.post(f"/automations/{aid}/enabled", params={"enabled": False}).json()["enabled"] is False


def test_runs_endpoint_returns_the_ticks_that_did_nothing(flag_on):
    """The reason this API exists — a quiet tick is data, not absence."""
    aid = client.post("/automations", json={**BODY, "conn_id": "conn-api-runs"}).json()["id"]
    append_run(AutomationRun(automation_id=aid, conn_id="conn-api-runs",
                             outcome="gated", reason="muted until 2027-01-01T00:00:00Z"))
    append_run(AutomationRun(automation_id=aid, conn_id="conn-api-runs",
                             outcome="not_fired", reason="metric(mon-7): no alert"))

    runs = client.get(f"/automations/{aid}/runs").json()["runs"]
    assert {r["outcome"] for r in runs} == {"gated", "not_fired"}
    assert any("muted until" in r["reason"] for r in runs)


def test_run_now_returns_the_reason_a_gated_automation_did_nothing(flag_on):
    """An operator asking 'why isn't this firing?' gets the reason, not silence."""
    aid = client.post("/automations", json={
        **BODY, "conn_id": "conn-api-run", "enabled": False}).json()["id"]
    resp = client.post(f"/automations/{aid}/run")
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "gated"
    assert resp.json()["reason"] == "disabled"


def test_run_now_on_an_unknown_automation_is_404(flag_on):
    assert client.post("/automations/nope/run").status_code == 404
