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

from typing import Any, Optional

# Materiality floor for a segment to anchor either side of the benchmark —
# the same shape as _detect_anomalous_period's gate (≥30 records and ≥3% of
# the scanned volume), so a boutique segment can't headline the opportunity.
_MIN_SEGMENT_N = 30.0
_MIN_SEGMENT_SHARE = 0.03
# Below this relative rate gap the difference is measurement noise — silence.
_MIN_RELATIVE_GAP = 0.03
# ... and the gap × volume itself must be material vs the whole scanned pie.
_MIN_OPPORTUNITY_SHARE = 0.005


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


def compute_opportunity(
    columns: list, rows: list, *, is_ratio: bool = False
) -> Optional[dict]:
    """The gap × volume computation over one finding's result grid. Pure.

    Expects the cross-section template shape: a segment label column, a count
    column named ``n`` (or ``count``/``records``), and either ``avg_per_record``
    or ``metric_total``. For a ratio metric ``metric_total`` IS the per-segment
    rate; for an additive metric the rate is ``metric_total / n``. Returns None
    whenever the shape, materiality, or gap thresholds don't hold — silence is
    the correct output for a grid this lens can't read honestly."""
    if not columns or not rows or len(rows) < 3:
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
    if len(segs) < 3:
        return None

    total_n = sum(n for _, _, n in segs)
    floor = max(_MIN_SEGMENT_N, _MIN_SEGMENT_SHARE * total_n)
    material = [s for s in segs if s[2] >= floor]
    if len(material) < 2:
        return None

    worst = min(material, key=lambda s: s[1])
    best = max(material, key=lambda s: s[1])
    if best[1] <= 0 or worst[0] == best[0]:
        return None
    relative_gap = (best[1] - worst[1]) / abs(best[1])
    if relative_gap < _MIN_RELATIVE_GAP:
        return None
    opportunity = (best[1] - worst[1]) * worst[2]
    material_total = sum(rate * n for _, rate, n in material)
    if material_total <= 0 or opportunity < _MIN_OPPORTUNITY_SHARE * material_total:
        return None

    return {
        "worst_segment": worst[0], "worst_rate": worst[1], "worst_n": worst[2],
        "best_segment": best[0], "best_rate": best[1],
        "relative_gap": relative_gap,
        "opportunity": opportunity,
    }


def annotate_opportunity(
    finding: dict, *, metric_label: str = "", is_ratio: bool = False,
    is_percent: bool = False,
) -> bool:
    """Append the benchmark-gap key number (+ a hedged note) to one finding,
    in place. Returns True when it annotated. Never raises — a finding this
    lens can't read stays exactly as it was."""
    try:
        gap = compute_opportunity(
            finding.get("columns") or [], finding.get("rows") or [],
            is_ratio=is_ratio)
        if not gap:
            return False
        label = metric_label or "the metric"
        value = _fmt(gap["opportunity"], is_percent=False)
        context = (
            f"{gap['worst_segment']} runs {_fmt(gap['worst_rate'], is_percent=is_percent)} "
            f"vs {gap['best_segment']}'s {_fmt(gap['best_rate'], is_percent=is_percent)} "
            f"per record; closing that gap across {gap['worst_n']:,.0f} records ≈ {value} "
            f"{label}. A ceiling computed from peers, not a forecast — and read direction "
            f"from the metric (for a cost-like {label}, higher is worse)."
        )
        finding.setdefault("key_numbers", []).append({
            "label": f"Opportunity: {gap['worst_segment']} → {gap['best_segment']} benchmark",
            "value": value,
            "delta": f"{gap['relative_gap'] * 100:.0f}% below benchmark",
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
