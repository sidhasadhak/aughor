"""R9 — deterministic wide→explore routing.

Covers the pure detector (``is_wide_question``), the ``decide_ask_route`` gate (forced on/off,
license-safe degrade, and the causal/lookup non-poaching contract), and the ``/ask`` endpoint
dispatch (a wide question threads ``requested_mode="explore"`` into the deep body only when the
flag is on; ``/investigate`` stays pinned to ``investigate``). Hermetic — no live LLM, no DB:
the classifier is injected/stubbed and the deep/quick bodies are faked.
"""
from __future__ import annotations

import inspect
import json as _json
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aughor.routers.investigations as inv
from aughor.agent.ask_router import decide_ask_route, is_wide_question
from aughor.agent.complexity import assess_complexity


@dataclass
class _Decision:
    confidence: float = 1.0
    reasoning: str = "stub"


def _benign(_q):
    """A classifier that would route borderline questions to investigate — so any 'explore'
    verdict in these tests comes ONLY from the deterministic wide gate, never the model."""
    return "investigate", _Decision()


# ── Pure detector ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "Give me an overview of the sales landscape",
    "What are the characteristics of high-value customers?",
    "Profile our product catalog",
    "Explore the different customer segments",
    "How does conversion vary across channels and regions?",
    "What factors relate to repeat purchasing?",
    "What is the optimal discount depth for margin?",
])
def test_is_wide_true(q):
    assert is_wide_question(q, assess_complexity(q)) is True


@pytest.mark.parametrize("q", [
    "Why did revenue drop last week?",              # causal
    "What is driving the increase in churn?",       # driver → causal
    "What is total revenue last month?",            # direct lookup
    "Show top 10 customers by revenue",             # ranking lookup
    "Compare revenue by region versus last quarter",  # comparison, not a landscape
    "",                                             # empty
])
def test_is_wide_false(q):
    assert is_wide_question(q, assess_complexity(q)) is False


def test_wide_yields_to_causal_even_with_a_wide_marker():
    # "explore" marker present, but it is a causal 'why' → an investigation, never a landscape.
    q = "Explore why customer churn is rising"
    assert is_wide_question(q, assess_complexity(q)) is False


# ── decide_ask_route: the flag-forced gate ────────────────────────────────────

def test_wide_routes_to_explore_when_flag_on():
    r = decide_ask_route("How does conversion vary across channels and regions?",
                         classifier=_benign, route_wide=True)
    assert r.depth == "deep" and r.mode == "explore"
    assert r.used_classifier is False   # deterministic — no model in the routing path


def test_wide_does_not_route_to_explore_when_flag_off():
    r = decide_ask_route("How does conversion vary across channels and regions?",
                         classifier=_benign, route_wide=False)
    assert r.mode != "explore"


def test_causal_stays_investigate_even_with_flag_on():
    r = decide_ask_route("Why did revenue drop last week?", classifier=_benign, route_wide=True)
    assert r.depth == "deep" and r.mode == "investigate"


def test_lookup_stays_quick_even_with_flag_on():
    r = decide_ask_route("What is total revenue last month?", classifier=_benign, route_wide=True)
    assert r.depth == "quick" and r.mode == "direct"


def test_wide_degrades_to_quick_without_capability():
    r = decide_ask_route("Profile our product catalog", classifier=_benign,
                         route_wide=True, has_deep=False)
    assert r.depth == "quick" and r.downgraded_from == "deep" and r.mode == "direct"


# ── Endpoint dispatch + requested_mode threading ──────────────────────────────

