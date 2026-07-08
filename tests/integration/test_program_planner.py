"""Integration tests for the plan-as-program executor (Rec 4, Stage 2–3).

The LLM plan step is faked (a canned `Program`) and the semop LLM is a deterministic fake that parses the
operator's ``[index] text`` listing; everything else — deterministic validation, the guarded DATA-step
execution against real registered DuckDB sources, and the named-artifact ledger mirror — runs for real.
"""
from __future__ import annotations

import re

import duckdb
from fastapi.testclient import TestClient

import pytest

import aughor.agent.program_planner as program_planner
import aughor.semops.operators as ops
from aughor.agent.program_planner import (
    Program,
    ProgramStep,
    run_program,
    validate_program,
)
from aughor.db import registry
from aughor.platform.contracts.execution import QueryResult
from aughor.semops.operators import _Aggregation, _FilterBatch, _RowVerdict

_LINE = re.compile(r"^\[(\d+)\]\s?(.*)$", re.M)


@pytest.fixture(autouse=True)
def _no_autoseed(monkeypatch):
    """Hermetic: `get_schema()` otherwise fires autoseed, which makes a real LLM call and writes the live
    data/glossary.yaml (a non-hermetic store). These tests don't need glossary enrichment, so disable it at
    the call-time gate."""
    monkeypatch.setattr("aughor.semantic.autoseed._ENABLED", False)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _tickets(tmp_path):
    con = duckdb.connect(str(tmp_path / "tickets.duckdb"))
    con.execute("CREATE TABLE tickets (ticket_id INT, description VARCHAR)")
    con.execute(
        "INSERT INTO tickets VALUES "
        "(1,'urgent outage in billing'),(2,'minor typo on the docs page'),"
        "(3,'urgent data loss report'),(4,'feature request for dark mode')"
    )
    con.close()
    return registry.add_connection("pp-tickets", "duckdb", str(tmp_path / "tickets.duckdb"))


class _FakeSemopProvider:
    """Parses the operator's row listing and applies a python rule per row (mirrors test_semops)."""

    def __init__(self, *, filter_fn=None, aggregate_fn=None):
        self.filter_fn = filter_fn
        self.aggregate_fn = aggregate_fn

    def complete(self, *, system, user, response_model):
        items = [(int(i), t) for i, t in _LINE.findall(user)]
        if response_model is _FilterBatch:
            return _FilterBatch(verdicts=[_RowVerdict(index=i, keep=bool(self.filter_fn(t))) for i, t in items])
        if response_model is _Aggregation:
            return _Aggregation(answer=self.aggregate_fn([t for _, t in items]))
        raise AssertionError(f"unexpected response_model {response_model!r}")


def _patch_semop(monkeypatch, provider):
    monkeypatch.setattr(ops, "get_provider", lambda role=None, **kw: provider)


# ── the endpoints (flag gate) ─────────────────────────────────────────────────

def test_plan_run_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.delenv("AUGHOR_PLAN_PROGRAM", raising=False)
    resp = client.post("/query/plan-run", json={"conn_id": "x", "program": {"steps": []}})
    assert resp.status_code == 404


def test_plan_answer_disabled_by_default(client: TestClient, monkeypatch):
    monkeypatch.delenv("AUGHOR_PLAN_PROGRAM", raising=False)
    resp = client.post("/query/plan-answer", json={"conn_id": "x", "question": "why"})
    assert resp.status_code == 404


def test_plan_run_endpoint_executes(client: TestClient, monkeypatch, tmp_path):
    """Reachable API on: a hand-authored DATA→SEMOP program runs end-to-end and returns the artifacts."""
    monkeypatch.setenv("AUGHOR_PLAN_PROGRAM", "1")
    cid = _tickets(tmp_path)
    _patch_semop(monkeypatch, _FakeSemopProvider(filter_fn=lambda t: "urgent" in t))
    program = {
        "steps": [
            {"id": "s0", "kind": "data", "writes": "rows",
             "sql": "SELECT ticket_id, description FROM tickets ORDER BY ticket_id"},
            {"id": "s1", "kind": "semop", "writes": "urgent", "reads": ["rows"],
             "operator": "filter", "column": "description", "predicate": "is urgent"},
        ]
    }
    resp = client.post("/query/plan-run", json={"conn_id": cid, "program": program})
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] is None and data["issues"] == []
    assert data["row_count"] == 2                              # only the two 'urgent' tickets survive
    assert set(data["artifacts"].keys()) == {"rows", "urgent"}
    assert data["program"]["steps"][0]["id"] == "s0"


