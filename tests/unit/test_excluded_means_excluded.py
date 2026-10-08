"""Excluded means excluded — exploration principles §6 (2026-10-08).

The user, 2026-10-07: a schema or table a person turns off "must never be queried by investigation
or quick analysis. That should close the loop." Before this, `ontology/visibility.py` recorded the
exclusion and only a coverage count read it: the explorer, Investigation and Quick analysis all
still queried the table. Now the door every statement passes refuses it — the platform's own probes
included — the schema text no longer lists it, and the explorer never lists it; a person's own
reads (the SQL editor, the Catalog) still pass.
"""
from __future__ import annotations

import uuid

import duckdb
import pytest

from aughor.db.connection import open_connection
from aughor.ontology import visibility as V


@pytest.fixture
def wh(tmp_path):
    """A warehouse with the same table name in a staging and a business schema."""
    path = tmp_path / "wh.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA stage; CREATE SCHEMA marts")
    con.execute("CREATE TABLE stage.orders AS SELECT 1 AS id, 'x' AS raw_payload")
    con.execute("CREATE TABLE marts.orders AS SELECT 1 AS order_id, 10.0 AS amount")
    con.execute("CREATE TABLE marts.customers AS SELECT 1 AS customer_id")
    con.close()
    conn_id = f"wh-{uuid.uuid4().hex[:8]}"
    yield conn_id, str(path)
    V._cache.pop(conn_id, None)


def test_a_turned_off_schema_is_refused_with_the_reason_and_the_rest_is_read(wh):
    conn_id, path = wh
    db = open_connection("duckdb", path, connection_id=conn_id)
    V.declare_exclusion(conn_id, "stage", V.SCHEMA_WIDE, "out_of_domain", declared_by="user:amit")

    refused = db.execute("chat", "SELECT * FROM stage.orders")
    assert refused.error.startswith("[EXCLUDED]") and "stage.orders" in refused.error
    assert "Catalog" in refused.error and "user:amit" in refused.error
    assert "blocked:exclusion" in refused.doors
    assert not db.execute("chat", "SELECT * FROM marts.orders").error


def test_the_platforms_own_probes_are_refused_too_but_a_persons_reads_pass(wh):
    conn_id, path = wh
    db = open_connection("duckdb", path, connection_id=conn_id)
    V.declare_exclusion(conn_id, "marts", "customers", "sensitive", declared_by="user:amit")

    probe = db.execute("__explorer__", "SELECT COUNT(*) FROM marts.customers", internal=True)
    assert probe.error.startswith("[EXCLUDED]"), "an internal probe ran past the exclusion"
    hidden = db.execute("chat", "WITH c AS (SELECT * FROM marts.customers) SELECT * FROM c")
    assert hidden.error.startswith("[EXCLUDED]"), "a CTE hid the excluded table from the door"
    for label in ("query_workbench", "sample"):
        assert not db.execute(label, "SELECT * FROM marts.customers").error, label


def test_an_unqualified_name_resolves_to_the_doors_own_schema(wh):
    conn_id, path = wh
    V.declare_exclusion(conn_id, "stage", "orders", "deprecated", declared_by="user:amit")
    staged = open_connection("duckdb", path, schema_name="stage", connection_id=conn_id)
    marts = open_connection("duckdb", path, schema_name="marts", connection_id=conn_id)
    assert staged.execute("chat", "SELECT * FROM orders").error.startswith("[EXCLUDED]")
    assert not marts.execute("chat", "SELECT * FROM orders").error, "marts.orders is not stage.orders"


def test_the_schema_text_no_longer_lists_it_and_is_unchanged_when_nothing_is_off(wh):
    conn_id, path = wh
    db = open_connection("duckdb", path, schema_name="marts", connection_id=conn_id)
    before = db.get_schema()
    assert "marts.orders" in before and "marts.customers" in before

    V.declare_exclusion(conn_id, "marts", "customers", "sensitive", declared_by="user:amit")
    text = db.get_schema()
    assert "marts.customers" not in text and "customer_id" not in text
    assert "marts.orders" in text and "amount" in text

    assert V.withdraw_exclusion(conn_id, "marts", "customers")
    assert db.get_schema() == before, "nothing turned off must leave the schema text byte for byte"


