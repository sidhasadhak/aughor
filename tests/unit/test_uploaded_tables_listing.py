"""Listing an uploads connection's tables must not build its database.

`/catalog/tree` wants schema and table NAMES. Getting them by querying means opening
the connection, and opening materializes every uploaded file into DuckDB — measured
at 9.56s of a 9.87s tree locally, 97% of it, to learn names that were on disk the
whole time. Serverless cold-starts far too often to reach the warm cache, so it paid
that rebuild on essentially every request (`/catalog/tree` p50 13.2s in production).

`uploaded_tables()` reads the upload directory and the sidecars instead, and is a
module-level function precisely so that no connector is constructed.

Two things files alone get WRONG unless handled, and both are pinned here.

A tombstoned table must not reappear: the materialized database excludes it, so a
listing that included it would resurrect a deletion.

A SEEDED connection also materializes tables that no uploaded file describes, so
files alone under-report. Those names come from the seed's own catalogue — a file
open and one query — because `_seed_from_duckdb` reads exactly that list and only
THEN does `CREATE TABLE … AS`. The copy is the cost; naming a table never required
copying it.
"""
from __future__ import annotations

import json

import duckdb
import pytest

from aughor.connectors.file.local_upload import LocalUploadConnection, uploaded_tables
from aughor.control_plane import vending


@pytest.fixture(autouse=True)
def _isolate_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")


def _put(conn_id: str, schema: str, filename: str, *, table_name: str | None = None):
    """Write a data file (and optional sidecar) the way an ingest would."""
    root = vending.STORAGE_ROOT / "default" / conn_id
    d = root / schema
    d.mkdir(parents=True, exist_ok=True)
    f = d / filename
    f.write_text("a,b\n1,2\n")
    if table_name:
        f.with_name(f.name + ".import.json").write_text(json.dumps({"table_name": table_name}))
    return root


def test_it_lists_schemas_and_tables_without_opening_anything(monkeypatch):
    _put("c1", "sales", "orders.csv")
    _put("c1", "sales", "returns.csv")
    _put("c1", "ops", "shifts.csv")

    def _boom(*a, **k):
        raise AssertionError("a listing constructed the connector — that is the cost")
    monkeypatch.setattr(LocalUploadConnection, "__init__", _boom)

    assert uploaded_tables("c1") == {"ops": ["shifts"], "sales": ["orders", "returns"]}


def test_the_sidecar_table_name_wins_over_the_filename():
    _put("c1", "sales", "2026-q1 export.csv", table_name="q1_orders")
    assert uploaded_tables("c1") == {"sales": ["q1_orders"]}


def test_a_tombstoned_table_does_not_reappear():
    """The materialized database excludes it, so the listing must too — the tombstone,
    not the file's presence, is the authority on what the user removed."""
    root = _put("c1", "sales", "orders.csv")
    _put("c1", "sales", "returns.csv")
    (root / "_removed_seeds.json").write_text(json.dumps({"tables": ["sales.orders"]}))

    assert uploaded_tables("c1") == {"sales": ["returns"]}


def test_a_tombstoned_schema_does_not_reappear():
    root = _put("c1", "sales", "orders.csv")
    _put("c1", "ops", "shifts.csv")
    (root / "_removed_seeds.json").write_text(json.dumps({"schemas": ["sales"]}))

    assert uploaded_tables("c1") == {"ops": ["shifts"]}


def test_a_seeded_connection_includes_the_seed_tables(tmp_path):
    """A seed materializes tables no uploaded file describes. Naming them needs only
    the seed's catalogue — a file open — not the CREATE TABLE AS copy that is the
    actual cost. Dropping them would silently under-report the catalog."""
    p = tmp_path / "seed.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE SCHEMA demo")
    con.execute("CREATE TABLE demo.orders AS SELECT * FROM range(3) t(id)")
    con.close()
    _put("c1", "sales", "orders.csv")

    assert uploaded_tables("c1", {"seed_duckdb": str(p)}) == {
        "sales": ["orders"], "demo": ["orders"]}


def test_a_connection_with_no_uploads_lists_nothing_rather_than_declining():
    """Empty is a real answer and must not be confused with "cannot answer" — the
    caller treats None as a reason to go and query."""
    _put("c1", "main", "placeholder.csv")
    assert uploaded_tables("c2") == {}


def test_sidecar_files_are_not_mistaken_for_data():
    _put("c1", "sales", "orders.csv", table_name="orders")
    assert uploaded_tables("c1") == {"sales": ["orders"]}


def test_a_tombstoned_seed_table_is_not_named(tmp_path):
    """`_seed_from_duckdb` skips tombstoned entries when materializing, so naming
    them here would show tables the database does not actually contain."""
    p = tmp_path / "seed.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE SCHEMA demo")
    con.execute("CREATE TABLE demo.orders AS SELECT * FROM range(1) t(id)")
    con.execute("CREATE TABLE demo.keepme AS SELECT * FROM range(1) t(id)")
    con.close()
    root = _put("c1", "sales", "x.csv")
    (root / "_removed_seeds.json").write_text(json.dumps({"tables": ["demo.orders"]}))

    got = uploaded_tables("c1", {"seed_duckdb": str(p)})
    assert got["demo"] == ["keepme"]


def test_an_upload_does_not_duplicate_a_seed_table_of_the_same_name(tmp_path):
    """Uploads override seeds on a clash, so the name appears once, not twice."""
    p = tmp_path / "seed.duckdb"
    con = duckdb.connect(str(p))
    con.execute("CREATE SCHEMA sales")
    con.execute("CREATE TABLE sales.orders AS SELECT * FROM range(1) t(id)")
    con.close()
    _put("c1", "sales", "orders.csv")

    assert uploaded_tables("c1", {"seed_duckdb": str(p)}) == {"sales": ["orders"]}


def test_a_missing_seed_file_is_not_a_failure_to_answer(tmp_path):
    """The connector logs and carries on when the seed is gone; so must this, rather
    than sending the caller off to materialize."""
    _put("c1", "sales", "orders.csv")
    assert uploaded_tables("c1", {"seed_duckdb": str(tmp_path / "nope.duckdb")}) == {
        "sales": ["orders"]}
