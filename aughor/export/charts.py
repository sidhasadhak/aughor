"""
Server-side chart rendering for report export (PDF / PPTX).

The frontend renders charts with ECharts from `{columns, rows, chart_type}` and
the backend already stored its OWN `chart_type` hint per finding — so we do NOT
re-implement the client's inference or drive a headless browser. We render the
same shape with matplotlib (Agg, headless), honouring the stored hint, into a
print-quality PNG that both the PDF and the PPTX embed.

`render_chart(...)` returns PNG bytes, or None when the data isn't chartable
(no numeric column, <2 rows, an unknown/`none` hint) — the caller then falls back
to a data table. One bad finding can never break the document.

TWO RENDERERS, ONE GRAMMAR. This is the print half of the chart grammar the web
speaks in `web/components/charts/exhibit.ts` — a finding's `exhibit` spec (semantic
colour · reference lines · point labels) and its `column_units` must read the SAME
here as on screen, or the exported PDF quietly contradicts the app. The severity
ramp stops and the cost-metric test below are mirrored from that module verbatim;
keep them in sync. An absent `exhibit` renders exactly as this module always did,
so the `chart.exhibit_grammar` flag needs no check here — the payload IS the gate.
"""
from __future__ import annotations

import io
import re
from typing import Callable, Optional

import matplotlib
matplotlib.use("Agg")  # headless — no display, safe on a server
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# The app's chart tokens — the LIGHT set (web/aughor-v2/theme/tokens-v2.css --chart-1..6),
# because a print artifact is a light-background surface, plus the extended high-cardinality
# hues from web/components/charts/echarts/theme.ts. Was an indigo palette that predated the
# tokens and had silently drifted: the PDF drew indigo bars for the blue chart the user had
# just been looking at.
_PALETTE = ["#1F77B4", "#2CA02C", "#FF7F0E", "#9467BD", "#D62728", "#17BECF",
            "#F97316", "#EC4899", "#10B981", "#6366F1", "#F59E0B", "#14B8A6"]
_GRID = "#e5e7eb"
_FG = "#27272a"
_MUTED = "#71717a"

# ── chart grammar (mirrors web/components/charts/exhibit.ts) ─────────────────
# Metrics where a BIG value is a cost (delay, loss, returns…) ramp red; everything
# else ramps in the calm primary blue.
_COST_METRIC_RE = re.compile(
    r"(delay|late|loss|lost|cancel|refund|return|churn|complaint|defect|error|fail"
    r"|missing|overdue|wait|downtime|leak)", re.I)
_BLUE_RAMP = ("#9DC4F5", "#4C8EEE", "#1D4E9E")
_RED_RAMP = ("#F5C0A0", "#E64848", "#8E1E1E")
# Sign-diverging pair (builders.ts barOption `diverging`).
_SIGN_POS, _SIGN_NEG = "#2EC87B", "#E64848"
# Point labels stay legible only while the plot is sparse; past this they overprint.
_SCATTER_LABEL_MAX = 40
_MIN_SEVERITY_ROWS = 3
# A summary-statistics PROFILE grid (min/max/mean/std/p1…p99 per column) is a table,
# never a chart — charting 6 stat measures as grouped bars produces an unreadable
# micro-legend that says nothing (the W5 outlier-report A/B caught exactly this).
_STAT_COL_RE = re.compile(r"^(min|max|mean|avg|std|stddev|median|p\d{1,2})(_val(ue)?)?$", re.I)


