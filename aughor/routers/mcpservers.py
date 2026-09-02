"""VA-9d — the allowlist as an API: write a server down, ask it what it offers.

Registering a server is the single most consequential write on this surface — it is how a
destination enters a deployment that reaches nothing by default — so the routes are shaped
to make that act deliberate and legible rather than convenient.

**Discovery is a separate call from registration.** A `POST` that also went out and talked
to the server would make "save this address" and "run code against it" one gesture, and a
typo'd command would be executed before anyone had read the row back. So a new server
arrives with an empty roster and someone presses Discover.

**Nothing here calls a tool.** The one door is `mcpservers/call.py`, reached by a chain
step; a `POST /mcp-servers/{id}/tools/{name}` here would be a second way through, and every
gate that lives at the door would then be a gate one caller can skip. The routes read,
write and discover — they do not invoke.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from aughor.mcpservers import store
from aughor.mcpservers.discover import TooManyTools, discover, health
from aughor.mcpservers.models import CALLABLE, McpServer
from aughor.mcpservers.session import McpUnreachable

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mcp-servers"])


class ServerRequest(BaseModel):
    """The authored half of a server row.

    Every field the model carries that a person may set is here. DS-14's lesson, in HTTP:
    a field missing from the REQUEST model is accepted, echoed back, and silently dropped —
    200, and the value never persisted. A new field on `McpServer` belongs here in the same
    change.
    """

    name: str = ""
    transport: str = "http"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict = Field(default_factory=dict)
    url: str = ""
    auth_header: str = ""
    enabled: bool = True


def _server_or_404(server_id: str) -> McpServer:
    server = store.get_server(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return server


def _view(server: McpServer) -> dict:
    """A server plus its roster, as every surface reads it.

    The roster's age rides along in the same object rather than being fetchable
    separately — a client that had to make a second call to learn how stale a list is, is a
    client that will render the list without it.
    """
    tools, discovered_at = store.get_roster(server.id)
    return {
        **server.to_safe_dict(),
        "discovered_at": discovered_at,
        "tool_count": len(tools),
        "callable_count": sum(1 for t in tools if t.disposition == CALLABLE),
        "tools": [t.model_dump() for t in tools],
    }


@router.get("/mcp-servers")
def list_servers() -> dict:
    """Every server this deployment may reach. An EMPTY list is the normal fresh state."""
    return {"servers": [_view(s) for s in store.list_servers()]}


@router.post("/mcp-servers")
def create_server(body: ServerRequest) -> dict:
    """Write a server down. Nothing is contacted — see the module docstring."""
    try:
        server = McpServer(**body.model_dump())
    except ValidationError as exc:
        # The model's own transport rules, surfaced as the 400 they are rather than the 500
        # an unhandled ValidationError would become.
        raise HTTPException(status_code=400, detail=_first_error(exc)) from exc
    return _view(store.save_server(server))


@router.put("/mcp-servers/{server_id}")
def update_server(server_id: str, body: ServerRequest) -> dict:
    """Replace the authored fields of a server, keeping its id, roster and timestamps.

    An empty `auth_header` in the body means "leave it alone", not "clear it". The field is
    never returned by any read — it is dropped, not masked — so a client round-tripping this
    object cannot send back what it was never given, and treating the absence as a clear
    would erase the credential on every rename. Clearing is `auth_header: "-"`, stated in
    the model's own vocabulary rather than left as a trick.
    """
    existing = _server_or_404(server_id)
    fields = body.model_dump()
    if not fields.get("auth_header"):
        fields["auth_header"] = existing.auth_header
    elif fields["auth_header"] == "-":
        fields["auth_header"] = ""
    try:
        updated = McpServer(**fields, id=existing.id, created_at=existing.created_at)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_first_error(exc)) from exc
    return _view(store.save_server(updated))


@router.delete("/mcp-servers/{server_id}")
def remove_server(server_id: str) -> dict:
    """Forget a server and its roster. A step naming it will refuse at the door, by name."""
    if not store.delete_server(server_id):
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"deleted": server_id}


@router.post("/mcp-servers/{server_id}/discover")
def discover_server(server_id: str) -> dict:
    """Ask the server what it offers, classify every tool, replace the roster.

    A server that is unreachable answers 502 rather than 500: the failure is upstream and
    the sentence says whose. A 500 here would send a reader to read OUR logs about somebody
    else's machine.
    """
    server = _server_or_404(server_id)
    try:
        discover(server)
    except TooManyTools as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except McpUnreachable as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{server.name or server.id} could not be reached: {exc}") from exc
    return _view(server)


@router.get("/mcp-servers/{server_id}/health")
def server_health(server_id: str) -> dict:
    """Can we reach it right now? A LIVE probe, unlike the roster — this is the button a
    person presses when that is exactly the question, and a cached answer answers a
    different one. It refreshes the roster on the way through, so a green health check and
    a stale list cannot disagree."""
    return {"server_id": server_id, **health(_server_or_404(server_id))}


def _first_error(exc: ValidationError) -> str:
    """One sentence from a pydantic error — the model's own message, not a summary of it."""
    errors = exc.errors()
    if not errors:
        return "that server record is not valid"
    msg = str(errors[0].get("msg", "")).replace("Value error, ", "")
    return msg or "that server record is not valid"
