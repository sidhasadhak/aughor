"""Monitor runner uses the real connection API (execute → QueryResult), not the phantom
`execute_query`. Regression for: every monitor check silently AttributeError'd on
`db.execute_query`, returned None, and reported "No condition met" — monitors never ran.
"""
from aughor.monitors.runner import _query, _scalar
from aughor.db.connection import DatabaseConnection


class _Result:
    def __init__(self, rows, error=None):
        self.rows = rows
        self.error = error


class ConnLike:
    """Implements execute(label, sql) like the real DuckDBConnection, and inherits the
    connection adapters (db.rows / db.scalar) the runner now delegates to — so the test
    exercises the real delegation path, not a re-implementation."""
    def __init__(self, rows, error=None):
        self._res = _Result(rows, error)
        self.calls = []

    def execute(self, label, sql):
        self.calls.append((label, sql))
        return self._res

    # the C3 adapters, bound from the ABC (they only call self.execute)
    rows = DatabaseConnection.rows
    scalar = DatabaseConnection.scalar


def test_query_uses_execute_and_returns_rows():
    db = ConnLike([(42,)])
    assert _query(db, "SELECT 42") == [(42,)]
    assert db.calls and db.calls[0][1] == "SELECT 42"


def test_query_returns_empty_on_error():
    db = ConnLike([], error="boom")
    assert _query(db, "SELECT 1") == []


def test_scalar_executes_against_connection_api():
    db = ConnLike([(5000,)])
    assert _scalar(db, "SELECT COUNT(*) FROM orders") == 5000.0


def test_scalar_handles_dict_rows():
    db = ConnLike([{"c": 17}])
    assert _scalar(db, "SELECT COUNT(*) AS c FROM orders") == 17.0


def test_scalar_none_on_error():
    db = ConnLike([], error="bad sql")
    assert _scalar(db, "SELECT nope") is None


def test_query_hands_the_connection_native_sql():
    """2026-09-26: theLook's Units Sold watch failed every minute on BigQuery with
    "Invalid date: 'created_at'" — the series SQL double-quotes identifiers (DuckDB's
    dialect, by design) and on BigQuery a double-quoted identifier is a string literal.
    The runner translates through the one seam every platform read uses."""
    import types
    seen = {}

    def rows(sql, label=""):
        seen["sql"] = sql
        return [("2026-09-01", 3.0)]
    bq = types.SimpleNamespace(dialect="bigquery", writes_native_sql=True, rows=rows)
    out = _query(bq, 'SELECT CAST("created_at" AS DATE) AS day, (COUNT(id)) AS value FROM inventory_items WHERE sold_at IS NOT NULL GROUP BY 1 ORDER BY 1')
    assert out == [("2026-09-01", 3.0)]
    assert '"created_at"' not in seen["sql"] and "`created_at`" in seen["sql"]
    # DuckDB gets it as written.
    duck = types.SimpleNamespace(dialect="duckdb", writes_native_sql=False, rows=rows)
    _query(duck, 'SELECT CAST("created_at" AS DATE) AS day FROM t')
    assert '"created_at"' in seen["sql"]


def test_scalar_hands_the_connection_native_sql_too():
    """The census after the anomaly fix found `_scalar` (threshold / any-change / trend
    monitors) still sending DuckDB quoting to native engines."""
    import types
    seen = {}

    def scalar(sql, label="", cast=float):
        seen["sql"] = sql
        return 1.0
    bq = types.SimpleNamespace(dialect="bigquery", writes_native_sql=True, scalar=scalar)
    assert _scalar(bq, 'SELECT COUNT(*) FROM "orders" WHERE "status" = \'x\'') == 1.0
    assert "`orders`" in seen["sql"] and '"orders"' not in seen["sql"]
