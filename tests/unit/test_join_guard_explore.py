"""Integration tests for the value-domain join-guard repair in the EXPLORE path.

Mirror tests/unit/test_join_guard_repair.py (which covers the ADA path) for
`plan_and_execute_subq` in aughor/agent/explore.py. Uses a real in-memory DuckDB
and a stubbed LLM so the accept/reject wiring is deterministic.

Also guards the pre-existing `metrics_section` omission: the explore error-fix
path called FIX_SQL_PROMPT.format() without `metrics_section`, raising KeyError
(unguarded → it crashed the node). These tests exercise both fix paths.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from aughor.db.connection import DuckDBConnection
from aughor.agent.state import QueryPlan, SQLFix, SubQuestion


def _conn():
    conn = DuckDBConnection.__new__(DuckDBConnection)
    conn._path = Path(":memory:")
    conn._conn = duckdb.connect(":memory:")
    conn._connection_id = "test"
    conn._schema_name = None
    conn._conn.execute("CREATE TABLE orders (cust VARCHAR, camp VARCHAR, amt INT)")
    conn._conn.execute(
        "INSERT INTO orders VALUES ('C1','M1',10),('C2','M2',20),('C3','M1',30)"
    )
    conn._conn.execute("CREATE TABLE campaigns (id VARCHAR, name VARCHAR)")
    conn._conn.execute("INSERT INTO campaigns VALUES ('M1','spring'),('M2','summer')")
    return conn


_BAD = "SELECT c.name, SUM(o.amt) AS rev FROM orders o JOIN campaigns c ON o.cust = c.id GROUP BY c.name"
_GOOD = "SELECT c.name, SUM(o.amt) AS rev FROM orders o JOIN campaigns c ON o.camp = c.id GROUP BY c.name"


class _StubProvider:
    """Returns a QueryPlan (with _plan_sql) for planner calls and an SQLFix
    (with _fix_sql) for fix calls — distinguished by response_model."""

    def __init__(self, plan_sql: str, fix_sql: str):
        self._plan_sql = plan_sql
        self._fix_sql = fix_sql

    def complete(self, *, system, user, response_model):
        if response_model is QueryPlan:
            return QueryPlan(
                hypothesis_id="sq1", tables=["orders", "campaigns"],
                queries=[self._plan_sql], reasoning="stub",
            )
        if response_model is SQLFix:
            return SQLFix(fixed_sql=self._fix_sql, fix_explanation="stub", data_quality_issue=None)
        # Any other model (e.g. schema-linking) — build empties.
        kwargs = {n: "" for n in response_model.model_fields}
        return response_model(**kwargs)


def _state():
    return {
        "question": "revenue by campaign",
        "schema_context": "TABLE: orders\n  cust, camp, amt\nTABLE: campaigns\n  id, name\n",
        "data_catalog": "",
        "connection_id": "test",
        "sub_questions": [SubQuestion(
            id="sq1", question="revenue by campaign", depends_on=[],
            purpose="relationship", expected_output="revenue per campaign",
        )],
        "current_subq_idx": 0,
        "subq_answers": [],
        "pitfalls": [],
        "events_context": "",
        "analysis_ledger": "(none)",
        "subq_data_portrait": {},
    }


def _run(monkeypatch, plan_sql, fix_sql):
    from aughor.agent import explore as E
    monkeypatch.setattr(E, "get_provider", lambda role="coder": _StubProvider(plan_sql, fix_sql))
    # Neutralise schema-linking so the stub schema is used verbatim.
    monkeypatch.setattr("aughor.tools.schema_linker.link_schema", lambda *a, **k: "")
    out = E.plan_and_execute_subq(_state(), _conn())
    return out


def _norm(sql: str) -> str:
    return sql.replace('"', "").replace(" AS ", " ")


def test_explore_adopts_clearing_fix(monkeypatch):
    out = _run(monkeypatch, plan_sql=_BAD, fix_sql=_GOOD)
    qh = out["query_history"]
    assert len(qh) == 1
    assert qh[0].error is None
    assert qh[0].row_count > 0
    assert "o.camp = c.id" in _norm(qh[0].sql)


def test_explore_rejects_nonclearing_fix(monkeypatch):
    out = _run(monkeypatch, plan_sql=_BAD, fix_sql=_BAD)
    qh = out["query_history"]
    assert len(qh) == 1
    # Original kept (still disjoint) — never replaced with a still-broken rewrite.
    assert "o.cust = c.id" in _norm(qh[0].sql)
    # A data-quality pitfall carries the warning forward.
    assert any("MISMATCH" in p.fix_explanation for p in out["pitfalls"])


def test_explore_clean_join_no_repair(monkeypatch):
    out = _run(monkeypatch, plan_sql=_GOOD, fix_sql=_BAD)
    qh = out["query_history"]
    assert len(qh) == 1
    assert qh[0].row_count > 0
    assert "o.camp = c.id" in _norm(qh[0].sql)
    # No repair fired → no pitfalls.
    assert out["pitfalls"] == []
