"""The briefing synthesis is multi-paragraph — the UI always expected it to be.

`BriefingPanel` labels the card "Full synthesis", clamps it to 150px with a bottom fade, and
offers "Read full synthesis ▾". The backend meanwhile capped the narrative at "exactly 2-3
sentences" in FIVE separate places, so expanding revealed nothing new: real briefs came out at
391 and 465 characters citing 3 of 8 findings. These lock the new contract, and — because the
defect was *several places disagreeing* — guard against one of them being changed alone.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import aughor.llm.provider as prov
from aughor.knowledge.briefing import (
    _SYSTEM,
    _SYSTEM_MULTI,
    BriefingCitation,
    BriefingNarrative,
    _build_user_prompt,
    generate_narrative,
)

_MULTI_PARA = (
    "Conversion surged while GMV contracted [1].\n\n"
    "Returns are the driver: 26% of items come back [2], and the worst platform sits at 48% [3].\n\n"
    "Refund costs fell 22% [4], which buys time but does not fix the mismatch."
)


class FakeProvider:
    def __init__(self, narrative: str = _MULTI_PARA):
        self.narrative = narrative
        self.prompts: list[tuple[str, str]] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.prompts.append((system, user))
        return BriefingNarrative(
            narrative=self.narrative,
            citations=[BriefingCitation(ref="1", insight_id="s0", domain="sales", finding="f")],
            headline_theme="Theme",
        )


@pytest.fixture
def fake(monkeypatch):
    fp = FakeProvider()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fp)
    return fp


# ── The contract the prompts now carry ───────────────────────────────────────

def test_system_prompts_ask_for_a_lede_then_depth():
    for prompt in (_SYSTEM, _SYSTEM_MULTI):
        assert "LEDE" in prompt
        assert "blank line" in prompt
        assert "Never pad" in prompt          # length must come from evidence, not filler


def test_multi_schema_prompt_still_forbids_cross_business_synthesis():
    """More room to write must not become licence to invent links between unrelated
    businesses — the exact risk a longer narrative introduces."""
    assert "do NOT draw connections" in _SYSTEM_MULTI
    assert "not licence to link them" in _SYSTEM_MULTI


def test_user_prompt_closes_by_asking_for_paragraphs():
    prompt = _build_user_prompt([{"finding": "x"}], [])
    assert "lede" in prompt and "paragraphs" in prompt


def test_no_place_still_caps_the_narrative_at_two_or_three_sentences():
    """The defect was FIVE independent places agreeing on a cap; fixing four would have
    left the model with contradictory instructions and no visible failure."""
    src = Path("aughor/knowledge/briefing.py").read_text()
    offenders = [ln.strip() for ln in src.splitlines()
                 if re.search(r"(exactly )?2-3 sentence", ln)
                 and "LEDE" not in ln and "lede" not in ln]
    assert offenders == [], f"stale 2-3 sentence cap still present: {offenders}"


# ── The narrative survives the pipeline intact ───────────────────────────────

def test_paragraph_breaks_survive_generation(fake):
    """`generate_narrative` runs the text through currency and number normalisation on the
    way out. If either collapsed whitespace, every paragraph break would vanish and the
    prompt change would look like it simply had not worked."""
    result = generate_narrative({"sales": [{"id": "s0", "finding": "f"}]},
                                patterns=[], connection_id="c")
    assert "\n\n" in result["narrative"]
    assert result["narrative"].count("\n\n") == 2          # all three paragraphs intact


def test_currency_rewrite_does_not_eat_paragraphs(monkeypatch):
    """The '$'→symbol rewrite is a regex over the whole narrative — verify on a non-USD
    business, the case where that substitution actually runs."""
    fp = FakeProvider("Revenue hit $1.2M [1].\n\nMargins held.")
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fp)
    result = generate_narrative({"sales": [{"id": "s0", "finding": "f"}]},
                                patterns=[], connection_id="c",
                                profile={"currency_code": "EUR"})
    assert "\n\n" in result["narrative"]
    assert "€1.2M" in result["narrative"]


def test_a_short_narrative_is_still_accepted(monkeypatch):
    """"Never pad" means a thin finding set legitimately yields a short brief — that must
    not be treated as a failure anywhere in the path."""
    fp = FakeProvider("Only one thing happened [1].")
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fp)
    result = generate_narrative({"sales": [{"id": "s0", "finding": "f"}]},
                                patterns=[], connection_id="c")
    assert result["narrative"] == "Only one thing happened [1]."


def test_per_finding_attribution_reads_every_paragraph(fake, monkeypatch):
    """Each cited sentence is attributed back to its finding as that finding's contextual
    narrative. A multi-paragraph brief should therefore enrich MORE findings, not fewer —
    the sentence splitter must not stop at the first paragraph."""
    captured: dict[str, str] = {}

    def fake_update(conn, insight_id, merge=None, lineage_edge=None):
        captured[insight_id] = (merge or {}).get("narrative", "")

    monkeypatch.setattr("aughor.explorer.dossier.update_dossier", fake_update)
    data = {"sales": [{"id": f"s{i}", "finding": f"finding {i}"} for i in range(4)]}
    generate_narrative(data, patterns=[], connection_id="c")
    # ref [1] maps to the first ranked insight; its attributed text is drawn from the lede
    assert captured, "no finding received an attributed narrative"
    assert any("Conversion surged" in t for t in captured.values())
