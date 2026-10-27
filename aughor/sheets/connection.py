"""The sheets, as one connection — *Sheets* — that the rest of Aughor reads as it reads any table (Arc SH).

A DuckDB connection over the organisation's projection: a cursor of the one database the API process writes
(``projection.py``), so a chat answer, a Catalog browse or a dashboard reads exactly what the grid shows. The engine is
writable by construction — the API process writes the projection — so, as for the Workspace, the door's checks are the
read-only boundary for a person's or a model's statement, and every result's doors say so.

Never pooled: it is a cursor, cheap to take, and the projection it reads is the request's organisation's — a pooled one
would be handed to the next request whatever its organisation.
"""
from __future__ import annotations

from aughor.db.connection import DuckDBConnection


class SheetsConnection(DuckDBConnection):
    dialect = "duckdb"
    engine_read_only = False
    poolable = False

    def __init__(self, dsn: str = "sheets://", schema_name: str | None = None, connection_id: str = "sheets",
                 meta: dict | None = None):
        from aughor.sheets import files, projection
        self._path = files.projection_path()
        self._conn = projection.cursor()
        self._connection_id = connection_id or "sheets"
        self._schema_name = None
        self._ontology = None
        self.engine_read_only = False

    def make_reader(self) -> "SheetsConnection":
        return SheetsConnection(connection_id=self._connection_id)

    def ibis_connection(self):
        """None: the projection is open read-write in this process, and a second, read-only open of the file is
        refused by DuckDB."""
        return None

    def test(self) -> tuple[bool, str]:
        try:
            self._conn.execute("SELECT 1")
            return True, "Connected"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
