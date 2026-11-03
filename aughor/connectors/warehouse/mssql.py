"""Microsoft SQL Server, and Azure Synapse through the same driver. `pymssql`; declared in `connectors/declarations.py`.

SQL Server has no session that refuses writes for a login that may write, so the door's checks are the boundary: say so with
a read-only login where it matters.
"""
from __future__ import annotations

from aughor.connectors.declarations import declaration
from aughor.connectors.warehouse.dbapi import DbApiWarehouse, limit_as_engine_caps, literal

_DECL = declaration("mssql")


class MSSQLConnection(DbApiWarehouse):
    connector_category = _DECL.category
    dialect = _DECL.dialect
    writes_native_sql = _DECL.native_sql
    engine_read_only = _DECL.engine_read_only
    param_style = _DECL.param_style
    _NAME = "SQL Server"
    _LIVENESS_SQL = "SELECT SERVERPROPERTY('ProductVersion')"

    def __init__(self, dsn: str = "", schema_name: str | None = None, connection_id: str = "", meta: dict | None = None) -> None:
        self.dep_check("pymssql", "pymssql>=2.3.0")
        import pymssql

        meta = meta or {}
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("schema_name") or "dbo"
        self._conn = pymssql.connect(
            server=meta.get("host", "localhost"), port=int(meta.get("port") or 1433),
            user=meta.get("user", ""), password=meta.get("password", ""), database=meta.get("database", ""),
            login_timeout=15, timeout=300, autocommit=True,
        )

    def is_healthy(self) -> bool:
        """A round trip: the driver goes on saying it is connected after the server has gone."""
        cur = None
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchall()
            return True
        except Exception:  # noqa: BLE001 — not healthy is the answer
            return False
        finally:
            self._close_cursor(cur)

    def _spelled_for_engine(self, sql: str) -> str:
        return limit_as_engine_caps(sql, "tsql")

    def _columns_sql(self) -> str:
        return ("SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE TABLE_SCHEMA = {literal(self._schema_name)} ORDER BY TABLE_NAME, ORDINAL_POSITION")
