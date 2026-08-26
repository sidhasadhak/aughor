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


def test_numeric_regex_matches_bigquery_type_names():
    # \bINT\b has no word boundary before "64", so INT64/FLOAT64 typed as "unknown",
    # no column was ever a measure on BigQuery, and the Phase-8 coverage manifest
    # came out empty — the LLM loop then re-asked the same questions with no memory.
    from aughor.tools.profiler import _NUMERIC_TYPES

    for t in ("INT64", "FLOAT64", "NUMERIC", "BIGNUMERIC", "BIGDECIMAL",
              "BIGINT", "DOUBLE", "UINTEGER", "DECIMAL(10,2)"):
        assert _NUMERIC_TYPES.search(t), t
    for t in ("STRING", "TIMESTAMP", "BOOL", "GEOGRAPHY"):
        assert not _NUMERIC_TYPES.search(t), t


def test_manifest_builds_cells_from_bigquery_shaped_profiles():
    # A measure with a range + a low-cardinality dimension must yield cells; with
    # zero cells Phase 8 has no deterministic questions and no coverage memory.
    from aughor.explorer.coverage_manifest import build_manifest

    tp = {"order_items": SimpleNamespace(date_columns=["created_at"])}
    cp = {
        "order_items.sale_price": SimpleNamespace(
            table="order_items", column="sale_price", semantic_type="measure",
            is_fk=False, value_range=(0.02, 999.0), unit=None,
            value_interpretation=None, is_low_cardinality=False, distinct_count=4188),
        "order_items.status": SimpleNamespace(
            table="order_items", column="status", semantic_type="dimension",
            is_fk=False, value_range=None, unit=None, value_interpretation=None,
            is_low_cardinality=True, distinct_count=5),
    }
    cells = build_manifest(tp, cp)
    assert cells, "BigQuery-shaped profiles must produce manifest cells"
    axes = {(c.metric, c.axis) for c in cells}
    assert ("sale_price", "headline") in axes
    assert any(m == "sale_price" and a == "dimension" for m, a in axes)


def test_schema_filter_extracts_tables_from_backticked_sql():
    # BigQuery/MySQL insights quote tables with backticks; the extractor knew only
    # double quotes and returned nothing, so the schema post-filter dropped every
    # warehouse insight and the Briefing emptied itself one fetch after rendering.
    from aughor.routers.exploration import _tables_from_sql

    assert _tables_from_sql("SELECT s, COUNT(*) FROM `order_items` GROUP BY 1") == {"order_items"}
    assert _tables_from_sql("SELECT s FROM `thelook`.`orders`") == {"orders", "thelook.orders"}
    assert _tables_from_sql('SELECT s FROM "thelook"."orders"') == {"orders", "thelook.orders"}
    assert _tables_from_sql("SELECT s FROM order_items JOIN `orders` o ON 1=1") == {"order_items", "orders"}


def test_no_lowercase_information_schema_anywhere():
    # BigQuery resolves lowercase information_schema as a DATASET NAME and 404s;
    # queries built with it silently return None/[] on every warehouse read that
    # uses them — the schema filter's None fail-closed turned that into the
    # "Briefing says no exploration ran / run exploration / still nothing" loop.
    # Uppercase works on every engine (DuckDB/MySQL case-insensitive, Postgres
    # folds down, Snowflake folds up), so lowercase dotted references are banned
    # outside demo seeds.
    import pathlib
    import re

    import aughor

    root = pathlib.Path(aughor.__file__).parent
    pat = re.compile(r"information_schema\.(tables|columns|schemata)")
    offenders = []
    for p in root.rglob("*.py"):
        if "demo" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                offenders.append(f"{p.relative_to(root)}:{i}")
    assert not offenders, f"lowercase information_schema references: {offenders}"


def test_parse_columns_uses_portable_information_schema_and_connection_schema():
    stub = _StubConn(rows=[("id", "INT64"), ("created_at", "TIMESTAMP")])
    cols = _parse_columns(stub, "orders")
    assert cols == [("id", "INT64"), ("created_at", "TIMESTAMP")]
    sent = stub.seen[0]
    # Uppercase is the portable spelling: BigQuery requires it, Postgres folds it.
    assert "INFORMATION_SCHEMA.COLUMNS" in sent
    # The schema filter must come from the connection, never default to 'public'.
    assert "table_schema = 'thelook'" in sent