def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    v = h.lstrip("#")
    return tuple(int(v[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a, b, t: float) -> tuple[float, float, float]:
    return tuple(av + (bv - av) * t for av, bv in zip(a, b))  # type: ignore[return-value]


def _severity_ramp(lo: float, hi: float, field: str) -> Callable[[float], tuple]:
    """Piecewise-linear interpolation through a 3-stop ramp, normalised to [lo, hi].
    Degenerate ranges sit at the middle stop. Mirrors exhibit.ts severityRamp()."""
    stops = [_hex_to_rgb(c) for c in (_RED_RAMP if _COST_METRIC_RE.search(field or "") else _BLUE_RAMP)]

    def _at(v: float):
        if v is None:
            return stops[1]
        t = min(1.0, max(0.0, (v - lo) / (hi - lo))) if hi > lo else 0.5
        return _mix(stops[0], stops[1], t * 2) if t <= 0.5 else _mix(stops[1], stops[2], (t - 0.5) * 2)

    return _at


_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥",
                     "INR": "₹", "AUD": "A$", "CAD": "C$", "SGD": "S$", "CHF": "CHF ",
                     "BRL": "R$", "ZAR": "R"}


def _fmt_for(field: str, units: Optional[dict]) -> Callable[[float], str]:
    """Per-field value formatter. An explicit `{col: "percent"}` unit is authoritative
    and scale-aware — a fraction (0.745) is ×100, an already-scaled percent (74.5) is
    left — so the PDF reads "74.5%" exactly where the app does; a `"currency:CHF"`
    unit prefixes the SOURCE currency's symbol. Mirrors the web's valueFormatter
    (builders.ts); absent a hint this is the legacy `_compact`."""
    u = (units or {}).get(field)
    if u == "percent":
        return lambda n: (f"{n * 100:.1f}%" if abs(n) <= 1.0001 else f"{n:.1f}%")
    if isinstance(u, str) and u.startswith("currency:"):
        sym = _CURRENCY_SYMBOLS.get(u[len("currency:"):], u[len("currency:"):] + " ")
        return lambda n: sym + _compact(n)
    return _compact


def _color_mode(exhibit: Optional[dict]) -> Optional[str]:
    """The exhibit's colour mode, tolerating every malformed shape. A spec this
    renderer can't read must degrade to a PLAIN chart — never to no chart, which
    is what an exception here would cause (render_chart's except → a table)."""
    if not isinstance(exhibit, dict):
        return None
    color = exhibit.get("color")
    return color.get("mode") if isinstance(color, dict) else None


def _ref_lines(exhibit: Optional[dict]) -> list[dict]:
    if not isinstance(exhibit, dict):
        return []
    lines = exhibit.get("ref_lines")
    if not isinstance(lines, list):
        return []
    out = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        v = _to_num(line.get("value"))
        if v is not None:
            out.append({"value": v, "label": str(line.get("label") or "")})
    return out


def _draw_ref_lines(ax, exhibit: Optional[dict], axis: str, fmt: Callable[[float], str]) -> None:
    """Dashed reference lines (peer median · global average · benchmark) on the VALUE
    axis — "x" for horizontal bars, "y" for a timeseries/scatter. Drawn in the neutral
    tick colour: a reference line is axis furniture, never a data series (mirrors the
    web's REF_LINE_COLOR rule — a palette hue would read as another series, and a red
    one would vanish into a same-family severity ramp)."""
    lines = _ref_lines(exhibit)
    if not lines:
        return
    # Stagger the labels by index (as the web does): two close reference values — a peer
    # median beside the global average — would otherwise print on top of each other.
    for k, line in enumerate(sorted(lines, key=lambda le: le["value"])):
        v, text = line["value"], f"{line['label']} {fmt(line['value'])}".strip()
        if axis == "x":
            ax.axvline(v, color=_MUTED, linestyle="--", linewidth=0.9, zorder=1)
            ax.annotate(text, xy=(v, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(2, 3 + k * 9), textcoords="offset points",
                        fontsize=6.5, color=_MUTED, ha="left", va="bottom")
        else:
            ax.axhline(v, color=_MUTED, linestyle="--", linewidth=0.9, zorder=1)
            ax.annotate(text, xy=(1.0, v), xycoords=("axes fraction", "data"),
                        xytext=(-2, 3), textcoords="offset points",
                        fontsize=6.5, color=_MUTED, ha="right", va="bottom")

_DATE_NAME = re.compile(r"(_date|_at|_time|^date$|^month$|^week$|^period$|^quarter$|^day$|^year$|date|month|quarter)", re.I)
_DATE_VAL = re.compile(r"^\d{4}-\d{2}")
# Identifiers must never be charted as measures. Covers snake_case (case-insensitive)
# AND camelCase (case-sensitive suffix after a lowercase letter — franchiseID slips
# past `_id$` because lowercasing erases the boundary; live incident: the PDF plotted
# SUM(franchiseID) as 3M-tall bars). Mirrors aughor/tools/profiler._KEY_PATTERN(_CAMEL).
_SKIP_ID = re.compile(r"(_id|_key|_code|_pk|_uuid|_guid|_sk|_hash)$|^id$", re.I)
_SKIP_ID_CAMEL = re.compile(r"[a-z](ID|Id|Key|Code|Num|Number|Identifier|UUID|Uuid|GUID|Guid|PK|Pk)$")


def _id_like(name: str) -> bool:
    return bool(_SKIP_ID.search(name or "") or _SKIP_ID_CAMEL.search(name or ""))


def _pretty(name: str) -> str:
    """`aircraft_type` → `Aircraft Type` — an axis/legend title a reader can read."""
    return (name or "").replace("_", " ").strip().title()


def _to_num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dlabel(v) -> str:
    """Tidy a date-ish axis label: drop a trailing midnight time (2024-10-01
    00:00:00 → 2024-10-01) so the axis isn't cluttered."""
    s = str(v)
    return s[:10] if s.endswith("00:00:00") and len(s) >= 10 else s


def _first_non_null(rows, i):
    for r in rows[:20]:
        if i < len(r) and r[i] not in (None, ""):
            return r[i]
    return rows[0][i] if rows and i < len(rows[0]) else None


def _classify(columns, rows):
    """Split column indexes into (date, numeric, category) — mirrors the TS classifier."""
    date_idx, num_idx, cat_idx = [], [], []
    for i, c in enumerate(columns):
        fv = _first_non_null(rows, i)
        is_date = bool(_DATE_NAME.search(c or "")) or (isinstance(fv, str) and bool(_DATE_VAL.match(fv)))
        if is_date:
            date_idx.append(i)
        elif not _id_like(c or "") and _to_num(fv) is not None:
            num_idx.append(i)
        else:
            cat_idx.append(i)
    # Prefer a non-identifier label column (name over franchiseID) for the category axis.
    cat_idx.sort(key=lambda i: _id_like(columns[i] or ""))
    return date_idx, num_idx, cat_idx


def _compact(n: float) -> str:
    a = abs(n)
    if a >= 1e9:
        return f"{n / 1e9:.1f}B"
    if a >= 1e6:
        return f"{n / 1e6:.1f}M"
    if a >= 1e3:
        return f"{n / 1e3:.1f}K"
    if n == int(n):
        return str(int(n))
    return f"{n:.2f}"


def _style(ax):
    ax.set_facecolor("white")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(_GRID)
    ax.tick_params(colors=_MUTED, labelsize=8, length=0)
    ax.yaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def _finish(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_chart(
    columns: list[str],
    rows: list[list],
    chart_type: str = "auto",
    title: str = "",
    *,
    width: float = 7.0,
    height: float = 3.4,
    units: Optional[dict] = None,
    exhibit: Optional[dict] = None,
) -> Optional[bytes]:
    """Render a finding's result to a PNG, honouring the stored chart_type hint.

    `units` is the finding's `column_units` ({"metric_total": "percent"}) so a rate
    prints "74.5%" here exactly as it does on screen; `exhibit` is its chart-grammar
    spec (semantic colour · reference lines · point labels). Both are optional and
    additive — absent, this renders byte-identically to before.

    Returns None when the data isn't chartable — the caller shows a table instead.
    """
    if not columns or not rows:
        return None
    ct = (chart_type or "auto").lower().replace("-", "_")
    if ct in ("none", ""):
        return None

    date_idx, num_idx, cat_idx = _classify(columns, rows)
    if not num_idx:
        return None
    # Stats-grid gate: ≥3 numeric columns named like summary statistics → table fallback.
    if sum(1 for i in num_idx if _STAT_COL_RE.match((columns[i] or "").strip())) >= 3:
        return None
    # Entity-profile gate: an ID-labelled grid with ≥3 measures is a PROFILE (the
    # Genie reports render these as tables — "Top 3 Customers — Profile Analysis").
    # Grouped bars over 3+ heterogeneous per-entity measures have no single message.
    if (not date_idx and len(num_idx) >= 3 and cat_idx
            and all(_id_like(columns[i] or "") for i in cat_idx
                    if len({str(r[i]) for r in rows if i < len(r)}) > 2)):
        return None

    try:
        # ── time series: date x-axis ──────────────────────────────────────────
        if date_idx and ct in ("line", "multi_line", "area", "auto", "combo"):
            return _render_timeseries(columns, rows, date_idx[0], num_idx, cat_idx, ct, title,
                                      width, height, units, exhibit)
        # ── scatter: two numerics, no category ───────────────────────────────
        if ct == "scatter" and len(num_idx) >= 2:
            return _render_scatter(columns, rows, num_idx, cat_idx, title, width, height, units, exhibit)
        # ── pie: one category + one measure ──────────────────────────────────
        if ct in ("pie", "treemap") and cat_idx:
            return _render_pie(columns, rows, cat_idx[0], num_idx[0], title, width, height)
        # ── default: categorical bar / grouped / stacked / combo ─────────────
        if cat_idx:
            return _render_bar(columns, rows, cat_idx[0], num_idx, ct, title, width, height, units, exhibit)
        # numerics only, no category, no date → scatter if 2, else single bar of values
        if len(num_idx) >= 2:
            return _render_scatter(columns, rows, num_idx, cat_idx, title, width, height, units, exhibit)
        return _render_bar(columns, rows, None, num_idx, ct, title, width, height, units, exhibit)
    except Exception:
        # Never let a render failure break the document — fall back to a table.
        plt.close("all")
        return None


def _render_timeseries(columns, rows, dx, num_idx, cat_idx, ct, title, w, h, units=None, exhibit=None):
    fig, ax = plt.subplots(figsize=(w, h))
    _style(ax)
    _fmt = _fmt_for(columns[num_idx[0]] if num_idx and num_idx[0] < len(columns) else "", units)
    # category present → one line per series (multi_line)
    if cat_idx and ct in ("multi_line", "auto", "line") and len(num_idx) >= 1:
        cx, vy = cat_idx[0], num_idx[0]
        series: dict = {}
        for r in rows:
            key = str(r[cx]) if cx < len(r) else ""
            y = _to_num(r[vy] if vy < len(r) else None)
            x = r[dx] if dx < len(r) else None
            if y is None or x is None:
                continue
            series.setdefault(key, []).append((_dlabel(x), y))
        if len(series) > 1:
            for k, (name, pts) in enumerate(sorted(series.items())[:8]):
                pts.sort(key=lambda p: p[0])
                ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", ms=2.5,
                        lw=1.6, color=_PALETTE[k % len(_PALETTE)], label=name)
            ax.legend(fontsize=7, frameon=False, ncol=min(4, len(series)), loc="upper left")
            _decorate_x(ax, [_dlabel(r[dx]) for r in rows if dx < len(r)])
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v)))
            _draw_ref_lines(ax, exhibit, "y", _fmt)
            if title:
                ax.set_title(title, fontsize=9.5, color=_FG, loc="left", pad=8)
            return _finish(fig)
    # single (or stacked) series over time
    xs = [_dlabel(r[dx]) for r in rows if dx < len(r)]
    vy = num_idx[0]
    ys = [_to_num(r[vy]) if vy < len(r) else None for r in rows]
    pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
    pairs.sort(key=lambda p: p[0])
    if not pairs:
        plt.close(fig)
        return None
    px, py = [p[0] for p in pairs], [p[1] for p in pairs]
    if ct == "area":
        ax.fill_between(range(len(px)), py, color=_PALETTE[0], alpha=0.18)
    ax.plot(range(len(px)), py, marker="o", ms=2.5, lw=1.8, color=_PALETTE[0])
    ax.set_xticks(range(len(px)))
    ax.set_xticklabels(px)
    _decorate_x(ax, px)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v)))
    _draw_ref_lines(ax, exhibit, "y", _fmt)
    if title:
        ax.set_title(title, fontsize=9.5, color=_FG, loc="left", pad=8)
    return _finish(fig)


def _render_bar(columns, rows, cx, num_idx, ct, title, w, h, units=None, exhibit=None):
    # Top-N by the first measure for readability.
    vy = num_idx[0]
    data = []
    for r in rows:
        label = str(r[cx]) if (cx is not None and cx < len(r)) else str(len(data) + 1)
        y = _to_num(r[vy] if vy < len(r) else None)
        if y is not None:
            data.append((label, [(_to_num(r[i] if i < len(r) else None) or 0.0) for i in num_idx]))
    if not data:
        return None
    # Largest-first by default; an "asc" exhibit means the QUERY asked for the bottom of
    # the ranking (ORDER BY <measure> ASC LIMIT N), so the chart leads with the row the
    # query led with instead of burying it at the far end.
    _asc = isinstance(exhibit, dict) and exhibit.get("order") == "asc"
    data.sort(key=lambda d: d[1][0], reverse=not _asc)
    data = data[:20]
    # Scale-sanity for multi-series: only series within 25x of the primary share an
    # axis honestly (a 3M series next to a 0.02 share flattens everything else), and
    # cap at 4 for readability — mirrors the frontend's scoreDualAxis rules.
    if len(num_idx) >= 2:
        def _series_max(s: int) -> float:
            return max((abs(d[1][s]) for d in data), default=0.0)
        p_max = _series_max(0) or 1.0
        keep = [s for s in range(len(num_idx))
                if s == 0 or (0 < _series_max(s) and p_max / max(_series_max(s), 1e-12) < 25
                              and _series_max(s) / p_max < 25)][:4]
        if len(keep) < len(num_idx):
            num_idx = [num_idx[s] for s in keep]
            data = [(d[0], [d[1][s] for s in keep]) for d in data]
    labels = [d[0] for d in data]
    fig, ax = plt.subplots(figsize=(w, max(h, 0.32 * len(labels) + 1.0)))
    _style(ax)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.yaxis.grid(False)
    y_pos = range(len(labels))
    n_series = len(num_idx)
    multi = n_series >= 2 and ct in ("stacked_bar", "combo", "grouped_bar", "auto")
    if multi:
        # grouped horizontal bars per measure
        bar_h = 0.8 / n_series
        for s in range(n_series):
            offsets = [y - 0.4 + bar_h * (s + 0.5) for y in y_pos]
            ax.barh(offsets, [d[1][s] for d in data], height=bar_h,
                    color=_PALETTE[s % len(_PALETTE)], label=columns[num_idx[s]])
        ax.legend(fontsize=7, frameon=False, loc="lower right")
    else:
        # Semantic colour: a "severity" exhibit ramps each bar by its OWN value — the
        # redundant encoding that makes a worst-N ranking read at a glance. Absent the
        # spec this is the flat primary, exactly as before.
        vals = [d[1][0] for d in data]
        mode = _color_mode(exhibit)
        color = _PALETTE[0]
        if mode == "sign":
            # The sign IS the message (a signed contribution/change) — mirrors the web's
            # diverging bars, which the PDF used to flatten to one indifferent hue.
            color = [_SIGN_POS if v >= 0 else _SIGN_NEG for v in vals]
        elif mode == "severity" and len(vals) >= _MIN_SEVERITY_ROWS:
            ramp = _severity_ramp(min(vals), max(vals), columns[vy] if vy < len(columns) else "")
            color = [ramp(v) for v in vals]
        ax.barh(list(y_pos), vals, color=color, height=0.7)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels([l[:28] for l in labels], fontsize=8)
    ax.invert_yaxis()
    _fmt = _fmt_for(columns[vy] if vy < len(columns) else "", units)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v)))
    if not multi:
        for i, d in enumerate(data):
            ax.text(d[1][0], i, " " + _fmt(d[1][0]), va="center", fontsize=7.5, color=_MUTED)
    # A horizontal bar puts the VALUE on x, so the reference line is vertical.
    _draw_ref_lines(ax, exhibit, "x", _fmt)
    if title:
        ax.set_title(title, fontsize=9.5, color=_FG, loc="left", pad=8)
    return _finish(fig)


