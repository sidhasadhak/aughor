"""Optional observability — Langfuse traces per investigation, OTel spans per node,
MLflow trace trees per run.

Activation — **nothing exports until something is configured** (VA-3, decision ④):
  OTLP:     set AUGHOR_OTLP_ENDPOINT (+ AUGHOR_OTLP_HEADERS / AUGHOR_OTLP_PROTOCOL).
            OpenTelemetry's own OTEL_EXPORTER_OTLP_ENDPOINT still works, second.
  Langfuse: set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY — same pipeline, no SDK.

**Langfuse rides the OTel exporter (OA·LF-1).** It used to speak the Langfuse
Python SDK v2 directly — ``lf.trace()``, ``tr.span()``, ``tr.generation()``.
None of those methods exist on the v4 client this project resolves to, so init
succeeded, every call raised, and every raise was swallowed at debug level: the
backend was configured, reported enabled, and shipped nothing. Langfuse v3+ is
itself OpenTelemetry-native, so the repair is to delete the SDK span path and
point the exporter this module already builds at Langfuse's OTLP endpoint
(``{host}/api/public/otel/v1/traces``, HTTP + Basic auth). One span pipeline,
one place to break, and a version bump can no longer rot it silently — see
``tests/unit/test_telemetry_sdk_surface.py``.
  MLflow:   point AUGHOR_MLFLOW_TRACKING_URI (or MLFLOW_TRACKING_URI) at a server —
            self-gating on the URI, like the other two backends, since the
            2026-07-31 flag strategy deleted the `obs.mlflow` flag. Unlike the
            other two, MLflow owns trace *creation* via autolog (LangChain/OpenAI),
            so this module only nests node/tool spans under the active trace and
            tags it with the investigation id.

Spans carry three vocabularies at once, because no two readers share one: our own
attribute names, Langfuse's observation keys, and the OpenTelemetry **GenAI**
semantic conventions (``aughor/obs/genai.py``) that make a model call legible to
Jaeger, Tempo, Grafana or a bare collector. Before VA-3 an exported trace held our
phase spans and nothing else — the model calls and the tool spans reached no
external backend by any path at all.

All public functions are strict no-ops when no backend is configured.
"""
from __future__ import annotations

import contextvars
import functools
import logging
import os
import sys
import threading
import time as _time
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ── Langfuse (over OTLP) ──────────────────────────────────────────────────────
#
# Langfuse's OTel attribute keys. Hardcoded rather than imported from the SDK so a
# span still carries the right keys when `langfuse` is not installed at all (the
# exporter is plain OTLP — the package is only needed for the trace-id seed).
# `tests/unit/test_telemetry_sdk_surface.py` pins these against the installed SDK,
# so a rename upstream fails a test instead of silently un-labelling every span.
_LF_TRACE_NAME  = "langfuse.trace.name"
_LF_TRACE_INPUT = "langfuse.trace.input"
_LF_TRACE_OUTPUT = "langfuse.trace.output"
_LF_SESSION_ID  = "session.id"
_LF_OBS_TYPE    = "langfuse.observation.type"
_LF_OBS_INPUT   = "langfuse.observation.input"
_LF_OBS_OUTPUT  = "langfuse.observation.output"
_LF_OBS_MODEL   = "langfuse.observation.model.name"
_LF_AS_ROOT     = "langfuse.internal.as_root"

# investigation_id → the trace-level attributes new_trace() collected, pending the
# first span that can carry them. NOT a handle memo (the thing v2 needed and this
# does not): the trace's identity is now a pure function of the investigation id,
# `_lf_trace_id`, so any invocation in a sliced run derives the same trace without
# having seen new_trace. That is what makes an orphaned span structurally
# impossible here rather than merely recovered-from
# (docs/VERCEL_PLATFORM_DESIGN_2026-08-05.md §2).
_traces: dict[str, dict] = {}


def _langfuse_otlp() -> tuple[str, dict[str, str]] | None:
    """Langfuse's OTLP endpoint + auth headers, or None when unconfigured.

    Mirrors what the Langfuse SDK's own span processor builds
    (`langfuse/_client/span_processor.py`) — same path, same Basic-auth header —
    so we speak its ingestion contract without depending on its client."""
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not pk or not sk:
        return None
    import base64
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    auth = base64.b64encode(f"{pk}:{sk}".encode("utf-8")).decode("ascii")
    return f"{host}/api/public/otel/v1/traces", {
        "Authorization": f"Basic {auth}",
        "x-langfuse-sdk-name": "python",
        "x-langfuse-public-key": pk,
    }


def _lf_trace_id(seed: str) -> str | None:
    """The 32-hex OTel trace id for an investigation id — deterministic, so every
    invocation of a sliced run lands on ONE Langfuse trace and the id we hand the
    frontend stays the key that resolves it. Uses the SDK's own seeding function
    so our derivation cannot drift from the one Langfuse documents."""
    if not seed:
        return None
    try:
        from langfuse import Langfuse  # type: ignore[import]
        return Langfuse.create_trace_id(seed=seed)
    except Exception as exc:
        logger.debug("Langfuse trace-id seeding unavailable for %s: %s", seed, exc)
        return None


# ── OpenTelemetry ─────────────────────────────────────────────────────────────

_otel_tracer: Any = None
_otel_provider: Any = None
_otel_init_done = False


