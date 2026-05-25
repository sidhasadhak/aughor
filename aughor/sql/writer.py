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

    # Generic column-missing pattern (Postgres, other dialects)
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

    def __init__(self, db, schema_str: str | None = None):
        self._db = db
        self._schema: str = schema_str if schema_str is not None else db.get_schema()
        self._table_cols: dict[str, list[str]] = _parse_schema_tables(self._schema)
        self._llm: LLMProvider = get_provider("coder")

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def table_cols(self) -> dict[str, list[str]]:
        return self._table_cols

    # ── SQL generation ─────────────────────────────────────────────────────────

    def write(self, question: str, extra_context: str = "") -> str:
        """
        Natural-language question → executable SQL.

        extra_context: any additional framing (domain entities, relationships,
        coverage angles, etc.) prepended before the question.
        """
        class _SQL(BaseModel):
            sql: str

        result = self._llm.complete(
            system=(
                "You are a data analyst writing SQL against a business database. "
                "Write SELECT-only SQL using exact table and column names from the schema. "
                f"Target dialect: {self._db.dialect}. "
                "Never invent column names — use only names that appear in the SCHEMA."
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
                    system="Fix the SQL query. Return corrected_sql and a one-line explanation.",
                    user=FIX_SQL_PROMPT.format(
                        dialect=self._db.dialect,
                        sql=current_sql,
                        error=current_error,
                        error_diagnosis=diagnosis + "\n" if diagnosis else "",
                        schema=self._schema,
                        kb_patterns_section="",
                    ),
                    response_model=_Fix,
                )
                return FixResult(
                    ok=True,
                    sql=fixed.corrected_sql,
                    explanation=fixed.explanation,
                    attempts=attempt,
                )
            except Exception as e:
                current_error = str(e)

        return FixResult(ok=False, sql=sql, final_error=current_error, attempts=max_retries)
