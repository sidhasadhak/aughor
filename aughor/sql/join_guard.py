"""
Value-domain join guard.

Every other join safety gate (detect_invalid_joins, check_entity_column_alignment,
Phase-8 binder) reasons about column names / types / ontology.  A wrong join can
still slip through when two columns share a name-shape but hold values from
entirely different entities — e.g. orders.customer_id = 'C-000123' while
forms.c_id = 'CF-98122'.  The value domain cannot be fooled the way names can.

This module probes value overlap by sampling both sides of each explicit JOIN
condition and checking containment.  A real FK has high overlap; a bogus join
has ~0%.  The check is entirely fail-open: any exception (unparseable SQL, CTE
alias, empty table, connection unavailable) returns no warnings and lets the
query proceed normally.

Hook: call check_join_value_domains(conn, sql) alongside detect_invalid_joins
in execute_planned_queries.  The returned JoinDomainWarning objects satisfy the
same .to_prompt_text() interface as JoinWarning / AmbiguityWarning.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

# Overlap below this fraction → warn.  Chosen conservatively so a lightly
# populated child table (e.g. a fresh orders table for today only) doesn't
# fire a false positive.  The warn-not-block design lets the query run.
_THRESHOLD = 0.15

# Rows sampled from each side.  Large enough to detect systematic mismatches;
# small enough that DuckDB resolves the probe in < 100 ms even on cold data.
_SAMPLE_A = 100   # from the join's LHS (the "many" / FK side)
_SAMPLE_B = 1000  # from the join's RHS (the referenced / PK side)

# Limit the number of join pairs probed per query — each probe is one extra
# query execution, so cap at 4 to keep the pre-flight fast.
_MAX_PROBES = 4


def _quote_table(name: str) -> str:
    """Return a safely quoted table reference for DuckDB.

    Handles both plain names ('orders') and schema-qualified names
    ('beauty.orders').  Does not attempt to quote names that already contain
    quotes, to avoid double-quoting caller mistakes.
    """
    if '"' in name:
        return name
    parts = name.split(".")
    return ".".join(f'"{p}"' for p in parts)


def _extract_join_conditions(sql: str) -> list[tuple[str, str, str, str]]:
    """Return (table_a, col_a, table_b, col_b) for each explicit JOIN … ON eq."""
    try:
        import sqlglot
        import sqlglot.expressions as exp

        tree = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)

        # Build alias → real-table-name map.
        alias_map: dict[str, str] = {}
        for tbl in tree.find_all(exp.Table):
            real = tbl.name or ""
            if tbl.db:
                real = f"{tbl.db}.{tbl.name}"
            alias = tbl.alias or real
            if alias:
                alias_map[alias.lower()] = real

        conditions: list[tuple[str, str, str, str]] = []
        for join in tree.find_all(exp.Join):
            on = join.args.get("on")
            if not on:
                continue
            for eq in on.find_all(exp.EQ):
                left, right = eq.left, eq.right
                if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                    continue
                raw_ta = (left.table or "").lower()
                raw_tb = (right.table or "").lower()
                if not raw_ta or not raw_tb:
                    continue
                t_a = alias_map.get(raw_ta, raw_ta)
                t_b = alias_map.get(raw_tb, raw_tb)
                c_a = left.name or ""
                c_b = right.name or ""
                if t_a and c_a and t_b and c_b and t_a != t_b:
                    conditions.append((t_a, c_a, t_b, c_b))
        return conditions
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: SQL parse failed — no conditions extracted",
                 counter="join_guard.parse_error")
        return []


def _probe_overlap(
    conn: "DatabaseConnection",
    table_a: str,
    col_a: str,
    table_b: str,
    col_b: str,
) -> float | None:
    """Fraction of sampled values from table_a.col_a found in table_b.col_b.

    Returns None on any failure (fail-open).
    """
    try:
        ta = _quote_table(table_a)
        tb = _quote_table(table_b)
        qa = f'"{col_a}"'
        qb = f'"{col_b}"'

        probe_sql = f"""
WITH s_a AS (
    SELECT DISTINCT CAST({qa} AS VARCHAR) AS v
    FROM {ta}
    USING SAMPLE {_SAMPLE_A} ROWS
),
s_b AS (
    SELECT DISTINCT CAST({qb} AS VARCHAR) AS v
    FROM {tb}
    USING SAMPLE {_SAMPLE_B} ROWS
)
SELECT
    (SELECT COUNT(*) FROM s_a) AS total,
    (SELECT COUNT(*) FROM s_a WHERE v IN (SELECT v FROM s_b)) AS matched
""".strip()

        result = conn.execute("__domain_probe__", probe_sql)
        if result and result.rows:
            # The connection stringifies all result values (no dtype passthrough),
            # so coerce to int before any numeric comparison.
            total = int(result.rows[0][0])
            matched = int(result.rows[0][1])
            if total > 0:
                return matched / total
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: value-domain probe failed — join allowed to proceed",
                 counter="join_guard.probe_error")
    return None


@dataclass
class JoinDomainWarning:
    table_a: str
    col_a: str
    table_b: str
    col_b: str
    overlap: float

    def to_prompt_text(self) -> str:
        pct = f"{self.overlap:.0%}"
        return (
            f"JOIN VALUE-DOMAIN MISMATCH: {self.table_a}.{self.col_a} ↔ "
            f"{self.table_b}.{self.col_b} — only {pct} of sampled values match. "
            f"These columns likely belong to different entities. "
            f"Verify you are joining on the correct column pair."
        )


def check_join_value_domains(
    conn: "DatabaseConnection",
    sql: str,
    threshold: float = _THRESHOLD,
) -> list[JoinDomainWarning]:
    """Check each explicit JOIN condition for value-domain overlap.

    Returns a (possibly empty) list of warnings.  Never raises — entirely
    fail-open so the calling query path is never blocked by the guard.
    """
    warnings: list[JoinDomainWarning] = []
    try:
        conditions = _extract_join_conditions(sql)
        for t_a, c_a, t_b, c_b in conditions[:_MAX_PROBES]:
            overlap = _probe_overlap(conn, t_a, c_a, t_b, c_b)
            if overlap is not None and overlap < threshold:
                warnings.append(JoinDomainWarning(t_a, c_a, t_b, c_b, overlap))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: domain check failed — no warnings emitted",
                 counter="join_guard.check_error")
    return warnings
