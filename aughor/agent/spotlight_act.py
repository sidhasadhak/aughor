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


def _supersede_prior(new_p, supersedes: str) -> str:
    """SP-11 — a corrected re-draft REPLACES the pending draft it follows, so the
    inbox holds one pending proposal per ask. Guarded, never trusted: only a PENDING
    proposal on the SAME connection is resolved, so a model cannot retire another
    conversation's work by naming its id. Returns the sentence for the summary
    ("" when nothing was superseded — the new draft stands either way)."""
    from aughor.actions.inbox import get_proposal, supersede_proposal

    old_id = str(supersedes or "").strip()
    if not old_id or old_id == new_p.id:
        return ""
    old = get_proposal(old_id)
    if old is None or not old.pending or old.connection_id != new_p.connection_id:
        return (f" NOTE: {old_id} was not superseded — it is not a pending draft on "
                f"this connection; both records stand.")
    if supersede_proposal(old_id, actor="spotlight:redraft",
                          note=f"superseded by {new_p.id}"):
        return f" It replaces {old_id}, which is now resolved as superseded."
    return ""


def _announce(emit, p) -> None:
    """SP-9 — a staged proposal announces itself on the turn's frame channel, so the
    chat renders the RECORD (fetched by id) as a card rather than re-parsing prose.
    A no-op for every sync caller (MCP, Slack, the /spotlight routes, tests) — and
    best-effort even when bound: a dropped frame loses a card, never a proposal."""
    if emit is None:
        return
    try:
        emit("proposal_staged", {"proposal_id": p.id, "kind": p.kind,
                                 "connection_id": p.connection_id,
                                 "action_id": p.action_id})
    except Exception:
        logger.debug("proposal_staged frame dropped", exc_info=True)


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


def draft_agent(connection_id: str, args: dict, *, emit=None) -> dict:
    """Validate and STAGE an agent draft on the one inbox — never create directly.

    SP-8: when ``schedule`` carries the ask's own when/where clause ("every morning at
    9am to #ops"), the agent and its chain stage as ONE ``agent_bundle`` proposal —
    accept creates the agent and saves the chain running as it, all or nothing."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.custom_agents.store import validate_agent_draft
    from aughor.org.context import current_org_id

    name = str(args.get("name") or "").strip()
    instructions = str(args.get("instructions") or "").strip()
    schema_scope = str(args.get("schema_scope") or "").strip()
    doc_ids = [str(d) for d in (args.get("doc_ids") or []) if str(d).strip()]

    problems = validate_agent_draft(name=name or None, instructions=instructions,
                                    connection_id=connection_id, doc_ids=doc_ids,
                                    schema_scope=schema_scope or None)
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
    agent_params = {"name": name, "instructions": instructions,
                    "schema_scope": schema_scope, "doc_ids": doc_ids}

    schedule = str(args.get("schedule") or "").strip()
    if schedule:
        return _stage_agent_bundle(connection_id, agent_params, schedule,
                                   reasoning=reasoning, disclosure=disclosure,
                                   supersedes=str(args.get("supersedes") or ""), emit=emit)

    p = stage_proposal(StagedProposal(
        kind="agent_draft", org_id=current_org_id() or "",
        connection_id=connection_id, action_id=f"agent:{name}",
        params=agent_params,
        reasoning=reasoning, proposer="spotlight", source="agent"))
    replaced = _supersede_prior(p, str(args.get("supersedes") or ""))
    _announce(emit, p)
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "documents_attached": len(doc_ids),
        "summary": (f"Agent draft '{clip(name, NAME_CLIP)}' staged for approval (proposal {p.id}) — "
                    f"nothing exists yet; a human accepts it in the inbox and only "
                    f"then is the agent created.{disclosure}{replaced}"),
    }


def _open_choice_fields(draft: dict) -> list[dict]:
    """SP-9 — the draft's open choices as FIELDS the card can offer: [{"action", "key"}].
    Read back through the same holes door the accept gates on, so the card's fields and
    the accept's refusals can never name different choices."""
    from aughor.runners import automation_payload_holes
    from aughor.runners.automation_save import parse_hole
    fields = []
    for h in automation_payload_holes(dict(draft or {})):
        parsed = parse_hole(h)
        if parsed is not None:
            fields.append({"action": parsed[0], "key": parsed[1]})
    return fields


