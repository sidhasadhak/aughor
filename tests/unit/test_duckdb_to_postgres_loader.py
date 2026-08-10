"""The DuckDB → Postgres loader's type policy and table discovery.

The copy itself needs a live Postgres and is verified by the script at run time — it
counts rows source against target and exits non-zero on any mismatch. What is worth
pinning without a server is the part that fails QUIETLY: the type mapping. A wrong row
count is loud and stops a deploy. A column that arrives in the wrong type is silent,
survives the copy, and shows up later as a number that does not add up.

This codebase has already paid for that exact failure — a currency column narrowed on
reload, losing data that looked fine until someone summed it, with `TRY_CAST('4.2' AS
BIGINT)` succeeding in DuckDB and hiding it. So the policy under test is not "map types
correctly", which is unfalsifiable, but the narrower and checkable claim: **nothing is
ever narrowed, and anything unrecognised lands in TEXT.**
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "load_duckdb_to_postgres.py"
_spec = importlib.util.spec_from_file_location("_loader", _SCRIPT)
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)          # type: ignore[union-attr]


@pytest.mark.parametrize("duck, pg", [
    ("BIGINT", "BIGINT"),
    ("INTEGER", "INTEGER"),
    ("DOUBLE", "DOUBLE PRECISION"),
    ("VARCHAR", "TEXT"),
    ("BOOLEAN", "BOOLEAN"),
    ("DATE", "DATE"),
    ("TIMESTAMP", "TIMESTAMP"),
    ("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"),
    ("UUID", "UUID"),
    ("JSON", "JSONB"),
    ("BLOB", "BYTEA"),
])
def test_known_types_map_exactly(duck, pg):
    assert loader._pg_type(duck) == pg


@pytest.mark.parametrize("duck, pg", [
    ("DECIMAL(18,2)", "NUMERIC(18,2)"),
    ("DECIMAL(38,9)", "NUMERIC(38,9)"),
    ("NUMERIC(10,4)", "NUMERIC(10,4)"),
])
def test_decimal_carries_its_precision(duck, pg):
    """A money column is the reason this branch exists. Dropping the scale would round
    every amount in the table, and nothing downstream would report it."""
    assert loader._pg_type(duck) == pg


@pytest.mark.parametrize("wide", ["HUGEINT", "UBIGINT"])
def test_types_wider_than_bigint_become_numeric_not_bigint(wide):
    """The narrowing test. Both of these overflow a Postgres BIGINT, and both would
    *usually* fit — a copy that works on the sample and truncates on the real data is
    worse than one that refuses."""
    assert loader._pg_type(wide) == "NUMERIC"


@pytest.mark.parametrize("exotic", [
    "STRUCT(a INTEGER, b VARCHAR)", "INTEGER[]", "MAP(VARCHAR, INTEGER)",
    "ENUM('a','b')", "SOMETHING_INVENTED_LATER", "",
])
def test_anything_unrecognised_lands_in_text(exotic):
    """The policy in one assertion. TEXT keeps the value readable and the problem
    visible; guessing keeps neither."""
    assert loader._pg_type(exotic) == "TEXT"


def test_the_duckdb_schema_name_is_preserved_by_default(tmp_path):
    """The app scopes a connection by schema name, so `luxexperience.orders` has to stay
    `luxexperience.orders`. Renaming it on the way across would break every saved
    reference to a table while the copy reported success."""
    duckdb = pytest.importorskip("duckdb")
    f = tmp_path / "demo.duckdb"
    con = duckdb.connect(str(f))
    con.execute("CREATE SCHEMA shop")
    con.execute("CREATE TABLE shop.orders (id BIGINT, total DECIMAL(18,2))")
    con.execute("INSERT INTO shop.orders VALUES (1, 9.99)")
    con.close()

    con = duckdb.connect(str(f), read_only=True)
    try:
        found = loader._tables(con, None)
    finally:
        con.close()

    assert ("shop", "orders") in found


def test_a_file_spanning_two_schemas_refuses_rather_than_picking_one(tmp_path, capsys):
    """Ambiguity is reported, not resolved by coin flip. Silently choosing one schema
    would copy half the file and call it done."""
    duckdb = pytest.importorskip("duckdb")
    f = tmp_path / "two.duckdb"
    con = duckdb.connect(str(f))
    con.execute("CREATE SCHEMA a; CREATE SCHEMA b")
    con.execute("CREATE TABLE a.t1 (x INTEGER)")
    con.execute("CREATE TABLE b.t2 (x INTEGER)")
    con.close()

    rc = loader.load(f, dsn="", target_schema=None, only=None, wipe=False, dry_run=True)

    assert rc == 2
    assert "--schema" in capsys.readouterr().err


def test_dry_run_touches_no_database(tmp_path, capsys):
    """`--dry-run` takes no credential and opens no connection, so inspecting a file is
    something anyone can do before deciding anything."""
    duckdb = pytest.importorskip("duckdb")
    f = tmp_path / "one.duckdb"
    con = duckdb.connect(str(f))
    con.execute("CREATE SCHEMA shop; CREATE TABLE shop.t (x INTEGER)")
    con.execute("INSERT INTO shop.t VALUES (1), (2), (3)")
    con.close()

    rc = loader.load(f, dsn="", target_schema=None, only=None, wipe=False, dry_run=True)

    out = capsys.readouterr().out
    assert rc == 0
    assert "3 rows" in out.replace(",", "")
    assert "nothing written" in out
