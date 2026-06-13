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


def _table_key(t) -> tuple[str, str]:
    """A (qualified, bare) lowercased key for a sqlglot Table node."""
    parts = [p for p in (getattr(t, "catalog", ""), getattr(t, "db", ""), t.name) if p]
    return ".".join(parts).lower(), (t.name or "").lower()


def unresolved_identifiers(
    sql: str, table_cols: dict[str, list[str]], dialect: str = "duckdb"
) -> tuple[set[str], set[str]]:
    """Static schema-grounding check — the deterministic pre-execution gate.

    Returns ``(unknown_columns, unknown_tables)``: identifiers in `sql` that cannot be
    resolved against the real schema in `table_cols` AFTER casing/separator normalisation.
    This runs AFTER :func:`repair_identifiers`, so a mere casing slip (``customer_id`` vs
    ``customerID``) is already fixed and never reported here — what remains is a genuine
    invention (``segment``, ``region``) or a missing/cross-dataset table (``reviews``),
    the residual Phase-8 Binder-error classes that a blind execute+retry only discovers by
    failing first (logging an Activity-Tab error). Catching them statically lets the caller
    skip the question before it ever runs.

    ``unknown_tables``  base (non-CTE) tables whose name matches no key in `table_cols`
                        (by qualified or bare name).
    ``unknown_columns`` column refs matching no real column of any in-scope table AND not a
                        query-defined alias/CTE/derived name. Computed ONLY when every base
                        table is known and the query has no table-valued/UNNEST/VALUES/LATERAL
                        source (whose columns aren't in `table_cols`) — so an incomplete view
                        of the schema can never yield a false "unknown".

    Conservative and fail-safe by construction: a false *miss* (a real bad column slips
    through to the existing retry loop) is cheap; a false *positive* (skipping a valid
    question) is not — so every uncertainty resolves toward "resolved". Any parse failure
    returns ``(set(), set())``."""
    if not sql or not table_cols:
        return set(), set()
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return set(), set()
    if tree is None:
        return set(), set()

    # Known-table index: match a query table by exact-qualified OR bare name.
    by_qualified: dict[str, list[str]] = {}
    by_bare: dict[str, list[list[str]]] = {}
    for tname, cols in table_cols.items():
        by_qualified[tname.lower()] = cols or []
        by_bare.setdefault(tname.split(".")[-1].lower(), []).append(cols or [])

    ctes = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    unknown_tables: set[str] = set()
    in_scope_cols: set[str] = set()   # real columns of the query's known base tables (normed)
    all_tables_known = True
    for t in tree.find_all(exp.Table):
        bare = (t.name or "").lower()
        if not bare or bare in ctes:
            continue
        qual, _ = _table_key(t)
        if qual in by_qualified:
            cols = by_qualified[qual]
        elif bare in by_bare:
            cols = [c for group in by_bare[bare] for c in group]   # union across same-named tables
        else:
            unknown_tables.add(t.name)
            all_tables_known = False
            continue
        in_scope_cols.update(_norm(c) for c in cols)

    # Column check only when we have a complete, ordinary view of the FROM clause —
    # an unknown table or an exotic source means columns can legitimately come from
    # outside `table_cols`, so we must not flag them.
    exotic = any(tree.find_all(exp.Unnest)) or any(tree.find_all(exp.Values)) \
        or any(tree.find_all(exp.Lateral))
    if unknown_tables or exotic or not in_scope_cols:
        return set(), unknown_tables

    # Names the query itself defines (aliases, CTE names, derived-column aliases) — these
    # shadow base columns and must never be reported as unknown.
    defined: set[str] = set(ctes)
    for a in tree.find_all(exp.Alias):
        nm = a.alias
        if nm:
            defined.add(_norm(nm))
    for ta in tree.find_all(exp.TableAlias):
        if ta.name:
            defined.add(_norm(ta.name))
        for c in ta.columns:
            if getattr(c, "name", ""):
                defined.add(_norm(c.name))

    unknown_columns: set[str] = set()
    for col in tree.find_all(exp.Column):
        name = col.name
        if not name or "*" in name:
            continue
        n = _norm(name)
        if n in in_scope_cols or n in defined:
            continue
        unknown_columns.add(name)

    return unknown_columns, unknown_tables
