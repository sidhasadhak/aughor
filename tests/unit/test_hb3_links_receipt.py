"""HB-3 — the manifest's links, the outcome column, and the wave's receipt held as a
test (HB-1/HB-2's precedent; the live drive follows the merge):

  Olist's dispatch promise breaks → the framed finding lands in the supply-chain
  group's channel (routed by the MAP, HB-1's route() called in anger) → a ticket is
  proposed, approved, FIRED (a Jira-shaped stub answers OPS-123) → the ticket is
  filed on the promise → its close is recorded with the outcome → the Briefing's
  chain block reports the breach rate before and after, with the chain.

External HTTP is the only stub (fire_action's transport); every store, gate, grant,
route and door in between is the real one, hermetic under conftest.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aughor.automations import probes as P
from aughor.automations.engine import run_automation
from aughor.automations.models import Automation, Effect
from aughor.hub import links as L

_NOW = datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc)
_PROMISE = "promise:order_to_delivery.dispatch"


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


# ── the links store and the outcome column ────────────────────────────────────────

def test_file_list_close_with_snapshots(monkeypatch):
    stamped = {"breached": 120, "reached": 1283, "breach_rate": 0.0935,
               "as_of": "2018-08-29", "connection_id": "olist"}
    monkeypatch.setattr(L, "stamped_measures", lambda ref: dict(stamped))
    row = L.file_link(object_ref=_PROMISE, kind="ticket", ref="OPS-123",
                      title="Dispatch breach — carrier X, south region",
                      source="automation:a1")
    assert row["status"] == "open"
    assert row["metrics_at_filing"]["breach_rate"] == 0.0935

    stamped["breach_rate"] = 0.061   # the world improved before the close
    closed = L.close_link(row["id"], outcome="carrier X re-routed via hub B",
                          number_recovered="34 late lines", closed_by="user:ana")
    assert closed["status"] == "closed"
    assert closed["outcome"].startswith("carrier X")
    assert closed["number_recovered"] == "34 late lines"
    assert closed["metrics_at_filing"]["breach_rate"] == 0.0935
    assert closed["metrics_at_close"]["breach_rate"] == 0.061

    filed = L.list_links(object_ref=_PROMISE)
    assert filed and filed[0]["id"] == row["id"]


def test_links_doors(client, monkeypatch):
    monkeypatch.setattr(L, "stamped_measures", lambda ref: {})
    resp = client.post("/links", json={"object_ref": "process:order_to_delivery",
                                       "kind": "thread", "ref": "C1:171234.5678"})
    assert resp.status_code == 200
    link_id = resp.json()["id"]
    resp = client.post(f"/links/{link_id}/close", json={"outcome": "resolved in thread"})
    assert resp.status_code == 200 and resp.json()["status"] == "closed"
    assert client.post("/links", json={"object_ref": "notasecurable", "kind": "ticket"}
                       ).status_code == 422


# ── the receipt, end to end ───────────────────────────────────────────────────────

def _measured_promise_rows():
    return [{"name": "dispatch", "process": "order_to_delivery", "stage": "shipped",
             "process_owner": "group:supply-chain", "breached": 120, "reached": 1283,
             "breach_rate": 0.0935, "as_of": "2018-08-29", "segment": "late_orders"}]


def _stub_transport(monkeypatch, sent: list):
    """The ONE stub: the outbound HTTP. A Jira-shaped trigger answers with a ticket
    key; everything before and after is real."""
    def fake_fire(trigger, payload):
        sent.append((trigger, payload))
        return SimpleNamespace(status="ok", error=None, id="log1",
                               resource_ref="OPS-123" if trigger.type == "jira" else "",
                               recommendation=payload.recommendation)
    monkeypatch.setattr("aughor.notifications.executor.fire_action", fake_fire)
    return fake_fire


def test_the_receipt_chain(client, monkeypatch):
    from aughor.metastore.models import group_principal
    from aughor.metastore.store import add_grant
    from aughor.notifications.models import ActionTrigger
    from aughor.notifications.store import save_trigger
    from aughor.org.context import current_org_id
    from aughor.rbac.groups import upsert_group

    org = current_org_id()

    # HB-1's half, real: the supply-chain group with a channel, subscribed to the
    # promise's process by a level grant.
    save_trigger(ActionTrigger(id="tr_ops", name="#ops (supply chain)", type="webhook",
                               url="https://hooks.example.test/ops"))
    save_trigger(ActionTrigger(id="tr_jira", name="Ops Jira", type="jira",
                               url="https://jira.example.test/rest/api/2/issue",
                               project="OPS"))
    upsert_group(org, "supply-chain", "Supply chain", channel_trigger_id="tr_ops")
    add_grant(group_principal("supply-chain"), "process:order_to_delivery",
              "subscribe", org_id=org)

    # The measured breach, stamped (ON-9's shape); the transport stub.
    monkeypatch.setattr(P, "_promise_rows", lambda a, c: (_measured_promise_rows(), ""))
    monkeypatch.setattr(L, "stamped_measures",
                        lambda ref: {"breached": 120, "reached": 1283,
                                     "breach_rate": 0.0935, "as_of": "2018-08-29",
                                     "connection_id": "olist"})
    sent: list = []
    _stub_transport(monkeypatch, sent)

    # Leg 1+2 — the breach fires the trigger; the finding (here, the framed sentence a
    # deep step would bind) lands wherever the MAP routes the promise: the group's
    # channel, no channel named anywhere in the chain.
    auto = Automation(
        id="hb3receipt", conn_id="olist", name="Dispatch promise watch",
        conditions=[{"kind": "promise_breached",
                     "config": {"process": "order_to_delivery"}}],
        effects=[Effect(kind="notify", alias="land", config={
            "route_about": {"$from": "trigger.about"},
            "about": {"$from": "trigger.about"},
            "message": "Dispatch promise broken on 9.35% of lines — carrier X, south "
                       "region carries the concentration. Receipt attached."})])
    run = run_automation(auto, now=_NOW, persist=False, via="schedule")
    assert run.outcome == "fired", run.reason
    land = run.effects[0]
    assert land.status == "executed", land.message
    assert "group:supply-chain" in land.message
    assert sent and sent[0][0].id == "tr_ops"          # landed in the group's channel

    # ...and the landing was FILED on the promise (everything lands on the map).
    filed = L.list_links(object_ref=_PROMISE)
    assert filed and filed[0]["kind"] == "webhook"

    # Leg 3 — the ticket is PROPOSED (require_approval parks it), approved, FIRED.
    ticket = Automation(
        id="hb3ticket", conn_id="olist", name="Dispatch breach ticket",
        conditions=[{"kind": "promise_breached",
                     "config": {"process": "order_to_delivery"}}],
        effects=[Effect(kind="notify", alias="ticket", config={
            "trigger_id": "tr_jira", "require_approval": True, "about": _PROMISE,
            "message": "Open a ticket: dispatch promise broken (9.35%), carrier X."})])
    run2 = run_automation(ticket, now=_NOW, persist=True, via="schedule")
    assert run2.outcome == "paused"
    step = run2.effects[0]
    assert step.status == "approval_required"
    proposal_id = (step.data or {}).get("proposal_id")
    assert proposal_id, "the park staged no proposal"

    from aughor.actions.inbox import accept_proposal
    result, _grant = accept_proposal(proposal_id, actor="user:ana")
    assert result.status == "executed", result.message
    assert "OPS-123" in result.message

    # Leg 4 — the ticket is filed on the promise, with the created key.
    tickets = [ln for ln in L.list_links(object_ref=_PROMISE) if ln["kind"] == "ticket"]
    assert tickets and tickets[0]["ref"] == "OPS-123"

    # Leg 5 — its close is recorded, outcome column filled.
    closed = client.post(f"/links/{tickets[0]['id']}/close",
                         json={"outcome": "carrier X re-routed",
                               "number_recovered": "34 late lines"}).json()
    assert closed["status"] == "closed"

    # Leg 6 — the Briefing's chain block: breach rate before and after, with the chain.
    from aughor.knowledge.promise_chains import promise_chain_findings
    findings = promise_chain_findings("olist")
    assert findings, "the chain block reported nothing"
    text = findings[0]["finding"]
    assert "OPS-123" in text and "carrier X re-routed" in text
    assert "unchanged at 9.35%" in text     # frozen data: honest before == after
    assert findings[0]["domain"] == "Promises"
