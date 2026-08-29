"""RC-2 — the chart, for surfaces that cannot draw one themselves.

`POST /charts/svg` renders a turn's grid through the SAME resolver the browser
and the PDF already use (``aughor/export/echarts.py`` → ``chart_ssr.bundle.mjs``
→ ``web/components/charts/vega``), so a chart posted into Slack is the chart the
platform itself would have drawn. This route adds a DOOR, not a renderer: there
is no second grammar and no second engine to drift from the first.

SVG, not PNG, is the honest thing to return here. The one rasterizer this repo
had (``svg_to_png``, reportlab's renderPM) needs a backend that is absent far
more often than it is present — it is dead on this machine today, which is why
the PPTX export's chart images degrade silently — and a chart door whose output
depends on whether a system cairo happens to be installed is a door that reports
"no chart" for the wrong reason. Callers that need raster convert at their own
edge, where the destination's format is actually known.

204, not 404, when the data has no honest chart: that is the same verdict the
browser reaches for the same grid, and it means "there is nothing here worth
drawing", not "you asked wrong". A caller degrades to its data table instead of
posting a picture of nothing.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(tags=["charts"])

# A chart is a picture of a shape, not a rendering of a result set. Past a few
# hundred rows the marks stop being separable and the SSR subprocess starts
# paying for pixels nobody can read, so the grid is capped here rather than
# trusted from the wire — this door is reachable by any authenticated caller.
_MAX_ROWS = 500


class ChartSvgRequest(BaseModel):
    """One chart request, in the vocabulary the `/ask` stream already speaks:
    `columns` + `rows` as the grid frames carry them, `chart_type` as the
    `chart_type` frame names it, and `chart_config` verbatim as the
    `chart_config` frame emits it (the exhibit rides inside — the same place
    the web reads it from)."""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    chart_type: str = "auto"
    chart_config: dict = Field(default_factory=dict)
    column_units: Optional[dict] = None
    title: str = ""
    labels: bool = True
    width: int = 760
    height: int = 0
    # Leave empty to get the org's effective currency for `connection_id`. A
    # headless caller relaying `/ask` frames has no way to know the symbol —
    # it is never on the wire — and a euro business whose Slack charts read in
    # bare numbers is the same drift the export path already resolves for PDFs.
    money_symbol: str = ""
    connection_id: str = ""


@router.post("/charts/svg")
def render_chart_svg_route(req: ChartSvgRequest) -> Response:
    """Render one grid to SVG. 204 when the data has no honest chart, or when
    the renderer is unavailable — both mean the same thing to a caller (fall
    back to the table), and `render_charts_svg` already fails open to `None`
    for a missing node, a dead bundle, or a timeout."""
    from aughor.export.echarts import render_charts_svg

    if not req.columns or not req.rows:
        return Response(status_code=204)

    # `exhibit` is lifted out of `chart_config` rather than taken as its own
    # field because that is where the wire puts it: `_answer_core` merges the
    # quick exhibit INTO chart_config before emitting, so a caller relaying the
    # frame verbatim has it nested. The SSR bundle reads `exhibit`, and has
    # never read `chart_config` itself.
    exhibit = req.chart_config.get("exhibit") if isinstance(req.chart_config, dict) else None

    # Same resolution the export door does, for the same reason its comment
    # gives: the router resolves the effective currency and injects it, so the
    # renderer never reaches for settings itself. An explicit symbol wins.
    money = req.money_symbol
    if not money and req.connection_id:
        from aughor.routers.investigations import resolve_currency_symbol
        money = resolve_currency_symbol(req.connection_id, None)

    svg = render_charts_svg([{
        "columns": req.columns,
        "rows": req.rows[:_MAX_ROWS],
        "chart_type": req.chart_type or "auto",
        "chart_config": req.chart_config or None,
        "exhibit": exhibit if isinstance(exhibit, dict) else None,
        "column_units": req.column_units or None,
        "title": req.title or "",
        "labels": req.labels,
        "width": req.width if req.width > 0 else 760,
        "height": req.height,
    }], money_symbol=money)[0]

    if not svg:
        return Response(status_code=204)
    return Response(content=svg, media_type="image/svg+xml")
