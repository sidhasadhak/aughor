"""Every entry of a Briefing's synthesis stands on a query a reader can open.

The user, 2026-10-11, on luxexperience's Full synthesis: its first sentence — web session conversion "fallen from 100%
to 31%" — opened as "Confidence 0%" and "— no query recorded —", and "no full synthesis entry should be without an
evidence backing it". The cited finding was a metric's move: it had its query, but the citation dropped it, and the
Briefing's own list never held it, so the page opened a stand-in. Three other candidates carried no query at all.
"""
from __future__ import annotations

import re

import pytest

import aughor.llm.provider as prov
from aughor.knowledge.briefing import BriefingCitation, BriefingNarrative, generate_narrative

MOVE_SQL = "SELECT day, SUM(converted) * 1.0 / COUNT(*) FROM web_sessions GROUP BY day ORDER BY day"


def _cite(ref: str) -> BriefingCitation:
    """A narrator's citation of [ref]: what it echoes besides the number is never read."""
    return BriefingCitation(ref=ref, insight_id=f"x{ref}", domain="d", finding="f")


class CitesEverything:
    """A narrator that cites every numbered finding it was given — so a test sees exactly what it could cite."""

    def __init__(self):
        self.users: list[str] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.users.append(user)
        refs = re.findall(r"^\[(\d+)\]", user, flags=re.M)
        return BriefingNarrative(
            narrative=" ".join(f"Claim [{r}]." for r in refs), headline_theme="t",
            citations=[_cite(r) for r in refs])


@pytest.fixture
def narrator(monkeypatch):
    fake = CitesEverything()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: fake)
    return fake


def test_a_cited_metric_move_carries_its_query_confidence_and_novelty(narrator):
    move = {"id": "metric-move::web_session_conversion_rate", "angle": "Trend", "metric_move": True,
            "finding": "Web Session Conversion Rate has fallen from 100% to 31% (-69%) over the period.",
            "sql": MOVE_SQL, "confidence": 0.8, "novelty": 3}
    out = generate_narrative({"Key Metrics": [move]}, [], "c1")
    [cit] = out["citations"]
    assert cit["finding"] == move["finding"]
    assert (cit["sql"], cit["confidence"], cit["novelty"]) == (MOVE_SQL, 0.8, 3)


def test_a_candidate_no_query_backs_is_never_cited_and_the_reason_is_said(narrator):
    chain = {"id": "promise-chain::ship_on_time", "angle": "Outcome", "promise_chain": True,
             "finding": "The fulfilment.ship_on_time promise has 1 filed link (ticket T-1).",
             "sql": "", "confidence": 0.9, "novelty": 3}
    found = {"id": "f1", "angle": "Level", "finding": "Return rate is 25%.", "sql": "SELECT 0.25",
             "confidence": 0.7, "novelty": 2}
    out = generate_narrative({"Promises": [chain], "General": [found]}, [], "c1")
    assert "ship_on_time" not in narrator.users[-1]                         # never offered to the narrator
    assert [c["finding"] for c in out["citations"]] == ["Return rate is 25%."]
    assert all(c["sql"] for c in out["citations"])
    [held] = [h for h in out["held_back"] if h["severity"] == "unbacked"]
    assert held["reason"] == "no query backs it — the brief cites only what a query shows"
    assert held["count"] == 1 and held["domains"] == ["Promises"]


def test_with_nothing_backed_the_brief_is_empty_and_says_what_it_held_back(narrator):
    out = generate_narrative({"Promises": [{"id": "p", "finding": "A promise moved.", "sql": "  "}]}, [], "c1")
    assert out["narrative"] == "" and out["citations"] == []
    assert narrator.users == []                                             # no model call for nothing to say
    assert [h["severity"] for h in out["held_back"]] == ["unbacked"]


def test_an_alert_carries_the_query_its_monitor_runs(monkeypatch):
    from types import SimpleNamespace

    from aughor.knowledge import period_brief
    from aughor.monitors.models import Monitor

    alert = SimpleNamespace(id="a1", monitor_id="m1", monitor_name="Revenue drop", triggered_at="2026-10-10T07:00:00Z",
                            message="Revenue fell 30%.", severity="critical")
    gone = SimpleNamespace(id="a2", monitor_id="m-gone", monitor_name="Old", triggered_at="2026-10-10T08:00:00Z",
                           message="x", severity="warning")
    monkeypatch.setattr("aughor.monitors.store.get_alerts", lambda **k: [alert, gone])
    monitors = {"m1": Monitor(id="m1", conn_id="c1", name="Revenue drop", custom_sql="SELECT SUM(amount) FROM orders")}
    monkeypatch.setattr("aughor.monitors.store.get_monitor", lambda mid: monitors.get(mid))
    window = SimpleNamespace(start=__import__("datetime").date(2026, 10, 10), end=__import__("datetime").date(2026, 10, 11))
    got = {f["id"]: f["sql"] for f in period_brief.alert_findings("c1", window)}
    assert got == {"alert::a1": "SELECT SUM(amount) FROM orders", "alert::a2": ""}   # a monitor gone backs nothing


class NumbersByUse:
    """A narrator that numbers its markers in the order it USES them, not by the prompt's [N] — LuxExperience's
    September edition (2026-10-12): [1] sat on the AOV sentence and opened the clienteling finding."""

    def __init__(self):
        self.users: list[str] = []

    def complete(self, *, system, user, response_model, temperature=0.1):
        self.users.append(user)
        return BriefingNarrative(
            narrative="Clienteling GMV per interaction rose to €15,098 [1]. Average order value fell to €581 from "
                      "€598 [2]. Returns stayed level [3].",
            headline_theme="t",
            citations=[_cite(r) for r in ("1", "2", "3")])


def test_a_marker_opens_the_finding_whose_figures_its_sentence_says(monkeypatch):
    narrator = NumbersByUse()
    monkeypatch.setattr(prov, "get_provider", lambda role=None: narrator)
    gmv = {"id": "gmv", "angle": "Trend", "finding": "Clienteling-influenced GMV per interaction rose to €15,098 from "
           "€13,156 (+15%).", "sql": "SELECT 1", "confidence": 0.9, "novelty": 3}
    aov = {"id": "aov", "angle": "Trend", "finding": "Average order value fell to €581 from €598 (-3%).",
           "sql": "SELECT 2", "confidence": 0.8, "novelty": 3}
    ret = {"id": "ret", "angle": "Level", "finding": "Item return rate held at 12%.", "sql": "SELECT 3",
           "confidence": 0.7, "novelty": 2}
    out = generate_narrative({"Sales": [gmv, aov, ret]}, [], "c1")
    # the prompt numbered AOV [1]; the narrator used GMV first and numbered it [1]
    assert re.search(r"^\[1\][^\n]*\n\s+\"Average order value", narrator.users[-1], flags=re.M)
    by_ref = {c["ref"]: c["finding"] for c in out["citations"]}
    assert by_ref["1"] == gmv["finding"] and by_ref["2"] == aov["finding"]
    # a sentence with no telling figure keeps its number
    assert by_ref["3"] == ret["finding"]
