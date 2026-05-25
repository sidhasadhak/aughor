"""Statistical analysis tools — anomaly detection, trend analysis, period comparison.

Auto-analyzes query results and attaches statistical grounding to evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy import stats as scipy_stats


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class AnomalyResult:
    value: float
    mean: float
    std: float
    z_score: float
    is_anomaly: bool
    direction: str
    percentile: float
    interpretation: str


@dataclass
class TrendResult:
    slope: float
    r_squared: float
    direction: str
    interpretation: str


@dataclass
class StatResult:
    """Attached to a QueryResult after auto-analysis."""
    type: str                        # "anomaly" | "trend" | "comparison" | "distribution"
    interpretation: str              # human-readable, injected into LLM evidence
    is_significant: bool
    sigma: Optional[float] = None    # z-score magnitude when relevant
    p_value: Optional[float] = None  # for Mann-Whitney comparisons


# ── Core: anomaly detection ───────────────────────────────────────────────────

def detect_anomaly(
    historical_values: list[float],
    current_value: float,
    threshold_sigma: float = 2.0,
) -> AnomalyResult:
    """Z-score anomaly detection. current_value vs historical_values baseline."""
    arr = np.array(historical_values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

    z = (current_value - mean) / std if std > 0 else 0.0
    is_anomaly = abs(z) > threshold_sigma
    direction = "below" if z < 0 else "above"
    pct = float(scipy_stats.percentileofscore(arr, current_value))
    pct_change = ((current_value - mean) / mean * 100) if mean != 0 else 0.0

    interp = (
        f"Current value ({current_value:,.1f}) is {abs(pct_change):.1f}% {direction} "
        f"the historical mean ({mean:,.1f}), {pct:.0f}th percentile "
        f"[z={z:.2f}, {'ANOMALY' if is_anomaly else 'normal'}]"
    )
    return AnomalyResult(
        value=current_value, mean=mean, std=std, z_score=z,
        is_anomaly=is_anomaly, direction=direction, percentile=pct,
        interpretation=interp,
    )


# ── Core: trend ───────────────────────────────────────────────────────────────

def detect_trend(values: list[float]) -> TrendResult:
    """Linear regression trend over an ordered series."""
    if len(values) < 3:
        return TrendResult(0, 0, "flat", "Insufficient data for trend analysis")

    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    slope, _, r, _, _ = scipy_stats.linregress(x, y)
    r_sq = r ** 2

    if abs(slope) < 0.001 * (np.mean(y) or 1):
        direction = "flat"
    elif slope > 0:
        direction = "upward"
    else:
        direction = "downward"

    interp = (
        f"Trend is {direction} (slope={slope:.4f}/period, R²={r_sq:.2f}). "
        f"{'Strong' if r_sq > 0.7 else 'Weak'} linear fit."
    )
    return TrendResult(slope=float(slope), r_squared=float(r_sq), direction=direction, interpretation=interp)


# ── Core: period comparison (Mann-Whitney U) ──────────────────────────────────

def compare_periods(group_a: list[float], group_b: list[float]) -> StatResult:
    """
    Non-parametric test: are two distributions significantly different?
    Use for before/after comparisons (e.g. pre-anomaly vs anomaly window).
    """
    if len(group_a) < 3 or len(group_b) < 3:
        return StatResult(
            type="comparison",
            interpretation="Insufficient data for period comparison (need ≥ 3 values per group).",
            is_significant=False,
        )

    stat, p = scipy_stats.mannwhitneyu(group_a, group_b, alternative="two-sided")
    mean_a = float(np.mean(group_a))
    mean_b = float(np.mean(group_b))
    pct_change = ((mean_b - mean_a) / mean_a * 100) if mean_a != 0 else 0.0
    direction = "higher" if pct_change > 0 else "lower"
    significant = p < 0.05

    interp = (
        f"Period B is {abs(pct_change):.1f}% {direction} than Period A "
        f"(means: {mean_a:,.1f} → {mean_b:,.1f}). "
        f"Mann-Whitney p={p:.4f} — {'statistically significant' if significant else 'not significant'} at α=0.05."
    )
    return StatResult(
        type="comparison",
        interpretation=interp,
        is_significant=significant,
        p_value=float(p),
    )


# ── Auto-analysis: called on every successful QueryResult ────────────────────

def analyze_query_result(columns: list[str], rows: list[list]) -> list[StatResult]:
    """
    Inspect a query result and run whichever statistical tests are appropriate.
    Returns a (possibly empty) list of StatResult to attach to the QueryResult.
    """
    if not rows or not columns:
        return []

    results: list[StatResult] = []

    # Find numeric column indices
    numeric_idxs = _numeric_column_indices(columns, rows)
    if not numeric_idxs:
        return []

    date_idx = _date_column_index(columns)

    for num_idx in numeric_idxs[:2]:  # analyse at most 2 numeric columns
        values = _extract_floats(rows, num_idx)
        if len(values) < 4:
            continue

        col_name = columns[num_idx]

        # Time-series path: date column present and enough rows
        if date_idx is not None and date_idx != num_idx and len(values) >= 10:
            stat = _analyze_time_series(col_name, values)
            if stat:
                results.append(stat)

        # Distribution path: group labels + values (no date col, or date already handled)
        elif date_idx is None and len(values) >= 5:
            stat = _analyze_distribution(col_name, values)
            if stat:
                results.append(stat)

        # Trend path: ordered numeric series
        if len(values) >= 6:
            trend = detect_trend(values)
            if trend.r_squared > 0.5:  # only surface strong trends
                results.append(StatResult(
                    type="trend",
                    interpretation=f"[{col_name}] {trend.interpretation}",
                    is_significant=trend.r_squared > 0.7,
                ))

    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _analyze_time_series(col_name: str, values: list[float]) -> Optional[StatResult]:
    """
    Try STL decomposition (statsmodels) for seasonality-aware anomaly detection.
    Falls back to plain z-score if STL fails or series is too short.
    """
    last = values[-1]
    baseline = values[:-1]

    # Attempt STL with weekly period (7) if we have at least 2 full periods
    if len(values) >= 14:
        try:
            from statsmodels.tsa.seasonal import STL
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                stl = STL(values, period=7, robust=True)
                fit = stl.fit()
            residuals = list(fit.resid)
            # Anomaly = is the last residual unusual vs residual history?
            res_baseline = residuals[:-1]
            res_last = residuals[-1]
            anomaly = detect_anomaly(res_baseline, res_last)
            label = "STL-decomposed residual" if anomaly.is_anomaly else "STL residual"
            return StatResult(
                type="anomaly",
                interpretation=(
                    f"[{col_name}] After removing seasonality ({label}): "
                    f"{anomaly.interpretation}"
                ),
                is_significant=anomaly.is_anomaly,
                sigma=round(abs(anomaly.z_score), 2),
            )
        except Exception:
            pass  # fall through to z-score

    # Fallback: plain z-score on raw values
    anomaly = detect_anomaly(baseline, last)
    return StatResult(
        type="anomaly",
        interpretation=f"[{col_name}] {anomaly.interpretation}",
        is_significant=anomaly.is_anomaly,
        sigma=round(abs(anomaly.z_score), 2),
    )


def _analyze_distribution(col_name: str, values: list[float]) -> Optional[StatResult]:
    """Z-score across group values — flags outlier segments."""
    arr = np.array(values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    if std == 0:
        return None

    z_scores = (arr - mean) / std
    max_z_idx = int(np.argmax(np.abs(z_scores)))
    max_z = float(z_scores[max_z_idx])

    if abs(max_z) < 1.5:
        return None  # nothing interesting

    direction = "above" if max_z > 0 else "below"
    return StatResult(
        type="distribution",
        interpretation=(
            f"[{col_name}] Distribution across {len(values)} groups: "
            f"most extreme value is {abs(max_z):.1f}σ {direction} the mean "
            f"({values[max_z_idx]:,.1f} vs mean {mean:,.1f})."
        ),
        is_significant=abs(max_z) >= 2.0,
        sigma=round(abs(max_z), 2),
    )


_DATE_KEYWORDS = ("date", "day", "week", "month", "year", "time", "period", "_at", "_on")
_NUMERIC_SKIP = ("id", "rank", "row", "index", "num", "count_star")


def _date_column_index(columns: list[str]) -> Optional[int]:
    for i, col in enumerate(columns):
        if any(kw in col.lower() for kw in _DATE_KEYWORDS):
            return i
    return None


def _numeric_column_indices(columns: list[str], rows: list[list]) -> list[int]:
    idxs = []
    for i, col in enumerate(columns):
        if any(kw in col.lower() for kw in _NUMERIC_SKIP):
            continue
        try:
            floats = [float(row[i]) for row in rows[:20] if row[i] not in (None, "NULL", "")]
            if len(floats) >= 2:
                idxs.append(i)
        except (ValueError, TypeError, IndexError):
            pass
    return idxs


def _extract_floats(rows: list[list], col_idx: int) -> list[float]:
    result = []
    for row in rows:
        try:
            v = row[col_idx]
            if v not in (None, "NULL", ""):
                result.append(float(v))
        except (ValueError, TypeError, IndexError):
            pass
    return result
