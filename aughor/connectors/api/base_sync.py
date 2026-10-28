"""RestApiSync — base class for all REST API connectors.

Pattern: sync REST API data → materialize into local DuckDB mirror → serve queries.
The rest of the Aughor pipeline (SQL generation, ontology, profiling, domain intel)
works completely unchanged — it just sees a DuckDB connection.

Subclasses implement:
  _objects()                    → list of object names to sync
  _fetch_page(obj, after, since) → (records: list[dict], next_cursor: str | None)

State is persisted in data/sync_state_{conn_id}.json so incremental syncs
survive server restarts.

An incremental sync must leave the mirror as a full sync of the same data would
(Arc SV-3, Grist's reload oracle — tests/unit/test_api_sync_rebuild.py). One
thing it cannot see is a deletion at the source, of a record or of a field from
every record: it fetches only what changed, and a deleted record does not come
back to say so. Deletions are seen only by a full sync, which replaces the table.
"""
from __future__ import annotations

import json
import logging
from abc import abstractmethod
from datetime import datetime, timezone

import duckdb

from aughor.connectors.base import Connector
from aughor.db.doors import through_door
from aughor.control_plane.contracts.execution import QueryResult
from aughor.db.paths import state_dir
from aughor.db.quoting import quote_ident

logger = logging.getLogger(__name__)

# Through `state_dir()`, like every other per-connection generated store — so
# `AUGHOR_STATE_DIR` isolates it (both hermeticity lists already carry that env, so this
# needed no new one) and the IN-4 data home reaches it once `migrate-state` has run.
# These were `Path("data/api_sync")` / `Path("data")`: invisible to both isolation lists,
# and a migration would have moved every store EXCEPT the API sync state. Module constants
# on purpose — the house convention `db/paths.state_dir` documents, which conftest meets by
# setting the env before any app import.
_STATE_ROOT = state_dir()
_SYNC_ROOT  = _STATE_ROOT / "api_sync"
MAX_ROWS    = 2_000
FULL_SYNC_LOOKBACK_DAYS = 730   # 2 years of history on first sync
# The column an incremental sync replaces changed rows by. Matched without case, as DuckDB
# matches names — Salesforce spells it `Id`. An object without it is always synced in full.
KEY_COLUMN  = "id"


