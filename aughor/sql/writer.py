"""Centralised SQL writer — one place for generation and error-correction.

Used by:
  - Phase 8 domain intelligence (aughor/explorer/agent.py)
  - Manual retry endpoint  (aughor/api.py  /exploration/{id}/retry-query)
  - Chat pipeline          (aughor/api.py  _stream_chat)

Design goals
------------
* Schema context is built once at construction time and reused — no repeated
  introspection on every fix attempt.
* fix() resolves table aliases in the failing SQL (e.g. "o" → "orders") and
  injects that table's exact column list into the prompt so the LLM can pick
  the right column instead of falling back to SUM(0)-style hacks.
* All callers share the same FIX_SQL_PROMPT so prompt improvements propagate
  everywhere automatically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from aughor.llm.provider import LLMProvider, get_provider
from aughor.tools.schema import _parse_schema_tables


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class FixResult:
    ok: bool
    sql: str
    explanation: str = ""
    attempts: int = 1
    final_error: str = ""


# ── Alias resolver ────────────────────────────────────────────────────────────

# Matches: FROM tablename [AS alias]  or  JOIN tablename [AS alias]
# Stops at keywords that can follow a table reference so they aren't
# mistaken for aliases (ON, SET, WHERE, AND, OR, INNER, LEFT, etc.)
_FROM_JOIN = re.compile(
    r'(?:FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?(?!ON\b|SET\b|WHERE\b|AND\b|OR\b|INNER\b|LEFT\b|RIGHT\b|FULL\b|CROSS\b)(\w+))?',
    re.IGNORECASE,
)


def _resolve_aliases(sql: str) -> dict[str, str]:
    """Return {alias_lower: real_table_name} from every FROM/JOIN clause."""
    aliases: dict[str, str] = {}
    for m in _FROM_JOIN.finditer(sql):
        table, alias = m.group(1), m.group(2)
        aliases[table.lower()] = table
        if alias:
            aliases[alias.lower()] = table
    return aliases


# ── Error → targeted diagnosis ────────────────────────────────────────────────

def _extract_candidate_bindings(error: str) -> list[str]:
    """
    DuckDB includes the real column names in Binder errors, e.g.:
      Candidate bindings: : "timestamp", "movement_id", "movement_type"
    Extract them — they are more authoritative than a schema lookup.
    """
    m = re.search(r'Candidate bindings\s*:?\s*:?\s*(.+?)(?:\n|$)', error)
    if not m:
        return []
    return re.findall(r'"(\w+)"', m.group(1))


def _make_diagnosis(error: str, sql: str, table_cols: dict[str, list[str]]) -> str:
    """
    Turn a raw SQL error into an actionable DIAGNOSIS block for the fix prompt.

    Priority order for column list:
    1. DuckDB "Candidate bindings" — the engine tells us the real columns directly
    2. Schema lookup via alias resolution — table_cols from build_schema_context
    """
    # DuckDB Binder: Table "im" does not have a column named "id"
    m = re.search(
        r'[Tt]able\s+"?(\w+)"?\s+does not have a column named\s+"?(\w+)"?',
        error,
    )
    if m:
        alias_ref, bad_col = m.group(1).lower(), m.group(2)
        aliases = _resolve_aliases(sql)
        real_table = aliases.get(alias_ref, alias_ref)

        # Prefer DuckDB's own candidate bindings — they're always correct
        candidates = _extract_candidate_bindings(error)
        if not candidates:
            # Fall back to schema lookup
            candidates = (
                table_cols.get(real_table)
                or table_cols.get(real_table.lower())
                or next((v for k, v in table_cols.items() if k.lower() == real_table.lower()), None)
                or []
            )

        if candidates:
            return (
                f"DIAGNOSIS: '{bad_col}' does not exist in table '{real_table}'.\n"
                f"Exact columns in {real_table}: {', '.join(candidates)}\n"
                f"Use the semantically closest column from this list for the same intent as '{bad_col}'. "
                "NEVER substitute SUM(0), NULL, or any constant — that silently destroys query intent."
            )
        return (
            f"DIAGNOSIS: '{bad_col}' does not exist in table '{real_table}'. "
            "Use only column names that appear verbatim in the SCHEMA above."
        )

    # Referenced table/alias used but not brought into FROM/JOIN
    # (DuckDB: 'Referenced table "oi" not found!')
    m = re.search(r'[Rr]eferenced table\s+"?(\w+)"?\s+not found', error)
    if m:
        bad = m.group(1)
        present = ", ".join(sorted(set(_resolve_aliases(sql).values()))) or "(see SCHEMA)"
        return (
            f"DIAGNOSIS: table/alias '{bad}' is referenced but never appears in any FROM or JOIN. "
            f"Either add the JOIN that brings '{bad}' in (only on a real key relationship), or remove "
            f"every reference to '{bad}'. Tables currently in the query: {present}."
        )

    # Column referenced but not exposed by the FROM/CTEs
    # (DuckDB: 'Referenced column "x" not found in FROM clause!')
    m = re.search(r'[Rr]eferenced column\s+"?(\w+)"?\s+not found', error)
    if m:
        bad = m.group(1)
        cands = _extract_candidate_bindings(error)
        hint = f" Columns available here: {', '.join(cands)}." if cands else ""
        return (
            f"DIAGNOSIS: column '{bad}' is not exposed by the query's FROM/CTEs — it may live inside a "
            f"subquery that does not SELECT it out, be defined after it is used, or be misspelled.{hint} "
            f"SELECT '{bad}' out of the inner query before referencing it, or qualify it with its table."
        )

    # Ambiguous column — exists in 2+ joined tables, must be qualified
    # (DuckDB: 'Ambiguous reference to column name "x"'; Postgres: 'column reference "x" is ambiguous')
    m = re.search(r'[Aa]mbiguous reference to column name\s+"?(\w+)"?', error) or \
        re.search(r'column reference\s+"?(\w+)"?\s+is ambiguous', error)
    if m:
        bad = m.group(1)
        return (
            f"DIAGNOSIS: column '{bad}' exists in more than one joined table, so it must be qualified. "
            f"Prefix every use of it with the intended table alias (e.g. o.{bad} or oi.{bad})."
        )

    # Non-aggregated column in SELECT/ORDER BY missing from GROUP BY
    # (DuckDB: 'column "x" must appear in the GROUP BY clause or must be part of
    #  an aggregate function.'). The column EXISTS — it just needs grouping or
    # aggregating, so this is distinct from the missing-column branch above and
    # must NOT be treated as a dead reference.
    m = re.search(r'column\s+"?(\w+)"?\s+must appear in the GROUP BY clause', error, re.IGNORECASE)
    if m:
        bad = m.group(1)
        return (
            f"DIAGNOSIS: column '{bad}' is selected or ordered-by but is neither listed in "
            f"GROUP BY nor wrapped in an aggregate. Choose ONE: (a) add '{bad}' to the GROUP BY "
            f"clause if you want one row per '{bad}' value; (b) wrap it in an aggregate matching "
            f"the intent — SUM/COUNT/AVG for a metric, or MIN/MAX/ANY_VALUE({bad}) for a "
            f"display-only attribute. If '{bad}' appears only in ORDER BY, order by an aggregate "
            f"instead (e.g. ORDER BY SUM(metric) DESC), not the raw column. "
            f"Do NOT drop the column — it exists; it is only ungrouped."
        )

    # Outer join directly onto a subquery (DuckDB can't do non-inner joins on arbitrary subqueries)
    if "non-inner join on subquery" in error.lower():
        return (
            "DIAGNOSIS: this engine cannot LEFT/RIGHT/FULL JOIN directly onto a subquery. Rewrite as one "
            "of: (a) an INNER JOIN if every row matches anyway; (b) move the subquery into a WITH (CTE) "
            "and join the CTE — WITH sub AS (<subquery>) SELECT ... LEFT JOIN sub ON ...; or "
            "(c) a correlated scalar subquery in SELECT. Prefer the CTE rewrite."
        )

    # Generic column-missing pattern (Postgres, other dialects) — catch-all after the
    # specific column/table branches above.
    if "does not have a column" in error or (
        "column" in error.lower() and ("not" in error.lower() or "unknown" in error.lower())
    ):
        candidates = _extract_candidate_bindings(error)
        hint = f" Available columns: {', '.join(candidates)}." if candidates else ""
        return (
            "DIAGNOSIS: A column name in the query does not exist in its table."
            + hint
            + " Use ONLY exact column names from the SCHEMA. "
            "Do NOT substitute SUM(0), NULL, or a constant — that produces wrong results silently."
        )

    # Table missing
    if ("does not exist" in error or "no such table" in error.lower()) and "table" in error.lower():
        return (
            "DIAGNOSIS: A table name does not exist. "
            "Use ONLY the table names listed in the SCHEMA above."
        )

    # DuckDB: TIMESTAMPDIFF not found (MySQL function)
    err_lower = error.lower()
    if "timestampdiff" in err_lower:
        return (
            "DIAGNOSIS: TIMESTAMPDIFF is a MySQL function — DuckDB doesn't have it. "
            "Use datediff('day', date1, date2) for day differences, or "
            "CAST(date2 AS DATE) - CAST(date1 AS DATE) which returns an integer number of days."
        )

    # DuckDB: JULIANDAY not found (SQLite function)
    if "julianday" in err_lower:
        return (
            "DIAGNOSIS: JULIANDAY is a SQLite function — DuckDB doesn't have it. "
            "For day differences use datediff('day', date1, date2). "
            "For date-to-number conversions use epoch_days(date::DATE) or CAST(date AS DATE) arithmetic."
        )

    # DuckDB: aggregate in GROUP BY
    if "group by clause cannot contain aggregates" in err_lower:
        return (
            "DIAGNOSIS: An aggregate function (COUNT, SUM, AVG, etc.) appears inside GROUP BY — "
            "that is never valid. GROUP BY must contain only raw column references. "
            "Move the aggregate to SELECT or HAVING."
        )

    # DuckDB: HAVING references a SELECT alias
    if "having" in err_lower and ("does not exist" in err_lower or "not found" in err_lower):
        return (
            "DIAGNOSIS: HAVING cannot reference a SELECT alias — rewrite using the full expression. "
            "E.g. instead of HAVING converted = 1, use HAVING SUM(CASE WHEN ... THEN 1 ELSE 0 END) = 1."
        )

    # DuckDB: to_char (Postgres/Oracle date-formatting fn) does not exist
    if "to_char" in err_lower:
        return (
            "DIAGNOSIS: to_char() is a Postgres/Oracle function — DuckDB doesn't have it. "
            "To format a date/timestamp as text use strftime(col, '%Y-%m') for month, "
            "'%Y-%m-%d' for day, or '%Y' for year. To bucket rows by month use "
            "date_trunc('month', col). Do NOT use to_char."
        )

    # DuckDB: date_part/EXTRACT applied to a date subtraction. (date - date)
    # returns an INTEGER number of days, so date_part('day', a - b) AND
    # EXTRACT(EPOCH FROM (a - b)) — which DuckDB lowers to date_part('epoch', BIGINT) —
    # both fail with 'No function matches date_part(VARCHAR, BIGINT)'.
    if "date_part" in err_lower and (
        "bigint" in err_lower or "integer" in err_lower or "no function matches" in err_lower
    ):
        return (
            "DIAGNOSIS: date_part/EXTRACT on a date subtraction fails because in DuckDB "
            "(date - date) already returns an INTEGER number of days, not an interval — so "
            "date_part('day', a - b) and EXTRACT(EPOCH FROM (a - b)) both error. "
            "For elapsed SECONDS use date_diff('second', b, a); for DAYS use "
            "date_diff('day', b, a) or just (a - b) when both are DATE. Remove the "
            "date_part/EXTRACT wrapper. (Subtracting two TIMESTAMPs yields an INTERVAL, on "
            "which EXTRACT(EPOCH FROM ...) is valid — cast both sides to TIMESTAMP if you need seconds.)"
        )

    return ""


# ── SqlWriter ─────────────────────────────────────────────────────────────────

class SqlWriter:
    """
    Single entry point for SQL generation and error-correction.

    Instantiate once per session (or per request) — schema introspection is
    cached on the instance and reused across all write/fix calls.

    Parameters
    ----------
    db          DatabaseConnection  — exposes .get_schema() and .dialect
    schema_str  Optional pre-built schema string; skips db.get_schema() if
                supplied (useful when the caller already holds a fresh schema)
    """

    def __init__(self, db, schema_str: str | None = None, temperature: float = 0.1):
        self._db = db
        self._schema: str = schema_str if schema_str is not None else db.get_schema()
        self._table_cols: dict[str, list[str]] = _parse_schema_tables(self._schema)
        self._llm: LLMProvider = get_provider("coder")
        # Decode temperature for the write/fix calls. Defaults to 0.1 — the same
        # value LLMProvider.complete() already used implicitly — so existing
        # callers are unaffected. The eval harness sets 0.0 for deterministic,
        # noise-controlled measurement (so a fix-path retry can't add variance).
        self._temperature: float = temperature

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def table_cols(self) -> dict[str, list[str]]:
        return self._table_cols

    # ── SQL generation ─────────────────────────────────────────────────────────

    # DuckDB-specific rules injected into every write prompt
    _DUCKDB_RULES = """
