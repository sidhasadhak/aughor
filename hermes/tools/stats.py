"""Statistical analysis tools — anomaly detection, trend analysis."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats as scipy_stats


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


def detect_anomaly(historical_values: list[float], current_value: float, threshold_sigma: float = 2.0) -> AnomalyResult:
    """
    Z-score based anomaly detection.
    Returns whether current_value is statistically unusual vs the historical baseline.
    """
    arr = np.array(historical_values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0

    z_score = (current_value - mean) / std if std > 0 else 0.0
    is_anomaly = abs(z_score) > threshold_sigma
    direction = "below" if z_score < 0 else "above"
    percentile = float(scipy_stats.percentileofscore(arr, current_value))

    pct_change = ((current_value - mean) / mean * 100) if mean != 0 else 0.0
    interpretation = (
        f"Current value ({current_value:,.1f}) is {abs(pct_change):.1f}% {direction} "
        f"the historical mean ({mean:,.1f}), at {percentile:.0f}th percentile "
        f"[z={z_score:.2f}, {'ANOMALY' if is_anomaly else 'normal'}]"
    )

    return AnomalyResult(
        value=current_value,
        mean=mean,
        std=std,
        z_score=z_score,
        is_anomaly=is_anomaly,
        direction=direction,
        percentile=percentile,
        interpretation=interpretation,
    )


@dataclass
class TrendResult:
    slope: float
    r_squared: float
    direction: str
    interpretation: str


def detect_trend(values: list[float]) -> TrendResult:
    """Linear regression trend over a series."""
    if len(values) < 3:
        return TrendResult(0, 0, "flat", "Insufficient data for trend analysis")

    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    slope, intercept, r, p, se = scipy_stats.linregress(x, y)
    r_sq = r ** 2

    if abs(slope) < 0.001 * np.mean(y):
        direction = "flat"
    elif slope > 0:
        direction = "upward"
    else:
        direction = "downward"

    interpretation = (
        f"Trend is {direction} (slope={slope:.4f}/day, R²={r_sq:.2f}). "
        f"{'Strong' if r_sq > 0.7 else 'Weak'} linear fit."
    )
    return TrendResult(slope=float(slope), r_squared=float(r_sq), direction=direction, interpretation=interpretation)
