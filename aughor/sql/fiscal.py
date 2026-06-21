"""Fiscal-period bucketing — apply an org's `fiscal_year_start_month` to time-grain SQL.

A fiscal year that starts in month M (M≠1) shifts QUARTER and YEAR boundaries: a company on
an April fiscal year reports Apr–Jun as Q1, and a date in Feb 2025 belongs to the fiscal year
that started Apr 2024. Calendar `date_trunc` gets these wrong. `fiscal_period_expr` shifts the
date back by (M-1) months, truncates, then shifts forward — so the bucket START is the real
fiscal-period start.

It is a strict NO-OP at the default (month 1 = January → plain `date_trunc`), so existing
calendar-year orgs are byte-for-byte unchanged. DAY/WEEK/MONTH grains are never shifted (a
month is a month regardless of fiscal start). Currently emits DuckDB syntax (Aughor's primary
engine); other dialects fall back to plain calendar `date_trunc` rather than risk wrong SQL.
"""
from __future__ import annotations

from typing import Optional

_SHIFTABLE = {"quarter", "year"}


def fiscal_period_expr(grain: str, col: str, fiscal_start_month: Optional[int] = 1,
                       dialect: str = "duckdb") -> str:
    """Return a SQL expression that buckets `col` into the (fiscal-aware) period `grain`.

    Falls back to plain ``date_trunc('<grain>', <col>)`` — the calendar bucket — whenever the
    fiscal year starts in January (the default), the grain isn't quarter/year, or the dialect
    isn't one we emit fiscal arithmetic for. So a non-fiscal org gets identical SQL."""
    g = (grain or "").strip().lower()
    m = fiscal_start_month or 1
    plain = f"date_trunc('{g}', {col})"
    if g not in _SHIFTABLE or m == 1 or (dialect or "").lower() != "duckdb":
        return plain
    if not (2 <= m <= 12):
        return plain
    n = m - 1   # months to shift so the fiscal-year start lands on a calendar-year start
    return f"(date_trunc('{g}', {col} - INTERVAL {n} MONTH) + INTERVAL {n} MONTH)"
