"""Query runner and visual query builder endpoints."""
from __future__ import annotations

import asyncio
import re
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aughor.licensing import Capability, gate

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


# ── Semantic operators over SQL result text ────────────────────────────────────
# Run an LLM operator (filter / extract / top_k / aggregate) over ONE text column of a SQL result
# set — the unstructured residue SQL can't reason over (tickets, reviews, notes). SQL does the
# structured push-down first; the LLM only touches the small text residue. Cost is bounded by
# push-down + an explicit per-operator row cap (refuse over the cap, surfaced). See aughor/semops.

class _ExtractFieldReq(BaseModel):
    name: str
    description: str = ""


class _SemanticOpRequest(BaseModel):
    conn_id: str
    sql: str
    operator: Literal["filter", "extract", "top_k", "aggregate"]
    column: str
    predicate: Optional[str] = None          # required for filter
    fields: list[_ExtractFieldReq] = []      # required for extract
    criterion: Optional[str] = None          # required for top_k
    k: int = 10                              # top_k: how many rows to keep
    instruction: Optional[str] = None        # required for aggregate
    out_column: str = "answer"               # aggregate: name of the synthesized column
    limit: int = 500
    max_rows: int = 200
    override_cap: bool = False


def _wrap_limited(sql: str, limit: int) -> str:
    sql = sql.strip().rstrip(";")
    lim = limit if limit > 0 else 500
    return f"SELECT * FROM ({sql}) __q LIMIT {lim}"


