"""What each dataset is for, whether it is on, and how mature it is — the exploration principles' doors (2026-10-08).

``GET /exploration/{conn}/datasets`` is the Catalog's read: per schema and per table, the LAYER a person
set (or the one its signs propose, with the evidence), whether a person turned it off, and its maturity
— Structure, Questions, Time, as shares and a number — plus the month's exploration budget. A read: the
schema and table names come the way the Catalog lists them, everything else from stores.

The writes are a person's: setting a layer (one dataset, or accepting every proposal at once) and
turning a schema or a table off or back on. Each is recorded under the person signed in. Setting a
layer that asks questions is the event that starts them (§2), within the budget; turning a dataset off
takes it out of every mode at once (§6).
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from aughor.security.authz import caller, connection_owner_guard

router = APIRouter(tags=["exploration"], dependencies=[Depends(connection_owner_guard)])


class LayerRequest(BaseModel):
    schema_name: str
    table: str = ""
    layer: str


class AcceptRequest(BaseModel):
    #: The schemas whose proposed layer a person accepts; empty = every schema not set yet.
    schemas: list[str] = []


class OffRequest(BaseModel):
    schema_name: str
    table: str = ""
    off: bool
    reason: str = "out_of_domain"
    note: str = ""


def _columns_by_table(conn_id: str) -> dict[str, list[tuple[str, str]]]:
    """Each profiled table's ``(column, type)`` by bare name — the column signs' evidence."""
    from aughor.tools.profile_cache import merged_profile_entry
    out: dict[str, list[tuple[str, str]]] = {}
    for c in ((merged_profile_entry(conn_id) or {}).get("columns") or {}).values():
        if isinstance(c, dict) and c.get("table") and c.get("column"):
            out.setdefault(str(c["table"]).split(".")[-1].lower(), []).append((str(c["column"]), str(c.get("dtype") or "")))
    return out


def _schemas_of(conn_id: str) -> list[dict]:
    from aughor.db.registry import get_conn_type
    from aughor.routers.catalog import quick_schemas
    got = quick_schemas(conn_id, get_conn_type(conn_id))
    if got is None:
        raise HTTPException(status_code=503, detail="the connection's schemas could not be read just now")
    return got


def _dataset_key(conn_id: str, schema: str, n_schemas: int) -> str:
    from aughor.explorer.program import key_for
    return key_for(conn_id, schema if n_schemas >= 2 else None)


def datasets(conn_id: str) -> dict:
    from aughor.briefing.ranges import governed_metrics
    from aughor.explorer import budget as B
    from aughor.explorer import maturity as M
    from aughor.explorer import program as P
    from aughor.explorer import store as expl_store
    from aughor.ontology import dataset_layers as L
    from aughor.ontology.declarations import EXCLUSION_REASONS
    from aughor.ontology.visibility import SCHEMA_WIDE, excluded
    from aughor.routers._shared import connection_has_business

    schemas = _schemas_of(conn_id)
    cols = _columns_by_table(conn_id)
    has_business = connection_has_business(conn_id)
    explored = frozenset(x for x in L.LAYERS if "questions" in L.auto_jobs(x, connection_has_business=has_business))
    profiled = set(cols)
    out = []
    for sch in schemas:
        name = sch["name"]
        tables = [t["name"] for t in sch.get("tables") or []]
        key = _dataset_key(conn_id, name, len(schemas))
        state = expl_store.load(key)
        prog = P.load(key)
        declared = L.load_declared(conn_id, name)
        metrics = governed_metrics(conn_id, name if len(schemas) >= 2 else None)
        own_set = declared["schema"]
        table_cols = {t: cols.get(t.lower(), []) for t in tables}
        proposed = L.propose_schema(name, table_cols, approved_metrics=len(metrics))
        layer = (own_set or {}).get("layer", "")
        off = excluded(conn_id, name)
        rows = []
        for t in tables:
            t_set = declared["tables"].get(t.lower())
            t_prop = L.propose_table(t, table_cols.get(t, []))
            t_layer = (t_set or {}).get("layer") or layer
            t_off = None if off is not None else excluded(conn_id, name, t)
            rows.append({
                "name": t,
                "layer": {"set": t_set, "proposed": t_prop.to_dict() if t_prop.layer and t_prop.layer != (layer or proposed.layer) else None,
                          "effective": t_layer},
                "off": t_off.to_dict() if t_off is not None else None,
                "maturity": M.maturity(state, prog, metrics, layer=t_layer, explored_layers=explored,
                                       table=t, profiled=t.lower() in profiled),
            })
        last = P.last_run(prog)
        out.append({
            "name": name,
            "key": key,
            "layer": {"set": own_set, "proposed": proposed.to_dict(), "effective": layer,
                      "policy": L.POLICY.get(layer, "") if layer else
                      "structure only — its questions wait for a person to set its layer",
                      "jobs": sorted(L.auto_jobs(layer, connection_has_business=has_business))},
            "off": off.to_dict() if off is not None and off.table == SCHEMA_WIDE else None,
            "maturity": M.maturity(state, prog, metrics, layer=layer, explored_layers=explored),
            "program": {"held": prog.get("held"), "reopened": prog.get("reopened"), "last_run": last,
                        "watch": prog.get("watch") or {}, "failures": prog.get("failures", 0)},
            "tables": rows,
        })
    return {"connection_id": conn_id, "schemas": out, "budget": B.standing(conn_id),
            "layers": [{"id": x, "label": L.LABEL[x], "policy": L.POLICY[x]} for x in L.LAYERS],
            "exclusion_reasons": list(EXCLUSION_REASONS)}


@router.get("/exploration/{conn_id}/datasets")
async def get_datasets(conn_id: str):
    """Every schema and table of the connection: its layer (set, or proposed with evidence), whether it is
    off, its maturity, and the month's exploration budget."""
    return await asyncio.get_running_loop().run_in_executor(None, datasets, conn_id)


