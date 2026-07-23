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

from aughor.licensing import Capability, gate

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


class _MergeEntitiesRequest(BaseModel):
    merge_ids: list[str]      # the cluster of entity ids to merge (must include canonical_id)
    canonical_id: str         # the survivor — others are merged into it


class _ColumnConfigEdit(BaseModel):
    """One human edit to one column's {visible, sample, index} config (R11).
    Only the flags present in the body change; the entry becomes source=human."""
    table: str
    column: str
    visible: Optional[bool] = None
    sample: Optional[bool] = None
    index: Optional[bool] = None
    note: str = ""


class _ComputedPropertyOverride(BaseModel):
    label: Optional[str] = None
    formula_sql: Optional[str] = None
    unit: Optional[str] = None


class _ObjectSetOverride(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    filter_sql: Optional[str] = None
    is_default: Optional[bool] = None


class _MetricOverride(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    formula_sql: Optional[str] = None
    grain: Optional[str] = None
    unit: Optional[str] = None
    entity: Optional[str] = None   # required only when authoring a brand-new metric


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
            # load_latest_ontology already overlays human overrides (the shared
            # authority seam), so the read APIs / UI reflect edits for free.
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
    from aughor.ontology.store import _load, _schema_prefix
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


@router.get("/ontology/duplicate-entities")
def get_duplicate_entities(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    threshold: float = Query(default=0.85, ge=0.5, le=1.0),
):
    """Near-duplicate entity clusters (embedding self-similarity + connected components), as merge
    SUGGESTIONS — never applied. A read; empty when embeddings are unavailable or nothing clusters."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    from aughor.ontology.dedup import detect_duplicate_entities
    return {"clusters": detect_duplicate_entities(graph, threshold=threshold)}


@router.get("/ontology/actions")
def get_ontology_actions(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {aid: a.model_dump() for aid, a in graph.actions.items()}


@router.get("/ontology/kinetic-actions")
def get_kinetic_actions(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Wave K: human-declared governed actions overlaid onto the graph. Read-only — empty unless
    the `kinetic.actions` flag is on and the connection has declared actions in its ontology
    overrides. These are NOT executed here (that is the K2 executor); this surfaces what is
    declared, for the authoring UI and for the agent's action prompt-section."""
    graph = _get_ontology_graph(connection_id, schema_name)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {aid: a.model_dump() for aid, a in graph.kinetic_actions.items()}


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
#
# Overrides are persisted to the fingerprint-INDEPENDENT YAML overlay
# (aughor/ontology/overrides.py), NOT the structural fingerprint cache, so they
# survive every rebuild (a row-count change re-fingerprints and rebuilds). SQL
# fields are EXPLAIN-bound against the live DB before they can earn authority.

def _explain_for(connection_id: str):
    """Return (explain_fn, closer): explain_fn(sql) -> error-or-None via dry_run."""
    db = open_connection_for(connection_id)

    def _explain(sql: str) -> Optional[str]:
        ok, msg = db.dry_run(sql)
        return None if ok else (msg or "did not bind")

    def _close():
        try:
            db.close()
        except Exception:
            pass

    return _explain, _close


def _bind_and_persist(connection_id: str, schema: str, ov):
    """EXPLAIN-bind the override's SQL fields, persist it, and return (ov, graph)."""
    from aughor.ontology.overrides import bind_overrides, save_override
    graph = _get_ontology_graph(connection_id, schema)
    try:
        explain, close = _explain_for(connection_id)
        try:
            bind_overrides(ov, graph, explain)
        finally:
            close()
    except Exception:
        pass  # binding is best-effort; unbound SQL simply won't earn `verified`
    save_override(connection_id, schema, ov)
    return ov, graph


def _override_result(ov) -> dict:
    """Response shape: the saved override + whether its SQL bound + any warnings."""
    warnings = [f"{f}: {b.get('note')}" for f, b in ov.binding.items() if not b.get("bound")]
    return {
        "override": ov.model_dump(),
        # verified == every SQL field bound (no-SQL override is trivially verified)
        "verified": all(b.get("bound") for b in ov.binding.values()) if ov.binding else True,
        "warnings": warnings,
    }


@router.put("/ontology/entities/{entity_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def override_ontology_entity(
    entity_id: str,
    body: _EntityOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    from aughor import govern
    govern.guard("ontology.override", connection_id)  # P4: mutating the semantic layer
    from aughor.ontology.overrides import OntologyOverride
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    ov = OntologyOverride(target_kind="entity", target_id=entity_id, fields=fields)
    ov, graph = _bind_and_persist(connection_id, effective, ov)
    if graph is not None and entity_id not in graph.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return _override_result(ov)


@router.put(
    "/ontology/entities/{entity_id}/computed-properties/{prop_id}",
    dependencies=[gate(Capability.ONTOLOGY_EDIT)],
)
def override_ontology_computed_property(
    entity_id: str,
    prop_id: str,
    body: _ComputedPropertyOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Assert (or correct) a derived metric on an entity. Once its formula EXPLAIN-binds,
    it is injected into the NL2SQL prompt with authority — overriding the auto-derived one."""
    from aughor.ontology.overrides import OntologyOverride
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    ov = OntologyOverride(
        target_kind="computed_property", target_id=f"{entity_id}::{prop_id}", fields=fields)
    ov, graph = _bind_and_persist(connection_id, effective, ov)
    if graph is not None and entity_id not in graph.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return _override_result(ov)


@router.put(
    "/ontology/entities/{entity_id}/object-sets/{set_id}",
    dependencies=[gate(Capability.ONTOLOGY_EDIT)],
)
def override_ontology_object_set(
    entity_id: str,
    set_id: str,
    body: _ObjectSetOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Define (or correct) a named row-filter (object set) on an entity."""
    from aughor.ontology.overrides import OntologyOverride
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    ov = OntologyOverride(
        target_kind="object_set", target_id=f"{entity_id}::{set_id}", fields=fields)
    ov, graph = _bind_and_persist(connection_id, effective, ov)
    if graph is not None and entity_id not in graph.entities:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    return _override_result(ov)


@router.put("/ontology/metrics/{metric_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def override_ontology_metric(
    metric_id: str,
    body: _MetricOverride,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Assert (or correct) a metric's canonical formula. EXPLAIN-bound, then injected
    with authority through the unified metrics catalog."""
    from aughor.ontology.overrides import OntologyOverride
    effective = _resolve_schema(connection_id, schema_name)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no override fields provided")
    ov = OntologyOverride(target_kind="metric", target_id=metric_id, fields=fields)
    ov, _ = _bind_and_persist(connection_id, effective, ov)
    return _override_result(ov)


@router.delete("/ontology/overrides/{kind}/{target_id:path}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def delete_ontology_override(
    kind: str,
    target_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Remove a human override so the auto-derived value is restored on next read."""
    from aughor import govern
    govern.guard("ontology.delete_override", connection_id)  # P4: reverts a governed semantic edit
    from aughor.ontology.overrides import delete_override
    if kind not in ("entity", "object_set", "computed_property", "metric"):
        raise HTTPException(status_code=400, detail=f"unknown override kind '{kind}'")
    effective = _resolve_schema(connection_id, schema_name)
    removed = delete_override(connection_id, effective, kind, target_id)  # type: ignore[arg-type]
    return {"removed": removed, "kind": kind, "target_id": target_id}


@router.get("/ontology/overrides", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def list_ontology_overrides(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """List all human overrides for this connection+schema (the version-controlled set)."""
    from aughor.ontology.overrides import load_overrides
    effective = _resolve_schema(connection_id, schema_name)
    return {"overrides": [o.model_dump() for o in load_overrides(connection_id, effective)]}


# ── Self-improving loop: engine-proposed recommendations ────────────────────────

@router.get("/ontology/recommendations", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def list_ontology_recommendations(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
    ripe_only: bool = Query(default=True),
):
    """List engine-proposed ontology fixes (the self-improving loop's output).

    ripe_only (default) hides one-off sightings — only recommendations seen enough
    times to be worth a human's review are returned.
    """
    from aughor.ontology.recommendations import load_recommendations
    effective = _resolve_schema(connection_id, schema_name)
    recs = load_recommendations(connection_id, effective)
    if ripe_only:
        recs = [r for r in recs if r.ripe]
    return {"recommendations": [r.model_dump() for r in recs]}


@router.post("/ontology/recommendations/{rec_id}/accept", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def accept_ontology_recommendation(
    rec_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Promote a recommendation into an EXPLAIN-bound human override (override-wins path)."""
    from aughor.ontology.recommendations import accept
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    explain, close = _explain_for(connection_id)
    try:
        res = accept(connection_id, effective, rec_id, graph, explain)
    finally:
        close()
    if res is None:
        raise HTTPException(status_code=404, detail=f"recommendation '{rec_id}' not found")
    return res


@router.post("/ontology/recommendations/{rec_id}/dismiss", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def dismiss_ontology_recommendation(
    rec_id: str,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Dismiss a recommendation so the loop won't resurface it."""
    from aughor.ontology.recommendations import get_recommendation, save_recommendation
    effective = _resolve_schema(connection_id, schema_name)
    rec = get_recommendation(connection_id, effective, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"recommendation '{rec_id}' not found")
    rec.status = "dismissed"
    save_recommendation(connection_id, effective, rec)
    return {"dismissed": True, "id": rec_id}


# ── Version-control round-trip: export ontology to files / import edits ─────────

@router.post("/ontology/export", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def export_ontology_tree(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Write the live ontology to a readable, version-controllable YAML tree."""
    from aughor.ontology.filetree import export_tree, export_root
    effective = _resolve_schema(connection_id, schema_name)
    graph = _get_ontology_graph(connection_id, effective)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    root = export_root(connection_id, effective)
    paths = export_tree(root, graph)
    return {"root": str(root), "files": len(paths)}


@router.post("/ontology/import", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def import_ontology_tree(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Re-import on-disk edits to the exported tree as EXPLAIN-bound overrides.

    Edits are diffed against the PRE-override auto-built graph, so re-importing an
    unedited export is a no-op and only changed fields become overrides.
    """
    from aughor.ontology.filetree import import_tree, export_root
    from aughor.ontology.overrides import bind_overrides, save_override
    from aughor.ontology.store import load_ontology
    effective = _resolve_schema(connection_id, schema_name)
    fingerprint = _latest_fingerprint(connection_id, effective)
    base = load_ontology(connection_id, effective, fingerprint) if fingerprint else None
    if base is None:
        base = _get_ontology_graph(connection_id, effective)
    if base is None:
        raise HTTPException(status_code=404, detail="Ontology not available")

    candidates = import_tree(export_root(connection_id, effective), base)
    explain, close = _explain_for(connection_id)
    saved = []
    try:
        for ov in candidates:
            bind_overrides(ov, base, explain)
            save_override(connection_id, effective, ov)
            saved.append({"kind": ov.target_kind, "target": ov.target_id,
                          "bound": all(b.get("bound") for b in ov.binding.values()) if ov.binding else True})
    finally:
        close()
    return {"imported": len(saved), "overrides": saved}


# ── R11: per-column {visible, sample, index} config ─────────────────────────

@router.get("/ontology/column-config")
def get_column_config(
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """The persisted per-column config, grouped per table. Readable regardless of
    the `ontology.column_config` flag (the flag gates runtime consumption, not the
    artifact); `enabled` tells the caller whether edits will take effect."""
    from aughor.kernel.flags import flag_enabled
    from aughor.ontology.column_config import load_column_configs
    effective = _resolve_schema(connection_id, schema_name)
    tables: dict[str, dict[str, dict]] = {}
    for (table, column), fl in sorted(load_column_configs(connection_id, effective).items()):
        tables.setdefault(table, {})[column] = fl.model_dump()
    return {
        "connection_id": connection_id,
        "schema": effective,
        "enabled": flag_enabled("ontology.column_config"),
        "tables": tables,
    }


@router.put("/ontology/column-config", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def put_column_config(
    body: _ColumnConfigEdit,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Apply a human edit to one column's config — override-wins, rebuild-proof.
    Invalidates the schema cache so pruning changes reach the next prompt."""
    if body.visible is None and body.sample is None and body.index is None:
        raise HTTPException(status_code=422, detail="pass at least one of visible/sample/index")
    from aughor.ontology.column_config import set_column_flags
    effective = _resolve_schema(connection_id, schema_name)
    flags = set_column_flags(
        connection_id, effective, body.table, body.column,
        visible=body.visible, sample=body.sample, index=body.index, note=body.note,
    )
    _invalidate_schema_cache(connection_id)
    return {
        "saved": True,
        "table": body.table,
        "column": body.column,
        "flags": flags.model_dump(),
    }


@router.post("/ontology/entities/merge", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
def merge_ontology_entities(
    body: _MergeEntitiesRequest,
    connection_id: str = BUILTIN_ID,
    schema_name: Optional[str] = Query(default=None),
):
    """Apply a duplicate-entity merge (the confirm step for `/ontology/duplicate-entities`). Collapses
    `merge_ids` into `canonical_id`, repointing every cross-reference, and persists. Gated + explicit —
    never automatic, because a wrong merge would corrupt the ontology."""
    if len(set(body.merge_ids)) < 2:
        raise HTTPException(status_code=400, detail="merge_ids must list at least 2 distinct entities")
    if body.canonical_id not in body.merge_ids:
        raise HTTPException(status_code=400, detail="canonical_id must be one of merge_ids")

    from aughor.ontology.store import apply_entity_merge
    effective = _resolve_schema(connection_id, schema_name)
    fingerprint = _latest_fingerprint(connection_id, effective)
    if not fingerprint:
        graph = _get_ontology_graph(connection_id, effective)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint

    merged = apply_entity_merge(connection_id, effective, fingerprint, body.merge_ids, body.canonical_id)
    if merged is None:
        raise HTTPException(status_code=404, detail="Ontology not available, or an entity id was unknown")
    return {
        "merged_into": body.canonical_id,
        "removed": [e for e in body.merge_ids if e != body.canonical_id],
        "entity": merged.entities[body.canonical_id].model_dump(),
        "entity_count": len(merged.entities),
    }


@router.put("/ontology/actions/{action_id}", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
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
    loop = asyncio.get_running_loop()

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

@router.post("/ontology/rebuild", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
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
        # Journal the failure (the build raised before its own emit could fire) —
        # the original "ontology silently doesn't build" becomes a queryable event.
        try:
            from aughor.kernel.ledger import Ledger
            Ledger.default().emit(
                "ontology.build",
                {"ok": False, "entities": 0, "stage": "rebuild",
                 "error": detail, "in_memory": in_memory},
                conn_id=connection_id,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).debug("ontology.build failure-emit skipped", exc_info=True)
        raise HTTPException(status_code=422, detail=detail)
    # Industry-aware intelligence keystone: (re)infer the Business Profile whenever
    # the ontology is rebuilt, so the explorer's industry-specific angles are ready
    # before exploration. Best-effort — a profile failure must not fail the rebuild.
    profile_industry = None
    try:
        from aughor.profile.infer import infer_business_profile
        from aughor.orgsettings import resolve_industry
        bp = infer_business_profile(connection_id, effective)
        profile_industry = resolve_industry(bp.industry)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "Business-profile inference after ontology rebuild failed (non-fatal): %s", exc)
    return {
        "ok": True,
        "schema_name": graph.schema_name,
        "generated_at": graph.generated_at,
        "entities": len(graph.entities),
        "industry": profile_industry,
    }


@router.get("/ontology/build-status")
def ontology_build_status(connection_id: str = BUILTIN_ID, limit: int = 5):
    """Surface the ontology build outcome — the WCH-3 observability the original
    'ontology silently doesn't build' symptom needed. Returns the connection's
    last in-memory build result (which stage failed + why) AND the recent
    ontology.build journal events (persistent trail across restarts)."""
    from aughor.kernel.ledger import Ledger
    last_build = None
    try:
        db = open_connection_for(connection_id)
        last_build = getattr(db, "last_build", None)
        db.close()
    except Exception:
        last_build = None
    events = Ledger.default().events(kind="ontology.build", conn_id=connection_id, limit=int(limit))
    return {"connection_id": connection_id, "last_build": last_build, "recent_builds": events}


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


@router.post("/ontology/skills", dependencies=[gate(Capability.ONTOLOGY_EDIT)])
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
