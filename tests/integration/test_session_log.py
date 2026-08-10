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
def _own_the_log(monkeypatch):
    """Each test owns the table AND the capture window. The kernel ledger is a
    session-scoped tmp DB shared by the whole run, so without this the log
    accumulates across tests and any global assertion silently reads someone
    else's events. The window lives in the same ledger and is just as leaky: one
    left open would silently record prompt CONTENT into a later test's payloads.

    It owns the FLAG state for the same reason. These tests reconstruct a quick `/ask`
    turn from what the fast path logs; with `ask.converse` on, the converse body serves
    that turn and logs a different shape, so the assertions describe a door the run is
    not using. Pinned off explicitly — `route_mix` above is precisely the reader that
    counts BOTH shapes, and it sets its own events rather than driving a live turn."""
    from aughor.obs import prompt_window

    monkeypatch.delenv("AUGHOR_ASK_CONVERSE", raising=False)
    Ledger.default().session_events_clear()
    prompt_window.close_window()
    yield
    Ledger.default().session_events_clear()
    prompt_window.close_window()


# ── the decision gate ─────────────────────────────────────────────────────────

def test_quick_ask_is_reconstructible_from_session_events(
        client: TestClient, builtin_conn_id: str, monkeypatch):
    """THE gate: one quick turn, one trace, request → work → response."""
    _stub_providers(monkeypatch)

    _ask(client, builtin_conn_id, "which group leads?")

    all_events = _all_events()
    assert all_events, "the quick path wrote no session events"

    # The ask mints exactly ONE run — the property that did not exist before E1 (the
    # quick path had no trace id at all). Identified by its own user_request rather
    # than by owning the whole store: a background scheduler tick landing mid-test
    # would otherwise read as "the ask minted two traces", which is a different and
    # false claim (it has flaked exactly that way twice).
    opens = [e for e in all_events if e["kind"] == session_log.USER_REQUEST]
    assert len(opens) == 1, f"expected one ask run, got {[e['trace_id'] for e in opens]}"
    trace = opens[0]["trace_id"]
    events = [e for e in all_events if e["trace_id"] == trace]

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

def test_tool_call_is_written_on_entry(monkeypatch):
    """The reason this is an event log and not a span table: work that never
    returns still leaves a call. A span row only appears after the body does."""
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
    from aughor import telemetry

    with telemetry.bind_trace("t-join"):
        with telemetry.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"}):
            pass

    session_spans = {e["span_id"] for e in _all_events(trace_id="t-join") if e["span_id"]}
    history_spans = {r["span_id"] for r in Ledger.default().task_history(trace_id="t-join")}
    assert session_spans, "no session span recorded"
    assert session_spans == history_spans, "the two sinks disagree on the span id"


def test_failure_records_ok_false_and_error_class(monkeypatch):
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
    # Forced OFF explicitly: since CR0 the session log defaults on, and this
    # test's claim is precisely that binding works with the sinks off.
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
    session_log.emit(session_log.USER_REQUEST, name="orphan")
    assert [e for e in _all_events() if e["name"] == "orphan"] == []


def test_identity_rides_the_ambient_contextvars(monkeypatch):
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
    from aughor import telemetry

    with telemetry.bind_trace("t-keep"):
        session_log.emit(session_log.TOOL_CALL, name="x")
    assert Ledger.default().session_events_prune(keep_days=0, max_rows=0) == 0
    assert len(_all_events(trace_id="t-keep")) == 1


def test_llm_calls_are_recorded_per_call(monkeypatch):
    """metering.record_llm sums tokens into a per-run aggregate; the per-call
    detail — which model, how long, was it the fallback — used to be discarded
    (telemetry.log_generation existed with zero call sites)."""
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
    call = calls[0]
    # Real columns, not payload JSON — "tokens by model" must be a GROUP BY.
    assert (call["provider"], call["model"]) == ("ollama", "qwen-test")
    assert (call["prompt_tokens"], call["completion_tokens"], call["total_tokens"]) == (11, 7, 18)
    assert call["ok"] is True
    assert call["duration_ms"] is not None
    assert call["payload"]["role"] == "coder"
    assert call["payload"]["fallback"] is False


def test_fallback_model_swap_is_visible(monkeypatch):
    """The silent Anthropic fallback can change the model mid-run, which would
    quietly invalidate any measurement attributing the result to the primary."""
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
    assert (call["provider"], call["model"]) == ("anthropic", "claude-x")
    assert (call["prompt_tokens"], call["completion_tokens"]) == (3, 2)


