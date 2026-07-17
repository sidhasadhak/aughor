"""R15 — the opportunity-cost / benchmark lens: gap-to-benchmark × volume.

The strongest move in the Databricks losing-money report: not "long-haul load
factor is 74.5%" but "raising it to the short-haul benchmark of 77.2% fills
1,767 seats across 258 flights". The decision is the QUANTIFIED gap.

This is a deterministic POST-PASS over a cross-section finding's own rows — no
model, no extra query. The dimensional scan already returns, per segment, the
metric and the volume (``segment, metric_total, n[, avg_per_record]``); the
lens finds the weakest material segment, benchmarks it against its best
material peer, and appends one key number:

    (benchmark rate − weakest rate) × weakest segment's volume

Honesty rules: segments below the materiality floor never anchor either side
(mirroring ``_detect_anomalous_period``'s gates); the gap must clear BOTH a
rate floor (≥3% relative — below that is measurement noise) and a volume-aware
floor (the opportunity itself ≥0.5% of the material total — the Databricks
case is a 3.5% rate gap that matters precisely because the volume is large);
the context sentence always carries the hedge — a ceiling computed from peers,
not a forecast, and the directional read is the reader's (for a cost-like
metric, "higher" is worse). Gated by ``lens.decision_grade``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Materiality floor for a segment to anchor either side of the benchmark, so a
# boutique segment can't headline the opportunity. Measured against the TYPICAL
# segment rather than the scanned total, because a share-of-total floor is
# scale-dependent: with N segments the mean share is 1/N, so a >33-segment grid
# has NO segment above 3% and becomes structurally unreadable — which is exactly
# where the story tends to live (84 routes spanning 68.6%–87.7% load factor, all
# of them silenced). Against the typical segment the rule holds at any grain.
_MIN_SEGMENT_N = 30.0
_MIN_SEGMENT_OF_TYPICAL = 0.25
# Below this relative rate gap the difference is measurement noise — silence.
_MIN_RELATIVE_GAP = 0.03
# ... and the gap × volume itself must be material vs the whole scanned pie.
_MIN_OPPORTUNITY_SHARE = 0.005
# When the grid is a TRUE proportion the sampling error replaces the flat rate floor:
# a gap must clear this many standard errors to be signal rather than noise.
_MIN_GAP_Z = 3.0


def _median(vals: list) -> float:
    """The typical value — robust to the one giant segment that would drag a mean."""
    s = sorted(vals)
    if not s:
        return 0.0
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2.0


def _proportion_gap_is_signal(laggard: tuple, benchmark: tuple) -> bool:
    """Is the gap between two proportions bigger than their own measurement error?

    The flat `_MIN_RELATIVE_GAP` is a small-sample proxy for exactly this question, and
    at large n it silences the case this lens exists to find: long-haul at 77.7% against
    short-haul's 79.4% is a 2.1% relative gap — under the floor — yet it is measured over
    66,764 seats, which makes it ~8 standard errors and 1,135 empty seats. The same 1.7pp
    over 40 seats is nothing. So when `n` is the rate's own denominator, ask the data."""
    def _se(p: float, n: float) -> float:
        p = min(max(p, 0.0), 1.0)
        return ((p * (1.0 - p) / n) ** 0.5) if n > 0 else float("inf")
    se = (_se(laggard[1], laggard[2]) ** 2 + _se(benchmark[1], benchmark[2]) ** 2) ** 0.5
    if se <= 0:
        return True
    return (abs(laggard[1] - benchmark[1]) / se) >= _MIN_GAP_Z


# Cost-like measures: the ones where HIGHER is worse, so the laggard is the segment
# with the biggest number and the benchmark is its lowest material peer. Mirrors the
# renderers' severity-ramp constants — `_COST_METRIC_RE` in aughor/export/charts.py and
# `COST_METRIC_COL` in web/components/charts/exhibit.ts (keep the three in sync). Those
# two already spend this signal on colour; the direction of the MATH is the consumer it
# never reached — a refund-rate ranking benchmarked "upward" inverts the whole claim.
_COST_METRIC_RE = re.compile(
    r"(delay|late|loss|lost|cancel|refund|return|churn|complaint|defect|error|fail"
    r"|missing|overdue|wait|downtime|leak)", re.I)


def metric_lower_is_better(metric_label: str = "", metric_sql: str = "") -> bool:
    """Is this a cost-like metric (lower = better)? Deterministic name scan, no model."""
    return bool(_COST_METRIC_RE.search(f"{metric_label or ''} {metric_sql or ''}"))


