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
    #: AO-2f — optional home channel; see `SlackBot.channel_id`.
    channel_id: str = ""
    #: AO-6 — hold automation posts as this bot for a person's click; see `SlackBot.rehearse`.
    rehearse: bool = False


@router.get("/slack-bots")
def list_slack_bots():
    """The active workspace's bots, tokens masked.

    A bot bound to no connection is org-level and stays listed everywhere — it answers
    about whatever the caller asks, so no workspace owns it yet."""
    from aughor.metastore import scoped_to_workspace
    # AO-2a — each row says whether anything is LISTENING for it, from the supervisor's
    # last heartbeat; "enabled" alone read as alive on a machine where nothing ran.
    return {"bots": [{**b.to_safe_dict(), **store.liveness_fields(b.id)}
                     for b in scoped_to_workspace(store.list_bots(), key="connection_id")]}


@router.get("/slack-bots/manifest")
def slack_bot_manifest(name: str = "Aughor", description: str = "", agent_id: str = "",
                       agent_view: bool = True):
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
        "manifest": render_manifest(name=name, description=description, agent_view=agent_view,
                                    redirect_url=_oauth_redirect_uri()),
        "agent_view": agent_view,
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


# ── AO-2d · one configuration token ──────────────────────────────────────────────

def _public_api_base() -> str:
    """The API's public HTTPS origin, when the operator declared one (`AUGHOR_PUBLIC_API_URL`).
    Empty beats guessed: Slack refuses a non-HTTPS redirect, and a wrong origin would
    send every install to the wrong door."""
    import os
    return os.environ.get("AUGHOR_PUBLIC_API_URL", "").strip().rstrip("/")


def _oauth_redirect_uri() -> str:
    base = _public_api_base()
    return f"{base}/slack-bots/oauth/callback" if base.startswith("https://") else ""


class SlackAppCreate(BaseModel):
    """One configuration token, from api.slack.com/apps → Your App Configuration Tokens.
    Used once, never stored."""
    config_token: str
    name: str = "Aughor"
    description: str = ""
    agent_id: str = ""
    connection_id: str = ""
    agent_view: bool = True


@router.post("/slack-bots/apps")
def create_slack_app(body: SlackAppCreate):
    """Create the Slack app from the manifest Aughor renders, with Slack's own API.

    Measured 2026-10-03: twenty manual steps across four surfaces and five pasted
    secrets. After this call the app exists, its signing secret is stored, and an
    OAuth client is on the record — so on an HTTPS deployment the install is a button
    (`GET /slack-bots/{id}/install`). What stays by hand is the app-level token: Slack
    offers no API for it, and the response says so (`needs`), never pretending.
    """
    from aughor.slackbots import apps
    name = (body.name or "Aughor").strip()
    description = body.description
    if body.agent_id and not description:
        try:
            from aughor.custom_agents.store import get_agent
            agent = get_agent(body.agent_id)
            if agent:
                description = agent.purpose or ""
                name = name if name != "Aughor" else agent.name
        except Exception:
            logger.warning("app create: agent lookup failed; using the given name", exc_info=True)
    redirect = _oauth_redirect_uri()
    manifest = render_manifest(name=name, description=description, agent_view=body.agent_view,
                               redirect_url=redirect)
    ok, info = apps.create_app(body.config_token, manifest)
    if not ok:
        raise HTTPException(status_code=422,
                            detail=f"Slack refused to create the app: {info.get('error', 'unknown')}")
    creds = info.get("credentials") or {}
    bot = SlackBot(
        name=name, agent_id=body.agent_id, connection_id=body.connection_id,
        agent_view=body.agent_view, slack_app_id=str(info.get("app_id") or ""),
        signing_secret=str(creds.get("signing_secret") or ""),
        client_id=str(creds.get("client_id") or ""),
        client_secret=str(creds.get("client_secret") or ""),
        # Off until it can listen: no bot token, no app-level token yet. The card says why.
        enabled=False,
        disabled_reason="not installed yet — finish the two steps on the Slack door",
    )
    saved = store.save_bot(bot)
    needs = ["bot_token", "app_token"]
    return {
        "bot": saved.to_safe_dict(),
        "app_id": saved.slack_app_id,
        "install_url": (f"/slack-bots/{saved.id}/install" if redirect else ""),
        "manage_url": f"https://api.slack.com/apps/{saved.slack_app_id}" if saved.slack_app_id else "",
        "needs": needs,
        "oauth_available": bool(redirect),
        "steps": [
            ("Install the app to your workspace — the Install button does it here."
             if redirect else
             "Install the app to your workspace: open the app at api.slack.com → Install to "
             "Workspace, then paste the Bot User OAuth Token (xoxb-…) here. (A button "
             "needs a public HTTPS origin: set AUGHOR_PUBLIC_API_URL.)"),
            "Generate the app-level token: Basic Information → App-Level Tokens, scope "
            "connections:write, and paste it (xapp-…) here. Slack offers no API for this one.",
        ],
    }


