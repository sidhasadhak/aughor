"""Deterministic column-identifier repair.

DuckDB (and most engines) treat identifiers as case-INSENSITIVE but separator-
SENSITIVE: ``customerID`` and ``CUSTOMERID`` are the same column, but ``customer_id``
is a *different* (here, nonexistent) one. An LLM with a snake_case prior reliably
rewrites a camelCase schema's ``customerID`` to ``customer_id`` — producing a
"Table X does not have a column named Y" Binder error on every such query (the #1
Phase-8 failure class on camelCase datasets like Bakehouse).

This rewrites such identifiers back to the exact schema name BEFORE execution, so the
query never errors and never burns a repair round-trip. It is conservative: it only
touches a column whose separator/case-normalised form has a UNIQUE match among the
query's real columns. A genuinely invented column (no match) is left untouched — that
is a different failure class (hallucination), not a casing slip. Fail-safe: any parse
problem returns the original SQL unchanged.
"""
from __future__ import annotations


def _norm(name: str) -> str:
    """Separator/case-insensitive key: 'customer_id' and 'customerID' → 'customerid'."""
    return (name or "").replace("_", "").replace("-", "").replace(" ", "").lower()


def repair_identifiers(sql: str, table_cols: dict[str, list[str]], dialect: str = "duckdb") -> str:
    """Remap mis-cased / mis-separated column identifiers in `sql` to the exact schema
    column name. `table_cols` maps (possibly schema-qualified) table → its columns.
    Returns the original SQL when nothing is repaired or on any parse failure."""
    if not sql or not table_cols:
        return sql
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql
    if tree is None:
        return sql

    # The base tables this query touches (bare names + CTE names to exclude).
    ctes = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    used_bare = {
        (t.name or "").lower()
        for t in tree.find_all(exp.Table)
        if (t.name or "").lower() not in ctes
    }

    # Build the norm→real column map across ONLY the query's tables. A norm that resolves
    # to two different real names is ambiguous → never guessed.
    norm_to_real: dict[str, str] = {}
    ambiguous: set[str] = set()
    real_exact: set[str] = set()
    for tname, cols in table_cols.items():
        if (tname.split(".")[-1].lower() not in used_bare) and (tname.lower() not in used_bare):
            continue
        for c in cols or []:
            real_exact.add(c)
            n = _norm(c)
            if n in norm_to_real and norm_to_real[n] != c:
                ambiguous.add(n)
            else:
                norm_to_real[n] = c

    if not norm_to_real:
        return sql

    changed = False
    for col in tree.find_all(exp.Column):
        name = col.name
        if not name or name in real_exact:        # already an exact, valid column
            continue
        n = _norm(name)
        if n in ambiguous:
            continue
        real = norm_to_real.get(n)
        if real and real != name:
            col.set("this", exp.to_identifier(real))
            changed = True

    return tree.sql(dialect=dialect) if changed else sql
