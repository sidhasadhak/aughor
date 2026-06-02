"""Ontology graph — entities, relationships, actions, metrics, lifecycle counts, rebuild."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aughor.db.connection import open_connection_for
from aughor.db.registry import BUILTIN_ID, get_meta
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


def _resolve_schema(connection_id: str, schema_name: Optional[str]) -> str:
    """Return the effective schema name: explicit param > connection meta > 'default'."""
    if schema_name:
        return schema_name
    try:
        meta = get_meta(connection_id)
        return meta.get("schema_name") or "default"
    except Exception:
        return "default"


def _get_ontology_graph(connection_id: str, schema_name: Optional[str] = None):
    """Open connection, build/load schema, and return its OntologyGraph.

    If schema_name is supplied and differs from the connection's configured schema,
    the connection is opened against that specific schema.  Otherwise the connection's
    registered schema is used.
    """
    try:
        if schema_name:
            # Open against the requested schema explicitly so multi-schema
            # databases (e.g. one DuckDB file with analytics/raw/events/…) build
            # and cache a distinct ontology per schema rather than only the one
            # named in the connection's stored metadata.
            from aughor.db.connection import open_connection
            from aughor.db.registry import get_dsn, get_meta
            conn_type, dsn = get_dsn(connection_id)
            meta = get_meta(connection_id)
            db = open_connection(
                conn_type, dsn,
                schema_name=schema_name,
                connection_id=connection_id,
                meta=meta,
            )
        else:
            db = open_connection_for(connection_id)
        db.get_schema()
        return db.get_ontology()
    except Exception:
        return None


def _latest_fingerprint(connection_id: str, schema_name: Optional[str] = None) -> Optional[str]:
    from aughor.ontology.store import _load, _schema_prefix, _conn_prefix
    cache = _load()
    effective = _resolve_schema(connection_id, schema_name)
    prefix = _schema_prefix(connection_id, effective)
    matches = [k for k in cache if k.startswith(prefix)]
    if not matches:
        return None
    # key = "{conn_id}:{schema_name}:{fingerprint}" — return the fingerprint part
    last = matches[-1]
    return last[len(prefix):]


# ── Read endpoints ─────────────────────────────────────────────────────────────

@router.get("/ontology/schemas")
def list_ontology_schemas(connection_id: str = BUILTIN_ID):
    """List the DB schemas that have a cached ontology for this connection."""
    from aughor.ontology.store import list_schemas
    schemas = list_schemas(connection_id)
    # Always include the connection's configured schema even if not yet cached
    try:
        meta = get_meta(connection_id)
        configured = meta.get("schema_name") or "default"
        if configured not in schemas:
            schemas = [configured] + schemas
    except Exception:
        pass
    return {"schemas": schemas}


@router.get("/ontology")
def get_ontology(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available for this connection")
    return graph.model_dump()


@router.get("/ontology/entities")
def get_ontology_entities(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {eid: e.model_dump() for eid, e in graph.entities.items()}


@router.get("/ontology/relationships")
def get_ontology_relationships(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {rid: r.model_dump() for rid, r in graph.relationships.items()}


@router.get("/ontology/actions")
def get_ontology_actions(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {aid: a.model_dump() for aid, a in graph.actions.items()}


@router.get("/ontology/entities/{entity_id}/object-sets")
def get_entity_object_sets(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Return all named ObjectSets for an entity — keyed by object set id."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return {sid: s.model_dump() for sid, s in entity.object_sets.items()}


@router.get("/ontology/entities/{entity_id}/properties")
def get_entity_properties(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Return the EntityProperty map for a single entity — keyed by column name."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return {name: prop.model_dump() for name, prop in entity.properties.items()}


@router.get("/ontology/interfaces")
def get_ontology_interfaces(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Return all detected OntologyInterfaces for this schema — keyed by interface id."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {iid: iface.model_dump() for iid, iface in graph.interfaces.items()}


@router.get("/ontology/metrics")
def get_ontology_metrics(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {mid: m.model_dump() for mid, m in graph.metrics.items()}


# ── Override (write) endpoints ─────────────────────────────────────────────────

@router.put("/ontology/entities/{entity_id}")
def override_ontology_entity(
    entity_id: str,
    body: _EntityOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    from aughor.ontology.store import patch_entity
    effective = _resolve_schema(connection_id, schema_name)
    fingerprint = _latest_fingerprint(connection_id, effective)
    if not fingerprint:
        graph = _get_ontology_graph(connection_id, effective)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = patch_entity(connection_id, effective, fingerprint, entity_id, overrides)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return updated.entities[entity_id].model_dump()


@router.put("/ontology/actions/{action_id}")
def override_ontology_action(
    action_id: str,
    body: _ActionOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    from aughor.ontology.store import patch_action
    effective = _resolve_schema(connection_id, schema_name)
    fingerprint = _latest_fingerprint(connection_id, effective)
    if not fingerprint:
        graph = _get_ontology_graph(connection_id, effective)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = patch_action(connection_id, effective, fingerprint, action_id, overrides)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")
    return updated.actions[action_id].model_dump()


# ── Lifecycle counts ───────────────────────────────────────────────────────────

@router.get("/ontology/entities/{entity_id}/lifecycle-counts")
async def get_entity_lifecycle_counts(
    entity_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    loop = asyncio.get_event_loop()

    graph = await loop.run_in_executor(None, lambda: _get_ontology_graph(connection_id, schema_name))
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


# ── Rebuild ────────────────────────────────────────────────────────────────────

@router.post("/ontology/rebuild")
def rebuild_ontology(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    from aughor.ontology.store import invalidate as invalidate_ontology
    effective = _resolve_schema(connection_id, schema_name)
    invalidate_ontology(connection_id, effective)
    _invalidate_schema_cache(connection_id)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=500, detail="Ontology rebuild failed")
    return {
        "ok": True,
        "schema_name": graph.schema_name,
        "generated_at": graph.generated_at,
        "entities": len(graph.entities),
    }
