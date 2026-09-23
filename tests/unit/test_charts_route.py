"""RC-2 — the chart door (`POST /charts/svg`).

The contract, not the renderer: the renderer is `aughor/export/echarts.py`, and
it is already covered in `test_export.py`. What matters here is that the DOOR
relays the wire's own vocabulary faithfully, caps what a public caller can ask
it to draw, and answers 204 — not 500, not an empty SVG — every time there is
no honest chart. A caller reads 204 as "fall back to the data table", so the
distinction between "nothing worth drawing" and "something went wrong" has to
survive at the boundary.

One test drives the REAL Vega bundle, guarded the way `test_export.py` guards
its own: a chart path proved only against a stub would look exactly as healthy
as one that draws nothing.
"""
from __future__ import annotations

import shutil as _shutil
from pathlib import Path as _Path

import pytest
from fastapi.testclient import TestClient

from aughor.api import app

client = TestClient(app)

_SSR_BUNDLE = _Path(__file__).resolve().parents[2] / "aughor" / "export" / "chart_ssr.bundle.mjs"
_ssr = pytest.mark.skipif(not _shutil.which("node") or not _SSR_BUNDLE.exists(),
                          reason="chart SSR needs node + chart_ssr.bundle.mjs")

_GRID = {
    "columns": ["region", "revenue"],
    "rows": [["East", 120], ["West", 98], ["North", 143], ["South", 131]],
}


