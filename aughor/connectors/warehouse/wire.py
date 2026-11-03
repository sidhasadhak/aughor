"""Engines that speak another's protocol and answer its catalog: the same driver and the same door, under their own name.

Postgres's: CockroachDB, TimescaleDB, YugabyteDB, Greenplum, Redshift, Aurora, AlloyDB, Neon and Supabase. MySQL's: MariaDB, TiDB,
Aurora, SingleStore, StarRocks and Doris. Each is one declaration in `aughor/connectors/declarations.py`; these classes exist for
what they do differently. An engine may refuse what makes a session read-only, or take it and do nothing, so read-only is
measured here rather than assumed, and one that is not says so: the door's checks are then the boundary, as on BigQuery.
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from aughor.connectors.warehouse.mysql import MySQLConnection
from aughor.db.connection import PostgresConnection

#: A server or pooler refusing the startup `options` parameter, as PgBouncer, Supavisor and Redshift word it.
_NO_STARTUP_OPTIONS = re.compile(r"unsupported startup parameter|unrecognized configuration parameter|options", re.I)


class PostgresWireConnection(PostgresConnection):
    connector_category = "warehouse"
    engine_read_only = True

    @staticmethod
    def is_server_schema(schema: str) -> bool:
        """Listed as tables like any other, and none of the person's: TimescaleDB's own four."""
        return schema.startswith("_timescaledb_")

    def __init__(self, dsn: str, schema_name: str | None = None, connection_id: str = "", meta: dict | None = None) -> None:
        super().__init__(dsn, schema_name=schema_name, connection_id=connection_id)

    def _connect(self) -> None:
        import psycopg2

        try:
            super()._connect()
        except psycopg2.OperationalError as exc:
            if not _NO_STARTUP_OPTIONS.search(str(exc)):
                raise
            self._connect_without_startup_options()

    def _connect_without_startup_options(self) -> None:
        import psycopg2

        from aughor.db.dsn import split_dsn

        base, params, _dropped = split_dsn(self._dsn)
        self._conn = psycopg2.connect(base, **params)
        self._conn.autocommit = True
        with self._conn.cursor() as cur:
            try:
                cur.execute("SET default_transaction_read_only = on")
                self.engine_read_only = True
            except psycopg2.Error:
                self.engine_read_only = False
            if self._schema_name != "public":
                cur.execute(f"SET search_path = {self._schema_name}")

    def translate(self, sql: str) -> str:
        """DuckDB's `/` is a float's, so sqlglot casts the numerator. CockroachDB has no float divided by an int, and on the rest
        casting the denominator as well changes nothing."""
        out = super().translate(sql)
        if "/" not in out or "DOUBLE PRECISION" not in out:
            return out
        try:
            tree = sqlglot.parse_one(out, read="postgres")
            for div in tree.find_all(exp.Div):
                if div.left.is_type(exp.DataType.Type.DOUBLE) and not div.right.is_type(exp.DataType.Type.DOUBLE):
                    div.set("expression", exp.cast(div.right.copy(), "DOUBLE PRECISION"))
            return tree.sql(dialect="postgres")
        except sqlglot.errors.SqlglotError:
            return out


#: A MySQL-protocol server refusing `SET SESSION TRANSACTION READ ONLY`, as TiDB words it, or not parsing it at all.
_NO_READ_ONLY_SESSION = re.compile(r"noop implementation|syntax|not supported|unsupported", re.I)


class MySQLWireConnection(MySQLConnection):
    def __init__(self, dsn: str = "", schema_name: str | None = None, connection_id: str = "", meta: dict | None = None) -> None:
        import pymysql

        try:
            super().__init__(dsn, schema_name=schema_name, connection_id=connection_id, meta=meta)
        except pymysql.MySQLError as exc:
            if not _NO_READ_ONLY_SESSION.search(str(exc)):
                raise
            self._SESSION_INIT = None
            super().__init__(dsn, schema_name=schema_name, connection_id=connection_id, meta=meta)
        self.engine_read_only = self._session_reads_read_only()

    def _session_reads_read_only(self) -> bool:
        """What the server says of this session. The names differ by engine and age; none answering means none is enforced."""
        for variable in ("transaction_read_only", "tx_read_only"):
            try:
                with self._conn.cursor() as cur:
                    cur.execute(f"SELECT @@session.{variable} AS read_only")
                    return str(cur.fetchone()["read_only"]) == "1"
            except Exception:  # noqa: BLE001 — an engine without the variable, and the next spelling is tried
                continue
        return False
