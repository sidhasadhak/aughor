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
all four engines read before WHERE; the pair sample draws its 300 rows at random from it; and DuckDB
reads a large table's value lists whole, because a sample of 2,048-row blocks lists the wrong values
of a column whose rows are grouped.
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

#: One marker per scan the profiler issues on a large table. Asserting each one was issued keeps the guards below
#: from passing on an empty population, the day a threshold or a column gate stops a statement from being sent.
_SHAPES = {
    "pair sample": "S0",
    "batch scan": "COUNT(DISTINCT",
    "value ranges": "MIN(",
    "top values": "GROUP BY 1",
    "entity values": "SELECT DISTINCT",
}


@pytest.fixture(scope="module")
def large_flights(tmp_path_factory):
    """The repro table, profiled once — plus a catalog-miss pass, which is the only way DuckDB reaches the
    sampled batch scan and value ranges (SUMMARIZE covers every column otherwise).

    `origin_city` and `zone` are GROUPED, as a table loaded in key order is: each value holds one contiguous run
    of rows. `zone`'s runs shrink with its number, and neighbouring runs differ by less than one 2,048-row block,
    so only a read of the whole column lists its top ten in order.
    """
    path = tmp_path_factory.mktemp("large_table_sample") / "flights.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE flights AS SELECT range AS flight_id, "
        "CASE WHEN range % 30 = 0 THEN 'cancelled' WHEN range % 97 = 0 THEN 'diverted' ELSE 'arrived' END AS status, "
        f"'city_' || CAST(range * 120 // {_ROWS} AS VARCHAR) AS origin_city, "
        f"'zone_' || lpad(CAST(CAST(floor(25 * pow(range / {_ROWS}.0, 1.5)) AS INTEGER) AS VARCHAR), 2, '0') AS zone, "
        "CAST(range % 1440 AS DOUBLE) AS dep_minute "
        f"FROM range({_ROWS})"
    )
    con.close()

    db = open_connection("duckdb", str(path), connection_id="t")
    statements: list[tuple[str, str]] = []
    run = db.execute
    run_bounded = db.execute_bounded

    def recording(label, sql):
        result = run(label, sql)
        statements.append((sql, result.error or ""))
        return result

    # Both entry points, because the profiler reads through both: the entity value
    # sample and the dense date range go through `execute_bounded` (the bounded reads),
    # and a recorder wrapping only `execute` would report those statements as never
    # issued — which is exactly the miss `_SHAPES` exists to catch.
    def recording_bounded(label, sql, max_rows):
        result = run_bounded(label, sql, max_rows)
        statements.append((sql, result.error or ""))
        return result

    db.execute = recording
    db.execute_bounded = recording_bounded
    try:
        tables, columns = profile_connection(db, ["flights"], {"flights": set()})
        build_column_profiles(
            db, "flights", profiler._parse_columns(db, "flights"), set(), tables["flights"].row_count, fast_stats={})
    finally:
        db.close()
    yield SimpleNamespace(path=path, tables=tables, columns=columns, statements=statements)


def test_the_table_takes_the_sampled_path(large_flights):
    assert large_flights.tables["flights"].row_count > profiler._LARGE_TABLE_THRESHOLD


def test_a_large_table_keeps_its_top_values(large_flights):
    status = large_flights.columns["flights.status"]
    assert status.is_low_cardinality
    assert set(status.top_values or ()) == _STATUSES


def test_duckdb_lists_a_grouped_column_exactly(large_flights):
    assert large_flights.columns["flights.zone"].top_values == [f"zone_{k:02d}" for k in range(10)]


def test_a_large_table_keeps_its_whole_entity_value_sample(large_flights):
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


def test_every_profiler_statement_runs_on_a_large_duckdb_table(large_flights):
    statements = large_flights.statements
    missing = [shape for shape, marker in _SHAPES.items() if not any(marker in sql.upper() for sql, _ in statements)]
    assert not missing, f"no statement was issued for: {missing}"
    assert [(sql, error) for sql, error in statements if error] == []


class _Recorder:
    def __init__(self, dialect):
        self.dialect = dialect
        self.seen: list[str] = []

    def execute(self, label, sql):
        self.seen.append(sql)
        return SimpleNamespace(error=None, rows=[], columns=[], row_count=0)

    def execute_bounded(self, label, sql, max_rows):
        return self.execute(label, sql)


def _received_by(dialect: str) -> list[str]:
    """Every statement one large table's column profile sends, spelled as `dialect` receives it."""
    recorder = _Recorder(dialect)
    # Postgres is handed the profiler's own spelling and translates at its connection; the others run natively
    # behind the profiler's transpiling wrapper.
    conn = recorder if dialect == "postgres" else _TranspilingConnection(recorder)
    columns = [("id", "BIGINT"), ("status", "VARCHAR"), ("brand", "VARCHAR"), ("amount", "DOUBLE"), ("note", "VARCHAR")]
    stats = {   # `note` misses the catalog (the batch scan); `amount` has no min/max (the range scan)
        "id": {"approx_unique": 2_000_000},
        "status": {"approx_unique": 3},
        "brand": {"approx_unique": 400},
        "amount": {"approx_unique": 90_000},
    }
    build_column_profiles(conn, "orders", columns, set(), 2_000_000, fast_stats=stats)
    if dialect == "postgres":
        return [DatabaseConnection.translate(SimpleNamespace(dialect=dialect), sql) for sql in recorder.seen]
    return recorder.seen


def _reads_the_sample_first(sql: str) -> bool:
    body = " ".join(sql.upper().split())
    body = body[body.find(" FROM "):]
    at = body.find(" TABLESAMPLE ")
    return at >= 0 and not any(0 <= body.find(clause) < at for clause in (" WHERE ", " GROUP BY ", " ORDER BY ", " LIMIT "))


@pytest.mark.parametrize("dialect", ["postgres", "bigquery", "snowflake"])
def test_a_warehouse_samples_its_large_scans_before_where_and_limit(dialect):
    sampled = [sql for sql in _received_by(dialect) if "TABLESAMPLE" in sql.upper()]
    # The batch scan is exempt off Postgres: those engines count distincts approximately over the whole table.
    expected = [shape for shape in _SHAPES if shape != "batch scan" or dialect == "postgres"]
    unsampled = [shape for shape in expected if not any(_SHAPES[shape] in sql.upper() for sql in sampled)]
    assert not unsampled, f"issued without a sample: {unsampled}"
    assert [sql for sql in sampled if not _reads_the_sample_first(sql)] == []


def test_an_engine_without_table_samples_is_not_shuffled_whole():
    # sqlglot drops the sample for MySQL, so a shuffle there would sort every row of a large table to pick 300.
    recorder = _Recorder("mysql")
    profiler._row_sample(_TranspilingConnection(recorder), "orders", [("id", "BIGINT")],
                         profiler._LARGE_TABLE_THRESHOLD + 1)
    assert recorder.seen and not any("RAND" in sql.upper() for sql in recorder.seen)
