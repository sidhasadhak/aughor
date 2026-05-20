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
    from hermes.db.connection import DatabaseConnection


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

_NUMERIC_TYPES = re.compile(
    r"\b(INT|INTEGER|BIGINT|SMALLINT|TINYINT|HUGEINT|FLOAT|DOUBLE|"
    r"DECIMAL|NUMERIC|REAL|NUMBER)\b",
    re.IGNORECASE,
)
_TIMESTAMP_TYPES = re.compile(
    r"\b(TIMESTAMP|DATE|DATETIME|TIMESTAMPTZ|TIMESTAMP WITH TIME ZONE)\b",
    re.IGNORECASE,
)
_BOOL_TYPES = re.compile(r"\b(BOOLEAN|BOOL|BIT)\b", re.IGNORECASE)
_TEXT_TYPES = re.compile(r"\b(VARCHAR|TEXT|STRING|CHAR|BPCHAR)\b", re.IGNORECASE)


# ── Result dataclasses (lightweight — no Pydantic to keep import cost low) ───

class ColumnProfile:
    __slots__ = (
        "table", "column", "dtype",
        "semantic_type",
        "null_rate", "distinct_count", "is_low_cardinality",
        "value_range",        # (min, max) for measures
        "value_interpretation",  # "fraction 0-1", "currency", "count", "duration_days"
        "unit",               # "percent_fraction", "USD", "count", "days"
        "top_values",         # for dimensions: most frequent values
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
        is_fk: bool = False,
    ):
        self.table = table
        self.column = column
        self.dtype = dtype
        self.semantic_type = semantic_type
        self.null_rate = null_rate
        self.distinct_count = distinct_count
        self.is_low_cardinality = is_low_cardinality
        self.value_range = value_range
        self.value_interpretation = value_interpretation
        self.unit = unit
        self.top_values = top_values
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
        "grain_column", "grain_verified",
        "primary_timestamp", "date_range",
        "freshness_lag_hours",
        "computed_at",
    )

    def __init__(
        self,
        table: str,
        row_count: int = 0,
        grain_column: Optional[str] = None,
        grain_verified: bool = False,
        primary_timestamp: Optional[str] = None,
        date_range: Optional[tuple] = None,
        freshness_lag_hours: Optional[float] = None,
        computed_at: Optional[str] = None,
    ):
        self.table = table
        self.row_count = row_count
        self.grain_column = grain_column
        self.grain_verified = grain_verified
        self.primary_timestamp = primary_timestamp
        self.date_range = date_range
        self.freshness_lag_hours = freshness_lag_hours
        self.computed_at = computed_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        if isinstance(d.get("date_range"), tuple):
            d["date_range"] = list(d["date_range"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TableProfile":
        dr = d.get("date_range")
        if dr and isinstance(dr, list):
            d = {**d, "date_range": tuple(dr)}
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
                f'SELECT column_name, column_type FROM (DESCRIBE "{table}")',
            )
            if r.error or not r.rows:
                # Fallback: information_schema (works on DuckDB too)
                r = conn.execute(
                    "__profiler__",
                    f"SELECT column_name, data_type FROM information_schema.columns "
                    f"WHERE table_name = '{table}' ORDER BY ordinal_position",
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

    if is_fk or _KEY_PATTERN.search(col_lower):
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

def _q(name: str) -> str:
    """Quote an identifier."""
    return f'"{name}"'


def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_table_profile(
    conn: "DatabaseConnection",
    table: str,
    columns: list[tuple[str, str]],
    fk_cols: set[str],
) -> TableProfile:
    """
    Compute Tier 1 table-level statistics via 3–4 SQL queries.
    All queries are best-effort — failures produce partial profiles, not errors.
    """
    row_count = 0
    grain_column: Optional[str] = None
    grain_verified = False
    primary_timestamp: Optional[str] = None
    date_range: Optional[tuple] = None
    freshness_lag_hours: Optional[float] = None

    qt = _q(table)

    # ── 1. Row count ──────────────────────────────────────────────────────────
    r = conn.execute("__profiler__", f"SELECT COUNT(*) FROM {qt}")
    if not r.error and r.rows:
        try:
            row_count = int(r.rows[0][0])
        except (TypeError, ValueError):
            pass

    if row_count == 0:
        return TableProfile(table=table, row_count=0)

    # ── 2. Grain detection ────────────────────────────────────────────────────
    # Try PK-style candidates in priority order:
    # 1) column named exactly "{table}_id" or "{table[:-1]}_id"
    # 2) any column ending _id or _key with low cardinality expectation
    # 3) first column (last resort)
    col_names = [c for c, _ in columns]
    grain_candidates = []

    # Exact match: orders → order_id, customers → customer_id
    singular = table.rstrip("s")
    preferred = [f"{singular}_id", f"{table}_id", "id"]
    for pref in preferred:
        if pref in col_names:
            grain_candidates.insert(0, pref)
            break

    # All _id / _key columns
    for cn in col_names:
        if _KEY_PATTERN.search(cn.lower()) and cn not in grain_candidates:
            grain_candidates.append(cn)

    # Fallback: first column
    if col_names and col_names[0] not in grain_candidates:
        grain_candidates.append(col_names[0])

    for candidate in grain_candidates[:4]:  # try at most 4
        qc = _q(candidate)
        r2 = conn.execute(
            "__profiler__",
            f"SELECT COUNT(DISTINCT {qc}) FROM {qt}",
        )
        if not r2.error and r2.rows:
            try:
                distinct = int(r2.rows[0][0])
                if distinct == row_count:
                    grain_column = candidate
                    grain_verified = True
                    break
                elif grain_column is None:
                    grain_column = candidate  # best guess even if not verified
            except (TypeError, ValueError):
                pass

    # ── 3. Primary timestamp + date range ────────────────────────────────────
    ts_cols = [
        c for c, dtype in columns
        if _TIMESTAMP_TYPES.search(dtype)
        and not _KEY_PATTERN.search(c.lower())  # exclude FK-like timestamps
    ]

    if not ts_cols:
        # Try name heuristics on non-timestamp-typed columns (Postgres VARCHAR timestamps)
        ts_cols = [
            c for c, _ in columns
            if _TIMESTAMP_PATTERN.search(c.lower())
            and not _KEY_PATTERN.search(c.lower())
        ][:2]

    # Priority: created_at > order_date > first timestamp found
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
        qts = _q(primary_timestamp)
        try:
            r3 = conn.execute(
                "__profiler__",
                f"SELECT MIN({qts})::VARCHAR, MAX({qts})::VARCHAR FROM {qt}",
            )
            if not r3.error and r3.rows and r3.rows[0][0] is not None:
                min_d, max_d = str(r3.rows[0][0]), str(r3.rows[0][1])
                date_range = (min_d, max_d)

                # Freshness: how old is the latest record?
                try:
                    # Parse max_d into a datetime (best-effort)
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                        try:
                            max_dt = datetime.strptime(max_d[:19], fmt)
                            now = datetime.now()
                            lag = (now - max_dt).total_seconds() / 3600
                            freshness_lag_hours = round(lag, 1)
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass
        except Exception:
            pass

    return TableProfile(
        table=table,
        row_count=row_count,
        grain_column=grain_column,
        grain_verified=grain_verified,
        primary_timestamp=primary_timestamp,
        date_range=date_range,
        freshness_lag_hours=freshness_lag_hours,
    )


def build_column_profiles(
    conn: "DatabaseConnection",
    table: str,
    columns: list[tuple[str, str]],
    fk_cols: set[str],
    row_count: int,
) -> list[ColumnProfile]:
    """
    Compute column profiles for a table via 2 batched queries:
      1) One aggregate query covering null rates + distinct counts for ALL columns
      2) Top-values queries for low-cardinality string columns (up to 5 per table)

    Falls back gracefully if the batch query is too wide.
    """
    if not columns or row_count == 0:
        return []

    qt = _q(table)
    profiles: list[ColumnProfile] = []

    # ── Batch 1: null counts + distinct counts (all columns, one query) ───────
    # SELECT COUNT(col) / COUNT(DISTINCT col) for every column
    # For wide tables (>40 cols) we chunk to avoid query-size issues
    CHUNK = 30
    col_chunks = [columns[i: i + CHUNK] for i in range(0, len(columns), CHUNK)]

    raw_stats: dict[str, dict] = {}  # col_name → {non_null, distinct}

    for chunk in col_chunks:
        selects = []
        for col, _ in chunk:
            qc = _q(col)
            selects.append(f"COUNT({qc}) AS _nn_{col}")
            selects.append(f"COUNT(DISTINCT {qc}) AS _dc_{col}")
        sql = f"SELECT {', '.join(selects)} FROM {qt}"
        r = conn.execute("__profiler__", sql)
        if r.error or not r.rows:
            # Per-column fallback (slower but robust)
            for col, _ in chunk:
                qc = _q(col)
                r2 = conn.execute(
                    "__profiler__",
                    f"SELECT COUNT({qc}), COUNT(DISTINCT {qc}) FROM {qt}",
                )
                if not r2.error and r2.rows:
                    raw_stats[col] = {
                        "non_null": int(r2.rows[0][0] or 0),
                        "distinct": int(r2.rows[0][1] or 0),
                    }
            continue

        row = r.rows[0]
        for i, (col, _) in enumerate(chunk):
            try:
                raw_stats[col] = {
                    "non_null": int(row[i * 2] or 0),
                    "distinct": int(row[i * 2 + 1] or 0),
                }
            except (IndexError, TypeError):
                pass

    # ── Batch 2: value range for numeric columns (one query per table) ────────
    numeric_cols = [
        (col, dtype) for col, dtype in columns
        if _NUMERIC_TYPES.search(dtype) and not _KEY_PATTERN.search(col.lower())
    ]

    value_ranges: dict[str, tuple] = {}
    if numeric_cols:
        selects = []
        for col, _ in numeric_cols[:20]:  # cap at 20 to keep query manageable
            qc = _q(col)
            selects.append(f"MIN({qc})::DOUBLE AS _lo_{col}, MAX({qc})::DOUBLE AS _hi_{col}")
        sql = f"SELECT {', '.join(selects)} FROM {qt}"
        r = conn.execute("__profiler__", sql)
        if not r.error and r.rows:
            row = r.rows[0]
            for i, (col, _) in enumerate(numeric_cols[:20]):
                try:
                    lo = _safe_float(row[i * 2])
                    hi = _safe_float(row[i * 2 + 1])
                    if lo is not None and hi is not None:
                        value_ranges[col] = (lo, hi)
                except (IndexError, TypeError):
                    pass

    # ── Batch 3: top values for low-cardinality string/dimension columns ──────
    top_values_map: dict[str, list[str]] = {}
    dim_candidates = [
        col for col, dtype in columns
        if _TEXT_TYPES.search(dtype) and not _KEY_PATTERN.search(col.lower())
        and raw_stats.get(col, {}).get("distinct", 9999) <= 30
    ][:5]  # at most 5 top-value queries per table

    for col in dim_candidates:
        qc = _q(col)
        r = conn.execute(
            "__profiler__",
            f"SELECT {qc}, COUNT(*) AS n FROM {qt} "
            f"WHERE {qc} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
        )
        if not r.error and r.rows:
            top_values_map[col] = [str(row[0]) for row in r.rows if row[0] is not None]

    # ── Assemble ColumnProfile objects ────────────────────────────────────────
    for col, dtype in columns:
        stats = raw_stats.get(col, {})
        non_null = stats.get("non_null", row_count)
        distinct = stats.get("distinct", 0)
        null_rate = max(0.0, 1.0 - (non_null / row_count)) if row_count > 0 else 0.0
        is_low_card = distinct <= 30
        vrange = value_ranges.get(col)
        is_fk = col in fk_cols or bool(_KEY_PATTERN.search(col.lower()))

        sem_type = _semantic_type(
            col, dtype, is_fk, distinct, row_count, null_rate, vrange
        )

        interp, unit = (None, None)
        if sem_type == "measure":
            interp, unit = _value_interpretation(col, vrange)

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
            is_fk=is_fk,
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

    Designed to run once at connection time. Typically < 2 s for schemas
    under 10 tables; capped at 20 tables with fact-table prioritisation.
    """
    table_profiles: dict[str, TableProfile] = {}
    column_profiles: dict[str, ColumnProfile] = {}

    # Prioritise likely fact tables so they're profiled even in large schemas.
    # _FACT_SIGNALS is derived from KB SQL templates at module load time.
    prioritised = sorted(
        tables,
        key=lambda t: (0 if _FACT_SIGNALS.match(t) else 1, t),
    )

    for table in prioritised[:20]:  # raised cap; fact tables always come first
        fk_cols = fk_hints.get(table, set())

        cols = _parse_columns(conn, table)
        if not cols:
            table_profiles[table] = TableProfile(table=table)
            continue

        tp = build_table_profile(conn, table, cols, fk_cols)
        table_profiles[table] = tp

        col_profs = build_column_profiles(conn, table, cols, fk_cols, tp.row_count)
        for cp in col_profs:
            column_profiles[f"{table}.{cp.column}"] = cp

    return table_profiles, column_profiles


# ── Schema context rendering ──────────────────────────────────────────────────

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

    for table, tp in sorted(table_profiles.items()):
        # Header line
        grain_str = ""
        if tp.grain_column:
            tick = " ✓" if tp.grain_verified else " ?"
            grain_str = f" | grain: {tp.grain_column}{tick}"
        date_str = ""
        if tp.date_range:
            date_str = f" | {tp.date_range[0][:10]} → {tp.date_range[1][:10]}"
        stale_warn = ""
        if tp.freshness_lag_hours is not None and tp.freshness_lag_hours > 72:
            stale_warn = f" ⚠ stale ({tp.freshness_lag_hours:.0f}h ago)"

        lines.append(
            f"  [PROFILE] {table} — {tp.row_count:,} rows{grain_str}{date_str}{stale_warn}"
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

            if cp.null_rate > 0.01:
                parts.append(f"| {cp.null_rate * 100:.0f}% null")

            if cp.value_range and cp.value_interpretation:
                lo, hi = cp.value_range
                parts.append(f"| range {lo:.2g}–{hi:.2g}")

            lines.append(" ".join(parts))

    return "\n".join(lines)
