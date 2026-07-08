"""RBAC row-level policy (Rec 7) — declarative per-role, per-table row filters.

The row-level twin of ``rbac/policy.py`` (which maps endpoints → permissions): a declarative table of
``{role: {table: predicate}}`` that ``sql/rls.py`` compiles into the executed SQL's WHERE, so a role
physically cannot read rows outside its filter. Predicates are templates over the caller's identity —
``{org_id}`` / ``{user_id}`` placeholders, substituted (single-quote-escaped) at query time.

Ships EMPTY: the mechanism is inert until a deployment declares policies here (or a future admin store
populates them). The most common policy is tenant isolation, e.g.::

    ROW_POLICIES = {
        "viewer":  {"orders": "org_id = '{org_id}'"},
        "analyst": {"orders": "org_id = '{org_id}'"},
    }

Owner is never filtered (sees everything). A caller holding several roles resolves to the MOST-permissive
role's filter set (viewer ⊂ analyst ⊂ owner — the role ladder), mirroring the permission model.
"""
from __future__ import annotations

from aughor.rbac.roles import ANALYST, OWNER, VIEWER

# {role_name: {table_name: predicate_template}} — declare a deployment's row policies here. Empty = inert.
ROW_POLICIES: dict[str, dict[str, str]] = {}

# Role precedence for picking the effective filter set (higher = more permissive).
_RANK = {VIEWER: 1, ANALYST: 2, OWNER: 3}


def _esc(value: str) -> str:
    """Escape a session value for safe interpolation inside a single-quoted SQL literal."""
    return (value or "").replace("'", "''")


def resolve_row_filters(roles: list[str], org_id: str, user_id: str) -> dict[str, str]:
    """The concrete ``{table: predicate}`` filters for a caller, or ``{}`` when unrestricted.

    Owner (or any caller with no policy for their effective role) is unrestricted. The caller's
    most-permissive role selects the policy set; ``{org_id}``/``{user_id}`` are substituted safely."""
    if not roles or OWNER in roles:
        return {}
    effective = max(roles, key=lambda r: _RANK.get(r, 0))
    templates = ROW_POLICIES.get(effective, {})
    if not templates:
        return {}
    org_e, user_e = _esc(org_id), _esc(user_id)
    return {
        table: pred.replace("{org_id}", org_e).replace("{user_id}", user_e)
        for table, pred in templates.items()
    }
