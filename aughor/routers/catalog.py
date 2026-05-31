"""Catalog tree endpoint."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from aughor.db.connection import open_connection_for

logger = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])


@router.get("/catalog/tree")
async def get_catalog_tree():
    """Return the full 4-level catalog hierarchy: Section → Catalog → Schema → Table."""
    loop = asyncio.get_event_loop()

    def _quick_schemas(conn_id: str, conn_type: str) -> list[dict]:
        try:
            db = open_connection_for(conn_id)
            if conn_type == "duckdb":
                rows = db.execute(
                    "__catalog__",
                    """
                    SELECT schema_name, table_name, estimated_size
                    FROM duckdb_tables()
                    WHERE internal = false
                      AND schema_name NOT IN ('information_schema','temp','pg_catalog')
                    ORDER BY schema_name, table_name
                    """,
                ).rows
            else:
                rows = db.execute(
                    "__catalog__",
                    """
                    SELECT
                        t.table_schema,
                        t.table_name,
                        COALESCE(s.n_live_tup, 0)
                    FROM information_schema.tables t
                    LEFT JOIN pg_stat_user_tables s
                        ON s.schemaname = t.table_schema
                        AND s.relname   = t.table_name
                    WHERE t.table_type = 'BASE TABLE'
                      AND t.table_schema NOT IN
                          ('information_schema','pg_catalog','pg_toast')
                    ORDER BY t.table_schema, t.table_name
                    """,
                ).rows
            db.close()
        except Exception as exc:
            logger.debug("catalog tree: schema query failed for %s: %s", conn_id, exc)
            return []

        schema_map: dict[str, list] = {}
        for schema, table_name, row_est in rows:
            schema_map.setdefault(schema, []).append({"name": table_name, "row_count": row_est})
        return [{"name": s, "tables": t} for s, t in schema_map.items()]

    def _build_tree() -> dict:
        from aughor.db.registry import list_connections, SAMPLES_ID

        sections: list[dict] = []

        sample_schemas: list[dict] = []
        try:
            sample_schemas = _quick_schemas(SAMPLES_ID, "duckdb")
        except Exception as exc:
            logger.debug("catalog tree: samples unavailable: %s", exc)

        sections.append({
            "id": "samples",
            "label": "Sample Catalog",
            "entries": [{"conn_id": SAMPLES_ID, "name": "samples", "conn_type": "duckdb", "builtin": True, "schemas": sample_schemas}],
        })

        user_entries = []
        for conn_info in list_connections():
            cid = conn_info["id"]
            if cid == SAMPLES_ID:
                continue
            schemas = _quick_schemas(cid, conn_info.get("conn_type", "duckdb"))
            user_entries.append({
                "conn_id": cid,
                "name": conn_info["name"],
                "conn_type": conn_info.get("conn_type", ""),
                "builtin": conn_info.get("builtin", False),
                "schemas": schemas,
            })

        sections.append({"id": "connections", "label": "My Connections", "entries": user_entries})
        return {"sections": sections}

    return await loop.run_in_executor(None, _build_tree)
