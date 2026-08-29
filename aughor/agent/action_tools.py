"""VA-9c — the one tool that lets an agent act, and the grant that bounds it.

Measured before building (2026-08-29): every tool an agent could call was a READ —
`run_sql`, `answer_question`, `deep_analysis`, `list_tables`, `describe_table`, plus the
platform read roster. `stage_proposal` was reachable only from an HTTP route, and
`platform_tools` is documented as "the read roster for one connection", never filtered
per agent. So VA-9's own receipt — *grant one agent `post_message`; ask it to summarise a
finding and post; the write pauses at approval* — was not merely unbuilt, it was
unreachable: an agent had no way to propose anything.

**A grant is permission to PROPOSE, never permission to EXECUTE.** That distinction is the
whole design. A granted action still lands in the resolve-once inbox (`actions/inbox.py`)
and waits for a human accept, or for a target-bound standing grant minted separately per
value. Collapsing the two would turn "this agent may suggest a refund" into "this agent
may issue refunds", which is exactly what the approvals plane exists to prevent — and the
proposal inbox already holds a live `refund_orders` row to make the point concrete.

**Named actions, never a connection's whole roster.** VA-9's rule. An agent with no grants
gets no write tool AT ALL, rather than a tool that always refuses: a tool the model can
see is a tool it will try, and every attempt spends a turn arguing with a gate.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)


def granted_actions(agent: Any) -> list[str]:
    """The action ids this agent may propose. Empty for an unbound run or no grants."""
    return [a for a in (getattr(agent, "tool_grants", None) or []) if isinstance(a, str) and a]


def action_tools(connection_id: str, *, agent: Any = None,
                 schema_name: str = "") -> list[ToolSpec]:
    """The write roster for one agent — empty unless it has been granted something.

    Returning [] rather than a refusing tool is deliberate: the model picks from what it
    can see, so an always-refusing tool costs a turn every time it is tempted.
    """
    grants = granted_actions(agent)
    if not grants:
        return []

    def _propose(args: dict) -> dict:
        return propose_one(
            connection_id, schema_name=schema_name, grants=grants,
            action_id=str(args.get("action_id") or ""),
            params=args.get("params") if isinstance(args.get("params"), dict) else {},
            reasoning=str(args.get("reasoning") or ""),
            proposer=f"agent:{getattr(agent, 'id', '') or 'unknown'}",
        )

    return [ToolSpec(
        name="propose_action",
        description=(
            "Propose one governed action from this connection's declared roster — for "
            "example posting a finding, or opening a ticket. NOTHING happens when you "
            "call this: the proposal is staged for a human to accept or reject, and only "
            "an accept executes it. Use it when the user has asked for something to be "
            "DONE rather than answered, and say plainly that you have proposed it and it "
            f"awaits approval. You may propose only: {', '.join(sorted(grants))}."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action_id": {"type": "string",
                              "description": f"One of: {', '.join(sorted(grants))}"},
                "params": {"type": "object",
                           "description": "Arguments the action declares, by name."},
                "reasoning": {"type": "string",
                              "description": "Why this action, in one sentence, for the "
                                             "human who will read it before accepting."},
            },
            "required": ["action_id"],
        },
        run=_propose,
    )]


def propose_one(connection_id: str, *, grants: list[str], action_id: str,
                params: Optional[dict] = None, reasoning: str = "",
                schema_name: str = "", proposer: str = "agent") -> dict:
    """Validate one proposed action and stage it. Never executes, never raises.

    Refusals are returned as data, not exceptions: the model is mid-turn and a refusal it
    can read is one it can act on, where a raised error ends the answer.
    """
    if action_id not in grants:
        # Named explicitly. "not permitted" without the roster invites the model to guess
        # again, and each guess is another turn.
        return {"ok": False, "status": "not_granted",
                "message": (f"This agent may not propose '{action_id}'. "
                            f"Granted: {', '.join(sorted(grants)) or 'none'}.")}

    from aughor.actions.propose import ProposedAction, validate_proposals
    from aughor.ontology.store import load_latest_ontology

    graph = load_latest_ontology(connection_id, schema_name or None)
    if graph is None or not (getattr(graph, "kinetic_actions", None) or {}):
        return {"ok": False, "status": "no_actions",
                "message": "This connection declares no actions."}

    validated = validate_proposals(
        graph, [ProposedAction(action_id=action_id, params=dict(params or {}),
                               reasoning=reasoning)], scope=connection_id)
    if not validated:
        return {"ok": False, "status": "invalid", "message": "The proposal did not validate."}

    p = validated[0]
    if not p.ok:
        # The authored message verbatim — a submission criterion's own words are what the
        # action's author wrote for exactly this moment.
        return {"ok": False, "status": p.status, "action_id": p.action_id,
                "message": p.message}

    from aughor.actions.inbox import StagedProposal, stage_proposal
    staged = stage_proposal(StagedProposal(
        connection_id=connection_id, schema_name=schema_name or "",
        action_id=p.action_id, params=p.params, reasoning=p.reasoning,
        proposer=proposer, source="agent",
        # A fresh run/call key per tool call: two proposals of the same action in one
        # conversation are two decisions a human should see separately, and collapsing
        # them would silently drop the second.
        run_id=uuid.uuid4().hex, call_id=p.action_id))
    return {
        "ok": True, "status": "awaiting_approval", "action_id": p.action_id,
        "proposal_id": staged.id, "params": p.params,
        "expires_at": staged.expires_at,
        "message": ("Proposed and awaiting a human's approval — nothing has been "
                    "executed. Tell the user it is queued for approval, never that it "
                    "is done."),
    }
