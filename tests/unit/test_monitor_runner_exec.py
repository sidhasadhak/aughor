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
