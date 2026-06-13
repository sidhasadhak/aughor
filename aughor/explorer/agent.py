"""
SchemaExplorer — proactive, curiosity-driven background schema cartography.

Aughor connects to a database and immediately begins a background exploration:
one small SQL query at a time, rate-limited to avoid overloading the database,
pausing entirely whenever a user investigation is running.

The 5 exploration phases (building on profiler output for Phases 1 & 2):
  3. Null meaning resolution  — why is a column nullable? (pending vs missing)
  4. Join verification        — orphan checks + cardinality confirmation
  5. Lifecycle mapping        — state machine extraction for entity tables
  6. Distribution profiling   — shape characterisation for measure columns
  7. Cross-table patterns     — pre-computed analytical insights

Each query produces a (think, sql, observation) episode for SkyRL-SQL training.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

from aughor.explorer.models import (
    DistributionProfile,
    DistributionShape,
    ExplorationPhase,
    ExplorationStatus,
    JoinVerificationResult,
    LifecycleMap,
    LifecycleTransition,
    NullMeaning,
    NullMeaningResult,
    OntologyInsight,
)
from aughor.explorer import store as _store
from aughor.explorer.episodes import EpisodeCollector
from aughor.explorer.grounding import (
    GroundingResult,
    numeric_cells_block,
    verify_finding,
)

logger = logging.getLogger(__name__)

_RATE_SECONDS_SCHEMA = 0.0   # schema phases (3-7) run as fast as the DB allows
_RATE_SECONDS_INTEL  = 5.0   # domain intel phase runs at 1 query per 5 seconds
_COST_LARGE_ROWS     = 5_000_000  # Tier 3 — at/above this, prefer approximate aggregates

# State-value vocabulary for lifecycle classification
_TERMINAL = frozenset({
    "canceled", "cancelled", "returned", "closed", "archived", "failed",
    "rejected", "expired", "deleted", "churned", "lost", "void", "voided",
    "refunded", "bounced", "blocked",
    # "completed", "done", "delivered", "shipped" removed — these are
    # context-dependent (e.g. "shipped" is mid-flow in fulfillment).
    # Terminal classification is now advisory, not filtering.
})
_ACTIVE = frozenset({
    "active", "live", "running", "processing", "open", "pending", "approved",
    "in_progress", "inprogress", "scheduled", "confirmed", "new", "created",
    "placed", "accepted", "ready", "invoiced",
})

# Substring signals for heuristic state classification when exact match fails
_TERMINAL_SUBS = ("cancel", "fail", "reject", "expir", "close", "archiv", "delet", "return", "void", "refund", "churn")
_ACTIVE_SUBS   = ("pend", "process", "approv", "creat", "open", "activ", "run", "sched", "place", "accept", "new")


# ── Temporal scope — Tier 0: role-aware recency ───────────────────────────────────
# Anchor the analytical window's recency on the CONSENSUS TRAILING EDGE OF ACTIVITY
# among measure-bearing event/fact tables — never MAX(any date column). A calendar /
# date-dimension table holds one row per day far into the future and is uniformly dense
# (so effective_date_range == its full span); anchoring on the global MAX would push the
# window past the last real fact and every fact filter returns zero rows ("no data"
# briefings). See docs/ADAPTIVE_TEMPORAL_SCOPE.md §3.

_SENTINEL_MAX_YEAR = 9999
_SENTINEL_MIN_YEAR = 1900
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _profile_field(prof, name):
    """Read a field from a TableProfile/ColumnProfile that may be a dataclass or a dict."""
    if isinstance(prof, dict):
        return prof.get(name)
    return getattr(prof, name, None)


def _table_recency(prof):
    """Sentinel-filtered recency for a table — (YYYY-MM-DD, is_effective) or (None, False).
    Prefers the dense ``effective_date_range`` over the raw ``date_range``."""
    for key, is_eff in (("effective_date_range", True), ("date_range", False)):
        rng = _profile_field(prof, key)
        if rng and len(rng) >= 2 and _ISO_DATE.match(str(rng[1])):
            head = str(rng[1])[:10]
            try:
                year = int(head[:4])
            except ValueError:
                continue
            if year >= _SENTINEL_MAX_YEAR or year <= _SENTINEL_MIN_YEAR:
                continue  # 9999-12-31 / 1900-01-01 / epoch placeholder — not real activity
            return head, is_eff
    return None, False


def _table_has_measure(cols) -> bool:
    """True when the table has ≥1 additive measure column — what makes it an *activity*
    (fact/event) table rather than a calendar/dimension spine. Tolerates ``cols`` as a
    dict {name: profile} or a list of profiles, each a dataclass or a dict."""
    if not cols:
        return False
    vals = cols.values() if isinstance(cols, dict) else cols
    return any(_profile_field(c, "semantic_type") == "measure" for c in vals)


# A date dimension / calendar table runs across the *whole* date axis (often into the
# future, e.g. TPC-DS date_dim → 2100) and the profiler frequently mis-tags its integer
# date-part columns (d_year, d_moy, d_qoy…) as "measures" — which would wrongly admit it
# to the activity pool and push the window past all real facts. Catch it by name and by
# shape (its "measures" are overwhelmingly date-parts). See docs/ADAPTIVE_TEMPORAL_SCOPE.md §3,§7.
_CALENDAR_NAME_RE = re.compile(
    r"(?:^|[._])(date_dim|dim_date|dim_day|day_dim|d_date|time_dim|dim_time|calendar|dates?)(?:$|[._])",
    re.I,
)
_DATEPART_RE = re.compile(
    r"(year|month|moy|day|dom|dow|doy|quarter|qoy|qtr|week|woy|seq|fiscal|fy|holiday|weekend|season|date_sk|julian)",
    re.I,
)


def _col_name(c, key=None):
    """Best-effort column name from a profile (dataclass/dict) or its dict key."""
    return getattr(c, "column", None) or (c.get("column") if isinstance(c, dict) else None) or key


def _is_calendar_spine(table, cols) -> bool:
    """True when *table* is a calendar / date-dimension spine — by name (date_dim,
    dim_date, calendar…) or by shape (≥70% of its measure-tagged columns are date-parts).
    Such tables must be excluded from activity anchoring even when mis-tagged with measures."""
    base = str(table).split(".")[-1].lower()
    if _CALENDAR_NAME_RE.search(base):
        return True
    if not cols:
        return False
    items = cols.items() if isinstance(cols, dict) else [(None, c) for c in cols]
    measure_names = [
        _col_name(c, k) for k, c in items
        if _profile_field(c, "semantic_type") == "measure"
    ]
    measure_names = [n for n in measure_names if n]
    if len(measure_names) >= 4:
        dateparts = sum(1 for n in measure_names if _DATEPART_RE.search(n))
        if dateparts / len(measure_names) >= 0.7:
            return True
    return False


def _is_activity_table(table, cols) -> bool:
    """An *activity* (fact/event) table: measure-bearing and not a calendar spine."""
    return _table_has_measure(cols) and not _is_calendar_spine(table, cols)


def _days_between(a: str, b: str) -> int:
    """Absolute day gap between two ISO date strings; 0 on parse error."""
    try:
        return abs((datetime.fromisoformat(b[:10]) - datetime.fromisoformat(a[:10])).days)
    except (ValueError, TypeError):
        return 0


# When two activity tables share (nearly) the same trailing edge, the *core fact*
# (most rows) is the better anchor than a fresher-by-days peripheral table — a tiny
# `campaigns` (5K rows) ending the same day as a 6.4M-row `order_items` should not win.
_ANCHOR_RECENCY_TOLERANCE_DAYS = 45


def _anchor_activity(tp, cp=None):
    """Return ``(table, recency, is_effective)`` for the anchor activity table — the one
    whose trailing edge defines the window. Among measure-bearing tables whose recency is
    within ``_ANCHOR_RECENCY_TOLERANCE_DAYS`` of the latest, prefer the **core fact**
    (largest row_count): recency ties shouldn't hand the window to a small peripheral
    table. Falls back to all dated tables when no measures are detected. Returns
    ``(None, None, False)`` when nothing is usable."""
    activity, spine = [], []   # each: (recency, is_effective, table, row_count)
    for table, prof in (tp or {}).items():
        rec, is_eff = _table_recency(prof)
        if rec is None:
            continue
        rows = _profile_field(prof, "row_count") or 0
        (activity if _is_activity_table(table, (cp or {}).get(table)) else spine).append(
            (rec, is_eff, table, rows))
    pool = activity or spine
    if not pool:
        return None, None, False

    latest = max(r[0] for r in pool)
    # Tables effectively at the trailing edge (within tolerance of the latest recency).
    fresh = [r for r in pool if _days_between(r[0], latest) <= _ANCHOR_RECENCY_TOLERANCE_DAYS]
    # Among those, the core fact (most rows) wins; recency breaks any row-count tie.
    rec, is_eff, table, _rows = max(fresh, key=lambda r: (r[3], r[0]))
    return table, rec, is_eff


def _table_min(prof):
    """Sentinel-filtered earliest date for a table — 'YYYY-MM-DD' or None. Mirrors
    ``_table_recency`` on the range *start*, preferring the dense effective range."""
    for key in ("effective_date_range", "date_range"):
        rng = _profile_field(prof, key)
        if rng and len(rng) >= 2 and _ISO_DATE.match(str(rng[0])):
            head = str(rng[0])[:10]
            try:
                year = int(head[:4])
            except ValueError:
                continue
            if year >= _SENTINEL_MAX_YEAR or year <= _SENTINEL_MIN_YEAR:
                continue
            return head
    return None


def _role_aware_time_window(tp, cp=None, jmap=None, months: int = 12):
    """Choose the analytical window by anchoring recency on *activity* tables.

    Returns ``(start_iso, end_iso, discrepancy)`` where ``discrepancy`` is a list of
    ``(table, recency)`` for non-activity tables (calendar / dimension spines) whose
    dates extend *past* the chosen activity edge — a data-quality signal worth
    surfacing. Returns ``(None, None, [])`` when no usable, non-sentinel date range
    exists. ``jmap`` is accepted for a future join-graph in-degree refinement; the
    measure signal (``cp``) is the primary catch today.

    The window start is CLAMPED to the earliest fact across the activity tables:
    a dataset holding 17 days of history must not get a "last 12 months" window
    whose start pre-dates its first row by 11 months — the blind-window bug that
    framed a 1-month bakehouse dataset as a year of analysis.
    """
    from datetime import timedelta as _td

    _anchor, best_rec, best_eff = _anchor_activity(tp, cp)
    if best_rec is None:
        return None, None, []

    discrepancy = sorted(
        ((t, _table_recency(p)[0]) for t, p in (tp or {}).items()
         if not _is_activity_table(t, (cp or {}).get(t)) and (_table_recency(p)[0] or "") > best_rec),
        key=lambda x: x[1], reverse=True,
    )

    # Earliest fact among activity tables (fall back to any dated table) — the
    # honest lower bound for the window.
    _mins = [
        m for t, p in (tp or {}).items()
        if _is_activity_table(t, (cp or {}).get(t)) and (m := _table_min(p))
    ] or [m for p in (tp or {}).values() if (m := _table_min(p))]
    data_min = min(_mins) if _mins else None

    try:
        max_d = datetime.fromisoformat(best_rec)
        if best_eff:
            # an effective max is month-truncated — nudge forward to cover the final month
            max_d = max_d + _td(days=31)
        start_d = max_d - _td(days=round(months * 30.4375))
        start = start_d.strftime("%Y-%m-%d")
        if data_min and data_min > start:
            start = data_min
        return start, max_d.strftime("%Y-%m-%d"), discrepancy
    except (ValueError, TypeError):
        return None, None, []


def _window_for_tables(tp, cp, tables, months: int = 12):
    """Derive a time window from ONLY the given tables (bare or qualified names) —
    the per-dataset/per-domain view. On a multi-dataset connection the global window
    anchors on the freshest dataset; a domain living in a different dataset (e.g.
    17-day ``bakehouse.*`` beside 24-month ``ecommerce.*``) needs its own anchor and
    its own clamp. Returns ``(start, end)`` or ``None``."""
    if not tables:
        return None
    wanted = set()
    for t in tables:
        s = str(t)
        wanted.add(s.lower())
        wanted.add(s.split(".")[-1].lower())
    sub_tp = {
        t: p for t, p in (tp or {}).items()
        if t.lower() in wanted or t.split(".")[-1].lower() in wanted
    }
    if not sub_tp:
        return None
    sub_cp = {t: (cp or {}).get(t) for t in sub_tp}
    start, end, _ = _role_aware_time_window(sub_tp, sub_cp, None, months)
    return (start, end) if start and end else None


# A "no data" finding — the query matched nothing (all-NULL row from an empty join/filter)
# or the interpreter explicitly reported no data. These must not become insights: they're
# noise in the Briefing and, worse, become broken monitors when a user clicks Create Monitor.
_NO_DATA_RE = re.compile(
    r"(returned no data|no data (found|available|to report|for)|0 \w+ (were |was )?found|"
    r"null values for all|no rows (returned|found|matched)|query (failed|errored)|"
    r"no matching (rows|records|data)|empty result set)",
    re.I,
)


# A connection can hold several UNRELATED uploaded datasets, each landing in its own
# schema (e.g. a bakehouse CRM in `bakehouse.*` + an ecommerce store in `ecommerce.*`).
# They share no real key, so any join across them is a hallucination — exactly the
# `bakehouse.sales_customers ⋈ ecommerce.orders` garbage that produced a broken finding.
# "Dataset" = the schema path (everything before the table name). The inferred join map
# can't be trusted to separate them (it had a false-positive cross-schema edge), so the
# schema is the reliable boundary.

def _dataset_of(tbl: str) -> str:
    """Schema path of a (possibly qualified) table name; '' when unqualified."""
    parts = str(tbl).split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else ""


def _tables_in_sql(sql: str) -> set:
    """Real (non-CTE) qualified table names referenced by a SQL string. Best-effort."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql)
    except Exception:
        return set()
    cte_names = {(c.alias_or_name or "").lower() for c in tree.find_all(exp.CTE)}
    out = set()
    for t in tree.find_all(exp.Table):
        if (t.name or "").lower() in cte_names:
            continue
        parts = [p for p in (t.catalog, t.db, t.name) if p]
        if parts:
            out.add(".".join(parts))
    return out


def _crosses_datasets(sql: str) -> bool:
    """True when the SQL references real tables from ≥2 distinct schemas (datasets) — a
    join across unrelated uploaded datasets. Operates on the generated SQL's *qualified*
    table refs, so it works regardless of how the ontology stored source tables. Tables
    with no schema qualifier are ignored (they can't be cross-dataset)."""
    datasets = {_dataset_of(t) for t in _tables_in_sql(sql)}
    datasets.discard("")
    return len(datasets) > 1


def _is_degenerate_result(rows, finding_text: str = "") -> bool:
    """True when a Phase-8 result carries no real data — an all-NULL single/leading row
    (the filter/join matched nothing) or an interpretation that explicitly says so.

    High-precision by design: a legitimate ``COUNT(...) = 0`` returns 0 (not NULL), so
    real "zero X" findings survive; only genuinely empty results are dropped."""
    if rows:
        total = non_null = 0
        for r in rows[:5]:
            cells = list(r.values()) if isinstance(r, dict) else list(r)
            for c in cells:
                total += 1
                if c is not None:
                    non_null += 1
        if total > 0 and non_null == 0:
            return True
    return bool(finding_text and _NO_DATA_RE.search(finding_text))


