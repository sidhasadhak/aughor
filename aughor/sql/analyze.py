"""Shared SQL-analysis facade — one place that turns SQL into semantic facts.

sqlglot is already a load-bearing core dependency (fanout.py / lint.py /
measure_grain.py parse on the AST), but several trust-critical checks still
string-munge the SQL (`ontology/validator.py` product-of-aggregates regex,
`investigations._extract_tables`, `sql_consistency`, …) — each fragile in its own
way. `analyze(sql)` parses ONCE and exposes the reusable semantic facts so those
consumers share one rigorous extraction instead of N regexes.

Layer 2 of the three-layer framing (text→AST is solved by sqlglot; chips
reverse-compile is the genuinely hard layer and stays out of scope). Pure static
analysis; `analyze()` never raises — an unparseable string yields `SqlFacts(ok=False)`
with empty facts, so callers degrade to "no constraint" exactly as the regexes did.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Aggregate:
    """One aggregate-function call found in the query."""
    func: str          # 'sum' | 'count' | 'avg' | 'min' | 'max' | lowercased other
    arg_sql: str       # the argument as SQL text, e.g. 'price * quantity', '*', 'x'
    is_distinct: bool  # AGG(DISTINCT …)
    is_windowed: bool  # part of an OVER(…) window (doesn't collapse rows)


@dataclass
class SqlFacts:
    dialect: str
    ok: bool                                   # parsed successfully
    tables: set[str] = field(default_factory=set)       # base tables (bare, lowercased), CTE refs excluded
    ctes: set[str] = field(default_factory=set)         # CTE names defined in the query
    columns: set[str] = field(default_factory=set)      # referenced column names (bare, lowercased)
    aggregates: list[Aggregate] = field(default_factory=list)
    group_by: set[str] = field(default_factory=set)     # GROUP BY expressions (sql text)
    product_of_aggregates: bool = False        # AGG(…) * AGG(…) — the double-count anti-pattern

    @property
    def has_aggregate(self) -> bool:
        return bool(self.aggregates)


def analyze(sql: str | None, dialect: str = "duckdb") -> SqlFacts:
    """Parse `sql` once and return its semantic facts. Never raises: an
    unparseable/empty string returns SqlFacts(ok=False) with empty facts."""
    if not sql or not str(sql).strip():
        return SqlFacts(dialect=dialect, ok=False)
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return SqlFacts(dialect=dialect, ok=False)
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        tree = None
    if tree is None:
        return SqlFacts(dialect=dialect, ok=False)

    facts = SqlFacts(dialect=dialect, ok=True)

    # CTE names — referencing one of these is NOT a base table.
    facts.ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE) if c.alias_or_name}

    # Base tables (exclude CTE references; a pre-aggregated CTE is not the raw grain).
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if name and name not in facts.ctes:
            facts.tables.add(name)

    # Referenced columns (bare names).
    for col in tree.find_all(exp.Column):
        if col.name:
            facts.columns.add(col.name.lower())

    # GROUP BY expressions.
    for grp in tree.find_all(exp.Group):
        for e in grp.expressions:
            facts.group_by.add(e.sql(dialect=dialect))

    # Aggregate calls (Sum/Count/Avg/Min/Max + any AggFunc subclass).
    for agg in tree.find_all(exp.AggFunc):
        inner = agg.this
        is_distinct = isinstance(inner, exp.Distinct)
        arg = inner.expressions[0] if (is_distinct and inner.expressions) else inner
        if arg is None:
            arg_sql = "*"
        elif isinstance(arg, exp.Star):
            arg_sql = "*"
        else:
            arg_sql = arg.sql(dialect=dialect)
        facts.aggregates.append(Aggregate(
            func=agg.key.lower(),
            arg_sql=arg_sql,
            is_distinct=is_distinct,
            is_windowed=isinstance(agg.parent, exp.Window),
        ))

    facts.product_of_aggregates = _has_product_of_aggregates(tree, exp)
    return facts


def _has_product_of_aggregates(tree, exp) -> bool:
    """A multiplication whose BOTH operands contain an aggregate — `SUM(a)*SUM(b)`,
    `SUM(COALESCE(a,0))*AVG(b)`, etc. — the $3T double-count anti-pattern. Crucially
    NOT `SUM(a*b)` (the Mul is INSIDE the aggregate, so it has an AggFunc ancestor),
    and NOT `2*SUM(x)` or `SUM(x)*qty` (only one operand is an aggregate). This is
    the AST replacement for the `AGG(...)\\s*\\*\\s*AGG(` regex, which silently
    misses any nested-paren argument like `SUM(COALESCE(price,0))*SUM(qty)`."""
    for mul in tree.find_all(exp.Mul):
        # `SUM(a * b)` — the multiply is the aggregate's argument, which is correct.
        if mul.find_ancestor(exp.AggFunc) is not None:
            continue
        left, right = mul.left, mul.right
        if left is None or right is None:
            continue
        if left.find(exp.AggFunc) is not None and right.find(exp.AggFunc) is not None:
            return True
    return False
