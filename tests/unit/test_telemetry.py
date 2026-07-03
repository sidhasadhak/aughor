"""
Unit tests for aughor.telemetry.

All tests run without Langfuse or OTel credentials — the module must be
completely no-op (no crash, correct return values) when env vars are absent.
"""
from __future__ import annotations

import sys
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reload_telemetry():
    """Force a fresh import of aughor.telemetry (clears the lazy-init flags)."""
    for mod in list(sys.modules.keys()):
        if "aughor.telemetry" in mod or mod == "aughor.telemetry":
            del sys.modules[mod]
    import aughor.telemetry as tel
    return tel


# ── new_trace ─────────────────────────────────────────────────────────────────

def test_new_trace_returns_investigation_id_when_disabled():
    """new_trace must return investigation_id even when Langfuse is not configured."""
    import aughor.telemetry as tel
    result = tel.new_trace("inv-abc123", "Why did sales drop?", "conn-1")
    assert result == "inv-abc123"


def test_new_trace_idempotent_on_same_id():
    """Calling new_trace twice with the same id should not raise."""
    import aughor.telemetry as tel
    r1 = tel.new_trace("inv-dup", "Q1", "c1")
    r2 = tel.new_trace("inv-dup", "Q1", "c1")
    assert r1 == r2 == "inv-dup"


def test_new_trace_works_without_env_vars(monkeypatch):
    """No LANGFUSE_PUBLIC_KEY/SECRET_KEY → new_trace is a no-op."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    tel = _reload_telemetry()
    result = tel.new_trace("inv-no-key", "Test question", "conn-x")
    assert result == "inv-no-key"


# ── span ──────────────────────────────────────────────────────────────────────

def test_span_context_manager_no_crash_when_disabled():
    """span() must work as a no-op context manager when telemetry is disabled."""
    import aughor.telemetry as tel
    with tel.span("", "some_node", {"meta": "data"}) as sp:
        result = 42
    # sp is None (no backend configured), result should be computed normally
    assert result == 42
    assert sp is None


def test_span_with_unknown_trace_id_no_crash():
    """span() with a trace_id that was never registered should not crash."""
    import aughor.telemetry as tel
    with tel.span("ghost-trace-id", "decompose", {"iteration": 0}) as sp:
        x = "inner work"
    assert x == "inner work"
    assert sp is None


def test_span_exception_propagates():
    """Exceptions raised inside span() must propagate normally."""
    import aughor.telemetry as tel
    with pytest.raises(ValueError, match="intentional"):
        with tel.span("", "node", {}):
            raise ValueError("intentional")


# ── end_trace ─────────────────────────────────────────────────────────────────

def test_end_trace_no_crash_on_unknown_id():
    """end_trace on a trace that was never registered must not raise."""
    import aughor.telemetry as tel
    tel.end_trace("nonexistent-trace-id")  # should be silent no-op


def test_end_trace_removes_from_internal_dict():
    """After end_trace, the trace is removed from the internal _traces dict."""
    import aughor.telemetry as tel
    # Manually insert a sentinel so we can verify removal
    tel._traces["test-end-trace"] = object()
    tel.end_trace("test-end-trace")
    assert "test-end-trace" not in tel._traces


# ── log_generation ────────────────────────────────────────────────────────────

def test_log_generation_no_crash_when_disabled():
    """log_generation must be a silent no-op when Langfuse is not configured."""
    import aughor.telemetry as tel
    tel.log_generation(
        trace_id="",
        name="decompose",
        model="llama-3.3-70b",
        input_messages=[{"role": "user", "content": "Hello"}],
        output="Some output",
        metadata={"hypothesis_id": "h1"},
    )


def test_log_generation_with_unknown_trace_id_no_crash():
    """log_generation on an unregistered trace_id must not crash."""
    import aughor.telemetry as tel
    tel.log_generation(
        trace_id="unknown-id",
        name="synthesize",
        model="qwen2.5-coder:32b",
        input_messages=[],
        output="report text",
    )


# ── node_span decorator ───────────────────────────────────────────────────────

def test_node_span_return_value_preserved():
    """@node_span must not alter the wrapped function's return value."""
    import aughor.telemetry as tel

    @tel.node_span("test_node")
    def my_node(state):
        return {"result": state["x"] * 2}

    out = my_node({"x": 21, "trace_id": "", "iteration": 0, "current_hypothesis_idx": 0, "hypotheses": []})
    assert out == {"result": 42}


