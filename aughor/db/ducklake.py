"""A version-aware DuckDB connection backed by a DuckLake catalog.

DuckLake (the DuckDB team's lakehouse format) keeps table data as immutable Parquet and
table *metadata* in a SQL catalog, so every write is an immutable, time-travellable
snapshot. Backing an Aughor connection with one makes snapshot-pinned receipts EXACT: a
finding gets a real ``dl:<catalog>:<id>`` data version (not just a fingerprint) and can be
reproduced ``AT (VERSION => n)`` — which is what lets re-validate *prove* a finding was
correct-as-computed vs mis-derived, instead of inferring it.

This is the connection + the time-travel. Wiring it into ingestion/registry so uploads
land in DuckLake (versioned by default) is the remaining follow-on; everything downstream
(``aughor/db/snapshot.py``, ``build_dossier``, ``revalidate_finding``) already consumes the
native token the moment a connection is DuckLake-backed.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from aughor.db.connection import DuckDBConnection, apply_lane_envelope


def _attach_ducklake(conn, catalog_path: str, alias: str, *, read_only: bool = False) -> None:
    conn.execute("INSTALL ducklake")
    conn.execute("LOAD ducklake")
    ro = " (READ_ONLY)" if read_only else ""
    conn.execute(f"ATTACH 'ducklake:{catalog_path}' AS {alias}{ro}")
    conn.execute(f"USE {alias}")


class DuckLakeConnection(DuckDBConnection):
    """A DuckDB connection whose storage is a DuckLake catalog (versioned). Inherits all of
    :class:`DuckDBConnection` (execute / get_schema / raw_execute / …); only the open + the
    parallel-reader open differ, because the catalog is ATTACHed rather than opened as a file.
    The DuckLake catalog is made the default database, so plain table names resolve to it and
    ``AT (VERSION => n)`` time-travel works on bare names."""

    dialect = "duckdb"
    CATALOG = "lake"

    def __init__(self, catalog_path: str | Path, schema_name: str | None = None,
                 connection_id: str = ""):
        self._path = Path(catalog_path)
        self._conn = duckdb.connect(":memory:")
        _attach_ducklake(self._conn, str(self._path), self.CATALOG)
        self._connection_id = connection_id
        self._schema_name = schema_name or None
        apply_lane_envelope(self._conn, connection_id)

    def make_reader(self) -> "DuckLakeConnection":
        """A fresh reader over the same catalog (READ_ONLY, so it never contends with the
        writer for the catalog's metadata lock)."""
        clone = DuckLakeConnection.__new__(DuckLakeConnection)
        clone._path = self._path
        clone._schema_name = self._schema_name
        clone._connection_id = self._connection_id
        clone._ontology = self._ontology
        clone._conn = duckdb.connect(":memory:")
        _attach_ducklake(clone._conn, str(self._path), self.CATALOG, read_only=True)
        apply_lane_envelope(clone._conn, clone._connection_id)
        return clone
