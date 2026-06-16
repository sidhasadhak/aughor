"""Structural query signatures — deterministic near-duplicate detection for findings.

The explorer's Phase-8 loop asks an LLM to propose "the next most valuable question",
relying on its self-reported `novelty` score to avoid repetition. The model is a generous
self-grader: it rates "top countries by customer count" and "customer concentration by
continent" as both novel, so a domain can spend its whole budget emitting the SAME finding
four cosmetically-different ways (different aliases, a ROUND(...)-pct wrapper, COUNT(*) vs
COUNT(DISTINCT pk)). Novelty-decay never triggers because the *scores* stay high.

A query's STRUCTURE is the honest signal the model's self-assessment isn't. Two queries that
read the same tables, group by the same keys, and aggregate the same measures answer the same
question of the same data at the same grain — a structural duplicate, whatever the prose says.
``query_signature`` reduces a query to that fingerprint so the loop can drop the duplicate
deterministically. It is high-precision by design: a different measure (count vs revenue) or a
different grain (by continent vs by continent+country) yields a different signature and is kept.
"""
from __future__ import annotations


def _norm(name: str) -> str:
    """Separator/case-insensitive column key — 'customer_id' and 'customerID' agree."""
    return (name or "").replace("_", "").replace("-", "").replace(" ", "").lower()


def query_signature(sql: str, dialect: str = "duckdb") -> tuple | None:
    """A structural fingerprint: ``(tables, group_keys, measures)`` as frozensets.

    - ``tables``      base (non-CTE) table names the query reads.
    - ``group_keys``  the columns it groups by (the analytical grain).
    - ``measures``    the aggregates it computes, normalised so cosmetic variants agree:
                      every COUNT(...) → ``count``; SUM/AVG/etc. keep their argument column
                      (so SUM(revenue) ≠ SUM(quantity)); aggregates inside a window (OVER)
                      are ignored — those are pct-of-total / ranking wrappers, not the
                      primary measure.

    Two queries with equal signatures ask the same question of the same data at the same
    grain. Returns ``None`` when the SQL doesn't parse (caller treats that as "not a dup")."""
    if not sql:
        return None
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    ctes = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    tables = frozenset(
        ".".join(p for p in (t.catalog, t.db, t.name) if p).lower()
        for t in tree.find_all(exp.Table)
        if (t.name or "").lower() and (t.name or "").lower() not in ctes
    )

    group_keys: set[str] = set()
    for g in tree.find_all(exp.Group):
        for e in g.expressions:
            cols = list(e.find_all(exp.Column))
            if cols:
                group_keys.update(_norm(c.name) for c in cols)
            elif isinstance(e, exp.Column):
                group_keys.add(_norm(e.name))

    measures: set[str] = set()
    for agg in tree.find_all(exp.AggFunc):
        if agg.find_ancestor(exp.Window) is not None:
            continue                                   # pct-of-total / window wrapper, not a measure
        fn = (agg.key or "").lower()
        if fn == "count":
            measures.add("count")                      # COUNT(*) ≡ COUNT(DISTINCT pk) — "how many rows"
        else:
            cols = sorted({_norm(c.name) for c in agg.find_all(exp.Column)})
            measures.add(f"{fn}:{','.join(cols)}")

    return (tables, frozenset(group_keys), frozenset(measures))


def is_structural_duplicate(sql: str, prior_sqls, dialect: str = "duckdb") -> bool:
    """True when `sql` has the same structural signature as any query in `prior_sqls`.
    Fail-safe: an unparseable `sql` is never a duplicate (returns False)."""
    sig = query_signature(sql, dialect)
    if sig is None:
        return False
    for p in prior_sqls or ():
        if query_signature(p, dialect) == sig:
            return True
    return False


def is_redundant_insight(sql: str, prior_sqls, dialect: str = "duckdb") -> bool:
    """Coarser than `is_structural_duplicate`: True when `sql` asks the SAME analytical
    question as a prior one — same group-keys AND same measures AND at least one shared
    table — even if a secondary join/column makes the full signature differ (e.g. a
    "conversion by traffic_source" query that also tacks a refund column + the refunds
    table onto the same grain). That mismatch is exactly what let two DIFFERENT findings
    render as the same briefing chart. Used for CROSS-domain dedup.

    Guards against over-matching: requires non-empty group_keys (only grouped analyses)
    and a shared table — so "orders by status" and "customers by status" (same grain +
    COUNT but disjoint tables) are NOT treated as redundant. Fail-safe: unparseable →
    not redundant."""
    sig = query_signature(sql, dialect)
    if sig is None:
        return False
    tables, gkeys, measures = sig
    if not gkeys:
        return False
    for p in prior_sqls or ():
        psig = query_signature(p, dialect)
        if psig is None:
            continue
        ptables, pg, pm = psig
        if gkeys == pg and measures == pm and (tables & ptables):
            return True
    return False
