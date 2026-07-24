"""E4c — the perturbation-brittleness axis (`aughor/evals/perturb.py`).

The comparison is the easy half (a deterministic result-set comparator this repo already
trusts). The dangerous half is the perturbation SET: a rewording that changes meaning turns a
correct answer into a recorded defect, so the first tests below are about the perturbations
themselves rather than about the machinery that applies them.

The second theme is the difference between *unmeasured* and *maximally brittle*. A case whose
unperturbed run errored has no answer for a rewording to differ from — scoring it 0.0 would
let a broken baseline masquerade as a fragile one, which is the same mistake `fidelity` avoids
by treating an unmeasured axis as absent rather than zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from aughor.evals.perturb import (
    DEFAULT_PERTURBATIONS,
    Perturbation,
    brittleness,
    suite_robustness,
)


@dataclass
class _Case:
    id: str = "c1"
    question: str = "What is total revenue by region?"


@dataclass
class _Obs:
    rows: list = field(default_factory=list)
    error: str = ""
    sql: str = ""


def _target(mapping: dict, default):
    """A target that answers per-question, so a test can make one rewording misbehave."""
    def target(case):
        return mapping.get(case.question, default)
    return target


# ── the perturbation set itself ───────────────────────────────────────────────

def test_every_default_perturbation_declares_why_it_preserves_meaning():
    """The rationale is not decoration — it is the only thing standing between this axis and
    a false brittleness report."""
    for p in DEFAULT_PERTURBATIONS:
        assert p.rationale.strip(), p.name
        assert len(p.rationale) > 40, f"{p.name}: state the argument, not a label"


def test_no_default_perturbation_alters_the_words_of_the_question():
    """Capitalisation, spacing, terminal punctuation and a courtesy wrapper only. A synonym
    substitution or a reordered clause could change what was asked."""
    q = "What is total revenue by region in 2024?"
    significant = {"total", "revenue", "region", "2024"}
    for p in DEFAULT_PERTURBATIONS:
        words = set(p(q).lower().replace("?", "").split())
        assert significant <= words, f"{p.name} dropped or altered a meaningful token"


def test_perturbations_are_deterministic():
    q = "How many orders shipped late?"
    for p in DEFAULT_PERTURBATIONS:
        assert p(q) == p(q)


def test_the_default_set_covers_both_punctuation_directions():
    """Otherwise brittleness would be an artefact of how the case happened to be authored."""
    names = {p.name for p in DEFAULT_PERTURBATIONS}
    assert {"trailing_punctuation", "question_mark"} <= names


# ── measurement ───────────────────────────────────────────────────────────────

def test_a_stable_pipeline_scores_one():
    rows = [[1, "eu"], [2, "us"]]
    b = brittleness(_Case(), _target({}, _Obs(rows=rows)))
    assert b.measurable is True
    assert b.drifted == 0
    assert b.score == 1.0
    assert b.total >= 4


def test_a_rewording_that_changes_the_result_set_is_drift():
    case = _Case()
    stable = _Obs(rows=[[1]])
    drifted = _Obs(rows=[[999]])
    target = _target({case.question.lower(): drifted}, stable)

    b = brittleness(case, target)
    assert b.drifted == 1
    assert b.score == pytest.approx(1 - 1 / b.total)
    assert any(d.get("drifted") for d in b.details if d.get("perturbation") == "lowercase")


def test_a_rewording_that_breaks_the_pipeline_counts_as_drift():
    """The answer changed from rows to no answer — the largest change available."""
    case = _Case()
    target = _target({case.question.lower(): _Obs(error="binder error: no such column")},
                     _Obs(rows=[[1]]))
    b = brittleness(case, target)
    assert b.drifted == 1
    assert b.errored == 1


def test_a_rewording_that_raises_counts_as_drift_not_a_crash():
    case = _Case()

    def target(c):
        if c.question != case.question:
            raise RuntimeError("pipeline exploded")
        return _Obs(rows=[[1]])

    b = brittleness(case, target)
    assert b.measurable is True
    assert b.drifted == b.total
    assert b.score == 0.0


# ── unmeasured is not brittle ─────────────────────────────────────────────────

def test_a_case_whose_baseline_errored_is_unmeasured_not_brittle():
    b = brittleness(_Case(), _target({}, _Obs(error="table not found")))
    assert b.measurable is False
    assert b.score is None
    assert "Unmeasured, not brittle" in b.reason


def test_a_case_whose_baseline_raised_is_unmeasured():
    def target(_):
        raise RuntimeError("boom")
    b = brittleness(_Case(), target)
    assert b.measurable is False
    assert b.score is None


def test_a_sql_only_case_has_no_question_to_reword():
    b = brittleness(_Case(question="  "), _target({}, _Obs(rows=[[1]])))
    assert b.measurable is False
    assert "nothing to reword" in b.reason


def test_a_no_op_rewording_does_not_inflate_the_score():
    """`lowercase` on an already-lowercase question changes nothing, and counting it as a
    survived perturbation would make a robustness score depend on the case's capitalisation."""
    lower_case_q = _Case(question="what is total revenue by region")
    b = brittleness(lower_case_q, _target({}, _Obs(rows=[[1]])))
    skipped = [d for d in b.details if d.get("skipped")]
    assert skipped, "the no-op must be recorded as skipped"
    assert b.total == len([d for d in b.details if not d.get("skipped")])


def test_an_unrewritable_case_is_skipped_not_scored_as_survived():
    """The dangerous fallback: handing back the ORIGINAL case would re-run the baseline
    question and count the identical result as a perturbation that survived, inflating
    robustness on exactly the unusual case shapes where the rewriting failed."""
    class _Frozen:
        id = "f1"
        question = "What is revenue?"

        def __setattr__(self, *_):           # refuses any rewriting
            raise AttributeError("frozen")

    b = brittleness(_Frozen(), _target({}, _Obs(rows=[[1]])))
    assert b.total == 0
    assert b.score is None, "no perturbation applied ⇒ unmeasured, not perfect"
    assert all(d.get("skipped") for d in b.details)


def test_the_original_case_is_never_mutated():
    case = _Case()
    original = case.question
    brittleness(case, _target({}, _Obs(rows=[[1]])))
    assert case.question == original


# ── suite aggregation ─────────────────────────────────────────────────────────

def test_suite_robustness_averages_only_the_measurable_cases():
    good, broken = _Case(id="a"), _Case(id="b", question="Which region is worst?")

    def target(c):
        if c.question.startswith("Which region"):
            return _Obs(error="unmeasurable")
        return _Obs(rows=[[1]])

    mean, detail = suite_robustness([good, broken], target)
    assert mean == 1.0                                  # the broken case is excluded, not 0
    assert [d.measurable for d in detail] == [True, False]


def test_an_axis_nobody_could_measure_is_none_not_zero():
    mean, _ = suite_robustness([_Case()], _target({}, _Obs(error="down")))
    assert mean is None


def test_a_custom_perturbation_set_is_honoured():
    shout = Perturbation("shout", lambda q: q.upper(), "x" * 50)
    b = brittleness(_Case(), _target({}, _Obs(rows=[[1]])), perturbations=[shout])
    assert b.total == 1
    assert b.details[0]["perturbation"] == "shout"
