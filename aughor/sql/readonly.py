"""AST-based read-only / mutation detection for LLM-emitted SQL.

The execution gate (`security/safety.py` → `db/connection.py:_security_pre`) was
regex + first-token only. That passes exactly what an AST catches:

  * `SELECT lo_export('/tmp/x', 1)` / `SELECT setval('s', 1)` / `SELECT nextval('s')`
    — mutating Postgres functions that look like reads,
  * `EXPLAIN ANALYZE DELETE FROM t` — Postgres runs the DML,
  * `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` — CTE-masked write,
  * `SELECT * INTO new_table FROM t` — CTAS that creates a table,
  * `exp.Command` DDL the first-token check's keyword list doesn't enumerate.

Adapted from Apache Superset (Apache-2.0) — superset/sql/parse.py (is_mutating /
is_destructive / the mutating node + function + command name lists).

Design — POSITIVE DETECTION ONLY: every function returns True only when the AST
*confirms* a mutation. On a parse failure it returns False, so the caller's
existing regex first-token gate stays the fallback. This strictly ADDS coverage
and never newly blocks the many legitimate SELECTs sqlglot can't parse across
Aughor's dialects. The mutation verdict, when found, is decisive — callers must
not swallow it via a tolerate()/except-pass.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

# Build node tuples by name so a sqlglot version missing one (e.g. exp.Grant on
# an older release) degrades gracefully instead of raising AttributeError.
def _nodes(*names: str) -> tuple[type, ...]:
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


_MUTATING_NODES = _nodes(
    "Insert", "Update", "Delete", "Merge", "Create", "Drop",
    "TruncateTable", "Alter", "Copy", "Grant", "Revoke", "Comment",
)
_DESTRUCTIVE_NODES = _nodes("Drop", "TruncateTable", "Alter")

# Postgres large-object writers + sequence mutators — parse as exp.Anonymous
# function calls inside an otherwise read-looking SELECT. (`currval` only reads
# the session's last value, so it is intentionally absent.)
_MUTATING_FUNCTION_NAMES: frozenset[str] = frozenset({
    "LO_FROM_BYTEA", "LO_EXPORT", "LO_IMPORT", "LO_PUT", "LO_CREATE",
    "LOWRITE", "LO_UNLINK", "SETVAL", "NEXTVAL",
})

# Head keywords sqlglot falls back to an opaque exp.Command for, each of which
# mutates state or wraps a DML body. Case-insensitive lookup.
_MUTATING_COMMAND_NAMES: frozenset[str] = frozenset({
    "DO", "PREPARE", "EXECUTE", "CALL", "COPY", "GRANT", "REVOKE", "SET", "RESET",
    "REFRESH", "REINDEX", "VACUUM", "CREATE", "ALTER", "DROP", "TRUNCATE",
    "LOAD", "ATTACH", "DETACH", "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
})

# Info-disclosure / file / network / process functions to deny even though they
# don't mutate. These are function calls (exp.Anonymous/exp.Func), never columns.
_DISALLOWED_FUNCTIONS: frozenset[str] = frozenset({
    "PG_READ_FILE", "PG_READ_BINARY_FILE", "PG_LS_DIR", "PG_STAT_FILE",
    "LO_IMPORT", "LO_EXPORT", "DBLINK", "DBLINK_EXEC",
    "PG_SLEEP", "PG_TERMINATE_BACKEND", "PG_CANCEL_BACKEND",
    "VERSION", "CURRENT_SETTING",
})

_SessionParameter = getattr(exp, "SessionParameter", None)


def _parse(sql: str, dialect: str | None) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(sql, dialect=dialect, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception:
        return None


def _expr_is_mutating(parsed: exp.Expression, dialect: str | None) -> bool:
    if _MUTATING_NODES and parsed.find(*_MUTATING_NODES):
        return True

    # `SELECT ... INTO target` — CTAS (Postgres/Redshift/TSQL) or MySQL
    # `INTO OUTFILE` (a write). Rare-but-legit `SELECT ... INTO @var` reads are
    # vanishingly uncommon in generated analytics SQL, so we block decisively.
    if isinstance(parsed, exp.Select) and parsed.args.get("into"):
        return True

    # Mutating function calls — restricted to exp.Anonymous so a built-in like
    # `upper('lo_export')` (whose .name is the first arg) isn't misclassified.
    for fn in parsed.find_all(exp.Anonymous):
        if (fn.name or "").upper() in _MUTATING_FUNCTION_NAMES:
            return True

    if isinstance(parsed, exp.Command):
        head = (parsed.name or "").upper()
        if head in _MUTATING_COMMAND_NAMES:
            return True
        # EXPLAIN ANALYZE <dml> — Postgres actually runs the DML.
        if head == "EXPLAIN" and parsed.expression is not None:
            body = (parsed.expression.name or "")
            if body.upper().startswith("ANALYZE "):
                return is_mutating(body[len("ANALYZE "):], dialect)

    return False


def is_mutating(sql: str, dialect: str | None = None) -> bool:
    """True iff the AST confirms the statement mutates data/schema/state.

    Returns False on a parse failure (the caller's regex gate is the fallback).
    """
    parsed = _parse(sql, dialect)
    return False if parsed is None else _expr_is_mutating(parsed, dialect)


def is_destructive(sql: str, dialect: str | None = None) -> bool:
    """True iff the statement is destructive DDL (DROP / TRUNCATE / ALTER)."""
    parsed = _parse(sql, dialect)
    if parsed is None:
        return False
    if _DESTRUCTIVE_NODES and parsed.find(*_DESTRUCTIVE_NODES):
        return True
    if isinstance(parsed, exp.Command) and (parsed.name or "").upper() in {"ALTER", "DROP", "TRUNCATE"}:
        return True
    return False


def disallowed_functions(
    sql: str,
    dialect: str | None = None,
    denylist: frozenset[str] = _DISALLOWED_FUNCTIONS,
) -> set[str]:
    """Return the set of denylisted function / session-parameter names present.

    Catches `pg_read_file()`, `version()`, `current_setting()`, `@@version`, etc.
    Empty set on a parse failure.
    """
    parsed = _parse(sql, dialect)
    if parsed is None:
        return set()
    deny = {d.upper() for d in denylist}
    found: set[str] = set()
    for fn in parsed.find_all(exp.Anonymous):
        name = (fn.name or "").upper()
        if name in deny:
            found.add(name)
    for fn in parsed.find_all(exp.Func):
        try:
            name = fn.sql_name().upper()
        except Exception:
            name = ""
        if name in deny:
            found.add(name)
    if _SessionParameter is not None:
        for sp in parsed.find_all(_SessionParameter):
            name = (sp.name or "").upper()
            if name in deny or "VERSION" in name:
                found.add(name or "SESSION_PARAMETER")
    return found
