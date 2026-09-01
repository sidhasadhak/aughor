"""DS-15 — conversation authors the canvas: describe an outcome, get a drawn chain.

The shape is the one this platform already uses for every governed write: **a proposal,
never an execution**. The model drafts, the same validators a save runs refuse a draft
that could not be saved, a dry run shows what it WOULD do, and a human arms it. A grant
here is permission to propose — which is what the rest of this codebase already means by
one, so this wave adds a new author rather than a new kind of authority.

Three things make the draft honest rather than plausible:

* **It is offered only what THIS deployment has.** The prompt carries the palette's own
  answer about which kinds work here and why the others do not, plus the real ids — the
  Slack bots that exist, the metrics that are defined, the vetted queries that are stored.
  A model that is never shown a channel it cannot post to cannot propose posting to it.
* **It is refused by the same code a save is refused by.** The draft is constructed as an
  `Automation`, so every model validator and `validate_chain` runs: an unknown effect
  kind, a missing required key, a binding onto a step that does not exist, a fan-out over
  something that is not a list. A proposal that would not save is not drawn.
* **It fails CLOSED, with a reason.** `actions/propose.py` fails open to `[]` because
  proposing an action garnishes an answer somebody already asked for. Here the proposal IS
  the request, so answering "nothing" to "build me a chain" would be a silent no — the
  caller gets a refusal that names what went wrong instead.

Nothing here writes. The one thing this module must never learn to do is save what it
drafted; the human who reads the dry run is the whole point.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: The chain a model may draft. Deliberately the AUTHORING shape and no more: no id, no
#: `enabled`, no `exposed_as_tool`, no schedule state. A draft that could arrive already
#: armed, or already exposed as an MCP tool, would be a proposal that had made a decision
#: the human is being asked to make.
class ProposedStep(BaseModel):
    kind: str = ""
    alias: str = ""
    config: dict = Field(default_factory=dict)
    when: list[dict] = Field(default_factory=list)
    when_logic: str = "all"
    else_of: str = ""
    for_each: Optional[dict] = None


class ProposedTrigger(BaseModel):
    kind: str = ""
    config: dict = Field(default_factory=dict)


class ProposedChain(BaseModel):
    """What the model returns. Prose fields included, because a chain a person has to arm
    needs a name and a sentence they can judge it by."""

    name: str = ""
    description: str = ""
    conditions: list[ProposedTrigger] = Field(default_factory=list)
    condition_logic: str = "all"
    effects: list[ProposedStep] = Field(default_factory=list)
    #: The model's own account of what it could not do. Asked for explicitly, because the
    #: alternative is a chain that quietly drops the half of the request it could not
    #: express — and a person reading a drawn canvas has no way to notice the absence.
    notes: str = ""


@dataclass
class ChainProposal:
    """A staged chain, or a refusal that says why. Never a saved automation."""

    verdict: str                       # "proposed" | "refused"
    reason: str = ""
    draft: Optional[dict] = None       # the CreateAutomationRequest-shaped payload
    dry_run: dict = field(default_factory=dict)
    notes: str = ""


_SYS = """\
You design AUTOMATION CHAINS for Aughor. A chain has TRIGGERS (when it runs) and STEPS
(what it does, in order). You will be given exactly what this deployment can do; propose a
chain using ONLY that.

Rules that decide whether your proposal is accepted at all:
- Use only the trigger and step kinds listed as AVAILABLE. A kind listed as unavailable
  cannot be used no matter how well it fits — say so in `notes` instead.
- Every kind's required config keys must be present, with real ids from the lists given.
  Never invent a bot id, a metric name, a query id or an action id.
- A step may read an earlier step with {"$from": "<alias>.<key>"}, using only the keys that
  step PUBLISHES. Give a step an `alias` when a later step reads it.
- A binding is an OBJECT in the config, never text inside a string. Correct:
  {"message": {"$from": "summary.answer"}}. WRONG: {"message": "{\"$from\": \"summary.answer\"}"}
  — that posts the literal characters. A field is EITHER a whole binding or a plain
  string; a binding cannot be embedded in a sentence.
