"""Wave E1 — the agent-session log (`obs.session_log`).

The decision gate for this feature is one claim: **a quick /ask turn is fully
reconstructible from `session_events` alone.** Before E1 it was not — the quick
path minted no trace id at all (`telemetry.new_trace` is called in exactly one
place, inside the deep path) and its SQL bypasses the span-emitting executor, so
the most-used door in the product left no correlated record. `test_quick_ask_*`
below is that gate; the rest guard the properties it depends on.
"""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from aughor.kernel.ledger import Ledger
from aughor.obs import session_log


# ── helpers ───────────────────────────────────────────────────────────────────

def _stub_providers(monkeypatch):
    """Deterministic coder/narrator so a turn completes without a live model."""
    import aughor.llm.provider as prov
    from aughor.routers.investigations import _ChatAnswer, _PostAnswer

    class FakeCoder:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _ChatAnswer:
                return _ChatAnswer(
                    sql="SELECT * FROM (VALUES (1, 2), (3, 4)) AS t(x, y)",
                    headline="Group **A** leads")
            return response_model()

        def complete_streaming(self, *, system, user, response_model, temperature=0.0,
                               text_field, on_text):
            on_text("Group **A** leads")
            return self.complete(system=system, user=user, response_model=response_model)

    class FakeNarrator:
        def complete(self, system=None, user=None, response_model=None, temperature=0.1, **kw):
            if response_model is _PostAnswer:
                return _PostAnswer(narrative="A leads.", anomalies=[], trend="stable",
                                   confidence="high", questions=[])
            return response_model()

        def complete_streaming(self, *, system, user, response_model, temperature=0.0,
                               text_field, on_text):
            on_text("A leads.")
            return _PostAnswer(narrative="A leads.", anomalies=[], trend="stable",
                               confidence="high", questions=[])

    fakes = {"coder": FakeCoder()}
    monkeypatch.setattr(prov, "get_provider",
                        lambda role="coder", **kw: fakes.get(role, FakeNarrator()))


def _ask(client, conn_id, question, *, timeout=60):
    """POST /ask and drain the stream; returns parsed SSE frames."""
    events = []
    with client.stream("POST", "/ask", json={
        "connection_id": conn_id, "question": question, "depth": "quick",
    }) as r:
        assert r.status_code == 200, r.text
        t0 = time.monotonic()
        for line in r.iter_lines():
            if line and line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                except Exception:
                    continue
            if time.monotonic() - t0 > timeout:
                pytest.fail("/ask did not finish in time")
    return events


def _all_events(**kw):
    return Ledger.default().session_events(limit=1000, ascending=True, **kw)


@pytest.fixture(autouse=True)
def _own_the_log():
    """Each test owns the table. The kernel ledger is a session-scoped tmp DB
    shared by the whole run, so without this the log accumulates across tests and
    any global assertion silently reads someone else's events."""
    Ledger.default().session_events_clear()
    yield
    Ledger.default().session_events_clear()


# ── the decision gate ─────────────────────────────────────────────────────────

