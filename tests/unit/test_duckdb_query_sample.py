"""DuckDB's query-level sample (`USING SAMPLE …`), kept where DuckDB's grammar takes it.

Every statement a `DuckDBConnection` runs or dry-runs goes through sqlglot's DuckDB reader and writer first
(`_normalize_to_duckdb`), and sqlglot writes the query-level sample at the very end, after ORDER BY, LIMIT and
OFFSET. DuckDB takes it straight after QUALIFY and refuses it anywhere later. Measured 2026-09-17 on DuckDB 1.5.2
with sqlglot 30.8.0, and unchanged in 30.18.0, the newest release: `SELECT * FROM flights USING SAMPLE 10% LIMIT 5`
ran as `… LIMIT 5 USING SAMPLE SYSTEM (10 PERCENT)` and failed with `Parser Error: syntax error at or near "USING"`.
A table-level `TABLESAMPLE` belongs to its table and was never affected.

Whether two statements are the same is DuckDB's call, not sqlglot's. sqlglot reads both orders into one tree, so only
DuckDB's own parser (`json_serialize_sql`) can tell the statement that ran from the one written.
"""
from __future__ import annotations

import json

import duckdb
import pytest
import sqlglot

import aughor.db.connection as connection
from aughor.db.connection import DuckDBConnection, rewrite_julianday

#: Valid DuckDB with a clause written after the query-level sample. Every one failed through the connection.
_AFTER_THE_SAMPLE = {
    "limit": "SELECT * FROM flights USING SAMPLE 10% LIMIT 5",
    "group by, then order by": ("SELECT status, COUNT(*) AS n FROM flights WHERE cancelled = 0 GROUP BY 1 "
                                "USING SAMPLE 10% ORDER BY 2 DESC"),
    "the duckdb pack's count, limited": "SELECT count(*) FROM flights USING SAMPLE 10% LIMIT 1",
    "order by, limit, offset": "SELECT * FROM flights USING SAMPLE 100 ROWS ORDER BY id LIMIT 5 OFFSET 2",
    "offset": "SELECT id FROM flights USING SAMPLE 10% OFFSET 2",
    "a seeded method": "SELECT * FROM flights USING SAMPLE reservoir(50 ROWS) REPEATABLE (42) LIMIT 5",
    "method and seed in brackets": "SELECT * FROM flights USING SAMPLE 10 PERCENT (bernoulli, 7) LIMIT 3",
    "having": "SELECT status, count(*) FROM flights GROUP BY 1 HAVING count(*) > 0 USING SAMPLE 10% ORDER BY 1",
    "qualify": "SELECT * FROM flights QUALIFY row_number() OVER (ORDER BY id) < 3 USING SAMPLE 10% LIMIT 2",
    "distinct on": "SELECT DISTINCT ON (status) status, id FROM flights USING SAMPLE 50% ORDER BY status, id",
    "join using": "SELECT f.status, c.name FROM flights f JOIN carriers c USING (status) USING SAMPLE 10% LIMIT 3",
    "from first": "FROM flights USING SAMPLE 10% LIMIT 5",
    "subquery": "SELECT * FROM (SELECT * FROM flights USING SAMPLE 10% LIMIT 5) q",
    "cte": "WITH s AS (SELECT * FROM flights USING SAMPLE 10% LIMIT 50) SELECT count(*) FROM s",
    "the table sampled too": "SELECT * FROM flights AS f TABLESAMPLE 10% USING SAMPLE 50% LIMIT 1",
}


@pytest.fixture()
def flights(tmp_path):
    path = tmp_path / "flights.duckdb"
    seed = duckdb.connect(str(path))
    seed.execute("CREATE TABLE flights AS SELECT i AS id, 'carrier_' || (i % 7) AS status, "
                 "(i % 11 = 0)::INT AS cancelled FROM range(1000) t(i)")
    seed.execute("CREATE TABLE carriers AS SELECT 'carrier_' || i AS status, 'c' || i AS name FROM range(7) t(i)")
    seed.close()
    conn = DuckDBConnection(path, connection_id="query-sample")
    yield conn
    conn.close()