def _render_pie(columns, rows, cx, vy, title, w, h):
    data = []
    for r in rows:
        label = str(r[cx]) if cx < len(r) else ""
        y = _to_num(r[vy] if vy < len(r) else None)
        if y is not None and y > 0:
            data.append((label, y))
    data.sort(key=lambda d: d[1], reverse=True)
    if len(data) > 8:  # collapse the long tail
        head, tail = data[:7], data[7:]
        data = head + [("Other", sum(d[1] for d in tail))]
    if not data:
        return None
    fig, ax = plt.subplots(figsize=(w * 0.75, h))
    ax.pie([d[1] for d in data], labels=[d[0][:20] for d in data], autopct="%1.0f%%",
           colors=_PALETTE, textprops={"fontsize": 8, "color": _FG},
           wedgeprops={"edgecolor": "white", "linewidth": 1})
    ax.axis("equal")
    if title:
        ax.set_title(title, fontsize=9.5, color=_FG, pad=8)
    return _finish(fig)


def _render_scatter(columns, rows, num_idx, cat_idx=None, title="", w=7.0, h=3.4,
                    units=None, exhibit=None):
    """Two numerics, correlation / outlier detection. An entity scatter (the exhibit
    grammar) additionally NAMES each point by its id-like column and colours the points
    by a low-cardinality second dimension — three dimensions plus identity in one
    exhibit, which is exactly what an outlier question needs."""
    xi, yi = num_idx[0], num_idx[1]
    cat_idx = cat_idx or []
    # Identity = the id-like column (aircraft_id); hue = a genuine low-cardinality
    # dimension (aircraft_type). The classifier sorts non-identifiers first, so read
    # the label from the back and the group from the front.
    label_i = next((i for i in reversed(cat_idx) if _id_like(columns[i] or "")), None)
    if label_i is None:
        label_i = cat_idx[0] if cat_idx else None
    group_i = next((i for i in cat_idx
                    if i != label_i and not _id_like(columns[i] or "")
                    and len({str(r[i]) for r in rows if i < len(r)}) <= 12), None)

    pts = []   # (x, y, label, group)
    for r in rows:
        x = _to_num(r[xi] if xi < len(r) else None)
        y = _to_num(r[yi] if yi < len(r) else None)
        if x is None or y is None:
            continue
        pts.append((x, y,
                    str(r[label_i]) if label_i is not None and label_i < len(r) else "",
                    str(r[group_i]) if group_i is not None and group_i < len(r) else None))
    if len(pts) < 2:
        return None

    fig, ax = plt.subplots(figsize=(w, h))
    _style(ax)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.7)
    if group_i is not None:
        groups: dict = {}
        for p in pts:
            groups.setdefault(p[3], []).append(p)
        # Most-populated groups keep their own hue; the long tail collapses to "Other"
        # so a wide dimension can't explode the legend (mirrors the web's cap).
        ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
        kept, rest = ranked[:8], [p for _, ps in ranked[8:] for p in ps]
        entries = kept + ([("Other", rest)] if rest else [])
        for k, (name, ps) in enumerate(entries):
            ax.scatter([p[0] for p in ps], [p[1] for p in ps], s=18,
                       color=_PALETTE[k % len(_PALETTE)], alpha=0.85,
                       edgecolors="white", linewidths=0.4, label=name)
        # A named column OUTSIDE the plot: "best" placement drops the legend on top of
        # the very outliers the exhibit exists to show, and it hides the labelled points.
        leg = ax.legend(fontsize=6.5, frameon=False, loc="center left", bbox_to_anchor=(1.01, 0.5),
                        title=_pretty(columns[group_i]), alignment="left")
        leg.get_title().set_fontsize(7)
        leg.get_title().set_color(_FG)
    else:
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=18, color=_PALETTE[0],
                   alpha=0.7, edgecolors="white", linewidths=0.4)
    _spec = exhibit if isinstance(exhibit, dict) else {}
    if _spec.get("label_points") and label_i is not None and len(pts) <= _SCATTER_LABEL_MAX:
        for x, y, label, _g in pts:
            if label:
                ax.annotate(label[:14], (x, y), xytext=(0, 5), textcoords="offset points",
                            fontsize=6, color=_FG, ha="center")
    fx, fy = _fmt_for(columns[xi], units), _fmt_for(columns[yi], units)
    ax.set_xlabel(_pretty(columns[xi]), fontsize=8, color=_MUTED)
    ax.set_ylabel(_pretty(columns[yi]), fontsize=8, color=_MUTED)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fx(v)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fy(v)))
    # Quadrant dividers (mean/median) — "is this entity high-volume AND high-severity?"
    q = _spec.get("quadrant")
    q = q if isinstance(q, dict) else {}
    if _to_num(q.get("x")) is not None:
        ax.axvline(_to_num(q.get("x")), color=_MUTED, linestyle="--", linewidth=0.9, zorder=1)
    if _to_num(q.get("y")) is not None:
        ax.axhline(_to_num(q.get("y")), color=_MUTED, linestyle="--", linewidth=0.9, zorder=1)
    _draw_ref_lines(ax, exhibit, "y", fy)
    if title:
        ax.set_title(title, fontsize=9.5, color=_FG, loc="left", pad=8)
    return _finish(fig)


def _decorate_x(ax, labels):
    # Thin x ticks when crowded so the axis stays legible.
    n = len(labels)
    if n > 12:
        step = max(1, n // 10)
        ticks = list(range(0, n, step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([labels[i] for i in ticks], rotation=45, ha="right", fontsize=7)
    else:
        ax.tick_params(axis="x", labelrotation=45)
        for lbl in ax.get_xticklabels():
            lbl.set_ha("right")
            lbl.set_fontsize(7.5)