def test_without_tables_takes_out_only_the_named_block():
    from aughor.db.schema_render import without_tables
    text = ("TABLE: a.x  (3 rows)\n  id  INTEGER\n  name  VARCHAR\n\n"
            "TABLE: a.y  (1 rows)\n  id  INTEGER\n\nDETECTED JOINS\n  a.x.id → a.y.id\n")
    out = without_tables(text, lambda n: n == "a.x")
    assert out.startswith("TABLE: a.y") and "name" not in out and "DETECTED JOINS" in out
    assert without_tables(text, lambda n: False) == text


def test_the_explorer_never_lists_a_turned_off_table(wh):
    from aughor.explorer.agent import SchemaExplorer
    conn_id, path = wh
    V.declare_exclusion(conn_id, "stage", V.SCHEMA_WIDE, "out_of_domain", declared_by="user:amit")
    db = open_connection("duckdb", path, connection_id=conn_id)
    ex = SchemaExplorer(conn_id, db)
    tp, _cp, _j = ex._load_profiler_data()
    assert tp and not any(t.startswith("stage.") for t in tp), list(tp)
    assert ex._turned_off == 1


def test_a_connector_that_renders_its_own_schema_text_hands_it_out_without_them(tmp_path):
    """DuckDB's renderer drops the table itself; every other connector writes its own text, and
    `open_connection` is where all of them are built — SQLite stands in for the warehouses here."""
    import sqlite3
    path = tmp_path / "wh.sqlite"
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE orders (id INTEGER, amount REAL); CREATE TABLE secrets (id INTEGER, ssn TEXT);")
    con.close()
    conn_id = f"sq-{uuid.uuid4().hex[:8]}"
    db = open_connection("sqlite", f"sqlite:///{path}", connection_id=conn_id)
    before = db.get_schema()
    assert "secrets" in before and "orders" in before
    V.declare_exclusion(conn_id, "main", "secrets", "sensitive", declared_by="user:amit")
    text = db.get_schema()
    assert "secrets" not in text and "ssn" not in text and "orders" in text
    assert db.execute("chat", "SELECT * FROM secrets").error.startswith("[EXCLUDED]")
    V._cache.pop(conn_id, None)


def test_a_cached_result_for_a_turned_off_table_is_never_served():
    """Found live 2026-10-08: the Cockpit measured Uber's three metrics from `ncr_ride_bookings` after it
    was turned off — every statement was answered from the result cache, which sits in front of the door."""
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.db import matcache
    conn_id = f"mc-{uuid.uuid4().hex[:8]}"
    sql = "SELECT COUNT(*) FROM uber.rides"
    matcache.put_cache(conn_id, sql, QueryResult(hypothesis_id="h", sql=sql, columns=["n"], rows=[[7]], row_count=1))
    assert matcache.get_cached(conn_id, sql).rows == [[7]]
    V.declare_exclusion(conn_id, "uber", "rides", "other", declared_by="user:amit")
    assert matcache.get_cached(conn_id, sql) is None, "a turned-off table's cached rows were served"
    assert V.withdraw_exclusion(conn_id, "uber", "rides")
    assert matcache.get_cached(conn_id, sql).rows == [[7]]
    V._cache.pop(conn_id, None)


def test_a_metric_reading_a_turned_off_table_says_so_whole_never_that_its_query_failed():
    from datetime import date
    from types import SimpleNamespace

    from aughor.semantic import metric_time as mt
    m = SimpleNamespace(sql="SUM(amount)", tables=["uber.rides"], time_kind="flow", time_column="uber.rides.day",
                        until_column="", outcome_column="", filters=[])
    why = "[EXCLUDED] uber.rides is turned off for analysis — it is excluded (other, by amit). Turn it back on in the Catalog to use it."
    rows, said = mt.run_measure(m, [mt.Window("current", date(2026, 1, 1), date(2026, 1, 2))],
                                lambda sql: ([], [], why))
    assert rows == [] and said.startswith("uber.rides is turned off") and said.endswith("to use it.")