- Only a key marked as a list may be used as a `for_each` source.
- If the request cannot be built from what is available, return no effects and explain in
  `notes`. A partial chain that silently drops half the request is worse than a refusal.

Prefer the smallest chain that does what was asked. Name it in the user's words.
"""


def _deployment_section(conn_id: str) -> str:
    """Everything the model is allowed to use, in the deployment's own words.

    Built from the SAME sources the canvas reads — the palette for what is placeable and
    why, the dataflow tables for what each kind publishes and may bind, the registry for
    the real objects. A prompt assembled from a second, hand-written list of kinds would
    drift from the one the save enforces, and the drift would show up as a proposal that
    validates in the prompt and is refused by the code.
    """
    from aughor.automations.dataflow import BINDABLE_FIELDS, LIST_PUBLISHED, PUBLISHED_KEYS
    from aughor.automations.models import required_keys
    from aughor.automations.palette import entries

    lines: list[str] = ["AVAILABLE TRIGGERS AND STEPS ON THIS DEPLOYMENT:"]
    for row in entries(conn_id):
        family = "trigger" if row["group"] == "trigger" else "effect"
        need = ", ".join(required_keys(row["kind"], family=family)) or "no required keys"
        if row["availability"] != "ready":
            lines.append(f"- {row['kind']} — UNAVAILABLE: {row['reason']}")
            continue
        pub = row["publishes"]
        publishes = ("anything that operation returns" if pub is None
                     else ", ".join(pub) or "nothing")
        listy = LIST_PUBLISHED.get(row["kind"], ())
        bit = f" (a list: {', '.join(listy)})" if listy else ""
        lines.append(
            f"- {row['kind']} — {row['label']}. {row['description']} "
            f"Requires: {need}. Publishes: {publishes}{bit}. "
            f"Bindable: {', '.join(BINDABLE_FIELDS.get(row['kind'], ())) or 'nothing'}")

    # Guard against a table that grew a kind the palette does not offer: the model must
    # never be told about a kind it cannot place, but a kind it CAN place must never be
    # missing either.
    offered = {r["kind"] for r in entries(conn_id)}
    for kind in PUBLISHED_KEYS:
        if kind not in offered:
            logger.debug("kind %s is not offered by the palette; not proposed", kind)

    lines.append("")
    lines.append(_objects_section(conn_id))
    return "\n".join(lines)


def _objects_section(conn_id: str) -> str:
    """The REAL ids a step may name. Without these the model invents plausible ones, and a
    plausible id is the failure mode that looks most like success."""
    from aughor.components.registry import components

    by_family: dict[str, list[str]] = {}
    try:
        for c in components(conn_id):
            if c.family in ("trigger", "effect"):
                continue                      # the kinds are listed above, not here
            label = f"{c.kind} ({c.label})" if c.label and c.label != c.kind else c.kind
            if c.availability != "ready" and c.reason:
                label += f" [{c.reason}]"
            by_family.setdefault(c.family, []).append(label)
    except Exception as exc:                  # a roster that cannot be read is not fatal
        from aughor.kernel.errors import tolerate
        tolerate(exc, "component roster is advisory for the chain proposer",
                 counter="chain_propose.roster")

    _title = {"metric": "GOVERNED METRICS (use the name as `metric`)",
              "trusted_query": "TRUSTED QUERIES (use the id as `query_id`)",
              "declared_action": "DECLARED ACTIONS (use the id as `action_id`)",
              "connector": "CONNECTOR TYPES", "platform_tool": "PLATFORM TOOLS",
              "mcp_tool": "MCP TOOLS"}
    out = ["REAL OBJECTS ON THIS CONNECTION — never invent an id:"]
    for family, items in by_family.items():
        if family in ("connector", "platform_tool", "mcp_tool"):
            continue                          # not addressable from a chain step
        out.append(f"{_title.get(family, family)}: " + ("; ".join(items) or "none"))
    out.append(_bots_section())
    return "\n".join(out)


def _bots_section() -> str:
    """The Slack bots that actually exist, by id — `slack_post` names one."""
    try:
        from aughor.slackbots.store import list_bots
        bots = [f"{b.id} ({b.name})" for b in list_bots() if getattr(b, "enabled", True)]
    except Exception:
        bots = []
    return "SLACK BOTS (use the id as `bot_id`): " + ("; ".join(bots) or "none configured")


def _as_binding(value: Any) -> Any:
    """A string that IS a binding, turned into one. Anything else untouched.

    Found by driving it live: the model returned `"{\"$from\": \"step.key\"}"` — a STRING
    holding the JSON of a binding — and nothing refused it, because a string is a legal
    literal. The chain validated, dry-ran clean, and would have posted those characters to
    Slack. A well-formed wrong answer, which this codebase treats as worse than an
    exception.

    Only an EXACT match is repaired: the whole value must parse to an object whose single
    key is `$from`. A binding embedded in a sentence is left alone deliberately — the
    engine cannot interpolate one, so guessing at what the author meant would replace a
    visible mistake with an invisible one.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not (text.startswith("{") and "$from" in text):
        return value
    try:
        import json
        parsed = json.loads(text)
    except ValueError:
        return value
    if isinstance(parsed, dict) and set(parsed) == {"$from"} and isinstance(parsed["$from"], str):
        return parsed
    return value


