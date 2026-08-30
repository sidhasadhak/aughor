"""The /slack-bots surface — create and manage Slack bots from inside Aughor (RC-5).

Every response goes through `SlackBot.to_safe_dict`, so a raw token never leaves the
server. The update path accepts the mask it handed out and keeps the stored secret, so
an ordinary edit-form save cannot blank a credential — the same contract ActionHub
triggers use for their webhook URL.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
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


#: The header the supervisor presents. Its own name, not `X-Api-Key`: this key opens
#: exactly one route, and a reader should not have to work out which of two meanings a
#: shared header carries.
RUNTIME_KEY_HEADER = "x-aughor-runtime-key"


@router.post("/slack-bots/supervisor-key")
def issue_supervisor_key():
    """Mint the supervisor's key and return it ONCE, with the line to paste.

    This exists because the first version of the fail-closed gate answered "set
    AUGHOR_API_KEY and restart" — a shell export, a restart, and every other client
    locked out of the API to protect one route. Configuration the product requires has
    to be reachable from the product; a button that hands you the value is the smallest
    honest version of that.
    """
    raw = store.issue_supervisor_key()
    return {"key": raw, "env_line": f"AUGHOR_RUNTIME_KEY={raw}",
            "issued_at": store.supervisor_key_issued_at()}


@router.get("/slack-bots/supervisor-key")
def supervisor_key_status():
    """Whether a key exists and when it was minted — never the key. Issued once, and a
    lost one is re-issued rather than recovered."""
    at = store.supervisor_key_issued_at()
    return {"issued": bool(at), "issued_at": at}


def _refuse_without_a_front_door(request: Request) -> None:
    """Refuse to hand out raw credentials to a deployment that authenticates nobody.

    The policy table has always said `ADMIN_MANAGE_ORG` for this route, and the
    docstring below has always said "admin-gated". Both were true only on an
    enterprise-licensed deployment: `enforce_rbac` returns early without the `RBAC_SSO`
    capability, and `_require_auth`'s shared-key door only engages when `AUGHOR_API_KEY`
    is set. A default self-hosted install therefore served `xoxb-`/`xapp-` tokens in
    plaintext to any caller that could reach the port — proved with an unauthenticated
    `curl` on a live instance, 2026-08-30.

    So this one route asks whether the deployment can identify its callers AT ALL, and
    refuses when it cannot. Every other route may reasonably be open on a laptop; this
    is the one place raw credentials leave the server, and a credential handed to an
    unauthenticated caller is a credential given away.

    The key is read from `aughor.api` rather than from `os.environ`, deliberately: that
    module captured it at import, and it is what actually enforces. A gate reading a
    different source than its enforcer is a second opinion — the same mistake the
    integrations readiness check made a few hours earlier, found the same way.
    """
    # The scoped key first: it is the one a person can actually issue from the product.
    if store.supervisor_key_matches(request.headers.get(RUNTIME_KEY_HEADER, "")):
        return
    from aughor.api import _API_KEY
    if _API_KEY:
        return
    from aughor.licensing import Capability, has_capability
    from aughor.security.authz import require_identity_enabled
    if require_identity_enabled() and has_capability(Capability.RBAC_SSO):
        return
    raise HTTPException(
        status_code=503,
        detail="refusing to serve Slack tokens: this caller is unauthenticated. "
               "Generate a supervisor key in Integrations → Slack and put it in the bot "
               "supervisor's environment as AUGHOR_RUNTIME_KEY (an org-wide "
               "AUGHOR_API_KEY works too, if this deployment already sets one). Posting "
               "from automations is unaffected — only the socket supervisor reads this "
               "route.")


@router.get("/slack-bots/runtime")
def slack_bots_runtime(request: Request):
    """The supervisor's door: enabled bots with PLAINTEXT tokens.

    A deliberately separate route rather than a `?reveal=1` flag on the listing. A flag
    makes the masking default one forgotten parameter away from being bypassed, and puts
    the safe and unsafe forms behind the same policy entry; a distinct path can be
    governed, logged and reasoned about on its own — and it cannot be reached by
    accident from a UI that meant to list bots.

    A socket cannot be opened with a mask, so this is the one place raw credentials
    leave the server. Everything else masks. Admin-gated in `rbac/policy.py` — and,
    because that gate is inert without an enterprise licence, FAIL-CLOSED here as well:
    see :func:`_refuse_without_a_front_door`.
    """
    _refuse_without_a_front_door(request)
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
