"""One renderer (CA-4, §5-3a): print charts come from the web's OWN chart
resolver — ``web/components/charts/resolveOption.ts`` and the ECharts builders,
bundled by ``npm run build:chart-ssr`` into ``chart_ssr.bundle.mjs`` beside this
module — executed as a node subprocess that returns SVG. The PDF draws exactly
the chart the user was looking at because it runs the same function; the
matplotlib port this replaces was a hand-kept mirror that drifted by design.

Fail-open at every seam: no node on PATH, a dead bundle, a timeout, or an
un-chartable grid all return ``None`` and the document falls back to the data
table — the same honest degradation the old renderer had.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

_BUNDLE = Path(__file__).with_name("chart_ssr.bundle.mjs")
_TIMEOUT_S = 30


def _node_bin() -> Optional[str]:
    return os.environ.get("AUGHOR_NODE_BIN") or shutil.which("node")


def render_charts_svg(charts: list[dict[str, Any]], *,
                      money_symbol: str = "") -> list[Optional[str]]:
    """Render a batch of chart requests to SVG strings via the SSR bundle —
    one subprocess for the whole document. Each request carries
    ``{columns, rows, chart_type, chart_config, exhibit, column_units, title,
    labels, width, height}``; the result aligns index-for-index, ``None`` where
    no honest chart exists (or rendering failed)."""
    if not charts:
        return []
    node = _node_bin()
    if not node or not _BUNDLE.exists():
        return [None] * len(charts)
    try:
        proc = subprocess.run(
            [node, str(_BUNDLE)],
            input=json.dumps({"charts": charts, "money_symbol": money_symbol}).encode("utf-8"),
            capture_output=True, timeout=_TIMEOUT_S,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:500] or "non-zero exit")
        out = json.loads(proc.stdout.decode("utf-8"))
        svgs = out.get("svgs") or []
        return [(s if isinstance(s, str) and s.strip() else None) for s in svgs] + \
            [None] * max(0, len(charts) - len(svgs))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "chart SSR is best-effort; findings fall back to their data tables",
                 counter="export.chart_ssr")
        return [None] * len(charts)


def render_chart_svg(columns: list, rows: list, chart_type: str, title: str, *,
                     units: Optional[dict] = None, exhibit: Optional[dict] = None,
                     labels: bool = True, width: int = 760, height: int = 0,
                     money_symbol: str = "") -> Optional[str]:
    """Single-chart convenience over :func:`render_charts_svg`."""
    return render_charts_svg([{
        "columns": columns or [], "rows": rows or [],
        "chart_type": chart_type or "auto", "title": title or "",
        "column_units": units or None, "exhibit": exhibit or None,
        "labels": labels, "width": width, "height": height,
    }], money_symbol=money_symbol)[0]


#: Rasterized charts are drawn on white rather than the page's own surface. Slack
#: composites a PNG against whichever theme the READER chose, so a transparent
#: background puts our dark-mode axis labels on a dark canvas for half the channel
#: and an invisible chart is worse than a table. PDF and PPTX embed on white pages
#: anyway, so nothing else notices.
_RASTER_BACKGROUND = "#ffffff"


def svg_to_png(svg: str, *, scale: float = 2.0) -> Optional[bytes]:
    """Rasterize an SVG for surfaces that cannot embed vectors (Slack, PPTX).

    resvg ships prebuilt wheels and links no system library, which is the whole
    reason it replaced svglib + reportlab's renderPM here: renderPM needs an
    rlPyCairo backend that was absent far more often than present — it was dead on
    the machine this was written on, which is why PPTX chart images degraded in
    silence and why `routers/charts.py` refused to serve PNG at all.

    Still best-effort, and still the same contract: any failure returns None and
    the caller falls back to its table or prose. A chart is the nice-to-have half
    of an answer; the numbers are the answer.
    """
    if not (svg or "").strip():
        return None
    try:
        import resvg_py
        return bytes(resvg_py.svg_to_bytes(svg_string=svg, zoom=scale,
                                           background=_RASTER_BACKGROUND))
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "SVG rasterization is best-effort; vector surfaces are unaffected",
                 counter="export.chart_raster")
        return None
