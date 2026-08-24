"""The active user-agent for the current request — a ContextVar, so the whole
answer pipeline (including ContextThreadPoolExecutor workers and asyncio.to_thread
context sections) sees one consistent agent without threading a parameter through
every layer. Set by the /ask door, read at the two slice-1 seams: the prompt
brief and the document-retrieval scope."""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Optional

from aughor.custom_agents.models import UserAgent

_active: contextvars.ContextVar[Optional[UserAgent]] = contextvars.ContextVar(
    "aughor_user_agent", default=None
)


@dataclass
class _Activation:
    """What has to be undone when the agent is released.

    A plain ``contextvars.Token`` until VA-8: activating an agent now also arms that
    agent's per-run token cap, and the two have to come down together. Structural rather
    than a second call every caller has to remember — "activating an agent" and
    "activating its guardrails" being separable is exactly how a governance plane ends up
    configured and unenforced. No call site changed: nobody inspects this, they only pass
    it back to `release_agent`.
    """

    agent_token: contextvars.Token
    budget_token: Any = None


def activate_agent(agent: UserAgent) -> "_Activation":
    token = _active.set(agent)
    budget_token = None
    try:
        from aughor.govern.guardrails import arm_run_cap, policy_for
        budget_token = arm_run_cap(policy_for(agent.id))
    except Exception as exc:                # noqa: BLE001 — a cap that cannot be armed
        # must not stop the agent from running; it is a ceiling, not a gate.
        import logging
        logging.getLogger(__name__).warning(
            "guardrail run cap not armed for agent %s: %s", agent.id, exc)
    return _Activation(agent_token=token, budget_token=budget_token)


def release_agent(token: "_Activation") -> None:
    # Tolerant of a bare ContextVar token: `activate_agent` returned one directly before
    # VA-8, and a caller holding an old one (a resumed run, a pickled path) must still be
    # able to put the agent down.
    if isinstance(token, _Activation):
        try:
            from aughor.govern.guardrails import disarm_run_cap
            disarm_run_cap(token.budget_token)
        except Exception as exc:            # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "releasing an agent's guardrail cap; the agent is still released",
                     counter="guardrails.disarm")
        _active.reset(token.agent_token)
        return
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
