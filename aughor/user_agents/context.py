"""The active user-agent for the current request — a ContextVar, so the whole
answer pipeline (including ContextThreadPoolExecutor workers and asyncio.to_thread
context sections) sees one consistent agent without threading a parameter through
every layer. Set by the /ask door, read at the two slice-1 seams: the prompt
brief and the document-retrieval scope."""
from __future__ import annotations

import contextvars
from typing import Optional

from aughor.user_agents.models import UserAgent

_active: contextvars.ContextVar[Optional[UserAgent]] = contextvars.ContextVar(
    "aughor_user_agent", default=None
)


def activate_agent(agent: UserAgent) -> contextvars.Token:
    return _active.set(agent)


def release_agent(token: contextvars.Token) -> None:
    _active.reset(token)


def current_agent() -> Optional[UserAgent]:
    return _active.get()


def agent_brief_block() -> str:
    """The active agent's pinned instructions as a leading prompt block
    (rules_block-style). Empty string when no agent is active — the seam is
    inert on the default path."""
    agent = current_agent()
    if agent is None or not agent.instructions.strip():
        return ""
    return (
        f"AGENT BRIEF — you are operating as the user-defined agent '{agent.name}'.\n"
        "Follow these standing instructions where they apply; they refine domain "
        "focus and presentation, and never override safety or grounding rules:\n"
        f"{agent.instructions.strip()}\n\n"
    )


def agent_pack_ids() -> list[str]:
    """The active agent's explicit pack bindings ([] = none / no agent).

    A PREFERENCE that restricts pack selection to these packs — never a
    deploy-gate bypass (the pinned-binding requirement in packs/intake.py
    applies unchanged). An agent without pack bindings leaves the connection's
    normal pack steering untouched (packs are operator-deployed infrastructure,
    not per-agent context like documents)."""
    agent = current_agent()
    return list(agent.pack_ids) if agent is not None else []


def agent_doc_ids() -> Optional[set[str]]:
    """The active agent's document scope.

    None  → no agent active: retrieval is unrestricted (default behavior).
    set() → an agent is active: retrieval is restricted to ITS documents —
            an agent with no bound documents sees none (its context is what
            its creator gave it, fail-closed).
    """
    agent = current_agent()
    if agent is None:
        return None
    return set(agent.doc_ids)
