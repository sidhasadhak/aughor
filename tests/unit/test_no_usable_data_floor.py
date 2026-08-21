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


# ── evidence the PHASES never captured (CA-3's analyst loop) ─────────────────
# Live, on an airline canvas: "give me route wise number of flights" ran deep, the model
# answered from one `run_sql` without any phase tool firing, and the report read
#
#   Data unavailable — flight count could not be analyzed
#   Every diagnostic query failed or returned zero rows …
#
# directly above "The network operated a total of 1,981 flights" and a correct list of
# 42-flight routes. Both halves cannot be true. The floor counts phase FINDINGS, and an
# ad-hoc query produces none — so a successful run was published as a total failure.
# Declaring a failure that did not happen is the same lie CA-0 exists to stop, reversed.

def test_ad_hoc_evidence_is_not_a_failed_run():
    phases = [{"phase_id": "intake", "findings": [INTAKE_SPEC]}]
    synth = _synth("MEDIUM")
    synth.headline = "ZRH-HAM leads with 42 flights"

    fired = _apply_no_usable_data_floor(synth, phases, {"metric_label": "flight count"},
                                        84)

    assert not fired
    assert synth.headline == "ZRH-HAM leads with 42 flights"
    assert "zero rows" not in synth.executive_summary


def test_but_an_unstructured_run_still_cannot_claim_confidence():
    """Rows outside the phases keep the report honest about WHAT happened; they do not
    make it structurally sound. The waterfall and recommendations are assembled from
    phase findings that do not exist, so they still go."""
    phases = [{"phase_id": "intake", "findings": [INTAKE_SPEC]}]
    synth = _synth("HIGH")
    synth.attribution_waterfall = [{"segment": "long-haul", "contribution": -7.0}]
    synth.recommendations = ["Rebalance the long-haul schedule"]

    _apply_no_usable_data_floor(synth, phases, {"metric_label": "flight count"}, 84)

    assert synth.confidence == "LOW"
    assert synth.attribution_waterfall == [] and synth.recommendations == []
    assert synth.confidence_justification.startswith("No structured phase produced evidence")


def test_a_genuinely_empty_run_still_says_so():
    """The guard's own case must survive the fix: nothing gathered anywhere still reads
    as a failure, exactly as CA-0 made it."""
    phases = [
        {"phase_id": "intake", "findings": [INTAKE_SPEC]},
        {"phase_id": "cross_section", "findings": [_zero_row_finding("PLATFORM")]},
    ]
    synth = _synth("HIGH")

    assert _apply_no_usable_data_floor(synth, phases, {"metric_label": "traffic"}, 0)
    assert synth.headline.startswith("Data unavailable — traffic")


def test_the_default_is_the_phase_script_s_behaviour():
    """The phase script never gathers evidence outside its phases, so omitting the
    argument must behave exactly as before this seam existed."""
    phases = [{"phase_id": "intake", "findings": [INTAKE_SPEC]}]
    synth = _synth("HIGH")
    assert _apply_no_usable_data_floor(synth, phases, {"metric_label": "traffic"})
