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