def _stage_agent_bundle(connection_id: str, agent_params: dict, schedule: str, *,
                        reasoning: str, disclosure: str, supersedes: str = "",
                        emit=None) -> dict:
    """SP-8 — ONE proposal holding both records: the agent, and the chain that runs as
    it. The chain is drafted by DS-15's own proposer from the schedule clause, carries
    SP-7's open choices, and names NO agent id — the agent does not exist yet, and the
    accept sets the id from the record it just created rather than trusting a claim
    about one yet to be born. A chain the proposer refuses refuses the whole bundle:
    an agent staged beside a refusal would be exactly the half-married pair this kind
    exists to prevent."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.automations.propose import propose_chain
    from aughor.org.context import current_org_id

    name = str(agent_params.get("name") or "")
    proposal = propose_chain(schedule, conn_id=connection_id)
    if proposal.verdict != "proposed" or not proposal.draft:
        return {"staged": False, "verdict": proposal.verdict,
                "reason": proposal.reason, "notes": proposal.notes,
                "summary": (f"Nothing staged — the platform declined to draft the "
                            f"schedule ({proposal.verdict}): "
                            f"{proposal.reason or 'see notes'}. The agent was not "
                            f"staged either: this ask is one thing, and half of it "
                            f"is not it.")}
    chain_name = str(proposal.draft.get("name") or schedule[:60])
    to_fill = list(proposal.to_fill or [])
    first_run = proposal.first_run or ""
    open_note = (" OPEN CHOICES: " + "; ".join(to_fill) + "." if to_fill else "")
    p = stage_proposal(StagedProposal(
        kind="agent_bundle", org_id=current_org_id() or "",
        connection_id=connection_id,
        action_id=f"agent:{name}+automation:{chain_name}",
        params={"agent": dict(agent_params), "automation": dict(proposal.draft)},
        detail={"to_fill": to_fill, "open_choices": _open_choice_fields(proposal.draft),
                "first_run": first_run,
                "dry_run_ok": bool(proposal.dry_run), "runs_as": name},
        reasoning=(reasoning + open_note), proposer="spotlight", source="agent"))
    replaced = _supersede_prior(p, supersedes)
    _announce(emit, p)
    open_line = (" It cannot be accepted until these are chosen: " + "; ".join(to_fill)
                 + " — the approver fills them on the card, or ask and draft again."
                 if to_fill else "")
    when_line = (f" Accepted, its first run would be {_utc_words(first_run)}."
                 if first_run else "")
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "draft": proposal.draft, "dry_run": proposal.dry_run, "notes": proposal.notes,
        "to_fill": to_fill, "first_run": first_run,
        "summary": (f"ONE proposal staged (proposal {p.id}): agent "
                    f"'{clip(name, NAME_CLIP)}' AND its schedule "
                    f"'{clip(chain_name, NAME_CLIP)}', accepted or refused together — "
                    f"accept creates the agent and saves the chain running as it, all "
                    f"or nothing.{disclosure}{open_line}{when_line}{replaced}"),
    }


def draft_automation(connection_id: str, args: dict, *, emit=None) -> dict:
    """Describe an outcome → DS-15 drafts and validates the chain → stage it here.

    SP-8: ``run_as_agent`` names an EXISTING agent the chain runs as — its runs and
    their spend attributed to it — so a chain can run as one without a bundle."""
    from aughor.actions.inbox import StagedProposal, stage_proposal
    from aughor.automations.propose import propose_chain
    from aughor.org.context import current_org_id

    outcome = str(args.get("outcome") or "").strip()
    if not outcome:
        return {"staged": False,
                "summary": "Nothing to draft — describe the outcome the automation "
                           "should produce, in one sentence."}
    run_as = str(args.get("run_as_agent") or "").strip()
    agent = None
    if run_as:
        agent, refusal = _resolve_agent(connection_id, run_as)
        if agent is None:
            return {"staged": False, "summary": f"Nothing staged: {refusal}"}

    proposal = propose_chain(outcome, conn_id=connection_id)
    if proposal.verdict != "proposed" or not proposal.draft:
        return {"staged": False, "verdict": proposal.verdict,
                "reason": proposal.reason, "notes": proposal.notes,
                "summary": (f"The platform declined to draft this ({proposal.verdict}): "
                            f"{proposal.reason or 'see notes'} — a considered refusal, "
                            f"not an error.")}

    name = str(proposal.draft.get("name") or outcome[:60])
    to_fill = list(proposal.to_fill or [])
    first_run = proposal.first_run or ""
    # SP-7 — the approver reads what is still open in the record itself, not only in chat.
    open_note = (" OPEN CHOICES: " + "; ".join(to_fill) + "." if to_fill else "")
    params = dict(proposal.draft)
    if agent is not None:
        # SP-8 — the chain runs as the named agent; VA-9b's per-run attribution
        # (`acting_agent`) reads exactly this field off the saved record.
        params["agent_id"] = agent.id
    p = stage_proposal(StagedProposal(
        kind="automation_draft", org_id=current_org_id() or "",
        connection_id=connection_id, action_id=f"automation:{name}",
        params=params,
        detail={"to_fill": to_fill, "open_choices": _open_choice_fields(proposal.draft),
                "first_run": first_run,
                "dry_run_ok": bool(proposal.dry_run),
                "runs_as": agent.name if agent is not None else ""},
        reasoning=(str(args.get("reasoning") or outcome)[:_MAX_REASON] + open_note),
        proposer="spotlight", source="agent"))
    replaced = _supersede_prior(p, str(args.get("supersedes") or ""))
    _announce(emit, p)
    open_line = (" It cannot be accepted until these are chosen: " + "; ".join(to_fill)
                 + " — the approver fills them on the card, or ask and draft again."
                 if to_fill else "")
    when_line = (f" It waits for its schedule: accepted now, its first run would be "
                 f"{_utc_words(first_run)}." if first_run else "")
    as_line = (f" It runs as agent '{clip(agent.name, NAME_CLIP)}', its runs and spend "
               f"attributed there." if agent is not None else "")
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "draft": proposal.draft, "dry_run": proposal.dry_run, "notes": proposal.notes,
        "to_fill": to_fill, "first_run": first_run,
        "summary": (f"Automation draft '{clip(name, NAME_CLIP)}' staged for approval (proposal {p.id}) "
                    f"with its dry-run attached — it joins the one scheduler only "
                    f"after a human accepts it in the inbox.{as_line}{open_line}{when_line}{replaced}"),
    }


def _utc_words(iso: str) -> str:
    """``2026-09-16T09:00:00Z`` → ``Tue 16 Sep 2026, 09:00 UTC`` — the clock is always named."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return f"{dt:%a} {dt.day} {dt:%b %Y}, {dt:%H:%M} UTC"


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


