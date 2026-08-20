"""A question that asks to SEE the data is not a comparison that failed.

Live, on an airline canvas. "Give me route wise number of flights" run deep produced:

    Data unavailable — flight count could not be analyzed
    … as no prior period exists in the current dataset to facilitate a comparative
      analysis …
    N/A · Available history (2024-06-01 → 2024-06-07, ~7 days) vs No prior period
      exists in the data
    BOTTOM LINE … future analysis will require a broader historical dataset

Every one of those sentences is about a comparison the question never asked for. The
deep path is built around "why did X change", so a listing fell through it and came out
framed as a failure to do something nobody requested.
"""
from __future__ import annotations

import pytest

from aughor.agent.investigate import _is_descriptive_question


@pytest.mark.parametrize("q", [
    "Give me route wise number of flights",
    "show me revenue by region",
    "number of orders per customer",
    "breakdown of sales by channel",
    "how many flights by carrier",
    "what are the totals by month",
    # No dimension, and still a request to see the data. Requiring one was the
    # conservative first cut; a sweep of question shapes found these falling through to
    # the change frame and earning a report about a comparison nobody asked for.
    "what is the average order value",
    "how many flights are there",
    "what is the total revenue",
])
def test_a_request_to_see_the_data_is_descriptive(q):
    assert _is_descriptive_question(q)


@pytest.mark.parametrize("q, why", [
    ("why did revenue drop in November", "a cause question"),
    ("what drove the change in traffic by region", "a cause question WITH a dimension"),
    ("which route is weakest", "a diagnostic — it has its own route"),
    ("where are we losing money by segment", "a diagnostic WITH a dimension"),
    ("why did Direkteingabe traffic move in August", "the specimen question"),
    ("compare November to October by region", "an explicit comparison"),
    ("what is the reason revenue dropped", "opens like a lookup, asks for a cause"),
    ("how many orders did we lose", "a count question about a loss"),
    ("show me why sales declined", "a listing verb over a cause question"),
])
def test_the_routes_that_already_exist_keep_their_framing(q, why):
    """The two established routes must not be swallowed: a movement and a weakness are
    still what they were."""
    assert not _is_descriptive_question(q), why


def test_the_verdict_is_stamped_on_the_spec():
    """It must reach the report, not just be computable — that is the whole seam."""
    from aughor.agent.prompts_investigate import IntakeOutput
    assert IntakeOutput.model_fields["descriptive_only"].default is False


def test_a_descriptive_report_carries_no_comparison_basis():
    """"vs No prior period exists in the data" under a breakdown is an answer to an
    unasked question — the same reason a cross-sectional run blanks it."""
    from aughor.agent.investigate import _comparison_basis
    assert _comparison_basis({"descriptive_only": True,
                              "comparison_label": "No prior period exists in the data"}) == ""
    # …and a run that DID compare still says what against.
    assert _comparison_basis({"comparison_label": "October 2024 (MoM)"}) == "October 2024 (MoM)"
    # The cross-sectional case it shares the rule with is unchanged.
    assert _comparison_basis({"cross_sectional": True, "comparison_label": "x"}) == ""


# ── how the run is framed to the narrator ────────────────────────────────────

def test_a_descriptive_run_is_told_to_describe():
    from aughor.agent.investigate import _framing_note

    note = _framing_note({"descriptive_only": True, "no_prior_period": True})

    assert note.lstrip().startswith("DESCRIPTIVE REQUEST")
    # It FORBIDS the apology rather than issuing it. The phrase "a longer history"
    # appears in both notes — the difference is the verb, so assert on that: the CA-0
    # note instructs the narrator to say it, this one instructs it not to.
    assert "Do NOT discuss prior periods" in note
    assert "Say in the executive summary that no prior period exists" not in note
    assert "Do NOT frame the answer as a limitation" in note


def test_no_prior_period_still_says_so_when_the_question_asked_about_change():
    """The CA-0 note is right for a change question and must survive: a comparison that
    cannot be made has to be stated."""
    from aughor.agent.investigate import _framing_note

    note = _framing_note({"no_prior_period": True,
                          "observation_start": "2024-06-01", "observation_end": "2024-06-07"})

    assert note.lstrip().startswith("NO PRIOR PERIOD")
    assert "no prior period exists" in note.lower()
    assert "2024-06-01" in note


def test_descriptive_wins_over_no_prior_period():
    """A listing over a single-span dataset hits BOTH conditions. Ordering is the whole
    fix: told to lament the missing period, the narrator apologises over the breakdown
    it was actually asked for."""
    from aughor.agent.investigate import _framing_note

    note = _framing_note({"descriptive_only": True, "no_prior_period": True,
                          "observation_start": "2024-06-01", "observation_end": "2024-06-07"})

    assert "NO PRIOR PERIOD:" not in note


def test_an_ordinary_change_run_gets_no_extra_framing():
    from aughor.agent.investigate import _framing_note
    assert _framing_note({"comparison_label": "October 2024 (MoM)"}) == ""


def test_a_weakness_scan_is_not_asked_to_lament_a_missing_period():
    """A "which is weakest" scan compares dimensions, not periods — a missing prior
    period is as irrelevant to it as to a listing. Found by sweeping the question shapes
    rather than from a screenshot; it had been shipping the apology all along."""
    from aughor.agent.investigate import _framing_note

    assert _framing_note({"cross_sectional": True, "no_prior_period": True,
                          "observation_start": "2024-06-01",
                          "observation_end": "2024-06-07"}) == ""