_LITERAL_DIM_RE = re.compile(r"""['"][^'"]*['"]\s+AS\s+(\w+)""", re.IGNORECASE)


def _has_fabricated_dimension(sql: str) -> bool:
    """True when a query invents its dimension by aliasing a constant literal and
    grouping by it — e.g. ``SELECT 'Unknown' AS signup_source ... GROUP BY signup_source``.

    The model writes this when the real column doesn't exist, producing a vacuous
    single-group "breakdown" the narrator then presents as a real category ("the
    only channel represented"). High-precision: only fires when the SOLE grouping
    key is the constant — a real dimension alongside it is a legitimate breakdown.
    """
    if not sql:
        return False
    low = sql.lower()
    if "group by" not in low:
        return False
    gb = low.split("group by", 1)[1]
    gb = re.split(r"\b(order\s+by|having|limit|window|qualify)\b", gb, maxsplit=1)[0]
    keys = [k.strip() for k in gb.split(",") if k.strip()]
    if len(keys) != 1:
        return False  # another real dimension is present → legitimate breakdown
    key = keys[0]
    if key.startswith("'") or key.startswith('"'):
        return True  # GROUP BY 'literal'
    return any(m.group(1).lower() == key for m in _LITERAL_DIM_RE.finditer(sql))


def _clamp_novelty(v) -> int:
    """Novelty is a 1-5 score (see the interpret prompt). The LLM occasionally
    echoes a data magnitude into it — e.g. revenue 77568 lands in `novelty`, which
    then pins confidence at 95% (``0.4 + novelty*0.1`` capped) and lets a junk
    finding own the headline (novelty drives ranking). Clamp to the valid range."""
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return 3


# Per-grain mislabel (#6): a line-item-grain column averaged and presented as a
# per-ORDER / per-customer metric. True AOV = SUM(revenue)/COUNT(DISTINCT order);
# `AVG(oi.line_total) AS aov` averages LINE ITEMS, undercounting (the $467-vs-$1108
# mislabel). High-precision: keys off a line-grain column name inside AVG() that's
# then labelled (alias or narration) as an order/customer-level metric.
_LINE_GRAIN_COL = re.compile(r"line_?(total|amount|item|price|value|subtotal|qty|quantity)|item_(total|amount|price|qty)", re.I)
_PER_ORDER_LABEL = re.compile(r"\baov\b|average\s+order\s+value|avg_?order_?value|order_?value|per[\s_]order|per[\s_]customer|per[\s_]basket", re.I)


def _mislabeled_per_grain(sql: str, finding_text: str = "") -> bool:
    """True when SQL averages a line-item-grain column but the alias or the finding
    narrates it as a per-order/per-customer value — a semantic mislabel the numeric
    grounding can't catch (the averaged value is a real cell, just the wrong metric)."""
    if not sql:
        return False
    for m in re.finditer(r"AVG\s*\(([^)]*)\)(?:\s+AS\s+(\w+))?", sql, re.IGNORECASE):
        arg, alias = m.group(1), (m.group(2) or "")
        if _LINE_GRAIN_COL.search(arg) and (_PER_ORDER_LABEL.search(alias) or _PER_ORDER_LABEL.search(finding_text)):
            return True
    return False


# Semantic metric groups (#5). A repair that swaps a column from one group for a
# column in another changed WHAT is measured (revenue→cost), not just how. An LLM
# faithfulness check rates these "faithful" (cf. 5ba0fbe) — the deterministic
# column-group swap is the reliable signal, like the de-temporalisation guard.
_METRIC_GROUPS: "dict[str, re.Pattern[str]]" = {
    "revenue":  re.compile(r"revenue|gross_?sales|net_?sales|gmv|turnover|\bsales\b|total_amount|grand_total|line_total|amount_paid", re.I),
    "cost":     re.compile(r"\bcost|expense|spend|cogs|unit_cost|landed|purchase_price", re.I),
    "profit":   re.compile(r"profit|margin|markup|earnings|contribution", re.I),
    "discount": re.compile(r"discount|markdown|rebate|coupon|promo_amount", re.I),
    "price":    re.compile(r"unit_price|list_price|msrp|\bprice\b", re.I),
    "quantity": re.compile(r"\bqty\b|quantity|units?_sold|\bunits\b|volume", re.I),
}


def _semantic_metric_drift(original_sql: str, fixed_sql: str) -> bool:
    """True when a repair replaced a metric column with one of a DIFFERENT business
    meaning (revenue↔cost, price↔quantity …). Compares the metric-group membership
    of columns dropped vs added: a clean, disjoint group swap = the metric drifted."""
    if not original_sql or not fixed_sql:
        return False
    removed = _query_columns(original_sql) - _query_columns(fixed_sql)
    added = _query_columns(fixed_sql) - _query_columns(original_sql)
    if not removed or not added:
        return False

    def _groups(cols: "set[str]") -> "set[str]":
        return {g for c in cols for g, pat in _METRIC_GROUPS.items() if pat.search(c)}

    gr_removed, gr_added = _groups(removed), _groups(added)
    # Both sides name a metric, the meaning changed, and there is no overlap that
    # would mean the original metric is still present.
    return bool(gr_removed and gr_added and not (gr_removed & gr_added))


# Column/table names the SQL engine reported as nonexistent — harvested generically from
# DuckDB *and* Postgres binder errors and fed back to the question generator so it stops
# re-proposing the same hallucinated names (the dominant Phase-8 failure class: a generator
# that "expects" a region/campaign_id/touchpoint_id column the schema doesn't have). This is
# negative knowledge accumulated from the live engine — no schema or connection specifics.
# Ambiguous-column errors are deliberately NOT harvested: that column DOES exist, it just
# needs qualifying (handled by the repair diagnosis instead).
_DEAD_REF_RES = (
    re.compile(r'does not have a column named\s+"?(\w+)"?', re.I),
    re.compile(r'[Rr]eferenced column\s+"?(\w+)"?\s+not found', re.I),
    re.compile(r'column\s+"?(\w+)"?\s+does not exist', re.I),          # Postgres
    re.compile(r'[Rr]eferenced table\s+"?(\w+)"?\s+not found', re.I),
    re.compile(r'[Rr]elation\s+"?(\w+)"?\s+does not exist', re.I),     # Postgres
)


def _extract_dead_refs(error: str) -> set:
    """Nonexistent column/table names named in a SQL engine error (DuckDB + Postgres)."""
    out: set = set()
    for pat in _DEAD_REF_RES:
        out.update(pat.findall(error or ""))
    return out


# Coverage angles that inherently require a date/timestamp (aging, over-time, cohorts).
# Offering one on a domain with NO real timestamp forces the generator to invent a date
# column — the `invoice_date`-on-a-dateless-`invoices`-table hallucination. Substring-matched
# so checklist wording can vary. See _phase8 temporal-feasibility gate (#1).
_TEMPORAL_ANGLE_RE = re.compile(
    r"(trend|season|retention|lifecycle|cohort|churn|aging|recency|lead.?time|"
    r"growth|velocity|momentum|over.?time|time.?series|tenure)",
    re.I,
)


def _is_temporal_angle(angle: str) -> bool:
    """True when a coverage angle inherently needs a date/timestamp column."""
    return bool(_TEMPORAL_ANGLE_RE.search(angle or ""))


# Coverage angles that need a SPECIFIC KIND of column. Offering one when the
# domain has no matching column forces the generator to invent the dimension —
# the `'Unknown' AS signup_source` channel hallucination. Substring-matched on
# both the angle name (keys) and the available column names (patterns), so
# checklist/column wording can vary. See _phase8 column-feasibility gate (#1).
_ANGLE_REQUIRED_COLS: dict[str, "re.Pattern[str]"] = {
    "channel_mix":          re.compile(r"channel|source|medium|utm|referr|acqui", re.I),
    "attribution":          re.compile(r"channel|source|medium|utm|referr|attribut|touchpoint|campaign", re.I),
    "campaign_roi":         re.compile(r"campaign|utm|ad_|adset|spend|budget|cost", re.I),
    "conversion":           re.compile(r"conver|funnel|stage|status|step|visit|session|signup|lead", re.I),
    "experiments":          re.compile(r"experiment|variant|\bab_|test_group|bucket|treatment|cohort_group", re.I),
    "payment_behavior":     re.compile(r"payment|pay_|tender|method|installment|card|gateway|wallet", re.I),
    "refund_rate":          re.compile(r"refund|return|chargeback|cancel|reversal|dispute", re.I),
    "receivables":          re.compile(r"invoice|due|outstanding|receivable|balance|paid|payment_date|aging", re.I),
    "supplier_performance": re.compile(r"supplier|vendor|partner|on_time|delay|fulfil|deliver", re.I),
    "inventory_health":     re.compile(r"invent|stock|sku|quantity|on_hand|reorder|warehouse|backorder", re.I),
    "lead_times":           re.compile(r"lead.?time|deliver|ship|fulfil|expected|actual.?date|dispatch", re.I),
    "fulfillment":          re.compile(r"fulfil|ship|deliver|dispatch|status|tracking|warehouse", re.I),
}


def _angle_feasible(angle: str, columns: "set[str]") -> bool:
    """True unless the angle needs a column class entirely absent from the domain.

    Conservative: an angle with no specific column requirement is always feasible,
    and a present-but-oddly-named column is matched by the broad patterns — so a
    false drop (skipping a real angle) is rare, and far cheaper than a fabrication."""
    pat = _ANGLE_REQUIRED_COLS.get((angle or "").lower())
    if pat is None:
        return True
    return any(pat.search(c) for c in columns)


def _query_columns(sql: str) -> set:
    """Lowercased bare column names referenced by a SQL string (best-effort, via sqlglot).
    Used to tell a meaning-changing repair (one column SUBSTITUTED for another) apart from a
    benign one (a join added, or an alias qualified) — both of which preserve the columns."""
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql)
    except Exception:
        return set()
    return {(c.name or "").lower() for c in tree.find_all(exp.Column) if c.name}


# SQL that computes OVER TIME — a date/time function, INTERVAL, or a date literal. Used to
# catch a repair that silently DE-TEMPORALISES a time-based question (the invoice case: invoice
# AGE via DATE_DIFF on a date + a date-range filter, "repaired" into a plain payment-delay
# column). Deterministic and high-precision — no LLM judgement (an LLM rated that drift faithful).
_TEMPORAL_SQL_RE = re.compile(
    r"\b(date_?diff|datediff|date_?trunc|date_?part|date_?add|date_?sub|extract|strftime|"
    r"julian_?day|current_date|current_timestamp|interval)\b"
    r"|'\d{4}-\d{2}-\d{2}",   # a date literal like '2025-05-17'
    re.I,
)


def _has_temporal_sql(sql: str) -> bool:
    """True when SQL computes over time (date/time function, INTERVAL, or a date literal)."""
    return bool(_TEMPORAL_SQL_RE.search(sql or ""))


# A date-difference whose two date operands are IDENTICAL — DATE_DIFF(CURRENT_DATE,
# CURRENT_DATE) or DATE_DIFF(x.c, x.c) — is always 0. A repair on a dateless table that
# can't find a real date column sometimes fakes the time computation this way, keeping a
# temporal *shape* while answering nothing (so _has_temporal_sql alone won't flag it). The
# operand class excludes parens, so nested-call operands simply don't match (no false flag).
_VACUOUS_DATEDIFF_RE = re.compile(
    r"date_?diff\s*\(\s*(?:'[^']*'\s*,\s*)?(?P<a>[^,()]+?)\s*,\s*(?P<b>[^,()]+?)\s*\)",
    re.I,
)


def _has_vacuous_temporal(sql: str) -> bool:
    """True when a date-difference compares a value to itself → a constant-0 'time' metric."""
    for m in _VACUOUS_DATEDIFF_RE.finditer(sql or ""):
        a = re.sub(r"\s+", "", m.group("a")).lower()
        b = re.sub(r"\s+", "", m.group("b")).lower()
        if a == b:
            return True
    return False


def _ontology_skip_note(last_build: Optional[dict]) -> str:
    """An actionable 'why domain intelligence is empty' message, from the build outcome the
    connection recorded (which stage failed + why). Turns a silent empty Hub into a clear,
    retryable status. Falls back to a generic note when no build detail is available."""
    lb = last_build or {}
    stage, err = lb.get("stage"), lb.get("error")
    if stage and err:
        return f"Domain intelligence couldn't be built — {stage} failed: {err}"
    if stage:
        return f"Domain intelligence couldn't be built — the {stage} stage produced no object model."
    return (
        "Ontology unavailable — the object model that domain intelligence is "
        "derived from could not be built (the schema may be too sparse to model)."
    )


