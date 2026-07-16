"""
Schema profiler — Tier 1 (SQL-only, no LLM).

Runs a small set of aggregate queries against a live connection to produce
TableProfile and ColumnProfile objects. These describe the *shape* of the data
(grain, row counts, date ranges, null rates, cardinality, value ranges) rather
than just the DDL structure that schema_context already provides.

Profiles are computed once per (connection_id, schema_fingerprint) and cached.
They make every downstream prompt more accurate:
  - Planner knows grain before writing JOINs → avoids double-counting
  - Planner knows semantic type → correct aggregation functions
  - Scorer knows value interpretation → reads 0.2 as "20% discount" not "$0.20"
  - Decomposer knows date range → grounds hypotheses in real time windows

Design principles:
  - All computation is pure SQL — deterministic and trustworthy
  - Batch as aggressively as possible (one stats query per table, not per column)
  - Every query is best-effort: a failure skips that stat, not the whole profile
  - No LLM calls — those are Sprint 3 (Tier 2 inference from empirical corrections)
"""
from __future__ import annotations

import glob
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection


# ── Fact-table signal regex (auto-derived from KB SQL templates) ──────────────

_KB_DIR = Path(__file__).parent.parent.parent / "data" / "kb"

_FALLBACK_FACT_TERMS = (
    "order", "sale", "transaction", "revenue", "invoice", "payment",
    "purchase", "session", "event", "conversion", "return", "refund",
    "shipment", "delivery", "cart", "item", "line",
)

_FROM_JOIN = re.compile(r"\b(?:FROM|JOIN)\s+(\w+)\b", re.IGNORECASE)
_CTE_DEF   = re.compile(r"\b(\w+)\s+AS\s*\(", re.IGNORECASE)

# Table names whose leading stem is misleading — derived/aggregated views, not entities.
# e.g. "net_revenue_daily" → stem "net" would match "net_promoter_score" tables, etc.
_DERIVED_SUFFIXES = re.compile(
    r"_(daily|weekly|monthly|quarterly|annual|summary|metrics|stats|"
    r"report|view|agg|aggregated|snapshot|staging|stg|raw|temp|tmp|cte)$",
    re.IGNORECASE,
)
_STEM_BLOCKLIST = frozenset({
    "with", "net", "fin", "main", "daily", "base", "raw",
    "temp", "tmp", "stg", "ranked", "cohort", "final",
})


