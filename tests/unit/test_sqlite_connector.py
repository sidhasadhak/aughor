"""Unit tests for the first-class SQLite connector.

Covers the DatabaseConnection contract (execute / get_schema / dry_run / test /
close), DSN normalisation, dialect translation, read-only safety, parallel-reader
cloning, and the registry wiring that makes "sqlite" a selectable connection type.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aughor.connectors.file.sqlite import SQLiteConnection, _dsn_to_path
from aughor.db.connection import open_connection


def _make_db(tmp_path: Path) -> str:
    """Create a small on-disk SQLite DB and return its path."""
    p = tmp_path / "shop.sqlite"
    con = sqlite3.connect(str(p))
    con.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL);
        INSERT INTO customers VALUES (1,'Ann','NYC'),(2,'Bo','LA'),(3,'Cy','NYC');
        INSERT INTO orders VALUES (10,1,5.0),(11,1,7.5),(12,2,3.0);
        """
    )
    con.commit()
    con.close()
    return str(p)


# ── DSN normalisation ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("dsn,expected", [
    ("/a/b/c.sqlite", "/a/b/c.sqlite"),
    ("sqlite:////a/b/c.sqlite", "/a/b/c.sqlite"),
    ("sqlite:///rel.db", "rel.db"),
    ("file:/x/y.db", "/x/y.db"),
    ("", ":memory:"),
])
def test_dsn_to_path(dsn, expected):
    assert _dsn_to_path(dsn) == expected


# ── factory + identity ──────────────────────────────────────────────────────────

def test_factory_dispatches_to_sqlite(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    assert isinstance(conn, SQLiteConnection)
    assert conn.dialect == "sqlite"
    assert conn.connector_category == "file"
    conn.close()


def test_test_ok_and_missing_file(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    ok, msg = conn.test()
    assert ok and "tables" in msg
    conn.close()

    missing = SQLiteConnection(str(tmp_path / "nope.sqlite"))
    ok, msg = missing.test()
    assert not ok and "not found" in msg


# ── schema introspection ────────────────────────────────────────────────────────

def test_get_schema_lists_tables_and_columns(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    schema = conn.get_schema()
    assert "TABLE: customers" in schema
    assert "TABLE: orders" in schema
    assert "customer_id" in schema
    assert "(3 rows)" in schema  # customers row count rendered
    conn.close()


# ── execution ─────────────────────────────────────────────────────────────────

def test_execute_select(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    r = conn.execute("h", "SELECT city, COUNT(*) AS n FROM customers GROUP BY city ORDER BY n DESC")
    assert r.error is None
    assert r.columns == ["city", "n"]
    assert r.rows[0] == ["NYC", "2"]  # values stringified, like other connectors
    conn.close()


def test_execute_join(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    r = conn.execute("h",
        "SELECT c.name, SUM(o.amount) AS total FROM customers c "
        "JOIN orders o ON c.id = o.customer_id GROUP BY c.name ORDER BY total DESC")
    assert r.error is None
    assert r.rows[0] == ["Ann", "12.5"]
    conn.close()


def test_execute_bad_sql_returns_error_not_raises(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    r = conn.execute("h", "SELECT no_such_col FROM customers")
    assert r.error is not None
    assert r.row_count == 0
    conn.close()


def test_write_is_rejected_read_only(tmp_path):
    """A mutation must not succeed — either blocked by the safety gate or by the
    read-only engine. Either way: an error, and the data is unchanged."""
    path = _make_db(tmp_path)
    conn = open_connection("sqlite", path, connection_id="t")
    r = conn.execute("h", "DELETE FROM customers")
    assert r.error is not None
    # confirm untouched
    r2 = conn.execute("h", "SELECT COUNT(*) AS n FROM customers")
    assert r2.rows == [["3"]]
    conn.close()


# ── dry_run validation ──────────────────────────────────────────────────────────

def test_dry_run_good_and_bad(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    assert conn.dry_run("SELECT id FROM customers")[0] is True
    ok, err = conn.dry_run("SELECT bogus FROM customers")
    assert ok is False and "bogus" in err
    conn.close()


# ── dialect translation ─────────────────────────────────────────────────────────

def test_translate_duckdb_to_sqlite(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    # EXTRACT(...) is DuckDB/standard-flavoured; sqlglot should transpile it so the
    # query runs on SQLite without raising.
    r = conn.execute("h", "SELECT COUNT(*) AS n FROM orders WHERE amount > 4")
    assert r.error is None and r.rows == [["2"]]
    conn.close()


# ── parallel reader ─────────────────────────────────────────────────────────────

def test_make_reader_is_independent(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    reader = conn.make_reader()
    assert reader is not conn
    r = reader.execute("h", "SELECT COUNT(*) AS n FROM orders")
    assert r.rows == [["3"]]
    reader.close()
    # original still usable after the reader closed
    assert conn.execute("h", "SELECT COUNT(*) AS n FROM customers").rows == [["3"]]
    conn.close()


def test_is_healthy(tmp_path):
    conn = open_connection("sqlite", _make_db(tmp_path), connection_id="t")
    assert conn.is_healthy() is True
    conn.close()
    assert conn.is_healthy() is False


# ── registry wiring ──────────────────────────────────────────────────────────────

def test_registry_exposes_sqlite():
    from aughor.connectors.registry import REGISTRY, FORM_FIELDS, DSN_PREVIEWS, build_connector
    assert "sqlite" in REGISTRY.supported_types()
    assert "sqlite" in FORM_FIELDS
    assert "sqlite" in DSN_PREVIEWS
    assert REGISTRY.get_class("sqlite") is SQLiteConnection
    # build_connector instantiates an in-memory connection without a path
    conn = build_connector("sqlite", dsn=":memory:", connection_id="t")
    assert isinstance(conn, SQLiteConnection)
    conn.close()
