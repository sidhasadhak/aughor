"""Dry-run binding verification (P1b, the live half beyond column-existence).

Column-existence (resolver.verify_binding_columns) checks names against the catalog; this
actually asks the DATABASE whether each bound column is queryable (catches type/permission/
view issues a name check misses) by dry-running a zero-row probe. The `conn` only needs a
`dry_run(sql) -> (ok, error)` method, so it's trivially faked in tests. Never raises.
"""
from __future__ import annotations

import re


def _safe_ident(name: str) -> str:
    """Keep only identifier-safe chars (the probe targets resolver/introspection-derived names,
    but never trust blindly into SQL)."""
    return re.sub(r"[^A-Za-z0-9_.]", "", name or "")


def dry_run_binding(conn, binding: dict) -> tuple[bool, list[str]]:
    """Dry-run a zero-row SELECT for every bound column. Returns (ok, errors). A value-role
    (no table) is skipped. ok == True iff every probe binds."""
    errors: list[str] = []
    for role, b in (binding or {}).items():
        if not isinstance(b, dict):
            continue
        table = _safe_ident(b.get("table") or "")
        # The role's own column and every attribute's column (`columns`, IP-3): a recipe reads the
        # attributes, so an attribute bound to a column that is not there is the failure that matters.
        cols = [c for c in dict.fromkeys(
            [_safe_ident(b.get("column") or "")]
            + [_safe_ident(str(v)) for v in (b.get("columns") or {}).values()]) if c]
        if not table:
            continue
        sql = f"SELECT {', '.join(cols)} FROM {table} LIMIT 0" if cols else f"SELECT * FROM {table} LIMIT 0"
        try:
            ok, err = conn.dry_run(sql)
        except Exception as e:
            ok, err = False, str(e)
        if not ok:
            errors.append(f"{role}: {err}")
    return (not errors, errors)