def _parse_headers(raw: str) -> dict[str, str]:
    """``k1=v1,k2=v2`` → dict, deliberately the same format as
    ``OTEL_EXPORTER_OTLP_HEADERS`` so an operator can paste a header line out of
    any OpenTelemetry doc and have it work. A malformed pair is skipped rather
    than raised: a typo in one header must not take tracing down, and an export
    that then fails auth fails loudly at the collector, where it is visible."""
    out: dict[str, str] = {}
    for pair in raw.split(","):
        k, sep, v = pair.partition("=")
        if sep and k.strip():
            out[k.strip()] = v.strip()
    return out


def _otlp_target() -> tuple[str, dict[str, str], str, str] | None:
    """Where spans go — ``(endpoint, headers, protocol, label)``, or None when
    nothing is configured and this whole module stays a no-op.

    Three sources, and the precedence between them is the design (VA-3):

    1. ``AUGHOR_OTLP_ENDPOINT`` — the product's own switch, and the one the
       roadmap's decision ④ names. **Unset means no export and zero egress**, which
       is why every other source is checked only after it: BYO-observability is
       the twin of BYOK, and a telemetry pipe that turns itself on is the opposite
       of that. Setting it is what turns Langfuse, VoltOps, Grafana Tempo or a bare
       otel-collector into "point it here". Transport defaults to OTLP/**HTTP**,
       because that is the one all four accept from a pasted URL;
       ``AUGHOR_OTLP_PROTOCOL=grpc`` switches it.
    2. ``OTEL_EXPORTER_OTLP_ENDPOINT`` — OpenTelemetry's own variable, kept on its
       historical gRPC transport byte-for-byte. Introducing our name must not
       silently unplug a deployment that is already exporting through the standard
       one; it is second, not deleted.
    3. Langfuse keys — the fallback destination, OTLP/HTTP with Basic auth
       (OA·LF-1: one span pipeline, no second SDK to rot).
    """
    endpoint = os.getenv("AUGHOR_OTLP_ENDPOINT", "").strip()
    if endpoint:
        protocol = "grpc" if os.getenv(
            "AUGHOR_OTLP_PROTOCOL", "http").strip().lower().startswith("grpc") else "http"
        return (endpoint, _parse_headers(os.getenv("AUGHOR_OTLP_HEADERS", "")),
                protocol, "OpenTelemetry")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if endpoint:
        return endpoint, {}, "grpc", "OpenTelemetry"
    lf = _langfuse_otlp()
    if lf is not None:
        return lf[0], lf[1], "http", "Langfuse"
    return None


def _otel() -> Any | None:
    """The tracer, once. Destination, transport and headers come from
    :func:`_otlp_target`; the exporter class is picked per protocol rather than
    shared, because the two OTLP transports are separate packages and Langfuse's
    endpoint does not accept gRPC at all."""
    global _otel_tracer, _otel_provider, _otel_init_done
    if _otel_init_done:
        return _otel_tracer
    _otel_init_done = True
    target = _otlp_target()
    if target is None:
        return None
    endpoint, headers, protocol, what = target
    try:
        from opentelemetry import trace  # type: ignore[import]
        from opentelemetry.sdk.resources import Resource  # type: ignore[import]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]

        if protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import]
                OTLPSpanExporter)
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import]
                OTLPSpanExporter)
        exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers or None)

        # A service name, so a run arriving in a shared collector is attributable
        # to this app rather than landing as `unknown_service` beside everything
        # else pointed at the same endpoint.
        provider = TracerProvider(resource=Resource.create(
            {"service.name": os.getenv("OTEL_SERVICE_NAME", "aughor")}))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _otel_provider = provider
        _otel_tracer = trace.get_tracer("aughor")
        logger.info("%s tracing enabled (endpoint=%s, protocol=%s)", what, endpoint, protocol)
    except ImportError:
        logger.debug("opentelemetry packages not installed — OTel tracing disabled")
    except Exception as exc:
        logger.warning("OTel init failed (tracing disabled): %s", exc)
    return _otel_tracer


def _otel_context(trace_id: str):
    """A context whose span parent carries ``trace_id``'s derived OTel trace id, so
    spans from different invocations of one sliced run join a single trace.

    Returns None when there is nothing to pin to, in which case the SDK mints its own
    trace id — a correct trace, just not one addressable by the investigation id."""
    tid = _lf_trace_id(trace_id)
    if tid is None:
        return None
    try:
        from opentelemetry import trace as _t  # type: ignore[import]
        ctx = _t.SpanContext(
            trace_id=int(tid, 16),
            span_id=int(tid[:16], 16),   # a stable synthetic parent for this trace
            is_remote=True,
            trace_flags=_t.TraceFlags(_t.TraceFlags.SAMPLED),
        )
        return _t.set_span_in_context(_t.NonRecordingSpan(ctx))
    except Exception as exc:
        logger.debug("OTel context build failed for %s: %s", trace_id, exc)
        return None


def _otel_parent(trace_id: str):
    """The context a new span should hang from — the difference between a tree and
    a flat list.

    ``None`` means "whatever span is currently active", i.e. real nesting: a tool
    span opened inside a phase span becomes its child, which is the shape an
    external viewer draws as a tree. Pinning every span to the trace's synthetic
    root instead — which is what unconditionally passing :func:`_otel_context`
    does — exports a run as N siblings and loses the parentage the local sinks
    have recorded all along.

    The active span is only trusted when it is on the SAME trace we would pin to.
    Otherwise an unrelated ambient span — a web framework's request span, say —
    would adopt the investigation's spans onto its trace, and the run would stop
    being addressable by its investigation id.
    """
    tid = _lf_trace_id(trace_id) if trace_id else None
    try:
        from opentelemetry import trace as _t  # type: ignore[import]
        ctx = _t.get_current_span().get_span_context()
        if ctx.is_valid and (tid is None or ctx.trace_id == int(tid, 16)):
            return None
    except Exception as exc:
        logger.debug("OTel parent probe failed for %s: %s", trace_id, exc)
    return _otel_context(trace_id)


