"""Arc BG-3 (ROADMAP §3.66) — the gates every edition's words pass, and the calendar ahead.

A number no measurement holds and a sentence that claims a cause or a forecast may not be shown. Dates are dates,
never figures; a share declared as a ratio reads as a percentage. (Arc BG's own writer was retired by Arc BC — its
composed edition is tested in `test_briefing_compose_write.py`; these gates are what it passes.)
"""
from __future__ import annotations

from datetime import date

import pytest

from aughor.briefing import edition as E
from aughor.briefing import guide as G
from aughor.briefing import ranges
from aughor.briefing.compose.sources import Source
from aughor.briefing.compose.spec import allowed_numbers

OCT29 = date(2026, 10, 29)

ALLOWED = allowed_numbers({
    "sales": Source(id="sales", label="Sales", kind="check", columns=["start", "value", "this_range"],
                    rows=[["2026-10-19", 166988.0, True]], unit="EUR",
                    facts={"current": 166988.0, "previous": 158815.0, "rel": 0.05146, "n": 259,
                           "usual_mean": 160960.0, "usual_low": 149913.0, "usual_high": 172007.0, "usual_n": 8,
                           "extreme": {"which": "highest", "of": 13}}),
    "conv": Source(id="conv", label="Conversion", kind="check", columns=["start", "value", "this_range"],
                   rows=[["2026-10-19", 0.0205, True]], unit="ratio 0..1",
                   facts={"current": 0.0205, "previous": 0.0208, "streak": -3, "n": 9873}),
})


@pytest.mark.parametrize("text", [
    "Sales were €167.0k in the week of 19–25 October 2026.",
    "That is 5.1% more than the week before.",
    "2.05% of visits ended in an order, the third fall in a row.",
    "The highest of the 13 weeks read, on 259 orders.",
    "Inside its usual range of €149.9k to €172.0k.",
])
def test_a_measured_number_passes(text):
    assert E.unmeasured_numbers(text, ALLOWED) == []


@pytest.mark.parametrize("text,miss", [
    ("Sales were €190.0k.", "190.0k"),
    ("That is 12% more than the week before.", "12%"),
    ("About 21 more orders would have been placed.", "21"),
])
def test_a_number_nobody_measured_is_caught(text, miss):
    assert miss in " ".join(E.unmeasured_numbers(text, ALLOWED))


def test_a_cause_and_a_forecast_are_held_and_said():
    held = dict(E.held_sentences("Sales were €167.0k. Bigger baskets drove the week. Sales will rise next "
                                 "week. Visits held alongside fewer orders.", ALLOWED))
    assert "Sales were €167.0k." not in held
    assert "cause" in held["Bigger baskets drove the week."]
    assert "forecast" in held["Sales will rise next week."]
    assert "Visits held alongside fewer orders." not in held          # "alongside" describes, it claims nothing


def test_an_iso_day_is_a_date_not_a_figure():
    """"2026-04-30" lost its year to the year rule and read "30" as a figure: a true sentence withheld."""
    assert E.unmeasured_numbers("THE OUTNET has no orders after 2026-04-30.", ALLOWED) == []


def test_a_share_declared_as_a_ratio_reads_as_a_percentage_and_a_percent_keeps_its_sign():
    assert E._unit("ratio 0-1 (e-commerce typically 0.005-0.05)", [0.0205, 0.0217, None]) == "ratio 0..1"
    assert E._unit("ratio 0-1", [0.4, 1.7]) == "ratio 0-1"              # not a share when a value is past 1
    assert E._text(0.0205, "Session conversion", "ratio 0..1", "") == "2.05%"
    assert E._text(0.476, "Return rate", "ratio 0..1", "") == "47.6%"
    assert E._text(47.55, "Gross margin on items", "%", "").endswith("%")


def test_the_calendar_ahead_is_written_by_code():
    spec, _ = ranges.resolve_range("last_week", today=OCT29, lag_days=1, lag_source="learned")
    guide = G.BriefingGuide(calendar=[G.CalendarDay(name="Singles Day", when="11-11", source="calendar"),
                                      G.CalendarDay(name="Spring sale", when="03-20", source="data")])
    assert E.coming_up(guide, spec) == [{"name": "Singles Day", "date": "2026-11-11",
                                         "line": "Singles Day, Wednesday 11 November.", "source": "calendar"}]
