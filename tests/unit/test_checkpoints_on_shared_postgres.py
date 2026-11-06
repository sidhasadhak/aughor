"""Track B2 (docs/TENX_PROGRAM_2026-11-05.md): a paused investigation resumes on another process.

Measured 2026-11-06: with ``AUGHOR_DB_URL`` naming a Postgres every store moved there except the
LangGraph checkpointer, which kept a SQLite file on the local disk — a run paused on one host could
only resume on that host, and a second process sharing the database saw no checkpoint at all. The
exit, as the program wrote it: pause here, resume in a SECOND PROCESS pointed at the same database.
The graph is a three-node stand-in compiled with the platform's own ``_checkpointer`` — the thing
under test is where the checkpoint lives, not the investigation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import uuid

import pytest

from aughor.agent import graph as G

PG_URL = os.environ.get("AUGHOR_PG_TEST_URL", "postgres://postgres:aughor@localhost:5544/aughor")


def _pg_available() -> bool:
    try:
        import psycopg2
        psycopg2.connect(PG_URL, connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="needs a live shared Postgres")

#: The stand-in graph, as source, so the second process builds exactly the same one.
GRAPH_SRC = textwrap.dedent('''
    from typing import TypedDict
    from langgraph.graph import END, StateGraph
    from aughor.agent.graph import _checkpointer

    class S(TypedDict):
        steps: list

    def node(name):
        return lambda s: {"steps": [*s["steps"], name]}

    def build():
        g = StateGraph(S)
        for n in ("plan", "query", "write"):
            g.add_node(n, node(n))
        g.set_entry_point("plan"); g.add_edge("plan", "query"); g.add_edge("query", "write"); g.add_edge("write", END)
        return g.compile(checkpointer=_checkpointer(), interrupt_before=["write"])
''')


@pytest.fixture
def shared_db(monkeypatch):
    monkeypatch.setenv("AUGHOR_DB_URL", PG_URL)
    yield
    for saver in list(G._PG_SAVERS.values()):
        saver.conn.close()
    G._PG_SAVERS.clear()


def test_the_checkpointer_on_postgres_is_langgraphs_own_saver_in_the_stores_schema(shared_db):
    from langgraph.checkpoint.postgres import PostgresSaver

    from aughor.db.backend import store_schema
    saver = G._checkpointer()
    assert isinstance(saver, PostgresSaver)
    assert G._checkpointer() is saver                                      # one pool per process
    with saver.conn.connection() as conn:
        assert conn.execute("SHOW search_path").fetchone()["search_path"] == store_schema(G._CHECKPOINT_DB)


def test_a_run_paused_here_resumes_in_a_second_process(shared_db):
    ns: dict = {}
    exec(GRAPH_SRC, ns)
    thread = f"b2-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread}}
    paused = ns["build"]().invoke({"steps": []}, cfg)
    assert paused["steps"] == ["plan", "query"]                             # stopped before "write"
    assert G.read_checkpoint_state(thread)["exists"] is True

    # WHERE it lives is the claim. Two processes on one machine also share the local SQLite file, so a
    # resume alone cannot tell a shared database from a shared disk (the first falsifier run proved
    # exactly that: with the Postgres branch switched off, this test still passed). The rows are read
    # where they must be — the store's Postgres schema — and must be absent from the local file.
    import sqlite3

    import psycopg2

    from aughor.db.backend import store_schema
    table = f'"{store_schema(G._CHECKPOINT_DB)}".checkpoints'
    with psycopg2.connect(PG_URL) as pg, pg.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))      # absent table = no rows, not a crash
        rows = 0
        if cur.fetchone()[0]:
            cur.execute(f"SELECT count(*) FROM {table} WHERE thread_id = %s", (thread,))
            rows = cur.fetchone()[0]
        assert rows > 0, "the paused run is not in the shared database"
    if G._CHECKPOINT_DB.exists():
        with sqlite3.connect(f"file:{G._CHECKPOINT_DB}?mode=ro", uri=True) as local:
            has_table = local.execute("SELECT 1 FROM sqlite_master WHERE name = 'checkpoints'").fetchone()
            assert not has_table or not local.execute(
                "SELECT 1 FROM checkpoints WHERE thread_id = ?", (thread,)).fetchone(), "it went to the local disk"

    child = GRAPH_SRC + textwrap.dedent(f'''
        import json
        from aughor.agent.graph import read_checkpoint_state
        before = read_checkpoint_state({thread!r})
        if not before["exists"]:
            print(json.dumps({{"found": False, "values": {{}}, "done": []}})); raise SystemExit(0)
        done = build().invoke(None, {{"configurable": {{"thread_id": {thread!r}}}}})
        print(json.dumps({{"found": True, "values": before["values"], "done": done["steps"]}}))
    ''')
    # The second process resolves the SAME store location — as two hosts on one database do, each at the
    # default. Measured in the full suite: another test reloads `aughor.agent.graph` at a temp path and
    # never reloads it back, so this process's `_CHECKPOINT_DB` (and so its schema) differed from a fresh
    # import's, and the child looked in the wrong schema.
    env = {**os.environ, "AUGHOR_DB_URL": PG_URL, "AUGHOR_CHECKPOINTS_DB": str(G._CHECKPOINT_DB)}
    out = subprocess.run([sys.executable, "-c", child], env=env, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["found"] is True, "the second process found no checkpoint for the paused run"
    assert got["values"]["steps"] == ["plan", "query"]
    assert got["done"] == ["plan", "query", "write"]                       # resumed, finished elsewhere

    # And the first process sees what the second one did.
    assert G.read_checkpoint_state(thread)["values"]["steps"] == ["plan", "query", "write"]


def test_without_the_extra_the_first_checkpoint_says_what_to_install(shared_db, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_saver(name, *a, **k):
        if name.startswith("langgraph.checkpoint.postgres"):
            raise ImportError("not installed")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_saver)
    with pytest.raises(RuntimeError, match="shared-state"):
        G._checkpointer()


def test_sqlite_is_unchanged_when_no_database_is_named(monkeypatch):
    from langgraph.checkpoint.sqlite import SqliteSaver
    monkeypatch.delenv("AUGHOR_DB_URL", raising=False)
    assert isinstance(G._checkpointer(), SqliteSaver)