def flush_traces(timeout_ms: int = 5_000) -> None:
    """Force-export buffered spans. The BatchSpanProcessor exports on a timer, and a
    serverless invocation is frozen the moment it responds — so on Vercel the timer
    routinely never fires and the batch dies with the process. Call at the end of a
    request that produced spans. No-op when tracing is off; never raises."""
    if _otel_provider is None:
        return
    try:
        _otel_provider.force_flush(timeout_ms)
    except Exception as exc:
        logger.debug("OTel force_flush failed: %s", exc)


# ── MLflow (self-gating on AUGHOR_MLFLOW_TRACKING_URI) ────────────────────────

_mlf: Any = None
_mlf_lock = threading.Lock()
_mlf_retry_at = 0.0  # monotonic time before which a failed init is not re-attempted
_MLF_RETRY_COOLDOWN_S = 60.0
_MLF_ATTR_MAX_CHARS = 2000  # cap string span attributes (e.g. SQL text)


def _mlflow() -> Any | None:
    """The mlflow module — only when a tracking URI is configured and init succeeded.

    SELF-GATING on config presence since the 2026-07-31 flag strategy (§4C): the old
    `obs.mlflow` flag was deleted, because a flag that is a no-op without an external
    server and silently inert with one configured is two ways to be confused — the
    URI being set IS the operator's intent. Like Langfuse/OTel this is env-configured,
    but it stays re-checked per call so unsetting the URI and restarting cleanly
    disables, and a transient failure (tracking server still booting) retries after a
    cooldown instead of disabling for the process lifetime. Every failure path
    degrades to None (tracing off), never raises.
    """
    global _mlf
    try:
        enabled = bool(os.getenv("AUGHOR_MLFLOW_TRACKING_URI")
                       or os.getenv("MLFLOW_TRACKING_URI"))
    except Exception:
        return None
    if not enabled:
        if _mlf is not None:
            _mlflow_disable()
        return None
    if _mlf is not None:
        return _mlf
    if _time.monotonic() < _mlf_retry_at:
        return None
    with _mlf_lock:
        if _mlf is not None or _time.monotonic() < _mlf_retry_at:
            return _mlf
        return _mlflow_init()


def _mlflow_init() -> Any | None:
    """One init attempt (runs under ``_mlf_lock``); failure arms the retry cooldown."""
    global _mlf, _mlf_retry_at
    try:
        import mlflow  # type: ignore[import]
    except ImportError:
        _mlf_retry_at = float("inf")  # the package won't appear mid-process
        logger.warning(
            "an MLflow tracking URI is set but the `mlflow` package is not installed — "
            "MLflow tracing disabled (install with: uv sync --extra observability)")
        return None
    try:
        # Bound the first-touch cost: init runs lazily on the answer path, so an
        # unreachable tracking server must fail in seconds, not minutes of HTTP
        # retries. setdefault — an operator's explicit values win.
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
        os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")
        uri = os.getenv("AUGHOR_MLFLOW_TRACKING_URI") or os.getenv("MLFLOW_TRACKING_URI")
        if uri:
            mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(os.getenv("AUGHOR_MLFLOW_EXPERIMENT", "aughor"))
        # Autolog owns trace creation: LangChain/LangGraph runs (graph nodes, token
        # counts) and direct OpenAI-client calls (the instructor-wrapped provider)
        # each become a trace. Best-effort per flavor — a missing integration
        # package must not disable the rest.
        for _flavor in ("langchain", "openai"):
            try:
                getattr(mlflow, _flavor).autolog()
            except Exception as exc:
                logger.debug("mlflow.%s.autolog unavailable: %s", _flavor, exc)
        _mlf = mlflow
        logger.info("MLflow tracing enabled (tracking_uri=%s)", mlflow.get_tracking_uri())
    except Exception as exc:
        _mlf_retry_at = _time.monotonic() + _MLF_RETRY_COOLDOWN_S
        logger.warning("MLflow init failed (will retry in %.0fs): %s",
                       _MLF_RETRY_COOLDOWN_S, exc)
    return _mlf


def _mlflow_disable() -> None:
    """The flag flipped OFF after a successful init: unpatch autolog, stop tracing.

    Without this, autolog would keep exporting full LLM prompts/completions to
    the tracking server even though the operator turned the feature off.
    """
    global _mlf, _mlf_retry_at
    with _mlf_lock:
        mlf, _mlf = _mlf, None
        if mlf is None:
            return
        for _flavor in ("langchain", "openai"):
            try:
                getattr(mlf, _flavor).autolog(disable=True)
            except Exception as exc:
                logger.debug("mlflow.%s.autolog disable failed: %s", _flavor, exc)
        _mlf_retry_at = 0.0  # re-enabling re-inits immediately
        logger.info("MLflow tracing disabled (no tracking URI configured)")


