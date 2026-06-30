"""The unified /ask door router (Phase 0 of the Insight+Deep merge).

These exercise the pure decision function with the LLM intent classifier injected,
so the deterministic spine, the borderline-only tiebreak, the explicit overrides,
and the license-safe degrade are all covered without a live model.
"""
from __future__ import annotations

import json as _json
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import aughor.routers.investigations as inv
from aughor.agent.ask_router import decide_ask_route


@dataclass
class _Decision:
    confidence: float = 0.9
    reasoning: str = "test reasoning"


class _RecordingClassifier:
    """Stand-in for classify_question — records calls and returns a fixed mode."""

    def __init__(self, mode: str = "investigate", confidence: float = 0.9):
        self.mode = mode
        self.confidence = confidence
        self.calls: list[str] = []

    def __call__(self, question: str):
        self.calls.append(question)
        return self.mode, _Decision(confidence=self.confidence)


def _route(q, **kw):
    # Default to a classifier that would explode if called — so "no classifier call"
    # is enforced structurally on the deterministic paths.
    kw.setdefault("classifier", _boom)
    return decide_ask_route(q, **kw)


def _boom(question):  # pragma: no cover - only called if a deterministic path leaks
    raise AssertionError(f"classifier must not be consulted for: {question!r}")


# ── Deterministic auto paths (no model call) ──────────────────────────────────

def test_simple_lookup_routes_quick_without_classifier():
    r = _route("What is total revenue?")
    assert r.depth == "quick" and r.mode == "direct"
    assert r.used_classifier is False and r.forced is None


def test_ranking_lookup_routes_quick():
    r = _route("Show top 10 customers by revenue")
    assert r.depth == "quick" and r.used_classifier is False


def test_causal_question_routes_deep_without_classifier():
    r = _route("Why did revenue drop last week?")
    assert r.depth == "deep" and r.mode == "investigate"
    assert r.used_classifier is False


def test_complex_question_routes_deep_without_classifier():
    r = _route("Why did revenue drop 8% last week compared to the prior week?")
    assert r.depth == "deep" and r.used_classifier is False


# ── Borderline path consults the classifier ───────────────────────────────────

def test_moderate_noncausal_question_uses_classifier_investigate():
    clf = _RecordingClassifier(mode="investigate", confidence=0.8)
    r = decide_ask_route(
        "Compare revenue by region versus last quarter, and break it down by channel",
        classifier=clf,
    )
    assert r.depth == "deep" and r.used_classifier is True
    assert r.confidence == 0.8 and len(clf.calls) == 1


def test_moderate_noncausal_question_classifier_direct_routes_quick():
    clf = _RecordingClassifier(mode="direct")
    r = decide_ask_route(
        "Compare revenue by region versus last quarter, and break it down by channel",
        classifier=clf,
    )
    assert r.depth == "quick" and r.used_classifier is True


def test_explore_mode_routes_deep():
    clf = _RecordingClassifier(mode="explore")
    r = decide_ask_route(
        "Compare revenue by region versus last quarter, and break it down by channel",
        classifier=clf,
    )
    assert r.depth == "deep"


def test_ambiguous_simple_question_falls_through_to_classifier():
    # simple tier but under-specified → not an obvious quick; the tiebreak runs.
    clf = _RecordingClassifier(mode="direct")
    r = decide_ask_route("How is performance lately?", classifier=clf)
    assert r.ambiguous is True and r.used_classifier is True
    assert len(clf.calls) == 1


def test_classifier_failure_falls_back_to_deep():
    def _raise(_q):
        raise RuntimeError("llm down")

    r = decide_ask_route(
        "Compare revenue by region versus last quarter, and break it down by channel",
        classifier=_raise,
    )
    assert r.depth == "deep" and r.used_classifier is False


# ── Explicit overrides win, deterministically ─────────────────────────────────

def test_depth_override_quick_forces_quick():
    # even a causal question is forced quick when the user asked for it
    r = _route("Why did revenue drop last week?", depth_override="quick")
    assert r.depth == "quick" and r.forced == "quick"


def test_depth_override_deep_forces_deep():
    r = _route("What is total revenue?", depth_override="deep")
    assert r.depth == "deep" and r.forced == "deep"


def test_deep_flag_escalation_forces_deep():
    r = _route("What is total revenue?", deep_flag=True)
    assert r.depth == "deep" and r.forced == "deep_flag"


def test_insight_id_is_a_dossier_drill():
    r = _route("anything", insight_id="ins_123")
    assert r.depth == "deep" and r.forced == "dossier"


def test_insight_id_with_deep_flag_is_escalation_not_dossier():
    r = _route("anything", insight_id="ins_123", deep_flag=True)
    assert r.forced == "deep_flag"


# ── License-safe degrade ──────────────────────────────────────────────────────

def test_deep_route_degrades_to_quick_without_capability():
    r = _route("Why did revenue drop last week?", has_deep=False)
    assert r.depth == "quick" and r.downgraded_from == "deep"
    assert r.mode == "direct"


def test_forced_deep_also_degrades_without_capability():
    r = _route("anything", depth_override="deep", has_deep=False)
    assert r.depth == "quick" and r.downgraded_from == "deep"


def test_quick_route_unaffected_by_capability():
    r = _route("What is total revenue?", has_deep=False)
    assert r.depth == "quick" and r.downgraded_from is None


# ── The route event payload ───────────────────────────────────────────────────

def test_to_event_shape_for_deep():
    r = _route("Why did revenue drop last week?")
    ev = r.to_event()
    assert ev["depth"] == "deep" and ev["alternatives"] == ["quick"]
    assert set(ev) >= {"depth", "mode", "tier", "score", "confidence", "ambiguous",
                       "why", "alternatives", "forced", "downgraded_from"}


