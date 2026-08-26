"""The profiler's hand-built SQL must reach every engine in that engine's dialect.

Pinned because the original failure was silent three times over: on BigQuery a
double-quoted identifier is a string literal, so every profiler probe errored,
the profile came out empty, and the explorer treated "no profiler data" as a
successful no-op run — the whole intelligence layer (exploration, briefing,
ontology) never worked on any non-DuckDB/Postgres warehouse.
"""

from types import SimpleNamespace

from aughor.tools.profiler import (
    _NATIVE_PROFILER_DIALECTS,
    _TranspilingConnection,
    _parse_columns,
)


class _StubConn:
    dialect = "bigquery"
    _schema_name = "thelook"

    def __init__(self, rows=None):
        self.seen: list[str] = []
        self._rows = rows if rows is not None else []

    def execute(self, label, sql):
        self.seen.append(sql)
        return SimpleNamespace(error=None, rows=self._rows, columns=[])


def test_wrapper_transpiles_duckdb_flavor_to_backticks():
    stub = _StubConn()
    wrapped = _TranspilingConnection(stub)
    wrapped.execute("__profiler__", 'SELECT COUNT("a") AS n FROM "thelook"."orders"')
    assert len(stub.seen) == 1
    sent = stub.seen[0]
    assert "`orders`" in sent and '"orders"' not in sent


def test_wrapper_transpiles_casts_and_date_trunc():
    stub = _StubConn()
    wrapped = _TranspilingConnection(stub)
    wrapped.execute(
        "__profiler__",
        "SELECT date_trunc('month', \"created_at\")::VARCHAR AS m FROM \"orders\"",
    )
    sent = stub.seen[0]
    assert "::" not in sent
    assert "TRUNC" in sent.upper()


def test_wrapper_passes_unparseable_sql_through_unchanged():
    stub = _StubConn()
    wrapped = _TranspilingConnection(stub)
    weird = "PRAGMA definitely_not_sql("
    wrapped.execute("__profiler__", weird)
    assert stub.seen == [weird]


def test_wrapper_passes_attributes_through():
    stub = _StubConn()
    wrapped = _TranspilingConnection(stub)
    assert wrapped.dialect == "bigquery"
    assert wrapped._schema_name == "thelook"


def test_native_dialect_gate_covers_the_right_engines():
    # DuckDB is the flavor the SQL is written in; Postgres overlaps enough to run
    # it natively. Everything else must go through the transpiling wrapper.
    for native in ("", "duckdb", "postgres"):
        assert native in _NATIVE_PROFILER_DIALECTS
    for foreign in ("bigquery", "mysql", "snowflake"):
        assert foreign not in _NATIVE_PROFILER_DIALECTS


def test_every_connector_can_build_intelligence():
    # The explorer's ontology gate and the birth rite both call
    # db.build_intelligence(); it lived only on the DuckDB family, so no
    # warehouse engine could ever build an ontology (or a briefing).
    from aughor.connectors.base import Connector

    assert hasattr(Connector, "build_intelligence")
    from aughor.connectors.warehouse.bigquery import BigQueryConnection
    from aughor.connectors.warehouse.snowflake import SnowflakeConnection

    for cls in (BigQueryConnection, SnowflakeConnection):
        assert hasattr(cls, "build_intelligence")


def test_parse_columns_uses_portable_information_schema_and_connection_schema():
    stub = _StubConn(rows=[("id", "INT64"), ("created_at", "TIMESTAMP")])
    cols = _parse_columns(stub, "orders")
    assert cols == [("id", "INT64"), ("created_at", "TIMESTAMP")]
    sent = stub.seen[0]
    # Uppercase is the portable spelling: BigQuery requires it, Postgres folds it.
    assert "INFORMATION_SCHEMA.COLUMNS" in sent
    # The schema filter must come from the connection, never default to 'public'.
    assert "table_schema = 'thelook'" in sent
