"""Per-dialect capability contract (Rec 6, Hasura-NDC-inspired).

A machine-checkable descriptor of the SQL constructs that HARD-ERROR on each native dialect — the deterministic
twin of the prose writer-rules in ``db/dialects.py``. The value concentrates on the four native-SQL dialects
(bigquery/snowflake/mysql/exasol), where the LLM's SQL runs verbatim: a construct one dialect supports and
another rejects (``QUALIFY``, ``ILIKE``, ``DATE_TRUNC``, ``SAFE_DIVIDE``, ``DIV0`` …) is a footgun the model
only discovers via a failed dry-run today. Transpile-from-DuckDB dialects (duckdb/postgres/sqlite/motherduck)
run the LLM's DuckDB SQL through sqlglot's translator, so they are PERMISSIVE here — checking their (DuckDB-form)
SQL against the target's real capabilities would be a false positive.

Conservative by design: only constructs known to error are listed, so a diagnostic is high-confidence. This is
NOT an exhaustive function map (that would be a maintenance trap) — it is a small, high-signal footgun set.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Feature keys recognised by ``sql/capability_check.py`` (AST-detectable): a window-filter QUALIFY clause and
# a case-insensitive ILIKE. (The ``::`` cast syntax is intentionally omitted — after parsing it is
# indistinguishable from CAST(...), so it can't be flagged without false positives.)
FEATURE_QUALIFY = "qualify"
FEATURE_ILIKE = "ilike"


@dataclass(frozen=True)
class DialectCapabilities:
    """What a dialect CANNOT run. Empty sets ⇒ permissive (no capability diagnostics)."""
    dialect: str
    # UPPERCASE function names that error on this dialect (used on the wrong engine).
    unsupported_functions: frozenset[str] = field(default_factory=frozenset)
    # Feature keys (FEATURE_*) whose syntax errors on this dialect.
    unsupported_features: frozenset[str] = field(default_factory=frozenset)


# Only HIGH-CONFIDENCE footguns, cross-checked against db/dialects.py:
#   - QUALIFY: supported on snowflake/bigquery/duckdb; ERRORS on postgres/mysql.
#   - ILIKE:   supported on postgres/snowflake/duckdb; ERRORS on bigquery/mysql.
#   - SAFE_DIVIDE: bigquery-only.   DIV0/IFF: snowflake-only.   DATE_TRUNC: absent on mysql.
_CAPS: dict[str, DialectCapabilities] = {
    "bigquery": DialectCapabilities(
        "bigquery",
        unsupported_functions=frozenset({"DIV0", "IFF", "DATEDIFF"}),
        unsupported_features=frozenset({FEATURE_ILIKE}),
    ),
    "snowflake": DialectCapabilities(
        "snowflake",
        unsupported_functions=frozenset({"SAFE_DIVIDE"}),
    ),
    "mysql": DialectCapabilities(
        "mysql",
        unsupported_functions=frozenset({"DATE_TRUNC", "DATE_DIFF", "SAFE_DIVIDE", "DIV0", "IFF"}),
        unsupported_features=frozenset({FEATURE_QUALIFY, FEATURE_ILIKE}),
    ),
    "postgres": DialectCapabilities(
        "postgres",
        unsupported_functions=frozenset({"SAFE_DIVIDE", "DIV0", "IFF"}),
        unsupported_features=frozenset({FEATURE_QUALIFY}),
    ),
}

_PERMISSIVE = DialectCapabilities("")   # duckdb / sqlite / motherduck / exasol / unknown → no diagnostics


def for_dialect(dialect: str) -> DialectCapabilities:
    """The capability descriptor for a dialect (permissive for transpile-from-DuckDB / unknown engines)."""
    caps = _CAPS.get((dialect or "").lower(), _PERMISSIVE)
    # Keep the requested dialect name for messages even when permissive.
    return caps if caps is not _PERMISSIVE else DialectCapabilities(dialect or "")


# Human names for the AST-detected features, for the writer-prompt avoid-line.
_FEATURE_LABEL = {FEATURE_QUALIFY: "QUALIFY", FEATURE_ILIKE: "ILIKE"}


def avoid_line(dialect: str) -> str:
    """One deterministic "don't use these" directive for the SQL-writer prompt, derived from the capability
    contract — the machine-checked complement to the prose dos in ``db/dialects.py``. Empty for a permissive
    dialect (so transpile-from-DuckDB engines add nothing). Rec 6: pre-empt the footgun at generation time,
    not only at repair time."""
    caps = for_dialect(dialect)
    bad = sorted(caps.unsupported_functions) + sorted(
        _FEATURE_LABEL.get(f, f.upper()) for f in caps.unsupported_features)
    if not bad:
        return ""
    return f"AVOID on {dialect} (these constructs error here): {', '.join(bad)}."
