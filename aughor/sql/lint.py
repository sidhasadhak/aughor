"""SQL linter — programmatic guards against known anti-patterns.

Runs after LLM generation, BEFORE execution.  Returns a list of LintIssue.
Callers can treat "error" severity as a hard block (trigger a targeted rewrite)
and "warning" as a soft signal (log / surface to the user).

Why this exists
---------------
Prompt rules are advisory — the LLM can ignore them.  Code-based checks are
enforced.  This module catches the patterns that keep recurring regardless of
how many times we add them to prompts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import sqlglot
import sqlglot.expressions as exp


# ── Issue type ────────────────────────────────────────────────────────────────

@dataclass
class LintIssue:
    severity: Literal["error", "warning"]
    rule: str
    message: str
    hint: str   # injected verbatim into the fix prompt


# ── Helpers ───────────────────────────────────────────────────────────────────

_AGG_TYPES = (exp.Sum, exp.Count, exp.Avg, exp.Max, exp.Min)


def _has_agg(node: exp.Expression) -> bool:
    return bool(next(node.find_all(*_AGG_TYPES), None))


# ── Rules ─────────────────────────────────────────────────────────────────────

def _check_ratio_avg(tree: exp.Expression) -> list[LintIssue]:
    """AVG(col/col) — per-row average of ratios is NOT a ratio of aggregates."""
    issues: list[LintIssue] = []
    for avg_node in tree.find_all(exp.Avg):
        inner = avg_node.this
        if isinstance(inner, (exp.Div, exp.Mul)):
            issues.append(LintIssue(
                severity="error",
                rule="RATIO_AVG",
                message=(
                    f"AVG({inner.sql()}) computes the mean of per-row ratios — "
                    "statistically wrong for ratio-of-aggregates questions. "
                    "A single outlier row (e.g. price=$0.01, freight=$5) inflates the result."
                ),
                hint=(
                    f"Replace AVG({inner.sql()}) with "
                    f"ROUND(SUM(numerator)/NULLIF(SUM(denominator),0),2). "
                    "Example: AVG(freight_value/price) → "
                    "ROUND(SUM(freight_value)/NULLIF(SUM(price),0),2)"
                ),
            ))
    return issues


def _check_div_nullif(tree: exp.Expression) -> list[LintIssue]:
    """Aggregate / aggregate without NULLIF — division-by-zero risk."""
    issues: list[LintIssue] = []
    seen: set[str] = set()
    for div_node in tree.find_all(exp.Div):
        left  = div_node.this
        right = div_node.expression
        if not (_has_agg(left) and _has_agg(right)):
            continue
        if isinstance(right, exp.Nullif):
            continue   # already protected
        key = div_node.sql()
        if key in seen:
            continue
        seen.add(key)
        issues.append(LintIssue(
            severity="error",
            rule="DIV_NO_NULLIF",
            message=(
                f"Division '{div_node.sql()}' has no NULLIF guard on the denominator — "
                "raises a division-by-zero error when the denominator aggregates to 0."
            ),
            hint=(
                f"Wrap the denominator: "
                f"{left.sql()} / NULLIF({right.sql()}, 0)"
            ),
        ))
    return issues


def _check_not_in_null(sql: str) -> list[LintIssue]:
    """col NOT IN (...) without IS NOT NULL — NULLs silently bypass the filter."""
    issues: list[LintIssue] = []
    for col in re.findall(r'\b(\w+)\s+NOT\s+IN\s*\(', sql, re.IGNORECASE):
        if re.search(rf'\b{re.escape(col)}\s+IS\s+NOT\s+NULL\b', sql, re.IGNORECASE):
            continue
        issues.append(LintIssue(
            severity="warning",
            rule="NOT_IN_NULL",
            message=(
                f"'{col} NOT IN (...)' has no 'AND {col} IS NOT NULL' guard. "
                "NULL values in {col} silently pass the filter (NULL NOT IN (...) evaluates to NULL, not FALSE)."
            ),
            hint=f"Add 'AND {col} IS NOT NULL' alongside the NOT IN clause.",
        ))
    return issues


def _check_limit_no_time_filter(sql: str) -> list[LintIssue]:
    """LIMIT used as a proxy for a time filter — returns an arbitrary slice, not a period."""
    issues: list[LintIssue] = []
    has_limit  = bool(re.search(r'\bLIMIT\s+\d+\b', sql, re.IGNORECASE))
    # Heuristic: if there's a LIMIT but no WHERE/HAVING with a date/time comparison,
    # and the query has a GROUP BY with a date-like column, it's probably wrong.
    has_time_where = bool(re.search(
        r"WHERE\b.*\b(date_trunc|year|month|day|to_date|cast.*timestamp"
        r"|order_purchase_timestamp|created_at|updated_at|event_date)\b",
        sql, re.IGNORECASE | re.DOTALL,
    ))
    has_date_group = bool(re.search(
        r"GROUP\s+BY\b.*\b(date_trunc|month|year|day|week)\b",
        sql, re.IGNORECASE | re.DOTALL,
    ))
    if has_limit and has_date_group and not has_time_where:
        issues.append(LintIssue(
            severity="warning",
            rule="LIMIT_AS_TIME_FILTER",
            message=(
                "Query uses LIMIT on a time-grouped result without a date WHERE clause. "
                "LIMIT returns an arbitrary row cap, not a specific time period."
            ),
            hint=(
                "If the intent is 'show for a single month', add "
                "WHERE month_col = (SELECT MAX(month_col) FROM ...) "
                "and remove LIMIT, or at least keep it only for row-count safety."
            ),
        ))
    return issues


def _check_group_by_ordinal(tree: exp.Expression) -> list[LintIssue]:
    """GROUP BY 1,2,3 is fragile — a reorder of SELECT columns silently breaks it."""
    issues: list[LintIssue] = []
    for gb in tree.find_all(exp.Group):
        for expr in gb.expressions:
            if isinstance(expr, exp.Literal) and expr.is_number:
                issues.append(LintIssue(
                    severity="warning",
                    rule="GROUP_BY_ORDINAL",
                    message=(
                        f"GROUP BY uses positional ordinals ({expr.sql()}) instead of column names. "
                        "Reordering SELECT columns silently produces wrong groupings."
                    ),
                    hint="Replace positional GROUP BY ordinals with explicit column names.",
                ))
                break   # one warning per GROUP BY clause is enough
    return issues


# ── Public API ────────────────────────────────────────────────────────────────

def lint(sql: str, dialect: str = "postgres") -> list[LintIssue]:
    """Run all lint rules against *sql* and return a (possibly empty) list of issues.

    Never raises — parse failures are silently skipped so a lint error never
    blocks query execution.
    """
    issues: list[LintIssue] = []

    # Rules that need raw SQL text
    issues += _check_not_in_null(sql)
    issues += _check_limit_no_time_filter(sql)

    # Rules that need the AST
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return issues   # unparseable SQL — let the DB report the syntax error

    issues += _check_ratio_avg(tree)
    issues += _check_div_nullif(tree)
    issues += _check_group_by_ordinal(tree)

    return issues


def error_hint(issues: list[LintIssue]) -> str:
    """Concatenate hints from error-severity issues into a single fix-prompt hint."""
    return " | ".join(i.hint for i in issues if i.severity == "error")


def has_errors(issues: list[LintIssue]) -> bool:
    return any(i.severity == "error" for i in issues)
