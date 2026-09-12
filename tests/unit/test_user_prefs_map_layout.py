"""ON-3b — the ontology map's arrangement is a per-user preference, not a per-browser one.

A person drags the cards on the ontology map where they want them; that has to follow them to their next browser
and their next machine, which is what `aughor/db/user_prefs.py` is for. This file holds the two things that makes
true: the value's shape is CHECKED on the way in (a preferences store with a closed key registry stops being one
the moment a key takes whatever a UI sends), and what goes in comes back out per user.
"""
from __future__ import annotations

import pytest

from aughor.db.user_prefs import ALLOWED_KEYS, MAX_CARDS, MAX_MAPS, get_preferences, set_preference

KEY = "ontology_map_layout"
LAYOUT = {"914df862:luxexperience": {"Order": {"x": 12, "y": -40.5}, "Product": {"x": 300, "y": 8}}}


def check(value):
    validator, _description = ALLOWED_KEYS[KEY]
    return validator(value)


def test_the_key_is_in_the_registry_and_says_what_it_is():
    assert KEY in ALLOWED_KEYS
    assert "ontology map" in ALLOWED_KEYS[KEY][1]
    assert KEY in get_preferences()["known_keys"]          # the 422's list, and the UI's


def test_a_position_comes_back_as_two_finite_numbers():
    assert check(LAYOUT) == {"914df862:luxexperience": {"Order": {"x": 12.0, "y": -40.5},
                                                        "Product": {"x": 300.0, "y": 8.0}}}
    assert check({}) == {}


@pytest.mark.parametrize("value, said", [
    ("nope", "must be an object of maps"),
    ({"c:s": "left a bit"}, "must map an object type"),
    ({"c:s": {"Order": {"x": "left", "y": 1}}}, "needs a numeric x and y"),
    ({"c:s": {"Order": {"x": 1}}}, "needs a numeric x and y"),
    ({"c:s": {"Order": {"x": float("inf"), "y": 1}}}, "needs a finite x and y"),
    ({"  ": {}}, "keyed by"),
    ({f"c{i}:s": {} for i in range(MAX_MAPS + 1)}, f"at most {MAX_MAPS} maps"),
    ({"c:s": {f"T{i}": {"x": 0, "y": 0} for i in range(MAX_CARDS + 1)}}, f"at most {MAX_CARDS} are kept"),
])
def test_what_the_store_refuses_rather_than_writing(value, said):
    with pytest.raises(ValueError) as exc:
        check(value)
    assert said in str(exc.value)


def test_the_arrangement_survives_the_round_trip():
    written = set_preference(KEY, LAYOUT)
    assert written["preferences"][KEY] == check(LAYOUT)
    assert get_preferences()["preferences"][KEY]["914df862:luxexperience"]["Order"] == {"x": 12.0, "y": -40.5}
    # a later drag replaces the whole map, so a card removed from the ontology does not linger
    set_preference(KEY, {"914df862:luxexperience": {"Order": {"x": 1, "y": 2}}})
    assert get_preferences()["preferences"][KEY] == {"914df862:luxexperience": {"Order": {"x": 1.0, "y": 2.0}}}


def test_a_typo_is_refused_by_name_rather_than_written_silently():
    with pytest.raises(ValueError) as exc:
        set_preference("ontology_map_layouts", LAYOUT)
    assert "unknown preference" in str(exc.value) and KEY in str(exc.value)