@_ssr
def test_renders_a_real_chart_through_the_shared_resolver():
    r = client.post("/charts/svg", json={**_GRID, "chart_type": "auto",
                                         "title": "Revenue by region", "money_symbol": "€"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    body = r.text
    assert body.lstrip().startswith("<svg")
    # Marks, not just axes: an empty chart is also well-formed SVG, which is
    # exactly how a broken resolver passes a "did it return SVG?" assertion.
    assert body.count("<path") > 2
    assert "East" in body and "West" in body


@pytest.mark.parametrize("payload", [
    {"columns": [], "rows": []},
    {"columns": ["a"], "rows": []},
    {"columns": [], "rows": [[1]]},
])
def test_no_data_is_204_not_an_error(payload):
    assert client.post("/charts/svg", json=payload).status_code == 204


def test_no_honest_chart_is_204(monkeypatch):
    monkeypatch.setattr("aughor.export.echarts.render_charts_svg", lambda charts, **kw: [None])
    assert client.post("/charts/svg", json={**_GRID, "chart_type": "auto"}).status_code == 204


def test_a_dead_renderer_is_204_not_500(monkeypatch):
    # `render_charts_svg` fails open to None for a missing node, a dead bundle
    # or a timeout. The door must not turn that into an error the caller has to
    # special-case — "no chart" is one answer, however it was reached.
    monkeypatch.setattr("aughor.export.echarts._node_bin", lambda: None)
    assert client.post("/charts/svg", json={**_GRID, "chart_type": "auto"}).status_code == 204


def test_exhibit_is_lifted_out_of_chart_config_where_the_wire_puts_it(monkeypatch):
    # `_answer_core` merges the exhibit INTO chart_config before emitting, so a
    # caller relaying the frame verbatim has it nested. The bundle reads
    # `exhibit`, and has never read `chart_config` itself.
    seen: list[dict] = []

    def _capture(charts, **kw):
        seen.extend(charts)
        return ["<svg/>"]

    monkeypatch.setattr("aughor.export.echarts.render_charts_svg", _capture)
    exhibit = {"kind": "ranked", "highlight": "East"}
    client.post("/charts/svg", json={**_GRID, "chart_type": "bar",
                                     "chart_config": {"exhibit": exhibit, "stacked": True}})
    assert seen[0]["exhibit"] == exhibit
    assert seen[0]["chart_config"] == {"exhibit": exhibit, "stacked": True}


def test_a_chart_config_without_an_exhibit_passes_none_rather_than_a_fragment(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr("aughor.export.echarts.render_charts_svg",
                        lambda charts, **kw: (seen.extend(charts), ["<svg/>"])[1])
    client.post("/charts/svg", json={**_GRID, "chart_config": {"stacked": True}})
    assert seen[0]["exhibit"] is None


def test_the_grid_is_capped_at_the_door(monkeypatch):
    # Reachable by any authenticated caller: a chart is a picture of a shape,
    # and past a few hundred rows the marks stop being separable while the SSR
    # subprocess keeps paying for pixels nobody can read.
    from aughor.routers.charts import _MAX_ROWS
    seen: list[dict] = []
    monkeypatch.setattr("aughor.export.echarts.render_charts_svg",
                        lambda charts, **kw: (seen.extend(charts), ["<svg/>"])[1])
    client.post("/charts/svg", json={"columns": ["a"], "rows": [[i] for i in range(_MAX_ROWS + 250)]})
    assert len(seen[0]["rows"]) == _MAX_ROWS


def test_defaults_match_the_renderer_the_other_surfaces_use(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr("aughor.export.echarts.render_charts_svg",
                        lambda charts, **kw: (seen.extend(charts), ["<svg/>"])[1])
    client.post("/charts/svg", json=_GRID)
    assert seen[0]["chart_type"] == "auto"   # let the resolver decide, as the web does
    assert seen[0]["width"] == 760           # the print/SSR default
    assert seen[0]["labels"] is True


def test_currency_defaults_from_the_connection_when_the_caller_cannot_know_it(monkeypatch):
    # The symbol is never on the `/ask` wire, so a headless door has no way to
    # relay it. Left empty, the route resolves it exactly as the export door
    # does — otherwise a euro business gets Slack charts in bare numbers.
    seen: list[dict] = []
    monkeypatch.setattr("aughor.routers.investigations.resolve_currency_symbol",
                        lambda conn, schema: "€" if conn == "lux" else "$")
    monkeypatch.setattr("aughor.export.echarts.render_charts_svg",
                        lambda charts, **kw: (seen.append(kw), ["<svg/>"])[1])

    client.post("/charts/svg", json={**_GRID, "connection_id": "lux"})
    assert seen[0]["money_symbol"] == "€"


def test_an_explicit_symbol_wins_over_the_connection(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr("aughor.routers.investigations.resolve_currency_symbol",
                        lambda conn, schema: "€")
    monkeypatch.setattr("aughor.export.echarts.render_charts_svg",
                        lambda charts, **kw: (seen.append(kw), ["<svg/>"])[1])

    client.post("/charts/svg", json={**_GRID, "connection_id": "lux", "money_symbol": "£"})
    assert seen[0]["money_symbol"] == "£"


def test_no_connection_means_no_lookup(monkeypatch):
    # The resolver reaches the profile store; a caller that named no connection
    # must not pay for that, nor get another org's currency by accident.
    monkeypatch.setattr("aughor.routers.investigations.resolve_currency_symbol",
                        lambda conn, schema: (_ for _ in ()).throw(AssertionError("must not resolve")))
    seen: list[dict] = []
    monkeypatch.setattr("aughor.export.echarts.render_charts_svg",
                        lambda charts, **kw: (seen.append(kw), ["<svg/>"])[1])

    client.post("/charts/svg", json=_GRID)
    assert seen[0]["money_symbol"] == ""


# ── the band that rendered nothing ───────────────────────────────────────────────

#: A category plus an ADDITIVE measure. `chartTypeInference` sends 7-24 unique categories
#: here to a `treemap`; at 6 or fewer it is a bar, at 25+ a bar again. The middle is the
#: band that returned 204 on every headless surface at once.
_BAND = {
    "columns": ["product", "revenue"],
    "rows": [[f"Item {i}", 1000 * (40 - i)] for i in range(10)],
}


@_ssr
def test_the_commonest_business_grid_renders_a_chart():
    """"Top sellers by revenue" — and for a long time, no chart at all.

    `resolveVegaSpec` resolves `auto` INSIDE tier 1, but `chart-ssr-entry` asks
    `resolveTier3Spec` first, and tier 3 matches on the concrete type. Asked about the
    literal string "auto" it never matched, so the treemap it has drawn all along was
    never offered the data — tier 1 then inferred `treemap`, found it outside its own
    supported set, and returned null. PDF, PPTX, this door and the Slack bot that relays
    it all dropped the chart in silence and fell back to a table.

    This runs the REAL bundle, so it is also a staleness guard: edit
    `web/scripts/chart-ssr-entry.ts` without `npm run build:chart-ssr` and the shipped
    artifact is what answers here.
    """
    r = client.post("/charts/svg", json={**_BAND, "chart_type": "auto", "title": "Top sellers"})
    assert r.status_code == 200, "a category and an additive measure must draw something"
    assert r.text.lstrip().startswith("<svg"), r.text[:200]


@_ssr
@pytest.mark.parametrize("n", [7, 12, 24])
def test_every_row_count_in_the_band_renders(n):
    """7, 12 and 24 all returned 204 before; 6 and 25 never did. Parametrised because a
    single row count would not show that it is a BAND, and a future threshold change
    would slip through a one-sample guard."""
    grid = {"columns": ["product", "revenue"],
            "rows": [[f"Item {i}", 1000 * (n + 5 - i)] for i in range(n)]}
    assert client.post("/charts/svg", json={**grid, "chart_type": "auto"}).status_code == 200


@_ssr
@pytest.mark.parametrize("columns,rows", [
    # The shapes that already worked. The fix substitutes a type ONLY when the inference
    # names a tier-3 one, precisely so these keep tier 1's own column choice.
    (["product", "score"], [[f"Item {i}", 90 - i] for i in range(8)]),
    (["day", "revenue"], [[f"2026-09-{d:02d}", 100 + d * 7] for d in range(1, 15)]),
    (["region", "revenue"], [["East", 120], ["West", 98], ["North", 143]]),
])
def test_the_shapes_that_already_rendered_still_do(columns, rows):
    r = client.post("/charts/svg", json={"columns": columns, "rows": rows, "chart_type": "auto"})
    assert r.status_code == 200
