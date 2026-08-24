"""`/query/run` answered with the executor's statement, and two buttons persist that string.

The response's `sql` field carried `result.sql` — whatever the connector made of the query
on its way to the engine. Two things happen to a statement in there:

* the row cap wraps it — `SELECT * FROM (…) AS __q LIMIT n` — so a PREVIEW limit is baked
  into the text, and `__q` is a synthetic alias the user never wrote;
* `DuckDBConnection._run` transpiles through sqlglot, which renders a `:name` placeholder
  as `$name`. So one parameterised query came back spelled `$who` on a duckdb connection
  and `:who` on the Workspace, which has no transpile step.

That reads as cosmetic until you follow the field. `ResultsPanel` hands `result.sql`
straight to `pinQueryToDashboard` and to `onSchedule` — so a card pinned from a 50-row
preview was permanently capped at 50 and wrapped in a subquery, and a scheduled query
carried the same. `_write_builder_receipt` already recorded `body.sql` for exactly this
reason; the response field had simply never followed it.

Found by driving the live API after a restart, not by a test — the wrap and the `$who` are
both visible in the JSON and neither had ever been asserted.
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)

SQL = "SELECT id, name FROM t WHERE name = :who ORDER BY id"


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "echo.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE t AS SELECT i AS id, 'n' || i AS name FROM range(20) AS r(i)")
    c.close()
    cid = registry.add_connection("sql-echo", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def _run(cid: str, sql: str, **extra) -> dict:
    r = client.post("/query/run", json={"conn_id": cid, "sql": sql, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_response_echoes_the_statement_the_user_sent(conn):
    out = _run(conn, SQL, params={"who": "n3"}, limit=5, source="query_workbench")

    assert out["sql"] == SQL


def test_no_preview_limit_is_baked_into_the_echoed_sql(conn):
    """The consequence that matters: Pin and Schedule persist this string. A card pinned
    from a 5-row preview must not be a 5-row card forever."""
    out = _run(conn, SQL, params={"who": "n3"}, limit=5, source="query_workbench")

    assert "__q" not in out["sql"], "the executor's subquery wrap reached a persisted field"
    assert "LIMIT 5" not in out["sql"].upper()


def test_the_placeholder_keeps_the_spelling_the_user_typed(conn):
    """sqlglot renders `:who` as `$who` in the duckdb dialect. Echoing that back means the
    Pin button stores SQL the user cannot recognise — and cannot re-run through this same
    route, which speaks `:name`."""
    out = _run(conn, SQL, params={"who": "n3"}, limit=5, source="query_workbench")

    assert ":who" in out["sql"] and "$who" not in out["sql"]


def test_duckdb_and_the_workspace_now_agree(conn):
    """The two connectors differ by a transpile step, and that difference used to reach the
    client. Asserted across both because a fix applied to one path is this repo's most
    repeated bug."""
    duck = _run(conn, SQL, params={"who": "n3"}, limit=5, source="query_workbench")
    work = _run("workspace", "SELECT :n AS v", params={"n": 1}, limit=5,
                source="query_workbench")

    assert duck["sql"] == SQL
    assert work["sql"] == "SELECT :n AS v"


@pytest.mark.parametrize("fmt", [None, "typed"])
def test_both_response_shapes_answer_the_same_way(conn, fmt):
    """`format:"typed"` and the legacy shape are assembled in different places, and only
    one of them was ever going to get fixed by accident."""
    extra = {"format": fmt} if fmt else {}
    out = _run(conn, SQL, params={"who": "n3"}, limit=5, source="query_workbench", **extra)

    assert out["sql"] == SQL


def test_a_cache_hit_answers_with_the_same_string_as_the_live_run(conn):
    """A cached response is meant to be indistinguishable from the run it replaces. The
    cache stores the RESULT, whose `.sql` is the executor's form, so it was not."""
    first = _run(conn, SQL, params={"who": "n3"}, limit=5, use_cache=True,
                 source="query_workbench")
    second = _run(conn, SQL, params={"who": "n3"}, limit=5, use_cache=True,
                  source="query_workbench")

    assert first["sql"] == second["sql"] == SQL


def test_a_blocked_query_already_did_this_and_still_does(conn):
    """The one path that was always right — kept, so a refactor cannot quietly regress the
    only correct example the file had."""
    out = _run(conn, "DROP TABLE t", limit=5, source="query_workbench")

    assert out["sql"] == "DROP TABLE t"
    assert out["error"]


def test_the_signed_receipt_and_the_response_now_agree(conn):
    """They are two records of one run. `_write_builder_receipt` always stored `body.sql`;
    the response field disagreeing with it meant the drawer and the grid described the
    same query differently."""
    out = _run(conn, SQL, params={"who": "n3"}, limit=5, source="query_workbench")
    assert out.get("receipt_id"), "no receipt to compare against"

    receipt = client.get(f"/receipt/{out['receipt_id']}")
    assert receipt.status_code == 200, receipt.text
    # The receipt calls it `executed_sql`; `_write_builder_receipt` fills it from
    # `body.sql`. That name is a small lie either way — it is the statement the user asked
    # for, not the one the engine saw — but it is the RIGHT lie, because it is the one a
    # person can read, re-run and recognise.
    stored = [step["sql"] for step in receipt.json()["executed_sql"]]
    assert stored == [SQL] and out["sql"] == SQL
