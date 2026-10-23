"""A dashboard's cards — kept in the card store (Arc CT, CT-3; the home moved in CT-7).

**No new store.** ``aughor.cards`` has kept cards by scope since it was written. A
person's dashboard reads two of its scopes:

* ``connection`` — the cards pinned for everyone on the connection. These are the cards the
  Briefing's dashboard drew before dashboards had names, and anyone's dashboard may place them.
* ``user`` — the person's own. A card a person's dashboard creates is kept here, so a limit
  set on it is theirs and nobody else's dashboard shows it.

A card placed in a dashboard is not moved by being placed: the spec points at it.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from aughor.dashboards.home import Home
from aughor.cards.models import StoredCard

SHARED = "connection"
OWN = "user"


class Refused(ValueError):
    """A card that may not be kept. ``str(exc)`` is the sentence to show."""


def shared(connection_id: str) -> list[StoredCard]:
    """The cards pinned for everyone on the connection, newest first."""
    from aughor.cards.store import list_cards
    return list_cards(connection_id=connection_id, scope=SHARED, scope_ref=connection_id)


def own(home: Home) -> list[StoredCard]:
    """The person's own cards on this connection, newest first."""
    from aughor.cards.store import list_cards
    return list_cards(connection_id=home.connection_id, scope=OWN, scope_ref=home.owner)


def cards_of(home: Home) -> list[StoredCard]:
    """Every card this person's dashboard may place: their own, then the connection's."""
    return [*own(home), *shared(home.connection_id)]


def place(home: Home, card: StoredCard, *, metric: Optional[Any] = None) -> StoredCard:
    """Keep ``card`` as this person's own, on this connection.

    ``metric`` is the approved :class:`~aughor.semantic.metrics.MetricDefinition` the card was
    made from, when it was made from one. The card then records the metric's name and the
    version it had, so a later change to the metric can be seen against the card.
    A metric that is not approved is refused: a draft is nobody's word yet.
    """
    from aughor.cards.store import get_card, upsert_card

    # A card's id is its own across the whole store, and an upsert by id MOVES the row. So a
    # card that already lives somewhere else is refused rather than quietly taken from there.
    held = get_card(card.id) if card.id else None
    if held is not None and (held.scope, held.scope_ref) != (OWN, home.owner):
        raise Refused(
            f'The card "{card.id}" already belongs to the {held.scope} "{held.scope_ref}". '
            "A card lives in one place; make a new one.")
    if card.connection_id and card.connection_id != home.connection_id:
        raise Refused(
            f'The card "{card.title or card.id}" reads the connection "{card.connection_id}"; '
            f'this dashboard is on "{home.connection_id}". A dashboard holds cards of its own connection.')

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
        "scope": OWN, "scope_ref": home.owner, "connection_id": home.connection_id,
        "provenance": provenance}))


def same_card_key(card: Any) -> str:
    """What makes two cards one: the approved metric each was made from; else the same kind, title
    and query, spaced and cased alike — a copy. Two definitions of one figure under different names
    are the metric approval's to catch (``semantic/metric_twins.py``), by their figures."""
    metric = str(getattr(getattr(card, "provenance", None), "metric", "") or "")
    if metric:
        return f"metric:{metric}"
    sql = " ".join(str(getattr(card, "sql", "") or "").lower().split()).rstrip("; ")
    title = " ".join(str(getattr(card, "title", "") or "").lower().split())
    return f"copy:{getattr(card, 'kind', '')}|{title}|{sql}" if sql else ""


def not_offered(home: Home, held: list, placed: Iterable[str]) -> dict[str, str]:
    """Why each card the dashboard does NOT place is not offered back to it, by card id (the user,
    2026-10-08: duplicates removed "from all places"): superseded by another card, made from a
    metric that was deprecated, or a copy of a card already on the dashboard. Said beside the list,
    never silently dropped."""
    from aughor.semantic.metrics import list_metrics

    on = set(placed)
    by_id = {c.id: c for c in held}
    placed_keys = {same_card_key(by_id[i]): by_id[i] for i in on if i in by_id and same_card_key(by_id[i])}
    deprecated = {m.name for m in list_metrics(connection_id=home.connection_id)
                  if m.status == "deprecated" and m.connection == home.connection_id}
    out: dict[str, str] = {}
    for c in held:
        if c.id in on:
            continue
        superseded = str(getattr(c.provenance, "superseded_by", "") or "")
        metric = str(getattr(c.provenance, "metric", "") or "")
        twin = placed_keys.get(same_card_key(c)) if same_card_key(c) else None
        if superseded:
            other = by_id.get(superseded)
            out[c.id] = f"superseded by “{other.title if other else superseded}”"
        elif metric and metric in deprecated:
            out[c.id] = f"made from {metric}, which was deprecated"
        elif twin is not None:
            out[c.id] = f"a copy of “{twin.title or twin.id}”, already on this dashboard"
    return out


def take_over(home: Home, card: StoredCard) -> StoredCard:
    """Make a card that belonged to a canvas this person's own (CT-10: a canvas dashboard moved
    to the Briefing). The card is the same card — its id, its query, its history — kept in a
    new place; the one move this module makes, and only for a card of the same connection."""
    from aughor.cards.store import upsert_card
    if card.connection_id != home.connection_id:
        raise Refused(f'The card "{card.title or card.id}" is on another connection.')
    return upsert_card(card.model_copy(update={"scope": OWN, "scope_ref": home.owner}))
