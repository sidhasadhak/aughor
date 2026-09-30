"""The profiler's hand-built SQL must reach every engine in that engine's dialect.

Pinned because the original failure was silent three times over: on BigQuery a
double-quoted identifier is a string literal, so every profiler probe errored,
the profile came out empty, and the explorer treated "no profiler data" as a
successful no-op run — the whole intelligence layer (exploration, briefing,
ontology) never worked on any non-DuckDB/Postgres warehouse.

The translation was a private wrapper keyed on the dialect NAME, so Exasol — which declares
`postgres` while running SQL as written — was never translated. Since GM-1 every profiler
statement declares `sql_dialect="duckdb"` and the connection's door translates; the stub below
applies the door's step exactly as a native connector does.
"""

from types import SimpleNamespace

from aughor.db.dialects import sql_for_engine
from aughor.tools.profiler import (
    _NATIVE_PROFILER_DIALECTS,
    _parse_columns,
    build_column_profiles,
)


class _StubConn:
    """A native BigQuery connection: it runs what it is handed, after the door's dialect step."""
    dialect = "bigquery"
    writes_native_sql = True
    _schema_name = "thelook"

    def __init__(self, rows=None):
        self.seen: list[str] = []
        self.bounded: list[tuple[str, int]] = []
        self.declared: list = []
        self._rows = rows if rows is not None else []

    def execute(self, label, sql, *, sql_dialect=None, internal=False):
        self.declared.append(sql_dialect)
        self.seen.append(sql_for_engine(self, sql, sql_dialect))
        return SimpleNamespace(error=None, rows=self._rows, columns=[])

    def execute_bounded(self, label, sql, max_rows, *, sql_dialect=None, internal=False):
        self.declared.append(sql_dialect)
        self.bounded.append((sql_for_engine(self, sql, sql_dialect), max_rows))
        return SimpleNamespace(error=None, rows=self._rows, row_count=len(self._rows), columns=[])


def test_every_profiler_statement_is_declared_duckdb():
    """What the retired wrapper did for three engines by name, each statement now says for itself."""
    stub = _StubConn()
    _parse_columns(stub, "orders")
    columns = [("id", "INT64"), ("status", "STRING"), ("amount", "FLOAT64"), ("created_at", "TIMESTAMP")]
    build_column_profiles(stub, "orders", columns, set(), 50_000, fast_stats={})
    assert len(stub.declared) > 3, "the profiler issued too few statements to say anything"
    assert set(stub.declared) == {"duckdb"}, stub.declared


def test_the_door_renders_duckdb_flavor_as_backticks():
    stub = _StubConn()
    stub.execute("__profiler__", 'SELECT COUNT("a") AS n FROM "thelook"."orders"', sql_dialect="duckdb")
    assert len(stub.seen) == 1
    sent = stub.seen[0]
    assert "`orders`" in sent and '"orders"' not in sent


def test_the_door_renders_casts_and_date_trunc():
    stub = _StubConn()
    stub.execute(
        "__profiler__",
        "SELECT date_trunc('month', \"created_at\")::VARCHAR AS m FROM \"orders\"",
        sql_dialect="duckdb",
    )
    sent = stub.seen[0]
    assert "::" not in sent
    assert "TRUNC" in sent.upper()


def test_a_declared_bounded_read_is_rendered_and_keeps_its_bound():
    # The value sample reads past the answer cap through `execute_bounded`; the retired wrapper once handed the
    # engine's own one the DuckDB spelling untranspiled.
    stub = _StubConn()
    stub.execute_bounded(
        "__profiler__",
        'SELECT DISTINCT CAST("city" AS VARCHAR) AS v FROM "orders" WHERE "city" IS NOT NULL LIMIT 2001',
        2001,
        sql_dialect="duckdb",
    )
    assert stub.seen == []
    [(sent, max_rows)] = stub.bounded
    assert max_rows == 2001
    assert "`orders`" in sent and "`city`" in sent and '"' not in sent


def test_unparseable_sql_passes_through_unchanged():
    stub = _StubConn()
    weird = "PRAGMA definitely_not_sql("
    stub.execute("__profiler__", weird, sql_dialect="duckdb")
    assert stub.seen == [weird]


def test_the_approximate_distinct_gate_covers_the_right_engines():
    # DuckDB is the flavor the SQL is written in; Postgres overlaps enough to run it after its own
    # translation. The other engines take APPROX_COUNT_DISTINCT over a large table's batch scan.
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
    # BigQuery/MySQL findings quote tables with backticks; the extractor knew only
    # double quotes and returned nothing, so the schema post-filter dropped every
    # warehouse finding and the Briefing emptied itself one fetch after rendering.
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
