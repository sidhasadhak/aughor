"""The one tool a cockpit is drafted with (Arc CT, CT-5; bound to a person's cockpit in CT-7).

It was first offered in a Data Canvas's chat. The canvas is for investigation (§6 item
36(l)), so it is offered nowhere a person talks to a model now: the Briefing's "new cockpit"
runs a model with this tool ALONE, bound to the cockpit it drafts (``aughor/cockpit/ask.py``).

It takes three shapes of call. ``options`` costs nothing and says what a cockpit here may be
made of and how one is written. ``new`` and ``edit`` stage ONE proposal and change nothing.

The work is the platform's (``aughor/cockpit/propose.py``). This module is the agent's side
of it: the words the model reads, and the frame a screen draws the draft from.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from aughor.agent.tool_loop import ToolSpec
from aughor.cockpit.home import Home
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
        "finding": {"type": "string", "description": "The finding the Briefing shows that this card shows, by its id."},
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
            "person has must be listed here. A card they already have is not listed; the spec places it by "
            "its id.")},
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


def _shows(card: dict) -> str:
    """What a new card shows, in a reader's words. Said in the summary, so a person reads it
    before keeping: the third run of the receipt found "which categories sell best" drafted
    as a cockpit of totals, and nothing said so."""
    if card.get("kind") != "kpi":
        return f'"{card.get("title")}", a chart of its rows'
    whole = " for the whole connection" if card.get("from") == "metric" else ""
    return f'"{card.get("title")}", one figure{whole}'


def draft_cockpit(home: Home, args: dict, *, emit: Optional[Emit] = None, said: Optional[str] = None,
                  schema: Optional[str] = None) -> dict:
    """``said`` is what the person asked for; a limit is set only where they named it."""
    from aughor.cockpit import propose

    op = str((args or {}).get("op") or "options")
    if op == "options":
        return propose.options(home, schema)
    if op not in (propose.MODE_NEW, propose.MODE_EDIT):
        told = f'"{op}" is not one of: options, new, edit.'
        return {"staged": False, "refused": [told], "error": told,
                "summary": f'Nothing staged: "{op}" is not one of options, new, edit.'}

    drafted = propose.draft(
        home, mode=op, spec=args.get("spec"), patches=args.get("patches"),
        cards=args.get("cards"), reasoning=str(args.get("reasoning") or ""), said=said, schema=schema)
    if not drafted.staged:
        # `error` is what the platform keeps of a step's result, always (the tool loop's step
        # record). Without it a refused draft's reasons went to the model and nowhere else,
        # and nobody reading the run afterwards could say why it took two rounds. The
        # sentences are said once more in `refused`, one to a line, for the writer to repair.
        told = " ".join(drafted.refusals)
        if drafted.not_checked:
            return {"staged": False, "could_not_check": True, "refused": list(drafted.refusals),
                    "error": told,
                    "summary": "Nothing staged, and drafting it again will not help. Tell the user why."}
        return {"staged": False, "refused": list(drafted.refusals), "error": told,
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
    made = [c for c in (p.params or {}).get("cards") or [] if isinstance(c, dict)]
    shows = f" The new cards show: {'; '.join(_shows(c) for c in made)}." if made else ""
    # A new cockpit where one stands replaces it whole. Said in the summary: the third run of
    # the receipt found two that would have taken off 9 and 12 cards, and nothing said it.
    whole = ""
    if op == propose.MODE_NEW and before:
        gone = [t["title"] for t in detail.get("taken_off") or [] if t.get("what") == "card"]
        whole = (f" It replaces the cockpit that stands (version {before}) whole"
                 + (f", and takes off {len(gone)} of its cards: {'; '.join(gone)}." if gone
                    else "; every card on it is kept.")
                 + " To add to that cockpit instead, draft an edit.")
    replaced = (f" It replaces the earlier draft{'s' if len(drafted.replaced) != 1 else ''} "
                f"{', '.join(drafted.replaced)}." if drafted.replaced else "")
    return {
        "staged": True, "proposal_id": p.id, "expires_at": p.expires_at,
        "summary": (f"Drafted {what}: {shape} (proposal {p.id}).{shows}{whole} Nothing is changed yet. The "
                    f"person keeps it, all of it or none of it, and it then appears among their cockpits in "
                    f"the Briefing.{replaced}"),
    }


def drafting_tool(home: Home, *, emit: Optional[Emit] = None, said: Optional[str] = None,
                  schema: Optional[str] = None) -> ToolSpec:
    """``draft_cockpit``, bound to one person's cockpit. The cockpit, the person and what they
    asked for bind by closure: none of them is the model's to state."""
    return ToolSpec(
        name="draft_cockpit",
        description=(
            "Draft a cockpit for a person's Briefing, or a change to one. A cockpit is the standing set "
            "of cards a person keeps watching for one area of the business: cards in sections, in tabs "
            "when there are many, some shown only on a condition such as a figure crossing its limit. "
            "Call it FIRST with op options: that returns what a cockpit here may be made of, the "
            "cockpit as it stands, and how one is written. Then call it with op new and the whole "
            "spec, or op edit and the operations. You write no SQL and state no figure: a new card "
            "names the approved metric, the trusted query or the finding it is made from. It STAGES "
            "one proposal and changes nothing; the person keeps it or not. When it refuses it names "
            "every fault: repair them all, then call again."
        ),
        parameters=_PARAMS,
        run=lambda a: draft_cockpit(home, a, emit=emit, said=said, schema=schema),
    )
