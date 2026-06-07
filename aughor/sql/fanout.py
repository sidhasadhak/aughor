"""
M24d — Conservative multi-fact FAN-OUT detector (Cube-style, borrow).

Fan-out (a.k.a. join-amplification / chasm trap) is the platform's #1
model-invariant correctness failure: when a query joins one hub/dimension to TWO
or more satellite ("many"-side) tables and then aggregates over both, the join
multiplies rows and SUM/COUNT over-count. The textbook case from the real-DB eval:
`campaigns JOIN clicks JOIN impressions ... COUNT(clicks), COUNT(impressions)`
→ clicks × impressions per campaign.

Cube prevents this structurally with primary keys + symmetric aggregates. We
borrow the *detection* half here and (separately) trigger a directed pre-aggregate
rewrite. This module is DETECTION ONLY and is deliberately HIGH-PRECISION /
partial-recall: it must NEVER flag a correct query (the semantic_validator
false-positive scar), so every guard below errs toward staying silent.

It flags iff ALL hold in the OUTERMOST query scope:
  1. ≥2 RAW base tables are joined directly (CTE / subquery sources are EXCLUDED —
     pre-aggregating each satellite in its own CTE is the CORRECT fix, so it must
     not trip);
  2. those base tables share a foreign-key ROOT (both carry a column that roots to
     the same FK, i.e. both are on the "many" side of the same hub key; date/time
     surrogate keys are excluded);
  3. there are NON-DISTINCT aggregates (SUM/AVG/COUNT(*) etc.) whose arguments
     reference columns from ≥2 of those shared-root tables. COUNT(DISTINCT …) — the
     fan-out-safe form — does NOT count.

Returns a FanoutFinding or None. Pure static analysis; no DB calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aughor.tools.schema import _fk_root


@dataclass
class FanoutFinding:
    hub_root: str                      # the shared FK root the satellites fan out across
    satellites: list[str]              # base tables aggregated across the fan-out
    aggregates: list[str] = field(default_factory=list)  # offending aggregate exprs (text)

    def to_prompt_text(self) -> str:
        sats = ", ".join(self.satellites)
        return (
            f"FAN-OUT RISK: {sats} are each on the many-side of '{self.hub_root}' and are "
            f"joined directly while both are aggregated — the join multiplies rows and the "
            f"totals over-count. Pre-aggregate EACH of {sats} in its own CTE (group by the "
            f"shared key) and THEN join the CTEs."
        )


def _table_fk_roots(cols: list[str]) -> set[str]:
    """FK roots present on a table's columns (date/time keys already excluded by _fk_root)."""
    roots: set[str] = set()
    for c in cols:
        r = _fk_root(c)
        if r:
            roots.add(r)
    return roots


def detect_fanout(sql: str, table_cols: dict[str, list[str]], dialect: str = "duckdb"):
    """Return a FanoutFinding if the OUTER scope fans out across ≥2 shared-root
    satellites with non-distinct aggregates over both, else None. Best-effort:
    any parse/analysis error returns None (never raise into the pipeline)."""
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.optimizer.scope import build_scope
    except Exception:
        return None

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    try:
        root = build_scope(tree)
    except Exception:
        root = None
    if root is None:
        return None

    # ── 1. RAW base tables in the OUTER scope (exclude CTEs / derived tables) ──
    # root.sources maps alias/name -> Scope (for CTEs/subqueries) or exp.Table.
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    alias_to_table: dict[str, str] = {}   # alias-or-name(lower) -> real base table (lower, bare)
    base_tables: set[str] = set()
    for alias, source in root.sources.items():
        if isinstance(source, exp.Table):
            name = source.name.lower()
            if name in cte_names:
                continue  # a reference to a CTE — pre-aggregated, safe
            bare = name
            alias_to_table[alias.lower()] = bare
            alias_to_table[name] = bare
            base_tables.add(bare)

    if len(base_tables) < 2:
        return None

    # Map each base table to the schema's column list (match on bare/last segment).
    def _schema_cols(bare: str) -> list[str]:
        for t, cols in table_cols.items():
            if t.split(".")[-1].lower() == bare or t.lower() == bare:
                return cols
        return []

    roots_by_table: dict[str, set[str]] = {bt: _table_fk_roots(_schema_cols(bt)) for bt in base_tables}

    # ── 2. shared FK roots among ≥2 base tables ───────────────────────────────
    shared: dict[str, list[str]] = {}
    bts = sorted(base_tables)
    for i in range(len(bts)):
        for j in range(i + 1, len(bts)):
            common = roots_by_table[bts[i]] & roots_by_table[bts[j]]
            for r in common:
                shared.setdefault(r, [])
                for t in (bts[i], bts[j]):
                    if t not in shared[r]:
                        shared[r].append(t)
    if not shared:
        return None

    # ── 3. non-distinct aggregates referencing columns of ≥2 shared-root tables ─
    # Only aggregates in the OUTER scope (root.expression is the outer Select).
    outer = root.expression
    agg_tables: dict[str, list[str]] = {}   # base table -> [agg text]
    for agg in outer.find_all(exp.AggFunc):
        # skip COUNT(DISTINCT …) — the fan-out-safe form
        inner = agg.this
        if isinstance(inner, exp.Distinct):
            continue
        # collect the base tables referenced by this aggregate's column args
        for col in agg.find_all(exp.Column):
            tref = (col.table or "").lower()
            bt = alias_to_table.get(tref)
            if bt:
                agg_tables.setdefault(bt, []).append(agg.sql(dialect=dialect))

    # COUNT(*) and unqualified aggregates carry no table ref — conservatively
    # ignored (we only flag when we can attribute aggregates to ≥2 satellites).
    for r, sats in shared.items():
        aggregated = [t for t in sats if t in agg_tables]
        if len(aggregated) >= 2:
            aggs = sorted({a for t in aggregated for a in agg_tables[t]})
            return FanoutFinding(hub_root=r, satellites=sorted(aggregated), aggregates=aggs[:6])

    return None
