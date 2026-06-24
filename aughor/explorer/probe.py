"""Grounded probe generation — the SOTA fix for column hallucination.

Phase 8 used to generate SQL free-form; the model's prior overrode the schema and
it invented columns (``line_total``, ``quantity``) that don't exist, caught only by
a post-hoc gate that discarded ~40% of the token budget. The fix: the LLM never
writes a column name into SQL. It fills a STRUCTURED :class:`Probe` by CHOOSING
measures/dimensions/filters from the connection's REAL columns; we validate the
picks by set-membership (≈0 cost) and COMPILE the probe to grain-safe SQL
deterministically. A non-existent column is structurally impossible to emit.

v1 covers single-table probes and grain-safe star-joins (measures on one fact
table, dimensions/filters on a directly-joined table). Anything the compiler can't
express returns None and the caller falls back to the bounded free-form generator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_TOP_N = 20
_OPS = {"=", "!=", "<>", ">", ">=", "<", "<="}
_RATE_HINTS = ("fraction", "percent", "ratio", "rate", "pct")


def _norm(s: str) -> str:
    return (s or "").replace("_", "").replace("-", "").replace(" ", "").lower()


@dataclass
class ProbeFilter:
    column: str
    op: str
    value: object


@dataclass
class ProbeHaving:
    measure: str
    op: str
    value: float


@dataclass
class Probe:
    """A schema-bound analytical intent. Column fields name REAL columns; the LLM
    picks them from enumerated lists, never free-writing SQL."""
    question: str = ""
    angle: str = ""
    why: str = ""
    measures: list = field(default_factory=list)       # measure columns to aggregate
    dimensions: list = field(default_factory=list)     # group-by columns (0-2)
    filters: list = field(default_factory=list)        # list[ProbeFilter]
    having: Optional[ProbeHaving] = None               # composite threshold on an aggregated measure
    sort_desc: bool = True


def validate_probe(probe: Probe, allowed_measures, allowed_dims, allowed_filters) -> list:
    """Column tokens in the probe that are NOT real columns (empty list = valid).
    Matching is normalisation-insensitive (``customer_id`` ≡ ``customerID``)."""
    am = {_norm(c) for c in allowed_measures}
    ad = {_norm(c) for c in allowed_dims}
    af = {_norm(c) for c in allowed_filters} | am | ad
    bad: list = []
    for m in probe.measures or []:
        if _norm(m) not in am:
            bad.append(m)
    for d in probe.dimensions or []:
        if _norm(d) not in ad:
            bad.append(d)
    for f in (probe.filters or []):
        if _norm(getattr(f, "column", "")) not in af:
            bad.append(getattr(f, "column", ""))
    if probe.having and _norm(probe.having.measure) not in am:
        bad.append(probe.having.measure)
    return bad


def _agg_for(col: str, profile) -> str:
    """Grain-safe aggregate for a measure: AVG for a rate/percent column, SUM for an
    additive one — mirrors the manifest compiler's choice, from profile metadata."""
    blob = " ".join(str(getattr(profile, a, "") or "")
                    for a in ("unit", "value_interpretation", "semantic_type")).lower()
    if any(h in blob for h in _RATE_HINTS) or any(h in _norm(col) for h in ("rate", "ratio", "pct", "percent")):
        return f"AVG({{q}}{col})"
    vr = getattr(profile, "value_range", None)
    if isinstance(vr, (tuple, list)) and len(vr) >= 2:
        lo, hi = vr[0], vr[1]
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and -1.0 <= lo and hi <= 1.5:
            return f"AVG({{q}}{col})"
    return f"SUM({{q}}{col})"


def _fmt_value(v) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("'", "''")
    return f"'{s}'"


def _resolve(colnorm_to_tables: dict, cols) -> Optional[set]:
    """The minimal set of tables hosting all given columns, or None if any is unknown."""
    tables: set = set()
    for c in cols:
        hosts = colnorm_to_tables.get(_norm(c))
        if not hosts:
            return None
        tables.add(frozenset(hosts))
    return tables