def _resolve_agent(connection_id: str, ref: str):
    """An EXISTING agent on THIS connection (or unbound), by id or exact name —
    ``(agent, "")`` or ``(None, refusal)``. The same binding law `_resolve_automation`
    applies to a write's target: an agent that belongs to another connection is
    refused with its home named, and an unknown name is a refusal, never an
    invitation to invent one."""
    from aughor.custom_agents.store import get_agent, list_agents

    ref = str(ref or "").strip()
    if not ref:
        return None, "name the agent the chain should run as — its id or its exact name"
    a = get_agent(ref)
    if a is None:
        matches = [x for x in list_agents() if x.name == ref]
        if len(matches) > 1:
            ids = ", ".join(x.id for x in matches)
            return None, (f"{len(matches)} agents are named {clip(ref, NAME_CLIP)!r} — "
                          f"use an id: {ids}")
        a = matches[0] if matches else None
    if a is None:
        return None, (f"no agent {clip(ref, NAME_CLIP)!r} exists — to create one WITH "
                      f"this schedule, use draft_agent with its schedule field")
    if (a.connection_id or "") not in ("", connection_id):
        return None, (f"agent '{clip(a.name, NAME_CLIP)}' belongs to connection "
                      f"{a.connection_id!r}, not this conversation's — switch there "
                      f"to run a chain as it")
    return a, ""


def pause_or_resume_automation(connection_id: str, args: dict, *, emit=None) -> dict:
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

    # SP-6 — an evidence chain travels VERBATIM onto the record the approver
    # reads: a proactive proposal that cannot show its rows is an opinion.
    evidence = str(args.get("evidence") or "").strip()
    reasoning = (str(args.get("reasoning") or f"{action} requested in conversation")
                 [:_MAX_REASON])
    if evidence:
        reasoning += " EVIDENCE: " + clip(evidence, 400)
    p = stage_proposal(StagedProposal(
        kind="automation_state", org_id=current_org_id() or "",
        connection_id=connection_id, action_id=f"automation-{action}:{clip(a.name, NAME_CLIP)}",
        params={"automation_id": a.id, "action": action,
                **({"until": until} if action == "pause" else {})},
        reasoning=reasoning,
        proposer="spotlight", source="agent"))
    _announce(emit, p)
    tail = f" until {until}" if action == "pause" else ""
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "automation_id": a.id,
        "summary": (f"Proposed: {action} automation '{clip(a.name, NAME_CLIP)}'{tail} (proposal "
                    f"{p.id}). Nothing changed yet — a human accepts it in the "
                    f"inbox and only then does it apply."),
    }