class SchemaExplorer:
    """
    Background schema exploration agent.

    Create one per connected database and schedule ``explore()`` as an
    asyncio task.  Call ``pause()`` / ``resume()`` to yield to investigations.
    """

    def __init__(
        self,
        connection_id: str,
        conn: "DatabaseConnection",
        canvas_id: Optional[str] = None,
        tables_filter: Optional[list[str]] = None,
    ) -> None:
        self.connection_id = connection_id
        self.canvas_id = canvas_id
        self.tables_filter = tables_filter  # non-empty list = restrict phases 3-7 to these tables
        self._conn = conn
        self._status = ExplorationStatus(
            connection_id=connection_id,
            canvas_id=canvas_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        # Canvas-scoped explorer uses a separate state/episode key
        _store_key = f"canvas_{canvas_id}" if canvas_id else connection_id
        self._store_key = _store_key
        self._episodes = EpisodeCollector(_store_key)
        self._can_run = asyncio.Event()
        self._can_run.set()
        self._stopped = False
        self._state = _store.load_canvas(canvas_id) if canvas_id else _store.load(connection_id)
        # Restore the time-to-first-insight milestone if this run is resuming a
        # prior one, so TTFI isn't re-stamped (and re-emitted) on every restart.
        self._status.first_insight_at = self._state.get("first_insight_at")
        self._last_query_at: float = 0.0
        self._rate_seconds: float = _RATE_SECONDS_SCHEMA
        self._time_window: Optional[tuple[str, str]] = None  # (start_iso, end_iso) — 12-month window
        self._dead_refs: set = set()  # column/table names the engine reported as nonexistent
        self._macro_context: Optional[dict] = None  # Tier 2 full-span long-arc rollup
        self._cost_large: bool = False               # Tier 3 — connection big enough for approx
        self._prev_watermark: Optional[str] = None   # Tier 3 — anchor edge at the last run

    # ── State persistence helpers ─────────────────────────────────────────────

    def _save_state(self) -> None:
        if self.canvas_id:
            _store.save_canvas(self.canvas_id, self._state)
        else:
            _store.save(self.connection_id, self._state)

    # ── External control ──────────────────────────────────────────────────────

    def _journal(self, kind: str, payload: dict | None = None) -> None:
        """Best-effort kernel-journal emit, scoped to this exploration — the
        event spine the UI subscribes to (K2). Never raises into the run."""
        try:
            from aughor.kernel.ledger import Ledger
            from aughor.kernel.jobs import current_job_id
            Ledger.default().emit(
                kind, payload or {},
                conn_id=self.connection_id, canvas_id=self.canvas_id,
                job_id=current_job_id(),
            )
        except Exception:
            logger.debug("journal emit failed (%s)", kind, exc_info=True)

    def _record_first_insight(self) -> None:
        """Stamp the time-to-first-insight milestone (B-6) on the first insight
        of the run. No-op after that, so a restart/resume never re-stamps. Emits
        an `exploration.first_insight` event carrying elapsed seconds so the
        connect→first-insight funnel is a query, not a guess."""
        if self._status.first_insight_at:
            return
        now = datetime.now(timezone.utc)
        self._status.first_insight_at = now.isoformat()
        self._state["first_insight_at"] = self._status.first_insight_at
        elapsed: float | None = None
        if self._status.started_at:
            try:
                elapsed = round((now - datetime.fromisoformat(self._status.started_at)).total_seconds(), 1)
            except (ValueError, TypeError):
                elapsed = None
        self._journal("exploration.first_insight", {
            "elapsed_seconds": elapsed,
            "insights_found": self._status.insights_found,
            "phase": self._status.phase.value if isinstance(self._status.phase, ExplorationPhase) else self._status.phase,
        })
        logger.info("[explorer:%s] ⏱ time-to-first-insight: %ss", self.connection_id, elapsed)

    def _emit_insight(self, insight: dict, sql: str, *, journal_extra: dict | None = None) -> None:
        """Common emission tail for a discovered insight, shared by Phase 7
        (cross-table) and Phase 8 (domain intel). Bumps counters, writes the K3
        ledger artifact (Trust-Receipt provenance), fires the live
        `exploration.insight` event so subscribed panels surface it immediately,
        and stamps the TTFI milestone. The caller has already appended the
        insight to `self._state["insights"]`.

        Before this helper, Phase 7 insights bumped only the counters — they had
        no artifact and emitted no event, so the *earliest* findings never
        surfaced live (the panels saw them only on the slow 60s fallback poll or
        at completion). Routing both phases here closes that built-not-wired gap.
        """
        self._status.insights_found += 1
        self._status.facts_discovered += 1
        self._record_first_insight()
        insight_id = insight.get("id", "")
        # K3: the finding becomes a versioned ledger artifact with provenance
        # edges — the Trust Receipt ("why believe this number") is a SELECT over
        # these, not a reconstruction. Supersede-not-delete; re-explore → version+1.
        try:
            from aughor.kernel.ledger import Ledger
            from aughor.kernel.jobs import current_job_id
            _lineage = [("source_sql", "sql", sql)]
            for _tbl in sorted(_tables_in_sql(sql))[:8]:
                _lineage.append(("input", f"table:{_tbl}", None))
            _lineage.append(("validated_by", "guard:numeric_grounding",
                             "all magnitudes matched result cells"))
            Ledger.default().artifact_write(
                "finding",
                f"insight:{self.connection_id}:{insight_id}",
                insight,
                conn_id=self.connection_id,
                canvas_id=self.canvas_id,
                created_by_job=current_job_id(),
                lineage=_lineage,
            )
        except Exception:
            logger.debug("finding artifact write failed", exc_info=True)
        payload = {"insight_id": insight_id, "finding": str(insight.get("finding", ""))[:120]}
        if journal_extra:
            payload.update(journal_extra)
        self._journal("exploration.insight", payload)

    def pause(self) -> None:
        """Yield execution — called when a user investigation begins."""
        self._can_run.clear()
        self._status.paused = True

    def resume(self) -> None:
        """Resume exploration — called when a user investigation ends."""
        self._can_run.set()
        self._status.paused = False

    def stop(self) -> None:
        """Permanently stop (e.g. connection deleted)."""
        self._stopped = True
        self._can_run.set()  # unblock if currently paused so the task exits

    @property
    def status(self) -> ExplorationStatus:
        return self._status

    # ── Execution gate ────────────────────────────────────────────────────────

    async def _gate(self) -> None:
        """Block until unpaused, then enforce the per-phase rate limit."""
        await self._can_run.wait()
        if self._stopped:
            raise asyncio.CancelledError()
        if self._rate_seconds > 0:
            elapsed = time.monotonic() - self._last_query_at
            wait = self._rate_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)

    async def _run(self, sql: str, think: str = "") -> Optional[list]:
        """Execute one read-only SQL query off the event loop and record an episode turn."""
        loop = asyncio.get_running_loop()
        self._last_query_at = time.monotonic()
        self._status.queries_executed += 1
        try:
            result = await loop.run_in_executor(
                None, self._conn.execute, "__explorer__", sql
            )
            if result.error:
                self._episodes.add(think=think, sql=sql, observation=f"ERROR: {result.error}")
                return None
            obs_rows = "\n".join(str(r) for r in (result.rows or [])[:6])
            obs = f"{result.row_count} rows\ncols: {result.columns}\n{obs_rows}"
            self._episodes.add(think=think, sql=sql, observation=obs)
            return result.rows or []
        except Exception as e:
            self._episodes.add(think=think, sql=sql, observation=f"EXCEPTION: {e}")
            return None

    # ── Time window helpers ───────────────────────────────────────────────────

    def _compute_time_window(
        self, tp: dict, cp: Optional[dict] = None, jmap: Optional[dict] = None,
    ) -> Optional[tuple[str, str]]:
        """Anchor the 12-month window's recency on the consensus trailing edge of
        *activity* (measure-bearing event/fact tables), excluding calendar/dimension
        spines — so a date dimension running into the future can't push the window past
        the last real fact and yield empty ("no data") briefings. Sentinel dates
        (9999/1900/epoch) are filtered, and the dense ``effective_date_range`` is
        preferred over the raw ``date_range``. See docs/ADAPTIVE_TEMPORAL_SCOPE.md §3.
        """
        start, end, discrepancy = _role_aware_time_window(tp, cp, jmap)
        if discrepancy:
            spines = ", ".join(f"{t} (→{r})" for t, r in discrepancy[:3])
            logger.info(
                "[explorer:%s] Date spine(s) extend past the last activity (%s): %s — "
                "anchoring on observed activity, not the calendar.",
                self.connection_id, end, spines,
            )
        if not (start and end):
            return None

        # Tier 1: narrow to the CURRENT regime when one is clearly present. Regime-narrows-
        # only — we move the window start forward to a recent structural break, never widen
        # or weaken the Tier-0 result; any failure falls back to the fixed window.
        try:
            anchor, _rec, _eff = _anchor_activity(tp, cp)
            if anchor:
                regime_start = self._regime_window_start(anchor, tp, start)
                # Floor: never narrow below ~a quarter of data — guards against a recent
                # daily/weekly spike collapsing the window to days.
                if regime_start and regime_start > start and _days_between(regime_start, end) >= 90:
                    logger.info(
                        "[explorer:%s] Tier 1: narrowing window to current regime (start %s → %s)",
                        self.connection_id, start, regime_start,
                    )
                    start = regime_start
        except Exception:
            logger.debug("[explorer:%s] Tier 1 regime refinement skipped", self.connection_id, exc_info=True)

        return start, end

    def _regime_window_start(self, table: str, tp: dict, win_start: str) -> Optional[str]:
        """Query the activity density series (rows per period) for ``table`` and return the
        current-regime start date when a structural break falls *inside* the window
        (``> win_start``), else None. Best-effort; never raises into the pipeline.
        Tier 1 of docs/ADAPTIVE_TEMPORAL_SCOPE.md."""
        prof = tp.get(table)
        ts_col = getattr(prof, "primary_timestamp", None) if prof else None
        if not ts_col:
            return None
        grain = (getattr(prof, "time_grain", None) or "month")
        unit = {"day": "day", "week": "week", "month": "month",
                "quarter": "quarter", "year": "year"}.get(grain, "month")
        sql = (
            f"SELECT date_trunc('{unit}', {ts_col})::VARCHAR AS p, COUNT(*) AS c "
            f"FROM {table} WHERE {ts_col} IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        try:
            r = self._conn.execute("__explorer__", sql)
        except Exception:
            return None
        rows = (r.rows or []) if not getattr(r, "error", None) else []
        if len(rows) < 12:   # need enough periods for a meaningful regime
            return None
        periods = [str(row[0])[:10] for row in rows]
        counts = [row[1] for row in rows]
        try:
            from aughor.explorer.regime import adaptive_window
            rstart, _rend, _reason = adaptive_window(periods, counts)
        except Exception:
            return None
        return rstart if (rstart and rstart > win_start) else None

    def _compute_macro_context(self, tp: dict, cp: dict) -> Optional[dict]:
        """Tier 2: one coarse full-span rollup over the anchor activity table — the long
        arc (secular trend / growth factor) the briefing juxtaposes against the recent
        regime. Cheap (one GROUP BY year, ~N_years rows). Best-effort; returns None on
        any failure. See aughor/explorer/temporal.py + docs/ADAPTIVE_TEMPORAL_SCOPE.md §5."""
        anchor, _rec, _eff = _anchor_activity(tp, cp)
        if not anchor:
            return None
        prof = tp.get(anchor)
        ts_col = getattr(prof, "primary_timestamp", None) if prof else None
        if not ts_col:
            return None

        # Roll up at year grain unless the full span is short (then quarter).
        grain = "year"
        # Pick one additive measure column on the anchor to roll up alongside row counts.
        # Skip key/id-like columns the profiler mis-tags as measures — SUM(l_orderkey)
        # is a meaningless aggregate of identifiers, not a business quantity.
        def _looks_like_key(name: str) -> bool:
            n = name.lower()
            # _key/_id (snake) and ...key/...id (TPC-style concat: l_orderkey, partkey)
            return (n in ("id", "key") or n.endswith(("_id", "_key", "_no", "_num", "_code", "_sk",
                                                       "key", "id"))
                    or n.startswith(("id_", "key_")))
        measure_col = None
        for col_name, col_p in (cp.get(anchor) or {}).items():
            if _profile_field(col_p, "semantic_type") == "measure" and not _looks_like_key(col_name):
                measure_col = col_name
                break

        measure_expr = f", SUM({measure_col}) AS m" if measure_col else ""
        sql = (
            f"SELECT date_trunc('{grain}', {ts_col})::VARCHAR AS p, COUNT(*) AS c{measure_expr} "
            f"FROM {anchor} WHERE {ts_col} IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        try:
            r = self._conn.execute("__explorer__", sql)
        except Exception:
            return None
        rows = (r.rows or []) if not getattr(r, "error", None) else []
        if len(rows) < 2:
            return None

        periods = [str(row[0])[:10] for row in rows]
        counts = [row[1] for row in rows]
        measures = [row[2] for row in rows] if measure_col else None

        from aughor.explorer.temporal import build_macro_context
        micro_start = self._time_window[0] if self._time_window else None
        return build_macro_context(
            periods, counts, measures=measures, measure_name=measure_col,
            micro_start=micro_start, grain=grain, anchor=anchor,
        )

    def _time_filter(self, table: str, tp: dict) -> str:
        """
        Return a SQL AND-clause fragment for the 12-month time window, e.g.
          'AND order_purchase_timestamp >= \'2023-09-14\''
        Returns '' if no time window is set or the table has no primary timestamp.
        """
        if not self._time_window:
            return ""
        t_profile = tp.get(table)
        if not t_profile:
            return ""
        ts_col = getattr(t_profile, "primary_timestamp", None)
        if not ts_col:
            return ""
        start_str, _ = self._time_window
        return f"AND {ts_col} >= '{start_str}'"

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def explore(self, domain_intel_only: bool = False) -> None:
        """Full exploration run — schedule this as an asyncio.Task.

        If domain_intel_only=True (triggered by "Explore 5 more") skips phases 3-7
        and runs only Phase 8, consuming the extended budget.
        """
        logger.info(f"[explorer:{self.connection_id}] Starting (domain_intel_only={domain_intel_only})")
        _loop = asyncio.get_running_loop()
        try:
            tp, cp, jmap = await _loop.run_in_executor(None, self._load_profiler_data)
            if not tp:
                logger.info(f"[explorer:{self.connection_id}] No profiler data, aborting")
                return

            self._status.tables_total = len(tp)
            self._status.columns_total = sum(len(v) for v in cp.values())
            self._status.joins_total = len(jmap.get("joins", []))

            # Compute the 12-month window — recency anchored on activity (fact) tables,
            # not the calendar spine (Tier 0; docs/ADAPTIVE_TEMPORAL_SCOPE.md §3).
            self._time_window = self._compute_time_window(tp, cp, jmap)
            if self._time_window:
                logger.info(
                    "[explorer:%s] Time window: %s → %s",
                    self.connection_id, self._time_window[0], self._time_window[1],
                )

            # Tier 3 cost governor: capture the activity high-water mark (for incremental
            # re-exploration) and decide whether this connection is large enough that the
            # curiosity loop should use approximate aggregates. Best-effort, never fatal.
            try:
                from aughor.explorer.watermark import get_watermark, set_watermark
                _anchor, _rec, _ = _anchor_activity(tp, cp)
                self._prev_watermark = get_watermark(self.connection_id, _anchor) if _anchor else None
                if _anchor and _rec:
                    set_watermark(self.connection_id, _anchor, _rec)
                self._cost_large = any((_profile_field(p, "row_count") or 0) >= _COST_LARGE_ROWS
                                       for p in (tp or {}).values())
                if self._cost_large:
                    logger.info("[explorer:%s] Tier 3: large connection — approximate aggregates on",
                                self.connection_id)
            except Exception:
                self._cost_large = False

            # Tier 2: cheap full-span macro rollup over the anchor — the long arc that
            # briefings juxtapose against the recent-regime micro window. Best-effort.
            try:
                self._macro_context = self._compute_macro_context(tp, cp)
                if self._macro_context:
                    self._state["macro_context"] = self._macro_context
                    self._save_state()
                    logger.info(
                        "[explorer:%s] Macro context: %s %s→%s (%d %ss)",
                        self.connection_id, self._macro_context.get("anchor"),
                        self._macro_context.get("first_period"), self._macro_context.get("last_period"),
                        self._macro_context.get("n_periods"), self._macro_context.get("grain"),
                    )
            except Exception:
                logger.debug("[explorer:%s] Tier 2 macro context skipped", self.connection_id, exc_info=True)

            if not domain_intel_only:
                # Phases 3-7: schema cartography — run as fast as the DB allows
                self._rate_seconds = _RATE_SECONDS_SCHEMA

                # Phase 3 — Null meaning resolution
                self._status.phase = ExplorationPhase.NULL_MEANING
                self._journal("exploration.phase", {"phase": "null_meaning"})
                await self._phase3_null_meaning(tp, cp)

                # Phase 4 — Join verification
                self._status.phase = ExplorationPhase.JOIN_VERIFICATION
                self._journal("exploration.phase", {"phase": "join_verification"})
                await self._phase4_joins(jmap)

                # Phase 5 — Lifecycle mapping
                self._status.phase = ExplorationPhase.LIFECYCLE_MAPPING
                self._journal("exploration.phase", {"phase": "lifecycle_mapping"})
                await self._phase5_lifecycle(tp, cp)

                # Phase 6 — Distribution profiling
                self._status.phase = ExplorationPhase.DISTRIBUTION
                self._journal("exploration.phase", {"phase": "distribution"})
                await self._phase6_distributions(cp, tp)

                # Phase 7 — Cross-table pattern discovery
                self._status.phase = ExplorationPhase.CROSS_TABLE
                self._journal("exploration.phase", {"phase": "cross_table"})
                await self._phase7_patterns(cp, jmap, tp)

            # ── Ontology gate: Phase 8 needs the ontology; build it now if it
            # hasn't been created yet.  On a fresh connection, phases 3-7 can
            # finish in <10 s while the ontology build (triggered by the first
            # /ontology API request) may not have happened yet.  get_schema()
            # is idempotent + cached — instant on the second call.
            from aughor.ontology.store import load_latest_ontology as _load_onto
            if not _load_onto(self.connection_id):
                logger.info(
                    "[explorer:%s] Ontology not found before Phase 8 — building now…",
                    self.connection_id,
                )
                try:
                    await _loop.run_in_executor(None, self._conn.build_intelligence)
                    logger.info(
                        "[explorer:%s] Ontology build complete, proceeding to Phase 8",
                        self.connection_id,
                    )
                except Exception as _onto_exc:
                    logger.warning(
                        "[explorer:%s] Ontology build failed — Phase 8 will be skipped: %s",
                        self.connection_id, _onto_exc,
                    )

            # Phase 8 — Domain intelligence: slow down to avoid overloading the DB
            # and to allow the user to stop between queries if needed
            self._rate_seconds = _RATE_SECONDS_INTEL
            self._status.phase = ExplorationPhase.DOMAIN_INTEL
            self._journal("exploration.phase", {"phase": "domain_intel"})
            self._status.domain_intel_skipped = False   # cleared; set by Phase 8 if it bails
            self._status.domain_intel_note = None
            await self._phase8_domain_intelligence(cp, tp)

            # Done — persist runtime counters so the status fallback can restore them
            self._status.phase = ExplorationPhase.COMPLETE
            self._journal("exploration.phase", {"phase": "complete"})
            self._status.completed_at = datetime.now(timezone.utc).isoformat()
            self._state["phase"] = ExplorationPhase.COMPLETE.value
            self._state["tables_total"] = self._status.tables_total
            self._state["columns_total"] = self._status.columns_total
            self._state["queries_executed"] = self._status.queries_executed
            self._state["started_at"] = self._status.started_at
            self._state["completed_at"] = self._status.completed_at
            self._state["domain_intel_skipped"] = self._status.domain_intel_skipped
            self._state["domain_intel_note"] = self._status.domain_intel_note
            self._save_state()
            logger.info(
                f"[explorer:{self.connection_id}] Complete — "
                f"{self._status.queries_executed}q, "
                f"{self._status.facts_discovered} facts, "
                f"{self._status.insights_found} insights"
            )

        except asyncio.CancelledError:
            self._save_state()
            logger.info(f"[explorer:{self.connection_id}] Cancelled, progress saved")
            raise
        except Exception as e:
            self._status.phase = ExplorationPhase.FAILED
            self._journal("exploration.phase", {"phase": "failed"})
            self._status.error = str(e)
            self._save_state()
            logger.error(f"[explorer:{self.connection_id}] Error: {e}", exc_info=True)

    # ── Profiler data loader ──────────────────────────────────────────────────

    def _load_profiler_data(self):
        """
        Return (table_profiles, col_profiles_by_table, join_map).
        Reads from profile cache when available, builds from DB otherwise.
        col_profiles_by_table: {table: {col_name: ColumnProfile}}
        """
        try:
            # Discover tables (SHOW TABLES is blocked by the SELECT-only validator,
            # so use information_schema for both dialects)
            schema = getattr(self._conn, "_schema_name", None)
            if self._conn.dialect == "duckdb":
                if schema:
                    schema_filter = f"= '{schema}'"
                else:
                    # No specific schema configured — scan all user-defined schemas.
                    # DuckDB databases can store tables in non-default schemas
                    # (e.g. samples.duckdb uses 'ecommerce'). Exclude system catalogs.
                    schema_filter = "NOT IN ('information_schema', 'pg_catalog', 'temp')"
            else:
                schema_filter = f"= '{schema or 'public'}'"
            r = self._conn.execute(
                "__explorer__",
                f"SELECT table_schema, table_name FROM information_schema.tables "
                f"WHERE table_schema {schema_filter} "
                f"AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name",
            )
            raw_tables = [(row[0], row[1]) for row in (r.rows or [])] if not r.error else []
            # When multiple schemas exist, fully-qualify table names so generated
            # SQL resolves correctly (e.g. bakehouse.sales_franchises).
            schemas_seen = {s for s, _ in raw_tables}
            if len(schemas_seen) > 1 or (schema and schema not in schemas_seen and len(raw_tables) > 0):
                tables = [f'{s}.{t}' for s, t in raw_tables]
            elif len(schemas_seen) == 1 and not schema:
                # Single schema, no explicit schema configured — still qualify to be safe
                single_schema = next(iter(schemas_seen))
                tables = [f'{single_schema}.{t}' for s, t in raw_tables]
            else:
                tables = [t for _, t in raw_tables]

            if not tables:
                return {}, {}, {}

            # Filter tables to canvas scope when set
            if self.tables_filter:
                filter_set = set(self.tables_filter)
                tables = [t for t in tables if t in filter_set or t.split('.')[-1] in filter_set]
            if not tables:
                return {}, {}, {}

            # Build / load profiles (idempotent, cached)
            from aughor.tools.profile_cache import get_or_build_profiles
            tp, cp_flat = get_or_build_profiles(
                self._conn, self.connection_id, tables, {}
            )

            # Re-group flat {"table.col": ColumnProfile} → {table: {col: ColumnProfile}}
            cp: dict[str, dict] = {}
            for col_p in cp_flat.values():
                cp.setdefault(col_p.table, {})[col_p.column] = col_p

            # Build a minimal schema string for join inference
            lines = []
            for table in tables:
                lines.append(f"TABLE: {table}")
                for col_p in cp.get(table, {}).values():
                    lines.append(f"  {col_p.column}  {col_p.dtype}")
            schema_str = "\n".join(lines)

            from aughor.tools.schema import _parse_schema_tables, _compute_join_map
            jmap = _compute_join_map(_parse_schema_tables(schema_str))

            return tp, cp, jmap

        except Exception as e:
            logger.warning(f"[explorer:{self.connection_id}] _load_profiler_data failed: {e}")
            return {}, {}, {}

    # ── Phase 3: Null meaning resolution ─────────────────────────────────────

    async def _phase3_null_meaning(self, tp: dict, cp: dict) -> None:
        """
        For each column with a non-trivial null rate (1%–99%), determine whether
        the null is business-meaningful or a data quality problem.
        """
        for table, col_map in cp.items():
            # Find the lifecycle/status column for this table (for cross-reference)
            status_col = _find_status_col(col_map)

            for col_name, col_p in col_map.items():
                if col_p.null_rate is None:
                    continue
                if not (0.01 <= col_p.null_rate <= 0.99):
                    continue
                if col_p.semantic_type in ("key", "timestamp"):
                    continue

                key = f"{table}:{col_name}"
                if key in self._state.get("null_meanings", {}):
                    self._status.null_meanings_resolved += 1
                    continue

                await self._gate()

                if status_col and status_col != col_name:
                    result = await self._null_cross_ref(table, col_name, status_col, col_p.null_rate, tp=tp)
                else:
                    meaning = NullMeaning.MISSING if col_p.null_rate > 0.3 else NullMeaning.UNKNOWN
                    result = NullMeaningResult(
                        table=table, column=col_name,
                        null_rate=col_p.null_rate, meaning=meaning,
                    )

                self._state.setdefault("null_meanings", {})[key] = {
                    "meaning": result.meaning.value,
                    "business_rule": result.business_rule,
                    "evidence_sql": result.evidence_sql,
                }
                self._status.null_meanings_resolved += 1
                self._status.facts_discovered += 1
                self._save_state()

    async def _null_cross_ref(
        self, table: str, col: str, status_col: str, null_rate: float,
        tp: Optional[dict] = None,
    ) -> NullMeaningResult:
        tf = self._time_filter(table, tp or {})
        sql = (
            f"SELECT {status_col} AS s, COUNT(*) AS total, "
            f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null_n, "
            f"ROUND(SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS null_pct "
            f"FROM {table} WHERE 1=1 {tf} "
            f"GROUP BY {status_col} ORDER BY null_pct DESC LIMIT 20"
        )
        think = (
            f"'{table}.{col}' has {null_rate:.0%} nulls. "
            f"Cross-referencing with '{status_col}' to classify: "
            f"pending-event vs terminal-state vs data-quality issue."
        )
        rows = await self._run(sql, think=think)
        if not rows:
            return NullMeaningResult(
                table=table, column=col, null_rate=null_rate, meaning=NullMeaning.UNKNOWN
            )

        # rows: [(status_val, total, null_n, null_pct), ...]
        try:
            high = [r for r in rows if r[3] is not None and float(r[3]) > 80]
            low  = [r for r in rows if r[3] is not None and float(r[3]) < 10]
        except (TypeError, ValueError):
            return NullMeaningResult(
                table=table, column=col, null_rate=null_rate, meaning=NullMeaning.UNKNOWN
            )

        if high and low:
            null_states = [str(r[0]) for r in high]
            business_rule = (
                f"NULL when {status_col} IN "
                f"({', '.join(repr(s) for s in null_states)})"
            )
            is_terminal = any(
                s.lower() in _TERMINAL or any(t in s.lower() for t in _TERMINAL_SUBS)
                for s in null_states
            )
            meaning = (
                NullMeaning.NOT_APPLICABLE_TERMINAL if is_terminal else NullMeaning.PENDING
            )
        elif rows and all(r[3] is not None and float(r[3] or 0) > 30 for r in rows):
            meaning, business_rule = NullMeaning.MISSING, None
        else:
            meaning, business_rule = NullMeaning.MIXED, None

        return NullMeaningResult(
            table=table, column=col, null_rate=null_rate,
            meaning=meaning, business_rule=business_rule, evidence_sql=sql,
        )

    # ── Phase 4: Join verification ────────────────────────────────────────────

    async def _phase4_joins(self, jmap: dict) -> None:
        """
        Verify each inferred FK relationship with an orphan check.
        A verified join has orphan_count == 0.
        """
        joins = jmap.get("joins", [])
        done_keys = {v.get("key") for v in self._state.get("join_verifications", [])}

        for j in joins:
            t1, c1, t2, c2 = j["t1"], j["c1"], j["t2"], j["c2"]
            key = f"{t1}.{c1}→{t2}.{c2}"
            if key in done_keys:
                self._status.joins_verified += 1
                continue

            await self._gate()

            # CAST both keys to VARCHAR for the orphan comparison: the same logical key
            # can carry different physical types across tables (e.g. franchiseID BIGINT
            # here, VARCHAR there), and a raw `NOT IN` then errors "Cannot compare VARCHAR
            # and BIGINT". Comparing the string forms is the right FK check (an id is an id)
            # and never raises.
            sql = (
                f"SELECT "
                f"(SELECT COUNT(DISTINCT {c1}) FROM {t1}) AS fk_distinct, "
                f"(SELECT COUNT(DISTINCT {c2}) FROM {t2}) AS pk_distinct, "
                f"(SELECT COUNT(*) FROM {t1} "
                f" WHERE {c1} IS NOT NULL "
                f" AND CAST({c1} AS VARCHAR) NOT IN (SELECT CAST({c2} AS VARCHAR) FROM {t2} WHERE {c2} IS NOT NULL)"
                f") AS orphan_count"
            )
            think = (
                f"Verify FK {t1}.{c1} → {t2}.{c2}: "
                f"count distinct values and check for orphan rows."
            )
            rows = await self._run(sql, think=think)

            if rows and rows[0]:
                try:
                    fk_d = int(rows[0][0] or 0)
                    pk_d = int(rows[0][1] or 0)
                    orphans = int(rows[0][2] or 0)
                except (TypeError, ValueError):
                    continue

                if fk_d == pk_d:
                    card = "1:1"
                elif fk_d > pk_d:
                    card = "N:1"
                else:
                    card = "1:N"

                self._state.setdefault("join_verifications", []).append({
                    "key": key,
                    "from_table": t1, "from_col": c1,
                    "to_table": t2, "to_col": c2,
                    "orphan_count": orphans,
                    "fk_distinct": fk_d, "pk_distinct": pk_d,
                    "verified": orphans == 0,
                    "cardinality": card,
                })
                self._status.joins_verified += 1
                self._status.facts_discovered += 1
                done_keys.add(key)
                self._save_state()

    # ── Phase 5: Lifecycle mapping ────────────────────────────────────────────

    async def _phase5_lifecycle(self, tp: dict, cp: dict) -> None:
        """
        For each table with a status/lifecycle column, extract the state
        distribution and (when possible) state-transition frequencies.
        """
        for table, col_map in cp.items():
            if table in self._state.get("lifecycle_maps", {}):
                self._status.lifecycles_mapped += 1
                continue

            status_col = _find_status_col(col_map)
            if not status_col:
                continue

            await self._gate()

            tf = self._time_filter(table, tp)

            # State distribution
            sql = (
                f"SELECT {status_col} AS state, COUNT(*) AS n "
                f"FROM {table} WHERE {status_col} IS NOT NULL {tf} "
                f"GROUP BY {status_col} ORDER BY n DESC LIMIT 30"
            )
            think = (
                f"Extract lifecycle states for {table}.{status_col}. "
                f"Classify terminal vs active states."
            )
            rows = await self._run(sql, think=think)
            if not rows:
                continue

            states = [str(r[0]) for r in rows]
            terminal, active = _classify_states(states)

            # Try to extract transitions via self-join if PK + timestamp exist
            tp_entry = tp.get(table)
            pk_col = tp_entry.grain_column if tp_entry else None
            ts_col = tp_entry.primary_timestamp if tp_entry else None
            transitions: list[LifecycleTransition] = []

            if pk_col and ts_col:
                await self._gate()
                # Time filter for self-join must be qualified with alias 'a'
                alias_tf = (
                    f"AND a.{ts_col} >= '{self._time_window[0]}'"
                    if self._time_window else ""
                )
                trans_sql = (
                    f"SELECT a.{status_col} AS from_s, b.{status_col} AS to_s, COUNT(*) AS n "
                    f"FROM {table} a "
                    f"JOIN {table} b ON a.{pk_col} = b.{pk_col} AND a.{ts_col} < b.{ts_col} "
                    f"WHERE a.{status_col} != b.{status_col} {alias_tf} "
                    f"GROUP BY a.{status_col}, b.{status_col} "
                    f"ORDER BY n DESC LIMIT 20"
                )
                think2 = (
                    f"Extract state transitions for {table}: "
                    f"self-join on {pk_col} ordered by {ts_col}."
                )
                trans_rows = await self._run(trans_sql, think=think2)
                if trans_rows:
                    transitions = [
                        LifecycleTransition(
                            from_state=str(r[0]), to_state=str(r[1]), count=int(r[2])
                        )
                        for r in trans_rows
                    ]

            self._state.setdefault("lifecycle_maps", {})[table] = {
                "status_column": status_col,
                "states": states,
                "terminal_states": terminal,
                "active_states": active,
                "transitions": [
                    {"from": t.from_state, "to": t.to_state, "n": t.count}
                    for t in transitions
                ],
            }
            self._status.lifecycles_mapped += 1
            self._status.facts_discovered += 1
            self._save_state()

    # ── Phase 6: Distribution profiling ──────────────────────────────────────

    async def _phase6_distributions(self, cp: dict, tp: dict = None) -> None:
        """
        Characterise the value distribution of every measure column.
        Uses basic stats + percentiles to classify shape.
        """
        tp = tp or {}
        # Phase-completion guard: if a previous full run already finished this
        # phase, skip it entirely rather than re-checking every column.
        if self._state.get("phase6_done"):
            self._status.distributions_profiled = len(self._state.get("distributions", {}))
            return

        for table, col_map in cp.items():
            for col_name, col_p in col_map.items():
                if col_p.semantic_type != "measure":
                    continue

                key = f"{table}:{col_name}"
                existing = self._state.get("distributions", {}).get(key)
                if existing is not None and not existing.get("_partial"):
                    # Fully computed in a previous run — skip
                    self._status.distributions_profiled += 1
                    continue

                await self._gate()

                tf = self._time_filter(table, tp)
                stats_sql = (
                    f"SELECT COUNT(*) AS n, "
                    f"MIN({col_name}) AS mn, MAX({col_name}) AS mx, "
                    f"AVG(CAST({col_name} AS FLOAT)) AS mean_v, "
                    f"AVG(CAST({col_name} AS FLOAT)*CAST({col_name} AS FLOAT)) - AVG(CAST({col_name} AS FLOAT))*AVG(CAST({col_name} AS FLOAT)) AS variance, "
                    f"SUM(CASE WHEN {col_name}=0 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS pct_zero "
                    f"FROM {table} WHERE {col_name} IS NOT NULL {tf}"
                )
                rows = await self._run(stats_sql, think=f"Distribution stats for {table}.{col_name}.")
                if not rows or not rows[0] or not rows[0][0]:
                    continue

                try:
                    n, mn, mx, mean_v, variance, pct_zero = [
                        float(x) if x is not None else 0.0 for x in rows[0]
                    ]
                    n = int(n)
                    if n == 0:
                        continue
                    std_dev = variance ** 0.5 if variance > 0 else 0.0
                except (TypeError, ValueError):
                    continue

                # Initial shape classification from basic stats
                shape = _classify_shape(mn, mx, mean_v, std_dev, float(pct_zero))

                # Save a partial record immediately after the first query so that a
                # server crash between the two queries doesn't cause the stats query
                # to re-fire on the next run.
                self._state.setdefault("distributions", {})[key] = {
                    "shape": shape.value, "p25": None, "p50": None, "p75": None,
                    "pct_zero": pct_zero, "min": mn, "max": mx, "mean": mean_v,
                    "col_type": col_p.dtype,
                    "_partial": True,
                }
                self._save_state()

                # Refine with percentiles
                await self._gate()
                pct_sql = (
                    f"SELECT "
                    f"percentile_cont(0.25) WITHIN GROUP (ORDER BY {col_name}) AS p25, "
                    f"percentile_cont(0.5)  WITHIN GROUP (ORDER BY {col_name}) AS p50, "
                    f"percentile_cont(0.75) WITHIN GROUP (ORDER BY {col_name}) AS p75 "
                    f"FROM {table} WHERE {col_name} IS NOT NULL {tf}"
                )
                pct_rows = await self._run(pct_sql, think=f"Percentiles for {table}.{col_name}.")
                p25 = p50 = p75 = None
                if pct_rows and pct_rows[0]:
                    try:
                        p25 = float(pct_rows[0][0] or 0)
                        p50 = float(pct_rows[0][1] or 0)
                        p75 = float(pct_rows[0][2] or 0)
                        if p50 and p50 > 0 and mean_v / p50 > 1.5:
                            shape = DistributionShape.SKEWED_RIGHT
                    except (TypeError, ValueError):
                        pass

                # Write final (non-partial) record
                self._state["distributions"][key] = {
                    "shape": shape.value, "p25": p25, "p50": p50, "p75": p75,
                    "pct_zero": pct_zero, "min": mn, "max": mx, "mean": mean_v,
                    "col_type": col_p.dtype,
                }
                self._status.distributions_profiled += 1
                self._status.facts_discovered += 1
                self._save_state()

        # Mark the entire phase as done so restarts can skip it immediately
        self._state["phase6_done"] = True
        self._save_state()

    # ── Phase 7: Cross-table pattern discovery ────────────────────────────────

    async def _phase7_patterns(self, cp: dict, jmap: dict, tp: dict = None) -> None:
        """
        For each verified join, check if a dimension in the PK table (t2)
        meaningfully explains variation in a measure in the FK table (t1).
        Records findings as OntologyInsights.
        """
        tp = tp or {}
        done_ids = {i.get("id") for i in self._state.get("insights", [])}
        joins = jmap.get("joins", [])[:10]  # bound query count

        for j in joins:
            t_fact = j["t1"]   # fact/event table (orders, order_items)
            t_dim  = j["t2"]   # dimension table (customers, products)
            fk_col = j["c1"]
            pk_col = j["c2"]

            dim_cols = [
                name for name, p in cp.get(t_dim, {}).items()
                if (p.semantic_type == "dimension"
                    and p.is_low_cardinality
                    and p.distinct_count is not None
                    and 2 <= p.distinct_count <= 20)
            ][:2]

            mea_cols = [
                name for name, p in cp.get(t_fact, {}).items()
                if p.semantic_type == "measure"
            ][:2]

            if not dim_cols or not mea_cols:
                continue

            for dim_col in dim_cols:
                for mea_col in mea_cols:
                    insight_id = f"{t_dim}.{dim_col}×{t_fact}.{mea_col}"
                    if insight_id in done_ids:
                        continue

                    await self._gate()

                    # Time-scope the fact table to 12-month window
                    fact_tf = ""
                    if self._time_window:
                        t_profile = tp.get(t_fact)
                        ts_col = getattr(t_profile, "primary_timestamp", None) if t_profile else None
                        if ts_col:
                            fact_tf = f"AND f.{ts_col} >= '{self._time_window[0]}'"

                    sql = (
                        f"SELECT d.{dim_col} AS dim_val, "
                        f"ROUND(AVG(f.{mea_col}), 2) AS avg_measure, "
                        f"COUNT(*) AS n "
                        f"FROM {t_fact} f "
                        f"JOIN {t_dim} d ON f.{fk_col} = d.{pk_col} "
                        f"WHERE f.{mea_col} IS NOT NULL AND d.{dim_col} IS NOT NULL {fact_tf} "
                        f"GROUP BY d.{dim_col} "
                        f"HAVING COUNT(*) >= 30 "
                        f"ORDER BY avg_measure DESC LIMIT 20"
                    )
                    think = (
                        f"Does '{dim_col}' ({t_dim}) explain variation "
                        f"in '{mea_col}' ({t_fact})? "
                        f"Checking for >15% variation across segments."
                    )
                    rows = await self._run(sql, think=think)
                    if not rows or len(rows) < 2:
                        continue

                    try:
                        vals = [float(r[1]) for r in rows if r[1] is not None]
                        if not vals or min(vals) <= 0:
                            continue
                        ratio = max(vals) / min(vals)
                        if ratio < 1.15:
                            continue  # not interesting enough

                        top, bot = rows[0], rows[-1]
                        total_n = sum(int(r[2] or 0) for r in rows)
                        finding = (
                            f"{t_dim}.{dim_col}='{top[0]}' → "
                            f"avg {mea_col} = {top[1]:.2f} vs "
                            f"{bot[1]:.2f} for '{bot[0]}' "
                            f"({(ratio - 1) * 100:.0f}% variation, n={total_n:,})"
                        )
                        insight = {
                            "id": insight_id,
                            "entities_involved": [t_dim, t_fact],
                            "dimensions": [dim_col],
                            "measures": [mea_col],
                            "finding": finding,
                            "sql": sql,
                            "confidence": min(0.95, 0.5 + (ratio - 1) * 0.5),
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "canvas_id": self.canvas_id,
                            "promoted_to_org": False,
                            "promotion_confidence": 0.0,
                        }
                        self._state.setdefault("insights", []).append(insight)
                        done_ids.add(insight_id)
                        self._emit_insight(insight, sql, journal_extra={"phase": "cross_table"})
                        self._save_state()
                    except (TypeError, ValueError, ZeroDivisionError):
                        continue


    # ── Phase 8: Domain intelligence curiosity loop ───────────────────────────

    async def _phase8_domain_intelligence(
        self,
        cp: dict | None = None,
        tp: dict | None = None,
    ) -> None:
        """
        For each ontology domain, run an adaptive curiosity loop:
          1. Build domain context from ontology entities + existing findings
          2. Ask LLM: what is the most valuable question to investigate next?
          3. Execute the SQL, interpret the result as a business insight
          4. Store the finding, update knowledge state
          5. Repeat until stopping criteria met
        Stopping: hard budget (15 per domain, extendable by user) OR
                  all coverage angles answered OR novelty decay < 2 avg over last 3

        cp: {table: {col: ColumnProfile}}   (column profiles — cardinality, FK flags)
        tp: {table: TableProfile}           (table profiles — grain, row counts)
        """
        self._episodes.phase = "domain_intel"
        _loop = asyncio.get_running_loop()
        from pydantic import BaseModel as _BM
        from typing import Literal as _Lit
        from aughor.llm.provider import get_provider
        from aughor.ontology.store import load_latest_ontology
        from aughor.sql.writer import SqlWriter

        ontology = load_latest_ontology(self.connection_id)
        if not ontology:
            # Surface the SPECIFIC failure the build recorded (stage + reason) so the user
            # gets an actionable message + Retry instead of a silent empty Hub.
            note = _ontology_skip_note(getattr(self._conn, "last_build", None))
            logger.warning("[explorer:%s] Phase 8: skipping — %s", self.connection_id, note)
            self._status.domain_intel_skipped = True
            self._status.domain_intel_note = note
            return

        # Group entities by domain
        domain_entities: dict[str, list] = {}
        for eid, entity in ontology.entities.items():
            d = entity.domain or "General"
            domain_entities.setdefault(d, []).append(entity)

        if not domain_entities:
            self._status.domain_intel_skipped = True
            self._status.domain_intel_note = (
                "Ontology built, but produced no entities to reason about."
            )
            return

        # ── Pydantic models for structured LLM output ──────────────────────────

        class _NextQuestion(_BM):
            question: str      # plain-English business question
            sql: str           # executable SQL using exact table/column names
            angle: str         # which coverage angle this answers (from the checklist)
            why: str           # why this is the most valuable next question

        class _Interpretation(_BM):
            finding: str       # 1-2 sentence business insight, specific with numbers
            novelty: int       # 1-5: how new is this vs existing findings for this domain
            angle_covered: str # which coverage angle this satisfies

        # ── Coverage angles per domain ─────────────────────────────────────────

        DOMAIN_ANGLES: dict[str, list[str]] = {
            "Commerce":   ["volume", "value", "retention", "basket_composition", "seasonality"],
            "Finance":    ["revenue", "margins", "payment_behavior", "refund_rate", "receivables"],
            "Marketing":  ["channel_mix", "conversion", "campaign_roi", "attribution", "experiments"],
            "Operations": ["fulfillment", "inventory_health", "supplier_performance", "lead_times"],
        }
        DEFAULT_ANGLES = ["volume", "value", "patterns", "anomalies", "trends"]

        HARD_BUDGET = 15

        llm = get_provider("coder")
        sql_writer = SqlWriter(self._conn)

        def _last_episode_error() -> str:
            """Read the observation from the most recent episode — used to get SQL errors."""
            try:
                import json as _j
                ep_path = Path("data") / f"episodes_{self.connection_id}.jsonl"
                if ep_path.exists():
                    last = ep_path.read_text().strip().split("\n")[-1]
                    return _j.loads(last).get("observation", "SQL execution failed")
            except Exception:
                pass
            return "SQL execution failed"

        # Dataset isolation: a connection may hold unrelated uploaded datasets in separate
        # schemas (e.g. bakehouse + ecommerce). The generated SQL is schema-qualified, so a
        # bare→dataset map lets us also restrict the table context the LLM sees. No-op for a
        # single-schema connection.
        _all_datasets = {_dataset_of(t) for t in (tp or {}) if _dataset_of(t)}
        multi_dataset = len(_all_datasets) > 1
        _bare2dataset = {str(q).split(".")[-1].lower(): _dataset_of(q)
                         for q in (tp or {}) if _dataset_of(q)}

        def _ds(tbl):
            """Dataset (schema) of a possibly-bare table, via the qualified-table universe."""
            return _dataset_of(tbl) or _bare2dataset.get(str(tbl).split(".")[-1].lower(), "")

        if multi_dataset:
            logger.info("[explorer:%s] Phase 8: multi-dataset connection %s — isolating datasets",
                        self.connection_id, sorted(_all_datasets))

        for domain, entities in domain_entities.items():
            await self._gate()
            if self._stopped:
                return

            angles = DOMAIN_ANGLES.get(domain, DEFAULT_ANGLES)
            budgets = self._state.setdefault("domain_budgets", {})
            coverage = self._state.setdefault("domain_coverage", {})
            domain_insights: list[dict] = [
                i for i in self._state.get("insights", []) if i.get("domain") == domain
            ]

            used = budgets.get(domain, 0)

            # Dataset isolation, hoisted to cover the WHOLE per-domain context. A domain's
            # entities can span unrelated uploaded datasets (Customer = bakehouse.sales_customers
            # AND ecommerce.customers). Restricting only the schema BLOCK still leaves the other
            # dataset's entities — and their column names — in the entity/relationship context,
            # and the generator then reaches for them (ecommerce `line_total`/`customer` in a
            # bakehouse domain), burning budget on questions the gates must skip. Scope `entities`
            # to the dominant dataset HERE so every downstream block (entity context, relationships,
            # schema, grains) sees one dataset only — the principle the measure-grain leak taught.
            if multi_dataset:
                from collections import Counter as _Counter
                _ent_tbl_ds = _Counter(_ds(t) for e in entities for t in e.source_tables if _ds(t))
                if len(_ent_tbl_ds) > 1:
                    _primary_ds = max(sorted(_ent_tbl_ds), key=lambda d: _ent_tbl_ds[d])
                    _scoped = [e for e in entities if any(_ds(t) == _primary_ds for t in e.source_tables)]
                    if _scoped and len(_scoped) < len(entities):
                        logger.info(
                            "[explorer:%s] Phase 8: %s domain spans %s — scoping entities to '%s' "
                            "(%d→%d entities)",
                            self.connection_id, domain, sorted(_ent_tbl_ds), _primary_ds,
                            len(entities), len(_scoped),
                        )
                        entities = _scoped

            entity_context = "\n".join(
                f"  - {e.display_name} ({', '.join(e.source_tables)}): {e.description}"
                for e in entities
            )
            relationship_context = "\n".join(
                f"  - {r.from_entity} → {r.to_entity} ({r.verb}, {r.cardinality})"
                for r in ontology.relationships.values()
                if any(e.id == r.from_entity or e.id == r.to_entity for e in entities)
            )[:2000]

            logger.info(f"[explorer:{self.connection_id}] Phase 8: {domain} domain — {len(entities)} entities, used={used}")

            while used < budgets.get(f"{domain}__cap", HARD_BUDGET):
                cap = budgets.get(f"{domain}__cap", HARD_BUDGET)
                await self._gate()
                if self._stopped:
                    return

                covered_angles = coverage.get(domain, [])

                # Stop on novelty decay: avg novelty of last 3 findings < 2
                if len(domain_insights) >= 3:
                    recent_novelty = [i.get("novelty", 3) for i in domain_insights[-3:]]
                    if sum(recent_novelty) / 3 < 2.0:
                        logger.info(f"[explorer:{self.connection_id}] Phase 8: {domain} — novelty decay, stopping")
                        break

                existing_findings = "\n".join(
                    f"  • [{i.get('angle','')}] {i.get('finding','')}"
                    for i in domain_insights
                ) or "  (none yet)"

                uncovered = [a for a in angles if a not in covered_angles]
                if not uncovered:
                    # All named angles covered — let LLM propose deeper / cross-cutting questions
                    uncovered = ["deeper_analysis", "anomalies", "cross_domain_patterns", "trends"]

                # Build compact schema for domain tables — grounding _NextQuestion SQL generation
                domain_tables = {tbl for ent in entities for tbl in ent.source_tables}
                # Table-level isolation backstop: entities are already scoped to the dominant
                # dataset above, but an entity that itself SPANS datasets can still drag the
                # other schema's tables in here — trim them so the schema block stays single-set.
                if multi_dataset:
                    from collections import Counter
                    counts = Counter(_ds(t) for t in domain_tables if _ds(t))
                    if len(counts) > 1:
                        primary = max(sorted(counts), key=lambda d: counts[d])
                        domain_tables = {t for t in domain_tables if _ds(t) == primary}
                        logger.info(
                            "[explorer:%s] Phase 8: %s domain spans %s — restricting tables to '%s'",
                            self.connection_id, domain, sorted(counts), primary,
                        )

                # ── Temporal-feasibility gate (#1) ──────────────────────────────
                # A table with no real timestamp cannot support date filters, aging or
                # trends; offering a time-based angle (or window) there forces the generator
                # to invent a date column — the `invoice_date`-on-a-dateless-`invoices`
                # hallucination. Drop temporal angles when the whole domain is dateless, and
                # always name the dateless tables so the LLM never applies time logic to them.
                def _tbl_ts(t):
                    p = (tp or {}).get(t) or (tp or {}).get(t.lower())
                    return getattr(p, "primary_timestamp", None) if p else None
                dateless_tables = sorted(t for t in domain_tables if not _tbl_ts(t))
                domain_has_dates = any(_tbl_ts(t) for t in domain_tables)
                if not domain_has_dates:
                    uncovered = [a for a in uncovered if not _is_temporal_angle(a)] or [
                        "distribution", "composition", "ranking", "anomalies"]
                    temporal_guard_block = (
                        "NO TEMPORAL DATA: this domain has NO date or timestamp column. Do NOT use "
                        "any date filter, time window, DATE_DIFF, aging buckets, trends, seasonality, "
                        "growth or over-time analysis, and do NOT invent a date/timestamp column. "
                        "Analyze only by category, status, distribution, ratio and rank.\n\n"
                    )
                elif dateless_tables:
                    temporal_guard_block = (
                        f"TABLES WITH NO DATE COLUMN: {', '.join(dateless_tables)}. For these you MUST "
                        f"NOT use a date filter, time window, DATE_DIFF, aging bucket or over-time "
                        f"analysis, and MUST NOT invent a date column for them — analyze them only by "
                        f"category, status, distribution, ratio or rank. Time-based analysis is valid "
                        f"only on tables that have a listed timestamp column.\n\n"
                    )
                else:
                    temporal_guard_block = ""

                domain_schema_lines: list[str] = []
                domain_cols: set[str] = set()
                domain_table_cols: dict[str, list] = {}   # scoped to THIS domain's tables
                for tbl in sorted(domain_tables):
                    cols = (
                        sql_writer.table_cols.get(tbl)
                        or sql_writer.table_cols.get(tbl.lower())
                        or next((v for k, v in sql_writer.table_cols.items() if k.lower() == tbl.lower()), None)
                    )
                    if cols:
                        domain_schema_lines.append(f"  {tbl}: {', '.join(cols)}")
                        domain_cols.update(str(c).lower() for c in cols)
                        domain_table_cols[tbl] = cols

                # Joinable-neighbour grounding: a domain often analyses a metric that lives on a
                # SIBLING fact table reached by a verified FK (Customer 'value' lives on
                # sales_transactions.totalPrice, not on sales_customers). That table isn't a
                # domain entity, so without its columns here the generator GUESSES the measure
                # name (total_amount vs the real totalPrice) — the gate skips it, but a budget
                # slot is wasted and the domain starves. Surface the EXACT columns of same-dataset,
                # verified-FK neighbours so the generator joins with real names. Same dataset only
                # (the cross-dataset guard still rejects an actual cross-schema join).
                _nbr_tables: set[str] = set()
                for jv in self._state.get("join_verifications", []):
                    _ft, _tt = jv.get("from_table", ""), jv.get("to_table", "")
                    for _a, _b in ((_ft, _tt), (_tt, _ft)):
                        if _a in domain_tables and _b and _b not in domain_tables and _ds(_b) == _ds(_a):
                            _nbr_tables.add(_b)
                _nbr_lines: list[str] = []
                for nt in sorted(_nbr_tables)[:4]:    # cap — keep the prompt tight
                    cols = (sql_writer.table_cols.get(nt)
                            or next((v for k, v in sql_writer.table_cols.items() if k.lower() == nt.lower()), None))
                    if cols:
                        _nbr_lines.append(f"  {nt}: {', '.join(cols)}")
                        domain_table_cols[nt] = cols                 # so measure-grains sees its grain too
                        domain_cols.update(str(c).lower() for c in cols)

                domain_schema_block = (
                    "EXACT COLUMN NAMES — use ONLY these, never invent:\n"
                    + "\n".join(domain_schema_lines)
                ) if domain_schema_lines else ""
                if _nbr_lines:
                    domain_schema_block += (
                        "\nJOINABLE TABLES (reachable by a verified key — if you join to one, use its "
                        "EXACT column names below; NEVER invent a measure like total_amount/line_total):\n"
                        + "\n".join(_nbr_lines)
                    )

                # ── Column-feasibility gate (#1) ────────────────────────────────
                # Drop named angles whose required column class is absent (a
                # channel/source column for channel_mix, a payment column for
                # payment_behavior …). Offering them forces the generator to stub
                # the missing dimension with a constant literal. Keep at least one
                # angle so the loop never starves.
                if domain_cols:
                    _feasible = [a for a in uncovered if _angle_feasible(a, domain_cols)]
                    if _feasible and len(_feasible) < len(uncovered):
                        logger.info(
                            "[explorer:%s] Phase 8: %s — dropping infeasible angles %s (required column absent)",
                            self.connection_id, domain,
                            [a for a in uncovered if a not in _feasible],
                        )
                        uncovered = _feasible

                # ── Grain + cardinality context ─────────────────────────────────
                # Inject table grains, row counts, FK columns, and high-cardinality
                # info so the LLM writes JOIN-safe SQL.
                grain_lines: list[str] = []
                fk_pairs: list[tuple[str, str, str]] = []   # (child_tbl, fk_col, parent_tbl hint)

                for tbl in sorted(domain_tables):
                    t_profile = (tp or {}).get(tbl) or (tp or {}).get(tbl.lower())
                    c_profiles = (cp or {}).get(tbl) or (cp or {}).get(tbl.lower()) or {}
                    row_count = getattr(t_profile, "row_count", None) if t_profile else None
                    grain_col = getattr(t_profile, "grain_column", None) if t_profile else None

                    row_str = f"{row_count:,} rows" if row_count else "? rows"
                    grain_str = f"grain={grain_col}" if grain_col else "grain=unknown"
                    grain_lines.append(f"  {tbl} ({row_str}, {grain_str})")

                    # Cardinality notes for columns with known profiles
                    for col_name, col_p in list(c_profiles.items())[:20]:
                        dc = getattr(col_p, "distinct_count", None)
                        is_fk = getattr(col_p, "is_fk", False)
                        sem = getattr(col_p, "semantic_type", "") or ""
                        if is_fk and dc is not None:
                            # FK column — record for join rule generation
                            fk_pairs.append((tbl, col_name, f"{dc:,} distinct"))
                            grain_lines.append(
                                f"    {col_name}: FK ({dc:,} distinct) → references another table's grain"
                            )
                        elif dc is not None and not getattr(col_p, "is_low_cardinality", False) and dc > 100:
                            # High-cardinality measure/ID — note the global distinct count
                            if sem in ("id", "foreign_key", "metric") or col_name.endswith("_id"):
                                grain_lines.append(f"    {col_name}: {dc:,} distinct values (global, not per row)")

                grain_block = ""
                if grain_lines:
                    grain_block = (
                        "TABLE GRAINS AND CARDINALITY — critical for correct SQL:\n"
                        + "\n".join(grain_lines)
                        + "\n"
                    )
                # Measure-additivity PREVENTION: per-unit vs per-line grain so the generator
                # writes SUM(x*quantity) for a unit price and SUM(x) for a line total. No-op safe.
                # Scope to THIS domain's tables — passing the whole connection injects another
                # dataset's measure columns (e.g. ecommerce `total_amount`/`line_total`) into a
                # bakehouse prompt, and the generator then writes them onto tables that don't
                # have them (the #1 Binder-error class on a mixed-dataset workspace).
                from aughor.semantic.measure_grain import measure_grains_block as _mg_block
                _mgb = _mg_block(self.connection_id, self._conn, domain_table_cols or sql_writer.table_cols)
                if _mgb:
                    grain_block += "\n" + _mgb + "\n"

                # Build join-safety rules from FK knowledge
                join_rules: list[str] = []
                # Also scan all join verifications for relevant relationships
                jv_all = self._state.get("join_verifications", [])
                for jv_entry in jv_all:
                    ft = jv_entry.get("from_table", "")
                    tt = jv_entry.get("to_table", "")
                    fc = jv_entry.get("from_col", "")
                    card = jv_entry.get("cardinality", "")
                    if ft in domain_tables or tt in domain_tables:
                        if "many" in card.lower() or card in ("N:1", "1:N", "N:M"):
                            join_rules.append(
                                f"  {ft} ↔ {tt} via {fc} ({card}): "
                                f"COUNT(*) after JOIN = rows in {ft}, NOT in {tt}. "
                                f"To count {tt} rows: COUNT(DISTINCT {tt}.grain_col)."
                            )

                # Always add the generic join-safety rule
                join_rules.insert(0, (
                    "  GENERAL: When JOINing a parent table to a child (one-to-many), COUNT(*) counts "
                    "child rows. To count parents use COUNT(DISTINCT parent.grain_column). "
                    "For per-parent averages, aggregate the child in a subquery first:\n"
                    "    SELECT parent_col, AVG(child_cnt) FROM parent\n"
                    "    JOIN (SELECT fk_col, COUNT(*) AS child_cnt FROM child GROUP BY fk_col) s\n"
                    "    ON parent.grain = s.fk_col GROUP BY parent_col\n"
                    "  NEVER do: COUNT(DISTINCT child.col) / COUNT(*) in a join — total-vs-total ratio.\n"
                    "  NEVER do: COUNT(DISTINCT col_a) / COUNT(DISTINCT col_b) — also a total-vs-total ratio.\n"
                    "  ALWAYS use subquery aggregation for per-parent averages:\n"
                    "    AVG(x_cnt) FROM (SELECT parent_id, COUNT(DISTINCT x) AS x_cnt FROM child GROUP BY parent_id) s\n"
                    "    JOIN parent ON parent.grain = s.parent_id"
                ))

                join_safety_block = (
                    "JOIN SAFETY RULES — read before writing any JOIN:\n"
                    + "\n".join(join_rules)
                    + "\n"
                ) if join_rules else ""

                # Build prior-phases context (phases 3-7 findings)
                prior_phases_lines: list[str] = []
                nm = self._state.get("null_meanings", {})
                if nm:
                    meaningful = {k: v for k, v in nm.items() if v.get("meaning") not in ("not_applicable", "unknown")}
                    if meaningful:
                        prior_phases_lines.append("NULL SEMANTICS (from Phase 3):")
                        for k, v in list(meaningful.items())[:8]:
                            prior_phases_lines.append(f"  {k.replace(':', '.')}: NULL = {v.get('meaning', '?')} ({v.get('null_rate', 0):.0%})")
                jv = self._state.get("join_verifications", [])
                if jv:
                    orphans = [j for j in jv if j.get("orphan_count", 0) > 0]
                    if orphans:
                        prior_phases_lines.append("JOIN ISSUES (from Phase 4):")
                        for j in orphans[:5]:
                            prior_phases_lines.append(f"  {j.get('key', '?')}: {j.get('orphan_count', 0)} orphan rows")
                lm = self._state.get("lifecycle_maps", {})
                if lm:
                    prior_phases_lines.append("LIFECYCLES (from Phase 5):")
                    for tbl, m in list(lm.items())[:5]:
                        prior_phases_lines.append(f"  {tbl}.{m.get('status_column', '?')}: {', '.join(m.get('active_states', [])[:4])} → {', '.join(m.get('terminal_states', [])[:3])}")
                prior_phases_block = "\n".join(prior_phases_lines) + "\n\n" if prior_phases_lines else ""

                # Step 1: Ask LLM what to investigate next (grain-aware, schema-grounded)
                # Run synchronous Ollama call in a thread so the event loop stays alive.
                try:
                    _sys1 = (
                        "You are a data analyst autonomously exploring a business database. "
                        "Propose exactly one SQL query that will reveal the most valuable business insight "
                        "for the given domain.\n\n"
                        "CRITICAL RULES:\n"
                        "1. Use ONLY the exact column names listed in EXACT COLUMN NAMES — never guess.\n"
                        "2. Write SELECT-only SQL with real aggregations and comparisons.\n"
                        "3. READ the JOIN SAFETY RULES before writing any JOIN. "
                        "After a one-to-many JOIN, COUNT(*) counts child rows, not parent rows. "
                        "Always use COUNT(DISTINCT parent.grain_col) to count parent entities. "
                        "For per-parent averages, subquery the child first.\n"
                        "4. BANNED PATTERN — never divide two COUNT(DISTINCT) values to express an average: "
                        "COUNT(DISTINCT child.col_a) / COUNT(DISTINCT parent.col_b) is ALWAYS wrong — "
                        "it gives total-A / total-B across the whole group, not the average A per B row. "
                        "The correct pattern for 'average X per parent' is: "
                        "AVG(x_count) FROM (SELECT parent_id, COUNT(DISTINCT x) AS x_count FROM child GROUP BY parent_id) sub. "
                        "This applies equally to COUNT(DISTINCT x) / COUNT(*) — both are banned.\n"
                        "5. RESPECT the TIME WINDOW in the user prompt — scope every query touching a "
                        "timestamped table to the specified date range. Trends, seasonality, and "
                        "growth metrics are only meaningful within a bounded, recent window."
                    )
                    time_window_block = ""
                    # The window must reflect THIS domain's dataset, not the connection's
                    # freshest dataset (multi-dataset connections), and its phrasing must
                    # reflect the actual coverage — a 17-day dataset framed as "the last
                    # 12 months" produces findings narrated over data that doesn't exist.
                    _domain_window = _window_for_tables(tp, cp, domain_tables) or self._time_window
                    if _domain_window:
                        # Name only the profiler-vetted timestamp columns. Without this the
                        # LLM invents a date filter on a date-NAMED integer column (e.g.
                        # ClickBench EventDate::USMALLINT) → "USMALLINT vs DATE". If a
                        # connection has no real timestamp anywhere, omit the window
                        # instruction entirely rather than provoke an un-runnable filter.
                        _ts_cols = sorted({
                            f"{t}.{getattr(p, 'primary_timestamp', None)}"
                            for t, p in (tp or {}).items()
                            if getattr(p, "primary_timestamp", None)
                        })
                        if _ts_cols:
                            _wstart, _wend = _domain_window[0], _domain_window[1]
                            _wdays = _days_between(_wstart, _wend) or 0
                            if _wdays < 300:
                                _frame = (
                                    f"DATA COVERAGE: this domain's data spans only ~{_wdays} days "
                                    f"({_wstart} to {_wend}) — that is ALL the history that exists. "
                                    f"Scope queries to that range and frame findings as 'over the "
                                    f"available {_wdays}-day history' — NEVER as 'the last 12 months' "
                                    f"or any period longer than the coverage. Do not propose MoM "
                                    f"comparisons with under ~2 months of data, nor YoY/seasonality "
                                    f"with under ~13 months. "
                                )
                            else:
                                _frame = (
                                    f"TIME WINDOW: Scope queries to the last 12 months "
                                    f"({_wstart} to {_wend}). "
                                )
                            time_window_block = (
                                f"{_frame}The ONLY "
                                f"real timestamp columns are: {', '.join(_ts_cols)}. "
                                f"Add WHERE <that column> >= '{_wstart}' only when "
                                f"your query touches one of those tables. NEVER add a date filter "
                                f"to a table without a listed timestamp column, and never compare "
                                f"a non-date column to a date literal.\n\n"
                            )

                    # Negative knowledge: names earlier queries proved don't exist. Steers the
                    # generator off repeated hallucinations (the #1 wasted-budget failure class).
                    dead_refs_block = ""
                    if self._dead_refs:
                        _avoid = ", ".join(sorted(self._dead_refs)[:30])
                        dead_refs_block = (
                            f"NONEXISTENT NAMES — earlier queries failed because these columns/tables "
                            f"do not exist in the table they were used on. Do NOT reference any of them "
                            f"unless it appears verbatim in the SCHEMA above: {_avoid}\n\n"
                        )
                    _usr1 = (
                        f"DOMAIN: {domain}\n\n"
                        f"ENTITIES IN THIS DOMAIN:\n{entity_context}\n\n"
                        f"RELATIONSHIPS:\n{relationship_context}\n\n"
                        f"{domain_schema_block}\n\n"
                        f"{grain_block}\n"
                        f"{join_safety_block}\n"
                        f"{temporal_guard_block}"
                        f"{time_window_block}"
                        f"{dead_refs_block}"
                        f"{prior_phases_block}"
                        f"COVERAGE ANGLES TO EXPLORE: {', '.join(uncovered)}\n"
                        f"ANGLES ALREADY COVERED: {', '.join(covered_angles) or 'none'}\n\n"
                        f"EXISTING FINDINGS FOR THIS DOMAIN:\n{existing_findings}\n\n"
                        "Propose the single most valuable next question. "
                        "Choose an uncovered angle. Write grain-correct SQL."
                    )
                    nq: _NextQuestion = await _loop.run_in_executor(
                        None,
                        lambda: llm.complete(system=_sys1, user=_usr1, response_model=_NextQuestion),
                    )
                except Exception as e:
                    logger.warning(f"[explorer:{self.connection_id}] Phase 8: LLM question gen failed for {domain}: {e}")
                    break

                # Qualify bare table names to their unique schema FIRST: on a multi-dataset
                # connection the LLM drops the qualifier (`FROM reviews`), which both errors
                # on DuckDB (no cross-schema search path) and hides a cross-dataset reference
                # from the guard below. Qualifying makes a same-dataset reference runnable and
                # exposes a cross-dataset one (`reviews` → ecommerce.reviews in a bakehouse domain).
                if multi_dataset:
                    try:
                        from aughor.sql.identifiers import qualify_table_names
                        nq.sql = qualify_table_names(nq.sql, sql_writer.table_cols,
                                                     getattr(self._conn, "dialect", "duckdb"))
                    except Exception as _exc:
                        from aughor.kernel.errors import tolerate
                        tolerate(_exc, "table qualification is best-effort; on failure the "
                                 "cross-dataset guard still runs on the original SQL",
                                 counter="explorer.qualify_failed")

                # Dataset-isolation guard: if the LLM still wrote a cross-dataset join,
                # drop it — a hallucinated join between unrelated uploaded datasets that can
                # only return garbage (the bakehouse ⋈ ecommerce class).
                if multi_dataset and _crosses_datasets(nq.sql):
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — skipping cross-dataset join: %s",
                        self.connection_id, domain, nq.angle, sorted(_tables_in_sql(nq.sql)),
                    )
                    used += 1
                    budgets[domain] = used
                    continue

                # Feasibility guard (#1, free-proposed angles): the generator stubbed
                # a missing column with a constant literal ('Unknown' AS signup_source
                # … GROUP BY signup_source) — a fabricated dimension. Catch it BEFORE
                # wasting an execute+interpret cycle (the named-angle gate above only
                # covers the checklist; the LLM can free-propose any angle).
                if _has_fabricated_dimension(nq.sql):
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — skipping fabricated-dimension question (constant grouping key)",
                        self.connection_id, domain, nq.angle,
                    )
                    used += 1
                    budgets[domain] = used
                    continue

                # Step 2: Execute SQL — repair loop: run → fail → fix with real error → repeat
                MAX_ATTEMPTS = 3
                think_str = f"Domain {domain} | angle={nq.angle} | {nq.question}"
                sql = nq.sql
                # Deterministic identifier repair: the LLM rewrites a camelCase schema's
                # `customerID` to snake_case `customer_id` (a nonexistent column → Binder
                # error → wasted retry, often a dropped angle). Remap to the exact column
                # name BEFORE execution so the query just runs. Invented columns are left
                # alone (a different, hallucination class).
                try:
                    from aughor.sql.identifiers import repair_identifiers
                    sql = repair_identifiers(sql, sql_writer.table_cols,
                                             getattr(self._conn, "dialect", "duckdb"))
                except Exception as _exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(_exc, "identifier repair is best-effort; on failure execute the "
                             "original SQL (the retry loop still catches a casing error)",
                             counter="explorer.repair_failed")
                # ── Schema-grounding pre-flight (#residual, deterministic) ───────
                # Casing slips are now repaired; what survives is a genuine invention —
                # `segment`/`region`/generic `id`, or an invented table (`product_items`).
                # A blind execute+retry only learns this by FAILING first, and that first
                # failure is exactly the Binder error the user sees in the Activity Tab.
                # Catch it statically, harvest the dead names (so the very next budget
                # iteration regenerates avoiding them — the existing NONEXISTENT-NAMES
                # block), and skip without ever executing. Mirrors the cross-dataset /
                # fabricated-dimension guards: a runnable question is worth more than a
                # logged error, and the loop will simply propose a valid one next.
                try:
                    from aughor.sql.identifiers import unresolved_identifiers
                    _bad_cols, _bad_tbls = unresolved_identifiers(
                        sql, sql_writer.table_cols, getattr(self._conn, "dialect", "duckdb"))
                    if _bad_cols or _bad_tbls:
                        self._dead_refs |= _bad_cols | _bad_tbls
                        from aughor.stats import stats as _s; _s.inc("explorer.invention_skips")
                        logger.info(
                            "[explorer:%s] Phase 8: %s/%s — skipping invented identifiers "
                            "(cols=%s tables=%s); harvested to negative knowledge",
                            self.connection_id, domain, nq.angle,
                            sorted(_bad_cols), sorted(_bad_tbls),
                        )
                        used += 1
                        budgets[domain] = used
                        self._state["domain_budgets"] = budgets
                        continue
                except Exception as _exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(_exc, "schema-grounding pre-flight is best-effort; on failure "
                             "fall through to the execute+retry loop (no worse than before)",
                             counter="explorer.preflight_failed")
                # Tier 3: on a large connection, swap exact COUNT(DISTINCT) for the HLL
                # approximation — orders of magnitude cheaper on big facts, ~1-3% off.
                if self._cost_large:
                    try:
                        from aughor.sql.cost import approximate_aggregates
                        sql = approximate_aggregates(sql, getattr(self._conn, "dialect", "duckdb"))
                    except Exception as _exc:
                        from aughor.kernel.errors import tolerate
                        tolerate(_exc, "HLL approximation is an optional cost optimisation; on "
                                 "failure run the exact aggregate (correct, just slower)",
                                 counter="explorer.cost_approx_failed")

                # ── Universal bind-check (#residual backstop, deterministic) ─────
                # EXPLAIN the final SQL against the real engine BEFORE executing. The
                # static gate models the dominant invention class, but no static checker
                # enumerates EVERY binder rule — a dangling table alias (c.customer_id with
                # no `c` in scope), a GROUP BY/aggregate violation, a residual VARCHAR/BIGINT
                # mismatch. dry_run IS the engine's binder, so it catches them all without
                # returning rows or logging an episode. On a bind failure, harvest the dead
                # names and attempt ONE grounded fix (fix() dry-runs internally, so it only
                # returns SQL that binds); adopt the fix or skip. This guarantees the first
                # real execution binds — no failed-bind episode reaches the Activity Tab —
                # while still salvaging a fixable question into an insight rather than losing it.
                try:
                    _ok, _berr = self._conn.dry_run(sql)
                    if not _ok:
                        self._dead_refs |= _extract_dead_refs(_berr)
                        _fix = await _loop.run_in_executor(
                            None, lambda: sql_writer.fix(sql, _berr, max_retries=2))
                        if _fix.ok and _fix.sql:
                            logger.info(
                                "[explorer:%s] Phase 8: %s/%s — pre-flight bind-fix applied: %s",
                                self.connection_id, domain, nq.angle, _fix.explanation,
                            )
                            sql = _fix.sql
                        else:
                            from aughor.stats import stats as _s; _s.inc("explorer.bindcheck_skips")
                            logger.info(
                                "[explorer:%s] Phase 8: %s/%s — skipping unbindable question (%s)",
                                self.connection_id, domain, nq.angle,
                                (_berr.splitlines()[0] if _berr else "bind error")[:90],
                            )
                            used += 1
                            budgets[domain] = used
                            self._state["domain_budgets"] = budgets
                            continue
                except Exception as _exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(_exc, "pre-flight bind-check is best-effort; on failure fall "
                             "through to the execute+retry loop (no worse than before)",
                             counter="explorer.bindcheck_failed")
                rows = None

                for attempt in range(MAX_ATTEMPTS):
                    label = think_str if attempt == 0 else f"[retry {attempt}] {think_str}"
                    rows = await self._run(sql, think=label)
                    if rows is not None:
                        break
                    error_msg = _last_episode_error()
                    # Accumulate negative knowledge — names the engine says don't exist — so
                    # the next-question generator stops re-proposing them (even on the final attempt).
                    self._dead_refs |= _extract_dead_refs(error_msg)
                    if attempt >= MAX_ATTEMPTS - 1:
                        logger.warning(
                            f"[explorer:{self.connection_id}] Phase 8: all {MAX_ATTEMPTS} attempts "
                            f"failed for {domain}/{nq.angle}"
                        )
                        break
                    fix = await _loop.run_in_executor(
                        None, lambda: sql_writer.fix(sql, error_msg, max_retries=1)
                    )
                    if not fix.ok:
                        logger.warning(
                            f"[explorer:{self.connection_id}] Phase 8: fix failed at attempt "
                            f"{attempt+1} for {domain}/{nq.angle}: {fix.final_error}"
                        )
                        break
                    logger.info(
                        f"[explorer:{self.connection_id}] Phase 8: fix attempt {attempt+1} "
                        f"for {domain}/{nq.angle} — {fix.explanation}"
                    )
                    sql = fix.sql

                used += 1
                budgets[domain] = used
                self._state["domain_budgets"] = budgets

                if not rows or len(rows) == 0:
                    logger.debug(f"[explorer:{self.connection_id}] Phase 8: empty result for {nq.question}")
                    continue

                # ── Fan-out de-fan (deterministic, #1 correctness lever) ─────────
                # A SUM of a parent measure across a one-to-many join over-counts
                # (5x on TPC-H) — and this becomes a Briefing number. Replace it with
                # the exact DISTINCT(parent-key, measure) dedup before interpreting.
                # Adopt only if it dry-runs clean and re-executes; silent otherwise.
                try:
                    from aughor.sql.fanout import detect_fanout, defan
                    _dialect = getattr(self._conn, "dialect", "duckdb")
                    _ff = detect_fanout(sql, sql_writer.table_cols, dialect=_dialect)
                    if _ff:
                        _rw = defan(sql, _ff, dialect=_dialect)
                        if _rw and _rw.strip() != sql.strip() and self._conn.dry_run(_rw)[0]:
                            _rerows = await self._run(_rw, think=f"[de-fan] {think_str}")
                            if _rerows:
                                logger.info(
                                    "[explorer:%s] Phase 8: %s/%s — de-fanned over-counting SUM (%s ⋈ %s)",
                                    self.connection_id, domain, nq.angle, _ff.satellites, _ff.children,
                                )
                                sql, rows = _rw, _rerows
                except Exception:
                    pass

                # ── Intent-preservation gate (#2) ───────────────────────────────
                # A repair can make a query RUN while silently changing its MEANING. The
                # highest-confidence, deterministic case: the repair DE-TEMPORALISES a time-based
                # question — the invoice case computed invoice AGE via DATE_DIFF on a date plus a
                # date-range filter, and the "fix" swapped in a plain payment-delay column,
                # stripping every temporal construct. When the repair substituted columns AND the
                # original computed over time but the repaired query no longer does, the result
                # answers a DIFFERENT question — drop it (a runnable-but-wrong finding is worse
                # than none). No LLM judgement: an LLM rated this exact drift "faithful".
                if sql != nq.sql:
                    _removed = _query_columns(nq.sql) - _query_columns(sql)
                    _detemporalised = bool(_removed) and _has_temporal_sql(nq.sql) and not _has_temporal_sql(sql)
                    _vacuous = _has_vacuous_temporal(sql)
                    if _detemporalised or _vacuous:
                        logger.info(
                            "[explorer:%s] Phase 8: %s/%s — dropping finding; repair %s a time-based "
                            "question (removed %s, added %s)",
                            self.connection_id, domain, nq.angle,
                            "neutered (DATE_DIFF of identical dates → constant)" if _vacuous else "de-temporalised",
                            sorted(_removed), sorted(_query_columns(sql) - _query_columns(nq.sql)),
                        )
                        continue

                # Format result for LLM interpretation (max 20 rows)
                result_text = "\n".join(str(r) for r in rows[:20])

                # ── Sanity-check: detect impossible ratios before interpretation ──
                # If the SQL contains COUNT(DISTINCT ...) / COUNT(*) across a join,
                # the result may look like "2970 distinct sellers per 110k orders" when
                # 2970 is actually the global seller population — catch and skip.
                _skip_result = False
                try:
                    sql_upper = sql.upper()
                    has_join = "JOIN" in sql_upper
                    # Detect either banned ratio pattern:
                    #   COUNT(DISTINCT x) / COUNT(*)           — child vs all rows
                    #   COUNT(DISTINCT x) / COUNT(DISTINCT y)  — total-A / total-B
                    # Detect either banned ratio pattern (must have an actual division):
                    #   COUNT(DISTINCT x) / COUNT(*)           — child vs all rows
                    #   COUNT(DISTINCT x) / COUNT(DISTINCT y)  — total-A / total-B
                    import re as _re
                    _div_ratio_pat = _re.compile(
                        r"COUNT\s*\(\s*DISTINCT[^)]+\)"   # COUNT(DISTINCT x)
                        r"[\s\d.*]*"                       # optional multiplier/cast
                        r"/"                               # division
                        r"\s*COUNT\s*\(",                  # / COUNT(
                        _re.IGNORECASE,
                    )
                    has_distinct_div = bool(_div_ratio_pat.search(sql_upper))
                    if has_join and has_distinct_div:
                        # Check if any result value could be a spurious ratio:
                        # if a "distinct_X_count" cell value equals a known total cardinality
                        # for a global dimension column, the ratio is meaningless.
                        for row in rows[:5]:
                            for cell in row:
                                try:
                                    val = int(cell) if cell is not None else None
                                except (ValueError, TypeError):
                                    val = None
                                if val is None:
                                    continue
                                # Check against known global cardinalities from cp
                                for tbl_p, col_profiles in (cp or {}).items():
                                    for col_n, col_p in col_profiles.items():
                                        dc = getattr(col_p, "distinct_count", None)
                                        if dc and abs(val - dc) <= max(2, dc * 0.01):
                                            # Value equals a known global cardinality
                                            # Only flag if this looks like a "per-X" misread
                                            if col_n.endswith("_id") and not getattr(col_p, "is_low_cardinality", True):
                                                logger.info(
                                                    "[explorer:%s] Phase 8: skipping likely grain-confused result "
                                                    "— result cell %d matches global cardinality of %s.%s (%d). "
                                                    "SQL had JOIN+COUNT(DISTINCT)/COUNT(*).",
                                                    self.connection_id, val, tbl_p, col_n, dc,
                                                )
                                                _skip_result = True
                except Exception:
                    pass

                # ── Two grain bugs detect_fanout/the ratio check above miss: integer
                # division of aggregates (→ avg=1.0, "all orders 3 items") and a single-join
                # COUNT(*) aliased as a PARENT entity (→ "2000 products" = 25 × 80 items).
                # Both narrate confident WRONG numbers grounding can't catch (the inflated
                # value is a real cell). Skip rather than store a runnable-but-wrong finding.
                if not _skip_result:
                    try:
                        from aughor.sql.fanout import (
                            integer_division_risk, count_star_entity_fanout, count_star_chasm_fanout,
                            avg_over_chasm_fanout,
                        )
                        _tc = getattr(sql_writer, "table_cols", {})
                        # Measure-additivity: per-unit measure summed without ×quantity
                        # (under-count) or per-line measure ×quantity (double-count). Grains
                        # are data-detected once per connection and cached.
                        from aughor.semantic.measure_grain import (
                            connection_measure_grains, measure_grain_misuse,
                        )
                        _mg, _qc = connection_measure_grains(self.connection_id, self._conn, _tc)
                        _grain = (integer_division_risk(sql)
                                  or count_star_entity_fanout(sql, _tc)
                                  or count_star_chasm_fanout(sql, _tc, dialect=getattr(self._conn, "dialect", "duckdb"))
                                  or avg_over_chasm_fanout(sql, _tc, dialect=getattr(self._conn, "dialect", "duckdb"))
                                  or (measure_grain_misuse(sql, _mg, _qc, dialect=getattr(self._conn, "dialect", "duckdb")) if _mg else None))
                        if _grain:
                            from aughor.stats import stats as _s; _s.inc("explorer.grain_skips")
                            logger.info(
                                "[explorer:%s] Phase 8: %s/%s — skipping (SQL grain bug: %s)",
                                self.connection_id, domain, nq.angle, _grain,
                            )
                            _skip_result = True
                    except Exception as _exc:
                        from aughor.kernel.errors import tolerate
                        tolerate(_exc, "grain-bug lint is best-effort; on failure keep the "
                                 "finding (no worse than before the lint existed)",
                                 counter="explorer.grain_lint_failed")

                if _skip_result:
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — result skipped (grain-confused ratio detected)",
                        self.connection_id, domain, nq.angle,
                    )
                    continue

                # Step 3: Interpret the result — run in thread to keep event loop live
                try:
                    _cells_block = numeric_cells_block(rows)
                    _sys3 = (
                        "You are interpreting a SQL query result as a concise business insight. "
                        "Write 1-2 sentences maximum. Include specific numbers from the result. "
                        "Focus on what is actionable or surprising.\n\n"
                        "CRITICAL INTERPRETATION RULES:\n"
                        "- Use ONLY numbers that appear in the result. Copy each value exactly as it "
                        "is — never scale it or add a magnitude suffix (K/M/B) the value does not "
                        "already have. If a cell is 2.49, write 2.49, never 2.49M.\n"
                        "- If a column is labelled 'distinct_X_count' in a grouped query, it is the "
                        "TOTAL distinct count of X across all rows in that group, NOT a per-row average. "
                        "Do NOT say 'X per Y' unless the SQL explicitly computed an average (AVG or ratio "
                        "from a subquery with per-grain counts).\n"
                        "- Only use ratio language ('per order', 'per customer') when the SQL computed "
                        "a genuine per-grain aggregation.\n"
                        "- Novelty score: 1=already known/trivial, 5=genuinely new and surprising."
                    )
                    _usr3 = (
                        f"DOMAIN: {domain}\n"
                        f"QUESTION: {nq.question}\n"
                        f"SQL:\n{sql}\n\n"
                        f"SQL RESULT (first 20 rows):\n{result_text}\n\n"
                        f"NUMERIC VALUES IN THE RESULT (cite these exactly):\n{_cells_block}\n\n"
                        f"{grain_block}"
                        f"EXISTING FINDINGS FOR CONTEXT:\n{existing_findings}\n\n"
                        "Interpret this result as a business insight. "
                        "Be precise about what the numbers represent — do not invent per-row ratios "
                        "from total-level aggregations."
                    )
                    interp: _Interpretation = await _loop.run_in_executor(
                        None,
                        lambda: llm.complete(system=_sys3, user=_usr3, response_model=_Interpretation),
                    )
                except Exception as e:
                    logger.warning(f"[explorer:{self.connection_id}] Phase 8: LLM interpretation failed for {domain}: {e}")
                    continue

                # Drop "no data" findings — an empty/all-NULL result or an interpretation
                # that says as much. They pollute the Briefing and turn into broken monitors.
                if _is_degenerate_result(rows, interp.finding):
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — skipping degenerate (no-data) finding",
                        self.connection_id, domain, nq.angle,
                    )
                    continue

                # Drop fabricated-dimension findings — the model stubbed a missing
                # column with a constant literal ('Unknown' AS channel … GROUP BY
                # channel), yielding a vacuous single-group "breakdown" the narrator
                # dresses up as a real category ("the only channel represented").
                if _has_fabricated_dimension(sql):
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — skipping fabricated-dimension finding (constant grouping key)",
                        self.connection_id, domain, nq.angle,
                    )
                    continue

                # Drop per-grain mislabels (#6) — a line-item AVG presented as a
                # per-order/per-customer metric (AVG(line_total) AS aov). The numeric
                # grounding below can't catch it: the averaged value is a real cell,
                # only the metric name is wrong (the $467-AOV-vs-$1108 case).
                if _mislabeled_per_grain(sql, interp.finding):
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — skipping per-grain mislabel (line-item AVG sold as a per-order metric)",
                        self.connection_id, domain, nq.angle,
                    )
                    continue

                # Drop narration-inversion findings — a per-group/per-row value the
                # narrator universalised over a varying distribution ("3 orders have 1
                # item" → "all orders have 3 items"). Deterministic: fires only when the
                # prose says "all/every/each <entity> have/has <N>" AND N is one of
                # several differing values in the result, so the data disproves it.
                from aughor.agent.verify import inverted_universal_claim
                _inv = inverted_universal_claim(interp.finding, rows)
                if _inv:
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — skipping narration inversion (%s)",
                        self.connection_id, domain, nq.angle, _inv,
                    )
                    continue

                # Drop semantic metric drift (#5) — the self-repair loop swapped the
                # metric column for one with a DIFFERENT business meaning (revenue↔cost,
                # price↔qty) while "fixing" the SQL, so the finding now measures the
                # wrong thing. Compare the original draft (nq.sql) to what actually ran.
                if sql != nq.sql and _semantic_metric_drift(nq.sql, sql):
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — skipping semantic metric drift (repair changed WHAT is measured)",
                        self.connection_id, domain, nq.angle,
                    )
                    continue

                # Ground every magnitude-bearing number in the prose against the real
                # result cells. The narrator sometimes fabricates a magnitude/unit
                # ("2.49M" for a cell of 2.49 — off 1e6). Try one corrective rewrite that
                # may only cite the exact values; if it still can't be grounded, drop the
                # finding rather than headline a wrong number.
                _g = verify_finding(interp.finding, rows)
                if not _g.grounded:
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — ungrounded number(s) %s; re-grounding",
                        self.connection_id, domain, nq.angle, _g.ungrounded,
                    )
                    try:
                        _sys_rg = (
                            "Your previous business insight contained a number that does NOT "
                            "appear in the data — a fabricated magnitude or unit. Rewrite it "
                            "using ONLY values from the provided list. Copy each value exactly; "
                            "never scale it or add a magnitude suffix (K/M/B) it does not already "
                            "have. If a number cannot be supported by the list, drop it and "
                            "describe the pattern qualitatively. 1-2 sentences. Keep the same "
                            "novelty and angle_covered."
                        )
                        _usr_rg = (
                            f"QUESTION: {nq.question}\n"
                            f"SQL:\n{sql}\n\n"
                            f"EXACT RESULT VALUES YOU MAY CITE:\n{numeric_cells_block(rows)}\n\n"
                            f"YOUR PREVIOUS (UNGROUNDED) INSIGHT:\n{interp.finding}\n\n"
                            f"Ungrounded number(s) to remove or fix: {', '.join(_g.ungrounded)}\n"
                            "Rewrite it grounded strictly in the exact values above."
                        )
                        interp_rg: _Interpretation = await _loop.run_in_executor(
                            None,
                            lambda: llm.complete(system=_sys_rg, user=_usr_rg, response_model=_Interpretation),
                        )
                        if verify_finding(interp_rg.finding, rows).grounded:
                            interp = interp_rg
                            _g = GroundingResult(grounded=True)
                    except Exception as e:
                        logger.warning(
                            "[explorer:%s] Phase 8: re-grounding failed for %s: %s",
                            self.connection_id, domain, e,
                        )
                if not _g.grounded:
                    logger.info(
                        "[explorer:%s] Phase 8: %s/%s — dropping finding with unverifiable "
                        "number(s) %s",
                        self.connection_id, domain, nq.angle, _g.ungrounded,
                    )
                    continue

                # Step 4: Store the insight
                insight_id = f"{domain}__{nq.angle}__{used}"
                insight = {
                    "id": insight_id,
                    "domain": domain,
                    "angle": interp.angle_covered or nq.angle,
                    "entities_involved": [e.id for e in entities[:4]],
                    "dimensions": [],
                    "measures": [],
                    "finding": interp.finding,
                    # The query that ACTUALLY produced the result — after the self-repair
                    # loop fixed column/binder errors (and any Tier-3 approx rewrite). Storing
                    # nq.sql here showed a non-runnable draft as "the data behind this claim",
                    # breaking the Evidence layer's provenance.
                    "sql": sql,
                    "confidence": min(0.95, 0.4 + _clamp_novelty(interp.novelty) * 0.1),
                    "novelty": _clamp_novelty(interp.novelty),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "canvas_id": self.canvas_id,
                    "promoted_to_org": False,
                    "promotion_confidence": 0.0,
                }
                self._state.setdefault("insights", []).append(insight)
                domain_insights.append(insight)
                self._emit_insight(insight, sql, journal_extra={"domain": domain})

                # Mark angle as covered
                angle_key = interp.angle_covered or nq.angle
                covered = coverage.get(domain, [])
                if angle_key not in covered:
                    covered.append(angle_key)
                    coverage[domain] = covered
                self._state["domain_coverage"] = coverage
                self._status.domain_budgets = dict(budgets)
                self._status.domain_coverage = dict(coverage)

                self._save_state()
                logger.info(
                    f"[explorer:{self.connection_id}] Phase 8: {domain}/{angle_key} — "
                    f"novelty={interp.novelty} — \"{interp.finding[:80]}…\""
                )