def trace_identity() -> tuple[str, str, str]:
    """The ambient (session_id, user_id, agent_id) for trace attribution.

    All three ride request-scoped contextvars (org.context session/user set by
    the /ask stream + identity middleware; user_agents.context agent set by the
    persona wrapper) and propagate into the deep-run job and the parallel-wave
    workers (ContextThreadPoolExecutor copies context) — so a node span deep in a
    wave still sees them, with nothing threaded through the graph. Every lookup
    degrades to '' rather than raise (telemetry must never break the answer path).
    """
    try:
        from aughor.org.context import current_session_id, current_user_id
        session_id, user_id = current_session_id(), current_user_id()
    except Exception:
        session_id, user_id = "", ""
    try:
        from aughor.custom_agents.context import current_agent
        agent = current_agent()
        agent_id = agent.id if agent is not None else ""
    except Exception:
        agent_id = ""
    return session_id, user_id, agent_id


def _tag_current_trace(mlf: Any, trace_id: str) -> None:
    """Attribute the active trace so MLflow's Sessions / user / per-agent + cost
    views populate (E1 of
    docs/DATABRICKS_OSS_AND_AGENTIC_PLATFORM_STUDY_2026-07-11.md).

    ``investigation_id`` and ``agent_id`` are TAGS (mutable, filterable); session
    and user go through ``update_current_trace``'s dedicated kwargs, which write
    the reserved ``mlflow.trace.session`` / ``mlflow.trace.user`` metadata the
    demo's Sessions and user filters key on. Idempotent, best-effort — a tagging
    failure never breaks the span it rides on.
    """
    session_id, user_id, agent_id = trace_identity()
    tags = {"investigation_id": trace_id}
    if agent_id:
        tags["agent_id"] = agent_id
    try:
        mlf.update_current_trace(tags=tags, session_id=session_id or None, user=user_id or None)
    except Exception as exc:
        logger.debug("MLflow trace tag failed: %s", exc)


def _mlflow_enter_span(stack: ExitStack, name: str, attributes: dict | None,
                       *, span_type: str | None = None, trace_id: str = "") -> Any | None:
    """Enter an MLflow span on ``stack`` when the flag is on AND a trace is active.

    Autolog owns the trace root — a call outside a traced run never creates an
    orphan trace. Tags the active trace with the investigation id + ambient
    session/user/agent attribution when given (idempotent in-memory tag). String
    attributes are capped at ``_MLF_ATTR_MAX_CHARS`` (SQL text). Start failures
    degrade to None.
    """
    mlf = _mlflow()
    if mlf is None:
        return None
    try:
        if mlf.get_current_active_span() is None:
            return None
        if trace_id:
            _tag_current_trace(mlf, trace_id)
        attrs = {k: (v[:_MLF_ATTR_MAX_CHARS] if isinstance(v, str) else v)
                 for k, v in _flat_attrs(attributes or {}).items()}
        kwargs = {"span_type": span_type} if span_type else {}
        return stack.enter_context(mlf.start_span(name, attributes=attrs, **kwargs))
    except Exception as exc:
        logger.debug("MLflow span start failed: %s", exc)
        return None


def _close_span_stack(stack: ExitStack, what: str) -> None:
    """End the spans on ``stack``, letting any in-flight body exception mark them
    as errored, and never letting a span-END failure replace the body's outcome
    (a successful result must not be discarded because telemetry hiccuped)."""
    try:
        stack.__exit__(*sys.exc_info())
    except Exception as exc:
        logger.debug("%s span end failed: %s", what, exc)


@contextmanager
def mlflow_tool_span(
    name: str,
    attributes: dict | None = None,
    *,
    span_kind: str = "tool",
    span_attrs: dict | None = None,
) -> Generator[Any, None, None]:
    """A TOOL span for a unit of work (e.g. a guarded SQL execution).

    Two independent, both-optional sinks hang off this one call:
    - the MLflow TOOL span nested under the active trace — no-op unless a tracking
      URI is configured, mlflow imports, AND a trace is already active;
    - the `task_history` row (flag `obs.task_table`) — no-op unless that flag is
      on, inheriting the ambient node trace id + parenting to the enclosing span.

    Body exceptions propagate normally (both sinks record the error on exit); a
    sink's own start/end failure never reaches the caller.
    """
    stack = ExitStack()
    # Local sinks first (outermost) so their span id is the parent of anything the
    # body opens, and a body exception is recorded before it unwinds. No-op unless
    # `obs.task_table` / `obs.session_log`. trace_id="" → inherit the ambient trace.
    stack.enter_context(_obs_span(name, "", attributes, span_kind=span_kind,
                                  span_attrs=span_attrs))
    span_obj = _mlflow_enter_span(stack, name, attributes, span_type="TOOL")
    _otel_tool_span(stack, name, span_kind, attributes, span_attrs)
    try:
        yield span_obj
    finally:
        _close_span_stack(stack, "MLflow tool")


def _otel_tool_span(stack: ExitStack, name: str, span_kind: str,
                    attributes: dict | None, span_attrs: dict | None) -> None:
    """Put a tool span on the OTLP pipeline (VA-3).

    Every sink this function's caller drives was local — MLflow needs a tracking
    URI, `task_history` needs a flag, the session log needs a flag — so the eight
    call sites of :func:`mlflow_tool_span` (guarded SQL, its retries, delegation
    hops, agent evaluation) reached an external backend through **no path at all**.
    An exported trace was phases and nothing else; the work inside them was
    invisible to the very tool you would open to find out where the time went.

    A delegation hop is labelled ``invoke_agent``, not ``execute_tool``: it is the
    one span kind here that is another agent's whole run, and collapsing it into a
    tool call is what makes a delegation tree unreadable in an external viewer.
    """
    otel = _otel()
    if otel is None:
        return
    try:
        from aughor.obs import genai
        tid = _active_trace_id.get()
        if span_kind == "delegation":
            agent = str((span_attrs or {}).get("delegate_agent_name") or "").strip()
            attrs = genai.agent_attrs(agent or name.removeprefix("delegate:"))
            sname = genai.span_name(genai.OP_INVOKE_AGENT, agent) if agent else name
        else:
            # `span_kind` is only a TYPE when it says something: the default
            # "tool" would just restate the operation name.
            attrs = genai.tool_attrs(name, kind=None if span_kind == "tool" else span_kind)
            sname = name
        attrs.update(_flat_attrs({**(span_attrs or {}), **(attributes or {})}))
        stack.enter_context(otel.start_as_current_span(
            sname, context=_otel_parent(tid), attributes=attrs))
    except Exception as exc:
        logger.debug("OTel tool span start failed for %s: %s", name, exc)


# ── task_history sink (feature flag `obs.task_table`) ─────────────────────────
#
# One append-only row per span, sunk from the SAME span calls that already drive
# Langfuse/OTel/MLflow — the queryable spine of "what the agent actually did"
# (Rec 4 of the 2026-07-11 platform study). A pure SINK: strict no-op unless the
# flag is on, so an unflagged process is byte-identical (no rows written).
#
# Parent linkage + the ambient trace id ride contextvars, so:
#   • a node span (`span()`, which carries trace_id) publishes the trace id, and a
#     tool span nested inside it (`mlflow_tool_span`, which doesn't) reads it back;
#   • `parent_span_id` is the enclosing span on the stack — one call tree per run;
#   • ContextThreadPoolExecutor's `copy_context()` carries the stack into each
#     parallel wave as a COPY, so a worker's child spans never leak back to the
#     parent stack (the same structural match that makes MLflow nesting work).

_span_stack: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "aughor_task_span_stack", default=())
_active_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "aughor_task_trace_id", default="")

# Metadata keys lifted into the dedicated input/captured_output columns (in
# preference order); everything else on the span becomes labels JSON.
#
# ⚠️ Those labels land in `task_history` ONLY — the `session_events` payload carries
# just `span_kind` plus the input/output text. Anything a TRACE READER needs (the
# waterfall, the node view) has to travel on `span_attrs`, which is written into the
# payload of both the call and the result. Passing it as an ordinary attribute puts it
# in the other table, where `build_timeline` will never see it.
_INPUT_KEYS = ("input", "sql", "question", "query")
_OUTPUT_KEYS = ("captured_output", "output", "result", "row_count")


def _task_table_enabled() -> bool:
    try:
        return True
    except Exception:
        return False


def _split_span_attrs(attributes: dict | None) -> tuple[str | None, str | None, dict]:
    """Split span metadata into (input, captured_output, labels): the first present
    input/output key goes to its dedicated column (stringified + capped, since SQL
    text can be large); the remainder become labels."""
    attrs = dict(attributes or {})
    inp = outp = None
    for k in _INPUT_KEYS:
        v = attrs.get(k)
        if v not in (None, ""):
            inp = str(v)[:_MLF_ATTR_MAX_CHARS]
            attrs.pop(k, None)
            break
    for k in _OUTPUT_KEYS:
        v = attrs.get(k)
        if v not in (None, ""):
            outp = str(v)[:_MLF_ATTR_MAX_CHARS]
            attrs.pop(k, None)
            break
    return inp, outp, attrs


def _session_log_enabled() -> bool:
    try:
        from aughor.obs import session_log
        return session_log.enabled()
    except Exception:
        return False


def current_trace_id() -> str:
    """The ambient trace id, or '' when nothing has bound one."""
    return _active_trace_id.get()


@contextmanager
def bind_trace(trace_id: str) -> Generator[str, None, None]:
    """Pin ``trace_id`` as the ambient trace for the enclosed block.

    Deliberately independent of every observability flag. The trace id is a
    *correlation* fact, not a sink: binding it costs one contextvar set, and
    making it conditional is exactly the bug this fixes — the id used to be
    published only from inside the ``obs.task_table`` sink, so with that flag off
    (the default) nothing downstream could correlate at all, and on the quick
    answer path nothing bound one in the first place.

    Nested binds are honoured (innermost wins) and unwound on exit. A falsy id is
    a no-op rather than an error, so callers need not branch.
    """
    if not trace_id:
        yield _active_trace_id.get()
        return
    token = _active_trace_id.set(trace_id)
    try:
        yield trace_id
    finally:
        _active_trace_id.reset(token)


