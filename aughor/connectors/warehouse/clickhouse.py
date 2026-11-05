"""ClickHouse over HTTP. `clickhouse-connect`; declared in `connectors/declarations.py`.

Read-only is the engine's: `readonly` on every query makes the server refuse a write.
"""
from __future__ import annotations

from aughor.connectors.declarations import declaration
from aughor.connectors.warehouse.dbapi import DbApiWarehouse, literal

_DECL = declaration("clickhouse")


class ClickHouseConnection(DbApiWarehouse):
    connector_category = _DECL.category
    dialect = _DECL.dialect
    writes_native_sql = _DECL.native_sql
    engine_read_only = _DECL.engine_read_only
    param_style = _DECL.param_style
    _NAME = "ClickHouse"
    _LIVENESS_SQL = "SELECT version()"

    def __init__(self, dsn: str = "", schema_name: str | None = None, connection_id: str = "", meta: dict | None = None) -> None:
        self.dep_check("clickhouse_connect", "clickhouse-connect>=0.8.0")
        from clickhouse_connect import dbapi

        meta = meta or {}
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("database") or meta.get("schema_name") or "default"
        self._conn = dbapi.connect(
            host=meta.get("host", "localhost"), port=int(meta.get("port") or 8123),
            username=meta.get("user", "default"), password=meta.get("password", ""), database=self._schema_name,
            secure=str(meta.get("secure", "")).strip().lower() in ("1", "true", "yes"),
            readonly=2,     # the driver reads a keyword it does not know as a server setting
        )

    def _columns_sql(self) -> str:
        return ("SELECT table, name, type FROM system.columns "
                f"WHERE database = {literal(self._schema_name)} ORDER BY table, position")

    def query_history(self, *, hours: int = 24 * 14, limit: int = 2000):
        """Arc NV-3 — finished SELECT statements on this database from `system.query_log`, newest first."""
        from aughor.db.query_history import rows_from_result
        hours, limit = max(1, int(hours)), max(1, min(int(limit), 10000))
        source = "system.query_log"
        sql = (
            "SELECT event_time, query, user FROM system.query_log "
            f"WHERE type = 'QueryFinish' AND query_kind = 'Select' AND current_database = {literal(self._schema_name)} "
            f"AND event_time > now() - INTERVAL {hours} HOUR ORDER BY event_time DESC LIMIT {limit}"
        )
        result = self.execute_bounded("__query_history__", sql, limit, sql_dialect=None, internal=True)
        return rows_from_result(result, self.dialect, source=source, hours=hours, limit=limit)
