"""Ontology graph — entities, relationships, actions, metrics, lifecycle counts, rebuild."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.db.connection import open_connection_for
from aughor.db.registry import BUILTIN_ID
from aughor.routers._shared import invalidate_schema_cache as _invalidate_schema_cache

router = APIRouter(tags=["ontology"])


class _EntityOverride(BaseModel):
    description: Optional[str] = None
    active_filter: Optional[str] = None
    default_filters: Optional[list[str]] = None
    exclude_when: Optional[list[str]] = None
    lifecycle_states: Optional[list[str]] = None
    terminal_states: Optional[list[str]] = None


class _ActionOverride(BaseModel):
    description: Optional[str] = None
    sql_template: Optional[str] = None
    business_rules_enforced: Optional[list[str]] = None
    returns: Optional[str] = None


def _get_ontology_graph(connection_id: str):
    try:
        db = open_connection_for(connection_id)
        db.get_schema()
        return db.get_ontology()
    except Exception:
        return None


def _latest_fingerprint(connection_id: str) -> Optional[str]:
    from aughor.ontology.store import _load
    cache = _load()
    prefix = f"{connection_id}:"
    matches = [k for k in cache if k.startswith(prefix)]
    if not matches:
        return None
    return matches[-1][len(prefix):]


@router.get("/ontology")
def get_ontology(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available for this connection")
    return graph.model_dump()


@router.get("/ontology/entities")
def get_ontology_entities(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {eid: e.model_dump() for eid, e in graph.entities.items()}


@router.get("/ontology/relationships")
def get_ontology_relationships(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {rid: r.model_dump() for rid, r in graph.relationships.items()}


@router.get("/ontology/actions")
def get_ontology_actions(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {aid: a.model_dump() for aid, a in graph.actions.items()}


@router.get("/ontology/metrics")
def get_ontology_metrics(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {mid: m.model_dump() for mid, m in graph.metrics.items()}


@router.put("/ontology/entities/{entity_id}")
def override_ontology_entity(entity_id: str, body: _EntityOverride, connection_id: str = BUILTIN_ID):
    from aughor.ontology.store import patch_entity
    fingerprint = _latest_fingerprint(connection_id)
    if not fingerprint:
        graph = _get_ontology_graph(connection_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = patch_entity(connection_id, fingerprint, entity_id, overrides)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return updated.entities[entity_id].model_dump()


@router.put("/ontology/actions/{action_id}")
def override_ontology_action(action_id: str, body: _ActionOverride, connection_id: str = BUILTIN_ID):
    from aughor.ontology.store import patch_action
    fingerprint = _latest_fingerprint(connection_id)
    if not fingerprint:
        graph = _get_ontology_graph(connection_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = patch_action(connection_id, fingerprint, action_id, overrides)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")
    return updated.actions[action_id].model_dump()


@router.get("/ontology/entities/{entity_id}/lifecycle-counts")
async def get_entity_lifecycle_counts(entity_id: str, connection_id: str = BUILTIN_ID):
    loop = asyncio.get_event_loop()

    # Ontology load is itself a DB call — push it off the event loop too
    graph = await loop.run_in_executor(None, lambda: _get_ontology_graph(connection_id))
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    if not entity.has_lifecycle or not entity.lifecycle_column or not entity.source_tables:
        return []

    table = entity.source_tables[0]
    col   = entity.lifecycle_column
    where = f"WHERE {entity.active_filter}" if entity.active_filter else ""
    sql   = f"SELECT {col} AS state, COUNT(*) AS cnt FROM {table} {where} GROUP BY {col} ORDER BY cnt DESC LIMIT 50"

    def _work():
        db  = open_connection_for(connection_id)
        try:
            res = db.execute("lifecycle_counts", sql)
        finally:
            try:
                db.close()
            except Exception:
                pass
        return res

    try:
        res = await loop.run_in_executor(None, _work)
        if res.error:
            raise HTTPException(status_code=500, detail=res.error)
        return [{"state": str(r[0]), "count": int(r[1])} for r in (res.rows or [])]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ontology/rebuild")
def rebuild_ontology(connection_id: str = BUILTIN_ID):
    from aughor.ontology.store import invalidate as invalidate_ontology
    invalidate_ontology(connection_id)
    _invalidate_schema_cache(connection_id)
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=500, detail="Ontology rebuild failed")
    return {"ok": True, "generated_at": graph.generated_at, "entities": len(graph.entities)}
