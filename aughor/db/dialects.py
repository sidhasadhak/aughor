"""Per-dialect SQL-writer rules — dialect knowledge as DATA, selected by how a
connection executes the LLM's SQL.

Aughor has TWO execution modes (this was inconsistent + under-documented before):

  * transpile-from-DuckDB — the connection's execute() runs translate()
    (sqlglot read=duckdb → dialect). DuckDB itself and Postgres take this path.
    The LLM should write DuckDB SQL; sqlglot is the dialect layer (it correctly
    transpiles date_trunc → TIMESTAMP_TRUNC on BigQuery, etc., so a hand-rolled
    time-grain table would be redundant here).

  * native — the connection executes the LLM's SQL verbatim (no transpile).
    BigQuery / Snowflake / MySQL / Exasol take this path. Here the LLM MUST
    write correct *native* SQL, and previously got only "Target dialect: X." with
    no guidance — the gap this module fills. (Exasol declared `postgres` until
    DE-3a and was handed Postgres's rules; it has its own block now.)

`writer_rules(db)` picks the right block from the connection's `dialect` +
`writes_native_sql` flag. Rules cross-checked against Apache Superset's
db_engine_specs (Apache-2.0).
"""
from __future__ import annotations

# DuckDB rules — also the rules for any transpile-from-DuckDB connection (the LLM
# writes DuckDB; sqlglot translates it). Moved here from sql/writer.py.
DUCKDB_RULES = """
DUCKDB DIALECT RULES (violations cause runtime errors):
- Date differences: use date_diff('day', date1, date2) for days or date_diff('second', a, b) for seconds. NEVER use TIMESTAMPDIFF, JULIANDAY. (date - date) already returns an INTEGER day count, so NEVER wrap a date subtraction in date_part/EXTRACT — date_part('day', a - b) and EXTRACT(EPOCH FROM (a - b)) both error. EXTRACT(EPOCH FROM ...) is valid ONLY on an INTERVAL (timestamp - timestamp).
- Date bucketing: use date_trunc('month'|'week'|'day'|'quarter'|'year', ts).
- Interval arithmetic: use INTERVAL '1' DAY syntax. NEVER cast an interval to numeric directly.
- GROUP BY (aggregates): NEVER put aggregate functions (COUNT, SUM, AVG, MAX, MIN) inside GROUP BY. Aggregates belong only in SELECT or HAVING.
- GROUP BY (completeness): every column in SELECT or ORDER BY that is NOT inside an aggregate MUST also appear in GROUP BY. To show a non-grouped attribute, wrap it in MIN/MAX/ANY_VALUE(col); to sort by a metric, ORDER BY the aggregate (e.g. ORDER BY SUM(x) DESC), not a raw ungrouped column.
- HAVING: reference only aggregate expressions or columns that appear in GROUP BY. You CANNOT reference SELECT aliases in HAVING.
- String aggregation: use string_agg(col, sep) not GROUP_CONCAT.
- Type casting: use col::TYPE syntax (e.g. val::DATE, val::NUMERIC) or CAST(val AS TYPE).
- Window functions: fully supported — OVER (PARTITION BY ... ORDER BY ...).
""".strip()

_TRANSPILE_NOTE = (
    "\n\nNOTE: Write DuckDB-flavored SQL. It is automatically translated to the "
    "target engine before execution — do NOT use functions specific to the target "
    "dialect; use the DuckDB forms above."
)

# Native-execution dialects: the LLM's SQL runs verbatim, so it must be correct
# in THIS dialect. Concise, high-yield rules (bucketing / diff / safe-divide /
# casting / string-agg) — the operations LLMs most often get wrong cross-dialect.
#
# DE-3b: the blocks live on each engine's declaration (`connectors/declarations.py`,
# `writer_rules`) and are DERIVED here, one per dialect — stated once, referenced here.
from aughor.connectors.declarations import derive_writer_rules  # noqa: E402

_DIALECT_RULES: dict[str, str] = derive_writer_rules()



def rules_for_dialect(dialect: str) -> str:
    """Native-dialect rule block, with a safe ANSI fallback for unknown engines."""
    return _DIALECT_RULES.get(
        dialect,
        f"Target dialect: {dialect}. Write standard ANSI SQL; avoid engine-specific "
        "functions, and guard divisions with NULLIF(denominator, 0).",
    )


