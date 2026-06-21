"""Connection management — CRUD, schema, settings, files, freshness, process maps."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from aughor.db.connection import open_connection, open_connection_for
from aughor.db.registry import (
    get_dsn,
    BUILTIN_ID,
    add_connection,
    delete_connection,
    get_connection_settings,
    list_connections,
    update_connection_settings,
)
from aughor.routers._shared import (
    explorers as _explorers,
    explorer_tasks as _explorer_tasks,
    get_schema_cached as _get_schema_cached,
    invalidate_schema_cache as _invalidate_schema_cache,
    kickoff_exploration as _kickoff_exploration,
)
from aughor.tools.schema import _norm_type

logger = logging.getLogger(__name__)
router = APIRouter(tags=["connections"])

_INSTRUCTIONS_FILE = Path(__file__).parent.parent.parent / "data" / "instructions.json"


def _load_instructions() -> dict:
    if _INSTRUCTIONS_FILE.exists():
        return json.loads(_INSTRUCTIONS_FILE.read_text())
    return {}


class AddConnectionRequest(BaseModel):
    name: str
    conn_type: str
    dsn: str = ""
    schema_name: Optional[str] = None
    meta: dict = {}


class InstructionsRequest(BaseModel):
    text: str


class _ConnectionSettings(BaseModel):
    ontology_refresh_hours: Optional[int] = None
    briefings_enabled: Optional[bool] = None


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/connections")
def get_connections():
    # Surface each connection's briefings opt-in so the Briefing workspace can list
    # only enabled connections without an N+1 settings fetch. Briefings are opt-OUT:
    # enabled unless explicitly turned off in Catalog.
    conns = list_connections()
    for c in conns:
        s = get_connection_settings(c.get("id", ""))
        c["briefings_enabled"] = s.get("briefings_enabled", True) is not False
    return conns


@router.post("/connections", status_code=201)
async def create_connection(req: AddConnectionRequest):
    combined_meta = {**req.meta}
    if req.schema_name:
        combined_meta["schema_name"] = req.schema_name

    # Test the connection off the event loop — large files (e.g. 8GB DuckDB) can
    # take 60+ seconds to open; blocking here would freeze all HTTP handling.
    loop = asyncio.get_event_loop()
    try:
        def _test():
            db = open_connection(req.conn_type, req.dsn, schema_name=req.schema_name, meta=combined_meta)
            ok, msg = db.test()
            db.close()
            return ok, msg
        ok, msg = await loop.run_in_executor(None, _test)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")
    if not ok:
        raise HTTPException(status_code=400, detail=f"Connection test failed: {msg}")

    conn_id = add_connection(name=req.name, conn_type=req.conn_type, dsn=req.dsn, meta=combined_meta)

    # Auto-onboarding: kick off schema exploration in the background so a brand-new
    # connection becomes intelligent without a manual step. It's non-blocking (the
    # heavy work runs as a background task), visible via GET /exploration/{id}/status,
    # and cancellable via POST /exploration/{id}/stop.
    explorer_started = False
    try:
        explorer_started = _kickoff_exploration(conn_id, auto=True)
    except Exception:
        logger.warning("create_connection: explorer kickoff failed for %s", conn_id, exc_info=True)

    return {
        "id": conn_id,
        "message": "Connection added",
        "test_result": msg,
        "exploring": explorer_started,
    }


@router.post("/connections/{conn_id}/test")
async def test_connection(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        def _test():
            db = open_connection_for(conn_id)
            ok, msg = db.test()
            db.close()
            return ok, msg
        ok, msg = await loop.run_in_executor(None, _test)
        return {"ok": ok, "message": msg}
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.delete("/connections/{conn_id}", status_code=204)
def remove_connection(conn_id: str):
    explorer = _explorers.pop(conn_id, None)
    task = _explorer_tasks.pop(conn_id, None)
    if explorer:
        explorer.stop()
    if task and not task.done():
        task.cancel()
    # Cancel every kernel job in this scope — including canvas explorations
    # running on this connection, which the registry pops above don't cover.
    try:
        from aughor.kernel.jobs import kernel
        kernel().cancel_scope(conn_id=conn_id)
    except Exception:
        logger.warning("Could not cancel kernel jobs for deleted connection %s",
                       conn_id, exc_info=True)
    _invalidate_schema_cache(conn_id)
    try:
        delete_connection(conn_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")


# ── Schema ────────────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}/schema")
async def connection_schema(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        def _work():
            s = _get_schema_cached(conn_id, db)
            db.close()
            return s
        schema = await loop.run_in_executor(None, _work)
        return {"schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connections/{conn_id}/schema/refresh")
async def refresh_schema_cache(conn_id: str):
    """Bust the server-side schema cache for a connection and return the fresh schema."""
    _invalidate_schema_cache(conn_id)
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        def _work():
            s = _get_schema_cached(conn_id, db)
            db.close()
            return s
        schema = await loop.run_in_executor(None, _work)
        return {"ok": True, "schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connections/{conn_id}/schema/rich")
async def connection_schema_rich(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        from aughor.tools.schema import build_rich_schema
        from aughor.db.type_overrides import get_table_overrides
        def _work():
            s = _get_schema_cached(conn_id, db)
            db.close()
            result = build_rich_schema(s)
            # Apply user type overrides so the rich schema stays in sync
            for table in result.get("tables", []):
                tname = table.get("name", "")
                overrides = get_table_overrides(conn_id, tname)
                if overrides:
                    for col in table.get("columns", []):
                        if col.get("name") in overrides:
                            col["type"] = overrides[col["name"]]
            return result
        return await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connections/{conn_id}/schema/mermaid")
async def connection_schema_mermaid(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        from aughor.tools.schema import build_mermaid_er
        def _work():
            s = _get_schema_cached(conn_id, db)
            db.close()
            return {"diagram": build_mermaid_er(s)}
        return await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Schema profile ────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}/schema/profile")
async def connection_schema_profile(conn_id: str):
    """Return cached column/table profiles for the Schema Shape tab."""
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        from aughor.tools.schema import _parse_schema_tables
        from aughor.tools.profile_cache import compute_schema_fingerprint, load_profiles

        def _work():
            schema_str = _get_schema_cached(conn_id, db)
            table_cols = _parse_schema_tables(schema_str)
            col_counts = {t: len(cols) for t, cols in table_cols.items()}
            fingerprint = compute_schema_fingerprint(col_counts)
            result = load_profiles(conn_id, fingerprint)
            db.close()
            return result

        cached = await loop.run_in_executor(None, _work)
        if cached is None:
            return {"available": False, "tables": [], "columns": []}
        table_profiles, column_profiles = cached
        return {
            "available": True,
            "tables": [tp.to_dict() for tp in table_profiles.values()],
            "columns": [cp.to_dict() for cp in column_profiles.values()],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Freshness ─────────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}/freshness")
async def connection_freshness(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    def _work():
        from aughor.tools.schema import _parse_schema_tables
        _DATE_PAT = re.compile(
            r"(_at|_date|_time|_ts|timestamp|created|updated|modified|inserted)$",
            re.IGNORECASE,
        )
        try:
            schema_str = db.get_schema()
            table_cols = _parse_schema_tables(schema_str)
        except Exception:
            db.close()
            return {"freshness": None, "source": None}

        max_ts: str | None = None
        max_source: str | None = None
        for table, cols in list(table_cols.items())[:12]:
            date_cols = [c for c in cols if _DATE_PAT.search(c)][:1]
            for col in date_cols:
                try:
                    result = db.execute("freshness", f'SELECT MAX("{col}") AS max_ts FROM "{table}"')
                    if not result.error and result.rows and result.rows[0][0] not in (None, "NULL"):
                        val = str(result.rows[0][0])
                        if max_ts is None or val > max_ts:
                            max_ts = val
                            max_source = f"{table}.{col}"
                except Exception:
                    continue
        db.close()
        return {"freshness": max_ts, "source": max_source}

    return await loop.run_in_executor(None, _work)


# ── Table sample ──────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}/tables/{table}/sample")
async def table_sample(conn_id: str, table: str, limit: int = 100, schema: str = ""):
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    safe_table  = table.replace('"', '').replace(';', '')
    safe_schema = schema.replace('"', '').replace(';', '') if schema else ""
    ref = f'"{safe_schema}"."{safe_table}"' if safe_schema else f'"{safe_table}"'
    _limit = int(limit)

    def _work():
        db = None
        try:
            db = open_connection_for(conn_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Connection not found")
        try:
            result = db.execute("sample", f"SELECT * FROM {ref} LIMIT {_limit}")
            error = result.error
            if error and getattr(db, "_seed_failed", None):
                # A failed seed materialization presents as "table does not exist" —
                # surface the real cause instead of a bare binder error.
                error = f"{error} (sample seed problem: {db._seed_failed})"
            columns = result.columns
            rows = [[str(v) if v is not None else None for v in row] for row in result.rows]
            return {"columns": columns, "rows": rows, "row_count": len(rows), "error": error}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    return await loop.run_in_executor(None, _work)


@router.get("/connections/{conn_id}/tables/{table}/columns")
async def table_columns(conn_id: str, table: str, schema: str = ""):
    """Reliable per-table column list (name + type) via a direct query — the
    same lightweight path as the sample reader, so Overview and Sample Data stay
    in sync even when the heavy whole-connection rich schema is unavailable."""
    loop = asyncio.get_event_loop()
    safe_table = table.replace('"', "").replace(";", "")
    safe_schema = schema.replace('"', "").replace(";", "") if schema else ""
    ref = f'"{safe_schema}"."{safe_table}"' if safe_schema else f'"{safe_table}"'

    def _work():
        db = None
        try:
            db = open_connection_for(conn_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Connection not found")
        try:
            # For DuckDB we can use raw_execute to bypass _validate (which rejects
            # DESCRIBE / PRAGMA) and avoid thread-safety issues by creating db in-thread.
            from aughor.db.type_overrides import apply_overrides
            # DuckDB-like connectors (including LocalUploadConnection) have dialect=duckdb
            # and raw_execute to bypass validation for DESCRIBE / PRAGMA.
            if getattr(db, 'dialect', '') == 'duckdb' and hasattr(db, 'raw_execute'):
                # 1. DESCRIBE is the most reliable path for DuckDB/MotherDuck — it always
                # returns concrete types (INTEGER, VARCHAR, TIMESTAMP, etc.) and works
                # across attached databases, in-memory, and remote MotherDuck.
                try:
                    columns, rows, _ = db.raw_execute(f"DESCRIBE {ref}")
                    if rows:
                        cols = [{"name": r[0], "type": _norm_type(str(r[1]))} for r in rows]
                        return {"columns": apply_overrides(conn_id, safe_table, cols)}
                except Exception:
                    pass
                # 2. PRAGMA table_info — SQLite-native, works everywhere DuckDB works.
                try:
                    columns, rows, _ = db.raw_execute(f"PRAGMA table_info({ref})")
                    if rows:
                        cols = [{"name": r[1], "type": _norm_type(str(r[2]))} for r in rows]
                        return {"columns": apply_overrides(conn_id, safe_table, cols)}
                except Exception:
                    pass
                # 3. information_schema.columns with current_database filter — standard SQL,
                # but MotherDuck sometimes returns empty data_type here, so we only use it
                # if it actually yields types.
                try:
                    where = f"table_name = '{safe_table}'"
                    if safe_schema:
                        where += f" AND table_schema = '{safe_schema}'"
                    _, db_rows, _ = db.raw_execute("SELECT current_database()")
                    if db_rows:
                        current_db = str(db_rows[0][0]).replace("'", "''")
                        where += f" AND table_catalog = '{current_db}'"
                    columns, rows, _ = db.raw_execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        f"WHERE {where} ORDER BY ordinal_position"
                    )
                    if rows:
                        cols = [{"name": r[0], "type": _norm_type(str(r[1]) if r[1] is not None else "")} for r in rows]
                        if any(c["type"] for c in cols):
                            return {"columns": apply_overrides(conn_id, safe_table, cols)}
                except Exception:
                    pass
                # 3b. information_schema.columns WITHOUT table_catalog filter.
                try:
                    where = f"table_name = '{safe_table}'"
                    if safe_schema:
                        where += f" AND table_schema = '{safe_schema}'"
                    columns, rows, _ = db.raw_execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        f"WHERE {where} ORDER BY ordinal_position"
                    )
                    if rows:
                        cols = [{"name": r[0], "type": _norm_type(str(r[1]) if r[1] is not None else "")} for r in rows]
                        if any(c["type"] for c in cols):
                            return {"columns": apply_overrides(conn_id, safe_table, cols)}
                except Exception:
                    pass
                # 4. Final fallback: empty SELECT — use cursor description to recover types.
                try:
                    columns, rows, types = db.raw_execute(f"SELECT * FROM {ref} LIMIT 0")
                    cols = [{"name": c, "type": _norm_type(t) or ""} for c, t in zip(columns, types)]
                    return {"columns": apply_overrides(conn_id, safe_table, cols)}
                except Exception:
                    pass
            else:
                # Non-DuckDB path: use standard execute (which validates SQL)
                try:
                    where = f"table_name = '{safe_table}'"
                    if safe_schema:
                        where += f" AND table_schema = '{safe_schema}'"
                    res = db.execute(
                        "columns",
                        "SELECT column_name, data_type FROM information_schema.columns "
                        f"WHERE {where} ORDER BY ordinal_position",
                    )
                    if res.rows:
                        cols = [{"name": r[0], "type": _norm_type(str(r[1]))} for r in res.rows]
                        return {"columns": apply_overrides(conn_id, safe_table, cols)}
                except Exception:
                    pass
                try:
                    res = db.execute("columns", f"SELECT * FROM {ref} LIMIT 0")
                    cols = [{"name": c, "type": ""} for c in res.columns]
                    return {"columns": apply_overrides(conn_id, safe_table, cols)}
                except Exception:
                    pass
            return {"columns": []}
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    return await loop.run_in_executor(None, _work)




class _AlterColumnRequest(BaseModel):
    column: str
    new_type: str


@router.post("/connections/{conn_id}/tables/{table}/alter-column")
async def alter_table_column(conn_id: str, table: str, body: _AlterColumnRequest, schema: str = ""):
    """Alter the type of a single column. Best-effort for DuckDB/SQLite connectors."""
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    safe_table = table.replace('"', "").replace(";", "")
    safe_schema = schema.replace('"', "").replace(";", "") if schema else ""
    safe_col = body.column.replace('"', "").replace(";", "")
    safe_type = body.new_type.replace(";", "")  # basic sanitisation
    ref = f'"{safe_schema}"."{safe_table}"' if safe_schema else f'"{safe_table}"'

    from aughor.db.type_overrides import set_override
    set_override(conn_id, safe_table, safe_col, safe_type)
    _invalidate_schema_cache(conn_id)

    # Invalidate Qdrant investigation cache for this connection so old cached
    # SQL (generated before the type change) is not replayed.
    try:
        from aughor.tools.prior_analyses import INVESTIGATIONS_COLLECTION
        from aughor.semantic.vector_store import delete_by_filter
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        filt = Filter(
            must=[FieldCondition(key="connection_id", match=MatchValue(value=conn_id))]
        )
        deleted = delete_by_filter(INVESTIGATIONS_COLLECTION, filt)
        if deleted:
            print(f"[alter_column] cleared {deleted} cached investigations for {conn_id}")
    except Exception:
        pass

    # For local_upload connections, update the sidecar so the type is applied
    # on next load (each request creates a fresh in-memory DB from sidecars).
    conn_type, _ = get_dsn(conn_id)
    if conn_type == "local_upload":
        from aughor.connectors.file.local_upload import _UPLOAD_ROOT, _SIDECAR_SUFFIX, _safe_ident
        upload_dir = _UPLOAD_ROOT / (conn_id or "default")
        schema_dir = upload_dir / _safe_ident(safe_schema or "main", "main")
        if schema_dir.exists():
            for f in schema_dir.iterdir():
                if not f.is_file() or f.name.endswith(_SIDECAR_SUFFIX):
                    continue
                sc = f.with_name(f"{f.name}{_SIDECAR_SUFFIX}")
                if sc.exists():
                    try:
                        cfg = json.loads(sc.read_text())
                        if cfg.get("table_name") == safe_table:
                            cfg.setdefault("column_types", {})[safe_col] = safe_type
                            sc.write_text(json.dumps(cfg, indent=2))
                            break
                    except Exception:
                        pass

    def _work():
        try:
            # DuckDB syntax (best-effort; many connectors don't support ALTER COLUMN TYPE)
            sql = f'ALTER TABLE {ref} ALTER COLUMN "{safe_col}" TYPE {safe_type}'
            db.execute("alter_column", sql)
            return {
                "ok": True, "applied": True, "override_only": False, "sql": sql,
                "message": f"Column {safe_col} changed to {safe_type}.",
            }
        except Exception as e:
            # For local_upload, the sidecar column_types were updated above, so the
            # table is genuinely recreated with the new type on the next connection
            # open. Re-register the file in the current ephemeral DB so it takes
            # effect immediately too. This is a REAL type change.
            if conn_type == "local_upload":
                try:
                    from aughor.connectors.file.local_upload import LocalUploadConnection
                    if isinstance(db, LocalUploadConnection):
                        schema_dir = db._schema_dir(safe_schema or "main")
                        for f in schema_dir.iterdir():
                            if not f.is_file() or f.name.endswith(_SIDECAR_SUFFIX):
                                continue
                            sc = f.with_name(f"{f.name}{_SIDECAR_SUFFIX}")
                            if sc.exists():
                                cfg = json.loads(sc.read_text())
                                if cfg.get("table_name") == safe_table:
                                    db._register_file(f, safe_table, safe_schema or "main", cfg.get("column_types", {}))
                                    break
                    return {
                        "ok": True, "applied": True, "override_only": False, "sql": None,
                        "message": f"Column {safe_col} changed to {safe_type} (applied on reload).",
                    }
                except Exception:
                    logger.warning("local_upload type recreation failed for %s.%s", safe_table, safe_col, exc_info=True)
            # Other connectors: ALTER is unsupported and we cannot rewrite the source.
            # We saved a DISPLAY-ONLY override (catalog shows the new type) but the
            # underlying column type is unchanged and queries still use the real type.
            # Be honest about this — do NOT claim the column was changed.
            return {
                "ok": True, "applied": False, "override_only": True, "sql": None,
                "error": str(e),
                "message": (
                    f"Saved a display override: the catalog will show {safe_col} as {safe_type}, "
                    f"but this connector does not support changing the column type, so the database "
                    f"column is unchanged and queries still use its real type."
                ),
            }
        finally:
            try:
                db.close()
            except Exception:
                pass

    return await loop.run_in_executor(None, _work)

# ── Instructions ──────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}/instructions")
def get_instructions(conn_id: str):
    data = _load_instructions()
    return {"text": data.get(conn_id, {}).get("text", "")}


@router.put("/connections/{conn_id}/instructions")
def put_instructions(conn_id: str, req: InstructionsRequest):
    data = _load_instructions()
    data.setdefault(conn_id, {})["text"] = req.text
    _INSTRUCTIONS_FILE.write_text(json.dumps(data, indent=2))
    return {"ok": True}


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/connections/{conn_id}/settings")
def get_conn_settings(conn_id: str):
    return get_connection_settings(conn_id)


@router.put("/connections/{conn_id}/settings")
def put_conn_settings(conn_id: str, body: _ConnectionSettings):
    # Merge only the fields the caller actually sent (partial update) so toggling one
    # setting — e.g. briefings_enabled — never clobbers another (ontology_refresh_hours).
    return update_connection_settings(conn_id, body.model_dump(exclude_unset=True))


# ── Files (local_upload connector) ────────────────────────────────────────────

def _open_file_connector(conn_id: str, need: str):
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not hasattr(db, need):
        raise HTTPException(status_code=400, detail="Connection is not a file connector")
    return db


def _stage_upload(file: UploadFile):
    """Write an UploadFile to a temp dir under its original name; return (tmp_dir, tmp_path)."""
    import shutil, tempfile
    original = Path(file.filename or "upload.csv").name
    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / original
    with tmp_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return tmp_dir, tmp_path


@router.post("/connections/{conn_id}/files/analyze")
async def analyze_connection_file(conn_id: str, file: UploadFile = File(...)):
    """Inspect a file (columns, inferred types, type-mismatch suggestions, preview)
    without ingesting it — drives the import review UI."""
    import shutil
    db = _open_file_connector(conn_id, "analyze_file")
    tmp_dir, tmp_path = _stage_upload(file)
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: db.analyze_file(tmp_path))
        info["filename"] = tmp_path.name
        return info
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Analyze failed: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/connections/{conn_id}/files", status_code=201)
async def upload_file_to_connection(
    conn_id: str,
    file: UploadFile = File(...),
    table_name: Optional[str] = Form(None),
    schema: Optional[str] = Form(None),
    column_types: Optional[str] = Form(None),
):
    """Ingest a file as a table. Optional table_name, schema, and column_types
    (a JSON object mapping column → cast type) configure the import."""
    import shutil
    db = _open_file_connector(conn_id, "ingest_file")
    types: dict = {}
    if column_types:
        try:
            parsed = json.loads(column_types)
            if isinstance(parsed, dict):
                types = parsed
        except Exception:
            raise HTTPException(status_code=400, detail="column_types must be valid JSON")
    tmp_dir, tmp_path = _stage_upload(file)
    try:
        loop = asyncio.get_event_loop()
        tname = await loop.run_in_executor(
            None,
            lambda: db.ingest_file(
                tmp_path,
                table_name=(table_name or None),
                schema=(schema or "main"),
                column_types=types,
            ),
        )
        return {
            "table_name": tname,
            "schema": schema or "main",
            "filename": tmp_path.name,
            "message": "File ingested",
        }
    except TypeError:
        # Connector without the extended signature — fall back to plain ingest.
        tname = await asyncio.get_event_loop().run_in_executor(
            None, lambda: db.ingest_file(tmp_path, table_name=(table_name or None))
        )
        return {"table_name": tname, "filename": tmp_path.name, "message": "File ingested"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ingestion failed: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/connections/{conn_id}/files")
async def list_connection_files(conn_id: str):
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not hasattr(db, "list_files"):
        return {"files": []}
    return {"files": await loop.run_in_executor(None, db.list_files)}


@router.delete("/connections/{conn_id}/files/{filename}", status_code=200)
async def delete_connection_file(conn_id: str, filename: str, schema: str = "main"):
    loop = asyncio.get_event_loop()
    def _delete():
        try:
            db = open_connection_for(conn_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Connection not found")
        if not hasattr(db, "delete_file"):
            raise HTTPException(status_code=400, detail="Not a file connector")
        try:
            db.delete_file(filename, schema)
        except TypeError:
            db.delete_file(filename)
        db.close()
    await loop.run_in_executor(None, _delete)
    return {"message": f"File '{filename}' removed"}


@router.get("/connections/{conn_id}/schemas")
async def list_connection_schemas(conn_id: str):
    loop = asyncio.get_event_loop()
    def _work():
        db = _open_file_connector(conn_id, "list_schemas")
        result = db.list_schemas()
        db.close()
        return result
    return {"schemas": await loop.run_in_executor(None, _work)}


class _SchemaCreate(BaseModel):
    name: str


@router.post("/connections/{conn_id}/schemas", status_code=201)
async def create_connection_schema(conn_id: str, body: _SchemaCreate):
    loop = asyncio.get_event_loop()
    db = _open_file_connector(conn_id, "create_schema")
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Schema name is required")
    schema = await loop.run_in_executor(None, lambda: db.create_schema(name))
    return {"schema": schema, "message": "Schema created"}


def _purge_schema_artifacts(conn_id: str, schema: str) -> None:
    """Delete the derived intelligence for a (connection, schema) so a removed schema
    leaves no stale profile/exploration behind in the Briefing/KPI strip. Best-effort."""
    from aughor.kernel.errors import tolerate
    try:
        from aughor.profile import store as _pstore
        _pstore.invalidate(conn_id, schema)
    except Exception as e:
        tolerate(e, "remove-schema: profile invalidate", counter="schema.remove.profile")
    import re as _re
    from pathlib import Path as _Path
    safe = lambda s: _re.sub(r"[^A-Za-z0-9._-]", "_", s)  # noqa: E731
    for pat in (f"exploration_{safe(conn_id)}__{safe(schema)}.json",
                f"episodes_{safe(conn_id)}__{safe(schema)}.jsonl"):
        try:
            p = _Path("data") / pat
            if p.exists():
                p.unlink()
        except Exception as e:
            tolerate(e, "remove-schema: artifact unlink", counter="schema.remove.artifact")


@router.delete("/connections/{conn_id}/schemas/{schema}", status_code=200)
async def delete_connection_schema(conn_id: str, schema: str):
    """Remove a whole schema from a workspace connection — drops its DuckDB schema +
    every backing upload file, then purges the schema's derived profile/exploration."""
    loop = asyncio.get_event_loop()
    def _work():
        db = _open_file_connector(conn_id, "drop_schema")
        if not hasattr(db, "drop_schema"):
            raise HTTPException(status_code=400, detail="Not a file connector")
        try:
            db.drop_schema(schema)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        finally:
            db.close()
    await loop.run_in_executor(None, _work)
    _purge_schema_artifacts(conn_id, schema)
    return {"message": f"Schema '{schema}' removed"}


@router.delete("/connections/{conn_id}/tables/{table}", status_code=200)
async def delete_connection_table(conn_id: str, table: str, schema: str = "main"):
    """Remove a single table from a workspace connection — drops it from DuckDB and
    deletes its backing upload file(s)."""
    loop = asyncio.get_event_loop()
    def _work():
        db = _open_file_connector(conn_id, "delete_table")
        if not hasattr(db, "delete_table"):
            raise HTTPException(status_code=400, detail="Not a file connector")
        try:
            db.delete_table(table, schema)
        finally:
            db.close()
    await loop.run_in_executor(None, _work)
    return {"message": f"Table '{table}' removed"}


# ── Process map + causal graph ────────────────────────────────────────────────

@router.get("/connections/{conn_id}/process-map/{entity_id}")
def get_process_map(conn_id: str, entity_id: str):
    try:
        from aughor.process.mapper import build_process_map
        return build_process_map(entity_id, conn_id).model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("process_map failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connections/{conn_id}/causal-graph")
def get_causal_graph(conn_id: str):
    from aughor.process.causal import load_causal_graph
    return [e.model_dump() for e in load_causal_graph(conn_id)]
