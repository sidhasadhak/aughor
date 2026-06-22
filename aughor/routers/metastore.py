"""UC-compatible read-only namespace API (PLATFORM_ARCHITECTURE.md §2/§11).

A Unity-Catalog-shaped surface over the metastore so external engines can browse the
`catalog.schema.table` namespace through a familiar contract — the seam that makes a
later swap to UC-OSS (or exposing the catalog via the UC / Iceberg-REST API) an
adapter, not a rewrite. Read-only for now; catalogs come from the first-class
metastore objects, schemas/tables ride the live introspection the catalog tree does
(which also keeps the metastore's Schema rows fresh).

Namespace identifiers use the catalog *id* (the stable conn-id) so the three-part
name `catalog.schema.table` is a valid identifier path; the connection's display name
rides along as `comment`. Access control on this surface (grants) is a later step —
today it exposes the org metastore namespace.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from aughor.metastore import Catalog, Schema, get_catalog, list_catalogs, list_schemas

router = APIRouter(prefix="/api/2.1/unity-catalog", tags=["unity-catalog"])


def _catalog_obj(cat: Catalog) -> dict:
    return {
        "name": cat.id,             # the namespace identifier (stable conn-id)
        "comment": cat.name,        # the human display name
        "id": cat.id,
        "created_at": cat.created_at,
        "updated_at": cat.updated_at,
        "securable_type": "CATALOG",
    }


def _schema_obj(s: Schema) -> dict:
    return {
        "name": s.name,
        "catalog_name": s.catalog_id,
        "full_name": s.full_name,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "securable_type": "SCHEMA",
    }


def _table_obj(catalog_name: str, schema_name: str, t: dict) -> dict:
    return {
        "name": t["name"],
        "catalog_name": catalog_name,
        "schema_name": schema_name,
        "full_name": f"{catalog_name}.{schema_name}.{t['name']}",
        "table_type": "TABLE",
        "securable_type": "TABLE",
        "row_count": t.get("row_count"),
    }


async def _live_entries() -> list[dict]:
    """The catalog tree's connection entries (live introspection; also refreshes the
    metastore's Schema rows as a side effect)."""
    from aughor.routers.catalog import get_catalog_tree
    tree = await get_catalog_tree()
    sections = tree.get("sections") or []
    return sections[0]["entries"] if sections else []


# ── catalogs ──────────────────────────────────────────────────────────────────

@router.get("/catalogs")
def uc_list_catalogs() -> dict:
    return {"catalogs": [_catalog_obj(c) for c in list_catalogs()]}


@router.get("/catalogs/{name}")
def uc_get_catalog(name: str) -> dict:
    cat = get_catalog(name)
    if cat is None:
        raise HTTPException(status_code=404, detail=f"catalog '{name}' not found")
    return _catalog_obj(cat)


# ── schemas ───────────────────────────────────────────────────────────────────

@router.get("/schemas")
async def uc_list_schemas(catalog_name: str = Query(...)) -> dict:
    await _live_entries()   # refresh the metastore's Schema rows from live introspection
    return {"schemas": [_schema_obj(s) for s in list_schemas(catalog_name)]}


@router.get("/schemas/{full_name}")
async def uc_get_schema(full_name: str) -> dict:
    catalog_name, _, schema_name = full_name.partition(".")
    if not schema_name:
        raise HTTPException(status_code=400, detail="schema full_name must be 'catalog.schema'")
    await _live_entries()
    for s in list_schemas(catalog_name):
        if s.name == schema_name:
            return _schema_obj(s)
    raise HTTPException(status_code=404, detail=f"schema '{full_name}' not found")


# ── tables (live-introspected; not persisted) ─────────────────────────────────

async def _tables_in(catalog_name: str, schema_name: str) -> list[dict] | None:
    for entry in await _live_entries():
        if entry.get("conn_id") != catalog_name:
            continue
        for sch in entry.get("schemas", []):
            if sch.get("name") == schema_name:
                return sch.get("tables", [])
        return None   # catalog found, schema absent
    return None       # catalog absent


@router.get("/tables")
async def uc_list_tables(catalog_name: str = Query(...), schema_name: str = Query(...)) -> dict:
    tables = await _tables_in(catalog_name, schema_name)
    if tables is None:
        raise HTTPException(status_code=404, detail=f"'{catalog_name}.{schema_name}' not found")
    return {"tables": [_table_obj(catalog_name, schema_name, t) for t in tables]}


@router.get("/tables/{full_name}")
async def uc_get_table(full_name: str) -> dict:
    parts = full_name.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="table full_name must be 'catalog.schema.table'")
    catalog_name, schema_name, table_name = parts
    tables = await _tables_in(catalog_name, schema_name)
    for t in (tables or []):
        if t.get("name") == table_name:
            return _table_obj(catalog_name, schema_name, t)
    raise HTTPException(status_code=404, detail=f"table '{full_name}' not found")
