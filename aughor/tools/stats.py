"""Statistical analysis tools — anomaly detection, trend analysis, period comparison.

Auto-analyzes query results and attaches statistical grounding to evidence.
"""
from __future__ import annotations

import re
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
    type: str                        # "anomaly" | "trend" | "comparison" | "distribution" | "association"
    interpretation: str              # human-readable, injected into LLM evidence
    is_significant: bool
    sigma: Optional[float] = None    # z-score magnitude when relevant
    p_value: Optional[float] = None  # for Mann-Whitney comparisons


@dataclass
class AssociationResult:
    """Whether two categorical dimensions are related — and by how much.

    The missing primitive. Everything else in this module tests ONE measure (over time,
    across segments, against its own history); nothing tested two DIMENSIONS against each
    other. So a question of the form "how do A and B relate?" had no test to reach, and
    the honest answer — *they don't* — was not an answer the platform could produce. It
    answered with two separate rankings instead, which are true whatever the relationship
    is, and therefore say nothing about it.
    """
    rows: int                        # distinct values of dimension A
    cols: int                        # distinct values of dimension B
    n: float                         # total observations in the table
    cramers_v: float                 # effect size, 0 (independent) → 1 (perfectly determined)
    chi2: Optional[float]            # None when the measure is not frequency data
    dof: Optional[int]
    p_value: Optional[float]
    max_abs_residual: float          # largest standardised deviation from independence
    top_cells: list = field(default_factory=list)   # [(row_label, col_label, residual)]
    is_dependent: bool = False
    interpretation: str = ""


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


# ── Association between two categorical dimensions ───────────────────────────

#: Below this Cramér's V the two dimensions are reported as effectively independent even
#: when a p-value clears 0.05 — on a large table a trivial dependence is detectable but
#: not decision-relevant, and "significant" is not the same claim as "matters".
_ASSOCIATION_NEGLIGIBLE_V = 0.10
#: A standardised residual worth naming. With a 17×4 table there are 68 cells, so ~3 will
#: exceed |2| by chance alone — the threshold names candidates, the p-value judges them.
_RESIDUAL_NOTABLE = 2.0