@pytest.fixture
def ask_client(monkeypatch):
    captured: dict = {}

    async def fake_deep(*a, **k):
        captured["requested_mode"] = k.get("requested_mode")
        yield inv._sse("deep_marker", {})

    async def fake_chat(*a, **k):
        yield inv._sse("quick_marker", {})

    monkeypatch.setattr(inv, "_investigation_job_streamed", fake_deep)
    monkeypatch.setattr(inv, "_stream_chat", fake_chat)
    monkeypatch.setattr(inv, "_metered_stream", lambda gen, budget=None: gen)
    # Borderline tiebreak stays hermetic; the overview pre-gate is neutralized so a wide
    # phrasing reaches the router (the tour path is covered elsewhere).
    monkeypatch.setattr("aughor.agent.ask_router._default_classifier",
                        lambda q: ("direct", _Decision()))
    monkeypatch.setattr("aughor.licensing.has_capability", lambda *a, **k: True)
    monkeypatch.setenv("AUGHOR_ASK_OVERVIEW", "0")
    app = FastAPI()
    app.include_router(inv.router)
    return TestClient(app), captured


def _events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            out.append(_json.loads(line[len("data: "):]))
    return out


def test_ask_wide_question_routes_to_explore_body(ask_client, monkeypatch):
    client, captured = ask_client
    monkeypatch.setenv("AUGHOR_EXPLORE_ROUTE_WIDE", "1")
    r = client.post("/ask", json={"question": "How does conversion vary across channels and regions?",
                                  "connection_id": "c1"})
    evs = _events(r.text)
    assert evs[0]["type"] == "route" and evs[0]["mode"] == "explore" and evs[0]["depth"] == "deep"
    assert any(e["type"] == "deep_marker" for e in evs)
    assert captured["requested_mode"] == "explore"   # threaded to the graph → the explore wave


def test_ask_wide_question_not_explore_when_flag_off(ask_client, monkeypatch):
    client, captured = ask_client
    monkeypatch.setenv("AUGHOR_EXPLORE_ROUTE_WIDE", "0")
    r = client.post("/ask", json={"question": "How does conversion vary across channels and regions?",
                                  "connection_id": "c1"})
    evs = _events(r.text)
    assert evs[0]["mode"] != "explore"
    # If it happened to reach the deep body, it must be pinned to investigate — never explore.
    if captured.get("requested_mode") is not None:
        assert captured["requested_mode"] == "investigate"


def test_ask_causal_question_pins_investigate_with_flag_on(ask_client, monkeypatch):
    client, captured = ask_client
    monkeypatch.setenv("AUGHOR_EXPLORE_ROUTE_WIDE", "1")
    r = client.post("/ask", json={"question": "Why did revenue drop last week?", "connection_id": "c1"})
    evs = _events(r.text)
    assert evs[0]["mode"] == "investigate"
    assert any(e["type"] == "deep_marker" for e in evs)
    assert captured["requested_mode"] == "investigate"


def test_defaults_preserve_the_investigate_pin():
    # /investigate passes no requested_mode → both hops default to "investigate" (byte-identical).
    for fn in (inv._stream_investigation, inv._investigation_job_streamed):
        assert inspect.signature(fn).parameters["requested_mode"].default == "investigate"


# ── Graph reachability: requested_mode actually selects the subgraph (no LLM) ──
# route_question bypasses the classifier for an explicit requested_mode, so this proves —
# deterministically — that the "explore" we thread from /ask lands on the explore subgraph
# node (and "investigate" on the ADA branch). Closes the gap the faked deep body leaves open.

def test_requested_mode_explore_selects_the_explore_subgraph():
    from aughor.agent.nodes import route_after_classify, route_question
    state = {"question": "How does conversion vary across channels and regions?",
             "requested_mode": "explore"}
    upd = route_question(state)
    assert upd["query_mode"] == "explore"
    assert route_after_classify({**state, **upd}) == "exploratory_scan_explore"


def test_requested_mode_investigate_selects_the_ada_branch():
    from aughor.agent.nodes import route_after_classify, route_question
    state = {"question": "Why did revenue drop last week?", "requested_mode": "investigate"}
    upd = route_question(state)
    assert upd["query_mode"] == "investigate"
    assert route_after_classify({**state, **upd}) == "exploratory_scan"
