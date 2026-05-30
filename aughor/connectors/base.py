"""Connector ABC — extends DatabaseConnection with category + namespace.

All Sprint-25 connectors inherit from this instead of DatabaseConnection
directly. Existing DuckDB and Postgres connections remain in db/connection.py
and are handled by open_connection() as before; they gain `connector_category`
and `namespace` through monkey-patching at the registry layer.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Literal

from aughor.db.connection import DatabaseConnection


ConnectorCategory = Literal["warehouse", "file", "api", "knowledge"]


class Connector(DatabaseConnection):
    """Base class for all pluggable connectors.

    Sub-classes must:
      - implement the DatabaseConnection ABC (execute, get_schema, test, close)
      - set `connector_category` class variable
      - set `dialect` class variable (usually "duckdb" for file connectors)
    """

    connector_category: ConnectorCategory = "warehouse"

    @property
    def namespace(self) -> str:
        """Short prefix used in federated queries (14d). Defaults to connection_id."""
        return getattr(self, "_connection_id", "")

    # ── Helpers every connector gets for free ─────────────────────────────────

    @classmethod
    def dep_check(cls, package: str, install: str) -> None:
        """Raise ImportError with a helpful message if `package` is not installed."""
        try:
            __import__(package)
        except ImportError:
            raise ImportError(
                f"{cls.__name__} requires '{package}'. "
                f"Install it with:  uv pip install '{install}'"
            ) from None

    def ingest_file(self, file_path, table_name: str) -> None:  # type: ignore[override]
        """Optional: file connectors override this to accept uploaded files."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support file ingestion")
