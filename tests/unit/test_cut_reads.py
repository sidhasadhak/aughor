"""A read its connection cut is known to be cut (Arc ON leftovers, S2).

Every consumer that needs a WHOLE read — the key measurement across connections, the join engine's reads, the federated
driver — detects a cut the same way: `row_count` counting more rows than `rows` holds. SQLite, BigQuery, Exasol, MySQL
and Snowflake fetched only up to their cap and reported the capped count, so a cut read looked complete; each now
fetches one row past its cap. The Workspace and SQLite connections also read past their caps when a caller bounds the
read, where every cross-source measurement and keyed read on them used to stop at the cap."""
from __future__ import annotations

import sqlite3

import pytest

from aughor.connectors.file.sqlite import SQLiteConnection


# ── SQLite, capped at the shared 500 ───────────────────────────────────────────────────────────


def _sqlite(tmp_path, n: int) -> SQLiteConnection:
    path = tmp_path / f"rows_{n}.sqlite"
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (n INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(n)])
    con.commit()
    con.close()
    return SQLiteConnection(str(path))


def test_sqlite_counts_a_read_its_cap_cut_and_reads_past_the_cap_when_bounded(tmp_path):
    over = _sqlite(tmp_path, 505)
    cut = over.execute("q", "SELECT n FROM t")
    assert (len(cut.rows), cut.row_count) == (500, 501)
    whole = over.execute_bounded("__source_keys__", "SELECT n FROM t", 1000)
    assert (len(whole.rows), whole.row_count) == (505, 505)
    bound = over.execute_with_params("q", "SELECT n FROM t WHERE n >= :lo", {"lo": 0})
    assert (len(bound.rows), bound.row_count) == (500, 501)
    _, payload = over.read_typed_rows("__source_keys__", "SELECT n FROM t", 500)
    assert payload["truncated"] is True and len(payload["rows"]) == 500

    exact = _sqlite(tmp_path, 500)
    full = exact.execute("q", "SELECT n FROM t")
    assert (len(full.rows), full.row_count) == (500, 500)
    _, payload = exact.read_typed_rows("__source_keys__", "SELECT n FROM t", 500)
    assert payload["truncated"] is False    # exactly the cap is every row, not a cut read


# ── warehouses that fetch up to a cap: MySQL, Snowflake, Exasol, BigQuery (driven by fakes) ───────


class _Cursor:
    """A DB-API cursor over fixed rows; a context manager too, as pymysql's is."""

    def __init__(self, rows):
        self._rows, self._at, self.description = rows, 0, [("n",)]

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


def _mysql(monkeypatch, n):
    import aughor.connectors.warehouse.mysql as M
    monkeypatch.setattr(M, "MAX_ROWS", 3)
    conn = M.MySQLConnection.__new__(M.MySQLConnection)
    rows = [{"n": i} for i in range(n)]
    conn._conn = type("Conn", (), {"cursor": lambda _s: _Cursor(rows), "ping": lambda _s, reconnect=True: None})()
    return conn


def _snowflake(monkeypatch, n):
    import aughor.connectors.warehouse.snowflake as S
    monkeypatch.setattr(S, "MAX_ROWS", 3)
    conn = S.SnowflakeConnection.__new__(S.SnowflakeConnection)
    rows = [(i,) for i in range(n)]
    conn._conn = type("Conn", (), {"cursor": lambda _s: _Cursor(rows)})()
    return conn


def _exasol(monkeypatch, n):
    import aughor.connectors.warehouse.exasol as E
    monkeypatch.setattr(E, "MAX_ROWS", 3)
    conn = E.ExasolConnection.__new__(E.ExasolConnection)
    rows = [(i,) for i in range(n)]

    class Statement(_Cursor):
        def columns(self):
            return {"n": "DECIMAL"}

    conn._conn = type("Conn", (), {"execute": lambda _s, sql: Statement(rows)})()
    return conn


