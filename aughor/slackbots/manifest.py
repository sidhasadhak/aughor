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
  Manifest and record are written in one act so the two cannot disagree.
"""
from __future__ import annotations

#: What the bot actually needs, and why:
#:   app_mentions:read — the mention that starts a turn
#:   chat:write        — post the answer (and, for RC-5.4, a scheduled post)
#:   *_history         — read the thread the mention lives in, so follow-ups compose
#:   im:history/write  — the same conversation in a DM
#:   files:write       — RC-2's chart PNG and CSV
BOT_SCOPES = [
    "app_mentions:read",
    "chat:write",
    "channels:history",
    "groups:history",
    "im:history",
    "im:write",
    "files:write",
]

#: The events the transport handles. Anything else Slack could send is noise the bot
#: would receive, log and drop — so it is not subscribed to.
BOT_EVENTS = ["app_mention", "message.im"]


def render_manifest(*, name: str, description: str = "", agent_view: bool = False) -> dict:
    """The manifest as a dict; the caller serialises it as JSON.

    JSON, never YAML: Slack's YAML tab rejected this manifest with "can't translate"
    during RC-1's live setup, and the failure names nothing a user can act on.
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
    if agent_view:
        # Slack's Agent/Assistant surface: the native stop button and the session
        # lifecycle RC-2's progress cards ride on.
        manifest["features"]["assistant_view"] = {
            "assistant_description": (description or "Ask about your data.")[:140],
        }
        manifest["features"]["agent_view"] = {}
        manifest["oauth_config"]["scopes"]["bot"].append("assistant:write")
    return manifest
