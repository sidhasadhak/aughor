"""Agent model recommendations must be usable for what agents actually do.

Every agent call in this codebase asks for a `response_model` — the calls are
structured, not free-text. A model that answers prose beautifully and returns EMPTY
content for a structured request is worse than no recommendation at all, because
`POST /agents/apply-recommended-models` will pin it and the failure then hides behind
the provider fallback chain (measured 2026-08-13: the chain answered from gemini while
the pinned model returned nothing).
"""
from __future__ import annotations

from aughor.kernel.agents import list_charters
from aughor.llm.matrix import VOUCHED


def _vouched_for(backend: str, model: str):
    return next((v for v in VOUCHED if v.backend == backend and v.model == model), None)


def test_every_recommendation_is_a_vouched_id():
    """A recommendation naming an id nobody has seen in the live catalogue is a guess.
    Vouching is the record that someone checked."""
    unvouched = []
    for c in list_charters():
        for backend, model in (getattr(c, "recommended_models", {}) or {}).items():
            if _vouched_for(backend, model) is None:
                unvouched.append(f"{c.id} → {backend}:{model}")
    assert not unvouched, f"recommended models with no vouch entry: {unvouched}"


def test_no_agent_is_recommended_a_model_that_cannot_do_structured_output():
    """The specific defect this test exists for: `nemotron-3-nano-omni-...-reasoning`
    was recommended to the Watcher while returning empty content for every structured
    call. It is marked not-fast_eligible for exactly that reason, and an agent
    recommendation is a structured-call binding."""
    broken = []
    for c in list_charters():
        for backend, model in (getattr(c, "recommended_models", {}) or {}).items():
            v = _vouched_for(backend, model)
            if v is not None and "empty structured output" in (v.note or "").lower():
                broken.append(f"{c.id} → {model}")
    assert not broken, (
        f"agents recommended a model known to return empty structured output: {broken}")
