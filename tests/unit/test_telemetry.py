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
    """Force a fresh import of aughor.telemetry (clears the lazy-init flags).

    Rebinds the PACKAGE ATTRIBUTE as well as the `sys.modules` entry. Deleting only the
    latter leaves `aughor.telemetry` (the attribute on the parent package) pointing at the
    old module, so the two import spellings resolve to DIFFERENT module objects with
    different ContextVars: `import aughor.telemetry as t` reads the stale attribute while
    `from aughor.telemetry import f` reads the fresh entry. A trace bound through one is
    then invisible through the other, silently — which is how MI-1's tests came to pass
    alone and fail in the suite on 2026-09-03."""
    import aughor
    for mod in list(sys.modules.keys()):
        if "aughor.telemetry" in mod or mod == "aughor.telemetry":
            del sys.modules[mod]
    import aughor.telemetry as tel
    aughor.telemetry = tel
    return tel


@pytest.fixture(autouse=True, scope="module")
def _restore_telemetry_module():
    """Put the original module object back — in BOTH places — when this file is done, so
    the reload above cannot leak a divergent module into every file that runs after."""
    import aughor
    import aughor.telemetry as original
    yield
    sys.modules["aughor.telemetry"] = original
    aughor.telemetry = original


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
    """log_generation must be a silent no-op when no endpoint is configured."""
    import aughor.telemetry as tel
    tel.log_generation(
        trace_id="",
        name="decompose",
        model="llama-3.3-70b",
        backend="groq",
        prompt_tokens=120,
        completion_tokens=8,
        duration_ms=430.0,
        content={"user_prompt": "Hello", "response": "Some output"},
        metadata={"hypothesis_id": "h1"},
    )