def assess_association(
    table: "np.ndarray | list[list[float]]",
    row_labels: list[str],
    col_labels: list[str],
    *,
    is_frequency: bool = True,
) -> Optional[AssociationResult]:
    """Test whether two categorical dimensions are related, given their contingency table.

    ``is_frequency`` gates the significance test, and the gate is the point. A chi-square
    test of independence is defined on COUNTS — independent trials falling into cells.
    Run it on summed revenue and the "p-value" is arithmetic without a meaning: dollars
    are not trials, one large order is not a thousand small ones, and the number would
    grow with the units you chose. So for a non-frequency measure this reports the
    structure (how far each cell sits from proportional) and withholds the p-value,
    rather than laundering a guess into a statistic — the same posture
    ``is_additive_measure`` takes before claiming a share-of-total.

    Returns None when the table is too small or too sparse to say anything.
    """
    arr = np.asarray(table, dtype=float)
    if arr.ndim != 2 or arr.shape[0] < 2 or arr.shape[1] < 2:
        return None
    if not np.isfinite(arr).all() or (arr < 0).any():
        return None
    n = float(arr.sum())
    if n <= 0:
        return None

    # Expected counts under independence: the outer product of the margins. This is
    # also exactly "what the table would look like if the two dimensions were unrelated",
    # which is the comparison the question is asking for.
    row_tot = arr.sum(axis=1, keepdims=True)
    col_tot = arr.sum(axis=0, keepdims=True)
    if (row_tot <= 0).any() or (col_tot <= 0).any():
        return None                      # an all-zero row/column: no basis to compare
    expected = row_tot @ col_tot / n

    shape = f"{arr.shape[0]}x{arr.shape[1]}"
    cells_total = arr.shape[0] * arr.shape[1]

    if not is_frequency:
        # A DIFFERENT measure, not the same one with the p-value hidden. Chi-square
        # machinery is meaningless on dollars: `(observed-expected)/sqrt(expected)` is
        # only a σ because counts are Poisson-ish, and on a revenue table it produced a
        # confident "+207σ" — a number with no scale behind it that would change if the
        # column were cents. So compare COMPOSITIONS instead: how each row's mix differs
        # from the overall mix, in percentage points, which is scale-free and means
        # exactly what it says.
        row_mix = arr / row_tot
        overall = (col_tot / n).ravel()
        dev = row_mix - overall
        max_pp = float(np.abs(dev).max() * 100)
        flat_pp = sorted(
            ((abs(float(dev[i][j])), row_labels[i], col_labels[j], float(dev[i][j]) * 100)
             for i in range(arr.shape[0]) for j in range(arr.shape[1])), reverse=True)
        top = [(r, c, pp) for _a, r, c, pp in flat_pp[:3]]
        detail = "; ".join(f"{r}: {c} is {pp:+.1f}pp vs the overall mix" for r, c, pp in top)
        interp = (
            f"[{shape} contingency] COMPOSITION ONLY — the measure is not frequency data, "
            f"so no test of independence applies and none is claimed. Largest deviation "
            f"from the overall mix: {max_pp:.1f} percentage points. {detail}. "
            f"For a significance verdict, re-run this cross-tab with COUNT(*)."
        )
        return AssociationResult(
            rows=int(arr.shape[0]), cols=int(arr.shape[1]), n=n, cramers_v=float("nan"),
            chi2=None, dof=None, p_value=None, max_abs_residual=max_pp,
            top_cells=top, is_dependent=False, interpretation=interp,
        )

    chi2_stat = float(((arr - expected) ** 2 / expected).sum())
    dof = (arr.shape[0] - 1) * (arr.shape[1] - 1)
    # Cramér's V — the effect size. Scale-free and comparable across table shapes, which
    # is what makes "0.04" a usable answer where a chi-square of 49.7 is not.
    cramers_v = float(np.sqrt(chi2_stat / (n * (min(arr.shape) - 1)))) if n > 0 else 0.0
    residuals = (arr - expected) / np.sqrt(expected)
    max_abs = float(np.abs(residuals).max())
    p_value = float(scipy_stats.chi2.sf(chi2_stat, dof)) if dof > 0 else None

    flat = sorted(
        ((abs(float(residuals[i][j])), row_labels[i], col_labels[j], float(residuals[i][j]))
         for i in range(arr.shape[0]) for j in range(arr.shape[1])),
        reverse=True,
    )
    top_cells = [(r, c, z) for _a, r, c, z in flat[:3] if abs(z) >= _RESIDUAL_NOTABLE]

    # Dependent only when the test AND the effect size agree. Either alone misleads: a
    # big table makes a trivial dependence "significant", and a small one makes a real
    # one insignificant.
    negligible = cramers_v < _ASSOCIATION_NEGLIGIBLE_V
    is_dependent = (p_value is not None and p_value < 0.05) and not negligible

    if is_dependent:
        cells = "; ".join(f"{r}×{c} {'over' if z > 0 else 'under'}-represented ({z:+.1f}σ)"
                          for r, c, z in top_cells)
        detail = f" Most divergent: {cells}." if cells else ""
        interp = (f"RELATED: the two dimensions are NOT independent (Cramér's V="
                  f"{cramers_v:.2f}, p={p_value:.3g}). Knowing one shifts the distribution "
                  f"of the other.{detail}")
    else:
        why = (f"p={p_value:.2f} — the observed spread is within sampling noise"
               if p_value is not None and p_value >= 0.05
               else f"Cramér's V={cramers_v:.2f}, a negligible effect")
        interp = (
            f"INDEPENDENT: no material relationship between the two dimensions "
            f"({why}; largest cell deviation {max_abs:.1f}σ across {cells_total} "
            f"cells). The mix of one is effectively constant across the other, so apparent "
            f"differences between groups are noise — do NOT report a driver, a segment "
            f"effect, or an interaction. What varies is the SIZE of each group, not its "
            f"composition."
        )

    return AssociationResult(
        rows=int(arr.shape[0]), cols=int(arr.shape[1]), n=n, cramers_v=cramers_v,
        chi2=chi2_stat, dof=dof, p_value=p_value, max_abs_residual=max_abs,
        top_cells=top_cells, is_dependent=is_dependent,
        interpretation=f"[{shape} contingency] {interp}",
    )


