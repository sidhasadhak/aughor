"""Temporal scope — Tier 0: role-aware recency window anchoring.

Extracted from the explorer/agent.py god-file (K4 code-health split). Tier 0 bounds
the analytical window: it anchors recency on the CONSENSUS TRAILING EDGE OF ACTIVITY
among measure-bearing fact/event tables (never MAX(any date column)) and clamps the
window start to the earliest fact — so a calendar/date-dimension spine that runs far
into the future can't push the window past the last real fact and turn every fact
filter into a "no data" briefing.

Tier 1 (the recent active regime) lives in regime.py; Tier 2 (the macro long-arc
rollup) in temporal.py. See docs/ADAPTIVE_TEMPORAL_SCOPE.md §3.

Public entry points (imported by the explorer):
  - role_aware_time_window(tp, cp, jmap, months) -> (start, end, discrepancy)
  - window_for_tables(tp, cp, tables, months)    -> (start, end) | None   (per-dataset)
  - anchor_activity(tp, cp)                       -> (table, recency, is_effective)
  - days_between(a, b) / profile_field(prof, name) — shared primitives

The remaining helpers (_table_recency, _is_calendar_spine, _is_activity_table,
_table_has_measure, _col_name, _table_min) are module-internal.
"""
from __future__ import annotations

import re
from datetime import datetime

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


def profile_field(prof, name):
    """Read a field from a TableProfile/ColumnProfile that may be a dataclass or a dict."""
    if isinstance(prof, dict):
        return prof.get(name)
    return getattr(prof, name, None)


def _table_recency(prof):
    """Sentinel-filtered recency for a table — (YYYY-MM-DD, is_effective) or (None, False).
    Prefers the dense ``effective_date_range`` over the raw ``date_range``."""
    for key, is_eff in (("effective_date_range", True), ("date_range", False)):
        rng = profile_field(prof, key)
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
    return any(profile_field(c, "semantic_type") == "measure" for c in vals)


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
        if profile_field(c, "semantic_type") == "measure"
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


def days_between(a: str, b: str) -> int:
    """Absolute day gap between two ISO date strings; 0 on parse error."""
    try:
        return abs((datetime.fromisoformat(b[:10]) - datetime.fromisoformat(a[:10])).days)
    except (ValueError, TypeError):
        return 0


# When two activity tables share (nearly) the same trailing edge, the *core fact*
# (most rows) is the better anchor than a fresher-by-days peripheral table — a tiny
# `campaigns` (5K rows) ending the same day as a 6.4M-row `order_items` should not win.
_ANCHOR_RECENCY_TOLERANCE_DAYS = 45


def anchor_activity(tp, cp=None):
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
        rows = profile_field(prof, "row_count") or 0
        (activity if _is_activity_table(table, (cp or {}).get(table)) else spine).append(
            (rec, is_eff, table, rows))
    pool = activity or spine
    if not pool:
        return None, None, False

    latest = max(r[0] for r in pool)
    # Tables effectively at the trailing edge (within tolerance of the latest recency).
    fresh = [r for r in pool if days_between(r[0], latest) <= _ANCHOR_RECENCY_TOLERANCE_DAYS]
    # Among those, the core fact (most rows) wins; recency breaks any row-count tie.
    rec, is_eff, table, _rows = max(fresh, key=lambda r: (r[3], r[0]))
    return table, rec, is_eff


def _table_min(prof):
    """Sentinel-filtered earliest date for a table — 'YYYY-MM-DD' or None. Mirrors
    ``_table_recency`` on the range *start*, preferring the dense effective range."""
    for key in ("effective_date_range", "date_range"):
        rng = profile_field(prof, key)
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


def role_aware_time_window(tp, cp=None, jmap=None, months: int = 12):
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

    _anchor, best_rec, best_eff = anchor_activity(tp, cp)
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


def window_for_tables(tp, cp, tables, months: int = 12):
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
    start, end, _ = role_aware_time_window(sub_tp, sub_cp, None, months)
    return (start, end) if start and end else None
