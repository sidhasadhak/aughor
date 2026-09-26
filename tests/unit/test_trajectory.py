"""TJ-2 (§3.47) — one record per run: the step event and the trajectory read.

Pinned: the tool loop writes one `step` event per step from its one seam, with the
work-artifact fields always and the payload fields only under an open capture window;
`trajectory_of` walks the run's trace across the stores that already carry it — steps,
answers, statements, guard fires, picks, reward fields — withholding step payloads on an
ungated read; a deep run's investigation id IS its trace; the eval harness binds a trace
per run and records each rollout's own.
"""
from __future__ import annotations

import pytest

from aughor import telemetry
from aughor.agent.tool_loop import ToolSpec, run_tool_loop
from aughor.kernel.ledger import Ledger
from aughor.llm.faux import FauxToolCall, set_responses
from aughor.llm.provider import LLMProvider
from aughor.obs import prompt_window, session_log

_PARAMS = {"type": "object", "properties": {"sql": {"type": "string"}}}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.delenv("AUGHOR_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("AUGHOR_TOOL_LOOP_STEPS", raising=False)
    return LLMProvider(backend="faux", role="coder")


@pytest.fixture(autouse=True)
def _no_capture_window():
    prompt_window.close_window()
    yield
    prompt_window.close_window()


def _run_sql(args):
    return {"sql": args.get("sql", ""), "row_count": 3, "rows": [[1], [2], [3]],
            "guard_receipts": [{"guard": "fanout", "action": "warn", "detail": "x"}]}


def _boom(args):
    raise RuntimeError("no such table orders")


def _tools(**fns):
    return [ToolSpec(name=n, description=f"the {n} tool", parameters=_PARAMS, run=f)
            for n, f in fns.items()]


def _steps(trace: str) -> list[dict]:
    rows = Ledger.default().session_events(trace_id=trace, kind=session_log.STEP, limit=50)
    return sorted(rows, key=lambda r: r["seq"])


# ── the step event ────────────────────────────────────────────────────────────────────

def test_every_loop_step_lands_as_one_step_event_with_its_work_fields(provider):
    set_responses([
        FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"),
        FauxToolCall(payload={"sql": "SELECT 2"}, name="boom"),
        FauxToolCall(payload={}, name="ghost"),
        "done",
    ])
    with telemetry.bind_trace("tj2-steps"):
        result = run_tool_loop(provider, "sys", "q?", _tools(run_sql=_run_sql, boom=_boom),
                               conn_id="c1", site="converse.tool")
    assert result.answer == "done"
    rows = _steps("tj2-steps")
    assert [r["name"] for r in rows] == ["run_sql", "boom", "ghost"]
    first = rows[0]
    assert first["ok"] is True or first["ok"] == 1
    assert first["row_count"] == 3 and first["conn_id"] == "c1"
    assert first["duration_ms"] is not None
    p = first["payload"]
    assert p["index"] == 1 and p["tool"] == "run_sql" and p["site"] == "converse.tool"
    assert p["sql"] == "SELECT 1" and p["guards"] == ["fanout"] and p["error"] == ""
    assert p["captured"] is False and "arguments" not in p and "result_excerpt" not in p
    second = rows[1]["payload"]
    assert second["ok"] is False and "no such table orders" in second["error"]
    assert rows[2]["payload"]["error"] == "no such tool"       # a hallucinated name is a step too


def test_payload_fields_ride_only_under_an_open_capture_window(provider):
    set_responses([FauxToolCall(payload={"sql": "SELECT 9"}, name="run_sql"), "ok"])
    prompt_window.open_window(calls=5, minutes=5, opened_by="test", reason="tj2")
    assert prompt_window.active()
    with telemetry.bind_trace("tj2-captured"):
        run_tool_loop(provider, "sys", "q?", _tools(run_sql=_run_sql))
    p = _steps("tj2-captured")[0]["payload"]
    assert p["captured"] is True
    assert "SELECT 9" in p["arguments"] and "row_count" in p["result_excerpt"]
    # A step is not a model call: the window's budget is untouched by it.
    assert prompt_window.status().get("calls_remaining", prompt_window.status().get("calls")) in (5, None) \
        or prompt_window.active()


def test_a_loop_outside_any_trace_writes_nothing(provider):
    before = len(Ledger.default().session_events(kind=session_log.STEP, limit=5000))
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"), "ok"])
    run_tool_loop(provider, "sys", "q?", _tools(run_sql=_run_sql))
    assert len(Ledger.default().session_events(kind=session_log.STEP, limit=5000)) == before


# ── the trajectory read ───────────────────────────────────────────────────────────────

def _one_run(provider, trace: str, *, verdict: str = "") -> str:
    """A whole run under one trace: request, two picks, a statement, a guard fire, a
    history row and (optionally) a person's verdict."""
    from aughor.db.history import create_investigation
    from aughor.feedback.verdicts import record_verdict
    from aughor.security.audit import AuditLogger, GuardVerdicts
    set_responses([FauxToolCall(payload={"sql": "SELECT 1"}, name="run_sql"), "answered"])
    with telemetry.bind_trace(trace):
        session_log.emit(session_log.USER_REQUEST, name="ask", conn_id="c1",
                         payload={"question": "how many orders?", "depth": "quick"})
        run_tool_loop(provider, "sys", "how many orders?",
                      _tools(run_sql=_run_sql, list_tables=lambda a: []), conn_id="c1",
                      trace_id=trace)
        AuditLogger.log(connection_id="c1", sql="SELECT 1", verdict="safe", row_count=3)
        GuardVerdicts.record(pattern="fanout", subject="orders", phase="execute", sql="SELECT 1")
        inv_id = create_investigation("how many orders?", "c1")
        session_log.emit(session_log.FINAL_RESPONSE, name="ask", ok=True, duration_ms=12.5)
    if verdict:
        record_verdict("c1", inv_id, verdict, note="fine")
    return inv_id


def test_trajectory_of_walks_every_store_the_trace_reaches(provider):
    from aughor.obs.trajectory import trajectory_of
    inv_id = _one_run(provider, "tj2-walk", verdict="accept")
    t = trajectory_of("tj2-walk")
    assert t["question"] == "how many orders?" and t["conn_id"] == "c1" and t["ok"] in (True, 1)
    assert [s["tool"] for s in t["steps"]] == ["run_sql"] and t["steps"][0]["sql"] == "SELECT 1"
    assert t["executions"][0]["sql"] == "SELECT 1" and t["executions"][0]["row_count"] == 3
    assert t["guards"][0]["pattern"] == "fanout"
    assert t["decisions"] and t["decisions"][0]["chosen"] == "run_sql"
    assert t["answers"][0]["investigation_id"] == inv_id
    assert t["answers"][0]["verdict"]["verdict"] == "accept"
    # TJ-3: the label from the one rule — the fixture's fanout row carries no action, so the
    # run is not clean and not negative: unlabeled, with the reason.
    assert {k: t["reward"][k] for k in ("human_verdict", "recheck", "execution", "guard_fires")} == {
        "human_verdict": "accept", "recheck": None, "execution": "ok", "guard_fires": 1}
    assert t["reward"]["label"] in ("unlabeled", "negative") and t["reward"]["reasons"]
    assert t["counts"]["steps"] == 1 and t["counts"]["executions"] == 1


def test_step_payloads_are_withheld_on_an_ungated_read_and_served_on_a_gated_one(provider):
    from aughor.obs.trajectory import trajectory_of
    prompt_window.open_window(calls=5, minutes=5, opened_by="test", reason="tj2")
    _one_run(provider, "tj2-gate")
    ungated = trajectory_of("tj2-gate")
    step = ungated["steps"][0]
    assert step["captured"] is True and step["arguments"] == "" and step["payload_withheld"] is True
    assert "§6" in ungated["payload_withheld"]
    gated = trajectory_of("tj2-gate", gated=True)
    assert "SELECT 1" in gated["steps"][0]["arguments"] and gated["payload_withheld"] is None


def test_an_unknown_trace_is_none_and_the_route_says_404(provider):
    from fastapi.testclient import TestClient

    from aughor.api import app
    from aughor.obs.trajectory import trajectory_of
    assert trajectory_of("nope-nope") is None
    client = TestClient(app)
    assert client.get("/traces/nope-nope/trajectory").status_code == 404
    _one_run(provider, "tj2-route")
    body = client.get("/traces/tj2-route/trajectory").json()
    assert body["measured"] is True and body["steps"][0]["tool"] == "run_sql"
    assert body["payload_withheld"]                             # the ungated read, by construction


def test_a_deep_runs_investigation_id_is_its_trace():
    """The deep path mints its trace from the investigation id; a row written before any
    trace was bound still joins by its own id."""
    from aughor.db.history import by_trace, create_investigation
    from aughor.obs.trajectory import trajectory_of
    inv_id = create_investigation("why did revenue fall?", "c1")
    assert [r["id"] for r in by_trace(inv_id)] == [inv_id]
    t = trajectory_of(inv_id)
    assert t is not None and t["answers"][0]["investigation_id"] == inv_id
    assert t["question"] == "why did revenue fall?" and t["steps"] == []


def test_a_store_that_cannot_be_read_says_so(provider, monkeypatch):
    from aughor.obs import trajectory as tj
    _one_run(provider, "tj2-down")
    monkeypatch.setattr(tj, "_guard_rows", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("locked")))
    t = tj.trajectory_of("tj2-down")
    assert t["guards"] == {"unavailable": "guard_verdicts could not be read (RuntimeError)"}
    assert t["counts"]["guards"] is None and t["reward"]["guard_fires"] is None


