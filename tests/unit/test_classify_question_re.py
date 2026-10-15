"""Regression guard: `re` must be importable at module scope in agent.nodes.

A definitional question ("What is net revenue?") that the router reads as a describe reaches
the definitional-detection branch in classify_question(), which calls `re.search(...)`.
`nodes.py` previously imported `re` only *locally* inside two other functions, so this site
raised a bare `NameError: name 're' is not defined` — the whole investigation died and streamed
`{"type":"error","message":"name 're' is not defined"}` with no report.

These tests pin the module-level import and run the exact failing code path. Since 2026-10-15
the classifier reads the question's SHAPE by code first and asks the model only on the
borderline, in the same four words (`ShapeDecision`); the stubbed provider stands in for that
call so no LLM is needed."""
import re as _re

from aughor.agent import nodes as N
from aughor.agent.state import ShapeDecision


def test_re_is_bound_at_module_scope():
    # The structural fix: `re` resolvable from every function's globals in nodes.py.
    assert getattr(N, "re", None) is _re, "agent.nodes must import `re` at module scope"
    assert N.classify_question.__globals__.get("re") is _re


class _StubLLM:
    def __init__(self, decision):
        self._decision = decision
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        assert kwargs.get("response_model") is ShapeDecision, "the model is asked for the SHAPE"
        return self._decision


def _run_classify(monkeypatch, question, shape="describe", confidence=0.9):
    stub = _StubLLM(ShapeDecision(shape=shape, confidence=confidence, reasoning="stub"))
    monkeypatch.setattr(N, "get_provider", lambda *_a, **_k: stub)
    return N.classify_question(question), stub


def test_a_weakness_question_is_a_diagnosis_by_code_and_asks_no_model(monkeypatch):
    # "Which ... weakest" hunts where value is weak — the shape rules read it, so the body is
    # investigate with no model call, and no code path here can raise the old NameError.
    (effective_mode, decision), stub = _run_classify(
        monkeypatch, "Which product category is weakest by revenue?")
    assert effective_mode == "investigate" and decision.mode == "investigate"
    assert decision.shape == "diagnose" and stub.calls == 0


def test_definitional_describe_question_runs_re_search(monkeypatch):
    # A genuinely definitional question makes the regex MATCH, so the `re.search` result is
    # actually used — exercises the branch end-to-end. KB lookup is wrapped in try/except, so
    # absence of a strong match simply leaves mode == direct.
    (effective_mode, _decision), _stub = _run_classify(monkeypatch, "What is net revenue?")
    assert effective_mode in ("direct", "final_text")


def test_a_borderline_question_asks_the_model_for_its_shape(monkeypatch):
    # No question word, no verify word, no why: code reads nothing, the model says describe,
    # and the body derived from it is direct — the same branch, through the model's answer.
    (effective_mode, decision), stub = _run_classify(monkeypatch, "Net revenue by region last month")
    assert stub.calls == 1
    assert effective_mode == "direct" and decision.shape == "describe"
