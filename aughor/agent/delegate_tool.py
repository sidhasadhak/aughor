"""VA-2 — `delegate_task`: the tool that turns configured agents into usable specialists.

Before this, a custom agent could only be IMPERSONATED: `/ask` took an `agent_id` and the
whole turn ran as that agent. It was configuration you could put on, not a colleague you
could ask. This is the other half — the conversation hands a task to a named agent and
gets its answer back, mid-turn, without the user leaving the thread.

Three rules this module exists to hold:

**The roster costs a line each.** Every candidate agent appears in the supervisor's prompt,
so the roster reads `purpose`, never `instructions`. Listing full instructions is precisely
how a prompt becomes mostly other agents' prose — measured here once at 65% of a template
carrying nothing for the question. Agents without a purpose get a bounded fallback, never
an unbounded one.

**A delegate cannot out-reach its own definition.** The delegate answers on ITS
`connection_id` and `schema_scope`, not the caller's. Delegation must not become a way to
read a warehouse the agent was never bound to — the binding is the security boundary, and
it is enforced here rather than trusted to the prompt.

**The result is always an array.** Even for one target. Fan-out is the obvious next step
and a caller that special-cases the single-target shape is a caller that breaks when it
arrives.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from aughor.agent.delegation import DelegationContext, DelegationRefused

logger = logging.getLogger(__name__)

#: A purpose we synthesise for an agent that never set one. Bounded on purpose: the
#: fallback must not reintroduce the unbounded-prose problem `purpose` exists to prevent.
_FALLBACK_PURPOSE_CHARS = 140


def _fallback_purpose(agent) -> str:
    line = (agent.instructions or "").strip().splitlines()
    first = line[0].strip() if line else ""
    if not first:
        return "No purpose set — this agent has not described what it is for."
    return (first[:_FALLBACK_PURPOSE_CHARS] + "…") if len(first) > _FALLBACK_PURPOSE_CHARS else first


def delegation_targets() -> list[dict]:
    """Every agent this conversation may hand work to, as the supervisor will read them.

    Custom agents only for the roster's *default* body: charters already act through the
    tools in this same roster (a charter is platform work with a job lifecycle, so
    delegating to one returns a job handle rather than an answer, and mixing the two
    shapes in one tool result is how a caller learns to trust neither).
    """
    from aughor.custom_agents import list_agents

    out: list[dict] = []
    for a in list_agents():
        if not a.enabled:
            continue
        out.append({
            "id": a.id,
            "name": a.name,
            "purpose": (a.purpose or "").strip() or _fallback_purpose(a),
            "connection_id": a.connection_id,
            "schema_scope": a.schema_scope,
        })
    return out


def roster_block(targets: list[dict]) -> str:
    """The `<specialized_agents>` section of the supervisor's prompt. One line each."""
    if not targets:
        return ""
    lines = [f"- {t['name']} (id: {t['id']}) — {t['purpose']}" for t in targets]
    return ("You may delegate to these agents with delegate_task:\n"
            + "\n".join(lines)
            + "\nDelegate when an agent's purpose matches the task better than your own "
              "tools do. Each answers on its own data binding, so it may see things you "
              "cannot. Do not delegate work you can already do.")


