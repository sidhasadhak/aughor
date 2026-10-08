"""A move explained in words — written by the model, held to the breakdown's numbers (2026-10-08).

The user, after the second round: build "a model-written explanation of a move". The watch job's SQL breakdown
says where a change sits; the model now says it in two or three sentences — and a number it was not handed,
or a claim beyond a description, sends the draft back once and then withholds it, said.
"""
from __future__ import annotations

import asyncio
import uuid

from aughor.explorer import move_story as S
from aughor.explorer import program as P

MOVE = {"name": "revenue", "metric": "revenue", "rel": -0.12, "current": 88_000.0, "previous": 100_000.0}
EXPLAINED = [
    {"metric": "revenue", "dimension": "country", "group": "United States", "change": -9_000.0,
     "current": 41_000.0, "previous": 50_000.0, "share": False},
    {"metric": "revenue", "dimension": "country", "group": "Brazil", "change": -2_000.0,
     "current": 18_000.0, "previous": 20_000.0, "share": False},
]
READING = {"through": "2026-10-07", "moved": [MOVE], "explained": EXPLAINED}


def _facts(findings=None):
    return S.facts_of(MOVE, EXPLAINED, reading=READING, grain="day", findings=findings)


def test_the_model_is_handed_the_numbers_and_each_segments_share_worked_out():
    f = _facts()
    assert f["change_pct"] == -12.0 and f["period"] == "the day to 2026-10-07"
    us = f["segments"][0]
    assert us["segment"] == "United States" and us["share_of_the_move_pct"] == 75.0
    assert f["segments"][1]["share_of_the_move_pct"] == 16.7


def test_a_number_it_was_not_handed_and_a_causal_claim_are_refused():
    f = _facts()
    ok = ("Revenue fell 12% in the day to 2026-10-07, from 100,000 to 88,000. "
          "The United States carries 75% of the move, down 9,000.")
    assert S.problems_with(ok, f) == []
    invented = "Revenue fell 12%, and 40% of the drop came from the United States."
    assert S.problems_with(invented, f) == ["it states 40%, which the breakdown does not hold"]
    causal = "Revenue fell 12% because the United States caused the drop."
    assert any("causal claim" in p for p in S.problems_with(causal, f))
    assert S.problems_with("", f) == ["it is empty"]


class _LLM:
    def __init__(self, *drafts):
        self.drafts = list(drafts)
        self.prompts = []
        self.model = "fake-narrator"

    def complete(self, *, system, user, response_model):
        self.prompts.append((system, user))
        return response_model(text=self.drafts.pop(0))


def test_a_clean_draft_is_kept_with_what_was_checked():
    llm = _LLM("Revenue fell 12%, from 100,000 to 88,000; the United States carries 75% of it.")
    out = S.narrate(_facts(), llm=llm)
    assert out["text"].startswith("Revenue fell 12%") and out["model"] == "fake-narrator"
    assert "CLAIM LICENCE: descriptive" in llm.prompts[0][0], "the prompt states the contract it is held to"
    assert len(llm.prompts) == 1


def test_a_draft_that_breaks_a_rule_is_sent_back_once_then_withheld():
    fixed = _LLM("Revenue fell 12% because of tariffs.", "Revenue fell 12%; the United States carries 75% of it.")
    out = S.narrate(_facts(), llm=fixed)
    assert out["text"] == "Revenue fell 12%; the United States carries 75% of it."
    assert "It broke these rules" in fixed.prompts[1][1]
    stubborn = _LLM("Revenue fell 30%.", "Revenue fell 31%.")
    out = S.narrate(_facts(), llm=stubborn)
    assert out["text"] == "" and out["withheld"].endswith("it states 31%, which the breakdown does not hold")


def test_what_the_platform_found_about_a_moving_segment_is_handed_over_and_a_short_name_matches_nothing():
    state = {"insights": [{"finding": "United States orders ship slower than any other country"},
                          {"finding": "Returns are flat"}, {"finding": "US buyers prefer weekends"}]}
    assert S.findings_naming(state, ["United States", "US"]) == [
        "United States orders ship slower than any other country"]


def test_a_readings_biggest_move_is_explained_and_kept_once(monkeypatch):
    conn = f"wh-{uuid.uuid4().hex[:6]}"
    key = P.key_for(conn, "marts")
    P.record_watch(key, "day", READING)
    monkeypatch.setattr("aughor.explorer.store.load", lambda k: {"insights": []})
    llm = _LLM("Revenue fell 12%; the United States carries 75% of it.")
    assert S.explain_reading(conn, "marts", "day", llm=llm)["text"]
    assert P.load(key)["watch"]["day"]["story"]["metric"] == "revenue"
    assert S.explain_reading(conn, "marts", "day", llm=llm) is None, "a move is explained once"


def test_the_explanation_is_a_capped_job_and_a_spent_budget_withholds_it(monkeypatch):
    import aughor.explorer.continuous as cont
    conn = f"wh-{uuid.uuid4().hex[:6]}"
    key = P.key_for(conn, "marts")
    P.record_watch(key, "day", READING)
    monkeypatch.setattr("aughor.explorer.budget.standing",
                        lambda c, now=None: {"spent_out": True, "remaining": -10, "sentence": "the budget is spent"})
    assert asyncio.run(cont.explain_move(conn, "marts", "day")) is None
    assert P.load(key)["watch"]["day"]["story"]["withheld"] == "not written — the budget is spent"

    submitted = []

    class _K:
        async def submit(self, kind, factory, **kw):
            submitted.append((kind, kw))
            return "job-1"

    monkeypatch.setattr("aughor.explorer.budget.standing",
                        lambda c, now=None: {"spent_out": False, "remaining": 7_000, "sentence": ""})
    monkeypatch.setattr("aughor.kernel.jobs.kernel", lambda: _K())
    assert asyncio.run(cont.explain_move(conn, "marts", "day", through="2026-10-07")) == "job-1"
    kind, kw = submitted[0]
    assert kind == "explain_move" and kw["payload"]["token_cap"] == 7_000
    assert kw["idempotency_key"] == f"explain_move:{key}:day:2026-10-07"


def test_the_explanation_job_spends_under_the_explorers_charter_and_counts_against_the_budget():
    from aughor.explorer.budget import SPENDING_KINDS
    from aughor.kernel.agents import charter_for_kind
    assert charter_for_kind("explain_move").id == "scout"
    assert "explain_move" in SPENDING_KINDS
