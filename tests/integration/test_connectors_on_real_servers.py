"""What a connector has to do on a real server before its tile loses the Preview badge.

Connect, read the schema, answer the SQL the platform writes and the SQL the model writes, cut a long read and say so,
profile a table, and have a write refused: by the door, and by the server itself where the declaration says it does.

It writes a table called `proof_orders` to each server, so it runs only when asked, against throwaway containers:

    docker run -d --name aughor-proof-cockroach -p 26257:26257 cockroachdb/cockroach:latest-v24.3 start-single-node --insecure
    docker run -d --name aughor-proof-timescale -p 5433:5432 -e POSTGRES_PASSWORD=proof -e POSTGRES_DB=proof timescale/timescaledb:latest-pg16
    docker run -d --name aughor-proof-mariadb -p 3307:3306 -e MARIADB_ROOT_PASSWORD=proof -e MARIADB_DATABASE=proof mariadb:11
    docker run -d --name aughor-proof-mysql -p 3308:3306 -e MYSQL_ROOT_PASSWORD=proof -e MYSQL_DATABASE=proof mysql:8.4
    docker run -d --name aughor-proof-tidb -p 4000:4000 pingcap/tidb:v8.5.1
    docker run -d --name aughor-proof-clickhouse -p 8123:8123 -e CLICKHOUSE_USER=proof -e CLICKHOUSE_PASSWORD=proof -e CLICKHOUSE_DB=proof clickhouse/clickhouse-server:24.8
    docker run -d --name aughor-proof-mssql --platform linux/amd64 -p 1433:1433 -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD=Proof_12345 mcr.microsoft.com/mssql/server:2022-latest
    docker run -d --name aughor-proof-oracle -p 1521:1521 -e ORACLE_PASSWORD=proof -e APP_USER=proof -e APP_USER_PASSWORD=proof gvenzl/oracle-free:23-slim

    AUGHOR_PROOF_SERVERS=1 pytest tests/integration/test_connectors_on_real_servers.py
"""
from __future__ import annotations

import os
import re
import socket
import time
from dataclasses import dataclass, field

import pytest

from aughor.db.connection import open_connection

pytestmark = pytest.mark.skipif(not os.environ.get("AUGHOR_PROOF_SERVERS"), reason="writes to local servers: set AUGHOR_PROOF_SERVERS=1")

ROWS = [
    (1, "2026-01-10 08:00:00", "10.50", "north"),
    (2, "2026-01-20 09:00:00", "20.00", "south"),
    (3, "2026-02-05 10:00:00", "30.00", "north"),
    (4, "2026-02-06 11:00:00", "40.00", "south"),
    (5, "2026-03-01 12:00:00", "50.00", "north"),
    (6, "2026-03-02 13:00:00", None, "south"),
]


def _value(v) -> str:
    return "NULL" if v is None else f"'{v}'"


def _inserts(timestamp: str = "'{}'") -> list[str]:
    return [f"INSERT INTO proof_orders (id, created_at, amount, region) VALUES ({i}, {timestamp.format(at)}, {a if a else 'NULL'}, '{r}')"
            for i, at, a, r in ROWS]