def _questions_on_layer(conn_id: str, schema: str, n_schemas: int) -> Optional[str]:
    """A layer that asks questions was just set: start them now, within the budget (§2's event).
    Returns what happened, said; None when nothing was due."""
    from aughor.explorer import budget as B
    from aughor.explorer import store as expl_store
    from aughor.routers._shared import automatic_jobs, explorer_refusal
    sch = schema if n_schemas >= 2 else None
    if explorer_refusal(conn_id) or "questions" not in automatic_jobs(conn_id, sch):
        return None
    key = _dataset_key(conn_id, schema, n_schemas)
    state = expl_store.load(key)
    if expl_store.is_unfinished(state):
        return "its run is under way; its questions follow on the next check"
    standing = B.standing(conn_id)
    if standing["spent_out"]:
        from aughor.explorer import program as P
        P.hold(key, standing["sentence"])
        return standing["sentence"]
    from aughor.kernel.concurrency import spawn
    from aughor.routers._shared import spawn_explorer
    learned = bool(state.get("structure_learned")) or state.get("phase") == "complete"
    spawn(spawn_explorer(conn_id, schema_name=sch, domain_intel_only=learned,
                         reason="its layer was set — its first questions"), name=f"layer-{key}")
    return "its questions have started"


@router.put("/exploration/{conn_id}/datasets/layer")
async def put_layer(conn_id: str, req: LayerRequest):
    """A person sets a schema's layer, or one table's. The system layer is never read, so setting it turns
    the dataset off too."""
    from aughor.ontology import dataset_layers as L
    from aughor.ontology.visibility import SCHEMA_WIDE, declare_exclusion
    by = caller()
    try:
        rec = L.set_layer(conn_id, req.schema_name, req.layer, table=req.table, set_by=by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if req.layer == "system":
        declare_exclusion(conn_id, req.schema_name, req.table or SCHEMA_WIDE, "system_table",
                          note="set to the system layer", declared_by=by)
    started = None
    if not req.table:
        n = len(await asyncio.get_running_loop().run_in_executor(None, _schemas_of, conn_id))
        started = _questions_on_layer(conn_id, req.schema_name, n)
    return {**rec, "started": started}


@router.delete("/exploration/{conn_id}/datasets/layer")
def delete_layer(conn_id: str, schema_name: str, table: str = ""):
    from aughor.ontology import dataset_layers as L
    if not L.clear_layer(conn_id, schema_name, table=table):
        raise HTTPException(status_code=404, detail="no layer is set there")
    return {"ok": True}


@router.post("/exploration/{conn_id}/datasets/layers/accept")
async def accept_layers(conn_id: str, req: AcceptRequest):
    """A person accepts the proposed layer of each named schema (or of every schema not set yet)."""
    from aughor.ontology import dataset_layers as L
    from aughor.ontology.visibility import SCHEMA_WIDE, declare_exclusion
    loop = asyncio.get_running_loop()
    current = await loop.run_in_executor(None, datasets, conn_id)
    by = caller()
    accepted, started = [], {}
    n = len(current["schemas"])
    for sch in current["schemas"]:
        if req.schemas and sch["name"] not in req.schemas:
            continue
        if not req.schemas and sch["layer"]["set"]:
            continue
        layer = sch["layer"]["proposed"]["layer"]
        if not layer:
            continue
        L.set_layer(conn_id, sch["name"], layer, set_by=by)
        if layer == "system":
            declare_exclusion(conn_id, sch["name"], SCHEMA_WIDE, "system_table",
                              note="set to the system layer", declared_by=by)
        accepted.append({"schema": sch["name"], "layer": layer})
        said = _questions_on_layer(conn_id, sch["name"], n)
        if said:
            started[sch["name"]] = said
    return {"accepted": accepted, "started": started}


@router.put("/exploration/{conn_id}/datasets/off")
def put_off(conn_id: str, req: OffRequest):
    """A person turns a schema or a table off for analysis — never explored, never queried by Investigation
    or Quick analysis — or back on. A person may still read it in the SQL editor."""
    from aughor.ontology.visibility import SCHEMA_WIDE, declare_exclusion, withdraw_exclusion
    target = req.table or SCHEMA_WIDE
    if not req.off:
        if not withdraw_exclusion(conn_id, req.schema_name, target):
            raise HTTPException(status_code=404, detail="it is not turned off")
        return {"ok": True, "off": None}
    try:
        e = declare_exclusion(conn_id, req.schema_name, target, req.reason, note=req.note, declared_by=caller())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True, "off": e.to_dict()}
