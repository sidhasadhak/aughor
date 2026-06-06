"""
Column ambiguity pre-flight check.

Scans a generated SQL query for unqualified column references that exist
in two or more tables in the schema context.  Run *before* execution so
the error classifier can inject these warnings into the FIX_SQL prompt
if the query later fails with "column reference is ambiguous".

Returns an empty list when no ambiguities are found — zero overhead on
single-table queries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# SQL keywords to ignore when scanning for column tokens
_SQL_KEYWORDS = frozenset({
    "select", "from", "where", "join", "on", "group", "by", "order", "having",
    "limit", "offset", "as", "and", "or", "not", "in", "is", "null", "true",
    "false", "case", "when", "then", "else", "end", "inner", "left", "right",
    "outer", "cross", "with", "distinct", "all", "union", "except", "intersect",
    "asc", "desc", "between", "like", "ilike", "cast", "extract", "epoch",
    "interval", "date", "time", "count", "sum", "avg", "min", "max", "coalesce",
    "nullif", "over", "partition", "rows", "range", "preceding", "following",
    "current", "row", "unbounded", "year", "month", "day", "hour", "minute",
    "second", "using", "natural", "full", "exists", "any", "some", "all",
    "values", "set", "into", "returning",
})


@dataclass
class AmbiguityWarning:
    column: str
    found_in: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        tables = " and ".join(self.found_in)
        return (
            f"Column '{self.column}' exists in {tables} — qualify it to avoid "
            f"an ambiguous-column error: {self.found_in[0]}.{self.column}."
        )


@dataclass
class JoinWarning:
    from_table: str
    to_table: str
    reason: str

    def to_prompt_text(self) -> str:
        return (
            f"WARNING: {self.reason} — do NOT JOIN '{self.from_table}' and "
            f"'{self.to_table}' without a valid shared key column."
        )


_FROM_JOIN_TABLE = re.compile(r'\b(?:FROM|JOIN)\s+(\w+)', re.IGNORECASE)


def detect_invalid_joins(sql: str, schema_context: str) -> list[JoinWarning]:
    """
    Scan *sql* for table pairs that appear in the same query but have no
    detected join path in the schema.

    Uses the `no_join` list from _compute_join_map — if both tables from a
    known-unconnected pair appear in the SQL, that is almost certainly a
    hallucinated join.  Returns an empty list for single-table queries or
    when all pairs are joinable.
    """
    sql_tables = {m.group(1).lower() for m in _FROM_JOIN_TABLE.finditer(sql)}
    if len(sql_tables) < 2:
        return []

    from aughor.tools.schema import _parse_schema_tables, _compute_join_map
    table_cols = _parse_schema_tables(schema_context)
    jmap = _compute_join_map(table_cols)

    warnings: list[JoinWarning] = []
    for t1, t2 in jmap.get("no_join", []):
        if t1.lower() in sql_tables and t2.lower() in sql_tables:
            warnings.append(JoinWarning(
                from_table=t1,
                to_table=t2,
                reason=f"No shared key detected between '{t1}' and '{t2}'",
            ))
    return warnings


def detect_ambiguous_columns(sql: str, schema_context: str) -> list[AmbiguityWarning]:
    """
    Parse *schema_context* for table→column mappings, then scan *sql* for
    unqualified column references that appear in 2+ tables.
    """
    col_to_tables = _build_col_map(schema_context)
    ambiguous = {c: tbls for c, tbls in col_to_tables.items() if len(tbls) > 1}
    if not ambiguous:
        return []

    # Find all identifier tokens NOT preceded by a dot (not already qualified)
    # and NOT followed by ( (not a function call)
    warnings: list[AmbiguityWarning] = []
    seen: set[str] = set()

    for m in re.finditer(
        r"(?<!\.)(?<!\w)\b([a-zA-Z_][a-zA-Z0-9_]*)\b(?!\s*\()", sql
    ):
        token = m.group(1).lower()
        if token in _SQL_KEYWORDS or token in seen:
            continue
        if token in ambiguous:
            # Verify it's genuinely unqualified in context (no preceding dot)
            start = m.start()
            preceding = sql[max(0, start - 2) : start]
            if "." not in preceding:
                warnings.append(
                    AmbiguityWarning(column=token, found_in=ambiguous[token])
                )
                seen.add(token)

    return warnings


def _build_col_map(schema_context: str) -> dict[str, list[str]]:
    """Parse schema_context lines → {column_name_lower: [table1, table2, ...]}."""
    col_to_tables: dict[str, list[str]] = {}
    current_table: str | None = None

    for line in schema_context.splitlines():
        table_m = re.match(r"^TABLE:\s+([\w.]+)", line)
        if table_m:
            current_table = table_m.group(1)
            continue
        if current_table and line.startswith("  "):
            # Column lines look like "  col_name  TYPE" — skip comment lines
            col_m = re.match(r"^\s{2}(\w+)\s+\S", line)
            if col_m and not line.strip().startswith("--"):
                col = col_m.group(1).lower()
                col_to_tables.setdefault(col, [])
                if current_table not in col_to_tables[col]:
                    col_to_tables[col].append(current_table)

    return col_to_tables
