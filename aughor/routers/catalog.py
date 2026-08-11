"""Catalog tree endpoint."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from aughor.db.connection import open_connection_for
from aughor.db.registry import get_meta

logger = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])


@router.get("/catalog/tree")
async def get_catalog_tree(workspace_id: str | None = None):
    """Return the full 4-level catalog hierarchy: Section → Catalog → Schema → Table.
    Scoped to `workspace_id`'s connections when given (data-path tenancy)."""
    loop = asyncio.get_running_loop()

    def _quick_schemas(conn_id: str, conn_type: str) -> list[dict] | None:
        """This catalog's schemas, or None when they could not be read at all."""
        try:
            db = open_connection_for(conn_id)
            meta = get_meta(conn_id)
            schema_filter = meta.get("schema_name")
            # local_upload (the Workspace) is DuckDB-backed in memory, so it uses
            # the DuckDB introspection path, not the Postgres one.
            if conn_type in ("duckdb", "local_upload") or getattr(db, "dialect", "") == "duckdb":
                # Primary: information_schema.tables is the only reliable cross-database
                # view in MotherDuck — duckdb_tables() leaks tables from ALL attached DBs.
                # We filter by the current database so the catalog matches the connection scope.
                rows: list = []
                current_db = ""
                try:
                    # Use db.execute (not db._conn) so this works for LocalUploadConnection too.
                    res = db.execute("__catalog__", "SELECT current_database()")
                    if res.rows:
                        current_db = str(res.rows[0][0])
                except Exception:
                    pass
                if current_db:
                    safe_db = current_db.replace("'", "''")
                    rows = db.execute(
                        "__catalog__",
                        f"""
                        SELECT table_schema, table_name, 0
                        FROM information_schema.tables
                        WHERE table_type = 'BASE TABLE'
                          AND table_schema NOT IN ('information_schema','temp','pg_catalog')
                          AND table_catalog = '{safe_db}'
                        ORDER BY table_schema, table_name
                        """,
                    ).rows
                # Fallback to duckdb_tables() for local DuckDB files when information_schema
                # is somehow unavailable.
                if not rows:
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
            # If schema_name is configured for this connection, filter to that schema only.
            if schema_filter and rows:
                rows = [r for r in rows if r[0] == schema_filter]
            db.close()
        except Exception as exc:
            # None, NOT [] — the caller reconciles the metastore to whatever comes
            # back, and an empty list means "this catalog has no schemas", which
            # DELETES every schema row it has. "I could not look" and "there is
            # nothing there" are different answers and must not share a value.
            logger.debug("catalog tree: schema query failed for %s: %s", conn_id, exc)
            return None

        schema_map: dict[str, list] = {}
        for schema, table_name, row_est in rows:
            schema_map.setdefault(schema, []).append({"name": table_name, "row_count": row_est})
        return [{"name": s, "tables": t} for s, t in schema_map.items()]

    def _build_tree() -> dict:
        from aughor.db.registry import list_connections
        from aughor.metastore import accessible_catalog_ids

        # Data-path tenancy gate, now resolved through the metastore (grants).
        allowed = accessible_catalog_ids(workspace_id)
        # Single catalog list. The Workspace (which now folds in the sample
        # ecommerce tables) is returned first by list_connections.
        entries = []
        for conn_info in list_connections():
            cid = conn_info["id"]
            if allowed is not None and cid not in allowed:
                continue  # not in the active workspace — don't surface its schema
            introspected = _quick_schemas(cid, conn_info.get("conn_type", "duckdb"))
            schemas = introspected or []
            # Keep the metastore's first-class Schema rows tracking live introspection
            # (catalog.schema namespace). Best-effort — never break the tree build.
            #
            # SKIPPED when introspection FAILED, because this reconcile deletes: a
            # connection that could not be opened used to report zero schemas, and
            # this call then removed every schema row the catalog had. A GET that
            # destroys metadata whenever a database blinks is not a read. The next
            # successful request re-inserted them, so the damage showed up as write
            # churn rather than as an error — store_metastore had 1701 writes in
            # production against single digits for every other store.
            if introspected is not None:
                try:
                    from aughor.metastore import set_catalog_schemas
                    set_catalog_schemas(cid, [s["name"] for s in schemas])
                except Exception as exc:
                    from aughor.kernel.errors import tolerate
                    tolerate(exc, "metastore schema sync", counter="metastore.schema_sync")
            entries.append({
                "conn_id": cid,
                "name": conn_info["name"],
                "conn_type": conn_info.get("conn_type", ""),
                "builtin": conn_info.get("builtin", False),
                "schemas": schemas,
            })

        return {"sections": [{"id": "connections", "label": "Catalogs", "entries": entries}]}

    return await loop.run_in_executor(None, _build_tree)
