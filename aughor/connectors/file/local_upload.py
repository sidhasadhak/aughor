"""Local file upload connector — CSV, Parquet, Excel materialized into DuckDB.

No external dependencies — DuckDB handles all file formats natively.

DSN:   local://  (sentinel; storage is vended by the control plane, tenant-scoped)

Storage layout (tenant-pathed, schema-aware)::

    data/uploads/{org_id}/{connection_id}/
        main/                       # default schema
            sales.csv
            sales.csv.import.json   # {"table_name","schema","column_types"}
        finance/
            ledger.parquet

The {org_id} segment is resolved via aughor.platform.vending.vend_storage (§5.1);
this connector never joins the upload root directly.
            ledger.parquet.import.json

Each *schema* is a sub-directory; each data file becomes one table inside that
schema. A sidecar ``*.import.json`` records the chosen table name and any
per-column type overrides so the in-memory DuckDB can be rebuilt identically on
every request (the connector is constructed fresh per request and reloads from
disk).

Typical use::

    conn = LocalUploadConnection(dsn="local://", connection_id="workspace")
    info = conn.analyze_file(Path("/tmp/sales.csv"))      # preview + type hints
    conn.ingest_file(Path("/tmp/sales.csv"),
                     table_name="sales", schema="finance",
                     column_types={"id": "BIGINT", "ts": "TIMESTAMP"})
    conn.execute("inv1", "SELECT * FROM finance.sales LIMIT 10")
"""
from __future__ import annotations

import json
import logging
import re
import threading
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from aughor.connectors.base import Connector
from aughor.platform.contracts.execution import QueryResult
from aughor.platform.vending import STORAGE_ROOT, vend_storage

logger = logging.getLogger(__name__)

MAX_ROWS = 2000
# The managed-storage root; single source of truth lives in the vending seam.
# Paths are resolved per-connection via vend_storage() (tenant-scoped), not by
# joining this directly — kept as an alias for back-compat callers.
_UPLOAD_ROOT = STORAGE_ROOT
DEFAULT_SCHEMA = "main"

# A removed-seed tombstone: seed schemas/tables are re-materialized on every connector
# construction, so deleting one only sticks if we persist that it was removed and skip it on
# the next re-seed. Lives in the connection's upload dir alongside the user files.
_TOMBSTONE_FILE = "_removed_seeds.json"

# Serializes ATTACH/DETACH of the shared seed file. The connector is constructed
# fresh per request, so without this two concurrent requests race on the same
# samples.duckdb and one silently materializes nothing (missing-sample-data bug).
_SEED_LOCK = threading.Lock()

_SUPPORTED_EXTENSIONS = {
    ".csv":     "read_csv_auto",
    ".tsv":     "read_csv_auto",
    ".parquet": "read_parquet",
    ".parq":    "read_parquet",
    ".xlsx":    "read_excel",
    ".xls":     "read_excel",
    ".json":    "read_json_auto",
}

# Allow-list of cast targets we let the UI request (prevents SQL injection via
# the column_types map — values are interpolated into CREATE TABLE ... AS).
_ALLOWED_CAST_TYPES = {
    "BIGINT", "INTEGER", "DOUBLE", "DECIMAL", "VARCHAR",
    "BOOLEAN", "DATE", "TIMESTAMP", "TIME",
}

# Tighter types we probe for, in preference order, when a column is VARCHAR.
_PROBE_TYPES = ["BIGINT", "DOUBLE", "BOOLEAN", "DATE", "TIMESTAMP"]

# DuckDB scalar types we'll TRY_CAST to when reproducing a pinned schema contract
# on reload. Complex types (STRUCT/LIST/MAP/UNION) are deliberately excluded so a
# parquet/JSON column with a nested type passes through untouched — those formats
# carry their own schema and are already deterministic, and their type strings
# contain nested identifiers we must never interpolate into SQL.
_PINNABLE_BASE_TYPES = {
    "BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT",
    "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT", "UHUGEINT",
    "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC",
    "VARCHAR", "TEXT", "STRING", "CHAR", "BLOB",
    "BOOLEAN", "BOOL", "DATE", "TIME", "TIMESTAMP",
    "TIMESTAMP WITH TIME ZONE", "TIMESTAMP_S", "TIMESTAMP_MS",
    "TIMESTAMP_NS", "TIME WITH TIME ZONE", "UUID",
}