class RestApiSync(Connector):
    """Base for REST API connectors. Subclasses add _objects() + _fetch_page()."""

    connector_category = "api"
    # DE-1 — the mirror is a DuckDB file this connector writes on every sync; the door's checks are the read-only
    # boundary for a person's or a model's statement, said on every result's doors.
    engine_read_only = False

    def is_healthy(self) -> bool:
        """For the pool (DE-3d): the mirror's DuckDB answers; the API behind it is the next sync's affair."""
        return self._handle_answers(getattr(self, "_duckdb", None))
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
        """Sync one API object. Returns count of records written.

        `since` set → incremental: the records changed since then replace their rows by
        KEY_COLUMN. `since` None → full: every record is fetched and the table is replaced,
        which is the only way a deletion at the source reaches the mirror. An object with no
        KEY_COLUMN, or no table yet, has nothing to replace rows by — appended, every changed
        row would sit in the mirror twice — so its sync is a full one whatever `since` says.
        """
        state      = self._load_state()
        table_name = obj.lower().replace("-", "_").replace(" ", "_")
        table      = quote_ident(self, table_name)
        columns    = self._table_columns(table_name)
        if since is not None and KEY_COLUMN not in {c.lower() for c in columns}:
            since = None

        # The watermark is when the fetch STARTS. Stamped after it, a record changed while the
        # pages were being read sits before the next sync's `since` and is never fetched.
        started = datetime.now(timezone.utc)
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
        all_keys = sorted({k for r in flat_records for k in r})

        tmp = quote_ident(self, f"_tmp_{table_name}")
        self._load_records(tmp, all_keys, flat_records)
        try:
            if since is None:
                self._duckdb.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM {tmp}")
            else:
                # By NAME, over the union of columns. By position (`SELECT *`), a page that
                # lacks one field and adds another wrote its values into the wrong columns,
                # without an error. A field the table has not seen is added to it, nullable.
                known = {c.lower() for c in columns}
                for key in all_keys:
                    if key.lower() not in known:
                        self._duckdb.execute(f"ALTER TABLE {table} ADD COLUMN {quote_ident(self, key)} VARCHAR")
                id_col = quote_ident(self, KEY_COLUMN)
                self._duckdb.execute(f"DELETE FROM {table} WHERE {id_col} IN (SELECT {id_col} FROM {tmp})")
                self._duckdb.execute(f"INSERT INTO {table} BY NAME SELECT * FROM {tmp}")
        finally:
            self._duckdb.execute(f"DROP TABLE IF EXISTS {tmp}")

        # Update state
        state[obj] = {"last_sync": started.isoformat(), "rows": len(records)}
        self._save_state(state)
        logger.info("API sync: %s.%s → %d records", self._connection_id, obj, len(records))
        return len(records)

    def _table_columns(self, table_name: str) -> list[str]:
        """The mirror table's column names — none when it has not been synced yet."""
        return [r[0] for r in self._duckdb.execute(
            "SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE table_catalog = current_database() AND table_schema = 'main' AND table_name = ? "
            "ORDER BY ordinal_position", [table_name]).fetchall()]

    def _load_records(self, tmp: str, keys: list[str], flat_records: list[dict]) -> None:
        """The records as a temp table of named VARCHAR columns, a missing key read as NULL
        (`_flatten` makes every value a string or None). This was `register(tmp, records)`:
        DuckDB scans a DataFrame or an Arrow table, never a list of dicts, so every sync
        raised before it wrote a row."""
        self._duckdb.execute(
            f"CREATE OR REPLACE TEMP TABLE {tmp} ("
            + ", ".join(f"{quote_ident(self, k)} VARCHAR" for k in keys) + ")")
        self._duckdb.executemany(
            f"INSERT INTO {tmp} VALUES ({', '.join('?' for _ in keys)})",
            [[r.get(k) for k in keys] for r in flat_records])

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

    param_style = "duckdb"

    def _bind_execute(self, sql: str, params: dict):
        self._duckdb.execute(sql, params)
        cols = [d[0] for d in self._duckdb.description] if self._duckdb.description else []
        return cols, self._duckdb.fetchall()

    def execute(self, hypothesis_id: str, sql: str, *, sql_dialect: str | None = None, internal: bool = False) -> QueryResult:
        return through_door(self, sql, sql_dialect, lambda statement: self._duckdb_read(self._duckdb, hypothesis_id, statement, MAX_ROWS), internal=internal)

    def execute_bounded(self, hypothesis_id: str, sql: str, max_rows: int, *,
                        sql_dialect: str | None = None, internal: bool = False) -> QueryResult:
        """Up to ``max_rows`` rows — the cross-source reads and key measurements read past MAX_ROWS."""
        return through_door(self, sql, sql_dialect, lambda statement: self._duckdb_read(self._duckdb, hypothesis_id, statement, max(1, max_rows)), internal=internal)

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
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE table_schema = 'main' "
                "ORDER BY table_name, ordinal_position"
            )
            rows = self._duckdb.fetchall()
            from collections import OrderedDict
            table_cols: "OrderedDict[str, list[tuple[str, str]]]" = OrderedDict()
            for tname, col, dtype in rows:
                table_cols.setdefault(tname, []).append((col, dtype))
            state = self._load_state()
            # Canonical house format + A2 head samples (the bracketed one-liner hid
            # every column from the schema-linker and the data catalog).
            from aughor.db.schema_render import column_head_samples
            def _run(sql):
                self._duckdb.execute(sql)
                return self._duckdb.fetchall()
            for tname, cols in table_cols.items():
                row_count = state.get(tname, {}).get("rows", "?")
                lines.append(f"TABLE: {tname}  ({row_count} rows)")
                samples = column_head_samples(
                    _run, '"' + tname.replace('"', '""') + '"', [c for c, _ in cols])
                for col, dtype in cols:
                    lines.append(f"  {col}  {dtype}" + samples.get(col, ""))
                lines.append("")
        except Exception as e:
            lines.append(f"# Schema introspection failed: {e}")
        return "\n".join(lines) or f"(no data synced yet — run POST /connections/{self._connection_id}/sync)"

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass
