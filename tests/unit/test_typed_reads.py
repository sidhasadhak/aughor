"""Every connector hands back typed values and reads past its cap when bounded (Arc ON leftovers, O1).

A cross-source object query joins its sides in memory from the values each source holds, so a connector that offered
no typed rows was refused as a side: BigQuery, Snowflake, MySQL and Exasol, and the five DuckDB-backed connectors
(MotherDuck, S3, Google Sheets, the federated connection, the REST syncs), whose execute was one body copied five times.
The copies became one shared read; the warehouses offer their drivers' values with each column's type named the way
the stage reads it."""
from __future__ import annotations

import importlib

import duckdb
import pytest


# ── the five DuckDB-backed connectors, through the one shared read ───────────────────────────


DUCKDB_BACKED = [
    ("aughor.connectors.warehouse.motherduck", "MotherDuckConnection", "_conn", "aughor.connectors.warehouse.motherduck"),
    ("aughor.connectors.file.s3", "S3Connection", "_duckdb", "aughor.connectors.file.s3"),
    ("aughor.connectors.api.gsheets", "GoogleSheetsConnector", "_duckdb", "aughor.connectors.api.gsheets"),
    ("aughor.connectors.federated", "FederatedConnection", "_duckdb", "aughor.connectors.federated"),
    ("aughor.connectors.api.stripe", "StripeConnector", "_duckdb", "aughor.connectors.api.base_sync"),
]


@pytest.mark.parametrize("module, name, handle, caps", DUCKDB_BACKED, ids=[row[1] for row in DUCKDB_BACKED])
def test_a_duckdb_backed_connector_offers_typed_values_a_bounded_read_and_the_heal(module, name, handle, caps,
                                                                                    monkeypatch):
    cls = getattr(importlib.import_module(module), name)
    monkeypatch.setattr(importlib.import_module(caps), "MAX_ROWS", 5)
    conn = cls.__new__(cls)
    conn._connection_id = "typed-read-t"
    db = duckdb.connect(":memory:")
    db.execute("CREATE TABLE t AS SELECT range AS n, 'x' || range AS s FROM range(7)")
    setattr(conn, handle, db)
    try:
        cut = conn.execute("q", "SELECT n, s FROM t ORDER BY n")
        assert cut.error is None, cut.error
        assert (len(cut.rows), cut.row_count) == (5, 7)
        whole = conn.execute_bounded("__source_keys__", "SELECT n FROM t", 100)
        assert (len(whole.rows), whole.row_count) == (7, 7)
        _, payload = conn.read_typed_rows("__source_keys__", "SELECT n, s FROM t ORDER BY n", 3)
        assert payload is not None, "no typed rows offered"
        assert payload["rows"] == [[0, "x0"], [1, "x1"], [2, "x2"]] and payload["truncated"] is True
        assert payload["types"] == ["BIGINT", "VARCHAR"]
        healed = conn.execute("q", "SELECT ROUND(JULIANDAY(TIMESTAMP '2024-01-01 18:00:00') - "
                                   "JULIANDAY(TIMESTAMP '2024-01-01 06:00:00'), 2) AS d")
        assert healed.error is None and healed.rows == [["0.5"]] and "julian(" in healed.sql.lower()
    finally:
        db.close()


# ── the warehouses, driven by fakes of their drivers ─────────────────────────────────────────


class _Cursor:
    """A DB-API cursor over fixed rows with a description; a context manager too, as pymysql's is."""

    def __init__(self, rows, description):
        self._rows, self._at, self.description = rows, 0, description

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._at = 0

    def fetchmany(self, size):
        out = self._rows[self._at:self._at + size]
        self._at += len(out)
        return out


def _snowflake(monkeypatch):
    import aughor.connectors.warehouse.snowflake as S
    monkeypatch.setattr(S, "MAX_ROWS", 2)
    conn = S.SnowflakeConnection.__new__(S.SnowflakeConnection)
    rows = [(i, f"x{i}") for i in range(5)]
    description = [("n", 0, None, None, 38, 0, True), ("s", 2, None, None, None, None, True)]   # FIXED(38,0), TEXT
    conn._conn = type("Conn", (), {"cursor": lambda _s: _Cursor(rows, description)})()
    return conn


