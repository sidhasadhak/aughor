"""Plane-conformance tests for the Capability plane (AL-02) — `aughor/capability`.

The review's acceptance bar: "a new capability can be added by registering one impl + reusing the
Trust/Semantic/Memory planes — no edits to Orchestration." So the tests prove (1) a toy capability
registered from outside runs through the template unchanged (the bar), (2) the template sequences
the four phases, short-circuits execute on a Trust-plane BLOCK, and adopts a validate repair, and
(3) the real `SqlCapability` runs end-to-end — delegating to `trust.verify` + `conn.execute` + the
result formatter — on a spy connection and on the real DuckDB fixture.
"""
from __future__ import annotations

import pytest

from aughor.capability import (
    CapabilityRequest,
    get_capability,
    register_capability,
    registered_domains,
    run_capability,
)
from aughor.capability.builtins import SqlCapability
from aughor.trust import Scope, Verdict
from aughor.platform.contracts.execution import QueryResult


@pytest.fixture
def clean_registry():
    """Snapshot the global registry and restore it, so toy registrations don't leak across tests."""
    from aughor.capability import registry as reg
    snapshot = dict(reg._PIPELINES)
    yield
    reg._PIPELINES.clear()
    reg._PIPELINES.update(snapshot)


class _SpyConn:
    """A minimal DatabaseConnection stand-in that records what it executed."""
    dialect = "duckdb"

    def __init__(self):
        self.executed: list[str] = []

    def execute(self, tag: str, sql: str) -> QueryResult:
        self.executed.append(sql)
        return QueryResult(hypothesis_id=tag, sql=sql, columns=["n"], rows=[[1]],
                           row_count=1, error=None)


# ── The verify bar: a new capability is added by registering one impl ────────────────────

def test_register_new_capability_runs_through_template(clean_registry):
    class _ToyForecast:
        domain = "forecast"
        kind = "metadata"
        def generate(self, req): return f"forecast({req.question})"
        def validate(self, artifact, req): return Verdict(kind="metadata", artifact=artifact)
        def execute(self, artifact, req): return {"prediction": 42}
        def interpret(self, output, req): return f"predicted {output['prediction']}"

    register_capability(_ToyForecast())
    res = run_capability("forecast", CapabilityRequest(question="sales next month"))
    assert res is not None
    assert res.ok is True
    assert res.domain == "forecast"
    assert res.trace == ("generate", "validate", "execute", "interpret")
    assert res.output == {"prediction": 42}
    assert res.narrative == "predicted 42"


def test_unknown_domain_returns_none():
    assert run_capability("does-not-exist", CapabilityRequest()) is None


# ── Template mechanics: block short-circuit + repair adoption ─────────────────────────────

def test_block_short_circuits_before_execute(clean_registry):
    spy = _SpyConn()
    # A DELETE fails the Trust plane's readonly BLOCK, so execute must never run.
    res = run_capability("data", CapabilityRequest(artifact="DELETE FROM orders",
                                                   scope=Scope(conn=spy, dialect="duckdb")))
    assert res.ok is False
    assert res.trace == ("generate", "validate")          # execute + interpret skipped
    assert spy.executed == []                              # the DB was never touched
    assert res.error                                       # a blocker reason is surfaced


def test_validate_repair_is_adopted(clean_registry):
    class _ToyRepair:
        domain = "repairs"
        kind = "sql"
        def generate(self, req): return "SELECT orig"
        def validate(self, artifact, req): return Verdict(kind="sql", artifact="SELECT repaired", repaired=True)
        def execute(self, artifact, req): return {"got": artifact}
        def interpret(self, output, req): return ""

    register_capability(_ToyRepair())
    res = run_capability("repairs", CapabilityRequest())
    assert res.ok is True
    assert res.artifact == "SELECT repaired"              # the template adopted verdict.artifact
    assert res.output == {"got": "SELECT repaired"}       # execute saw the repaired form


# ── The real SqlCapability: delegation to trust.verify + conn.execute + the formatter ────

def test_sql_capability_end_to_end_on_spy_conn(clean_registry):
    spy = _SpyConn()
    res = run_capability("data", CapabilityRequest(artifact="SELECT 1 AS n",
                                                   scope=Scope(conn=spy, dialect="duckdb")))
    assert res.ok is True
    assert res.trace == ("generate", "validate", "execute", "interpret")
    assert spy.executed == ["SELECT 1 AS n"]
    assert res.output["row_count"] == 1
    assert "Rows returned: 1" in res.narrative            # delegated to format_result_for_llm


def test_sql_capability_registered_by_default():
    assert "data" in registered_domains()
    assert isinstance(get_capability("data"), SqlCapability)


def test_sql_capability_without_connection_is_a_clean_error(clean_registry):
    res = run_capability("data", CapabilityRequest(artifact="SELECT 1", scope=Scope()))
    assert res.ok is False
    assert "no connection" in res.error


def test_sql_capability_on_real_duckdb_fixture(clean_registry, builtin_conn_id):
    from aughor.db.connection import open_connection_for
    db = open_connection_for(builtin_conn_id)
    try:
        res = run_capability("data", CapabilityRequest(
            artifact="SELECT 1 AS n", scope=Scope(conn=db, dialect="duckdb")))
    finally:
        db.close()
    assert res.ok is True
    assert res.trace == ("generate", "validate", "execute", "interpret")
    assert res.output["row_count"] == 1
    assert res.narrative