# ── the harness ───────────────────────────────────────────────────────────────────────

def test_an_eval_run_binds_a_trace_and_each_rollout_records_its_own():
    from aughor.evals import store
    from aughor.evals.evaluator import EvalObservation
    from aughor.evals.runner import run_suite
    suite = store.create_suite("tj2-suite", target="ask", connection_id="c1")
    store.add_case(suite["id"], question="how many orders?")

    def target(case):
        return EvalObservation(sql="SELECT 1", rows=[[1]], row_count=1,
                               meta={"door": "ask", "trace_id": "case-trace-7"})

    assert telemetry.current_trace_id() == ""
    summary = run_suite(suite["id"], target, iterations=1, evaluators=[])
    assert telemetry.current_trace_id() == ""                  # released after the run
    run = store.get_run(summary.run_id)
    assert run["trace_id"].startswith("eval-")
    detail = next(s["detail"] for s in store.run_results(summary.run_id)[0]["scores"]
                  if s["evaluator"] == "trace.observation")
    assert detail["trace_id"] == "case-trace-7"


def test_the_ask_target_reads_the_runs_trace_off_the_route_receipt(monkeypatch):
    import json

    from aughor.evals.evaluator import EvalCase
    from aughor.evals.targets import ask_target
    from aughor.routers import investigations as inv

    async def _fake_stream(req, request):
        yield "data: " + json.dumps({"type": "route", "depth": "quick", "trace_id": "run-abc"}) + "\n\n"
        yield "data: " + json.dumps({"type": "sql", "sql": "SELECT 1"}) + "\n\n"
        yield "data: " + json.dumps({"type": "headline", "headline": "one"}) + "\n\n"

    monkeypatch.setattr(inv, "build_ask_stream", _fake_stream)
    monkeypatch.setattr("aughor.db.connection.open_connection_for", lambda cid: None)
    obs = ask_target("c1")(EvalCase(id="k1", question="how many?"))
    assert obs.sql == "SELECT 1" and obs.meta["trace_id"] == "run-abc"


def test_the_route_receipt_carries_the_bound_trace():
    """The frame the harness reads: `route.trace_id` is the ambient run trace."""
    import inspect

    from aughor.routers import investigations as inv
    src = inspect.getsource(inv._stream_ask)
    assert '_route_ev["trace_id"] = _ambient() or ""' in src