# A bare scalar type name plus an optional numeric precision — e.g. BIGINT,
# VARCHAR, DECIMAL(18,3), TIMESTAMP WITH TIME ZONE. Anything with quotes, letters
# inside parens, or nested parens (STRUCT(a INT), col[]) fails to match and is
# passed through rather than cast. Defence in depth: contract types come from
# DuckDB's own DESCRIBE, not user input, but interpolation stays allow-listed.
_PINNABLE_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9 ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?$")

_SIDECAR_SUFFIX = ".import.json"


def _is_pinnable_type(t: str) -> bool:
    """True when ``t`` is a DuckDB scalar type safe to reproduce via TRY_CAST on reload."""
    s = str(t).strip().upper()
    if not _PINNABLE_TYPE_RE.match(s):
        return False
    return s.split("(", 1)[0].strip() in _PINNABLE_BASE_TYPES


def _is_data_file(f: Path) -> bool:
    """A real uploaded data file — not a sidecar config, and a supported type."""
    return (
        f.is_file()
        and not f.name.endswith(_SIDECAR_SUFFIX)
        and f.suffix.lower() in _SUPPORTED_EXTENSIONS
    )


def _safe_ident(name: str, fallback: str = "table") -> str:
    """Sanitize an arbitrary string into a safe lowercase SQL identifier."""
    s = re.sub(r"[^0-9a-zA-Z_]", "_", (name or "").strip()).lower()
    s = re.sub(r"_+", "_", s).strip("_")
    if not s or not re.match(r"[a-z_]", s[0]):
        s = f"{fallback}_{s}" if s else fallback
    return s[:63]


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
        # Storage is vended by the control plane, never addressed directly (Invariant
        # #2): the capability resolves the tenant-scoped path {root}/{org}/{conn}/...
        self._cap = vend_storage(connection_id)
        self._upload_dir = self._cap.root
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        (self._upload_dir / DEFAULT_SCHEMA).mkdir(exist_ok=True)
        self._duckdb = duckdb.connect(":memory:")
        # Alias the handle under the name the DuckDB intelligence-build path expects
        # (build_intelligence / profilers read ._conn). LocalUpload is DuckDB-backed,
        # so this lets it reuse DuckDBConnection.build_intelligence (see below).
        self._conn = self._duckdb
        # Tables materialized from a read-only seed DB (e.g. the sample catalog).
        self._seed_path = (meta or {}).get("seed_duckdb")
        self._seeded: set[tuple[str, str]] = set()
        self._seed_failed: str | None = None  # reason string when seeding broke
        # Seed schemas/tables the user removed — loaded BEFORE seeding so re-seed skips them.
        self._removed_seed_schemas, self._removed_seed_tables = self._load_tombstone()
        self._seed_from_duckdb()        # sample/demo tables (read-only)
        self._reload_existing_files()   # user uploads (override seeds on clash)
        self._set_search_path()         # resolve bare names across user schemas

    def _set_search_path(self) -> None:
        """Point search_path so bare table names resolve to the RIGHT schema.

        Two regimes:
        • SCOPED (``schema_name`` set — a per-schema explorer pass or a schema-/
          canvas-scoped chat/ADA run): pin search_path to ONLY that schema so an
          unqualified ``FROM orders`` resolves to ``<schema>.orders`` and can NEVER
          silently leak to a sibling schema's same-named table (e.g. a missimi-scoped
          query reading ``netflix.orders``/``main.orders`` — the source of confidently
          wrong answers). Cross-schema reads must then be explicitly qualified.
        • UNSCOPED (no ``schema_name`` — the whole-Workspace surface): include every
          user schema so ``FROM order_items`` resolves to ``ecommerce.order_items``
          without fully-qualified names (the original runaway-error fix).

        Qualified names (``schema.table``) and system catalogs resolve regardless of
        search_path in both regimes."""
        try:
            if self._schema_name:
                # Scoped: bare names must stay inside the scope.
                self._duckdb.execute(f"SET search_path = '{self._schema_name}'")
                return
            schemas = [
                r[0] for r in self._duckdb.execute(
                    "SELECT DISTINCT schema_name FROM duckdb_tables() WHERE internal = false"
                ).fetchall()
            ]
            if "main" not in schemas:
                schemas.append("main")
            if schemas:
                self._duckdb.execute(f"SET search_path = '{','.join(schemas)}'")
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "search_path routing is best-effort; qualified names still resolve",
                     counter="workspace.search_path", conn_id=self._connection_id)

    def build_intelligence(self) -> str:
        """Build the heavy intelligence (profiles + ontology + enrichment) for this
        uploaded/seeded Workspace.

        `build_intelligence` lives only on DuckDBConnection, not the Connector base,
        so without this override the explorer's Phase-8 ontology gate raises
        AttributeError and domain intelligence is silently skipped for every
        file/connector-framework connection. LocalUpload is DuckDB-backed (._conn is
        our in-memory handle), so we reuse the DuckDB implementation directly."""
        from aughor.db.connection import DuckDBConnection
        return DuckDBConnection.build_intelligence(self)

    def _seed_from_duckdb(self) -> None:
        """Materialize tables from a read-only seed DuckDB file into this
        in-memory database, preserving their original schema names. Used to fold
        the sample catalog into the Workspace so demo data and uploads coexist."""
        if not self._seed_path:
            return
        p = Path(self._seed_path)
        if not p.exists():
            self._seed_failed = f"seed file not found: {p}"
            logger.error("Seed DB missing for %s: %s", self._connection_id, p)
            return
        failed: list[str] = []
        try:
            with _SEED_LOCK:
                self._duckdb.execute(f"ATTACH '{p.as_posix()}' AS _seed (READ_ONLY)")
                try:
                    tbls = self._duckdb.execute(
                        "SELECT schema_name, table_name FROM duckdb_tables() "
                        "WHERE database_name = '_seed' AND internal = false"
                    ).fetchall()
                    if not tbls:
                        self._seed_failed = "seed DB attached but contains no tables"
                        logger.error("Seed DB %s has no tables (conn=%s)", p, self._connection_id)
                    for schema, table in tbls:
                        # Honor the removed-seed tombstone — a schema (or single table) the
                        # user deleted must not come back on this re-seed.
                        if schema in self._removed_seed_schemas or f"{schema}.{table}" in self._removed_seed_tables:
                            continue
                        try:
                            self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                            self._duckdb.execute(
                                f'CREATE TABLE "{schema}"."{table}" AS '
                                f'SELECT * FROM _seed."{schema}"."{table}"'
                            )
                            self._seeded.add((schema, table))
                        except Exception as exc:
                            failed.append(f"{schema}.{table}")
                            logger.error(
                                "Seed materialization failed for %s.%s (conn=%s): %s",
                                schema, table, self._connection_id, exc,
                            )
                finally:
                    self._duckdb.execute("DETACH _seed")
            if failed:
                self._seed_failed = f"failed to materialize: {', '.join(failed)}"
            logger.debug(
                "Seed materialized %d tables (%d failed) for conn=%s",
                len(self._seeded), len(failed), self._connection_id,
            )
        except Exception as exc:
            # Demo data is best-effort; never block the Workspace on a seed error —
            # but the failure must be visible (it presents as "sample data missing").
            self._seed_failed = f"seed attach failed: {exc}"
            logger.error(
                "Seed DB attach failed for conn=%s (%s): %s",
                self._connection_id, p, exc, exc_info=True,
            )
            try:
                self._duckdb.execute("DETACH _seed")
            except Exception:
                pass

    # ── Schema directories ──────────────────────────────────────────────────────

    def _schema_dir(self, schema: str) -> Path:
        return self._upload_dir / _safe_ident(schema, DEFAULT_SCHEMA)

    def list_schemas(self) -> list[str]:
        names = {DEFAULT_SCHEMA}
        for d in self._upload_dir.iterdir():
            if d.is_dir():
                names.add(d.name)
        return sorted(names)

    # ── Removed-seed tombstone ──────────────────────────────────────────────────

    def _load_tombstone(self) -> tuple[set, set]:
        """``(removed_schemas, removed_tables)`` the user deleted from the seed catalog.
        Fail-open to empty (a corrupt/absent tombstone never blocks the connection)."""
        schemas: set = set()
        tables: set = set()
        try:
            p = self._upload_dir / _TOMBSTONE_FILE
            if p.exists():
                data = json.loads(p.read_text())
                schemas = set(data.get("schemas") or [])
                tables = set(data.get("tables") or [])
        except Exception as exc:
            logger.debug("removed-seed tombstone load failed for %s: %s", self._connection_id, exc)
        return schemas, tables

    def _save_tombstone(self) -> None:
        try:
            (self._upload_dir / _TOMBSTONE_FILE).write_text(json.dumps(
                {"schemas": sorted(self._removed_seed_schemas),
                 "tables": sorted(self._removed_seed_tables)}))
        except Exception as exc:
            logger.debug("removed-seed tombstone save failed for %s: %s", self._connection_id, exc)

    def restore_seeds(self, schema: str | None = None) -> None:
        """Clear the tombstone (all, or one schema) so the sample catalog re-materializes on
        the next connector construction. The UI's 'restore sample data' affordance."""
        if schema is None:
            self._removed_seed_schemas.clear()
            self._removed_seed_tables.clear()
        else:
            s = _safe_ident(schema, "schema")
            self._removed_seed_schemas.discard(s)
            self._removed_seed_tables = {t for t in self._removed_seed_tables if not t.startswith(f"{s}.")}
        self._save_tombstone()

    def create_schema(self, name: str) -> str:
        schema = _safe_ident(name, "schema")
        self._schema_dir(schema).mkdir(parents=True, exist_ok=True)
        try:
            self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        except Exception:
            pass
        # Re-creating a schema the user previously removed is an explicit "bring it back" —
        # lift its tombstone so the seed (if any) returns on the next construction.
        if schema in self._removed_seed_schemas:
            self.restore_seeds(schema)
        return schema

    def drop_schema(self, name: str) -> None:
        schema = _safe_ident(name, "schema")
        if schema == DEFAULT_SCHEMA:
            raise ValueError("The default 'main' schema cannot be deleted.")
        d = self._schema_dir(schema)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        try:
            self._duckdb.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        except Exception:
            pass
        # Tombstone EVERY dropped schema — seed-backed OR uploaded — not just seeds. The
        # tombstone, not the `rmtree` above, is what keeps a schema gone: `ignore_errors=True`
        # can leave files behind and a restore-from-backup can re-create them, and
        # `_reload_existing_files` now honors the tombstone where a raw filesystem scan would
        # resurrect them (this closes the upload-resurrection gap, not just the seed one).
        self._removed_seed_schemas.add(schema)
        # A schema tombstone subsumes any table tombstones under it — drop the now-redundant ones.
        self._removed_seed_tables = {t for t in self._removed_seed_tables
                                     if not t.startswith(f"{schema}.")}
        self._save_tombstone()

    # ── Analyze (no persistence) ────────────────────────────────────────────────

    def analyze_file(self, file_path: Path, sample_rows: int = 20) -> dict:
        """Inspect a file and return inferred columns, a sample preview, a row
        count, and type-mismatch suggestions — without ingesting anything."""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. Supported: {sorted(_SUPPORTED_EXTENSIONS)}"
            )
        reader = _SUPPORTED_EXTENSIONS[ext]
        src = f"{reader}('{file_path.as_posix()}')"

        con = duckdb.connect(":memory:")
        try:
            desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
            columns: list[dict] = []
            for row in desc:
                name, dtype = row[0], str(row[1])
                suggested = None
                if dtype.upper().startswith("VARCHAR"):
                    suggested = self._suggest_type(con, src, name)
                columns.append({
                    "name": name,
                    "detected_type": dtype,
                    "suggested_type": suggested,
                })

            prev = con.execute(f"SELECT * FROM {src} LIMIT {int(sample_rows)}").fetchall()
            pcols = [d[0] for d in con.description] if con.description else []
            rows = [
                [None if v is None else str(v) for v in r]
                for r in prev
            ]
            try:
                total = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
            except Exception:
                total = len(rows)
        finally:
            con.close()

        return {
            "columns": columns,
            "preview": {"columns": pcols, "rows": rows},
            "row_count": total,
            "suggested_table_name": _safe_ident(file_path.stem),
        }

    @staticmethod
    def _suggest_type(con, src: str, col: str) -> str | None:
        """Return a tighter type if ≥95% of non-empty values cast cleanly."""
        c = col.replace('"', '""')
        probes = ", ".join(
            f'count(*) FILTER (WHERE try_cast("{c}" AS {t}) IS NOT NULL) AS p{i}'
            for i, t in enumerate(_PROBE_TYPES)
        )
        q = (
            f'SELECT count(*) FILTER (WHERE "{c}" IS NOT NULL '
            f"AND trim(CAST(\"{c}\" AS VARCHAR)) <> '') AS nn, {probes} FROM {src}"
        )
        try:
            res = con.execute(q).fetchone()
        except Exception:
            return None
        nn = res[0] or 0
        if nn == 0:
            return None
        threshold = 0.95 * nn
        for i, t in enumerate(_PROBE_TYPES):
            if (res[i + 1] or 0) >= threshold:
                # DOUBLE that's fully integer-castable is reported as BIGINT first
                return t
        return None

    # ── File ingestion ─────────────────────────────────────────────────────────

    def ingest_file(
        self,
        file_path: Path,
        table_name: str | None = None,
        schema: str = DEFAULT_SCHEMA,
        column_types: dict | None = None,
    ) -> str:
        """Copy a file into the given schema dir and register it as a DuckDB
        table, applying any per-column type overrides. Returns the table name."""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {ext}. Supported: {sorted(_SUPPORTED_EXTENSIONS)}"
            )

        schema = _safe_ident(schema, DEFAULT_SCHEMA)
        sdir = self._schema_dir(schema)
        sdir.mkdir(parents=True, exist_ok=True)

        dest = sdir / file_path.name
        if file_path.resolve() != dest.resolve():
            shutil.copy2(file_path, dest)

        table_name = _safe_ident(table_name or file_path.stem)
        clean_types = self._clean_types(column_types)

        # Materialize the table first (applying any user overrides), THEN pin the
        # result: DESCRIBE the created table to capture the full effective
        # {column: type} contract — Databricks' schemaHints analog. On reload we
        # reproduce these exact types instead of re-sniffing the file, which can
        # drift across DuckDB versions / sampling and silently re-type a column.
        self._register_file(dest, table_name, schema, clean_types)
        contract = self._describe_contract(schema, table_name)

        # Persist the import config + the pinned contract + provenance, so reload
        # is deterministic and the table's origin is inspectable (surfaced by
        # list_files → the ontology / Hub).
        (sdir / f"{file_path.name}{_SIDECAR_SUFFIX}").write_text(
            json.dumps({
                "table_name": table_name,
                "schema": schema,
                "column_types": clean_types,
                "schema_contract": contract,
                "source_file": file_path.name,
                "format": ext.lstrip("."),
                "created_by": "upload",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, indent=2)
        )
        # Ingesting is an explicit "bring it back" — lift any tombstone on this schema/table
        # so `_reload_existing_files` (which now honors tombstones) re-materializes it on the
        # next construction. Without this, a re-upload after a delete would vanish on restart.
        key = f"{schema}.{table_name}"
        if schema in self._removed_seed_schemas or key in self._removed_seed_tables:
            self._removed_seed_schemas.discard(schema)
            self._removed_seed_tables.discard(key)
            self._save_tombstone()
        return table_name

    def _describe_contract(self, schema: str, table_name: str) -> dict:
        """The effective ``{column: duckdb_type}`` of a just-created table — the
        pinned schema contract. Best-effort: returns ``{}`` on any failure, in
        which case reload falls back to re-sniffing (today's behavior)."""
        try:
            desc = self._duckdb.execute(
                f'DESCRIBE "{schema}"."{table_name}"').fetchall()
            return {str(r[0]): str(r[1]) for r in desc}
        except Exception:
            return {}

    @staticmethod
    def _clean_types(column_types: dict | None) -> dict:
        if not column_types:
            return {}
        out = {}
        for col, t in column_types.items():
            tu = str(t).upper().strip()
            if tu in _ALLOWED_CAST_TYPES:
                out[col] = tu
        return out

    def _register_file(
        self,
        path: Path,
        table_name: str,
        schema: str = DEFAULT_SCHEMA,
        column_types: dict | None = None,
        schema_contract: dict | None = None,
    ) -> None:
        ext = path.suffix.lower()
        reader = _SUPPORTED_EXTENSIONS.get(ext, "read_csv_auto")
        src = f"{reader}('{path.as_posix()}')"
        select_sql = self._build_select(src, column_types, schema_contract)
        fq = f'"{schema}"."{table_name}"'
        try:
            self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            self._duckdb.execute(f"DROP TABLE IF EXISTS {fq}")
            self._duckdb.execute(f"CREATE TABLE {fq} AS {select_sql}")
        except Exception as e:
            raise RuntimeError(
                f"Failed to load {path.name} as table '{schema}.{table_name}': {e}"
            ) from e

    def _build_select(
        self,
        src: str,
        column_types: dict | None = None,
        schema_contract: dict | None = None,
    ) -> str:
        """Build the SELECT that materializes a file into a table.

        Two regimes, chosen by which map is supplied:
        • ``schema_contract`` (reload): TRY_CAST every column whose pinned type is a
          safe scalar back to that exact type — reproduces the ingest-time schema
          deterministically, immune to ``read_*_auto`` re-sniffing drift. Columns
          with a complex/non-scalar pinned type pass through unchanged.
        • ``column_types`` (ingest): TRY_CAST only the user-overridden columns; the
          rest keep the reader's freshly-inferred type. (Original behavior.)
        """
        strict = bool(schema_contract)
        pin = schema_contract if strict else (column_types or {})
        if not pin:
            return f"SELECT * FROM {src}"
        con = self._duckdb
        try:
            desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
            cols = [r[0] for r in desc]
        except Exception:
            return f"SELECT * FROM {src}"
        parts = []
        for name in cols:
            esc = name.replace('"', '""')
            t = pin.get(name)
            cast_to = None
            if t:
                if strict:
                    cast_to = str(t) if _is_pinnable_type(t) else None
                elif str(t).upper() in _ALLOWED_CAST_TYPES:
                    cast_to = str(t).upper()
            if cast_to:
                parts.append(f'TRY_CAST("{esc}" AS {cast_to}) AS "{esc}"')
            else:
                parts.append(f'"{esc}"')
        return f"SELECT {', '.join(parts)} FROM {src}"

    def _reload_existing_files(self) -> None:
        """Re-register every file under every schema dir on startup — EXCEPT anything the
        user tombstoned. Without this skip a deleted schema/table whose backing file survived
        the delete silently re-materializes here: `drop_schema` uses `rmtree(ignore_errors=
        True)` (a lock / permission / disk-full leaves files behind), and a restore-from-backup
        re-creates them outright. The tombstone — not the file's mere presence — is the
        authority on what the user removed."""
        for sdir in sorted(self._upload_dir.iterdir()):
            if not sdir.is_dir():
                continue
            schema = sdir.name
            if schema in self._removed_seed_schemas:
                continue  # user deleted this schema — do not resurrect surviving files
            try:
                self._duckdb.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            except Exception:
                pass
            for f in sorted(sdir.iterdir()):
                if not _is_data_file(f):
                    continue
                cfg = self._read_sidecar(f)
                table_name = cfg.get("table_name") or _safe_ident(f.stem)
                if f"{schema}.{table_name}" in self._removed_seed_tables:
                    continue  # user deleted this table — do not resurrect a surviving file
                column_types = cfg.get("column_types") or {}
                # Prefer the pinned full contract (deterministic reload); old
                # sidecars without one fall back to overrides-only re-sniffing.
                schema_contract = cfg.get("schema_contract") or None
                try:
                    self._register_file(f, table_name, schema, column_types,
                                        schema_contract=schema_contract)
                except Exception:
                    pass  # never break startup on one bad file

    @staticmethod
    def _read_sidecar(data_file: Path) -> dict:
        sc = data_file.with_name(f"{data_file.name}{_SIDECAR_SUFFIX}")
        if sc.exists():
            try:
                return json.loads(sc.read_text())
            except Exception:
                return {}
        return {}

    def list_files(self) -> list[dict]:
        """Metadata for all ingested files across schemas."""
        result = []
        for sdir in sorted(self._upload_dir.iterdir()):
            if not sdir.is_dir():
                continue
            schema = sdir.name
            for f in sorted(sdir.iterdir()):
                if not _is_data_file(f):
                    continue
                cfg = self._read_sidecar(f)
                result.append({
                    "filename": f.name,
                    "table_name": cfg.get("table_name") or _safe_ident(f.stem),
                    "schema": schema,
                    "size_bytes": f.stat().st_size,
                    "extension": f.suffix.lower(),
                    "column_types": cfg.get("column_types") or {},
                    "schema_contract": cfg.get("schema_contract") or {},
                    "created_by": cfg.get("created_by"),
                    "created_at": cfg.get("created_at"),
                    "source_file": cfg.get("source_file"),
                })
        return result

    def delete_table(self, table: str, schema: str = DEFAULT_SCHEMA) -> None:
        """Remove a single table: drop it from DuckDB and delete its backing file(s).
        Matches by the table's resolved name (sidecar table_name, else the file stem)."""
        schema = _safe_ident(schema, DEFAULT_SCHEMA)
        tbl = _safe_ident(table, "table")
        sdir = self._schema_dir(schema)
        if sdir.exists():
            for f in list(sdir.iterdir()):
                if not _is_data_file(f):
                    continue
                cfg = self._read_sidecar(f)
                tname = cfg.get("table_name") or _safe_ident(f.stem)
                if tname == tbl:
                    if f.exists():
                        f.unlink()
                    sc = f.with_name(f"{f.name}{_SIDECAR_SUFFIX}")
                    if sc.exists():
                        sc.unlink()
        try:
            self._duckdb.execute(f'DROP TABLE IF EXISTS "{schema}"."{tbl}"')
        except Exception:
            pass
        # Tombstone the table — seed-backed OR uploaded — so a surviving backing file (or a
        # re-materialized seed) is not silently re-registered on the next construction.
        self._removed_seed_tables.add(f"{schema}.{tbl}")
        self._save_tombstone()

    def delete_file(self, filename: str, schema: str = DEFAULT_SCHEMA) -> None:
        schema = _safe_ident(schema, DEFAULT_SCHEMA)
        sdir = self._schema_dir(schema)
        path = sdir / Path(filename).name
        cfg = self._read_sidecar(path)
        table_name = cfg.get("table_name") or _safe_ident(path.stem)
        if path.exists():
            path.unlink()
        sc = path.with_name(f"{path.name}{_SIDECAR_SUFFIX}")
        if sc.exists():
            sc.unlink()
        try:
            self._duckdb.execute(f'DROP TABLE IF EXISTS "{schema}"."{table_name}"')
        except Exception:
            pass
        # Tombstone the table so a surviving copy of this file isn't re-registered on reload
        # (delete_file previously wrote NO tombstone at all — its sole protection against
        # resurrection was the unlink having succeeded).
        self._removed_seed_tables.add(f"{schema}.{table_name}")
        self._save_tombstone()

    # ── DatabaseConnection ABC ─────────────────────────────────────────────────

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

    def make_reader(self) -> "LocalUploadConnection":
        """Return a fresh clone safe for use in a parallel thread."""
        clone = LocalUploadConnection.__new__(LocalUploadConnection)
        clone._connection_id = self._connection_id
        clone._schema_name = self._schema_name
        clone._upload_dir = self._upload_dir
        clone._duckdb = duckdb.connect(":memory:")
        clone._seed_path = self._seed_path
        clone._seeded = set()
        # Carry the seed tombstones onto the clone BEFORE seeding — `_seed_from_duckdb` reads them to
        # skip user-removed seed schemas/tables. `make_reader` bypasses `__init__` (which normally
        # sets these via `_load_tombstone`), so without this the clone raised AttributeError on every
        # seed attach (fail-open, but log-spamming — and it dropped the tombstone filter). Copy as new
        # sets so the clone honours the same removals without sharing the parent's mutable state.
        clone._removed_seed_schemas = set(self._removed_seed_schemas)
        clone._removed_seed_tables = set(self._removed_seed_tables)
        clone._seed_from_duckdb()
        clone._reload_existing_files()
        clone._set_search_path()
        return clone

    def dry_run(self, sql: str) -> tuple[bool, str]:
        try:
            self._duckdb.execute(f"EXPLAIN {sql.rstrip(chr(59))}")
            return True, ""
        except Exception as e:
            return False, str(e)

    def raw_execute(self, sql: str) -> tuple[list[str], list, list[str]]:
        """Execute a raw SQL query bypassing validation and security checks.
        Returns (column_names, rows, types)."""
        self._duckdb.execute(sql)
        rows = self._duckdb.fetchall()
        desc = self._duckdb.description or []
        columns = [d[0] for d in desc]
        types = [str(d[1]) for d in desc]
        return columns, rows, types

    def get_schema(self) -> str:
        parts: list[str] = []
        try:
            # Respect schema_name filter if set; otherwise list all non-system schemas.
            if self._schema_name:
                self._duckdb.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema = ? AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name",
                    [self._schema_name],
                )
            else:
                self._duckdb.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'temp') "
                    "AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name"
                )
            schema_table_rows = self._duckdb.fetchall()
            schemas_present = {s for s, _ in schema_table_rows}
            multi_schema = len(schemas_present) > 1
            for tschema, tname in schema_table_rows:
                try:
                    count = self._duckdb.execute(
                        f'SELECT COUNT(*) FROM "{tschema}"."{tname}"'
                    ).fetchone()[0]
                except Exception:
                    count = "?"
                # Emit schema-qualified names when there are multiple schemas or
                # the table lives outside the default schema so the LLM always
                # references the correct table.
                display_name = f"{tschema}.{tname}" if (multi_schema or tschema != DEFAULT_SCHEMA) else tname
                parts.append(f"TABLE: {display_name}  ({count:,} rows)")
                try:
                    cols = self._duckdb.execute(
                        f'DESCRIBE "{tschema}"."{tname}"'
                    ).fetchall()
                    from aughor.db.type_overrides import get_table_overrides
                    _overrides = get_table_overrides(self._connection_id or "", tname)
                    for col in cols:
                        col_name, col_type = col[0], col[1]
                        if col_name in _overrides:
                            col_type = _overrides[col_name]
                        parts.append(f"  {col_name}  {col_type}")
                except Exception:
                    parts.append("  # column info unavailable")
        except Exception as e:
            parts.append(f"# Schema introspection failed: {e}")
        return "\n".join(parts) or "(no files uploaded yet)"

    def test(self) -> tuple[bool, str]:
        files = self.list_files()
        if not files:
            return True, "Local upload connector ready (no files uploaded yet)"
        names = [
            f["table_name"] if f["schema"] == DEFAULT_SCHEMA
            else f"{f['schema']}.{f['table_name']}"
            for f in files
        ]
        return True, f"Local upload: {len(files)} file(s) loaded as tables: {', '.join(names)}"

    def close(self) -> None:
        try:
            self._duckdb.close()
        except Exception:
            pass
