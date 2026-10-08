"""A play is offered for a thing it is ABOUT, not for a word it shares with it (2026-10-09).

Eight citations of one Briefing carried the same play — "Concentration risk up, churn_rate up:
investigate top customers…" — under findings about repeat purchase rate, sell-through and delivery
lead time. The retriever scored a one-word overlap with a play's recommendation text at half a
point, then added two for the play's learned success rate whatever the fit, so one proven play
beat every relevant one. ``fit`` asks that the play name the thing: every word of its trigger
metric's name, or every word of one of its tags. Measured on theLook's 50 findings: 35 carried a
play before, three plays between them, and a first cut that took two tag words across two tags
still paired "Overall return rate" with blended CAC on "customer" + "overall".
"""
from __future__ import annotations

import pytest

from aughor.playbook import retriever as R
from aughor.playbook.models import PlaybookEntry


def _play(pid: str, metric: str, rec: str, rate: float, tags: list[str] = ()) -> PlaybookEntry:
    return PlaybookEntry(id=pid, trigger_metric=metric, trigger_condition=f"{metric} up", recommendation=rec,
                         historical_success_rate=rate, status="active", tags=list(tags))


PROVEN = _play("p-conc", "concentration_risk",
               "investigate top customers are volatile — likely over-reliance on key accounts in that order to identify the root cause",
               rate=0.9)
FITTING = _play("p-repeat", "repeat_purchase_rate", "read the second-order cohort against the first; check the promotion calendar", rate=0.0)
CAC = _play("p-cac", "mkt_blended_cac", "look at paid social first", rate=0.7,
            tags=["blended CAC", "overall CAC", "customer acquisition cost", "what is my CAC"])
RETURNS = _play("p-returns", "ec_return_rate", "read returns by category against the promotion calendar", rate=0.3,
                tags=["return rate", "returns"])


@pytest.fixture
def plays(monkeypatch):
    monkeypatch.setattr(R, "list_active_entries", lambda: [PROVEN, FITTING, CAC, RETURNS])
    monkeypatch.setattr("aughor.packs.industry_choice.readable_industries", lambda scope: None)


def test_without_a_fit_the_proven_play_wins_on_one_shared_word(plays):
    """The defect, kept as a measurement: "order" in the finding's angle meets "in that order" in the
    play's text, and the learned rate carries it. Every other caller keeps this reading."""
    got = R.retrieve_for_metric_and_phases(["Key Questions", "order status distribution"], limit=1)
    assert [p.id for p in got] == ["p-conc"]


def test_with_a_fit_a_play_must_name_the_thing_in_full(plays):
    assert R.retrieve_for_metric_and_phases(["Key Questions", "order status distribution"], limit=1, fit=True) == []
    # theLook's "Overall return rate" finding (measures: count; domain: Customer) is about returns, not CAC:
    # "customer" in one tag and "overall" in another are not a name.
    got = R.retrieve_for_metric_and_phases(["count", "Overall return rate", "Customer"], limit=1, fit=True)
    assert [p.id for p in got] == ["p-returns"]
    # One word of a trigger metric is not the metric: "cost" in "total inventory cost" is not CAC.
    assert R.retrieve_for_metric_and_phases(["cost", "Cost concentration by product category", "Catalog"], limit=1, fit=True) == []
    # The name in full, however it is spelled: snake_case, spaced, or the tag's words.
    assert [p.id for p in R.retrieve_for_metric_and_phases(["repeat_purchase_rate"], limit=1, fit=True)] == ["p-repeat"]
    assert [p.id for p in R.retrieve_for_metric_and_phases(["repeat purchase rate fell"], limit=1, fit=True)] == ["p-repeat"]
    assert [p.id for p in R.retrieve_for_metric_and_phases(["customer acquisition cost up"], limit=1, fit=True)] == ["p-cac"]
    assert [p.id for p in R.retrieve_for_metric_and_phases(["blended CAC"], limit=1, fit=True)] == ["p-cac"]


def test_fit_is_read_on_whole_names_and_relevance_before_any_boost():
    assert R.metric_words("mkt_blended_cac") == {"blended", "cac"}
    assert R.words("what is my CAC") == {"cac"}
    assert R.fits(PROVEN, R.words("order status distribution")) is False
    assert R.fits(FITTING, R.words("Repeat Purchase Rate")) is True
    assert R.fits(FITTING, R.words("repeat rate")) is False                   # "purchase" is missing
    assert R.fits(_play("p-rate", "rate", "x", 0.0), R.words("return rate")) is False   # a name of generic words names nothing
    # The pairings theLook's findings were handed under looser rules, each refused by the whole name.
    assert R.fits(_play("p-mix", "ec_new_vs_returning", "x", 0.0, tags=["customer mix"]), R.words("Average age by gender Customer")) is False
    assert R.fits(_play("p-cpm", "mkt_cpm", "x", 0.0, tags=["price per 1000"]), R.words("Retail-price breakdown by department")) is False
    assert R.fits(_play("p-cat", "ec_revenue_by_category", "x", 0.0, tags=["category breakdown"]), R.words("Cost concentration by product category")) is False
    assert R.fits(_play("p-cm", "fin_contribution_margin", "x", 0.0, tags=["how much per user"]), R.words("User demographics")) is False
    # "total revenue" is generic words only: every revenue finding would be handed the GMV play.
    assert R.fits(_play("p-gmv", "ec_gmv", "x", 0.0, tags=["total revenue"]), R.words("Total revenue generation")) is False
    assert R.fits(_play("p-gmv", "ec_gmv", "x", 0.0, tags=["total revenue"]), R.words("GMV by month")) is True
    assert R._relevance(PROVEN, {"order"}) == R.WORD_HIT
    assert R._relevance(FITTING, {"repeat_purchase_rate"}) == R.METRIC_HIT
    assert R._score(PROVEN, {"nothing"}) == 0.0                                # no overlap: no boost either
