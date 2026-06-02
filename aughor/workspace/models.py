"""Workspace data models."""
from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field


class Workspace(BaseModel):
    """A named grouping of DB connections — the top-level scope.

    A user may keep one Workspace with several connections (e.g. all of an
    e-commerce stack's databases) and another Workspace with a different set.
    Connections, Canvases and intelligence are all viewed through the lens of
    the currently-selected Workspace.

    `connection_ids` references entries in the connection registry; the
    Workspace itself owns no credentials.
    """
    id: str
    name: str
    description: str = ""
    connection_ids: List[str] = Field(default_factory=list)
    is_default: bool = False   # the auto-created catch-all workspace
    created_at: str = ""
    updated_at: str = ""
