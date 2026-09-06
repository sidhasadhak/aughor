"""SP-3 (§3.11) — Spotlight's Act limb: the writes, every one of them governed.

`spotlight_tools` (the Know roster) promised this module by name: its contract is
"every tool is a read", stated absolutely, so the writes live next door — the same
split `action_tools` already models. Five tools, two custody classes:

* **Cosmetic, self-scoped → applies instantly.** `set_preference` changes how the
  platform looks to the CALLER (theme, density, default connection) and nothing about
  what runs or what anyone else sees. That is §3.11's cosmetic line, and the store's
  closed key registry is what keeps the line from creeping.
* **Structural → stages a proposal, never posts.** `draft_agent` and
  `draft_automation` produce records that would otherwise go INSTANTLY live through
  their create routes — so here they are staged as new kinds on the ONE inbox
  (`actions/inbox.py`), where accept is the arming and reject leaves the platform
  byte-identical. The model drafts; the human certifies. A second approval surface
  was the refused alternative, three times over, in the inbox's own words.
  `pause_or_resume_automation` and `propose_agent_grant` (the wave's leftovers)
  ride the same custody: changing what runs, or what an agent may propose, is
  structural however small the diff looks — and a grant is permission to PROPOSE,
  never to execute (VA-9c's line, restated where the tool offers it).

`draft_automation` deliberately owns none of the drafting: DS-15's `propose_chain`
already turns an outcome sentence into a validated, dry-run-attached chain and refuses
what the validators refuse. This tool adds exactly one thing — the staged handoff to a
human — and forwards a refusal verbatim, because a considered "nothing here can do
that" is an answer, not an error.
"""
from __future__ import annotations

import logging

from aughor.agent.spotlight_text import NAME_CLIP, clip
from aughor.agent.tool_loop import ToolSpec

logger = logging.getLogger(__name__)

_MAX_REASON = 400


def set_preference(args: dict) -> dict:
    """Apply one cosmetic, self-scoped preference — instantly, per §3.11's line."""
    from aughor.db.user_prefs import set_preference as store_set

    try:
        out = store_set(str(args.get("key") or ""), args.get("value"))
    except ValueError as exc:
        return {"applied": False, "error": str(exc)}
    return {"applied": True,
            "summary": (f"Preference applied for {out['user']}: "
                        f"{args.get('key')} → {args.get('value')}. It follows this "
                        f"user across sessions; the reset door is the same tool."),
            **out}


