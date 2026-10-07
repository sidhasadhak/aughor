"""Ask this briefing — the conversation keeps to the Briefing's schema and reads the Briefing on screen.

Measured 2026-10-06 (trace f6c0d51e): on `workspace` / `uber_ncr`, "Which city is generating
highest revenue?" arrived with `schema: "uber_ncr"` and was answered from `luxexperience.orders`
and `data_co.data_co_supplychain`. The quick body had honoured the schema for months; the
converse body — the default since SP-14 — handed its tools the bare connection, so `list_tables`
showed every dataset on the connection, and the brief block lived only behind a tool call that
carried no schema.
"""
from __future__ import annotations

import asyncio

import pytest

WORKSPACE_ALL = ("TABLE: luxexperience.orders  (5 rows)\n  ship_country  VARCHAR\n"
                 "TABLE: data_co.data_co_supplychain  (9 rows)\n  Order City  VARCHAR\n"
                 "TABLE: uber_ncr.rides  (10 rows)\n  pickup_location  VARCHAR")


class _Db:
    def __init__(self, text: str):
        self.text = text

    def get_schema(self) -> str:
        return self.text


class _Scope:
    """What `resolve_execution_scope` hands back: the scoped connection opens on ONE schema."""

    def __init__(self, schema, tables=()):
        self.declared_schema = schema
        self.tables = tuple(tables)

    @property
    def is_full_schema(self) -> bool:
        return not self.tables

    def open(self):
        return _Db(f"TABLE: {self.declared_schema}.rides  (10 rows)\n  pickup_location  VARCHAR")


@pytest.fixture
def workspace(monkeypatch):
    from aughor.canvas import scope as scope_mod
    from aughor.db import connection as conn_mod
    monkeypatch.setattr(conn_mod, "open_connection_for", lambda cid: _Db(WORKSPACE_ALL))
    monkeypatch.setattr(scope_mod, "resolve_execution_scope",
                        lambda cid, canvas_id=None, *, schema_scope=None, **kw: _Scope(schema_scope))


def test_list_tables_lists_only_the_schema_in_scope(workspace):
    from aughor.agent.converse_tools import list_tables
    out = list_tables("workspace", {}, schema_scope="uber_ncr")
    assert "uber_ncr.rides" in out["schema"]
    assert "luxexperience" not in out["schema"] and "data_co" not in out["schema"]
    assert out["scope"].startswith("schema uber_ncr only")


def test_an_unscoped_turn_still_sees_the_whole_connection(workspace):
    from aughor.agent.converse_tools import list_tables
    out = list_tables("workspace", {})
    assert out == {"schema": WORKSPACE_ALL}


def test_describe_table_cannot_reach_another_dataset(workspace):
    from aughor.agent.converse_tools import describe_table
    out = describe_table("workspace", {"table": "data_co.data_co_supplychain"}, schema_scope="uber_ncr")
    assert out.get("error") == "no such table"
    assert out["available"] == ["uber_ncr.rides"]


def test_every_data_tool_is_bound_to_the_turns_scope(monkeypatch):
    from aughor.agent import converse_tools as ct
    names = ("answer_question", "run_sql", "list_tables", "describe_table", "deep_analysis")
    seen: dict = {}

    def spy(name):
        def run(connection_id, args, **kw):
            seen[name] = kw.get("schema_scope")
            return {}
        return run

    for name in names:
        monkeypatch.setattr(ct, name, spy(name))
    tools = {t.name: t for t in ct.converse_tools("workspace", schema_scope="uber_ncr")}
    for name in names:
        tools[name].run({})
    assert seen == {name: "uber_ncr" for name in names}


def test_answer_question_hands_the_scope_to_the_quick_body(monkeypatch):
    from aughor.agent import converse_tools as ct
    from aughor.routers import investigations as inv
    got: dict = {}

    class _Done(Exception):
        pass

    def core(question, connection_id, history, **kw):
        got.update(kw)
        raise _Done()

    monkeypatch.setattr(inv, "answer_core", core)
    with pytest.raises(_Done):
        ct.answer_question("workspace", {"question": "Which city?"}, schema_scope="uber_ncr")
    assert got["schema_scope"] == "uber_ncr"


