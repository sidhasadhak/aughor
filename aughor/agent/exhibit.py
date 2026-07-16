"""Chart-grammar exhibit spec — deterministic chart SEMANTICS for a finding.

The 2026-07-16 chart-grammar study (the two Databricks Genie reports on the
airline dataset) showed the readability gap is discipline, not chart variety:
color always carries meaning, rankings get reference context (peer benchmark /
global average lines), and outlier scatters name their entities. This module
computes that meaning DETERMINISTICALLY from rows the investigation already
fetched — no model, no extra query — and attaches it as one additive payload:

    finding["exhibit"] = {
        "color":       {"mode": "neutral"|"categorical"|"severity"|"sign", "field": ...},
        "ref_lines":   [{"value": 74.5, "label": "Avg (all segments)", "kind": "global_avg"}],
        "label_points": true,          # scatter: name each point (entity identity)
        "quadrant":    {"x": ..., "y": ...},
        "order":       "asc",          # lead with the row the QUERY led with (bottom-N)
    }

The web renderer (web/components/charts/exhibit.ts) treats an absent spec as
"render exactly as before", so everything here is gated by the emitters behind
flag ``chart.exhibit_grammar`` — off by default, byte-identical payloads.

Honesty rules: a reference line that sits far outside the plotted values is
dropped (it would distort the axis instead of adding context); the severity
ramp fires only for rate/percent rankings (a magnitude ranking's bar length
already carries the message — Genie leaves those neutral too).
"""
from __future__ import annotations

import re
from statistics import median
from typing import Any, Optional

# Rate/share-like measure names — the rankings that earn a severity ramp.
_RATE_COL_RE = re.compile(r"(share|rate|pct|percent|ratio|margin|factor|_of_total)", re.I)
# Count/instrumentation columns are never the plotted measure.
_COUNT_COL_NAMES = {"n", "count", "records", "n_records", "row_count"}
_ID_COL_RE = re.compile(r"(^|_)(id|key|sk|pk|code|uuid|guid|hash)$", re.I)
# A ref line must sit within the data span ± this margin (of the span) to be drawn.
_REF_SPAN_MARGIN = 0.5
_MIN_SEVERITY_ROWS = 3


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "NULL":
            return None
        return float(str(v).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _metric_index(finding: dict) -> Optional[int]:
    """Index of the plotted measure: prefer the cross-section template names, else
    the LAST column that parses numeric and isn't a count/id column."""
    cols = [str(c) for c in (finding.get("columns") or [])]
    rows = finding.get("rows") or []
    if not cols or not rows:
        return None
    low = [c.lower() for c in cols]
    named = next((i for i, c in enumerate(low)
                  if c in ("metric_total", "value", "val", "avg_per_record")), None)
    candidates = [named] if named is not None else [
        i for i in range(len(cols) - 1, -1, -1)
        if low[i] not in _COUNT_COL_NAMES and not _ID_COL_RE.search(cols[i])
    ]
    for i in candidates:
        vals = [x for x in (_num(r[i]) for r in rows if i < len(r)) if x is not None]
        if len(vals) >= max(1, len(rows) // 2):
            return i
    return None


def _metric_values(finding: dict) -> list[float]:
    """The plotted measure's values."""
    i = _metric_index(finding)
    if i is None:
        return []
    return [x for x in (_num(r[i]) for r in (finding.get("rows") or []) if i < len(r))
            if x is not None]


def clip_ref_lines(ref_lines: list[dict], values: list[float]) -> list[dict]:
    """Keep only reference lines near the plotted range — a line far outside it
    stretches the axis and buries the data (worse than no context)."""
    finite = [v for v in values if v is not None]
    if not finite:
        return []
    lo, hi = min(finite), max(finite)
    span = (hi - lo) or (abs(hi) or 1.0)
    lo_ok, hi_ok = lo - _REF_SPAN_MARGIN * span, hi + _REF_SPAN_MARGIN * span
    out = []
    for line in ref_lines or []:
        v = _num(line.get("value"))
        if v is not None and lo_ok <= v <= hi_ok:
            out.append({"value": v, "label": str(line.get("label") or ""),
                        "kind": line.get("kind")})
    return out


def order_from_sql(sql: str, measure: str) -> Optional[str]:
    """``"asc"`` when the query deliberately asked for the BOTTOM of the ranking —
    ``ORDER BY <measure> ASC`` with a ``LIMIT``. Otherwise None (the renderers'
    largest-first default stands).

    A "worst 15 routes" query answers a question whose subject is the FIRST row;
    both renderers sort largest-first regardless, which buries that row at the far
    end of the chart and leads with the least interesting one. The SQL is the
    authority on which end of the ranking was asked for — not the prose, and not a
    guess about whether high is good. Deterministic; None on any parse failure."""
    if not sql or not measure:
        return None
    try:
        import sqlglot
        from sqlglot import expressions as exp
        tree = sqlglot.parse_one(sql)
        if not tree or not tree.find(exp.Limit):
            return None
        order = tree.find(exp.Order)
        if not order:
            return None
        for o in order.find_all(exp.Ordered):
            col = o.this
            name = col.name if isinstance(col, (exp.Column, exp.Alias)) else str(col)
            if str(name).lower() == measure.lower():
                return "asc" if not o.args.get("desc") else None
    except Exception:
        return None
    return None


def attach_exhibit(finding: dict, *, severity: bool = False,
                   ref_lines: Optional[list[dict]] = None,
                   label_points: Optional[bool] = None,
                   quadrant: Optional[dict] = None,
                   order: Optional[str] = None) -> None:
    """Merge the given semantics into ``finding["exhibit"]`` (in place). Ref
    lines are clipped against the finding's own plotted values; an empty spec
    is not written at all, so a no-signal finding stays byte-identical."""
    spec: dict = dict(finding.get("exhibit") or {})
    if severity:
        spec["color"] = {"mode": "severity"}
    if ref_lines:
        clipped = clip_ref_lines(ref_lines, _metric_values(finding))
        if clipped:
            merged = list(spec.get("ref_lines") or [])
            seen = {(r.get("label"), r.get("value")) for r in merged}
            merged += [r for r in clipped if (r.get("label"), r.get("value")) not in seen]
            spec["ref_lines"] = merged
    if label_points is not None:
        spec["label_points"] = bool(label_points)
    if quadrant:
        spec["quadrant"] = quadrant
    if order:
        spec["order"] = order
    if spec:
        finding["exhibit"] = spec


def _order_for(finding: dict) -> Optional[str]:
    """The finding's own SQL decides which end of the ranking leads."""
    i = _metric_index(finding)
    if i is None:
        return None
    cols = [str(c) for c in (finding.get("columns") or [])]
    return order_from_sql(str(finding.get("sql") or ""), cols[i])


def _rate_column_share(finding: dict) -> Optional[str]:
    """The finding's rate-like measure column name, if it has exactly one."""
    cols = [str(c) for c in (finding.get("columns") or [])]
    units = finding.get("column_units") or {}
    rate_cols = [c for c in cols
                 if (units.get(c) == "percent" or _RATE_COL_RE.search(c))
                 and c.lower() not in _COUNT_COL_NAMES and not _ID_COL_RE.search(c)]
    return rate_cols[0] if len(rate_cols) >= 1 else None


def exhibit_for_cross_section(finding: dict, *, is_ratio: bool, is_percent: bool) -> None:
    """The cross-section (WHERE-lens) exhibit: a severity ramp when the ranked
    measure is a rate/percent, plus two deterministic reference lines computed
    from the SAME rows — the segment-weighted average (≈ the true global when
    the segments partition the population) and the R15 best-material-peer
    benchmark. Fail-open: a grid this can't read honestly annotates nothing."""
    try:
        from aughor.agent.opportunity import compute_opportunity, segment_rates
        refs: list[dict] = []
        segs = segment_rates(finding.get("columns") or [], finding.get("rows") or [],
                             is_ratio=is_ratio)
        if segs and len(segs) >= 3:
            total_n = sum(n for _, _, n in segs)
            if total_n > 0:
                wavg = sum(rate * n for _, rate, n in segs) / total_n
                rates = [rate for _, rate, _ in segs]
                if max(rates) > min(rates):
                    refs.append({"value": wavg, "label": "Avg (all segments)",
                                 "kind": "global_avg"})
        gap = compute_opportunity(finding.get("columns") or [], finding.get("rows") or [],
                                  is_ratio=is_ratio)
        if gap:
            refs.append({"value": gap["best_rate"],
                         "label": f"Benchmark: {gap['best_segment']}",
                         "kind": "benchmark"})
        n_rows = len(finding.get("rows") or [])
        attach_exhibit(finding,
                       severity=is_percent and n_rows >= _MIN_SEVERITY_ROWS,
                       ref_lines=refs,
                       order=_order_for(finding))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "chart-grammar exhibit is best-effort", counter="chart.exhibit")


def exhibit_for_lens(finding: dict, *, peer_median: bool = False) -> None:
    """The WHY-lens exhibit (benchmark/drill shares): severity ramp on the
    share ranking; for the peer-benchmark lens, a peer-median reference line
    computed from the share column across the peers. Fail-open."""
    try:
        share_col = _rate_column_share(finding)
        refs: list[dict] = []
        if peer_median and share_col:
            cols = [str(c) for c in (finding.get("columns") or [])]
            idx = cols.index(share_col)
            vals = [x for x in (_num(r[idx]) for r in (finding.get("rows") or [])
                                if idx < len(r)) if x is not None]
            if len(vals) >= 3:
                refs.append({"value": median(vals), "label": "Peer median",
                             "kind": "peer_median"})
        n_rows = len(finding.get("rows") or [])
        attach_exhibit(finding,
                       severity=bool(share_col) and n_rows >= _MIN_SEVERITY_ROWS,
                       ref_lines=refs)
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "chart-grammar lens exhibit is best-effort", counter="chart.exhibit")


def quick_exhibit(columns: list, rows: list, chart_type: str) -> Optional[dict]:
    """The quick-/ask-path exhibit, from the result grid alone (no benchmark is
    computed on that path, so ref lines are honestly absent): a severity ramp
    for a single-rate ranking; point labels for a scatter. Pure; None = no spec."""
    try:
        cols = [str(c) for c in (columns or [])]
        if not cols or not rows or len(rows) < _MIN_SEVERITY_ROWS:
            return None
        hint = (chart_type or "auto").lower()
        if hint == "scatter":
            return {"label_points": True}
        if hint not in ("auto", "bar", "bar_horizontal", "bar_vertical"):
            return None

        def _is_measure(i: int) -> bool:
            if cols[i].lower() in _COUNT_COL_NAMES or _ID_COL_RE.search(cols[i]):
                return False
            vals = [x for x in (_num(r[i]) for r in rows[:50] if i < len(r)) if x is not None]
            return len(vals) >= max(1, min(len(rows), 50) // 2)

        measures = [i for i in range(len(cols)) if _is_measure(i)]
        has_dimension = any(i not in measures for i in range(len(cols)))
        if has_dimension and len(measures) == 1 and _RATE_COL_RE.search(cols[measures[0]]):
            return {"color": {"mode": "severity"}}
        return None
    except Exception:
        return None
