"""The briefing's full-coverage digest — a DETERMINISTIC per-domain listing.

When more findings exist than the cited top-8, ``_coverage_digest`` lists the remainder per domain
so the narrator sees the whole picture. This was an LLM tree-reduce; on a real brief it spent ~5
model calls compressing 1,291 characters for a narrator with a 32k+ window — and on a throttled
free tier the digest alone exhausted the allowance, so the brief died before the narrator ran.
These assert the drop-detection, that the top-N are not repeated, per-domain isolation, that the
caps count rather than silently drop, the prompt wiring, and above all that NO LLM is involved.
"""
from __future__ import annotations

import pytest

import aughor.llm.provider as prov
from aughor.knowledge.briefing import (
    BriefingCitation,
    BriefingNarrative,
    _build_user_prompt,
    _coverage_digest,
    generate_narrative,
)


class FakeProvider:
    """Counts every call, so a digest that quietly reaches for the LLM fails the test."""

    def __init__(self):
        self.calls: list[str] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.calls.append(user)
        return BriefingNarrative(
            narrative="Synthesis [1].",
            citations=[BriefingCitation(ref="1", insight_id="s0", domain="sales", finding="f")],
            headline_theme="Theme",
        )


@pytest.fixture
def fake(monkeypatch):
    fp = FakeProvider()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fp)
    return fp


def _domain(prefix: str, n: int) -> list[dict]:
    return [{"id": f"{prefix}{i}", "finding": f"{prefix} finding {i}", "novelty": float(n - i)}
            for i in range(n)]


def test_no_digest_when_everything_was_cited():
    data = {"sales": _domain("s", 2)}
    assert _coverage_digest(data, cited_ids={"s0", "s1"}) == ""


def test_digest_costs_no_llm_calls(fake):
    """The whole point of the change: breadth without a model call."""
    _coverage_digest({"sales": _domain("s", 6), "support": _domain("p", 5)}, cited_ids=set())
    assert fake.calls == []


def test_digest_lists_the_uncited_findings_verbatim():
    data = {"sales": _domain("s", 3)}
    out = _coverage_digest(data, cited_ids={"s0"})
    assert "sales:" in out
    assert "s finding 1" in out and "s finding 2" in out   # the uncited ones, in full
    assert "s finding 0" not in out                        # already in the prompt above — not repeated


def test_digest_covers_every_domain():
    data = {"sales": _domain("s", 6), "support": _domain("p", 5)}
    out = _coverage_digest(data, cited_ids={f"s{i}" for i in range(3)})
    assert "sales:" in out and "support:" in out


def test_digest_never_blends_domains():
    """A domain's block must carry only its own findings."""
    data = {"sales": _domain("s", 4), "support": _domain("p", 4)}
    out = _coverage_digest(data, cited_ids=set())
    blocks = out.split("support:")
    assert "p finding" not in blocks[0]                    # the sales block stays clean


def test_a_domain_with_no_uncited_findings_is_omitted():
    data = {"sales": _domain("s", 2), "support": _domain("p", 2)}
    out = _coverage_digest(data, cited_ids={"s0", "s1"})   # sales fully cited
    assert "sales:" not in out and "support:" in out


def test_per_domain_cap_counts_the_tail_instead_of_dropping_it():
    """A silent truncation reads as 'that was everything'. The count keeps it honest."""
    out = _coverage_digest({"sales": _domain("s", 20)}, cited_ids=set())
    assert "+8 further findings" in out                     # 20 listed-capped at 12


def test_char_budget_is_enforced_and_reported():
    big = [{"id": f"b{i}", "finding": "x" * 500} for i in range(40)]
    out = _coverage_digest({"sales": big}, cited_ids=set())
    assert len(out) < 6000                                  # bounded well under a prompt blowout
    assert "further findings" in out                        # and says so


def test_digest_is_empty_rather_than_raising_on_odd_input():
    assert _coverage_digest({}, cited_ids=set()) == ""
    assert _coverage_digest({"sales": [{"id": "s0"}]}, cited_ids=set()) == ""   # no finding text


def test_build_user_prompt_includes_digest():
    prompt = _build_user_prompt([{"finding": "x"}], [], coverage_digest="sales:\n  - all good")
    assert "FULL COVERAGE" in prompt
    assert "all good" in prompt


def test_build_user_prompt_omits_digest_when_empty():
    prompt = _build_user_prompt([{"finding": "x"}], [], coverage_digest="")
    assert "FULL COVERAGE" not in prompt


def test_generate_narrative_makes_exactly_one_llm_call(fake):
    """14 findings used to mean ~5 digest calls + 1 narrator call. Now: just the narrator."""
    data = {"sales": _domain("s", 7), "support": _domain("p", 7)}
    result = generate_narrative(data, patterns=[], connection_id="c")
    assert result["narrative"] == "Synthesis [1]."
    assert len(fake.calls) == 1
    assert "FULL COVERAGE" in fake.calls[0]                  # and it still carried the breadth
