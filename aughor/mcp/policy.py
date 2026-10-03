"""DE-2b — what each MCP tool and each API route an agent reaches NEEDS: `read`, `run` or `act`.

Shared by the MCP server (which hides a disallowed tool from `tools/list` and refuses it by
name) and the API (which enforces the policy on every request the MCP client marks as its
own), so the two never disagree about what a tool is. The codes are stable: a client can
match on them.
"""
from __future__ import annotations

from typing import Literal, Optional

from mcp.types import ToolAnnotations

from aughor.mcp.client import AGENT_HEADER, AGENT_MARK, TOOL_HEADER  # noqa: F401 — the one spelling

Level = Literal["read", "run", "act"]

#: Stable refusal codes.
CODE_LEVEL = "AGENT_LEVEL_DENIED"            # the policy's level is below what the tool needs
CODE_TOOL = "AGENT_TOOL_DENIED"              # the tool is not on the organisation's allowlist
CODE_CONNECTION = "AGENT_CONNECTION_DENIED"  # the connection is not on the organisation's allowlist
CODE_SELF_SET = "AGENT_POLICY_NOT_SELF_SET"  # an agent tried to set its own policy
ERROR = "agent_policy_denied"

#: The eighteen static tools, by what they need. `run` spends model calls or starts work;
#: `act` changes something. A tool missing here is a registration mistake a test catches.
TOOL_LEVELS: dict[str, Level] = {
    "list_connections": "read",
    "ask": "run",
    "deep_analysis": "run",
    "get_investigation": "read",
    "get_metric": "read",
    "list_findings": "read",
    "get_briefing": "run",          # POST /exploration/{c}/briefing may spend a model call to synthesise
    "explore": "run",
    "list_jobs": "read",
    "get_job": "read",
    "cancel_job": "act",
    "search_graph": "read",
    "describe_entity": "read",
    "get_table_health": "read",
    "list_trusted_queries": "read",
    "list_runs": "read",
    "inspect_run": "read",
    "read_run_span": "read",
}

#: API routes an agent reaches whose method alone does not say what they need (a POST that
#: only reads, a POST that spends, a POST that changes). Everything else: GET/HEAD/OPTIONS
#: are `read`; any other method is `act` — the conservative reading of an unmapped write.
ROUTE_LEVELS: dict[tuple[str, str], Level] = {
    ("POST", "/chat"): "run",
    ("POST", "/investigate"): "run",
    ("POST", "/exploration/{conn_id}/start"): "run",
    ("POST", "/exploration/{conn_id}/briefing"): "run",
    ("POST", "/jobs/{job_id}/cancel"): "act",
    ("POST", "/automations/{automation_id}/run"): "act",
}

#: Spotlight's roster: the Act limb's tools stage changes for a person; everything else on the
#: roster reads. Kept here beside the route map so the API's gate and the MCP server's list
#: agree without the API having to be asked.
SPOTLIGHT_ACT_TOOLS: frozenset[str] = frozenset({
    "set_preference", "draft_agent", "draft_automation", "edit_automation", "draft_monitor",
    "draft_brief", "pause_or_resume_automation", "set_agent_limit", "propose_agent_grant",
})


def spotlight_tool_level(name: str) -> Level:
    return "act" if name in SPOTLIGHT_ACT_TOOLS else "read"


def route_level(method: str, template: str, tool_name: Optional[str] = None) -> Level:
    """What a request to this route needs. A Spotlight call is classified by the tool it names;
    an automation run is an act; the rest by the map, then by method."""
    m = method.upper()
    if template.startswith("/spotlight/tools/"):
        name = template.rsplit("/", 1)[-1]
        if name.startswith("{") and tool_name:
            name = tool_name
        return spotlight_tool_level(name)
    if (m, template) in ROUTE_LEVELS:
        return ROUTE_LEVELS[(m, template)]
    if m in ("GET", "HEAD", "OPTIONS"):
        return "read"
    return "act"


def tool_level(name: str) -> Level:
    """What an MCP tool needs: a static tool by its row, a Spotlight tool by the roster's split,
    anything else (an automation) an act."""
    if name in TOOL_LEVELS:
        return TOOL_LEVELS[name]
    if name in SPOTLIGHT_ACT_TOOLS:
        return "act"
    return "act"


def tool_annotations(level: Level) -> ToolAnnotations:
    """The MCP hints a client reads before calling: a `read` tool is read-only; an `act` tool is
    destructive in the protocol's sense (it changes something outside the conversation); a
    `run` tool is neither read-only nor destructive — it spends, and starts work."""
    if level == "read":
        return ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)
    if level == "act":
        return ToolAnnotations(readOnlyHint=False, destructiveHint=True)
    return ToolAnnotations(readOnlyHint=False, destructiveHint=False)


def refusal(code: str, *, tool: Optional[str], policy_level: str, required: Optional[str] = None,
            connection: Optional[str] = None) -> dict:
    """The refusal body, the same from the API and from the MCP server."""
    body: dict = {"error": ERROR, "code": code, "tool": tool, "policy_level": policy_level}
    if required:
        body["required_level"] = required
    if connection:
        body["connection"] = connection
    body["hint"] = {
        CODE_LEVEL: f"this organisation's agent policy is '{policy_level}'; the tool needs '{required}'. "
                    "A person with ADMIN_MANAGE_ORG can raise it at PUT /org-settings/agent-policy.",
        CODE_TOOL: "the tool is not on this organisation's agent allowlist.",
        CODE_CONNECTION: f"connection {connection!r} is not on this organisation's agent allowlist.",
        CODE_SELF_SET: "an agent cannot set its own policy; a person does, at PUT /org-settings/agent-policy.",
    }.get(code, "")
    return body