def _as_fractions(segs: list) -> list:
    """A percent-SCALED rate grid (77.7) → fractions (0.777).

    The volume `n` is the rate's own denominator, so `gap × n` is only unit-correct
    when the gap is a fraction: 1.7 percentage-points × 66,764 seats is 113,499 of
    nothing, where (1.7/100) × 66,764 = 1,135 seats. The lens SQL asks for
    `100.0 * SUM(x) / SUM(y)`, so percent-scaled grids are the norm on that path.
    Threshold mirrors `_fmt`'s own 1.5 convention: at or below it the grid is already
    a fraction and must not be touched."""
    if any(abs(r) > 1.5 for _, r, _ in segs):
        return [(s, r / 100.0, n) for s, r, n in segs]
    return segs


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "NULL":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v: float, *, is_percent: bool = False) -> str:
    if is_percent:
        pct = v * 100.0 if abs(v) <= 1.5 else v
        return f"{pct:.1f}%"
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.2f}B"
    if a >= 1e6:
        return f"{v / 1e6:.2f}M"
    if a >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.2f}" if a != int(a) else f"{int(v):,}"


def segment_rates(
    columns: list, rows: list, *, is_ratio: bool = False
) -> Optional[list[tuple[str, float, float]]]:
    """Parse a cross-section result grid into per-segment ``(label, rate, n)``. Pure.

    Expects the cross-section template shape: a segment label column, a count
    column named ``n`` (or ``count``/``records``), and either ``avg_per_record``
    or ``metric_total``. For a ratio metric ``metric_total`` IS the per-segment
    rate; for an additive metric the rate is ``metric_total / n``. Returns None
    when the grid doesn't carry that shape. Shared by the R15 opportunity lens
    and the chart-grammar exhibit builder (aughor/agent/exhibit.py)."""
    if not columns or not rows:
        return None
    low = [str(c).lower() for c in columns]

    def _idx(*names: str) -> Optional[int]:
        for name in names:
            if name in low:
                return low.index(name)
        return None

    n_i = _idx("n", "count", "records", "n_records")
    avg_i = _idx("avg_per_record")
    val_i = _idx("metric_total", "val", "value")
    if n_i is None or (avg_i is None and val_i is None):
        return None
    seg_i = next((i for i in range(len(columns)) if i not in (n_i, avg_i, val_i)), None)
    if seg_i is None:
        return None

    segs: list[tuple[str, float, float]] = []   # (label, rate, n)
    for r in rows:
        if len(r) <= max(i for i in (seg_i, n_i, avg_i, val_i) if i is not None):
            continue
        n = _num(r[n_i])
        if not n or n <= 0:
            continue
        if avg_i is not None:
            rate = _num(r[avg_i])
        elif is_ratio:
            rate = _num(r[val_i])
        else:
            v = _num(r[val_i])
            rate = (v / n) if v is not None else None
        if rate is None:
            continue
        segs.append((str(r[seg_i]), rate, n))
    return segs or None


def compute_opportunity(
    columns: list, rows: list, *, is_ratio: bool = False, is_percent: bool = False,
    lower_is_better: bool = False, volume_is_denominator: bool = False,
) -> Optional[dict]:
    """The gap × volume computation over one finding's result grid. Pure.

    `lower_is_better` orients the read for a cost-like rate (leakage, defect rate):
    the laggard is then the HIGHEST-rate segment and the benchmark its lowest material
    peer. Left False, a refund-rate ranking would benchmark the worst leaker as the
    target to reach — the claim inverted.

    `is_percent` declares the rate may arrive percent-SCALED (77.7 rather than 0.777),
    which the lens SQL produces by construction; it is normalised to a fraction before
    gap × volume so the result carries the volume's unit and not 100× of it.

    `volume_is_denominator` declares `n` to be the rate's own denominator — a true
    proportion — which swaps the flat rate floor for the gap's own sampling error.

    Returns None whenever the shape, materiality, or gap thresholds don't hold —
    silence is the correct output for a grid this lens can't read honestly."""
    # A true proportion needs only its one peer to benchmark against: "long-haul flies
    # 77.7% full against short-haul's 79.4%" is the whole claim, and a ≥3 rule cannot
    # express it. Every other grid still needs a peer GROUP for "best peer" to mean
    # anything.
    min_segs = 2 if volume_is_denominator else 3
    if not columns or not rows or len(rows) < min_segs:
        return None
    segs = segment_rates(columns, rows, is_ratio=is_ratio)
    if not segs or len(segs) < min_segs:
        return None
    if is_ratio and is_percent:
        segs = _as_fractions(segs)

    floor = max(_MIN_SEGMENT_N, _MIN_SEGMENT_OF_TYPICAL * _median([n for _, _, n in segs]))
    material = [s for s in segs if s[2] >= floor]
    if len(material) < 2:
        return None

    # The laggard is the segment to be fixed; the benchmark is its best material peer.
    laggard = (max if lower_is_better else min)(material, key=lambda s: s[1])
    benchmark = (min if lower_is_better else max)(material, key=lambda s: s[1])
    if benchmark[1] <= 0 or laggard[0] == benchmark[0]:
        return None
    gap = abs(laggard[1] - benchmark[1])
    relative_gap = gap / abs(benchmark[1])
    if volume_is_denominator:
        if not _proportion_gap_is_signal(laggard, benchmark):
            return None
    elif relative_gap < _MIN_RELATIVE_GAP:
        return None
    opportunity = gap * laggard[2]
    if volume_is_denominator:
        # Material against what the opportunity would MOVE, not against the whole pie.
        # A 1,290-seat gain measured against 273,878 sold seats reads as 0.47% and
        # vanishes; measured against the 72,456 EMPTY seats it is 1.8% of the gap that
        # is actually addressable. For a cost-like rate the addressable side flips: it
        # is the leaked amount, not the clean remainder.
        base = sum(((rate if lower_is_better else (1.0 - rate)) * n)
                   for _, rate, n in material)
    else:
        base = sum(rate * n for _, rate, n in material)
    if base <= 0 or opportunity < _MIN_OPPORTUNITY_SHARE * base:
        return None

    return {
        "worst_segment": laggard[0], "worst_rate": laggard[1], "worst_n": laggard[2],
        "best_segment": benchmark[0], "best_rate": benchmark[1],
        "relative_gap": relative_gap,
        "opportunity": opportunity,
    }


