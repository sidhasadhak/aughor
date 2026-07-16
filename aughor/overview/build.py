"""Overview mode — "Show me interesting facts about this schema".

The widest-possible question, answered the way Databricks Genie offers it by
default: not an investigation of one metric, but a deterministic *profile* of the
whole dataset, ranked by notability and capped for diversity so the result is a
scannable TOUR across many tables and fact TYPES — never one measure ranked N ways.

Seven lenses, each a cheap grounded probe (most read the cached column profiles,
so they cost zero SQL):

  scale · concentration · outlier · distribution · composition · coverage · relationship

Each produces :class:`OverviewFact`s with a templated (deterministic, no-LLM)
headline, the notability score, and the exact SQL + a small result the frontend
draws as a tiny chart. The orchestrator scores every candidate, then selects a
DIVERSE top-N (one per lens first, then fill by score with per-(measure,dimension)
caps) so the tour spans the schema instead of fixating.

Fully deterministic and bounded — no per-turn LLM, a hard probe cap — so it is
cheap enough to be the default first-look on any new connection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

from aughor.overview import metrics as M

# ── tuning (bounded so the tour stays fast + graduation-eligible) ─────────────
_MAX_TABLES = 14          # profile/scan the largest N tables
_MAX_DIMS_PER_TABLE = 3   # probe at most this many dimensions per table
_MAX_PROBES = 26          # hard ceiling on live group-by probes
_MIN_NOTABILITY = 0.18    # drop facts below this before selection
_DIM_MAX_CARD = 40        # a "material" dimension: 2..40 distinct values
_LABEL = "__overview__"   # dunder label → read-only, audit/PII-exempt internal probe

_RATE_INTERP = ("fraction", "percent", "ratio", "rate", "pct")


@dataclass
class OverviewFact:
    lens: str                         # scale|concentration|outlier|distribution|composition|coverage|relationship
    headline: str
    stat: str                         # pre-rendered primary number (frontend may re-format)
    stat_label: str
    why: str
    notability: float
    table: str = ""
    measure: Optional[str] = None
    dimension: Optional[str] = None
    sql: str = ""
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    chart_type: str = "none"          # bar|line|none
    chart_config: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "lens": self.lens, "headline": self.headline, "stat": self.stat,
            "stat_label": self.stat_label, "why": self.why,
            "notability": round(self.notability, 3), "table": self.table,
            "measure": self.measure, "dimension": self.dimension, "sql": self.sql,
            "columns": self.columns, "rows": self.rows,
            "chart_type": self.chart_type, "chart_config": self.chart_config,
        }


@dataclass
class OverviewReport:
    facts: list = field(default_factory=list)
    summary: str = ""
    tables_seen: int = 0
    tables_total: int = 0
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "facts": [f.to_dict() for f in self.facts], "summary": self.summary,
            "tables_seen": self.tables_seen, "tables_total": self.tables_total,
            "generated_at": self.generated_at,
        }


# ── small prose-number formatter (the UI re-formats; prose needs readable text) ─

def _fmt(v: float, kind: str = "number") -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if kind == "pct":
        return f"{v * 100:.1f}%"      # v is always a fraction (share/deviation/null-rate)
    if kind == "ratio":
        return f"{v:.1f}×"
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.1f}B"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e3:
        return f"{v / 1e3:.1f}K"
    if a == int(a):
        return f"{int(v):,}"
    return f"{v:,.2f}"


def _clean_label(name: str) -> str:
    return (name or "").split(".")[-1].replace("_", " ").strip()


# ── self-contained profiling (one SUMMARIZE per table) ────────────────────────
# The shared profiler assumes bare table names resolve via search_path; on a
# multi-schema DuckDB (the workspace connection) only schema-qualified names work,
# so we profile ourselves: `SUMMARIZE SELECT * FROM schema.table` returns, in ONE
# query, every stat the lenses need — row count, per-column type, approx_unique,
# null %, min/max/avg/median/std. Robust across connection types (information_schema
# / SUMMARIZE), qualified names throughout, and never raises.

_NUMERIC_TYPES = ("INT", "BIGINT", "HUGEINT", "DOUBLE", "DECIMAL", "FLOAT", "REAL",
                  "NUMERIC", "TINYINT", "SMALLINT", "UBIGINT")
_DATE_TYPES = ("DATE", "TIMESTAMP", "DATETIME", "TIME")


def _profile(conn, qualified_tables: list):
    from aughor.tools.profiler import is_key_like
    tabs: dict = {}
    cols: list = []
    for qt in qualified_tables:
        colnames, rows = _probe(conn, f"SUMMARIZE SELECT * FROM {qt}")
        if not rows:
            continue
        idx = {str(c).lower(): i for i, c in enumerate(colnames or [])}

        def cell(r, key):
            i = idx.get(key)
            return r[i] if (i is not None and i < len(r)) else None

        rc = 0
        ts_col = ts_min = ts_max = None
        tcols: list = []
        for r in rows:
            name = str(cell(r, "column_name"))
            ctype = str(cell(r, "column_type") or "").upper()
            rc = max(rc, int(_f(cell(r, "count")) or 0))
            approx = int(_f(cell(r, "approx_unique")) or 0)
            npct = _f(cell(r, "null_percentage"))
            mn, mx = _f(cell(r, "min")), _f(cell(r, "max"))
            is_num = any(t in ctype for t in _NUMERIC_TYPES)
            is_date = any(t in ctype for t in _DATE_TYPES)
            is_id = is_key_like(name) or (is_num and name.lower().endswith("_id"))
            if is_date:
                st = "timestamp"
                if ts_col is None:
                    ts_col, ts_min, ts_max = name, cell(r, "min"), cell(r, "max")
            elif is_id:
                st = "key"
            elif is_num:
                st = "measure"
            elif approx and approx <= _DIM_MAX_CARD:
                st = "dimension"
            else:
                st = "text"
            top = None
            if approx == 1 and st in ("dimension", "text"):
                _, one = _probe(conn, f"SELECT {name} FROM {qt} WHERE {name} IS NOT NULL LIMIT 1")
                top = [str(one[0][0])] if one else None
            tcols.append(SimpleNamespace(
                table=qt, column=name, dtype=ctype, semantic_type=st,
                distinct_count=approx, null_rate=((npct / 100.0) if npct is not None else 0.0),
                value_range=((mn, mx) if (is_num and mn is not None and mx is not None) else None),
                mean=_f(cell(r, "avg")), stddev=_f(cell(r, "std")), p50=_f(cell(r, "q50")),
                value_interpretation=None, unit=None, top_values=top, is_fk=is_id))
        cols += tcols
        date_range = n_periods = None
        if ts_min and str(ts_min) != "NULL":
            date_range = (str(ts_min), str(ts_max))
            n_periods = 1 if str(ts_min)[:7] == str(ts_max)[:7] else 2
        tabs[qt] = SimpleNamespace(table=qt, row_count=rc, date_range=date_range,
                                   n_periods=n_periods, time_grain=None, primary_timestamp=ts_col)
    return tabs, cols


# ── profile helpers ───────────────────────────────────────────────────────────

def _is_measure(c) -> bool:
    return (getattr(c, "semantic_type", "") == "measure"
            and not getattr(c, "is_fk", False)
            and not _is_coord(getattr(c, "column", "")))


def _is_rate(c) -> bool:
    interp = (getattr(c, "value_interpretation", "") or "").lower()
    unit = (getattr(c, "unit", "") or "").lower()
    if any(t in interp or t in unit for t in _RATE_INTERP):
        return True
    vr = getattr(c, "value_range", None)
    if vr and len(vr) == 2:
        try:
            return -1.0 <= float(vr[0]) and float(vr[1]) <= 1.5
        except (TypeError, ValueError):
            return False
    return False


def _is_additive(c) -> bool:
    return _is_measure(c) and not _is_rate(c)


def _is_coord(name: str) -> bool:
    n = (name or "").lower()
    return n in {"lat", "lng", "lon", "latitude", "longitude"} or n.endswith(
        ("_lat", "_lng", "_lon"))


def _material_dims(cols) -> list:
    out = []
    for c in cols:
        st = (getattr(c, "semantic_type", "") or "").lower()
        if getattr(c, "is_fk", False) or st in ("key", "measure", "timestamp", "text", "primary_key"):
            continue
        if "BOOL" in (getattr(c, "dtype", "") or "").upper():
            continue                  # a True/False flag makes poor concentration prose ("concentrates in True")
        dc = getattr(c, "distinct_count", 0) or 0
        if 2 <= dc <= _DIM_MAX_CARD:
            out.append(c)
    # fewer distinct values first — the crisp cuts (2 origins) beat the fuzzy ones
    return sorted(out, key=lambda c: getattr(c, "distinct_count", 0) or 0)


def _probe(conn, sql: str):
    """Run a bounded read-only probe. Returns (columns, rows) with rows as lists of
    stringified cells (DuckDB/Postgres emit str cells), or (None, None) on error."""
    try:
        r = conn.execute(_LABEL, sql)
    except Exception:
        return None, None
    if getattr(r, "error", None):
        return None, None
    return list(r.columns or []), list(r.rows or [])


def _f(x) -> Optional[float]:
    try:
        if x is None or x == "NULL":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


# ── the lenses ─────────────────────────────────────────────────────────────────

def _lens_scale(tprofiles: dict, entity_hint: str) -> list:
    """One shape fact: how big and how wide the dataset is (pure, no SQL)."""
    if not tprofiles:
        return []
    biggest = max(tprofiles.values(), key=lambda t: getattr(t, "row_count", 0) or 0)
    rows = getattr(biggest, "row_count", 0) or 0
    ntables = len(tprofiles)
    span = ""
    dr = getattr(biggest, "date_range", None)
    grain = getattr(biggest, "time_grain", None)
    nper = getattr(biggest, "n_periods", None) or 0
    if dr and len(dr) == 2 and dr[0]:
        span = f" spanning {str(dr[0])[:10]} → {str(dr[1])[:10]}"
        if nper and nper <= 1:
            span += " (a single period — no trend is assessable)"
    ent = _clean_label(getattr(biggest, "table", entity_hint))
    return [OverviewFact(
        lens="scale",
        headline=f"{_fmt(rows)} {ent} across {ntables} tables",
        stat=_fmt(rows), stat_label=ent,
        why=f"the dataset holds {ntables} related tables{span}"
            + (f", at {grain} grain" if grain else ""),
        notability=0.4, table=getattr(biggest, "table", ""),
    )]


def _lens_group_probes(conn, table: str, cols: list, tprofile) -> list:
    """Concentration / composition / outlier / relationship — all derived from ONE
    group-by probe per (table, dimension): value = Σ(primary additive measure) and
    the row COUNT per group. A single scan feeds four lenses."""
    facts: list = []
    dims = _material_dims(cols)[:_MAX_DIMS_PER_TABLE]
    if not dims:
        return facts
    # the money column, if any — but only a strictly NON-NEGATIVE one: SUM / share /
    # per-record deviation of a signed net measure (award_miles earn+ / redeem−) is
    # misleading, so a table with only signed measures falls back to count-based facts.
    def _nonneg(c) -> bool:
        vr = getattr(c, "value_range", None)
        return not (vr and _f(vr[0]) is not None and _f(vr[0]) < 0)
    additive = [c for c in cols if _is_additive(c) and _nonneg(c)]
    measure = additive[0].column if additive else None

    for dcol in dims:
        dim = dcol.column
        if measure:
            sql = (f"SELECT {dim} AS grp, COUNT(*) AS n, ROUND(SUM({measure}), 2) AS val "
                   f"FROM {table} WHERE {dim} IS NOT NULL GROUP BY 1 ORDER BY val DESC LIMIT 25")
            value_kind, mlabel = "money", _clean_label(measure)
        else:
            sql = (f"SELECT {dim} AS grp, COUNT(*) AS n "
                   f"FROM {table} WHERE {dim} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 25")
            value_kind, mlabel = "count", "records"
        colnames, rows = _probe(conn, sql)
        if not rows:
            continue
        groups = [str(r[0]) for r in rows]
        counts = [(_f(r[1]) or 0.0) for r in rows]
        values = [(_f(r[2]) if len(r) > 2 else _f(r[1])) or 0.0 for r in rows]
        ngroups = len(groups)
        if ngroups < 2:
            continue

        chart_rows = [[g, v] for g, v in zip(groups, values)][:12]
        chart = {"type": "bar", "x_field": "group", "y_field": "value",
                 "title": f"{mlabel} by {_clean_label(dim)}"}
        base = dict(table=table, measure=(measure or None), dimension=dim,
                    sql=sql, columns=["group", "value"], rows=chart_rows,
                    chart_type="bar", chart_config=chart)

        # ── concentration ──
        hhi = M.hhi(values)
        top1 = M.top_share(values, 1)
        conc_nb = M.notability_concentration(hhi, top1)
        if conc_nb >= _MIN_NOTABILITY:
            facts.append(OverviewFact(
                lens="concentration",
                headline=f"{mlabel.capitalize()} concentrates in {groups[0]} ({_fmt(top1, 'pct')})",
                stat=_fmt(top1, "pct"), stat_label=f"of {mlabel} from {groups[0]}",
                why=(f"{groups[0]} alone carries {_fmt(top1, 'pct')} of {mlabel} across "
                     f"{ngroups} {_clean_label(dim)} values (HHI {hhi:.2f} — "
                     f"{'dominated' if hhi > 0.5 else 'concentrated' if hhi > 0.25 else 'spread'})"),
                notability=conc_nb, **base))

        # ── composition (only when it's a small, readable mix) ──
        if 2 <= ngroups <= 6 and value_kind == "money":
            s = M.shares(values)
            mix = ", ".join(f"{g} {_fmt(x, 'pct')}" for g, x in list(zip(groups, s))[:4])
            comp_nb = min(0.75, 0.3 + abs((s[0] if s else 0) - 1.0 / ngroups) * 1.4)
            facts.append(OverviewFact(
                lens="composition",
                headline=f"{_clean_label(dim).capitalize()} mix: {groups[0]} leads at {_fmt(s[0], 'pct')}",
                stat=_fmt(s[0], "pct"), stat_label=f"{groups[0]} share of {mlabel}",
                why=f"the {_clean_label(dim)} split of {mlabel} — {mix}",
                notability=comp_nb, **base))

        # ── relationship XOR outlier (per-record) — one per-unit angle per cut ──
        # A small dimension with a large per-record ratio is a structural DRIVER
        # ("first class fares 51× economy") — the richer fact, so it wins; otherwise
        # fall back to a single-group OUTLIER against the peer median. Never both, so
        # a cut shows at most its "where the total is" + one "per-unit" angle.
        pr = [(v / n if n else 0.0) for v, n in zip(values, counts)]
        if value_kind == "money" and any(pr):
            lo, hi = min(pr), max(pr)
            ratio = M.spread_ratio(lo, hi)
            if 2 <= ngroups <= 4 and ratio >= 2.0:
                ghi, glo = groups[pr.index(hi)], groups[pr.index(lo)]
                facts.append(OverviewFact(
                    lens="relationship",
                    headline=f"{mlabel.capitalize()} scales {_fmt(ratio, 'ratio')} across {_clean_label(dim)}",
                    stat=_fmt(ratio, "ratio"), stat_label=f"{ghi} vs {glo} per record",
                    why=(f"{ghi} averages {_fmt(hi)} per record vs {_fmt(lo)} for {glo} — "
                         f"a structural {_clean_label(dim)} effect, not a data error"),
                    notability=M.notability_spread(ratio), **base))
            else:
                med = sorted(pr)[len(pr) // 2]
                idx = max(range(ngroups), key=lambda i: abs(M.deviation(pr[i], pr)))
                dev = M.deviation(pr[idx], pr)
                out_nb = M.notability_deviation(dev)
                if out_nb >= _MIN_NOTABILITY and abs(dev) >= 0.25:
                    facts.append(OverviewFact(
                        lens="outlier",
                        headline=(f"{groups[idx]} has {'unusually high' if dev > 0 else 'unusually low'} "
                                  f"{mlabel} per record"),
                        stat=_fmt(pr[idx]), stat_label=f"avg {mlabel} for {groups[idx]}",
                        why=(f"{groups[idx]} averages {_fmt(pr[idx])} vs ~{_fmt(med)} typical "
                             f"({_fmt(abs(dev), 'pct')} {'above' if dev > 0 else 'below'}) — "
                             f"a structural difference, not necessarily under/over-performance"),
                        notability=out_nb, **base))
    return facts


def _lens_named_outlier(conn, table: str, cols: list, tprofile) -> list:
    """R15 — the named-outlier-ENTITY lens (flag ``lens.decision_grade``): surface the
    single most extreme entity BY ID — the `research_agent_outliers` output shape
    ("customer CU0036204: 2,423 tickets ≈ 6 flights/day"). Where the group lens cuts by
    a SMALL dimension, this cuts by the table's high-cardinality entity column (customer
    id, aircraft registration) and names the record that towers over its top-10 peers.
    One probe per table; the "potential causes" hedge is honest by construction — a
    dominance this extreme is either a data artifact or a real whale, and the drill
    (the attached SQL) is how you find out."""
    facts: list = []
    row_count = float(getattr(tprofile, "row_count", 0) or 0)
    if row_count < 100:
        return facts

    # The entity column: a repeated identifier — high-card but NOT row-unique (a
    # per-row id like ticket_id aggregates to nothing). Most-repeated wins: that is
    # the id whose top entity means the most events/records per entity.
    def _entity_col(c) -> bool:
        st = (getattr(c, "semantic_type", "") or "").lower()
        dc = float(getattr(c, "distinct_count", 0) or 0)
        return (st in ("key", "dimension", "text")
                and not _is_coord(getattr(c, "column", ""))
                and 30 <= dc <= 0.9 * row_count)

    entities = sorted((c for c in cols if _entity_col(c)),
                      key=lambda c: float(getattr(c, "distinct_count", 0) or 1))
    if not entities:
        return facts
    ent = entities[0].column
    ent_label = _clean_label(ent)

    def _nonneg(c) -> bool:
        vr = getattr(c, "value_range", None)
        return not (vr and _f(vr[0]) is not None and _f(vr[0]) < 0)
    additive = [c for c in cols if _is_additive(c) and _nonneg(c)]
    measure = additive[0].column if additive else None

    if measure:
        sql = (f"SELECT {ent} AS grp, COUNT(*) AS n, ROUND(SUM({measure}), 2) AS val "
               f"FROM {table} WHERE {ent} IS NOT NULL GROUP BY 1 ORDER BY val DESC LIMIT 10")
        mlabel = _clean_label(measure)
    else:
        sql = (f"SELECT {ent} AS grp, COUNT(*) AS n FROM {table} "
               f"WHERE {ent} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 10")
        mlabel = "records"
    colnames, rows = _probe(conn, sql)
    if not rows or len(rows) < 5:
        return facts
    groups = [str(r[0]) for r in rows]
    counts = [(_f(r[1]) or 0.0) for r in rows]
    values = [(_f(r[2]) if len(r) > 2 else _f(r[1])) or 0.0 for r in rows]

    peers = sorted(values[1:])
    med = peers[len(peers) // 2]
    if med <= 0 or values[0] <= 0:
        return facts
    dev = (values[0] - med) / med
    if dev < 1.0:          # the leader must at least DOUBLE its top-10 peer median
        return facts

    chart_rows = [[g, v] for g, v in zip(groups, values)]
    facts.append(OverviewFact(
        lens="outlier",
        headline=(f"{ent_label.capitalize()} {groups[0]} towers over its peers — "
                  f"{_fmt(values[0])} {mlabel}"),
        stat=_fmt(values[0]), stat_label=f"{mlabel} for {groups[0]}",
        why=(f"{groups[0]} carries {_fmt(values[0])} {mlabel} across {_fmt(counts[0])} records "
             f"vs ~{_fmt(med)} for its top-10 peers ({_fmt(dev, 'pct')} above). Potential causes: "
             f"a data-quality artifact (duplicated or mis-keyed records) or a genuinely dominant "
             f"{ent_label} — drill this fact to verify which"),
        notability=min(0.92, 0.12 + M.notability_deviation(dev)),
        table=table, measure=(measure or None), dimension=ent,
        sql=sql, columns=["group", "value"], rows=chart_rows,
        chart_type="bar",
        chart_config={"type": "bar", "x_field": "group", "y_field": "value",
                      "title": f"top {ent_label} by {mlabel}"},
    ))
    return facts


def _lens_distribution(by_table: dict) -> list:
    """Shape-of-the-numbers facts from cached moments (skew, span) — no SQL."""
    facts: list = []
    for table, cols in by_table.items():
        for c in cols.values():
            if not _is_additive(c):
                continue
            mean, p50, vr = getattr(c, "mean", None), getattr(c, "p50", None), getattr(c, "value_range", None)
            col = _clean_label(c.column)
            sk = M.skew_ratio(mean, p50)
            if sk >= 1.6:
                nb = M.notability_skew(sk)
                lo = vr[0] if vr and len(vr) == 2 else None
                hi = vr[1] if vr and len(vr) == 2 else None
                span = f", ranging {_fmt(lo)}–{_fmt(hi)}" if lo is not None else ""
                facts.append(OverviewFact(
                    lens="distribution",
                    headline=f"{col.capitalize()} is heavily right-skewed",
                    stat=_fmt(sk, "ratio"), stat_label="mean-to-median",
                    why=(f"the median {col} is {_fmt(p50)} but the mean is {_fmt(mean)} "
                         f"({_fmt(sk, 'ratio')}){span} — a long tail of high values"),
                    notability=nb, table=table, measure=c.column))
            elif vr and len(vr) == 2:
                ratio = M.spread_ratio(vr[0], vr[1])
                if ratio >= 200:
                    facts.append(OverviewFact(
                        lens="distribution",
                        headline=f"{col.capitalize()} spans {_fmt(ratio, 'ratio')}",
                        stat=_fmt(ratio, "ratio"), stat_label=f"{col} min-to-max",
                        why=f"{col} ranges {_fmt(vr[0])} to {_fmt(vr[1])} — a very wide spread",
                        notability=M.notability_spread(ratio), table=table, measure=c.column))
    return facts


def _lens_coverage(by_table: dict, tprofiles: dict, touched_tables: set) -> list:
    """Did-you-know facts: single-value columns, heavy nulls, untouched big tables."""
    facts: list = []
    for table, cols in by_table.items():
        for c in cols.values():
            col = _clean_label(c.column)
            dc = getattr(c, "distinct_count", 0) or 0
            st = (getattr(c, "semantic_type", "") or "").lower()
            if dc == 1 and st not in ("key",):
                tv = getattr(c, "top_values", None)
                val = tv[0] if tv else "one value"
                facts.append(OverviewFact(
                    lens="coverage",
                    headline=f"Every row shares one {col}: {val}",
                    stat="100%", stat_label=f"single {col}",
                    why=f"{col} never varies — worth knowing before you filter or group by it",
                    notability=M.notability_coverage(single_value=True), table=table, measure=c.column))
            nr = getattr(c, "null_rate", 0.0) or 0.0
            if nr >= 0.30 and st != "key":
                facts.append(OverviewFact(
                    lens="coverage",
                    headline=f"{col.capitalize()} is {_fmt(nr, 'pct')} empty",
                    stat=_fmt(nr, "pct"), stat_label=f"{col} null rate",
                    why=f"{_fmt(nr, 'pct')} of {table} rows have no {col} — a coverage gap to know about",
                    notability=M.notability_coverage(null_rate=nr), table=table, measure=c.column))
    # untouched large tables — ONE summary fact naming the biggest few, so the tour
    # doesn't repeat a dozen near-identical "N rows — untouched" cards.
    untouched = sorted(
        ((getattr(tp, "row_count", 0) or 0, t) for t, tp in tprofiles.items()
         if t not in touched_tables and (getattr(tp, "row_count", 0) or 0) >= 5000),
        reverse=True)
    if untouched:
        names = [_clean_label(t) for _, t in untouched[:3]]
        biggest = untouched[0][0]
        namelist = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
        facts.append(OverviewFact(
            lens="coverage",
            headline=(f"{namelist} {'holds' if len(names) == 1 else 'hold'} sizable data no metric touched"
                      if len(names) <= 3 else f"{len(untouched)} tables sit untouched by common metrics"),
            stat=_fmt(biggest), stat_label=f"rows in {names[0]}",
            why=(f"{'this table is' if len(untouched) == 1 else f'{len(untouched)} tables are'} "
                 f"sizable but no common metric surfaced them — places to explore "
                 f"({', '.join(names)}…)" if len(untouched) > 3 else
                 "sizable tables no common metric surfaced — good places to explore next"),
            notability=M.notability_coverage(untouched_rows=biggest), table=untouched[0][1]))
    return facts


# ── selection: score → diverse top-N ──────────────────────────────────────────

_MAX_PER_LENS = 2      # keep the tour diverse — never N variations of one lens
_MAX_PER_CUT = 2       # a (table, dimension) may show at most its "where" + its "per-unit" angle
_MAX_PER_TABLE = 2     # …and no single TABLE monopolises the tour (airline `tickets` took 3/8)


def _schema_of(f) -> str:
    """Owning schema of a fact's schema-qualified table ('' when unqualified)."""
    t = f.table or ""
    return t.split(".")[0] if "." in t else ""


