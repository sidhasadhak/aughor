"""P-B — parallelize the plan-time pre-flight retrievals (flag `preflight.parallel`).

plan_queries runs four INDEPENDENT, deterministic, non-LLM retrievals before the planning call:
relevant-schema ∥ KB planning patterns ∥ causal context ∥ closed-loop corrections. Under the flag
they run concurrently (ContextThreadPoolExecutor); off, one-at-a-time. These pin: the assembled
planning prompt is byte-identical across the flag, the closed-loop liveness signal survives, and
the wave actually runs concurrently.
"""
from __future__ import annotations

import time

import aughor.agent.nodes as N
from aughor.agent.state import Hypothesis, QueryIntent, QueryPlanV2


class _CaptureLLM:
    """Stub coder provider: records the `user` prompt and returns a minimal valid QueryPlanV2."""
    def __init__(self):
        self.user = None

    def complete(self, system=None, user=None, response_model=None):
        self.user = user
        return QueryPlanV2(hypothesis_id="h1",
                           query_intents=[QueryIntent(description="measure revenue")])


def _install(monkeypatch, *, sleep=0.0):
    """Deterministic retrievals so the ONLY variable across a flag toggle is serial-vs-parallel."""
    def _schema(desc, schema):
        if sleep:
            time.sleep(sleep)
        return "SCHEMA-BLOCK"

    def _kb(desc):
        if sleep:
            time.sleep(sleep)
        return "KB-BLOCK"

    def _causal(desc, conn_id=None):
        if sleep:
            time.sleep(sleep)
        return "CAUSAL"

    def _priors(question, connection_id):
        if sleep:
            time.sleep(sleep)
        return "PRIORS"

    monkeypatch.setattr("aughor.semantic.retriever.retrieve_relevant_schema", _schema)
    monkeypatch.setattr("aughor.semantic.kb_retriever.retrieve_for_planning", _kb)
    monkeypatch.setattr("aughor.process.causal.build_causal_context_section", _causal)
    monkeypatch.setattr("aughor.verify.priors.build_corrections_section", _priors)
    llm = _CaptureLLM()
    monkeypatch.setattr(N, "get_provider", lambda *_a, **_k: llm)
    return llm


def _state():
    return {
        "question": "why did revenue drop",
        "connection_id": "c1",
        "schema_context": "TABLE t",
        "hypotheses": [Hypothesis(id="h1", description="revenue hypothesis")],
        "current_hypothesis_idx": 0,
        "prior_analyses": ["past study A"],
        "events_context": "",
    }


def test_preflight_parallel_prompt_is_byte_identical_to_serial(monkeypatch):
    llm = _install(monkeypatch)
    monkeypatch.delenv("AUGHOR_PREFLIGHT_PARALLEL", raising=False)
    out_off = N.plan_queries(_state())
    prompt_off = llm.user

    llm2 = _install(monkeypatch)
    monkeypatch.setenv("AUGHOR_PREFLIGHT_PARALLEL", "1")
    out_on = N.plan_queries(_state())
    prompt_on = llm2.user

    assert prompt_on == prompt_off                       # the assembled planning prompt is identical
    assert "SCHEMA-BLOCK" in prompt_on and "KB-BLOCK" in prompt_on
    assert prompt_on.index("CAUSAL") < prompt_on.index("PRIORS")   # causal then priors, as serial
    # closed-loop liveness (Bet 0) survives the parallel path
    assert out_on.get("verification_checks") == ["priors_injected"] == out_off.get("verification_checks")


def test_preflight_parallel_runs_concurrently(monkeypatch):
    _install(monkeypatch, sleep=0.2)
    monkeypatch.setenv("AUGHOR_PREFLIGHT_PARALLEL", "1")
    t0 = time.time()
    N.plan_queries(_state())
    dt = time.time() - t0
    assert dt < 0.5, f"expected concurrent (~0.2s), got {dt:.2f}s — retrievals serialized"


def test_preflight_serial_when_flag_off(monkeypatch):
    _install(monkeypatch, sleep=0.2)
    monkeypatch.delenv("AUGHOR_PREFLIGHT_PARALLEL", raising=False)
    t0 = time.time()
    N.plan_queries(_state())
    dt = time.time() - t0
    assert dt >= 0.75, f"expected serial (~0.8s), got {dt:.2f}s — should not parallelize when off"
