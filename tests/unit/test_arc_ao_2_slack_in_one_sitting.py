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


# ── AO-2c · agent mode by default, and one-way ──────────────────────────────────────

def test_a_new_manifest_is_in_agent_mode_with_its_events():
    from aughor.slackbots.manifest import AGENT_EVENTS, BOT_EVENTS, render_manifest
    m = render_manifest(name="x")
    assert "agent_view" in m["features"]
    # The first live `apps.manifest.create` (2026-10-03) was refused: "invalid_manifest:
    # Remove assistant_view feature". Slack's reference: new apps can only use agent_view,
    # and agent_view requires agent_description (max 300) — an empty object is refused too.
    assert "assistant_view" not in m["features"]
    assert m["features"]["agent_view"] == {"agent_description": "Ask about your data."}
    long = render_manifest(name="x", description="d" * 400)
    assert len(long["features"]["agent_view"]["agent_description"]) == 300
    assert "assistant:write" in m["oauth_config"]["scopes"]["bot"]
    events = m["settings"]["event_subscriptions"]["bot_events"]
    assert events == list(BOT_EVENTS) + list(AGENT_EVENTS), \
        "the README told a person to add these by hand; the manifest must carry them"
    assert "redirect_urls" not in m["oauth_config"], "no public origin, no redirect"
    legacy = render_manifest(name="x", agent_view=False)
    assert "agent_view" not in legacy["features"] and "assistant_view" not in legacy["features"]
    assert legacy["settings"]["event_subscriptions"]["bot_events"] == list(BOT_EVENTS)


def test_the_manifest_route_defaults_to_agent_mode_and_carries_the_callback(client, monkeypatch):
    body = client.get("/slack-bots/manifest").json()
    assert body["agent_view"] is True
    assert "agent_view" in body["manifest"]["features"]
    monkeypatch.setenv("AUGHOR_PUBLIC_API_URL", "https://aughor.example.com")
    body = client.get("/slack-bots/manifest").json()
    assert body["manifest"]["oauth_config"]["redirect_urls"] == \
        ["https://aughor.example.com/slack-bots/oauth/callback"]
    monkeypatch.setenv("AUGHOR_PUBLIC_API_URL", "http://aughor.example.com")
    assert "redirect_urls" not in client.get("/slack-bots/manifest").json()["manifest"]["oauth_config"], \
        "Slack refuses a non-HTTPS redirect; better none than a wrong one"


def test_agent_mode_is_one_way(client, slack_ok):
    r = client.post("/slack-bots", json={
        "name": "agentic", "bot_token": "xoxb-x", "app_token": "xapp-x", "signing_secret": "s",
        "agent_view": True})
    assert r.status_code == 200, r.text
    bot = r.json()
    body = {"name": "agentic", "enabled": True, "agent_id": "", "connection_id": "",
            "agent_view": False}
    r = client.patch(f"/slack-bots/{bot['id']}", json=body)
    assert r.status_code == 409
    assert "one-way" in r.json()["detail"]
    assert client.patch(f"/slack-bots/{bot['id']}", json={**body, "agent_view": True}).status_code == 200


# ── AO-2d · one configuration token ────────────────────────────────────────────────

def _created(app_id="A123"):
    return True, {"ok": True, "app_id": app_id,
                  "credentials": {"client_id": "111.222", "client_secret": "cs-secret",
                                  "verification_token": "v", "signing_secret": "sig-secret"},
                  "oauth_authorize_url": "https://slack.com/oauth/v2/authorize?x"}


