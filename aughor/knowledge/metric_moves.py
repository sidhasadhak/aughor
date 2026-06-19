"""
Metric moves — north-star trends as first-class brief candidates.

The biggest thing on a CEO's screen is rarely a single explorer finding — it is a
KPI that *moved* (margin 47% → 34%, AOV €75 → €56, repeat-rate 5% → 15%). Those moves
live in each north-star metric's ``chart_sql`` TIME TREND, not in the explorer's
findings, so the old brief never led with them.

This module turns a material trend into a synthetic "finding" so it competes for the
brief's lead through the SAME impact ranking as every other candidate (see
``knowledge.triage``): a −28% margin move scores high on the change term AND hits the
north-star term, so it out-ranks a noise-level ROAS contrast and earns the headline.

Split into a PURE core (``series_move`` / ``build_move_finding`` — unit-tested, no DB)
and a thin DB driver (``compute_metric_moves`` — runs each metric's chart_sql via an
injected ``run_sql`` and fails open per metric).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from aughor.knowledge.triage import currency_symbol


# A label that reads as a time bucket (year, ISO month, month name, quarter) — the
# signature that tells a TIME TREND (compute a move) from a TOP-N BREAKDOWN (no move).
_DATE_LABEL = re.compile(
    r"\b(?:19|20)\d{2}\b|\d{4}-\d{2}|\bq[1-4]\b|"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*", re.I,
)

# Default: only surface a move of at least this relative magnitude (10%).
MATERIAL_REL = 0.10


@dataclass(frozen=True)
class Move:
    start: float
    end: float
    rel: float        # (end-start)/|start|
    direction: str    # 'up' | 'down'
    points: int


def _num(cell) -> Optional[float]:
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    if isinstance(cell, str):
        s = cell.strip().lstrip("$€£¥₹").rstrip("%").replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def _is_time_trend(labels: list) -> bool:
    """A series is a time trend when most of its labels read as time buckets — so a
    top-N breakdown ('Fragrance', 'Skincare', …) is never mistaken for a move."""
    if not labels:
        return False
    dated = sum(1 for v in labels if v is not None and _DATE_LABEL.search(str(v)))
    return dated >= (len(labels) + 1) // 2


def series_move(columns, rows, min_points: int = 3) -> Optional[Move]:
    """The net first→last move of a TIME-TREND series, or None when it isn't a trend,
    is too short, or has a zero baseline (no defined relative move). Assumes the
    chart_sql ordered its buckets ascending (it does — see NorthStarMetric.chart_sql)."""
    if not rows or len(rows) < min_points:
        return None
    # Normalise to row-lists; label = first column, value = first numeric non-label column.
    norm = [list(r.values()) if isinstance(r, dict) else list(r) for r in rows]
    labels = [r[0] if r else None for r in norm]
    if not _is_time_trend(labels):
        return None
    ncols = max((len(r) for r in norm), default=0)
    val_idx = None
    for i in range(1, ncols):
        col = [_num(r[i]) for r in norm if i < len(r)]
        if col and sum(1 for v in col if v is not None) >= max(min_points, len(col) // 2):
            val_idx = i
            break
    if val_idx is None:
        return None
    vals = [_num(r[val_idx]) if val_idx < len(r) else None for r in norm]
    vals = [v for v in vals if v is not None]
    if len(vals) < min_points:
        return None
    start, end = vals[0], vals[-1]
    if start == 0:
        return None
    rel = (end - start) / abs(start)
    return Move(start=start, end=end, rel=rel,
               direction="up" if end >= start else "down", points=len(vals))


# ── finding synthesis ────────────────────────────────────────────────────────

_PCT_HINT = re.compile(r"percent|ratio|\brate\b|margin|sentiment|share|%", re.I)
_CUR_HINT = re.compile(r"usd|eur|gbp|jpy|cny|inr|\$|€|£|revenue|\bvalue\b|\baov\b|price|spend|sales|order\s+value", re.I)


def _fmt_value(value: float, name: str, unit: str, sym: str) -> str:
    """Format a metric value for prose: percent metrics as 'NN%' (scaling a 0..1 ratio
    up), currency metrics with the business's symbol, everything else as a plain number."""
    hay = f"{name} {unit}"
    if _PCT_HINT.search(hay):
        v = value * 100 if abs(value) <= 1.5 else value
        return f"{v:.0f}%"
    if _CUR_HINT.search(hay):
        return f"{sym}{value:,.0f}" if abs(value) >= 10 else f"{sym}{value:,.2f}"
    return f"{value:g}"


