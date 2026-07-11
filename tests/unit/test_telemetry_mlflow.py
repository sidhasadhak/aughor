"""
Unit tests for the MLflow leg of aughor.telemetry (feature flag `obs.mlflow`).

Hermetic: the mlflow package is stubbed via sys.modules — no server, no real
dependency. The contract under test:

- flag OFF  → strict no-op: no import attempt, span()/mlflow_tool_span behave
  exactly as before (byte-identical default path).
- flag ON, package missing → graceful degrade (one init attempt, no raise).
- flag ON, transient init failure (server booting) → cooldown retry, NOT a
  process-lifetime disable.
- flag ON, package present → init once under a lock (experiment + autologs),
  node spans nest under an ACTIVE trace only, the trace is tagged with the
  investigation id, TOOL spans wrap execution, body exceptions propagate,
  and a span-END failure never replaces the body's outcome.
- flag toggled OFF after init → autolog is unpatched (no more trace export).

The real-package integration test lives at the bottom, skipped unless mlflow
is installed (uv sync --extra observability); it cleans up its global state
(autolog patches, tracking URI) so the rest of the suite is unaffected.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

import aughor.telemetry as tel


# ── Helpers ───────────────────────────────────────────────────────────────────

class _StubSpan:
    def __init__(self, name, span_type=None, attributes=None):
        self.name = name
        self.span_type = span_type
        self.attributes = attributes or {}
        self.entered = False
        self.exited = False
        self.exc_type = None
        self.exit_raises = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exited = True
        self.exc_type = exc_type
        if self.exit_raises:
            raise RuntimeError("span end blew up")
        return False


def _make_stub(active: bool = True) -> types.ModuleType:
    """A minimal mlflow stand-in recording every interaction."""
    m = types.ModuleType("mlflow")
    m.calls = {"experiment": [], "autolog": [], "autolog_disable": [],
               "spans": [], "tags": [], "identity": [], "uri": []}

    m.set_tracking_uri = lambda uri: m.calls["uri"].append(uri)
    m.get_tracking_uri = lambda: "stub://tracking"
    m.set_experiment = lambda name: m.calls["experiment"].append(name)

    class _Flavor:
        def __init__(self, calls):
            self._calls = calls

        def autolog(self, disable=False):
            self._calls["autolog_disable" if disable else "autolog"].append(1)

    m.langchain = _Flavor(m.calls)
    m.openai = _Flavor(m.calls)
    m.get_current_active_span = lambda: object() if active else None

    def start_span(name, span_type=None, attributes=None):
        s = _StubSpan(name, span_type, attributes)
        m.calls["spans"].append(s)
        return s

    m.start_span = start_span

    def _update_current_trace(tags=None, session_id=None, user=None, **_):
        m.calls["tags"].append(tags)
        m.calls["identity"].append({"session_id": session_id, "user": user})

    m.update_current_trace = _update_current_trace
    return m


@pytest.fixture(autouse=True)
def _fresh_mlflow_state(monkeypatch):
    """Reset the module-level lazy-init state so each test starts cold, and keep
    the init's os.environ.setdefault writes from leaking across tests."""
    monkeypatch.setattr(tel, "_mlf", None)
    monkeypatch.setattr(tel, "_mlf_retry_at", 0.0)
    for k in ("MLFLOW_HTTP_REQUEST_TIMEOUT", "MLFLOW_HTTP_REQUEST_MAX_RETRIES"):
        monkeypatch.delenv(k, raising=False)
    yield
    tel._mlf = None
    tel._mlf_retry_at = 0.0
    for k in ("MLFLOW_HTTP_REQUEST_TIMEOUT", "MLFLOW_HTTP_REQUEST_MAX_RETRIES"):
        os.environ.pop(k, None)


def _set_flag(monkeypatch, value: bool):
    import aughor.kernel.flags as flags
    monkeypatch.setattr(
        flags, "flag_enabled",
        lambda name: value if name == "obs.mlflow" else False,
    )


# ── Flag OFF: byte-identical default path ────────────────────────────────────

def test_flag_off_no_init_attempt(monkeypatch):
    _set_flag(monkeypatch, False)
    exploding = types.ModuleType("mlflow")  # any attribute access would AttributeError
    monkeypatch.setitem(sys.modules, "mlflow", exploding)
    with tel.mlflow_tool_span("sql.execute", {"query_id": "q1"}) as s:
        assert s is None
    assert tel._mlf is None  # never imported/initialized


