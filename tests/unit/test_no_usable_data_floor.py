"""A report with no evidence rows can never ship above LOW — CA-0.

Fixture shape = investigation 7774b792 (2026-08-19): five cross-section queries, every one
`rows: []` / `row_count: 0` (the filter `CHANNEL_LVL_0 = 'Direkteingabe'` matched nothing —
the value lives in CHANNEL_LVL_1), plus the synthetic intake-spec finding. The narrator shipped
confidence HIGH and "Desktop devices and Windows OS represent the primary segments". The old
floor keyed on `columns`, which a zero-row query still carries and the intake finding always
has — so it never fired.
"""
from __future__ import annotations

from aughor.agent.investigate import _apply_no_usable_data_floor, _finding_has_rows
from aughor.agent.prompts_investigate import ADASynthesisModel


def _synth(conf="HIGH") -> ADASynthesisModel:
    return ADASynthesisModel(
        headline="Cross-Sectional Analysis of Direkteingabe Orders on Chrome Browser",
        executive_summary="Desktop devices and Windows OS represent the primary segments, accounting for the majority of order volume.",
        closing_summary="",
        total_change_label="",
        attribution_waterfall=[],
        confidence=conf,
        confidence_justification="The findings are based on a direct cross-sectional scan.",
        recommendations=[],
    )


def _zero_row_finding(dim: str) -> dict:
    return {
        "finding_id": f"cs_{dim}",
        "title": f"Total Orders by {dim}",
        "sql": f"SELECT {dim}, SUM(ORDERS) FROM t WHERE CHANNEL_LVL_0 = 'Direkteingabe' AND BROWSER_NAME = 'Chrome' GROUP BY 1",
        "columns": [dim, "Total Orders", "records", "Total Orders per record"],
        "rows": [],
        "row_count": 0,
        "error": None,
    }


INTAKE_SPEC = {
    "finding_id": "intake_spec", "title": "Investigation Specification", "sql": "",
    "columns": ["field", "value"], "rows": [["Metric", "Total Orders (SUM(ORDERS))"]],
    "row_count": 6, "error": None,
}


def test_finding_has_rows_predicate():
    assert not _finding_has_rows(_zero_row_finding("OS_NAME"))
    assert not _finding_has_rows(INTAKE_SPEC), "synthetic spec rows are not evidence"
    assert not _finding_has_rows({**_zero_row_finding("X"), "rows": [[1]], "row_count": 1, "error": "boom"})
    assert _finding_has_rows({**_zero_row_finding("X"), "rows": [["Desktop", 10]], "row_count": 1})
    # row_count absent → rows is the fallback
    assert _finding_has_rows({"sql": "SELECT 1", "rows": [[1]], "error": None})


def test_specimen_7774b792_ships_low_not_high():
    phases = [
        {"phase_id": "intake", "findings": [INTAKE_SPEC]},
        {"phase_id": "cross_section", "findings": [_zero_row_finding(d) for d in
                                                   ("CHANNEL_LVL_1", "CHANNEL_LVL_2", "PLATFORM", "DEVICE_CLASS", "OS_NAME")]},
    ]
    synth = _synth("HIGH")
    fired = _apply_no_usable_data_floor(synth, phases, {"metric_label": "Total Orders"})
    assert fired
    assert synth.confidence == "LOW"
    assert synth.headline.startswith("Data unavailable — Total Orders")
    assert "zero rows" in synth.executive_summary
    assert synth.recommendations == [] and synth.attribution_waterfall == []
    assert synth.confidence_justification.startswith("No usable data was gathered")


def test_one_real_row_anywhere_leaves_the_verdict_alone():
    phases = [
        {"phase_id": "intake", "findings": [INTAKE_SPEC]},
        {"phase_id": "cross_section", "findings": [
            _zero_row_finding("PLATFORM"),
            {**_zero_row_finding("OS_NAME"), "rows": [["macOS", 15487]], "row_count": 1},
        ]},
    ]
    synth = _synth("HIGH")
    assert not _apply_no_usable_data_floor(synth, phases, {"metric_label": "traffic"})
    assert synth.confidence == "HIGH"
    assert synth.headline.startswith("Cross-Sectional")
