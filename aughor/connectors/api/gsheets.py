"""Google Sheets connector for Aughor.

Reads one or more worksheets from a Google Spreadsheet into a local DuckDB
session so they can be queried like any other table.

DSN format:  gsheet://<spreadsheet_id>
Meta fields: {
    "spreadsheet_id": "1AbC...",     # or full /spreadsheets/d/<id>/ URL
    "sheets": "Sheet1,Sheet2",        # optional; comma-separated tab names
}

The sheet must be shared "Anyone with the link can view" — each worksheet is
fetched through its public CSV (gviz) export endpoint, handled by DuckDB's
httpfs extension. No credentials are used; private sheets require OAuth, which
this connector intentionally does not claim to support.

Optional dep:
  uv pip install 'duckdb>=0.10.0'   (already a core Aughor dependency)
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

import duckdb

from aughor.connectors.base import Connector
from aughor.platform.contracts.execution import QueryResult

MAX_ROWS = 2000

# ── Cross-request worksheet cache ─────────────────────────────────────────────
# A fresh connector is built per request; without this, every single query would
# re-download every worksheet over HTTP (slow + hammers Google's rate limits).
# We materialise the fetched worksheets into a temp DuckDB file keyed by
# (spreadsheet, sheets) with a short TTL; subsequent connectors READ_ONLY-attach
# it and copy the tables in — no HTTP, full type fidelity, no pyarrow dependency.
import tempfile as _tempfile

_SHEET_TTL_SECONDS = 300
_CACHE_DIR = Path(_tempfile.gettempdir()) / "aughor_gsheets_cache"
# key -> (timestamp, duckdb_file_path, [table_names])
_sheet_cache: dict[str, tuple[float, str, list[str]]] = {}


def invalidate_sheet_cache(spreadsheet_id: str | None = None) -> None:
    """Drop cached worksheets (call to force a re-fetch). None = clear all."""
    keys = list(_sheet_cache) if spreadsheet_id is None else [
        k for k in _sheet_cache if k.startswith(f"{spreadsheet_id}|")
    ]
    for k in keys:
        entry = _sheet_cache.pop(k, None)
        if entry:
            try:
                os.remove(entry[1])
            except Exception:
                pass


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

    def _cache_key(self) -> str:
        return f"{self._spreadsheet_id}|{','.join(self._sheets)}"

    def _load_from_cache(self) -> bool:
        """Copy worksheets from a fresh temp-DB cache (no HTTP). True on hit."""
        cached = _sheet_cache.get(self._cache_key())
        if not cached or (time.time() - cached[0]) >= _SHEET_TTL_SECONDS:
            return False
        _, fpath, tables = cached
        if not os.path.exists(fpath):
            return False
        try:
            self._duckdb.execute(f"ATTACH '{fpath}' AS _cache (READ_ONLY)")
            for table in tables:
                self._duckdb.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _cache."{table}"')
            self._duckdb.execute("DETACH _cache")
            return True
        except Exception:
            try:
                self._duckdb.execute("DETACH _cache")
            except Exception:
                pass
            return False

    def _save_to_cache(self, tables: list[str]) -> None:
        """Persist the just-fetched worksheets to a temp DuckDB file (best-effort)."""
        if not tables:
            return
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            fpath = str(_CACHE_DIR / (hashlib.md5(self._cache_key().encode()).hexdigest() + ".duckdb"))
            tmp = f"{fpath}.{os.getpid()}.{int(time.time()*1000)}.tmp"
            self._duckdb.execute(f"ATTACH '{tmp}' AS _cache")
            for table in tables:
                self._duckdb.execute(f'CREATE TABLE _cache."{table}" AS SELECT * FROM "{table}"')
            self._duckdb.execute("DETACH _cache")
            os.replace(tmp, fpath)  # atomic; existing READ_ONLY readers keep old inode
            _sheet_cache[self._cache_key()] = (time.time(), fpath, list(tables))
        except Exception:
            pass

    def _load_sheets(self) -> None:
        if self._load_from_cache():
            return

        targets = self._sheets or [""]  # empty string = first/default sheet
        loaded: list[str] = []
        for sheet in targets:
            table = _safe_table_name(sheet) if sheet else "sheet1"
            url = self._export_url(sheet or None)
            try:
                self._duckdb.execute(f'DROP TABLE IF EXISTS "{table}"')
                self._duckdb.execute(
                    f'CREATE TABLE "{table}" AS '
                    f"SELECT * FROM read_csv_auto('{url}', header=true, all_varchar=false)"
                )
                loaded.append(table)
            except Exception:
                # Skip sheets that fail to load rather than break the whole connection.
                pass
        self._save_to_cache(loaded)

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import enforce_row_policy, security_pre, security_post

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked
        sql, _rp = enforce_row_policy(self, hypothesis_id, sql)   # RBAC row-policy (Rec 7); no-op off
        if _rp is not None:
            return _rp

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
        return security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            self._duckdb.execute(f"EXPLAIN {sql.rstrip(';')}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        # Canonical Aughor schema format: `TABLE: name  (N rows)` followed by
        # 2-space-indented `  col  TYPE` lines. This is what build_rich_schema,
        # the schema-linker and the data catalog all parse — emitting the older
        # bracketed one-liner would hide every column from those layers.
        lines: list[str] = []
        try:
            self._duckdb.execute(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns "
                "ORDER BY table_name, ordinal_position"
            )
            rows = self._duckdb.fetchall()
            from collections import OrderedDict
            table_cols: "OrderedDict[str, list[tuple[str, str]]]" = OrderedDict()
            for tname, col, dtype in rows:
                table_cols.setdefault(tname, []).append((col, dtype))
            for tname, cols in table_cols.items():
                try:
                    self._duckdb.execute(f'SELECT COUNT(*) FROM "{tname}"')
                    n = int(self._duckdb.fetchone()[0])
                except Exception:
                    n = 0
                lines.append(f"TABLE: {tname}  ({n:,} rows)")
                for col, dtype in cols:
                    lines.append(f"  {col}  {dtype}")
                lines.append("")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines).strip() or "(no worksheets loaded)"

    def raw_execute(self, sql: str) -> tuple[list[str], list, list[str]]:
        """Run a raw query bypassing the SELECT-only validator — for metadata
        (DESCRIBE/PRAGMA) used by the catalog + columns endpoints."""
        self._duckdb.execute(sql)
        rows = self._duckdb.fetchall()
        desc = self._duckdb.description or []
        columns = [d[0] for d in desc]
        types = [str(d[1]) if len(d) > 1 and d[1] is not None else "" for d in desc]
        return columns, rows, types

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
