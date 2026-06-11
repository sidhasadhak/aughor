"""Saved-query data model.

A SavedQuery is a named, connection-scoped Query Builder query. It stores both the executable
SQL *and* the visual builder ``spec`` (primary table, joins, dimensions, measures, filters,
order-by, limit) so loading one restores the full visual builder — not just a SQL dump. The
backend treats ``spec`` as opaque JSON: the frontend owns its shape, the store round-trips it.
"""
from __future__ import annotations

from typing import Any, Dict
from pydantic import BaseModel, Field


class SavedQuery(BaseModel):
    id: str
    connection_id: str
    name: str
    sql: str = ""
    spec: Dict[str, Any] = Field(default_factory=dict)  # opaque visual-builder state
    created_at: str = ""
    updated_at: str = ""
