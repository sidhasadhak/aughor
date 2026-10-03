"""Arc AO-2 — Slack in one sitting: a bot card that tells the truth, a key gate that holds.

Measured 2026-10-03 (docs/AGENT_OPS_STUDY_2026-10-03.md §2 A1–A7): the supervisor is
started by nobody and has no heartbeat, so the card read "enabled" while nothing listened;
`POST /slack-bots/supervisor-key` was outside the RBAC policy, so on a licensed deployment
it fell to the write floor and its status GET was open; regenerating the key took every bot
dark within a reconcile. These pin the heartbeat, the liveness the card reads, the policy
entries and the rotation grace.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from aughor.rbac.permissions import Permission
from aughor.rbac.policy import POLICY, required_permission


@pytest.fixture()
def client():
    from aughor.api import app
    return TestClient(app)


@pytest.fixture
def slack_ok(monkeypatch):
    """Stub `auth.test` — verification is a Slack round trip, and no test may make one."""
    monkeypatch.setattr("aughor.slackbots.verify.auth_test",
                        lambda token: (True, {"team_id": "T1", "user_id": "U-BOT",
                                              "app_id": "A1", "team": "acme"}))


@pytest.fixture(autouse=True)
def _leave_the_stores_as_found():
    """The Slack stores accumulate across a session (`test_slackbots` relies on starting
    with no key issued); every key, heartbeat and bot this file makes is removed after."""
    from aughor.slackbots import store
    yield
    for row in store._KEYS.all():
        store._KEYS.delete(row["id"])
    for row in store._RUNTIME.all():
        store._RUNTIME.delete(row["id"])
    for bot in store.list_bots():
        store.delete_bot(bot.id)


# ── AO-2e · who may mint ───────────────────────────────────────────────────────────

def test_minting_the_supervisor_key_is_an_admin_act():
    assert POLICY[("POST", "/slack-bots/supervisor-key")] is Permission.ADMIN_MANAGE_ORG
    assert POLICY[("GET", "/slack-bots/supervisor-key")] is Permission.ADMIN_MANAGE_ORG
    assert required_permission("POST", "/slack-bots/supervisor-key") is Permission.ADMIN_MANAGE_ORG
    # The same bar as the route whose tokens the key unlocks.
    assert required_permission("POST", "/slack-bots/supervisor-key") \
        is required_permission("GET", "/slack-bots/runtime")


def test_the_heartbeat_is_gated_like_the_runtime_read():
    assert POLICY[("POST", "/slack-bots/runtime/heartbeat")] is Permission.ADMIN_MANAGE_ORG


# ── AO-2e · a rotation keeps the old key for a grace window ─────────────────────────

def test_rotating_the_key_keeps_the_previous_one_for_a_grace_window(monkeypatch):
    from aughor.slackbots import store
    old = store.issue_supervisor_key()
    new = store.issue_supervisor_key()
    assert store.supervisor_key_matches(new)
    assert store.supervisor_key_matches(old), "the running supervisor must not go dark mid-rotation"
    status = store.supervisor_key_status()
    assert status["issued"] is True
    assert status["previous_valid_until"], "the window is said, so the operator knows the deadline"
    # Past the window the old key is dead.
    later = datetime.now(timezone.utc) + timedelta(seconds=store.KEY_GRACE_S + 5)
    monkeypatch.setattr(store, "_utcnow", lambda: later)
    assert store.supervisor_key_matches(new)
    assert not store.supervisor_key_matches(old)
    assert store.supervisor_key_status()["previous_valid_until"] == ""


def test_the_status_route_names_the_grace(client):
    client.post("/slack-bots/supervisor-key")
    body = client.post("/slack-bots/supervisor-key").json()
    assert body["previous_valid_for_s"] > 0
    assert "previous_valid_until" in client.get("/slack-bots/supervisor-key").json()


# ── AO-2a · the heartbeat and what the card reads from it ───────────────────────────

def _issue(client) -> str:
    return client.post("/slack-bots/supervisor-key").json()["key"]


def _bot(client, slack_ok, name="salesbot") -> str:
    r = client.post("/slack-bots", json={
        "name": name, "agent_id": "ua_1", "connection_id": "c1",
        "bot_token": "xoxb-x", "app_token": "xapp-x", "signing_secret": "s"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_the_heartbeat_needs_the_supervisors_key(client):
    r = client.post("/slack-bots/runtime/heartbeat", json={
        "supervisor_id": "h:1", "running": [], "failed": [], "reconcile_ms": 30000})
    assert r.status_code == 503, "the heartbeat is the supervisor's word; nobody else may speak it"


def test_a_bot_reads_listening_after_a_heartbeat_and_not_before(client, slack_ok):
    bot_id = _bot(client, slack_ok)
    before = next(b for b in client.get("/slack-bots").json()["bots"] if b["id"] == bot_id)
    assert before["listening"] is None
    assert "npm run dev" in before["liveness_hint"]

    key = _issue(client)
    r = client.post("/slack-bots/runtime/heartbeat",
                    headers={"X-Aughor-Runtime-Key": key},
                    json={"supervisor_id": "host:7:2026-10-03T00:00:00Z",
                          "running": [bot_id], "failed": [], "reconcile_ms": 30000})
    assert r.status_code == 200, r.text
    assert r.json()["recorded"] is True

    after = next(b for b in client.get("/slack-bots").json()["bots"] if b["id"] == bot_id)
    assert after["listening"] is not None
    assert after["listening"]["supervisor_id"] == "host:7:2026-10-03T00:00:00Z"
    assert after["listening"]["since"] and after["listening"]["last_seen_at"]


def test_a_failed_start_is_said_on_the_card(client, slack_ok):
    bot_id = _bot(client, slack_ok, name="failing")
    key = _issue(client)
    client.post("/slack-bots/runtime/heartbeat", headers={"X-Aughor-Runtime-Key": key},
                json={"supervisor_id": "h:1", "running": [],
                      "failed": [{"id": bot_id, "error": "invalid_auth"}], "reconcile_ms": 30000})
    row = next(b for b in client.get("/slack-bots").json()["bots"] if b["id"] == bot_id)
    assert row["listening"] is None
    assert "invalid_auth" in row["liveness_hint"]


def test_a_stale_heartbeat_reads_as_not_listening(client, slack_ok, monkeypatch):
    from aughor.slackbots import store
    bot_id = _bot(client, slack_ok, name="stale")
    key = _issue(client)
    client.post("/slack-bots/runtime/heartbeat", headers={"X-Aughor-Runtime-Key": key},
                json={"supervisor_id": "h:1", "running": [bot_id], "failed": [],
                      "reconcile_ms": 30000})
    # Three reconcile intervals of silence: the process is gone, whatever the last beat said.
    later = datetime.now(timezone.utc) + timedelta(seconds=95)
    monkeypatch.setattr(store, "_utcnow", lambda: later)
    row = next(b for b in client.get("/slack-bots").json()["bots"] if b["id"] == bot_id)
    assert row["listening"] is None
    assert "last heard" in row["liveness_hint"]


def test_a_second_supervisor_does_not_erase_the_first(client, slack_ok):
    a = _bot(client, slack_ok, name="a")
    b = _bot(client, slack_ok, name="b")
    key = _issue(client)
    for sup, bot in (("h1:1", a), ("h2:2", b)):
        client.post("/slack-bots/runtime/heartbeat", headers={"X-Aughor-Runtime-Key": key},
                    json={"supervisor_id": sup, "running": [bot], "failed": [],
                          "reconcile_ms": 30000})
    rows = {x["id"]: x for x in client.get("/slack-bots").json()["bots"]}
    assert rows[a]["listening"]["supervisor_id"] == "h1:1"
    assert rows[b]["listening"]["supervisor_id"] == "h2:2"
