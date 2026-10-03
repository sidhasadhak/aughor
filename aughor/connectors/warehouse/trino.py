"""Trino connector for Aughor — DE-3b's proving engine (ROADMAP §3.51; §6 item 37(d)).

DSN format:  trino://host:8080
Meta fields: {"user": "...", "password": "...", "catalog": "...", "schema_name": "..."}

Optional dep:
  uv pip install 'trino>=0.330.0'

Declared once in `aughor/connectors/declarations.py` (dialect `trino`, native SQL, no bind style,
the writer rules, the refused constructs, the picker's label and badge); this module is the
connector that declaration names. Its live receipt — a local Trino container answering through
the picker, the writer rules and the catalog — is owed from the user's machine.
"""
from __future__ import annotations

import time

from aughor.connectors.base import Connector
from aughor.connectors.declarations import declaration
from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.doors import through_door
from aughor.db.errors import classify_error

MAX_ROWS = 2000
_DECL = declaration("trino")


class TrinoConnection(Connector):
    connector_category = _DECL.category
    # DE-3b — read from the declaration, not restated: the declaration is the one place these
    # facts are written; the class references it.
    dialect = _DECL.dialect
    writes_native_sql = _DECL.native_sql
    # Trino has no session-level read-only; the door's checks are the boundary, said on the doors.
    engine_read_only = _DECL.engine_read_only
    #: No `param_style` (see the declaration and tests' NO_BINDING): the DBAPI binds positionally.

    def __init__(
        self,
        dsn: str,
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self.dep_check("trino", "trino>=0.330.0")
        import trino

        meta = meta or {}
        self._connection_id = connection_id
        self._schema_name = schema_name or meta.get("schema_name") or ""
        self._catalog = meta.get("catalog") or ""

        host_port = dsn.removeprefix("trino://").removeprefix("https://").removeprefix("http://").strip("/") \
            or meta.get("host", "")
        host, _, port = host_port.partition(":")
        user = meta.get("user") or "aughor"
        password = meta.get("password") or ""
        kwargs: dict = {
            "host": host or "localhost",
            "port": int(port) if port.isdigit() else 8080,
            "user": user,
            "catalog": self._catalog or None,
            "schema": self._schema_name or None,
            "request_timeout": 30,
        }
        if password:
            # A password needs TLS on the wire; the driver refuses basic auth over plain HTTP.
            kwargs["http_scheme"] = "https"
            kwargs["auth"] = trino.auth.BasicAuthentication(user, password)
        self._conn = trino.dbapi.connect(**kwargs)

    def is_healthy(self) -> bool:
        """Cheap liveness probe for the pool (DE-3d): the DBAPI connection stays usable until
        closed; a closed one has no transaction and refuses a cursor."""
        try:
            return self._conn is not None and not bool(getattr(self._conn, "_closed", False))
        except Exception:
            return False

    @staticmethod
    def _stage_type(description_row: object) -> str:
        """The DBAPI description names the Trino type (`type_code`) in its own words."""
        from aughor.connectors.base import stage_type
        try:
            return stage_type(description_row[1])
        except Exception:
            return stage_type(None)

    def execute(self, hypothesis_id: str, sql: str, *, sql_dialect: str | None = None, internal: bool = False) -> QueryResult:
        return through_door(self, sql, sql_dialect, lambda statement: self._execute(hypothesis_id, statement, MAX_ROWS), internal=internal)

    def execute_bounded(self, hypothesis_id: str, sql: str, max_rows: int, *,
                        sql_dialect: str | None = None, internal: bool = False) -> QueryResult:
        """Up to ``max_rows`` rows — the cross-source reads and key measurements read past MAX_ROWS."""
        return through_door(self, sql, sql_dialect, lambda statement: self._execute(hypothesis_id, statement, max(1, max_rows)), internal=internal)

    def _execute(self, hypothesis_id: str, sql: str, max_rows: int) -> QueryResult:
        from aughor.db.connection import enforce_row_policy, offer_typed_rows, security_pre, security_post

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked
        sql, _rp = enforce_row_policy(self, hypothesis_id, sql)   # RBAC row-policy (Rec 7); no-op off
        if _rp is not None:
            return _rp

        _t0 = time.monotonic()
        cur = None
        try:
            cur = self._conn.cursor()
            cur.execute(sql)
            description = list(cur.description or [])
            columns = [d[0] for d in description]
            # one row past the cap: a read the cap cut counts more rows than it keeps
            rows_raw = cur.fetchmany(max_rows + 1)
            offer_typed_rows([list(row) for row in rows_raw[:max_rows]], truncated=len(rows_raw) > max_rows,
                             types=[self._stage_type(d) for d in description])
            rows = [[str(v) if v is not None else "NULL" for v in row] for row in rows_raw[:max_rows]]
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=columns, rows=rows, row_count=len(rows_raw),
            )
        except Exception as e:
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=[], rows=[], row_count=0, error=str(e), error_kind=classify_error(e),
            )
        finally:
            try:
                if cur is not None:
                    cur.close()
            except Exception:
                pass
        elapsed_ms = (time.monotonic() - _t0) * 1000
        return security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            cur = self._conn.cursor()
            cur.execute(f"EXPLAIN (TYPE VALIDATE) {sql.rstrip(';')}")
            cur.fetchall()
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        lines: list[str] = []
        try:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = ? ORDER BY table_name, ordinal_position",
                [self._schema_name or "default"],
            )
            from collections import defaultdict
            table_cols: dict[str, list[str]] = defaultdict(list)
            for tname, col, dtype in cur.fetchall():
                table_cols[tname].append(f"{col} {dtype}")
            for tname, cols in table_cols.items():
                lines.append(f"TABLE: {tname} [{', '.join(cols)}]")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines)

    def test(self) -> tuple[bool, str]:
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT version()")
            row = cur.fetchone()
            return True, f"Connected to Trino {row[0] if row else '?'}"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