@contextmanager
def _obs_span(task: str, trace_id: str, attributes: dict | None,
              *, span_kind: str = "node",
              span_attrs: dict | None = None) -> Generator[None, None, None]:
    """One observation frame around a unit of work, driving both local sinks.

    Both sinks share ONE span id and one parent linkage — which is the reason
    they are combined rather than stacked independently: a ``session_events``
    row joins to the ``task_history`` row for the same work on ``span_id``,
    instead of two tables describing one span under two different identifiers.

    The two record different things on purpose. ``task_history`` gets a single
    row on exit (span-shaped). The session log gets ``tool_call`` on ENTRY and
    ``tool_call_result`` on exit, so work that never returns — a hang, a
    cancellation, a killed process — still leaves a call with no result, which a
    span row can never show.

    Strict no-op when both flags are off. A body exception propagates unchanged
    but is recorded first; the sinks' own failures never reach the caller —
    telemetry must not break the node it wraps.
    """
    task_table = _task_table_enabled()
    session_log_on = _session_log_enabled()
    if not (task_table or session_log_on):
        yield
        return
    span_id = uuid.uuid4().hex
    parent = _span_stack.get()
    parent_id = parent[-1] if parent else None
    tid = trace_id or _active_trace_id.get()
    tok_stack = _span_stack.set(parent + (span_id,))
    tok_tid = _active_trace_id.set(tid) if trace_id else None
    inp, _, _ = _split_span_attrs(attributes)
    if session_log_on:
        from aughor.obs import session_log as _slog
        _slog.emit(_slog.TOOL_CALL, name=task, trace_id=tid, span_id=span_id,
                   parent_span_id=parent_id,
                   payload={"span_kind": span_kind, **(span_attrs or {}),
                            **({"input": inp} if inp else {})})
    start = datetime.now(timezone.utc)
    t0 = _time.monotonic()
    err: str | None = None
    err_class: str | None = None
    try:
        yield
    except BaseException as exc:  # record the failure, then re-raise unchanged
        err = f"{type(exc).__name__}: {exc}"[:_MLF_ATTR_MAX_CHARS]
        err_class = type(exc).__name__
        raise
    finally:
        _span_stack.reset(tok_stack)
        if tok_tid is not None:
            _active_trace_id.reset(tok_tid)
        duration_ms = round((_time.monotonic() - t0) * 1000, 1)
        # Re-split at EXIT: `_split_span_attrs` copies, so a body that records
        # what it produced (`attrs["row_count"] = …`) is reflected here. Reading
        # the output at entry — before the work ran — could only ever see None.
        _, outp_attr, labels = _split_span_attrs(attributes)
        _rows = (attributes or {}).get("row_count")
        try:
            _rows = int(_rows) if _rows is not None else None
        except (TypeError, ValueError):
            _rows = None
        if task_table:
            try:
                from aughor.kernel.ledger import Ledger
                from aughor.org.context import current_org_id
                Ledger.default().task_history_insert({
                    "span_id": span_id,
                    "trace_id": tid or None,
                    "parent_span_id": parent_id,
                    "task": task,
                    "input": inp,
                    "captured_output": outp_attr,
                    "start_time": start.isoformat(),
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "duration_ms": duration_ms,
                    "error_message": err,
                    "labels": labels or None,
                    "org_id": current_org_id() or "default",
                })
            except Exception as exc:
                from aughor.kernel.errors import tolerate
                tolerate(exc, "task_history sink best-effort; the span it wraps proceeds",
                         counter="obs.task_table.sink")
        if session_log_on:
            from aughor.obs import session_log as _slog
            _slog.emit(_slog.TOOL_CALL_RESULT, name=task, trace_id=tid,
                       span_id=span_id, parent_span_id=parent_id,
                       ok=err is None, duration_ms=duration_ms, error_class=err_class,
                       row_count=_rows,
                       payload={"span_kind": span_kind, **(span_attrs or {}),
                                **({"output": outp_attr} if outp_attr else {}),
                                **({"error": err} if err else {})})


# ── Public API ────────────────────────────────────────────────────────────────

def agent_trace_stats(agent_id: str, *, limit: int = 200) -> dict | None:
    """Aggregate MLflow trace stats for a user-agent's runs (traces carry the
    ``agent_id`` tag written by :func:`_tag_current_trace`).

    Returns ``{trace_count, error_count, total_tokens, total_cost,
    latency_p50_ms, latency_p90_ms}`` — or ``None`` when tracing is off, mlflow
    is unavailable, or nothing has been logged yet. The Agent Workspace overview
    degrades to run-history-only on ``None`` (B3: MLflow is a one-directional
    dependency — the workspace works without the server). Best-effort; the tag
    filter is sanitised (our agent ids are hex, but never interpolate a quote).
    """
    mlf = _mlflow()
    if mlf is None or not agent_id:
        return None
    safe_id = agent_id.replace("'", "")
    if safe_id != agent_id:
        return None  # never seen; a quoted id can't be one of ours
    try:
        exp = mlf.get_experiment_by_name(os.getenv("AUGHOR_MLFLOW_EXPERIMENT", "aughor"))
        if exp is None:
            return None
        traces = mlf.search_traces(
            locations=[exp.experiment_id],
            filter_string=f"tags.agent_id = '{safe_id}'",
            max_results=limit, return_type="list", include_spans=False,
        )
        if not traces:
            return None
        durations: list[float] = []
        tokens = 0
        cost = 0.0
        errors = 0
        for t in traces:
            info = t.info
            d = getattr(info, "execution_duration", None) or getattr(info, "execution_time_ms", None)
            if d:
                durations.append(float(d))
            tu = getattr(info, "token_usage", None)
            if isinstance(tu, dict):
                tokens += int(tu.get("total_tokens") or tu.get("total") or 0)
            c = getattr(info, "cost", None)
            if c:
                cost += float(c)
            state = str(getattr(info, "state", "") or getattr(info, "status", ""))
            if state and "OK" not in state.upper():
                errors += 1
        durations.sort()

        def _pct(p: float) -> float | None:
            if not durations:
                return None
            return round(durations[min(len(durations) - 1, int(p * len(durations)))], 1)

        return {
            "trace_count": len(traces),
            "error_count": errors,
            "total_tokens": tokens,
            "total_cost": round(cost, 4),
            "latency_p50_ms": _pct(0.5),
            "latency_p90_ms": _pct(0.9),
        }
    except Exception as exc:
        logger.debug("agent_trace_stats failed: %s", exc)
        return None


