"""A large table is profiled from a sample, and the sample has to reach the engine as one.

`build_column_profiles` samples every table over `_LARGE_TABLE_THRESHOLD` rows. It spelled the
sample as DuckDB's query-level `USING SAMPLE 5 PERCENT`, written straight after the table name, in
front of WHERE and LIMIT — and neither reading of that statement ran:

- as written, DuckDB refuses it: its grammar has no place for that clause before WHERE;
- through `DuckDBConnection._normalize_to_duckdb`, sqlglot moves the clause to the very end, after
  LIMIT, which DuckDB refuses too. Postgres, BigQuery and Snowflake received that same shape.

The profiler reads a failed probe as "no values", so nothing said anything. Measured 2026-09-17 on
BTS's January 2019 on-time file (638,649 rows): `flights.status` had 3 values and no `top_values`,
so no lifecycle was ever detected on it, and the row-aligned pair sample fell back to the table's
first 300 rows. The sample now rides on the table — `FROM t TABLESAMPLE SYSTEM (5 PERCENT)` — which
all four engines read before WHERE, and the pair sample draws its 300 rows at random from it rather
than taking one sampled block's first 300.
"""
from __future__ import annotations

from types import SimpleNamespace

import duckdb
import pytest

import aughor.tools.profiler as profiler
from aughor.db.connection import DatabaseConnection, open_connection
from aughor.ontology.builder import extract_structural_ontology
from aughor.tools.profiler import _TranspilingConnection, build_column_profiles, profile_connection

_ROWS = 638_649   # the BTS table the defect was measured on
_STATUSES = {"arrived", "cancelled", "diverted"}
_CITIES = {f"city_{i}" for i in range(120)}

#: One marker per sampled statement the profiler writes. Asserting each one ran keeps the guard below from
#: passing on an empty population, the day a threshold or a column gate stops a statement from being issued.
_SAMPLED_SHAPES = {
    "pair sample": 'AS "s0"',
    "batch scan": "COUNT(DISTINCT",
    "value ranges": "MIN(",
    "top values": "GROUP BY 1",
    "entity values": "SELECT DISTINCT",
}


@pytest.fixture(scope="module")
def large_flights(tmp_path_factory):
    """The repro table, profiled once — plus a catalog-miss pass, which is the only way DuckDB reaches the
    sampled batch scan and value ranges (SUMMARIZE covers every column otherwise)."""
    path = tmp_path_factory.mktemp("large_table_sample") / "flights.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE flights AS SELECT range AS flight_id, "
        "CASE WHEN range % 30 = 0 THEN 'cancelled' WHEN range % 97 = 0 THEN 'diverted' ELSE 'arrived' END AS status, "
        "'city_' || CAST(range % 120 AS VARCHAR) AS origin_city, "
        "CAST(range % 1440 AS DOUBLE) AS dep_minute "
        f"FROM range({_ROWS})"
    )
    con.close()

    db = open_connection("duckdb", str(path), connection_id="t")
    statements: list[tuple[str, str]] = []
    run = db.execute

    def recording(label, sql):
        result = run(label, sql)
        statements.append((sql, result.error or ""))
        return result

    db.execute = recording
    try:
        tables, columns = profile_connection(db, ["flights"], {"flights": set()})
        build_column_profiles(
            db, "flights", profiler._parse_columns(db, "flights"), set(), tables["flights"].row_count, fast_stats={})
    finally:
        db.close()
    yield SimpleNamespace(path=path, tables=tables, columns=columns, statements=statements)


def _sampled(statements):
    return [(sql, error) for sql, error in statements if "SAMPLE" in sql.upper()]


def test_the_table_takes_the_sampled_path(large_flights):
    assert large_flights.tables["flights"].row_count > profiler._LARGE_TABLE_THRESHOLD


def test_a_large_table_keeps_its_top_values(large_flights):
    status = large_flights.columns["flights.status"]
    assert status.is_low_cardinality
    assert set(status.top_values or ()) == _STATUSES


def test_a_large_table_keeps_its_entity_value_sample(large_flights):
    assert set(large_flights.columns["flights.origin_city"].value_sample or ()) == _CITIES


def test_the_lifecycle_the_top_values_enable(large_flights):
    graph = extract_structural_ontology("t", "main", "fp", large_flights.tables, large_flights.columns,
                                        {"joins": [], "no_join": []}, {})
    (flight,) = [e for e in graph.entities.values() if "flights" in e.source_tables]
    assert flight.lifecycle_column == "status"
    assert set(flight.lifecycle_states) == _STATUSES
    assert flight.terminal_states == ["cancelled"]


def test_the_pair_sample_is_spread_across_the_table(large_flights):
    # `flight_id` is the row number and DuckDB samples SYSTEM by 2,048-row vector, so rows from one sampled block
    # share one `flight_id // 2048`. LIMIT without a shuffle returns exactly that block, as does the prefix fallback —
    # and on BTS one carrier's block of two-letter codes read as a US-state column.
    db = open_connection("duckdb", str(large_flights.path), connection_id="t")
    try:
        columns = profiler._parse_columns(db, "flights")
        samples = profiler._row_sample(db, "flights", columns, large_flights.tables["flights"].row_count)
    finally:
        db.close()
    (ids,) = [sample.values for sample in samples if sample.column == "flight_id"]
    assert len(ids) == profiler._PAIR_SAMPLE_ROWS
    assert len({int(v) // 2048 for v in ids}) > 1


def test_every_sampled_profiler_statement_runs(large_flights):
    sampled = _sampled(large_flights.statements)
    missing = [shape for shape, marker in _SAMPLED_SHAPES.items() if not any(marker in sql for sql, _ in sampled)]
    assert not missing, f"no sampled statement was issued for: {missing}"
    assert [(sql, error) for sql, error in sampled if error] == []


def _reads_the_sample_first(sql: str) -> bool:
    body = " ".join(sql.upper().split())
    body = body[body.find(" FROM "):]
    at = body.find(" TABLESAMPLE ")
    return at >= 0 and not any(0 <= body.find(clause) < at for clause in (" WHERE ", " GROUP BY ", " ORDER BY ", " LIMIT "))


class _Recorder:
    def __init__(self, dialect):
        self.dialect = dialect
        self.seen: list[str] = []

    def execute(self, label, sql):
        self.seen.append(sql)
        return SimpleNamespace(error=None, rows=[], columns=[])


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "snowflake"])
def test_every_warehouse_receives_the_sample_before_where_and_limit(large_flights, dialect):
    # Postgres translates at its connection; BigQuery and Snowflake run natively behind the profiler's wrapper.
    sampled = [sql for sql, _ in _sampled(large_flights.statements)]
    assert sampled
    if dialect == "postgres":
        sent = [DatabaseConnection.translate(SimpleNamespace(dialect=dialect), sql) for sql in sampled]
    else:
        recorder = _Recorder(dialect)
        for sql in sampled:
            _TranspilingConnection(recorder).execute("__profiler__", sql)
        sent = recorder.seen
    assert [sql for sql in sent if not _reads_the_sample_first(sql)] == []


def test_an_engine_without_table_samples_is_not_shuffled_whole():
    # sqlglot drops the sample for MySQL, so a shuffle there would sort every row of a large table to pick 300.
    recorder = _Recorder("mysql")
    profiler._row_sample(_TranspilingConnection(recorder), "orders", [("id", "BIGINT")],
                         profiler._LARGE_TABLE_THRESHOLD + 1)
    assert recorder.seen and not any("RAND" in sql.upper() for sql in recorder.seen)