@router.get("/slack-bots/{bot_id}/install")
def slack_bot_install(bot_id: str):
    """Send the browser to Slack's install page for this app. The state is the bot id,
    sealed, so the callback cannot be pointed at another record."""
    from fastapi.responses import RedirectResponse
    from aughor.secretvault import encrypt_secret
    from aughor.slackbots import apps
    from aughor.slackbots.manifest import BOT_SCOPES
    bot = store.get_bot_decrypted(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="no such slack bot")
    redirect = _oauth_redirect_uri()
    if not redirect:
        raise HTTPException(status_code=409, detail="no public HTTPS origin is declared "
                            "(AUGHOR_PUBLIC_API_URL), so Slack cannot send the install back "
                            "here — install at api.slack.com and paste the bot token instead")
    if not bot.client_id:
        raise HTTPException(status_code=409, detail="this bot's app was not created by Aughor, "
                            "so there is no OAuth client to install with")
    scopes = list(BOT_SCOPES) + (["assistant:write"] if bot.agent_view else [])
    return RedirectResponse(apps.install_url(bot.client_id, scopes, redirect,
                                             state=encrypt_secret(bot.id)), status_code=302)


@router.get("/slack-bots/oauth/callback")
def slack_bot_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Slack's redirect after the install: the code becomes the bot token on the record.
    Open (no key) because the browser carries none; the sealed state is the authority."""
    from fastapi.responses import RedirectResponse
    import os
    from aughor.secretvault import decrypt_secret
    from aughor.slackbots import apps
    web = os.environ.get("AUGHOR_WEB_URL", "").strip().rstrip("/")

    def _back(outcome: str, bot_id: str = "") -> RedirectResponse | dict:
        if web:
            return RedirectResponse(f"{web}/?tab=integrations&slack_install={outcome}"
                                    + (f"&bot={bot_id}" if bot_id else ""), status_code=302)
        return {"outcome": outcome, "bot_id": bot_id}

    if error:
        return _back(f"refused:{error}")
    bot_id = decrypt_secret(state or "") or ""
    bot = store.get_bot_decrypted(bot_id) if bot_id else None
    if bot is None or not state or bot_id == state:
        raise HTTPException(status_code=400, detail="unrecognised install state")
    ok, info = apps.exchange_code(bot.client_id, bot.client_secret, code, _oauth_redirect_uri())
    if not ok or not info.get("access_token"):
        return _back(f"failed:{info.get('error', 'unknown')}", bot.id)
    team = info.get("team") or {}
    installed = bot.model_copy(update={
        "bot_token": str(info.get("access_token")),
        "team_id": str(team.get("id") or bot.team_id),
        "bot_user_id": str(info.get("bot_user_id") or bot.bot_user_id),
    })
    try:
        installed = _verify(installed)
    except HTTPException as exc:
        return _back(f"failed:{exc.detail}", bot.id)
    # Listening needs the app-level token too; until it is pasted the card still says why.
    ready = bool(installed.app_token)
    installed = installed.model_copy(update={
        "enabled": ready,
        "disabled_reason": "" if ready else "installed — paste the app-level token to finish",
    })
    store.save_bot(installed)
    return _back("installed", bot.id)


# ── AO-2b · the managed supervisor ───────────────────────────────────────────────

@router.get("/slack-bots/supervisor")
def managed_supervisor_status():
    """What the API knows about the supervisor it runs (flag `slack.managed_supervisor`):
    off, running (pid), restarting, stopped or failed — with the reason named."""
    from aughor.slackbots.managed import managed_status
    return managed_status()


@router.post("/slack-bots/supervisor/restart")
def managed_supervisor_restart():
    from aughor.slackbots.managed import host, managed_status
    h = host()
    if h is None:
        raise HTTPException(status_code=409, detail="the API is not managing a supervisor "
                            "(flag slack.managed_supervisor is off, or the API started "
                            "without it) — nothing to restart")
    h.restart()
    return managed_status()


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
    status = store.supervisor_key_status()
    return {"key": raw, "env_line": f"AUGHOR_RUNTIME_KEY={raw}",
            "issued_at": status["issued_at"],
            # AO-2e — the replaced key keeps working this long, so the running supervisor
            # is not dark between "Regenerate" and the restart.
            "previous_valid_until": status["previous_valid_until"],
            "previous_valid_for_s": store.KEY_GRACE_S if status["previous_valid_until"] else 0}


@router.get("/slack-bots/supervisor-key")
def supervisor_key_status():
    """Whether a key exists, when it was minted, and until when the previous one still
    opens the door — never the key. Issued once, and a lost one is re-issued rather than
    recovered."""
    return store.supervisor_key_status()


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

    The posture is read from `aughor.api` rather than from `os.environ`, deliberately:
    that module captured the key at import, and it is what actually enforces. A gate
    reading a different source than its enforcer is a second opinion — the same mistake
    the integrations readiness check made a few hours earlier, found the same way. It
    asks through `api_key_configured()`, a public predicate: whether a door exists is
    this module's business, the key behind it is not.
    """
    # The scoped key first: it is the one a person can actually issue from the product.
    if store.supervisor_key_matches(request.headers.get(RUNTIME_KEY_HEADER, "")):
        return
    from aughor.api import api_key_configured
    if api_key_configured():
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


