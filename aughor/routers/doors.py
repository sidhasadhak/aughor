"""The headless doors to a custom agent (Arc AO-5): HTTP, webhook, A2A, Teams.

Every route here is reached by a caller with no session, so each carries its own
credential and is listed under `_AUTH_EXEMPT` by its own prefix (`/doors/`,
`/.well-known/`): the agent's key for the HTTP, webhook and A2A doors; the Bot Framework's
signature for Teams. Nothing here opens the rest of the API — a caller holding an agent's
key is that agent's caller, and the answer it gets is the agent's, with the agent's own
brief, documents, packs and grants (VA-9c's rule: grants only ever propose).

The caller is attributed as a principal (`principal_ref`, RC-4) — `api:http:<asker>`,
`api:webhook:<asker>`, `api:a2a:<asker>`, `teams:<user id>` — so verdicts and spend know who
asked, and never trusted over a real session.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["doors"])

_REFUSED = "refused: this door needs the agent's key as a bearer token"


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else ""


def _agent_or_401(agent_id: str, request: Request):
    """The agent, once the bearer key matches. Every refusal is the same 401 — a wrong key
    and an unknown agent must look identical to a caller probing for agents."""
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.keys import agent_key_matches
    token = _bearer(request)
    agent = get_agent(agent_id)
    if agent is None or not token or not agent_key_matches(agent_id, token):
        raise HTTPException(status_code=401, detail=_REFUSED)
    if not agent.enabled:
        raise HTTPException(status_code=409, detail=f"agent '{agent.name}' is paused; it answers nothing")
    return agent


def _public_api() -> str:
    return os.environ.get("AUGHOR_PUBLIC_API_URL", "").strip().rstrip("/")


class DoorAsk(BaseModel):
    question: str
    #: Who is asking, in the caller's words (a user id, an email, a service name) — becomes
    #: the principal the answer is attributed to. Optional; "anonymous" when absent.
    asker: str = ""
    connection_id: str = ""
    session_id: str = ""
    depth: str = "quick"


# ── AO-5b · HTTP ─────────────────────────────────────────────────────────────────

@router.post("/doors/agents/{agent_id}/ask")
async def door_ask(agent_id: str, body: DoorAsk, request: Request, stream: bool = False):
    """Ask the agent, as itself. JSON by default — the folded answer: headline, SQL, rows,
    receipt — or the ask door's own SSE with ``?stream=1`` for a caller that renders it."""
    from aughor.custom_agents.reach import fold_ask, principal_for
    agent = _agent_or_401(agent_id, request)
    principal = principal_for("http", body.asker)
    if stream:
        from fastapi.responses import StreamingResponse
        from aughor.routers.investigations import AskRequest, build_ask_stream
        req = AskRequest(question=body.question, connection_id=body.connection_id or agent.connection_id or "workspace",
                         agent_id=agent.id, principal_ref=principal, session_id=body.session_id,
                         depth=body.depth if body.depth in ("quick", "deep", "auto") else "quick",
                         allow_clarify=False)
        return StreamingResponse(build_ask_stream(req, None), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await fold_ask(agent_id=agent.id, question=body.question,
                          connection_id=body.connection_id or agent.connection_id,
                          principal_ref=principal, session_id=body.session_id,
                          depth=body.depth if body.depth in ("quick", "deep", "auto") else "quick")


# ── AO-5d · an inbound webhook as a conversation ─────────────────────────────────

class WebhookAsk(DoorAsk):
    #: Where to POST the folded answer when the caller cannot wait on the request; the
    #: response still carries it. Nothing else is ever sent there.
    callback_url: str = ""


@router.post("/doors/agents/{agent_id}/webhook")
async def door_webhook(agent_id: str, body: WebhookAsk, request: Request):
    """A webhook that is a conversation turn: a question in, the agent's answer out — in the
    response, and to ``callback_url`` when one is given (the delivery's outcome is said)."""
    from aughor.custom_agents.reach import fold_ask, principal_for
    agent = _agent_or_401(agent_id, request)
    answer = await fold_ask(agent_id=agent.id, question=body.question,
                            connection_id=body.connection_id or agent.connection_id,
                            principal_ref=principal_for("webhook", body.asker),
                            session_id=body.session_id)
    delivered: Optional[dict[str, Any]] = None
    if body.callback_url:
        delivered = _deliver(body.callback_url, answer)
    return {**answer, "callback": delivered}


def _deliver(url: str, answer: dict) -> dict[str, Any]:
    import json
    import urllib.error
    import urllib.request
    if not url.lower().startswith(("http://", "https://")):
        return {"ok": False, "why": "callback_url must be http(s)"}
    req = urllib.request.Request(url, data=json.dumps(answer).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {"ok": 200 <= resp.status < 300, "status": resp.status}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "why": f"could not deliver: {exc}"}


# ── AO-5e · A2A ──────────────────────────────────────────────────────────────────

@router.get("/.well-known/agent.json")
def a2a_agent_card():
    """The Agent Card: Aughor's enabled custom agents as skills, each at its own endpoint."""
    from aughor.custom_agents import list_agents
    from aughor.custom_agents.reach import a2a_card
    return a2a_card(list_agents(), public_api=_public_api())


@router.post("/doors/a2a/{agent_id}")
async def a2a_send(agent_id: str, body: dict, request: Request):
    """JSON-RPC 2.0, method ``message/send`` (A2A): the message's text parts are the
    question; the result is a completed Task whose artifact carries the headline and the
    answer's data. Other methods are refused with the JSON-RPC error that names them."""
    from aughor.custom_agents.reach import a2a_task, fold_ask, principal_for, text_of_message
    rpc_id = body.get("id")
    method = str(body.get("method") or "")
    if method not in ("message/send", "tasks/send"):
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32601, "message": f"method not supported: {method or '(none)'}; "
                                                      "this agent answers `message/send`"}}
    agent = _agent_or_401(agent_id, request)
    params = body.get("params") or {}
    message = params.get("message") or {}
    question = text_of_message(message)
    if not question:
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32602, "message": "the message carries no text part"}}
    asker = str((message.get("metadata") or {}).get("asker") or params.get("asker") or "")
    answer = await fold_ask(agent_id=agent.id, question=question,
                            connection_id=agent.connection_id,
                            principal_ref=principal_for("a2a", asker),
                            session_id=str(params.get("contextId") or message.get("contextId") or ""))
    task_id = str(params.get("id") or message.get("taskId") or uuid.uuid4().hex)
    return {"jsonrpc": "2.0", "id": rpc_id,
            "result": a2a_task(task_id, answer, context_id=str(message.get("contextId") or ""))}