def test_flag_off_span_still_works(monkeypatch):
    _set_flag(monkeypatch, False)
    with tel.span("inv-1", "decompose", {"iteration": 0}) as lf:
        assert lf is None  # Langfuse unconfigured, MLflow off — unchanged


def test_flag_off_span_body_exception_propagates(monkeypatch):
    _set_flag(monkeypatch, False)
    with pytest.raises(ValueError, match="node blew"):
        with tel.span("inv-1", "decompose", {}):
            raise ValueError("node blew")


# ── Flag ON, package missing ──────────────────────────────────────────────────

def test_missing_package_degrades_gracefully(monkeypatch):
    _set_flag(monkeypatch, True)
    monkeypatch.setitem(sys.modules, "mlflow", None)  # import mlflow → ImportError
    with tel.mlflow_tool_span("sql.execute") as s:
        assert s is None
    assert tel._mlf is None
    assert tel._mlf_retry_at == float("inf")  # permanent: package can't appear later
    with tel.mlflow_tool_span("sql.execute") as s2:  # no re-attempt storm
        assert s2 is None


# ── Flag ON, transient init failure → cooldown retry ──────────────────────────

def test_init_failure_retries_after_cooldown(monkeypatch):
    _set_flag(monkeypatch, True)
    stub = _make_stub()
    boots = {"n": 0}

    def _flaky_set_experiment(name):
        boots["n"] += 1
        if boots["n"] == 1:
            raise ConnectionError("tracking server still booting")
        stub.calls["experiment"].append(name)

    stub.set_experiment = _flaky_set_experiment
    monkeypatch.setitem(sys.modules, "mlflow", stub)

    with tel.mlflow_tool_span("sql.execute") as s:
        assert s is None  # first attempt failed
    assert tel._mlf is None and tel._mlf_retry_at > 0
    with tel.mlflow_tool_span("sql.execute") as s:
        assert s is None  # inside cooldown: no second attempt
    assert boots["n"] == 1
    tel._mlf_retry_at = 0.0  # cooldown elapsed
    with tel.mlflow_tool_span("sql.execute") as s:
        assert s is not None  # recovered without a process restart
    assert boots["n"] == 2


def test_init_bounds_http_retries(monkeypatch):
    """Init must cap mlflow's HTTP timeout/retries so a dead server can't stall
    the answer path for minutes — but an operator's explicit values win."""
    _set_flag(monkeypatch, True)
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_TIMEOUT", "30")
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    with tel.mlflow_tool_span("sql.execute"):
        pass
    assert os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] == "30"  # respected
    assert os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] == "1"  # defaulted


# ── Flag ON, stubbed package ──────────────────────────────────────────────────

def test_init_sets_experiment_and_autologs_once(monkeypatch):
    _set_flag(monkeypatch, True)
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    monkeypatch.setenv("AUGHOR_MLFLOW_TRACKING_URI", "http://mlflow.test:5001")
    with tel.mlflow_tool_span("sql.execute"):
        pass
    with tel.mlflow_tool_span("sql.execute"):
        pass
    assert stub.calls["uri"] == ["http://mlflow.test:5001"]
    assert stub.calls["experiment"] == ["aughor"]
    assert len(stub.calls["autolog"]) == 2  # langchain + openai, once each


def test_tool_span_wraps_with_tool_type(monkeypatch):
    _set_flag(monkeypatch, True)
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    with tel.mlflow_tool_span("sql.execute", {"query_id": "q1", "sql": "SELECT 1"}) as s:
        assert s is not None and s.entered
    assert s.exited
    assert s.span_type == "TOOL"
    assert s.attributes["query_id"] == "q1"
    assert s.attributes["sql"] == "SELECT 1"


def test_long_string_attributes_are_capped(monkeypatch):
    _set_flag(monkeypatch, True)
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    big_sql = "SELECT " + "x" * 10_000
    with tel.mlflow_tool_span("sql.execute", {"sql": big_sql}):
        pass
    (s,) = stub.calls["spans"]
    assert len(s.attributes["sql"]) == tel._MLF_ATTR_MAX_CHARS


def test_no_active_trace_means_no_orphan_span(monkeypatch):
    """Outside a traced run (no autolog root), nothing is created."""
    _set_flag(monkeypatch, True)
    stub = _make_stub(active=False)
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    with tel.mlflow_tool_span("sql.execute") as s:
        assert s is None
    with tel.span("inv-2", "decompose", {}):
        pass
    assert stub.calls["spans"] == []
    assert stub.calls["tags"] == []


