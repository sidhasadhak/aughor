"""
Server-side chart rendering for report export (PDF / PPTX).

The frontend renders charts with Vega-Lite from `{columns, rows, chart_type}` and
the backend already stored its OWN `chart_type` hint per finding — so we do NOT
re-implement the client's inference or drive a headless browser. We render the
same shape with matplotlib (Agg, headless), honouring the stored hint, into a
print-quality PNG that both the PDF and the PPTX embed.

`render_chart(...)` returns PNG bytes, or None when the data isn't chartable
(no numeric column, <2 rows, an unknown/`none` hint) — the caller then falls back
to a data table. One bad finding can never break the document.
"""
from __future__ import annotations

import io
import re
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # headless — no display, safe on a server
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# Indigo-led palette, aligned with the app's chart colours (AUG_PALETTE).
_PALETTE = ["#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
            "#3b82f6", "#ef4444", "#14b8a6", "#a855f7", "#f97316"]
_GRID = "#e5e7eb"
_FG = "#27272a"
_MUTED = "#71717a"

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
) -> Optional[bytes]:
    """Render a finding's result to a PNG, honouring the stored chart_type hint.

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

    try:
        # ── time series: date x-axis ──────────────────────────────────────────
        if date_idx and ct in ("line", "multi_line", "area", "auto", "combo"):
            return _render_timeseries(columns, rows, date_idx[0], num_idx, cat_idx, ct, title, width, height)
        # ── scatter: two numerics, no category ───────────────────────────────
        if ct == "scatter" and len(num_idx) >= 2:
            return _render_scatter(columns, rows, num_idx, title, width, height)
        # ── pie: one category + one measure ──────────────────────────────────
        if ct in ("pie", "treemap") and cat_idx:
            return _render_pie(columns, rows, cat_idx[0], num_idx[0], title, width, height)
        # ── default: categorical bar / grouped / stacked / combo ─────────────
        if cat_idx:
            return _render_bar(columns, rows, cat_idx[0], num_idx, ct, title, width, height)
        # numerics only, no category, no date → scatter if 2, else single bar of values
        if len(num_idx) >= 2:
            return _render_scatter(columns, rows, num_idx, title, width, height)
        return _render_bar(columns, rows, None, num_idx, ct, title, width, height)
    except Exception:
        # Never let a render failure break the document — fall back to a table.
        plt.close("all")
        return None


def _render_timeseries(columns, rows, dx, num_idx, cat_idx, ct, title, w, h):
    fig, ax = plt.subplots(figsize=(w, h))
    _style(ax)
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
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _compact(v)))
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
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _compact(v)))
    if title:
        ax.set_title(title, fontsize=9.5, color=_FG, loc="left", pad=8)
    return _finish(fig)


def _render_bar(columns, rows, cx, num_idx, ct, title, w, h):
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
    data.sort(key=lambda d: d[1][0], reverse=True)
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
        ax.barh(list(y_pos), [d[1][0] for d in data], color=_PALETTE[0], height=0.7)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels([l[:28] for l in labels], fontsize=8)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _compact(v)))
    if not multi:
        for i, d in enumerate(data):
            ax.text(d[1][0], i, " " + _compact(d[1][0]), va="center", fontsize=7.5, color=_MUTED)
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


def _render_scatter(columns, rows, num_idx, title, w, h):
    xi, yi = num_idx[0], num_idx[1]
    xs, ys = [], []
    for r in rows:
        x = _to_num(r[xi] if xi < len(r) else None)
        y = _to_num(r[yi] if yi < len(r) else None)
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    if len(xs) < 2:
        return None
    fig, ax = plt.subplots(figsize=(w, h))
    _style(ax)
    ax.xaxis.grid(True, color=_GRID, linewidth=0.7)
    ax.scatter(xs, ys, s=18, color=_PALETTE[0], alpha=0.7, edgecolors="white", linewidths=0.4)
    ax.set_xlabel(columns[xi], fontsize=8, color=_MUTED)
    ax.set_ylabel(columns[yi], fontsize=8, color=_MUTED)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _compact(v)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _compact(v)))
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
