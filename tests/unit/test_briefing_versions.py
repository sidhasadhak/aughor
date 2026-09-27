"""A Briefing is kept as of the day it was built (Arc BR-6).

Before this, nothing stored a built Briefing at all — `build_period_briefing` returned it to
the page and to the sender, and neither wrote it down, so the platform could not say what it
had told someone or that it had changed.
"""
from __future__ import annotations

import pytest

from aughor.briefing import versions


def _brief(**metrics) -> dict:
    """A built Briefing, reduced to the part that is compared: its measured figures."""
    return {"narrative": "prose that varies between runs over identical rows",
            "measured": [{"name": n, "current": v, "unit": ""} for n, v in metrics.items()]}


@pytest.fixture
def key():
    return {"scope_key": "8233e4fd", "range_key": "2026-08-01..2026-08-31", "recipe": "month"}


def test_the_first_reading_is_version_one(key):
    out = versions.record("c1", _brief(return_rate=10.0), **key)
    assert out["kept"] is True
    assert out["version"] == 1
    assert [r["what"] for r in out["revisions"]] == ["first measured"]


def test_the_same_figures_again_write_nothing(key):
    """The standing view is re-POSTed on every mount; opening a Briefing twice in a minute
    must not leave two versions, and the as-of belongs to the day the figures are FROM."""
    first = versions.record("c2", _brief(return_rate=10.0), **key)
    again = versions.record("c2", _brief(return_rate=10.0), **key)

    assert again["kept"] is False
    assert again["version"] == first["version"] == 1
    assert len(versions.history("c2", **key)) == 1


def test_a_figure_that_moves_enough_becomes_a_new_version(key):
    versions.record("c3", _brief(return_rate=10.0), **key)
    out = versions.record("c3", _brief(return_rate=12.0), **key)   # +20%, well over the band

    assert out["kept"] is True and out["version"] == 2
    moved = [r for r in out["revisions"] if r["what"] == "moved"]
    assert [m["name"] for m in moved] == ["return_rate"]
    assert moved[0]["from"] == 10.0 and moved[0]["to"] == 12.0


def test_a_move_under_the_noise_band_is_not_news(key):
    """5% is the platform's own bar for two readings of one number — imported from the
    departure gate, not re-declared here, so the two can never drift apart."""
    from aughor.govern.departure import NOISE_REL

    versions.record("c4", _brief(return_rate=10.0), **key)
    out = versions.record("c4", _brief(return_rate=10.0 * (1 + NOISE_REL / 2)), **key)

    assert out["kept"] is False
    assert len(versions.history("c4", **key)) == 1


def test_the_earlier_version_survives_the_later_one(key):
    """THE mutation test §3.48 names: overwrite instead of supersede and this fails."""
    versions.record("c5", _brief(return_rate=10.0), **key)
    versions.record("c5", _brief(return_rate=12.0), **key)

    rows = versions.history("c5", **key)
    assert len(rows) == 2, "a new version must supersede the old one, never replace it"
    assert sorted(int(r["version"]) for r in rows) == [1, 2]
    older = [r for r in rows if int(r["version"]) == 1][0]
    assert older["superseded_by"], "version 1 must point at what replaced it"
    assert versions.figures(older["payload"]["briefing"]) == {"return_rate": 10.0}


def test_the_narrative_is_not_what_is_compared(key):
    """The prose is model-written and differs between runs over identical rows. Digesting it
    would make every visit a revision and the history meaningless."""
    versions.record("c6", _brief(return_rate=10.0), **key)
    same_numbers = _brief(return_rate=10.0)
    same_numbers["narrative"] = "an entirely different sentence about the same rows"

    assert versions.record("c6", same_numbers, **key)["kept"] is False


def test_two_recipes_over_one_range_are_two_briefings(key):
    """BR-4 gives each horizon its own recipe; the Day and the Week over the same days are
    two Briefings, not two versions of one."""
    day = {**key, "recipe": "day"}
    week = {**key, "recipe": "week"}
    versions.record("c7", _brief(return_rate=10.0), **day)
    versions.record("c7", _brief(return_rate=99.0), **week)

    assert len(versions.history("c7", **day)) == 1
    assert len(versions.history("c7", **week)) == 1


def test_the_page_says_as_of_and_only_says_revised_when_it_was(key):
    first = versions.record("c8", _brief(return_rate=10.0), **key, as_of="2026-09-15T08:00:00Z")
    assert versions.as_of_line(first) == "as of 2026-09-15"

    revised = versions.record("c8", _brief(return_rate=12.0), **key, as_of="2026-10-12T08:00:00Z")
    assert versions.as_of_line(revised) == "as of 2026-09-15 · revised 2026-10-12"


def test_a_metric_that_stops_being_measured_is_a_revision(key):
    versions.record("c9", _brief(return_rate=10.0, margin=51.9), **key)
    out = versions.record("c9", _brief(return_rate=10.0), **key)

    assert out["kept"] is True
    assert [(r["name"], r["what"]) for r in out["revisions"]] == [("margin", "no longer measured")]


def test_the_real_briefing_shape_is_what_is_read(key):
    """Caught before it shipped: a built Briefing keeps its figures at
    `brief["period"]["measured"]` — `sheet_lines`, the reader that turns a brief into the lines
    a send departs with, reads that path. Reading the top level alone returned `{}` for every
    real Briefing, so nothing ever differed and version 1 would have stood forever."""
    built = {"narrative": "…", "period": {"label": "Month",
                                          "measured": [{"name": "return_rate", "current": 10.0}]}}
    assert versions.figures(built) == {"return_rate": 10.0}

    versions.record("c10", built, **key)
    moved = {"narrative": "…", "period": {"label": "Month",
                                          "measured": [{"name": "return_rate", "current": 12.0}]}}
    out = versions.record("c10", moved, **key)
    assert out["kept"] is True and out["version"] == 2
