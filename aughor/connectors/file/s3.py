"""S3/R2/MinIO connector — Parquet and CSV files via DuckDB httpfs.

DuckDB's bundled `httpfs` extension handles S3 natively — no extra Python dep.
For MinIO or Cloudflare R2, set `endpoint` in meta.

DSN format:   s3://bucket/prefix
Meta fields:  {"region": "us-east-1", "key_id": "AKIA…", "secret": "…",
               "endpoint": "https://…"}  (endpoint optional for non-AWS)

Files discovered:  *.parquet, *.csv, *.json  under bucket/prefix/
Each file becomes a VIEW named after the file stem.

Note: httpfs is bundled with duckdb>=0.8 — no pip install needed.
"""
from __future__ import annotations

import re
import time
from pathlib import PurePosixPath
from urllib.parse import urlparse, parse_qs

import duckdb

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

MAX_ROWS = 2000

_VIEW_EXTS = {".parquet", ".parq", ".csv", ".tsv", ".json"}


def _parse_s3_dsn(dsn: str, meta: dict) -> dict:
    """Extract bucket, prefix, and auth params from DSN + meta."""
    parsed = urlparse(dsn)
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")
    qs = parse_qs(parsed.query)

    return {
        "bucket":   bucket,
        "prefix":   prefix,
        "region":   qs.get("region", [meta.get("region", "us-east-1")])[0],
        "key_id":   qs.get("key_id",  [meta.get("key_id", "")])[0],
        "secret":   qs.get("secret",  [meta.get("secret", "")])[0],
        "endpoint": qs.get("endpoint", [meta.get("endpoint", "")])[0],
    }


class S3Connection(Connector):
    connector_category = "file"
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
        self._params = _parse_s3_dsn(dsn, meta)
        self._duckdb = duckdb.connect(":memory:")
        self._setup_httpfs()
        self._views: list[str] = []
        self._discover_files()

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _setup_httpfs(self) -> None:
        """Install and load httpfs; configure S3 credentials."""
        p = self._params
        try:
            self._duckdb.execute("INSTALL httpfs; LOAD httpfs;")
        except Exception:
            pass  # already installed

        secret_sql_parts = [
            f"TYPE S3",
            f"REGION '{p['region']}'",
        ]
        if p["key_id"] and p["secret"]:
            secret_sql_parts += [
                f"KEY_ID '{p['key_id']}'",
                f"SECRET '{p['secret']}'",
            ]
        if p["endpoint"]:
            secret_sql_parts += [
                f"ENDPOINT '{p['endpoint']}'",
                "USE_SSL TRUE",
            ]

        try:
            self._duckdb.execute(
                f"CREATE OR REPLACE SECRET _aughor_s3 ({', '.join(secret_sql_parts)})"
            )
        except Exception:
            # Fallback for older DuckDB that doesn't support CREATE SECRET
            if p["key_id"]:
                self._duckdb.execute(f"SET s3_region='{p['region']}'")
                self._duckdb.execute(f"SET s3_access_key_id='{p['key_id']}'")
                self._duckdb.execute(f"SET s3_secret_access_key='{p['secret']}'")
                if p["endpoint"]:
                    self._duckdb.execute(f"SET s3_endpoint='{p['endpoint']}'")

    def _s3_glob(self, extension: str) -> str:
        p = self._params
        prefix = f"{p['prefix']}/" if p['prefix'] and not p['prefix'].endswith("/") else p['prefix']
        return f"s3://{p['bucket']}/{prefix}**/*{extension}"

    def _discover_files(self) -> None:
        """Create VIEWs for each discovered file type under the prefix."""
        self._views = []
        for ext, reader in [
            (".parquet", "read_parquet"),
            (".csv",     "read_csv_auto"),
            (".json",    "read_json_auto"),
        ]:
            glob_path = self._s3_glob(ext)
            view_name = f"s3_{ext.lstrip('.')}"
            try:
                self._duckdb.execute(
                    f"CREATE OR REPLACE VIEW {view_name} AS "
                    f"SELECT *, filename FROM {reader}('{glob_path}', filename=true)"
                )
                # Validate view resolves at least one file
                self._duckdb.execute(f"SELECT COUNT(*) FROM {view_name} LIMIT 1")
                self._views.append(view_name)
            except Exception:
                # No files of that type found — skip silently
                try:
                    self._duckdb.execute(f"DROP VIEW IF EXISTS {view_name}")
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
                "WHERE table_schema = 'main' "
                "ORDER BY table_name, ordinal_position"
            )
            rows = self._duckdb.fetchall()
            from collections import defaultdict
            table_cols: dict[str, list[str]] = defaultdict(list)
            for tname, col, dtype in rows:
                table_cols[tname].append(f"{col} {dtype}")
            for tname, cols in table_cols.items():
                p = self._params
                lines.append(
                    f"TABLE: {tname}  "
                    f"[source: s3://{p['bucket']}/{p['prefix']}]  "
                    f"[{', '.join(cols)}]"
                )
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines)

    def test(self) -> tuple[bool, str]:
        p = self._params
        try:
            if self._views:
                return True, f"S3 connected: s3://{p['bucket']}/{p['prefix']} ({len(self._views)} views)"
            return True, f"S3 credentials configured for s3://{p['bucket']}/{p['prefix']} (no files found yet)"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass
