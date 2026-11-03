"""Databricks SQL warehouses and clusters. `databricks-sql-connector`; declared in `connectors/declarations.py`.

Written from Databricks's documentation and not yet run against a workspace, so it is Preview. Databricks has no read-only
session for a token that may write: the door's checks are the boundary.
"""
from __future__ import annotations

from aughor.connectors.declarations import declaration
from aughor.connectors.warehouse.dbapi import DbApiWarehouse, literal

_DECL = declaration("databricks")


class DatabricksConnection(DbApiWarehouse):
    connector_category = _DECL.category
    dialect = _DECL.dialect
    writes_native_sql = _DECL.native_sql
    engine_read_only = _DECL.engine_read_only
    _NAME = "Databricks"
    _LIVENESS_SQL = "SELECT current_version().dbsql_version"

    def __init__(self, dsn: str = "", schema_name: str | None = None, connection_id: str = "", meta: dict | None = None) -> None:
        self.dep_check("databricks.sql", "databricks-sql-connector>=3.0.0")
        from databricks import sql

        meta = meta or {}
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("schema_name") or "default"
        self._conn = sql.connect(
            server_hostname=meta.get("host", ""), http_path=meta.get("http_path", ""),
            access_token=meta.get("access_token", ""), catalog=meta.get("catalog") or None, schema=self._schema_name,
        )

    def _columns_sql(self) -> str:
        return ("SELECT table_name, column_name, full_data_type FROM INFORMATION_SCHEMA.COLUMNS "
                f"WHERE table_schema = {literal(self._schema_name)} ORDER BY table_name, ordinal_position")
