"""Intake data-coverage probe (T4-2, 2026-07-09).

Deep-Analysis audit finding (inv1): the intake declared "Data range inferred from sample (2023-01 to
2023-03); exact min/max unknown" on data actually spanning 2023-01 → 2025-01, and the report's
`observation_period` came out empty for the cross-sectional scan. T4-2 runs a deterministic MIN/MAX
probe at intake, records the real DATA COVERAGE window (surfaced as `observation_period` even for a
cross-sectional scan), and replaces an observation window that falls outside the real span.
`_observation_window_is_wrong` is the pure decision. See aughor/agent/investigate.py.
"""
from aughor.agent.investigate import _observation_window_is_wrong


def test_empty_window_is_wrong():
    assert _observation_window_is_wrong("", "", "2023-01-01", "2025-01-09") is True
    assert _observation_window_is_wrong(None, None, "2023-01-01", "2025-01-09") is True


def test_window_past_the_data_end_is_wrong():
    # a "last 3 months" the LLM anchored to 2026 while data ends 2025-01
    assert _observation_window_is_wrong("2026-01-01", "2026-03-01", "2023-01-01", "2025-01-09") is True


def test_window_before_the_data_start_is_wrong():
    assert _observation_window_is_wrong("2019-01-01", "2019-06-01", "2023-01-01", "2025-01-09") is True


def test_window_fully_inside_span_is_kept():
    # a legitimately narrow temporal window inside the real span is NOT overridden
    assert _observation_window_is_wrong("2024-01-01", "2024-06-01", "2023-01-01", "2025-01-09") is False
    assert _observation_window_is_wrong("2023-01-01", "2023-03-31", "2023-01-01", "2025-01-09") is False


def test_datetime_prefixes_are_tolerated():
    # ISO datetime strings (with a time part) compare on the date prefix
    assert _observation_window_is_wrong("2024-01-01 00:00:00", "2024-06-01 00:00:00",
                                        "2023-01-01", "2025-01-09") is False
