"""HB-1 — the routing half: where a departure about a securable GOES.

The deterministic sentence the arc specced: **a breach goes to the promise's owner
and its subscribers, and no model decides who gets what** (§3.18). This module is
that sentence as a function — pure resolution, no sending: HB-2's departure gate
will call it and the receipt doors call it today, so routing is inspectable before
anything ships a message.

Destinations come from two places, both named in ``why``:

  - **the owner** — the object's ``owner`` field read as a principal.
    ``owner_principal`` INTERPRETS the existing free-text field (``group:finance``,
    ``user:ana@corp``, ``agent:ua_x``); free text that is not a principal string
    stays what it always was — display text, honest and unrouted. That is the
    migration path §3.18 asked for without rewriting a single YAML file: the
    organisation's overrides tree is edited by people only (§6 item 20), so people
    adopt the principal spelling one owner at a time and each becomes routable the
    day they do.
  - **the subscribers** — every principal holding Subscribe-or-higher on the
    securable's chain (itself, its meaning parents, its ``domain`` tag securables —
    the same chain ``access.may`` walks, so routing and access can never disagree
    about coverage).

A **group** destination carries the group's channel (its Action Hub trigger id);
a person or agent destination is direct (no channel — the caller decides how to
reach an individual, which is HB-5's ground, not this wave's). One destination per
(principal, channel), whys merged — the noise-band law ("never the same finding
twice") starts at the router.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from aughor.metastore.models import principal_kind
from aughor.rbac.access import securable_chain
from aughor.rbac.levels import SUBSCRIBE, is_level, level_covers, normalize_level


@dataclass(frozen=True)
class Destination:
    """One place a departure about a securable lands."""
    principal: str            # who receives (user: / group: / agent:)
    channel_trigger_id: str   # the group's channel ("" = direct, no channel bound)
    group_id: str             # the group behind the channel ("" = direct)
    why: tuple[str, ...]      # the grants/ownership that put it here

    def to_dict(self) -> dict:
        return {"principal": self.principal, "channel_trigger_id": self.channel_trigger_id,
                "group_id": self.group_id, "why": list(self.why)}


def owner_principal(owner_text: str) -> Optional[str]:
    """The principal an ``owner`` field names, or None when it is display text.

    Reads, never rewrites: ``"group:supply-chain"`` routes, ``"Ana (logistics)"``
    stays the honest label it always was.
    """
    text = (owner_text or "").strip()
    return text if principal_kind(text) in ("user", "group", "agent") else None


def route(securable: str, *, org_id: str, owner: str = "",
          parents: Sequence[str] = (),
          tags: Optional[Mapping[str, str]] = None) -> list[Destination]:
    """Every destination for a departure about ``securable`` — owner first, then
    subscribers, deduplicated. ``owner`` is the object's owner field as stored
    (free text welcome; only a principal spelling routes)."""
    gathered: dict[tuple[str, str, str], list[str]] = {}

    def _add(principal: str, why: str) -> None:
        channel, group_id = "", ""
        if principal_kind(principal) == "group":
            group_id = principal.partition(":")[2]
            g = _get_group(org_id, group_id)
            if g is None:
                # A grant naming a deleted group grants nobody anything — and routes
                # nothing, rather than routing into a channel that no longer exists.
                return
            channel = g.channel_trigger_id
        gathered.setdefault((principal, channel, group_id), []).append(why)

    own = owner_principal(owner)
    if own:
        _add(own, f"owner of {securable}")

    chain = securable_chain(securable, parents, tags)
    for g in _subscribe_grants(org_id, chain):
        on = "it" if g.securable == securable else g.securable
        _add(g.principal,
             f"{g.principal} holds {normalize_level(g.privilege)} on {on}")

    return [Destination(p, ch, gid, tuple(whys))
            for (p, ch, gid), whys in gathered.items()]


def _subscribe_grants(org_id: str, chain: Sequence[str]) -> list:
    """Every grant on the chain at Subscribe or above (a Manage-holder subscribes by
    covering, the ladder's whole point)."""
    from aughor.metastore.store import list_grants
    out = []
    for s in chain:
        try:
            out.extend(
                g for g in list_grants(org_id=org_id, securable=s)
                if is_level(g.privilege) and level_covers(g.privilege, SUBSCRIBE)
            )
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "grant lookup failed — that securable routes nothing",
                     counter="rbac.routing.grants")
    return out


def _get_group(org_id: str, group_id: str):
    try:
        from aughor.rbac.groups import get_group
        return get_group(org_id, group_id)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "group lookup failed — that group routes nothing",
                 counter="rbac.routing.groups")
        return None