def test_run_sql_executes_on_the_scoped_connection(monkeypatch):
    from aughor.agent import converse_tools as ct
    got: dict = {}

    class _Done(Exception):
        pass

    def connection(connection_id, **kw):
        got.update(kw)
        raise _Done()

    monkeypatch.setattr(ct, "_connection", connection)
    with pytest.raises(_Done):
        ct.run_sql("workspace", {"sql": "SELECT 1"}, schema_scope="uber_ncr")
    assert got == {"canvas_id": None, "schema_scope": "uber_ncr"}


# ── The converse body: scope said, brief read, both threaded ──────────────────

def _drive(monkeypatch, **kwargs) -> dict:
    """Run one converse turn up to the loop call and return what the loop was handed."""
    from aughor.agent import converse_tools as ct
    from aughor.knowledge import brief_context as bc
    from aughor.routers import investigations as inv

    captured: dict = {}

    class _Stop(Exception):
        pass

    def fake_converse(connection_id, question, **kw):
        captured.update(kw)
        raise _Stop()

    def fake_brief(*args, **kw):
        captured["brief_call"] = (args, kw)
        return "BRIEF BLOCK FOR THE PERIOD\n"

    monkeypatch.setattr(ct, "converse", fake_converse)
    monkeypatch.setattr(ct, "tools_unsupported", lambda exc: False)
    monkeypatch.setattr(bc, "brief_block_for_scope", fake_brief)

    async def drain():
        async for _ in inv._stream_converse("Which city is generating highest revenue?",
                                            "workspace", [], session_id="s-brief", **kwargs):
            pass

    asyncio.run(drain())
    return captured


def test_a_briefing_ask_threads_the_scope_and_reads_the_open_period(monkeypatch):
    key = "range:last_month:2026-08-01..2026-08-31"
    got = _drive(monkeypatch, surface="briefing", schema_scope="uber_ncr", brief_period=key)
    assert got["schema_scope"] == "uber_ncr"
    assert "SCOPE — this conversation is pinned to schema 'uber_ncr'" in got["extra_context"]
    assert "BRIEF BLOCK FOR THE PERIOD" in got["extra_context"]
    args, kw = got["brief_call"]
    assert args[:2] == ("workspace", "uber_ncr")
    assert kw == {"period_key": key, "from_briefing": True}


def test_other_surfaces_get_no_brief_and_no_scope_line(monkeypatch):
    got = _drive(monkeypatch, surface="catalog")
    assert "brief_call" not in got
    assert "SCOPE —" not in (got.get("extra_context") or "")
    assert got["schema_scope"] is None


def test_the_ask_door_threads_scope_and_period_to_both_quick_bodies():
    """The /ask fork has two quick bodies; a field reaching one and not the other is the
    exact shape of this defect (the converse body never got `schema_scope`)."""
    import inspect

    from aughor.routers import investigations as inv
    src = inspect.getsource(inv._stream_ask)
    assert src.count("schema_scope=req.schema_name") >= 2
    assert src.count("brief_period=req.brief_period") >= 2


def test_the_loop_entry_binds_its_tools_to_the_scope(monkeypatch):
    """`converse()` builds the tool set; the scope must reach it, not stop at the loop."""
    from aughor.agent import converse_tools as ct
    from aughor.agent import tool_loop
    got: dict = {}

    def tools(connection_id, **kw):
        got.update(kw)
        return []

    monkeypatch.setattr(ct, "converse_tools", tools)
    monkeypatch.setattr(ct, "converse_system_prompt", lambda *a, **k: "")
    monkeypatch.setattr(tool_loop, "run_tool_loop", lambda *a, **k: "ran")
    assert ct.converse("workspace", "Which city?", provider=object(), schema_scope="uber_ncr") == "ran"
    assert got["schema_scope"] == "uber_ncr"
