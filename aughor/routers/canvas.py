"""Canvas CRUD, schema, history, suggestions, and recents."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel


def _canvas_owner_guard(request: Request) -> None:
    """Object-level authz (SEC-05): a by-id canvas route is reachable only by the
    org that owns the canvas's connection. No-op on routes without a ``canvas_id``
    (list/create/suggest-name) and in localhost mode (identity off)."""
    from aughor.security.authz import check_owner, get_principal
    canvas_id = request.path_params.get("canvas_id")
    if canvas_id:
        check_owner("canvas", canvas_id, get_principal(request))


router = APIRouter(tags=["canvas"], dependencies=[Depends(_canvas_owner_guard)])

# Per-Canvas instruction store (keyed by canvas_id). Kept separate from the
# connection-level instructions file so Canvases scoped to the same connection
# can carry distinct business rules.
_CANVAS_INSTRUCTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "canvas_instructions.json"


def _load_canvas_instructions() -> dict:
    if _CANVAS_INSTRUCTIONS_FILE.exists():
        try:
            return json.loads(_CANVAS_INSTRUCTIONS_FILE.read_text())
        except Exception:
            return {}
    return {}


class CreateCanvasRequest(BaseModel):
    # R10 — name is now optional (the Databricks generate_space_name:true analog):
    # an empty name is derived DETERMINISTICALLY from the scope server-side. The
    # richer LLM naming (/canvases/suggest-name) stays the optional client path.
    name: str = ""
    description: str = ""
    connection_id: str
    schema_name: Optional[str] = None
    tables: list[str] = []


class UpdateCanvasRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tables: Optional[list[str]] = None


class CanvasInstructionsRequest(BaseModel):
    text: str = ""


class SuggestNameRequest(BaseModel):
    connection_id: str
    tables: list[str] = []


@router.get("/canvases")
def get_canvases(include_legacy: bool = True, workspace_id: str | None = None):
    """List canvases. When `workspace_id` is given, only canvases whose connection
    belongs to that workspace are returned (data-path tenancy)."""
    from aughor.canvas.store import list_canvases
    from aughor.db.history import last_activity_by_canvas
    from aughor.metastore import accessible_catalog_ids
    from aughor.security.authz import org_visible_conn_ids
    allowed = accessible_catalog_ids(workspace_id)
    org_conns = org_visible_conn_ids()  # DATA-06: another org's canvases never appear
    activity = last_activity_by_canvas()
    out = []
    for c in list_canvases(include_legacy=include_legacy):
        conn = getattr(c, "primary_connection_id", None) or (c.scopes[0].connection_id if c.scopes else None)
        if allowed is not None and conn not in allowed:
            continue
        if org_conns is not None and conn not in org_conns:
            continue
        d = c.model_dump()
        # Most recent investigation/chat timestamp for this canvas (drives the
        # "latest investigation" sort and the recently-used section).
        d["last_activity"] = activity.get(c.id)
        out.append(d)
    return out


def _derive_canvas_name(scope) -> str:
    """R10 — deterministic auto-name from the scope (no model): the first scoped
    table, else the schema, else the generic fallback. 'flight_bookings' →
    'Flight Bookings Canvas'."""
    def _title(raw: str) -> str:
        return raw.split(".")[-1].replace("_", " ").strip().title()
    if scope.tables:
        return f"{_title(scope.tables[0])} Canvas"
    if scope.schema_name:
        return f"{_title(scope.schema_name)} Canvas"
    return "New Canvas"


@router.post("/canvases", status_code=201)
def create_canvas_endpoint(req: CreateCanvasRequest,
                           idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    from aughor.canvas.models import CanvasScope
    from aughor.canvas.store import create_canvas, get_canvas
    from aughor.util.idempotency import lookup, remember
    prior = lookup("canvas", idempotency_key)  # API-03: retry returns the same canvas
    if prior and (existing := get_canvas(prior)):
        return existing.model_dump()
    scope = CanvasScope(connection_id=req.connection_id, schema_name=req.schema_name, tables=req.tables)
    name = (req.name or "").strip() or _derive_canvas_name(scope)
    canvas = create_canvas(name=name, scopes=[scope], description=req.description)
    remember("canvas", idempotency_key, canvas.id)
    # R12 — canvas birth: kick off the "understand this data" job for the canvas
    # scope (eager intelligence → exploration handoff, one observable kernel job).
    # This endpoint is sync (threadpool), so bridge onto the captured app loop the
    # way scheduler ticks do; no loop (unit test / pre-startup) → skip quietly.
    # Flag-gated + best-effort: a birth hiccup never fails the create.
    from aughor.kernel.flags import flag_enabled
    if flag_enabled("birth.job"):
        try:
            from aughor.kernel.jobs import main_loop
            from . import _shared
            loop = main_loop()
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    _shared.spawn_birth(
                        scope.connection_id,
                        schema_name=scope.schema_name or None,
                        canvas_id=canvas.id,
                        tables_filter=scope.tables or None,
                    ),
                    loop,
                )
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "canvas birth kickoff is best-effort",
                     counter="birth.job", conn_id=scope.connection_id)
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
    # A canvas's explorer must not outlive it — before this, the task kept
    # running and the registry entry leaked on every create/delete cycle.
    try:
        from aughor.routers._shared import canvas_explorers, canvas_explorer_tasks
        from aughor.kernel.jobs import kernel
        ex = canvas_explorers.pop(canvas_id, None)
        if ex is not None:
            ex.stop()
        canvas_explorer_tasks.pop(canvas_id, None)
        kernel().cancel_scope(canvas_id=canvas_id)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Could not cancel explorer for deleted canvas %s", canvas_id, exc_info=True
        )


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
    all_inv = list_investigations(limit=400)
    # Scope strictly to THIS canvas (not the whole connection), and hide
    # report-less items — only completed investigations and chat sessions open.
    def _keep(inv: dict) -> bool:
        if inv.get("canvas_id") != canvas_id:
            return False
        return inv.get("kind") == "chat" or inv.get("status") == "complete"
    return {"investigations": [inv for inv in all_inv if _keep(inv)][:limit]}


@router.get("/canvases/{canvas_id}/suggestions")
async def get_canvas_suggestions(canvas_id: str):
    from aughor.canvas.store import get_canvas
    from aughor.routers.system import get_suggestions
    canvas = get_canvas(canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")
    conn_id = canvas.scopes[0].connection_id if canvas.scopes else None
    if not conn_id:
        return {"suggestions": [], "cached": False}
    # get_suggestions is async — must be awaited, else a coroutine object leaks
    # to the serializer ("'coroutine' object is not iterable" → HTTP 500).
    return await get_suggestions(connection_id=conn_id)


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


# ── Per-Canvas instructions ─────────────────────────────────────────────────

@router.get("/canvases/{canvas_id}/instructions")
def get_canvas_instructions(canvas_id: str):
    data = _load_canvas_instructions()
    return {"text": data.get(canvas_id, {}).get("text", "")}


@router.put("/canvases/{canvas_id}/instructions")
def put_canvas_instructions(canvas_id: str, req: CanvasInstructionsRequest):
    data = _load_canvas_instructions()
    data.setdefault(canvas_id, {})["text"] = req.text
    _CANVAS_INSTRUCTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CANVAS_INSTRUCTIONS_FILE.write_text(json.dumps(data, indent=2))
    return {"ok": True}


# ── LLM-suggested Canvas name + description ──────────────────────────────────

class _CanvasNameSuggestion(BaseModel):
    name: str
    description: str


@router.post("/canvases/suggest-name")
async def suggest_canvas_name(req: SuggestNameRequest):
    """Infer a short, human Canvas name + one-line description from the schema
    of the selected tables (or the whole connection when none are given)."""
    from aughor.db.connection import open_connection_for

    loop = asyncio.get_running_loop()
    try:
        db = open_connection_for(req.connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        schema_summary: str = await loop.run_in_executor(None, db.get_schema)
        db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    scope_note = (
        f"The Canvas is scoped to these tables: {', '.join(req.tables)}."
        if req.tables
        else "The Canvas includes all tables in the connection."
    )

    _system = (
        "You name data workspaces. Given a database schema and the tables a workspace "
        "is scoped to, produce a concise, human-friendly title (2-5 words, Title Case, "
        "no quotes) describing what the data is about, plus a one-sentence description "
        "(under 20 words). Base it strictly on the actual table and column names."
    )
    _user = f"Database schema:\n{schema_summary}\n\n{scope_note}\n\nReturn a name and description."

    def _llm_work() -> _CanvasNameSuggestion:
        from aughor.llm.provider import get_provider
        return get_provider("coder").complete(
            system=_system,
            user=_user,
            response_model=_CanvasNameSuggestion,
            temperature=0.3,
        )

    try:
        result = await loop.run_in_executor(None, _llm_work)
        return {"name": result.name.strip(), "description": result.description.strip()}
    except Exception:
        # Graceful fallback — never block Canvas creation on the LLM.
        fallback = req.tables[0] if req.tables else "New Canvas"
        return {"name": fallback, "description": ""}


# ── Canvas Artifacts ─────────────────────────────────────────────────────────

class CreateArtifactRequest(BaseModel):
    kind: str
    title: str
    description: str = ""
    sql: str = ""
    question: str = ""

@router.get("/canvases/{canvas_id}/artifacts")
def get_artifacts(canvas_id: str):
    from aughor.canvas.store import list_artifacts
    return {"artifacts": [a.model_dump() for a in list_artifacts(canvas_id)]}

@router.post("/canvases/{canvas_id}/artifacts", status_code=201)
def create_artifact_endpoint(canvas_id: str, req: CreateArtifactRequest):
    from aughor.canvas.store import create_artifact
    artifact = create_artifact(
        canvas_id=canvas_id, kind=req.kind, title=req.title,
        description=req.description, sql=req.sql, question=req.question,
    )
    return artifact.model_dump()

@router.delete("/canvases/{canvas_id}/artifacts/{artifact_id}", status_code=204)
def delete_artifact_endpoint(artifact_id: str):
    from aughor.canvas.store import delete_artifact
    if not delete_artifact(artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found")