def _repair_bindings(drafted: "ProposedChain") -> None:
    """Walk a draft's step configs and un-stringify any binding the model wrote as text."""
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(_as_binding(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(_as_binding(v)) for v in node]
        return node

    for step in drafted.effects:
        step.config = walk(step.config)


def propose_chain(outcome: str, *, conn_id: str, provider: Any = None) -> ChainProposal:
    """Draft a chain for ``outcome``, validate it, dry-run it. Never saves.

    ``provider`` is injectable so the suite can exercise every path here without spending a
    token — this repo has already paid once for tests that reached a live model.
    """
    from aughor.automations.models import Automation

    if not (outcome or "").strip():
        return ChainProposal(verdict="refused", reason="describe what the chain should do")

    try:
        prov = provider
        if prov is None:
            # The strong reasoner, for the reason the action proposer states one file over:
            # this is high-stakes JUDGMENT — pick kinds, wire aliases, satisfy required
            # keys — and the fast tier proposes chains that do not validate.
            from aughor.llm.provider import get_provider
            prov = get_provider("coder")
        drafted = prov.complete(system=_SYS + "\n\n" + _deployment_section(conn_id),
                                user=outcome, response_model=ProposedChain,
                                temperature=0.1)
    except Exception as exc:
        logger.warning("chain proposer failed: %s", exc)
        return ChainProposal(
            verdict="refused",
            reason=f"the proposer could not draft a chain: {exc}")

    if not drafted.effects:
        # The model was asked to say so rather than invent a chain it could not build.
        return ChainProposal(verdict="refused", notes=drafted.notes,
                             reason=drafted.notes or "nothing on this deployment can do that")

    _repair_bindings(drafted)

    payload = {
        "conn_id": conn_id,
        "name": drafted.name or "Proposed chain",
        "description": drafted.description or "",
        "conditions": [c.model_dump() for c in drafted.conditions],
        "condition_logic": drafted.condition_logic or "all",
        "effects": [e.model_dump(exclude_none=True) for e in drafted.effects],
    }

    # The SAME refusal a save performs. A draft that could not be saved must not be drawn:
    # a canvas showing a chain the Save button will reject is worse than a refusal, because
    # it looks like work that is nearly done.
    try:
        automation = Automation(**payload)
    except Exception as exc:
        return ChainProposal(verdict="refused", notes=drafted.notes,
                             reason=f"the drafted chain is not valid here: {exc}",
                             draft=payload)

    try:
        from aughor.automations.engine import run_automation
        run = run_automation(automation, dry_run=True)
        dry = run.model_dump()
    except Exception as exc:
        # A draft that validates but cannot even be previewed is still worth returning —
        # the human can fix it on the canvas — but it is returned WITHOUT a receipt rather
        # than with a fabricated one.
        logger.warning("dry run of a proposed chain failed: %s", exc)
        dry = {}

    return ChainProposal(verdict="proposed", draft=payload, dry_run=dry, notes=drafted.notes)