# ── validate_program (deterministic gate) ─────────────────────────────────────

def test_validate_program_good(tmp_path):
    cid = _tickets(tmp_path)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows",
                    sql="SELECT ticket_id, description FROM tickets"),
        ProgramStep(id="s1", kind="semop", writes="urgent", reads=["rows"],
                    operator="filter", column="description", predicate="is urgent"),
    ])
    assert validate_program(program, cid) == []


def test_validate_program_bad_read(tmp_path):
    cid = _tickets(tmp_path)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows", sql="SELECT ticket_id, description FROM tickets"),
        ProgramStep(id="s1", kind="semop", writes="x", reads=["nope"],
                    operator="filter", column="description", predicate="p"),
    ])
    assert any("not an earlier step's output" in i for i in validate_program(program, cid))


def test_validate_program_forward_ref_is_caught(tmp_path):
    """A step reading a LATER step's output is rejected — order IS topology, so this also covers cycles."""
    cid = _tickets(tmp_path)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows", sql="SELECT ticket_id, description FROM tickets"),
        ProgramStep(id="s1", kind="semop", writes="a", reads=["b"],     # 'b' is produced later, by s2
                    operator="filter", column="description", predicate="p"),
        ProgramStep(id="s2", kind="semop", writes="b", reads=["rows"],
                    operator="filter", column="description", predicate="p"),
    ])
    assert any("reads 'b'" in i and "not an earlier step's output" in i for i in validate_program(program, cid))


def test_validate_program_bad_semop_column(tmp_path):
    cid = _tickets(tmp_path)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows", sql="SELECT ticket_id, description FROM tickets"),
        ProgramStep(id="s1", kind="semop", writes="x", reads=["rows"],
                    operator="filter", column="no_such_col", predicate="p"),
    ])
    assert any("column 'no_such_col' is not in 'rows'" in i for i in validate_program(program, cid))


def test_validate_program_bad_sql_is_caught(tmp_path):
    cid = _tickets(tmp_path)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows", sql="SELECT * FROM no_such_table"),
    ])
    assert any("did not parse/ground" in i for i in validate_program(program, cid))


def test_validate_program_driver_must_read_nothing(tmp_path):
    cid = _tickets(tmp_path)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows", reads=["ghost"],
                    sql="SELECT ticket_id, description FROM tickets"),
    ])
    issues = validate_program(program, cid)
    assert any("driver) must read nothing" in i for i in issues)


# ── run_program (deterministic executor) ──────────────────────────────────────

def test_run_program_threads_sql_then_semops(monkeypatch, tmp_path):
    """DATA (real DuckDB) → SEMOP filter → SEMOP aggregate; each step's result is a named artifact."""
    cid = _tickets(tmp_path)
    _patch_semop(monkeypatch, _FakeSemopProvider(
        filter_fn=lambda t: "urgent" in t,
        aggregate_fn=lambda texts: f"{len(texts)} urgent tickets"))
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows",
                    sql="SELECT ticket_id, description FROM tickets ORDER BY ticket_id"),
        ProgramStep(id="s1", kind="semop", writes="urgent", reads=["rows"],
                    operator="filter", column="description", predicate="is urgent"),
        ProgramStep(id="s2", kind="semop", writes="summary", reads=["urgent"],
                    operator="aggregate", column="description", instruction="count them", out_column="answer"),
    ])
    pr = run_program(program, cid, investigation_id="inv-thread")
    assert pr.issues == []
    assert pr.result.columns == ["answer"] and pr.result.rows == [["2 urgent tickets"]]
    assert set(pr.artifacts.keys()) == {"rows", "urgent", "summary"}


