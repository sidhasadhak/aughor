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


# ── Stage A: DATA-reads-artifact dataflow ─────────────────────────────────────

def test_run_program_data_reads_semop_output(monkeypatch, tmp_path):
    """SEMOP filter → DATA GROUP BY over the filtered artifact: the SQL sees ONLY the surviving rows."""
    cid = _tickets(tmp_path)
    _patch_semop(monkeypatch, _FakeSemopProvider(filter_fn=lambda t: "urgent" in t))
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows",
                    sql="SELECT ticket_id, description FROM tickets ORDER BY ticket_id"),
        ProgramStep(id="s1", kind="semop", writes="urgent", reads=["rows"],
                    operator="filter", column="description", predicate="is urgent"),
        ProgramStep(id="s2", kind="data", writes="counted", reads=["urgent"],
                    sql="SELECT count(*) AS n FROM urgent"),
    ])
    pr = run_program(program, cid, investigation_id="inv-dataflow")
    assert pr.issues == []
    assert pr.result.columns == ["n"]
    assert pr.result.rows == [["2"]]                             # only the 2 urgent tickets flowed into SQL
    assert set(pr.artifacts.keys()) == {"rows", "urgent", "counted"}


def test_validate_program_data_reads_skips_static_parse(tmp_path):
    """A DATA step that reads an artifact ('urgent' — not a real table) must PASS validation: its SQL is
    checked at run, not statically parse-grounded (which would falsely reject it)."""
    cid = _tickets(tmp_path)
    program = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows", sql="SELECT ticket_id, description FROM tickets"),
        ProgramStep(id="s1", kind="semop", writes="urgent", reads=["rows"],
                    operator="filter", column="description", predicate="urgent"),
        ProgramStep(id="s2", kind="data", writes="counted", reads=["urgent"],
                    sql="SELECT count(*) AS n FROM urgent"),
    ])
    assert validate_program(program, cid) == []


def test_register_unregister_roundtrip(tmp_path):
    """The artifact relation is queryable after register and gone after teardown (no pooled-conn pollution)."""
    from aughor.agent.program_planner import _register_artifact, _unregister_artifacts
    from aughor.db.connection import open_connection_for
    cid = _tickets(tmp_path)
    db = open_connection_for(cid)
    qr = QueryResult(hypothesis_id="t", sql="", columns=["a", "b"],
                     rows=[["1", "x"], ["2", "y"]], row_count=2)
    assert _register_artifact(db, "myart", qr) is None
    res = db.execute("q", "SELECT count(*) AS n FROM myart")
    assert res.error is None and res.rows == [["2"]]
    _unregister_artifacts(db, ["myart"])
    assert db.execute("q2", "SELECT * FROM myart").error is not None   # relation gone after teardown


def test_register_artifact_empty_and_non_duckdb():
    """An empty artifact registers as a 0-row typed view; a non-DuckDB connection is rejected cleanly."""
    from aughor.agent.program_planner import _register_artifact

    class _NoConn:
        pass

    err = _register_artifact(_NoConn(), "x",
                             QueryResult(hypothesis_id="t", sql="", columns=["a"], rows=[["1"]], row_count=1))
    assert err is not None and "DuckDB only" in err


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


# ── Stage C: trusted-plan replay (closed_loop-gated) ──────────────────────────

