"""Regression guard: `re` must be importable at module scope in agent.nodes.

A diagnostic question (e.g. "Which product category is weakest by revenue?") that
the router classifies as `direct` reaches the definitional-detection branch in
classify_question(), which calls `re.search(...)`. `nodes.py` previously imported
`re` only *locally* inside two other functions, so this site raised a bare
`NameError: name 're' is not defined` — the whole investigation died and streamed
`{"type":"error","message":"name 're' is not defined"}` with no report.

These tests pin the module-level import and run the exact failing code path with a
stubbed provider so no LLM is needed."""
import re as _re

from aughor.agent import nodes as N
from aughor.agent.state import RouteDecision


def test_re_is_bound_at_module_scope():
    # The structural fix: `re` resolvable from every function's globals in nodes.py.
    assert getattr(N, "re", None) is _re, "agent.nodes must import `re` at module scope"
    assert N.classify_question.__globals__.get("re") is _re


class _StubLLM:
    def __init__(self, decision):
        self._decision = decision

    def complete(self, *args, **kwargs):
        return self._decision


def _run_classify(monkeypatch, question, mode="direct", confidence=0.9):
    decision = RouteDecision(mode=mode, confidence=confidence, reasoning="stub")
    monkeypatch.setattr(N, "get_provider", lambda *_a, **_k: _StubLLM(decision))
    return N.classify_question(question)


def test_diagnostic_direct_question_does_not_raise_nameerror(monkeypatch):
    # The reproduced crash: a "Which ... weakest" question routed `direct`.
    effective_mode, decision = _run_classify(
        monkeypatch, "Which product category is weakest by revenue?"
    )
    # Not definitional → stays direct (no KB final_text upgrade); crucially: no NameError.
    assert effective_mode == "direct"
    assert decision.mode == "direct"


def test_definitional_direct_question_runs_re_search(monkeypatch):
    # A genuinely definitional question makes the regex MATCH, so the `re.search`
    # result is actually used — exercises the branch end-to-end. KB lookup is wrapped
    # in try/except, so absence of a strong match simply leaves mode == direct.
    effective_mode, _decision = _run_classify(monkeypatch, "What is net revenue?")
    assert effective_mode in ("direct", "final_text")
