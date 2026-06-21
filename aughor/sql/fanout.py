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


def _fk_col_for_root(cols: list[str], root: str) -> str | None:
    """The column on a table that roots to `root` (e.g. root 'order' → 'order_id') —
    i.e. the key this table joins to the hub on. Used to ask a cardinality oracle
    whether the table is 1:1 on that key."""
    for c in cols:
        if _fk_root(c) == root:
            return c
    return None


def _singular(t: str) -> str:
    """Crude singular stem of a table name — used to tell the hub (stem == FK root)
    from its satellites (many-side tables that merely carry the hub's FK)."""
    return t[:-1] if t.endswith("s") else t


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


# ── Two grain bugs detect_fanout deliberately does NOT cover (it ignores COUNT(*)
# and needs ≥2 satellites / a SUM-AVG parent measure). Both produced confidently-
# narrated WRONG numbers in the explorer: integer division gave avg_items_per_order=1.0
# ("all orders 3 items"); a single-join COUNT(*) gave "2000 products" (25 × 80 items). ──

_AGG_DIV = re.compile(r"\b(?:count|sum)\s*\([^)]*\)\s*/\s*(?:(?:count|sum)\s*\(|\d)", re.I)
_FLOAT_COERCED = re.compile(
    r"::\s*(?:float|double|real|decimal|numeric)"
    r"|cast\s*\([^)]*\bas\s+(?:float|double|real|decimal|numeric)"
    r"|\b1\.0\b|\b100\.0\b|\b1000\.0\b",
    re.I,
)


def integer_division_risk(sql: str) -> str | None:
    """A non-distinct aggregate divided by another aggregate (or an int) with no float
    coercion: DuckDB integer division TRUNCATES the ratio — this produced the
    ``avg_items_per_order=1.0`` / "all orders had exactly 3 items" bug. High-precision:
    a genuine average uses AVG() or a float cast / ×1.0, so this only fires on
    COUNT/SUM ÷ COUNT/SUM/int with none of those present."""
    s = sql or ""
    if _AGG_DIV.search(s) and not _FLOAT_COERCED.search(s):
        return ("integer division of aggregates truncates the ratio — use AVG(), a FLOAT "
                "cast, or multiply the numerator by 1.0")
    return None


_COUNT_STAR_AS = re.compile(r"count\s*\(\s*\*\s*\)\s+as\s+([a-z_][a-z0-9_]*)", re.I)
_FROM_JOIN_TBL = re.compile(r"(?:from|join)\s+([a-z_][a-z0-9_.]*)", re.I)


def count_star_entity_fanout(sql: str, table_cols: dict | None = None) -> str | None:
    """``COUNT(*) AS <entity>_count`` where ``<entity>`` is the PARENT side of a join
    counts JOINED (child) rows, not distinct entities — the "2000 products" bug (25
    products × 80 order_items). The fan-out-safe form is ``COUNT(DISTINCT <entity>_id)``.

    High-precision via FK DIRECTION: only flags when another table in the query holds
    ``<entity>_id`` (i.e. <entity> is the referenced parent). So ``COUNT(*) AS order_count
    FROM orders JOIN customers`` is NOT flagged (orders is the many-side; nothing in the
    query references order_id), but ``COUNT(*) AS product_count FROM products JOIN
    order_items`` IS (order_items.product_id makes products the parent)."""
    s = sql or ""
    if " join " not in s.lower():
        return None
    # tables actually referenced in this query (base names)
    q_tables = {t.split(".")[-1].lower() for t in _FROM_JOIN_TBL.findall(s)}
    if not q_tables:
        return None
    tc = {str(t).split(".")[-1].lower(): {str(c).lower() for c in (cols or [])}
          for t, cols in (table_cols or {}).items()}
    for m in _COUNT_STAR_AS.finditer(s):
        alias = m.group(1).lower()
        stem = re.sub(r"^(?:num|n|total)_", "", re.sub(r"_(?:count|cnt)$", "", alias))
        singular = stem[:-1] if stem.endswith("s") else stem
        if not singular:
            continue
        fk = f"{singular}_id"
        # is <singular> a parent? another query table (not itself) holds <singular>_id
        for tname in q_tables:
            tbase = tname[:-1] if tname.endswith("s") else tname
            if tbase == singular:
                continue
            if fk in tc.get(tname, set()):
                return (f"COUNT(*) AS {m.group(1)} over a JOIN counts joined rows, not "
                        f"distinct {singular} — {tname}.{fk} makes {singular} the parent; "
                        f"use COUNT(DISTINCT {fk})")
    return None


def _chasm_roots(tree, root, table_cols: dict | None, is_unique_on=None) -> dict[str, set[str]]:
    """Hubs that have ≥2 RAW base-table satellites joined directly in the OUTER
    scope — i.e. a chasm. Returns {hub_fk_root: {satellite tables}} with ≥2 sats
    each, or {} when there's no chasm. Shared by the COUNT(*) and AVG chasm
    linters so they detect the SAME structure identically. CTE/subquery sources
    are excluded (pre-aggregating in a CTE is the fix).

    `is_unique_on(table_bare, key_col) -> bool | None` is an optional cardinality
    oracle. A "satellite" that is UNIQUE (1:1) on the hub key is a DIMENSION, not a
    fan-out source — it attaches exactly one row and multiplies nothing — so it is
    excluded from the satellite set. This removes the canonical false positive where
    a fact (e.g. `attribution`, many-per-order) is joined to a 1:1 table (e.g.
    `invoices`, one-per-order): without cardinality the two look like a chasm, but
    `SUM(measure × weight)` / `COUNT(*)` over that join does NOT over-count. When the
    oracle is absent or returns None (unknown), behaviour is unchanged — conservative,
    still flags — so this is purely additive precision, never new false negatives on
    the genuine ≥2-fact chasm."""
    from sqlglot import exp
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    base_tables: set[str] = set()
    for _alias, source in root.sources.items():
        if isinstance(source, exp.Table):
            name = source.name.lower()
            if name not in cte_names:
                base_tables.add(name)
    if len(base_tables) < 2:
        return {}

    def _schema_cols(bare: str) -> list[str]:
        for t, cols in (table_cols or {}).items():
            if str(t).split(".")[-1].lower() == bare or str(t).lower() == bare:
                return cols
        return []

    # Satellites of a hub = base tables that carry the hub's FK root but are NOT
    # the hub itself (the hub's singular stem equals the root).
    roots_by_table = {bt: _table_fk_roots(_schema_cols(bt)) for bt in base_tables}
    sat_by_root: dict[str, set[str]] = {}
    for bt in base_tables:
        for r in roots_by_table[bt]:
            if _singular(bt) != r and bt != r:   # bt is a satellite of hub r, not the hub
                # Cardinality-aware demotion: a table that is 1:1 on the hub key is a
                # dimension, not a fan-out satellite — it can't multiply rows.
                if is_unique_on is not None:
                    key_col = _fk_col_for_root(_schema_cols(bt), r)
                    if key_col and is_unique_on(bt, key_col) is True:
                        continue
                sat_by_root.setdefault(r, set()).add(bt)
    return {r: sats for r, sats in sat_by_root.items() if len(sats) >= 2}


def count_star_chasm_fanout(sql: str, table_cols: dict | None = None, dialect: str = "duckdb",
                            is_unique_on=None) -> str | None:
    """``COUNT(*)`` over a CHASM — ≥2 base tables on the many-side of the SAME hub key
    joined directly — counts the cross-product of the satellites, not either entity.
    The textbook case `campaigns JOIN clicks JOIN impressions ... COUNT(*)` returns
    clicks×impressions per campaign.

    detect_fanout deliberately ignores COUNT(*) (it has no column to attribute to a
    satellite) and defan() can't rewrite it (COUNT(*) of a cross-product has no single
    correct meaning) — so this is a DROP signal, complementary to the de-fan rewrite
    path. High-precision by the same rules as detect_fanout: needs ≥2 RAW base tables
    (CTE/subquery sources excluded — pre-aggregating is the fix) sharing an FK root, and
    a non-distinct COUNT(*)/COUNT(1) in the OUTER scope. Pure static analysis; returns a
    reason string or None; never raises."""
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

    # A chasm needs ≥2 satellites of the SAME hub joined directly — a single
    # hub⋈satellite join is not a chasm.
    chasm = _chasm_roots(tree, root, table_cols, is_unique_on=is_unique_on)
    if not chasm:
        return None

    # A non-distinct COUNT(*) / COUNT(1) in the OUTER scope.
    outer = root.expression
    for cnt in outer.find_all(exp.Count):
        inner = cnt.this
        if isinstance(inner, exp.Distinct):
            continue
        is_star = inner is None or isinstance(inner, exp.Star) or (
            isinstance(inner, exp.Literal) and not inner.is_string)
        if is_star:
            r = sorted(chasm)[0]
            sats = sorted(chasm[r])
            return (
                f"COUNT(*) over a chasm join ({', '.join(sats)} are each on the many-side "
                f"of '{r}') counts the cross-product of the satellites, not either entity — "
                f"pre-aggregate each in its own CTE keyed by '{r}', or use "
                f"COUNT(DISTINCT <entity>_id) for the entity you mean to count"
            )
    return None


def avg_over_chasm_fanout(sql: str, table_cols: dict | None = None, dialect: str = "duckdb",
                          is_unique_on=None) -> str | None:
    """``AVG(x)`` over a CHASM — every row is the cross-product of ≥2 satellites of
    one hub, so each distinct value is repeated by the OTHER satellite's fan-out
    multiplicity. Unlike SUM/COUNT (which merely inflate) the mean comes out
    *silently biased* — weighted by fan-out, not the true average; and unlike
    MIN/MAX (which survive duplication unchanged) it can't be trusted. detect_fanout
    targets additive measures and defan() bails on AVG by design, so this is a
    high-precision DROP signal on the SAME chasm structure as the COUNT(*) case:
    ≥2 RAW satellites of one hub + a non-DISTINCT, non-windowed AVG in the OUTER
    scope. Static analysis; returns a reason string or None; never raises."""
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

    chasm = _chasm_roots(tree, root, table_cols, is_unique_on=is_unique_on)
    if not chasm:
        return None

    # A non-DISTINCT AVG in the OUTER scope. Windowed AVG (AVG(x) OVER (...)) is a
    # different construct — it doesn't collapse the rows — so exclude it.
    outer = root.expression
    for avg in outer.find_all(exp.Avg):
        if isinstance(avg.this, exp.Distinct):
            continue
        if isinstance(avg.parent, exp.Window):
            continue
        r = sorted(chasm)[0]
        sats = sorted(chasm[r])
        col = avg.this.sql() if avg.this else "x"
        return (
            f"AVG({col}) over a chasm join ({', '.join(sats)} are each on the many-side "
            f"of '{r}') averages the cross-product, so every value is weighted by the "
            f"other satellite's fan-out — a biased mean, not the true average — "
            f"pre-aggregate each satellite in its own CTE keyed by '{r}' first"
        )
    return None


def sum_over_chasm_fanout(sql: str, table_cols: dict | None = None, dialect: str = "duckdb",
                          is_unique_on=None) -> str | None:
    """``SUM(x)`` over a CHASM — ≥2 RAW satellites of the SAME hub joined directly —
    sums a measure across the cross-product of the satellites, so the total is
    inflated by the OTHER satellite's fan-out multiplicity. The real-path scar: a
    ROAS query joined ``attribution``, ``invoices`` AND ``order_items`` (three
    satellites of ``order_id``) and computed ``SUM(weight*revenue_net) / SUM(spend)``
    — every satellite's measure repeated by the product of the others' row counts
    (spend over-counted 2.3M×, $48T vs $21M).

    detect_fanout DOES flag this chasm, but it is wired ONLY to the de-fan REWRITE
    path: when ``defan()`` can't build a clean pre-aggregated rewrite (multi-key
    chasms, fabricated joins), the over-counting SUM silently proceeds to
    interpretation and becomes a Briefing number. This is the DROP fallback that
    closes that gap — the SUM analogue of ``count_star_chasm_fanout`` /
    ``avg_over_chasm_fanout``, on the identical chasm structure: ≥2 RAW satellites
    of one hub (CTE/subquery sources excluded — pre-aggregating is the fix) + a
    non-DISTINCT, non-windowed SUM in the OUTER scope. Static analysis; returns a
    reason string or None; never raises.

    Conservative by construction: a chasm with the satellites pre-aggregated in
    CTEs is NOT flagged (the CTE refs aren't RAW base tables), so it fires only on
    the genuinely-fanned form and stays silent on the correct one — and only as a
    backstop after the de-fan rewrite has already had its chance."""
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

    chasm = _chasm_roots(tree, root, table_cols, is_unique_on=is_unique_on)
    if not chasm:
        return None

    # A non-DISTINCT SUM in the OUTER scope. Windowed SUM (SUM(x) OVER (...)) is a
    # different construct — it doesn't collapse the rows — so exclude it.
    outer = root.expression
    for s in outer.find_all(exp.Sum):
        if isinstance(s.this, exp.Distinct):
            continue
        if isinstance(s.parent, exp.Window):
            continue
        r = sorted(chasm)[0]
        sats = sorted(chasm[r])
        col = s.this.sql() if s.this else "x"
        return (
            f"SUM({col}) over a chasm join ({', '.join(sats)} are each on the many-side "
            f"of '{r}') sums across the cross-product of the satellites, so the total is "
            f"inflated by the other satellites' fan-out — pre-aggregate EACH satellite in "
            f"its own CTE keyed by '{r}' first, then join"
        )
    return None