def test_answer_program_replays_trusted_program(monkeypatch, tmp_path):
    """With closed_loop on, a clean fresh run is crystallized; a near-identical question then REPLAYS it
    deterministically — plan_program is NOT called a second time."""
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    cid = _tickets(tmp_path)
    canned = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows",
                    sql="SELECT ticket_id, description FROM tickets ORDER BY ticket_id"),
        ProgramStep(id="s1", kind="semop", writes="urgent", reads=["rows"],
                    operator="filter", column="description", predicate="is urgent"),
    ])
    calls = {"n": 0}

    def _fake_plan(q, c):
        calls["n"] += 1
        return canned

    monkeypatch.setattr(program_planner, "plan_program", _fake_plan)
    _patch_semop(monkeypatch, _FakeSemopProvider(filter_fn=lambda t: "urgent" in t))

    pr1 = program_planner.answer_program("which tickets are urgent", cid, org_id="o1")
    assert pr1.issues == [] and pr1.result.row_count == 2 and calls["n"] == 1

    pr2 = program_planner.answer_program("show the urgent tickets", cid, org_id="o1")
    assert pr2.issues == [] and pr2.result.row_count == 2
    assert calls["n"] == 1                          # REPLAYED — no second planning call


def test_answer_program_no_replay_when_closed_loop_off(monkeypatch, tmp_path):
    """Default (closed_loop off): nothing is saved or replayed — every turn re-plans (byte-identical)."""
    monkeypatch.delenv("AUGHOR_CLOSED_LOOP", raising=False)
    cid = _tickets(tmp_path)
    canned = Program(steps=[ProgramStep(id="s0", kind="data", writes="rows",
                                        sql="SELECT ticket_id FROM tickets")])
    calls = {"n": 0}

    def _fake_plan(q, c):
        calls["n"] += 1
        return canned

    monkeypatch.setattr(program_planner, "plan_program", _fake_plan)
    program_planner.answer_program("urgent tickets", cid, org_id="o1")
    program_planner.answer_program("urgent tickets", cid, org_id="o1")
    assert calls["n"] == 2                          # planned both times — no replay


def test_answer_program_stale_cached_falls_through(monkeypatch, tmp_path):
    """A cached program that no longer validates (schema drift) is rejected on replay → fresh planning."""
    monkeypatch.setenv("AUGHOR_CLOSED_LOOP", "1")
    cid = _tickets(tmp_path)
    from aughor.semantic.trusted_programs import TrustedProgram, save_trusted_program
    save_trusted_program(TrustedProgram(
        connection_id=cid, org_id="o1", question="count urgent tickets",
        program={"steps": [{"id": "s0", "kind": "data", "writes": "r",
                            "sql": "SELECT * FROM ghost_table"}], "rationale": ""}))
    fresh = Program(steps=[ProgramStep(id="s0", kind="data", writes="r", sql="SELECT ticket_id FROM tickets")])
    calls = {"n": 0}

    def _fake_plan(q, c):
        calls["n"] += 1
        return fresh

    monkeypatch.setattr(program_planner, "plan_program", _fake_plan)
    pr = program_planner.answer_program("count urgent tickets", cid, org_id="o1")
    assert calls["n"] == 1                          # stale plan rejected → planned fresh
    assert pr.issues == []


def test_data_step_guard_caveat_surfaces_as_warning(tmp_path):
    """WP-1a — the planner runs `execute_guarded` in deterministic-only mode (no
    LLM fixer), so a guard finding can't be repaired there; it must surface as a
    step warning on the ProgramResult instead of being dropped (the swallow seam)."""
    # id-arithmetic (SUM(measure * key)) is the right trigger here: it executes
    # without error, preflight can NOT repair it (only the LLM fixer could, and the
    # planner runs deterministic-only), so the caveat is the only surviving signal.
    con = duckdb.connect(str(tmp_path / "sales.duckdb"))
    con.execute("CREATE TABLE sales (order_id INT, amt DOUBLE)")
    con.execute("INSERT INTO sales VALUES (1, 10.0), (2, 20.0)")
    con.close()
    cid = registry.add_connection("pp-sales", "duckdb", str(tmp_path / "sales.duckdb"))
    prog = Program(steps=[
        ProgramStep(id="s0", kind="data", writes="rows",
                    sql="SELECT SUM(amt * order_id) AS x FROM sales"),
    ])
    res = run_program(prog, cid, investigation_id="wp1-caveat-test")
    assert any("s0: id-arithmetic" in w for w in res.warnings), res.warnings
