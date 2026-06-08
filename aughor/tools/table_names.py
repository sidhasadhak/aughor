"""Canonical table-name handling — the ONE place table names are split, compared,
and qualified.

Table names flow through the platform in more than one convention depending on the
connection and the builder that produced them:

    bare           "orders"
    schema.table   "analytics.orders"
    catalog.schema.table   "memory.bakehouse.reviews"

Different builders (build_schema_context, build_rich_schema, build_mermaid_er, the
ontology builder, the catalog tree) emit different conventions, so any code that
compares a name from one source against a name from another MUST go through
``same_table`` / ``bare`` here rather than ``==`` or its own ``.split(".")``. This
mismatch is exactly the bug that was independently re-fixed three times (ontology
relationship lifting, Workspace search_path, Catalog ERD filter) before this module
existed — centralising it is what stops it recurring.

Two leaf accessors on purpose:
    leaf(name)  → last segment, CASE PRESERVED  — use when constructing SQL / display.
    bare(name)  → leaf lowercased + unquoted     — use for comparison and dict keys.
"""
from __future__ import annotations

from dataclasses import dataclass


def leaf(name: str) -> str:
    """Last dotted segment with case and content preserved (quotes stripped).
    Use when the result becomes a SQL identifier or user-facing label —
    NOT lowercased, so it is safe on case-sensitive engines.
    'analytics.Orders' -> 'Orders'."""
    return (name or "").split(".")[-1].strip().strip('"')


def bare(name: str) -> str:
    """Comparison key: last segment, lowercased and unquoted.
    'Analytics.Orders' -> 'orders'. Use for matching / dict keys, never for SQL."""
    return leaf(name).lower()


def schema_of(name: str) -> str | None:
    """Schema segment (the part immediately left of the table) if the name is
    qualified, else None. Handles 2- and 3-part names:
    'analytics.orders' -> 'analytics'; 'memory.bakehouse.t' -> 'bakehouse';
    'orders' -> None."""
    parts = [p.strip().strip('"') for p in (name or "").split(".") if p.strip()]
    return parts[-2].lower() if len(parts) >= 2 else None


def split_ref(name: str) -> tuple[str | None, str]:
    """(schema_or_None, leaf) — schema lowercased, leaf case-preserved."""
    return schema_of(name), leaf(name)


def qualify(name: str, schema: str | None) -> str:
    """Schema-qualify a bare name. Passes through unchanged if it is already
    qualified (contains a dot) or no schema is given."""
    if not schema or "." in (name or ""):
        return name
    return f"{schema}.{name}"


def same_table(a: str, b: str, *, schema_strict: bool = False) -> bool:
    """True when two refs name the same table, tolerant of qualified-vs-bare.

    Default: compare the bare (leaf) segment only — the common case where one
    source is qualified and the other isn't. With ``schema_strict=True`` also
    require the schema segment to match *when both carry one* (a bare ref still
    matches a qualified one — absence of a schema is treated as "any")."""
    if bare(a) != bare(b):
        return False
    if schema_strict:
        sa, sb = schema_of(a), schema_of(b)
        if sa and sb and sa != sb:
            return False
    return True


def resolve(name: str, candidates, key=lambda x: x, *, schema_strict: bool = False):
    """Find the candidate whose ``key()`` names the same table as ``name``.

    Prefers an exact string match, then falls back to schema-tolerant matching.
    Returns the candidate (not the key) or None. Replaces the
    ``d.get(t) or d.get(t.split('.')[-1])`` band-aid pattern."""
    for c in candidates:
        if key(c) == name:
            return c
    for c in candidates:
        if same_table(key(c), name, schema_strict=schema_strict):
            return c
    return None


def resolve_in(mapping: dict, name: str, *, schema_strict: bool = False):
    """Dict lookup tolerant of qualified-vs-bare keys: exact first, then by
    same_table over the keys. Returns the value or None."""
    if name in mapping:
        return mapping[name]
    for k, v in mapping.items():
        if same_table(k, name, schema_strict=schema_strict):
            return v
    return None


@dataclass(frozen=True)
class TableRef:
    """Structured table reference. ``schema`` is None for bare names."""
    schema: str | None
    name: str  # leaf, case-preserved

    @classmethod
    def parse(cls, raw: str) -> "TableRef":
        s, n = split_ref(raw)
        return cls(s, n)

    @property
    def bare(self) -> str:
        return self.name.lower()

    def qualified(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    def __str__(self) -> str:
        return self.qualified()