class HeartbeatBody(BaseModel):
    supervisor_id: str
    running: list[str] = []
    failed: list[dict] = []
    reconcile_ms: int = 30000


@router.post("/slack-bots/runtime/heartbeat")
def slack_bots_heartbeat(body: HeartbeatBody, request: Request):
    """The supervisor's word that it is alive, after every reconcile (AO-2a).

    Gated exactly like the runtime read — it is the same process speaking — and the ONLY
    writer of the liveness store. Measured 2026-10-03: nothing started the supervisor,
    nothing watched it, and the bot card said "enabled" on a machine where it was not
    running. The card now reads *listening since …* from the last beat, or *not
    listening* with the command once the beats stop.
    """
    _refuse_without_a_front_door(request)
    row = store.record_heartbeat(body.supervisor_id.strip()[:200] or "unnamed",
                                 body.running, body.failed, body.reconcile_ms)
    return {"recorded": True, "supervisor_id": row["id"], "since": row["since"],
            "running": len(row["running"]), "failed": len(row["failed"])}


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
                           "bot_user_id": stored.bot_user_id,
                           # AO-1e — a platform-written reason survives an edit and is
                           # cleared the moment a person switches the bot back on.
                           "disabled_reason": "" if body.enabled else stored.disabled_reason})
    merged = merge_secrets(incoming, stored)
    # AO-2c — agent mode is one-way in Slack: an app switched to Agents & AI Apps cannot
    # be switched back, and a record that said otherwise would make the adapter send
    # parameters the app refuses. Refused with the reason rather than silently kept.
    if stored.agent_view and not merged.agent_view:
        raise HTTPException(status_code=409, detail="agent mode is one-way: Slack does not "
                            "let an app leave Agents & AI Apps once it is in it, so the "
                            "record cannot either")
    # A bot Aughor created arrives disabled with no tokens; keep the app's identity.
    merged = merged.model_copy(update={"client_id": stored.client_id or merged.client_id})
    # Re-verify only when a credential actually changed — an ordinary rename should not
    # depend on Slack being reachable.
    if any(getattr(merged, f) != getattr(stored, f)
           for f in ("bot_token", "app_token", "signing_secret")):
        merged = _verify(merged)
    # AO-2d — a bot that was waiting on its tokens goes live the moment it has both.
    if (not stored.enabled and stored.disabled_reason.startswith(("not installed", "installed"))
            and merged.bot_token and merged.app_token and not body.enabled):
        merged = merged.model_copy(update={"enabled": True, "disabled_reason": ""})
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
