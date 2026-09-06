"""SP-5 — the Spotlight roster over HTTP: the seam an out-of-process transport needs.

The conversational surfaces (chat rail, palette, Slack) all reach Spotlight through
`/ask` — one process, one custody. The MCP server runs OUTSIDE that process, and one
writer per `data/` is absolute, so its Spotlight tools must not touch the stores
directly. These two routes are that transport seam: GET lists the DECLARED roster
(names, descriptions, parameter schemas — what a transport registers from), POST
dispatches ONE call by name into the same tool bodies conversation runs.

Custody is unchanged by the transport: every Know/Guide entry is a read, every Act
entry stages into the one inbox or applies a self-scoped preference — the roster
cannot express anything else, so neither can this route. Auth is the API's normal
front door (`/spotlight` is deliberately NOT an exempt prefix), org scope rides the
identity contextvars, and an unknown tool is refused naming the roster.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["spotlight"])


def _roster(connection_id: str):
    from aughor.agent.spotlight_roster import spotlight_roster
    return spotlight_roster(connection_id)


@router.get("/spotlight/tools")
def list_spotlight_tools(connection_id: str = ""):
    """The declared roster, as a transport would register it.

    Descriptions and schemas are static declarations — the same for every
    connection — so the binding argument only shapes closures, never the listing.
    """
    tools = _roster(connection_id or "roster-listing")
    return {"count": len(tools),
            "tools": [{"name": t.name, "description": t.description,
                       "parameters": t.parameters} for t in tools]}


class SpotlightCall(BaseModel):
    """One tool invocation. `connection_id` is the binding conversation supplies by
    closure; an outside transport must say it out loud."""
    connection_id: str = ""
    args: dict = Field(default_factory=dict)
    session_id: Optional[str] = None


@router.post("/spotlight/tools/{tool_name}")
def call_spotlight_tool(tool_name: str, body: SpotlightCall) -> Any:
    tools = {t.name: t for t in _roster(body.connection_id)}
    spec = tools.get(tool_name)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"no Spotlight tool named {tool_name!r}; the roster is: "
                   + ", ".join(sorted(tools)))
    try:
        return {"tool": tool_name, "result": spec.run(dict(body.args or {}))}
    except Exception as exc:  # noqa: BLE001 — a tool that raises is a result (tool-loop law)
        from aughor.kernel.errors import tolerate
        tolerate(exc, "spotlight route: tool raised — relayed as a refusal",
                 counter="spotlight_route.tool_error")
        return {"tool": tool_name,
                "result": {"error": f"{type(exc).__name__}: {exc}"}}
