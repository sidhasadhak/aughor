"""J3 — refuse to attribute what cannot be floor-verified.

A grid produces two numbers and the temptation to subtract them. The Spider 2.0 work
established, expensively, that on a stochastic pipeline that subtraction is usually
meaningless: runs flip-flop between replicates even at temperature 0, so a four-point
difference between a baseline and a variant is only evidence if the baseline does not
differ from *itself* by four points.

So the order of operations here is inverted from the obvious one. Before any two cells are
compared, one cell is compared against itself: replicate the identical configuration and
measure the band it produces. That band is the **noise floor**, and it is the unit every
delta is denominated in. A delta inside the floor is not a small effect — it is not an
observation at all, and this module says so rather than reporting it with a hedge.

Three further pieces, each answering a way a composite score lies:

* **Per-axis repeatability.** A mean with no spread beside it invites a reader to treat
  0.64 and 0.66 as different numbers. Every axis carries its own band and stdev.
* **A harmonic composite.** The arithmetic mean of {1.0, 0.0} is a respectable 0.5, which is
  exactly how a broken axis disappears into a summary. The harmonic mean is 0.0. One broken
  axis must fail loudly, so the composite is harmonic and a zero anywhere zeroes it.
* **A plain-English diagnosis.** A refusal that reports `attributable=False` and stops has
  moved the interpretation problem rather than solved it. Every verdict says what happened,
  in the units the reader already has.

Nothing here calls a model or touches a store: it is arithmetic over `RunSummary` objects,
so it is cheap to test and impossible to get a different answer from twice.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

#: Axes a suite reports natively. `pass_rate` counts stable passes only (a flaky case is not
#: rounded up); `accuracy` is correctness over the cases that declared an expectation.
DEFAULT_AXES = ("pass_rate", "accuracy")

#: Below this, two runs of one configuration are treated as agreeing. Deliberately NOT a
#: round number: `run_golden._aggregate_runs` has used 0.05 as its `unstable` line since the
#: Spider work, measured against what that harness actually produced. Reusing it keeps one
#: definition of "these two runs disagree" in the codebase instead of two.
DEFAULT_FLOOR_THRESHOLD = 0.05


@dataclass(frozen=True)
class Axis:
    """One measured dimension across replicates of ONE configuration."""

    name: str
    values: tuple[float, ...]

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.values) if self.values else 0.0

    @property
    def band(self) -> float:
        """max − min. The honest spread at the tiny n an LLM eval can afford; stdev over
        three points is a number with more decimal places than information."""
        return (max(self.values) - min(self.values)) if self.values else 0.0

    @property
    def stdev(self) -> float:
        """Sample stdev, or 0.0 below two points — reported beside the band, never instead
        of it."""
        return statistics.stdev(self.values) if len(self.values) > 1 else 0.0

    def to_dict(self) -> dict:
        return {"axis": self.name, "n": self.n, "mean": round(self.mean, 4),
                "band": round(self.band, 4), "stdev": round(self.stdev, 4),
                "values": [round(v, 4) for v in self.values]}


@dataclass(frozen=True)
class Floor:
    """How far one configuration disagrees with itself on one axis."""

    axis: str
    replicates: int
    band: float
    stdev: float
    threshold: float
    verified: bool
    reason: str

    def to_dict(self) -> dict:
        return {"axis": self.axis, "replicates": self.replicates,
                "band": round(self.band, 4), "stdev": round(self.stdev, 4),
                "threshold": self.threshold, "verified": self.verified,
                "reason": self.reason}


@dataclass(frozen=True)
class Delta:
    """One baseline-vs-variant comparison, and whether it may be attributed at all."""

    axis: str
    baseline: str
    variant: str
    baseline_mean: float
    variant_mean: float
    delta: float
    floor: Optional[Floor]
    attributable: bool
    verdict: str

    def to_dict(self) -> dict:
        return {"axis": self.axis, "baseline": self.baseline, "variant": self.variant,
                "baseline_mean": round(self.baseline_mean, 4),
                "variant_mean": round(self.variant_mean, 4),
                "delta": round(self.delta, 4),
                "floor": self.floor.to_dict() if self.floor else None,
                "attributable": self.attributable, "verdict": self.verdict}


def _axis_value(summary: Any, name: str) -> Optional[float]:
    """Read one axis off a RunSummary (or anything shaped like one).

    ``None`` propagates rather than defaulting to zero: `accuracy` is None when no case
    declared an expectation, and folding that to 0.0 would report a suite that measured
    nothing as a suite that got everything wrong.
    """
    value = getattr(summary, name, None)
    if value is None and isinstance(summary, dict):
        value = summary.get(name)
    return None if value is None else float(value)


def axis_of(summaries: Sequence[Any], name: str) -> Axis:
    """Collect one axis across replicates, skipping replicates that did not measure it."""
    values = tuple(v for v in (_axis_value(s, name) for s in summaries) if v is not None)
    return Axis(name=name, values=values)


def noise_floor(replicates: Sequence[Any], *, axis: str = "pass_rate",
                threshold: float = DEFAULT_FLOOR_THRESHOLD) -> Floor:
    """Measure how much ONE configuration disagrees with itself.

    ``replicates`` must be repeated runs of the *same* cell. Fewer than two is not a
    conservative floor of zero — it is no floor at all, and the distinction matters because
    a floor of zero would make every delta attributable.
    """
    a = axis_of(replicates, axis)
    if a.n < 2:
        return Floor(axis=axis, replicates=a.n, band=0.0, stdev=0.0, threshold=threshold,
                     verified=False,
                     reason=(f"{a.n} replicate(s): a configuration was never run against "
                             f"itself, so there is no floor to denominate a delta in. "
                             f"Re-run the baseline cell at least twice."))
    if a.band > threshold:
        return Floor(axis=axis, replicates=a.n, band=a.band, stdev=a.stdev,
                     threshold=threshold, verified=False,
                     reason=(f"the same configuration scored {min(a.values):.3f}–"
                             f"{max(a.values):.3f} on {axis} across {a.n} runs, a band of "
                             f"{a.band:.3f} against a threshold of {threshold:.3f}. It "
                             f"disagrees with itself more than most variants will differ, "
                             f"so no delta measured here can be attributed to a change."))
    return Floor(axis=axis, replicates=a.n, band=a.band, stdev=a.stdev, threshold=threshold,
                 verified=True,
                 reason=(f"the same configuration held within {a.band:.3f} on {axis} across "
                         f"{a.n} runs (threshold {threshold:.3f}); deltas larger than that "
                         f"band are attributable."))


def compare(baseline: Sequence[Any], variant: Sequence[Any], *,
            axis: str = "pass_rate", floor: Optional[Floor] = None,
            baseline_label: str = "baseline", variant_label: str = "variant",
            threshold: float = DEFAULT_FLOOR_THRESHOLD) -> Delta:
    """Compare two cells on one axis, refusing when the floor does not permit it.

    When ``floor`` is omitted it is derived from ``baseline`` — the baseline's own
    replicates are the natural yardstick, since the variant's spread may itself be the
    effect under test.
    """
    floor = floor if floor is not None else noise_floor(baseline, axis=axis,
                                                        threshold=threshold)
    b, v = axis_of(baseline, axis), axis_of(variant, axis)

    if b.n == 0 or v.n == 0:
        missing = baseline_label if b.n == 0 else variant_label
        return Delta(axis=axis, baseline=baseline_label, variant=variant_label,
                     baseline_mean=b.mean, variant_mean=v.mean, delta=0.0, floor=floor,
                     attributable=False,
                     verdict=f"{missing} produced no measurement on {axis}; nothing to compare.")

    delta = v.mean - b.mean
    if not floor.verified:
        return Delta(axis=axis, baseline=baseline_label, variant=variant_label,
                     baseline_mean=b.mean, variant_mean=v.mean, delta=delta, floor=floor,
                     attributable=False,
                     verdict=(f"refusing to attribute a {delta:+.3f} change in {axis}: "
                              f"{floor.reason}"))
    if abs(delta) <= floor.band:
        return Delta(axis=axis, baseline=baseline_label, variant=variant_label,
                     baseline_mean=b.mean, variant_mean=v.mean, delta=delta, floor=floor,
                     attributable=False,
                     verdict=(f"{axis} moved {delta:+.3f} ({b.mean:.3f} → {v.mean:.3f}), "
                              f"but {baseline_label} varies by {floor.band:.3f} between "
                              f"runs of itself. The change is inside the noise — this is "
                              f"not a small effect, it is not an observation."))
    direction = "better" if delta > 0 else "worse"
    return Delta(axis=axis, baseline=baseline_label, variant=variant_label,
                 baseline_mean=b.mean, variant_mean=v.mean, delta=delta, floor=floor,
                 attributable=True,
                 verdict=(f"{variant_label} is {direction} on {axis} by {abs(delta):.3f} "
                          f"({b.mean:.3f} → {v.mean:.3f}), against a run-to-run floor of "
                          f"{floor.band:.3f} over {floor.replicates} replicates."))


def harmonic_composite(axes: dict) -> float:
    """One score over several axes, where a single broken axis fails loudly.

    The arithmetic mean of {1.0, 0.0} is 0.5 — a respectable-looking number for a system
    that is entirely broken on one dimension. The harmonic mean is 0.0. That asymmetry is
    the whole reason for the choice: a composite exists to be read instead of the detail,
    so it must not be able to hide the detail that matters most.

    Values are expected in [0, 1]. A zero or negative anywhere returns 0.0; an empty map
    returns 0.0 (nothing measured is not a pass).
    """
    values = [float(v) for v in axes.values() if v is not None]
    if not values:
        return 0.0
    if any(v <= 0 for v in values):
        return 0.0
    return len(values) / sum(1.0 / v for v in values)


@dataclass
class FidelityReport:
    """Everything needed to decide whether a grid said anything."""

    axes: dict = field(default_factory=dict)         # label → {axis → Axis}
    floors: dict = field(default_factory=dict)       # axis → Floor
    deltas: list = field(default_factory=list)       # list[Delta]
    composite: dict = field(default_factory=dict)    # label → float
    fixture: dict = field(default_factory=dict)      # provenance stamps
    warnings: list = field(default_factory=list)

    @property
    def attributable(self) -> bool:
        """True only if at least one delta survived floor verification."""
        return any(d.attributable for d in self.deltas)

    def summary_lines(self) -> list[str]:
        """The report a human reads first — verdicts, not tables."""
        lines = [f"fixture: {self.fixture or '(unstamped)'}"]
        for w in self.warnings:
            lines.append(f"⚠️  {w}")
        for axis, floor in self.floors.items():
            mark = "✓" if floor.verified else "✗"
            lines.append(f"{mark} floor[{axis}]: {floor.reason}")
        for d in self.deltas:
            mark = "→" if d.attributable else "·"
            lines.append(f"{mark} {d.verdict}")
        for label, score in self.composite.items():
            lines.append(f"composite[{label}] = {score:.4f}")
        return lines

    def to_dict(self) -> dict:
        return {
            "axes": {label: {name: a.to_dict() for name, a in per.items()}
                     for label, per in self.axes.items()},
            "floors": {axis: f.to_dict() for axis, f in self.floors.items()},
            "deltas": [d.to_dict() for d in self.deltas],
            "composite": {k: round(v, 4) for k, v in self.composite.items()},
            "fixture": self.fixture,
            "warnings": self.warnings,
            "attributable": self.attributable,
        }


def assess(cells: dict, *, baseline: str, axes: Iterable[str] = DEFAULT_AXES,
           threshold: float = DEFAULT_FLOOR_THRESHOLD,
           fixture: Optional[dict] = None) -> FidelityReport:
    """Turn a grid's replicated runs into a report that knows what it may claim.

    ``cells`` maps a label to that cell's list of replicate summaries. ``baseline`` names
    the cell every other cell is compared against, and whose self-disagreement sets the
    floor for every axis.
    """
    report = FidelityReport(fixture=dict(fixture or {}))
    axes = tuple(axes)

    if baseline not in cells:
        report.warnings.append(
            f"baseline cell {baseline!r} is not in the grid ({sorted(cells)}); no delta can "
            f"be computed, because there is nothing to compare against.")
        return report

    for label, runs in cells.items():
        report.axes[label] = {name: axis_of(runs, name) for name in axes}
        measured = {name: report.axes[label][name].mean
                    for name in axes if report.axes[label][name].n}
        report.composite[label] = harmonic_composite(measured)

    for name in axes:
        report.floors[name] = noise_floor(cells[baseline], axis=name, threshold=threshold)

    for label, runs in cells.items():
        if label == baseline:
            continue
        for name in axes:
            report.deltas.append(compare(
                cells[baseline], runs, axis=name, floor=report.floors[name],
                baseline_label=baseline, variant_label=label, threshold=threshold))
    return report