def _mysql(monkeypatch):
    from pymysql.constants import FIELD_TYPE

    import aughor.connectors.warehouse.mysql as M
    monkeypatch.setattr(M, "MAX_ROWS", 2)
    conn = M.MySQLConnection.__new__(M.MySQLConnection)
    rows = [{"n": i, "s": f"x{i}"} for i in range(5)]
    description = [("n", FIELD_TYPE.LONGLONG, None, None, None, None, None),
                   ("s", FIELD_TYPE.VAR_STRING, None, None, None, None, None)]
    conn._conn = type("Conn", (), {"cursor": lambda _s: _Cursor(rows, description),
                                   "ping": lambda _s, reconnect=True: None})()
    return conn


def _exasol(monkeypatch):
    import aughor.connectors.warehouse.exasol as E
    monkeypatch.setattr(E, "MAX_ROWS", 2)
    conn = E.ExasolConnection.__new__(E.ExasolConnection)
    rows = [(i, f"x{i}") for i in range(5)]

    class Statement(_Cursor):
        def columns(self):
            return {"n": {"type": "DECIMAL", "precision": 18, "scale": 0}, "s": {"type": "VARCHAR", "size": 10}}

    conn._conn = type("Conn", (), {"execute": lambda _s, sql: Statement(rows, None)})()
    return conn


def _bigquery(monkeypatch):
    pytest.importorskip("google.cloud.bigquery")
    from google.cloud.bigquery import SchemaField

    import aughor.connectors.warehouse.bigquery as B
    monkeypatch.setattr(B, "MAX_ROWS", 2)
    conn = B.BigQueryConnection.__new__(B.BigQueryConnection)
    conn._project, conn._dataset = "p", "d"
    data = [(i, f"x{i}") for i in range(5)]

    class Row:
        def __init__(self, values):
            self._values = values

        def values(self):
            return self._values

    class Job:
        def result(self, max_results=None):
            rows = [Row(v) for v in data][:max_results]
            return type("Rows", (), {"schema": [SchemaField("n", "INTEGER"), SchemaField("s", "STRING")],
                                     "__iter__": lambda _s: iter(rows)})()

    conn._client = type("Client", (), {"query": lambda _s, sql, job_config=None: Job()})()
    return conn


@pytest.mark.parametrize("make", [_snowflake, _mysql, _exasol, _bigquery], ids=["snowflake", "mysql", "exasol", "bigquery"])
def test_a_warehouse_offers_typed_values_named_for_the_stage_and_a_bounded_read(make, monkeypatch):
    conn = make(monkeypatch)
    conn._connection_id = "typed-read-t"
    _, payload = conn.read_typed_rows("__source_keys__", "SELECT n, s FROM t", 3)
    assert payload is not None, "no typed rows offered"
    assert payload["rows"] == [[0, "x0"], [1, "x1"], [2, "x2"]] and payload["truncated"] is True
    assert payload["types"] == ["BIGINT", "VARCHAR"]
    whole = conn.execute_bounded("__source_keys__", "SELECT n, s FROM t", 100)
    assert (len(whole.rows), whole.row_count) == (5, 5)
    capped = conn.execute("q", "SELECT n, s FROM t")
    assert (len(capped.rows), capped.row_count) == (2, 3)


@pytest.mark.parametrize("kind, precision, scale, named", [
    ("INT64", None, None, "BIGINT"), ("FLOAT64", None, None, "DOUBLE"), ("NUMERIC", None, None, "DECIMAL(38,9)"),
    ("NUMERIC", 12, 2, "DECIMAL(12,2)"), ("FIXED", 38, 0, "BIGINT"), ("NEWDECIMAL", 10, 4, "DECIMAL(10,4)"),
    ("BOOL", None, None, "BOOLEAN"), ("NEWDATE", None, None, "DATE"), ("TIMESTAMP_NTZ", None, None, "TIMESTAMP"),
    ("DATETIME", None, None, "TIMESTAMP"), ("GEOGRAPHY", None, None, "VARCHAR"), ("", None, None, ""),
])
def test_a_driver_type_is_named_the_way_the_stage_reads_it(kind, precision, scale, named):
    from aughor.connectors.base import stage_type
    assert stage_type(kind, precision, scale) == named
