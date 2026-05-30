"""FederatedConnection — cross-source SQL in a single DuckDB namespace.

Aggregates multiple registered connections into one queryable surface.
Tables from each member are exposed as `{namespace}__{table}` views so the
LLM can write cross-source JOINs without knowing the physical location of data.

Attachment strategies (in priority order):
  Postgres      → DuckDB ATTACH ... (TYPE postgres)   — live, reads directly from PG
  DuckDB file   → DuckDB ATTACH ...                   — live, reads directly from file
  Other (S3,
   LocalUpload,
   API mirror)  → Arrow materialise-and-register      — copies data at init time

Usage:
    POST /connections/federate { "name": "...", "connection_ids": ["id1", "id2"] }

    → creates conn_type="federated", meta={"connection_ids": [...]}
    → tables accessible as:  id1__orders, id2__customers, etc.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import TYPE_CHECKING

import duckdb

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)
MAX_ROWS         = 2_000
MATERIALIZE_CAP  = 500_000   # max rows pulled into federation DuckDB for non-native connectors


class FederatedConnection(Connector):
    """Unified DuckDB namespace across multiple heterogeneous connections."""

    connector_category = "warehouse"
    dialect            = "duckdb"

    def __init__(
        self,
        dsn: str = "",
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        meta = meta or {}
        self._connection_id = connection_id
        self._member_ids: list[str] = meta.get("connection_ids", [])
        self._duckdb = duckdb.connect(":memory:")

        # namespace → {"conn_id": …, "source_type": …, "tables": […]}
        self._namespaces: dict[str, dict] = {}

        for cid in self._member_ids:
            try:
                self._attach_member(cid)
            except Exception as exc:
                logger.warning("Federation: failed to attach %s — %s", cid, exc)

    # ── Attachment logic ───────────────────────────────────────────────────────

    def _attach_member(self, conn_id: str) -> None:
        from aughor.db.connection import open_connection_for
        from aughor.db.registry import get_dsn, get_meta

        conn = open_connection_for(conn_id)
        ns = conn_id            # namespace = connection_id (8-char slug)
        conn_type_name = type(conn).__name__
        meta = get_meta(conn_id)
        schema = meta.get("schema_name")

        attached_tables: list[str] = []

        # ── Postgres: ATTACH via postgres_scanner ─────────────────────────────
        if conn_type_name == "PostgresConnection":
            try:
                _, dsn = get_dsn(conn_id)
                try:
                    self._duckdb.execute("INSTALL postgres; LOAD postgres;")
                except Exception:
                    pass
                self._duckdb.execute(
                    f"ATTACH '{dsn}' AS \"{ns}\" (TYPE postgres, READ_ONLY)"
                )
                pg_schema = schema or "public"
                raw = self._duckdb.execute(
                    f"SELECT table_name FROM information_schema.tables "
                    f"WHERE table_catalog = '{ns}' AND table_schema = '{pg_schema}'"
                ).fetchall()
                for (tname,) in raw:
                    view = f"{ns}__{tname}"
                    self._duckdb.execute(
                        f'CREATE OR REPLACE VIEW "{view}" AS '
                        f'SELECT * FROM "{ns}".{pg_schema}."{tname}"'
                    )
                    attached_tables.append(view)
                logger.info("Federation: attached Postgres %s (%d tables via ATTACH)", conn_id, len(attached_tables))
            except Exception as exc:
                logger.warning("Federation: Postgres ATTACH failed for %s, falling back to materialise: %s", conn_id, exc)
                attached_tables = self._materialise(conn, ns)

        # ── DuckDB file: ATTACH directly ──────────────────────────────────────
        elif conn_type_name == "DuckDBConnection":
            try:
                _, file_path = get_dsn(conn_id)
                self._duckdb.execute(f'ATTACH \'{file_path}\' AS "{ns}" (READ_ONLY)')
                dk_schema = schema or "main"
                raw = self._duckdb.execute(
                    f"SELECT table_name FROM \"{ns}\".information_schema.tables "
                    f"WHERE table_schema = '{dk_schema}'"
                ).fetchall()
                for (tname,) in raw:
                    view = f"{ns}__{tname}"
                    self._duckdb.execute(
                        f'CREATE OR REPLACE VIEW "{view}" AS '
                        f'SELECT * FROM "{ns}".{dk_schema}."{tname}"'
                    )
                    attached_tables.append(view)
                logger.info("Federation: attached DuckDB %s (%d tables)", conn_id, len(attached_tables))
            except Exception as exc:
                logger.warning("Federation: DuckDB ATTACH failed for %s: %s", conn_id, exc)
                attached_tables = self._materialise(conn, ns)

        # ── Everything else: materialise via Arrow ────────────────────────────
        else:
            attached_tables = self._materialise(conn, ns)

        self._namespaces[ns] = {
            "conn_id":     conn_id,
            "source_type": conn_type_name,
            "tables":      attached_tables,
        }

    def _materialise(self, conn: "DatabaseConnection", ns: str) -> list[str]:
        """Copy tables from an in-memory connector into federation DuckDB via Arrow."""
        inner = getattr(conn, "_duckdb", None)
        if inner is None:
            return []
        registered: list[str] = []
        try:
            tables = [r[0] for r in inner.execute("SHOW TABLES").fetchall()]
        except Exception:
            return []
        for tname in tables:
            try:
                arrow_tbl = inner.execute(
                    f"SELECT * FROM {tname} LIMIT {MATERIALIZE_CAP}"
                ).arrow()
                view_name = f"{ns}__{tname}"
                self._duckdb.register(view_name, arrow_tbl)
                registered.append(view_name)
            except Exception as exc:
                logger.debug("Federation materialise: skipped %s.%s — %s", ns, tname, exc)
        logger.info("Federation: materialised %s (%d tables via Arrow)", ns, len(registered))
        return registered

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
        except Exception as exc:
            result = QueryResult(
                hypothesis_id=hypothesis_id, sql=sql,
                columns=[], rows=[], row_count=0, error=str(exc),
            )
        elapsed_ms = (time.monotonic() - _t0) * 1000
        return _security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

    def get_schema(self) -> str:
        """Build a federated schema context showing all member namespaces."""
        parts: list[str] = [
            f"FEDERATED CONNECTION ({len(self._namespaces)} sources)",
            "=" * 60,
            "Tables are accessible as: {namespace}__{table_name}",
            "",
        ]
        for ns, info in self._namespaces.items():
            parts.append(f"Source: {info['conn_id']} [{info['source_type']}]")
            for view in sorted(info["tables"]):
                try:
                    cnt_row = self._duckdb.execute(
                        f'SELECT COUNT(*) FROM "{view}"'
                    ).fetchone()
                    cnt = f"{cnt_row[0]:,}" if cnt_row else "?"
                except Exception:
                    cnt = "?"
                # Get columns
                try:
                    self._duckdb.execute(f'SELECT * FROM "{view}" LIMIT 0')
                    cols = ", ".join(d[0] for d in self._duckdb.description) if self._duckdb.description else ""
                except Exception:
                    cols = ""
                parts.append(f"  TABLE: {view} ({cnt} rows)  [{cols}]")
            parts.append("")

        # Cross-source join hints (reuse existing fuzzy inference on combined schema)
        parts.append("QUERY NOTE: Use {namespace}__{table} syntax for all tables.")
        parts.append("JOIN across namespaces is fully supported.")
        return "\n".join(parts)

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            self._duckdb.execute(f"EXPLAIN {sql.rstrip(';')}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def test(self) -> tuple[bool, str]:
        member_count = len(self._namespaces)
        total_tables = sum(len(v["tables"]) for v in self._namespaces.values())
        if member_count == 0:
            return False, "No member connections could be attached"
        return True, (
            f"Federated: {member_count} sources, "
            f"{total_tables} tables in unified namespace"
        )

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass

    def federation_members(self) -> list[dict]:
        """Metadata about each attached member — for the API."""
        return [
            {
                "conn_id":     info["conn_id"],
                "source_type": info["source_type"],
                "namespace":   ns,
                "tables":      info["tables"],
                "table_count": len(info["tables"]),
            }
            for ns, info in self._namespaces.items()
        ]
