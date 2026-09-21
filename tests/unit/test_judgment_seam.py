"""JD-1 — the judgment seam, driven through the faux backend: no credentials, no model call.

What each test pins, and how it could otherwise pass for the wrong reason:

* a bundle is ONE call, counted at the provider — the claim the seam exists to make;
* the schema is CLOSED — a response that names an option outside the set fails validation and
  comes back unavailable, not as a plausible string;
* a failed call makes every answer unavailable WITH its reason, and never raises.
"""
from __future__ import annotations

import pytest

from aughor.judgment.seam import (
    CHOICE, NOUL, SCORE, Answer, Choice, Noul, Score, agreement, judge,
)
from aughor.llm.faux import set_responses
from aughor.llm.provider import LLMProvider


@pytest.fixture
def provider():
    return LLMProvider(backend="faux", role="coder")


BUNDLE = [
    Noul("is_seasonal", "Revenue is lower in winter."),
    Choice("grain", "At what grain is this metric defined?", ("order", "item")),
    Score("severity", "How severe is the drop?", ("low", "medium", "high")),
]


def test_a_bundle_is_answered_in_one_call(provider, monkeypatch):
    calls = []
    real = provider.complete
    monkeypatch.setattr(provider, "complete",
                        lambda **kw: (calls.append(kw), real(**kw))[1])
    set_responses([{"is_seasonal": 0.8,
                    "grain": {"p0": 0.3, "p1": 0.7},
                    "severity": {"p0": 0.1, "p1": 0.2, "p2": 0.7}}])
    out = judge("Q3 revenue fell 12%.", BUNDLE, provider=provider)
    assert len(calls) == 1, "three questions must be one call"
    assert set(out) == {"is_seasonal", "grain", "severity"}


def test_each_kind_reads_back_its_value_and_a_normalised_distribution(provider):
    set_responses([{"is_seasonal": 0.2,
                    # Valid probabilities that do NOT sum to 1 — what normalising is for. (Each
                    # one is capped at 1; a first draft sent 3.0 and the schema rightly refused it.)
                    "grain": {"p0": 0.6, "p1": 0.2},
                    "severity": {"p0": 0.1, "p1": 0.6, "p2": 0.3}}])
    out = judge("state", BUNDLE, provider=provider)

    noul = out["is_seasonal"]
    assert noul.kind == NOUL and noul.value is False and noul.probability == pytest.approx(0.8)

    grain = out["grain"]
    assert grain.kind == CHOICE and grain.value == "order"
    assert grain.distribution == {"order": pytest.approx(0.75), "item": pytest.approx(0.25)}
    assert grain.probability == pytest.approx(0.75)

    sev = out["severity"]
    assert sev.kind == SCORE and sev.value == "medium"
    assert sum(sev.distribution.values()) == pytest.approx(1.0)


def test_the_schema_is_closed_so_an_invented_option_is_refused_not_passed_through(provider):
    """The model answering a choice with free text instead of a probability per listed option
    fails validation at the provider. It must come back UNAVAILABLE — a plausible string
    reaching the caller is the exact failure a closed schema exists to stop."""
    set_responses([{"is_seasonal": 0.5, "grain": "line_item",
                    "severity": {"p0": 1, "p1": 0, "p2": 0}}])
    out = judge("state", BUNDLE, provider=provider)
    assert all(not a.available for a in out.values())
    assert all("failed" in a.reason for a in out.values())
    assert all(a.value is None for a in out.values())


def test_a_failed_call_is_every_answer_unavailable_and_never_a_raise(provider, monkeypatch):
    def boom(**kw):
        raise RuntimeError("provider down")
    monkeypatch.setattr(provider, "complete", boom)
    out = judge("state", BUNDLE, provider=provider)
    assert {a.id for a in out.values()} == {"is_seasonal", "grain", "severity"}
    assert all(not a.available and "provider down" in a.reason for a in out.values())


def test_all_zero_probabilities_are_no_answer_rather_than_the_first_option(provider):
    """Without this, `max` over an all-zero distribution would silently return the first
    option — a confident answer from nothing."""
    set_responses([{"is_seasonal": 0.5, "grain": {"p0": 0, "p1": 0},
                    "severity": {"p0": 0, "p1": 1, "p2": 0}}])
    out = judge("state", BUNDLE, provider=provider)
    assert out["grain"].available is False and "zero" in out["grain"].reason
    assert out["severity"].available is True


def test_misuse_raises_but_an_empty_bundle_is_simply_empty(provider):
    with pytest.raises(ValueError, match="unique"):
        judge("s", [Noul("a", "x"), Noul("a", "y")], provider=provider)
    with pytest.raises(ValueError, match="identifiers"):
        judge("s", [Noul("my-q", "x")], provider=provider)
    assert judge("s", [], provider=provider) == {}


def test_questions_refuse_shapes_the_schema_could_not_express():
    with pytest.raises(ValueError, match="at least two"):
        Choice("c", "q", ("only",))
    with pytest.raises(ValueError, match="2-10"):
        Score("s", "q", ("one",))
    with pytest.raises(ValueError, match="distinct"):
        Choice("c", "q", ("a", "a"))


def test_an_answer_cannot_be_silently_empty():
    with pytest.raises(ValueError, match="carry its reason"):
        Answer("x", NOUL, False)
    with pytest.raises(ValueError, match="carry its probability"):
        Answer("x", NOUL, True, value=True)


def test_agreement_counts_an_unanswered_question_separately_from_a_disagreement():
    """JD-1's receipt. An unavailable answer is not a wrong one: folding it into the
    disagreements would make a flaky call look like a different opinion."""
    seam = {
        "a": Answer("a", CHOICE, True, value="order", probability=0.9),
        "b": Answer("b", CHOICE, True, value="item", probability=0.6),
        "c": Answer("c", CHOICE, False, reason="the judgment call failed: timeout"),
    }
    r = agreement({"a": "order", "b": "order", "c": "order"}, seam)
    assert r["compared"] == 3 and r["answered"] == 2 and r["unanswered"] == 1
    assert r["agreed"] == 1 and r["agreement"] == pytest.approx(0.5)
    assert r["disagreements"] == {"b": {"today": "order", "seam": "item"}}
    assert agreement({"a": "x"}, {"a": seam["c"]})["agreement"] is None