# ── learned prior: a bounded nudge from how often the user drilled each lens / table ──
_PRIOR_CAP = 0.15   # a prior promotes a fact in CLOSE calls; it never buries a notable one


def _prior_boost(lens_ct: int, table_ct: int) -> float:
    """A bounded, saturating notability nudge from the per-connection drill counts (see
    ``overview.drills``). Each source saturates (≈3 drills → half its 0.10 weight) and the
    sum is capped at ``_PRIOR_CAP``, so a well-liked lens/table rises in a tie but a genuinely
    notable deterministic fact still wins."""
    lens_b = 0.10 * (lens_ct / (lens_ct + 3.0)) if lens_ct > 0 else 0.0
    table_b = 0.10 * (table_ct / (table_ct + 3.0)) if table_ct > 0 else 0.0
    return min(_PRIOR_CAP, lens_b + table_b)


def _apply_priors(candidates: list, priors: Optional[dict]) -> None:
    """Fold the per-connection drill priors into each candidate's notability, in place. A
    no-op when there is no prior, so the tour stays byte-identical until a user drills."""
    if not priors:
        return
    lens_p = priors.get("lens") or {}
    table_p = priors.get("table") or {}
    if not lens_p and not table_p:
        return
    for f in candidates:
        b = _prior_boost(lens_p.get(f.lens, 0), table_p.get(f.table, 0))
        if b:
            f.notability = min(1.0, f.notability + b)