def test_to_event_shape_for_quick():
    ev = _route("What is total revenue?").to_event()
    assert ev["depth"] == "quick" and ev["alternatives"] == ["deep"]
    assert isinstance(ev["why"], str) and ev["why"]


# ── Endpoint dispatch (the actual merge: route event → correct body) ──────────

def _events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data: "):
            out.append(_json.loads(line[len("data: "):]))
    return out


@pytest.fixture
def ask_client(monkeypatch):
    async def fake_chat(*a, **k):
        yield inv._sse("quick_marker", {})

    async def fake_deep(*a, **k):
        yield inv._sse("deep_marker", {})

    monkeypatch.setattr(inv, "_stream_chat", fake_chat)
    monkeypatch.setattr(inv, "_investigation_job_streamed", fake_deep)
    monkeypatch.setattr(inv, "_metered_stream", lambda gen, budget=None: gen)
    # Keep the borderline routing tiebreak hermetic — no live LLM call for these
    # endpoint tests (the decision matrix is covered by the pure-function tests above).
    monkeypatch.setattr(
        "aughor.agent.ask_router._default_classifier",
        lambda q: ("direct", _Decision(confidence=1.0, reasoning="stub")),
    )
    app = FastAPI()
    app.include_router(inv.router)
    return TestClient(app)


def _set_cap(monkeypatch, value: bool):
    monkeypatch.setattr("aughor.licensing.has_capability", lambda *a, **k: value)


def test_ask_simple_question_routes_to_quick_body(ask_client, monkeypatch):
    _set_cap(monkeypatch, True)
    r = ask_client.post("/ask", json={"question": "What is total revenue?",
                                       "connection_id": "c1"})
    assert r.status_code == 200
    evs = _events(r.text)
    assert evs[0]["type"] == "route" and evs[0]["depth"] == "quick"
    assert any(e["type"] == "quick_marker" for e in evs)
    assert not any(e["type"] == "deep_marker" for e in evs)


def test_ask_causal_question_routes_to_deep_body(ask_client, monkeypatch):
    _set_cap(monkeypatch, True)
    r = ask_client.post("/ask", json={"question": "Why did revenue drop last week?",
                                       "connection_id": "c1"})
    evs = _events(r.text)
    assert evs[0]["type"] == "route" and evs[0]["depth"] == "deep"
    assert any(e["type"] == "deep_marker" for e in evs)


def test_ask_deep_route_degrades_to_quick_for_free_tier(ask_client, monkeypatch):
    _set_cap(monkeypatch, False)
    r = ask_client.post("/ask", json={"question": "Why did revenue drop last week?",
                                       "connection_id": "c1"})
    evs = _events(r.text)
    assert evs[0]["depth"] == "quick" and evs[0]["downgraded_from"] == "deep"
    assert any(e["type"] == "quick_marker" for e in evs)


def test_ask_disabled_flag_returns_404(ask_client, monkeypatch):
    monkeypatch.setenv("AUGHOR_UNIFIED_ASK", "0")
    r = ask_client.post("/ask", json={"question": "anything", "connection_id": "c1"})
    assert r.status_code == 404


# ── Phase 3: the clarify gate (ask vs guess) ──────────────────────────────────

def test_ask_ambiguous_question_emits_clarify_not_an_answer(ask_client, monkeypatch):
    _set_cap(monkeypatch, True)
    r = ask_client.post("/ask", json={"question": "How is performance lately?", "connection_id": "c1"})
    evs = _events(r.text)
    assert any(e["type"] == "clarify" for e in evs)
    # it asked instead of answering — neither body ran
    assert not any(e["type"] in ("quick_marker", "deep_marker") for e in evs)


def test_ask_value_ambiguity_emits_clarify(ask_client, monkeypatch):
    _set_cap(monkeypatch, True)
    r = ask_client.post("/ask", json={"question": "total amount of urgent orders", "connection_id": "c1"})
    evs = _events(r.text)
    clar = next((e for e in evs if e["type"] == "clarify"), None)
    assert clar and clar["source"] == "ambiguous_term" and "urgent" in clar["terms"]


def test_ask_skip_clarify_bypasses_to_a_body(ask_client, monkeypatch):
    _set_cap(monkeypatch, True)
    r = ask_client.post("/ask", json={"question": "How is performance lately?", "connection_id": "c1",
                                       "skip_clarify": True})
    evs = _events(r.text)
    assert not any(e["type"] == "clarify" for e in evs)
    assert any(e["type"] in ("quick_marker", "deep_marker") for e in evs)


def test_ask_explicit_depth_bypasses_clarify(ask_client, monkeypatch):
    _set_cap(monkeypatch, True)
    # an explicit depth override is a deliberate answer request — don't interrupt with a question
    r = ask_client.post("/ask", json={"question": "How is performance lately?", "connection_id": "c1",
                                       "depth": "quick"})
    evs = _events(r.text)
    assert not any(e["type"] == "clarify" for e in evs)
    assert any(e["type"] == "quick_marker" for e in evs)


def test_ask_clarify_disabled_by_flag(ask_client, monkeypatch):
    _set_cap(monkeypatch, True)
    monkeypatch.setenv("AUGHOR_ASK_CLARIFY", "0")
    r = ask_client.post("/ask", json={"question": "How is performance lately?", "connection_id": "c1"})
    evs = _events(r.text)
    assert not any(e["type"] == "clarify" for e in evs)
    assert any(e["type"] in ("quick_marker", "deep_marker") for e in evs)
