"""The house style for Settings → System's flag copy (the text-density pilot, 2026-10-10).

Before it, the 23 flag descriptions ran a median of 96 words, and 17 flags also showed their
disposition note in full — 1,247 words citing ROADMAP sections, arc ids, decision dates and a
function name. About 3,000 words on one tab, written for the engineer who built each flag
rather than the person deciding whether to turn it on. These checks keep the copy in the
three layers `FLAG_META` declares: a label, a summary of at most two short sentences, facts
drawn as chips, and plain details that end by saying what Off means.
"""
from __future__ import annotations

import re

import pytest

from aughor.kernel.flags import FLAG_ENV, FLAG_META

FACT_KINDS = {"model", "free", "schedule", "sends", "warehouse", "needs", "private", "route"}

#: What an engineer writes and a person deciding cannot use. Each pattern names one kind.
INTERNAL = {
    "route": r"(?:^|[\s(])/[a-z]|\b(?:GET|POST|PUT|DELETE|PATCH)\s",
    "roadmap": r"ROADMAP|§",
    "arc or wave id": r"\b(?:Arc|Wave|Stage|Phase)\s+[A-Z0-9]|\b[A-Z]{2,3}-\d",
    "code name": r"\b[a-z]+_[a-z_]+\b|`",
    "decision date": r"\b20\d\d-\d\d-\d\d\b|(?i:the user's call)",
    "engineer's promise": r"(?i)exactly as (?:today|before)",
}


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _words(text: str) -> int:
    return len(text.split())


def _copy(meta: dict) -> list[str]:
    return [meta.get("label", ""), meta.get("summary", ""), meta.get("description", "")] + [
        f.get("text", "") for f in meta.get("facts", [])
    ]


@pytest.mark.parametrize("name", sorted(FLAG_ENV))
def test_every_flag_has_the_three_layers(name):
    meta = FLAG_META.get(name)
    assert meta, f"{name} has no Settings copy"
    assert meta.get("label") and _words(meta["label"]) <= 9, f"{name}: label missing or long"
    assert meta.get("summary"), f"{name}: no summary"
    assert meta.get("facts"), f"{name}: no facts — what does it cost or touch?"
    assert "Off:" in meta.get("description", ""), f"{name}: details never say what Off means"


@pytest.mark.parametrize("name", sorted(FLAG_ENV))
def test_the_summary_is_two_short_sentences(name):
    sentences = _sentences(FLAG_META[name]["summary"])
    assert len(sentences) <= 2, f"{name}: {len(sentences)} sentences in the summary"
    long = [s for s in sentences if _words(s) > 20]
    assert not long, f"{name}: summary sentence over 20 words: {long}"


@pytest.mark.parametrize("name", sorted(FLAG_ENV))
def test_details_stay_plain_and_short(name):
    text = FLAG_META[name]["description"]
    assert _words(text) <= 70, f"{name}: details run {_words(text)} words"
    long = [s for s in _sentences(text) if _words(s) > 25]
    assert not long, f"{name}: details sentence over 25 words: {long}"


@pytest.mark.parametrize("name", sorted(FLAG_ENV))
def test_facts_are_chips(name):
    facts = FLAG_META[name]["facts"]
    assert len(facts) <= 3, f"{name}: {len(facts)} facts — a chip row, not a list"
    for f in facts:
        assert f.get("kind") in FACT_KINDS, f"{name}: unknown fact kind {f.get('kind')!r}"
        assert _words(f.get("text", "")) <= 6, f"{name}: fact too long: {f.get('text')!r}"


@pytest.mark.parametrize("name", sorted(FLAG_ENV))
def test_no_engineering_names_reach_the_reader(name):
    hits = {
        kind: m.group(0)
        for part in _copy(FLAG_META[name])
        for kind, pattern in INTERNAL.items()
        if (m := re.search(pattern, part))
    }
    assert not hits, f"{name}: {hits}"
