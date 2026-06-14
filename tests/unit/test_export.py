"""Report export → PDF / PPTX (charts, document model, endpoint serializer)."""
import pytest

from aughor.export import build_export_doc, export_report
from aughor.export.charts import render_chart

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

def test_render_chart_returns_png():
    png = render_chart(["category", "v"], [["a", 1], ["b", 2], ["c", 3]], "bar", "t")
    assert png and png[:4] == _PNG


def test_render_chart_line_and_pie():
    line = render_chart(["period", "v"], [["2025-01-01", 1], ["2025-02-01", 2]], "line", "t")
    pie = render_chart(["cat", "v"], [["a", 3], ["b", 1]], "pie", "t")
    assert line and line[:4] == _PNG
    assert pie and pie[:4] == _PNG


def test_render_chart_none_when_not_chartable():
    assert render_chart(["a", "b"], [["x", "y"]], "bar", "t") is None       # no numeric column
    assert render_chart(["a", "v"], [["x", 1]], "none", "t") is None        # explicit none
    assert render_chart([], [], "bar", "t") is None                          # empty


# ── document model ──────────────────────────────────────────────────────────

def test_ada_doc_has_rich_structure():
    doc = build_export_doc(_ada_inv())
    kinds = {b.kind for b in doc.blocks}
    assert {"heading", "chart", "keynums", "recs"} <= kinds
    assert doc.kind == "ada"
    # a chart block carries real PNG bytes
    assert any(b.kind == "chart" and b.png and b.png[:4] == _PNG for b in doc.blocks)


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
