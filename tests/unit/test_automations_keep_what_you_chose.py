"""Spotlight: "finishing a draft in the editor drops its timezone and its run-as agent" — and,
measured while fixing it, every canvas save reset a stored timezone to UTC and un-exposed a chain
from MCP: the request model had no `timezone`, and the canvas's full-record save never carried
`exposed_as_tool`, which its own door (`POST …/exposed`) flips. Cockpit (CT-5's survey): "a
proposal's approval card … is not drawn again when the chat is reopened" — the live frame was
never stored; the proposals a turn's run staged are found by its trace.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aughor.api import app

client = TestClient(app)

BODY = {
    "conn_id": "conn-keep",
    "name": "Morning revenue",
    "conditions": [{"kind": "schedule", "config": {"cron": "0 9 * * *"}}],
    "effects": [{"kind": "notify", "config": {"trigger_id": "trig-1"}}],
}


@pytest.fixture
def engine_on(monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "automations.engine")


def test_a_draft_finished_in_the_editor_keeps_its_clock_and_its_agent(engine_on):
    from aughor.custom_agents.store import create_agent
    agent = create_agent("Revenue watcher", purpose="revenue")
    made = client.post("/automations", json={**BODY, "timezone": "Europe/Berlin", "agent_id": agent.id})
    assert made.status_code == 200, made.text
    assert (made.json()["timezone"], made.json()["agent_id"]) == ("Europe/Berlin", agent.id)
    refused = client.post("/automations", json={**BODY, "agent_id": "ag_nobody"})
    assert refused.status_code == 422 and "no agent" in refused.json()["detail"]


def test_a_canvas_save_keeps_what_other_doors_set(engine_on):
    aid = client.post("/automations", json={**BODY, "timezone": "Asia/Kolkata"}).json()["id"]
    assert client.post(f"/automations/{aid}/exposed?exposed=true").status_code == 200
    # The canvas's save — the whole record it draws, which carries neither field.
    saved = client.put(f"/automations/{aid}", json={**BODY, "name": "Renamed on the canvas"})
    assert saved.status_code == 200, saved.text
    row = client.get(f"/automations/{aid}").json()
    assert (row["name"], row["timezone"], row["exposed_as_tool"]) == \
        ("Renamed on the canvas", "Asia/Kolkata", True)
    # Sent explicitly, they change — the door is the request, not the omission.
    client.put(f"/automations/{aid}", json={**BODY, "timezone": "", "exposed_as_tool": False})
    row = client.get(f"/automations/{aid}").json()
    assert (row["timezone"], row["exposed_as_tool"]) == ("", False)


def test_a_reopened_chat_draws_the_approval_cards_its_turns_staged():
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.db.history import save_chat_turn
    from aughor.telemetry import bind_trace

    with bind_trace("trace-cards-1"):
        save_chat_turn("draft me a returns cockpit", "conn-keep", "Staged a cockpit draft.", "",
                       session_id="sess-cards-1")
    staged = stage_proposal(StagedProposal(kind="cockpit_draft", connection_id="conn-keep",
                                           action_id="cockpit:new", params={}, trace_id="trace-cards-1",
                                           proposer="cockpit"))
    with bind_trace("trace-cards-2"):
        save_chat_turn("and revenue last week?", "conn-keep", "Revenue was flat.", "",
                       session_id="sess-cards-1")

    msgs = client.get("/chat-sessions/sess-cards-1/messages").json()
    cards = [[p["data"]["proposal_id"] for p in m["parts"] if p["type"] == "data-proposal_staged"]
             for m in msgs if m["role"] == "assistant"]
    assert cards == [[staged.id], []]                 # on the turn that staged it, and only there