@router.post("/query/semantic", dependencies=[gate(Capability.SEMANTIC_OPERATORS)])
async def query_semantic(body: _SemanticOpRequest):
    """Apply a semantic operator (filter / extract / top_k / aggregate over a text column) to a result.

    Re-runs the SQL server-side (authoritative — never trusts client-sent rows), then applies the
    operator to the text residue. Returns the transformed result plus surfaced operator metadata."""
    from aughor.db.connection import open_connection_for
    from aughor.semops.operators import apply_step

    if not body.sql.strip():
        raise HTTPException(status_code=400, detail="sql is required")
    if not body.column.strip():
        raise HTTPException(status_code=400, detail="column is required")
    if body.operator == "filter" and not (body.predicate or "").strip():
        raise HTTPException(status_code=400, detail="predicate is required for the filter operator")
    if body.operator == "extract" and not body.fields:
        raise HTTPException(status_code=400, detail="fields is required for the extract operator")
    if body.operator == "top_k" and not (body.criterion or "").strip():
        raise HTTPException(status_code=400, detail="criterion is required for the top_k operator")
    if body.operator == "top_k" and body.k < 1:
        raise HTTPException(status_code=400, detail="k must be >= 1 for the top_k operator")
    if body.operator == "aggregate" and not (body.instruction or "").strip():
        raise HTTPException(status_code=400, detail="instruction is required for the aggregate operator")

    try:
        db = open_connection_for(body.conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    wrapped = _wrap_limited(body.sql, body.limit)

    def _work():
        try:
            base = db.execute("__semantic__", wrapped)
        finally:
            try:
                db.close()
            except Exception as _e:
                from aughor.kernel.errors import tolerate
                tolerate(_e, "query/semantic: best-effort connection close", counter="query.semantic.close_failed")
        if base.error:
            return None, base
        op = apply_step(
            base, body.operator, body.column,
            predicate=body.predicate or "",
            fields=[(f.name, f.description) for f in body.fields],
            criterion=body.criterion or "",
            k=body.k,
            instruction=body.instruction or "",
            out_column=body.out_column,
            max_rows=body.max_rows,
            override_cap=body.override_cap,
        )
        return op, base

    loop = asyncio.get_event_loop()
    try:
        op, base = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if op is None:  # SQL failed before the operator ran
        return {"columns": base.columns, "rows": base.rows, "row_count": base.row_count,
                "sql": base.sql, "error": base.error, "operator": body.operator, "column": body.column}

    r = op.result
    return {
        "columns": r.columns,
        "rows": r.rows,
        "row_count": r.row_count,
        "sql": r.sql,
        "error": r.error,
        "operator": op.operator,
        "column": op.column,
        "input_rows": op.input_rows,
        "output_rows": op.output_rows,
        "truncated": op.truncated,
        "notes": op.notes,
        "llm_calls": op.llm_calls,
    }


@router.post("/query/semantic/text-columns", dependencies=[gate(Capability.SEMANTIC_OPERATORS)])
async def query_semantic_text_columns(body: _QueryRunRequest):
    """Detect which columns of a query's result read as free text — the operator candidates the UI
    should offer. Re-runs the SQL server-side and inspects the values (rows carry no dtypes)."""
    from aughor.db.connection import open_connection_for
    from aughor.semops.operators import detect_text_columns

    if not body.sql.strip():
        raise HTTPException(status_code=400, detail="sql is required")
    try:
        db = open_connection_for(body.conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    wrapped = _wrap_limited(body.sql, body.limit)

    def _work():
        try:
            return db.execute("__semantic_cols__", wrapped)
        finally:
            try:
                db.close()
            except Exception as _e:
                from aughor.kernel.errors import tolerate
                tolerate(_e, "query/semantic/text-columns: best-effort connection close",
                         counter="query.semantic.text_columns.close_failed")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result.error:
        return {"columns": [], "text_columns": [], "error": result.error}
    return {"columns": result.columns, "text_columns": detect_text_columns(result), "error": None}


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


class _DecompileRequest(BaseModel):
    sql: str
    dialect: str = "duckdb"


@router.post("/query/decompile")
def query_decompile(body: _DecompileRequest):
    """Query Builder Layer-3 — reverse-compile raw SQL back into the visual builder's chips
    (primary table, joins, dimensions, measures, filters, order/limit). Returns
    ``{ok: false, reason}`` for a shape the builder can't represent (CTE, set-op, subquery
    source), so the UI can keep the raw SQL instead of importing it lossily."""
    from aughor.sql.decompile import decompile_sql
    return decompile_sql(body.sql or "", dialect=body.dialect or "duckdb")


class _QueryValidateRequest(BaseModel):
    conn_id: str
    sql: str
    dialect: str = "duckdb"


@router.post("/query/validate")
def query_validate(body: _QueryValidateRequest):
    """On-demand governed validation of an answer's query: re-run the deterministic guard
    battery against the live connection — fan-out / chasm (static), join value-domain and
    filter value-domain (live probes) — and return a structured verdict. Each guard is
    fail-open: one that can't run is simply omitted, never an error. This is the explicit,
    user-triggered version of the guards that run inline during answer generation."""
    from aughor.db.connection import open_connection_for
    from aughor.kernel.errors import tolerate

    if not (body.sql or "").strip():
        raise HTTPException(status_code=400, detail="sql is required")
    try:
        db = open_connection_for(body.conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    sql = body.sql
    dialect = getattr(db, "dialect", None) or body.dialect or "duckdb"
    fanout_hits: list = []
    join_warnings: list = []
    filter_warnings: list = []
    try:
        # Fan-out / chasm — static analysis over the connection's schema-derived columns.
        try:
            from aughor.tools.schema import parse_schema_tables
            from aughor.agent.verifier import Verifier
            table_cols = parse_schema_tables(db.get_schema())
            fanout_hits = Verifier.scan([sql], table_cols, dialect)
        except Exception as exc:
            tolerate(exc, "validate: fan-out scan", counter="validate.fanout")
        # Join value-domain — live overlap probe of each join's keys.
        try:
            from aughor.sql.join_guard import check_join_value_domains
            join_warnings = [
                {"table_a": w.table_a, "col_a": w.col_a, "table_b": w.table_b,
                 "col_b": w.col_b, "overlap": w.overlap}
                for w in check_join_value_domains(db, sql)
            ]
        except Exception as exc:
            tolerate(exc, "validate: join value-domain", counter="validate.join")
        # Filter value-domain — a guessed enum literal that matches no row but has a near neighbour.
        try:
            from aughor.sql.join_guard import check_filter_value_domains
            filter_warnings = [
                {"table": w.table, "column": w.col, "literal": w.bad_value,
                 "op": w.op, "suggestion": w.suggestion or ""}
                for w in check_filter_value_domains(db, sql)
            ]
        except Exception as exc:
            tolerate(exc, "validate: filter value-domain", counter="validate.filter")
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "validate: db close", counter="validate.close")

    issues = len(fanout_hits) + len(join_warnings) + len(filter_warnings)
    return {
        "passed": issues == 0,
        "issue_count": issues,
        "fanout_hits": fanout_hits,
        "join_warnings": join_warnings,
        "filter_warnings": filter_warnings,
    }


class _ChatFeedbackRequest(BaseModel):
    conn_id: str
    turn_id: str
    verdict: str          # "helpful" | "unhelpful"
    note: str = ""


@router.post("/chat/feedback")
def chat_feedback(body: _ChatFeedbackRequest):
    """Record a helpful/unhelpful signal (and optional note) on a chat answer. Journaled to
    the ledger as a ``chat.feedback`` event so it rides the audit trail; fail-open."""
    from aughor.kernel.errors import tolerate
    try:
        from aughor.kernel.ledger import Ledger
        Ledger.default().emit(
            "chat.feedback",
            {"turn_id": body.turn_id, "verdict": body.verdict, "note": body.note[:2000]},
            conn_id=body.conn_id,
        )
    except Exception as exc:
        tolerate(exc, "chat feedback journal", counter="chat.feedback")
    return {"ok": True}


# ── Saved queries ─────────────────────────────────────────────────────────────
# Persist a Query Builder query (SQL + visual spec) so it survives reloads. Connection-scoped,
# mirrors the Canvas store pattern. ``spec`` is opaque JSON owned by the frontend.

class _SaveQueryRequest(BaseModel):
    connection_id: str
    name: str
    sql: str = ""
    spec: dict = {}


class _UpdateSavedQueryRequest(BaseModel):
    name: str | None = None
    sql: str | None = None
    spec: dict | None = None


@router.get("/saved-queries")
def saved_queries_list(connection_id: str | None = None):
    """List saved queries, optionally filtered to one connection (newest first)."""
    from aughor.savedquery.store import list_saved_queries
    return [q.model_dump() for q in list_saved_queries(connection_id)]


@router.post("/saved-queries", status_code=201)
def saved_queries_create(body: _SaveQueryRequest):
    """Create a saved query from the current builder state."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    from aughor.savedquery.store import create_saved_query
    q = create_saved_query(body.connection_id, body.name.strip(), body.sql, body.spec)
    return q.model_dump()


@router.get("/saved-queries/{query_id}")
def saved_queries_get(query_id: str):
    from aughor.savedquery.store import get_saved_query
    q = get_saved_query(query_id)
    if not q:
        raise HTTPException(status_code=404, detail="Saved query not found")
    return q.model_dump()


@router.put("/saved-queries/{query_id}")
def saved_queries_update(query_id: str, body: _UpdateSavedQueryRequest):
    from aughor.savedquery.store import update_saved_query
    q = update_saved_query(query_id, name=body.name, sql=body.sql, spec=body.spec)
    if not q:
        raise HTTPException(status_code=404, detail="Saved query not found")
    return q.model_dump()


@router.delete("/saved-queries/{query_id}", status_code=200)
def saved_queries_delete(query_id: str):
    from aughor.savedquery.store import delete_saved_query
    ok = delete_saved_query(query_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Saved query not found")
    return {"ok": True, "id": query_id}


# ── Measure grains (additivity) ────────────────────────────────────────────────
# Expose per-unit vs per-line classification for a connection's measure columns so the
# Query Builder can warn on grain misuse (SUM a per-unit price without ×quantity = under-count;
# SUM a per-line total ×quantity = double-count). Reuses the additivity semantic layer.

@router.get("/connections/{conn_id}/measure-grains")
def connection_measure_grains_endpoint(conn_id: str):
    """Return {grains: {col_lower: 'per_unit'|'per_line'}, quantity_cols: [...]} for a connection.
    Best-effort: ontology-stamped grains first (no DB), else a cached live probe. Never raises."""
    from aughor.semantic.measure_grain import (
        connection_measure_grains, grains_from_ontology, cached_connection_grains,
    )
    grains, qcols = grains_from_ontology(conn_id)
    if not grains:
        cached = cached_connection_grains(conn_id)  # cheap hit: no DB open, no schema introspection
        if cached is not None:
            grains, qcols = cached
        else:
            try:
                from aughor.db.connection import open_connection_for
                from aughor.tools.schema import parse_schema_tables
                db = open_connection_for(conn_id)
                try:
                    table_cols = parse_schema_tables(db.get_schema())
                    grains, qcols = connection_measure_grains(conn_id, db, table_cols)
                finally:
                    try:
                        db.close()
                    except Exception as _e:
                        from aughor.kernel.errors import tolerate
                        tolerate(_e, "measure-grains endpoint: best-effort connection close",
                                 counter="query.measure_grains.close_failed")
            except Exception:
                grains, qcols = {}, set()
    return {"grains": grains, "quantity_cols": sorted(qcols)}


# ── Distinct values (filter pickers) ───────────────────────────────────────────

def _quote_ident(name: str, schema: "str | None" = None) -> str:
    """Quote a (possibly already schema-qualified) table identifier — each dotted segment
    separately, never the whole dotted string as one identifier (the beautycommerce bug)."""
    if "." in name:
        return ".".join(f'"{p}"' for p in name.split("."))
    if schema and schema not in ("main", "public"):
        return f'"{schema}"."{name}"'
    return f'"{name}"'


@router.get("/connections/{conn_id}/distinct")
def column_distinct(conn_id: str, table: str, column: str, schema: "str | None" = None, limit: int = 200):
    """Distinct non-null values for a column, for filter-value pickers. Capped + best-effort."""
    from aughor.db.connection import open_connection_for
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        n = max(1, min(int(limit), 1000))
        qt, qc = _quote_ident(table, schema), f'"{column}"'
        res = db.execute("__distinct__", f"SELECT DISTINCT {qc} AS v FROM {qt} WHERE {qc} IS NOT NULL ORDER BY 1 LIMIT {n}")
        if getattr(res, "error", None):
            return {"values": [], "truncated": False}
        vals = [None if r[0] is None else str(r[0]) for r in (res.rows or [])]
        return {"values": vals, "truncated": len(vals) >= n}
    finally:
        try:
            db.close()
        except Exception as _e:
            from aughor.kernel.errors import tolerate
            tolerate(_e, "distinct endpoint: best-effort connection close", counter="query.distinct.close_failed")


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