# ── AO-5c · Teams bot records (admin routes; behind the API's own auth) ──────────

class TeamsBotBody(BaseModel):
    name: str = ""
    agent_id: str = ""
    connection_id: str = ""
    app_id: str
    app_password: str = ""
    tenant_id: str = ""
    enabled: bool = True


@router.get("/teams-bots")
def list_teams_bots():
    from aughor.teamsbots import store
    return {"bots": [b.to_safe_dict() for b in store.list_bots()]}


@router.post("/teams-bots")
def create_teams_bot(body: TeamsBotBody):
    """Bind an Azure Bot registration (app id + password) to a custom agent. The messaging
    endpoint to set on the registration is returned — this API's public HTTPS origin plus
    `/doors/teams/{id}/messages` — and said to be missing when no origin is declared."""
    from aughor.custom_agents import get_agent
    from aughor.teamsbots import store
    if body.agent_id and get_agent(body.agent_id) is None:
        raise HTTPException(status_code=404, detail="No such agent")
    if not body.app_id.strip() or not body.app_password.strip():
        raise HTTPException(status_code=422, detail="app_id and app_password are required")
    saved = store.save_bot(store.TeamsBot(**body.model_dump()))
    base = _public_api()
    return {"bot": saved.to_safe_dict(),
            "messaging_endpoint": (f"{base}/doors/teams/{saved.id}/messages" if base.startswith("https://") else ""),
            "needs": ([] if base.startswith("https://") else
                      ["a public HTTPS origin (AUGHOR_PUBLIC_API_URL) — the Bot Framework delivers "
                       "activities only to HTTPS; set it, then put "
                       f"<origin>/doors/teams/{saved.id}/messages on the Azure Bot's Configuration"])}


@router.delete("/teams-bots/{bot_id}")
def delete_teams_bot(bot_id: str):
    from aughor.teamsbots import store
    if not store.delete_bot(bot_id):
        raise HTTPException(status_code=404, detail="no such Teams bot")
    return {"deleted": bot_id}


# ── AO-5c · Teams (Bot Framework) ────────────────────────────────────────────────

@router.post("/doors/teams/{bot_id}/messages")
async def teams_messages(bot_id: str, body: dict, request: Request):
    """The bot's messaging endpoint. A signed `message` activity becomes a question to the
    bot's agent; the answer goes back through the Bot Connector at the activity's own
    serviceUrl. Anything else the Framework sends (typing, membership) is acknowledged."""
    from aughor.teamsbots import reply, store, verify
    bot = store.get_bot_decrypted(bot_id)
    if bot is None or not bot.enabled:
        raise HTTPException(status_code=404, detail="no such Teams bot")
    ok, why = verify.verify_activity_token(request.headers.get("authorization", ""), bot.app_id)
    if not ok:
        raise HTTPException(status_code=401, detail=f"refused: {why}")
    if str(body.get("type") or "") != "message":
        return {"ignored": str(body.get("type") or "unknown")}
    text = str(body.get("text") or "").strip()
    if not text:
        return {"ignored": "empty message"}
    from aughor.custom_agents import get_agent
    from aughor.custom_agents.reach import fold_ask
    agent = get_agent(bot.agent_id) if bot.agent_id else None
    if agent is None or not agent.enabled:
        answer = {"error": "this bot's agent is missing or paused", "headline": ""}
    else:
        who = str((body.get("from") or {}).get("id") or "")
        conv = str((body.get("conversation") or {}).get("id") or "")
        answer = await fold_ask(agent_id=agent.id, question=text,
                                connection_id=bot.connection_id or agent.connection_id,
                                principal_ref=f"teams:{who or 'unknown'}",
                                session_id=f"teams:{conv}" if conv else "")
    ok_t, token_or_why = reply.connector_token(bot.app_id, bot.app_password)
    if not ok_t:
        logger.warning("teams bot %s: %s", bot_id, token_or_why)
        return {"answered": False, "why": token_or_why, "headline": answer.get("headline", "")}
    sent, payload = reply.send_reply(
        service_url=str(body.get("serviceUrl") or ""),
        conversation_id=str((body.get("conversation") or {}).get("id") or ""),
        reply_to_id=str(body.get("id") or ""), text=reply.render_answer(answer),
        token=token_or_why, recipient=body.get("from"), from_=body.get("recipient"))
    return {"answered": sent, "why": "" if sent else str(payload.get("error") or payload),
            "headline": answer.get("headline", ""), "investigation_id": answer.get("investigation_id", "")}