def test_failed_llm_call_is_recorded(monkeypatch):
    """The record used to be written only after the call returned, so a model
    that failed past its retries left NO row — making "which model fails"
    unanswerable exactly when it matters."""
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "0")
    from types import SimpleNamespace

    from aughor import telemetry
    from aughor.llm.provider import LLMProvider
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool = True

    class _Endpoint:
        def create_with_completion(self, **kw):
            raise RuntimeError("model exploded")

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Endpoint()))

    with telemetry.bind_trace("t-llm-fail"):
        with pytest.raises(RuntimeError):
            LLMProvider._complete_on(client, "ollama", "qwen-test", "s", "u", _Out, 0.0,
                                     role="coder")

    call = [e for e in _all_events(trace_id="t-llm-fail")
            if e["kind"] == session_log.LLM_CALL][0]
    assert call["ok"] is False
    assert call["error_class"] == "RuntimeError"
    assert call["model"] == "qwen-test"
    # Unknown, not zero — the call never got far enough to report usage.
    assert call["prompt_tokens"] is None
    assert call["total_tokens"] is None


def test_unreported_usage_is_null_not_zero(monkeypatch):
    """Several local backends omit usage entirely. Folding that into 0 makes
    every cost aggregate quietly wrong, so it stays NULL and says so."""
    from types import SimpleNamespace

    from aughor import telemetry
    from aughor.llm.provider import LLMProvider
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool = True

    class _Endpoint:
        def create_with_completion(self, **kw):
            return _Out(), SimpleNamespace(usage=None)   # backend reported nothing

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Endpoint()))

    with telemetry.bind_trace("t-nousage"):
        LLMProvider._complete_on(client, "ollama", "local-model", "s", "u", _Out, 0.0,
                                 role="coder")

    call = [e for e in _all_events(trace_id="t-nousage")
            if e["kind"] == session_log.LLM_CALL][0]
    assert call["prompt_tokens"] is None and call["completion_tokens"] is None
    assert call["total_tokens"] is None
    assert call["payload"]["usage_reported"] is False


def test_retries_are_counted(monkeypatch):
    """A model that only ever succeeds on its second attempt used to look
    identical to one that never struggles — the count was local and discarded."""
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "3")
    from types import SimpleNamespace

    from aughor import telemetry
    from aughor.llm import provider as prov
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool = True

    calls = {"n": 0}

    class _Endpoint:
        def create_with_completion(self, **kw):
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("request timed out")   # _is_transient → retried
            return _Out(), SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))

    monkeypatch.setattr(prov.time, "sleep", lambda _s: None)   # no real backoff
    client = SimpleNamespace(chat=SimpleNamespace(completions=_Endpoint()))

    with telemetry.bind_trace("t-retry"):
        prov.LLMProvider._complete_on(client, "ollama", "qwen-test", "s", "u", _Out, 0.0,
                                      role="coder")

    call = [e for e in _all_events(trace_id="t-retry")
            if e["kind"] == session_log.LLM_CALL][0]
    assert call["ok"] is True
    assert call["retries"] == 2, "a call that needed two retries reported none"


def test_tool_results_carry_row_count(monkeypatch):
    """"The query ran" and "the query returned nothing" are different facts, and
    the zero-row case is usually the interesting one."""
    from aughor import telemetry

    with telemetry.bind_trace("t-rows"):
        attrs = {"sql": "SELECT 1", "query_id": "chat"}
        with telemetry.mlflow_tool_span("sql.execute", attrs):
            attrs["row_count"] = 0          # the body reports what it produced

    result = [e for e in _all_events(trace_id="t-rows")
              if e["kind"] == session_log.TOOL_CALL_RESULT][0]
    assert result["ok"] is True
    assert result["row_count"] == 0, "a zero-row result is indistinguishable from unknown"


def test_final_response_captures_the_answer(
        client: TestClient, builtin_conn_id: str, monkeypatch):
    """A run whose output was never captured cannot become a test case — which is
    what the rest of this arc needs from the log."""
    _stub_providers(monkeypatch)

    _ask(client, builtin_conn_id, "which group leads?")

    final = _all_events()[-1]
    assert final["kind"] == session_log.FINAL_RESPONSE
    assert "leads" in (final["payload"] or {}).get("headline", ""), \
        "the answer itself was not recorded"


def _one_llm_call(trace: str, *, system="SYS", user="USER"):
    """Drive one successful model call and return its recorded event."""
    from types import SimpleNamespace

    from aughor import telemetry
    from aughor.llm.provider import LLMProvider
    from pydantic import BaseModel

    class _Out(BaseModel):
        answer: str = "forty-two"

    class _Endpoint:
        def create_with_completion(self, **kw):
            return _Out(), SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2))

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Endpoint()))
    with telemetry.bind_trace(trace):
        LLMProvider._complete_on(client, "ollama", "m", system, user, _Out, 0.0, role="coder")
    return [e for e in _all_events(trace_id=trace) if e["kind"] == session_log.LLM_CALL][0]


def _open_capture(calls: int = 20):
    """Open a prompt-capture window for the test and guarantee it is closed after."""
    from aughor.obs import prompt_window
    prompt_window.open_window(calls=calls, minutes=5, opened_by="test")
    return prompt_window


