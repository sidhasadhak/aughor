"""Catalog tree endpoint."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from aughor.db.connection import open_connection_for
from aughor.db.registry import get_meta

logger = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])


def _as_count(value) -> int | None:
    """A row estimate as a number, or ``None`` when it is genuinely unknown.

    The connector layer stringifies every cell and renders SQL NULL as the literal
    string ``"NULL"``, so an unmeasured count reaches us as text, not as ``None``.
    Unknown has to stay unknown: a table nobody counted reads "—" in the UI, never
    "0 rows". Zero is a measurement and must be reserved for tables that really are
    empty.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "NULL":
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


@router.get("/catalog/tree")
async def get_catalog_tree(workspace_id: str | None = None):
    """Return the full 4-level catalog hierarchy: Section → Catalog → Schema → Table.
    Scoped to `workspace_id`'s connections when given (data-path tenancy)."""
    loop = asyncio.get_running_loop()

    def _quick_schemas(conn_id: str, conn_type: str) -> list[dict] | None:
        """This catalog's schemas, or None when they could not be read at all."""
        try:
            meta = get_meta(conn_id)
            schema_filter = meta.get("schema_name")
            # An uploads connection answers from its FILES — WITHOUT being opened.
            #
            # Its schema and table names live in the upload directory and the per-file
            # sidecars, while OPENING the connection materializes every file into
            # DuckDB: measured at 9.56s of a 9.87s tree locally, 97% of it, spent to
            # learn names that were on disk the whole time. Serverless cold-starts far
            # too often to ever reach the warm cache, so it paid that on every request.
            #
            # The branch is BEFORE `open_connection_for` deliberately — going through
            # the connector at all is what costs, so a listing must never construct one.
            if conn_type == "local_upload":
                from aughor.connectors.file.local_upload import uploaded_tables
                by_schema = uploaded_tables(conn_id, meta)
                if by_schema is not None:      # None → seeded/unreadable, query instead
                    # row_count is None, NOT 0. This path deliberately never opens the
                    # connection (that is the 9.56s it exists to avoid), so the count is
                    # not unavailable-and-therefore-zero — it is simply not measured. The
                    # UI renders None as "—"; a 0 here claimed every uploaded table was
                    # empty.
                    return [
                        {"name": s, "tables": [{"name": t, "row_count": None} for t in sorted(ts)]}
                        for s, ts in sorted(by_schema.items())
                        if not schema_filter or s == schema_filter
                    ]
            db = open_connection_for(conn_id)
            # (schema, table) → measured row estimate. Populated only by the DuckDB
            # branch; empty everywhere else, which leaves those branches' own numbers
            # exactly as they were.
            sizes: dict[tuple[str, str], int | None] = {}
            # local_upload (the Workspace) is DuckDB-backed in memory, so it uses
            # the DuckDB introspection path, not the Postgres one.
            if conn_type in ("duckdb", "local_upload") or getattr(db, "dialect", "") == "duckdb":
                # Primary: INFORMATION_SCHEMA.TABLES is the only reliable cross-database
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
                        SELECT table_schema, table_name, NULL
                        FROM INFORMATION_SCHEMA.TABLES
                        WHERE table_type = 'BASE TABLE'
                          AND table_schema NOT IN ('information_schema','temp','pg_catalog')
                          AND table_catalog = '{safe_db}'
                        ORDER BY table_schema, table_name
                        """,
                    ).rows
                    # information_schema knows the NAMES but carries no row estimate, so
                    # the count comes from duckdb_tables() as a SECOND, best-effort query
                    # rather than a join. Two reasons it is not merged into the query
                    # above: this must never be able to cost us the listing (an engine
                    # without duckdb_tables() still gets its table names), and scoping by
                    # `database_name` is what keeps MotherDuck's cross-database leak out —
                    # the same scope the table_catalog filter applies.
                    #
                    # estimated_size is an estimate by name, but on a checkpointed DuckDB
                    # file it matched COUNT(*) exactly where we measured it
                    # (superstore.orders 9,994). An estimate is the honest number here;
                    # counting 79 tables per catalog request is not affordable.
                    try:
                        for _schema, _table, _size in db.execute(
                            "__catalog__",
                            f"""
                            SELECT schema_name, table_name, estimated_size
                            FROM duckdb_tables()
                            WHERE internal = false
                              AND database_name = '{safe_db}'
                            """,
                        ).rows:
                            sizes[(str(_schema), str(_table))] = _as_count(_size)
                    except Exception as exc:
                        logger.debug(
                            "catalog tree: row estimates unavailable for %s: %s", conn_id, exc
                        )
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
            elif getattr(db, "dialect", "") == "bigquery":
                # BigQuery has no pg_stat_user_tables and its INFORMATION_SCHEMA is
                # dataset-scoped, so the Postgres introspection below can never run
                # there — every BigQuery catalog rendered empty. __TABLES__ is a
                # single free metadata scan and carries a real row count.
                dataset = schema_filter or getattr(db, "_dataset", "")
                if not dataset:
                    # A project-wide connection names no dataset to look in. That is
                    # "could not look", not "nothing there" — never the deleting [].
                    db.close()
                    return None
                rows = db.execute(
                    "__catalog__",
                    f"SELECT dataset_id, table_id, row_count FROM `{dataset}.__TABLES__` ORDER BY table_id",
                ).rows
            else:
                rows = db.execute(
                    "__catalog__",
                    """
                    SELECT
                        t.table_schema,
                        t.table_name,
                        s.n_live_tup
                    FROM INFORMATION_SCHEMA.TABLES t
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
            # The measured estimate wins where we have one; otherwise whatever the
            # branch's own query returned, normalized. Both arrive as strings from the
            # connector, and both may be honestly unknown.
            count = sizes.get((str(schema), str(table_name)), _as_count(row_est))
            schema_map.setdefault(schema, []).append({"name": table_name, "row_count": count})
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
