"""HB-1 — ONE resolver: ``may(principal, level, securable)``, and the ``explain``
that names its grants.

The union the arc specced (§3.18): a person is the union of their roles'
defaults, their groups' grants and their own — additive, no deny, clearances still
the separate AND (``govern/tags.py``). The four existing checks (tier, role,
endpoint policy, clearance) keep their gate sites in this slice — HB-1 is the
ROUTING half, and enforcement rides the same table when identity is on — but every
NEW question routes through here, and the answer always says why:

  - allowed → which grant granted (the clearance decision already names what
    blocked; the union must name what granted — §3.18's own sentence);
  - refused → what was looked at and found nothing.

**Inheritance follows meaning, not storage**, and the MEANING is the caller's to
present: ``parents`` is the securable's chain upward (a promise passes its process,
either passes its domain), because this module must stay pure over stores it does
not own — the ontology knows its shapes, this module only walks what it is handed.
The one parent it derives itself is the grant-bearing tag (§6 item 24 (b)): pass
``tags`` and every ``domain=<v>`` becomes ``domain:<v>`` in the chain.

**Identity off** (``principal_str`` empty/None) resolves to allowed-as-owner,
exactly as ``resolver.resolve_roles`` does — enforcement stays inert where the
platform runs today. **Fail-closed everywhere else:** an unknown level is a refusal,
a store error contributes nothing (never owner), and an agent principal gets NO
role default — an agent holds only what a grant or a group gives it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

from aughor.govern.tags import GRANT_BEARING_KEYS
from aughor.metastore.models import (
    domain_securable,
    group_principal,
    principal_kind,
    securable_kind,
)
from aughor.rbac.levels import is_level, level_covers, normalize_level, role_default_level


@dataclass(frozen=True)
class Decision:
    """An access answer that carries its reasons. ``explain`` is human-prose lines,
    one per grant that contributed (or, on a refusal, what was checked)."""
    allowed: bool
    #: The highest level found ("" when none).
    level: str = ""
    explain: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "level": self.level, "explain": list(self.explain)}


def securable_chain(securable: str, parents: Sequence[str] = (),
                    tags: Optional[Mapping[str, str]] = None) -> list[str]:
    """The securables a grant may sit on to cover ``securable``: itself, its meaning
    parents in the caller's order, then the grant-bearing tags' securables
    (``domain=x`` → ``domain:x``). Deduplicated, order kept — explain reads best when
    the most specific grant is named first."""
    chain: list[str] = [securable]
    chain.extend(p for p in parents if p)
    for key, value in (tags or {}).items():
        if key in GRANT_BEARING_KEYS and value:
            chain.append(domain_securable(value))
    seen: set[str] = set()
    out: list[str] = []
    for s in chain:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _grants_on(org_id: str, securables: Iterable[str]) -> list:
    """Every LEVEL grant on any of ``securables`` in the org. USAGE and any other
    non-ladder privilege belong to the catalog-access plane and are not read here."""
    from aughor.metastore.store import list_grants
    rows = []
    for s in securables:
        try:
            rows.extend(g for g in list_grants(org_id=org_id, securable=s)
                        if is_level(g.privilege))
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "grant lookup failed — contributes nothing (fail-closed)",
                     counter="rbac.access.grants")
    return rows


def holdings(principal_str: Optional[str], securable: str, org_id: str,
             parents: Sequence[str] = (),
             tags: Optional[Mapping[str, str]] = None) -> list[tuple[str, str]]:
    """Every (level, why) ``principal_str`` holds on ``securable`` — the union's raw
    material, shared by :func:`may` and the router. Empty principal → empty (the
    identity-off allowance is :func:`may`'s, not a holding)."""
    if not principal_str:
        return []
    found: list[tuple[str, str]] = []
    chain = securable_chain(securable, parents, tags)

    # 1. Role defaults — a PERSON's roles carry a level per securable kind.
    #    Agents (and any non-user principal) get none: only grants reach them.
    if principal_kind(principal_str) == "user":
        user_id = principal_str.partition(":")[2]
        try:
            from aughor.rbac.store import roles_for_user
            roles = roles_for_user(org_id, user_id)
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "role lookup failed — role defaults contribute nothing",
                     counter="rbac.access.roles")
            roles = []
        kind = securable_kind(securable)
        for role in roles:
            lvl = role_default_level(role, kind)
            if lvl:
                found.append((lvl, f"role {role} holds {lvl} on every {kind or 'securable'} by default"))

    # 2. Grants — the principal's own and each of their groups', on the whole chain.
    try:
        from aughor.rbac.groups import groups_of
        member_of = groups_of(org_id, principal_str)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "membership lookup failed — groups contribute nothing",
                 counter="rbac.access.groups")
        member_of = []
    mine = {principal_str} | {group_principal(g) for g in member_of}
    for g in _grants_on(org_id, chain):
        if g.principal in mine:
            via = "" if g.principal == principal_str else f" (member of {g.principal})"
            on = "" if g.securable == securable else f" on {g.securable}"
            found.append((normalize_level(g.privilege),
                          f"{g.principal} holds {normalize_level(g.privilege)}{on or ' on it'}{via}"))
    return found


def may(principal_str: Optional[str], level: str, securable: str, *,
        org_id: str, parents: Sequence[str] = (),
        tags: Optional[Mapping[str, str]] = None) -> Decision:
    """May ``principal_str`` act at ``level`` on ``securable``? The ONE union.

    ``principal_str`` is a principal string (``user:...`` / ``agent:...``); None or
    "" is identity-off and resolves to yes, as every resolver here always has.
    """
    needed = normalize_level(level)
    if not is_level(needed):
        return Decision(False, "", (f"unknown level {level!r} — refused (a typo must "
                                    "never read as a grant)",))
    if not principal_str:
        return Decision(True, "own", ("identity off — the caller is the owner, as everywhere",))

    found = holdings(principal_str, securable, org_id, parents, tags)
    if not found:
        chain = securable_chain(securable, parents, tags)
        return Decision(False, "", (
            f"nothing held: no role default, no grant to {principal_str} or its "
            f"groups on {' / '.join(chain)}",))

    best = max(found, key=lambda f: _rank(f[0]))
    granted = tuple(why for lvl, why in found if level_covers(lvl, needed))
    if granted:
        return Decision(True, best[0], granted)
    return Decision(False, best[0],
                    (f"held at most {best[0]} ({best[1]}) — {needed} needs more",))


def _rank(level_name: str) -> int:
    from aughor.rbac.levels import LADDER
    try:
        return LADDER.index(normalize_level(level_name))
    except ValueError:
        return -1