# ── Measure × key arithmetic — a fabrication the fan-out guards CAN'T see: the row
# count is right, but the VALUE is invented by multiplying a measure by a nominal id.
# Tight key suffixes by design (NOT _code/_num/_number — those can be real measures):
# a column ending here is an identifier, never a quantity. ──
_ARITH_KEY_COL = re.compile(r"(?:^|_)(?:id|key|pk|sk|fk|uuid|guid)$", re.I)


def _unwrap_arith(node):
    """Peel CAST/TRY_CAST/parens off a node to reach the underlying column."""
    from sqlglot import exp
    while isinstance(node, (exp.Cast, exp.TryCast, exp.Paren)):
        node = node.this
    return node


def _is_arith_key(node) -> bool:
    """True if `node` (after unwrapping casts/parens) is a key/id column reference."""
    from sqlglot import exp
    node = _unwrap_arith(node)
    return isinstance(node, exp.Column) and bool(_ARITH_KEY_COL.search((node.name or "").lower()))


def measure_times_key_arithmetic(sql: str, table_cols: dict | None = None,
                                 dialect: str = "duckdb") -> str | None:
    """A SUM/AVG that MULTIPLIES by — or directly aggregates — an id/key column
    fabricates a magnitude. An id is a nominal identifier, not a quantity, so
    ``SUM(unit_price * order_item_id)`` (price × the row's PRIMARY KEY — the real-path
    €150M "revenue" scar, with per-product garbage like P000545 "€36M", when
    order_items carried no quantity column) and ``SUM(order_id)`` have no arithmetic
    meaning. The fan-out detectors above watch for row-multiplication across joins;
    they never see a measure multiplied by a key WITHIN one table, so this closes that
    gap.

    High-precision: a true key column is never a legitimate multiplicand or a SUM/AVG
    argument, so this fires only on the unambiguous bug and stays silent on
    ``SUM(quantity * unit_price)`` (no key) and ``COUNT(order_id)`` (counting keys is
    valid — only SUM/AVG are checked). ``table_cols`` is accepted for call-site
    symmetry with the sibling guards but unused (name-based detection needs no schema).
    Static analysis; returns a reason string or None; never raises."""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    for agg in tree.find_all((exp.Sum, exp.Avg)):
        inner = agg.this
        if isinstance(inner, exp.Distinct) or isinstance(agg.parent, exp.Window):
            continue
        # (a) SUM/AVG directly over a key column — summing/averaging a nominal id.
        if _is_arith_key(inner):
            col = _unwrap_arith(inner)
            return (
                f"{agg.key.upper()}({col.name}) aggregates a key/id column — an id is a nominal "
                f"identifier, not a measure, so its SUM/AVG is a fabricated magnitude; aggregate "
                f"a real measure column instead"
            )
        # (b) a key column inside a multiplication within the aggregate — measure × id.
        for mul in agg.find_all(exp.Mul):
            for operand in (mul.this, mul.expression):
                if _is_arith_key(operand):
                    key = _unwrap_arith(operand)
                    return (
                        f"{agg.key.upper()}({mul.sql(dialect=dialect)}) multiplies by the key/id "
                        f"column '{key.name}' — an id is not a quantity, so this fabricates a "
                        f"magnitude (e.g. price × a row's primary key). Aggregate the measure alone, "
                        f"or multiply by the real quantity column"
                    )
    return None


def avg_of_row_ratios(sql: str, table_cols: dict | None = None,
                      dialect: str = "duckdb") -> str | None:
    """``AVG(<a> / <b>)`` — the mean of PER-ROW ratios — is the wrong recipe for a
    group-level rate: it weights every row equally regardless of denominator magnitude,
    so tiny-denominator rows dominate and the rate is skewed. The real-path scar: the Deep
    path derived freight-% as ``AVG(freight / price)`` → 1.48% for Germany while the
    correct ratio-of-sums (the Insight path) gave 2.17%. The right form is the RATIO OF
    SUMS: ``SUM(a) / NULLIF(SUM(b), 0)`` — every prompt already mandates it; this enforces it.

    High-precision: fires only on a non-DISTINCT, non-windowed AVG whose argument is a
    DIVISION BY A COLUMN. So ``AVG(col)``, ``AVG(score / 100.0)`` (a constant scale), and
    ``SUM(a)/SUM(b)`` / ``AVG(a)/AVG(b)`` (the Div is outside the AVG) are all left alone.
    ``table_cols`` is accepted for call-site symmetry but unused. Returns a reason or None;
    never raises."""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    for avg in tree.find_all(exp.Avg):
        if isinstance(avg.this, exp.Distinct) or isinstance(avg.parent, exp.Window):
            continue
        arg = avg.this
        while isinstance(arg, (exp.Paren, exp.Cast, exp.TryCast)):
            arg = arg.this
        if not isinstance(arg, exp.Div):
            continue
        den = arg.expression
        if isinstance(den, exp.Nullif):
            den = den.this if den.this is not None else (den.expressions[0] if den.expressions else den)
        while isinstance(den, exp.Paren):
            den = den.this
        # Only a divisor that references a COLUMN is a per-row varying denominator (a true
        # ratio); a pure numeric constant (AVG(x/100)) is just scaling and is fine.
        if den.find(exp.Column) is not None:
            return ("AVG(a/b) averages per-row ratios — for a group-level rate use the RATIO OF "
                    "SUMS: SUM(a)/NULLIF(SUM(b),0). Averaging per-row ratios over-weights "
                    "small-denominator rows and skews the rate (the freight-% 1.48%-vs-2.17% scar)")
    return None