def _fmt_numeric(value: float, name: str, unit: str, sym: str) -> float:
    """The numeric magnitude a value would DISPLAY as (after unit formatting/rounding) —
    so a 0.004 ratio shown as '0%' reads back as 0.0."""
    disp = _fmt_value(value, name, unit, sym)
    cleaned = re.sub(r"[^0-9.eE-]", "", disp) or "0"
    try:
        return abs(float(cleaned))
    except ValueError:
        return 0.0


def is_degenerate_move(move: Move, name: str, unit: str, currency_code: Optional[str]) -> bool:
    """True when a move rests on a near-zero base — its smaller endpoint rounds to zero at
    display precision (the '0% → 1% (+40%)' case). The big relative % is then an artifact of
    a near-zero denominator, not signal, so it must never surface (let alone lead). Mirrors
    the KPI strip's 'no rounds-to-zero on cards' rule, applied to a move's endpoints."""
    sym = currency_symbol(currency_code)
    lo = min(_fmt_numeric(move.start, name, unit, sym), _fmt_numeric(move.end, name, unit, sym))
    return lo == 0.0


def build_move_finding(name: str, unit: str, move: Move, currency_code: Optional[str],
                       domain: str = "Key Metrics") -> dict:
    """A synthetic finding dict describing a metric move, shaped exactly like an explorer
    insight so it flows through triage/impact ranking unchanged. The 'from X to Y (±N%)'
    phrasing is what ``triage.extract_change`` reads to score the move's magnitude."""
    sym = currency_symbol(currency_code)
    verb = "risen" if move.direction == "up" else "fallen"
    start = _fmt_value(move.start, name, unit, sym)
    end = _fmt_value(move.end, name, unit, sym)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    return {
        "id": f"metric-move::{slug}",
        "domain": domain,
        "angle": "Trend",
        "finding": f"{name} has {verb} from {start} to {end} ({move.rel * 100:+.0f}%) over the period.",
        "sql": "",   # populated by the driver with the metric's chart_sql
        "confidence": 0.8,   # a measured trend on the audited metric SQL — high trust
        "novelty": 3,
        "metric_move": True,
    }


# ── DB driver ────────────────────────────────────────────────────────────────

def compute_metric_moves(
    metrics: list[Any],
    run_sql: Callable[[str], tuple],
    currency_code: Optional[str] = None,
    *,
    material_rel: float = MATERIAL_REL,
    max_metrics: int = 8,
) -> list[dict]:
    """Run each north-star metric's ``chart_sql`` and return synthetic findings for the
    MATERIAL time-trend moves, biggest move first.

    ``metrics`` are NorthStarMetric models (or dicts) carrying ``name`` / ``chart_sql`` /
    ``unit_or_range``. ``run_sql(sql) -> (columns, rows, error)`` is injected so this stays
    testable and never imports the DB layer. Fail-open per metric: a chart_sql that errors
    or isn't a trend simply contributes nothing."""
    out: list[tuple[float, dict]] = []
    for m in (metrics or [])[:max_metrics]:
        name = (m.get("name") if isinstance(m, dict) else getattr(m, "name", "")) or ""
        chart_sql = (m.get("chart_sql") if isinstance(m, dict) else getattr(m, "chart_sql", "")) or ""
        unit = (m.get("unit_or_range") if isinstance(m, dict) else getattr(m, "unit_or_range", "")) or ""
        if not name or not chart_sql.strip():
            continue
        try:
            columns, rows, error = run_sql(chart_sql)
        except Exception as _e:
            from aughor.kernel.errors import tolerate
            tolerate(_e, "metric-move: chart_sql execution failed", counter="brief.metric_move.sql_failed")
            continue
        if error or not rows:
            continue
        move = series_move(columns, rows)
        if move is None or abs(move.rel) < material_rel:
            continue
        if is_degenerate_move(move, name, unit, currency_code):
            continue   # near-zero base — a big relative % that is noise, not signal
        finding = build_move_finding(name, unit, move, currency_code)
        finding["sql"] = chart_sql
        out.append((abs(move.rel), finding))
    out.sort(key=lambda t: t[0], reverse=True)
    return [f for _, f in out]
