"""Rec 4 · leverage #2 — the `aughor_ops` self-investigation connection.

"Aughor investigates Aughor": the platform's own span/job/event tables become a
queryable connection so Deep Analysis can ask "why were yesterday's briefings
slow?" as an ordinary investigation. Hermetic — the ledger is the test-isolated
temp system.db; spans are emitted through the real telemetry seam.

Contract:
- flag OFF → the connection is neither listed nor openable (no point pointing an
  investigator at an always-empty table).
- flag ON → it is listed, opens, exposes a curated aughor_ops.* schema, and reads
  back the spans the platform just recorded.
- it is read-only: the AST mutation gate blocks writes even though it is a DuckDB
  connection.
"""
from __future__ import annotations

import pytest

import aughor.telemetry as tel
from aughor.db import registry
from aughor.db.connection import open_connection_for


def _emit_a_run():
    with tel.span("ops-run", "explore", {"iteration": 0}):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"}):
            pass


# ── flag OFF: hidden + not openable ───────────────────────────────────────────

def test_absent_when_flag_off(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "0")
    assert registry.AUGHOR_OPS_ID not in [c["id"] for c in registry.list_connections()]
    with pytest.raises(KeyError):
        registry.get_dsn(registry.AUGHOR_OPS_ID)


# ── flag ON: listed, opens, self-investigates ─────────────────────────────────

def test_listed_and_queryable_when_flag_on(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "1")
    _emit_a_run()

    listed = {c["id"]: c for c in registry.list_connections()}
    assert registry.AUGHOR_OPS_ID in listed
    assert listed[registry.AUGHOR_OPS_ID]["conn_type"] == "aughor_ops"

    conn = open_connection_for(registry.AUGHOR_OPS_ID)
    schema = conn.get_schema()
    assert "aughor_ops.task_history" in schema
    assert "aughor_ops.jobs" in schema

    # the investigator reads the spans the platform just recorded
    res = conn.execute("q", "SELECT task, count(*) AS n FROM aughor_ops.task_history "
                            "WHERE trace_id = 'ops-run' GROUP BY task ORDER BY task")
    assert res.error is None
    counts = {row[0]: int(row[1]) for row in res.rows}
    assert counts == {"explore": 1, "sql.execute": 1}


def test_recovered_sql_is_visible_in_ops_connection(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "1")
    with tel.span("ops-sql", "plan_queries", None):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 42 AS answer"}):
            pass
    conn = open_connection_for(registry.AUGHOR_OPS_ID)
    res = conn.execute("q", "SELECT input FROM aughor_ops.task_history "
                            "WHERE trace_id = 'ops-sql' AND task = 'sql.execute'")
    assert res.error is None
    assert res.rows and res.rows[0][0] == "SELECT 42 AS answer"


# ── read-only: the mutation gate blocks writes ────────────────────────────────

@pytest.mark.parametrize("stmt", [
    "DROP TABLE aughor_ops.task_history",
    "INSERT INTO aughor_ops.task_history (span_id, task, start_time) VALUES ('x','y','z')",
    "UPDATE aughor_ops.task_history SET task = 'z'",
])
def test_mutations_are_blocked(monkeypatch, stmt):
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "1")
    _emit_a_run()
    conn = open_connection_for(registry.AUGHOR_OPS_ID)
    res = conn.execute("q", stmt)
    assert res.error, f"expected {stmt!r} to be blocked"