def _as_float(value) -> Optional[float]:
    """``float(value)`` or None — a predicate, not an exception handler, so a NULL or a
    text cell is treated as the absent datum it is."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value) if np.isfinite(float(value)) else None
    text = str(value).strip()
    if not text or text.upper() == "NULL":
        return None
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", text):
        return None
    return float(text)


def _looks_like_frequency(col_name: str, values: list[float]) -> bool:
    """Is this measure a COUNT — i.e. frequency data a chi-square test is defined on?

    Name first (``count``/``orders``/``n``/``freq``), then the values: all non-negative
    whole numbers is the shape of a tally. Conservative — an unrecognised measure is
    treated as non-frequency, which withholds the p-value rather than inventing one.
    """
    name = (col_name or "").lower()
    if any(kw in name for kw in ("count", "num_", "n_", "freq", "tally", "orders", "records", "rows")):
        return True
    if name.strip() in ("n", "cnt", "qty", "quantity"):
        return True
    return bool(values) and all(v >= 0 and float(v).is_integer() for v in values)


def _analyze_association(columns: list[str], rows: list[list]) -> Optional[StatResult]:
    """Detect a long-form cross-tab — two categorical columns + one measure — and test
    the two dimensions for association.

    Wired into :func:`analyze_query_result`, so it fires wherever a ``GROUP BY a, b``
    happens to be run, by any path, without a caller opting in. That is the leverage: the
    verdict attaches itself to the evidence the narrator reads, so "these are independent"
    reaches the report even when nobody asked the question that way.
    """
    if not rows or len(rows) < 4 or len(columns) < 3:
        return None
    numeric = _numeric_column_indices(columns, rows)
    if not numeric:
        return None
    measure_idx = numeric[0]
    cat_idx = [i for i in range(len(columns)) if i not in numeric]
    if len(cat_idx) != 2:
        return None                      # exactly two dimensions, else it is not a cross-tab
    a_idx, b_idx = cat_idx[0], cat_idx[1]

    a_labels = sorted({str(r[a_idx]) for r in rows if r[a_idx] is not None})
    b_labels = sorted({str(r[b_idx]) for r in rows if r[b_idx] is not None})
    if not (2 <= len(a_labels) <= 60 and 2 <= len(b_labels) <= 60):
        return None
    # What separates a cross-tab from row-level data is that a GROUP BY a, b emits each
    # pair EXACTLY ONCE. Duplicates mean these are raw rows, and summing them into a grid
    # would test something nobody computed.
    #
    # Density is deliberately NOT the gate. The first version required half the grid to
    # be filled, which rejected `region × state` — a pair where each state belongs to
    # exactly one region, so 147 of 196 cells are empty. That sparsity IS the dependence:
    # the most strongly related pairs are the emptiest grids, and gating on density
    # blinds the test precisely where it has the most to say.
    pairs = [(str(r[a_idx]), str(r[b_idx])) for r in rows]
    if len(set(pairs)) != len(pairs):
        return None

    # A non-numeric cell is DATA, not a failure — a NULL measure for a pair that has no
    # observations is exactly what a cross-tab looks like — so it is filtered by a
    # predicate rather than caught. (An `except: continue` here would also be a silent
    # swallow, which `test_no_new_silent_swallows` rightly refuses.)
    grid = np.zeros((len(a_labels), len(b_labels)), dtype=float)
    for r in rows:
        if r[a_idx] is None or r[b_idx] is None:
            continue
        v = _as_float(r[measure_idx])
        if v is None:
            continue
        grid[a_labels.index(str(r[a_idx]))][b_labels.index(str(r[b_idx]))] = v

    values = _extract_floats(rows, measure_idx)
    res = assess_association(grid, a_labels, b_labels,
                             is_frequency=_looks_like_frequency(columns[measure_idx], values))
    if res is None:
        return None
    return StatResult(
        type="association",
        interpretation=f"[{columns[a_idx]} × {columns[b_idx]}] {res.interpretation}",
        # An INDEPENDENT verdict is every bit as load-bearing as a dependent one — it is
        # the finding that stops a report inventing a driver — so it is marked significant
        # too. `is_significant` gates what reaches the narrator, not what is interesting.
        is_significant=True,
        sigma=res.max_abs_residual,
        p_value=res.p_value,
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

    # Two-dimension association: when the result IS a cross-tab, say whether the two
    # dimensions are related at all. Runs before the numeric scan below because it reads
    # the whole grid rather than one column of it.
    try:
        assoc = _analyze_association(columns, rows)
        if assoc:
            results.append(assoc)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "association analysis best-effort; other stats proceed",
                 counter="stats.association")

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
