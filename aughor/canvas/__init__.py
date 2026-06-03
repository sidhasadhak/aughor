"""Canvas — named, scoped workspaces that group a connection + optional table selection.

A Canvas is the primary context unit for investigations, chat, and exploration.
Canvases are only ever created explicitly by the user — connections and schemas
never spawn one automatically.

Data model supports N scopes (multi-connection federation, M14d) but the API
enforces len(scopes) == 1 until federation ships in Sprint 28.
"""
from aughor.canvas.models import Canvas, CanvasScope
from aughor.canvas.store import (
    canvas_store,
    create_canvas,
    get_canvas,
    list_canvases,
    update_canvas,
    delete_canvas,
    resolve_connection_id,
    delete_legacy_canvases,
    migrate_connections_to_legacy_canvases,
)

__all__ = [
    "Canvas",
    "CanvasScope",
    "canvas_store",
    "create_canvas",
    "get_canvas",
    "list_canvases",
    "update_canvas",
    "delete_canvas",
    "resolve_connection_id",
    "delete_legacy_canvases",
    "migrate_connections_to_legacy_canvases",
]