def test_creating_the_app_from_one_token_stores_what_slack_returned(client, monkeypatch):
    from aughor.slackbots import apps
    seen: dict = {}

    def _create(token, manifest):
        seen["token"] = token
        seen["manifest"] = manifest
        return _created()

    monkeypatch.setattr(apps, "create_app", _create)
    r = client.post("/slack-bots/apps", json={"config_token": "xoxe.xoxp-cfg", "name": "Look Bot",
                                              "agent_id": "ua_1", "connection_id": "c1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["token"] == "xoxe.xoxp-cfg"
    assert seen["manifest"]["display_information"]["name"] == "Look Bot"
    assert "agent_view" in seen["manifest"]["features"]
    bot = body["bot"]
    assert bot["slack_app_id"] == "A123" and bot["agent_id"] == "ua_1"
    assert bot["enabled"] is False and "not installed" in bot["disabled_reason"]
    assert bot["signing_secret"].startswith("sig-") and "secret" not in bot["signing_secret"], "masked"
    assert bot["client_secret"] != "cs-secret", "a secret never leaves the server in clear"
    assert body["needs"] == ["bot_token", "app_token"]
    assert body["oauth_available"] is False and body["install_url"] == ""
    assert "AUGHOR_PUBLIC_API_URL" in body["steps"][0]
    assert "no API" in body["steps"][1]
    # The configuration token was used once and is nowhere on the record.
    from aughor.slackbots import store
    raw = store.get_bot_decrypted(bot["id"])
    assert raw.client_secret == "cs-secret" and raw.signing_secret == "sig-secret"
    assert "xoxe" not in raw.model_dump_json()


def test_a_refused_manifest_is_slacks_own_words(client, monkeypatch):
    from aughor.slackbots import apps
    monkeypatch.setattr(apps, "create_app", lambda t, m: (False, {
        "error": "invalid_manifest: features.agent_view: unknown field"}))
    r = client.post("/slack-bots/apps", json={"config_token": "t", "name": "x"})
    assert r.status_code == 422 and "unknown field" in r.json()["detail"]


def test_the_install_is_a_button_only_with_a_public_https_origin(client, monkeypatch):
    from aughor.slackbots import apps
    monkeypatch.setattr(apps, "create_app", lambda t, m: _created())
    bot = client.post("/slack-bots/apps", json={"config_token": "t", "name": "x"}).json()["bot"]
    assert client.get(f"/slack-bots/{bot['id']}/install", follow_redirects=False).status_code == 409
    monkeypatch.setenv("AUGHOR_PUBLIC_API_URL", "https://aughor.example.com")
    r = client.get(f"/slack-bots/{bot['id']}/install", follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = r.headers["location"]
    assert loc.startswith("https://slack.com/oauth/v2/authorize?")
    assert "client_id=111.222" in loc and "assistant%3Awrite" in loc and "state=" in loc


def test_the_callback_turns_the_code_into_the_bot_token_and_waits_for_the_app_token(
        client, monkeypatch, slack_ok):
    from aughor.slackbots import apps, store
    monkeypatch.setattr(apps, "create_app", lambda t, m: _created())
    monkeypatch.setenv("AUGHOR_PUBLIC_API_URL", "https://aughor.example.com")
    bot = client.post("/slack-bots/apps", json={"config_token": "t", "name": "x"}).json()["bot"]
    state = client.get(f"/slack-bots/{bot['id']}/install", follow_redirects=False) \
        .headers["location"].split("state=")[1].split("&")[0]
    from urllib.parse import unquote
    state = unquote(state)
    monkeypatch.setattr(apps, "exchange_code", lambda cid, cs, code, uri: (True, {
        "ok": True, "access_token": "xoxb-installed", "team": {"id": "T9"}, "bot_user_id": "U9"}))
    r = client.get(f"/slack-bots/oauth/callback?code=c0de&state={state}", follow_redirects=False)
    assert r.status_code == 200, r.text            # no AUGHOR_WEB_URL → JSON, not a redirect
    assert r.json()["outcome"] == "installed"
    raw = store.get_bot_decrypted(bot["id"])
    assert raw.bot_token == "xoxb-installed"
    assert raw.enabled is False and "app-level token" in raw.disabled_reason
    # The last paste: the app-level token. Then it is live.
    monkeypatch.setattr("aughor.routers.slackbots._verify", lambda b: b)
    r = client.patch(f"/slack-bots/{bot['id']}", json={
        "name": "x", "enabled": False, "agent_id": "", "connection_id": "",
        "agent_view": True, "app_token": "xapp-pasted"})
    assert r.status_code == 200, r.text
    after = store.get_bot_decrypted(bot["id"])
    assert after.enabled is True and after.disabled_reason == "" and after.app_token == "xapp-pasted"
    assert after.client_id == "111.222", "the app's identity survives the edit"


def test_a_forged_state_is_refused(client):
    assert client.get("/slack-bots/oauth/callback?code=c&state=sb_whatever").status_code == 400


# ── AO-2b · the managed supervisor ──────────────────────────────────────────────────

class _Proc:
    def __init__(self, pid=4242):
        self.pid, self._code, self.terminated = pid, None, False

    def poll(self):
        return self._code

    def exit(self, code):
        self._code = code

    def terminate(self):
        self.terminated = True
        self._code = -15

    def wait(self, timeout=None):
        return self._code


def _tmp_supervisor(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "node_modules").mkdir()
    return tmp_path


def test_off_by_default_spawns_nothing(tmp_path):
    from aughor.slackbots.managed import ManagedSupervisor, managed_status
    spawned: list = []
    host = ManagedSupervisor(api_url="http://127.0.0.1:8000", runtime_key="k",
                             cwd=_tmp_supervisor(tmp_path), spawn=lambda *a: spawned.append(a) or _Proc(),
                             flag_enabled=lambda name: False)
    assert host.start() == "off" and spawned == []
    assert host.status().state == "off" and host.status().managed is False
    assert managed_status()["flag"] is False and managed_status()["state"] == "off"


def test_on_it_spawns_the_supervisor_with_its_own_key_and_the_api_url(tmp_path, monkeypatch):
    from aughor.slackbots import managed
    spawned: list = []
    monkeypatch.setattr(managed.ManagedSupervisor, "_npx", staticmethod(lambda: "/usr/bin/npx"))
    host = managed.ManagedSupervisor(api_url="http://127.0.0.1:8010", runtime_key="managed-key",
                                     cwd=_tmp_supervisor(tmp_path),
                                     spawn=lambda cmd, cwd, env: spawned.append((cmd, cwd, env)) or _Proc(),
                                     flag_enabled=lambda name: True)
    assert host.start() == "running"
    cmd, cwd, env = spawned[0]
    assert cmd == ["/usr/bin/npx", "tsx", "src/index.ts"] and cwd == tmp_path
    assert env["AUGHOR_API_URL"] == "http://127.0.0.1:8010"
    assert env["AUGHOR_RUNTIME_KEY"] == "managed-key" and env["AUGHOR_MANAGED_BY_API"] == "1"
    assert "SLACK_BOT_TOKEN" not in env
    s = host.status()
    assert s.state == "running" and s.pid == 4242 and s.managed and s.flag
    host.stop()
    assert spawned[0] and host.status().state == "stopped"


def test_a_missing_precondition_is_said_not_tried(tmp_path, monkeypatch):
    from aughor.slackbots import managed
    monkeypatch.setattr(managed.ManagedSupervisor, "_npx", staticmethod(lambda: ""))
    (tmp_path / "package.json").write_text("{}")          # no node_modules, no npx
    spawned: list = []
    host = managed.ManagedSupervisor(api_url="u", runtime_key="k", cwd=tmp_path,
                                     spawn=lambda *a: spawned.append(a) or _Proc(),
                                     flag_enabled=lambda name: True)
    assert host.start() == "failed" and spawned == []
    s = host.status()
    assert "node_modules" in s.last_error and "npx" in s.last_error
    assert len(s.preconditions) == 2


def test_an_exited_child_is_restarted_after_a_backoff(tmp_path, monkeypatch):
    import time as _t
    from aughor.slackbots import managed
    monkeypatch.setattr(managed, "_WATCH_S", 0.01)
    monkeypatch.setattr(managed, "BACKOFF_S", (0.01,))
    monkeypatch.setattr(managed.ManagedSupervisor, "_npx", staticmethod(lambda: "/usr/bin/npx"))
    procs: list = []

    def _spawn(cmd, cwd, env):
        p = _Proc(pid=100 + len(procs))
        procs.append(p)
        return p

    host = managed.ManagedSupervisor(api_url="u", runtime_key="k", cwd=_tmp_supervisor(tmp_path),
                                     spawn=_spawn, flag_enabled=lambda name: True)
    assert host.start() == "running"
    procs[0].exit(1)
    deadline = _t.time() + 3
    while len(procs) < 2 and _t.time() < deadline:
        _t.sleep(0.02)
    host.stop()
    assert len(procs) >= 2, "the child was not restarted"
    s = host.status()
    assert s.restarts >= 1 and s.last_exit_code == 1


def test_the_managed_child_writes_its_own_log_and_the_status_names_it(tmp_path, monkeypatch):
    """Receipt 2026-10-03: the child's output went to /dev/null while the cap message said
    'check the supervisor's own log'. Now the log exists, is appended across starts with a
    dated line, and the status says where it is."""
    import os
    import sys
    from aughor.slackbots import managed
    monkeypatch.setattr(managed.ManagedSupervisor, "_npx", staticmethod(lambda: "/usr/bin/npx"))
    log = tmp_path / "logs" / "supervisor.log"
    host = managed.ManagedSupervisor(api_url="u", runtime_key="k", cwd=_tmp_supervisor(tmp_path),
                                     log_path=log, spawn=lambda *a: _Proc(),
                                     flag_enabled=lambda name: True)
    # The REAL spawn, with a child that only prints: its words land in the log, under a header.
    proc = host._real_spawn([sys.executable, "-c", "print('child says hi')"], tmp_path, dict(os.environ))
    proc.wait(timeout=30)
    proc = host._real_spawn([sys.executable, "-c", "import sys; print('again', file=sys.stderr)"],
                            tmp_path, dict(os.environ))
    proc.wait(timeout=30)
    text = log.read_text(encoding="utf-8")
    assert text.count("--- supervisor started") == 2 and "child says hi" in text and "again" in text
    assert host.start() == "running"
    assert host.status().log_path == str(log)
    host.stop()


def test_the_status_carries_the_freshest_heartbeat_even_with_no_bot(slack_ok):
    """On a fresh install there is no bot card to read liveness from; the supervisor
    status is the one place that says whether the process the API runs is LISTENING."""
    from aughor.slackbots import managed, store
    assert managed.managed_status()["heartbeat"] is None
    store.record_heartbeat("host:1", [], [], 30000)
    store.record_heartbeat("host:2", ["sb_1"], [{"id": "sb_2", "error": "bad token"}], 30000)
    hb = managed.managed_status()["heartbeat"]
    assert hb["supervisor_id"] == "host:2" and hb["running"] == 1 and hb["failed"] == 1
    assert hb["fresh"] is True and hb["last_seen_at"] and hb["since"]


def test_the_managed_key_opens_the_runtime_route_and_a_regenerate_does_not_touch_it(client, slack_ok):
    from aughor.slackbots import store
    managed_key = store.issue_managed_key()
    assert store.supervisor_key_matches(managed_key)
    client.post("/slack-bots/supervisor-key")
    client.post("/slack-bots/supervisor-key")
    assert store.supervisor_key_matches(managed_key), "a person's rotation must not darken the managed child"
    assert client.get("/slack-bots/runtime", headers={"X-Aughor-Runtime-Key": managed_key}).status_code == 200


def test_the_supervisor_routes_say_off_and_refuse_a_restart_when_unmanaged(client):
    body = client.get("/slack-bots/supervisor").json()
    assert body["flag"] is False and body["state"] == "off"
    assert client.post("/slack-bots/supervisor/restart").status_code == 409