def _duckdb_tree(sql: str) -> dict:
    """DuckDB's own parse of ``sql``, without the character offsets that differ between two spellings."""
    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "query_location"}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    tree = json.loads(duckdb.connect().execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    assert not tree["error"], f"DuckDB does not parse {sql!r}: {tree}"
    return strip(tree)


def test_the_parse_sees_the_sample():
    """The comparison below can fail: DuckDB's tree changes with the sample's size, method, level and presence."""
    written = _duckdb_tree("SELECT * FROM flights USING SAMPLE 10% LIMIT 5")
    assert written == _duckdb_tree("SELECT * FROM flights USING SAMPLE SYSTEM (10 PERCENT) LIMIT 5")
    for other in ("SELECT * FROM flights USING SAMPLE 20% LIMIT 5",
                  "SELECT * FROM flights USING SAMPLE BERNOULLI (10 PERCENT) LIMIT 5",
                  "SELECT * FROM flights TABLESAMPLE 10% LIMIT 5",
                  "SELECT * FROM flights LIMIT 5"):
        assert written != _duckdb_tree(other), other


# ── the connection runs what DuckDB takes, and runs the same statement ────────────────

@pytest.mark.parametrize("label", sorted(_AFTER_THE_SAMPLE))
def test_sqlglots_own_writer_is_still_the_one_duckdb_refuses(label):
    """The tripwire under the override: what sqlglot writes by itself is what DuckDB will not parse. If a later
    sqlglot places the clause correctly, this fails — and then `_DuckDBWriter` has nothing left to do and should go
    (left in place, it would write the sample twice)."""
    stock = sqlglot.transpile(_AFTER_THE_SAMPLE[label], read="duckdb", write="duckdb",
                              error_level=sqlglot.ErrorLevel.IGNORE)[0]
    refused = json.loads(duckdb.connect().execute("SELECT json_serialize_sql(?)", [stock]).fetchone()[0])
    assert refused["error"] and refused["error_type"] == "parser", stock


@pytest.mark.parametrize("label", sorted(_AFTER_THE_SAMPLE))
def test_valid_duckdb_runs_and_dry_runs_through_the_connection(flights, label):
    sql = _AFTER_THE_SAMPLE[label]
    flights.raw_execute(sql)                      # the premise: DuckDB takes the statement exactly as written
    result = flights.execute("h", sql)
    assert not result.error, f"{result.error}\nran: {result.sql}"
    assert flights.dry_run(sql) == (True, "")


@pytest.mark.parametrize("label", sorted(_AFTER_THE_SAMPLE))
def test_the_statement_that_ran_is_the_statement_written(flights, label):
    sql = _AFTER_THE_SAMPLE[label]
    result = flights.execute("h", sql)
    assert not result.error, f"{result.error}\nran: {result.sql}"
    assert _duckdb_tree(result.sql) == _duckdb_tree(sql)


def test_the_rows_are_the_rows_the_written_statement_gives(flights):
    sql = ("SELECT status, COUNT(*) AS n FROM flights WHERE cancelled = 0 GROUP BY 1 "
           "USING SAMPLE 100 PERCENT (bernoulli) ORDER BY 2 DESC, 1 LIMIT 3")
    _columns, native, _types = flights.raw_execute(sql)
    result = flights.execute("h", sql)
    assert not result.error, result.error
    assert result.rows == [[str(v) for v in row] for row in native] and len(result.rows) == 3


def test_a_bound_statement_keeps_its_sample_in_place(flights):
    result = flights.execute_with_params(
        "h", "SELECT id FROM flights WHERE status = :s USING SAMPLE 100 PERCENT (bernoulli) ORDER BY id LIMIT 2",
        {"s": "carrier_3"})
    assert not result.error, f"{result.error}\nran: {result.sql}"
    assert result.rows == [["3"], ["10"]]


def test_a_sample_written_before_where_is_moved_to_where_duckdb_takes_it(flights):
    """DuckDB refuses a sample written ahead of WHERE. The round trip moves it to its place, which the query-level
    sample means anyway (DuckDB samples straight after FROM wherever the clause is written). So a sampled statement
    cannot simply be left as written."""
    written = "SELECT id FROM flights USING SAMPLE 100 PERCENT (bernoulli) WHERE id < 5 ORDER BY id LIMIT 3"
    with pytest.raises(duckdb.ParserException):
        flights.raw_execute(written)
    result = flights.execute("h", written)
    assert not result.error, f"{result.error}\nran: {result.sql}"
    assert result.rows == [["0"], ["1"], ["2"]]
    assert _duckdb_tree(result.sql) == _duckdb_tree(
        "SELECT id FROM flights WHERE id < 5 USING SAMPLE 100 PERCENT (bernoulli) ORDER BY id LIMIT 3")


#: No query-level sample: nothing about how these are written may change.
_NO_QUERY_SAMPLE = [
    "SELECT status, COUNT(*) FROM flights TABLESAMPLE 10% WHERE cancelled = 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
    "SELECT f.id, c.name FROM flights AS f LEFT JOIN carriers c ON f.status = c.status WHERE f.id > 3 "
    "ORDER BY 1 LIMIT 10 OFFSET 2",
    "WITH x AS (SELECT status, count(*) n FROM flights GROUP BY ALL) SELECT * FROM x "
    "QUALIFY row_number() OVER (PARTITION BY status ORDER BY n DESC) = 1",
    "SELECT id FROM flights WINDOW w AS (ORDER BY id) ORDER BY id LIMIT 1",
    "SELECT status FROM flights UNION ALL SELECT status FROM carriers ORDER BY 1 LIMIT 3",
    "SELECT * EXCLUDE (cancelled) FROM flights WHERE status ILIKE 'carrier_%' AND id = :id LIMIT 3",
    "SELECT date_trunc('month', DATE '2024-03-05'), strftime(DATE '2024-03-05', '%Y'), ifnull(NULL, 1), nvl(NULL, 2)",
    "SELECT list_transform([1, 2], x -> x + 1), id::VARCHAR FROM flights LIMIT 1",
]


@pytest.mark.parametrize("sql", _NO_QUERY_SAMPLE)
def test_a_statement_without_a_query_sample_is_written_as_sqlglot_writes_it(sql):
    stock = sqlglot.transpile(sql, read="duckdb", write="duckdb", error_level=sqlglot.ErrorLevel.IGNORE)[0]
    assert DuckDBConnection._normalize_to_duckdb(sql) == stock


# ── the rewrites around the round trip: the row policy before it, the heal after it ────

def test_the_row_policy_is_handed_the_statement_as_written_and_its_rewrite_runs(flights, monkeypatch):
    """The row policy runs BEFORE the round trip, so it still sees the statement as written. Its own rewrite is written
    by sqlglot's stock DuckDB writer, which moves the sample after LIMIT again; the round trip that follows puts it
    back."""
    import aughor.licensing as licensing
    import aughor.rbac.resolver as resolver
    import aughor.rbac.row_policy as row_policy
    import aughor.security.authz as authz
    from aughor.org.context import reset_org_id, reset_user_id, set_org_id, set_user_id

    monkeypatch.setattr(authz, "require_identity_enabled", lambda: True)
    monkeypatch.setattr(licensing, "has_capability", lambda *a, **k: True)
    monkeypatch.setattr(resolver, "resolve_roles", lambda principal: ["viewer"])
    monkeypatch.setattr(row_policy, "ROW_POLICIES", {"viewer": {"flights": "cancelled = 1"}})
    handed: list[str] = []
    policy = connection.enforce_row_policy

    def spy(conn, hypothesis_id, sql):
        handed.append(sql)
        return policy(conn, hypothesis_id, sql)

    monkeypatch.setattr(connection, "enforce_row_policy", spy)
    written = "SELECT id FROM flights USING SAMPLE 100 PERCENT (bernoulli) ORDER BY id LIMIT 3"
    org, user = set_org_id("o1"), set_user_id("u1")
    try:
        result = flights.execute("h", written + ";")
    finally:
        reset_user_id(user)
        reset_org_id(org)
    assert handed == [written]
    assert not result.error, f"{result.error}\nran: {result.sql}"
    assert result.rows == [["0"], ["11"], ["22"]]          # the policy's rows, every one of them sampled


_JULIANDAY_SAMPLED = ("SELECT ROUND(JULIANDAY(TIMESTAMP '2024-01-01 18:00:00') - JULIANDAY(TIMESTAMP '2024-01-01 06:00:00'),"
                      " 2) AS d FROM range(10) t(i) USING SAMPLE 100 PERCENT (bernoulli) ORDER BY d LIMIT 1")


def test_the_julianday_rewrite_keeps_the_sample_in_place():
    healed = rewrite_julianday(_JULIANDAY_SAMPLED)
    assert healed and "julianday" not in healed.lower()
    assert duckdb.connect().execute(healed).fetchall() == [(0.5,)]


def test_the_heal_is_handed_the_statement_that_ran_and_heals_it(flights, monkeypatch):
    handed: list[tuple[str, str]] = []
    heal = connection.heal_duckdb_refusal

    def spy(result, sql, attempt):
        handed.append((result.sql, sql))
        return heal(result, sql, attempt)

    monkeypatch.setattr(connection, "heal_duckdb_refusal", spy)
    result = flights.execute("h", _JULIANDAY_SAMPLED)
    assert len(handed) == 1 and handed[0][0] == handed[0][1]  # the heal gets the statement DuckDB refused
    assert "julianday" in handed[0][1].lower()
    assert not result.error, f"{result.error}\nran: {result.sql}"
    assert result.rows == [["0.5"]] and "julian(" in result.sql.lower()


def test_the_workspace_connection_heals_a_sampled_julianday_too(tmp_path, monkeypatch):
    """`LocalUploadConnection` never makes the round trip, so its statements run as written. The heal's rewrite is
    the one sqlglot writes, though."""
    from aughor.connectors.file.local_upload import LocalUploadConnection
    from aughor.control_plane import vending

    monkeypatch.setattr(vending, "STORAGE_ROOT", tmp_path / "uploads")
    conn = LocalUploadConnection(connection_id="ws")
    try:
        sampled = conn.execute("h", "SELECT i FROM range(100) t(i) USING SAMPLE 100 PERCENT (bernoulli) "
                                    "ORDER BY i LIMIT 2")
        assert not sampled.error, sampled.error
        assert sampled.rows == [["0"], ["1"]]
        healed = conn.execute("h", _JULIANDAY_SAMPLED)
        assert not healed.error, f"{healed.error}\nran: {healed.sql}"
        assert healed.rows == [["0.5"]] and "julian(" in healed.sql.lower()
    finally:
        getattr(conn, "close", lambda: None)()