def _bigquery(monkeypatch, n):
    pytest.importorskip("google.cloud.bigquery")
    import aughor.connectors.warehouse.bigquery as B
    monkeypatch.setattr(B, "MAX_ROWS", 3)
    conn = B.BigQueryConnection.__new__(B.BigQueryConnection)
    conn._project, conn._dataset = "p", "d"

    class Row:
        def __init__(self, i):
            self._i = i

        def values(self):
            return (self._i,)

    class Job:
        def result(self, max_results=None):
            rows = [Row(i) for i in range(n)][:max_results]
            return type("Rows", (), {"schema": [type("F", (), {"name": "n"})()], "__iter__": lambda _s: iter(rows)})()

    conn._client = type("Client", (), {"query": lambda _s, sql, job_config=None: Job()})()
    return conn


@pytest.mark.parametrize("make", [_mysql, _snowflake, _exasol, _bigquery], ids=["mysql", "snowflake", "exasol", "bigquery"])
def test_a_warehouse_counts_a_read_its_cap_cut(make, monkeypatch):
    over = make(monkeypatch, 5)
    over._connection_id, over.max_rows = "cut-read-t", 3
    cut = over.execute("q", "SELECT n FROM t")
    assert cut.error is None, cut.error
    assert (len(cut.rows), cut.row_count) == (3, 4)

    exact = make(monkeypatch, 3)
    exact._connection_id, exact.max_rows = "cut-read-t", 3
    full = exact.execute("q", "SELECT n FROM t")
    assert (len(full.rows), full.row_count) == (3, 3)


@pytest.mark.parametrize("make", [_mysql, _snowflake], ids=["mysql", "snowflake"])
def test_a_warehouse_counts_a_bound_read_its_cap_cut(make, monkeypatch):
    over = make(monkeypatch, 5)
    over._connection_id, over.max_rows = "cut-read-t", 3
    bound = over.execute_with_params("q", "SELECT n FROM t WHERE n >= :lo", {"lo": 0})
    assert bound.error is None, bound.error
    assert (len(bound.rows), bound.row_count) == (3, 4)


# ── the Workspace connection, capped at 2,000 ─────────────────────────────────────────────────


def test_the_workspace_connection_reads_past_its_cap_when_the_read_is_bounded(tmp_path, monkeypatch):
    from aughor.connectors.file import local_upload as LU
    from aughor.control_plane import vending

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(LU, "MAX_ROWS", 5)
    conn = LU.LocalUploadConnection(connection_id="ws")
    try:
        conn._duckdb.execute("CREATE TEMP TABLE cut_t AS SELECT range AS n FROM range(12)")
        cut = conn.execute("q", "SELECT n FROM cut_t")
        assert (len(cut.rows), cut.row_count) == (5, 12)
        whole = conn.execute_bounded("__source_keys__", "SELECT n FROM cut_t", 100)
        assert (len(whole.rows), whole.row_count) == (12, 12)
        _, payload = conn.read_typed_rows("__source_keys__", "SELECT n FROM cut_t", 100)
        assert payload["truncated"] is False and len(payload["rows"]) == 12
    finally:
        getattr(conn, "close", lambda: None)()


# ── what the cross-source object query says when its home connection stops early ──────────────


def test_a_home_connection_that_stops_at_a_cap_of_its_own_is_named_where_it_stopped():
    from aughor.control_plane.contracts.execution import QueryResult
    from aughor.semantic import cross_source as XS

    class Home:
        def read_typed_rows(self, label, sql, max_rows):
            return (QueryResult(hypothesis_id=label, sql=sql, columns=["k"], rows=[["1"], ["2"]], row_count=3),
                    {"rows": [[1], [2]], "types": ["INTEGER"], "truncated": True})

    plan = XS.CrossSourcePlan(home_sql="SELECT k FROM t", key_columns={}, stage_sql="SELECT k FROM __home", reads=[])
    result, _ = XS.execute_plan(plan, home_connection_id="home-t", home_db=Home(), open_source=lambda _c: None,
                                label="objects", display_sql="SELECT k FROM t")
    assert result.error and "home-t stopped at 2 of the objects this query reads" in result.error
    assert "250,000" not in result.error
