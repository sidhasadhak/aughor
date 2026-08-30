"""RC-5.1/5.2 — a Slack bot is a platform record, and its credentials never leak.

RC-1 and RC-2 both ran against ONE bot whose three tokens lived in a `.env.local` on a
laptop. This wave makes a bot a record so users can create as many as they want, and the
properties below are the ones that make that safe to expose:

* **No raw token ever leaves the server.** Every read path masks all three.
* **An ordinary save cannot blank a credential.** The API hands out a mask; the client
  sends it back unchanged; the update path must recognise its own mask and keep the
  stored secret. Getting this wrong silently destroys a working bot on a rename.
* **A bot is a REFERENCE to an agent, never a copy of one.** Nothing here duplicates
  instructions, docs or packs — that would fork the governing configuration.
* **A credential is verified before a record claims it works.** A bot stored with a bad
  token is a socket that fails to open at 03:00 with nobody watching.
* **The manifest is rendered from the code that uses it**, so scopes cannot drift from
  what the transport actually calls.

Hermetic: the conftest temp dirs; `auth.test` is stubbed, so no test touches the network.
"""
from __future__ import annotations

import pytest

from aughor.slackbots import store
from aughor.slackbots.manifest import BOT_SCOPES, render_manifest
from aughor.slackbots.models import (SlackBot, decrypt_secrets, encrypt_secrets,
                                     merge_secrets)


def _bot(**kw) -> SlackBot:
    base = dict(name="salesbot", agent_id="ag-1", connection_id="conn-a",
                bot_token="xoxb-real-secret", app_token="xapp-real-secret",
                signing_secret="sig-real-secret")
    base.update(kw)
    return SlackBot(**base)


@pytest.fixture
def slack_ok(monkeypatch):
    """Stub `auth.test` — verification is a Slack round trip, and no test may make one."""
    monkeypatch.setattr("aughor.slackbots.verify.auth_test",
                        lambda token: (True, {"team_id": "T1", "user_id": "U-BOT",
                                              "app_id": "A1", "team": "acme"}))


# ── secrets ──────────────────────────────────────────────────────────────────────

def test_every_secret_is_masked_on_read():
    safe = _bot().to_safe_dict()
    for field in ("bot_token", "app_token", "signing_secret"):
        assert "real-secret" not in safe[field], f"{field} leaked a raw value"
        assert "•" in safe[field]


def test_encrypt_is_idempotent_so_resaving_never_double_encrypts():
    once = encrypt_secrets(_bot())
    twice = encrypt_secrets(once)
    assert once.bot_token == twice.bot_token
    assert decrypt_secrets(twice).bot_token == "xoxb-real-secret"


def test_a_saved_bot_is_encrypted_at_rest():
    saved = store.save_bot(_bot())
    raw = store._STORE.get(saved.id)
    assert "xoxb-real-secret" not in str(raw), "the plaintext token reached the store"
    assert store.get_bot_decrypted(saved.id).bot_token == "xoxb-real-secret"


# ── the mask round-trip: the one that silently destroys a bot when wrong ─────────

def test_echoing_the_mask_back_keeps_the_stored_secret():
    stored = _bot()
    echoed = _bot(bot_token=stored.to_safe_dict()["bot_token"])   # what a save sends back
    assert merge_secrets(echoed, stored).bot_token == "xoxb-real-secret"


def test_a_genuinely_new_secret_replaces_the_old_one():
    assert merge_secrets(_bot(bot_token="xoxb-rotated"), _bot()).bot_token == "xoxb-rotated"


def test_an_absent_secret_keeps_the_stored_one():
    assert merge_secrets(_bot(bot_token=""), _bot()).bot_token == "xoxb-real-secret"


def test_a_bullet_containing_secret_is_not_mistaken_for_a_mask():
    """The mask is compared against the mask OF THE STORED VALUE, not against a bullet
    pattern. A shape test would treat any bullet-containing string as 'unchanged' and
    silently ignore a caller genuinely setting one."""
    stored = _bot()
    assert merge_secrets(_bot(bot_token="xoxb-••••••-mine"), stored).bot_token == "xoxb-••••••-mine"


# ── the store ────────────────────────────────────────────────────────────────────

def test_many_bots_coexist_each_bound_to_its_own_agent():
    """The whole point of the wave: N bots, not one."""
    a = store.save_bot(_bot(name="salesbot", agent_id="ag-sales"))
    b = store.save_bot(_bot(name="financebot", agent_id="ag-finance"))
    ids = {x.id for x in store.list_bots()}
    assert {a.id, b.id} <= ids and a.id != b.id
    assert {x.agent_id for x in store.list_bots()} >= {"ag-sales", "ag-finance"}