def self_ratio_tautology(sql: str, dialect: str = "duckdb") -> str | None:
    """A rate whose NUMERATOR and DENOMINATOR are the SAME aggregate expression —
    ``SUM(x) / NULLIF(SUM(x), 0)``, ``COUNT(y) / COUNT(y)`` — is identically 1.0 for
    every non-zero bucket, REGARDLESS of the data. It is never a real metric: a rate
    divides by a DIFFERENT base (margin/revenue, converted/total). This is the
    `gross_margin_usd / gross_margin_usd → 100%` trap that then gets narrated as "no
    COGS recorded". Pure structural analysis on the parse tree (so `SUM(a)/SUM(a+b)` is
    NOT flagged — different denominator); returns a reason or None; never raises."""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    def _agg_key(node) -> str | None:
        # canonical "FUNC(arg)" for an aggregate, ignoring whitespace/case; None if not an agg
        if isinstance(node, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
            inner = node.this
            arg = "" if inner is None else inner.sql(dialect=dialect)
            arg_norm = re.sub(r"\s+", "", arg).lower()
            return type(node).__name__.lower() + "(" + arg_norm + ")"
        return None

    for div in tree.find_all(exp.Div):
        num, den = div.this, div.expression
        # denominator is often wrapped in NULLIF(<agg>, 0) — unwrap to the first arg
        if isinstance(den, exp.Nullif):
            den = den.this if den.this is not None else den.expressions[0] if den.expressions else den
        nk, dk = _agg_key(num), _agg_key(den)
        if nk and dk and nk == dk:
            return (f"self-referential ratio: numerator and denominator are the same "
                    f"aggregate ({num.sql(dialect=dialect)}) — identically 1.0, not a real rate")
    return None


def _cte_grain_and_outputs(cte_select) -> tuple[set, set, set]:
    """For a CTE's SELECT, return (grain, measures, all_outputs) as output-name sets:
      grain    = output names that come from GROUP BY keys (the CTE's row grain);
      measures = output names whose projection is a NON-DISTINCT additive aggregate;
      all_outputs = every projected output name.
    Names are bare/lowercased (the alias if projected with one, else the column name)."""
    from sqlglot import exp

    def _out_name(proj) -> str:
        if isinstance(proj, exp.Alias):
            return (proj.alias or "").lower()
        if isinstance(proj, exp.Column):
            return (proj.name or "").lower()
        return ""

    grp = cte_select.args.get("group")
    group_cols = set()
    if grp is not None:
        for g in grp.expressions:
            for c in g.find_all(exp.Column):
                group_cols.add((c.name or "").lower())

    grain, measures, outs = set(), set(), set()
    for proj in cte_select.expressions:
        name = _out_name(proj)
        if name:
            outs.add(name)
        # measure = projection containing a non-distinct aggregate
        aggs = list(proj.find_all(exp.AggFunc))
        if aggs and not any(isinstance(a.this, exp.Distinct) for a in aggs):
            if name:
                measures.add(name)
        else:
            # a key/passthrough — grain if it (or its source column) is in GROUP BY
            cols = {(c.name or "").lower() for c in proj.find_all(exp.Column)}
            if name and (name in group_cols or (cols & group_cols)):
                grain.add(name)
    return grain, measures, outs


def cte_grain_mismatch_fanout(sql: str, table_cols: dict | None = None, dialect: str = "duckdb") -> str | None:
    """Fan-out HIDDEN inside CTEs: two pre-aggregated CTEs at DIFFERENT grains joined on
    only the coarser one's grain, so the coarser CTE's measure DUPLICATES across the
    finer CTE's extra grain dimension — and a downstream SUM/AVG over-counts it.

    The real-path scar: a gross-margin query pre-aggregated revenue per (order, category)
    in one CTE and COGS per (order) in another, joined on order_id, then SUM(revenue-cogs)
    per category — so every category absorbed the WHOLE order's COGS (~2.4× over-count) →
    a fabricated −149% margin on every category.

    The chasm detectors deliberately EXCLUDE CTE sources (pre-aggregating in a CTE is the
    fix for a RAW-table chasm), so this grain-mismatch case slips past them — this closes
    it. High-precision: fires only when (a) coarse CTE grain is a STRICT SUBSET of the fine
    CTE grain, (b) the join is on exactly the coarse grain, and (c) a non-distinct SUM/AVG
    references the coarse CTE's measure by a name the fine CTE does NOT also output (so it's
    unambiguously the fanned column). A per-row ratio of the two (rev/total) summed is NOT
    flagged. Static analysis; returns a reason or None; never raises."""
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if tree is None:
        return None

    ctes = {}
    for cte in tree.find_all(exp.CTE):
        sel = cte.this
        if isinstance(sel, exp.Select):
            ctes[cte.alias_or_name.lower()] = sel
    if len(ctes) < 2:
        return None

    info = {name: _cte_grain_and_outputs(sel) for name, sel in ctes.items()}

    # Find joins where BOTH sides are CTEs and the coarser fans across the finer.
    fanned: set = set()       # coarse-CTE measure names that duplicate, unambiguously
    for join in tree.find_all(exp.Join):
        joined = join.this
        if not isinstance(joined, exp.Table):
            continue
        right = joined.name.lower()
        # the left source is the FROM table of the enclosing SELECT (the arg key is
        # "from_" in this sqlglot; accept "from" too for version-robustness).
        sel = join.parent_select
        if sel is None:
            continue
        from_node = sel.args.get("from_") or sel.args.get("from")
        if from_node is None:
            continue
        _t0 = from_node.this if isinstance(from_node.this, exp.Table) else next(
            (t for t in from_node.find_all(exp.Table)), None)
        if _t0 is None:
            continue
        left = _t0.name.lower()
        if left not in ctes or right not in ctes:
            continue
        on = join.args.get("on")
        on_cols = {(c.name or "").lower() for c in on.find_all(exp.Column)} if on else set()
        if not on_cols:
            continue
        for a, b in ((left, right), (right, left)):
            ga, ma, _ = info[a]
            gb, _, ob = info[b]
            # a is the COARSER side; its grain must be a strict subset of b's, and the
            # join must be on exactly a's grain (so a fans across b's extra grain).
            if ga and gb and ga < gb and ga <= on_cols:
                fanned |= {m for m in ma if m not in ob}   # unambiguous coarse measures

    if not fanned:
        return None

    def _only_in_denominator(col_node, agg) -> bool:
        """True if `col_node` sits in a DIVISION DENOMINATOR on its way up to `agg` — a
        per-row divisor (SUM(rev / total)) whose duplication cancels, NOT an additive term
        (SUM(rev - cogs)) whose duplication accumulates."""
        node = col_node
        while node is not None and node is not agg:
            parent = node.parent
            if isinstance(parent, exp.Div) and parent.args.get("expression") is node:
                return True
            node = parent
        return False

    # A non-DISTINCT SUM/AVG that ACCUMULATES a fanned coarse measure (additively, not as a
    # mere divisor) → over-count.
    for agg in tree.find_all((exp.Sum, exp.Avg)):
        if isinstance(agg.this, exp.Distinct) or isinstance(agg.parent, exp.Window):
            continue
        fanned_nodes = [c for c in agg.find_all(exp.Column) if (c.name or "").lower() in fanned]
        if fanned_nodes and any(not _only_in_denominator(c, agg) for c in fanned_nodes):
            hit = sorted({(c.name or "").lower() for c in fanned_nodes})
            return (
                f"grain-mismatch fan-out: a coarser CTE's measure ({', '.join(hit)}) is "
                f"SUM/AVG'd after a join on only its grain, so it duplicates across the finer "
                f"CTE's extra grain (every group absorbs the whole coarser row). Pre-aggregate "
                f"both sides to the SAME grain, or join on the full key, before aggregating."
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


def build_chasm_fanout_rewrite(sql: str, finding: "FanoutFinding", dialect: str = "duckdb"):
    """Deterministic de-fan for a CHASM (≥2 satellites of one hub aggregated across a
    star join — the clicks×impressions case). Pre-aggregate EACH satellite to the hub
    key in its own CTE, then join the CTEs to the hub so each satellite's SUM/COUNT is
    counted once (TPC-H verified: 153M vs the 4x-inflated 612M).

    Returns rewritten SQL or None on any shape it can't prove correct: AVG/MIN/MAX or
    COUNT(DISTINCT)/COUNT(*) aggs, a hub-column aggregate mixed in, a WHERE on a
    satellite (predicates can't be safely split), a child-level GROUP BY, or a
    non-star join. Caller MUST dry-run/compare before adopting."""
    if finding is None or finding.kind != "chasm" or len(finding.satellites) < 2:
        return None
    try:
        import sqlglot
        from sqlglot import exp
    except Exception:
        return None

    sats = set(finding.satellites)
    try:
        sel = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    if not isinstance(sel, exp.Select) or sel.args.get("with"):
        return None

    alias_to_table = {(t.alias_or_name or "").lower(): t.name.lower() for t in sel.find_all(exp.Table)}
    sat_aliases = {a: tn for a, tn in alias_to_table.items() if tn in sats}
    hub_aliases = {a for a, tn in alias_to_table.items() if tn not in sats}
    if len(sat_aliases) < 2 or not hub_aliases:
        return None

    # Each satellite must join to ONE shared hub (star). Capture sat key + hub key.
    sat_join: dict[str, tuple] = {}   # sat_alias -> (sat_key Column, hub_alias, hub_key Column)
    for j in (sel.args.get("joins") or []):
        on = j.args.get("on")
        if not on:
            continue
        for eq in on.find_all(exp.EQ):
            l, r = eq.left, eq.right
            if not (isinstance(l, exp.Column) and isinstance(r, exp.Column)):
                continue
            for sc, hc in ((l, r), (r, l)):
                sa, ha = (sc.table or "").lower(), (hc.table or "").lower()
                if sa in sat_aliases and ha in hub_aliases:
                    sat_join[sa] = (sc, ha, hc)
    if set(sat_join) != set(sat_aliases):
        return None
    hubs = {ha for (_, ha, _) in sat_join.values()}
    if len(hubs) != 1:
        return None
    hub_alias = next(iter(hubs))

    # We rebuild the satellite joins as INNER (hub ⋈ CTE); a LEFT/RIGHT/FULL original
    # would change which hub rows survive — bail rather than alter semantics.
    for j in (sel.args.get("joins") or []):
        jt = j.this
        ja = (jt.alias_or_name or "").lower() if isinstance(jt, exp.Table) else None
        if ja in sat_aliases and (j.args.get("side") or "").upper() in ("LEFT", "RIGHT", "FULL"):
            return None

    where = sel.args.get("where")
    if where and any((c.table or "").lower() in sat_aliases for c in where.find_all(exp.Column)):
        return None  # a satellite predicate can't be safely pushed into one CTE

    grp = sel.args.get("group")
    group_cols = []
    if grp:
        for g in grp.expressions:
            if not isinstance(g, exp.Column) or (g.table or "").lower() != hub_alias:
                return None
            group_cols.append(g)

    # Classify projections: hub dim, or a SUM/COUNT over exactly one satellite column.
    proj_plan = []   # ("dim", Column, out_alias) | ("agg", sat_alias, body, out_alias)
    for e in sel.expressions:
        body = e.this if isinstance(e, exp.Alias) else e
        out_alias = e.alias if isinstance(e, exp.Alias) else None
        if isinstance(body, exp.Column):
            if (body.table or "").lower() != hub_alias:
                return None
            proj_plan.append(("dim", body, out_alias))
        elif isinstance(body, (exp.Sum, exp.Count)):
            inner = body.this
            if isinstance(inner, exp.Distinct) or not isinstance(inner, exp.Column):
                return None  # COUNT(*)/COUNT(DISTINCT) unattributable
            ta = (inner.table or "").lower()
            if ta not in sat_aliases:
                return None
            proj_plan.append(("agg", ta, body, out_alias))
        else:
            return None  # AVG/MIN/MAX/expr → bail
    aggregated = {p[1] for p in proj_plan if p[0] == "agg"}
    if len(aggregated) < 2:
        return None

    # Build a CTE per aggregated satellite: SELECT sat_key AS _k, <aggs> GROUP BY sat_key.
    ctes = {}
    agg_loc = {}   # id(body) -> (cte_name, agg_alias)
    for sa in aggregated:
        sat_key = sat_join[sa][0]
        cte_name = f"_s_{sa}"
        cproj = [exp.alias_(exp.column(sat_key.name), "_k")]
        ai = 0
        for p in proj_plan:
            if p[0] == "agg" and p[1] == sa:
                body = p[2]
                an = f"_a{ai}"; ai += 1
                cproj.append(exp.alias_(type(body)(this=exp.column(body.this.name)), an))
                agg_loc[id(body)] = (cte_name, an)
        cte_sel = exp.Select(expressions=cproj).from_(exp.to_table(sat_aliases[sa])).group_by(exp.column(sat_key.name))
        ctes[sa] = (cte_name, cte_sel)

    # Clone the original (keeps hub FROM/WHERE/GROUP BY), swap satellite joins for CTE joins,
    # re-project satellite aggs as SUM(cte._aN), and attach the WITH.
    outer = sel.copy()
    kept = []
    for j in (outer.args.get("joins") or []):
        jt = j.this
        ja = (jt.alias_or_name or "").lower() if isinstance(jt, exp.Table) else None
        if ja in sat_aliases:
            continue
        kept.append(j)
    for sa in aggregated:
        cte_name = ctes[sa][0]
        hub_key = sat_join[sa][2]
        kept.append(exp.Join(
            this=exp.to_table(cte_name),
            on=exp.EQ(this=exp.column(hub_key.name, table=hub_alias), expression=exp.column("_k", table=cte_name)),
            kind="INNER",
        ))
    outer.set("joins", kept)

    final_proj = []
    for p in proj_plan:
        if p[0] == "dim":
            col = exp.column(p[1].name, table=hub_alias)
            final_proj.append(exp.alias_(col, p[2]) if p[2] else col)
        else:
            body, out_alias = p[2], p[3]
            cte_name, an = agg_loc[id(body)]
            agg = exp.Sum(this=exp.column(an, table=cte_name))
            out_name = out_alias or f"{body.key.lower()}_{body.this.name}"
            final_proj.append(exp.alias_(agg, out_name))
    outer.set("expressions", final_proj)
    try:
        for cn, cs in ctes.values():
            outer = outer.with_(cn, as_=cs)
        return outer.sql(dialect=dialect)
    except Exception:
        return None


def defan(sql: str, finding: "FanoutFinding", dialect: str = "duckdb"):
    """Deterministic de-fan dispatcher. Returns a corrected SQL for the
    parent_fanout or chasm cases, or None when neither can be safely rewritten
    (the caller then falls back to the LLM hint)."""
    if finding is None:
        return None
    if finding.kind == "parent_fanout":
        return build_parent_fanout_rewrite(sql, finding, dialect)
    if finding.kind == "chasm":
        return build_chasm_fanout_rewrite(sql, finding, dialect)
    return None
