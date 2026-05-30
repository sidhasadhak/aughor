"""Canvas data models."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class CanvasScope(BaseModel):
    """One connection + optional table filter within a Canvas.

    tables: empty list means "full schema" — all tables in the connection.
    is_full_schema is a convenience flag that is True when tables is empty.
    """
    connection_id: str
    schema_name: Optional[str] = None          # override the connection's default schema
    tables: List[str] = Field(default_factory=list)  # empty = all tables

    @property
    def is_full_schema(self) -> bool:
        return not self.tables


class Canvas(BaseModel):
    """Named workspace that scopes investigations to a subset of tables.

    Sprint 21 enforces exactly one scope (len(scopes) == 1).
    The model already supports N for future federation (M14d / Sprint 28).
    """
    id: str
    name: str
    description: str = ""
    scopes: List[CanvasScope] = Field(default_factory=list)
    is_legacy: bool = False   # True for auto-generated connection→Canvas migrations
    created_at: str = ""
    updated_at: str = ""

    @property
    def primary_connection_id(self) -> Optional[str]:
        """The connection_id of the first (and currently only) scope."""
        return self.scopes[0].connection_id if self.scopes else None

    @property
    def table_filter(self) -> List[str]:
        """Tables selected in the first scope. Empty = full schema."""
        return self.scopes[0].tables if self.scopes else []
