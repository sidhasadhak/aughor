"""Connection management — CRUD, schema, settings, files, freshness, process maps."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from aughor.db.connection import open_connection, open_connection_for
from aughor.db.registry import (
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
)

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


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/connections")
def get_connections():
    return list_connections()


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

    # Fire explorer as a non-blocking background task — same pattern as startup.
    # Returns immediately; DB open + explore() run off the event loop.
    try:
        from aughor.api import _boot_explorer
        asyncio.create_task(_boot_explorer(conn_id, retry_interval=10, max_retries=3), name=f"boot-{conn_id}")
    except Exception as exc:
        logger.warning("Could not start explorer for new connection %s: %s", conn_id, exc)

    return {"id": conn_id, "message": "Connection added", "test_result": msg}


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
        schema = await loop.run_in_executor(None, lambda: _get_schema_cached(conn_id, db))
        db.close()
        return {"schema": schema}
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
        def _work():
            s = _get_schema_cached(conn_id, db)
            db.close()
            return build_rich_schema(s)
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
            return load_profiles(conn_id, fingerprint)

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
    finally:
        db.close()


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
        try:
            result = db.execute("sample", f"SELECT * FROM {ref} LIMIT {_limit}")
            columns = result.columns
            rows = [[str(v) if v is not None else None for v in row] for row in result.rows]
            return {"columns": columns, "rows": rows}
        finally:
            try:
                db.close()
            except Exception:
                pass

    try:
        return await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    return update_connection_settings(conn_id, body.model_dump(exclude_none=False))


# ── Files (local_upload connector) ────────────────────────────────────────────

@router.post("/connections/{conn_id}/files", status_code=201)
async def upload_file_to_connection(conn_id: str, file: UploadFile = File(...)):
    import shutil, tempfile
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not hasattr(db, "ingest_file"):
        raise HTTPException(status_code=400, detail="Connection is not a file connector")
    suffix = Path(file.filename or "upload.csv").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        table_name = db.ingest_file(tmp_path, table_name=None)
        return {"table_name": table_name, "filename": file.filename, "message": "File ingested"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ingestion failed: {e}")
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
    db.close()


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
async def delete_connection_file(conn_id: str, filename: str):
    loop = asyncio.get_event_loop()
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    if not hasattr(db, "delete_file"):
        raise HTTPException(status_code=400, detail="Not a file connector")
    await loop.run_in_executor(None, lambda: db.delete_file(filename))
    return {"message": f"File '{filename}' removed"}


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
