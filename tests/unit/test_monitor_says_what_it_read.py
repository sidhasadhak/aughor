"""A monitor's check says what it read, whether or not it fired (the Olist study, Gap 36, 2026-10-22).

"Monthly GMV floor" warned below R$900,000. August 2018 read R$848,860 — below the line — yet the check said
"No condition met", and whether it had read August, the month after, or the all-time R$13.49M was never shown.
A check now keeps the value it read and says it beside the line it is judged against; an alert prints a plain
number, never "1.349e+07".
"""
from types import SimpleNamespace

import pytest

from aughor.monitors import runner
from aughor.monitors.models import Monitor


def _db(value):
    return SimpleNamespace(scalar=lambda sql, **k: value)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(runner, "_last_alert_value", lambda mid: None)
    monkeypatch.setattr(runner, "_guard_caveats", lambda m, db: None)


def _floor(**kw):
    return Monitor(conn_id="workspace", name="Monthly GMV floor", custom_sql="SELECT SUM(price) FROM items",
                   alert_on="threshold_cross", threshold_direction="below", warning_threshold=900_000.0, **kw)


def test_a_check_that_raises_nothing_still_says_what_it_read():
    run = runner.check_monitor(_floor(), _db(13_494_400.74), suppress=False)
    assert run.alert is None and run.reading == 13_494_400.74
    assert runner.reading_words(_floor(), run) == "read 13,494,400.74 (warning below 900,000)"


def test_an_alert_prints_plain_numbers_and_the_reading_rides_beside_it():
    run = runner.check_monitor(_floor(), _db(848_860.1), suppress=False)
    assert run.alert is not None and run.alert.severity == "warning"
    assert "848,860.1 below warning threshold 900,000" in run.alert.message and "e+0" not in run.alert.message
    assert runner.reading_words(_floor(), run) == "read 848,860.1 (warning below 900,000)"


def test_a_check_that_read_nothing_says_nothing_rather_than_a_number():
    run = runner.check_monitor(_floor(), _db(None), suppress=False)
    assert run.reading is None and runner.reading_words(_floor(), run) == ""
