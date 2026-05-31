"""Query runner and visual query builder endpoints."""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["query"])


class _QueryRunRequest(BaseModel):
    conn_id: str
    sql: str
    limit: int = 500
    use_cache: bool = False
    use_bulk: bool = False


@router.post("/query/run")
async def query_run(body: _QueryRunRequest):
    """Execute a SQL query against a registered connection."""
    import time as _t
    from aughor.db.connection import open_connection_for

    if not body.sql.strip():
        raise HTTPException(status_code=400, detail="sql is required")

    if body.use_cache:
        from aughor.db.matcache import get_cached
        cached = get_cached(body.conn_id, body.sql)
        if cached is not None:
            return {
                "columns": cached.columns,
                "rows": cached.rows,
                "row_count": cached.row_count,
                "duration_ms": 0.0,
                "sql": cached.sql,
                "cached": True,
                "error": None,
            }

    try:
        db = open_connection_for(body.conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    _sql_to_run = body.sql
    _use_bulk   = body.use_bulk
    _limit      = body.limit

    def _work():
        t0 = _t.monotonic()
        try:
            if _use_bulk:
                result = db.bulk_read(_sql_to_run, limit=_limit)
            else:
                sql = _sql_to_run.strip().rstrip(";")
                if _limit > 0:
                    sql = f"SELECT * FROM ({sql}) __q LIMIT {_limit}"
                result = db.execute("__querybuilder__", sql)
        finally:
            try:
                db.close()
            except Exception:
                pass
        return result, (_t.monotonic() - t0) * 1000

    loop = asyncio.get_event_loop()
    try:
        result, duration_ms = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if body.use_cache and not result.error:
        from aughor.db.matcache import put_cache
        put_cache(body.conn_id, body.sql, result)

    return {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "duration_ms": round(duration_ms, 1),
        "sql": result.sql,
        "cached": False,
        "error": result.error,
    }


class _MeasureDef(BaseModel):
    expr: str
    alias: str = ""


class _FilterDef(BaseModel):
    col: str
    op: str
    val: str = ""


class _QueryBuildRequest(BaseModel):
    table: str
    dimensions: list[str] = []
    measures: list[_MeasureDef] = []
    filters: list[_FilterDef] = []
    order_by: str = ""
    limit: int = 1000


@router.post("/query/build-sql")
def query_build_sql(body: _QueryBuildRequest):
    """Build a SELECT statement from visual query builder parameters."""
    select_parts: list[str] = list(body.dimensions)
    for m in body.measures:
        alias = m.alias or re.sub(r"[^a-zA-Z0-9_]", "_", m.expr).lower()[:40]
        select_parts.append(f"{m.expr} AS {alias}")
    select_clause = ",\n  ".join(select_parts) if select_parts else "*"

    where_parts: list[str] = []
    for f in body.filters:
        if f.op in ("IS NULL", "IS NOT NULL"):
            where_parts.append(f"{f.col} {f.op}")
        elif f.val:
            where_parts.append(f"{f.col} {f.op} {f.val}")
    _and = "\n  AND "
    where_clause = f"WHERE {_and.join(where_parts)}" if where_parts else ""

    _AGG_RE = re.compile(r"\b(SUM|COUNT|AVG|MIN|MAX|STDDEV|VARIANCE|MEDIAN)\s*\(", re.I)
    has_agg = any(_AGG_RE.search(m.expr) for m in body.measures)
    group_by = (
        f"GROUP BY {', '.join(body.dimensions)}"
        if body.dimensions and has_agg
        else ""
    )
    order_by = f"ORDER BY {body.order_by}" if body.order_by else ""

    lines = [f"SELECT", f"  {select_clause}", f"FROM {body.table}"]
    if where_clause:
        lines.append(where_clause)
    if group_by:
        lines.append(group_by)
    if order_by:
        lines.append(order_by)
    if body.limit > 0:
        lines.append(f"LIMIT {body.limit}")

    return {"sql": "\n".join(lines)}


@router.get("/query/cache/stats")
def query_cache_stats():
    """Return materialization cache statistics."""
    from aughor.db.matcache import cache_stats
    return cache_stats()


@router.delete("/query/cache/{conn_id}", status_code=200)
def query_cache_invalidate(conn_id: str):
    """Invalidate all cached query results for a connection."""
    from aughor.db.matcache import invalidate
    invalidate(conn_id)
    return {"ok": True, "conn_id": conn_id}
