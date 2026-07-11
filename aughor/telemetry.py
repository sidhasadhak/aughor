"""Optional observability — Langfuse traces per investigation, OTel spans per node,
MLflow trace trees per run.

Activation:
  Langfuse: set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY
  OTel:     set OTEL_EXPORTER_OTLP_ENDPOINT
  MLflow:   flip the `obs.mlflow` feature flag (env AUGHOR_OBS_MLFLOW / Settings →
            System) + point AUGHOR_MLFLOW_TRACKING_URI at a server. Unlike the
            other two, MLflow owns trace *creation* via autolog (LangChain/OpenAI),
            so this module only nests node/tool spans under the active trace and
            tags it with the investigation id.

All public functions are strict no-ops when no backend is configured.
"""
from __future__ import annotations

import functools
import logging
import os
import sys
import threading
import time as _time
from contextlib import ExitStack, contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ── Langfuse ──────────────────────────────────────────────────────────────────

_lf: Any = None          # Langfuse client (None = disabled)
_lf_init_done = False
_traces: dict[str, Any] = {}  # investigation_id → Langfuse Trace object


def _langfuse() -> Any | None:
    global _lf, _lf_init_done
    if _lf_init_done:
        return _lf
    _lf_init_done = True
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not pk or not sk:
        return None
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    try:
        from langfuse import Langfuse  # type: ignore[import]
        _lf = Langfuse(public_key=pk, secret_key=sk, host=host)
        logger.info("Langfuse telemetry enabled (host=%s)", host)
    except ImportError:
        logger.debug("langfuse package not installed — Langfuse telemetry disabled")
    except Exception as exc:
        logger.warning("Langfuse init failed (telemetry disabled): %s", exc)
    return _lf


# ── OpenTelemetry ─────────────────────────────────────────────────────────────

_otel_tracer: Any = None
_otel_init_done = False


def _otel() -> Any | None:
    global _otel_tracer, _otel_init_done
    if _otel_init_done:
        return _otel_tracer
    _otel_init_done = True
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint:
        return None
    try:
        from opentelemetry import trace  # type: ignore[import]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore[import]

        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _otel_tracer = trace.get_tracer("aughor")
        logger.info("OpenTelemetry tracing enabled (endpoint=%s)", endpoint)
    except ImportError:
        logger.debug("opentelemetry packages not installed — OTel tracing disabled")
    except Exception as exc:
        logger.warning("OTel init failed (tracing disabled): %s", exc)
    return _otel_tracer


# ── MLflow (feature flag `obs.mlflow`) ────────────────────────────────────────

_mlf: Any = None
_mlf_lock = threading.Lock()
_mlf_retry_at = 0.0  # monotonic time before which a failed init is not re-attempted
_MLF_RETRY_COOLDOWN_S = 60.0
_MLF_ATTR_MAX_CHARS = 2000  # cap string span attributes (e.g. SQL text)


def _mlflow() -> Any | None:
    """The mlflow module — only when the `obs.mlflow` flag is ON and init succeeded.

    Unlike Langfuse/OTel (env-configured, checked once), the flag is
    operator-toggleable at runtime, so it is re-checked on every call (one
    kernel-ledger kv read — the house cost of a runtime flag). Init is
    lock-serialized (parallel waves must not race it) and a transient failure
    (tracking server still booting) retries after a cooldown instead of
    disabling for the process lifetime. Flipping the flag OFF after a
    successful init unpatches autolog. Every failure path degrades to None
    (tracing off), never raises.
    """
    global _mlf
    try:
        from aughor.kernel.flags import flag_enabled
        enabled = flag_enabled("obs.mlflow")
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
            "obs.mlflow is ON but the `mlflow` package is not installed — "
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
        logger.info("MLflow tracing disabled (obs.mlflow off)")


def _mlflow_enter_span(stack: ExitStack, name: str, attributes: dict | None,
                       *, span_type: str | None = None, trace_id: str = "") -> Any | None:
    """Enter an MLflow span on ``stack`` when the flag is on AND a trace is active.

    Autolog owns the trace root — a call outside a traced run never creates an
    orphan trace. Tags the active trace with the investigation id when given
    (idempotent in-memory tag). String attributes are capped at
    ``_MLF_ATTR_MAX_CHARS`` (SQL text). Start failures degrade to None.
    """
    mlf = _mlflow()
    if mlf is None:
        return None
    try:
        if mlf.get_current_active_span() is None:
            return None
        if trace_id:
            try:
                mlf.update_current_trace(tags={"investigation_id": trace_id})
            except Exception as exc:
                logger.debug("MLflow trace tag failed: %s", exc)
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
) -> Generator[Any, None, None]:
    """A TOOL span nested under the active MLflow trace (flag `obs.mlflow`).

    Strict no-op (yields None) unless the flag is on, mlflow imports, AND a
    trace is already active. Body exceptions propagate normally (the span
    records the error status on exit); span start/end failures never reach
    the caller.
    """
    stack = ExitStack()
    span_obj = _mlflow_enter_span(stack, name, attributes, span_type="TOOL")
    try:
        yield span_obj
    finally:
        _close_span_stack(stack, "MLflow tool")


