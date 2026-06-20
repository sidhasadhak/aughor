"""Exasol connector for Aughor.

DSN format:  exa://host:8563
Meta fields: {"user": "...", "password": "...", "schema_name": "..."}

Optional dep:
  uv pip install 'pyexasol>=0.25.0'
"""
from __future__ import annotations

import time

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

MAX_ROWS = 2000


class ExasolConnection(Connector):
    connector_category = "warehouse"
    dialect = "postgres"  # Exasol speaks standard SQL; postgres transpile is the closest fit
    writes_native_sql = True  # execute() runs the LLM's SQL natively (no duckdb transpile)

    def __init__(
        self,
        dsn: str,
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self.dep_check("pyexasol", "pyexasol>=0.25.0")
        import pyexasol

        meta = meta or {}
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("schema_name") or ""

        dsn_host = dsn.removeprefix("exa://").strip("/") or meta.get("host", "")

        self._conn = pyexasol.connect(
            dsn=dsn_host,
            user=meta.get("user", ""),
            password=meta.get("password", ""),
            schema=self._schema_name or "",
            connection_timeout=30,
        )

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import _security_pre, _security_post

        sql = sql.strip().rstrip(";")
        if (blocked := _security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked

        _t0 = time.monotonic()
        try:
            stmt = self._conn.execute(sql)
            columns = list(stmt.columns().keys())
            rows_raw = stmt.fetchmany(MAX_ROWS)
            rows = [[str(v) if v is not None else "NULL" for v in row] for row in rows_raw]
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=columns, rows=rows, row_count=len(rows),
            )
        except Exception as e:
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=[], rows=[], row_count=0, error=str(e),
            )
        elapsed_ms = (time.monotonic() - _t0) * 1000
        return _security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            # Exasol has no cheap EXPLAIN; prepare via a zero-row wrapper.
            self._conn.execute(f"SELECT * FROM ({sql.rstrip(';')}) AS _dry WHERE 1=0")
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        lines: list[str] = []
        try:
            stmt = self._conn.execute(
                """
                SELECT column_table, column_name, column_type
                FROM EXA_ALL_COLUMNS
                WHERE column_schema = :schema
                ORDER BY column_table, column_ordinal_position
                """,
                {"schema": (self._schema_name or "").upper()},
            )
            rows = stmt.fetchall()
            from collections import defaultdict
            table_cols: dict[str, list[str]] = defaultdict(list)
            for tname, col, dtype in rows:
                table_cols[tname].append(f"{col} {dtype}")
            for tname, cols in table_cols.items():
                lines.append(f"TABLE: {tname} [{', '.join(cols)}]")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines)

    def test(self) -> tuple[bool, str]:
        try:
            stmt = self._conn.execute("SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'")
            row = stmt.fetchone()
            version = row[0] if row else "?"
            return True, f"Connected to Exasol {version}"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