def probe_to_sql(probe: Probe, *, tables_cols: dict, col_profiles: dict,
                 joins: list, dialect: str = "duckdb") -> Optional[str]:
    """Compile a validated probe to grain-safe SQL, or None when v1 can't express it
    (caller falls back to free-form). ``tables_cols`` = {table: [cols]}; ``col_profiles``
    = {table: {col: profile}}; ``joins`` = verified join dicts."""
    measures = [m for m in (probe.measures or []) if m]
    if not measures:
        return None
    dims = [d for d in (probe.dimensions or []) if d][:2]
    filters = list(probe.filters or [])

    # column(normalised) -> tables hosting it, and (table,colnorm) -> real col name + profile
    colnorm_to_tables: dict = {}
    realname: dict = {}
    profof: dict = {}
    for t, cols in (tables_cols or {}).items():
        for c in (cols or []):
            n = _norm(c)
            colnorm_to_tables.setdefault(n, set()).add(t)
            realname[(t, n)] = c
    for t, cm in (col_profiles or {}).items():
        for c, p in (cm or {}).items():
            profof[(t, _norm(c))] = p

    # The measures must all live on ONE table (the fact) — keeps the join grain-safe
    # (no parent-measure fan-out). Dims/filters may live on a single directly-joined table.
    m_tables = _resolve(colnorm_to_tables, measures)
    if m_tables is None:
        return None
    fact_candidates = set.intersection(*[set(fs) for fs in m_tables]) if m_tables else set()
    if not fact_candidates:
        return None

    side_cols = dims + [getattr(f, "column", "") for f in filters]
    if probe.having:
        side_cols = side_cols + [probe.having.measure]

    def _build(fact: str) -> Optional[str]:
        # Which columns are NOT on the fact table → must come from one joined table.
        other_cols = [c for c in (dims + [getattr(f, "column", "") for f in filters])
                      if fact not in (colnorm_to_tables.get(_norm(c)) or set())]
        if not other_cols:
            return _single_table_sql(fact)
        other_tables = _resolve(colnorm_to_tables, other_cols)
        if other_tables is None:
            return None
        cand = set.intersection(*[set(fs) for fs in other_tables])
        cand.discard(fact)
        for j in cand:
            edge = _find_join(joins, fact, j)
            if edge:
                return _star_join_sql(fact, j, edge)
        return None

    def _q(table: str, col: str, alias: str = "") -> str:
        n = _norm(col)
        rn = realname.get((table, n), col)
        return f"{alias}.{rn}" if alias else rn

    def _measure_select(table: str, alias: str = "") -> tuple:
        sel = []
        order_expr = None
        for i, m in enumerate(measures):
            n = _norm(m)
            agg = _agg_for(realname.get((table, n), m), profof.get((table, n))).format(q=(alias + "." if alias else ""))
            a = f"m_{n}"
            sel.append(f"{agg} AS {a}")
            if i == 0:
                order_expr = a
        return sel, order_expr

    def _where(table_alias_map: dict) -> str:
        conds = []
        for f in filters:
            op = getattr(f, "op", "=")
            if op not in _OPS:
                continue
            n = _norm(getattr(f, "column", ""))
            host = next((t for t in (colnorm_to_tables.get(n) or set())), None)
            al = table_alias_map.get(host, "")
            conds.append(f"{_q(host, getattr(f,'column',''), al)} {op} {_fmt_value(getattr(f,'value',None))}")
        return (" WHERE " + " AND ".join(conds)) if conds else ""

    def _having(table: str, alias: str = "") -> str:
        h = probe.having
        if not h or h.op not in _OPS:
            return ""
        n = _norm(h.measure)
        agg = _agg_for(realname.get((table, n), h.measure), profof.get((table, n))).format(q=(alias + "." if alias else ""))
        return f" HAVING {agg} {h.op} {_fmt_value(h.value)}"

    def _single_table_sql(fact: str) -> str:
        sel, order_expr = _measure_select(fact)
        dim_sel = [_q(fact, d) for d in dims]
        select = ", ".join(dim_sel + sel)
        sql = f"SELECT {select} FROM {fact}"
        sql += _where({fact: ""})
        if dims:
            sql += " GROUP BY " + ", ".join(_q(fact, d) for d in dims)
        sql += _having(fact)
        if dims and order_expr:
            sql += f" ORDER BY {order_expr} {'DESC' if probe.sort_desc else 'ASC'} LIMIT {_TOP_N}"
        return sql

    def _star_join_sql(fact: str, dim_tbl: str, edge: tuple) -> str:
        fa, da = "f", "d"
        amap = {fact: fa, dim_tbl: da}
        f_col, d_col = edge
        sel, order_expr = _measure_select(fact, fa)
        dim_sel = []
        grp = []
        for d in dims:
            host = fact if fact in (colnorm_to_tables.get(_norm(d)) or set()) else dim_tbl
            expr = _q(host, d, amap[host])
            dim_sel.append(expr)
            grp.append(expr)
        select = ", ".join(dim_sel + sel)
        sql = (f"SELECT {select} FROM {fact} {fa} "
               f"JOIN {dim_tbl} {da} ON {fa}.{f_col} = {da}.{d_col}")
        sql += _where(amap)
        if grp:
            sql += " GROUP BY " + ", ".join(grp)
        sql += _having(fact, fa)
        if grp and order_expr:
            sql += f" ORDER BY {order_expr} {'DESC' if probe.sort_desc else 'ASC'} LIMIT {_TOP_N}"
        return sql

    for fact in sorted(fact_candidates):
        sql = _build(fact)
        if sql:
            return sql
    return None


def _find_join(joins: list, a: str, b: str) -> Optional[tuple]:
    """A verified join between tables a and b → (a_col, b_col), or None."""
    na, nb = _norm(a.split(".")[-1]), _norm(b.split(".")[-1])
    for j in (joins or []):
        ft, tt = j.get("from_table", ""), j.get("to_table", "")
        fc, tc = j.get("from_col", ""), j.get("to_col", "")
        if not (ft and tt and fc and tc):
            continue
        nft, ntt = _norm(ft.split(".")[-1]), _norm(tt.split(".")[-1])
        if nft == na and ntt == nb:
            return (fc, tc)
        if nft == nb and ntt == na:
            return (tc, fc)
    return None
