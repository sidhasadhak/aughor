"""A decomposition that compared a window against itself does not earn a place — CA-2.

Specimen cb37be54: `obs_traffic == comp_traffic` on every row, `abs_change = 0` everywhere
("Desktop 38475 | 38475 | 0", "SmartPhone 58314 | 58314 | 0"). `_is_zero_variance_ranking`
could not see it — its measure-column vocabulary had no `abs_change` — so the tautology reached
the narrator, who wrote "no significant variation ⇒ broad volume-based shift".
"""
from __future__ import annotations

from aughor.agent.investigate import (
    _finding_earns_place,
    _is_self_comparison_finding,
    _is_zero_variance_ranking,
    _measure_col_index,
)

SPECIMEN = {
    "title": "Traffic Decomposition by Device Class",
    "columns": ["DEVICE_CLASS", "obs_traffic", "comp_traffic", "abs_change"],
    "rows": [["Desktop", "38475", "38475", "0"], ["SmartPhone", "58314", "58314", "0"],
             ["unknown", "2826", "2826", "0"], ["Tablet", "1125", "1125", "0"]],
    "interpretation": "no measurable change in their contribution",
}


def test_the_specimen_is_a_self_comparison_and_earns_no_place():
    assert _is_self_comparison_finding(SPECIMEN)
    assert _finding_earns_place(SPECIMEN) is False


def test_change_column_is_the_measure_and_zero_everywhere_is_zero_variance():
    assert _measure_col_index(SPECIMEN["columns"]) == 3          # abs_change, not obs_traffic
    assert _is_zero_variance_ranking(SPECIMEN)


def test_a_real_decomposition_earns_its_place():
    real = {
        "columns": ["OS_NAME", "obs_traffic", "comp_traffic", "abs_change", "pct_change"],
        "rows": [["macOS", "10360", "5171", "5189", "1.0"], ["iOS", "18636", "14627", "4009", "0.27"],
                 ["Android", "9332", "5797", "3535", "0.61"]],
        "interpretation": "macOS doubled",
    }
    assert not _is_self_comparison_finding(real)
    assert not _is_zero_variance_ranking(real)
    assert _finding_earns_place(real) is True


def test_a_single_row_flat_period_is_a_fact_not_a_tautology():
    # one row whose obs equals comp is a genuinely flat period — a stated fact, kept
    flat = {"columns": ["period_label", "obs_value", "comp_value", "abs_change"],
            "rows": [["Total", "100", "100", "0"]], "interpretation": ""}
    assert _is_self_comparison_finding(flat) is False
    assert _is_zero_variance_ranking(flat) is False
    assert _finding_earns_place(flat) is True


def test_legacy_measure_vocabulary_still_resolves():
    assert _measure_col_index(["city", "share_pct"]) == 1
    assert _measure_col_index(["city", "n"]) is None