def _select(facts: list, limit: int) -> list:
    facts = [f for f in facts if f.notability >= _MIN_NOTABILITY]
    facts.sort(key=lambda f: f.notability, reverse=True)
    # A per-schema cap only binds when the pool actually spans >1 schema (a full-connection
    # overview on a multi-schema connection); on a scoped/single-schema tour it must never
    # starve the one schema, so leave it unbounded there. Reserve ≥2 slots for other schemas.
    multi_schema = len({s for s in (_schema_of(f) for f in facts) if s}) > 1
    max_per_schema = max(_MAX_PER_TABLE, limit - 2) if multi_schema else limit

    chosen: list = []
    lens_ct: dict = {}
    cut_ct: dict = {}
    table_ct: dict = {}
    schema_ct: dict = {}

    def _cut(f):
        return (f.table, f.dimension) if f.dimension else None

    def _semantic_ok(f) -> bool:
        # Semantic-repetition caps (lens, table+dimension cut) — enforced in EVERY pass:
        # even when filling, the tour must never become N variations of one lens or one cut.
        if lens_ct.get(f.lens, 0) >= _MAX_PER_LENS:
            return False
        c = _cut(f)
        return not (c and cut_ct.get(c, 0) >= _MAX_PER_CUT)

    def _source_ok(f) -> bool:
        # Source-diversity caps (table, schema) — RELAXED in the final fill pass so a narrow
        # schema (few fact-producing tables) still fills the tour instead of starving.
        if f.table and table_ct.get(f.table, 0) >= _MAX_PER_TABLE:
            return False
        sch = _schema_of(f)
        return not (sch and schema_ct.get(sch, 0) >= max_per_schema)

    def _take(f):
        chosen.append(f)
        lens_ct[f.lens] = lens_ct.get(f.lens, 0) + 1
        if f.table:
            table_ct[f.table] = table_ct.get(f.table, 0) + 1
        sch = _schema_of(f)
        if sch:
            schema_ct[sch] = schema_ct.get(sch, 0) + 1
        c = _cut(f)
        if c:
            cut_ct[c] = cut_ct.get(c, 0) + 1

    # pass 1 — the single most-notable fact of each lens (guarantees breadth of TYPES)
    seen_lens: set = set()
    for f in facts:
        if f.lens in seen_lens or not (_semantic_ok(f) and _source_ok(f)):
            continue
        _take(f)
        seen_lens.add(f.lens)
        if len(chosen) >= limit:
            return chosen
    # pass 2 — fill by score under ALL caps (semantic + source diversity)
    for f in facts:
        if f in chosen or not (_semantic_ok(f) and _source_ok(f)):
            continue
        _take(f)
        if len(chosen) >= limit:
            return chosen
    # pass 3 — a narrow schema can't satisfy the source caps; fill the remaining slots by
    # score under the SEMANTIC caps only, so the tour still reaches `limit` rather than
    # returning a stub. (On a wide schema passes 1–2 already filled it, so this is a no-op.)
    for f in facts:
        if f in chosen or not _semantic_ok(f):
            continue
        _take(f)
        if len(chosen) >= limit:
            break
    return chosen


