"""How an outside caller reaches a custom agent — the doors of Arc AO-5, and the one fold
that every headless door shares.

A door hands a question to the ask door AS the agent (`agent_id`), names the caller as a
principal the identity plane can attribute (`principal_ref`, RC-4), and folds the SSE
stream into one answer: the headline, the SQL that ran, the rows, the receipt. The fold is
the same for the HTTP door, the webhook, the A2A endpoint and the Teams reply — one copy,
so four doors cannot drift on what "the answer" is.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

#: The caller's provider prefixes, as the identity plane reads them (`identity/models.py`).
PRINCIPAL_PROVIDERS = ("api", "slack", "web", "automation", "system")


def principal_for(door: str, who: str = "") -> str:
    """`api:<door>:<who>` — attributable, never trusted over a real session (RC-4)."""
    who = re.sub(r"[^A-Za-z0-9._@-]", "", who or "")[:64] or "anonymous"
    return f"api:{door}:{who}"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s[:40] or "agent"


def mcp_tool_name(agent) -> str:
    """The tool an MCP client sees for this agent: `ask_<slug>`."""
    return f"ask_{slug(getattr(agent, 'name', '') or getattr(agent, 'id', ''))}"


async def fold_ask(*, agent_id: str, question: str, connection_id: str = "",
                   principal_ref: str = "", session_id: str = "", depth: str = "quick",
                   max_rows: int = 200) -> dict[str, Any]:
    """Run one question AS the agent through the ask door and fold the stream.

    Every frame the stream carries is the stream's business; the fold keeps the few a
    caller with no screen can use: the headline (the final one, else the deltas joined),
    the SQL that ran, the columns and up to ``max_rows`` rows, the receipt and the
    investigation id so a verdict can follow. An error frame is the answer's `error`.
    """
    from aughor.routers.investigations import AskRequest, build_ask_stream
    req = AskRequest(question=question, connection_id=connection_id or "workspace",
                     agent_id=agent_id, principal_ref=principal_ref or None,
                     session_id=session_id or "", depth=depth, allow_clarify=False)
    out: dict[str, Any] = {"agent_id": agent_id, "question": question, "headline": "",
                           "sql": "", "columns": [], "rows": [], "row_count": None,
                           "receipt_id": "", "investigation_id": "", "error": "",
                           "truncated": False, "frames": 0}
    deltas: list[str] = []
    async for sse in build_ask_stream(req, None):
        for line in str(sse).splitlines():
            if not line.startswith("data:"):
                continue
            try:
                frame = json.loads(line[5:].strip() or "{}")
            except json.JSONDecodeError as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "a door's SSE frame was not JSON; the fold skips it and keeps reading",
                         counter="agents.door_frame_unparsed")
                continue
            out["frames"] += 1
            t = frame.get("type")
            if t == "headline":
                out["headline"] = str(frame.get("headline") or "")
            elif t == "headline_delta":
                deltas.append(str(frame.get("headline") or frame.get("delta") or ""))
            elif t == "sql":
                out["sql"] = str(frame.get("sql") or "")
            elif t == "columns" and not out["columns"]:
                out["columns"] = list(frame.get("columns") or [])
            elif t == "rows":
                rows = list(frame.get("rows") or [])
                room = max_rows - len(out["rows"])
                if room > 0:
                    out["rows"].extend(rows[:room])
                if len(rows) > room:
                    out["truncated"] = True
                if frame.get("row_count") is not None:
                    out["row_count"] = frame.get("row_count")
            elif t == "receipt_id":
                out["receipt_id"] = str(frame.get("receipt_id") or frame.get("id") or "")
            elif t == "error":
                out["error"] = str(frame.get("message") or frame.get("error") or "error")
            elif t == "done":
                out["investigation_id"] = str(frame.get("investigation_id") or out["investigation_id"])
            if frame.get("investigation_id") and not out["investigation_id"]:
                out["investigation_id"] = str(frame["investigation_id"])
    if not out["headline"] and deltas:
        # Deltas may be cumulative or incremental; the longest tail is the whole headline.
        out["headline"] = max(deltas, key=len) if any(d.startswith(deltas[0][:3]) for d in deltas[1:]) \
            else "".join(deltas)
    if out["row_count"] is None:
        out["row_count"] = len(out["rows"]) if out["rows"] else None
    return out


def doors_for(agent, *, public_api: str = "", public_web: str = "") -> dict[str, Any]:
    """Every door this agent has, each with its state — what the Doors tab lists."""
    from aughor.custom_agents.keys import agent_key_issued_at
    issued = agent_key_issued_at(agent.id)
    api = (public_api or "").rstrip("/")
    web = (public_web or "").rstrip("/")
    key_hint = ("issue a key on the agent's Doors tab" if not issued else "")
    return {
        "mcp": {"state": "open" if agent.enabled else "paused", "tool": mcp_tool_name(agent),
                "how": "the Aughor MCP server registers one tool per enabled custom agent at "
                       "start (`python -m aughor.mcp`); its caller is a principal the "
                       "verdict and spend records attribute"},
        "http": {"state": "open" if issued and agent.enabled else ("no key" if not issued else "paused"),
                 "key_issued_at": issued,
                 "url": f"{api}/doors/agents/{agent.id}/ask" if api else f"/doors/agents/{agent.id}/ask",
                 "hint": key_hint},
        "embed": {"state": "open" if issued and agent.enabled else "needs the HTTP key",
                  "url": f"{web}/embed/agent/{agent.id}" if web else f"/embed/agent/{agent.id}"},
        "webhook": {"state": "open" if issued and agent.enabled else "needs the HTTP key",
                    "url": f"{api}/doors/agents/{agent.id}/webhook" if api else f"/doors/agents/{agent.id}/webhook"},
        "a2a": {"state": "open" if issued and agent.enabled else "needs the HTTP key",
                "card": f"{api}/.well-known/agent.json" if api else "/.well-known/agent.json",
                "url": f"{api}/doors/a2a/{agent.id}" if api else f"/doors/a2a/{agent.id}"},
    }


def a2a_card(agents: list, *, public_api: str = "") -> dict[str, Any]:
    """An Agent Card (A2A): Aughor as one agent whose SKILLS are the enabled custom agents,
    each reachable at its own endpoint with the same bearer key as the HTTP door."""
    api = (public_api or "").rstrip("/")
    return {
        "name": "Aughor",
        "description": "Governed answers over connected data — each skill is a custom agent "
                       "with its own scope and stance; every answer carries its SQL and a receipt.",
        "url": f"{api}/doors/a2a" if api else "/doors/a2a",
        "version": "1",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "authentication": {"schemes": ["bearer"],
                           "credentials": "the agent's HTTP key, issued on its Doors tab"},
        "defaultInputModes": ["text"], "defaultOutputModes": ["text", "application/json"],
        "skills": [{
            "id": a.id, "name": a.name, "description": a.purpose or (a.instructions or "")[:200],
            "tags": [t for t in ("data", a.connection_id, a.schema_scope) if t],
            "url": f"{api}/doors/a2a/{a.id}" if api else f"/doors/a2a/{a.id}",
        } for a in agents if getattr(a, "enabled", True)],
    }


def a2a_task(task_id: str, answer: dict, *, context_id: str = "") -> dict[str, Any]:
    """An A2A Task for one folded answer: completed with the headline as a text part and
    the SQL + rows as a data part; failed when the fold carried an error."""
    failed = bool(answer.get("error"))
    parts: list[dict[str, Any]] = [{"kind": "text", "text": answer.get("error") or answer.get("headline") or ""}]
    if not failed:
        parts.append({"kind": "data", "data": {
            "sql": answer.get("sql"), "columns": answer.get("columns"), "rows": answer.get("rows"),
            "row_count": answer.get("row_count"), "truncated": answer.get("truncated"),
            "receipt_id": answer.get("receipt_id"), "investigation_id": answer.get("investigation_id")}})
    return {
        "id": task_id, "contextId": context_id or task_id,
        "status": {"state": "failed" if failed else "completed"},
        "artifacts": [] if failed else [{"artifactId": f"{task_id}-answer", "name": "answer", "parts": parts}],
        "history": [],
    }


def text_of_message(message: Optional[dict]) -> str:
    """The text parts of an A2A message, joined."""
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or []
    return " ".join(str(p.get("text") or "") for p in parts
                    if isinstance(p, dict) and (p.get("kind") == "text" or "text" in p)).strip()
