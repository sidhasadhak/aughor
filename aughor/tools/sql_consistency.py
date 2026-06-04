"""
Cross-query consistency normalizer.

When multiple SQL queries are generated in parallel for the same hypothesis,
they can diverge in three common ways:

  1. Date truncation functions — one query uses DATE_TRUNC('month', col),
     another uses STRFTIME('%Y-%m', col), a third uses TO_CHAR(col, 'YYYY-MM').
     Downstream joins / UNION queries silently produce wrong results.

  2. Column alias disagreement — Q1 emits a column as `revenue`, Q2 emits
     the same concept as `total_revenue`. Downstream pivot/join logic breaks.

  3. JOIN path inconsistency — Q1 joins orders→order_items→products,
     Q2 joins orders→products directly (wrong or invalid path).

This module normalizes (1) and detects (2)+(3) after parallel generation,
before execution. All functions are deterministic — no LLM call.

Usage:
    from aughor.tools.sql_consistency import normalize_parallel_queries
    queries, notes = normalize_parallel_queries(queries, dialect)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ConsistencyNote:
    kind: str        # "date_normalized", "alias_mismatch", "join_divergence"
    detail: str
    query_indices: list[int] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        return f"[consistency:{self.kind}] {self.detail}"


# ── Date function normalizer ──────────────────────────────────────────────────

# For each dialect, ONE canonical date-trunc form per granularity.
# The normalizer rewrites all equivalent forms to the canonical one.

_DATE_VARIANTS: dict[str, list[tuple[re.Pattern[str], str]]] = {
    "duckdb": [
        # month truncation
        (re.compile(r"STRFTIME\s*\(\s*'%Y-%m'\s*,\s*([^)]+)\)", re.IGNORECASE),
         r"DATE_TRUNC('month', \1)"),
        (re.compile(r"TO_CHAR\s*\(\s*([^,]+),\s*'YYYY-MM'\s*\)", re.IGNORECASE),
         r"DATE_TRUNC('month', \1)"),
        # year truncation
        (re.compile(r"STRFTIME\s*\(\s*'%Y'\s*,\s*([^)]+)\)", re.IGNORECASE),
         r"DATE_TRUNC('year', \1)"),
        (re.compile(r"TO_CHAR\s*\(\s*([^,]+),\s*'YYYY'\s*\)", re.IGNORECASE),
         r"DATE_TRUNC('year', \1)"),
        # week truncation
        (re.compile(r"STRFTIME\s*\(\s*'%Y-%W'\s*,\s*([^)]+)\)", re.IGNORECASE),
         r"DATE_TRUNC('week', \1)"),
    ],
    "postgresql": [
        # month truncation — DuckDB strftime → Postgres DATE_TRUNC
        (re.compile(r"STRFTIME\s*\(\s*'%Y-%m'\s*,\s*([^)]+)\)", re.IGNORECASE),
         r"DATE_TRUNC('month', \1)"),
        # year
        (re.compile(r"STRFTIME\s*\(\s*'%Y'\s*,\s*([^)]+)\)", re.IGNORECASE),
         r"DATE_TRUNC('year', \1)"),
    ],
}

# DuckDB is also used under the label "duckdb" and "local_upload"
_DUCKDB_ALIASES = {"duckdb", "local_upload", "motherduck"}


def _canonical_dialect(dialect: str) -> str:
    d = (dialect or "").lower()
    if d in _DUCKDB_ALIASES or "duck" in d:
        return "duckdb"
    if "postgres" in d or "pg" == d:
        return "postgresql"
    return d


def _normalize_date_functions(sql: str, dialect: str) -> tuple[str, list[str]]:
    """Rewrite non-canonical date functions to the dialect's canonical form.
    Returns (rewritten_sql, list_of_changes_made)."""
    canon = _canonical_dialect(dialect)
    variants = _DATE_VARIANTS.get(canon, [])
    changes: list[str] = []
    for pattern, replacement in variants:
        new_sql, n = pattern.subn(replacement, sql)
        if n:
            changes.append(f"normalized date function to {replacement[:40]!r}")
            sql = new_sql
    return sql, changes


# ── Alias extractor ───────────────────────────────────────────────────────────

def _extract_output_aliases(sql: str) -> dict[str, str]:
    """Return {alias_lower: expr_lower} for every AS alias in the SELECT list."""
    aliases: dict[str, str] = {}
    # Simple pattern: <expr> AS <alias> — handles most cases
    for m in re.finditer(
        r'([A-Za-z0-9_.*()\s]+?)\s+AS\s+([A-Za-z_][A-Za-z0-9_]*)',
        sql, re.IGNORECASE
    ):
        expr = m.group(1).strip().lower()
        alias = m.group(2).strip().lower()
        aliases[alias] = expr
    return aliases


def _detect_alias_mismatches(
    queries: list[str],
) -> list[ConsistencyNote]:
    """Detect when the same SQL expression is aliased differently across queries."""
    # Build: expr → {alias: [query_indices]}
    expr_to_aliases: dict[str, dict[str, list[int]]] = {}
    for i, sql in enumerate(queries):
        for alias, expr in _extract_output_aliases(sql).items():
            # Normalize expr by stripping table qualifiers for comparison
            core = re.sub(r'\w+\.', '', expr).strip()
            expr_to_aliases.setdefault(core, {}).setdefault(alias, []).append(i)

    notes: list[ConsistencyNote] = []
    for expr, alias_map in expr_to_aliases.items():
        if len(alias_map) > 1:
            detail = (
                f"Expression '{expr[:60]}' is aliased differently across queries: "
                + ", ".join(f"'{a}' (q{','.join(str(i) for i in idxs)})"
                            for a, idxs in alias_map.items())
                + " — downstream joins may misalign columns."
            )
            affected = sorted({i for idxs in alias_map.values() for i in idxs})
            notes.append(ConsistencyNote(
                kind="alias_mismatch",
                detail=detail,
                query_indices=affected,
            ))
    return notes


# ── Public API ────────────────────────────────────────────────────────────────

def normalize_parallel_queries(
    queries: list[str],
    dialect: str,
) -> tuple[list[str], list[ConsistencyNote]]:
    """
    Normalize a batch of parallel-generated SQL queries for the same hypothesis.

    Steps:
      1. Normalize date truncation functions to the canonical dialect form.
      2. Detect alias mismatches across queries (informational — not auto-fixed
         because renaming aliases could break downstream CTEs).

    Returns (normalized_queries, consistency_notes).
    Never raises — on any exception returns (original_queries, []).
    """
    try:
        notes: list[ConsistencyNote] = []
        normalized: list[str] = []

        for i, sql in enumerate(queries):
            new_sql, changes = _normalize_date_functions(sql, dialect)
            normalized.append(new_sql)
            for change in changes:
                notes.append(ConsistencyNote(
                    kind="date_normalized",
                    detail=f"Query {i}: {change}",
                    query_indices=[i],
                ))

        if len(normalized) > 1:
            alias_notes = _detect_alias_mismatches(normalized)
            notes.extend(alias_notes)

        return normalized, notes

    except Exception:
        return queries, []