def test_span_nests_and_tags_investigation(monkeypatch):
    _set_flag(monkeypatch, True)
    stub = _make_stub(active=True)
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    with tel.span("inv-3", "decompose", {"iteration": 0}):
        pass
    with tel.span("inv-3", "baseline", {"iteration": 1}):
        pass
    names = [s.name for s in stub.calls["spans"]]
    assert names == ["decompose", "baseline"]
    # Tagged (idempotently) with the investigation id — a resumed run's new
    # MLflow trace is therefore tagged too, with no bookkeeping state.
    assert stub.calls["tags"] == [{"investigation_id": "inv-3"}] * 2
    # No session/user/agent set → no attribution beyond the investigation id.
    assert stub.calls["identity"] == [{"session_id": None, "user": None}] * 2
    assert all(s.exited for s in stub.calls["spans"])


def test_trace_tagged_with_ambient_session_user_agent(monkeypatch):
    """session/user/agent live on request-scoped contextvars; the seam attributes
    the trace to them ambiently (nothing threaded through span()). agent_id is a
    tag; session/user go through update_current_trace's dedicated kwargs."""
    import types as _types

    from aughor.org.context import (reset_session_id, reset_user_id,
                                    set_session_id, set_user_id)
    from aughor.user_agents.context import activate_agent, release_agent

    _set_flag(monkeypatch, True)
    stub = _make_stub(active=True)
    monkeypatch.setitem(sys.modules, "mlflow", stub)

    st = set_session_id("sess-1")
    su = set_user_id("user-1")
    tok = activate_agent(_types.SimpleNamespace(id="churn"))
    try:
        with tel.span("inv-9", "decompose", {}):
            pass
    finally:
        release_agent(tok)
        reset_user_id(su)
        reset_session_id(st)

    assert stub.calls["tags"] == [{"investigation_id": "inv-9", "agent_id": "churn"}]
    assert stub.calls["identity"] == [{"session_id": "sess-1", "user": "user-1"}]


def test_body_exception_propagates_and_marks_span(monkeypatch):
    _set_flag(monkeypatch, True)
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    with pytest.raises(ValueError, match="boom"):
        with tel.mlflow_tool_span("sql.execute"):
            raise ValueError("boom")
    (s,) = stub.calls["spans"]
    assert s.exited and s.exc_type is ValueError


def test_span_end_failure_never_discards_the_result(monkeypatch):
    """A span whose END raises must not replace the body's outcome — the exact
    executor scenario: a successful conn.execute result must survive."""
    _set_flag(monkeypatch, True)
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    result = None
    with tel.mlflow_tool_span("sql.execute") as s:
        s.exit_raises = True
        result = "rows"
    assert result == "rows"  # no exception escaped span end
    # And in span():
    with tel.span("inv-6", "decompose", {}) as lf:
        stub.calls["spans"][-1].exit_raises = True
        assert lf is None  # completes without raising


def test_body_exception_not_masked_by_end_failure(monkeypatch):
    """The body's real error must win even when the span end ALSO fails."""
    _set_flag(monkeypatch, True)
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    with pytest.raises(ValueError, match="real error"):
        with tel.mlflow_tool_span("sql.execute") as s:
            s.exit_raises = True
            raise ValueError("real error")


def test_broken_mlflow_api_never_breaks_caller(monkeypatch):
    """A backend that raises on span start must not affect the wrapped work."""
    _set_flag(monkeypatch, True)
    stub = _make_stub()

    def _explode(*a, **k):
        raise RuntimeError("server down")

    stub.start_span = _explode
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    with tel.mlflow_tool_span("sql.execute") as s:
        assert s is None  # degraded, not raised
    with tel.span("inv-4", "decompose", {}) as lf:
        assert lf is None  # span() path equally shielded


def test_runtime_toggle_off_unpatches_autolog(monkeypatch):
    """Flag flipped off at runtime → spans stop AND autolog is disabled, so
    trace export does not silently continue after the operator opted out."""
    import aughor.kernel.flags as flags
    stub = _make_stub()
    monkeypatch.setitem(sys.modules, "mlflow", stub)
    state = {"on": True}
    monkeypatch.setattr(
        flags, "flag_enabled",
        lambda name: state["on"] if name == "obs.mlflow" else False,
    )
    with tel.mlflow_tool_span("sql.execute") as s:
        assert s is not None
    state["on"] = False
    with tel.mlflow_tool_span("sql.execute") as s2:
        assert s2 is None
    assert len(stub.calls["spans"]) == 1
    assert len(stub.calls["autolog_disable"]) == 2  # both flavors unpatched
    # Re-enabling re-initializes cleanly.
    state["on"] = True
    with tel.mlflow_tool_span("sql.execute") as s3:
        assert s3 is not None
    assert len(stub.calls["autolog"]) == 4  # re-patched