def test_log_generation_with_unknown_trace_id_no_crash():
    """log_generation on an unregistered trace_id must not crash."""
    import aughor.telemetry as tel
    tel.log_generation(
        trace_id="unknown-id",
        name="synthesize",
        model="qwen2.5-coder:32b",
        backend="ollama",
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


# ── cross-invocation trace continuity ─────────────────────────────────────────
# In a sliced run the invocation adding a span is routinely not the one that
# called new_trace. This used to be a RECOVERY problem: the handle memo was
# process-local, and a miss was treated as "no trace", silently orphaning every
# such span — so `_trace_handle` rebuilt the handle by id.
#
# Since OA·LF-1 it is not a problem at all. Spans travel over OTLP and the trace
# id is *derived* from the investigation id (`_lf_trace_id`), so a later
# invocation computes the same trace id without ever having seen new_trace.
# These tests pin the continuity itself against real exported spans, not the
# mechanism that used to restore it.

@pytest.fixture()
def spans(monkeypatch):
    """Real OTel spans into an in-memory exporter.

    A fake client would only prove we call the methods we think we call — which is
    exactly what the old suite proved while the backend shipped nothing. Exporting
    real spans means the assertions are about what Langfuse would actually receive."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    import aughor.telemetry as tel

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tel, "_otel_tracer", provider.get_tracer("aughor-test"))
    monkeypatch.setattr(tel, "_otel_provider", provider)
    monkeypatch.setattr(tel, "_otel_init_done", True)
    monkeypatch.setattr(tel, "_traces", {})
    # The ledger emit is a separate sink and writes to the live data dir; off here.
    monkeypatch.setenv("AUGHOR_KERNEL_EVENTS", "0")
    return exporter


def _trace_ids(exporter) -> set[str]:
    return {format(s.context.trace_id, "032x") for s in exporter.get_finished_spans()}


def test_span_from_another_invocation_joins_the_same_trace(spans):
    """The memo is EMPTY — as it is in every invocation but the creating one. The
    span must still land on the investigation's trace, not a fresh one."""
    import aughor.telemetry as tel
    with tel.span("inv-sliced", "phase8_angle", {"slice": 3}) as sp:
        pass
    assert sp is not None, "span was orphaned"
    assert _trace_ids(spans) == {tel._lf_trace_id("inv-sliced")}


def test_two_invocations_produce_one_trace(spans):
    """The property that matters, stated directly: spans emitted by separate
    invocations — with no shared state between them — share a trace id."""
    import aughor.telemetry as tel
    tel.new_trace("inv-sliced", "Why did sales drop?", "conn-1")
    with tel.span("inv-sliced", "decompose"):
        pass
    tel._traces.clear()          # a fresh invocation: nothing carried over
    with tel.span("inv-sliced", "synthesize"):
        pass
    assert len(spans.get_finished_spans()) == 2
    assert _trace_ids(spans) == {tel._lf_trace_id("inv-sliced")}, \
        "a sliced run split across two Langfuse traces"


def test_first_span_carries_the_trace_level_attributes(spans, monkeypatch):
    """OTel has no trace object, so new_trace's name/input/session ride the first
    span. Without this the trace lands in Langfuse unnamed and inputless.

    MI-0: the question inside that input is now custody-gated, so this opens the capture
    window to keep proving what the test is for — that the attributes ride the first span.
    The gate itself is proven in `test_mi1_graded_ledger.py`."""
    import aughor.telemetry as tel
    from aughor.obs import prompt_window
    monkeypatch.setattr(prompt_window, "active", lambda: True)

    tel.new_trace("inv-attrs", "Why did sales drop?", "conn-1")
    with tel.span("inv-attrs", "decompose"):
        pass
    attrs = spans.get_finished_spans()[0].attributes
    assert attrs[tel._LF_TRACE_NAME] == "investigation"
    assert "Why did sales drop?" in attrs[tel._LF_TRACE_INPUT]
    assert attrs[tel._LF_SESSION_ID] == "inv-attrs"
    assert attrs[tel._LF_AS_ROOT] is True


def test_the_trace_attribute_withholds_the_question_with_the_window_shut(spans, monkeypatch):
    """MI-0's gate, asserted where the export actually happens. The trace stays named,
    sessioned and rooted — only the question is withheld, so nothing about finding or
    correlating a trace depends on the custody window."""
    import aughor.telemetry as tel
    from aughor.obs import prompt_window
    monkeypatch.setattr(prompt_window, "active", lambda: False)

    tel.new_trace("inv-shut", "Why did sales drop?", "conn-1")
    with tel.span("inv-shut", "decompose"):
        pass
    attrs = spans.get_finished_spans()[0].attributes
    assert "Why did sales drop?" not in attrs[tel._LF_TRACE_INPUT]
    assert "conn-1" in attrs[tel._LF_TRACE_INPUT]
    assert attrs[tel._LF_TRACE_NAME] == "investigation"
    assert attrs[tel._LF_SESSION_ID] == "inv-shut"


def test_only_the_first_span_claims_the_root(spans):
    """Popped, not read: a second span restating the trace's input would make every
    node look like the start of its own investigation."""
    import aughor.telemetry as tel
    tel.new_trace("inv-once", "Q", "c1")
    with tel.span("inv-once", "first"):
        pass
    with tel.span("inv-once", "second"):
        pass
    first, second = spans.get_finished_spans()
    assert tel._LF_AS_ROOT in first.attributes
    assert tel._LF_AS_ROOT not in second.attributes


def test_generation_is_typed_so_langfuse_renders_it_as_a_model_call(spans):
    """The observation type is what separates a generation from a plain span."""
    import aughor.telemetry as tel
    tel.log_generation("inv-sliced", "narrator", "llama-3.3-70b", backend="groq",
                       content={"user_prompt": "q", "response": "out"})
    (gen,) = spans.get_finished_spans()
    # The span NAME follows the GenAI convention `{operation} {model}` (VA-3), not
    # our internal role: a reader grouping model calls groups on this string, and
    # "narrator" is a fact about our pipeline that no external backend can use.
    assert gen.name == "chat llama-3.3-70b"
    assert gen.attributes[tel._LF_OBS_TYPE] == "generation"
    assert gen.attributes[tel._LF_OBS_MODEL] == "llama-3.3-70b"
    assert "out" in gen.attributes[tel._LF_OBS_OUTPUT]
    assert _trace_ids(spans) == {tel._lf_trace_id("inv-sliced")}


def test_generation_carries_the_genai_conventions_every_other_backend_reads(spans):
    """Langfuse's keys make it render; these make it legible in Jaeger, Tempo,
    Grafana or a bare collector — the point of VA-3."""
    import aughor.telemetry as tel
    from aughor.obs import genai
    tel.log_generation("inv-sliced", "narrator", "gemini-3.1-flash-lite",
                       backend="gemini", prompt_tokens=1200, completion_tokens=85,
                       duration_ms=1500.0, temperature=0.2)
    (gen,) = spans.get_finished_spans()
    assert gen.attributes[genai.OPERATION_NAME] == "chat"
    assert gen.attributes[genai.PROVIDER_NAME] == "gcp.gemini"
    assert gen.attributes[genai.REQUEST_MODEL] == "gemini-3.1-flash-lite"
    assert gen.attributes[genai.USAGE_INPUT_TOKENS] == 1200
    assert gen.attributes[genai.USAGE_OUTPUT_TOKENS] == 85


def test_generation_span_has_the_duration_the_call_actually_took(spans):
    """Written retroactively — the caller already knows the latency, so the span is
    back-dated instead of arriving zero-width. A generation with no duration makes
    a waterfall useless, which is the surface this data exists for."""
    import aughor.telemetry as tel
    tel.log_generation("inv-sliced", "narrator", "m", backend="groq", duration_ms=1500.0)
    (gen,) = spans.get_finished_spans()
    elapsed_ms = (gen.end_time - gen.start_time) / 1_000_000
    assert 1400 <= elapsed_ms <= 1700, f"span lasted {elapsed_ms}ms, not ~1500"


def test_generation_without_a_capture_window_exports_no_content(spans):
    """The user's decision, pinned: turning telemetry on must not start shipping
    prompt text off-box. Content rides only what `capture_prompt` already stored."""
    import aughor.telemetry as tel
    tel.log_generation("inv-sliced", "narrator", "m", backend="groq",
                       prompt_tokens=10, completion_tokens=2, content=None)
    (gen,) = spans.get_finished_spans()
    assert tel._LF_OBS_INPUT not in gen.attributes
    assert tel._LF_OBS_OUTPUT not in gen.attributes
    # …while the measurement still travels in full.
    assert gen.attributes[tel._LF_OBS_MODEL] == "m"


def test_unreported_usage_never_becomes_zero_tokens_on_the_wire(spans):
    """Local backends report no usage; a zero would make every downstream cost
    aggregate silently understate itself."""
    import aughor.telemetry as tel
    from aughor.obs import genai
    tel.log_generation("inv-sliced", "narrator", "llama3", backend="ollama",
                       prompt_tokens=None, completion_tokens=None)
    (gen,) = spans.get_finished_spans()
    assert genai.USAGE_INPUT_TOKENS not in gen.attributes
    assert genai.USAGE_OUTPUT_TOKENS not in gen.attributes


def test_end_trace_finalises_a_trace_it_did_not_create(spans):
    """The finalising invocation is routinely not the creating one in a sliced run."""
    import aughor.telemetry as tel
    tel.end_trace("inv-sliced", output={"headline": "done"})
    (end,) = spans.get_finished_spans()
    assert "done" in end.attributes[tel._LF_TRACE_OUTPUT]
    assert _trace_ids(spans) == {tel._lf_trace_id("inv-sliced")}


def test_end_trace_flushes_because_serverless_freezes_on_response(spans, monkeypatch):
    """The batch processor exports on a timer; a Vercel invocation is frozen the
    moment it responds, so an unflushed batch dies with the process."""
    import aughor.telemetry as tel
    flushed = []
    monkeypatch.setattr(tel._otel_provider, "force_flush", lambda *a: flushed.append(a))
    tel.end_trace("inv-sliced", output={"headline": "done"})
    assert flushed, "end_trace did not force-flush the span batch"


def test_a_broken_tracer_does_not_break_the_node_it_wraps(spans, monkeypatch):
    """A down collector must never propagate into the work being traced."""
    import aughor.telemetry as tel

    class _Boom:
        def start_as_current_span(self, *a, **kw):
            raise RuntimeError("collector unreachable")

    monkeypatch.setattr(tel, "_otel_tracer", _Boom())
    with tel.span("inv-sliced", "phase") as sp:
        ok = True
    assert ok and sp is None