# ── Public API ────────────────────────────────────────────────────────────────

def new_trace(investigation_id: str, question: str, connection_id: str) -> str:
    """Register a Langfuse trace for the investigation.

    Returns the trace_id to embed in AgentState and the SSE start event.
    Always returns ``investigation_id`` (even when Langfuse is disabled) so the
    frontend can use it as a stable correlation ID.
    """
    lf = _langfuse()
    if lf is not None:
        try:
            trace = lf.trace(
                id=investigation_id,
                name="investigation",
                input={"question": question, "connection_id": connection_id},
                tags=["aughor"],
            )
            _traces[investigation_id] = trace
        except Exception as exc:
            logger.debug("Langfuse trace creation failed: %s", exc)
    return investigation_id


@contextmanager
def span(
    trace_id: str,
    name: str,
    metadata: dict | None = None,
) -> Generator[Any, None, None]:
    """Context manager that wraps work with a Langfuse span + OTel span.

    Both are no-ops when the respective backend is unconfigured or ``trace_id``
    is empty.  The yielded value is the Langfuse span object (or ``None``).
    """
    _t0 = _time.monotonic()
    # ── Langfuse span ──────────────────────────────────────────────────────────
    lf_span = None
    if _langfuse() is not None and trace_id:
        tr = _traces.get(trace_id)
        if tr is not None:
            try:
                lf_span = tr.span(name=name, metadata=metadata or {})
            except Exception as exc:
                logger.debug("Langfuse span start failed: %s", exc)

    # ── MLflow + OTel nested spans ─────────────────────────────────────────────
    # One ExitStack for both: MLflow (flag `obs.mlflow`; autolog owns the trace
    # root, this only nests the node span + tags the trace with the
    # investigation id) and OTel. Span START failures degrade to no-span; span
    # END failures are suppressed (`_close_span_stack`) — telemetry must never
    # break the node it wraps. A body exception propagates to the caller intact
    # while still marking the spans as errored (the old per-backend
    # `except: yield` shape re-yielded after a body throw, masking the real
    # error with a generator RuntimeError).
    _stack = ExitStack()
    _mlflow_enter_span(_stack, name, metadata, trace_id=trace_id)
    otel = _otel()
    if otel is not None:
        try:
            _stack.enter_context(
                otel.start_as_current_span(name, attributes=_flat_attrs(metadata or {})))
        except Exception as exc:
            logger.debug("OTel span start failed: %s", exc)
    try:
        yield lf_span
    finally:
        _close_span_stack(_stack, "telemetry")

    # ── End Langfuse span ─────────────────────────────────────────────────────
    if lf_span is not None:
        try:
            lf_span.end()
        except Exception as exc:
            logger.debug("Langfuse span end failed: %s", exc)

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
    input_messages: list[dict],
    output: str,
    metadata: dict | None = None,
) -> None:
    """Log a single LLM call as a Langfuse generation. No-op when disabled."""
    if _langfuse() is None or not trace_id:
        return
    tr = _traces.get(trace_id)
    if tr is None:
        return
    try:
        gen = tr.generation(
            name=name,
            model=model,
            input=input_messages,
            output=output,
            metadata=metadata or {},
        )
        gen.end()
    except Exception as exc:
        logger.debug("Langfuse generation log failed: %s", exc)


def end_trace(trace_id: str, output: dict | None = None) -> None:
    """Finalise the trace (mark output) and flush the Langfuse client."""
    tr = _traces.pop(trace_id, None)
    if tr is None:
        return
    lf = _langfuse()
    if lf is None:
        return
    try:
        if output:
            tr.update(output=output)
        lf.flush()
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
    """Flatten a metadata dict to the scalar types OTel span attributes accept."""
    out: dict[str, str | int | float | bool] = {}
    for k, v in d.items():
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        else:
            out[str(k)] = str(v)
    return out
