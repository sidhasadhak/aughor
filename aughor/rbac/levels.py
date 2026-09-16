"""HB-1 — the access ladder, and the level each built-in role holds per securable kind.

One ordered ladder for every securable the platform names:

    view < subscribe < edit < manage < own

**Subscribe and Run are one rung** — receiving a thing's departures and running it
are the same trust decision ("this thing may reach me / act for me"), which is why
the ladder has five words and not six; ``RUN`` is an alias, not a level.

A level *covers* every level below it — holding ``manage`` answers a ``subscribe``
question with yes. There is **no deny**: the model is additive (the group-and-grant
shape the user chose, §6 item 24), so a person's effective level on a securable is the MAX
over everything they hold — their roles' defaults, their groups' grants and their
own. What a level does NOT do lives elsewhere on purpose: clearances
(``govern/tags.py``) still compose with AND — a level says what you may do to the
object, a clearance what the data requires of you — and this module stays pure so
both remain testable without a store.

**The built-in groups** are the platform-shipped defaults (§6 item 24 (d)): today's
three roles,
stored values unchanged (``viewer`` / ``analyst`` displayed Editor / ``owner``),
each carrying a default level per securable kind rather than one uniform verb. The
mapping below is derived from the permission bundles the roles already hold —
``viewer`` reads everything, ``analyst`` writes work but holds no governance verb,
``owner`` holds everything — so nobody's reach moves when the defaults
switch on. A Steward (manages definitions, not connections) arrives as data when a
deployment asks; it is deliberately absent here.
"""
from __future__ import annotations

from aughor.rbac.roles import ANALYST, OWNER, VIEWER

# ── The ladder (ordered, least to most) ──────────────────────────────────────
VIEW = "view"
SUBSCRIBE = "subscribe"
EDIT = "edit"
MANAGE = "manage"
OWN = "own"

#: Run is Subscribe's other name, never a sixth rung.
RUN = SUBSCRIBE

LADDER: tuple[str, ...] = (VIEW, SUBSCRIBE, EDIT, MANAGE, OWN)
_RANK: dict[str, int] = {name: i for i, name in enumerate(LADDER)}


def is_level(name: str) -> bool:
    """Whether ``name`` is a rung of the ladder (``run`` normalises to subscribe)."""
    return normalize_level(name) in _RANK


def normalize_level(name: str) -> str:
    """Lower-cased, with the ``run`` alias folded onto subscribe. Unknown strings
    pass through unchanged so the caller's error can name what it saw."""
    n = (name or "").strip().lower()
    return SUBSCRIBE if n == "run" else n


def level_covers(held: str, needed: str) -> bool:
    """True when holding ``held`` answers a ``needed`` question with yes.

    Fail-closed on vocabulary: an unknown level on EITHER side covers nothing and
    is covered by nothing — a typo must read as a refusal, never as a grant.
    """
    h, n = normalize_level(held), normalize_level(needed)
    if h not in _RANK or n not in _RANK:
        return False
    return _RANK[h] >= _RANK[n]


# ── Role defaults — a level per securable kind (§6 item 24 (d)) ──────────────
#
# Keyed by the STORED role name. ``"*"`` is the default for any securable kind the
# role has no specific word about; a specific kind overrides it. The analyst's
# agent/automation rung is EDIT like the rest of their work surface — creating an
# automation is `resource.write` today and the default changes no one's reach — while
# MANAGE (governance: other people's grants, an org's groups) stays owner's.
ROLE_DEFAULT_LEVELS: dict[str, dict[str, str]] = {
    VIEWER: {"*": VIEW},
    ANALYST: {"*": EDIT},
    OWNER: {"*": OWN},
}


def role_default_level(role_name: str, securable_kind: str) -> str | None:
    """The default level ``role_name`` carries on securables of ``securable_kind``,
    or None for an unknown role (fail-closed, like an unknown role's
    permissions)."""
    table = ROLE_DEFAULT_LEVELS.get((role_name or "").strip().lower())
    if table is None:
        return None
    return table.get((securable_kind or "").strip().lower(), table.get("*"))
