"""Statistical analysis tools — anomaly detection, trend analysis, period comparison.

Auto-analyzes query results and attaches statistical grounding to evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy import stats as scipy_stats

from aughor.tools.postproc import pct_changes, shares, is_additive_measure


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


@dataclass
class LevelShiftResult:
    prior_mean: float
    recent_mean: float
    rel_change: float          # (recent - prior) / prior
    t_stat: float              # Welch two-sample t (signed)
    p_value: float
    is_significant: bool       # p < alpha AND |rel_change| ≥ min_effect
    interpretation: str


def mean_shift_significance(
    values: list[float],
    min_per_group: int = 3,
    alpha: float = 0.05,
    min_effect: float = 0.03,
) -> Optional[LevelShiftResult]:
    """Two-sample (Welch) test for a SUSTAINED level shift between the earlier and later
    halves of an ordered series.

    This is the complement to single-point ``detect_anomaly``: point-anomaly detection asks
    "is the LAST observation an outlier vs history?" and is structurally BLIND to a gradual or
    sustained shift where no individual point is an outlier — e.g. a full-year revenue decline
    of −6% across 12 months, where every single month sits within the prior year's range but the
    two years' MEANS differ significantly. The prior code divided the mean gap by a single-period
    σ (wrong by √n); the correct test uses the standard error of the mean difference
    (SE = √(s₁²/n₁ + s₂²/n₂)), which is exactly Welch's two-sample t.

    Returns None when the series is too short to split into two groups of ``min_per_group``.
    ``is_significant`` requires BOTH statistical significance (p < alpha) AND a material effect
    (|rel_change| ≥ min_effect) so a trivially-small-but-significant wobble on a long, tight
    series does not force expensive downstream work."""
    arr = [float(v) for v in values if v is not None]
    n = len(arr)
    if n < 2 * min_per_group:
        return None
    mid = n // 2
    prior, recent = arr[:mid], arr[mid:]
    pm = float(np.mean(prior))
    rm = float(np.mean(recent))
    rel = (rm - pm) / pm if pm != 0 else 0.0
    try:
        t_stat, p_value = scipy_stats.ttest_ind(recent, prior, equal_var=False)
        t_stat = float(t_stat)
        p_value = float(p_value)
    except Exception:
        return None
    if not np.isfinite(t_stat) or not np.isfinite(p_value):
        return None
    is_sig = bool(p_value < alpha and abs(rel) >= min_effect)
    direction = "lower" if rel < 0 else "higher"
    interp = (
        f"Sustained level shift: recent-half mean ({rm:,.1f}) is {abs(rel) * 100:.1f}% {direction} "
        f"than prior-half mean ({pm:,.1f}) — Welch t={t_stat:.2f}, p={p_value:.3f} "
        f"[{'SIGNIFICANT shift' if is_sig else 'within noise'}]."
    )
    return LevelShiftResult(
        prior_mean=pm, recent_mean=rm, rel_change=rel, t_stat=t_stat,
        p_value=p_value, is_significant=is_sig, interpretation=interp,
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


# ── Proportions: rate confidence intervals + segment uniformity ───────────────

@dataclass
class SegmentRate:
    label: str
    successes: int
    n: int
    rate: float
    ci_low: float
    ci_high: float
    significant: bool   # differs from the pooled baseline (Bonferroni-corrected)


@dataclass
class UniformityResult:
    baseline_rate: float
    n_segments: int
    n_significant: int
    all_uniform: bool         # no segment differs significantly from baseline
    interpretation: str
    segments: list = field(default_factory=list)  # list[SegmentRate]


def proportion_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion — well-behaved at the small
    counts and near-zero rates (≈2.5%) where the normal approximation breaks down."""
    import math
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def two_proportion_pvalue(s1: int, n1: int, s2: int, n2: int) -> float:
    """Two-sided z-test p-value for the difference between two proportions
    (pooled-variance). Returns 1.0 (no evidence of difference) on degenerate input."""
    import math
    if n1 <= 0 or n2 <= 0:
        return 1.0
    p_pool = (s1 + s2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return 1.0
    z = (s1 / n1 - s2 / n2) / se
    return float(2 * scipy_stats.norm.sf(abs(z)))


def assess_rate_uniformity(
    segments: list[tuple[str, int, int]],
    alpha: float = 0.05,
) -> Optional[UniformityResult]:
    """Given per-segment (label, successes, n), decide whether any segment's rate
    differs from the pooled baseline beyond sampling noise.

    Each segment is tested against the POOL OF ALL OTHER segments (so the segment is
    not compared against a baseline it dominates), with a Bonferroni correction across
    the k segments. The headline question this answers: "is the apparent variation real,
    or is the rate uniform across this dimension?" — the Swiss-Air refund case where
    every segment reads ~2.5% and the right move is to NOT over-interpret the spread.

    Returns None when the input can't support a test (fewer than 2 segments with data).
    """
    clean = [(str(lbl), int(round(s)), int(round(n))) for lbl, s, n in segments
             if n and int(round(n)) > 0 and 0 <= int(round(s)) <= int(round(n))]
    if len(clean) < 2:
        return None

    total_s = sum(s for _, s, _ in clean)
    total_n = sum(n for _, _, n in clean)
    baseline = total_s / total_n if total_n else 0.0
    k = len(clean)
    corrected = alpha / k  # Bonferroni

    seg_results: list[SegmentRate] = []
    n_sig = 0
    for lbl, s, n in clean:
        lo, hi = proportion_ci(s, n)
        p = two_proportion_pvalue(s, n, total_s - s, total_n - n)
        sig = p < corrected
        if sig:
            n_sig += 1
        seg_results.append(SegmentRate(lbl, s, n, s / n, lo, hi, sig))

    all_uniform = n_sig == 0
    if all_uniform:
        interp = (
            f"UNIFORM / NO SIGNAL: all {k} segments fall within sampling noise of the "
            f"pooled rate {baseline:.2%} (no segment differs significantly at the 95% level, "
            f"Bonferroni-corrected for {k} comparisons). Apparent segment-to-segment "
            f"differences are statistical noise, not signal — do NOT attribute the spread to "
            f"any dimension or recommend segment-specific action on this basis. A rate this "
            f"flat across every segment is often structural or a data-generation artifact; "
            f"treat with low confidence until the data-generating process is validated."
        )
    else:
        movers = ", ".join(
            f"{sr.label} ({sr.rate:.2%}, n={sr.n})" for sr in seg_results if sr.significant
        )
        interp = (
            f"{n_sig} of {k} segments differ significantly from the pooled rate "
            f"{baseline:.2%} (95%, Bonferroni-corrected): {movers}. Remaining segments are "
            f"within sampling noise."
        )
    return UniformityResult(baseline, k, n_sig, all_uniform, interp, seg_results)


# NOTE: "share" is deliberately NOT a rate keyword — a share-of-total column (each
# segment's slice of one whole, summing to 1) is a COMPOSITION, not a per-segment
# proportion; pushing revenue shares through a two-proportion z-test produced the
# meaningless "45 of 48 segments differ from the pooled 2.08% rate (Bonferroni)".
_RATE_KEYWORDS = ("rate", "ratio", "pct", "percent", "proportion", "conversion", "frac")
_DENOM_KEYWORDS = ("total", "count", "tickets", "orders", "n_", "volume", "rows", "customers", "users", "_n")


def _analyze_rate_segments(columns: list[str], rows: list[list]) -> Optional[StatResult]:
    """Detect a rate-by-segment result (a proportion column + a denominator count
    column across ≥3 group rows) and test whether the rate is uniform across segments.

    Reconstructs successes = round(rate × denominator) so the numerator column need not
    be identified explicitly. Returns a StatResult only when a confident detection +
    assessment is possible; otherwise None (stays silent rather than guess)."""
    if not rows or len(rows) < 3 or not columns:
        return None
    lower = [c.lower() for c in columns]

    # rate column: name hints OR all values within [0, 1]
    rate_idx = None
    for i, c in enumerate(lower):
        vals = _extract_floats(rows, i)
        if not vals:
            continue
        named = any(kw in c for kw in _RATE_KEYWORDS)
        in_unit = all(0.0 <= v <= 1.0001 for v in vals)
        in_pct = all(0.0 <= v <= 100.0 for v in vals) and max(vals) > 1.5
        if named and (in_unit or in_pct):
            rate_idx = i
            break
        if rate_idx is None and in_unit and len(vals) >= 3 and max(vals) <= 1.0001 and min(vals) < 1.0:
            # Fallback: a [0,1] column with no obvious name — but NOT a composition.
            # Shares of one whole sum to ≈1 across segments (revenue_share, mix); a
            # genuine per-segment rate does not. A composition through a proportion
            # test yields nonsense significance on ordinary magnitude differences.
            if not (0.98 <= sum(vals) <= 1.02):
                rate_idx = i
    if rate_idx is None:
        return None

    rate_vals = _extract_floats(rows, rate_idx)
    scale = 100.0 if (rate_vals and max(rate_vals) > 1.5) else 1.0

    # denominator: an integer-ish numeric column (not the rate) with the largest sum
    denom_idx = None
    best_sum = -1.0
    for i, c in enumerate(lower):
        if i == rate_idx:
            continue
        vals = _extract_floats(rows, i)
        if len(vals) < 3:
            continue
        int_like = all(abs(v - round(v)) < 1e-6 for v in vals) and all(v >= 0 for v in vals)
        if not int_like:
            continue
        named = any(kw in c for kw in _DENOM_KEYWORDS)
        total = sum(vals)
        score = total * (10 if named else 1)
        if score > best_sum:
            best_sum = score
            denom_idx = i
    if denom_idx is None:
        return None

    # label column: first non-rate, non-denominator column (else synthesize indices)
    label_idx = next((i for i in range(len(columns)) if i not in (rate_idx, denom_idx)), None)

    segments: list[tuple[str, int, int]] = []
    for r_i, row in enumerate(rows):
        try:
            rate = float(row[rate_idx]) / scale
            n = float(row[denom_idx])
        except (ValueError, TypeError, IndexError):
            continue
        if n <= 0 or not (0.0 <= rate <= 1.0001):
            continue
        label = str(row[label_idx]) if label_idx is not None else f"row{r_i}"
        segments.append((label, round(rate * n), int(round(n))))

    result = assess_rate_uniformity(segments)
    if result is None:
        return None
    return StatResult(
        type="uniformity",
        interpretation=f"[{columns[rate_idx]}] {result.interpretation}",
        is_significant=result.n_significant > 0,
        p_value=None,
    )


# ── Auto-analysis: called on every successful QueryResult ────────────────────

def analyze_query_result(columns: list[str], rows: list[list], sql: Optional[str] = None) -> list[StatResult]:
    """
    Inspect a query result and run whichever statistical tests are appropriate.
    Returns a (possibly empty) list of StatResult to attach to the QueryResult.

    `sql` (when given) gates measure-additivity-sensitive signals: a concentration /
    share-of-total claim is only emitted for an ADDITIVE measure (so an AVG/ratio result
    never injects a false "Pareto concentration" into the LLM evidence).
    """
    if not rows or not columns:
        return []

    results: list[StatResult] = []

    # Rate-by-segment uniformity: is the apparent spread across groups real signal,
    # or noise around a flat baseline? (independent of the numeric-column scan below)
    try:
        rate_stat = _analyze_rate_segments(columns, rows)
        if rate_stat:
            results.append(rate_stat)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "rate-segment uniformity analysis best-effort; other stats proceed",
                 counter="stats.rate_segments")

    # Find numeric column indices
    numeric_idxs = _numeric_column_indices(columns, rows)
    if not numeric_idxs:
        return results

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
            # Period-over-period: surface the latest material change (additive, gated).
            changes = [c for c in pct_changes(values) if c is not None]
            if changes and abs(changes[-1]) >= 0.05:
                latest = changes[-1]
                results.append(StatResult(
                    type="comparison",
                    interpretation=(f"[{col_name}] Latest period {'+' if latest >= 0 else ''}"
                                    f"{latest * 100:.1f}% vs the prior period (period-over-period)."),
                    is_significant=abs(latest) >= 0.15,
                ))

        # Distribution path: group labels + values (no date col, or date already handled)
        elif date_idx is None and len(values) >= 5:
            stat = _analyze_distribution(col_name, values)
            if stat:
                results.append(stat)
            # Concentration: surface Pareto-style skew across groups — ONLY for an ADDITIVE
            # measure. Share-of-total is meaningless for an average/rate/ratio (summing
            # per-group AVGs is not a real total), so gate it to avoid a fabricated signal.
            if is_additive_measure(col_name, sql):
                sh = sorted((s for s in shares(values) if s is not None), reverse=True)
                if sh:
                    top1, top3 = sh[0], sum(sh[:3])
                    if top1 >= 0.40 or top3 >= 0.70:
                        results.append(StatResult(
                            type="contribution",
                            interpretation=(f"[{col_name}] Concentrated: the largest of {len(sh)} groups is "
                                            f"{top1 * 100:.0f}% of the total; top 3 = {top3 * 100:.0f}% (Pareto-style)."),
                            is_significant=top1 >= 0.5 or top3 >= 0.8,
                        ))

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
    Detect whether a metric series deviated from its own history. Two complementary tests are
    combined so neither blind spot silently passes:
      • single-point anomaly (STL-deseasonalised, or plain z-score) — "is the LAST point an outlier?"
      • sustained level shift (Welch two-sample) — "did the series MEAN move?" — which point-anomaly
        detection misses (a gradual multi-period decline where no single point is an outlier).
    The reported sigma/is_significant is the STRONGER of the two, so the downstream Tier-0 gate
    proceeds to dimensional analysis on a real level shift instead of dismissing it as "noise".
    """
    last = values[-1]
    baseline = values[:-1]

    point_sig = False
    point_sigma = 0.0
    point_interp = ""

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
            point_sig = anomaly.is_anomaly
            point_sigma = abs(anomaly.z_score)
            point_interp = f"[{col_name}] After removing seasonality ({label}): {anomaly.interpretation}"
        except Exception:
            pass  # fall through to plain z-score

    if not point_interp:
        # Fallback: plain z-score on raw values
        anomaly = detect_anomaly(baseline, last)
        point_sig = anomaly.is_anomaly
        point_sigma = abs(anomaly.z_score)
        point_interp = f"[{col_name}] {anomaly.interpretation}"

    # Sustained level-shift test — the point-anomaly blind spot. Reported as significant when a
    # material, statistically-real shift exists even though no single point is an outlier.
    shift = mean_shift_significance(values)
    if shift is not None and shift.is_significant and abs(shift.t_stat) > point_sigma:
        return StatResult(
            type="anomaly",
            interpretation=f"{point_interp} {shift.interpretation}",
            is_significant=True,
            sigma=round(abs(float(shift.t_stat)), 2),
        )

    # Coerce numpy scalars → plain Python (the STL/z-score paths yield numpy bool/float, which the
    # LangGraph msgpack checkpointer downstream cannot serialize).
    return StatResult(
        type="anomaly",
        interpretation=point_interp,
        is_significant=bool(point_sig),
        sigma=round(float(point_sigma), 2),
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
