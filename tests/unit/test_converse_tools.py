"""The tools a converse turn may choose — and the inversion they enforce.

The point of these tests is not that the tools return data. It is that the model
cannot reach the warehouse EXCEPT through the guarded chokepoint, that the guard
receipts arrive with the rows rather than being reconstructed afterwards, and that a
tool asked about something that does not exist answers rather than raises.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aughor.agent import converse_tools as ct


class _Result:
    def __init__(self, **kw):
        self.sql = kw.get("sql", "")
        self.columns = kw.get("columns", ["n"])
        self.rows = kw.get("rows", [[412]])
        self.row_count = kw.get("row_count", 1)
        self.error = kw.get("error")
        self.caveats = kw.get("caveats", [])


@pytest.fixture
def fake_conn(monkeypatch):
    # The real schema-render format: `TABLE: name` then two-space-indented columns.
    schema = "TABLE: analytics.orders\n  order_id  BIGINT\n  total  DOUBLE\n"
    conn = SimpleNamespace(get_schema=lambda: schema)
    monkeypatch.setattr(ct, "_connection", lambda cid: conn)
    return conn


def test_run_sql_goes_through_the_guarded_chokepoint(monkeypatch, fake_conn):
    """The inversion. The model picks the tool; the guards are not optional and not
    the model's to skip — so the tool must call `execute_guarded`, never a raw cursor."""
    seen = {}

    def _guarded(conn, sql, *, query_id, **kw):
        seen["sql"] = sql
        seen["query_id"] = query_id
        return _Result()

    monkeypatch.setattr("aughor.sql.executor.execute_guarded", _guarded)

    out = ct.run_sql("c1", {"sql": "SELECT count(*) FROM orders"})

    assert seen["sql"] == "SELECT count(*) FROM orders"
    assert out["row_count"] == 1


def test_guard_receipts_ride_back_with_the_rows(monkeypatch, fake_conn):
    """#279 shipped the collector with no consumer; this is it. A number handed over
    without the guard record is the thing this product exists not to do."""
    from aughor.kernel.registries import execution_hooks

    def _guarded(conn, sql, *, query_id, **kw):
        execution_hooks.emit_guard_receipt(
            "defan", "rewrote", "collapsed a fan-out join")
        return _Result()

    monkeypatch.setattr("aughor.sql.executor.execute_guarded", _guarded)

    out = ct.run_sql("c1", {"sql": "SELECT 1"})

    assert out["guard_receipts"], "the guards did something and the model was not told"
    assert out["guard_receipts"][0]["guard"] == "defan"


def test_caveats_reach_the_model(monkeypatch, fake_conn):
    """A query that ran without error can still be silently wrong — that knowledge has
    to arrive with the number, not be dropped at the boundary."""
    monkeypatch.setattr("aughor.sql.executor.execute_guarded",
                        lambda *a, **k: _Result(caveats=["value-disjoint join"]))

    assert ct.run_sql("c1", {"sql": "SELECT 1"})["caveats"] == ["value-disjoint join"]


def test_large_results_are_truncated_and_say_so(monkeypatch, fake_conn):
    """The model reasons about a shape. A 10k-row answer spends the context the rest of
    the conversation needs — but silently truncating would make it miscount."""
    monkeypatch.setattr("aughor.sql.executor.execute_guarded",
                        lambda *a, **k: _Result(rows=[[i] for i in range(500)],
                                                row_count=500))

    out = ct.run_sql("c1", {"sql": "SELECT 1"})

    assert len(out["rows"]) == ct._MAX_PREVIEW_ROWS
    assert out["truncated"] is True
    assert out["row_count"] == 500, "the true count must survive the preview"


def test_empty_sql_is_an_answer_not_a_crash(fake_conn):
    assert "error" in ct.run_sql("c1", {"sql": "   "})


def test_describe_table_finds_a_table_by_bare_name(fake_conn):
    """Models write `orders`, schemas store `analytics.orders`."""
    out = ct.describe_table("c1", {"table": "orders"})

    assert out["table"] == "analytics.orders"
    assert "order_id" in out["columns"]


def test_a_missing_table_answers_with_the_real_ones(fake_conn):
    """P2 again: the near-misses are what let the model recover instead of inventing
    a column list for a table that does not exist."""
    out = ct.describe_table("c1", {"table": "ordrs"})

    assert out["error"] == "no such table"
    assert "analytics.orders" in out["available"]


def test_the_connection_is_bound_not_model_supplied(fake_conn):
    """A tool that cannot express the wrong connection cannot be talked into it — so
    `connection_id` must not appear in any tool's parameter schema."""
    for spec in ct.converse_tools("c1"):
        props = spec.parameters.get("properties", {})
        assert "connection" not in props and "connection_id" not in props, spec.name


def test_every_tool_carries_a_description_that_can_route(fake_conn):
    """Descriptions ARE the routing policy (P3) — there is no intent classifier, so an
    empty or terse one is a tool the model cannot choose correctly."""
    for spec in ct.converse_tools("c1"):
        assert len(spec.description) > 60, f"{spec.name} cannot be routed on"


def test_the_system_prompt_states_rather_than_scripts(fake_conn):
    """It must name the warehouse and the guard contract without re-stating the routing
    policy, which would become a second, drifting copy of the tool descriptions."""
    prompt = ct.converse_system_prompt("superstore")

    assert "superstore" in prompt
    assert "caveat" in prompt.lower()
    assert "run_sql" not in prompt, "routing belongs in the tool descriptions, once"
