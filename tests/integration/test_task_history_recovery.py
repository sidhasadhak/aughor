"""Rec 4 · leverage #1 — recover generated SQL from task_history on the REAL path.

Proves the eval-recovery contract end-to-end, not on a stub: the actual guarded
executor (`aughor.sql.executor.execute_guarded`, the code every answer runs) emits
a `sql.execute` span carrying the SQL, and `aughor.obs.task_history.recover_sql`
reads it back — "SELECT what the agent did" instead of parsing logs. Hermetic: a
temp DuckDB, the test-isolated ledger, no LLM.
"""
from __future__ import annotations

import duckdb
import pytest

import aughor.telemetry as tel
from aughor.db.connection import DuckDBConnection
from aughor.obs import task_history as th
from aughor.sql.executor import execute_guarded


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "recover.duckdb"
    w = duckdb.connect(str(path))
    w.execute("CREATE TABLE orders(order_id INTEGER, amount DOUBLE)")
    w.executemany("INSERT INTO orders VALUES (?,?)", [(i, 10.0) for i in range(5)])
    w.close()
    conn = DuckDBConnection(str(path))
    yield conn
    conn.close()


def test_recover_sql_from_real_executor(monkeypatch, db):
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "1")
    sql_a = "SELECT COUNT(*) AS n FROM orders"
    sql_b = "SELECT SUM(amount) AS total FROM orders"

    # A run = a node span with two guarded executions nested under it, exactly as a
    # real investigation node would drive them.
    with tel.span("run-recover", "explore", {"iteration": 0}):
        r1 = execute_guarded(db, sql_a, query_id="q_a")
        r2 = execute_guarded(db, sql_b, query_id="q_b")
    assert not r1.error and not r2.error

    # The eval harness recovers the executed SQL WITHOUT touching the pipeline's
    # return values — purely from the queryable table.
    recovered = th.recover_sql("run-recover")
    assert sql_a in recovered
    assert sql_b in recovered

    run = th.recover_run("run-recover")
    # per-node latency breakdown is available (Rec 4: "…and per-node latency")
    by_task = run.latency_by_task()
    assert "explore" in by_task and "sql.execute" in by_task
    # the sql.execute spans parent to the node span — one call tree per run
    node = next(s for s in run.spans if s["task"] == "explore")
    sql_spans = [s for s in run.spans if s["task"] == "sql.execute"]
    assert len(sql_spans) == 2
    assert all(s["parent_span_id"] == node["span_id"] for s in sql_spans)
    assert run.errors() == []


def test_recover_is_empty_when_flag_off(monkeypatch, db):
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "0")
    with tel.span("run-off", "explore", {"iteration": 0}):
        execute_guarded(db, "SELECT 1", query_id="q")
    assert th.recover_sql("run-off") == []
