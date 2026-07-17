"""R16 P1 — argument-style report composition (flag `report.argument_style`).

Deterministic re-composition of the SAME report data: intake machinery out of
the body, key numbers inline in prose (not tile rows), one informative exhibit
per claim (degenerate results become sentences), and the R15 opportunity number
promoted to a Financial impact section. Flag off = the legacy composition.
"""
from __future__ import annotations

from aughor.export.document import build_export_doc


def _inv():
    return {
        "question": "where are we losing money?",
        "connection_id": "c",
        "completed_at": "2026-07-16T00:00:00Z",
        "report": {
            "_report_type": "investigate",
            "headline": "Long-haul capacity is underutilized",
            "executive_summary": "Load factors trail short-haul by 2.7 points.",
            "confidence": "high",
            "phases": [
                {"phase_id": "intake", "phase_name": "Question Intake", "status": "complete",
                 "findings": [{"title": "Investigation Specification",
                               "columns": ["field", "value"],
                               "rows": [["Metric", "net fare revenue"]],
                               "key_numbers": [], "chart_type": "none"}]},
                {"phase_id": "cross_section", "phase_name": "Where value is weakest",
                 "status": "complete", "summary": "Long-haul trails.",
                 "findings": [{
                     "title": "Load factor by haul",
                     "columns": ["haul", "metric_total", "n"],
                     "rows": [["long", 74.5, 258], ["short", 77.2, 900]],
                     "chart_type": "bar",
                     "interpretation": "Long-haul runs 74.5% vs short-haul 77.2%.",
                     "key_numbers": [
                         {"label": "long-haul load factor", "value": "74.5%", "delta": "-2.7pt"},
                         {"label": "Opportunity: long → short benchmark", "value": "1,767 seats",
                          "delta": "3% below benchmark",
                          "context": "A ceiling computed from peers, not a forecast."},
                     ]}]},
                {"phase_id": "temporal", "phase_name": "Temporal Trend", "status": "complete",
                 "summary": "Single period only.",
                 "findings": [{
                     "title": "Single-period data prevents trend analysis",
                     "columns": ["period", "value"],
                     "rows": [["2024-06", 83_272_278]],     # ONE row — the degenerate scatter
                     "chart_type": "line", "interpretation": "Only June 2024 exists.",
                     "key_numbers": []}]},
            ],
            "recommendations": [], "data_gaps": [],
        },
    }


def _kinds(doc):
    return [b.kind for b in doc.blocks]


def _headings(doc):
    return [b.text for b in doc.blocks if b.kind == "heading"]


def test_flag_off_keeps_the_legacy_composition(monkeypatch):
    monkeypatch.delenv("AUGHOR_REPORT_ARGUMENT_STYLE", raising=False)
    doc = build_export_doc(_inv())
    assert "Question Intake" in _headings(doc)          # machinery still in the body
    assert "keynums" in _kinds(doc)                     # tile block still emitted
    assert "Financial impact" not in _headings(doc)
    # legacy always ships the data table alongside any chart
    assert _kinds(doc).count("table") >= 2


def test_argument_style_recomposes_the_body(monkeypatch):
    monkeypatch.setenv("AUGHOR_REPORT_ARGUMENT_STYLE", "1")
    doc = build_export_doc(_inv())
    heads = _headings(doc)

    assert "Question Intake" not in heads               # machinery out of the body
    assert "keynums" not in _kinds(doc)                 # no tile rows …
    prose = " ".join(b.text or "" for b in doc.blocks if b.kind == "prose")
    assert "**long-haul load factor: 74.5%** (-2.7pt)" in prose   # … numbers inline, bold

    # one exhibit per claim: the 2-row haul comparison gets ONE exhibit
    # (chart if the renderer produced one, else the compact table) — never both.
    assert _kinds(doc).count("chart") + _kinds(doc).count("table") <= 1

    # the single-point "trend" renders NO exhibit — the sentence carries it
    assert "Only June 2024 exists." in " ".join(
        (b.text or "") for b in doc.blocks if b.kind == "finding")

    # the R15 opportunity number is promoted to its own decision section
    assert "Financial impact" in heads
    assert "1,767 seats" in prose
    assert "ceiling computed from peers" in prose
    # …and it no longer rides inline with the ordinary key numbers
    fi_idx = heads.index("Financial impact")
    assert fi_idx > heads.index("Where value is weakest")


def test_degenerate_exhibit_suppression_is_row_based():
    from aughor.export.document import _exhibit_argument
    assert _exhibit_argument(["a", "b"], [["x", 1]], "bar", "t") == []       # 1 row → nothing
    assert _exhibit_argument([], [], "bar", "t") == []
    out = _exhibit_argument(["a", "b"], [["x", 1], ["y", 2]], "none", "t")
    assert [b.kind for b in out] == ["table"]                                # no chart type → table
    assert len(out) == 1


def test_exhibit_table_fallback_is_capped():
    from aughor.export.document import _exhibit_argument
    rows = [[f"r{i}", i] for i in range(20)]
    out = _exhibit_argument(["k", "v"], rows, "none", "t")
    assert [b.kind for b in out] == ["table"]
    assert len(out[0].rows) == 8                                             # compact, not the grid


def test_suppressed_finding_renders_no_table_of_its_artifact_rows(monkeypatch):
    """A suppressed ratio finding's rows ARE the corrupt artifact; the caveat sentence
    carries it. The export must not print them as a clean table — the fan-out repair
    shipped a suppressed 'Route Market' cut as "intercontinental 55.73" beside a "2.8%"
    headline (inv 1a4615f7). The interpretation still renders; the rows do not."""
    inv = {
        "kind": "investigate",
        "report": {
            "_report_type": "investigate",
            "headline": "refund leakage rate recomputed — overall 2.8%",
            "executive_summary": "Overall 2.8%; two dimensions omitted.",
            "confidence": "low",
            "phases": [{
                "phase_id": "cross_section", "phase_name": "Where value is weakest",
                "status": "complete", "summary": "recomputed",
                "findings": [
                    {"title": "By channel", "columns": ["channel", "metric_total", "n"],
                     "rows": [["corporate", 3.41, 5000], ["web", 2.72, 5000]],
                     "chart_type": "bar_horizontal", "interpretation": "Corporate highest.",
                     "key_numbers": [], "_grain_repaired": True},
                    {"title": "By Route Market", "columns": ["market", "metric_total", "n"],
                     "rows": [["intercontinental", 55.73, 1], ["continental", 61.98, 1]],
                     "chart_type": "none", "interpretation": "could not be computed reliably.",
                     "key_numbers": [], "_suppressed": True},
                ]}],
            "recommendations": [], "data_gaps": [],
        },
    }
    for flag in ("1", "0"):        # argument style on AND off
        monkeypatch.setenv("AUGHOR_REPORT_ARGUMENT_STYLE", flag)
        doc = build_export_doc(inv)
        prose = " ".join((b.text or "") + " " + " ".join(
            "".join(str(c) for c in row) for row in (b.rows or [])) for b in doc.blocks)
        # the artifact rows are gone — not in prose, and not in any table block
        assert "55.73" not in prose and "61.98" not in prose and "intercontinental" not in prose
        finding_text = " ".join((b.text or "") for b in doc.blocks if b.kind == "finding")
        assert "could not be computed reliably" in finding_text   # the suppressed caveat stays
        assert "Corporate highest." in finding_text               # the REPAIRED finding still renders
        # the repaired channel finding DID produce an exhibit; the suppressed one did not
        assert any(b.kind in ("chart", "table") for b in doc.blocks)
