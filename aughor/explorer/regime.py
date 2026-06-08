"""Temporal Tier 1 — current-regime detection (statistical, not "last X").

Given a time-ordered activity series (rows per period, oldest → newest), find the start
of the CURRENT statistical regime — the analytical window should cover "since the last
sustained level shift," not an arbitrary 12 months. If a business 3×'d its volume or
pivoted in 2022, analyzing 2014–2021 pollutes the read.

Dependency-light (no `ruptures`/`scipy` — pure Python) and deterministic, so it is fully
unit-testable. Conservative: when there isn't enough history or no material shift, it
falls back to the full span rather than inventing a regime. A sufficiency constraint
keeps the current regime long enough for a trend at the chosen grain.

See docs/ADAPTIVE_TEMPORAL_SCOPE.md §4. This module is the pure algorithm; wiring the
density-series query into the explorer is the remaining Tier-1 integration step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RegimeResult:
    start: int                       # index into the series where the current regime begins
    changepoint: Optional[int]       # the detected shift index, or None if none
    reason: str
    before_level: Optional[float] = None
    after_level: Optional[float] = None


def _mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def detect_current_regime(
    counts,
    *,
    min_periods: int = 6,
    min_rel_shift: float = 0.5,
) -> RegimeResult:
    """Detect the start of the most recent sustained level shift in ``counts``.

    ``min_periods``  — both the prior and the current regime must hold at least this many
                       periods (sufficiency: a trend needs enough points).
    ``min_rel_shift`` — minimum relative change in mean level to call it a regime shift
                       (0.5 = a 50% level change vs the midpoint of the two means).

    Returns a RegimeResult; ``start`` is 0 (full span) when no reliable regime is found.
    """
    counts = [float(c) for c in (counts or [])]
    n = len(counts)
    if n < 2 * min_periods:
        return RegimeResult(0, None, "insufficient history to split — using full span")

    # Single-changepoint binary segmentation: pick the split that minimizes total
    # within-segment variance (sum of squared errors) — for a clean level shift this
    # lands exactly on the boundary. Then gate on significance so noise never splits.
    # (Single dominant break; multi-regime segmentation is a future refinement.)
    best_k, best_sse = None, None
    for k in range(min_periods, n - min_periods + 1):
        before, after = counts[:k], counts[k:]
        mb, ma = _mean(before), _mean(after)
        sse = sum((x - mb) ** 2 for x in before) + sum((x - ma) ** 2 for x in after)
        if best_sse is None or sse < best_sse:
            best_sse, best_k = sse, k

    before, after = counts[:best_k], counts[best_k:]
    mb, ma = _mean(before), _mean(after)
    denom = (abs(mb) + abs(ma)) / 2 or 1.0
    if abs(ma - mb) / denom < min_rel_shift:
        return RegimeResult(0, None, "no significant regime change — using full span")

    return RegimeResult(
        start=best_k, changepoint=best_k,
        reason=f"regime shift at period {best_k} (level {mb:.0f} → {ma:.0f})",
        before_level=mb, after_level=ma,
    )


def adaptive_window(periods, counts, *, min_periods: int = 6, min_rel_shift: float = 0.5):
    """Map a current-regime detection onto dates.

    ``periods`` is the list of period-start date strings (ISO, oldest → newest) aligned 1:1
    with ``counts``. Returns ``(start_date, end_date, reason)`` where start_date is the first
    period of the current regime and end_date is the last period — or (None, None, reason)
    when the inputs are unusable.
    """
    periods = list(periods or [])
    counts = list(counts or [])
    if not periods or len(periods) != len(counts):
        return None, None, "no usable activity series"
    res = detect_current_regime(counts, min_periods=min_periods, min_rel_shift=min_rel_shift)
    start_date = periods[res.start]
    end_date = periods[-1]
    reason = res.reason if res.changepoint is not None else "full span (no regime shift)"
    return start_date, end_date, reason