def test_quick_ask_is_reconstructible_from_session_events(
        client: TestClient, builtin_conn_id: str, monkeypatch):
    """THE gate: one quick turn, one trace, request → work → response."""
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    _stub_providers(monkeypatch)

    _ask(client, builtin_conn_id, "which group leads?")

    events = _all_events()
    assert events, "the quick path wrote no session events"

    # Exactly one run, and every event correlates to it — the property that did
    # not exist before E1 (the quick path had no trace id at all).
    traces = {e["trace_id"] for e in events}
    assert len(traces) == 1, f"expected one trace, got {traces}"

    kinds = [e["kind"] for e in events]
    assert kinds[0] == session_log.USER_REQUEST, f"run does not open with the request: {kinds}"
    assert kinds[-1] == session_log.FINAL_RESPONSE, f"run does not close with a response: {kinds}"

    req = events[0]
    assert req["payload"]["question"] == "which group leads?"
    assert req["conn_id"] == builtin_conn_id
    assert req["name"] == "ask"

    final = events[-1]
    assert final["ok"] is True
    assert final["duration_ms"] is not None and final["duration_ms"] >= 0

    # The work itself has to be in there, or "reconstructible" is a fiction: the
    # quick path calls db.execute directly rather than the guarded executor, so
    # until it was spanned the SQL that actually ran appeared nowhere.
    calls = [e for e in events if e["kind"] == session_log.TOOL_CALL]
    results = [e for e in events if e["kind"] == session_log.TOOL_CALL_RESULT]
    assert calls, "the executed SQL left no tool_call — the run is not reconstructible"
    assert {c["span_id"] for c in calls} == {r["span_id"] for r in results}, \
        "a call has no matching result"
    assert any("SELECT" in ((c["payload"] or {}).get("input") or "").upper()
               for c in calls), "no tool_call carries the SQL that ran"


def test_chat_door_is_also_covered(client: TestClient, builtin_conn_id: str, monkeypatch):
    """/chat has its own endpoint (it does not go through build_ask_stream), so it
    is wired separately — a live door left dark would defeat the purpose."""
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    _stub_providers(monkeypatch)

    with client.stream("POST", "/chat", json={
        "connection_id": builtin_conn_id, "question": "which group leads?", "mode": "ask",
    }) as r:
        assert r.status_code == 200
        for _ in r.iter_lines():
            pass

    events = _all_events()
    assert [e for e in events if e["kind"] == session_log.USER_REQUEST], "chat wrote no request event"
    assert {e["name"] for e in events if e["kind"] == session_log.USER_REQUEST} == {"chat"}


# ── the properties the gate depends on ────────────────────────────────────────

def test_flag_off_writes_nothing(client: TestClient, builtin_conn_id: str, monkeypatch):
    """Default path stays byte-identical: no flag, no rows, no minted id."""
    monkeypatch.delenv("AUGHOR_OBS_SESSION_LOG", raising=False)
    _stub_providers(monkeypatch)

    _ask(client, builtin_conn_id, "which group leads?")

    assert _all_events() == []


def test_tool_call_is_written_on_entry(monkeypatch):
    """The reason this is an event log and not a span table: work that never
    returns still leaves a call. A span row only appears after the body does."""
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from aughor import telemetry

    with telemetry.bind_trace("t-hang"):
        cm = telemetry.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"})
        cm.__enter__()          # enter and deliberately never exit (the hang case)
        mid_flight = _all_events(trace_id="t-hang")

    kinds = [e["kind"] for e in mid_flight]
    assert session_log.TOOL_CALL in kinds, "an in-flight call left no evidence"
    assert session_log.TOOL_CALL_RESULT not in kinds, "a result was recorded for work that never finished"


def test_span_ids_join_to_task_history(monkeypatch):
    """Both local sinks share one span id, so the two tables describe the same
    work under the same identifier and can be joined."""
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "1")
    from aughor import telemetry

    with telemetry.bind_trace("t-join"):
        with telemetry.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"}):
            pass

    session_spans = {e["span_id"] for e in _all_events(trace_id="t-join") if e["span_id"]}
    history_spans = {r["span_id"] for r in Ledger.default().task_history(trace_id="t-join")}
    assert session_spans, "no session span recorded"
    assert session_spans == history_spans, "the two sinks disagree on the span id"


