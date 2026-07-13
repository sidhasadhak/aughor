"""Grain-feasibility gate — don't answer a MONTHLY question with YEARLY data and
then contradict yourself about why.

The twin of :mod:`aughor.semantic.metric_feasibility` (which guards metric CLASS):
this guards time GRAIN. When a question asks for a breakdown at a finer time grain
(monthly, weekly, daily) than the answer actually delivered (e.g. grouped by
``fiscal_year``), this produces ONE grounded verdict:

  * is a finer-grain path to the same measure present in the schema  → **repair**
  * or is the measure only available at this coarser grain            → **abstain honestly**

so the headline, narrative, the semantic-inspect warning, and the follow-ups stop
disagreeing (the "massive disconnect": inspect says "use ``fiscal_month``" — a
column that doesn't exist — while the narrative says "monthly data is not
available", over a result that is correct but at the wrong grain).

Deterministic, high-precision, schema-grounded, never raises.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Coarser grain ⇒ larger rank. "requested finer than delivered" ⟺ rank(req) < rank(del).
_RANK = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3, "yearly": 4}

# The question asks for a breakdown AT this grain (finest match wins).
_REQ = [
    ("daily",     re.compile(r"\b(daily|day[-\s]?(?:by[-\s]?day|wise)|per[-\s]?day|each day|by day|day[-\s]?level)\b", re.I)),
    ("weekly",    re.compile(r"\b(weekly|week[-\s]?(?:by[-\s]?week|wise)|per[-\s]?week|each week|by week|week[-\s]?level|wow)\b", re.I)),
    ("monthly",   re.compile(r"\b(monthly|month[-\s]?(?:by[-\s]?month|wise)|per[-\s]?month|each month|by month|month[-\s]?level|mom|month[-\s]?over[-\s]?month)\b", re.I)),
    ("quarterly", re.compile(r"\b(quarterly|quarter[-\s]?(?:by[-\s]?quarter|wise)|per[-\s]?quarter|by quarter|quarter[-\s]?level|qoq)\b", re.I)),
    ("yearly",    re.compile(r"\b(yearly|annual\w*|year[-\s]?(?:by[-\s]?year|wise|over[-\s]?year)|per[-\s]?year|by year|year[-\s]?level|yoy)\b", re.I)),
]

# A time column provides down to this grain (a DATE gives daily → every grain above it).
_COL = [
    ("daily",     re.compile(r"(^|_)(date|day|datetime|timestamp|ts|dt|created_at|order_date|txn_date|event_date)(_|$)", re.I)),
    ("weekly",    re.compile(r"(^|_)(week|wk|iso_week|week_start|weeknum)(_|$)", re.I)),
    ("monthly",   re.compile(r"(^|_)(month|mon|month_start|year_month|yearmonth|fiscal_month|period_month)(_|$)", re.I)),
    ("quarterly", re.compile(r"(^|_)(quarter|qtr|fiscal_quarter)(_|$)", re.I)),
    ("yearly",    re.compile(r"(^|_)(year|fiscal_year|calendar_year|fy|yr)(_|$)", re.I)),
]

# Trailing unit/scale tokens stripped to get a measure's stem (net_sales_eur_m → net_sales).
_UNIT_SUFFIX = re.compile(
    r"(_(?:eur|usd|gbp|inr|jpy|cny|m|k|mm|bn|pct|percent|amount|amt|total|value|val|sum|avg))+$", re.I)


@dataclass
class GrainGap:
    """One grounded verdict about a time-grain shortfall."""

    requested: str                        # e.g. "monthly"
    delivered: str                        # e.g. "yearly" ("none" if the result has no time dim)
    feasible_via: Optional[str] = None    # a table that could serve the finer grain, else None → abstain

    @property
    def feasible(self) -> bool:
        return self.feasible_via is not None

    def caveat(self, measure: str = "the measure") -> str:
        """The single honest sentence every channel should agree on."""
        if self.feasible:
            return (f"{self.requested} breakdown was requested but the answer is at {self.delivered} "
                    f"grain — a finer breakdown is available from `{self.feasible_via}`")
        return (f"{self.requested} breakdown was requested, but {measure} is only reported at "
                f"{self.delivered} grain here — there is no finer time column to break it down by")


def requested_time_grain(question: str) -> Optional[str]:
    """The finest time grain the question asks a breakdown at, or None."""
    q = question or ""
    best = None
    for grain, rx in _REQ:
        if rx.search(q) and (best is None or _RANK[grain] < _RANK[best]):
            best = grain
    return best


def _col_grain(col: str) -> Optional[str]:
    for grain, rx in _COL:
        if rx.search(str(col)):
            return grain
    return None


def columns_grain(cols) -> Optional[str]:
    """The FINEST grain any time column in the set provides, or None."""
    best = None
    for c in cols or []:
        g = _col_grain(c)
        if g is not None and (best is None or _RANK[g] < _RANK[best]):
            best = g
    return best


def measure_terms(result_columns) -> list[str]:
    """Measure-column stems (time columns dropped) — the thing being broken down."""
    out = []
    for c in result_columns or []:
        cs = str(c)
        if _col_grain(cs) is not None:
            continue
        stem = _UNIT_SUFFIX.sub("", cs).strip("_").lower()
        if stem:
            out.append(stem)
    return out


def _finer_path(schema: str, measures: list[str], requested: str) -> Optional[str]:
    """A table in the schema carrying a measure AND a time column at least as fine
    as ``requested`` — a genuine repair target. Conservative: None unless clear."""
    if not schema or not measures:
        return None
    try:
        from aughor.tools.schema import parse_schema_tables
        tables = parse_schema_tables(schema)   # {table: [cols...]} best-effort
    except Exception:
        return None
    want = _RANK[requested]
    for tname, cols in (tables or {}).items():
        colset = [str(c) for c in cols]
        tg = columns_grain(colset)
        if tg is None or _RANK[tg] > want:
            continue                            # no time column fine enough
        blob = " ".join(colset).lower()
        if any(m and m in blob for m in measures):
            return tname
    return None


def grain_gap(question: str, result_columns, schema: str = "") -> Optional[GrainGap]:
    """One grounded verdict: does the question want a finer time grain than the
    answer delivered, and is a finer path available? ``None`` when there is no gap
    (no temporal breakdown requested, or the answer already met/exceeded it).
    Never raises."""
    try:
        req = requested_time_grain(question)
        if req is None:
            return None
        delivered = columns_grain(result_columns)
        if delivered is not None and _RANK[delivered] <= _RANK[req]:
            return None                          # already at/finer than requested
        measures = measure_terms(result_columns)
        alt = _finer_path(schema, measures, req)
        return GrainGap(requested=req, delivered=delivered or "none", feasible_via=alt)
    except Exception:
        return None
