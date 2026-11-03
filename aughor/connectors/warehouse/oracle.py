"""Oracle Database. `oracledb` in thin mode, so no client libraries; declared in `connectors/declarations.py`.

Read-only is the engine's: each statement runs in a READ ONLY transaction, so the server itself refuses a write. Oracle has no
session setting for this, and a read-only transaction reads one snapshot, so it is rolled back and begun again per statement.
A read-only transaction begun within seconds of a table's DDL refuses to read that table (ORA-01466), and says so.
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from aughor.connectors.declarations import declaration
from aughor.connectors.warehouse.dbapi import DbApiWarehouse, limit_as_engine_caps, literal

_DECL = declaration("oracle")
_PLAIN_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")

_NOT_ORACLES_OWN = "owner NOT IN (SELECT username FROM all_users WHERE oracle_maintained = 'Y')"
#: Oracle has no INFORMATION_SCHEMA, and the platform's catalog reads are written against it. Its own views, under those names.
_INFORMATION_SCHEMA = {
    "COLUMNS": ("SELECT owner AS table_schema, table_name, column_name, data_type, DECODE(nullable, 'N', 'NO', 'YES') AS is_nullable, "
                f"column_id AS ordinal_position FROM all_tab_columns WHERE {_NOT_ORACLES_OWN}"),
    "TABLES": f"SELECT owner AS table_schema, table_name, 'BASE TABLE' AS table_type FROM all_tables WHERE {_NOT_ORACLES_OWN}",
}


class OracleConnection(DbApiWarehouse):
    connector_category = _DECL.category
    dialect = _DECL.dialect
    writes_native_sql = _DECL.native_sql
    engine_read_only = _DECL.engine_read_only
    param_style = _DECL.param_style
    _NAME = "Oracle"
    _LIVENESS_SQL = "SELECT banner_full FROM v$version"

    def __init__(self, dsn: str = "", schema_name: str | None = None, connection_id: str = "", meta: dict | None = None) -> None:
        self.dep_check("oracledb", "oracledb>=2.0.0")
        import oracledb

        meta = meta or {}
        self._connection_id = connection_id
        oracledb.defaults.fetch_lobs = False    # a CLOB as its text, not a handle that dies with the cursor
        self._conn = oracledb.connect(
            user=meta.get("user", ""), password=meta.get("password", ""), host=meta.get("host", "localhost"),
            port=int(meta.get("port") or 1521), service_name=meta.get("service_name", ""),
        )
        # Oracle folds an unquoted name to upper case, so an owner is looked up that way.
        self._schema_name = str(schema_name or meta.get("schema_name") or meta.get("user", "")).upper()
        cur = self._conn.cursor()
        if _PLAIN_NAME.match(self._schema_name):
            cur.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {self._schema_name}")
        # A date reads and compares as the ISO text every other engine uses, not as the install's DD-MON-RR.
        cur.execute("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'")
        cur.execute("ALTER SESSION SET NLS_TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS.FF'")
        cur.close()

    def is_healthy(self) -> bool:
        try:
            return self._conn.is_healthy()
        except Exception:  # noqa: BLE001 — not healthy is the answer
            return False

    def _before_statement(self) -> None:
        self._conn.rollback()
        cur = self._conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.close()

    def _spelled_for_engine(self, sql: str) -> str:
        sql = limit_as_engine_caps(sql, "oracle")
        if "INFORMATION_SCHEMA" not in sql.upper():
            return sql
        try:
            tree = sqlglot.parse_one(sql, read="oracle")
            for table in list(tree.find_all(exp.Table)):
                view = _INFORMATION_SCHEMA.get(table.name.upper()) if table.db.upper() == "INFORMATION_SCHEMA" else None
                if view:
                    table.replace(sqlglot.parse_one(view, read="oracle").subquery(table.alias or table.name))
            return tree.sql(dialect="oracle")
        except sqlglot.errors.SqlglotError:
            return sql

    def _columns_sql(self) -> str:
        return ("SELECT table_name, column_name, data_type FROM all_tab_columns "
                f"WHERE owner = {literal(self._schema_name)} ORDER BY table_name, column_id")
