"""
Unit tests for the `task_history` spans-as-a-table sink (feature flag
`obs.task_table`, Rec 4 of the 2026-07-11 platform study).

Hermetic: the kernel ledger is already pointed at a temp `system.db` by
tests/conftest.py, so these assert directly against `Ledger.default()`.

The contract under test:

- Migration(4) creates the `task_history` table on ledger init.
- flag OFF → strict no-op: `span()` / `mlflow_tool_span` write NO rows
  (byte-identical default path).
- flag ON → one row per span, with Spice's shape; a tool span nested inside a
  node span inherits the node's trace_id and links `parent_span_id`; `sql` lands
  in the dedicated `input` column and the rest become labels.
- a body exception is recorded in `error_message` and then re-raised unchanged.
- `span_id` is idempotent (a re-emit replaces, never duplicates).
- parallel waves via ContextThreadPoolExecutor keep parent linkage per-worker
  (context is copied, child pushes don't leak back).
"""
from __future__ import annotations

import pytest

import aughor.telemetry as tel
from aughor.kernel.concurrency import ContextThreadPoolExecutor
from aughor.kernel.ledger import Ledger


@pytest.fixture
def on(monkeypatch):
    """Enable the flag for a test (env is read live, no caching)."""
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "1")


def _rows(trace_id):
    return Ledger.default().task_history(trace_id=trace_id, limit=100)


# ── table / migration ─────────────────────────────────────────────────────────

def test_migration_creates_table():
    cols = {
        r[1]
        for r in Ledger.default()._conn.execute("PRAGMA table_info(task_history)").fetchall()
    }
    assert {
        "span_id", "trace_id", "parent_span_id", "task", "input",
        "captured_output", "start_time", "end_time", "duration_ms",
        "error_message", "labels", "org_id",
    } <= cols


# ── flag OFF: byte-identical (no rows) ────────────────────────────────────────

def test_flag_off_writes_nothing(monkeypatch):
    monkeypatch.setenv("AUGHOR_OBS_TASK_TABLE", "0")
    with tel.span("trace-off", "decompose", {"iteration": 1}):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"}):
            pass
    assert _rows("trace-off") == []


# ── flag ON: node span row ────────────────────────────────────────────────────

def test_node_span_records_row(on):
    with tel.span("trace-node", "decompose", {"iteration": 3, "hypothesis_id": "h1"}):
        pass
    rows = _rows("trace-node")
    assert len(rows) == 1
    row = rows[0]
    assert row["task"] == "decompose"
    assert row["trace_id"] == "trace-node"
    assert row["parent_span_id"] is None
    assert row["duration_ms"] is not None and row["duration_ms"] >= 0
    assert row["error_message"] is None
    # non input/output metadata is preserved as labels
    assert row["labels"]["iteration"] == 3
    assert row["labels"]["hypothesis_id"] == "h1"


# ── flag ON: nested tool span inherits trace + links parent, SQL → input ──────

def test_nested_tool_span_inherits_trace_and_parent(on):
    with tel.span("trace-nest", "plan_queries", {"iteration": 0}):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT count(*) FROM orders",
                                                   "query_id": "q1", "dialect": "duckdb"}):
            pass
    rows = {r["task"]: r for r in _rows("trace-nest")}
    assert set(rows) == {"plan_queries", "sql.execute"}
    node, tool = rows["plan_queries"], rows["sql.execute"]
    # the tool span carried no trace_id itself but inherited the node's
    assert tool["trace_id"] == "trace-nest"
    # and links to the node as its parent
    assert tool["parent_span_id"] == node["span_id"]
    # SQL is lifted into the dedicated column; the rest are labels
    assert tool["input"] == "SELECT count(*) FROM orders"
    assert tool["labels"]["query_id"] == "q1"
    assert tool["labels"]["dialect"] == "duckdb"


# ── flag ON: body exception is captured then re-raised ────────────────────────

def test_body_exception_recorded_and_reraised(on):
    with pytest.raises(ValueError, match="boom"):
        with tel.span("trace-err", "synthesize", None):
            raise ValueError("boom")
    rows = _rows("trace-err")
    assert len(rows) == 1
    assert rows[0]["error_message"] == "ValueError: boom"


# ── flag ON: span_id idempotent (no duplicate on re-emit) ─────────────────────

def test_insert_is_idempotent_on_span_id(on):
    base = {
        "span_id": "fixed-span", "trace_id": "trace-idem", "task": "t",
        "start_time": "2026-07-13T00:00:00+00:00",
    }
    led = Ledger.default()
    led.task_history_insert(base)
    led.task_history_insert({**base, "task": "t2"})
    rows = _rows("trace-idem")
    assert len(rows) == 1
    assert rows[0]["task"] == "t2"  # REPLACE kept the latest


# ── flag ON: parallel waves keep parent linkage per-worker ────────────────────

def test_parallel_waves_link_to_submitting_span(on):
    def wave_leaf(i):
        with tel.mlflow_tool_span("sql.execute", {"sql": f"SELECT {i}"}):
            return None

    with tel.span("trace-par", "explore", {"iteration": 0}):
        with ContextThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(wave_leaf, range(3)))

    rows = {(_r["task"], _r["input"]): _r for _r in _rows("trace-par")}
    node = next(r for (t, _), r in rows.items() if t == "explore")
    leaves = [r for (t, _), r in rows.items() if t == "sql.execute"]
    assert len(leaves) == 3
    # every worker's tool span inherited the trace and parented to the node
    # (copy_context carried the stack in; worker pushes never leaked back out)
    for leaf in leaves:
        assert leaf["trace_id"] == "trace-par"
        assert leaf["parent_span_id"] == node["span_id"]


# ── obs.task_history recovery/analytics API ───────────────────────────────────

def test_recover_run_and_sql(on):
    from aughor.obs import task_history as th
    with tel.span("trace-api", "plan_queries", {"iteration": 0}):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 1"}):
            pass
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 2"}):
            pass
    run = th.recover_run("trace-api")
    assert run.sql_statements == ["SELECT 1", "SELECT 2"]  # execution order
    assert th.recover_sql("trace-api") == ["SELECT 1", "SELECT 2"]
    by_task = run.latency_by_task()
    assert "plan_queries" in by_task and "sql.execute" in by_task
    assert run.total_ms >= 0
    assert run.errors() == []


def test_recent_runs_and_slow_tasks(on):
    from aughor.obs import task_history as th
    with tel.span("trace-r1", "explore", None):
        with tel.mlflow_tool_span("sql.execute", {"sql": "SELECT 10"}):
            pass
    with tel.span("trace-r2", "synthesize", None):
        pass
    recent = {r["trace_id"]: r for r in th.recent_runs(limit=50)}
    assert "trace-r1" in recent and "trace-r2" in recent
    assert recent["trace-r1"]["sql"] == 1
    assert recent["trace-r2"]["sql"] == 0
    slow = {r["task"]: r for r in th.slow_tasks(limit=50)}
    assert "explore" in slow and slow["explore"]["count"] >= 1
    # prefix scopes to a task family
    sql_only = th.slow_tasks(task_prefix="sql.", limit=50)
    assert sql_only and all(r["task"].startswith("sql.") for r in sql_only)
