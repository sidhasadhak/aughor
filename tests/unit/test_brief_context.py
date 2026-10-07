"""Grounding "Ask this briefing" in the brief the user is looking at.

The old ask box sent five hand-assembled lines (theme + headline + three findings) up to a
DEEP investigation. This builds the block SERVER-SIDE from the same `conn:schema` cache entry
the Briefing rendered, so the answer is grounded in exactly what is on screen, can't drift
from it, and can't be spoofed into the prompt by a caller.

Two properties matter: it is BOUNDED (this rides in front of a quick answer), and it is EMPTY
when there is no brief — no context beats invented context.
"""
from __future__ import annotations

import json

import pytest

from aughor.knowledge.brief_context import (
    MAX_CITATIONS,
    MAX_FINDING_CHARS,
    MAX_NARRATIVE_CHARS,
    build_brief_block,
    brief_block_for_scope,
)

BRIEF = {
    "narrative": "Paid search closes the majority of orders regardless of first touch [1].",
    "headline_theme": "Paid Search Dominance and Margin Risk",
    "citations": [
        {"ref": "1", "domain": "Marketing", "finding": "Paid search closes 3,704 direct-first orders."},
        {"ref": "2", "domain": "Finance", "finding": "Womenswear is the largest cost driver at 24,508,769."},
    ],
}


def test_block_carries_verdict_synthesis_and_findings():
    out = build_brief_block(BRIEF)
    assert "Paid Search Dominance and Margin Risk" in out
    assert "closes the majority of orders" in out
    assert "3,704 direct-first orders" in out
    assert "[Marketing]" in out


def test_block_says_it_is_context_not_a_source_of_numbers():
    """The brief's figures must not be quoted as this answer's figures — the answer's numbers
    come from the query that runs. The instruction is the guard."""
    out = build_brief_block(BRIEF).lower()
    assert "context" in out
    assert "must still come from the query" in out


def test_no_brief_is_an_empty_block_not_a_fabricated_one():
    for empty in (None, {}, {"narrative": "", "headline_theme": "", "citations": []}, "not a dict"):
        assert build_brief_block(empty) == ""


def test_citations_are_capped():
    brief = {**BRIEF, "citations": [
        {"ref": str(i), "domain": "D", "finding": f"finding {i}"} for i in range(30)
    ]}
    out = build_brief_block(brief)
    assert out.count("  - ") == MAX_CITATIONS


def test_long_finding_and_narrative_are_truncated():
    brief = {
        "headline_theme": "T",
        "narrative": "n" * (MAX_NARRATIVE_CHARS + 500),
        "citations": [{"ref": "1", "domain": "D", "finding": "f" * (MAX_FINDING_CHARS + 500)}],
    }
    out = build_brief_block(brief)
    assert "…" in out
    assert len(out) < MAX_NARRATIVE_CHARS + MAX_FINDING_CHARS + 1000


def test_malformed_citations_are_skipped_not_crashed():
    brief = {**BRIEF, "citations": ["not a dict", {}, {"finding": ""}, {"finding": "kept"}]}
    out = build_brief_block(brief)
    assert "kept" in out
    assert out.count("  - ") == 1


# ── Scope resolution ──────────────────────────────────────────────────────────


@pytest.fixture
def _cache(tmp_path, monkeypatch):
    path = tmp_path / "briefing_cache.json"
    monkeypatch.setattr("aughor.knowledge.briefing._CACHE_PATH", path)
    return path


def test_scope_key_matches_the_briefing_route(_cache):
    """Must mirror the route's stamp exactly, or the ask grounds itself in a DIFFERENT
    schema's brief — the cross-schema class of bug this arc already fixed once."""
    _cache.write_text(json.dumps({
        "workspace:netflix": {**BRIEF, "headline_theme": "Netflix theme"},
        "workspace:luxexperience": {**BRIEF, "headline_theme": "Lux theme"},
        "workspace": {**BRIEF, "headline_theme": "Connection theme"},
        "canvas:c1": {**BRIEF, "headline_theme": "Canvas theme"},
    }))
    assert "Netflix theme" in brief_block_for_scope("workspace", "netflix")
    assert "Lux theme" in brief_block_for_scope("workspace", "luxexperience")
    assert "Connection theme" in brief_block_for_scope("workspace", None)
    assert "Canvas theme" in brief_block_for_scope("workspace", "netflix", canvas_id="c1")