def _postgres_seed(s: "Server") -> None:
    import psycopg2
    conn = psycopg2.connect(s.dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS proof_orders")
    cur.execute("CREATE TABLE proof_orders (id INT PRIMARY KEY, created_at TIMESTAMP, amount DECIMAL(10,2), region VARCHAR(20))")
    for statement in _inserts():
        cur.execute(statement)
    conn.close()


def _mysql_seed(s: "Server") -> None:
    import pymysql
    conn = pymysql.connect(host="localhost", port=int(s.meta["port"]), user=s.meta["user"], password=s.meta["password"], autocommit=True)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {s.meta['database']}")
    cur.execute(f"USE {s.meta['database']}")
    cur.execute("DROP TABLE IF EXISTS proof_orders")
    cur.execute("CREATE TABLE proof_orders (id INT PRIMARY KEY, created_at DATETIME, amount DECIMAL(10,2), region VARCHAR(20))")
    for statement in _inserts():
        cur.execute(statement)
    conn.close()


def _clickhouse_seed(s: "Server") -> None:
    import clickhouse_connect
    client = clickhouse_connect.get_client(host="localhost", port=int(s.meta["port"]), username=s.meta["user"], password=s.meta["password"], database=s.meta["database"])
    client.command("DROP TABLE IF EXISTS proof_orders")
    client.command("CREATE TABLE proof_orders (id Int32, created_at DateTime, amount Nullable(Decimal(10,2)), region String) ENGINE = MergeTree ORDER BY id")
    for statement in _inserts():
        client.command(statement)
    client.close()


def _mssql_seed(s: "Server") -> None:
    import pymssql
    conn = pymssql.connect(server="localhost", port=int(s.meta["port"]), user=s.meta["user"], password=s.meta["password"], autocommit=True)
    cur = conn.cursor()
    cur.execute("IF DB_ID('proof') IS NULL CREATE DATABASE proof")
    cur.execute("USE proof")
    cur.execute("IF OBJECT_ID('dbo.proof_orders') IS NOT NULL DROP TABLE dbo.proof_orders")
    cur.execute("CREATE TABLE dbo.proof_orders (id INT PRIMARY KEY, created_at DATETIME2, amount DECIMAL(10,2), region NVARCHAR(20))")
    for statement in _inserts():
        cur.execute(statement)
    conn.close()


def _oracle_seed(s: "Server") -> None:
    import oracledb
    conn = oracledb.connect(user=s.meta["user"], password=s.meta["password"], host="localhost", port=int(s.meta["port"]), service_name=s.meta["service_name"])
    cur = conn.cursor()
    cur.execute("BEGIN EXECUTE IMMEDIATE 'DROP TABLE proof_orders'; EXCEPTION WHEN OTHERS THEN NULL; END;")
    cur.execute("CREATE TABLE proof_orders (id NUMBER(10) PRIMARY KEY, created_at TIMESTAMP, amount NUMBER(10,2), region VARCHAR2(20))")
    for statement in _inserts("TIMESTAMP '{}'"):
        cur.execute(statement)
    conn.commit()
    conn.close()
    time.sleep(5)   # a READ ONLY transaction begun right after DDL refuses to read the table (ORA-01466)


@dataclass
class Server:
    type: str
    port: int
    seed: object
    native: str
    dsn: str = ""
    meta: dict = field(default_factory=dict)
    schema: str | None = None
    explored: str = "proof"


_PORTABLE_NATIVE = "SELECT region, SUM(amount) AS total FROM proof_orders GROUP BY region ORDER BY total DESC LIMIT 1"

SERVERS = {s.type: s for s in (
    Server("cockroachdb", 26257, _postgres_seed, _PORTABLE_NATIVE, dsn="postgresql://root@localhost:26257/defaultdb?sslmode=disable", explored="public"),
    Server("timescaledb", 5433, _postgres_seed, _PORTABLE_NATIVE, dsn="postgresql://postgres:proof@localhost:5433/proof", explored="public"),
    Server("mariadb", 3307, _mysql_seed, _PORTABLE_NATIVE, meta={"host": "localhost", "port": "3307", "user": "root", "password": "proof", "database": "proof"}),
    Server("mysql", 3308, _mysql_seed, _PORTABLE_NATIVE, meta={"host": "localhost", "port": "3308", "user": "root", "password": "proof", "database": "proof"}),
    Server("tidb", 4000, _mysql_seed, _PORTABLE_NATIVE, meta={"host": "localhost", "port": "4000", "user": "root", "password": "", "database": "proof"}),
    Server("clickhouse", 8123, _clickhouse_seed, _PORTABLE_NATIVE, meta={"host": "localhost", "port": "8123", "user": "proof", "password": "proof", "database": "proof"}),
    Server("mssql", 1433, _mssql_seed, "SELECT TOP 1 region, SUM(amount) AS total FROM proof_orders GROUP BY region ORDER BY total DESC",
           meta={"host": "localhost", "port": "1433", "user": "sa", "password": "Proof_12345", "database": "proof", "schema_name": "dbo"}, explored="dbo"),
    Server("oracle", 1521, _oracle_seed, "SELECT region, SUM(amount) AS total FROM proof_orders GROUP BY region ORDER BY total DESC FETCH FIRST 1 ROWS ONLY",
           meta={"host": "localhost", "port": "1521", "user": "proof", "password": "proof", "service_name": "FREEPDB1"}, explored="PROOF"),
)}


def _running(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("localhost", port)) == 0


@pytest.fixture(scope="module", params=sorted(SERVERS))
def server(request):
    s = SERVERS[request.param]
    if not _running(s.port):
        pytest.skip(f"nothing on :{s.port}")
    s.seed(s)
    conn = open_connection(s.type, s.dsn, schema_name=s.schema, connection_id=f"proof-{s.type}", meta=dict(s.meta))
    yield s, conn
    conn.close()


def _cells(row) -> list[str]:
    return [str(v).lower() for v in row]


def _number(v) -> float:
    return float(str(v))


def test_it_says_who_it_is(server):
    _, conn = server
    ok, said = conn.test()
    assert ok, said


def test_it_reads_the_schema(server):
    _, conn = server
    schema = conn.get_schema().lower()
    assert re.search(r"table: proof_orders\b", schema), schema
    for column in ("id ", "created_at ", "amount ", "region "):
        assert column in schema, schema


@pytest.mark.parametrize("sql,check", [
    ("SELECT region, SUM(amount) AS total, COUNT(*) AS n FROM proof_orders GROUP BY region ORDER BY total DESC LIMIT 1",
     lambda rows: _cells(rows[0])[0] == "north" and _number(rows[0][1]) == 90.5 and _number(rows[0][2]) == 3),
    ("SELECT DATE_TRUNC('month', created_at) AS month, SUM(amount) AS total FROM proof_orders GROUP BY 1 ORDER BY 1 LIMIT 2",
     lambda rows: str(rows[0][0]).startswith("2026-01") and _number(rows[0][1]) == 30.5 and str(rows[1][0]).startswith("2026-02") and _number(rows[1][1]) == 70),
    ("SELECT DATE_TRUNC('week', created_at) AS w, DATE_TRUNC('day', created_at) AS d, DATE_TRUNC('quarter', created_at) AS q, DATE_TRUNC('year', created_at) AS y FROM proof_orders WHERE id = 4",
     lambda rows: [str(v)[:10] for v in rows[0]] == ["2026-02-02", "2026-02-06", "2026-01-01", "2026-01-01"]),
    ("SELECT COUNT(*) FILTER (WHERE region = 'north') AS n, SUM(amount) FILTER (WHERE region = 'south') AS s FROM proof_orders",
     lambda rows: _number(rows[0][0]) == 3 and _number(rows[0][1]) == 60),
    ("SELECT id, ROW_NUMBER() OVER (PARTITION BY region ORDER BY created_at) AS rn FROM proof_orders QUALIFY rn <= 2 ORDER BY id DESC LIMIT 1",
     lambda rows: _number(rows[0][0]) == 4),
    ("SELECT COUNT(*) AS n, COUNT(DISTINCT region) AS regions, MIN(created_at) AS first_at, MAX(created_at) AS last_at FROM proof_orders",
     lambda rows: _number(rows[0][0]) == 6 and _number(rows[0][1]) == 2 and str(rows[0][2]).startswith("2026-01-10") and str(rows[0][3]).startswith("2026-03-02")),
    ("SELECT id, CAST(amount AS DOUBLE) AS d, CAST(created_at AS DATE) AS day FROM proof_orders WHERE amount IS NOT NULL AND created_at >= DATE '2026-02-01' ORDER BY id LIMIT 2",
     lambda rows: _number(rows[0][0]) == 3 and _number(rows[0][1]) == 30 and str(rows[0][2]).startswith("2026-02-05")),
    ("SELECT COALESCE(SUM(CASE WHEN region = 'north' THEN amount END), 0) / NULLIF(COUNT(*), 0) AS per FROM proof_orders",
     lambda rows: abs(_number(rows[0][0]) - 90.5 / 6) < 0.01),
    ("SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY region ORDER BY created_at DESC) AS rn FROM proof_orders) ranked WHERE rn = 1 ORDER BY id",
     lambda rows: [_number(r[0]) for r in rows] == [5, 6]),
    ("SELECT COUNT(*) AS n FROM proof_orders WHERE region ILIKE 'NOR%'",
     lambda rows: _number(rows[0][0]) == 3),
    ("SELECT id, ROW_NUMBER() OVER (PARTITION BY region ORDER BY created_at) AS rn FROM proof_orders QUALIFY rn = 1 ORDER BY id",
     lambda rows: [_number(r[0]) for r in rows] == [1, 2]),
], ids=["group-order-limit", "month-bucket-ordinal", "other-grains", "filter", "qualify-with-its-cap", "aggregates", "cast-and-date-literal", "case-coalesce-nullif", "window-in-subquery", "ilike", "qualify"])
def test_it_answers_the_sql_the_platform_writes(server, sql, check):
    _, conn = server
    result = conn.execute("proof", sql, sql_dialect="duckdb", internal=True)
    assert not result.error, f"{result.sql}\n{result.error}"
    assert check(result.rows), f"{result.sql}\n{result.rows}"


def test_it_answers_the_sql_the_model_writes(server):
    s, conn = server
    result = conn.execute("proof", s.native)
    assert not result.error, f"{result.sql}\n{result.error}"
    assert _cells(result.rows[0])[0] == "north" and _number(result.rows[0][1]) == 90.5


def test_a_cut_read_says_it_was_cut(server):
    _, conn = server
    result = conn.execute_bounded("proof", "SELECT id FROM proof_orders ORDER BY id", 2, sql_dialect="duckdb")
    assert not result.error, f"{result.sql}\n{result.error}"
    assert len(result.rows) == 2
    assert result.row_count > 2


def test_a_bound_value_reaches_the_engine_as_a_value(server):
    s, conn = server
    if hasattr(conn, "param_style") and not conn.param_style:   # Postgres's family binds through its own `_run`
        pytest.skip(f"{s.type} refuses a bound statement visibly")
    result = conn.execute_with_params("proof", "SELECT COUNT(*) AS n FROM proof_orders WHERE region = :region", {"region": "north' OR '1'='1"})
    assert not result.error, f"{result.sql}\n{result.error}"
    assert _number(result.rows[0][0]) == 0
    result = conn.execute_with_params("proof", "SELECT COUNT(*) AS n FROM proof_orders WHERE region = :region", {"region": "north"})
    assert _number(result.rows[0][0]) == 3, result


def _count(conn) -> float:
    return _number(conn.execute("proof", "SELECT COUNT(*) FROM proof_orders", sql_dialect="duckdb", internal=True).rows[0][0])


def test_the_door_refuses_a_write(server):
    _, conn = server
    before = _count(conn)
    result = conn.execute("proof", "INSERT INTO proof_orders (id, region) VALUES (99, 'door')")
    assert result.error, result
    assert re.search(r"(?i)read.only|select|not allowed|blocked|refus", result.error), result.error
    assert _count(conn) == before


def test_the_server_refuses_a_write_where_the_declaration_says_so(server):
    """Past the door, on the session itself: `engine_read_only` is a claim about the server, not about Aughor's checks."""
    s, conn = server
    if conn.engine_read_only is not True:
        pytest.skip(f"{s.type} declares that the door is the boundary")
    before = _count(conn)
    before_statement = getattr(conn, "_before_statement", None)
    if before_statement:
        before_statement()
    cur = conn._conn.cursor()
    with pytest.raises(Exception) as refused:
        cur.execute("INSERT INTO proof_orders (id, region) VALUES (98, 'session')")
        fetch = getattr(cur, "fetchall", None)
        if fetch and cur.description:
            fetch()
    print(f"{s.type} refused: {str(refused.value)[:160]}")
    assert re.search(r"(?i)read.only|readonly|1792|ORA-01456|cannot execute", str(refused.value)), refused.value
    assert _count(conn) == before


def test_the_connection_says_which_engine_it_is(server):
    from aughor.db.metadata import read_declared_metadata

    s, conn = server
    read = read_declared_metadata(conn)
    assert read.engine == s.type, read.as_dict()
    assert "read failed" not in " ".join(read.detail.values()), read.as_dict()


def test_a_profile_reads_the_table(server):
    """What adding a connection builds first: without columns here the catalog and the ontology come up empty."""
    from aughor.tools.profiler import profile_connection

    _, conn = server
    table = re.search(r"(?i)TABLE: (proof_orders)", conn.get_schema()).group(1)
    failed = []
    run = conn.execute
    def watched(hypothesis_id, sql, **kw):
        result = run(hypothesis_id, sql, **kw)
        if result.error and "SAMPLE" not in sql:    # `_row_sample` tries DuckDB's spelling and falls back on purpose
            failed.append(f"{result.sql}\n   -> {result.error[:150]}")
        return result
    conn.execute = watched
    try:
        tables, columns = profile_connection(conn, [table], {})
    finally:
        del conn.execute
    print("\n".join(failed))
    assert not failed, "\n".join(failed)
    assert table in tables, tables
    profile = tables[table]
    assert profile.row_count == 6, profile
    amount = next(v for k, v in columns.items() if k.lower().endswith(".amount"))
    assert amount.null_rate > 0, amount
    assert any(k.lower().endswith(".created_at") for k in columns), columns


def test_the_screens_read_it(server, client):
    """The doors the Catalog and the connection's tabs call, on a connection in the registry."""
    from aughor.db.registry import add_connection, delete_connection

    s, conn = server
    conn_id = add_connection(name=f"proof {s.type}", conn_type=s.type, dsn=s.dsn, meta=dict(s.meta))
    table = re.search(r"(?i)TABLE: (proof_orders)", conn.get_schema()).group(1)
    try:
        tested = client.post(f"/connections/{conn_id}/test")
        assert tested.status_code == 200 and tested.json().get("ok") is not False, tested.text

        columns = client.get(f"/connections/{conn_id}/tables/{table}/columns").json()["columns"]
        assert {c["name"].lower() for c in columns} == {"id", "created_at", "amount", "region"}, columns
        assert all(c["type"] for c in columns), columns

        sample = client.get(f"/connections/{conn_id}/tables/{table}/sample?limit=2").json()
        assert not sample["error"], sample
        assert sample["row_count"] == 2, sample

        tree = client.get("/catalog/tree").json()
        assert table in str(tree), tree
        assert "_timescaledb_" not in str(tree), tree

        from aughor.routers._shared import schemas_of_connection
        assert schemas_of_connection(conn_id) == [s.explored], "the Explorer fans out over this list, and spends on each"

        schema = client.get(f"/connections/{conn_id}/schema")
        assert schema.status_code == 200 and table.lower() in schema.text.lower(), schema.text
    finally:
        delete_connection(conn_id)


def test_a_server_that_is_not_running_says_so(server):
    """The 503 that names the database, not a 500. Nothing listens on port 1."""
    from aughor.db.errors import ConnectionUnreachable

    s, _ = server
    dsn = re.sub(r":\d+/", ":1/", s.dsn)
    with pytest.raises(ConnectionUnreachable):
        open_connection(s.type, dsn, meta={**s.meta, "port": "1"} if s.meta else {})


@pytest.mark.parametrize("type_", ["timescaledb", "mysql", "mariadb", "clickhouse", "mssql", "oracle"])
def test_a_wrong_password_is_not_called_unreachable(type_):
    from aughor.db.errors import ConnectionUnreachable

    s = SERVERS[type_]
    if not _running(s.port):
        pytest.skip(f"nothing on :{s.port}")
    dsn = s.dsn.replace("postgres:proof@", "postgres:wrong@")
    meta = {**s.meta, "password": "wrong"} if s.meta else {}
    try:
        conn = open_connection(type_, dsn, meta=meta)
        ok, said = conn.test()     # ClickHouse answers only when asked something
        assert not ok, said
    except ConnectionUnreachable:
        pytest.fail("a server that answered was called unreachable")
    except Exception as exc:  # noqa: BLE001 — the driver's own refusal is the right answer
        print(f"{type_} wrong password: {str(exc)[:120]}")