# ── Helpers (module-level) ────────────────────────────────────────────────────

def _find_status_col(col_map: dict) -> Optional[str]:
    """Return the most likely lifecycle/status column in a table's column map."""
    for col_name, col_p in col_map.items():
        if (
            col_p.semantic_type == "dimension"
            and col_p.is_low_cardinality
            and col_p.top_values
            and any(
                v.lower() in _TERMINAL | _ACTIVE
                or any(s in v.lower() for s in _TERMINAL_SUBS + _ACTIVE_SUBS)
                for v in col_p.top_values
            )
        ):
            return col_name
    return None


def _classify_states(states: list[str]) -> tuple[list[str], list[str]]:
    """Split a list of state names into (terminal, active) buckets."""
    terminal: list[str] = []
    active: list[str] = []
    for s in states:
        sl = s.lower()
        if sl in _TERMINAL or any(t in sl for t in _TERMINAL_SUBS):
            terminal.append(s)
        elif sl in _ACTIVE or any(a in sl for a in _ACTIVE_SUBS):
            active.append(s)
    return terminal, active


def _classify_shape(mn: float, mx: float, mean: float, std: float, pct_zero: float) -> DistributionShape:
    """Heuristic distribution shape from basic stats."""
    if mn >= 0 and mx <= 1.01:
        return DistributionShape.FRACTION_0_1
    if std == 0 or mx == mn:
        return DistributionShape.CONCENTRATED
    cv = std / abs(mean) if mean != 0 else float("inf")
    if pct_zero > 0.5 and cv > 1.5:
        return DistributionShape.CONCENTRATED
    if cv > 2.0:
        return DistributionShape.SKEWED_RIGHT
    if cv < 0.15:
        return DistributionShape.CONCENTRATED
    return DistributionShape.NORMAL
