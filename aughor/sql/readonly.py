"""AST-based read-only / mutation detection for LLM-emitted SQL.

The execution gate (`security/safety.py` → `db/connection.py:security_pre`) was
regex + first-token only. That passes exactly what an AST catches:

  * `SELECT lo_export('/tmp/x', 1)` / `SELECT setval('s', 1)` / `SELECT nextval('s')`
    — mutating Postgres functions that look like reads,
  * `EXPLAIN ANALYZE DELETE FROM t` — Postgres runs the DML,
  * `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` — CTE-masked write,
  * `SELECT * INTO new_table FROM t` — CTAS that creates a table,
  * `exp.Command` DDL the first-token check's keyword list doesn't enumerate.

Adapted from Apache Superset (Apache-2.0) — superset/sql/parse.py (is_mutating /
is_destructive / the mutating node + function + command name lists). The
external-reader denylist and file-path table-source check are adapted from
WrenAI (Apache-2.0) — core/wren/src/wren/policy.py: LLM SQL on a DuckDB-backed
connection can otherwise read the local filesystem (`read_csv`, `read_text`,
`glob`, bare `FROM '/path/x.csv'` replacement scans) or reach out over the
network (`postgres_scan`, httpfs paths) — reads, so the mutation gate passes
them. Blocked in EVERY AST position, and error strings report only the
function name, never its argument (the argument IS the sensitive path/DSN).

Design — POSITIVE DETECTION ONLY: every function returns True only when the AST
*confirms* a mutation. On a parse failure it returns False, so the caller's
existing regex first-token gate stays the fallback. This strictly ADDS coverage
and never newly blocks the many legitimate SELECTs sqlglot can't parse across
Aughor's dialects. The mutation verdict, when found, is decisive — callers must
not swallow it via a tolerate()/except-pass.

DE-1 (ROADMAP §3.51, `docs/DBX_STUDY_2026-10-01.md` §3.1) taught it the reads that
can write, measured on `f02c8f22` as passing every check: a locking clause
(`FOR UPDATE`, `FOR SHARE`, `LOCK IN SHARE MODE` — sqlglot's `locks`), the
side-effect functions (advisory locks, `GET_LOCK`, a `set_config` that turns the
Postgres read-only backstop off), a DML command inside a `BEGIN … END` block, and —
below the tree, where a parser drops them — a MySQL executable comment
(`/*!50000 DROP TABLE users */` is a comment to sqlglot and a statement to MySQL)
and `SELECT … INTO OUTFILE`, which does not parse at all. Those two are read from
the text, the one exception to the rule above, because the tree cannot carry them.
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

# Build node tuples by name so a sqlglot version missing one (e.g. exp.Grant on
# an older release) degrades gracefully instead of raising AttributeError.
def _nodes(*names: str) -> tuple[type, ...]:
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


_MUTATING_NODES = _nodes(
    "Insert", "Update", "Delete", "Merge", "Create", "Drop",
    "TruncateTable", "Alter", "Copy", "Grant", "Revoke", "Comment",
    # sqlglot parses these as dedicated nodes, NOT exp.Command, so the
    # command-head list below never sees them: ATTACH mounts an arbitrary
    # database file; INSTALL pulls an extension (FORCE INSTALL parses to the
    # same node).
    "Attach", "Detach", "Install",
)
_DESTRUCTIVE_NODES = _nodes("Drop", "TruncateTable", "Alter")

# The reads that can write (DE-1): a SELECT of one of these changes the session, the server or what other sessions
# may do. `set_config('default_transaction_read_only', 'off', false)` was rated SAFE and turned the pooled Postgres
# session's read-only backstop off (the study's finding 2); an advisory lock or `GET_LOCK` holds a lock for as long
# as the pooled connection lives; `BENCHMARK` burns the server's CPU on request.
_SIDE_EFFECT_FUNCTION_NAMES: frozenset[str] = frozenset({
    "SET_CONFIG", "PG_RELOAD_CONF", "PG_ROTATE_LOGFILE", "PG_SWITCH_WAL", "PG_CREATE_RESTORE_POINT", "PG_NOTIFY",
    "PG_ADVISORY_LOCK", "PG_ADVISORY_LOCK_SHARED", "PG_ADVISORY_XACT_LOCK", "PG_ADVISORY_XACT_LOCK_SHARED",
    "PG_TRY_ADVISORY_LOCK", "PG_TRY_ADVISORY_LOCK_SHARED", "PG_TRY_ADVISORY_XACT_LOCK",
    "PG_TRY_ADVISORY_XACT_LOCK_SHARED", "PG_ADVISORY_UNLOCK", "PG_ADVISORY_UNLOCK_SHARED", "PG_ADVISORY_UNLOCK_ALL",
    "GET_LOCK", "RELEASE_LOCK", "RELEASE_ALL_LOCKS", "BENCHMARK",
})

# Postgres large-object writers + sequence mutators — parse as exp.Anonymous
# function calls inside an otherwise read-looking SELECT. (`currval` only reads
# the session's last value, so it is intentionally absent.)
_MUTATING_FUNCTION_NAMES: frozenset[str] = frozenset({
    "LO_FROM_BYTEA", "LO_EXPORT", "LO_IMPORT", "LO_PUT", "LO_CREATE",
    "LOWRITE", "LO_UNLINK", "SETVAL", "NEXTVAL",
}) | _SIDE_EFFECT_FUNCTION_NAMES

# Below the tree (DE-1). MySQL executes the body of `/*!NNNNN … */`, and MariaDB of `/*M! … */`; to every parser
# it is a comment, so `SELECT 1 /*!50000 UNION SELECT user FROM mysql.user */` parsed as `SELECT 1`. `INTO OUTFILE`
# / `INTO DUMPFILE` write a file on the server and do not parse at all, so the tree could never see them either.
# Strings and ordinary comments are blanked before the file-write scan, so a value that merely says "into outfile"
# is data; an executable comment is matched on the raw text, because it IS a comment.
_EXECUTABLE_COMMENT = re.compile(r"/\*M?!")
_INTO_FILE = re.compile(r"\bINTO\s+(?:OUTFILE|DUMPFILE)\b", re.IGNORECASE)
_STRING_OR_PLAIN_COMMENT = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*(?!M?!).*?\*/", re.DOTALL)
#: A command head whose body is itself a statement: sqlglot hands back `BEGIN DELETE FROM t; END` as a Block holding
#: an opaque Command named BEGIN, with the DELETE in the command's text.
_BODY_COMMAND_NAMES: frozenset[str] = frozenset({"BEGIN", "DO"})

# Head keywords sqlglot falls back to an opaque exp.Command for, each of which
# mutates state or wraps a DML body. Case-insensitive lookup.
_MUTATING_COMMAND_NAMES: frozenset[str] = frozenset({
    "DO", "PREPARE", "EXECUTE", "CALL", "COPY", "GRANT", "REVOKE", "SET", "RESET",
    "REFRESH", "REINDEX", "VACUUM", "CREATE", "ALTER", "DROP", "TRUNCATE",
    "LOAD", "ATTACH", "DETACH", "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
})

# DuckDB (and friends) file / remote / secret readers — pure reads, invisible
# to the mutation gate, but they turn an LLM SQL surface into filesystem and
# network access. Matched against BOTH exp.Anonymous names (read_text, glob…)
# and exp.Func.sql_name() (READ_CSV, READ_PARQUET get dedicated sqlglot nodes).
_EXTERNAL_READER_FUNCTIONS: frozenset[str] = frozenset({
    # file readers / sniffers
    "READ_CSV", "READ_CSV_AUTO", "SNIFF_CSV",
    "READ_PARQUET", "PARQUET_SCAN", "PARQUET_METADATA", "PARQUET_SCHEMA",
    "PARQUET_KV_METADATA", "PARQUET_FILE_METADATA",
    "READ_JSON", "READ_JSON_AUTO", "READ_JSON_OBJECTS", "READ_JSON_OBJECTS_AUTO",
    "READ_NDJSON", "READ_NDJSON_AUTO", "READ_NDJSON_OBJECTS",
    "READ_TEXT", "READ_BLOB", "READ_XLSX", "GLOB",
    # spatial / lakehouse / cross-database scanners
    "ST_READ", "ST_READ_META",
    "ICEBERG_SCAN", "ICEBERG_METADATA", "ICEBERG_SNAPSHOTS", "DELTA_SCAN",
    "SQLITE_SCAN", "SQLITE_ATTACH", "POSTGRES_SCAN", "POSTGRES_ATTACH",
    "POSTGRES_QUERY", "MYSQL_QUERY",
    # environment / secret disclosure
    "GETENV", "DUCKDB_SECRETS", "WHICH_SECRET", "LOAD_AWS_CREDENTIALS",
    # MySQL server-side file read
    "LOAD_FILE",
})

# Info-disclosure / file / network / process functions to deny even though they
# don't mutate. These are function calls (exp.Anonymous/exp.Func), never columns.
_DISALLOWED_FUNCTIONS: frozenset[str] = frozenset({
    "PG_READ_FILE", "PG_READ_BINARY_FILE", "PG_LS_DIR", "PG_STAT_FILE",
    "LO_IMPORT", "LO_EXPORT", "DBLINK", "DBLINK_EXEC",
    "PG_SLEEP", "PG_TERMINATE_BACKEND", "PG_CANCEL_BACKEND",
    "VERSION", "CURRENT_SETTING",
}) | _EXTERNAL_READER_FUNCTIONS

# DuckDB's replacement scan turns a bare string/identifier table source into a
# file read: `FROM '/data/x.csv'`, `FROM 's3://bucket/x.parquet'`, and even
# quoted `FROM "x.csv"` when no such table exists. sqlglot parses all of these
# as exp.Table over a plain Identifier, so no function check can see them.
# Reported as the pseudo-name FILE_TABLE_SOURCE — never the path itself.
_FILE_SOURCE_SUFFIXES: tuple[str, ...] = (
    ".csv", ".tsv", ".parquet", ".parq", ".json", ".ndjson", ".jsonl",
    ".xlsx", ".xls", ".duckdb", ".db", ".gz", ".zst",
)
FILE_TABLE_SOURCE = "FILE_TABLE_SOURCE"


def _is_file_table_source(name: str) -> bool:
    lowered = name.lower()
    if "/" in lowered or "\\" in lowered or "://" in lowered:
        return True
    return lowered.endswith(_FILE_SOURCE_SUFFIXES)

_SessionParameter = getattr(exp, "SessionParameter", None)


def _parse(sql: str, dialect: str | None) -> exp.Expression | None:
    from aughor.db.dialects import known_dialect
    try:
        return sqlglot.parse_one(sql, dialect=known_dialect(dialect), error_level=sqlglot.ErrorLevel.RAISE)
    except Exception:
        return None


def hidden_statement(sql: str) -> str | None:
    """What the text carries that no syntax tree can show (DE-1): the name of the shape, or None.

    An executable comment is a statement to MySQL and a comment to every parser; `INTO OUTFILE` writes a server
    file and never parses. Both are read from the text — the one place they exist."""
    text = sql or ""
    if _EXECUTABLE_COMMENT.search(text):
        return "executable comment"
    if _INTO_FILE.search(_STRING_OR_PLAIN_COMMENT.sub(" ", text)):
        return "INTO OUTFILE/DUMPFILE"
    return None


def _expr_is_mutating(parsed: exp.Expression, dialect: str | None, depth: int = 0) -> bool:
    if _MUTATING_NODES and parsed.find(*_MUTATING_NODES):
        return True

    for select in parsed.find_all(exp.Select):
        # `SELECT ... INTO target` — CTAS (Postgres/Redshift/TSQL) or MySQL
        # `INTO OUTFILE` (a write). Rare-but-legit `SELECT ... INTO @var` reads are
        # vanishingly uncommon in generated analytics SQL, so we block decisively.
        if select.args.get("into"):
            return True
        # A locking clause (DE-1): `FOR UPDATE`, `FOR SHARE`, `FOR NO KEY UPDATE`, `FOR KEY SHARE`, MySQL's
        # `LOCK IN SHARE MODE`. A read that holds row locks for as long as the pooled connection lives.
        if select.args.get("locks"):
            return True

    # Mutating function calls — restricted to exp.Anonymous so a built-in like
    # `upper('lo_export')` (whose .name is the first arg) isn't misclassified.
    for fn in parsed.find_all(exp.Anonymous):
        if (fn.name or "").upper() in _MUTATING_FUNCTION_NAMES:
            return True

    # A command anywhere in the tree, not only at the root (DE-1): a `BEGIN … END` block parses as a Block holding
    # one opaque Command, and `SELECT 1; DELETE FROM t` as a Block of two statements.
    for command in parsed.find_all(exp.Command):
        head = (command.name or "").upper()
        if head in _MUTATING_COMMAND_NAMES:
            return True
        body = (command.expression.name or "") if command.expression is not None else ""
        # EXPLAIN ANALYZE <dml> — Postgres actually runs the DML.
        if head == "EXPLAIN" and body.upper().startswith("ANALYZE ") and depth < 3:
            if _text_is_mutating(body[len("ANALYZE "):], dialect, depth + 1):
                return True
        # BEGIN <statement> — the block's body is the statement that runs.
        if head in _BODY_COMMAND_NAMES and body and depth < 3:
            if _text_is_mutating(body, dialect, depth + 1):
                return True

    return False


def _text_is_mutating(sql: str, dialect: str | None, depth: int) -> bool:
    if hidden_statement(sql):
        return True
    parsed = _parse(sql, dialect)
    return False if parsed is None else _expr_is_mutating(parsed, dialect, depth)


def is_mutating(sql: str, dialect: str | None = None) -> bool:
    """True iff the AST confirms the statement mutates data/schema/state — or the text carries a statement the tree
    cannot show (`hidden_statement`).

    Returns False on a parse failure otherwise (the caller's regex gate is the fallback).
    """
    return _text_is_mutating(sql, dialect, 0)


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
    if parsed is None and dialect != "duckdb":
        # DuckDB-only constructs (`glob(...)` as a table function) fail the
        # generic parse — sqlglot maps GLOB to a binary operator there. Retry
        # as DuckDB: positive detection only, so a second parse can only ADD
        # coverage, never newly pass something.
        parsed = _parse(sql, "duckdb")
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
    for table in parsed.find_all(exp.Table):
        source = table.this
        if isinstance(source, exp.Identifier) and _is_file_table_source(source.name or ""):
            found.add(FILE_TABLE_SOURCE)
    return found