def draft_agent(connection_id: str, args: dict) -> dict:
    """Validate and STAGE an agent draft on the one inbox — never create directly."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.custom_agents.store import validate_agent_draft
    from aughor.org.context import current_org_id

    name = str(args.get("name") or "").strip()
    instructions = str(args.get("instructions") or "").strip()
    schema_scope = str(args.get("schema_scope") or "").strip()
    doc_ids = [str(d) for d in (args.get("doc_ids") or []) if str(d).strip()]

    problems = validate_agent_draft(name=name or None, instructions=instructions,
                                    connection_id=connection_id, doc_ids=doc_ids)
    if not name:
        problems.insert(0, "name is required")
    if not instructions:
        problems.insert(0, "instructions are required — an agent is a scope and a stance")
    if problems:
        return {"staged": False, "problems": problems,
                "summary": "Draft refused before staging: " + "; ".join(problems)}

    # The empty-documents trap, disclosed IN the record a human will read: an agent with
    # zero documents sees LESS context than plain chat, not the same — every agent the
    # old form created was silently in that state.
    disclosure = ("" if doc_ids else
                  " NOTE: no documents attached — this agent will see LESS context "
                  "than plain chat until documents are added.")
    reasoning = (str(args.get("reasoning") or "drafted from conversation")[:_MAX_REASON]
                 + disclosure)

    p = stage_proposal(StagedProposal(
        kind="agent_draft", org_id=current_org_id() or "",
        connection_id=connection_id, action_id=f"agent:{name}",
        params={"name": name, "instructions": instructions,
                "schema_scope": schema_scope, "doc_ids": doc_ids},
        reasoning=reasoning, proposer="spotlight", source="agent"))
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "documents_attached": len(doc_ids),
        "summary": (f"Agent draft '{clip(name, NAME_CLIP)}' staged for approval (proposal {p.id}) — "
                    f"nothing exists yet; a human accepts it in the inbox and only "
                    f"then is the agent created.{disclosure}"),
    }


def draft_automation(connection_id: str, args: dict) -> dict:
    """Describe an outcome → DS-15 drafts and validates the chain → stage it here."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.automations.propose import propose_chain
    from aughor.org.context import current_org_id

    outcome = str(args.get("outcome") or "").strip()
    if not outcome:
        return {"staged": False,
                "summary": "Nothing to draft — describe the outcome the automation "
                           "should produce, in one sentence."}

    proposal = propose_chain(outcome, conn_id=connection_id)
    if proposal.verdict != "proposed" or not proposal.draft:
        return {"staged": False, "verdict": proposal.verdict,
                "reason": proposal.reason, "notes": proposal.notes,
                "summary": (f"The platform declined to draft this ({proposal.verdict}): "
                            f"{proposal.reason or 'see notes'} — a considered refusal, "
                            f"not an error.")}

    name = str(proposal.draft.get("name") or outcome[:60])
    p = stage_proposal(StagedProposal(
        kind="automation_draft", org_id=current_org_id() or "",
        connection_id=connection_id, action_id=f"automation:{name}",
        params=dict(proposal.draft),
        reasoning=(str(args.get("reasoning") or outcome)[:_MAX_REASON]),
        proposer="spotlight", source="agent"))
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "draft": proposal.draft, "dry_run": proposal.dry_run, "notes": proposal.notes,
        "summary": (f"Automation draft '{clip(name, NAME_CLIP)}' staged for approval (proposal {p.id}) "
                    f"with its dry-run attached — it joins the one scheduler only "
                    f"after a human accepts it in the inbox."),
    }


def _resolve_automation(connection_id: str, ref: str):
    """An automation on THIS connection, by id or exact name — ``(automation, "")``
    or ``(None, refusal)``. The binding law applied to a write's TARGET: a chain on
    another connection is refused with its home named, never silently acted on."""
    from aughor.automations.store import get_automation, list_automations

    ref = str(ref or "").strip()
    if not ref:
        return None, "name the automation to act on — its id or its exact name"
    a = get_automation(ref)
    if a is not None:
        if (a.conn_id or "") not in ("", connection_id):
            return None, (f"automation '{clip(a.name, NAME_CLIP)}' belongs to connection "
                          f"{a.conn_id!r}, not this conversation's — switch there to act on it")
        return a, ""
    matches = [x for x in list_automations(conn_id=connection_id) if x.name == ref]
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        ids = ", ".join(x.id for x in matches)
        return None, f"{len(matches)} automations are named {clip(ref, NAME_CLIP)!r} — use an id: {ids}"
    return None, f"no automation named {clip(ref, NAME_CLIP)!r} on this connection"


