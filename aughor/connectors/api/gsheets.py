"""Google Sheets connector for Aughor.

Reads one or more worksheets from a Google Spreadsheet into a local DuckDB
session so they can be queried like any other table.

DSN format:  gsheet://<spreadsheet_id>
Meta fields: {
    "spreadsheet_id": "1AbC...",     # or full /spreadsheets/d/<id>/ URL
    "sheets": "Sheet1,Sheet2",        # optional; comma-separated tab names
    "api_key": "AIza...",             # optional; for private sheets via API
}

For public ("anyone with the link can view") sheets no credentials are needed —
each worksheet is fetched through its CSV export endpoint. DuckDB's httpfs
extension handles the HTTP fetch.

Optional dep:
  uv pip install 'duckdb>=0.10.0'   (already a core Aughor dependency)
"""
from __future__ import annotations

import re
import time

import duckdb

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

MAX_ROWS = 2000

_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def _extract_id(raw: str) -> str:
    m = _ID_RE.search(raw)
    if m:
        return m.group(1)
    return raw.strip()


def _safe_table_name(sheet: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", sheet.strip().lower()).strip("_")
    return name or "sheet"


class GoogleSheetsConnector(Connector):
    connector_category = "api"
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
        self._schema_name = schema_name

        raw_id = meta.get("spreadsheet_id") or dsn.removeprefix("gsheet://")
        self._spreadsheet_id = _extract_id(raw_id)
        self._sheets = [s.strip() for s in str(meta.get("sheets", "")).split(",") if s.strip()]
        self._api_key = meta.get("api_key", "")

        self._duckdb = duckdb.connect(":memory:")
        try:
            self._duckdb.execute("INSTALL httpfs; LOAD httpfs;")
        except Exception:
            pass
        self._load_sheets()

    def _export_url(self, sheet: str | None) -> str:
        base = f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/gviz/tq"
        params = "tqx=out:csv"
        if sheet:
            params += f"&sheet={sheet}"
        return f"{base}?{params}"

    def _load_sheets(self) -> None:
        targets = self._sheets or [""]  # empty string = first/default sheet
        for sheet in targets:
            table = _safe_table_name(sheet) if sheet else "sheet1"
            url = self._export_url(sheet or None)
            try:
                self._duckdb.execute(f"DROP TABLE IF EXISTS {table}")
                self._duckdb.execute(
                    f"CREATE TABLE {table} AS "
                    f"SELECT * FROM read_csv_auto('{url}', header=true, all_varchar=false)"
                )
            except Exception:
                # Skip sheets that fail to load rather than break the whole connection.
                pass

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import _security_pre, _security_post

        sql = sql.strip().rstrip(";")
        if (blocked := _security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked

        _t0 = time.monotonic()
        try:
            self._duckdb.execute(sql)
            rows_raw = self._duckdb.fetchall()
            columns = [d[0] for d in self._duckdb.description] if self._duckdb.description else []
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
        return _security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            self._duckdb.execute(f"EXPLAIN {sql.rstrip(';')}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        lines: list[str] = []
        try:
            self._duckdb.execute(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns "
                "ORDER BY table_name, ordinal_position"
            )
            rows = self._duckdb.fetchall()
            from collections import defaultdict
            table_cols: dict[str, list[str]] = defaultdict(list)
            for tname, col, dtype in rows:
                table_cols[tname].append(f"{col} {dtype}")
            for tname, cols in table_cols.items():
                lines.append(f"TABLE: {tname} [{', '.join(cols)}]")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines) or "(no worksheets loaded)"

    def test(self) -> tuple[bool, str]:
        try:
            self._duckdb.execute("SELECT table_name FROM information_schema.tables")
            tables = [r[0] for r in self._duckdb.fetchall()]
            if not tables:
                return False, (
                    "No worksheets could be loaded. Check the spreadsheet is shared "
                    "as 'anyone with the link can view' and the sheet names are correct."
                )
            return True, f"Loaded {len(tables)} worksheet(s): {', '.join(tables)}"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass
