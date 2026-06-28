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
    no guidance — the gap this module fills.

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
_DIALECT_RULES: dict[str, str] = {
    "bigquery": """
BIGQUERY (GoogleSQL) DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC(date_col, MONTH) or TIMESTAMP_TRUNC(ts, MONTH) / DATETIME_TRUNC(dt, MONTH). The grain (DAY/WEEK/MONTH/QUARTER/YEAR) is an UNQUOTED keyword, and the column is the FIRST arg — NOT date_trunc('month', col).
- Date differences: DATE_DIFF(d1, d2, DAY) / TIMESTAMP_DIFF(a, b, SECOND) (unit is an unquoted keyword, last arg).
- Division: use SAFE_DIVIDE(a, b) to avoid divide-by-zero errors (returns NULL).
- Type casting: CAST(x AS INT64 | FLOAT64 | NUMERIC | STRING | DATE | TIMESTAMP). Use INT64/FLOAT64/STRING — NOT INTEGER/VARCHAR. SAFE_CAST(...) returns NULL on failure.
- String aggregation: STRING_AGG(col, ',').
- Identifiers: backtick-quote `project.dataset.table`. Reference SELECT aliases in GROUP BY/ORDER BY by position or alias (allowed), but NOT in WHERE/HAVING.
""".strip(),
    "snowflake": """
SNOWFLAKE DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC('MONTH', ts) (grain quoted, column second). Supports MINUTE/HOUR/DAY/WEEK/MONTH/QUARTER/YEAR.
- Date differences: DATEDIFF('day', d1, d2) / DATEDIFF('second', a, b) (unit quoted, FIRST arg). TIMESTAMPDIFF(unit, a, b) is also valid — do not "fix" it away.
- Division: use DIV0(a, b) (returns 0 on zero denominator) or IFF(b = 0, NULL, a / b).
- Type casting: x::NUMBER / x::VARCHAR / CAST(x AS NUMBER). TRY_CAST(...) returns NULL on failure.
- String aggregation: LISTAGG(col, ',') WITHIN GROUP (ORDER BY col); to build an array use ARRAY_AGG(col).
- Filter by a window function: use QUALIFY (e.g. QUALIFY ROW_NUMBER() OVER (PARTITION BY x ORDER BY y) = 1) — you CANNOT put a window function in WHERE.
- Semi-structured (VARIANT/OBJECT/ARRAY): navigate with colon/bracket paths — col:field, col:a.b, col['k']; cast the leaf with ::STRING/::NUMBER. Expand an array into rows with LATERAL FLATTEN(input => col) f, then read f.value.
- Case-insensitive match: ILIKE '%text%' (not LOWER(col) LIKE).
- Identifiers fold to UPPERCASE unless double-quoted. You CANNOT reference SELECT aliases in WHERE/HAVING.
""".strip(),
    "mysql": """
MYSQL DIALECT RULES (violations cause query errors):
- Date bucketing: MySQL has NO date_trunc. Month → DATE_FORMAT(ts, '%Y-%m-01'); day → DATE(ts); year → DATE_FORMAT(ts, '%Y-01-01'); week (Mon start) → DATE_SUB(DATE(ts), INTERVAL WEEKDAY(ts) DAY). NEVER call date_trunc().
- Date differences: DATEDIFF(d1, d2) for whole days; TIMESTAMPDIFF(SECOND, a, b) for seconds (note: DATEDIFF takes exactly 2 args, no unit).
- Division: guard zero denominators with NULLIF — a / NULLIF(b, 0).
- Type casting: CAST(x AS SIGNED | DECIMAL(38,6) | CHAR | DATE | DATETIME). MySQL has no ::TYPE syntax and no CAST AS INT/VARCHAR (use SIGNED/CHAR).
- String aggregation: GROUP_CONCAT(col SEPARATOR ',').
- Identifiers: backtick-quote. You CAN reference SELECT aliases in GROUP BY/HAVING (MySQL extension).
""".strip(),
    "postgres": """
POSTGRESQL DIALECT RULES (violations cause query errors):
- Date bucketing: DATE_TRUNC('month'|'week'|'day'|'quarter'|'year', ts).
- Date differences: (d1 - d2) yields an INTEGER day count for dates; EXTRACT(EPOCH FROM (a - b)) for seconds between timestamps.
- Division: integer/integer truncates — cast one side (a::numeric / b) and guard zero with NULLIF(b, 0).
- Type casting: x::numeric / x::text / CAST(x AS date).
- String aggregation: STRING_AGG(col, ',').
- You CANNOT reference SELECT aliases in WHERE/HAVING/GROUP BY.
""".strip(),
}


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
        return rules_for_dialect(dialect)
    return DUCKDB_RULES if dialect == "duckdb" else DUCKDB_RULES + _TRANSPILE_NOTE