def test_bots_for_agent_finds_every_door_onto_one_agent():
    """The query an agent-delete cascade needs, so a deleted agent leaves no live socket."""
    store.save_bot(_bot(agent_id="ag-x", name="one"))
    store.save_bot(_bot(agent_id="ag-x", name="two"))
    store.save_bot(_bot(agent_id="ag-y", name="three"))
    assert {b.name for b in store.bots_for_agent("ag-x")} == {"one", "two"}


def test_delete_removes_and_is_honest_about_a_miss():
    saved = store.save_bot(_bot())
    assert store.delete_bot(saved.id) is True
    assert store.get_bot(saved.id) is None
    assert store.delete_bot(saved.id) is False


# ── the manifest ─────────────────────────────────────────────────────────────────

def test_manifest_grants_what_the_transport_actually_calls():
    scopes = render_manifest(name="salesbot")["oauth_config"]["scopes"]["bot"]
    assert "app_mentions:read" in scopes, "the mention that starts a turn"
    assert "chat:write" in scopes, "posting the answer"
    assert "files:write" in scopes, "RC-2 uploads a chart PNG and a CSV"
    assert set(scopes) == set(BOT_SCOPES)


def test_manifest_is_socket_mode_with_no_public_url():
    """Socket Mode connects OUT, which is what lets a self-hosted Aughor run bots."""
    m = render_manifest(name="b")
    assert m["settings"]["socket_mode_enabled"] is True
    assert "request_url" not in str(m), "socket mode needs no public endpoint"


def test_agent_view_is_opt_in_and_brings_its_scope():
    """Turning agentView on against an app without this mode costs the final message of
    every answer, so the manifest and the record must agree — hence opt-in, not default."""
    off = render_manifest(name="b", agent_view=False)
    assert "agent_view" not in off["features"]
    assert "assistant:write" not in off["oauth_config"]["scopes"]["bot"]

    on = render_manifest(name="b", agent_view=True)
    assert "agent_view" in on["features"]
    assert "assistant:write" in on["oauth_config"]["scopes"]["bot"]


def test_manifest_is_json_serialisable():
    """It is pasted on Slack's JSON tab. The YAML tab rejected this manifest with
    'can't translate' during RC-1's live setup."""
    import json
    assert json.loads(json.dumps(render_manifest(name="b")))["display_information"]["name"] == "b"


# ── the routes ───────────────────────────────────────────────────────────────────

