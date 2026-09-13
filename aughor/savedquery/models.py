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
    # SE-8C — how each `:name` parameter renders as a WIDGET (label, widget kind,
    # options, default). Opaque to the backend for the same reason `spec` is: the
    # editor owns its shape, the store round-trips it. A separate field, NOT part of
    # `spec`, because a non-empty spec is what routes a query to the visual builder —
    # parameter widgets on a SQL query must not change where it opens.
    param_defs: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
