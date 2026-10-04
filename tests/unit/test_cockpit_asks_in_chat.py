"""PENDING (Cockpit): the clarify gate read a request for a cockpit as an under-specified question
— 2 of the CT receipt's 10 asks were answered "which metric, and over what time period?" — and a
cockpit asked for in chat was answered as a question about data with nothing said. Measured
2026-10-04: since CT-7 the chat drafts no cockpit at all (the Briefing's Cockpit tab does, CT-9),
so the honest answer is to say where cockpits are made, before any gate or model sees the ask.
And `GET /suggestions` answered 500 on a server with no model key.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aughor.cockpit.intent import is_cockpit_ask
from aughor.routers import investigations as inv

#: The CT receipt's ten asks, verbatim (docs/COCKPIT_JSON_RENDER_STUDY_2026-09-28.md).
RECEIPT_ASKS = [
    "Build me a returns cockpit.",
    "Make a dashboard for this canvas: revenue, units sold and average order value on top, returns below.",
    "I want a cockpit with two tabs, Sales and Returns. Show an alert when the return rate goes above 12%.",
    "Create a cockpit for the operations team with shipping lead time, sell-through and repeat purchases.",
    "Set up a board with gross margin and net merchandise revenue, and show the conversion rate only when the range is final.",
    "Give me a cockpit of the key metrics for this canvas.",
    "Build a cockpit from the most interesting findings of this canvas.",
    "Cockpit with revenue, units and AOV. One section, nothing else.",
    "I need a returns watch: the item return rate with a limit at 10 percent, and a section that only appears when it is over.",
    "Make me an executive cockpit with tabs for Sales, Margin, Customers and Operations.",
]


def test_the_receipt_asks_are_recognised_and_questions_are_not():
    # Ask 9 names no cockpit, dashboard or board — left to the data path, on purpose.
    assert [is_cockpit_ask(a) for a in RECEIPT_ASKS] == [True] * 8 + [False, True]
    for q in ("What was revenue last month?", "Which dashboard metrics moved?",
              "Show revenue by board member", "Why did the cockpit's return rate card turn red?"):
        assert not is_cockpit_ask(q), q


def _events(text: str) -> list[dict]:
    return [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]


@pytest.fixture
def door(monkeypatch):
    async def model_body(*a, **k):                     # reaching a body means the door missed it
        raise AssertionError("a cockpit ask reached an answer body")
        yield
    for body in ("_stream_chat", "_investigation_job_streamed", "_stream_converse"):
        monkeypatch.setattr(inv, body, model_body)
    monkeypatch.setattr(inv, "_metered_stream", lambda gen, budget=None: gen)
    app = FastAPI()
    app.include_router(inv.router)
    return TestClient(app)


@pytest.mark.parametrize("ask", [RECEIPT_ASKS[5], RECEIPT_ASKS[7]])    # the two the gate paused
def test_the_door_says_where_cockpits_are_made_instead_of_asking_which_metric(door, monkeypatch, ask):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: n == "cockpit.composed")
    evs = _events(door.post("/ask", json={"question": ask, "connection_id": "c1"}).text)
    assert not any(e["type"] == "clarify" for e in evs)
    headline = next(e["headline"] for e in evs if e["type"] == "headline")
    assert headline.startswith("Cockpits are drafted in the Briefing, in its Cockpit tab")
    assert any(e["type"] == "done" for e in evs)
    # CP-4's envelope folds it, so a door that selects from the envelope says the same.
    assert evs[-1]["type"] == "envelope" and evs[-1]["envelope"]["headline"] == headline


def test_with_cockpits_off_the_door_says_that_instead(door, monkeypatch):
    monkeypatch.setattr("aughor.kernel.flags.flag_enabled", lambda n: False)
    evs = _events(door.post("/ask", json={"question": RECEIPT_ASKS[0], "connection_id": "c1"}).text)
    assert next(e["headline"] for e in evs if e["type"] == "headline").startswith(
        "Cockpits are switched off on this install")


def test_suggestions_without_a_model_serve_the_starters_and_say_why(monkeypatch):
    from aughor.routers import system

    class _NoKey:
        def complete(self, **k):
            raise RuntimeError("no API key configured for the coder binding")

    monkeypatch.setattr("aughor.llm.provider.get_provider", lambda role: _NoKey())
    monkeypatch.setattr("aughor.semantic.suggestions_cache.get_cached", lambda *a: None)
    app = FastAPI()
    app.include_router(system.router)
    r = TestClient(app).get("/suggestions", params={"connection_id": "workspace"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestions"] == [] and "starters" in body
    assert body["unavailable"].startswith("Suggested questions need a working model — no API key")
