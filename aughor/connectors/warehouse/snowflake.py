"""Snowflake connector for Aughor.

DSN format:  snowflake://account.region
Meta fields: {"user": "...", "password": "...", "database": "...",
              "schema_name": "PUBLIC", "warehouse": "COMPUTE_WH"}

Optional dep:
  uv pip install 'snowflake-connector-python>=3.0.0'
"""
from __future__ import annotations

import time

from aughor.connectors.base import Connector
from aughor.platform.contracts.execution import QueryResult

MAX_ROWS = 2000


class SnowflakeConnection(Connector):
    connector_category = "warehouse"
    dialect = "snowflake"
    writes_native_sql = True  # execute() runs the LLM's SQL natively (no duckdb transpile)

    def __init__(
        self,
        dsn: str,
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self.dep_check("snowflake.connector", "snowflake-connector-python>=3.0.0")
        import snowflake.connector

        meta = meta or {}
        account = dsn.removeprefix("snowflake://").strip("/") or meta.get("account", "")
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("schema_name") or "PUBLIC"
        self._database = meta.get("database", "")

        self._conn = snowflake.connector.connect(
            account=account,
            user=meta.get("user", ""),
            password=meta.get("password", ""),
            database=self._database,
            schema=self._schema_name,
            warehouse=meta.get("warehouse", ""),
            # network_timeout and login_timeout (seconds)
            login_timeout=30,
            network_timeout=60,
        )

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import security_pre, security_post

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked

        _t0 = time.monotonic()
        try:
            cur = self._conn.cursor()
            cur.execute(sql)
            rows_raw = cur.fetchmany(MAX_ROWS)
            columns = [desc[0] for desc in cur.description] if cur.description else []
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
        return security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            cur = self._conn.cursor()
            cur.execute(f"EXPLAIN {sql.rstrip(';')}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def export_csv(self, sql: str, path: str, *, statement_timeout: int = 60) -> tuple[bool, str]:
        """Materialize a query's FULL result to a CSV matching the Spider2 evaluator contract.

        Unlike ``execute`` (the UI path, which stringifies NULL → "NULL" and caps at MAX_ROWS for
        display), this writes the raw cursor: real NULL → empty cell, column order from
        ``cursor.description``, and EVERY row (no cap) — byte-compatible with the evaluator's
        ``pd.DataFrame(results, columns=cols).to_csv(index=False)``. Returns (ok, error)."""
        from aughor.sql.closed_loop import rows_to_csv
        try:
            cur = self._conn.cursor()
            cur.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {int(statement_timeout)}")
            cur.execute(sql.strip().rstrip(";"))
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()  # raw values, no stringify, no row cap
            rows_to_csv(columns, rows, path)
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        lines: list[str] = []
        try:
            cur = self._conn.cursor()
            query = """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
            """
            cur.execute(query, (self._schema_name.upper(),))
            rows = cur.fetchall()
            from collections import defaultdict
            table_cols: dict[str, list[str]] = defaultdict(list)
            for table_name, col_name, data_type in rows:
                table_cols[table_name].append(f"{col_name} {data_type}")
            for tname, cols in table_cols.items():
                lines.append(f"TABLE: {tname} [{', '.join(cols)}]")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines)

    def test(self) -> tuple[bool, str]:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT CURRENT_ACCOUNT(), CURRENT_DATABASE()")
            row = cur.fetchone()
            return True, f"Connected to Snowflake: account={row[0]}, db={row[1]}"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
