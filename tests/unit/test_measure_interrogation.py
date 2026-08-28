"""Spend is not loss — the measure substitution guard.

The intake prompt's INTENT GUARD admits "cost or spend" as a valid financial measure. That is
right for a COST question and wrong for a LOSS one, so `SUM(inventory_items.cost)` satisfied it
and two different vendors' models, asked "Where are we losing money?", both answered with a
ranking of where the business SPENDS most.

The result is worse than merely unhelpful: it is inverted. The department that spends the most is
the LARGEST department, so the shipped report headlined the most productive part of the business
as the place value was being destroyed — under a title that read "Men department accounts for over
half of total cost", with the actual loss ($1.06M of returns, $1.61M of cancellations) computed in
a later phase and never surfaced.

`_spend_measured_as_loss` is the deterministic backstop for when the model ignores the LOSS GUARD.
It ANNOTATES rather than rewrites: silently swapping the metric under the reader would be a second
substitution, which is the failure being guarded.
"""
from __future__ import annotations

import pytest

from aughor.agent.investigate import _is_loss_question, _spend_measured_as_loss

LOSS_Q = "Where are we losing money?"


@pytest.mark.parametrize("metric_sql", [
    "SUM(inventory_items.cost)",     # the observed failure, verbatim
    "SUM(ii.cost)",
    "SUM(cost)",
    "SUM(cogs)",
    "SUM(total_expense)",
])
def test_a_bare_spend_total_is_flagged_for_a_loss_question(metric_sql):
    assert _spend_measured_as_loss(LOSS_Q, metric_sql)


@pytest.mark.parametrize("metric_sql", [
    "SUM(sale_price - cost)",                                          # margin — can go negative
    "SUM(CASE WHEN status IN ('Returned','Cancelled') THEN sale_price END)",   # reversals
    "SUM(refund_amount)",                                              # an explicit loss column
    "SUM(write_off_amount)",
])
def test_a_real_loss_measure_is_not_flagged(metric_sql):
    """The guard must stay silent on every reading the LOSS GUARD actually asks for — otherwise it
    fires on the fix and trains the reader to ignore it."""
    assert not _spend_measured_as_loss(LOSS_Q, metric_sql)


@pytest.mark.parametrize("question", [
    "Where is our cost highest?",
    "What are we spending most on?",
    "Which category has the highest COGS?",
])
def test_a_cost_question_may_legitimately_use_a_spend_total(question):
    """The substitution is only wrong when the question asked about LOSS. Asked about cost, a cost
    metric is the correct answer and must not be second-guessed."""
    assert not _spend_measured_as_loss(question, "SUM(inventory_items.cost)")


def test_loss_vocabulary_is_recognised_beyond_the_exact_phrase():
    for q in ("where is the leakage?", "which region is bleeding?",
              "where are we wasting money", "biggest write-offs by category"):
        assert _is_loss_question(q), q
    for q in ("what is our revenue by region?", "how many orders shipped late?"):
        assert not _is_loss_question(q), q
