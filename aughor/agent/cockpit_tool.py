"""The one tool a cockpit is asked for with (Arc CT, CT-5; ROADMAP §3.50).

Offered on a turn only when three things hold, and absent otherwise — a tool the model can
see is a tool it will spend a turn trying:

* ``cockpit.composed`` is on. Off, the tool list is exactly what it was.
* the turn is in a Data Canvas. A cockpit belongs to one; there is none to draft elsewhere.
* the turn has a channel. What this tool makes is a proposal a person approves on a card,
  and a card needs somewhere to be drawn.

It takes three shapes of call. ``options`` costs nothing and says what a cockpit here may be
made of and how one is written — kept out of the description on purpose, because a
description is sent on every turn in every canvas and that text is wanted on the few turns
that ask for a cockpit. ``new`` and ``edit`` stage ONE proposal and change nothing.

The work is the platform's (``aughor/cockpit/propose.py``). This module is the agent's side
of it: the words the model reads, and the frame the chat draws the card from.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from aughor.agent.tool_loop import ToolSpec
from aughor.cockpit.propose import MAX_NEW_CARDS

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict], None]

FLAG = "cockpit.composed"

_CARD = {
    "type": "object",
    "properties": {
        "key": {"type": "string", "description": (
            "A name of your own for this new card, e.g. return-rate. Place the card in the spec by this name.")},
        "metric": {"type": "string", "description": "The approved metric this card measures, by its name."},
        "trusted_query": {"type": "string", "description": "The trusted query this card draws, by its id."},
        "finding": {"type": "string", "description": "The finding of this canvas this card shows, by its id."},
        "title": {"type": "string", "description": (
            "What the card is called. Leave it out to use the record's own name. It states no figure.")},
        "limit": {"type": "object", "description": (
            "Only when the user named one, and only on a card that shows a single figure: the value at which "
            "the card is over its limit."),
            "properties": {
                "warning": {"type": "number"},
                "critical": {"type": "number"},
                "direction": {"type": "string", "enum": ["above", "below"],
                              "description": "Crossed by going above it (the default) or below it."},
            }},
    },
    "required": ["key"],
}

_PARAMS = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["options", "new", "edit"], "description": (
            "options: what a cockpit here may be made of, the cockpit as it stands, and how one is written. "
            "new: draft a whole cockpit. edit: draft a change to the one that stands.")},
        "cards": {"type": "array", "items": _CARD, "maxItems": MAX_NEW_CARDS, "description": (
            f"new or edit: the cards to CREATE, at most {MAX_NEW_CARDS} to a draft, each made from exactly one "
            "of metric, trusted_query or finding. Every name the spec places that is not the id of a card the "
            "canvas holds must be listed here. A card the canvas already holds is not listed; the spec places "
            "it by its id.")},
        "spec": {"type": "object", "description": "new: the whole cockpit, as options describes it."},
        "patches": {"type": "array", "items": {"type": "object"}, "description": (
            "edit: RFC 6902 operations against the cockpit as it stands.")},
        "reasoning": {"type": "string", "description": "One or two sentences on why it is arranged this way."},
    },
    "required": ["op"],
}


def _announce(emit: Optional[Emit], p: Any) -> None:
    """The staged proposal, on the turn's frame channel, so the chat draws the RECORD as a
    card. Best-effort: a dropped frame loses a card on screen, never a proposal."""
    if emit is None:
        return
    try:
        emit("proposal_staged", {"proposal_id": p.id, "kind": p.kind,
                                 "connection_id": p.connection_id,
                                 "action_id": p.action_id})
    except Exception:
        logger.debug("proposal_staged frame dropped", exc_info=True)


def _count(n: int, one: str) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {one}s"


def draft_cockpit(connection_id: str, canvas_id: str, args: dict, *, emit: Optional[Emit] = None) -> dict:
    from aughor.cockpit import propose

    op = str((args or {}).get("op") or "options")
    if op == "options":
        return propose.options(connection_id, canvas_id)
    if op not in (propose.MODE_NEW, propose.MODE_EDIT):
        said = f'"{op}" is not one of: options, new, edit.'
        return {"staged": False, "refused": [said], "error": said,
                "summary": f'Nothing staged: "{op}" is not one of options, new, edit.'}

    drafted = propose.draft(
        connection_id, canvas_id, mode=op, spec=args.get("spec"), patches=args.get("patches"),
        cards=args.get("cards"), reasoning=str(args.get("reasoning") or ""))
    if not drafted.staged:
        # `error` is what the platform keeps of a step's result, always (the tool loop's step
        # record). Without it a refused draft's reasons went to the model and nowhere else,
        # and nobody reading the run afterwards could say why it took two rounds. The
        # sentences are said once more in `refused`, one to a line, for the writer to repair.
        said = " ".join(drafted.refusals)
        if drafted.not_checked:
            return {"staged": False, "could_not_check": True, "refused": list(drafted.refusals),
                    "error": said,
                    "summary": "Nothing staged, and drafting it again will not help. Tell the user why."}
        return {"staged": False, "refused": list(drafted.refusals), "error": said,
                "summary": "Nothing staged. Repair every point in `refused`, then draft it again."}

    p = drafted.proposal
    _announce(emit, p)
    detail = p.detail or {}
    n = detail.get("counts") or {}
    shape = ", ".join(filter(None, [
        _count(n.get("tabs", 0), "tab") if n.get("tabs") else "",
        _count(n.get("sections", 0), "section"),
        _count(n.get("cards", 0), "card") + (f" ({n['new']} new)" if n.get("new") else ""),
    ]))
    before = detail.get("replaces_version")
    what = (f'an edit to the cockpit "{detail.get("title")}", which stands at version {before}'
            if op == propose.MODE_EDIT else f'the cockpit "{detail.get("title")}"')
    replaced = (f" It replaces the earlier draft{'s' if len(drafted.replaced) != 1 else ''} "
                f"{', '.join(drafted.replaced)}." if drafted.replaced else "")
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "summary": (f"Drafted {what}: {shape} (proposal {p.id}). Nothing is changed yet. A person approves "
                    f"it on the card, all of it or none of it, and it then appears in this canvas's Cockpit tab."
                    f"{replaced}"),
    }


def cockpit_tools(connection_id: str, *, emit: Optional[Emit] = None,
                  canvas_id: Optional[str] = None) -> list[ToolSpec]:
    """``draft_cockpit``, when the flag is on and the turn is in a canvas with a channel."""
    if emit is None or not canvas_id:
        return []
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled(FLAG):
        return []
    return [ToolSpec(
        name="draft_cockpit",
        description=(
            "Draft this Data Canvas's cockpit, or a change to it. A cockpit is the standing set of cards a "
            "person keeps watching: cards in sections, in tabs when there are many, some shown only on a "
            "condition such as a figure crossing its limit. Use this when the user asks to build, make, "
            "change or rearrange one here; they may call it a dashboard or a board, and in your answer it "
            "is a cockpit. Call it FIRST with op options: that returns what a "
            "cockpit here may be made of, the cockpit as it stands, and how one is written. Then call it "
            "with op new and the whole spec, or op edit and the operations. You write no SQL and state no "
            "figure: a new card names the approved metric, the trusted query or the finding it is made "
            "from. It STAGES one proposal and changes nothing; a person approves it on the card, all of it "
            "or none. When it refuses it names every fault: repair them all, then call again. Quote the "
            "summary field verbatim."
        ),
        parameters=_PARAMS,
        run=lambda a: draft_cockpit(connection_id, canvas_id, a, emit=emit),
    )]
