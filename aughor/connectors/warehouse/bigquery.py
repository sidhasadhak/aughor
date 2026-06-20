"""BigQuery connector for Aughor.

DSN format:  bigquery://project-id
Meta fields: {"dataset": "analytics", "credentials": "/path/to/sa.json"}

Auth priority:
  1. meta["credentials"] — path to service account JSON
  2. Application Default Credentials (gcloud auth, Workload Identity, etc.)

Optional dep:
  uv pip install 'google-cloud-bigquery>=3.0.0'
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

MAX_ROWS = 2000


class BigQueryConnection(Connector):
    connector_category = "warehouse"
    dialect = "bigquery"
    writes_native_sql = True  # execute() runs the LLM's SQL natively (no duckdb transpile)

    def __init__(
        self,
        dsn: str,
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self.dep_check("google.cloud.bigquery", "google-cloud-bigquery>=3.0.0")
        from google.cloud import bigquery
        from google.oauth2 import service_account

        meta = meta or {}
        # dsn is the project ID (possibly "bigquery://project" or just "project")
        self._project = dsn.removeprefix("bigquery://").strip("/") or dsn
        self._dataset = schema_name or meta.get("dataset") or ""
        self._connection_id = connection_id

        cred_path = meta.get("credentials")
        if cred_path:
            creds = service_account.Credentials.from_service_account_file(
                cred_path,
                scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
            )
            self._client = bigquery.Client(project=self._project, credentials=creds)
        else:
            # Relies on ADC — gcloud auth, env GOOGLE_APPLICATION_CREDENTIALS, Workload Identity
            self._client = bigquery.Client(project=self._project)

    # ── DatabaseConnection ABC ─────────────────────────────────────────────────

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        import time as _time
        from aughor.db.connection import _security_pre, _security_post

        sql = sql.strip().rstrip(";")
        if (blocked := _security_pre(self._connection_id, hypothesis_id, sql)):
            return blocked

        _t0 = _time.monotonic()
        try:
            from google.cloud import bigquery
            job_config = bigquery.QueryJobConfig(
                default_dataset=f"{self._project}.{self._dataset}" if self._dataset else None
            )
            job = self._client.query(sql, job_config=job_config)
            rows_it = job.result(max_results=MAX_ROWS)
            columns = [field.name for field in rows_it.schema]
            rows = [
                [str(v) if v is not None else "NULL" for v in row.values()]
                for row in rows_it
            ]
            result = QueryResult(
                hypothesis_id=hypothesis_id,
                sql=sql,
                columns=columns,
                rows=rows,
                row_count=len(rows),
            )
        except Exception as e:
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=[], rows=[], row_count=0, error=str(e),
            )

        elapsed_ms = (_time.monotonic() - _t0) * 1000
        return _security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        """Use BigQuery's native dry-run — validates SQL + estimates bytes, zero cost."""
        try:
            from google.cloud import bigquery
            job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
            self._client.query(sql.rstrip(";"), job_config=job_config)
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_schema(self) -> str:
        lines: list[str] = []
        try:
            if self._dataset:
                tables = list(self._client.list_tables(f"{self._project}.{self._dataset}"))
            else:
                from google.cloud import bigquery
                ds_list = list(self._client.list_datasets(self._project))
                tables = []
                for ds in ds_list[:10]:  # cap to avoid massive schemas
                    tables.extend(list(self._client.list_tables(ds.reference)))

            for tbl_ref in tables[:100]:
                tbl = self._client.get_table(tbl_ref)
                cols = ", ".join(
                    f"{f.name} {f.field_type}" for f in tbl.schema
                )
                lines.append(f"TABLE: {tbl_ref.table_id} ({tbl.num_rows} rows) [{cols}]")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines)

    def test(self) -> tuple[bool, str]:
        try:
            list(self._client.list_datasets(self._project, max_results=1))
            return True, f"Connected to BigQuery project '{self._project}'"
        except Exception as e:
            return False, str(e)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
