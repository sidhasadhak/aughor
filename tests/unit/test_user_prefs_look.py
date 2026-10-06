"""The look — accent, grey, radius, scaling — is a per-person preference (ROADMAP §6 item 44).

The web hands these four to Radix Themes; the store keeps them so a person's look follows them to
another browser. Two things are held here: each key admits Radix's own values and nothing else, and
the lists are the same ones `web/lib/lookValues.ts` spells — a value the web offers and the store refuses
would be a choice that silently does not stick.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from aughor.db import user_prefs
from aughor.db.user_prefs import ALLOWED_KEYS, get_preferences, set_preference

LOOK = {"accent": user_prefs.LOOK_ACCENTS, "grey": user_prefs.LOOK_GREYS,
        "radius": user_prefs.LOOK_RADII, "scaling": user_prefs.LOOK_SCALINGS}
WEB = Path(__file__).resolve().parents[2] / "web" / "lib" / "lookValues.ts"


@pytest.mark.parametrize("key", sorted(LOOK))
def test_each_knob_is_a_known_key_that_takes_its_own_values_only(key):
    assert key in get_preferences()["known_keys"]
    validator, said = ALLOWED_KEYS[key]
    assert said
    for value in LOOK[key]:
        assert validator(value) == value
    with pytest.raises(ValueError, match="must be one of"):
        validator("chartreuse")


def test_a_look_comes_back_as_it_was_set():
    for key, value in (("accent", "teal"), ("grey", "sage"), ("radius", "small"), ("scaling", "95%")):
        set_preference(key, value)
    kept = get_preferences()["preferences"]
    assert {k: kept[k] for k in LOOK} == {"accent": "teal", "grey": "sage", "radius": "small", "scaling": "95%"}


@pytest.mark.parametrize("key, name", [("accent", "ACCENTS"), ("grey", "GREYS"), ("radius", "RADII"), ("scaling", "SCALINGS")])
def test_the_web_offers_exactly_what_the_store_admits(key, name):
    source = WEB.read_text()
    block = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.S)
    assert block, f"{name} is not declared in web/lib/lookValues.ts"
    offered = tuple(re.findall(r'"([^"]+)"', block.group(1)))
    assert offered == LOOK[key]
