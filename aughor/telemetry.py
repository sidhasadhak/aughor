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


def _trace_identity() -> tuple[str, str, str]:
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
        from aughor.user_agents.context import current_agent
        agent = current_agent()
        agent_id = agent.id if agent is not None else ""
    except Exception:
        agent_id = ""
    return session_id, user_id, agent_id


def _tag_current_trace(mlf: Any, trace_id: str) -> None:
    """Attribute the active trace so MLflow's Sessions / user / per-agent + cost
    views populate (E1 of the 2026-07-11 Databricks-OSS study).

    ``investigation_id`` and ``agent_id`` are TAGS (mutable, filterable); session
    and user go through ``update_current_trace``'s dedicated kwargs, which write
    the reserved ``mlflow.trace.session`` / ``mlflow.trace.user`` metadata the
    demo's Sessions and user filters key on. Idempotent, best-effort — a tagging
    failure never breaks the span it rides on.
    """
    session_id, user_id, agent_id = _trace_identity()
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
) -> Generator[Any, None, None]:
    """A TOOL span for a unit of work (e.g. a guarded SQL execution).

    Two independent, both-optional sinks hang off this one call:
    - the MLflow TOOL span nested under the active trace (flag `obs.mlflow`) —
      no-op unless that flag is on, mlflow imports, AND a trace is already active;
    - the `task_history` row (flag `obs.task_table`) — no-op unless that flag is
      on, inheriting the ambient node trace id + parenting to the enclosing span.

    Body exceptions propagate normally (both sinks record the error on exit); a
    sink's own start/end failure never reaches the caller.
    """
    stack = ExitStack()
    # task_history sink first (outermost) so its span id is the parent of anything
    # the body opens, and a body exception is recorded before it unwinds. No-op
    # unless `obs.task_table`. trace_id="" → inherit the ambient node trace id.
    stack.enter_context(_task_history_span(name, "", attributes))
    span_obj = _mlflow_enter_span(stack, name, attributes, span_type="TOOL")
    try:
        yield span_obj
    finally:
        _close_span_stack(stack, "MLflow tool")


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
_INPUT_KEYS = ("input", "sql", "question", "query")
_OUTPUT_KEYS = ("captured_output", "output", "result", "row_count")


def _task_table_enabled() -> bool:
    try:
        from aughor.kernel.flags import flag_enabled
        return flag_enabled("obs.task_table")
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


@contextmanager
def _task_history_span(task: str, trace_id: str, attributes: dict | None) -> Generator[None, None, None]:
    """Record one ``task_history`` row around the wrapped body (flag
    `obs.task_table`). Strict no-op when off. A body exception propagates
    unchanged but is first captured as ``error_message``; the sink's own failures
    (flag read, ledger write) never reach the caller — telemetry must not break
    the node it wraps."""
    if not _task_table_enabled():
        yield
        return
    span_id = uuid.uuid4().hex
    parent = _span_stack.get()
    parent_id = parent[-1] if parent else None
    tid = trace_id or _active_trace_id.get()
    tok_stack = _span_stack.set(parent + (span_id,))
    tok_tid = _active_trace_id.set(tid) if trace_id else None
    start = datetime.now(timezone.utc)
    t0 = _time.monotonic()
    err: str | None = None
    try:
        yield
    except BaseException as exc:  # record the failure, then re-raise unchanged
        err = f"{type(exc).__name__}: {exc}"[:_MLF_ATTR_MAX_CHARS]
        raise
    finally:
        _span_stack.reset(tok_stack)
        if tok_tid is not None:
            _active_trace_id.reset(tok_tid)
        try:
            inp, outp, labels = _split_span_attrs(attributes)
            from aughor.kernel.ledger import Ledger
            from aughor.org.context import current_org_id
            Ledger.default().task_history_insert({
                "span_id": span_id,
                "trace_id": tid or None,
                "parent_span_id": parent_id,
                "task": task,
                "input": inp,
                "captured_output": outp,
                "start_time": start.isoformat(),
                "end_time": datetime.now(timezone.utc).isoformat(),
                "duration_ms": round((_time.monotonic() - t0) * 1000, 1),
                "error_message": err,
                "labels": labels or None,
                "org_id": current_org_id() or "default",
            })
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "task_history sink best-effort; the span it wraps proceeds",
                     counter="obs.task_table.sink")


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
    # task_history sink first (outermost): pushes this node's span id + publishes
    # trace_id for nested tool spans to inherit. No-op unless `obs.task_table`.
    _stack.enter_context(_task_history_span(name, trace_id, metadata))
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
