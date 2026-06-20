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

        # Containment, not sample-vs-sample: take a small DISTINCT sample of the LHS
        # (FK side) and check each value against the FULL RHS column. Sampling BOTH
        # sides was the original bug — for a high-cardinality key (millions of distinct
        # order_id), two independent samples almost never intersect, so a perfectly
        # valid FK reported ~0% overlap and got flagged as fabricated. Checking the
        # sampled LHS values against the entire RHS gives the true containment fraction
        # (real FK → ~1.0; a bogus join like touchpoint_type=channel → 0.0).
        probe_sql = f"""
WITH s_a AS (
    SELECT DISTINCT CAST({qa} AS VARCHAR) AS v
    FROM {ta}
    USING SAMPLE {_SAMPLE_A} ROWS
)
SELECT
    (SELECT COUNT(*) FROM s_a) AS total,
    (SELECT COUNT(*) FROM s_a WHERE v IN (SELECT CAST({qb} AS VARCHAR) FROM {tb})) AS matched
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
            # Direction-aware containment: a real FK is contained in ONE direction
            # (child ⊆ parent), even when the parent has many keys the child lacks. The
            # single-direction check false-flagged a legitimate parent⋈child subset join
            # (orders ⋈ refunds: only ~10% of orders are refunded, so orders→refunds reads
            # 10%, but refunds→orders is ~100%). Probe BOTH ways and take the MAX — a truly
            # fabricated join (different entities, e.g. touchpoint_type = channel) is low
            # BOTH ways and still flags; a subset FK is high one way and passes.
            ov_ab = _probe_overlap(conn, t_a, c_a, t_b, c_b)
            ov_ba = _probe_overlap(conn, t_b, c_b, t_a, c_a)
            overlaps = [o for o in (ov_ab, ov_ba) if o is not None]
            if overlaps and max(overlaps) < threshold:
                warnings.append(JoinDomainWarning(t_a, c_a, t_b, c_b, max(overlaps)))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "join_guard: domain check failed — no warnings emitted",
                 counter="join_guard.check_error")
    return warnings


# ── WHERE/HAVING literal value-domain guard ─────────────────────────────────
# The join guard protects join KEYS; this protects FILTER LITERALS. A model that
# guesses an enum value — `order_status = 'cancelled'` when the data holds
# 'canceled' — produces a query that runs clean but silently matches ZERO rows, so
# every cancellation rate reads 0%. The fix probes the column's actual domain and,
# only when the column is enumerable (few distinct values) AND the guessed literal
# is absent BUT a close real value exists, flags it with the correct value. The
# close-match requirement keeps it high-precision: a genuinely-valid-but-empty
# filter (e.g. status='refunded' with no refunds yet) has no near neighbour and is
# left alone.
_FILTER_MAX_PROBES = 6
_ENUMERABLE_MAX_DISTINCT = 50


@dataclass
class FilterDomainWarning:
    table: str
    col: str
    bad_value: str
    valid_values: list[str]
    suggestion: str | None

    def to_prompt_text(self) -> str:
        vals = ", ".join(repr(v) for v in self.valid_values[:12])
        sugg = f" Did you mean '{self.suggestion}'?" if self.suggestion else ""
        return (
            f"FILTER VALUE MISMATCH: {self.table}.{self.col} = '{self.bad_value}' matches NO rows — "
            f"that exact value is not in the column.{sugg} The column's actual values are: {vals}. "
            f"Rewrite the predicate using an EXACT value from that list."
        )


def _extract_filter_literals(sql: str) -> list[tuple[str, str, str]]:
    """(table, col, literal) for `col = 'lit'` / `col IN ('a', …)` predicates that are
    NOT inside a JOIN … ON (those are the join guard's job). Unqualified columns resolve
    only when the query has exactly one base table — otherwise the column is ambiguous
    and skipped (fail-safe)."""
    out: list[tuple[str, str, str]] = []
    try:
        import sqlglot
        import sqlglot.expressions as exp
        tree = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception:
        return out
    alias_map: dict[str, str] = {}
    base_tables: list[str] = []
    for tbl in tree.find_all(exp.Table):
        real = f"{tbl.db}.{tbl.name}" if tbl.db else (tbl.name or "")
        alias = tbl.alias or real
        if alias:
            alias_map[alias.lower()] = real
        if real:
            base_tables.append(real)
    distinct_bases = set(base_tables)
    on_node_ids: set[int] = set()
    for j in tree.find_all(exp.Join):
        on = j.args.get("on")
        if on is not None:
            for node in on.walk():
                on_node_ids.add(id(node))

    def _resolve(colnode) -> str | None:
        raw_t = (colnode.table or "").lower()
        if raw_t:
            return alias_map.get(raw_t, raw_t)
        return next(iter(distinct_bases)) if len(distinct_bases) == 1 else None

    for eq in tree.find_all(exp.EQ):
        if id(eq) in on_node_ids:
            continue
        col = lit = None
        if isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Literal) and eq.right.is_string:
            col, lit = eq.left, eq.right
        elif isinstance(eq.right, exp.Column) and isinstance(eq.left, exp.Literal) and eq.left.is_string:
            col, lit = eq.right, eq.left
        if col is not None:
            t = _resolve(col)
            if t and col.name:
                out.append((t, col.name, lit.this))
    for inn in tree.find_all(exp.In):
        if id(inn) in on_node_ids:
            continue
        col = inn.this
        if isinstance(col, exp.Column):
            t = _resolve(col)
            if t and col.name:
                for e in inn.expressions:
                    if isinstance(e, exp.Literal) and e.is_string:
                        out.append((t, col.name, e.this))
    return out


def check_filter_value_domains(conn: "DatabaseConnection", sql: str) -> list[FilterDomainWarning]:
    """Flag WHERE/HAVING equality/IN literals that don't exist in an enumerable column's
    actual value domain (a guessed enum value). Fail-open; never raises."""
    import difflib
    from collections import defaultdict
    warnings: list[FilterDomainWarning] = []
    try:
        by_col: dict[tuple[str, str], set[str]] = defaultdict(set)
        for t, c, lit in _extract_filter_literals(sql):
            by_col[(t, c)].add(lit)
        for (t, c), lits in list(by_col.items())[:_FILTER_MAX_PROBES]:
            try:
                qt, qc = _quote_table(t), f'"{c}"'
                res = conn.execute(
                    "__filter_domain_probe__",
                    f"SELECT DISTINCT CAST({qc} AS VARCHAR) AS v FROM {qt} "
                    f"WHERE {qc} IS NOT NULL LIMIT {_ENUMERABLE_MAX_DISTINCT + 1}",
                )
                if not res or not res.rows:
                    continue
                vals = [r[0] for r in res.rows if r and r[0] is not None]
                if not vals or len(vals) > _ENUMERABLE_MAX_DISTINCT:
                    continue  # high-cardinality column — do not second-guess the literal
                present = {v.lower() for v in vals}
                for lit in lits:
                    if lit.lower() in present:
                        continue
                    close = difflib.get_close_matches(lit, vals, n=1, cutoff=0.6)
                    if close:  # only flag an obvious typo/variant, never a novel value
                        warnings.append(FilterDomainWarning(t, c, lit, vals, close[0]))
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "filter_guard: value-domain probe failed — query allowed to proceed",
                         counter="filter_guard.probe_error")
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "filter_guard: check failed — no warnings emitted",
                 counter="filter_guard.check_error")
    return warnings
