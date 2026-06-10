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

import re
from dataclasses import dataclass, field

from aughor.tools.schema import _fk_root


@dataclass
class FanoutFinding:
    hub_root: str                      # the shared FK root the satellites fan out across
    satellites: list[str]              # base tables aggregated across the fan-out
    aggregates: list[str] = field(default_factory=list)  # offending aggregate exprs (text)
    kind: str = "chasm"                # "chasm" (≥2 satellites) | "parent_fanout" (one-to-many)
    children: list[str] = field(default_factory=list)    # for parent_fanout: the many-side tables

    def to_prompt_text(self) -> str:
        if self.kind == "parent_fanout":
            parent = self.satellites[0] if self.satellites else "the parent table"
            kids = ", ".join(self.children) or "a finer-grained child"
            return (
                f"FAN-OUT RISK: aggregating {parent}'s measure across the join to {kids} "
                f"duplicates {parent} rows (each {parent} row repeats per matching {kids} row), "
                f"so SUM/AVG over-counts. Pre-aggregate {parent} to its own grain — or aggregate "
                f"{kids} in a CTE keyed by '{self.hub_root}' first — then join; never SUM "
                f"{parent}'s measure directly across this join."
            )
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

    # ── Single parent-measure fan-out (the one-to-many case the multi-satellite
    # check above misses): SUM/AVG of a PARENT's measure across a join to a finer-
    # grained child duplicates the parent's rows. Conservative — only when we can
    # confidently name the parent (its singularized table stem == the shared root)
    # and that parent, not the child, carries a non-distinct SUM/AVG.
    def _singular(t: str) -> str:
        return t[:-1] if t.endswith("s") else t

    for r, sats in shared.items():
        parents = [t for t in sats if _singular(t) == r or t == r]
        if len(parents) != 1:
            continue  # can't confidently identify the single parent → stay silent
        parent = parents[0]
        children = [t for t in sats if t != parent]
        if not children:
            continue
        parent_aggs = [a for a in agg_tables.get(parent, []) if re.search(r"\b(?:SUM|AVG)\b", a, re.I)]
        if parent_aggs:
            return FanoutFinding(
                hub_root=r, satellites=[parent], children=sorted(children),
                aggregates=sorted(set(parent_aggs))[:6], kind="parent_fanout",
            )

    return None


def build_parent_fanout_rewrite(sql: str, finding: "FanoutFinding", dialect: str = "duckdb"):
    """Deterministic de-fan for a parent_fanout: wrap the source in a DISTINCT
    subquery keyed by the parent's join column, so the parent's measure is summed
    ONCE per parent instead of once per fanned child row. Exact and filter-
    preserving (verified on TPC-H: $226.8B vs the 5x-inflated $1,134B).

    Returns rewritten SQL, or None when it cannot transform SAFELY — a CHILD-level
    GROUP BY (ambiguous chasm), a non-parent aggregate, a CTE/set-op, COUNT(*), or
    any shape it doesn't fully understand. High-precision: silence over a guess.
    The caller MUST still execute the rewrite and accept it only if it runs clean
    and yields a value ≤ the original (dedup can only remove duplicated rows)."""
    if finding is None or finding.kind != "parent_fanout" or not finding.satellites:
        return None
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None

    parent = finding.satellites[0]
    children = set(finding.children)
    try:
        sel = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if not isinstance(sel, exp.Select) or sel.args.get("with"):
        return None  # only a single flat SELECT (detect_fanout already excludes CTE sources)

    alias_to_table = {(t.alias_or_name or "").lower(): t.name.lower() for t in sel.find_all(exp.Table)}
    parent_aliases = {a for a, tn in alias_to_table.items() if tn == parent}
    if not parent_aliases:
        return None

    # Parent join key — the parent-side column of an ON-equality to a child table.
    parent_key = None
    for j in (sel.args.get("joins") or []):
        on = j.args.get("on")
        if not on:
            continue
        for eq in on.find_all(exp.EQ):
            for side, other in ((eq.left, eq.right), (eq.right, eq.left)):
                if (isinstance(side, exp.Column) and (side.table or "").lower() in parent_aliases
                        and isinstance(other, exp.Column)
                        and alias_to_table.get((other.table or "").lower()) in children):
                    parent_key = side
    if parent_key is None:
        return None

    # GROUP BY must be parent-level (a child dimension makes the parent measure ambiguous).
    group_cols = []
    grp = sel.args.get("group")
    if grp:
        for g in grp.expressions:
            if not isinstance(g, exp.Column) or (g.table or "").lower() not in parent_aliases:
                return None
            group_cols.append(g)

    inner_proj = [exp.alias_(parent_key.copy(), "_fk_pk")]
    outer_proj = []
    measure_alias: dict[str, str] = {}
    mi = 0
    for e in sel.expressions:
        body = e.this if isinstance(e, exp.Alias) else e
        out_alias = e.alias if isinstance(e, exp.Alias) else None
        if isinstance(body, exp.Column):
            if (body.table or "").lower() not in parent_aliases:
                return None
            inner_proj.append(body.copy())
            col = exp.column(body.name)
            outer_proj.append(exp.alias_(col, out_alias) if out_alias else col)
        elif isinstance(body, (exp.Sum, exp.Avg)):
            inner = body.this
            if not isinstance(inner, exp.Column) or (inner.table or "").lower() not in parent_aliases:
                return None
            key = inner.sql(dialect=dialect)
            if key not in measure_alias:
                measure_alias[key] = f"_m{mi}"
                mi += 1
                inner_proj.append(exp.alias_(inner.copy(), measure_alias[key]))
            new_agg = type(body)(this=exp.column(measure_alias[key]))
            # Preserve a stable output column name (downstream grounding/charts key
            # on it): the explicit alias, else "<func>_<measurecol>".
            out_name = out_alias or f"{body.key.lower()}_{inner.name}"
            outer_proj.append(exp.alias_(new_agg, out_name))
        else:
            return None  # COUNT(*), expressions, non-parent aggs → bail

    # Inner = clone of the original (keeps FROM/JOIN/WHERE verbatim), re-projected to
    # DISTINCT(key, dims, measures) with the aggregation/group/order stripped.
    inner = sel.copy()
    inner.set("expressions", inner_proj)
    for k in ("group", "having", "order", "limit", "qualify", "offset"):
        inner.set(k, None)
    inner.set("distinct", exp.Distinct())

    try:
        subq = exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier("_dedup")))
        outer = exp.Select(expressions=outer_proj).from_(subq)
        if group_cols:
            outer = outer.group_by(*[exp.column(g.name) for g in group_cols])
        return outer.sql(dialect=dialect)
    except Exception:
        return None
