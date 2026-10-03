"""Deleting an agent, with everything that would otherwise keep answering as it (AO-1e).

Measured 2026-10-03: ``delete_agent`` removed the row and its goldens, and nothing else.
A Slack bot bound to the agent stayed enabled — the supervisor kept its socket open and
it went on answering as an agent that no longer existed; an automation bound to it kept
``agent_id`` pointing at nothing. Both are durable intent that outlives the row, and the
repo's rule is that reversing durable intent clears the durable record before acting.

No new store. The cascade reads the three that already hold the bindings — the Slack
bot store, the automation store and the agent's own revisions in the ledger — writes
the two that must change, and returns a RECEIPT that says what moved. Revisions are
kept on purpose (supersede, do not delete): the history of how the agent was configured
is the one thing a deletion must not destroy.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def retire_agent(agent_id: str) -> Optional[dict[str, Any]]:
    """Delete ``agent_id`` and switch off what would keep running as it. ``None`` when
    there is no such agent; otherwise the receipt::

        {"deleted": id, "name": ..., "bots_disabled": [{id, name}],
         "automations_detached": [{id, name}], "revisions_kept": n}

    A cascade step that cannot run is SAID on the receipt (``*_error``), never swallowed
    into an empty list — an empty list would read as "nothing was bound".
    """
    from aughor.custom_agents.store import delete_agent, get_agent

    agent = get_agent(agent_id)
    if agent is None:
        return None
    receipt: dict[str, Any] = {
        "deleted": agent_id, "name": agent.name,
        "bots_disabled": [], "automations_detached": [], "revisions_kept": 0,
    }
    reason = f"its agent '{agent.name}' was deleted"

    # 1 · Slack bots fronting the agent go dark, and say why on the card.
    try:
        from aughor.slackbots.store import bots_for_agent, save_bot
        for bot in bots_for_agent(agent_id):
            if bot.enabled:
                save_bot(bot.model_copy(update={"enabled": False, "disabled_reason": reason}))
            receipt["bots_disabled"].append({"id": bot.id, "name": bot.name})
    except Exception as exc:                            # noqa: BLE001 — said, not hidden
        logger.warning("agent %s: slack bots not disabled: %s", agent_id, exc, exc_info=True)
        receipt["bots_disabled_error"] = str(exc)

    # 2 · Automations that run AS the agent are detached — the automation itself stays,
    #     because its schedule and effects are someone's intent too; it runs as nobody
    #     until a person binds it again. Step-level bindings are cleared with it.
    try:
        from aughor.automations.store import list_automations, upsert_automation
        for auto in list_automations():
            step_bound = any(e.agent_id == agent_id for e in auto.effects) or (
                auto.fallback_effect is not None and auto.fallback_effect.agent_id == agent_id)
            if auto.agent_id != agent_id and not step_bound:
                continue
            effects = [
                e.model_copy(update={"config": {**e.config, "agent_id": ""}})
                if e.agent_id == agent_id else e
                for e in auto.effects
            ]
            fallback = auto.fallback_effect
            if fallback is not None and fallback.agent_id == agent_id:
                fallback = fallback.model_copy(update={"config": {**fallback.config, "agent_id": ""}})
            upsert_automation(auto.model_copy(update={
                "agent_id": "" if auto.agent_id == agent_id else auto.agent_id,
                "effects": effects, "fallback_effect": fallback,
            }))
            receipt["automations_detached"].append({"id": auto.id, "name": auto.name})
    except Exception as exc:                            # noqa: BLE001
        logger.warning("agent %s: automations not detached: %s", agent_id, exc, exc_info=True)
        receipt["automations_detached_error"] = str(exc)

    # 3 · Revisions are KEPT. Counted so the receipt can say so.
    try:
        from aughor.custom_agents.revisions import list_revisions
        receipt["revisions_kept"] = len(list_revisions(agent_id))
    except Exception as exc:                            # noqa: BLE001
        logger.debug("agent %s: revision count unavailable: %s", agent_id, exc)
        receipt["revisions_kept_error"] = str(exc)

    if not delete_agent(agent_id):
        return None
    return receipt
