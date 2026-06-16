"""Temporal Tier 3 — query cost governor.

So intelligence builds "without breaking sweat" against TB-scale warehouses. Two safe,
high-value levers (no per-aggregate result-scaling pitfalls):

  • approximate_aggregates — COUNT(DISTINCT x) → approx_count_distinct(x), median/quantile
    → approx_quantile. The explorer leans heavily on high-cardinality distinct counts for
    cardinality/cross-table profiling; the HLL estimate is ~1-3% off for orders-of-magnitude
    less work. Dialect-gated (DuckDB today; a no-op where unsupported).
  • sample_aggregates — for a huge single-table scan, add USING SAMPLE p% and scale the
    additive aggregates (COUNT/SUM) by 100/p. Bounds the bytes scanned; flagged approximate.

Both are conservative: any parse/shape issue → the original SQL is returned unchanged. A
companion watermark (aughor/explorer/watermark.py) handles the incremental-delta lever.
See docs/ADAPTIVE_TEMPORAL_SCOPE.md §6.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Dialects with native HLL approx-distinct + approx-quantile.
_APPROX_DIALECTS = {"duckdb"}


@dataclass
class GovernResult:
    sql: str
    approximated: bool = False   # COUNT(DISTINCT)→approx etc.
    sampled: bool = False        # USING SAMPLE p% applied
    note: str = ""               # human-facing provenance ("≈ from a 10% sample")

    @property
    def is_approximate(self) -> bool:
        return self.approximated or self.sampled


def approximate_aggregates(sql: str, dialect: str = "duckdb") -> str:
    """Rewrite exact, expensive aggregates to their HLL/approx equivalents. No-op on an
    unsupported dialect or any parse failure (returns the input unchanged)."""
    if not sql or dialect not in _APPROX_DIALECTS:
        return sql
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql

    changed = False
    for count in list(tree.find_all(exp.Count)):
        inner = count.this
        if isinstance(inner, exp.Distinct) and inner.expressions:
            col = inner.expressions[0]
            count.replace(exp.func("approx_count_distinct", col))
            changed = True
    # MEDIAN(x) / QUANTILE-style → approx_quantile
    for med in list(tree.find_all(getattr(exp, "Median", ()))) if hasattr(exp, "Median") else []:
        arg = med.this
        med.replace(exp.func("approx_quantile", arg, exp.Literal.number(0.5)))
        changed = True

    if not changed:
        return sql
    try:
        return tree.sql(dialect=dialect)
    except Exception:
        return sql


def has_count_ratio(sql: str, dialect: str = "duckdb") -> bool:
    """True when the query divides a COUNT (i.e. computes a rate/ratio/share).

    HLL approximation is ~1-3% off PER count — acceptable for a magnitude, but for a
    ratio of two close counts that error flips rankings (a conversion 'leader' that's
    actually 4th in a dead heat). So callers skip approximation when this is True and
    keep the ratio exact. Parse failure → False (caller proceeds as before)."""
    if not sql:
        return False
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return False
    for div in tree.find_all(exp.Div):
        if list(div.find_all(exp.Count)):
            return True
    return False


def _single_table(tree, exp) -> bool:
    return len(list(tree.find_all(exp.Table))) == 1 and not list(tree.find_all(exp.Join))


def sample_aggregates(sql: str, dialect: str = "duckdb", pct: float = 10.0) -> Optional[str]:
    """For a single-table aggregate scan, sample p% of rows and scale additive aggregates
    (COUNT/SUM) by 100/p. Returns the rewritten SQL, or None when it isn't safe to sample
    (joins, multiple tables, non-DuckDB, parse failure). MIN/MAX/AVG/approx_* are left as-is."""
    if not sql or dialect not in _APPROX_DIALECTS or not (0 < pct < 100):
        return None
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if not _single_table(tree, exp):
        return None

    # Distinct counts don't scale under row sampling (and approx_count_distinct on a sample
    # undercounts), so a query carrying one cannot be sampled — fall back to full-scan approx.
    if "approx_count_distinct" in sql.lower():
        return None
    if any(isinstance(c.this, exp.Distinct) for c in tree.find_all(exp.Count)):
        return None

    select = tree.find(exp.Select)
    if select is None:
        return None
    scale = 100.0 / pct

    def _scale(node):
        # COUNT(...) and SUM(...) are additive under uniform sampling → multiply by 1/p.
        if isinstance(node, (exp.Count, exp.Sum)):
            if isinstance(getattr(node, "this", None), exp.Distinct):
                return  # never scale a DISTINCT count by sampling — wrong
            mult = exp.Mul(this=node.copy(), expression=exp.Literal.number(scale))
            node.replace(mult)

    scaled_any = False
    for proj in list(select.expressions):
        target = proj.this if isinstance(proj, exp.Alias) else proj
        for agg in list(target.find_all(exp.Count, exp.Sum)):
            before = agg.sql()
            _scale(agg)
            scaled_any = scaled_any or True

    # add the sample clause to the single table
    tbl = next(tree.find_all(exp.Table))
    try:
        tbl.set("sample", exp.TableSample(
            method=exp.var("SYSTEM"),
            percent=exp.Literal.number(pct),
        ))
    except Exception:
        return None

    try:
        out = tree.sql(dialect=dialect)
        sqlglot.parse_one(out, read=dialect)  # validate
        return out
    except Exception:
        return None


def govern(sql: str, *, dialect: str = "duckdb", row_count: Optional[int] = None,
           approx: bool = True, sample_threshold: int = 5_000_000,
           sample_pct: float = 10.0, allow_sampling: bool = False) -> GovernResult:
    """Apply the cost governor to an exploration query.

    approx (default on) swaps exact distinct/quantile for HLL/approx — safe + cheap.
    Sampling is opt-in (allow_sampling) and only kicks in for a single-table scan over a
    table at/above sample_threshold rows; it's flagged approximate via the returned note.
    """
    out = sql
    approximated = sampled = False
    notes: list = []

    if approx:
        new = approximate_aggregates(out, dialect)
        if new != out:
            out = new
            approximated = True
            notes.append("distinct/quantile via HLL approximation")

    if allow_sampling and row_count is not None and row_count >= sample_threshold:
        s = sample_aggregates(out, dialect, sample_pct)
        if s is not None:
            out = s
            sampled = True
            notes.append(f"≈ from a {sample_pct:g}% sample of {row_count:,} rows")

    return GovernResult(sql=out, approximated=approximated, sampled=sampled,
                        note="; ".join(notes))
