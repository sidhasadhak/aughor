"""Canonical time helpers — see aughor/util/time.py (consolidated from ~13 modules)."""
from datetime import datetime, timedelta, timezone

from aughor.util.time import now_iso, now_iso_z, age_hours


def test_now_iso_is_aware_offset():
    s = now_iso()
    assert "T" in s and s.endswith("+00:00")


def test_now_iso_z_uses_z_suffix():
    s = now_iso_z()
    assert s.endswith("Z") and "+00:00" not in s


def test_age_hours_recent_is_near_zero():
    assert age_hours(now_iso()) < 0.01
    assert age_hours(now_iso_z()) < 0.01


def test_age_hours_naive_string_treated_as_utc():
    past = (datetime.now(timezone.utc) - timedelta(hours=5)).replace(tzinfo=None).isoformat()
    assert 4.9 < age_hours(past) < 5.1


def test_age_hours_bad_input_returns_sentinel():
    assert age_hours("not-a-date") == 9999.0
    assert age_hours("") == 9999.0