def test_create_verifies_the_token_and_captures_what_slack_says(client, slack_ok):
    r = client.post("/slack-bots", json={"name": "salesbot", "agent_id": "ag-1",
                                         "bot_token": "xoxb-x", "app_token": "xapp-x",
                                         "signing_secret": "s"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["team_id"] == "T1" and body["bot_user_id"] == "U-BOT"
    assert "xoxb-x" not in r.text, "a raw token reached the API response"


def test_create_refuses_a_credential_slack_rejects(client, monkeypatch):
    monkeypatch.setattr("aughor.slackbots.verify.auth_test",
                        lambda token: (False, {"error": "invalid_auth"}))
    r = client.post("/slack-bots", json={"name": "b", "bot_token": "xoxb-bad",
                                         "app_token": "xapp-x", "signing_secret": "s"})
    assert r.status_code == 422 and "invalid_auth" in r.text


def test_create_names_every_missing_credential_at_once(client, slack_ok):
    r = client.post("/slack-bots", json={"name": "b"})
    assert r.status_code == 422
    for f in ("bot_token", "app_token", "signing_secret"):
        assert f in r.text


def test_a_rename_does_not_blank_the_credentials(client, slack_ok):
    """The edit-form path: read (masked) → change the name → save. If the mask were
    stored, the bot would stop working and nothing would say why."""
    created = client.post("/slack-bots", json={
        "name": "old", "agent_id": "ag-1", "bot_token": "xoxb-keepme",
        "app_token": "xapp-x", "signing_secret": "s"}).json()

    masked = client.get(f"/slack-bots/{created['id']}").json()
    masked["name"] = "new"
    r = client.patch(f"/slack-bots/{created['id']}", json=masked)

    assert r.status_code == 200 and r.json()["name"] == "new"
    assert store.get_bot_decrypted(created["id"]).bot_token == "xoxb-keepme"


def test_listing_masks_every_bot(client, slack_ok):
    client.post("/slack-bots", json={"name": "b1", "bot_token": "xoxb-secret1",
                                     "app_token": "xapp-x", "signing_secret": "s"})
    r = client.get("/slack-bots")
    assert r.status_code == 200 and "xoxb-secret1" not in r.text


def test_manifest_route_carries_the_paste_steps(client):
    r = client.get("/slack-bots/manifest", params={"name": "salesbot"})
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["display_information"]["name"] == "salesbot"
    assert any("JSON" in s for s in body["instructions"]), "the YAML tab is the known trap"


def test_unknown_bot_is_404(client):
    assert client.get("/slack-bots/sb_nope").status_code == 404


def _automation(effect):
    """A minimally valid Automation carrying `effect` — conn_id and a non-empty effects
    list are both required at construction."""
    from aughor.automations.models import Automation, Condition
    return Automation(
        name="Monday briefing", conn_id="conn-a",
        conditions=[Condition(kind="schedule", config={"cron": "0 9 * * 1"})],
        effects=[effect],
    )


# ── RC-5.4: the periodic trigger half ────────────────────────────────────────────

def test_slack_post_effect_requires_its_target_at_construction():
    """Rejected at parse, never at 03:00. An automation missing its channel would
    otherwise sit in the DB looking schedulable."""
    from aughor.automations.models import Effect
    with pytest.raises(ValueError):
        Effect(kind="slack_post", config={"bot_id": "sb_1"})       # no channel
    with pytest.raises(ValueError):
        Effect(kind="slack_post", config={"channel": "C1"})        # no bot
    Effect(kind="slack_post", config={"bot_id": "sb_1", "channel": "C1"})   # both: fine


def test_a_cron_posts_as_the_bot_and_the_thread_is_repliable(monkeypatch):
    """The loop this wave exists to close.

    `notify` fires an incoming webhook, which arrives under the WEBHOOK's identity with
    no thread anyone can reply into. This asserts the bot's OWN token is used, so the
    message arrives as the bot — and that the returned `ts` (the thread root a reply
    lands in, and the id the transport already uses as the Aughor session_id) is carried
    back rather than dropped.
    """
    from aughor.automations.engine import _dispatch_slack_post
    from aughor.automations.models import Effect

    bot = store.save_bot(_bot(name="salesbot", bot_token="xoxb-live-token"))
    seen = {}

    def _fake_post(token, channel, text, thread_ts=None):
        seen.update(token=token, channel=channel, text=text)
        return True, {"ts": "1788000000.000100", "channel": channel}

    monkeypatch.setattr("aughor.slackbots.post.post_as_bot", _fake_post)

    effect = Effect(kind="slack_post",
                    config={"bot_id": bot.id, "channel": "C123", "message": "revenue is up"})
    out = _dispatch_slack_post(effect, _automation(effect))

    assert out.status == "executed"
    assert seen["token"] == "xoxb-live-token", "must post with the BOT's token, not a webhook"
    assert seen["channel"] == "C123" and seen["text"] == "revenue is up"
    assert "1788000000.000100" in out.message, "the thread root must come back"


def test_posting_through_a_disabled_bot_is_refused(monkeypatch):
    """`enabled` is the platform's off switch; a scheduled post that ignored it would
    make that switch a lie."""
    from aughor.automations.engine import _dispatch_slack_post
    from aughor.automations.models import Effect

    bot = store.save_bot(_bot(enabled=False))
    monkeypatch.setattr("aughor.slackbots.post.post_as_bot",
                        lambda *a, **k: pytest.fail("a disabled bot must not post"))
    effect = Effect(kind="slack_post", config={"bot_id": bot.id, "channel": "C1"})
    out = _dispatch_slack_post(effect, _automation(effect))
    assert out.status == "dispatch_error" and "disabled" in out.message


def test_an_unknown_bot_is_a_verdict_not_a_crash():
    from aughor.automations.engine import _dispatch_slack_post
    from aughor.automations.models import Effect
    effect = Effect(kind="slack_post", config={"bot_id": "sb_gone", "channel": "C1"})
    out = _dispatch_slack_post(effect, _automation(effect))
    assert out.status == "dispatch_error" and "sb_gone" in out.message


def test_a_timed_out_post_is_uncertain_not_failed(monkeypatch):
    """It may have arrived. 'failed' would license a retry, and a retried
    maybe-delivered message is the duplicate the delivery layer exists to prevent."""
    from aughor.automations.engine import _dispatch_slack_post
    from aughor.automations.models import Effect

    bot = store.save_bot(_bot())
    monkeypatch.setattr("aughor.slackbots.post.post_as_bot",
                        lambda *a, **k: (False, {"error": "timeout", "uncertain": True}))
    effect = Effect(kind="slack_post", config={"bot_id": bot.id, "channel": "C1"})
    out = _dispatch_slack_post(effect, _automation(effect))
    assert out.status == "uncertain"


def test_slack_post_is_reachable_from_the_engine_dispatch_table():
    """The seam: registered in models AND wired in the engine. Both ends can exist while
    the feature does not."""
    from aughor.automations.engine import _DISPATCHERS
    assert "slack_post" in _DISPATCHERS


# ── VA-9b: whose credential is being spent ───────────────────────────────────────

def test_a_bot_can_belong_to_a_person():
    saved = store.save_bot(_bot(owner="amit@example.com"))
    assert store.get_bot(saved.id).owner == "amit@example.com"


def test_owner_scoping_includes_the_orgs_unowned_bots():
    """`owner=""` is what every bot created before VA-9b carries, and a shared workspace
    bot is legitimate. Excluding them would make this field a silent migration."""
    # Asserted by ID and by inclusion, not by an exact set of names: earlier tests in
    # this file leave bots in the store, so an equality assertion would be measuring the
    # whole file's history rather than this property.
    mine = store.save_bot(_bot(name="mine", owner="amit@example.com"))
    yours = store.save_bot(_bot(name="yours", owner="sam@example.com"))
    shared = store.save_bot(_bot(name="shared"))

    visible = {b.id for b in store.bots_for_owner("amit@example.com")}
    assert mine.id in visible
    assert shared.id in visible, "an unowned bot is the org's and stays visible"
    assert yours.id not in visible, "another person's credential is not mine to spend"


def test_an_owner_is_the_same_subject_the_identity_plane_resolves():
    """RC-4 maps `slack:U…` → a platform user; this stores that same user. One identity
    scheme, so 'my Slack' differs from yours without inventing a second."""
    from aughor.identity import attribution_key, store as ident_store
    ident_store.put_link("slack", "U0OWNER", "amit@example.com")
    bot = store.save_bot(_bot(owner="amit@example.com"))
    assert attribution_key("slack:U0OWNER") == bot.owner


# ── the one route that hands out raw credentials ─────────────────────────────────

def test_the_runtime_route_refuses_when_the_deployment_authenticates_nobody(client):
    """Proved against a live instance with an unauthenticated `curl`: the policy table
    said ADMIN_MANAGE_ORG and the docstring said "admin-gated", but `enforce_rbac`
    returns early without an enterprise licence and `_require_auth`'s key door only
    engages when `AUGHOR_API_KEY` is set. A default self-hosted install served `xoxb-`
    and `xapp-` tokens in plaintext to anyone who could reach the port."""
    r = client.get("/slack-bots/runtime")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "AUGHOR_API_KEY" in detail            # says how to fix it
    assert "Posting from automations is unaffected" in detail   # and what still works


def test_the_runtime_route_serves_a_deployment_that_has_a_front_door(client, slack_ok,
                                                                     monkeypatch):
    """With a shared key configured, `_require_auth` actually checks callers — the gate
    reads that same value rather than a second source, so the two cannot disagree."""
    # A name of its own: this store accumulates across the file and `salesbot` is
    # already taken by the fixture, whose token is a different string.
    client.post("/slack-bots", json={"name": "front-door-bot", "bot_token": "xoxb-t",
                                     "app_token": "xapp-t", "signing_secret": "sig"})
    monkeypatch.setattr("aughor.api._API_KEY", "a-real-key")

    # And the caller must now present it — the SAME key satisfies the gate and the
    # front door, which is the whole reason the gate reads `_require_auth`'s value
    # rather than one of its own.
    assert client.get("/slack-bots/runtime").status_code == 401

    r = client.get("/slack-bots/runtime", headers={"X-Api-Key": "a-real-key"})
    assert r.status_code == 200
    # Not an exact list — this store accumulates across the file. What matters is that
    # the route still does its job: RAW tokens, which is the only reason it exists.
    mine = next(b for b in r.json()["bots"] if b["name"] == "front-door-bot")
    assert mine["bot_token"] == "xoxb-t"
    assert "•" not in mine["app_token"]
