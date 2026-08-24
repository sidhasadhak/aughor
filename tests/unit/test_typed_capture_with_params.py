"""Parameterising a query used to cost you its column types.

`/query/run` chose between the two: `if _params: execute_with_params` `elif _typed:
execute_typed`. So `format:"typed"` plus a `:name` returned the legacy stringified shape —
no `columns_typed`, no per-column types — and nothing said so.

🔑 **The capture site was never missing.** `_offer_typed_rows` sits AFTER the `if params:`
branch in `DuckDBConnection._run`, `PostgresConnection._run` and
`LocalUploadConnection._run`, so a bound query was already offering typed rows the whole
time — into a sink the route never set. The rows were computed and thrown away, which is
the same shape as `status` being read in four places and written in none.

Verified through the ROUTE, not just the connector: the connector half worked before this
change, so a connector-level test would have passed against the defect.
"""
from __future__ import annotations

import duckdb
import pytest
from fastapi.testclient import TestClient

from aughor.api import app
from aughor.db import registry

client = TestClient(app)

SQL_PLAIN = "SELECT id, name, score FROM t WHERE name = 'n3' ORDER BY id"
SQL_BOUND = "SELECT id, name, score FROM t WHERE name = :who ORDER BY id"


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "typed.duckdb"
    c = duckdb.connect(str(db))
    c.execute("CREATE TABLE t AS SELECT i AS id, 'n' || i AS name, i * 1.5 AS score "
              "FROM range(10) AS r(i)")
    c.close()
    cid = registry.add_connection("typed-params", "duckdb", str(db))
    yield cid
    registry.delete_connection(cid)


def _run(cid: str, sql: str, **extra) -> dict:
    r = client.post("/query/run", json={"conn_id": cid, "sql": sql, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_parameterised_query_still_comes_back_typed(conn):
    """The defect, at the surface that had it."""
    out = _run(conn, SQL_BOUND, params={"who": "n3"}, format="typed",
               source="query_workbench", limit=10)

    assert "columns_typed" in out, "a bound query fell back to the untyped response"
    assert [c["name"] for c in out["columns_typed"]] == ["id", "name", "score"]
    assert out["row_count"] == 1


def test_the_types_are_the_same_ones_the_unbound_query_reports(conn):
    """Not merely present — IDENTICAL. A typed response assembled from inferred values
    rather than from cursor types would pass the test above and still be a regression:
    `_typed_response` falls back to inferring a column's type from its values when the
    cursor gave it none, and one row of data infers badly."""
    bound = _run(conn, SQL_BOUND, params={"who": "n3"}, format="typed",
                 source="query_workbench", limit=10)
    plain = _run(conn, SQL_PLAIN, format="typed", source="query_workbench", limit=10)

    assert bound["columns_typed"] == plain["columns_typed"]
    assert bound["rows"] == plain["rows"], "same query, same rows, whoever supplied 'n3'"


def test_the_value_is_still_bound_and_not_interpolated(conn):
    """The typed path must not have become a second, laxer executor. A value that would
    change the statement comes back as data: zero rows, no error, table intact."""
    out = _run(conn, SQL_BOUND, params={"who": "n3'; DROP TABLE t; --"}, format="typed",
               source="query_workbench", limit=10)

    assert out.get("error") in (None, ""), out.get("error")
    assert out["row_count"] == 0
    assert _run(conn, "SELECT count(*) AS n FROM t", format="typed",
                source="query_workbench", limit=10)["rows"][0][0] == 10


def test_an_unparameterised_typed_query_is_unchanged(conn):
    """The other half. A route change that routed everything through the new method would
    pass every test above and still be a behaviour change for the common case."""
    out = _run(conn, SQL_PLAIN, format="typed", source="query_workbench", limit=10)

    assert [c["name"] for c in out["columns_typed"]] == ["id", "name", "score"]
    assert out["row_count"] == 1


# ── the capture contract itself ──────────────────────────────────────────────────

def test_an_internal_label_still_skips_the_capture():
    """The safety rule the wrapper exists to hold in ONE place: internal queries skip the
    PII/audit post-pass, so a typed capture there would be an unredacted side channel.
    Both entry points have to honour it, and now both read it from the same function."""
    from aughor.db.connection import DatabaseConnection

    class _Probe(DatabaseConnection):
        dialect = "duckdb"
        def execute(self, hypothesis_id, sql):
            from aughor.db.connection import offer_typed_rows
            offer_typed_rows([[1]], truncated=False, types=["BIGINT"])
            return _ok(sql)
        def execute_with_params(self, hypothesis_id, sql, params):
            return self.execute(hypothesis_id, sql)
        def get_schema(self): ...
        def test(self): ...
        def close(self): ...

    probe = _Probe()
    # `__catalog__`-style dunder labels are what `_is_internal_query` recognises; a
    # plausible-looking name like "internal_profile" is NOT internal, and asserting against
    # one would have made this pass for the wrong reason.
    for label, expect_payload in (("query_workbench", True), ("__catalog__", False)):
        _r, payload = probe.execute_with_params_typed(label, "SELECT :v", {"v": 1})
        assert (payload is not None) is expect_payload, label
        _r, payload = probe.execute_typed(label, "SELECT 1")
        assert (payload is not None) is expect_payload, f"{label} (unbound)"


def test_an_errored_run_carries_no_typed_payload():
    """Fail closed. A payload alongside an error would be rows the legacy result dropped."""
    from aughor.db.connection import DatabaseConnection, QueryResult

    class _Broken(DatabaseConnection):
        dialect = "duckdb"
        def execute(self, hypothesis_id, sql):
            from aughor.db.connection import offer_typed_rows
            offer_typed_rows([[1]], truncated=False, types=["BIGINT"])
            return QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[],
                               row_count=0, error="boom")
        def execute_with_params(self, hypothesis_id, sql, params):
            return self.execute(hypothesis_id, sql)
        def get_schema(self): ...
        def test(self): ...
        def close(self): ...

    _result, payload = _Broken().execute_with_params_typed("query_workbench", "SELECT :v",
                                                           {"v": 1})
    assert payload is None


def _ok(sql):
    from aughor.db.connection import QueryResult
    return QueryResult(hypothesis_id="query_workbench", sql=sql, columns=["a"],
                       rows=[["1"]], row_count=1)


def test_sqlite_captures_on_its_bound_path_too(tmp_path):
    """SQLite's capture lives in `execute`, not in the shared bind envelope, so its bound
    path had to be given one explicitly — otherwise adding a parameter would silently drop
    the types on exactly the connector where the fix above cannot reach."""
    import sqlite3

    from aughor.connectors.file.sqlite import SQLiteConnection

    path = tmp_path / "s.sqlite"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    c.executemany("INSERT INTO t VALUES (?, ?)", [(1, "a"), (2, "b")])
    c.commit()
    c.close()

    conn = SQLiteConnection(dsn=str(path), connection_id="c1")
    result, payload = conn.execute_with_params_typed(
        "query_workbench", "SELECT id FROM t WHERE name = :n", {"n": "a"})

    assert result.error is None, result.error
    assert payload is not None, "the bound path offered nothing to capture"
    assert payload["rows"] == [[1]], "raw values, not the stringified ones"
