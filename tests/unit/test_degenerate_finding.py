"""Degenerate ("no data") finding guard — explorer drops empty Phase-8 results so they
never become Briefing findings or broken monitors. See agent._is_degenerate_result and
the frontend isDegenerateFinding mirror in web/components/BriefingPanel.tsx.

Origin: a user created a monitor from a finding whose query returned a single all-NULL
row (a broken cross-dataset join) → "The query returned no data: 0 customers were found"
→ the monitor fired "No condition met" forever.
"""
from aughor.explorer.agent import _is_degenerate_result


def test_all_null_single_row_is_degenerate():
    assert _is_degenerate_result([(None, None, None)]) is True
    assert _is_degenerate_result([{"a": None, "b": None}]) is True


def test_zero_count_is_not_degenerate():
    # COUNT(...) = 0 is a REAL finding (0 ≠ NULL) and must survive.
    assert _is_degenerate_result([(0,)]) is False
    assert _is_degenerate_result([("EU", 0, 0.0)]) is False


def test_real_rows_not_degenerate():
    assert _is_degenerate_result([("EU", 1200, 4.5)]) is False
    assert _is_degenerate_result([{"region": "EU", "rev": 1200}]) is False


def test_no_data_interpretation_text_is_degenerate():
    rows = [("EU", 5)]  # rows look fine, but the interpreter said there's no data
    assert _is_degenerate_result(rows, "The query returned no data: 0 customers were found") is True
    assert _is_degenerate_result(rows, "resulting in NULL values for all review coverage metrics") is True
    assert _is_degenerate_result([], "no matching records in the window") is True


def test_normal_finding_text_survives():
    rows = [("EU", 5)]
    assert _is_degenerate_result(rows, "Revenue grew 12% QoQ driven by the EU cohort") is False
    # "found" alone (without the 0-count phrasing) must not trip the guard
    assert _is_degenerate_result(rows, "We found a strong correlation between X and Y") is False


def test_empty_rows_and_no_text_is_degenerate():
    assert _is_degenerate_result([]) is False        # empty handled by the caller's len()==0 skip
    assert _is_degenerate_result([], "") is False
