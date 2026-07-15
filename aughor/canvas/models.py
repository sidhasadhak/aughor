"""Canvas data models."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class CanvasScope(BaseModel):
    """One connection + optional table filter within a Canvas.

    tables: empty list means "full schema" — all tables in the connection.
    is_full_schema is a convenience flag that is True when tables is empty.
    """
    connection_id: str
    schema_name: Optional[str] = None          # override the connection's default schema
    tables: List[str] = Field(default_factory=list)  # empty = all tables

    @model_validator(mode="after")
    def _adopt_single_owning_schema(self) -> "CanvasScope":
        """When a table-list scope names tables from exactly ONE schema but declares no
        schema, adopt that schema explicitly. This is the owning-schema derivation
        ``ExecutionScope.eff_schema`` already does at read time — but PERSISTED, so EVERY
        path that pins ``search_path`` (the overview tour, plus the crash-salvage / resume
        paths that skip the re-derivation and could otherwise leak a bare ``FROM orders`` to
        a sibling schema) sees the scope, not only the ones that re-derive it. A bare
        (unqualified) or multi-schema table list is genuinely unconstrained → left as-is.
        Fires on construction AND on load (``_row_to_canvas``), so existing canvases harden
        with no migration."""
        if not self.schema_name and self.tables:
            owners = {t.split(".")[0] for t in self.tables if "." in t}
            if len(owners) == 1:
                self.schema_name = next(iter(owners))
        return self

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


class CanvasArtifact(BaseModel):
    """Saved artifact from a Canvas conversation — query, report, or monitor seed."""
    id: str
    canvas_id: str
    kind: str  # "query" | "report" | "insight" | "monitor"
    title: str
    description: str = ""
    sql: str = ""
    question: str = ""
    created_at: str = ""
