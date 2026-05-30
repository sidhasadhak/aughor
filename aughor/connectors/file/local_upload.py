"""Local file upload connector — CSV, Parquet, Excel materialized into DuckDB.

No external dependencies — DuckDB handles all file formats natively.

DSN:   local://  (sentinel; files are stored in data/uploads/{connection_id}/)
Usage:
    conn = LocalUploadConnection(dsn="local://", connection_id="my_conn")
    conn.ingest_file(Path("/tmp/sales.csv"), "sales")
    result = conn.execute("inv1", "SELECT * FROM sales LIMIT 10")

The upload directory persists between server restarts. On __init__ any
previously-ingested tables are re-registered automatically.
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

MAX_ROWS = 2000
_UPLOAD_ROOT = Path("data/uploads")

_SUPPORTED_EXTENSIONS = {
    ".csv":     "read_csv_auto",
    ".tsv":     "read_csv_auto",
    ".parquet": "read_parquet",
    ".parq":    "read_parquet",
    ".xlsx":    "read_excel",
    ".xls":     "read_excel",
    ".json":    "read_json_auto",
}


class LocalUploadConnection(Connector):
    connector_category = "file"
    dialect = "duckdb"

    def __init__(
        self,
        dsn: str = "local://",
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self._connection_id = connection_id
        self._schema_name = schema_name
        self._upload_dir = _UPLOAD_ROOT / (connection_id or "default")
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        self._duckdb = duckdb.connect(":memory:")
        # Re-register any previously uploaded files
        self._reload_existing_files()

    # ── File ingestion ─────────────────────────────────────────────────────────

    def ingest_file(self, file_path: Path, table_name: str | None = None) -> str:
        """
        Copy a file into the upload directory and register it as a DuckDB table.
        Returns the table name used.
        """
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. Supported: {list(_SUPPORTED_EXTENSIONS)}"
            )

        # Persist the file in the upload dir
        dest = self._upload_dir / file_path.name
        if file_path != dest:
            import shutil
            shutil.copy2(file_path, dest)

        table_name = table_name or file_path.stem.lower().replace("-", "_").replace(" ", "_")
        self._register_file(dest, table_name)
        return table_name

    def _register_file(self, path: Path, table_name: str) -> None:
        ext = path.suffix.lower()
        reader = _SUPPORTED_EXTENSIONS.get(ext, "read_csv_auto")
        try:
            # DROP TABLE IF EXISTS so re-registration is idempotent
            self._duckdb.execute(f"DROP TABLE IF EXISTS {table_name}")
            self._duckdb.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM {reader}('{path}')"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load {path.name} as table '{table_name}': {e}") from e

    def _reload_existing_files(self) -> None:
        """Re-register all files in the upload dir on connector startup."""
        for f in sorted(self._upload_dir.iterdir()):
            if f.suffix.lower() in _SUPPORTED_EXTENSIONS and f.is_file():
                table_name = f.stem.lower().replace("-", "_").replace(" ", "_")
                try:
                    self._register_file(f, table_name)
                except Exception:
                    pass  # don't break startup if a file is unreadable

    def list_files(self) -> list[dict]:
        """Return metadata for all ingested files."""
        result = []
        for f in sorted(self._upload_dir.iterdir()):
            if f.suffix.lower() in _SUPPORTED_EXTENSIONS and f.is_file():
                result.append({
                    "filename": f.name,
                    "table_name": f.stem.lower().replace("-", "_").replace(" ", "_"),
                    "size_bytes": f.stat().st_size,
                    "extension": f.suffix.lower(),
                })
        return result

    def delete_file(self, filename: str) -> None:
        path = self._upload_dir / filename
        table_name = path.stem.lower().replace("-", "_").replace(" ", "_")
        if path.exists():
            path.unlink()
        try:
            self._duckdb.execute(f"DROP TABLE IF EXISTS {table_name}")
        except Exception:
            pass

    # ── DatabaseConnection ABC ─────────────────────────────────────────────────

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
        return "\n".join(lines) or "(no files uploaded yet)"

    def test(self) -> tuple[bool, str]:
        files = self.list_files()
        if not files:
            return True, "Local upload connector ready (no files uploaded yet)"
        table_names = [f["table_name"] for f in files]
        return True, f"Local upload: {len(files)} file(s) loaded as tables: {', '.join(table_names)}"

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass
