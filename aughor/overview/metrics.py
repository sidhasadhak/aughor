"""Pure notability math for the overview ("interesting facts") mode.

Deterministic, dependency-light helpers that turn a group-by result vector or a
column's cached distribution moments into a *notability* signal in ``[0, 1]``.
No HHI/Gini/skew helper existed in the repo (the only concentration code was
inline inside ``analyze_query_result``), so these are new — but they reuse the
same ideas the explorer already trusts (share vectors, mean/p50 skew, z-scores).

Every function is total (never raises) and returns 0.0 on degenerate input, so a
lens can score a fact without guarding each call.
"""
from __future__ import annotations

from typing import Sequence


def _clean(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f:  # drop NaN
            out.append(f)
    return out


def shares(values: Sequence[float]) -> list[float]:
    """Each value as a fraction of the (absolute) total. ``[]`` on a zero total."""
    vals = _clean(values)
    total = sum(abs(v) for v in vals)
    if total <= 0:
        return []
    return [abs(v) / total for v in vals]


def hhi(values: Sequence[float]) -> float:
    """Herfindahl–Hirschman index of a share vector — Σ(sᵢ²), in ``[0, 1]``.
    1.0 = one group holds everything; ~0 = perfectly even. The canonical
    concentration measure; > ~0.25 is "concentrated", > 0.5 is "dominated"."""
    s = shares(values)
    return sum(x * x for x in s) if s else 0.0


def top_share(values: Sequence[float], k: int = 1) -> float:
    """Combined share of the top-``k`` groups (by magnitude). ``top_share(v,1)``
    is the single-largest group's slice of the whole."""
    s = sorted(shares(values), reverse=True)
    return sum(s[:k]) if s else 0.0


def gini(values: Sequence[float]) -> float:
    """Gini coefficient of a non-negative vector — 0 = even, →1 = one group takes
    all. Complements HHI (Gini is inequality across ranks; HHI weights the head)."""
    vals = sorted(abs(v) for v in _clean(values))
    n = len(vals)
    total = sum(vals)
    if n < 2 or total <= 0:
        return 0.0
    # cumulative-share formula: G = (2·Σ i·xᵢ)/(n·Σx) − (n+1)/n
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    return max(0.0, (2 * cum) / (n * total) - (n + 1) / n)


def skew_ratio(mean: float | None, median: float | None) -> float:
    """mean/median — the cheap right-skew signal the explorer already uses
    (``mean/p50 > 1.5`` ⇒ heavy right tail). 1.0 = symmetric. 0.0 when unknown."""
    try:
        m, med = float(mean), float(median)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if med == 0:
        return 0.0
    return m / med


def spread_ratio(lo: float | None, hi: float | None) -> float:
    """max/min magnitude — how many orders of magnitude a measure spans. A fare
    range of 6→19,719 is ~3,300×, an obviously notable data fact. 0 when unknown."""
    try:
        a, b = abs(float(lo)), abs(float(hi))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if a <= 0:
        return 0.0
    return b / a


def deviation(value: float, peers: Sequence[float]) -> float:
    """Signed relative deviation of ``value`` from the MEDIAN of ``peers``
    (robust to the outlier itself). +0.5 = 50% above typical, −0.45 = 45% below.
    0.0 when there's no usable peer baseline."""
    p = _clean(peers)
    if len(p) < 2:
        return 0.0
    p.sort()
    mid = p[len(p) // 2] if len(p) % 2 else (p[len(p) // 2 - 1] + p[len(p) // 2]) / 2
    if mid == 0:
        return 0.0
    return (value - mid) / abs(mid)


# ── notability normalizers — map a raw signal onto [0, 1] "interestingness" ────
# Each is deliberately gentle so scores stay comparable ACROSS lenses (a 0.7
# concentration fact and a 0.7 outlier fact are meant to feel equally notable).

def _sat(x: float, half: float) -> float:
    """Saturating curve: 0 at 0, 0.5 at ``half``, →1 as x grows. x/(x+half)."""
    x = abs(x)
    return x / (x + half) if (x + half) > 0 else 0.0


def notability_concentration(hhi_value: float, top1: float) -> float:
    # Dominated-by-one (top1≈1) and high HHI both read as notable.
    return max(min(1.0, hhi_value * 1.6), min(1.0, max(0.0, top1 - 0.33) * 1.5))


def notability_deviation(rel: float) -> float:
    # A group 40% off the typical per-unit value is clearly interesting.
    return _sat(rel, 0.45)


def notability_skew(ratio: float) -> float:
    # mean/median of 1.5 → ~0.5; heavy tails saturate toward 1.
    return _sat(max(0.0, ratio - 1.0), 0.6)


def notability_spread(ratio: float) -> float:
    # 100× span → ~0.5; anything multi-order-of-magnitude is notable.
    import math
    if ratio <= 1:
        return 0.0
    return _sat(math.log10(ratio), 1.3)


def notability_coverage(null_rate: float = 0.0, single_value: bool = False,
                        untouched_rows: int = 0) -> float:
    if single_value:
        return 0.62                       # "every row is CHF" — a real did-you-know
    if untouched_rows > 0:
        import math
        return min(0.8, 0.35 + _sat(math.log10(untouched_rows + 1), 4.0))
    return _sat(null_rate, 0.35)          # 35% nulls → ~0.5
