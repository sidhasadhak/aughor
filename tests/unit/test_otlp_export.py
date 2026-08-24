"""VA-3 — what actually reaches an OTLP backend.

The wave's premise, measured 2026-08-23 before any of it was written: point the
exporter at Jaeger and a run arrived as **phase spans and nothing else**. The
2,506 recorded model calls never reached it (`telemetry.log_generation` had no
caller in its entire life) and neither did the eight tool-span sites (guarded SQL,
its retries, delegation hops, agent evaluation), because every sink hanging off
`mlflow_tool_span` was local — MLflow needs a tracking URI, `task_history` and the
session log need flags.

So these are seam tests, deliberately. Each one drives the ORDINARY production
path and asserts a span came out the other end; each one fails if the component
exists but is not wired, which is the failure mode that let two whole span
families stay invisible while every unit test passed.
"""
from __future__ import annotations

import os

import pytest

from aughor.obs import genai


@pytest.fixture()
def spans(monkeypatch):
    """Real OTel spans into an in-memory exporter — the same fixture shape as
    `test_telemetry.py`, for the same reason: a fake tracer would only prove we
    call the methods we think we call."""
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
    monkeypatch.setenv("AUGHOR_KERNEL_EVENTS", "0")
    return exporter


def _by_name(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


# ── 1. the seam that did not exist: a model call becomes a span ───────────────

def test_recording_a_model_call_exports_a_generation_span(spans):
    """THE seam test for this wave. `_record_llm_call` is the one chokepoint every
    backend funnels through; before VA-3 it wrote to the session log and stopped
    there, so an exported trace had no model calls in it at all."""
    import aughor.telemetry as tel
    from aughor.llm.provider import _record_llm_call

    with tel.bind_trace("inv-otlp"):
        _record_llm_call(backend="gemini", model="gemini-3.1-flash-lite",
                         role="narrator", prompt_tokens=1200, completion_tokens=85,
                         ms=1432.0, temperature=0.2)

    finished = spans.get_finished_spans()
    assert finished, "no span was exported — _record_llm_call is not wired to OTLP"
    (gen,) = finished
    assert gen.name == "chat gemini-3.1-flash-lite"
    assert gen.attributes[genai.PROVIDER_NAME] == "gcp.gemini"
    assert gen.attributes[genai.REQUEST_MODEL] == "gemini-3.1-flash-lite"
    assert gen.attributes[genai.USAGE_INPUT_TOKENS] == 1200
    assert gen.attributes[genai.USAGE_OUTPUT_TOKENS] == 85
    assert gen.attributes[genai.OPERATION_NAME] == "chat"


def test_a_failed_model_call_exports_its_error_class(spans):
    """A trace that shows only the calls that worked is the wrong half of the
    story — the one you open a trace viewer to find is the one that failed."""
    import aughor.telemetry as tel
    from aughor.llm.provider import _record_llm_call

    with tel.bind_trace("inv-otlp"):
        _record_llm_call(backend="openrouter", model="m", role="coder",
                         prompt_tokens=None, completion_tokens=None, ms=90.0,
                         ok=False, error_class="RateLimitError", retries=2)
    (gen,) = spans.get_finished_spans()
    assert gen.attributes[genai.ERROR_TYPE] == "RateLimitError"
    # …and the gateway keeps its own name rather than being relabelled as a
    # first-party provider, so cost aggregates stay attributable.
    assert gen.attributes[genai.PROVIDER_NAME] == "openrouter"


def test_a_model_call_outside_a_trace_exports_nothing(spans):
    """An uncorrelated span is noise that cannot be reconstructed into a run —
    the same posture the session log takes when it drops trace-less events."""
    from aughor.llm.provider import _record_llm_call
    _record_llm_call(backend="groq", model="m", role="fast",
                     prompt_tokens=1, completion_tokens=1, ms=5.0)
    assert spans.get_finished_spans() == ()


def test_export_carries_no_prompt_content_without_a_capture_window(spans):
    """The user's decision ④ companion: turning telemetry on must not, by itself,
    start shipping user text off-box. With no window open `capture_prompt` returns
    nothing, so there is nothing for the exporter to carry."""
    import aughor.telemetry as tel
    from aughor.llm.provider import _record_llm_call

    with tel.bind_trace("inv-otlp"):
        _record_llm_call(backend="groq", model="m", role="coder",
                         prompt_tokens=10, completion_tokens=3, ms=20.0,
                         system="SECRET SYSTEM PROMPT", user="SECRET USER QUESTION",
                         output="SECRET ANSWER")
    (gen,) = spans.get_finished_spans()
    blob = " ".join(str(v) for v in gen.attributes.values())
    assert "SECRET" not in blob, f"prompt content leaked onto the exported span: {blob}"


# ── 2. the other family that reached no backend: tool spans ───────────────────

def test_a_tool_span_reaches_the_exporter(spans):
    """`mlflow_tool_span` drove three sinks and all three were local. Guarded SQL —
    the single most useful span in a slow run — was invisible to the tool you open
    to find out where the time went."""
    import aughor.telemetry as tel
    with tel.bind_trace("inv-otlp"):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"}):
            pass
    (sp,) = spans.get_finished_spans()
    assert sp.name == "sql.execute"
    assert sp.attributes[genai.OPERATION_NAME] == "execute_tool"
    assert sp.attributes[genai.TOOL_NAME] == "sql.execute"


def test_a_delegation_hop_is_an_agent_invocation_not_a_tool_call(spans):
    """VA-2's hops. Collapsing another agent's whole run into `execute_tool` is
    what makes a delegation tree unreadable in an external viewer."""
    import aughor.telemetry as tel
    with tel.bind_trace("inv-otlp"):
        with tel.mlflow_tool_span("delegate:Luxury Revenue Analyst", {"question": "q"},
                                  span_kind="delegation",
                                  span_attrs={"delegate_agent_name": "Luxury Revenue Analyst",
                                              "delegation_depth": 2}):
            pass
    (sp,) = spans.get_finished_spans()
    assert sp.attributes[genai.OPERATION_NAME] == "invoke_agent"
    assert sp.attributes[genai.AGENT_NAME] == "Luxury Revenue Analyst"
    assert sp.name == "invoke_agent Luxury Revenue Analyst"
    # depth rides along, so VA-6 can alert on a runaway tree from the backend too
    assert sp.attributes["delegation_depth"] == 2


def test_a_tool_span_inside_a_node_span_is_its_CHILD(spans):
    """The difference between a tree and a flat list. Pinning every span to the
    trace's synthetic root — which unconditional `_otel_context` did — exported a
    run as N siblings and threw away parentage the local sinks had all along."""
    import aughor.telemetry as tel
    with tel.span("inv-otlp", "cross_section", {}):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"}):
            pass
    named = _by_name(spans)
    parent, child = named["cross_section"], named["sql.execute"]
    assert child.parent is not None, "the tool span was exported with no parent"
    assert child.parent.span_id == parent.context.span_id, \
        "the tool span is a SIBLING of the node it ran inside"
    assert child.context.trace_id == parent.context.trace_id


def test_a_body_exception_marks_the_tool_span_errored_and_still_propagates(spans):
    """Telemetry records the failure; it never swallows it."""
    import aughor.telemetry as tel
    from opentelemetry.trace import StatusCode
    with pytest.raises(ValueError, match="boom"):
        with tel.bind_trace("inv-otlp"):
            with tel.mlflow_tool_span("sql.execute"):
                raise ValueError("boom")
    (sp,) = spans.get_finished_spans()
    assert sp.status.status_code is StatusCode.ERROR


def test_an_unrelated_ambient_span_does_not_adopt_the_run(spans):
    """A web framework's request span is a valid active span on a DIFFERENT trace.
    Nesting into it would move the investigation's spans onto the request's trace
    and the run would stop being addressable by its investigation id."""
    import aughor.telemetry as tel
    from opentelemetry import trace as _t
    tracer = _t.get_tracer("unrelated")
    with tracer.start_as_current_span("http.request"):
        with tel.span("inv-otlp", "phase", {}):
            pass
    named = _by_name(spans)
    assert named["phase"].context.trace_id == int(tel._lf_trace_id("inv-otlp"), 16), \
        "the investigation's span was adopted onto an unrelated trace"


# ── 3. the switch: off unless configured (decision ④) ─────────────────────────

def _fresh(monkeypatch):
    import aughor.telemetry as tel
    monkeypatch.setattr(tel, "_otel_init_done", False)
    monkeypatch.setattr(tel, "_otel_tracer", None)
    monkeypatch.setattr(tel, "_otel_provider", None)
    for var in ("AUGHOR_OTLP_ENDPOINT", "AUGHOR_OTLP_HEADERS", "AUGHOR_OTLP_PROTOCOL",
                "OTEL_EXPORTER_OTLP_ENDPOINT", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    return tel


def test_nothing_configured_means_no_export_and_zero_egress(monkeypatch):
    """Decision ④, pinned. Local-first: an unconfigured install must not open a
    socket to anywhere."""
    tel = _fresh(monkeypatch)
    assert tel._otlp_target() is None
    assert tel._otel() is None


def test_aughor_endpoint_defaults_to_http_because_that_is_what_collectors_take(monkeypatch):
    tel = _fresh(monkeypatch)
    monkeypatch.setenv("AUGHOR_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
    endpoint, headers, protocol, _ = tel._otlp_target()
    assert endpoint == "http://localhost:4318/v1/traces"
    assert protocol == "http"
    assert headers == {}


def test_grpc_is_reachable_but_only_when_asked_for(monkeypatch):
    tel = _fresh(monkeypatch)
    monkeypatch.setenv("AUGHOR_OTLP_ENDPOINT", "localhost:4317")
    monkeypatch.setenv("AUGHOR_OTLP_PROTOCOL", "grpc")
    assert tel._otlp_target()[2] == "grpc"


def test_headers_use_the_otel_format_so_a_pasted_line_works(monkeypatch):
    tel = _fresh(monkeypatch)
    monkeypatch.setenv("AUGHOR_OTLP_ENDPOINT", "http://x/v1/traces")
    monkeypatch.setenv("AUGHOR_OTLP_HEADERS", "authorization=Bearer abc, x-scope-org=acme")
    assert tel._otlp_target()[1] == {"authorization": "Bearer abc", "x-scope-org": "acme"}


def test_a_malformed_header_is_skipped_rather_than_taking_tracing_down(monkeypatch):
    tel = _fresh(monkeypatch)
    monkeypatch.setenv("AUGHOR_OTLP_ENDPOINT", "http://x/v1/traces")
    monkeypatch.setenv("AUGHOR_OTLP_HEADERS", "good=1,garbage,=novalue,also=2")
    assert tel._otlp_target()[1] == {"good": "1", "also": "2"}


def test_the_standard_otel_variable_still_works_on_its_historical_transport(monkeypatch):
    """Introducing our own name must not silently unplug a deployment already
    exporting through OpenTelemetry's own variable."""
    tel = _fresh(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    endpoint, _, protocol, _ = tel._otlp_target()
    assert endpoint == "localhost:4317"
    assert protocol == "grpc"


def test_aughor_endpoint_wins_over_the_standard_one(monkeypatch):
    tel = _fresh(monkeypatch)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    monkeypatch.setenv("AUGHOR_OTLP_ENDPOINT", "http://chosen:4318/v1/traces")
    assert tel._otlp_target()[0] == "http://chosen:4318/v1/traces"


def test_langfuse_keys_are_the_last_fallback_not_the_first_choice(monkeypatch):
    tel = _fresh(monkeypatch)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-x")
    endpoint, headers, protocol, label = tel._otlp_target()
    assert label == "Langfuse" and protocol == "http"
    assert endpoint.endswith("/api/public/otel/v1/traces")
    assert headers["Authorization"].startswith("Basic ")
    # …and an explicit endpoint displaces it.
    monkeypatch.setenv("AUGHOR_OTLP_ENDPOINT", "http://mine:4318/v1/traces")
    assert tel._otlp_target()[3] == "OpenTelemetry"


# ── 4. the tree, for generations too ──────────────────────────────────────────

def test_a_model_call_is_a_CHILD_of_the_phase_that_made_it(spans):
    """Caught by the live receipt, not by a unit test: generations were pinned to
    the trace's synthetic root and arrived as siblings of the phase they ran
    inside, so the exported tree said the model call and the phase were unrelated.
    Every assertion in this file passed while that was true."""
    import aughor.telemetry as tel
    from aughor.llm.provider import _record_llm_call

    with tel.span("inv-otlp", "cross_section", {}):
        _record_llm_call(backend="gemini", model="gemini-3.1-flash-lite", role="coder",
                         prompt_tokens=11202, completion_tokens=418, ms=1730.0)
    named = _by_name(spans)
    phase, gen = named["cross_section"], named["chat gemini-3.1-flash-lite"]
    assert gen.parent is not None, "the generation was exported with no parent"
    assert gen.parent.span_id == phase.context.span_id, \
        "the model call is a SIBLING of the phase that made it"


def test_a_delegates_model_call_hangs_under_the_hop_not_the_caller(spans):
    """Two levels down. If a delegate's generations parent to the outer phase, the
    exported tree cannot answer 'what did the sub-agent spend', which is the whole
    reason VA-2's hops carry depth."""
    import aughor.telemetry as tel
    from aughor.llm.provider import _record_llm_call

    with tel.span("inv-otlp", "phase", {}):
        with tel.mlflow_tool_span("delegate:Analyst", span_kind="delegation",
                                  span_attrs={"delegate_agent_name": "Analyst"}):
            _record_llm_call(backend="groq", model="m", role="narrator",
                             prompt_tokens=5, completion_tokens=1, ms=10.0)
    named = _by_name(spans)
    hop, gen = named["invoke_agent Analyst"], named["chat m"]
    assert gen.parent.span_id == hop.context.span_id
    assert hop.parent.span_id == named["phase"].context.span_id


def test_a_plain_tool_span_does_not_restate_its_kind_as_a_type(spans):
    """`gen_ai.tool.type = "tool"` is noise; a real kind (`sql`, `eval`) is not."""
    import aughor.telemetry as tel
    with tel.bind_trace("inv-otlp"):
        with tel.mlflow_tool_span("sql.execute"):
            pass
        with tel.mlflow_tool_span("agent.evaluate", span_kind="eval"):
            pass
    named = _by_name(spans)
    assert genai.TOOL_TYPE not in named["sql.execute"].attributes
    assert named["agent.evaluate"].attributes[genai.TOOL_TYPE] == "eval"


def test_an_oversized_attribute_is_capped_and_marked_on_the_export_path(spans):
    """Collectors reject oversized spans, and a span dropped at ingest is a hole in
    a trace with nothing to explain it. Marked rather than silently cut: a query
    that reads as complete but was truncated sends someone debugging the wrong
    thing."""
    import aughor.telemetry as tel
    huge = "SELECT " + ("x" * 5000)
    with tel.bind_trace("inv-otlp"):
        with tel.mlflow_tool_span("sql.execute", {"sql": huge}):
            pass
    (sp,) = spans.get_finished_spans()
    got = sp.attributes["sql"]
    assert len(got) < len(huge)
    assert got.endswith("…[truncated]")


def test_numeric_attributes_survive_as_numbers_not_strings(spans):
    """A token count or a row count stringified is a number no backend can chart."""
    import aughor.telemetry as tel
    with tel.bind_trace("inv-otlp"):
        with tel.mlflow_tool_span("sql.execute", {"row_count": 17, "cached": False}):
            pass
    (sp,) = spans.get_finished_spans()
    assert sp.attributes["row_count"] == 17
    assert sp.attributes["cached"] is False


# ── 5. the suite itself must not export ───────────────────────────────────────

def test_the_test_suite_is_never_configured_to_export(monkeypatch):
    """Hermeticity guard for the wave's own switch.

    `aughor/api.py` used to call `load_dotenv()` unconditionally at import, so a
    developer's `.env` reached the test process the moment any test touched the app.
    That door is now shut at the source (`AUGHOR_SKIP_DOTENV`, set by the conftest),
    but this guard stays: `AUGHOR_OTLP_ENDPOINT` is one of the things `.env` can
    carry, and a suite configured to export would POST every span it produces to
    whatever collector that developer runs — thousands of test spans in their real
    trace data, plus a connection attempt and retry backoff per batch when nothing
    is listening.

    ⚠️ It applies `.env` through `dotenv_values` + `monkeypatch`, NOT `load_dotenv`.
    The first version called `load_dotenv` for real, which mutates `os.environ` for
    the REST OF THE PROCESS — measured 2026-08-24, this single line was the last
    surviving cause of `test_route_wide` failing on a laptop and passing in CI, long
    after the same leak had been closed everywhere else. Non-override semantics are
    reproduced deliberately, because that is what `load_dotenv` does and the guard is
    only honest if it takes the real path.

    `tests/conftest.py` neutralises the export variables for exactly this reason.
    This test fails if that scrub is removed, or if a NEW export variable is added
    without being added to it — the way a guard goes blind is that the world grows
    a key it was never taught to match.

    It takes the leak path ITSELF rather than hoping an earlier test took it. Written
    the obvious way — assert on the ambient env — it passed with the scrub deleted,
    because running this file alone never imports the app and so never loads `.env`:
    a probe that cannot fire and a true negative look identical."""
    import aughor.telemetry as tel
    _dotenv = pytest.importorskip("dotenv", reason="python-dotenv is optional")
    from pathlib import Path
    values = _dotenv.dotenv_values(Path(tel.__file__).parent.parent / ".env")
    for _key, _value in (values or {}).items():
        # `load_dotenv` never overrides a variable that is already set, and the whole
        # point of the scrub is that these ARE already set. Overriding here would test
        # a situation the leak could not produce.
        if _value is not None and _key not in os.environ:
            monkeypatch.setenv(_key, _value)
    assert tel._otlp_target() is None, (
        f"the suite is configured to export spans to {tel._otlp_target()[0]!r} — "
        f"conftest's export scrub is not covering every variable")
