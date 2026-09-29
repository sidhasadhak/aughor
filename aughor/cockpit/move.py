"""A canvas's cockpit, moved to a person's Briefing (Arc CT, CT-10; §6 item 36(l)).

The canvas is for investigation now, and its Cockpit tab is gone. A cockpit approved there
before the home moved still stands in the Ledger under the canvas. Moving it is one act, taken
by a person, never by a read:

1. every card its spec places becomes the person's own (``cards.take_over``) — the same card,
   its query and its history, in a new place;
2. its spec is kept as the first version of the person's cockpit, linked to the canvas
   version it came from;
3. the canvas's cockpit is retired with a note that says where it went.

**Supersede, do not delete.** The canvas history stays readable under its old key. If the
person's version cannot be kept, the cards are put back where they were and nothing moves.
"""
from __future__ import annotations

from typing import Any

from aughor.cockpit import cards as _cards
from aughor.cockpit import versions as _versions
from aughor.cockpit.home import Home, approver, new_id
from aughor.kernel.errors import tolerate


def move_from_canvas(canvas_id: str, *, connection_id: str, owner: str) -> dict[str, Any]:
    """Move one canvas's cockpit to this person. Returns ``{"moved": True, ...}`` or
    ``{"moved": False, "sentences": [...]}`` — never a half-moved cockpit."""
    from aughor.canvas.store import get_canvas
    from aughor.dashboard.store import get_card, upsert_card

    left = _versions.canvas_latest(canvas_id)
    if left is None:
        return _not("This canvas has no cockpit to move.")
    if left["retired"] or not left.get("spec"):
        return _not("This canvas's cockpit was retired or has already moved.")
    canvas = get_canvas(canvas_id)
    if canvas is None or (canvas.primary_connection_id or "") != connection_id:
        return _not("That canvas is not on this connection.")

    spec = left["spec"]
    title = _versions.title_of(spec) or canvas.name
    home = Home(connection_id, owner, new_id(title))
    by = approver(owner)

    # 1. The cards it places, made the person's own. What each was, so a failure can undo it.
    was: list[Any] = []
    try:
        for card_id in dict.fromkeys(left["cards"]):
            card = get_card(card_id)
            if card is None:
                continue
            if (card.scope, card.scope_ref) == ("canvas", canvas_id):
                was.append(card)
                _cards.take_over(home, card)
    except Exception as exc:
        _put_back(was, upsert_card)
        tolerate(exc, "a canvas cockpit's cards could not be moved; they were put back",
                 counter="cockpit.move.cards", canvas_id=canvas_id)
        return _not(f"The cards could not be moved: {exc}. Nothing moved.")

    # 2. The spec, kept as the person's first version, linked to where it came from.
    kept = _versions.keep(
        home, spec, approved_by=by, source=f"moved from the canvas '{canvas.name}'",
        note=f"Version {left['version']} of the canvas's cockpit, moved to the Briefing.",
        written_by_model=left["written_by_model"],
        came_from=[("moved_from", left["artifact_id"], f"canvas {canvas_id}, version {left['version']}")])
    if not kept.kept:
        _put_back(was, upsert_card)
        return {"moved": False, "sentences": [*kept.sentences, "Nothing moved."]}

    # 3. The canvas's cockpit, retired with a note that says where it went.
    gone = _versions.retire_canvas(canvas_id, approved_by=by,
                                   note=f"moved to the Briefing as '{title}'")
    said = [] if gone.kept else [
        "The cockpit was moved, but the canvas's own could not be marked as moved: "
        + (" ".join(gone.sentences) or "no reason was given") + ". It may be offered again; moving it "
        "twice makes a second copy, and nothing is lost."]
    return {"moved": True, **home.as_params(), "title": title, "version": kept.version,
            "cards_moved": len(was), "sentences": said}


def _put_back(cards: list[Any], upsert) -> None:
    for card in cards:
        try:
            upsert(card)
        except Exception as exc:
            tolerate(exc, f"a card of a cockpit that failed to move ({getattr(card, 'id', '')}) could not be put back",
                     counter="cockpit.move.undo", conn_id=getattr(card, "connection_id", None))


def _not(sentence: str) -> dict[str, Any]:
    return {"moved": False, "sentences": [sentence]}
