"""Canvas CRUD, schema, history, suggestions, and recents."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.db.registry import BUILTIN_ID

router = APIRouter(tags=["canvas"])


class CreateCanvasRequest(BaseModel):
    name: str
    description: str = ""
    connection_id: str
    schema_name: Optional[str] = None
    tables: list[str] = []


class UpdateCanvasRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tables: Optional[list[str]] = None


@router.get("/canvases")
def get_canvases(include_legacy: bool = True):
    from aughor.canvas.store import list_canvases
    return [c.model_dump() for c in list_canvases(include_legacy=include_legacy)]


@router.post("/canvases", status_code=201)
def create_canvas_endpoint(req: CreateCanvasRequest):
    from aughor.canvas.models import CanvasScope
    from aughor.canvas.store import create_canvas
    scope = CanvasScope(connection_id=req.connection_id, schema_name=req.schema_name, tables=req.tables)
    canvas = create_canvas(name=req.name, scopes=[scope], description=req.description)
    try:
        from aughor.canvas.store import migrate_connections_to_legacy_canvases
        migrate_connections_to_legacy_canvases()
    except Exception:
        pass
    return canvas.model_dump()


@router.get("/canvases/{canvas_id}")
def get_canvas_endpoint(canvas_id: str):
    from aughor.canvas.store import get_canvas
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return canvas.model_dump()


@router.put("/canvases/{canvas_id}")
def update_canvas_endpoint(canvas_id: str, req: UpdateCanvasRequest):
    from aughor.canvas.store import get_canvas, update_canvas
    from aughor.canvas.models import CanvasScope
    existing = get_canvas(canvas_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Canvas not found")
    new_scopes = None
    if req.tables is not None and existing.scopes:
        old_scope = existing.scopes[0]
        new_scopes = [CanvasScope(connection_id=old_scope.connection_id, schema_name=old_scope.schema_name, tables=req.tables)]
    canvas = update_canvas(canvas_id, name=req.name, description=req.description, scopes=new_scopes)
    return canvas.model_dump()


@router.delete("/canvases/{canvas_id}", status_code=204)
def delete_canvas_endpoint(canvas_id: str):
    from aughor.canvas.store import delete_canvas
    if not delete_canvas(canvas_id):
        raise HTTPException(status_code=404, detail="Canvas not found")


@router.get("/canvases/{canvas_id}/schema")
def get_canvas_schema(canvas_id: str):
    from aughor.canvas.store import get_canvas
    from aughor.tools.schema import build_canvas_schema_context
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return {"canvas_id": canvas_id, "schema": build_canvas_schema_context(canvas)}


@router.get("/canvases/{canvas_id}/history")
def get_canvas_history(canvas_id: str, limit: int = 20):
    from aughor.canvas.store import get_canvas
    from aughor.db.history import list_investigations
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    conn_id = canvas.scopes[0].connection_id if canvas.scopes else None
    if not conn_id:
        return {"investigations": []}
    all_inv = list_investigations(limit=200)
    return {"investigations": [inv for inv in all_inv if inv.get("connection_id") == conn_id][:limit]}


@router.get("/canvases/{canvas_id}/suggestions")
def get_canvas_suggestions(canvas_id: str):
    from aughor.canvas.store import get_canvas
    from aughor.routers.system import get_suggestions
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    conn_id = canvas.scopes[0].connection_id if canvas.scopes else None
    if not conn_id:
        return {"suggestions": [], "cached": False}
    return get_suggestions(connection_id=conn_id)


@router.get("/canvases/{canvas_id}/recents")
def get_canvas_recents(canvas_id: str, limit: int = 10):
    from aughor.canvas.store import get_canvas
    from aughor.db.history import list_investigations
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    conn_id = canvas.scopes[0].connection_id if canvas.scopes else None
    if not conn_id:
        return {"recents": []}
    all_inv = list_investigations(limit=100)
    filtered = [inv for inv in all_inv if inv.get("connection_id") == conn_id][:limit]
    return {"recents": [{"question": inv["question"], "status": inv.get("status", "complete"), "created_at": inv.get("created_at", "")} for inv in filtered]}
