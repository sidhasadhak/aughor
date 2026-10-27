"""Which figures sit on a person's Briefing front, and which they hide, per dataset (the user, 2026-10-26: "how can a
user choose what appears in the briefing and what not?"). A per-person preference beside the Briefing's switches; the
value's shape is checked on the way in, and the front's limit is the web's."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aughor.db.user_prefs import ALLOWED_KEYS, BRIEFING_FRONT_MAX, get_preferences

KEY = "briefing_figures"
WEB = Path(__file__).resolve().parents[2] / "web" / "lib" / "briefingFigures.ts"


def check(value):
    validator, _description = ALLOWED_KEYS[KEY]
    return validator(value)


def test_the_key_is_in_the_registry_and_says_what_it_is():
    assert "front" in ALLOWED_KEYS[KEY][1] and "hide" in ALLOWED_KEYS[KEY][1]
    assert KEY in get_preferences()["known_keys"]


def test_a_choice_per_dataset_is_kept_in_its_order_and_an_empty_one_dropped():
    got = check({"dcc63d83:luxexperience": {"front": ["gmv", "net_revenue_eur", "gmv"], "hidden": ["item_gross_margin_pct"]},
                 "8233e4fd": {"front": [], "hidden": []}})
    assert got == {"dcc63d83:luxexperience": {"front": ["gmv", "net_revenue_eur"], "hidden": ["item_gross_margin_pct"]}}


@pytest.mark.parametrize("value, said", [
    ("nope", "must be an object"),
    ({"c": "gmv"}, "must be an object with 'front' and 'hidden'"),
    ({"c": {"front": "gmv"}}, "list of metric names"),
    ({"c": {"front": [f"m{i}" for i in range(BRIEFING_FRONT_MAX + 1)]}}, f"at most {BRIEFING_FRONT_MAX}"),
    ({"c": {"front": ["gmv"], "hidden": ["gmv"]}}, "not both"),
])
def test_a_value_the_shape_refuses_is_said(value, said):
    with pytest.raises(ValueError, match=said):
        check(value)


def test_the_web_holds_the_same_front():
    assert re.search(rf"export const FRONT_MAX = {BRIEFING_FRONT_MAX};", WEB.read_text())
