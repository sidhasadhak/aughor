"""MotherDuck connector for Aughor — DuckDB in the cloud.

DSN format:  md:<database>            (token supplied via meta or env)
Meta fields: {"token": "<motherduck_token>", "database": "my_db"}

MotherDuck is DuckDB-compatible, so queries run through the local duckdb
client with an `md:` attachment. A MotherDuck service token authenticates the
session — pass it in the form or set the MOTHERDUCK_TOKEN env var.

Optional dep:
  uv pip install 'duckdb>=0.10.0'   (already a core Aughor dependency)
"""
from __future__ import annotations

import os
import time

import duckdb

from aughor.connectors.base import Connector
from aughor.platform.contracts.execution import QueryResult

MAX_ROWS = 2000


class MotherDuckConnection(Connector):
    connector_category = "warehouse"
    dialect = "duckdb"

    def __init__(
        self,
        dsn: str,
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        meta = meta or {}
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("schema_name") or "main"

        token = meta.get("token") or os.environ.get("MOTHERDUCK_TOKEN", "")
        if token:
            os.environ["motherduck_token"] = token

        database = meta.get("database", "") or dsn.removeprefix("md:").strip("/")
        # `md:` connects to the user's default MotherDuck account;
        # `md:<db>` attaches a specific database.
        target = f"md:{database}" if database else "md:"
        self._database = database

        self._conn = duckdb.connect(target)

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import security_pre, security_post

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked

        _t0 = time.monotonic()
        try:
            self._conn.execute(sql)
            rows_raw = self._conn.fetchall()
            columns = [d[0] for d in self._conn.description] if self._conn.description else []
            rows = [
                [str(v) if v is not None else "NULL" for v in row]
                for row in rows_raw[:MAX_ROWS]
            ]
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=columns, rows=rows, row_count=len(rows_raw),
            )
        except Exception as e:
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=[], rows=[], row_count=0, error=str(e),
            )
        elapsed_ms = (time.monotonic() - _t0) * 1000
        return security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            self._conn.execute(f"EXPLAIN {sql.rstrip(';')}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        lines: list[str] = []
        try:
            self._conn.execute(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = ? "
                "ORDER BY table_name, ordinal_position",
                [self._schema_name],
            )
            rows = self._conn.fetchall()
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
            self._conn.execute("SELECT current_database()")
            row = self._conn.fetchone()
            db = row[0] if row else "?"
            return True, f"Connected to MotherDuck (database={db})"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