def annotate_opportunity(
    finding: dict, *, metric_label: str = "", is_ratio: bool = False,
    is_percent: bool = False, lower_is_better: bool = False,
    volume_label: str = "records", volume_is_denominator: bool = False,
) -> bool:
    """Append the benchmark-gap key number (+ a hedged note) to one finding,
    in place. Returns True when it annotated. Never raises — a finding this
    lens can't read stays exactly as it was.

    `volume_label` names what `n` counts (seats, flights, records): for a ratio
    metric the opportunity carries the VOLUME's unit — gap is dimensionless, so
    (79.4% − 77.7%) × 66,764 seats is seats. For an additive metric the rate is
    already per-record, so the opportunity carries the metric's own unit."""
    try:
        rows = finding.get("rows") or []
        # A finding carries at most the first 50 rows. The benchmark is the BEST peer in
        # the grid, so on a truncated ORDER BY … ASC scan (84 routes → the 50 emptiest)
        # the real benchmark was cut and the "gap" would be measured against whatever
        # survived — a confident, quietly wrong number. Silence is the honest output.
        row_count = finding.get("row_count")
        if isinstance(row_count, (int, float)) and row_count > len(rows):
            return False
        gap = compute_opportunity(
            finding.get("columns") or [], rows,
            is_ratio=is_ratio, is_percent=is_percent, lower_is_better=lower_is_better,
            volume_is_denominator=volume_is_denominator)
        if not gap:
            return False
        label = metric_label or "the metric"
        per = "" if is_ratio else " per record"
        unit = volume_label if is_ratio else label
        # A ratio's opportunity is a COUNT of the volume's own unit, and a count reads
        # as "1,135 seats" — compacting it to "1.1K seats" throws away the precision
        # that makes the number decision-grade. Money keeps the compact form.
        value = (f"{gap['opportunity']:,.0f}" if is_ratio
                 else _fmt(gap["opportunity"], is_percent=False))
        context = (
            f"{gap['worst_segment']} runs {_fmt(gap['worst_rate'], is_percent=is_percent)} "
            f"vs {gap['best_segment']}'s {_fmt(gap['best_rate'], is_percent=is_percent)}"
            f"{per}; closing that gap across {gap['worst_n']:,.0f} {volume_label} ≈ {value} "
            f"{unit}. A ceiling computed from peers, not a forecast."
        )
        finding.setdefault("key_numbers", []).append({
            "label": f"Opportunity: {gap['worst_segment']} → {gap['best_segment']} benchmark",
            "value": value,
            "delta": (f"{gap['relative_gap'] * 100:.0f}% "
                      f"{'above' if lower_is_better else 'below'} benchmark"),
            "context": context,
        })
        note = finding.get("stat_note")
        finding["stat_note"] = (f"{note} · {context}" if note else context)
        return True
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "opportunity annotation is best-effort",
                 counter="lens.decision_grade")
        return False
