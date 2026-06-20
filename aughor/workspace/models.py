"""Workspace data models."""
from __future__ import annotations

from typing import Any, Dict, List
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
    # Per-workspace overrides of the app-wide OrgSettings (a partial subset of its
    # fields). Merged by orgsettings.effective_settings() with precedence
    # workspace override > app default. Empty = inherit the app-level settings.
    settings_override: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