DUCKDB DIALECT RULES (violations cause runtime errors):
- Date differences: use date_diff('day', date1, date2) for days or date_diff('second', a, b) for seconds. NEVER use TIMESTAMPDIFF, JULIANDAY. (date - date) already returns an INTEGER day count, so NEVER wrap a date subtraction in date_part/EXTRACT — date_part('day', a - b) and EXTRACT(EPOCH FROM (a - b)) both error. EXTRACT(EPOCH FROM ...) is valid ONLY on an INTERVAL (timestamp - timestamp).
- Interval arithmetic: use INTERVAL '1' DAY syntax. NEVER cast an interval to numeric directly.
- GROUP BY (aggregates): NEVER put aggregate functions (COUNT, SUM, AVG, MAX, MIN) inside GROUP BY. Aggregates belong only in SELECT or HAVING.
- GROUP BY (completeness): every column in SELECT or ORDER BY that is NOT inside an aggregate MUST also appear in GROUP BY. To show a non-grouped attribute, wrap it in MIN/MAX/ANY_VALUE(col); to sort by a metric, ORDER BY the aggregate (e.g. ORDER BY SUM(x) DESC), not a raw ungrouped column.
- HAVING: reference only aggregate expressions or columns that appear in GROUP BY. You CANNOT reference SELECT aliases in HAVING.
- String aggregation: use string_agg(col, sep) not GROUP_CONCAT.
- Type casting: use col::TYPE syntax (e.g. val::DATE, val::NUMERIC) or CAST(val AS TYPE).
- Window functions: fully supported — OVER (PARTITION BY ... ORDER BY ...).
""".strip()

    def write(self, question: str, extra_context: str = "") -> str:
        """
        Natural-language question → executable SQL.

        extra_context: any additional framing (domain entities, relationships,
        coverage angles, etc.) prepended before the question.
        """
        class _SQL(BaseModel):
            sql: str

        dialect_rules = self._DUCKDB_RULES if self._db.dialect == "duckdb" else f"Target dialect: {self._db.dialect}."

        result = self._llm.complete(
            temperature=self._temperature,
            system=(
                "You are a data analyst writing SQL against a business database. "
                "Write SELECT-only SQL using exact table and column names from the schema. "
                "Never invent column names — use only names that appear in the SCHEMA.\n\n"
                + dialect_rules
            ),
            user=(
                f"SCHEMA:\n{self._schema}\n\n"
                + (f"{extra_context}\n\n" if extra_context else "")
                + f"QUESTION: {question}\n\nWrite executable SQL."
            ),
            response_model=_SQL,
        )
        return result.sql

    # ── SQL correction ─────────────────────────────────────────────────────────

    def fix(
        self,
        sql: str,
        error: str,
        hint: str = "",
        max_retries: int = 2,
    ) -> FixResult:
        """
        Correct a failing SQL query with up to max_retries LLM attempts.

        Each attempt:
        1. Classifies the error and resolves the named alias to the real table.
        2. Injects that table's exact column list into the diagnosis block.
        3. Calls the LLM with FIX_SQL_PROMPT (shared with the chat pipeline).

        If max_retries is exhausted, returns FixResult(ok=False) with the
        original SQL and the last error — the caller decides what to do.
        """
        from aughor.agent.prompts import FIX_SQL_PROMPT

        class _Fix(BaseModel):
            corrected_sql: str
            explanation: str = ""

        current_sql = sql
        current_error = error

        for attempt in range(1, max_retries + 1):
            diagnosis = _make_diagnosis(current_error, current_sql, self._table_cols)
            if hint.strip():
                diagnosis += f"\nUSER GUIDANCE: {hint.strip()}"

            try:
                fixed = self._llm.complete(
                    temperature=self._temperature,
                    system="Fix the SQL query. Return corrected_sql and a one-line explanation.",
                    user=FIX_SQL_PROMPT.format(
                        dialect=self._db.dialect,
                        sql=current_sql,
                        error=current_error,
                        error_diagnosis=diagnosis + "\n" if diagnosis else "",
                        schema=self._schema,
                        kb_patterns_section="",
                        metrics_section="",
                    ),
                    response_model=_Fix,
                )
            except Exception as e:
                current_error = str(e)
                continue

            # Validate the correction before accepting it — catches the LLM
            # fixing one error while introducing another (wrong column, bad syntax).
            dry_ok, dry_err = self._db.dry_run(fixed.corrected_sql)
            if dry_ok:
                return FixResult(
                    ok=True,
                    sql=fixed.corrected_sql,
                    explanation=fixed.explanation,
                    attempts=attempt,
                )
            # Dry-run failed: feed the real error back into the next attempt
            current_sql = fixed.corrected_sql
            current_error = dry_err

        return FixResult(ok=False, sql=current_sql, final_error=current_error, attempts=max_retries)
