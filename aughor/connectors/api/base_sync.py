"""RestApiSync — base class for all REST API connectors.

Pattern: sync REST API data → materialize into local DuckDB mirror → serve queries.
The rest of the Aughor pipeline (SQL generation, ontology, profiling, domain intel)
works completely unchanged — it just sees a DuckDB connection.

Subclasses implement:
  _objects()                    → list of object names to sync
  _fetch_page(obj, after, since) → (records: list[dict], next_cursor: str | None)

State is persisted in data/sync_state_{conn_id}.json so incremental syncs
survive server restarts.
"""
from __future__ import annotations

import json
import logging
import time
from abc import abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from aughor.connectors.base import Connector
from aughor.agent.state import QueryResult

logger = logging.getLogger(__name__)

_SYNC_ROOT  = Path("data/api_sync")
_STATE_ROOT = Path("data")
MAX_ROWS    = 2_000
FULL_SYNC_LOOKBACK_DAYS = 730   # 2 years of history on first sync


class RestApiSync(Connector):
    """Base for REST API connectors. Subclasses add _objects() + _fetch_page()."""

    connector_category = "api"
    dialect            = "duckdb"

    def __init__(
        self,
        dsn: str = "",
        schema_name: str | None = None,
        connection_id: str = "",
        meta: dict | None = None,
    ) -> None:
        self._connection_id = connection_id
        self._meta = meta or {}
        self._db_path = _SYNC_ROOT / f"{connection_id}.duckdb"
        self._state_path = _STATE_ROOT / f"sync_state_{connection_id}.json"
        _SYNC_ROOT.mkdir(parents=True, exist_ok=True)
        self._duckdb = duckdb.connect(str(self._db_path))

    # ── Sync state ─────────────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            if self._state_path.exists():
                return json.loads(self._state_path.read_text())
        except Exception:
            pass
        return {}

    def _save_state(self, state: dict) -> None:
        self._state_path.write_text(json.dumps(state, indent=2))

    # ── Subclass contract ──────────────────────────────────────────────────────

    @abstractmethod
    def _objects(self) -> list[str]:
        """Return the list of API object names to sync (e.g. ["charges", "customers"])."""
        ...

    @abstractmethod
    def _fetch_page(
        self,
        obj: str,
        after: str | None,
        since: datetime | None,
    ) -> tuple[list[dict], str | None]:
        """
        Fetch one page of records for `obj`.
        `after`  — pagination cursor (None for first page)
        `since`  — only return records modified after this datetime (None = all)
        Returns (records, next_cursor).  next_cursor is None when done.
        """
        ...

    def _flatten(self, record: dict, prefix: str = "") -> dict:
        """Flatten a nested dict → dot-separated keys (for DuckDB column names)."""
        flat: dict = {}
        for k, v in record.items():
            key = f"{prefix}{k}".replace(".", "_").replace("-", "_")
            if isinstance(v, dict):
                flat.update(self._flatten(v, prefix=f"{key}_"))
            elif isinstance(v, list):
                flat[key] = json.dumps(v)  # store lists as JSON string
            else:
                flat[key] = str(v) if v is not None else None
        return flat

    # ── Full / incremental sync ────────────────────────────────────────────────

    def sync_object(self, obj: str, since: datetime | None = None) -> int:
        """Sync one API object. Returns count of records upserted."""
        state   = self._load_state()
        cursor  = None
        records: list[dict] = []

        while True:
            page, next_cursor = self._fetch_page(obj, after=cursor, since=since)
            records.extend(page)
            if not next_cursor:
                break
            cursor = next_cursor

        if not records:
            return 0

        flat_records = [self._flatten(r) for r in records]

        # Ensure all keys are present in every record (pad missing with None)
        all_keys = sorted({k for r in flat_records for k in r})
        flat_records = [{k: r.get(k) for k in all_keys} for r in flat_records]

        table_name = obj.lower().replace("-", "_").replace(" ", "_")

        # Create or replace table
        existing = {r[0] for r in self._duckdb.execute("SHOW TABLES").fetchall()}
        if table_name in existing:
            # Incremental: upsert by ID if column exists
            tmp = f"_tmp_{table_name}"
            self._duckdb.register(tmp, flat_records)
            if "id" in all_keys:
                self._duckdb.execute(
                    f"DELETE FROM {table_name} "
                    f"WHERE id IN (SELECT id FROM {tmp})"
                )
                self._duckdb.execute(f"INSERT INTO {table_name} SELECT * FROM {tmp}")
            else:
                self._duckdb.execute(f"INSERT INTO {table_name} SELECT * FROM {tmp}")
            try:
                self._duckdb.execute(f"DROP VIEW IF EXISTS {tmp}")
            except Exception:
                pass
        else:
            self._duckdb.register("_new_data", flat_records)
            self._duckdb.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM _new_data"
            )

        # Update state
        state[obj] = {"last_sync": datetime.now(timezone.utc).isoformat(), "rows": len(records)}
        self._save_state(state)
        logger.info("API sync: %s.%s → %d records", self._connection_id, obj, len(records))
        return len(records)

    def sync_all(self, incremental: bool = True) -> dict[str, int]:
        """Sync all objects. Returns {object: row_count}."""
        state   = self._load_state()
        results = {}
        for obj in self._objects():
            since = None
            if incremental and obj in state:
                try:
                    since = datetime.fromisoformat(state[obj]["last_sync"])
                except Exception:
                    pass
            try:
                count = self.sync_object(obj, since=since)
                results[obj] = count
            except Exception as exc:
                logger.warning("API sync failed for %s.%s: %s", self._connection_id, obj, exc)
                results[obj] = -1
        return results

    def sync_status(self) -> dict:
        state = self._load_state()
        tables = {r[0] for r in self._duckdb.execute("SHOW TABLES").fetchall()}
        return {
            "connection_id": self._connection_id,
            "synced_objects": list(tables),
            "last_sync_per_object": state,
            "total_tables": len(tables),
        }

    # ── DatabaseConnection ABC ─────────────────────────────────────────────────

    def execute(self, hypothesis_id: str, sql: str) -> QueryResult:
        from aughor.db.connection import security_pre, security_post

        sql = sql.strip().rstrip(";")
        if (blocked := security_pre(self._connection_id, hypothesis_id, sql)):
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
        return security_post(self._connection_id, hypothesis_id, sql, result, elapsed_ms)

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
            table_cols: defaultdict[str, list[str]] = defaultdict(list)
            for tname, col, dtype in rows:
                table_cols[tname].append(f"{col} {dtype}")
            state = self._load_state()
            for tname, cols in table_cols.items():
                row_count = state.get(tname, {}).get("rows", "?")
                lines.append(f"TABLE: {tname} ({row_count} rows) [{', '.join(cols)}]")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines) or f"(no data synced yet — run POST /connections/{self._connection_id}/sync)"

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass
