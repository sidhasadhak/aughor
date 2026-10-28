"""Arc ED, ED-2 (ROADMAP §3.58) — an HTTP caller as its own principal.

The HTTP transport had one door: a shared token (`AUGHOR_MCP_TOKEN`), behind which every client called the API as this
process. A caller may now present a service principal a person minted (its name and key, the API's own headers)
instead: the server asks the API who that is (`GET /ledger/v1/principals/service/me`), and when the API answers, every list and
call the caller makes runs as that principal — the API holds it to the agent policy and its grant and audits it under
its own name — and `tools/list` shows only the tools its grant admits.

A caller that presents no principal is served with the shared token as before. A name and key the API does not
recognise is refused at the door, never served as this process.
An answer is kept thirty seconds per name and key, so revoking a principal reaches a connected caller within that.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Optional

from aughor.mcp.client import SERVICE_KEY_HEADER, SERVICE_NAME_HEADER

_TTL = 30.0
_answers: dict[str, tuple[float, int, Optional[dict]]] = {}


def presented(headers: Any) -> Optional[tuple[str, str]]:
    """``(name, key)`` a request presents, or None. Reads a Starlette ``Headers`` or an ASGI scope's header list."""
    if isinstance(headers, list):
        found = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers}
    else:
        found = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    name = (found.get(SERVICE_NAME_HEADER.lower()) or "").strip()
    key = (found.get(SERVICE_KEY_HEADER.lower()) or "").strip()
    return (name, key) if name or key else None


async def answer(name: str, key: str, client) -> tuple[int, Optional[dict]]:
    """What the API says of this name and key — kept for thirty seconds, keyed by a hash, never the key itself."""
    kept_as = hashlib.sha256(f"{name}\x00{key}".encode("utf-8")).hexdigest()
    now = time.monotonic()
    kept = _answers.get(kept_as)
    if kept is not None and now - kept[0] < _TTL:
        return kept[1], kept[2]
    status, body = await client.service_principal_me(name, key)
    if status in (200, 401, 404):              # a transport failure is asked again next time, never remembered
        _answers[kept_as] = (now, status, body)
    return status, body


def forget() -> None:
    """Drop every kept answer (tests, and an operator who just revoked a key)."""
    _answers.clear()


def refused_because(status: int) -> str:
    return {401: "the service principal's name and key do not match an active principal",
            }.get(status, "the platform could not be asked who this service principal is")


def admits(grant: Optional[dict], tool: str) -> bool:
    """Whether the caller's grant admits a tool: its area named (or none named), and a propose tool's declared action
    named (or none named)."""
    if not grant:
        return True
    from aughor.mcp.policy import PROPOSED_ACTIONS, tool_area
    areas = grant.get("areas") or []
    if areas and tool_area(tool) not in areas:
        return False
    actions = grant.get("actions") or []
    proposed = PROPOSED_ACTIONS.get(tool)
    return not (actions and proposed and proposed not in actions)
