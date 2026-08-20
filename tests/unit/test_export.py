"""Report export → PDF / PPTX (charts, document model, endpoint serializer)."""
import pytest

import shutil as _shutil
from pathlib import Path as _Path

from aughor.export import build_export_doc, export_report
from aughor.export.echarts import render_chart_svg, render_charts_svg

_SSR_BUNDLE = _Path(__file__).resolve().parents[2] / "aughor" / "export" / "chart_ssr.bundle.mjs"
_ssr = pytest.mark.skipif(not _shutil.which("node") or not _SSR_BUNDLE.exists(),
                          reason="chart SSR needs node + chart_ssr.bundle.mjs")

_PNG = b"\x89PNG"
_PDF = b"%PDF"
_ZIP = b"PK\x03\x04"  # .pptx is a zip container


def _ada_inv() -> dict:
    return {
        "id": "x1", "kind": "investigation", "question": "Why did AOV change?",
        "connection_id": "demo", "completed_at": "2026-06-14T00:00:00",
        "report": {
            "_report_type": "investigate",
            "headline": "AOV rose 2% MoM",
            "executive_summary": "December AOV of **$260** rose **+2%** MoM.",
            "metric": "AOV", "observation_period": "Dec 2025", "comparison_basis": "MoM",
            "total_change_label": "+$5 (+2%)", "confidence": "HIGH",
            "confidence_justification": "z = 3.99",
            "phases": [{
                "phase_id": "baseline", "phase_name": "Baseline", "phase_icon": "", "status": "complete",
                "summary": "AOV was stable, then rose in December.",
                "findings": [{
                    "finding_id": "f1", "title": "Monthly AOV", "sql": "SELECT period, aov FROM o",
                    "columns": ["period", "aov"],
                    "rows": [["2025-10-01 00:00:00", 257.0], ["2025-11-01 00:00:00", 255.5], ["2025-12-01 00:00:00", 260.5]],
                    "row_count": 3, "error": None, "interpretation": "AOV rose to **$260**.",
                    "key_numbers": [{"label": "Dec AOV", "value": "$260", "delta": "+2%", "context": "MoM"}],
                    "chart_type": "line", "stat_note": "z=3.99", "is_significant": True,
                }],
            }],
            "attribution_waterfall": [
                {"cause": "US East", "amount_label": "$3", "pct_of_total": 60.0, "controllable": True, "structural": False},
                {"cause": "EU", "amount_label": "$2", "pct_of_total": 40.0, "controllable": False, "structural": True},
            ],
            "recommendations": [{"action": "Investigate US East", "expected_impact": "Recover $3",
                                 "owner": "Growth", "timeline": "Q3"}],
            "data_gaps": ["No channel-level data"],
        },
        "query_history": [],
    }


def _chat_inv() -> dict:
    return {
        "id": "c1", "kind": "chat", "question": "Top categories?",
        "connection_id": "demo", "completed_at": "2026-06-14T00:00:00",
        "report": {
            "headline": "Fragrance leads revenue",
            "sql": "SELECT category, revenue FROM s GROUP BY 1",
            "columns": ["category", "revenue"],
            "rows": [["Fragrance", 503000], ["Skincare", 368000], ["Makeup", 210000]],
            "chart_type": "bar",
            "intent": "You want categories ranked by revenue.",
            "approach": ["Group by category", "Sum revenue", "Order desc"],
            "insight": {"narrative": "**Fragrance** leads with **$503K**.",
                        "anomalies": ["Makeup lags the top two"], "trend": "up", "confidence": "high"},
        },
    }


def _analysis_inv() -> dict:
    return {
        "id": "a1", "kind": "investigation", "question": "What drove churn?",
        "connection_id": "demo", "completed_at": "2026-06-14T00:00:00",
        "report": {
            "headline": "Enterprise churn drove the decline",
            "verdict": "Churn concentrated in enterprise accounts.",
            "key_findings": [{"claim": "Enterprise churn doubled", "evidence": "From 2% to 4%.", "confidence": 0.82}],
            "what_is_not_the_cause": ["Pricing changes"],
            "risks": ["Further enterprise losses"],
            "recommended_actions": ["Launch a retention play"],
            "data_quality_notes": [{"table": "subs", "column": "plan", "issue": "nulls", "recommended_fix": "backfill"}],
        },
        "query_history": [],
    }