def propose_agent_grant(connection_id: str, args: dict, *, emit=None) -> dict:
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
    _announce(emit, p)
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
                         "description": "Leave empty unless the user named a schema. It "
                                        "must be one this connection has — a schema it "
                                        "does not have is refused."},
        "doc_ids": {"type": "array", "items": {"type": "string"},
                    "description": "Document ids to attach. Leaving this empty is "
                                   "RESTRICTIVE, not neutral — say so to the user."},
        "supersedes": {"type": "string",
                       "description": "When this draft CORRECTS one you staged earlier "
                                      "in this conversation, its proposal id — the old "
                                      "pending draft is resolved as superseded, so the "
                                      "inbox holds one proposal per ask. Leave empty "
                                      "for a new ask."},
        "schedule": {"type": "string",
                     "description": "When the SAME ask also says when or where the "
                                    "agent should run ('every morning at 9am to "
                                    "#ops'), put that clause here, in the user's own "
                                    "words. The agent and its chain then stage as ONE "
                                    "proposal: accepting it creates both together, "
                                    "all or nothing, the chain running as the new "
                                    "agent. Leave empty when the user asked only for "
                                    "an agent."},
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
        "supersedes": {"type": "string",
                        "description": "When this draft CORRECTS one you staged earlier "
                                       "in this conversation, its proposal id — the old "
                                       "pending draft is resolved as superseded, so the "
                                       "inbox holds one proposal per ask. Leave empty "
                                       "for a new ask."},
        "run_as_agent": {"type": "string",
                         "description": "An EXISTING agent (its id or exact name) the "
                                        "chain runs as, when the user names one — its "
                                        "runs and their spend are attributed to that "
                                        "agent. Never invent one; to create a NEW "
                                        "agent with this schedule, use draft_agent "
                                        "with its schedule field instead."},
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
        "evidence": {"type": "string",
                     "description": "The evidence rows behind this proposal (e.g. "
                                    "the run ids from a premortem finding's offer) "
                                    "— recorded verbatim for the approver."},
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


def spotlight_act_tools(connection_id: str, *, session_id: str = "",
                        emit=None) -> list[ToolSpec]:
    """The Act roster — cosmetic applies, structural stages; nothing executes here.

    ``emit`` is the streaming turn's frame channel (SP-9): a staged proposal announces
    itself so the chat can render the record as a card. Caller-owned context, bound by
    closure like everything else here; None from every sync transport."""
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
                "plain chat — always disclose that). When the ask ALSO says when or "
                "where the agent should run, pass that clause as schedule — the agent "
                "and its chain then stage as ONE proposal, accepted or refused "
                "together. Re-drafting after feedback? Pass supersedes with the "
                "earlier proposal id so the inbox holds ONE pending draft per ask. "
                "Quote the summary field verbatim; tell the user where the approval "
                "lives."
            ),
            parameters=_AGENT_PARAMS,
            run=lambda a: draft_agent(connection_id, a, emit=emit),
        ),
        ToolSpec(
            name="draft_automation",
            description=(
                "Turn a described outcome into a validated automation draft (with a "
                "dry-run receipt) and STAGE it for human approval in the inbox — it "
                "never schedules itself. Use for 'every Monday…', 'when X happens…', "
                "'remind/brief me…' asks. When the user names an existing agent it "
                "should run as, pass run_as_agent. Re-drafting after feedback? Pass "
                "supersedes with the earlier proposal id so the inbox holds ONE "
                "pending draft per ask. A refusal with a reason is an answer to "
                "relay, not an error. Quote the summary field verbatim."
            ),
            parameters=_AUTOMATION_PARAMS,
            run=lambda a: draft_automation(connection_id, a, emit=emit),
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
            run=lambda a: pause_or_resume_automation(connection_id, a, emit=emit),
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
            run=lambda a: propose_agent_grant(connection_id, a, emit=emit),
        ),
    ]
