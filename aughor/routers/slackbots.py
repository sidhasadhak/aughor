"""The /slack-bots surface — create and manage Slack bots from inside Aughor (RC-5).

Every response goes through `SlackBot.to_safe_dict`, so a raw token never leaves the
server. The update path accepts the mask it handed out and keeps the stored secret, so
an ordinary edit-form save cannot blank a credential — the same contract ActionHub
triggers use for their webhook URL.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.slackbots import store
from aughor.slackbots.manifest import render_manifest
from aughor.slackbots.models import SlackBot, merge_secrets

logger = logging.getLogger(__name__)
router = APIRouter(tags=["slack-bots"])


class SlackBotBody(BaseModel):
    name: str = ""
    enabled: bool = True
    agent_id: str = ""
    connection_id: str = ""
    bot_token: str = ""
    app_token: str = ""
    signing_secret: str = ""
    agent_view: bool = False


@router.get("/slack-bots")
def list_slack_bots():
    """Every bot, tokens masked."""
    return {"bots": [b.to_safe_dict() for b in store.list_bots()]}


@router.get("/slack-bots/manifest")
def slack_bot_manifest(name: str = "Aughor", description: str = "", agent_id: str = "",
                       agent_view: bool = False):
    """The Slack app manifest to paste at api.slack.com/apps?new_app=1.

    Rendered rather than documented: the scopes and the socket-mode/agent-view settings
    have to match what the running bot actually does, and a manifest a human retypes
    from a README drifts from the code the first time either changes.
    """
    if agent_id:
        try:
            from aughor.custom_agents.store import get_agent
            agent = get_agent(agent_id)
            if agent:
                name = name if name != "Aughor" else agent.name
                description = description or agent.purpose or ""
        except Exception:
            logger.warning("manifest: agent lookup failed; rendering with the given name",
                           exc_info=True)
    return {
        "manifest": render_manifest(name=name, description=description, agent_view=agent_view),
        # Named here rather than in a doc so the UI can render the steps beside the JSON.
        "instructions": [
            "Open api.slack.com/apps?new_app=1 and choose 'From a manifest'.",
            "Pick your workspace, then paste this JSON on the **JSON** tab — not YAML.",
            "Create the app, then Install to Workspace.",
            "Copy the Bot User OAuth Token (xoxb-…) from OAuth & Permissions.",
            "Copy the Signing Secret from Basic Information.",
            "Under Basic Information → App-Level Tokens, generate a token with "
            "connections:write and copy it (xapp-…).",
            "Paste all three back here to finish.",
        ],
    }


@router.get("/slack-bots/runtime")
def slack_bots_runtime():
    """The supervisor's door: enabled bots with PLAINTEXT tokens.

    A deliberately separate route rather than a `?reveal=1` flag on the listing. A flag
    makes the masking default one forgotten parameter away from being bypassed, and puts
    the safe and unsafe forms behind the same policy entry; a distinct path can be
    governed, logged and reasoned about on its own — and it cannot be reached by
    accident from a UI that meant to list bots.

    A socket cannot be opened with a mask, so this is the one place raw credentials
    leave the server. Everything else masks. Admin-gated in `rbac/policy.py`.
    """
    bots = [b for b in store.list_bots(include_disabled=False) if b.bot_token and b.app_token]
    return {"bots": [store.get_bot_decrypted(b.id).to_dict() for b in bots]}


@router.get("/slack-bots/{bot_id}")
def get_slack_bot(bot_id: str):
    bot = store.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="no such slack bot")
    return bot.to_safe_dict()


@router.post("/slack-bots")
def create_slack_bot(body: SlackBotBody):
    """Create a bot. Every credential must be present and must actually work —
    verification happens before the record exists, because a bot stored with a bad token
    is a socket that fails to open at 03:00 with nobody watching."""
    missing = [f for f in ("bot_token", "app_token", "signing_secret")
               if not (getattr(body, f) or "").strip()]
    if missing:
        raise HTTPException(status_code=422,
                            detail=f"missing credential(s): {', '.join(missing)}")
    bot = SlackBot(**body.model_dump())
    verified = _verify(bot)
    return store.save_bot(verified).to_safe_dict()


@router.patch("/slack-bots/{bot_id}")
def update_slack_bot(bot_id: str, body: SlackBotBody):
    stored = store.get_bot(bot_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="no such slack bot")
    incoming = SlackBot(**{**body.model_dump(), "id": bot_id,
                           "created_at": stored.created_at,
                           "team_id": stored.team_id, "slack_app_id": stored.slack_app_id,
                           "bot_user_id": stored.bot_user_id})
    merged = merge_secrets(incoming, stored)
    # Re-verify only when a credential actually changed — an ordinary rename should not
    # depend on Slack being reachable.
    if any(getattr(merged, f) != getattr(stored, f)
           for f in ("bot_token", "app_token", "signing_secret")):
        merged = _verify(merged)
    return store.save_bot(merged).to_safe_dict()


@router.delete("/slack-bots/{bot_id}")
def delete_slack_bot(bot_id: str):
    if not store.delete_bot(bot_id):
        raise HTTPException(status_code=404, detail="no such slack bot")
    return {"deleted": bot_id}


def _verify(bot: SlackBot) -> SlackBot:
    """Confirm the token works and capture what Slack says about it.

    A 422 rather than a stored-but-broken record: the failure a user can act on is the
    one they get while they still have the Slack tab open.
    """
    from aughor.slackbots.verify import auth_test
    ok, info = auth_test(bot.bot_token)
    if not ok:
        raise HTTPException(status_code=422,
                            detail=f"Slack rejected the bot token: {info.get('error', 'unknown')}")
    return bot.model_copy(update={
        "team_id": info.get("team_id", "") or bot.team_id,
        "bot_user_id": info.get("user_id", "") or bot.bot_user_id,
        "slack_app_id": info.get("app_id", "") or bot.slack_app_id,
    })