# ── charts ──────────────────────────────────────────────────────────────────

@_ssr
def test_render_chart_svg_returns_svg():
    # CA-4 one renderer: the print chart is the web resolver's own SVG.
    svg = render_chart_svg(["category", "v"], [["a", 1], ["b", 2], ["c", 3]], "bar", "t")
    assert svg and svg.lstrip().startswith("<svg")


@_ssr
def test_render_chart_svg_line_and_jobs():
    line = render_chart_svg(["period", "v"], [["2025-01-01", 1], ["2025-02-01", 2]], "line", "t")
    # A CA-4 job token resolves to its form in the same renderer.
    mag = render_chart_svg(["cat", "v"], [["a", 3], ["b", 1], ["c", 2]], "magnitude", "t")
    assert line and line.lstrip().startswith("<svg")
    assert mag and mag.lstrip().startswith("<svg")


@_ssr
def test_render_chart_svg_none_when_not_chartable():
    assert render_chart_svg(["a", "b"], [["x", "y"]], "bar", "t") is None   # no numeric column
    assert render_chart_svg(["a", "v"], [["x", 1]], "none", "t") is None    # explicit none
    assert render_chart_svg([], [], "bar", "t") is None                     # empty


@_ssr
def test_render_charts_svg_batch_aligns_index_for_index():
    svgs = render_charts_svg([
        {"columns": ["c", "v"], "rows": [["a", 1], ["b", 2]], "chart_type": "bar", "title": "one"},
        {"columns": ["a", "b"], "rows": [["x", "y"]], "chart_type": "bar", "title": "no chart"},
        {"columns": ["c", "v"], "rows": [["a", 3], ["b", 4]], "chart_type": "line", "title": "two"},
    ])
    assert len(svgs) == 3
    assert svgs[0] and svgs[2] and svgs[1] is None


def test_render_chart_svg_fails_open_without_node(monkeypatch):
    # No node on PATH → None, never an exception (the document falls back to tables).
    from aughor.export import echarts as E
    monkeypatch.setattr(E, "_node_bin", lambda: None)
    assert E.render_chart_svg(["c", "v"], [["a", 1], ["b", 2]], "bar", "t") is None


# ── document model ──────────────────────────────────────────────────────────

def test_ada_doc_has_rich_structure():
    """The export shape. `keynums` left this set when `report.argument_style` graduated
    to default-ON (2026-07-22 audit) and Wave 2d made it unconditional: the argument
    style drops stat-tile rows and bolds key numbers inline in the prose instead. With
    the flag gone there is no legacy composition left to assert against — the `keynums`
    assertion below now pins that nothing reintroduces tile rows."""
    doc = build_export_doc(_ada_inv())
    kinds = {b.kind for b in doc.blocks}
    assert {"heading", "chart", "recs"} <= kinds
    assert "keynums" not in kinds
    assert doc.kind == "ada"
    # a chart block carries the SSR's vector SVG (PNG rides along only where a
    # raster backend exists — PPTX degrades honestly without one)
    assert any(b.kind == "chart" and b.svg and b.svg.lstrip().startswith(b"<svg")
               for b in doc.blocks)


def test_chat_and_analysis_dispatch():
    assert build_export_doc(_chat_inv()).kind == "chat"
    assert build_export_doc(_analysis_inv()).kind == "investigation"


# ── full export ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inv_fn", [_ada_inv, _chat_inv, _analysis_inv])
@pytest.mark.parametrize("fmt,magic", [("pdf", _PDF), ("pptx", _ZIP)])
def test_export_produces_valid_file(inv_fn, fmt, magic):
    data, filename, media = export_report(inv_fn(), fmt)
    assert data[: len(magic)] == magic
    assert filename.endswith("." + fmt)
    assert len(data) > 1500
    assert media


def test_bad_format_raises():
    with pytest.raises(ValueError):
        export_report(_chat_inv(), "docx")
