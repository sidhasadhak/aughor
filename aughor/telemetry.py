"""Optional observability — Langfuse traces per investigation, OTel spans per node.

Activation:
  Langfuse: set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY
  OTel:     set OTEL_EXPORTER_OTLP_ENDPOINT

All public functions are strict no-ops when neither backend is configured.
"""
from __future__ import annotations

import functools
import logging
import os
from contextlib import contextmanager
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
    # ── Langfuse span ──────────────────────────────────────────────────────────
    lf_span = None
    if _langfuse() is not None and trace_id:
        tr = _traces.get(trace_id)
        if tr is not None:
            try:
                lf_span = tr.span(name=name, metadata=metadata or {})
            except Exception as exc:
                logger.debug("Langfuse span start failed: %s", exc)

    # ── OTel span ─────────────────────────────────────────────────────────────
    otel = _otel()
    if otel is not None:
        try:
            with otel.start_as_current_span(name, attributes=_flat_attrs(metadata or {})):
                yield lf_span
        except Exception:
            yield lf_span
    else:
        yield lf_span

    # ── End Langfuse span ─────────────────────────────────────────────────────
    if lf_span is not None:
        try:
            lf_span.end()
        except Exception as exc:
            logger.debug("Langfuse span end failed: %s", exc)


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
