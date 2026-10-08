"""The Briefing's switches are a per-person preference (the canvas, B1): which sections show, in
what order, and which cockpit rides with it. The value's shape is checked on the way in, as every
key of this closed registry is, and the registry's six ids are the web's six."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aughor.db.user_prefs import ALLOWED_KEYS, BRIEFING_SECTIONS, get_preferences

KEY = "briefing_sections"
WEB = Path(__file__).resolve().parents[2] / "web" / "lib" / "briefingSections.ts"


def check(value):
    validator, _description = ALLOWED_KEYS[KEY]
    return validator(value)


def test_the_key_is_in_the_registry_and_says_what_it_is():
    assert KEY in ALLOWED_KEYS
    assert "Briefing" in ALLOWED_KEYS[KEY][1] and "cockpit" in ALLOWED_KEYS[KEY][1]
    assert KEY in get_preferences()["known_keys"]


def test_every_section_once_in_the_kept_order_and_one_left_out_is_appended_shown():
    got = check({"sections": [{"id": "synthesis", "on": True}, {"id": "findings", "on": False}], "strip": "growth-review-1a2b"})
    assert [s["id"] for s in got["sections"]] == ["synthesis", "findings", "verdict", "key_metrics", "cockpit", "patterns"]
    assert [s["on"] for s in got["sections"]] == [True, False, True, True, True, True]
    assert got["strip"] == "growth-review-1a2b"
    assert check({})["sections"] == [{"id": s, "on": True} for s in BRIEFING_SECTIONS]
    assert check({"strip": None})["strip"] == ""


@pytest.mark.parametrize("value, said", [
    ("nope", "must be an object"),
    ({"sections": "findings"}, "must be a list"),
    ({"sections": [{"id": "footer"}]}, "each section is one of"),
    ({"sections": [{"id": "findings"}, {"id": "findings"}]}, "listed twice"),
    ({"strip": "Not An Id!"}, "id of one of your cockpits"),
])
def test_a_value_the_shape_refuses_is_said(value, said):
    with pytest.raises(ValueError, match=said):
        check(value)


def test_the_web_names_the_same_six_sections():
    ids = re.findall(r'\{ id: "([a-z_]+)", label:', WEB.read_text())
    assert tuple(ids) == BRIEFING_SECTIONS
