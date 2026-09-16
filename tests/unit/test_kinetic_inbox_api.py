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
from aughor.actions import inbox
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
    import aughor.actions.executor as ex
    calls: list = []
    monkeypatch.setattr(ex, "default_dispatch", lambda a, p, s="": calls.append((a.id, p)))
    return calls


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


def test_propose_stages_to_the_inbox(monkeypatch):
    """The producer wire: /propose persists valid proposals so they become durable + acceptable.
    (Both former gates — the proposer flag K4 and the inbox flag A4 — are permanent now:
    Wave 2 hardwired automations.proposals, Wave 5 hardwired kinetic.agent_actions.)"""
    class _G:
        kinetic_actions = {"refund": _action()}
    monkeypatch.setattr("aughor.routers.kinetic._resolve_graph", lambda c, s: _G())

    from aughor.actions.propose import Proposal
    monkeypatch.setattr("aughor.actions.propose.propose_actions",
                        lambda graph, ctx, scope="", provider=None, **kw: [
                            Proposal("refund", "proposed", {"order_id": "8821"}, "because")])

    body = client.post("/kinetic-actions/propose",
                       params={"connection_id": "conn-prod"},
                       json={"context": "order 8821 looks like a duplicate charge"}).json()
    prop = body["proposals"][0]
    assert prop["ok"] is True and "inbox_id" in prop
    # the staged proposal is retrievable and acceptable
    assert inbox.get_proposal(prop["inbox_id"]).action_id == "refund"


# ── the withdrawal door (ON-4) ───────────────────────────────────────────────────

def test_annotate_then_withdraw_over_http_and_a_second_withdrawal_is_404():
    """One edit, unsaid. Until this door the only way back was the connection-wide purge."""
    from aughor.actions import overlay as OV
    OV.purge_connections(["conn-withdraw-t"])
    try:
        params = {"connection_id": "conn-withdraw-t"}
        written = client.post("/kinetic-actions/annotate", params=params, json={
            "table": "orders", "column": "status", "key_column": "order_id", "row_key": "8821",
            "body": "known test order"}).json()
        listed = client.get("/kinetic-actions/annotations", params=params).json()["edits"]
        assert [e["id"] for e in listed] == [written["id"]]

        gone = client.delete(f"/kinetic-actions/annotations/{written['id']}", params=params)
        assert gone.status_code == 200, gone.text
        assert gone.json()["target"] == "orders.status#order_id=8821"
        assert client.get("/kinetic-actions/annotations", params=params).json()["edits"] == []

        again = client.delete(f"/kinetic-actions/annotations/{written['id']}", params=params)
        assert again.status_code == 404 and "already be withdrawn" in again.json()["detail"]
    finally:
        OV.purge_connections(["conn-withdraw-t"])


def test_a_withdrawal_does_not_reach_another_connection_over_http():
    from aughor.actions import overlay as OV
    OV.purge_connections(["conn-withdraw-a", "conn-withdraw-b"])
    try:
        mine = client.post("/kinetic-actions/annotate", params={"connection_id": "conn-withdraw-a"},
                           json={"table": "orders", "body": "mine"}).json()
        wrong = client.delete(f"/kinetic-actions/annotations/{mine['id']}",
                              params={"connection_id": "conn-withdraw-b"})
        assert wrong.status_code == 404
        assert client.get("/kinetic-actions/annotations",
                          params={"connection_id": "conn-withdraw-a"}).json()["edits"] != []
    finally:
        OV.purge_connections(["conn-withdraw-a", "conn-withdraw-b"])


def test_get_one_proposal_and_a_missing_one_is_404(flag_on):
    """SP-9 — the approval card's read: chat and Attention hold only an id."""
    p = inbox.stage_proposal(inbox.StagedProposal(
        connection_id="conn-api", action_id="refund", params={"order_id": "9"}))
    body = client.get(f"/kinetic-actions/inbox/{p.id}").json()
    assert body["proposal"]["id"] == p.id
    assert body["proposal"]["params"] == {"order_id": "9"}
    assert client.get("/kinetic-actions/inbox/nope-never").status_code == 404


def test_accept_carries_fills_to_the_inbox(flag_on):
    """SP-9 — the card's open-choice answers ride the accept body. The refusal for a
    fill that names a non-hole comes back as the executor's own 4xx, proposal intact."""
    import aughor.automations.store  # noqa: F401 — registers the holes door
    p = inbox.stage_proposal(inbox.StagedProposal(
        kind="automation_draft", connection_id="conn-api", action_id="automation:x",
        params={"conn_id": "conn-api", "name": "x",
                "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
                "effects": [{"kind": "slack_post",
                             "config": {"bot_id": "b", "channel": "",
                                        "message": "m"}}]}))
    r = client.post(f"/kinetic-actions/inbox/{p.id}/accept",
                    json={"actor": "tester", "fills": {"1.message": "edited"}})
    assert r.status_code == 422
    assert "not an open choice" in str(r.json())
    assert inbox.get_proposal(p.id).pending

    r = client.post(f"/kinetic-actions/inbox/{p.id}/accept",
                    json={"actor": "tester", "fills": {"1.channel": "#ops"}})
    assert r.status_code == 200, r.text
    assert inbox.get_proposal(p.id).params["effects"][0]["config"]["channel"] == "#ops"


def test_supersede_over_http_is_resolve_once(flag_on):
    """SP-11 — the editor's finish door: resolves a pending draft as replaced, and a
    second call (or one against settled work) reports False instead of erring."""
    p = inbox.stage_proposal(inbox.StagedProposal(
        kind="automation_draft", connection_id="conn-api", action_id="automation:e",
        params={"name": "e"}))
    r = client.post(f"/kinetic-actions/inbox/{p.id}/supersede",
                    json={"actor": "editor", "note": "finished in the editor as xyz"})
    assert r.status_code == 200 and r.json()["superseded"] is True
    row = inbox.get_proposal(p.id)
    assert row.status == "superseded" and "xyz" in row.status_message
    r = client.post(f"/kinetic-actions/inbox/{p.id}/supersede", json={"actor": "editor"})
    assert r.json()["superseded"] is False
