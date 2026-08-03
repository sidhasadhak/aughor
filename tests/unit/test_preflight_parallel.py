"""P-B — the plan-time pre-flight retrievals run concurrently.

plan_queries runs four INDEPENDENT, deterministic, non-LLM retrievals before the planning call:
relevant-schema ∥ KB planning patterns ∥ causal context ∥ closed-loop corrections. They run
concurrently (ContextThreadPoolExecutor). Wave 2d deleted the flag and the serial branch, so the
old on-vs-off byte-identity oracle has no second side — but the property it protected is still
testable, and is pinned here by varying COMPLETION order instead: the assembled prompt must be
byte-identical whether the four finish in order or in reverse. Also pinned: the closed-loop
liveness signal survives, and the wave actually runs concurrently.
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


def _install(monkeypatch, *, sleep=0.0, delays=None):
    """Deterministic retrievals.

    `delays` gives each retrieval its own latency, so a test can make the four COMPLETE in
    an order different from the order the prompt assembles them in — which is exactly what
    a pooled implementation could leak if it consumed futures as they resolved.
    """
    d = delays or {}

    # **kwargs absorbs the retrieval SCOPE (connection_id / schema) the node now passes —
    # this stub asserts on assembly order, not on the retriever's signature.
    def _schema(desc, schema, **kwargs):
        time.sleep(d.get("schema", sleep))
        return "SCHEMA-BLOCK"

    def _kb(desc):
        time.sleep(d.get("kb", sleep))
        return "KB-BLOCK"

    def _causal(desc, conn_id=None):
        time.sleep(d.get("causal", sleep))
        return "CAUSAL"

    def _priors(question, connection_id):
        time.sleep(d.get("priors", sleep))
        return "PRIORS"

    monkeypatch.setattr("aughor.semantic.retriever.retrieve_relevant_schema", _schema)
    monkeypatch.setattr("aughor.semantic.kb_retriever.retrieve_for_planning", _kb)
    monkeypatch.setattr("aughor.lifecycle.causal.build_causal_context_section", _causal)
    monkeypatch.setattr("aughor.feedback.priors.build_corrections_section", _priors)
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


def test_preflight_prompt_is_byte_identical_regardless_of_completion_order(monkeypatch):
    """The durable half of the batch-A receipt (`889789dda475`) — byte-identity, kept.

    The receipt claimed pooling the four retrievals changes nothing about the prompt.
    With the serial branch gone the oracle is no longer "the same run with the flag off";
    it is the same run whose retrievals finish in the OPPOSITE order. If assembly ever
    followed completion order, these two prompts would differ — which is the only way
    pooling could actually corrupt the prompt.
    """
    llm = _install(monkeypatch, delays={"schema": 0.0, "kb": 0.0, "causal": 0.0, "priors": 0.0})
    out_fast = N.plan_queries(_state())
    in_order = llm.user

    # Reverse the finishing order: priors first, schema last.
    llm2 = _install(monkeypatch,
                    delays={"schema": 0.20, "kb": 0.15, "causal": 0.10, "priors": 0.0})
    out_rev = N.plan_queries(_state())
    reversed_completion = llm2.user

    assert reversed_completion == in_order, "prompt followed completion order, not assembly order"
    assert "SCHEMA-BLOCK" in in_order and "KB-BLOCK" in in_order
    assert in_order.index("CAUSAL") < in_order.index("PRIORS")
    # closed-loop liveness (Bet 0) survives the parallel path, either way round
    assert out_fast.get("verification_checks") == ["priors_injected"] == out_rev.get("verification_checks")


def test_preflight_retrievals_run_concurrently(monkeypatch):
    _install(monkeypatch, sleep=0.2)
    t0 = time.time()
    N.plan_queries(_state())
    dt = time.time() - t0
    assert dt < 0.5, f"expected concurrent (~0.2s), got {dt:.2f}s — retrievals serialized"
