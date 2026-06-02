"""Workspace CRUD — the top-level scope that groups DB connections."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["workspace"])


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str = ""
    connection_ids: List[str] = []


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    connection_ids: Optional[List[str]] = None


@router.get("/workspaces")
def get_workspaces():
    from aughor.workspace.store import ensure_default_workspace, list_workspaces
    ensure_default_workspace()
    return [w.model_dump() for w in list_workspaces()]


@router.post("/workspaces", status_code=201)
def create_workspace_endpoint(req: CreateWorkspaceRequest):
    from aughor.workspace.store import create_workspace
    ws = create_workspace(
        name=req.name,
        connection_ids=req.connection_ids,
        description=req.description,
    )
    return ws.model_dump()


@router.get("/workspaces/{workspace_id}")
def get_workspace_endpoint(workspace_id: str):
    from aughor.workspace.store import get_workspace
    ws = get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws.model_dump()


@router.put("/workspaces/{workspace_id}")
def update_workspace_endpoint(workspace_id: str, req: UpdateWorkspaceRequest):
    from aughor.workspace.store import update_workspace
    ws = update_workspace(
        workspace_id,
        name=req.name,
        description=req.description,
        connection_ids=req.connection_ids,
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws.model_dump()


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace_endpoint(workspace_id: str):
    from aughor.workspace.store import delete_workspace
    if not delete_workspace(workspace_id):
        raise HTTPException(
            status_code=400,
            detail="Workspace not found or cannot be deleted (default workspace is protected)",
        )