def test_unknown_scope_grounds_in_nothing(_cache):
    _cache.write_text(json.dumps({"workspace:netflix": BRIEF}))
    assert brief_block_for_scope("workspace", "nope") == ""


def test_missing_cache_file_is_survivable(_cache):
    assert brief_block_for_scope("workspace", "netflix") == ""


def test_corrupt_cache_is_survivable(_cache):
    _cache.write_text("{not json")
    assert brief_block_for_scope("workspace", "netflix") == ""


def test_peek_never_generates(_cache, monkeypatch):
    """`get_briefing` synthesizes on a miss (an LLM call + a coverage fan-out). The read-side
    consumer must never trigger that."""
    from aughor.knowledge import briefing

    def _boom(*a, **k):
        raise AssertionError("peek_briefing must not generate a narrative")

    monkeypatch.setattr(briefing, "generate_narrative", _boom)
    _cache.write_text(json.dumps({}))
    assert briefing.peek_briefing("workspace:netflix") is None


# ── The range Briefing on screen (2026-10-07) ─────────────────────────────────
# A range Briefing is cached under `<scope>#<period key>`. The ask read only `<scope>`, so on
# `workspace:uber_ncr` — which held range entries and no standing one — it grounded in
# nothing, and it never said which period the user was looking at.

AUGUST = {
    "headline_theme": "Active Customer Count Exceeds Thresholds",
    "narrative": "During August 2026 the active customer count passed its warning threshold.",
    "citations": [{"ref": "1", "domain": "Alerts", "finding": "The Active Customer Count alert fired."}],
    "period": {
        "key": "range:last_month:2026-08-01..2026-08-31", "label": "Monthly",
        "covers": "August 2026", "compared_with": "July 2026",
        "start": "2026-08-01", "end": "2026-09-01", "as_of": "2026-10-06", "lag_days": 12,
        "still_moving": ["rides"],
        "measured": [{"name": "Gross bookings", "current": 1250.5, "previous": 1000.0,
                      "rel": 0.2505, "status": "settled"}],
        "unmeasured": [{"name": "Ride Completion Rate",
                        "reason": "no approved definition; approve one in the Semantic Layer"}],
    },
}
AUGUST_KEY = "range:last_month:2026-08-01..2026-08-31"


def test_the_open_period_is_read_from_its_own_entry(_cache):
    _cache.write_text(json.dumps({
        "workspace:uber_ncr": {**BRIEF, "headline_theme": "Standing theme"},
        f"workspace:uber_ncr#{AUGUST_KEY}": AUGUST,
    }))
    block = brief_block_for_scope("workspace", "uber_ncr", period_key=AUGUST_KEY)
    assert "Active Customer Count Exceeds Thresholds" in block
    assert "Standing theme" not in block
    # The standing entry is still what an ask with no period reads — unchanged.
    assert "Standing theme" in brief_block_for_scope("workspace", "uber_ncr")


def test_the_period_is_said_with_its_comparison_and_settling(_cache):
    _cache.write_text(json.dumps({f"workspace:uber_ncr#{AUGUST_KEY}": AUGUST}))
    block = brief_block_for_scope("workspace", "uber_ncr", period_key=AUGUST_KEY)
    assert "PERIOD: the monthly Briefing for August 2026, compared with July 2026" in block
    assert "2026-08-01 up to but not including 2026-09-01" in block
    assert "newest 12 days of data are not settled yet" in block
    assert "STILL MOVING" in block and "rides" in block