def _run_one(target: dict, task: str, ctx: DelegationContext, *,
             answer: Callable[..., dict], emit=None, session_id: str = "",
             caller_connection_id: str = "") -> dict:
    """One hop. Returns the row shape `delegate_task` always returns."""
    agent_id, name = target["id"], target["name"]

    # The delegate's OWN binding wins. Falling back to the caller's connection only when
    # the agent is unbound (which is what an empty connection_id means: "answer on the
    # connection you were asked on").
    conn = target.get("connection_id") or caller_connection_id

    child = ctx.child(agent_id)
    framed = task if not target.get("schema_scope") else (
        f"{task}\n\n(Answer within schema '{target['schema_scope']}'.)")

    try:
        result = answer(conn, {"question": framed}, emit=emit, session_id=session_id)
    except Exception as exc:                      # a delegate failing is a RESULT
        logger.warning("delegate %s failed: %s", agent_id, exc, exc_info=True)
        return {"agent_name": name, "response": f"{name} could not answer: {exc}",
                "usage": {}, "bailed": False, "refused": False, "error": True}

    # A delegate that errored inside the pipeline reports as an error, not as an answer —
    # a well-formed wrong answer is worse than a stated failure.
    if isinstance(result, dict) and result.get("error"):
        return {"agent_name": name, "response": str(result["error"]),
                "usage": {}, "bailed": False, "refused": False, "error": True}

    usage = (result or {}).get("usage") or {}
    ctx.spend(steps=1, usd=float(usage.get("cost_usd") or 0.0))
    child.spend(steps=1)

    return {
        "agent_name": name,
        "agent_id": agent_id,
        "response": (result or {}).get("answer") or (result or {}).get("outcome") or "",
        "sql": (result or {}).get("sql") or "",
        "usage": usage,
        "bailed": False,
        "refused": False,
        "depth": child.depth,
        "agent_path": "/".join(child.agent_path),
    }


def delegate_task(args: dict, *, ctx: DelegationContext, answer: Callable[..., dict],
                  emit=None, session_id: str = "",
                  caller_connection_id: str = "") -> list[dict]:
    """Hand a task to one or more named agents. ALWAYS returns a list."""
    task = (args.get("task") or "").strip()
    wanted: list[str] = [str(t) for t in (args.get("target_agents") or []) if str(t).strip()]

    if not task:
        return [DelegationRefused("NO_TASK", "No task was supplied to delegate.").as_result()]
    if not wanted:
        return [DelegationRefused(
            "NO_TARGET", "No target agent was named. Pick one from the roster.").as_result()]

    targets = {t["id"]: t for t in delegation_targets()}
    # Names are what a model actually writes; accept either and resolve to the id.
    by_name = {t["name"].lower(): t for t in targets.values()}

    rows: list[dict] = []
    for want in wanted:
        target = targets.get(want) or by_name.get(want.lower())
        try:
            ctx.check(target["id"] if target else want,
                      known_ids=set(targets) if target is None else None)
        except DelegationRefused as exc:
            rows.append(exc.as_result(agent_name=(target or {}).get("name", want)))
            continue
        rows.append(_run_one(target, task, ctx, answer=answer, emit=emit,
                             session_id=session_id,
                             caller_connection_id=caller_connection_id))
    return rows


_DELEGATE_PARAMS = {
    "type": "object",
    "properties": {
        "task": {"type": "string",
                 "description": "What the agent should do, stated as a complete question "
                                "or instruction. The agent does not see this conversation, "
                                "so include what it needs."},
        "target_agents": {"type": "array", "items": {"type": "string"},
                          "description": "Agent names or ids from the roster. More than "
                                         "one runs them all and returns every answer."},
    },
    "required": ["task", "target_agents"],
}


def delegation_tools(connection_id: str, *, ctx: Optional[DelegationContext] = None,
                     emit=None, session_id: str = "") -> list[Any]:
    """`delegate_task`, or nothing when there is no one to delegate to.

    An empty roster returns an empty list rather than a tool that always refuses: a tool
    the model can see is a tool it will try, and a roster of nobody is not a capability.
    """
    from aughor.agent.converse_tools import answer_question
    from aughor.agent.tool_loop import ToolSpec

    targets = delegation_targets()
    if not targets:
        return []

    live = ctx or DelegationContext()
    return [ToolSpec(
        name="delegate_task",
        description=(
            "Hand a task to one of this workspace's specialist agents and get its answer "
            "back. Each agent has its own data binding and standing instructions, so it "
            "may see things you cannot. Name one or more agents from the roster in the "
            "system prompt. Returns one result per agent, always as a list. Do not "
            "delegate work your own tools already cover."
        ),
        parameters=_DELEGATE_PARAMS,
        run=lambda a: delegate_task(a, ctx=live, answer=answer_question, emit=emit,
                                    session_id=session_id,
                                    caller_connection_id=connection_id),
    )]