def test_run_program_artifact_written_and_read_back(monkeypatch, tmp_path):
    """After a run, the ledger receipt for a step's artifact returns its payload + a `reads` lineage edge."""
    from aughor.kernel.ledger import Ledger
    cid = _tickets(tmp_path)
    _patch_semop(monkeypatch, _FakeSemopProvider(filter_fn=lambda t: "urgent" in t))
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows",
                    sql="SELECT ticket_id, description FROM tickets ORDER BY ticket_id"),
        ProgramStep(id="s1", kind="semop", writes="urgent", reads=["rows"],
                    operator="filter", column="description", predicate="is urgent"),
    ])
    pr = run_program(program, cid, investigation_id="inv-receipt")
    assert pr.issues == []

    rec = Ledger.default().receipt(f"artifact:{cid}:inv-receipt:urgent")
    assert rec is not None
    assert rec["artifact"]["payload"]["step_id"] == "s1"
    assert rec["artifact"]["payload"]["row_count"] == 2
    relations = {(e["relation"], e["ref"]) for e in rec["lineage"]}
    assert ("reads", f"artifact:{cid}:inv-receipt:rows") in relations
    assert ("program", f"plan:{cid}:inv-receipt") in relations


def test_run_program_stops_on_failing_step(monkeypatch, tmp_path):
    """A DATA step whose result carries an error stops the run — its failure is in `issues` and downstream
    steps never execute. The error is forced through the executor because the guard battery would otherwise
    deterministically REPAIR a merely-wrong table name (that per-step repair is exactly the feature Rec 4
    wants); here we prove the executor's own stop-on-hard-error control flow."""
    import aughor.sql.executor as executor_mod
    cid = _tickets(tmp_path)
    _patch_semop(monkeypatch, _FakeSemopProvider(filter_fn=lambda t: True))
    real = executor_mod.execute_guarded

    def _fake(conn, sql, *, query_id, **kw):
        if "FAIL_ME" in sql:
            return QueryResult(hypothesis_id=query_id, sql=sql, columns=[], rows=[], row_count=0, error="boom")
        return real(conn, sql, query_id=query_id, **kw)

    monkeypatch.setattr(executor_mod, "execute_guarded", _fake)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows", sql="SELECT ticket_id, description FROM tickets"),
        ProgramStep(id="s1", kind="data", writes="broken", sql="SELECT 1 AS x /* FAIL_ME */"),
        ProgramStep(id="s2", kind="semop", writes="never", reads=["broken"],
                    operator="filter", column="description", predicate="p"),
    ])
    pr = run_program(program, cid, investigation_id="inv-stop")   # run directly, bypassing validate
    assert pr.result.error == "boom"
    assert any("s1" in i for i in pr.issues)
    assert "broken" in pr.artifacts                              # the failing step's artifact IS recorded
    assert "never" not in pr.artifacts                           # the downstream semop never ran


# ── answer_program (plan → validate → run) ────────────────────────────────────

def test_answer_program_plan_validate_run(monkeypatch, tmp_path):
    """The full shape: a faked `plan_program` returns a canned program; gate → validate → run runs for real."""
    cid = _tickets(tmp_path)
    canned = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows",
                    sql="SELECT ticket_id, description FROM tickets ORDER BY ticket_id"),
        ProgramStep(id="s1", kind="semop", writes="urgent", reads=["rows"],
                    operator="filter", column="description", predicate="is urgent"),
    ])
    monkeypatch.setattr(program_planner, "plan_program", lambda q, c: canned)
    _patch_semop(monkeypatch, _FakeSemopProvider(filter_fn=lambda t: "urgent" in t))

    pr = program_planner.answer_program("which tickets are urgent?", cid)
    assert pr.issues == []
    assert pr.result.row_count == 2
    assert pr.program is canned
    assert set(pr.artifacts.keys()) == {"rows", "urgent"}


def test_answer_program_planning_failure_is_an_answer(monkeypatch, tmp_path):
    """A planning exception returns an error ProgramResult, never raises (mirrors answer_federated)."""
    cid = _tickets(tmp_path)

    def _boom(q, c):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(program_planner, "plan_program", _boom)
    pr = program_planner.answer_program("q", cid)
    assert pr.program is None
    assert pr.issues == ["planning failed"]
    assert "planning failed" in (pr.result.error or "")
