"""Wave A4 — the inbox + grants HTTP surface.

Locks the flag gate (every route 404s when `automations.proposals` is off, so the default install is
byte-identical) and the accept → execute → resolve-once contract end to end over HTTP: a re-accept of
an already-resolved proposal is a 409, not a second dispatch.

The declared action is resolved from a patched ontology; the executor's dispatch is patched to a
recorder so the HTTP round trip exercises the real accept path without an external side effect.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.kinetic import inbox
from aughor.ontology.models import ActionParameter, KineticAction

client = TestClient(app)


def _action() -> KineticAction:
    return KineticAction(
        id="refund", kind="side_effect",
        params=[ActionParameter(name="order_id", data_type="VARCHAR", required=True)],
        submission_criteria=[], side_effects=[], risk="low")   # low ⇒ no approval needed


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n == "automations.proposals")


@pytest.fixture
def wired(monkeypatch):
    class _G:
        kinetic_actions = {"refund": _action()}
    monkeypatch.setattr("aughor.ontology.store.load_latest_ontology",
                        lambda cid, schema=None: _G())
    import aughor.kinetic.executor as ex
    calls: list = []
    monkeypatch.setattr(ex, "default_dispatch", lambda a, p, s="": calls.append((a.id, p)))
    return calls


def test_every_route_404s_with_the_flag_off(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    assert client.get("/kinetic-actions/inbox").status_code == 404
    assert client.post("/kinetic-actions/inbox/x/accept", json={}).status_code == 404
    assert client.post("/kinetic-actions/inbox/x/reject", json={}).status_code == 404
    assert client.get("/kinetic-actions/grants").status_code == 404
    assert client.post("/kinetic-actions/grants/x/revoke").status_code == 404


def test_list_inbox_returns_staged_proposals(flag_on):
    inbox.stage_proposal(inbox.StagedProposal(
        connection_id="conn-api", action_id="refund", params={"order_id": "1"}))
    body = client.get("/kinetic-actions/inbox", params={"connection_id": "conn-api"}).json()
    assert any(p["action_id"] == "refund" for p in body["proposals"])


def test_accept_executes_then_a_reaccept_is_409(flag_on, wired):
    p = inbox.stage_proposal(inbox.StagedProposal(
        connection_id="conn-api-acc", action_id="refund", params={"order_id": "8821"}))

    first = client.post(f"/kinetic-actions/inbox/{p.id}/accept", json={"actor": "human"})
    assert first.status_code == 200
    assert first.json()["status"] == "executed"

    second = client.post(f"/kinetic-actions/inbox/{p.id}/accept", json={"actor": "human"})
    assert second.status_code == 409
    assert len(wired) == 1, "the re-accept dispatched a second side effect"


def test_reject_over_http(flag_on):
    p = inbox.stage_proposal(inbox.StagedProposal(
        connection_id="conn-api-rej", action_id="refund", params={"order_id": "1"}))
    r = client.post(f"/kinetic-actions/inbox/{p.id}/reject", json={"actor": "human"})
    assert r.json() == {"rejected": True}
    assert inbox.get_proposal(p.id).status == "rejected"


def test_accept_can_mint_a_grant_then_list_and_revoke_it(flag_on, wired):
    p = inbox.stage_proposal(inbox.StagedProposal(
        connection_id="conn-api-grant", action_id="refund", params={"order_id": "8821"}))
    acc = client.post(f"/kinetic-actions/inbox/{p.id}/accept",
                      json={"actor": "human", "mint_grant": True}).json()
    grant_id = acc["minted_grant"]
    assert grant_id

    listed = client.get("/kinetic-actions/grants", params={"connection_id": "conn-api-grant"}).json()
    assert any(g["id"] == grant_id and g["target_value"] == "8821" for g in listed["grants"])

    assert client.post(f"/kinetic-actions/grants/{grant_id}/revoke").json() == {"revoked": grant_id}
    assert client.post(f"/kinetic-actions/grants/{grant_id}/revoke").status_code == 404


def test_propose_stages_to_the_inbox_when_the_flag_is_on(monkeypatch):
    """The producer wire: /propose persists valid proposals so they become durable + acceptable.
    Needs both the proposer flag (K4) and the inbox flag (A4)."""
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled",
                        lambda n: n in ("automations.proposals", "kinetic.agent_actions"))
    class _G:
        kinetic_actions = {"refund": _action()}
    monkeypatch.setattr("aughor.routers.kinetic._resolve_graph", lambda c, s: _G())

    from aughor.kinetic.propose import Proposal
    monkeypatch.setattr("aughor.kinetic.propose.propose_actions",
                        lambda graph, ctx, scope="", provider=None: [
                            Proposal("refund", "proposed", {"order_id": "8821"}, "because")])

    body = client.post("/kinetic-actions/propose",
                       params={"connection_id": "conn-prod"},
                       json={"context": "order 8821 looks like a duplicate charge"}).json()
    prop = body["proposals"][0]
    assert prop["ok"] is True and "inbox_id" in prop
    # the staged proposal is retrievable and acceptable
    assert inbox.get_proposal(prop["inbox_id"]).action_id == "refund"