def test_prompt_capture_off_by_default(monkeypatch):
    """The session log is metadata by default. Content is a separate decision
    with a different blast radius, so it needs its own deliberate window."""
    from aughor.obs import prompt_window
    prompt_window.close_window()

    payload = _one_llm_call("t-nocapture")["payload"]
    assert "system_prompt" not in payload
    assert "user_prompt" not in payload
    assert "response" not in payload
    assert payload["role"] == "coder"     # metadata still recorded


def test_prompt_capture_records_content_while_a_window_is_open(monkeypatch):
    pw = _open_capture()
    try:
        payload = _one_llm_call("t-capture", system="SCHEMA CONTEXT", user="why did revenue drop?")
        assert payload["payload"]["system_prompt"] == "SCHEMA CONTEXT"
        assert payload["payload"]["user_prompt"] == "why did revenue drop?"
        assert "forty-two" in payload["payload"]["response"]
    finally:
        pw.close_window()


def test_a_window_closes_itself_once_its_budget_is_spent(monkeypatch):
    """The whole point of replacing the standing flag: capture stops on its own.
    A budget of one means the SECOND call stores metadata only."""
    pw = _open_capture(calls=1)
    try:
        first = _one_llm_call("t-window-1", system="SYS", user="USER")["payload"]
        second = _one_llm_call("t-window-2", system="SYS", user="USER")["payload"]
        assert first["system_prompt"] == "SYS"
        assert "system_prompt" not in second        # budget spent → content stops
        assert second["role"] == "coder"            # metadata keeps flowing
        assert pw.active() is False                 # and the window is gone, not zombie
    finally:
        pw.close_window()


def test_truncated_prompts_say_so(monkeypatch):
    """A silently shortened prompt reproduces a different call than the one that
    ran — worse than not capturing it, because it looks authoritative."""
    monkeypatch.setenv("AUGHOR_OBS_PROMPT_MAX_CHARS", "10")
    pw = _open_capture()
    try:
        payload = _one_llm_call("t-trunc", system="x" * 500, user="short")["payload"]
        assert payload["system_prompt"] == "x" * 10
        assert payload["system_prompt_truncated"] is True
        assert "user_prompt_truncated" not in payload     # fit, so unmarked
    finally:
        pw.close_window()


def test_failed_call_still_captures_the_prompt(monkeypatch):
    """The failing call is precisely the one you want to reproduce."""
    monkeypatch.setenv("AUGHOR_LLM_MAX_RETRIES", "0")
    _open_capture()
    from types import SimpleNamespace

    from aughor import telemetry
    from aughor.llm.provider import LLMProvider
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool = True

    class _Endpoint:
        def create_with_completion(self, **kw):
            raise RuntimeError("nope")

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Endpoint()))
    with telemetry.bind_trace("t-failcap"):
        with pytest.raises(RuntimeError):
            LLMProvider._complete_on(client, "ollama", "m", "SYS", "ASK", _Out, 0.0, role="coder")

    call = [e for e in _all_events(trace_id="t-failcap")
            if e["kind"] == session_log.LLM_CALL][0]
    assert call["ok"] is False
    assert call["payload"]["user_prompt"] == "ASK"
    assert "response" not in call["payload"]     # there wasn't one


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


def test_background_jobs_get_a_trace(monkeypatch):
    """Explorer/brief/monitor/birth runs never pass an ask door, so the kernel
    binds the job id as their trace — otherwise their spans land uncorrelated."""
    import asyncio

    from aughor import telemetry
    from aughor.kernel.jobs import JobKernel

    seen: dict[str, str] = {}

    async def _drive():
        k = JobKernel()
        job_id = await k.submit("exploration", _capture)
        for _ in range(200):                    # let the supervised task run
            await asyncio.sleep(0.01)
            if "trace" in seen:
                break
        return job_id

    async def _capture():
        seen["trace"] = telemetry.current_trace_id()

    job_id = asyncio.run(_drive())
    assert seen.get("trace") == job_id, "a background job ran with no trace bound"


def test_ask_trace_wins_over_the_job_id(monkeypatch):
    """A deep /ask submits its job from inside the ask stream, so it inherits that
    run's trace through the context copy — the job id must not override it."""
    import asyncio

    from aughor import telemetry
    from aughor.kernel.jobs import JobKernel

    seen: dict[str, str] = {}

    async def _capture():
        seen["trace"] = telemetry.current_trace_id()

    async def _drive():
        with telemetry.bind_trace("t-from-ask"):
            k = JobKernel()
            await k.submit("investigation", _capture)
            for _ in range(200):
                await asyncio.sleep(0.01)
                if "trace" in seen:
                    break

    asyncio.run(_drive())
    assert seen.get("trace") == "t-from-ask"


def test_session_events_is_queryable_as_an_ops_table():
    """The table joins the curated aughor_ops surface, so Deep Analysis can
    investigate the agent's own behaviour with NL2SQL — the same one-line move
    task_history already proved."""
    from aughor.db.connection import AughorOpsConnection
    assert "session_events" in AughorOpsConnection._OPS_TABLES
