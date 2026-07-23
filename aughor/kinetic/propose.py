"""Wave K4 — the agent proposes a declared action.

The agent's write surface is exactly {scoped read SQL, `ACTION:` read templates, declared
KineticActions} — never freeform. This module is the last of those: shown the connection's declared
actions and a context (a finding, a question), the model returns STRUCTURED proposals, each of which
is **dry-run validated here** (typed params coerced + submission criteria evaluated deterministically)
but **never executed** — a proposal is staged for a human to accept, who runs it through the one K2
executor. Nothing above LOW risk auto-fires; in fact nothing fires at all until a human accepts.

Structured output (a Pydantic response_model) is used instead of `KINETIC:id(...)` token parsing: it
is what instructor gives us for free and removes a brittle parse. When a criterion fails, the AUTHORED
message is returned to the caller so it can be fed back to the model to revise — the message is the
product, passed through verbatim, never paraphrased.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

from aughor.ontology.models import KineticAction, OntologyGraph
from aughor.kinetic.executor import CriterionError, ParamError, coerce_params, evaluate_predicate


class ProposedAction(BaseModel):
    """One action the model proposes to take, with its typed parameters and its reasoning."""
    action_id: str
    params: dict = Field(default_factory=dict)
    reasoning: str = ""


class ProposerOutput(BaseModel):
    """The proposer's structured output — zero or more proposals (empty = the model abstained)."""
    proposals: list[ProposedAction] = Field(default_factory=list)


@dataclass
class Proposal:
    """A staged proposal after deterministic validation — NOT executed."""
    action_id: str
    status: str                 # proposed | invalid_params | criterion_failed | unknown_action
    params: dict = field(default_factory=dict)
    reasoning: str = ""
    message: str = ""           # authored criterion message / validation error (verbatim)

    @property
    def ok(self) -> bool:
        return self.status == "proposed"


_PROPOSER_SYS = (
    "Decide whether the analysis below clearly calls for one of the DECLARED ACTIONS. If it does, "
    "PROPOSE that action and fill EVERY required parameter with a concrete value taken from the "
    "analysis, choosing values that satisfy the action's submission criteria. If no declared action "
    "clearly fits, return an empty proposals list. You are proposing for a human to review and accept "
    "— you are NOT executing. Use only the declared actions and only their declared parameters; never "
    "invent an action or a parameter.\n\n"
)


def build_kinetic_actions_section(graph: Optional[OntologyGraph]) -> str:
    """The DECLARED ACTIONS block for the proposer prompt — each action's id, params (with types +
    required), and submission criteria (so the model proposes values that will pass). Empty when the
    connection declares no actions, so the prompt collapses cleanly."""
    actions = getattr(graph, "kinetic_actions", None) or {}
    if not actions:
        return ""
    lines = ["DECLARED ACTIONS you may propose:"]
    for a in actions.values():
        lines.append(f"\n• {a.id} ({a.kind}) — {a.description or a.display_name or a.id}")
        for p in a.params:
            req = "required" if p.required else "optional"
            dv = f", default {p.default_value}" if p.default_value is not None else ""
            lines.append(f"    param {p.name}: {p.data_type} ({req}{dv})")
        for c in a.submission_criteria:
            lines.append(f"    must satisfy: {c.expr}")
    lines.append("")
    return "\n".join(lines)


def evaluate_proposal(action: KineticAction, params: dict, *, scope: str = "") -> tuple[str, str, dict]:
    """Dry-run validate a proposal — coerce params, then evaluate submission criteria. Returns
    ``(status, message, coerced_params)``. NEVER dispatches, approves, or executes: this is the
    staging gate, so a proposal that would fail its criteria is caught before a human ever sees it
    as executable, and the authored message goes back to the model to revise."""
    try:
        coerced = coerce_params(action, params)
    except ParamError as e:
        return "invalid_params", str(e), {}
    for crit in action.submission_criteria:
        try:
            passed = evaluate_predicate(crit.expr, coerced)
        except CriterionError:
            return "criterion_failed", crit.message, coerced
        if not passed:
            return "criterion_failed", crit.message, coerced
    return "proposed", "", coerced


def validate_proposals(graph: OntologyGraph, raw: list[ProposedAction], *, scope: str = "") -> list[Proposal]:
    """Turn raw model proposals into staged, validated :class:`Proposal`s (no execution)."""
    actions = getattr(graph, "kinetic_actions", None) or {}
    out: list[Proposal] = []
    for p in raw:
        action = actions.get(p.action_id)
        if action is None:
            out.append(Proposal(p.action_id, "unknown_action", p.params, p.reasoning,
                                message=f"'{p.action_id}' is not a declared action"))
            continue
        status, msg, coerced = evaluate_proposal(action, p.params, scope=scope)
        # carry the coerced params on a valid proposal so accept-time re-uses the exact values
        out.append(Proposal(p.action_id, status, coerced if status == "proposed" else p.params,
                            p.reasoning, message=msg))
    return out


def propose_actions(graph: Optional[OntologyGraph], context: str, *, scope: str = "",
                    provider=None) -> list[Proposal]:
    """Ask the model to propose actions for ``context`` (a finding / question), then dry-run
    validate each. Returns staged proposals — NOTHING is executed. ``provider`` is injectable
    (a fake in tests); the default resolves the ``fast`` role. Empty when the connection declares
    no actions or the model abstains; fail-open to [] on a proposer error (never blocks an answer)."""
    actions = getattr(graph, "kinetic_actions", None) or {}
    if not actions:
        return []
    section = build_kinetic_actions_section(graph)
    try:
        prov = provider
        if prov is None:
            # Proposing a governed action is high-stakes JUDGMENT (decide + fill params to satisfy the
            # criteria), not a throwaway — bind the strong reasoner, not the `fast` tier. The K4 live
            # proof confirmed the point: the strong model proposed valid params 3/3 where nano did not.
            from aughor.llm.provider import get_provider
            prov = get_provider("coder")
        out = prov.complete(system=_PROPOSER_SYS + section, user=context,
                            response_model=ProposerOutput, temperature=0.1)
    except Exception:
        from aughor.kernel.errors import tolerate
        import sys
        tolerate(sys.exc_info()[1], "kinetic proposer is advisory; answer proceeds",
                 counter="kinetic.proposer_failed")
        return []
    return validate_proposals(graph, list(out.proposals), scope=scope)
