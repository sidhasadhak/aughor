"""A cockpit published to a group or a role (the canvas, docs/COCKPIT_CANVAS_2026-10-08.md, B5).

A cockpit is a person's own. Publishing it makes its current version readable by the members of a
group or the holders of a role, under the publisher's name, with the same record a kept version
has: publishing is a version, and so is unpublishing. A reader reads it as it stands — the period
their own choice, a card they may not read standing and saying so — and may start a cockpit of
their own from it, which copies the publisher's own cards into theirs and keeps the spec as the
first version of a new cockpit, with the notes' stamps carried as the publisher's.

**Who may publish where** (the user's call, 2026-10-08): any member, to a group they belong to; a
role needs the role itself, or the permission that administers roles. Who may READ is the same
list from the other side: a cockpit reaches a person through a group they are in or a role they
hold. With identity off there is one operator, who is every group's nobody and the owner role.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any, Optional

from aughor.cockpit.home import NOBODY_IN_PARTICULAR, Home, new_id

GROUP = "group"
ROLE = "role"
KINDS = (GROUP, ROLE)


class Refused(Exception):
    """Why a cockpit is not published, read or copied, in a sentence a person can act on."""


def _org() -> str:
    from aughor.org.context import current_org_id
    return current_org_id() or "default"


def _principal(user_id: str):
    """The principal the RBAC resolver reads roles for: none where identity is off."""
    if not user_id or user_id == NOBODY_IN_PARTICULAR:
        return None
    from aughor.security.authz import Principal
    return Principal(user_id=user_id, org_id=_org())


def audience_of(user_id: str) -> dict:
    """The groups this person belongs to and the roles they hold — what a published cockpit
    reaches them through, and what they may publish to."""
    from aughor.metastore.models import user_principal
    from aughor.rbac.groups import get_group, groups_of
    from aughor.rbac.resolver import resolve_roles
    from aughor.rbac.roles import BUILTIN_ROLES
    org = _org()
    groups = []
    if user_id and user_id != NOBODY_IN_PARTICULAR:
        for gid in groups_of(org, user_principal(user_id)):
            g = get_group(org, gid)
            groups.append({"kind": GROUP, "id": gid, "name": (g.name if g else gid)})
    roles = [{"kind": ROLE, "id": r, "name": BUILTIN_ROLES[r].label if r in BUILTIN_ROLES else r}
             for r in resolve_roles(_principal(user_id))]
    return {"groups": groups, "roles": roles}


def _said(items: list[dict]) -> str:
    return ", ".join(f'"{i["name"]}"' for i in items) or "nothing"


def may_publish_to(user_id: str, target: Any) -> tuple[Optional[dict], str]:
    """The target as it is kept — ``{"kind", "id", "name"}`` — or ``(None, why not)``. A target is
    named by its id or its name."""
    if not isinstance(target, dict):
        return None, "A cockpit is published to a group or a role, each as {kind, id or name}."
    kind = str(target.get("kind") or "")
    ident = str(target.get("id") or target.get("name") or "").strip()
    aud = audience_of(user_id)
    if kind == GROUP:
        hit = next((g for g in aud["groups"] if g["id"] == ident or g["name"].lower() == ident.lower()), None)
        if hit:
            return hit, ""
        from aughor.rbac.groups import get_group
        g = get_group(_org(), ident)
        return None, (f'You are not a member of the group "{g.name if g else ident}", so you cannot publish to it. '
                      f"You can publish to: {_said(aud['groups'])}.")
    if kind == ROLE:
        hit = next((r for r in aud["roles"] if r["id"] == ident or r["name"].lower() == ident.lower()), None)
        if hit:
            return hit, ""
        from aughor.rbac.permissions import Permission
        from aughor.rbac.resolver import has_permission
        from aughor.rbac.roles import BUILTIN_ROLES
        known = next((r for r in BUILTIN_ROLES if r == ident or BUILTIN_ROLES[r].label.lower() == ident.lower()), None)
        if known and has_permission(_principal(user_id), Permission.ADMIN_MANAGE_ROLES):
            return {"kind": ROLE, "id": known, "name": BUILTIN_ROLES[known].label}, ""
        if known is None:
            return None, f'There is no role "{ident}". The roles are: {", ".join(r.label for r in BUILTIN_ROLES.values())}.'
        return None, (f'Publishing to the role "{BUILTIN_ROLES[known].label}" needs that role, or admin.manage_roles. '
                      f"You hold: {_said(aud['roles'])}.")
    return None, f'A cockpit is published to a group or a role, not "{kind or "nothing"}".'


def reaches(published_to: Any, audience: dict) -> bool:
    mine = {(a["kind"], a["id"]) for a in audience.get("groups", []) + audience.get("roles", [])}
    return any(isinstance(t, dict) and (t.get("kind"), t.get("id")) in mine for t in (published_to or []))


def _owner_and_id(key: str, connection_id: str) -> tuple[str, str]:
    rest = key[len(f"cockpit:person:{connection_id}:"):]
    owner, _, cockpit_id = rest.rpartition(":")
    return owner, cockpit_id


def shared_with(connection_id: str, user_id: str) -> list[dict]:
    """The cockpits others on this connection have published to a group this person is in or a
    role they hold, as they stand now. The person's own are not listed: they are theirs."""
    from aughor.cockpit import versions
    from aughor.kernel.ledger import Ledger
    audience = audience_of(user_id)
    out = []
    for row in Ledger.default().artifacts_of_kind(versions.KIND, conn_id=connection_id, limit=1000):
        key = str(row.get("natural_key") or "")
        if not key.startswith(f"cockpit:person:{connection_id}:") or not versions.is_mine(row):
            continue
        payload = row["payload"]
        if payload.get("retired") or not payload.get("published_to") or not payload.get("spec"):
            continue
        owner, cockpit_id = _owner_and_id(key, connection_id)
        if owner == user_id or not reaches(payload["published_to"], audience):
            continue
        out.append({"owner": owner, "cockpit_id": cockpit_id, "title": versions.title_of(payload.get("spec")),
                    "version": row.get("version"), "kept_at": row.get("created_at") or "",
                    "published_by": payload.get("published_by") or "", "published_to": list(payload["published_to"])})
    return sorted(out, key=lambda c: (c["title"].lower(), c["owner"]))


