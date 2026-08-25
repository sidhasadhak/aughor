"""Workspace CRUD — the top-level scope that groups DB connections."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["workspace"])


def _with_access(ws) -> dict:
    """The workspace plus ``accessible_connection_ids`` — membership ∪ explicit
    catalog grants, from the SAME resolver the router visibility gates use
    (:func:`aughor.metastore.sync.accessible_catalog_ids`).

    The field exists because the two halves of the gate had drifted apart in the
    UI: the backend served a granted catalog's rows while the connection picker
    filtered on ``connection_ids`` alone, so granting a catalog to a workspace
    widened the API and changed nothing on screen. Serving the effective set on
    the workspace itself gives every client one authority to read. Best-effort:
    a metastore failure degrades to membership, never to a 500 on the list."""
    d = ws.model_dump()
    try:
        from aughor.metastore.sync import accessible_catalog_ids
        ids = accessible_catalog_ids(ws.id)
        d["accessible_connection_ids"] = (
            sorted(ids) if ids is not None else list(ws.connection_ids or []))
    except Exception:
        d["accessible_connection_ids"] = list(ws.connection_ids or [])
    return d



class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str = ""
    connection_ids: List[str] = []
    settings_override: Dict[str, Any] = {}


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    connection_ids: Optional[List[str]] = None
    settings_override: Optional[Dict[str, Any]] = None


@router.get("/workspaces")
def get_workspaces():
    from aughor.workspace.store import ensure_default_workspace, list_workspaces
    ensure_default_workspace()
    return [_with_access(w) for w in list_workspaces()]


@router.post("/workspaces", status_code=201)
def create_workspace_endpoint(req: CreateWorkspaceRequest):
    from aughor.workspace.store import create_workspace
    ws = create_workspace(
        name=req.name,
        connection_ids=req.connection_ids,
        description=req.description,
        settings_override=req.settings_override,
    )
    return _with_access(ws)


@router.get("/workspaces/{workspace_id}")
def get_workspace_endpoint(workspace_id: str):
    from aughor.workspace.store import get_workspace
    ws = get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _with_access(ws)


@router.put("/workspaces/{workspace_id}")
def update_workspace_endpoint(workspace_id: str, req: UpdateWorkspaceRequest):
    from aughor.workspace.store import update_workspace
    ws = update_workspace(
        workspace_id,
        name=req.name,
        description=req.description,
        connection_ids=req.connection_ids,
        settings_override=req.settings_override,
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _with_access(ws)


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace_endpoint(workspace_id: str):
    from aughor.workspace.store import delete_workspace
    if not delete_workspace(workspace_id):
        raise HTTPException(
            status_code=400,
            detail="Workspace not found or cannot be deleted (default workspace is protected)",
        )