def test_failure_records_ok_false_and_error_class(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from aughor import telemetry

    with telemetry.bind_trace("t-err"):
        with pytest.raises(ValueError):
            with telemetry.mlflow_tool_span("sql.execute", {"sql": "SELECT bad"}):
                raise ValueError("boom")

    result = [e for e in _all_events(trace_id="t-err")
              if e["kind"] == session_log.TOOL_CALL_RESULT]
    assert len(result) == 1
    assert result[0]["ok"] is False
    assert result[0]["error_class"] == "ValueError"


def test_bind_trace_is_independent_of_obs_flags(monkeypatch):
    """The trace id is a correlation fact, not a sink. Publishing it used to
    happen only inside the task_table sink, so with that flag off nothing
    downstream could correlate — that coupling was the bug."""
    monkeypatch.delenv("AUGHOR_OBS_SESSION_LOG", raising=False)
    monkeypatch.delenv("AUGHOR_OBS_TASK_TABLE", raising=False)
    from aughor import telemetry

    assert telemetry.current_trace_id() == ""
    with telemetry.bind_trace("t-bound"):
        assert telemetry.current_trace_id() == "t-bound"
        with telemetry.bind_trace("t-inner"):       # innermost wins
            assert telemetry.current_trace_id() == "t-inner"
        assert telemetry.current_trace_id() == "t-bound"
    assert telemetry.current_trace_id() == ""


def test_emit_without_a_trace_is_dropped(monkeypatch):
    """An uncorrelated row cannot be reconstructed into anything; writing it
    would make the table look healthier than it is."""
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    session_log.emit(session_log.USER_REQUEST, name="orphan")
    assert [e for e in _all_events() if e["name"] == "orphan"] == []


def test_identity_rides_the_ambient_contextvars(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from aughor import telemetry
    from aughor.org.context import reset_session_id, set_session_id

    token = set_session_id("sess-42")
    try:
        with telemetry.bind_trace("t-ident"):
            session_log.emit(session_log.USER_REQUEST, name="ask")
    finally:
        reset_session_id(token)

    events = _all_events(trace_id="t-ident")
    assert events and events[0]["session_id"] == "sess-42"


def test_folded_views_summarise_a_run(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from aughor import telemetry

    with telemetry.bind_trace("t-fold"):
        session_log.emit(session_log.USER_REQUEST, name="ask",
                         payload={"question": "why?"}, conn_id="c1")
        for ok in (True, True, False):
            session_log.emit(session_log.TOOL_CALL, name="sql.execute", span_id="s")
            session_log.emit(session_log.TOOL_CALL_RESULT, name="sql.execute",
                             span_id="s", ok=ok, duration_ms=10.0)
        session_log.emit(session_log.FINAL_RESPONSE, name="ask", ok=True, duration_ms=99.0)

    run = next(r for r in session_log.recent_sessions() if r["trace_id"] == "t-fold")
    assert run["question"] == "why?"
    assert run["tool_calls"] == 3
    assert run["ok"] is True
    assert run["duration_ms"] == 99.0

    tools = {t["tool"]: t for t in session_log.tool_reliability()}
    assert tools["sql.execute"]["calls"] == 3
    assert tools["sql.execute"]["failures"] == 1
    assert tools["sql.execute"]["failure_rate"] == pytest.approx(1 / 3, abs=0.001)


def test_retention_prunes_by_age_and_row_cap(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from aughor import telemetry

    led = Ledger.default()
    with telemetry.bind_trace("t-prune"):
        for _ in range(5):
            session_log.emit(session_log.TOOL_CALL, name="x")

    assert len(_all_events(trace_id="t-prune")) == 5
    deleted = led.session_events_prune(keep_days=0, max_rows=2)
    assert deleted == 3
    assert len(led.session_events(limit=100)) == 2


def test_prune_disabled_when_both_limits_are_zero(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from aughor import telemetry

    with telemetry.bind_trace("t-keep"):
        session_log.emit(session_log.TOOL_CALL, name="x")
    assert Ledger.default().session_events_prune(keep_days=0, max_rows=0) == 0
    assert len(_all_events(trace_id="t-keep")) == 1


def test_llm_calls_are_recorded_per_call(monkeypatch):
    """metering.record_llm sums tokens into a per-run aggregate; the per-call
    detail — which model, how long, was it the fallback — used to be discarded
    (telemetry.log_generation existed with zero call sites)."""
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from types import SimpleNamespace

    from aughor import telemetry
    from aughor.llm.provider import LLMProvider
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool = True

    class _Endpoint:
        def create_with_completion(self, **kw):
            return _Out(), SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7))

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Endpoint()))

    with telemetry.bind_trace("t-llm"):
        LLMProvider._complete_on(client, "ollama", "qwen-test", "s", "u", _Out, 0.0,
                                 role="coder")

    calls = [e for e in _all_events(trace_id="t-llm") if e["kind"] == session_log.LLM_CALL]
    assert len(calls) == 1
    p = calls[0]["payload"]
    assert calls[0]["name"] == "qwen-test"
    assert (p["backend"], p["role"], p["model"]) == ("ollama", "coder", "qwen-test")
    assert (p["prompt_tokens"], p["completion_tokens"], p["total_tokens"]) == (11, 7, 18)
    assert p["fallback"] is False
    assert calls[0]["duration_ms"] is not None


def test_fallback_model_swap_is_visible(monkeypatch):
    """The silent Anthropic fallback can change the model mid-run, which would
    quietly invalidate any measurement attributing the result to the primary."""
    monkeypatch.setenv("AUGHOR_OBS_SESSION_LOG", "1")
    from types import SimpleNamespace

    from aughor import telemetry
    from aughor.llm.provider import LLMProvider
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool = True

    class _Messages:
        def create_with_completion(self, **kw):
            return _Out(), SimpleNamespace(
                usage=SimpleNamespace(input_tokens=3, output_tokens=2))

    client = SimpleNamespace(messages=_Messages())

    with telemetry.bind_trace("t-fb"):
        LLMProvider._complete_on(client, "anthropic", "claude-x", "s", "u", _Out, 0.0,
                                 role="coder", fallback=True)

    call = [e for e in _all_events(trace_id="t-fb") if e["kind"] == session_log.LLM_CALL][0]
    assert call["payload"]["fallback"] is True
    assert call["payload"]["model"] == "claude-x"


def test_journal_events_carry_the_ambient_trace(monkeypatch):
    """All ~29 event kinds correlate at once because emit() defaults trace_id
    from the ambient run — no call site was touched. Before this, `node.span`
    smuggled the trace into job_id and nothing else in the journal correlated."""
    from aughor import telemetry

    led = Ledger.default()
    with telemetry.bind_trace("t-journal"):
        led.emit("monitor.alert", {"metric": "revenue"})
    led.emit("api.started")   # outside any run → uncorrelated, and that is honest

    correlated = led.events(trace_id="t-journal", limit=20)
    assert [e["kind"] for e in correlated] == ["monitor.alert"]
    assert all(e["trace_id"] == "t-journal" for e in correlated)


def test_audited_sql_carries_the_ambient_trace(monkeypatch, tmp_path):
    """audit_log sees EVERY execution, including the quick path that bypasses the
    span-emitting executor — so it is where "which run ran this SQL" becomes
    answerable for all paths at once."""
    monkeypatch.setenv("AUGHOR_AUDIT_DB", str(tmp_path / "audit.db"))
    import importlib

    from aughor import telemetry
    from aughor.security import audit as audit_mod
    importlib.reload(audit_mod)

    with telemetry.bind_trace("t-sql"):
        audit_mod.AuditLogger.log(connection_id="c1", sql="SELECT 1", row_count=1)

    row = audit_mod.AuditLogger.recent(limit=1)[0]
    assert row["trace_id"] == "t-sql"


def test_session_events_is_queryable_as_an_ops_table():
    """The table joins the curated aughor_ops surface, so Deep Analysis can
    investigate the agent's own behaviour with NL2SQL — the same one-line move
    task_history already proved."""
    from aughor.db.connection import AughorOpsConnection
    assert "session_events" in AughorOpsConnection._OPS_TABLES