def test_node_span_two_arg_signature():
    """@node_span works for (state, conn) two-argument node functions."""
    import aughor.telemetry as tel

    @tel.node_span("two_arg_node")
    def my_node(state, conn):
        return {"used_conn": conn}

    out = my_node(
        {"trace_id": "", "iteration": 1, "current_hypothesis_idx": 0, "hypotheses": []},
        "mock_conn",
    )
    assert out == {"used_conn": "mock_conn"}


def test_node_span_exception_propagates():
    """Exceptions inside a @node_span-wrapped function must propagate."""
    import aughor.telemetry as tel

    @tel.node_span("failing_node")
    def bad_node(state):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        bad_node({"trace_id": "", "iteration": 0, "current_hypothesis_idx": 0, "hypotheses": []})


def test_node_span_no_crash_with_empty_hypotheses():
    """@node_span with no hypotheses in state must not raise."""
    import aughor.telemetry as tel

    @tel.node_span("scan")
    def scan_node(state):
        return {"ok": True}

    out = scan_node({"trace_id": "", "iteration": 0, "current_hypothesis_idx": 5, "hypotheses": []})
    assert out["ok"] is True


def test_node_span_reads_hypothesis_id_from_state():
    """@node_span correctly extracts hypothesis_id from the current index."""
    from aughor.agent.state import Hypothesis
    import aughor.telemetry as tel

    captured_meta = {}

    # Patch span to capture metadata
    original_span = tel.span
    from contextlib import contextmanager

    @contextmanager
    def spy_span(trace_id, name, metadata=None):
        captured_meta.update(metadata or {})
        yield None

    tel.span = spy_span
    try:
        @tel.node_span("score")
        def score_node(state):
            return {}

        hyps = [Hypothesis(id="h1", description="d1"), Hypothesis(id="h2", description="d2")]
        score_node({
            "trace_id": "t1",
            "iteration": 2,
            "current_hypothesis_idx": 1,
            "hypotheses": hyps,
        })
    finally:
        tel.span = original_span

    assert captured_meta.get("hypothesis_id") == "h2"
    assert captured_meta.get("iteration") == 2
    assert captured_meta.get("hypothesis_idx") == 1


def test_node_span_non_dict_state_passthrough():
    """If state is not a dict (unusual), the decorator must still call the function."""
    import aughor.telemetry as tel

    @tel.node_span("direct")
    def direct_node(state):
        return state

    sentinel = object()
    out = direct_node(sentinel)
    assert out is sentinel


# ── AgentState has trace_id ───────────────────────────────────────────────────

def test_agent_state_typeddict_has_trace_id():
    """AgentState TypedDict must include trace_id as an annotated key."""
    from aughor.agent.state import AgentState
    annotations = AgentState.__annotations__
    assert "trace_id" in annotations, (
        "trace_id missing from AgentState — SSE start event and LangGraph state will break"
    )


# ── _flat_attrs helper ────────────────────────────────────────────────────────

# ── SSE start-event format ────────────────────────────────────────────────────

def test_sse_start_event_trace_id_format():
    """
    Fast contract test: the SSE 'start' event that _stream_investigation yields
    must carry trace_id == investigation_id when Langfuse is disabled.

    This validates the same property as the e2e streaming test but without
    running the full HTTP stack or LangGraph.  We exercise:
      1. new_trace() returns the investigation_id unchanged (no Langfuse),
      2. _sse() serialises it into the event payload correctly.
    """
    import json
    from aughor import telemetry as tel
    from aughor.routers.investigations import _sse

    inv_id = "inv-sse-format-check"
    trace_id = tel.new_trace(inv_id, "Why did revenue drop?", "conn-test")

    # Simulate what _stream_investigation builds right before yielding 'start'
    start_event_str = _sse("start", {
        "question": "Why did revenue drop?",
        "connection_id": "conn-test",
        "investigation_id": inv_id,
        "trace_id": trace_id,
    })

    assert start_event_str.startswith("data: ")
    payload = json.loads(start_event_str.removeprefix("data: ").strip())
    assert payload["type"] == "start"
    assert payload["trace_id"] == inv_id, (
        "trace_id must equal investigation_id when Langfuse is not configured"
    )
    assert payload["investigation_id"] == inv_id


def test_flat_attrs_converts_to_otel_compatible_types():
    """_flat_attrs must produce only str/int/float/bool values."""
    from aughor.telemetry import _flat_attrs
    result = _flat_attrs({"a": 1, "b": 3.14, "c": True, "d": "text", "e": [1, 2]})
    for v in result.values():
        assert isinstance(v, (str, int, float, bool)), f"Non-scalar OTel attribute: {v!r}"
    assert result["e"] == "[1, 2]"
