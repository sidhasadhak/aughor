"""Deterministic capability gate (Rec 6): flag a SQL's use of constructs the target dialect can't run.

Walks the parsed AST (the ``readonly.py`` function-walk pattern) and compares the functions/features it uses
against ``db/capabilities.for_dialect``. Returns one plain-language diagnostic per unsupported construct — used
to enrich the SQL-repair prompt so a failing native-dialect query self-corrects with a precise hint instead of
another blind dry-run. Fail-open: an unparseable SQL or any error yields ``[]`` (never raises, never blocks).
"""
from __future__ import annotations

from aughor.db.capabilities import FEATURE_ILIKE, FEATURE_QUALIFY, for_dialect

# Concise "use this instead" hints for the flagged cross-dialect functions.
_ALT: dict[str, str] = {
    "SAFE_DIVIDE": "guard division with NULLIF(denominator, 0) (SAFE_DIVIDE is BigQuery-only)",
    "DIV0": "guard division with NULLIF(denominator, 0) (DIV0 is Snowflake-only)",
    "IFF": "use CASE WHEN ... THEN ... ELSE ... END (IFF is Snowflake-only)",
    "DATE_TRUNC": "MySQL has no DATE_TRUNC — bucket with DATE_FORMAT(ts, '%Y-%m-01') etc.",
    "DATE_DIFF": "use DATEDIFF(d1, d2) (this engine has no DATE_DIFF)",
    "DATEDIFF": "use DATE_DIFF(d1, d2, DAY) with an unquoted unit (BigQuery has no DATEDIFF)",
}


def _function_names(tree) -> set[str]:
    """Every function-ish name used in the tree, UPPERCASED (built-ins + engine-unknown anonymous calls)."""
    import sqlglot.expressions as exp
    names: set[str] = set()
    for node in tree.find_all(exp.Func):
        try:
            n = node.sql_name()
        except Exception:  # noqa: BLE001 — some nodes have no sql_name; fall back to the node key
            n = getattr(node, "key", "") or ""
        if n:
            names.add(n.upper())
    for node in tree.find_all(exp.Anonymous):
        if node.name:
            names.add(node.name.upper())
    return names


def capability_diagnostics(sql: str, dialect: str) -> list[str]:
    """Plain-language diagnostics for constructs unsupported on ``dialect`` (empty when all are supported or
    the SQL can't be parsed). Deterministic, fail-open, no LLM."""
    caps = for_dialect(dialect)
    if not caps.unsupported_functions and not caps.unsupported_features:
        return []
    try:
        import sqlglot
        import sqlglot.expressions as exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001 — a parse failure is not our concern; the dry-run reports it
        return []
    if tree is None:
        return []

    diags: list[str] = []
    for bad in sorted(_function_names(tree) & caps.unsupported_functions):
        alt = _ALT.get(bad)
        diags.append(f"{bad}(...) is not supported on {dialect}" + (f" — {alt}." if alt else "."))
    if FEATURE_QUALIFY in caps.unsupported_features and tree.find(exp.Qualify):
        diags.append(f"QUALIFY is not supported on {dialect} — filter window functions in an outer query "
                     "over a subquery instead.")
    if FEATURE_ILIKE in caps.unsupported_features and tree.find(exp.ILike):
        diags.append(f"ILIKE is not supported on {dialect} — use LOWER(col) LIKE LOWER('%…%').")
    return diags