def read_shared(connection_id: str, owner: str, cockpit_id: str, *, reader: str) -> dict:
    """A published cockpit as it stands, for a reader it reaches: ``{"home", "cockpit"}``. The
    owner reads their own through here too, as a reader would."""
    from aughor.cockpit import versions
    home = Home(connection_id, owner, cockpit_id)
    kept = versions.latest(home)
    if kept is None or kept["retired"] or not kept.get("spec"):
        raise Refused("This cockpit is not shared with you, or it was retired.")
    if owner != reader and not reaches(kept.get("published_to"), audience_of(reader)):
        raise Refused("This cockpit is not shared with you.")
    return {"home": home, "cockpit": kept}


def copy_for(connection_id: str, owner: str, cockpit_id: str, *, reader: str, approved_by: str) -> dict:
    """Start a cockpit of the reader's own from a published one: the publisher's own cards are
    copied into the reader's, the connection's shared cards are placed by their ids, and the spec
    is kept as the new cockpit's first version with the notes' stamps carried as they were.
    Returns ``{"kept": Kept, "cockpit_id", "title"}``; a refusal is in ``kept``."""
    from aughor.cockpit import cards as _cards
    from aughor.cockpit import versions
    from aughor.cockpit.propose import with_card_ids
    from aughor.dashboard.store import delete_card, upsert_card
    from aughor.kernel.errors import tolerate

    src = read_shared(connection_id, owner, cockpit_id, reader=reader)
    theirs: Home = src["home"]
    kept_src = src["cockpit"]
    title = versions.title_of(kept_src["spec"]) or cockpit_id
    mine = Home(connection_id, reader, new_id(title))
    held = {c.id: c for c in _cards.cards_of(theirs)}
    spec = copy.deepcopy(kept_src["spec"])

    ids: dict[str, str] = {}
    made: list[str] = []
    try:
        for el in spec["elements"].values():
            if not isinstance(el, dict) or el.get("type") != "Card":
                continue
            old = str((el.get("props") or {}).get("card") or "")
            card = held.get(old)
            if card is None or card.scope != _cards.OWN or old in ids:
                continue                          # a shared card is placed by its id; one not held is refused below
            copied = upsert_card(card.model_copy(update={
                "id": uuid.uuid4().hex[:8], "scope": _cards.OWN, "scope_ref": reader,
                "links": [*list(card.links or []), f"copied:{old}"],
            }))
            ids[old] = copied.id
            made.append(copied.id)
    except Exception as exc:
        for cid in made:
            try:
                delete_card(cid)
            except Exception as undo:
                tolerate(undo, f"a copied card ({cid}) could not be removed again", counter="cockpit.copy.undo")
        tolerate(exc, "a published cockpit could not be copied; what was made was removed", counter="cockpit.copy")
        return {"kept": versions.Kept(versions.FAILED, sentences=(f"The cockpit could not be copied: {exc}. Nothing was kept.",)),
                "cockpit_id": "", "title": title}

    kept = versions.keep(mine, with_card_ids(spec, ids), approved_by=approved_by,
                         source=f'started from "{title}", published by {kept_src.get("published_by") or owner} (version {kept_src["version"]})',
                         written_by_model=False, stamps_are_ours=True,
                         came_from=[("copied_from", kept_src["artifact_id"], "a published cockpit")])
    if not kept.kept:
        for cid in made:
            try:
                delete_card(cid)
            except Exception as undo:
                tolerate(undo, f"a copied card ({cid}) could not be removed again", counter="cockpit.copy.undo")
    return {"kept": kept, "cockpit_id": mine.cockpit_id if kept.kept else "", "title": title}