def build_overview(conn, connection_id: str, tables: list, *, schema: str = "",
                   entity_hint: str = "rows", limit: int = 8,
                   now: Optional[str] = None, priors: Optional[dict] = None) -> OverviewReport:
    """Profile the scoped tables and return a diverse, notability-ranked fact tour.

    Deterministic and bounded: one ``SUMMARIZE`` per table (zero further SQL for the
    scale / distribution / coverage lenses) plus at most ``_MAX_PROBES`` group-by scans
    for concentration/outlier/composition/relationship. ``tables`` are bare names;
    ``schema`` qualifies them for SQL. Never raises — a failed probe degrades to fewer
    facts, never an error on the answer path.

    ``priors`` (``{"lens": {name: n}, "table": {name: n}}`` from ``overview.drills``) folds
    the connection's drill history into a BOUNDED notability nudge before selection, so the
    tour learns which facts this user explores. Omit it (the default) for the pure
    deterministic tour."""
    def _qual(t: str) -> str:
        return t if ("." in t or not schema) else f"{schema}.{t}"
    qualified = [_qual(t) for t in tables]

    try:
        tprofiles, cprofiles = _profile(conn, qualified)
    except Exception:
        tprofiles, cprofiles = {}, {}

    by_table: dict = {}
    for c in cprofiles:
        by_table.setdefault(getattr(c, "table", ""), {})[getattr(c, "column", "")] = c

    # largest tables first — that's where the material facts concentrate
    ranked = sorted(tprofiles.items(), key=lambda kv: getattr(kv[1], "row_count", 0) or 0,
                    reverse=True)[:_MAX_TABLES]

    candidates: list = []
    candidates += _lens_scale(tprofiles, entity_hint)
    candidates += _lens_distribution(by_table)

    # R15 — the named-outlier-entity lens rides the same probe budget (one extra
    # probe per table). Flag read once; off = byte-identical tour.
    from aughor.kernel.flags import flag_enabled
    _decision_grade = flag_enabled("lens.decision_grade")

    probes = 0
    touched: set = set()
    for table, tp in ranked:
        if probes >= _MAX_PROBES:
            break
        cols = list(by_table.get(table, {}).values())
        if not cols:
            continue
        got = _lens_group_probes(conn, table, cols, tp)
        if got:
            touched.add(table)
            candidates += got
        probes += min(_MAX_DIMS_PER_TABLE, len(_material_dims(cols)))
        if _decision_grade and probes < _MAX_PROBES:
            named = _lens_named_outlier(conn, table, cols, tp)
            if named:
                touched.add(table)
                candidates += named
            probes += 1

    candidates += _lens_coverage(by_table, tprofiles, touched)

    _apply_priors(candidates, priors)     # learned per-connection nudge (no-op without a prior)
    facts = _select(candidates, limit)
    return OverviewReport(
        facts=facts,
        summary=(f"{len(facts)} notable facts across {len(touched) or len(ranked)} of "
                 f"{len(tprofiles)} tables — concentration, outliers, spread, coverage and more."),
        tables_seen=len(touched) or len(ranked),
        tables_total=len(tprofiles),
        generated_at=now or "",
    )
