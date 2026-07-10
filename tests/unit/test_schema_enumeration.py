"""Schema enumeration must count `main` as a real schema when it holds tables.

`schemas_of_connection` excluded 'main' wholesale (treating it as DuckDB's default
namespace). A connection with data in BOTH main and other schemas — e.g. a workspace
where a new dataset was uploaded into `main` next to an older one — then looked
single-schema: canonical_schema() collapsed an explicit "explore schema main" to the
bare key, silently resuming the OLD run and never exploring the main-schema data.
"""
from __future__ import annotations

import duckdb
import pytest

from aughor.db import registry
from aughor.routers._shared import canonical_schema, schemas_of_connection


@pytest.fixture()
def two_schema_conn(tmp_path):
    db = tmp_path / "two.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE main.sales_transactions AS SELECT 1 AS a")
    c.execute("CREATE SCHEMA luxexperience")
    c.execute("CREATE TABLE luxexperience.brands AS SELECT 1 AS b")
    c.close()
    cid = registry.add_connection("two-schema", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


@pytest.fixture()
def main_only_conn(tmp_path):
    db = tmp_path / "one.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE main.customers AS SELECT 1 AS a")
    c.close()
    cid = registry.add_connection("main-only", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def test_main_counts_as_a_schema_alongside_others(two_schema_conn):
    assert set(schemas_of_connection(two_schema_conn)) == {"luxexperience", "main"}
    # An explicit "explore main" keeps its per-schema key instead of collapsing
    # to the bare connection (where it would resume an unrelated old run).
    assert canonical_schema(two_schema_conn, "main") == "main"
    assert canonical_schema(two_schema_conn, "luxexperience") == "luxexperience"


def test_single_main_schema_still_resolves_bare(main_only_conn):
    # A DB whose only schema is main keeps the bare-key behavior (no state split).
    assert canonical_schema(main_only_conn, "main") is None