def test_measured_and_unmeasured_figures_ride_the_block(_cache):
    _cache.write_text(json.dumps({f"workspace:uber_ncr#{AUGUST_KEY}": AUGUST}))
    block = brief_block_for_scope("workspace", "uber_ncr", period_key=AUGUST_KEY)
    assert "Gross bookings: 1,250.5 (previous period 1,000, +25.1%) [settled]" in block
    assert "NOT MEASURED FOR THIS PERIOD" in block and "Ride Completion Rate" in block


def test_an_open_period_with_no_briefing_is_said_not_filled(_cache):
    _cache.write_text(json.dumps({"workspace:uber_ncr": BRIEF}))
    block = brief_block_for_scope("workspace", "uber_ncr", period_key=AUGUST_KEY)
    assert "has not been built for the period" in block
    assert BRIEF["headline_theme"] not in block


def test_a_period_key_that_is_not_a_range_key_is_never_read(_cache):
    """The key is joined into a cache key; anything but a range key falls back to the scope."""
    _cache.write_text(json.dumps({
        "workspace:uber_ncr": {**BRIEF, "headline_theme": "Standing theme"},
        "workspace:uber_ncr#../other": {**BRIEF, "headline_theme": "Walked"},
    }))
    block = brief_block_for_scope("workspace", "uber_ncr", period_key="../other")
    assert "Walked" not in block and "Standing theme" in block


def test_a_quiet_period_still_says_its_window(_cache):
    quiet = {"narrative": "", "citations": [], "period": {**AUGUST["period"], "measured": []}}
    _cache.write_text(json.dumps({f"workspace:uber_ncr#{AUGUST_KEY}": quiet}))
    block = brief_block_for_scope("workspace", "uber_ncr", period_key=AUGUST_KEY)
    assert "August 2026" in block
    assert "No narrative was written for this period" in block


def test_key_metric_tiles_are_described_only_when_asked_from_the_briefing(_cache, monkeypatch):
    from aughor.business_profile import store as pstore
    from aughor.business_profile.models import NorthStarMetric

    class _Profile:
        north_star_metrics = [
            NorthStarMetric(name="Ride Completion Rate", definition="d", maps_to="rides.status",
                            why_it_matters="w", unit_or_range="percent 0-100",
                            value_sql="SELECT AVG(CASE WHEN status='Completed' THEN 1 ELSE 0 END) FROM rides"),
            NorthStarMetric(name="No SQL", definition="d", maps_to="m", why_it_matters="w",
                            unit_or_range="u"),
        ]

    monkeypatch.setattr(pstore, "load", lambda conn, schema: _Profile())
    _cache.write_text(json.dumps({f"workspace:uber_ncr#{AUGUST_KEY}": AUGUST}))
    on_page = brief_block_for_scope("workspace", "uber_ncr", period_key=AUGUST_KEY, from_briefing=True)
    assert "KEY METRICS ON THE PAGE" in on_page
    assert "Ride Completion Rate: SELECT AVG(CASE WHEN status='Completed'" in on_page
    assert "No SQL" not in on_page
    elsewhere = brief_block_for_scope("workspace", "uber_ncr", period_key=AUGUST_KEY)
    assert "KEY METRICS" not in elsewhere


def test_a_standing_brief_renders_exactly_as_before():
    """Every quick answer in a scope with a cached brief carries this block; the period work
    must not change it by a byte when there is no period."""
    assert build_brief_block(BRIEF) == (
        "THE BRIEFING THE USER IS LOOKING AT — the question is most likely ABOUT this.\n"
        "Use it to resolve references ('that', 'the drop', 'those brands') and to stay on the\n"
        "same entities and time window. It is CONTEXT, not a source of numbers: every figure\n"
        "in your answer must still come from the query you run.\n"
        "\n"
        "VERDICT: Paid Search Dominance and Margin Risk\n"
        "SYNTHESIS: Paid search closes the majority of orders regardless of first touch [1].\n"
        "FINDINGS IT CITES:\n"
        "  - [Marketing] Paid search closes 3,704 direct-first orders.\n"
        "  - [Finance] Womenswear is the largest cost driver at 24,508,769.\n"
    )
