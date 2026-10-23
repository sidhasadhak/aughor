"""Data that cannot be reached is said of the DATA, never as a metric waiting on a person (2026-10-23).

LuxExperience's Postgres was down. The range measurement said so as one row under not-measured, named
"headline metrics"; the Dashboard counted it as "1 approved metric can't be measured for a period" and offered
"Set their dates". The user read it as a metric still to review, approved Repeat Purchase Rate in the Semantic
Layer to clear it (04:16 UTC), came back — the Postgres still down — and found the same row: "it does not
refresh". Nothing was stale; an outage was dressed as a metric.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from aughor.briefing import ranges


@contextmanager
def _down():
    raise ConnectionRefusedError("connection to server at localhost port 5555 failed")
    yield  # pragma: no cover


def _spec():
    spec, _ = ranges.resolve_range("last_month", today=date(2026, 10, 23), lag_days=1)
    return spec


def test_the_cockpit_door_says_the_data_could_not_be_reached_and_names_no_metric():
    out = ranges.measured_block("c", _spec(), runner=_down)
    assert out["measured"] == [] and out["unmeasured"] == [], out["unmeasured"]
    assert out.get("unreachable") == "the connection could not be opened (ConnectionRefusedError)"


def test_the_narrator_and_the_sent_edition_say_it_of_the_data():
    from aughor.knowledge.period_brief import period_note

    block = {**ranges.range_block(_spec()), "unreachable": "the connection could not be opened (OperationalError)"}
    note = period_note(block, today=date(2026, 10, 23))
    assert "The data could not be reached for this month (the connection could not be opened (OperationalError))" in note
    assert "State no figure" in note and "Not measured for this" not in note
    sections = dict(ranges.sheet_lines({"period": block}))
    assert sections["unmeasured"] == [
        "Nothing was measured: the data could not be reached — the connection could not be opened (OperationalError)."]
