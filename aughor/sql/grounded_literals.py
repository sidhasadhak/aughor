"""R7 (deferred, closed) — the grounded-literal contract.

Entity resolution (``ask.resolve_first``) binds a question's entity to a
VERIFIED stored value before generation ("Mytheresa" exists in
``brands.brand``) and instructs the model to use it verbatim. That contract
was soft — prompt-only; nothing checked the generated SQL actually obeyed, so
a re-spelled literal ("Mytheresea", "MYTHERESA ") silently filtered zero rows.

This module enforces it deterministically at the post-generation chokepoint:
for every binding, if the SQL filters the bound column with a literal that is
a NEAR-MISS of the bound value (the same entity, re-spelled), rewrite it to
the verified value — sqlglot AST surgery via the same ``repair_filter_literals``
machinery the live-domain guard uses. A literal that names a genuinely
DIFFERENT value (a deliberate comparison entity) is never touched: the
similarity gate protects it. Fail-open everywhere; an optional ``dry_run``
callable vetoes any rewrite that no longer binds.

Scope note: true named-parameter execution would touch every connector
adapter for no additional safety — the contract is "the verified value
reaches the SQL", and that is enforceable right here. (Wire study
2026-07-15, R7 follow-on.)
"""
from __future__ import annotations

import difflib
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# A drifted literal must be THIS similar to the bound value to count as a
# re-spelling of the same entity. Below it, the literal is presumed to name a
# different value on purpose (e.g. a comparison entity) and is left alone.
_SAME_ENTITY_CUTOFF = 0.75


def _bare(name: str) -> str:
    return (name or "").split(".")[-1].lower()


def enforce_grounded_literals(
    sql: str,
    bindings: list,
    dialect: str = "duckdb",
    dry_run: Optional[Callable[[str], tuple[bool, str]]] = None,
) -> tuple[str, list[dict]]:
    """Rewrite near-miss literals on resolution-bound columns to the bound value.

    ``bindings`` are duck-typed EntityBinding-likes (``table``/``column``/``value``).
    Returns ``(sql, repairs)`` — the original SQL and ``[]`` whenever nothing
    qualifies, the shape can't be read, or the dry-run vetoes the rewrite."""
    try:
        if not sql or not bindings:
            return sql, []
        from aughor.sql.join_guard import (
            FilterDomainWarning,
            extract_filter_literals,
            repair_filter_literals,
        )

        by_col: dict[tuple[str, str], list] = {}
        for b in bindings:
            col = getattr(b, "column", "") or ""
            if col and (getattr(b, "value", "") or ""):
                by_col.setdefault((_bare(getattr(b, "table", "")), col.lower()), []).append(b)

        warnings: list = []
        repairs: list[dict] = []
        for t, c, lit, op in extract_filter_literals(sql):
            if op not in ("=", "IN"):
                continue  # never weaken a negation
            cands = by_col.get((_bare(t), c.lower())) or by_col.get(("", c.lower()))
            if cands is None:
                # A binding whose table dropped out of the final SQL (a join alias
                # path) still owns its column name if exactly one binding uses it.
                same_col = [b for (bt, bc), bs in by_col.items() if bc == c.lower() for b in bs]
                cands = same_col if len(same_col) == 1 else None
            if not cands:
                continue
            for b in cands:
                value = b.value
                if lit == value:
                    break  # verbatim — the contract held
                ratio = difflib.SequenceMatcher(None, lit.lower(), value.lower()).ratio()
                if ratio >= _SAME_ENTITY_CUTOFF:
                    # repair_filter_literals resolves BARE table names (sqlglot
                    # Table.name), while the extractor may emit qualified ones —
                    # key the warning bare so the rewrite actually lands.
                    warnings.append(FilterDomainWarning(_bare(t), c, lit, [value], value, op))
                    repairs.append({"column": f"{_bare(t)}.{c}", "from": lit, "to": value,
                                    "similarity": round(ratio, 3)})
                    break

        if not warnings:
            return sql, []
        fixed = repair_filter_literals(sql, warnings, dialect)
        if not fixed or fixed.strip() == sql.strip():
            return sql, []
        if dry_run is not None:
            try:
                ok, _msg = dry_run(fixed)
            except Exception:
                ok = False
            if not ok:
                return sql, []  # never trade a runnable query for a broken repair
        return fixed, repairs
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "grounded-literal enforcement is fail-open",
                 counter="grounded_literals")
        return sql, []