def pause_or_resume_automation(connection_id: str, args: dict) -> dict:
    """Stage a pause (with its end) or a resume on the one inbox — never applied here."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.org.context import current_org_id

    action = str(args.get("action") or "").strip().lower()
    if action not in ("pause", "resume"):
        return {"staged": False,
                "summary": f"unknown action {action!r} — this tool stages a pause or a resume"}
    a, refusal = _resolve_automation(connection_id, str(args.get("automation") or ""))
    if a is None:
        return {"staged": False, "summary": f"Nothing staged: {refusal}"}
    until = str(args.get("until") or "").strip()
    if action == "pause" and not until:
        return {"staged": False,
                "summary": ("Nothing staged: a pause has an end — say until when "
                            "(an ISO timestamp); to stop it for good, that is "
                            "disabling, a different act.")}

    p = stage_proposal(StagedProposal(
        kind="automation_state", org_id=current_org_id() or "",
        connection_id=connection_id, action_id=f"automation-{action}:{clip(a.name, NAME_CLIP)}",
        params={"automation_id": a.id, "action": action,
                **({"until": until} if action == "pause" else {})},
        reasoning=(str(args.get("reasoning") or f"{action} requested in conversation")
                   [:_MAX_REASON]),
        proposer="spotlight", source="agent"))
    tail = f" until {until}" if action == "pause" else ""
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "automation_id": a.id,
        "summary": (f"Proposed: {action} automation '{clip(a.name, NAME_CLIP)}'{tail} (proposal "
                    f"{p.id}). Nothing changed yet — a human accepts it in the "
                    f"inbox and only then does it apply."),
    }


def propose_agent_grant(connection_id: str, args: dict) -> dict:
    """Stage ONE declared action onto an agent's grant list — permission to PROPOSE."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.custom_agents.store import get_agent, list_agents, validate_agent_grants
    from aughor.org.context import current_org_id

    ref = str(args.get("agent") or "").strip()
    action_id = str(args.get("action_id") or "").strip()
    if not ref or not action_id:
        return {"staged": False,
                "summary": "Nothing staged: name the agent (id or exact name) and "
                           "the declared action to grant."}
    agent = get_agent(ref)
    if agent is None:
        matches = [a for a in list_agents() if a.name == ref]
        if len(matches) > 1:
            ids = ", ".join(a.id for a in matches)
            return {"staged": False,
                    "summary": f"Nothing staged: {len(matches)} agents are named "
                               f"{clip(ref, NAME_CLIP)!r} — use an id: {ids}"}
        agent = matches[0] if matches else None
    if agent is None:
        return {"staged": False,
                "summary": f"Nothing staged: no agent {clip(ref, NAME_CLIP)!r} exists."}
    problems = validate_agent_grants([action_id], connection_id, agent.schema_scope)
    if problems:
        return {"staged": False, "problems": problems,
                "summary": "Nothing staged: " + "; ".join(problems)}
    if action_id in agent.tool_grants:
        return {"staged": False,
                "summary": f"Nothing staged: agent '{clip(agent.name, NAME_CLIP)}' already holds the "
                           f"{clip(action_id, NAME_CLIP)} grant."}

    p = stage_proposal(StagedProposal(
        kind="agent_grant", org_id=current_org_id() or "",
        connection_id=connection_id, action_id=f"agent-grant:{clip(agent.name, NAME_CLIP)}:{clip(action_id, NAME_CLIP)}",
        params={"agent_id": agent.id, "action_id": action_id},
        reasoning=(str(args.get("reasoning") or "granted from conversation")[:_MAX_REASON]
                   + " NOTE: a grant is permission to PROPOSE this action — every "
                     "proposal still lands in this inbox for a human."),
        proposer="spotlight", source="agent"))
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "agent_id": agent.id,
        "summary": (f"Proposed: let agent '{clip(agent.name, NAME_CLIP)}' PROPOSE {clip(action_id, NAME_CLIP)} "
                    f"(proposal {p.id}). A grant is never permission to execute — "
                    f"its proposals still wait for a human; nothing changes until "
                    f"this is accepted in the inbox."),
    }


# ── the roster ───────────────────────────────────────────────────────────────────────