def writer_rules(db: object) -> str:
    """The dialect rule block for the SQL-writer prompt, chosen by execution mode.

    Native-execution connections (writes_native_sql=True) get their dialect's
    native rules; transpile-from-DuckDB connections (DuckDB itself, Postgres) get
    the DuckDB rules (+ a translate note when the target isn't DuckDB).
    """
    dialect = getattr(db, "dialect", "duckdb")
    if getattr(db, "writes_native_sql", False):
        # Native execution runs the LLM's SQL verbatim, so append the machine-checked "don't use these"
        # directive from the capability contract (Rec 6) — pre-empting the footgun at generation time.
        from aughor.db.capabilities import avoid_line
        avoid = avoid_line(dialect)
        return rules_for_dialect(dialect) + (f"\n- {avoid}" if avoid else "")
    return DUCKDB_RULES if dialect == "duckdb" else DUCKDB_RULES + _TRANSPILE_NOTE


def native_sql(db: object, sql: str) -> str:
    """Platform SQL written in DuckDB's dialect — a measurement probe, a keyed read, an object page's read — in the
    dialect ``db`` runs. A connection that runs SQL as it is written (`writes_native_sql`: BigQuery, MySQL, Snowflake,
    Exasol) is handed it translated, since on the backtick engines a double-quoted identifier is a string literal and a
    read written for DuckDB matches nothing there, silently. One that translates from DuckDB itself, DuckDB included,
    is handed it as written. A statement that cannot be translated is handed as written, and the engine refuses it with
    its own reason."""
    dialect = str(getattr(db, "dialect", "") or "")
    if not getattr(db, "writes_native_sql", False) or dialect in ("", "duckdb"):
        return sql
    try:
        import sqlglot
        return sqlglot.transpile(sql, read="duckdb", write=dialect)[0]
    except Exception:  # noqa: BLE001 — the engine's refusal names what it could not run
        return sql


def known_dialect(dialect: str | None) -> str | None:
    """``dialect`` when sqlglot has a dialect of that name, else None — sqlglot's generic parser (DE-1).

    The parse step reads a statement in the dialect of the engine behind the door. An engine sqlglot has no dialect
    for is parsed as standard SQL rather than refused outright: a refusal of every statement would say nothing about
    the statement, and the token-level checks carry the rest. Every connector shipped here declares a dialect
    sqlglot knows; this is the floor for one that does not."""
    if not dialect:
        return None
    try:
        from sqlglot.dialects.dialect import Dialect
        return dialect if Dialect.get(dialect) is not None else None
    except Exception:  # noqa: BLE001 — a parser that cannot say is the generic parser
        return None


#: GM-1 — the one dialect a statement may declare it was written in. Platform code writes DuckDB's: a probe, a
#: series, a keyed read. A statement written for the engine itself — the model's under the writer rules, a person's,
#: one sqlglot rendered in the connection's own dialect — declares nothing.
PLATFORM_DIALECT = "duckdb"


def authored_dialect(db: object) -> str:
    """The dialect a statement written for ``db`` is in: the engine's own on one that runs SQL as it is written
    (`writes_native_sql`: BigQuery, MySQL, Snowflake, Exasol), DuckDB's on one the door translates from DuckDB
    (DuckDB itself, Postgres). A guard reads a model's or a person's statement in this dialect, and a probe that
    carries a fragment of one — a CTE, a subquery, a join expression — is rendered in it and declares nothing,
    since declaring DuckDB would translate the native fragment and corrupt it (GM-1)."""
    dialect = getattr(db, "dialect", "")
    native = getattr(db, "writes_native_sql", False) is True
    return dialect if native and isinstance(dialect, str) and dialect else PLATFORM_DIALECT


def sql_for_engine(db: object, sql: str, sql_dialect: str | None) -> str:
    """GM-1 — the door's dialect step: ``sql`` as the engine behind ``db`` must receive it, from the dialect its
    author declared.

    ``None`` is a statement written for this engine and is handed on as written. ``"duckdb"`` is platform SQL and
    goes through `native_sql`: translated for an engine that runs SQL as written, unchanged for one that translates
    from DuckDB itself. Every connector's `execute` and `execute_bounded` apply this step first, before the safety
    check, the row policy and the audit, so each of those reads the statement the engine will run.

    Before GM-1 the translation was a function each call site had to remember. The monitor runner forgot, and
    theLook's Units Sold watch failed 2,283 times on BigQuery (`docs/GATE_MAP_STUDY_2026-09-26.md`). A declaration
    this step cannot read is refused rather than handed on as written, where it would fail on the engine with
    nothing saying why."""
    if sql_dialect is None:
        return sql
    if sql_dialect != PLATFORM_DIALECT:
        raise ValueError(f"sql_dialect={sql_dialect!r}: platform SQL is written in DuckDB's dialect "
                         f"(sql_dialect={PLATFORM_DIALECT!r}); a statement written for the engine declares nothing")
    return native_sql(db, sql)
