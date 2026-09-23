"""The monitor rules as pure functions — ONE definition, read by the runner that fires an
alert, the backtest that replays it and the Watcher that proposes it.

Measured before this module: the runner scored a day against every prior row, the Watcher's
replay scored it against a rolling 30-day window — two definitions of "anomaly", so a watch
could be proposed on one replay and fire on another. A backtest is only a promise about the
rule that will actually run, so the rule lives here and the callers share it.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Optional

#: Fewer prior points than this and a σ is a guess — the runner records a baseline instead.
MIN_HISTORY = 5
#: A z at or beyond this multiple of the threshold reads as critical rather than warning.
CRITICAL_FACTOR = 1.5


@dataclass(frozen=True)
class AnomalyVerdict:
    fired: bool
    z: float
    mean: float
    std: float
    severity: str = ""       # "critical" | "warning" | ""
    direction: str = ""      # "above" | "below" | ""

    @property
    def baseline_building(self) -> bool:
        return self.std == 0.0 and self.z == 0.0 and not self.fired


def anomaly_verdict(history: list[float], current: float, sigma: float) -> AnomalyVerdict:
    """The runner's anomaly rule: ``current`` against the mean and population σ of
    ``history``; fires at ``sigma`` standard deviations, critical at 1.5× that."""
    if len(history) < MIN_HISTORY:
        return AnomalyVerdict(False, 0.0, float(mean(history)) if history else 0.0, 0.0)
    mu, sd = float(mean(history)), float(pstdev(history))
    if sd < 1e-9:
        return AnomalyVerdict(False, 0.0, mu, sd)
    z = abs(current - mu) / sd
    if z < sigma:
        return AnomalyVerdict(False, z, mu, sd)
    return AnomalyVerdict(True, z, mu, sd,
                          severity="critical" if z >= sigma * CRITICAL_FACTOR else "warning",
                          direction="above" if current > mu else "below")


@dataclass(frozen=True)
class ThresholdVerdict:
    fired: bool
    severity: str = ""       # "critical" | "warning" | ""
    threshold: Optional[float] = None


def threshold_verdict(value: float, *, direction: str, warning: Optional[float],
                      critical: Optional[float]) -> ThresholdVerdict:
    """The runner's threshold rule: critical first, then warning; ``direction`` says which
    side of the line is the breach."""
    def crossed(threshold: float) -> bool:
        return value < threshold if direction == "below" else value > threshold
    if critical is not None and crossed(critical):
        return ThresholdVerdict(True, "critical", critical)
    if warning is not None and crossed(warning):
        return ThresholdVerdict(True, "warning", warning)
    return ThresholdVerdict(False)