# ── executor wiring ───────────────────────────────────────────────────────────

def test_executor_emits_tool_span(monkeypatch):
    """execute_guarded routes its execute through mlflow_tool_span (name + attrs)."""
    _set_flag(monkeypatch, True)
    stub = _make_stub(active=True)
    monkeypatch.setitem(sys.modules, "mlflow", stub)

    from aughor.platform.contracts.execution import QueryResult

    class _Conn:
        dialect = "duckdb"

        def execute(self, query_id, sql):
            return QueryResult(hypothesis_id=query_id, sql=sql,
                               columns=["n"], rows=[[1]], row_count=1, error=None)

    from aughor.sql.executor import execute_guarded
    result = execute_guarded(_Conn(), "SELECT 1 AS n", query_id="q-obs")
    assert result.row_count == 1
    names = [s.name for s in stub.calls["spans"]]
    assert "sql.execute" in names
    s = stub.calls["spans"][names.index("sql.execute")]
    assert s.attributes["query_id"] == "q-obs"
    assert s.attributes["dialect"] == "duckdb"
    assert "SELECT 1" in s.attributes["sql"]


# ── Real-package integration (skipped unless installed) ──────────────────────

def test_real_mlflow_trace_roundtrip(monkeypatch, tmp_path):
    """Against the real package: nest under a real active trace, tag it, read it
    back. Cleans up its global side effects (autolog patches, tracking URI) so
    the rest of a shared-process suite is unaffected."""
    mlflow = pytest.importorskip("mlflow", minversion="3.0")
    _set_flag(monkeypatch, True)
    # Traces export through an async queue by default — the write races the
    # read-back below. Synchronous export keeps this test deterministic.
    monkeypatch.setenv("MLFLOW_ENABLE_ASYNC_TRACE_LOGGING", "false")
    # A plain-path FILE store — mlflow-skinny has no SQLAlchemy, so sqlite:///
    # URIs don't exist in a fresh env (CI caught exactly that), and MLflow
    # ≥3.14 gates the filesystem backend behind an env opt-out.
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.setenv("AUGHOR_MLFLOW_TRACKING_URI", str(tmp_path / "mlruns"))
    monkeypatch.setenv("AUGHOR_MLFLOW_EXPERIMENT", "aughor-test")

    import types as _types

    from aughor.org.context import (reset_session_id, reset_user_id,
                                    set_session_id, set_user_id)
    from aughor.user_agents.context import activate_agent, release_agent

    prev_uri = mlflow.get_tracking_uri()
    st = set_session_id("sess-int")
    su = set_user_id("user-int")
    tok = activate_agent(_types.SimpleNamespace(id="agent-int"))
    try:
        # Simulate the autolog-owned root; our legs nest inside it.
        with tel.span("inv-int", "warmup", {}):  # triggers lazy init
            pass
        with mlflow.start_span(name="investigation"):
            with tel.span("inv-int", "decompose", {"iteration": 0}):
                with tel.mlflow_tool_span("sql.execute", {"query_id": "q1",
                                                          "sql": "SELECT 1"}):
                    pass

        trace_id = mlflow.get_last_active_trace_id()
        assert trace_id is not None
        trace = mlflow.MlflowClient().get_trace(trace_id)
        span_names = {s.name for s in trace.data.spans}
        assert {"investigation", "decompose", "sql.execute"} <= span_names
        assert trace.info.tags.get("investigation_id") == "inv-int"
        # Ambient attribution landed on the REAL trace (silent-no-op catcher —
        # a wrong update_current_trace kwarg would be swallowed in prod).
        assert trace.info.tags.get("agent_id") == "agent-int"
        meta = dict(getattr(trace.info, "trace_metadata", None)
                    or getattr(trace.info, "request_metadata", {}) or {})
        assert meta.get("mlflow.trace.session") == "sess-int"
        assert meta.get("mlflow.trace.user") == "user-int"
    finally:
        tel._mlflow_disable()  # unpatch autolog for the rest of the suite
        mlflow.set_tracking_uri(prev_uri)
        release_agent(tok)
        reset_user_id(su)
        reset_session_id(st)
