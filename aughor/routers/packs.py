"""Specialist pack endpoints (P0/P1) — list, inspect, validate, propose bindings, activate.

The list/detail/validate endpoints are connection-free. propose-bindings takes a `table_cols`
map (the caller fetches it from the catalog) so the grounding proposal is usable + testable
without coupling this router to live introspection. Gated by the `specialist_packs` flag.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.kernel.flags import flag_enabled
from aughor.packs import (
    load_pack, list_packs, validate_pack, PacksError,
    schema_facts_from_table_cols, propose_bindings, save_binding, load_binding,
)
from aughor.packs.resolver import binding_report

router = APIRouter(tags=["packs"])

PACKS_DIR = Path(__file__).resolve().parents[2] / "packs"


def _summary(pack_dir: Path) -> dict:
    try:
        pack = load_pack(pack_dir)
    except PacksError as e:
        return {"id": pack_dir.name, "ok": False, "error": str(e)}
    r = validate_pack(pack_dir)
    m = pack.manifest
    return {
        "id": pack.id, "name": m.name, "status": m.status, "version": m.version,
        "domains": m.domains, "metrics": len(pack.metrics), "roles": len(pack.entities),
        "evals": len(pack.evals), "ok": r.ok,
        "errors": r.errors, "warnings": r.warnings,
    }


@router.get("/packs")
def get_packs():
    """All packs under packs/ with a validation summary, plus the feature-flag state."""
    enabled = flag_enabled("specialist_packs")
    packs = []
    if PACKS_DIR.is_dir():
        for pid in list_packs(PACKS_DIR):
            packs.append(_summary(PACKS_DIR / pid))
    return {"enabled": enabled, "packs": packs}


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str):
    """Full pack detail + validation report."""
    pack_dir = PACKS_DIR / pack_id
    if not (pack_dir / "pack.yaml").is_file():
        raise HTTPException(status_code=404, detail=f"no pack {pack_id!r}")
    try:
        pack = load_pack(pack_dir)
    except PacksError as e:
        raise HTTPException(status_code=422, detail=str(e))
    r = validate_pack(pack_dir)
    return {
        "manifest": pack.manifest.model_dump(),
        "expertise": pack.expertise,
        "metrics": [m.model_dump() for m in pack.metrics],
        "entities": {k: v.model_dump() for k, v in pack.entities.items()},
        "questions": pack.questions.model_dump(),
        "playbooks": [p.model_dump() for p in pack.playbooks],
        "evals": [e.model_dump() for e in pack.evals],
        "validation": {"ok": r.ok, "errors": r.errors, "warnings": r.warnings},
    }


class ProposeIn(BaseModel):
    connection_id: str = ""
    schema: Optional[str] = None
    table_cols: Optional[dict[str, list[str]]] = None    # omit to introspect the connection
    business_model: str = ""


def _facts_for_connection(connection_id: str, schema: Optional[str], business_model: str):
    """Build dtype-aware SchemaFacts from a live connection's schema context (the introspection
    glue). Best-effort: returns None on any failure so the caller can ask for a posted map."""
    try:
        from aughor.routers.connections import open_connection_for
        from aughor.tools.schema import build_schema_context
        from aughor.packs.adapter import schema_facts_from_schema_context
        conn = open_connection_for(connection_id)
        raw = getattr(conn, "raw", None) or getattr(conn, "_conn", None) or conn
        ctx = build_schema_context(raw, schema_name=schema, connection_id=connection_id)
        return schema_facts_from_schema_context(ctx, business_model=business_model)
    except Exception:
        return None


@router.post("/packs/{pack_id}/propose-bindings")
def post_propose_bindings(pack_id: str, body: ProposeIn):
    """Propose role→table/column bindings for this pack. Pass `table_cols` explicitly, or omit
    it and we introspect `connection_id` (+ optional `schema`) live. Returns each role's
    candidate (table/column/value, confidence, evidence) + a bound summary for deploy review."""
    pack_dir = PACKS_DIR / pack_id
    if not (pack_dir / "pack.yaml").is_file():
        raise HTTPException(status_code=404, detail=f"no pack {pack_id!r}")
    try:
        pack = load_pack(pack_dir)
    except PacksError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if body.table_cols:
        facts = schema_facts_from_table_cols(body.table_cols, business_model=body.business_model)
    else:
        facts = _facts_for_connection(body.connection_id, body.schema, body.business_model)
        if facts is None:
            raise HTTPException(status_code=422,
                                detail="provide table_cols or a reachable connection_id")
    rep = binding_report(pack.entities, facts)
    return {
        "fully_bound": rep["fully_bound"], "bound": rep["bound"], "total": rep["total"],
        "proposals": {role: vars(cand) for role, cand in rep["proposals"].items()},
    }


class BindIn(BaseModel):
    connection_id: str
    bindings: dict
    verified: bool = False
    version: int = 1
    table_cols: Optional[dict[str, list[str]]] = None   # if given, verify columns exist


@router.post("/packs/{pack_id}/bind")
def post_bind(pack_id: str, body: BindIn):
    """Pin a confirmed binding for (org, pack, connection). When `table_cols` is supplied the
    bound columns are checked to actually exist and `verified` reflects that (column-existence
    half of verification; recipe dry-run is the live step)."""
    from aughor.packs import verify_binding_columns
    verified = body.verified
    missing: list[str] = []
    if body.table_cols is not None:
        verified, missing = verify_binding_columns(body.bindings, body.table_cols)
    rec = save_binding(pack_id, body.connection_id, body.bindings,
                       version=body.version, verified=verified)
    rec["missing"] = missing
    return rec


@router.get("/packs/{pack_id}/binding")
def get_binding(pack_id: str, connection_id: str):
    """The pinned binding for (org, pack, connection), or null."""
    return load_binding(pack_id, connection_id)