def new_trace(investigation_id: str, question: str, connection_id: str) -> str:
    """Register a Langfuse trace for the investigation.

    Returns the trace_id to embed in AgentState and the SSE start event.
    Always returns ``investigation_id`` (even when Langfuse is disabled) so the
    frontend can use it as a stable correlation ID.

    OTel has no "create a trace" call — a trace begins with its first span. So this
    records the trace-level attributes and the next ``span()`` carries them up. The
    id is unaffected: it is derived, not allocated, so a run whose first span happens
    in a later invocation still lands on the same trace.
    """
    if _otel() is not None:
        _traces[investigation_id] = {
            _LF_TRACE_NAME: "investigation",
            _LF_TRACE_INPUT: _json_attr({"question": question, "connection_id": connection_id}),
            _LF_SESSION_ID: investigation_id,
        }
    return investigation_id


def _json_attr(value: Any) -> str:
    """A dict/list as a span-attribute string. OTel attributes are scalars, and
    Langfuse parses these fields as JSON — so a str() repr would render as an
    unparseable blob in the UI."""
    import json
    try:
        return json.dumps(value, default=str)[:_MLF_ATTR_MAX_CHARS]
    except Exception:
        return str(value)[:_MLF_ATTR_MAX_CHARS]


@contextmanager
def span(
    trace_id: str,
    name: str,
    metadata: dict | None = None,
) -> Generator[Any, None, None]:
    """Context manager that wraps work with an OTel span (which is also the Langfuse
    span — one pipeline since OA·LF-1) plus the MLflow and local-sink spans.

    Every backend is a no-op when unconfigured. The yielded value is the OTel span
    object, or ``None`` when tracing is off.
    """
    _t0 = _time.monotonic()

    # ── MLflow + OTel nested spans ─────────────────────────────────────────────
    # One ExitStack for both: MLflow (autolog owns the trace
    # root, this only nests the node span + tags the trace with the
    # investigation id) and OTel. Span START failures degrade to no-span; span
    # END failures are suppressed (`_close_span_stack`) — telemetry must never
    # break the node it wraps. A body exception propagates to the caller intact
    # while still marking the spans as errored (the old per-backend
    # `except: yield` shape re-yielded after a body throw, masking the real
    # error with a generator RuntimeError).
    _stack = ExitStack()
    # Local sinks first (outermost): push this node's span id + publish trace_id
    # for nested tool spans to inherit. No-op unless a local obs flag is on.
    _stack.enter_context(_obs_span(name, trace_id, metadata, span_kind="node"))
    _mlflow_enter_span(_stack, name, metadata, trace_id=trace_id)
    otel = _otel()
    otel_span = None
    if otel is not None:
        try:
            attrs = _flat_attrs(metadata or {})
            # The first span of a run carries the trace-level attributes new_trace
            # collected — in OTel a trace has no separate object to hang them on.
            # Popped, so exactly one span claims the root and a re-entrant node
            # cannot restate the trace's input on a child.
            pending = _traces.pop(trace_id, None) if trace_id else None
            if pending:
                attrs = {**attrs, **pending, _LF_AS_ROOT: True}
            otel_span = _stack.enter_context(
                otel.start_as_current_span(
                    name, context=_otel_parent(trace_id), attributes=attrs))
        except Exception as exc:
            logger.debug("OTel span start failed: %s", exc)
    try:
        yield otel_span
    finally:
        _close_span_stack(_stack, "telemetry")

    # ── Kernel event journal — local-first observability, on regardless of
    # Langfuse/OTel config (those are usually unconfigured in dev, which made
    # this instrumentation effectively dead; the ledger journal is always there).
    if os.environ.get("AUGHOR_KERNEL_EVENTS", "1") != "0":
        try:
            from aughor.kernel.ledger import Ledger
            Ledger.default().emit(
                "node.span",
                {"name": name, "ms": round((_time.monotonic() - _t0) * 1000, 1),
                 **(metadata or {})},
                job_id=trace_id or None,
            )
        except Exception as exc:
            logger.debug("Ledger span emit failed: %s", exc)


