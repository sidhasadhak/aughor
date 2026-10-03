"""DE-2b — the API enforces the organisation's agent policy on every request the MCP client
marks as its own, and audits each one with its principal.

Inert for any request that does not carry the agent mark (`X-Aughor-Agent: mcp`): the web
app and every other caller are untouched, byte for byte. For a marked request:

1. the tool allowlist — the tool the client names (`X-Aughor-Tool`) must be allowed;
2. the level — what the route (and, for Spotlight, the tool) needs against the policy's;
3. the connection allowlist — the connection the request names in its path, query or body.

A refusal is a 403 with a stable code (`mcp/policy.py`). Allowed or refused, the call is
written to the Ledger as `mcp.tool_call` with the principal (org, user), the tool, the route,
the verdict and BOUNDED arguments, and the governance feed shows it under data access — the
audit page the plan asked for.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException, Request

from aughor.mcp.policy import (
    AGENT_HEADER,
    AGENT_MARK,
    CODE_CONNECTION,
    CODE_LEVEL,
    CODE_SELF_SET,
    CODE_TOOL,
    TOOL_HEADER,
    refusal,
    route_level,
)

#: Where a request names its connection. Path params first, then the query, then the body.
_CONNECTION_KEYS = ("conn_id", "connection_id", "connection")
_ARG_CAP = 160          # per value
_ARGS_CAP = 1200        # per call


def is_agent_request(request: Request) -> bool:
    return (request.headers.get(AGENT_HEADER) or "").strip().lower() == AGENT_MARK


def _bounded(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k)[:40]: _bounded(v) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [_bounded(v) for v in value[:10]]
    if isinstance(value, str):
        return value if len(value) <= _ARG_CAP else value[:_ARG_CAP] + "…"
    return value


async def _body_json(request: Request) -> Optional[dict]:
    """The JSON body when there is one. Starlette caches the body, so the handler's own
    parse still sees it; a body that is not JSON is simply not inspected."""
    if request.method in ("GET", "HEAD", "OPTIONS", "DELETE"):
        return None
    if "application/json" not in (request.headers.get("content-type") or ""):
        return None
    try:
        raw = await request.body()
        data = json.loads(raw.decode("utf-8")) if raw else None
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _connection_named(request: Request, body: Optional[dict]) -> Optional[str]:
    for source in (request.path_params or {}, dict(request.query_params), body or {}):
        for key in _CONNECTION_KEYS:
            v = source.get(key)
            if v:
                return str(v)
    return None


def _audit(request: Request, *, tool: Optional[str], allowed: bool, code: Optional[str],
           required: str, policy, connection: Optional[str], body: Optional[dict], org_id: str) -> None:
    try:
        from aughor.kernel.ledger import Ledger
        from aughor.org.context import current_user_id
        args: dict = {}
        if request.query_params:
            args["query"] = _bounded(dict(request.query_params))
        if body:
            args["body"] = _bounded(body)
        text = json.dumps(args, ensure_ascii=False)
        if len(text) > _ARGS_CAP:
            args = {"truncated": True, "head": text[:_ARGS_CAP] + "…"}
        Ledger.default().emit("mcp.tool_call", {
            "tool": tool, "method": request.method, "route": request.scope.get("route").path
            if request.scope.get("route") is not None else request.url.path,
            "actor": current_user_id() or (request.headers.get("X-Aughor-User") or "mcp"),
            "org_id": org_id, "agent": AGENT_MARK,
            "allowed": allowed, "code": code, "required_level": required, "policy_level": policy.level,
            "policy_source": policy.source, "connection": connection, "args": args,
        }, conn_id=connection)
    except Exception as exc:  # the audit must never take the call with it, but it is said
        from aughor.kernel.errors import tolerate
        tolerate(exc, "agent call audit is best-effort", counter="agent_gate.audit")


async def enforce_agent_policy(request: Request) -> None:
    """App-wide dependency: the organisation's agent policy, on marked requests only."""
    if not is_agent_request(request):
        return
    from aughor.org.context import current_org_id
    from aughor.orgsettings.agent_policy import effective_agent_policy

    org_id = current_org_id()
    policy = effective_agent_policy(org_id)
    tool = (request.headers.get(TOOL_HEADER) or "").strip() or None
    route = request.scope.get("route")
    template = getattr(route, "path", None) or request.url.path
    required = route_level(request.method, template, tool)
    body = await _body_json(request)
    connection = _connection_named(request, body)

    code: Optional[str] = None
    if template.startswith("/org-settings/agent-policy") and request.method not in ("GET", "HEAD", "OPTIONS"):
        code = CODE_SELF_SET          # an agent never sets its own policy, whatever its level
    elif tool and not policy.allows_tool(tool):
        code = CODE_TOOL
    elif not policy.allows_level(required):
        code = CODE_LEVEL
    elif not policy.allows_connection(connection):
        code = CODE_CONNECTION

    _audit(request, tool=tool, allowed=code is None, code=code, required=required, policy=policy,
           connection=connection, body=body, org_id=org_id)
    if code is not None:
        raise HTTPException(status_code=403, detail=refusal(
            code, tool=tool, policy_level=policy.level, required=required, connection=connection))