_PREF_PARAMS = {
    "type": "object",
    "properties": {
        "key": {"type": "string",
                "description": "One of: theme, density, or the default connection key "
                               "the result lists — unknown keys are refused with the "
                               "known ones named."},
        "value": {"type": "string",
                  "description": "The value (e.g. dark, light, system for theme)."},
    },
    "required": ["key", "value"],
}
_AGENT_PARAMS = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short agent name."},
        "instructions": {"type": "string",
                         "description": "The agent's pinned instructions — its scope "
                                        "and stance, in full sentences."},
        "schema_scope": {"type": "string",
                         "description": "Optional schema to pin the agent to."},
        "doc_ids": {"type": "array", "items": {"type": "string"},
                    "description": "Document ids to attach. Leaving this empty is "
                                   "RESTRICTIVE, not neutral — say so to the user."},
        "reasoning": {"type": "string",
                      "description": "One sentence on why, shown to the approver."},
    },
    "required": ["name", "instructions"],
}
_AUTOMATION_PARAMS = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string",
                    "description": "The outcome the automation should produce, in the "
                                   "user's own words (e.g. 'brief me every Monday on "
                                   "refund rate')."},
        "reasoning": {"type": "string",
                      "description": "One sentence on why, shown to the approver."},
    },
    "required": ["outcome"],
}
_STATE_PARAMS = {
    "type": "object",
    "properties": {
        "automation": {"type": "string",
                       "description": "The automation's id or its exact name."},
        "action": {"type": "string", "enum": ["pause", "resume"],
                   "description": "pause mutes it until a time; resume clears a pause."},
        "until": {"type": "string",
                  "description": "REQUIRED for pause: when it ends, as an ISO "
                                 "timestamp (e.g. 2026-09-13T00:00:00Z). A pause "
                                 "always has an end."},
        "reasoning": {"type": "string",
                      "description": "One sentence on why, shown to the approver."},
    },
    "required": ["automation", "action"],
}
_GRANT_PARAMS = {
    "type": "object",
    "properties": {
        "agent": {"type": "string",
                  "description": "The agent's id or its exact name."},
        "action_id": {"type": "string",
                      "description": "ONE declared action id on this connection — "
                                     "never a wildcard."},
        "reasoning": {"type": "string",
                      "description": "One sentence on why, shown to the approver."},
    },
    "required": ["agent", "action_id"],
}


def spotlight_act_tools(connection_id: str, *, session_id: str = "") -> list[ToolSpec]:
    """The Act roster — cosmetic applies, structural stages; nothing executes here."""
    return [
        ToolSpec(
            name="set_preference",
            description=(
                "Set ONE of the caller's own cosmetic preferences — theme (dark, "
                "light, system), density, or their default connection — applied "
                "instantly and following them across sessions. Self-scoped only: "
                "this never changes what runs or what anyone else sees. Quote the "
                "summary field verbatim to confirm what was applied."
            ),
            parameters=_PREF_PARAMS,
            run=lambda a: set_preference(a),
        ),
        ToolSpec(
            name="draft_agent",
            description=(
                "Draft a custom agent from the user's description and STAGE it for "
                "human approval in the inbox — nothing is created until a person "
                "accepts. Provide name and instructions; attach document ids when "
                "the user names sources (an agent with no documents sees LESS than "
                "plain chat — always disclose that). Quote the summary field "
                "verbatim; tell the user where the approval lives."
            ),
            parameters=_AGENT_PARAMS,
            run=lambda a: draft_agent(connection_id, a),
        ),
        ToolSpec(
            name="draft_automation",
            description=(
                "Turn a described outcome into a validated automation draft (with a "
                "dry-run receipt) and STAGE it for human approval in the inbox — it "
                "never schedules itself. Use for 'every Monday…', 'when X happens…', "
                "'remind/brief me…' asks. A refusal with a reason is an answer to "
                "relay, not an error. Quote the summary field verbatim."
            ),
            parameters=_AUTOMATION_PARAMS,
            run=lambda a: draft_automation(connection_id, a),
        ),
        ToolSpec(
            name="pause_or_resume_automation",
            description=(
                "STAGE a pause (until a stated time) or a resume of one automation "
                "for human approval in the inbox — nothing applies until a person "
                "accepts. Use for 'pause the Monday brief', 'silence that alert "
                "until next week', 'turn it back on' asks. A pause always has an "
                "end; permanently stopping a chain is disabling, which lives on the "
                "Automations page. Quote the summary field verbatim."
            ),
            parameters=_STATE_PARAMS,
            run=lambda a: pause_or_resume_automation(connection_id, a),
        ),
        ToolSpec(
            name="propose_agent_grant",
            description=(
                "STAGE adding ONE declared action to a custom agent's grant list, "
                "for human approval in the inbox. A grant is permission to PROPOSE "
                "that action — the agent's proposals still wait for a human; "
                "nothing ever auto-executes. Use when the user wants an agent to be "
                "able to suggest a specific action. Unknown agents or undeclared "
                "actions are refused with the known ones named. Quote the summary "
                "field verbatim."
            ),
            parameters=_GRANT_PARAMS,
            run=lambda a: propose_agent_grant(connection_id, a),
        ),
    ]