def _extract_sql_strings(obj) -> list[str]:
    """Recursively collect all string values from a nested JSON object."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out = []
        for v in obj.values():
            out.extend(_extract_sql_strings(v))
        return out
    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(_extract_sql_strings(item))
        return out
    return []


def _build_fact_signals() -> re.Pattern:
    """
    Scan every KB JSON file once and derive a set of real fact-table name stems:
      1. Collect table names after FROM / JOIN keywords across all KB SQL
      2. Subtract CTE aliases (defined via `<name> AS (`)
      3. Drop derived/aggregated table names (ending in _daily, _summary, etc.)
      4. Keep only names with 3+ references (noise filter)
      5. Extract the leading word-stem (up to first _ or digit); skip blocklisted stems
      6. Weight stems by reference count; keep those above a minimum share threshold

    Falls back to _FALLBACK_FACT_TERMS if the KB directory is missing or empty.
    """
    if not _KB_DIR.exists():
        stems = _FALLBACK_FACT_TERMS
    else:
        table_refs: Counter = Counter()
        cte_names: set[str] = set()

        for path in glob.glob(str(_KB_DIR / "*.json")):
            try:
                with open(path) as f:
                    entries = json.load(f)
            except Exception:
                continue
            if not isinstance(entries, list):
                continue
            for entry in entries:
                sql_strings = _extract_sql_strings(entry.get("sql_assets", []))
                sql_strings += _extract_sql_strings(entry.get("template", ""))
                for sql in sql_strings:
                    for name in _FROM_JOIN.findall(sql):
                        table_refs[name.lower()] += 1
                    for name in _CTE_DEF.findall(sql):
                        cte_names.add(name.lower())

        # Remove CTE aliases and derived/aggregated table names
        real_tables = {
            name: count
            for name, count in table_refs.items()
            if name not in cte_names
            and count >= 3
            and not _DERIVED_SUFFIXES.search(name)
        }

        if not real_tables:
            stems = _FALLBACK_FACT_TERMS
        else:
            # Extract leading word-stem (split on first _ or digit).
            # e.g. "order_items" → "order", "event_logs" → "event"
            stem_counts: Counter = Counter()
            for name, count in real_tables.items():
                stem = re.split(r"[_\d]", name)[0]
                if len(stem) >= 3 and stem not in _STEM_BLOCKLIST:
                    stem_counts[stem] += count

            # Keep stems that account for ≥ 0.3% of total reference weight
            total = sum(stem_counts.values())
            threshold = max(3, total * 0.003)
            candidates = [s for s, c in stem_counts.items() if c >= threshold]

            # Deduplicate: if both singular and plural form exist, keep the shorter one
            # e.g. "order" and "orders" → keep "order" (it's already a prefix of "orders")
            deduped: list[str] = []
            for s in sorted(candidates, key=len):
                if not any(s.startswith(kept) for kept in deduped):
                    deduped.append(s)
            stems = tuple(deduped) if deduped else _FALLBACK_FACT_TERMS

    pattern = r"^(" + "|".join(re.escape(s) for s in stems) + r")"
    return re.compile(pattern, re.IGNORECASE)


# Built once at module load — zero cost at runtime
_FACT_SIGNALS: re.Pattern = _build_fact_signals()


# ── Regex helpers ─────────────────────────────────────────────────────────────

_KEY_PATTERN = re.compile(
    r"(_id|_key|_code|_num|_number|_identifier|_pk|_uuid|_guid)$", re.IGNORECASE
)
# camelCase identifier suffixes — franchiseID, supplierID, customerID, eventGUID …
# The snake_case _KEY_PATTERN above misses these: lowercasing erases the boundary
# (franchiseID → "franchiseid", which has no "_id$"), so the id falls through to the
# numeric branch and is mis-typed as a "measure" (then needlessly distribution-profiled).
# The lookbehind requires a lowercase letter before the uppercase suffix, so plain words
# (valid, void, grid, solid, humid, rapid) never match. Checked against ORIGINAL case.
def is_key_like(name: str) -> bool:
    """Public: does this column name look like an identifier/key (snake_case OR
    camelCase)? The canonical id-detection — chart/guard code imports this instead
    of the private patterns."""
    return bool(_KEY_PATTERN.search(name or "") or _KEY_PATTERN_CAMEL.search(name or ""))


_KEY_PATTERN_CAMEL = re.compile(
    r"(?<=[a-z])(ID|Id|Key|Code|Num|Number|Identifier|UUID|Uuid|GUID|Guid|Pk|PK)$"
)
_TIMESTAMP_PATTERN = re.compile(
    r"(date|time|_at|_on|timestamp|created|updated|delivered|approved|"
    r"purchase|shipping|processed|modified|inserted|loaded)$",
    re.IGNORECASE,
)
_CURRENCY_PATTERN = re.compile(
    r"(price|amount|revenue|cost|profit|sales|spend|budget|value|"
    r"income|margin|earning|fee|charge|payment|total|subtotal)$",
    re.IGNORECASE,
)
_COUNT_PATTERN = re.compile(
    r"(quantity|qty|count|num|number|cnt|volume|units|items)$",
    re.IGNORECASE,
)
_DURATION_PATTERN = re.compile(
    r"(days|hours|minutes|seconds|duration|age|lag|lead|delay)$",
    re.IGNORECASE,
)
_FLAG_PATTERN = re.compile(
    r"^(is_|has_|was_|can_|should_|did_|allow|enabled|active|deleted|"
    r"verified|confirmed|flagged|blocked|archived)",
    re.IGNORECASE,
)
# Geographic / code-like numeric columns that should never be treated as measures.
# Matches: seller_zip_code_prefix, postal_code, geo_id, country_code, area_prefix …
_GEO_CODE_PATTERN = re.compile(
    r"(zip|postal|postcode|geo_|lat|lon|latitude|longitude|"
    r"country|city|state|region|province|prefecture|district)|_prefix$",
    re.IGNORECASE,
)

_NUMERIC_TYPES = re.compile(
    # `U?` covers DuckDB unsigned ints (UTINYINT/USMALLINT/UINTEGER/UBIGINT/UHUGEINT) —
    # ClickBench stores EventDate as USMALLINT, which the bare \bSMALLINT\b missed.
    r"\b(U?(?:TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|INT)|"
    r"FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL|NUMBER)\b",
    re.IGNORECASE,
)
_TIMESTAMP_TYPES = re.compile(
    r"\b(TIMESTAMP|DATE|DATETIME|TIMESTAMPTZ|TIMESTAMP WITH TIME ZONE)\b",
    re.IGNORECASE,
)
_BOOL_TYPES = re.compile(r"\b(BOOLEAN|BOOL|BIT)\b", re.IGNORECASE)
_TEXT_TYPES = re.compile(r"\b(VARCHAR|TEXT|STRING|CHAR|BPCHAR)\b", re.IGNORECASE)


def _select_timestamp_cols(columns: list[tuple[str, str]]) -> list[str]:
    """Columns usable as a table's primary timestamp, best first.

    Real DATE/TIMESTAMP-*typed* columns win. Only when there are none do we fall back to
    date-*named* columns — but never NUMERIC-typed ones: a date-named integer (ClickBench
    ``EventDate``::USMALLINT holding epoch-days, or a ``YYYYMMDD`` int) cannot be compared
    to a date literal and raises "USMALLINT vs DATE". Excluding it means the table gets no
    time window rather than an un-runnable date filter. ``columns`` is ``[(name, dtype)]``."""
    typed = [
        c for c, dtype in columns
        if _TIMESTAMP_TYPES.search(dtype or "") and not _KEY_PATTERN.search(c.lower())
    ]
    if typed:
        return typed
    return [
        c for c, dtype in columns
        if _TIMESTAMP_PATTERN.search(c.lower())
        and not _KEY_PATTERN.search(c.lower())
        and not _NUMERIC_TYPES.search(dtype or "")
    ][:2]


# ── Result dataclasses (lightweight — no Pydantic to keep import cost low) ───

class ColumnProfile:
    __slots__ = (
        "table", "column", "dtype",
        "semantic_type",
        "null_rate", "distinct_count", "is_low_cardinality",
        "value_range",        # (min, max) for measures
        # distribution shape for measures (the "shape of the numbers"):
        "mean", "stddev", "p25", "p50", "p75",
        "value_interpretation",  # "fraction 0-1", "currency", "count", "duration_days"
        "unit",               # "percent_fraction", "USD", "count", "days"
        "top_values",         # for dimensions: most frequent values
        "value_sample",       # high-card entity dims (30<distinct≤cap): the distinct set, for offline binding
        "is_fk",
    )

    def __init__(
        self,
        table: str,
        column: str,
        dtype: str,
        semantic_type: str,
        null_rate: float = 0.0,
        distinct_count: int = 0,
        is_low_cardinality: bool = False,
        value_range: Optional[tuple] = None,
        value_interpretation: Optional[str] = None,
        unit: Optional[str] = None,
        top_values: Optional[list[str]] = None,
        value_sample: Optional[list[str]] = None,
        is_fk: bool = False,
        mean: Optional[float] = None,
        stddev: Optional[float] = None,
        p25: Optional[float] = None,
        p50: Optional[float] = None,
        p75: Optional[float] = None,
    ):
        self.table = table
        self.column = column
        self.dtype = dtype
        self.semantic_type = semantic_type
        self.null_rate = null_rate
        self.distinct_count = distinct_count
        self.is_low_cardinality = is_low_cardinality
        self.value_range = value_range
        self.mean = mean
        self.stddev = stddev
        self.p25 = p25
        self.p50 = p50
        self.p75 = p75
        self.value_interpretation = value_interpretation
        self.unit = unit
        self.top_values = top_values
        self.value_sample = value_sample
        self.is_fk = is_fk

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d: dict) -> "ColumnProfile":
        vr = d.get("value_range")
        if vr and isinstance(vr, list):
            d = {**d, "value_range": tuple(vr)}
        obj = cls.__new__(cls)
        for k in cls.__slots__:
            setattr(obj, k, d.get(k))
        return obj


class TableProfile:
    __slots__ = (
        "table", "row_count",
        "grain_column", "grain_verified", "grain_columns",
        "primary_timestamp", "date_range",
        "effective_date_range",
        "n_periods", "trailing_partial", "time_grain",
        "freshness_lag_hours",
        "computed_at",
    )

    def __init__(
        self,
        table: str,
        row_count: int = 0,
        grain_column: Optional[str] = None,
        grain_verified: bool = False,
        grain_columns: Optional[list] = None,
        primary_timestamp: Optional[str] = None,
        date_range: Optional[tuple] = None,
        effective_date_range: Optional[tuple] = None,
        freshness_lag_hours: Optional[float] = None,
        computed_at: Optional[str] = None,
        n_periods: Optional[int] = None,
        trailing_partial: bool = False,
        time_grain: Optional[str] = None,
    ):
        self.table = table
        self.row_count = row_count
        self.grain_column = grain_column
        self.grain_verified = grain_verified
        # grain_columns = a PROVEN composite primary key (e.g. order_items at
        # (order_id, order_item_id)) when NO single column is unique. A separate signal
        # from grain_column/grain_verified (which stay single-column for their existing
        # consumers); surfaced in the planner-facing portrait so a composite-keyed fact
        # isn't mistaken for having a single PK (or its line-number key for a measure).
        self.grain_columns = grain_columns
        self.primary_timestamp = primary_timestamp
        # n_periods = number of populated months; trailing_partial = the most
        # recent month is far below typical volume (an INCOMPLETE period that
        # would otherwise read as a sharp drop — exclude it from trend/PoP).
        self.n_periods = n_periods
        self.trailing_partial = trailing_partial
        # time_grain = the analytical grain chosen from span + cadence
        # ("day"/"week"/"month"/…); None => temporal extent too thin for a trend.
        self.time_grain = time_grain
        # date_range = absolute (min, max) including outliers.
        self.date_range = date_range
        # effective_date_range = the DENSE region (min, max) where the bulk of
        # rows actually live, ignoring sparse stray rows.  A table whose real
        # data is 2016–2018 but has 3 stray 2020 rows has date_range ending in
        # 2020 yet effective_date_range ending in 2018 — so a "last 12 months"
        # window anchored on the effective max actually returns data.
        self.effective_date_range = effective_date_range
        self.freshness_lag_hours = freshness_lag_hours
        self.computed_at = computed_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        if isinstance(d.get("date_range"), tuple):
            d["date_range"] = list(d["date_range"])
        if isinstance(d.get("effective_date_range"), tuple):
            d["effective_date_range"] = list(d["effective_date_range"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TableProfile":
        patch = {}
        dr = d.get("date_range")
        if dr and isinstance(dr, list):
            patch["date_range"] = tuple(dr)
        edr = d.get("effective_date_range")
        if edr and isinstance(edr, list):
            patch["effective_date_range"] = tuple(edr)
        if patch:
            d = {**d, **patch}
        obj = cls.__new__(cls)
        for k in cls.__slots__:
            setattr(obj, k, d.get(k))
        return obj


# ── Column catalogue ──────────────────────────────────────────────────────────

def _parse_columns(conn: "DatabaseConnection", table: str) -> list[tuple[str, str]]:
    """Return [(col_name, dtype), ...] for a table."""
    try:
        if conn.dialect == "duckdb":
            # Wrap DESCRIBE in a subquery so it passes the SELECT-only validator
            r = conn.execute(
                "__profiler__",
                f'SELECT column_name, column_type FROM (DESCRIBE {table})',
            )
            if r.error or not r.rows:
                # Fallback: information_schema (works on DuckDB too)
                parts = table.split('.') if ('.' in table and not table.startswith('"')) else [None, table]
                schema_part = parts[0] if len(parts) > 1 else getattr(conn, "_schema_name", None)
                table_part = parts[-1]
                where = f"WHERE table_name = '{table_part}'"
                if schema_part:
                    where += f" AND table_schema = '{schema_part}'"
                r = conn.execute(
                    "__profiler__",
                    f"SELECT column_name, data_type FROM information_schema.columns "
                    f"{where} ORDER BY ordinal_position",
                )
            if r.error or not r.rows:
                return []
            return [(row[0], row[1]) for row in r.rows]
        else:
            schema_name = getattr(conn, "_schema_name", "public")
            r = conn.execute(
                "__profiler__",
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{table}' AND table_schema = '{schema_name}' "
                f"ORDER BY ordinal_position",
            )
            if r.error or not r.rows:
                return []
            return [(row[0], row[1]) for row in r.rows]
    except Exception:
        return []


# ── Semantic type inference (deterministic, no LLM) ──────────────────────────

def _semantic_type(
    col: str,
    dtype: str,
    is_fk: bool,
    distinct_count: int,
    row_count: int,
    null_rate: float,
    value_range: Optional[tuple],
) -> str:
    col_lower = col.lower()

    if is_fk or _KEY_PATTERN.search(col_lower) or _KEY_PATTERN_CAMEL.search(col):
        return "key"
    if _BOOL_TYPES.search(dtype):
        return "flag"
    if _FLAG_PATTERN.match(col_lower):
        return "flag"
    if _TIMESTAMP_TYPES.search(dtype):
        return "timestamp"
    if _NUMERIC_TYPES.search(dtype):
        # Low-range integers that aren't keys → likely ordinal or flag
        if distinct_count <= 2 and value_range and value_range[1] <= 1:
            return "flag"
        if distinct_count <= 10 and value_range:
            lo, hi = value_range
            if lo >= 0 and hi <= 10 and isinstance(hi, (int, float)) and hi == int(hi):
                return "ordinal"
        # Geo/postal/code columns that happen to be stored as integers — not measures
        if _GEO_CODE_PATTERN.search(col_lower):
            return "key"
        return "measure"
    if _TEXT_TYPES.search(dtype):
        cardinality = distinct_count / max(row_count, 1)
        if distinct_count <= 30 or cardinality < 0.02:
            return "dimension"
        return "text"
    return "unknown"


def _value_interpretation(col: str, value_range: Optional[tuple]) -> tuple[Optional[str], Optional[str]]:
    """
    Returns (interpretation_string, unit) for measure columns.
    Purely deterministic — range + column name heuristics, no LLM.
    """
    col_lower = col.lower()
    if value_range is None:
        return None, None

    lo, hi = value_range
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return None, None

    # Range 0–1 → almost certainly a fraction / percentage
    if 0 <= lo_f and hi_f <= 1.0:
        return "fraction 0–1 (likely percentage)", "percent_fraction"

    # Name-based heuristics
    if _CURRENCY_PATTERN.search(col_lower):
        return "currency amount", "USD"
    if _COUNT_PATTERN.search(col_lower):
        return "count", "count"
    if _DURATION_PATTERN.search(col_lower):
        return "duration", "days"

    return None, None


# ── Core profile builders ─────────────────────────────────────────────────────

_LARGE_TABLE_THRESHOLD = 500_000   # rows above which we skip full-scan queries
# Composite-PK detection needs a COUNT(DISTINCT a,b) scan (no catalog stat exists for a
# column PAIR). It's a ONE-TIME, cached, bounded cost (≤ _COMPOSITE_GRAIN_MAX_PROBES pairs,
# only when single-column detection already failed), so it runs on facts a bit larger than
# the single-column scan cap — but still bounded so a huge warehouse fact is skipped.
_COMPOSITE_GRAIN_MAX_ROWS = 5_000_000
_COMPOSITE_GRAIN_MAX_PROBES = 4
_SAMPLE_PCT            = 5          # % to sample for top-values on large tables

# ── High-cardinality entity-value samples (R5) ────────────────────────────────
# Low-card (≤30 distinct) dimensions get their values via top_values above. The
# "Mytheresa"-class entity columns (brands/merchants/categories) sit ABOVE that
# cap, so entity resolution used to live-probe the warehouse on every question.
# We persist the distinct set for string dimensions plausibly holding an entity
# NAME with 30 < distinct ≤ cap, so binding can happen offline. Columns above the
# cap (customer names, SKUs, free text) stay live-probe — the sample stays bounded.
_VALUE_SAMPLE_MAX_DISTINCT = 2000   # only persist a column's values when it has this many or fewer
_VALUE_SAMPLE_MAX_COLS     = 8      # cap entity-dim columns sampled per table (matches resolve's max_cols)
_ENTITY_DIM_RE = re.compile(
    r"(name|platform|brand|franchise|company|merchant|vendor|segment|category|"
    r"channel|region|country|city|store|entity|product|customer|owner|type|status|label)",
    re.IGNORECASE,
)


def _q(name: str) -> str:
    """Quote an identifier."""
    return f'"{name}"'


def _qt(table: str) -> str:
    """Quote a table identifier, handling schema.table format."""
    if '.' in table and not table.startswith('"'):
        parts = table.split('.')
        return '.'.join(f'"{p}"' for p in parts)
    return _q(table)


def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _robust_date_range(
    conn: "DatabaseConnection",
    qt: str,
    qts: str,
) -> Optional[tuple]:
    """Find the DENSE date region of a timestamp column, ignoring sparse outliers.

    Bins rows by month and keeps only the months whose row count clears a
    density floor (>= 25% of the median populated month, min 2 rows).  The
    returned (min, max) spans those dense months — so 3 stray rows in 2020 next
    to a real 2016–2018 body of data no longer drag the max into 2020.

    One cheap grouped scan; works on both DuckDB and Postgres (both support
    date_trunc).  Returns None when there isn't enough signal to be confident,
    in which case callers should fall back to the absolute date_range.
    """
    try:
        r = conn.execute(
            "__profiler__",
            f"SELECT date_trunc('month', {qts})::VARCHAR AS m, COUNT(*) AS c "
            f"FROM {qt} WHERE {qts} IS NOT NULL GROUP BY 1 ORDER BY 1",
        )
    except Exception:
        return None
    if r.error or not r.rows:
        return None

    months = [(str(row[0]), int(row[1])) for row in r.rows if row[0] is not None]
    if len(months) < 2:
        return None

    counts = sorted(c for _, c in months)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    floor = max(2, median * 0.25)

    dense = [m for m, c in months if c >= floor]
    if not dense:
        return None
    # If every month is already dense, the absolute range is fine — signal None
    # so the caller keeps date_range as-is.
    if len(dense) == len(months):
        return None
    return (min(dense), max(dense))


_GRAIN_DAYS = [
    ("year", 365.25), ("quarter", 91.31), ("month", 30.44),
    ("week", 7.0), ("day", 1.0), ("hour", 1.0 / 24), ("minute", 1.0 / 1440),
]


def _choose_grain(span_days, distinct_days):
    """Pick the analytical time grain from the data's actual SPAN and CADENCE.

    Returns (grain_name | None, n_periods). grain=None => the temporal extent is
    too thin for any trend (caller should analyse cross-sectionally instead).

    Principle: choose the COARSEST grain that still yields >= TARGET periods (so a
    baseline/trend has enough history without drowning in noise), but never finer
    than the data's native cadence (monthly snapshots can't be read daily).
    """
    TARGET, VIABLE = 12, 4
    if not span_days or span_days <= 0:
        return None, 0
    # Native cadence ≈ days between populated days. ~1 => daily-dense; large =>
    # sparse snapshots that only make sense at a coarse grain.
    cadence = (span_days / distinct_days) if distinct_days and distinct_days > 0 else 1.0
    # Resolution floor: don't pick a grain much finer than the cadence. Sub-day
    # grains only when the whole span is short (otherwise day is the floor).
    sub_day_ok = span_days < 3
    floor = max(cadence * 0.8, (1.0 / 24 if sub_day_ok else 1.0))
    allowed = [(n, d) for n, d in _GRAIN_DAYS if d >= floor] or [("day", 1.0)]
    for name, gd in allowed:          # coarse -> fine
        if span_days / gd >= TARGET:
            return name, int(span_days / gd)
    name, gd = allowed[-1]            # finest allowed grain
    n = int(span_days / gd)
    return (name if n >= VIABLE else None), n


def _span_days(date_range):
    try:
        a = datetime.fromisoformat(str(date_range[0])[:19].replace(" ", "T"))
        b = datetime.fromisoformat(str(date_range[1])[:19].replace(" ", "T"))
        return max(0.0, (b - a).total_seconds() / 86400.0)
    except Exception:
        return None


def _period_density(conn: "DatabaseConnection", qt: str, qts: str, date_range):
    """Return (grain, n_periods, trailing_partial) using a DATA-DERIVED grain.

    The grain is chosen from the span + cadence (see _choose_grain); n_periods is
    the count of populated buckets at that grain; trailing_partial flags an
    incomplete final bucket (would otherwise read as a sudden drop). grain=None
    means the temporal extent is too thin — analyse cross-sectionally.
    """
    if not date_range:
        return None, None, False
    span = _span_days(date_range)
    # Cadence signal: distinct populated calendar days (one cheap query).
    distinct_days = None
    try:
        r0 = conn.execute(
            "__profiler__",
            f"SELECT COUNT(DISTINCT date_trunc('day', {qts})) FROM {qt} WHERE {qts} IS NOT NULL",
        )
        if not r0.error and r0.rows and r0.rows[0][0] is not None:
            distinct_days = int(r0.rows[0][0])
    except Exception:
        pass
    grain, est = _choose_grain(span, distinct_days)
    if grain is None:
        return None, (distinct_days or None), False
    # Count populated buckets at the chosen grain + detect a partial trailing one.
    try:
        r = conn.execute(
            "__profiler__",
            f"SELECT date_trunc('{grain}', {qts})::VARCHAR AS p, COUNT(*) AS c "
            f"FROM {qt} WHERE {qts} IS NOT NULL GROUP BY 1 ORDER BY 1",
        )
    except Exception:
        return grain, est, False
    if r.error or not r.rows:
        return grain, est, False
    buckets = [(str(row[0]), int(row[1])) for row in r.rows if row[0] is not None]
    if len(buckets) < 3:
        return grain, (len(buckets) or None), False
    counts = sorted(c for _, c in buckets)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    trailing_partial = bool(buckets[-1][1] < 0.5 * median)
    return grain, len(buckets), trailing_partial


# ── Catalog-based stats (zero full-table scans) ───────────────────────────────

def _catalog_stats_duckdb(
    conn: "DatabaseConnection",
    table: str,
    schema: Optional[str] = None,
) -> tuple[Optional[int], dict]:
    """
    DuckDB: pull row count from duckdb_tables() and per-column stats from SUMMARIZE.
    Returns (row_count, {col: {approx_unique, null_pct, min, max, q25, q50, q75}}).
    Zero full-table scans — both queries read only catalog metadata.
    """
    # If table is schema.table, split it (embedded schema wins over passed schema)
    if '.' in table and not table.startswith('"'):
        parts = table.split('.')
        schema = parts[0]
        table = parts[1]

    # ── Row count from catalog ────────────────────────────────────────────────
    if schema:
        rc_sql = (
            f"SELECT estimated_size FROM duckdb_tables() "
            f"WHERE table_name = '{table}' AND schema_name = '{schema}'"
        )
    else:
        rc_sql = (
            f"SELECT estimated_size FROM duckdb_tables() "
            f"WHERE table_name = '{table}' "
            f"AND schema_name NOT IN ('information_schema','pg_catalog','temp')"
        )
    row_count: Optional[int] = None
    r = conn.execute("__profiler__", rc_sql)
    if not r.error and r.rows and r.rows[0][0] is not None:
        try:
            row_count = int(r.rows[0][0])
        except (TypeError, ValueError):
            pass

    # ── SUMMARIZE — one query, all column stats ───────────────────────────────
    qt = _qt(f'{schema}.{table}' if schema else table)
    sum_sql = f"SELECT * FROM (SUMMARIZE {qt})"
    col_stats: dict = {}
    r2 = conn.execute("__profiler__", sum_sql)
    if not r2.error and r2.rows and r2.columns:
        # DuckDB SUMMARIZE columns vary by version; map by name
        col_idx = {c.lower(): i for i, c in enumerate(r2.columns)}
        def _get(row, key, fallback=None):
            idx = col_idx.get(key)
            return row[idx] if idx is not None else fallback

        for row in r2.rows:
            col_name = _get(row, "column_name") or _get(row, "column_id")
            if not col_name:
                continue
            count_val = _get(row, "count")          # non-null count (string in some versions)
            try:
                count_int = int(float(str(count_val))) if count_val is not None else None
            except (TypeError, ValueError):
                count_int = None
            # If row_count still unknown, estimate from non-null count + null_pct
            null_pct_raw = _get(row, "null_percentage")
            null_pct = None
            try:
                null_pct = float(str(null_pct_raw)) if null_pct_raw is not None else 0.0
            except (TypeError, ValueError):
                null_pct = 0.0
            if row_count is None and count_int is not None and null_pct is not None and null_pct < 100:
                try:
                    row_count = int(count_int / max(1e-6, 1.0 - null_pct / 100.0))
                except (ZeroDivisionError, OverflowError):
                    pass

            col_stats[str(col_name)] = {
                "approx_unique": _safe_int(_get(row, "approx_unique")),
                "null_pct":      null_pct,   # 0–100
                "min":           _get(row, "min"),
                "max":           _get(row, "max"),
                "avg":           _safe_float(_get(row, "avg")),
                "std":           _safe_float(_get(row, "std")),
                "q25":           _safe_float(_get(row, "q25")),
                "q50":           _safe_float(_get(row, "q50")),
                "q75":           _safe_float(_get(row, "q75")),
                "count":         count_int,
            }

    return row_count, col_stats


def _catalog_stats_postgres(
    conn: "DatabaseConnection",
    table: str,
    schema: str = "public",
) -> tuple[Optional[int], dict]:
    """
    PostgreSQL: row count from pg_class.reltuples (zero scan),
    column stats from pg_stats (pre-computed by autovacuum, zero scan).
    Returns (row_count_estimate, {col: {null_frac, n_distinct, top_vals, val_min, val_max}}).
    """
    # If table is schema.table, split it (embedded schema wins)
    if '.' in table and not table.startswith('"'):
        parts = table.split('.')
        schema = parts[0]
        table = parts[1]

    # ── Row count estimate from catalog ──────────────────────────────────────
    row_count: Optional[int] = None
    r = conn.execute(
        "__profiler__",
        f"SELECT reltuples::bigint FROM pg_class c "
        f"JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE c.relname = '{table}' AND n.nspname = '{schema}'",
    )
    if not r.error and r.rows and r.rows[0][0] is not None:
        try:
            row_count = max(0, int(r.rows[0][0]))
        except (TypeError, ValueError):
            pass

    # ── pg_stats — null_frac, n_distinct, most_common_vals ───────────────────
    r2 = conn.execute(
        "__profiler__",
        f"SELECT attname, null_frac, n_distinct, "
        f"most_common_vals::text, histogram_bounds::text "
        f"FROM pg_stats WHERE tablename = '{table}' AND schemaname = '{schema}'",
    )
    col_stats: dict = {}
    if not r2.error and r2.rows:
        for row in r2.rows:
            col_name, null_frac, n_dist_raw, mcv_text, hist_text = row
            if not col_name:
                continue

            # n_distinct: -1=unique, negative fraction, positive=absolute count
            n_distinct: Optional[int] = None
            if n_dist_raw is not None:
                nd = float(n_dist_raw)
                if nd == -1.0:
                    n_distinct = -1          # sentinel: column is unique
                elif nd < 0:
                    # fraction of row_count; resolve later when row_count known
                    n_distinct = nd          # store as float sentinel
                else:
                    n_distinct = int(nd)

            # Parse most_common_vals: "{val1,val2,...}" postgres text array
            top_vals: list[str] = []
            if mcv_text:
                inner = mcv_text.strip("{}")
                if inner:
                    top_vals = [v.strip('"') for v in inner.split(",")][:10]

            # Min/max from histogram bounds (first and last bucket boundary)
            val_min = val_max = None
            if hist_text:
                inner = hist_text.strip("{}")
                if inner:
                    bounds = inner.split(",")
                    if bounds:
                        val_min = bounds[0].strip('"')
                        val_max = bounds[-1].strip('"')

            col_stats[col_name] = {
                "null_frac":  float(null_frac) if null_frac is not None else 0.0,
                "n_distinct": n_distinct,
                "top_vals":   top_vals,
                "val_min":    val_min,
                "val_max":    val_max,
            }

    return row_count, col_stats


def _safe_int(v) -> Optional[int]:
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return None


def build_table_profile(
    conn: "DatabaseConnection",
    table: str,
    columns: list[tuple[str, str]],
    fk_cols: set[str],
    fast_stats: Optional[dict] = None,   # pre-fetched catalog stats for this table
    row_count_hint: Optional[int] = None,
) -> TableProfile:
    """
    Compute Tier 1 table-level statistics.

    Uses DB-native catalog stats (fast_stats) when available — zero full-table
    scans.  Falls back to COUNT(*) only for databases / versions where catalog
    stats are missing or stale (e.g. a table never ANALYZEd on Postgres).
    """
    row_count: int = row_count_hint or 0
    grain_column: Optional[str] = None
    grain_verified = False
    primary_timestamp: Optional[str] = None
    date_range: Optional[tuple] = None
    effective_date_range: Optional[tuple] = None
    freshness_lag_hours: Optional[float] = None
    n_periods: Optional[int] = None
    trailing_partial: bool = False
    grain: Optional[str] = None

    qt = _qt(table)
    fast_stats = fast_stats or {}

    # ── 1. Row count ──────────────────────────────────────────────────────────
    # Use catalog estimate if we have one; fall back to COUNT(*) only when it's
    # genuinely missing (rare: table never vacuumed / fresh DuckDB without stats).
    if row_count == 0:
        r = conn.execute("__profiler__", f"SELECT COUNT(*) FROM {qt}")
        if not r.error and r.rows:
            try:
                row_count = int(r.rows[0][0])
            except (TypeError, ValueError):
                pass

    if row_count == 0:
        return TableProfile(table=table, row_count=0)

    # ── 2. Grain detection — prefer catalog distinct counts ───────────────────
    col_names = [c for c, _ in columns]
    grain_candidates = []
    singular = table.rstrip("s")
    preferred = [f"{singular}_id", f"{table}_id", "id"]
    for pref in preferred:
        if pref in col_names:
            grain_candidates.insert(0, pref)
            break
    for cn in col_names:
        if _KEY_PATTERN.search(cn.lower()) and cn not in grain_candidates:
            grain_candidates.append(cn)
    if col_names and col_names[0] not in grain_candidates:
        grain_candidates.append(col_names[0])

    for candidate in grain_candidates[:4]:
        # Try catalog stats first (no scan)
        cs = fast_stats.get(candidate, {})
        approx_u = cs.get("approx_unique") or cs.get("n_distinct")
        if approx_u is not None:
            try:
                distinct = int(approx_u)
            except (TypeError, ValueError):
                distinct = None
            if distinct is not None:
                if distinct == row_count or abs(distinct - row_count) <= max(1, row_count * 0.01):
                    grain_column = candidate
                    grain_verified = True
                    break
                elif grain_column is None:
                    grain_column = candidate
        else:
            # Catalog miss. On a small table an exact COUNT(DISTINCT) is cheap. On a LARGE
            # table the exact scan is too costly — but a HyperLogLog (approx_count_distinct,
            # one cheap pass) verifies uniqueness within ~1%, so a big table's PK is no longer
            # missed (was: skip entirely → grain left unverified). HLL is DuckDB-only; other
            # dialects keep the conservative skip.
            qc = _q(candidate)
            exact = row_count <= _LARGE_TABLE_THRESHOLD
            if exact:
                r2 = conn.execute("__profiler__", f"SELECT COUNT(DISTINCT {qc}) FROM {qt}")
            elif conn.dialect == "duckdb":
                r2 = conn.execute("__profiler__", f"SELECT approx_count_distinct({qc}) FROM {qt}")
            else:
                r2 = None
            if r2 is not None and not r2.error and r2.rows:
                try:
                    distinct = int(r2.rows[0][0])
                    # exact → equality. HLL (approx_count_distinct) is noisy in magnitude (DuckDB
                    # can over-estimate ~15%), but a PK's estimate is ≈row_count while a
                    # non-unique key's is far smaller — so test the RATIO, not an absolute delta.
                    is_unique = (distinct == row_count) if exact else (distinct >= row_count * 0.9)
                    if is_unique:
                        grain_column = candidate
                        grain_verified = True
                        break
                    elif grain_column is None:
                        grain_column = candidate
                except (TypeError, ValueError):
                    pass

    # ── 2b. Composite grain — no single column was unique; many facts are keyed by a
    # PAIR (parent FK × line/sequence col, e.g. order_items at (order_id, order_item_id)).
    # Probe the key-like candidates pairwise (bounded + cached) so the planner sees the true
    # grain rather than mistaking a line-number key for a single PK or a measure.
    grain_columns: Optional[list[str]] = None
    if not grain_verified and 0 < row_count <= _COMPOSITE_GRAIN_MAX_ROWS:
        key_like = [c for c in grain_candidates if _KEY_PATTERN.search(c.lower())]
        probes = 0
        for i in range(len(key_like)):
            if grain_columns or probes >= _COMPOSITE_GRAIN_MAX_PROBES:
                break
            for j in range(i + 1, len(key_like)):
                if probes >= _COMPOSITE_GRAIN_MAX_PROBES:
                    break
                a, b = key_like[i], key_like[j]
                probes += 1
                rc = conn.execute(
                    "__profiler__",
                    f"SELECT COUNT(*) FROM (SELECT DISTINCT {_q(a)}, {_q(b)} FROM {qt})",
                )
                distinct = _safe_float(rc.rows[0][0]) if (not rc.error and rc.rows) else None
                if distinct is not None and int(distinct) == row_count:
                    grain_columns = [a, b]   # proven one row per (a, b)
                    break

    # ── 3. Primary timestamp — use catalog min/max when available ─────────────
    ts_cols = _select_timestamp_cols(columns)

    def _ts_priority(col: str) -> int:
        c = col.lower()
        if c in ("created_at", "order_date", "event_date", "transaction_date"):
            return 0
        if c.endswith("_at") or c.endswith("_date"):
            return 1
        return 2

    ts_cols.sort(key=_ts_priority)

    if ts_cols:
        primary_timestamp = ts_cols[0]
        cs = fast_stats.get(primary_timestamp, {})
        ts_min = cs.get("min") or cs.get("val_min")
        ts_max = cs.get("max") or cs.get("val_max")

        if ts_min and ts_max:
            date_range = (str(ts_min), str(ts_max))
        else:
            # Catalog miss: run MIN/MAX (one cheap query, not a full scan on
            # indexed timestamp columns)
            qts = _q(primary_timestamp)
            try:
                r3 = conn.execute(
                    "__profiler__",
                    f"SELECT MIN({qts})::VARCHAR, MAX({qts})::VARCHAR FROM {qt}",
                )
                if not r3.error and r3.rows and r3.rows[0][0] is not None:
                    date_range = (str(r3.rows[0][0]), str(r3.rows[0][1]))
            except Exception:
                pass

        if date_range:
            max_d = date_range[1]
            try:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        max_dt = datetime.strptime(max_d[:19], fmt)
                        lag = (datetime.now() - max_dt).total_seconds() / 3600
                        freshness_lag_hours = round(lag, 1)
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

            # Robust dense-region bounds, ignoring sparse outlier rows that would
            # otherwise drag MAX(date) into a period with no real data.
            effective_date_range = _robust_date_range(conn, qt, _q(primary_timestamp))
            # Data-derived grain + period count + incomplete-trailing detection.
            grain, n_periods, trailing_partial = _period_density(conn, qt, _q(primary_timestamp), date_range)

    return TableProfile(
        table=table,
        row_count=row_count,
        grain_column=grain_column,
        grain_verified=grain_verified,
        grain_columns=grain_columns,
        primary_timestamp=primary_timestamp,
        date_range=date_range,
        effective_date_range=effective_date_range,
        freshness_lag_hours=freshness_lag_hours,
        n_periods=n_periods,
        trailing_partial=trailing_partial,
        time_grain=grain,
    )


def build_column_profiles(
    conn: "DatabaseConnection",
    table: str,
    columns: list[tuple[str, str]],
    fk_cols: set[str],
    row_count: int,
    fast_stats: Optional[dict] = None,   # pre-fetched catalog stats for this table
    index_config: Optional[dict[str, bool]] = None,   # R11 per-column `index` decisions
) -> list[ColumnProfile]:
    """
    Compute column profiles.

    Strategy:
      1. Drain per-column null_rate / distinct_count from catalog stats (zero scan).
      2. For columns missing from catalog, run a single batched scan query — but
         ONLY on tables below _LARGE_TABLE_THRESHOLD.  Above threshold, use
         TABLESAMPLE so the query stays cheap regardless of table size.
      3. Top-values: pulled from catalog (most_common_vals on Postgres, skipped on
         DuckDB SUMMARIZE).  For dimension columns still missing top-values, run a
         GROUP BY with TABLESAMPLE on large tables.
      4. Value ranges: from catalog min/max (SUMMARIZE / histogram_bounds).
         Scan-based MIN/MAX fired only for small tables missing catalog ranges.
    """
    if not columns or row_count == 0:
        return []

    qt = _qt(table)
    fast_stats = fast_stats or {}
    large = row_count > _LARGE_TABLE_THRESHOLD

    # ── Drain catalog stats ───────────────────────────────────────────────────
    raw_stats: dict[str, dict] = {}       # col → {non_null, distinct}
    value_ranges: dict[str, tuple] = {}   # col → (lo, hi)
    dist_map: dict[str, dict] = {}        # col → {mean, stddev, p25, p50, p75}
    top_values_map: dict[str, list[str]] = {}

    for col, dtype in columns:
        cs = fast_stats.get(col, {})
        if not cs:
            continue

        # null_rate from catalog
        if "null_pct" in cs:        # DuckDB SUMMARIZE: 0–100
            null_pct = float(cs["null_pct"] or 0)
            non_null = int(row_count * (1.0 - null_pct / 100.0))
        elif "null_frac" in cs:     # Postgres pg_stats: 0.0–1.0
            null_frac = float(cs["null_frac"] or 0)
            non_null = int(row_count * (1.0 - null_frac))
        else:
            non_null = row_count

        # distinct count from catalog
        raw_distinct = cs.get("approx_unique") or cs.get("n_distinct")
        if raw_distinct is not None and raw_distinct == -1:
            distinct = row_count   # unique column
        elif raw_distinct is not None and isinstance(raw_distinct, float) and raw_distinct < 0:
            distinct = max(1, int(abs(raw_distinct) * row_count))
        elif raw_distinct is not None:
            try:
                distinct = int(raw_distinct)
            except (TypeError, ValueError):
                distinct = 0
        else:
            distinct = 0

        raw_stats[col] = {"non_null": non_null, "distinct": distinct}

        # value range from catalog
        mn = cs.get("min") or cs.get("val_min")
        mx = cs.get("max") or cs.get("val_max")
        if mn is not None and mx is not None and _NUMERIC_TYPES.search(dtype):
            lo = _safe_float(mn)
            hi = _safe_float(mx)
            if lo is not None and hi is not None:
                value_ranges[col] = (lo, hi)

        # distribution shape from catalog (DuckDB SUMMARIZE already computes these)
        if _NUMERIC_TYPES.search(dtype) and not _KEY_PATTERN.search(col.lower()):
            d = {
                "mean":   cs.get("avg"),
                "stddev": cs.get("std"),
                "p25":    cs.get("q25"),
                "p50":    cs.get("q50"),
                "p75":    cs.get("q75"),
            }
            if any(v is not None for v in d.values()):
                dist_map[col] = d

        # top values from pg most_common_vals (already parsed)
        tvs = cs.get("top_vals")
        if tvs:
            top_values_map[col] = tvs

    # ── Columns missing from catalog: batch scan (sampled on large tables) ────
    missing_cols = [c for c, _ in columns if c not in raw_stats]
    if missing_cols:
        CHUNK = 30
        sample_clause = f" USING SAMPLE {_SAMPLE_PCT} PERCENT" if large else ""
        chunks = [missing_cols[i: i + CHUNK] for i in range(0, len(missing_cols), CHUNK)]
        for chunk in chunks:
            selects = []
            for col in chunk:
                qc = _q(col)
                selects.append(f"COUNT({qc}) AS _nn_{col}")
                selects.append(f"COUNT(DISTINCT {qc}) AS _dc_{col}")
            sql = f"SELECT {', '.join(selects)} FROM {qt}{sample_clause}"
            r = conn.execute("__profiler__", sql)
            if r.error or not r.rows:
                for col in chunk:
                    raw_stats[col] = {"non_null": row_count, "distinct": 0}
                continue
            row_data = r.rows[0]
            for i, col in enumerate(chunk):
                try:
                    nn  = int(row_data[i * 2] or 0)
                    dc  = int(row_data[i * 2 + 1] or 0)
                    # Scale up sampled counts
                    if large and _SAMPLE_PCT < 100:
                        factor = 100 / _SAMPLE_PCT
                        nn = min(row_count, int(nn * factor))
                        dc = min(row_count, int(dc * factor))
                    raw_stats[col] = {"non_null": nn, "distinct": dc}
                except (IndexError, TypeError):
                    raw_stats[col] = {"non_null": row_count, "distinct": 0}

    # ── Value ranges for numeric columns still missing ────────────────────────
    numeric_missing = [
        (col, dtype) for col, dtype in columns
        if _NUMERIC_TYPES.search(dtype)
        and not _KEY_PATTERN.search(col.lower())
        and col not in value_ranges
    ]
    if numeric_missing and not large:
        selects = []
        for col, _ in numeric_missing[:20]:
            qc = _q(col)
            selects.append(f"MIN({qc})::DOUBLE AS _lo_{col}, MAX({qc})::DOUBLE AS _hi_{col}")
        r = conn.execute("__profiler__", f"SELECT {', '.join(selects)} FROM {qt}")
        if not r.error and r.rows:
            row_data = r.rows[0]
            for i, (col, _) in enumerate(numeric_missing[:20]):
                try:
                    lo = _safe_float(row_data[i * 2])
                    hi = _safe_float(row_data[i * 2 + 1])
                    if lo is not None and hi is not None:
                        value_ranges[col] = (lo, hi)
                except (IndexError, TypeError):
                    pass

    # ── Top values for low-cardinality string columns still missing ───────────
    dim_missing = [
        col for col, dtype in columns
        if _TEXT_TYPES.search(dtype)
        and not _KEY_PATTERN.search(col.lower())
        and col not in top_values_map
        and raw_stats.get(col, {}).get("distinct", 9999) <= 30
    ][:5]

    for col in dim_missing:
        qc = _q(col)
        sample_clause = f" USING SAMPLE {_SAMPLE_PCT} PERCENT" if large else ""
        r = conn.execute(
            "__profiler__",
            f"SELECT {qc}, COUNT(*) AS n FROM {qt}{sample_clause} "
            f"WHERE {qc} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
        )
        if not r.error and r.rows:
            top_values_map[col] = [str(row[0]) for row in r.rows if row[0] is not None]

    # ── High-cardinality entity-value samples (R5) ────────────────────────────
    # For string dimensions plausibly holding an entity name with 30 < distinct ≤
    # cap, persist the distinct set so entity resolution can bind offline. The
    # distinct GATE (from raw_stats) bounds the scan; LIMIT cap+1 + the len check
    # drops any column that turns out larger than the cap (kept as live-probe only).
    value_sample_map: dict[str, list[str]] = {}

    def _index_eligible(col: str) -> bool:
        # R11: an explicit per-column config entry wins (human `index: true` can
        # widen past the name gate; `false` excludes); otherwise the deterministic
        # R5 gate — entity-name-ish and not key-like. The cardinality band below
        # stays a hard capture constraint either way (the sample must stay bounded).
        if index_config is not None and col in index_config:
            return index_config[col]
        return bool(
            not _KEY_PATTERN.search(col.lower()) and _ENTITY_DIM_RE.search(col.lower())
        )

    highcard_dims = [
        col for col, dtype in columns
        if _TEXT_TYPES.search(dtype)
        and _index_eligible(col)
        and 30 < raw_stats.get(col, {}).get("distinct", 0) <= _VALUE_SAMPLE_MAX_DISTINCT
    ][:_VALUE_SAMPLE_MAX_COLS]
    for col in highcard_dims:
        qc = _q(col)
        sample_clause = f" USING SAMPLE {_SAMPLE_PCT} PERCENT" if large else ""
        r = conn.execute(
            "__profiler__",
            f"SELECT DISTINCT CAST({qc} AS VARCHAR) AS v FROM {qt}{sample_clause} "
            f"WHERE {qc} IS NOT NULL LIMIT {_VALUE_SAMPLE_MAX_DISTINCT + 1}",
        )
        if not r.error and r.rows and len(r.rows) <= _VALUE_SAMPLE_MAX_DISTINCT:
            vals = [str(row[0]) for row in r.rows if row[0] is not None]
            if vals:
                value_sample_map[col] = vals

    # ── Assemble ColumnProfile objects ────────────────────────────────────────
    profiles: list[ColumnProfile] = []
    for col, dtype in columns:
        stats   = raw_stats.get(col, {})
        non_null = stats.get("non_null", row_count)
        distinct = stats.get("distinct", 0)
        null_rate = max(0.0, 1.0 - (non_null / row_count)) if row_count > 0 else 0.0
        is_low_card = distinct <= 30
        vrange  = value_ranges.get(col)
        is_fk   = col in fk_cols or bool(_KEY_PATTERN.search(col.lower()))

        sem_type = _semantic_type(col, dtype, is_fk, distinct, row_count, null_rate, vrange)

        interp, unit = (None, None)
        if sem_type == "measure":
            interp, unit = _value_interpretation(col, vrange)

        dist = dist_map.get(col, {})
        profiles.append(ColumnProfile(
            table=table,
            column=col,
            dtype=dtype,
            semantic_type=sem_type,
            null_rate=round(null_rate, 4),
            distinct_count=distinct,
            is_low_cardinality=is_low_card,
            value_range=vrange,
            value_interpretation=interp,
            unit=unit,
            top_values=top_values_map.get(col),
            value_sample=value_sample_map.get(col),
            is_fk=is_fk,
            mean=dist.get("mean"),
            stddev=dist.get("stddev"),
            p25=dist.get("p25"),
            p50=dist.get("p50"),
            p75=dist.get("p75"),
        ))

    return profiles


# ── Top-level entry point ─────────────────────────────────────────────────────

def profile_connection(
    conn: "DatabaseConnection",
    tables: list[str],
    fk_hints: dict[str, set[str]],  # {table: {col, col, ...}}
) -> tuple[dict[str, TableProfile], dict[str, ColumnProfile]]:
    """
    Profile all tables in `tables`. Returns:
      table_profiles:  {table_name: TableProfile}
      column_profiles: {"table.column": ColumnProfile}

    Strategy:
      1. Fetch DB-native catalog stats for every table upfront (one query per table):
         - DuckDB:   duckdb_tables() row count + SUMMARIZE per-column stats
         - Postgres: pg_class.reltuples row count + pg_stats per-column stats
      2. Pass `fast_stats` to build_table_profile() and build_column_profiles() so
         they skip full-table COUNT / COUNT(DISTINCT) / MIN / MAX scans.
      3. Falls back gracefully to scan-based stats for small tables or when catalog
         data is absent/stale.
    """
    table_profiles: dict[str, TableProfile] = {}
    column_profiles: dict[str, ColumnProfile] = {}
    dialect = getattr(conn, "dialect", "")

    # R11 — when the per-column config exists, its `index` flag decides value-sample
    # eligibility (human override wins; defaults mirror the R5 gate, so an unedited
    # config changes nothing). Flag-gated + lazy import so the profiler stays
    # import-light; any hiccup falls back to the built-in gate.
    index_cfg: dict[str, dict[str, bool]] = {}
    try:
        from aughor.kernel.flags import flag_enabled
        if flag_enabled("ontology.column_config"):
            from aughor.ontology.column_config import load_column_configs
            _cc_conn = getattr(conn, "_connection_id", None) or "fixture"
            _cc_schema = getattr(conn, "_schema_name", None) or "default"
            for (_t, _c), _fl in load_column_configs(_cc_conn, _cc_schema).items():
                index_cfg.setdefault(_t, {})[_c] = bool(_fl.index)
    except Exception:
        index_cfg = {}

    # ── Pre-fetch catalog stats for ALL tables (cheap, no full scans) ─────────
    # {table_name: (row_count, {col: {...stats...}})}
    all_catalog: dict[str, tuple[Optional[int], dict]] = {}
    for table in tables:
        try:
            if dialect == "duckdb":
                schema_name = getattr(conn, "schema_name", None)
                rc, col_stats = _catalog_stats_duckdb(conn, table, schema=schema_name)
            elif dialect == "postgres":
                schema_name = getattr(conn, "schema_name", None) or "public"
                rc, col_stats = _catalog_stats_postgres(conn, table, schema=schema_name)
            else:
                rc, col_stats = None, {}
            all_catalog[table] = (rc, col_stats)
        except Exception:
            all_catalog[table] = (None, {})

    # ── Prioritise likely fact tables so they're profiled even in large schemas ─
    prioritised = sorted(
        tables,
        key=lambda t: (0 if _FACT_SIGNALS.match(t) else 1, t),
    )

    for table in prioritised[:20]:
        fk_cols = fk_hints.get(table, set())
        catalog_rc, fast_stats = all_catalog.get(table, (None, {}))

        cols = _parse_columns(conn, table)
        if not cols:
            table_profiles[table] = TableProfile(table=table)
            continue

        tp = build_table_profile(
            conn, table, cols, fk_cols,
            fast_stats=fast_stats,
            row_count_hint=catalog_rc,
        )
        table_profiles[table] = tp

        col_profs = build_column_profiles(
            conn, table, cols, fk_cols, tp.row_count,
            fast_stats=fast_stats,
            index_config=index_cfg.get(table),
        )
        for cp in col_profs:
            column_profiles[f"{table}.{cp.column}"] = cp

    return table_profiles, column_profiles


# ── Schema context rendering ──────────────────────────────────────────────────

def detect_schema_quirks(
    table_profiles: dict[str, TableProfile],
    column_profiles: dict[str, ColumnProfile],
) -> list[str]:
    """
    Cross-table cardinality analysis: detect semantic ID mismatches that LLMs
    will silently get wrong without explicit guidance.

    Currently detects:
      Per-row ID columns — an *_id column whose distinct_count equals its table's
      row_count (every row has a unique value) while another column in the SAME
      table has lower cardinality, suggesting the per-row column is a session/
      transaction hash rather than a stable entity identifier.

    Returns a list of ⚠ warning strings ready to prepend to scan_context.
    """
    quirks: list[str] = []

    # Build lookup: table → {col_name → distinct_count}
    table_col_distinct: dict[str, dict[str, int]] = {}
    for key, cp in column_profiles.items():
        if "." not in key:
            continue
        tbl, col = key.split(".", 1)
        table_col_distinct.setdefault(tbl, {})[col] = cp.distinct_count or 0

    for table, tp in table_profiles.items():
        if not tp.row_count or tp.row_count < 100:
            continue  # too small to reason about reliably

        col_distinct = table_col_distinct.get(table, {})
        if not col_distinct:
            continue

        row_count = tp.row_count

        # Find *_id columns that are unique per row (likely per-transaction hashes)
        per_row_ids = [
            col for col, distinct in col_distinct.items()
            if col.lower().endswith("_id") and distinct == row_count
        ]
        # Find *_id columns with fewer distinct values (stable entity identifiers)
        stable_ids = [
            col for col, distinct in col_distinct.items()
            if col.lower().endswith("_id")
            and 0 < distinct < row_count
            and col not in per_row_ids
        ]

        for per_row_col in per_row_ids:
            # Only flag when there's a plausible stable alternative in the same table
            # e.g. orders.customer_id (99441 distinct = 99441 rows) alongside
            #      customer.customer_unique_id (96096 distinct < 99441 rows)
            candidates = []
            for stable_col in stable_ids:
                # Heuristic: share a common prefix (e.g. both start with "customer")
                stem = per_row_col.replace("_id", "")
                if stem and stable_col.startswith(stem):
                    candidates.append(stable_col)

            if candidates:
                stable_col = candidates[0]
                stable_distinct = col_distinct[stable_col]
                repeat_count = row_count - stable_distinct
                quirks.append(
                    f"⚠ SCHEMA QUIRK [{table}]: `{per_row_col}` is unique per row "
                    f"({row_count:,} distinct = {row_count:,} rows) — it is a "
                    f"per-transaction hash, NOT a stable entity identifier. "
                    f"Use `{stable_col}` instead ({stable_distinct:,} distinct → "
                    f"implies {repeat_count:,} rows share the same {stable_col}, "
                    f"i.e. repeat transactions exist). "
                    f"NEVER GROUP BY or COUNT DISTINCT on `{per_row_col}` to count "
                    f"unique entities — always use `{stable_col}`."
                )

    return quirks


def render_profile_annotations(
    table_profiles: dict[str, TableProfile],
    column_profiles: dict[str, ColumnProfile],
    relevant_tables: Optional[list[str]] = None,
) -> str:
    """
    Produce a compact profile block to append to schema_context.

    Format per table:
      [PROFILE] orders — 9,994 rows | grain: order_id ✓ | 2014-01-03 → 2017-12-30
        discount   measure   fraction 0–1 (likely percentage) | range 0.0–0.8 | 0% null
        status     dimension 4 values: Shipped, Pending, Canceled, Returned
        customer_id key      FK | 793 distinct
        order_date timestamp 2014-01-03 → 2017-12-30

    Kept intentionally compact — one line per column, token-budget-aware.
    Tables not in `relevant_tables` (when supplied) get summary line only.
    """
    if not table_profiles:
        return ""

    tables_to_detail = set(relevant_tables) if relevant_tables else set(table_profiles.keys())
    lines: list[str] = ["DATA PROFILES (computed from actual data — trust these over schema names):"]

    # Prepend any cross-table cardinality quirks before the per-table stats
    quirks = detect_schema_quirks(table_profiles, column_profiles)
    if quirks:
        lines.append("")
        lines.append("SCHEMA QUIRKS (auto-detected — read before writing any query):")
        for q in quirks:
            lines.append(f"  {q}")
        lines.append("")

    for table, tp in sorted(table_profiles.items()):
        # Header line
        grain_str = ""
        if getattr(tp, "grain_columns", None):
            grain_str = f" | grain: ({', '.join(tp.grain_columns)}) ✓"   # proven composite PK
        elif tp.grain_column:
            tick = " ✓" if tp.grain_verified else " ?"
            grain_str = f" | grain: {tp.grain_column}{tick}"
        date_str = ""
        if tp.date_range:
            date_str = f" | {tp.date_range[0][:10]} → {tp.date_range[1][:10]}"
            edr = getattr(tp, "effective_date_range", None)
            if edr and (edr[0][:10], edr[1][:10]) != (tp.date_range[0][:10], tp.date_range[1][:10]):
                date_str += f" (dense data {edr[0][:10]} → {edr[1][:10]}; outliers outside)"
        stale_warn = ""
        if tp.freshness_lag_hours is not None and tp.freshness_lag_hours > 72:
            stale_warn = f" ⚠ stale ({tp.freshness_lag_hours:.0f}h ago)"
        tg = getattr(tp, "time_grain", None)
        partial_warn = ""
        if getattr(tp, "trailing_partial", False):
            partial_warn = f" ⚠ last {tg or 'period'} PARTIAL (incomplete — exclude from trend/PoP)"
        period_str = ""
        if tg and tp.n_periods:
            period_str = f" · {tp.n_periods} {tg}{'s' if tp.n_periods != 1 else ''} of history"
        elif tp.date_range and tg is None:
            period_str = " · too few periods for a trend → analyse cross-sectionally"

        lines.append(
            f"  [PROFILE] {table} — {tp.row_count:,} rows{grain_str}{date_str}{period_str}{stale_warn}{partial_warn}"
        )

        # Column detail (only for relevant tables)
        if table not in tables_to_detail:
            continue

        col_profs = [
            cp for key, cp in sorted(column_profiles.items())
            if key.startswith(f"{table}.")
        ]

        for cp in col_profs:
            parts = [f"    {cp.column:<24} {cp.semantic_type:<10}"]

            if cp.value_interpretation:
                parts.append(cp.value_interpretation)
            elif cp.top_values:
                vals = ", ".join(cp.top_values[:6])
                parts.append(f"{cp.distinct_count} values: {vals}")
            elif cp.is_fk:
                parts.append(f"FK | {cp.distinct_count:,} distinct")
            elif cp.value_range and cp.semantic_type == "measure":
                parts.append(f"range {cp.value_range[0]:.2g}–{cp.value_range[1]:.2g}")

            # Null semantics (F3): distinguish a DEAD column (100% null), a STRUCTURAL
            # sparse column (populated only for a subset — a real attribute with ≥2 distinct
            # values among non-nulls, e.g. `shade` only for Makeup), and NOISE (one value
            # sprinkled across a few rows, e.g. a 95%-null `gift_message` with 1 distinct
            # value). Uses null_rate + distinct_count — both already computed, no extra scan.
            if cp.null_rate >= 0.999:
                parts.append("| ⚠ 100% NULL — dead column, exclude from analysis")
            elif cp.null_rate >= 0.80:
                if (cp.distinct_count or 0) >= 2:
                    parts.append(f"| {cp.null_rate * 100:.0f}% null — STRUCTURAL (populated for "
                                 f"a subset only; a real attribute for that subset, not noise)")
                else:
                    parts.append(f"| {cp.null_rate * 100:.0f}% null — NOISE (one value in a few "
                                 f"rows; low-signal, exclude as a dimension/finding)")
            elif cp.null_rate > 0.01:
                parts.append(f"| {cp.null_rate * 100:.0f}% null")

            if cp.value_range and cp.value_interpretation:
                lo, hi = cp.value_range
                parts.append(f"| range {lo:.2g}–{hi:.2g}")

            # Distribution shape (the "shape of the numbers") for measures — so the
            # agent can reason about typical-vs-extreme, outliers, and skew.
            if cp.semantic_type == "measure" and (getattr(cp, "p50", None) is not None or getattr(cp, "mean", None) is not None):
                dparts = []
                if cp.p50 is not None:  dparts.append(f"median {cp.p50:.3g}")
                if cp.mean is not None: dparts.append(f"avg {cp.mean:.3g}")
                if cp.p25 is not None and cp.p75 is not None:
                    dparts.append(f"IQR {cp.p25:.3g}–{cp.p75:.3g}")
                if dparts:
                    parts.append("| " + " · ".join(dparts))

            lines.append(" ".join(parts))

    return "\n".join(lines)
