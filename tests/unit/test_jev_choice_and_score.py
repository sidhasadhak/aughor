"""CP-1 — Choice and Score reach the hosted binding, which answered noul only.

The seam has typed all three primitives since JD-1; `jev.py` accepted one, because the
banded cascade asked for one. Arc CP's treatment judgement needs a Choice (which treatment
this ask earns) and Scores (how specific, how many steps, what stakes), so the binding
grows to meet the types that were already there.

Nothing guarded the old restriction — "noul bundles only" lived in a docstring and an `if`,
and no test asserted it — so these are the first guards this surface has had.

What they pin:

* the WIRE is per-primitive: `criteria` is a MAP for a choice and an ORDERED LIST for a
  score, and the two are not interchangeable — a list sent for a choice loses the keys its
  answer comes back under;
* a winning key OUTSIDE the declared set is refused. Schema-constrained output is the
  vendor's claim, not our guarantee, and this is the one place a violation is silent: an
  unrecognised option assigned into `value` travels on as though a caller had a branch for it;
* a Score's `value` is read from the DISTRIBUTION, not by rounding the vendor's float, so it
  is derived exactly as the house backend derives it and the two cannot disagree about what
  "the level" is — while the continuous position is kept, because the guidance for a score is
  to threshold it and never round it.
"""
from __future__ import annotations

from aughor.judgment.jev import JevJudge
from aughor.judgment.seam import CHOICE, NOUL, SCORE, Choice, Noul, Score

TREATMENT = Choice(id="treatment", question="How much work does this ask earn?",
                   options=("lookup", "single_query", "multi_query", "investigation"))
STAKES = Score(id="stakes", question="How much does being wrong cost?",
               levels=("private_thread", "team_channel", "scheduled_post"))


def _judge(answers: dict):
    """A JevJudge whose transport returns `answers` and records what was sent."""
    sent = []

    def post(url, body, headers):
        sent.append(body)
        return {"model": "jev-test", "usage": {}, "answers": answers}
    return JevJudge("k", "jev-test", post=post), sent


# ── the wire ─────────────────────────────────────────────────────────────────────────────

def test_a_choice_sends_a_criteria_MAP_and_a_score_sends_an_ORDERED_LIST():
    """The shapes are not interchangeable. A choice's answer comes back keyed by the option,
    so the request must carry those keys; a score's levels are ordered, so its criteria are a
    sequence and their ORDER is the scale."""
    j, sent = _judge({})
    j.judge("an ask", [TREATMENT, STAKES])
    qs = sent[0]["questions"]
    assert qs["treatment"]["type"] == "choice"
    assert qs["treatment"]["criteria"] == {o: o for o in TREATMENT.options}
    assert qs["stakes"]["type"] == "score"
    assert qs["stakes"]["criteria"] == list(STAKES.levels), "order IS the scale"


def test_a_mixed_bundle_goes_in_one_call():
    """Latency scales with tokens, not question count — so the treatment judgement asks
    everything at once rather than paying a round trip per lever."""
    j, sent = _judge({})
    j.judge("an ask", [Noul(id="causal", proposition="Does it ask why?"), TREATMENT, STAKES])
    assert len(sent) == 1
    assert set(sent[0]["questions"]) == {"causal", "treatment", "stakes"}
    assert [sent[0]["questions"][k]["type"] for k in ("causal", "treatment", "stakes")] == \
        ["noul", "choice", "score"]


# ── choice ───────────────────────────────────────────────────────────────────────────────

def test_a_choice_round_trips_with_its_distribution():
    j, _ = _judge({"treatment": {"type": "choice", "choice": "multi_query", "confidence": 0.6,
                                 "probabilities": {"lookup": 0.1, "single_query": 0.2,
                                                   "multi_query": 0.6, "investigation": 0.1}}})
    a = j.judge("an ask", [TREATMENT])["treatment"]
    assert a.available and a.kind == CHOICE and a.value == "multi_query"
    assert a.probability == 0.6
    assert set(a.distribution) == set(TREATMENT.options)
    assert abs(sum(a.distribution.values()) - 1.0) < 1e-9
    assert a.score is None, "a choice has no ordered position"


def test_a_key_outside_the_closed_set_is_REFUSED():
    """The guard that matters most. `deep_research` is not one of our four; accepting it
    would hand a caller a treatment its own routing has no branch for."""
    j, _ = _judge({"treatment": {"type": "choice", "choice": "deep_research",
                                 "probabilities": {"deep_research": 1.0}}})
    a = j.judge("an ask", [TREATMENT])["treatment"]
    assert not a.available
    assert "deep_research" in a.reason and a.value is None


def test_weights_against_undeclared_names_are_dropped_not_folded_in():
    """Renormalising an unknown name's mass INTO the declared set would silently inflate
    whichever option happened to be adjacent in the response."""
    j, _ = _judge({"treatment": {"type": "choice", "choice": "lookup",
                                 "probabilities": {"lookup": 0.5, "single_query": 0.5,
                                                   "telepathy": 99.0}}})
    a = j.judge("an ask", [TREATMENT])["treatment"]
    assert set(a.distribution) == {"lookup", "single_query"}
    assert abs(a.distribution["lookup"] - 0.5) < 1e-9


# ── score ────────────────────────────────────────────────────────────────────────────────

def test_a_score_keeps_the_continuous_position_and_reads_its_level_from_the_distribution():
    """1.4 means "between team_channel and scheduled_post, nearer team_channel", which the
    level name cannot say. `value` still comes from the distribution, so it is the same
    derivation the house backend uses."""
    j, _ = _judge({"stakes": {"type": "score", "score": 1.4,
                              "probabilities": {"private_thread": 0.1, "team_channel": 0.5,
                                                "scheduled_post": 0.4}}})
    a = j.judge("an ask", [STAKES])["stakes"]
    assert a.available and a.kind == SCORE
    assert a.value == "team_channel"
    assert a.score == 1.4


def test_a_missing_or_impossible_score_falls_back_to_weighting_the_distribution():
    """Not an unavailable answer: the level probabilities are present and usable, and the
    fallback is the exact number the house backend would have produced from them."""
    j, _ = _judge({"stakes": {"type": "score", "score": 99.0,
                              "probabilities": {"private_thread": 0.0, "team_channel": 0.0,
                                                "scheduled_post": 1.0}}})
    a = j.judge("an ask", [STAKES])["stakes"]
    assert a.available and a.value == "scheduled_post"
    assert a.score == 2.0, "weighted position of the top level in a 3-level scale"


def test_a_score_with_no_usable_probabilities_is_unavailable_with_its_reason():
    j, _ = _judge({"stakes": {"type": "score", "score": 1.0, "probabilities": {}}})
    a = j.judge("an ask", [STAKES])["stakes"]
    assert not a.available and "stakes" in a.reason


# ── the seam's promise survives ──────────────────────────────────────────────────────────

def test_an_unavailable_answer_carries_its_OWN_kind():
    """A refused bundle used to report every question as a noul, because that was the only
    kind this backend knew. A caller branching on `kind` would have mis-read a choice."""
    def boom(url, body, headers):
        raise RuntimeError("network down")
    j = JevJudge("k", "jev-test", post=boom)
    out = j.judge("an ask", [TREATMENT, STAKES, Noul(id="n", proposition="p")])
    assert [out[k].kind for k in ("treatment", "stakes", "n")] == [CHOICE, SCORE, NOUL]
    assert all(not a.available and a.reason for a in out.values())
