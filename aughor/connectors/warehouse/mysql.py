"""MySQL / MariaDB connector for Aughor.

DSN format:  mysql://user:password@host:3306/database
Meta fields: {"ssl_ca": "/path/to/ca.pem"}  (optional)

Optional dep:
  uv pip install 'PyMySQL>=1.0.0'
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

MAX_ROWS = 2000


class MySQLConnection(Connector):
    connector_category = "warehouse"
    dialect = "mysql"

    def __init__(
        self,
        dsn: str,
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self.dep_check("pymysql", "PyMySQL>=1.0.0")
        import pymysql

        meta = meta or {}
        self._connection_id = connection_id

        # Parse DSN:  mysql://user:pass@host:3306/dbname
        parsed = urlparse(dsn.replace("mysql://", "http://", 1))  # urlparse needs a scheme
        self._host     = parsed.hostname or meta.get("host", "localhost")
        self._port     = parsed.port or int(meta.get("port", 3306))
        self._user     = parsed.username or meta.get("user", "root")
        self._password = parsed.password or meta.get("password", "")
        self._database = (parsed.path or "").lstrip("/") or meta.get("database", "")
        self._schema_name = schema_name or self._database

        ssl_opts = {}
        if meta.get("ssl_ca"):
            ssl_opts = {"ssl": {"ca": meta["ssl_ca"]}}

        self._conn = pymysql.connect(
            host=self._host, port=self._port,
            user=self._user, password=self._password,
            database=self._database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=30,
            **ssl_opts,
        )

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import _security_pre, _security_post

        sql = sql.strip().rstrip(";")
        if (blocked := _security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked

        _t0 = time.monotonic()
        try:
            with self._conn.cursor() as cur:
                cur.execute(sql)
                rows_raw = cur.fetchmany(MAX_ROWS)
                columns = list(rows_raw[0].keys()) if rows_raw else (
                    [desc[0] for desc in cur.description] if cur.description else []
                )
                rows = [[str(v) if v is not None else "NULL" for v in row.values()] for row in rows_raw]
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=columns, rows=rows, row_count=len(rows),
            )
        except Exception as e:
            # Auto-reconnect on dropped connection
            try:
                self._conn.ping(reconnect=True)
            except Exception:
                pass
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=[], rows=[], row_count=0, error=str(e),
            )
        elapsed_ms = (time.monotonic() - _t0) * 1000
        return _security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"EXPLAIN {sql.rstrip(';')}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        lines: list[str] = []
        try:
            with self._conn.cursor() as cur:
                cur.execute("""
                    SELECT table_name, column_name, column_type
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    ORDER BY table_name, ordinal_position
                """, (self._database,))
                rows = cur.fetchall()
            from collections import defaultdict
            table_cols: dict[str, list[str]] = defaultdict(list)
            for row in rows:
                table_cols[row["table_name"]].append(
                    f"{row['column_name']} {row['column_type']}"
                )
            for tname, cols in table_cols.items():
                lines.append(f"TABLE: {tname} [{', '.join(cols)}]")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines)

    def test(self) -> tuple[bool, str]:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT VERSION()")
                row = cur.fetchone()
            version = list(row.values())[0] if row else "?"
            return True, f"Connected to MySQL {version} @ {self._host}"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
