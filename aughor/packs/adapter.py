"""Build the resolver's SchemaFacts from a warehouse's table/column layout (P1b).

The resolver (resolver.py) reasons over a connection-agnostic ``SchemaFacts``. This adapter
derives those facts from a ``table_cols`` map (``{table: [columns]}``) — the same structure the
SQL layer already extracts from a live connection — using the shared FK-root heuristic so
identity columns and FK edges are detected the same way the join/fan-out guards detect them.

Kept PURE over ``table_cols`` so it's unit-testable today; a thin live wrapper
(``table_cols`` from introspection → here) is the only connection-dependent glue and is what
gets exercised in live testing.
"""
from __future__ import annotations

import re
from typing import Optional

from aughor.tools.schema import fk_root
from aughor.packs.resolver import SchemaFacts, TableFact, ColumnFact

_DATE_KW = ("date", "day", "week", "month", "year", "time", "_at", "_on", "_ts", "_dt",
            "timestamp", "created", "updated", "delivered", "approved", "signup", "joined")


def _base(table: str) -> str:
    """Bare entity name for owner matching — mirrors the SQL layer's table-base rule so a
    column's fk_root lines up with its owning table (dim_customers ↔ customer_id → 'customer')."""
    b = table.split(".")[-1].lower()
    b = re.sub(r"^(dim|fact|tbl|stg)_", "", b)
    b = re.sub(r"_(dim|fact|tbl)$", "", b)
    return b.rstrip("s")


def _is_date(col: str) -> bool:
    return any(k in col.lower() for k in _DATE_KW)


def schema_facts_from_table_cols(
    table_cols: dict[str, list[str]],
    business_model: str = "",
    row_counts: Optional[dict[str, int]] = None,
) -> SchemaFacts:
    """Derive SchemaFacts: a column is an IDENTITY if its FK-root matches its own table's base
    (the table's own key); an FK EDGE when its root matches another table's base. Date columns
    are name-detected. Pure; never raises."""
    row_counts = row_counts or {}
    bases = {t: _base(t) for t in table_cols}
    base_to_table: dict[str, str] = {}
    for t, b in bases.items():
        base_to_table.setdefault(b, t)   # first table owning a base wins as the FK target

    tables: list[TableFact] = []
    for t, cols in table_cols.items():
        b = bases[t]
        col_facts: list[ColumnFact] = []
        refs: dict[str, str] = {}
        for c in (cols or []):
            root = fk_root(c)
            is_id = root is not None and root == b
            col_facts.append(ColumnFact(name=c, is_date=_is_date(c), is_identity=is_id))
            if root is not None and root != b and root in base_to_table:
                refs[c] = base_to_table[root]
        tables.append(TableFact(name=t, columns=col_facts, references=refs,
                                row_count=int(row_counts.get(t, 0))))
    return SchemaFacts(tables=tables, business_model=business_model)
