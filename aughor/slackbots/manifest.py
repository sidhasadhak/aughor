"""The Slack app manifest Aughor renders for a new bot (RC-5).

Rendered from code rather than kept as a document, because every value in it has to
match what the running bot does: the scopes are what the transport calls, and
`socket_mode_enabled` is what makes the whole design possible on a self-hosted install.
A manifest a human retypes from a README drifts from the code the first time either
changes, and the drift shows up as a permission error in a live workspace.

Two values are load-bearing:

* **`files:write`** — RC-2 uploads a chart PNG and a CSV into the thread. Granting it at
  creation costs nothing; adding it later makes every user re-authorize an installed app.
* **`agent_view`** — only when the record says so. The adapter's `agentView` requires an
  app in this mode, and turning it on against an `assistant_view` app makes `stopStream`
  send a parameter that app cannot accept, which costs the final message of every answer.
  Manifest and record are written in one act so the two cannot disagree. The manifest
  carries `agent_view` and never `assistant_view`: Slack refuses the pair on a new app.
"""
from __future__ import annotations

#: What the bot actually needs, and why:
#:   app_mentions:read — the mention that starts a turn
#:   chat:write        — post the answer (and, for RC-5.4, a scheduled post)
#:   *_history         — read the thread the mention lives in, so follow-ups compose
#:   im:history/write  — the same conversation in a DM
#:   files:write       — RC-2's chart PNG and CSV
#:   reactions:read    — TJ-4: ✅ / ❌ on an answer is a verdict on its turn (2026-09-26)
#:   users:read        — the transport resolves the asker's name with `users.info` on every
#:                       message. Left out until the first live sitting (2026-10-03): the
#:                       answer still arrived, but the supervisor logged "Could not fetch
#:                       user info … missing_scope, needed: users:read" per message and a
#:                       verdict's note named a user id. Granted at creation it costs
#:                       nothing; added later it is a re-install.
BOT_SCOPES = [
    "app_mentions:read",
    "chat:write",
    "channels:history",
    "groups:history",
    "im:history",
    "im:write",
    "files:write",
    "reactions:read",
    "users:read",
]

#: The events the transport handles. Anything else Slack could send is noise the bot
#: would receive, log and drop — so it is not subscribed to.
#: `reaction_added` (TJ-4): the bot reads a reaction on its own answer as a verdict; a
#: reaction removed is not subscribed — a verdict is not un-said by taking the emoji back.
BOT_EVENTS = ["app_mention", "message.im", "reaction_added"]

#: AO-2c — the events agent mode needs, which `bots/slack/README.md` told a person to add
#: by hand while the manifest left them out: the Agents & AI Apps surface opens a session
#: on `app_home_opened`, follows the user with `app_context_changed`, and the native stop
#: button and the title arrive as `agent_session_*`. Rendered when `agent_view` is on, so
#: the manifest and the README no longer disagree.
AGENT_EVENTS = ["app_home_opened", "app_context_changed", "agent_session_stopped",
                "agent_session_title_changed"]


def render_manifest(*, name: str, description: str = "", agent_view: bool = True,
                    redirect_url: str = "") -> dict:
    """The manifest as a dict; the caller serialises it as JSON.

    JSON, never YAML: Slack's YAML tab rejected this manifest with "can't translate"
    during RC-1's live setup, and the failure names nothing a user can act on.

    ``agent_view`` defaults to True (AO-2c, §6 item 38(f)): Slack closed the legacy
    assistant view to new apps on 2026-08-20 and retires it in February 2027, so a new
    app is in agent mode or it is on borrowed time. ``redirect_url`` (AO-2d): the API's
    OAuth callback, when the deployment has a public HTTPS origin — it is what lets the
    install be a button rather than a paste.
    """
    display_name = (name or "Aughor").strip()[:35]
    manifest = {
        "display_information": {
            "name": display_name,
            "description": (description or "Answers data questions from your warehouse.")[:140],
        },
        "features": {
            "bot_user": {"display_name": display_name, "always_online": True},
            "app_home": {"messages_tab_enabled": True,
                         "messages_tab_read_only_enabled": False},
        },
        "oauth_config": {"scopes": {"bot": list(BOT_SCOPES)}},
        "settings": {
            "event_subscriptions": {"bot_events": list(BOT_EVENTS)},
            # Socket Mode connects OUT over a WebSocket, so a user's bot needs no public
            # URL, tunnel or webhook endpoint. This is what lets a self-hosted Aughor run
            # bots at all, and it is why there is no request_url anywhere in here.
            "socket_mode_enabled": True,
            "org_deploy_enabled": False,
            "token_rotation_enabled": False,
        },
    }
    if redirect_url:
        manifest["oauth_config"]["redirect_urls"] = [redirect_url]
    if agent_view:
        # Slack's Agent surface: the native stop button and the session lifecycle RC-2's
        # progress cards ride on. `agent_view` ALONE, with its required description.
        #
        # Until 2026-10-03 this rendered `assistant_view` AND an empty `agent_view` — a pair
        # nobody had sent to `apps.manifest.create`. The first live create was refused:
        # "invalid_manifest: Remove assistant_view feature". Slack's manifest reference:
        # "New apps can only use agent_view", and `agent_view.agent_description` is
        # required when the subgroup is present (max 300 characters) — the empty object
        # would have been the next refusal.
        manifest["features"]["agent_view"] = {
            "agent_description": (description or "Ask about your data.")[:300],
        }
        manifest["oauth_config"]["scopes"]["bot"].append("assistant:write")
        manifest["settings"]["event_subscriptions"]["bot_events"] += list(AGENT_EVENTS)
    return manifest
