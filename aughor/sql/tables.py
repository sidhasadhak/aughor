"""CTE-safe table extraction from arbitrary SQL.

The naive `find_all(exp.Table)` treats a CTE name as a real table, so

    WITH foo AS (SELECT * FROM secret_table) SELECT * FROM foo

would report `foo` (harmless) and *miss* `secret_table` — exactly backwards for
any scope/authorization decision. This walks sqlglot scopes and excludes CTE
names, surfacing only the real physical tables a query reads.

Adapted from Apache Superset (Apache-2.0) — superset/sql/parse.py
(extract_tables_from_statement / is_cte).

Reusable primitive for the cross-schema/scope guard (see the cross-schema leak
work) and any future per-tenant authorization — it does not change execution by
itself.
"""
from __future__ import annotations

from typing import NamedTuple

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, ScopeType, traverse_scope


class TableRef(NamedTuple):
    table: str
    schema: str | None
    catalog: str | None

    def qualified(self) -> str:
        return ".".join(p for p in (self.catalog, self.schema, self.table) if p)


def _is_cte(source: exp.Table, scope: Scope) -> bool:
    """A table-looking source that actually resolves to a CTE in the parent scope."""
    parent_sources = scope.parent.sources if scope.parent else {}
    ctes_in_scope = {
        name
        for name, parent_scope in parent_sources.items()
        if isinstance(parent_scope, Scope) and parent_scope.scope_type == ScopeType.CTE
    }
    return source.name in ctes_in_scope


def _extract(parsed: exp.Expression) -> set[TableRef]:
    sources: list[exp.Table] | set[exp.Table]
    if isinstance(parsed, exp.Describe):
        # DESCRIBE has no scope sources — query the tables directly.
        sources = list(parsed.find_all(exp.Table))
    elif isinstance(parsed, exp.Command):
        # e.g. `SHOW COLUMNS FROM foo` — reparse the literal as a pseudo-SELECT.
        literal = parsed.find(exp.Literal)
        if literal is None:
            return set()
        try:
            pseudo = sqlglot.parse_one(f"SELECT {literal.this}")
        except Exception:
            return set()
        sources = list(pseudo.find_all(exp.Table))
    else:
        sources = [
            source
            for scope in traverse_scope(parsed)
            for source in scope.sources.values()
            if isinstance(source, exp.Table) and not _is_cte(source, scope)
        ]
    return {
        TableRef(
            s.name,
            s.db if s.db else None,
            s.catalog if s.catalog else None,
        )
        for s in sources
    }


def extract_tables(sql: str, dialect: str | None = None) -> set[TableRef]:
    """Return the set of real physical tables a query reads (CTE names excluded).

    Empty set on a parse failure (caller decides how to treat un-enumerable SQL).
    """
    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
    except Exception:
        return set()
    if parsed is None:
        return set()
    try:
        return _extract(parsed)
    except Exception:
        return set()