def log_generation(
    trace_id: str,
    name: str,
    model: str,
    *,
    backend: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    duration_ms: float | None = None,
    temperature: float | None = None,
    error_class: str | None = None,
    content: dict | None = None,
    metadata: dict | None = None,
) -> None:
    """Export one LLM call as a span. No-op when no OTLP endpoint is configured.

    This is the record that had no call sites for the whole life of the file. The
    consequence was not that model calls were traced badly — it is that a trace
    exported to Jaeger, Tempo or Langfuse contained **no model calls at all**: our
    phases arrived as spans, and the 2,506 recorded generations, their models and
    their token counts stayed in the local session log. ``_record_llm_call`` is
    now its caller, which is the single chokepoint every backend already funnels
    through.

    Two vocabularies ride the same span on purpose: Langfuse's observation keys
    (what makes it render as a model call rather than a bar) and the OTel **GenAI**
    conventions (what makes every other reader show the model, provider and token
    counts). Neither is a superset of the other, and both are cheap.

    **Content is not captured here.** ``content`` is whatever
    ``session_log.capture_prompt`` already decided to store — an operator's
    prompt-capture window is the one gate, and it is a *budget* that is spent when
    content is stored, so asking for it a second time on the export path would
    charge an operator twice for one call. Absent a window this is metadata only:
    model, provider, tokens, latency, error. That is the answer to "does turning
    on telemetry start shipping user text off-box" — only if you opened the window.

    The span is written **retroactively**: the caller already knows how long the
    call took, so ``duration_ms`` back-dates the start rather than reporting a
    zero-width span at the moment of recording. A generation with no duration is
    the shape that makes a waterfall useless.
    """
    otel = _otel()
    if otel is None or not trace_id:
        return
    try:
        from aughor.obs import genai
        attrs: dict[str, Any] = {
            _LF_OBS_TYPE: "generation",
            _LF_OBS_MODEL: model,
            **genai.generation_attrs(
                backend=backend, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                temperature=temperature, conversation_id=trace_id,
                error_class=error_class),
            **_flat_attrs(metadata or {}),
        }
        if content:
            # `capture_prompt`'s own key names, mapped onto Langfuse's input/output
            # fields so an open window is inspectable in the UI it was opened for.
            _in = {k: v for k, v in content.items()
                   if k in ("system_prompt", "user_prompt")}
            if _in:
                attrs[_LF_OBS_INPUT] = _json_attr(_in)
            if (_out := content.get("response")) is not None:
                attrs[_LF_OBS_OUTPUT] = _json_attr(_out)
        start_ns = None
        if duration_ms is not None:
            start_ns = _time.time_ns() - int(max(0.0, duration_ms) * 1_000_000)
        with otel.start_as_current_span(
            genai.span_name(genai.OP_CHAT, model) if model else (name or "chat"),
            # `_otel_parent`, not `_otel_context`: a model call runs INSIDE the
            # phase (or the delegation hop) that made it, and pinning it to the
            # trace's synthetic root instead exports it as a sibling — which is
            # how the receipt caught this, with three generations arriving as
            # roots while every unit test passed.
            context=_otel_parent(trace_id),
            attributes=attrs,
            start_time=start_ns,
        ):
            pass
    except Exception as exc:
        logger.debug("generation span failed: %s", exc)


def end_trace(trace_id: str, output: dict | None = None) -> None:
    """Finalise the trace (mark output) and force-export the buffered spans.

    In a sliced run the finalising invocation is routinely not the one that created the
    trace. That is no longer something to recover from: the trace id is derived from the
    investigation id, so this invocation addresses the same trace without ever having
    held a handle. Safe to call twice — a second call finds nothing pending and just
    flushes.

    The flush is the load-bearing part on serverless: the batch processor exports on a
    timer, and the invocation is frozen the moment it responds."""
    otel = _otel()
    pending = _traces.pop(trace_id, None)
    if otel is None:
        return
    try:
        if output:
            # A zero-duration span carrying the trace's output. Langfuse reads
            # langfuse.trace.* off any span in the trace, so this is the finalisation
            # even though the root span closed in some other invocation.
            attrs = {_LF_TRACE_OUTPUT: _json_attr(output)}
            if pending:
                attrs.update(pending)
            with otel.start_as_current_span(
                    "investigation.end", context=_otel_context(trace_id), attributes=attrs):
                pass
        flush_traces()
    except Exception as exc:
        logger.debug("Langfuse end_trace failed: %s", exc)


def node_span(name: str):
    """Decorator factory.  Wraps a LangGraph node function with a telemetry span.

    Works for both ``(state,)`` and ``(state, conn)`` node signatures.
    Reads ``trace_id`` from the state dict.  Attaches ``iteration``,
    ``hypothesis_idx``, and ``hypothesis_id`` as span metadata.

    Usage::

        @node_span("decompose")
        def decompose_question(state: AgentState) -> dict:
            ...
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(state, *args, **kwargs):
            if not isinstance(state, dict):
                return fn(state, *args, **kwargs)
            _tid = state.get("trace_id") or ""
            _idx = state.get("current_hypothesis_idx", 0)
            _hyps = state.get("hypotheses") or []
            _hid = _hyps[_idx].id if _idx < len(_hyps) else ""
            meta = {
                "iteration": state.get("iteration", 0),
                "hypothesis_idx": _idx,
                "hypothesis_id": _hid,
            }
            with span(_tid, name, meta):
                return fn(state, *args, **kwargs)
        return wrapper
    return decorator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flat_attrs(d: dict) -> dict[str, str | int | float | bool]:
    """Flatten a metadata dict to the scalar types OTel span attributes accept.

    Strings are capped at ``_MLF_ATTR_MAX_CHARS``, same as every other sink. This
    is the EXPORT path, so an uncapped value is not merely a fat row: generated SQL
    and framed questions arrive here, collectors reject or truncate oversized spans,
    and a span dropped at ingest is a hole in a trace with nothing to explain it.
    Truncation is marked rather than silent — a query that reads as complete but
    was cut is the kind of evidence that sends someone debugging the wrong thing."""
    out: dict[str, str | int | float | bool] = {}
    for k, v in d.items():
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[str(k)] = v
            continue
        text = v if isinstance(v, str) else str(v)
        if len(text) > _MLF_ATTR_MAX_CHARS:
            text = text[:_MLF_ATTR_MAX_CHARS] + "…[truncated]"
        out[str(k)] = text
    return out
