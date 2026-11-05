"""What every plain DB-API warehouse does the same way, so a connector is only what is its own.

A subclass opens `self._conn` and says how to read its columns. The door, the security gates, the row policy, the row cap,
typed values and the audit are here, the same order every connector runs them in (`trino.py` is the same read, written out).
"""
from __future__ import annotations

import re
import time

import sqlglot

from aughor.connectors.base import Connector, stage_type
from aughor.db.signing import sign
from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.doors import through_door
from aughor.db.errors import classify_error

MAX_ROWS = 2000


def literal(value: str) -> str:
    """A schema's name as a SQL string, for the catalog reads a driver's differing bind styles make awkward."""
    return "'" + str(value).replace("'", "''") + "'"


def limit_as_engine_caps(sql: str, dialect: str) -> str:
    """A LIMIT on an engine that has none, as its own cap. Unparseable SQL is left for the engine to refuse."""
    if not re.search(r"\bLIMIT\b", sql, re.I):
        return sql
    try:
        return sqlglot.transpile(sql, read=dialect, write=dialect)[0]
    except sqlglot.errors.SqlglotError:
        return sql


class DbApiWarehouse(Connector):
    reads_one_schema = True   # the one it connected to: `routers._shared.schemas_of_connection` lists no other
    #: One statement that proves the server answers, and what `test()` calls it.
    _LIVENESS_SQL = "SELECT 1"
    _NAME = ""

    def _columns_sql(self) -> str:
        """Three columns, ordered by table then position: table, column, type."""
        raise NotImplementedError

    def _before_statement(self) -> None:
        """What the session needs before each statement. Most need nothing."""

    def _spelled_for_engine(self, sql: str) -> str:
        """The platform's catalog reads and row caps are written one way, and a person's habit may be too. Most need nothing."""
        return sql

    def is_healthy(self) -> bool:
        return getattr(self, "_conn", None) is not None and not bool(getattr(self._conn, "closed", False))

    def execute(self, hypothesis_id: str, sql: str, *, sql_dialect: str | None = None, internal: bool = False) -> QueryResult:
        return through_door(self, sql, sql_dialect, lambda statement: self._execute(hypothesis_id, statement, MAX_ROWS), internal=internal)

    def execute_bounded(self, hypothesis_id: str, sql: str, max_rows: int, *,
                        sql_dialect: str | None = None, internal: bool = False) -> QueryResult:
        """Up to ``max_rows`` rows: the cross-source reads and key measurements read past MAX_ROWS."""
        return through_door(self, sql, sql_dialect, lambda statement: self._execute(hypothesis_id, statement, max(1, max_rows)), internal=internal)

    def _execute(self, hypothesis_id: str, sql: str, max_rows: int) -> QueryResult:
        from aughor.db.connection import enforce_row_policy, offer_typed_rows, security_post, security_pre

        sql = self._spelled_for_engine(sql.strip().rstrip(";"))
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked
        sql, policy = enforce_row_policy(self, hypothesis_id, sql)
        if policy is not None:
            return policy

        started = time.monotonic()
        cur = None
        try:
            self._before_statement()
            cur = self._conn.cursor()
            cur.execute(sign(sql))
            description = list(cur.description or [])
            # one row past the cap: a read the cap cut counts more rows than it keeps
            rows_raw = cur.fetchmany(max_rows + 1) if description else []
            offer_typed_rows([list(row) for row in rows_raw[:max_rows]], truncated=len(rows_raw) > max_rows,
                             types=[stage_type(d[1] if isinstance(d[1], str) else None) for d in description])
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql, columns=[d[0] for d in description],
                rows=[[str(v) if v is not None else "NULL" for v in row] for row in rows_raw[:max_rows]],
                row_count=len(rows_raw),
            )
        except Exception as exc:  # noqa: BLE001 — an engine error is the result's error, never a raise
            result = QueryResult(hypothesis_id=hypothesis_id, sql=sql, columns=[], rows=[], row_count=0,
                                 error=str(exc), error_kind=classify_error(exc))
        finally:
            self._close_cursor(cur)
        return security_post(self._connection_id, hypothesis_id, sql, result, (time.monotonic() - started) * 1000)

    def _bind_execute(self, sql: str, params: dict) -> tuple[list[str], list]:
        """The base class's bound run stops here. A subclass whose driver binds says how in `param_style`."""
        cur = None
        try:
            self._before_statement()
            cur = self._conn.cursor()
            cur.execute(sign(sql), params)
            description = list(cur.description or [])
            rows = cur.fetchmany(self.max_rows + 1) if description else []
            return [d[0] for d in description], [list(row) for row in rows]
        finally:
            self._close_cursor(cur)

    def get_schema(self) -> str:
        cur = None
        try:
            self._before_statement()
            cur = self._conn.cursor()
            cur.execute(self._columns_sql())
            tables: dict[str, list[str]] = {}
            for table, column, kind in cur.fetchall():
                tables.setdefault(str(table), []).append(f"{column} {kind}")
            return "\n".join(f"TABLE: {name} [{', '.join(cols)}]" for name, cols in tables.items())
        except Exception as exc:  # noqa: BLE001 — said in the schema text, as every connector says it
            return f"# Schema introspection failed: {exc}"
        finally:
            self._close_cursor(cur)

    def test(self) -> tuple[bool, str]:
        cur = None
        try:
            self._before_statement()
            cur = self._conn.cursor()
            cur.execute(self._LIVENESS_SQL)
            row = cur.fetchone()
            return True, f"Connected to {self._NAME} {row[0] if row else ''}".strip()
        except Exception as exc:  # noqa: BLE001 — the test's answer
            return False, str(exc)
        finally:
            self._close_cursor(cur)

    def _close_cursor(self, cur) -> None:
        try:
            if cur is not None:
                cur.close()
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "best-effort cursor close; the result is already read", counter="dbapi.cursor_close_failed",
                     conn_id=getattr(self, "_connection_id", None))

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception as exc:  # noqa: BLE001
            from aughor.kernel.errors import tolerate
            tolerate(exc, "best-effort connection close", counter="dbapi.close_failed", conn_id=getattr(self, "_connection_id", None))
