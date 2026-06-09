"""Temporal Tier 2 — multi-resolution macro context.

Tier 0/1 (see agent.py + regime.py) bound the *micro* window: the recent, active
regime the expensive curiosity-loop explores. Tier 2 adds the cheap *macro* layer —
one coarse full-span rollup (yearly/quarterly) over the anchor activity table — so
briefings can juxtapose the long arc against the current regime:

    "revenue grew 4× over 8 years, but the current 2-yr regime is flattening."

A fixed window can't produce that juxtaposition. This module is pure (no DB / LLM);
the explorer feeds it a rollup series and persists the result for the briefing.
See docs/ADAPTIVE_TEMPORAL_SCOPE.md §5.
"""
from __future__ import annotations

from typing import Optional

_SENTINEL_MAX_YEAR = 9999
_SENTINEL_MIN_YEAR = 1900


def _fmt(n: float) -> str:
    """Compact human number: 1234 → 1.2k, 3_900_000 → 3.9M."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    a = abs(n)
    if a >= 1e9:
        return f"{n / 1e9:.1f}B"
    if a >= 1e6:
        return f"{n / 1e6:.1f}M"
    if a >= 1e3:
        return f"{n / 1e3:.1f}k"
    if a == int(a):
        return str(int(n))
    return f"{n:.1f}"


def _growth(first: float, last: float) -> Optional[str]:
    """Multiplicative growth descriptor first→last, or None if not meaningful."""
    try:
        first = float(first); last = float(last)
    except (TypeError, ValueError):
        return None
    if first <= 0:
        return None
    factor = last / first
    if factor >= 1.15:
        return f"grew {factor:.1f}×"
    if factor <= 0.87:
        return f"shrank to {factor:.2f}× ({(1 - factor) * 100:.0f}% lower)"
    return "held roughly flat"


def _year_of(period: str) -> Optional[int]:
    try:
        return int(str(period)[:4])
    except (TypeError, ValueError):
        return None


def build_macro_context(
    periods,
    counts,
    *,
    measures=None,
    measure_name: Optional[str] = None,
    micro_start: Optional[str] = None,
    grain: str = "year",
    anchor: Optional[str] = None,
    min_periods: int = 3,
) -> Optional[dict]:
    """Build the macro long-arc context from a full-span rollup series.

    periods       — period labels (e.g. ["2018", "2019", ...] or "2018-Q1")
    counts        — row count per period (aligned with periods)
    measures      — optional measure sum per period (aligned); may contain None
    measure_name  — the measure column rolled up (for labelling)
    micro_start   — the Tier-1 micro-window start, for the juxtaposition line
    grain/anchor  — rollup grain and anchor table, for labelling
    min_periods   — minimum non-sentinel periods required to emit a macro arc.
                    At year grain the default of 3 guarantees ≥1 complete interior
                    year, so partial boundary years (a fact table that starts in Nov
                    or ends in May) can't masquerade as YoY growth — only a genuine
                    multi-year arc is surfaced.

    Returns a serialisable dict, or None when the span is too short to be a real
    long arc (a deliberately conservative gate — better silent than misleading).
    """
    if not periods or not counts or len(periods) != len(counts):
        return None

    # Drop sentinel periods (9999/1900 placeholders) and non-parseable labels.
    series = []
    for i, p in enumerate(periods):
        yr = _year_of(p)
        if yr is None or yr >= _SENTINEL_MAX_YEAR or yr <= _SENTINEL_MIN_YEAR:
            continue
        m = None
        if measures is not None and i < len(measures):
            m = measures[i]
        series.append({"period": str(p)[:10], "rows": counts[i], "measure": m})

    if len(series) < max(2, min_periods):
        return None

    first, last = series[0], series[-1]
    rows_growth = _growth(first["rows"], last["rows"])

    measure_growth = None
    has_measure = measure_name is not None and all(s["measure"] is not None for s in (first, last))
    if has_measure:
        measure_growth = _growth(first["measure"], last["measure"])

    return {
        "grain": grain,
        "anchor": anchor,
        "first_period": first["period"],
        "last_period": last["period"],
        "n_periods": len(series),
        "rows_first": first["rows"],
        "rows_last": last["rows"],
        "rows_growth": rows_growth,
        "measure_name": measure_name if has_measure else None,
        "measure_first": first["measure"] if has_measure else None,
        "measure_last": last["measure"] if has_measure else None,
        "measure_growth": measure_growth,
        "micro_start": micro_start,
        # cap the per-period detail to keep the prompt block small
        "series": series[-12:],
    }


def render_macro_context(ctx: Optional[dict]) -> str:
    """Format the macro context as a compact prompt/annotation block. '' when absent."""
    if not ctx:
        return ""
    grain = ctx.get("grain", "year")
    anchor = ctx.get("anchor")
    on = f" on `{anchor}`" if anchor else ""
    lines = [
        "LONG-ARC CONTEXT (macro — full history; juxtapose against the recent-regime findings):",
        f"  Span: {ctx['first_period']} → {ctx['last_period']} "
        f"({ctx['n_periods']} {grain}s){on}.",
    ]
    arc_bits = []
    if ctx.get("rows_growth"):
        arc_bits.append(
            f"Activity {ctx['rows_growth']} ({_fmt(ctx['rows_first'])} → {_fmt(ctx['rows_last'])} rows/{grain})"
        )
    if ctx.get("measure_growth"):
        arc_bits.append(
            f"{ctx['measure_name']} {ctx['measure_growth']} "
            f"({_fmt(ctx['measure_first'])} → {_fmt(ctx['measure_last'])})"
        )
    if arc_bits:
        lines.append("  " + ". ".join(arc_bits) + ".")
    if ctx.get("micro_start"):
        lines.append(f"  Current deep-dive regime: since {ctx['micro_start']} — recent findings reflect this window, not the full span.")
    if ctx.get("series"):
        ybits = []
        for s in ctx["series"]:
            label = s["period"][:7] if grain != "year" else s["period"][:4]
            if s.get("measure") is not None:
                ybits.append(f"{label}={_fmt(s['rows'])}/{_fmt(s['measure'])}")
            else:
                ybits.append(f"{label}={_fmt(s['rows'])}")
        lines.append("  By " + grain + ": " + ", ".join(ybits))
    return "\n".join(lines)
