"""Ontology graph — entities, relationships, actions, metrics, lifecycle counts, rebuild."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aughor.db.connection import open_connection_for
from aughor.db.registry import BUILTIN_ID, get_meta
from aughor.ontology.models import OntologyAction
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
    # Fast path: return the cached graph built by exploration / build_intelligence.
    # get_schema() is the lightweight introspection path and (since the schema
    # fast/slow split) does NOT build the ontology, so db.get_ontology() would be
    # None here — we must read the ontology store directly.
    try:
        from aughor.ontology.store import load_latest_ontology
        graph = load_latest_ontology(connection_id, schema_name or None)
        if graph is None and schema_name:
            graph = load_latest_ontology(connection_id, None)
        if graph is not None:
            return graph
    except Exception:
        pass

    # Not cached yet — build it (heavier: profiles + enrichment + validation).
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
        # build_intelligence() (not get_schema()) is what builds + caches + sets
        # the OntologyGraph. Learned-skill overlay happens inside the store seam.
        db.build_intelligence()
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
        # The build re-opens the connection; in-memory file uploads (local_upload,
        # dsn local://…) are empty on re-open, so no graph is produced. That's a
        # client-actionable condition, not a server fault — return a clear 422
        # rather than a confusing 500.
        from aughor.db.registry import get_dsn
        try:
            conn_type, dsn = get_dsn(connection_id)
        except Exception:
            conn_type, dsn = "", ""
        in_memory = conn_type == "local_upload" or str(dsn).startswith("local://")
        detail = (
            "Ontology can't be rebuilt for an in-memory file upload — its data isn't "
            "re-readable on rebuild. Re-upload the data to refresh."
            if in_memory else
            "Ontology could not be built for this connection (no schema returned)."
        )
        raise HTTPException(status_code=422, detail=detail)
    return {
        "ok": True,
        "schema_name": graph.schema_name,
        "generated_at": graph.generated_at,
        "entities": len(graph.entities),
    }


# ── Skills (learned actions / procedural memory) ────────────────────────────────

def _skill_schema(connection_id: str, schema_name: Optional[str]) -> str:
    """Airtight {conn}:{schema} key for learned skills.

    An explicit schema_name (the UI passes one drawn from the graph's own schema
    list) is honored; otherwise we read the schema the live ontology graph is
    actually built under — the SAME value the planner's overlay reads from — never
    a connection-metadata guess.  This guarantees the write key == the read key.
    """
    if schema_name:
        return schema_name
    from aughor.memory.skills import resolve_active_schema
    return resolve_active_schema(connection_id)


@router.get("/ontology/skills")
def list_learned_skills(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Learned skills (origin='learned' OntologyActions) for this connection/schema."""
    from aughor.memory.skills import load_learned_actions
    effective = _skill_schema(connection_id, schema_name)
    actions = load_learned_actions(connection_id, effective)
    return {"schema_name": effective, "skills": [a.model_dump() for a in actions.values()]}


@router.post("/ontology/skills/propose")
def propose_learned_skill(
    inv_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Crystallize a *candidate* skill from a finished investigation.

    Returns the proposed OntologyAction WITHOUT persisting it — the UI shows it
    for confirmation, then calls POST /ontology/skills to save.
    """
    from aughor.memory.skills import propose_skill_from_investigation
    graph = _get_ontology_graph(connection_id, schema_name)
    # Key on the graph's own schema_name — the exact overlay read key.
    effective = graph.schema_name if graph else _skill_schema(connection_id, schema_name)
    t2e = dict(graph.table_to_entity) if graph else None
    candidate = propose_skill_from_investigation(inv_id, table_to_entity=t2e)
    if candidate is None:
        raise HTTPException(
            status_code=422,
            detail="Run is not skill-worthy (low confidence, ungrounded, or no read-only query).",
        )
    return {"schema_name": effective, "candidate": candidate.model_dump()}


@router.post("/ontology/skills")
def save_learned_skill(
    action: OntologyAction,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Persist a confirmed learned skill, gated by a read-only dry-run (EXPLAIN)."""
    from aughor.memory.skills import save_skill

    effective = _skill_schema(connection_id, schema_name)

    def _validator(sql: str) -> bool:
        db = open_connection_for(connection_id)
        try:
            res = db.execute("skill_dry_run", f"EXPLAIN {sql}")
            return not res.error
        finally:
            try:
                db.close()
            except Exception:
                pass

    ok = save_skill(connection_id, effective, action, validator=_validator)
    if not ok:
        raise HTTPException(status_code=422, detail="Skill rejected: SQL is not read-only or failed dry-run.")
    return {"ok": True, "schema_name": effective, "id": action.id}


@router.post("/ontology/skills/{action_id}/use")
def use_learned_skill(
    action_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Increment a learned skill's usage_count (feeds per-skill autonomy)."""
    from aughor.memory.skills import record_skill_use
    from aughor.memory.trust import skill_autonomy
    effective = _skill_schema(connection_id, schema_name)
    count = record_skill_use(connection_id, effective, action_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="Learned skill not found.")
    return {"ok": True, "usage_count": count, "autonomy": skill_autonomy(count, connection_id)}


@router.delete("/ontology/skills/{action_id}")
def delete_learned_skill(
    action_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    from aughor.memory.skills import delete_skill
    effective = _skill_schema(connection_id, schema_name)
    if not delete_skill(connection_id, effective, action_id):
        raise HTTPException(status_code=404, detail="Learned skill not found.")
    return {"ok": True}


# ── Autonomy (trust → L0–L3 ladder) ─────────────────────────────────────────────

@router.get("/ontology/autonomy")
def get_autonomy(connection_id: str = BUILTIN_ID):
    """The connection's earned L0–L3 autonomy level, computed from reflection
    signals (aughor.memory.trust)."""
    from aughor.memory.trust import autonomy_level
    return autonomy_level(connection_id)
