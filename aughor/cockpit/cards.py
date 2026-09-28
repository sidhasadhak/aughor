"""A cockpit's cards — kept in the card store, at canvas scope (Arc CT, CT-3).

**No new store.** ``aughor.dashboard`` has stored and listed cards by canvas since it was
written (``list_cards(scope='canvas', scope_ref=canvas_id)``); no screen ever asked. This
module is the two calls a cockpit needs over it, and nothing of its own is persisted here.

A card placed for a canvas never appears in the Briefing's cockpit, which lists
``scope='connection'``, and the arrangement the Briefing keeps (``card_layouts``) is not
touched: a composed cockpit is arranged by its spec.
"""
from __future__ import annotations

from typing import Any, Optional

from aughor.dashboard.models import DashboardCard

SCOPE = "canvas"


class Refused(ValueError):
    """A card that may not be placed. ``str(exc)`` is the sentence to show."""


def cards_of(canvas_id: str) -> list[DashboardCard]:
    """The cards this canvas holds, newest first."""
    from aughor.dashboard.store import list_cards
    return list_cards(scope=SCOPE, scope_ref=canvas_id)


def place(canvas_id: str, card: DashboardCard, *, metric: Optional[Any] = None) -> DashboardCard:
    """Keep ``card`` for this canvas, on the canvas's own connection.

    ``metric`` is the approved :class:`~aughor.semantic.metrics.MetricDefinition` the card was
    made from, when it was made from one. The card then records the metric's name and the
    version it had, so a later change to the metric can be seen against the card.
    A metric that is not approved is refused: a draft is nobody's word yet.
    """
    from aughor.canvas.store import get_canvas
    from aughor.dashboard.store import get_card, upsert_card

    canvas = get_canvas(canvas_id)
    if canvas is None:
        raise Refused(f'The canvas "{canvas_id}" does not exist, so no card can be kept for it.')
    # A card's id is its own across the whole store, and an upsert by id MOVES the row. So a
    # card that already lives somewhere else is refused rather than quietly taken from there.
    held = get_card(card.id) if card.id else None
    if held is not None and (held.scope, held.scope_ref) != (SCOPE, canvas_id):
        raise Refused(
            f'The card "{card.id}" already belongs to the {held.scope} "{held.scope_ref}". '
            "A card lives in one place; make a new one for this canvas.")
    conn_id = canvas.primary_connection_id or ""
    if card.connection_id and card.connection_id != conn_id:
        raise Refused(
            f'The card "{card.title or card.id}" reads the connection "{card.connection_id}"; '
            f'the canvas "{canvas.name}" is on "{conn_id}". A canvas holds cards of its own connection.')

    provenance = card.provenance
    if metric is not None:
        status = getattr(metric, "status", "")
        if status != "approved":
            raise Refused(
                f'The metric "{getattr(metric, "name", "")}" is {status or "not approved"}. '
                "A card is made from an approved metric.")
        provenance = provenance.model_copy(update={
            "metric": str(metric.name), "metric_version": int(getattr(metric, "version", 0) or 0)})

    return upsert_card(card.model_copy(update={
        "scope": SCOPE, "scope_ref": canvas_id, "connection_id": conn_id, "provenance": provenance}))
