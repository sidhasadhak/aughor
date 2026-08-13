"""Query runner and visual query builder endpoints."""
from __future__ import annotations

import asyncio
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from aughor.licensing import Capability, gate


def _query_owner_guard(request: Request) -> None:
    """Object-level authz (SEC-05 / DATA-06): a by-id route on this router is reachable
    only by the org that owns the resource. Covers ``query_id`` (saved queries) and
    ``conn_id`` path params (measure-grains, distinct, cache invalidation) — the
    connections router's own guard does not see routes mounted here. No-op on routes
    without those params and in localhost mode."""
    from aughor.security.authz import check_owner, get_principal
    if (qid := request.path_params.get("query_id")):
        check_owner("saved_query", qid, get_principal(request))
    if (cid := request.path_params.get("conn_id")):
        check_owner("connection", cid, get_principal(request))


def _check_conn_org(request: Request, *conn_ids: str) -> None:
    """DATA-06 for body-carried connection ids: 403 when any id belongs to another
    org. The path-param guard above cannot see request bodies, so every handler
    that resolves a ``conn_id`` from its body calls this before touching the
    connection. No-op in localhost mode and for the shared builtins (their org
    resolves to None), same as ``check_owner`` everywhere else."""
    from aughor.security.authz import check_owner, get_principal
    principal = get_principal(request)
    for cid in conn_ids:
        if cid:
            check_owner("connection", cid, principal)


router = APIRouter(tags=["query"], dependencies=[Depends(_query_owner_guard)])


# ── SE-3 F — cancellation and a time limit that actually bites ─────────────────

class QueryAborted(Exception):
    """A run ended early on purpose. ``reason`` is 'cancelled' or 'timeout'."""

    def __init__(self, reason: str, elapsed_ms: float, limit_ms: float = 0.0):
        self.reason = reason
        self.elapsed_ms = elapsed_ms
        self.limit_ms = limit_ms
        super().__init__(reason)


#: How often the watchdog looks up from the query to check the clock and the client.
#: 250 ms bounds the overshoot past a deadline without making an idle wait busy.
_WATCH_INTERVAL_S = 0.25


async def _run_watched(db, work, *, request: Request, limit_ms: float):
    """Run blocking ``work()`` in a thread, watched by the event loop.

    Two things end a run early, and they are the same mechanism: the client went
    away, or the budget expired. Both reach the engine through ``db.interrupt()``.

    **Why the client's disconnect is the cancel signal, rather than a job id and a
    second endpoint.** The roadmap sketched `POST /query/submit` → `{job_id}` with
    cancel over the jobs surface. Measured against how this actually deploys, that
    shape does not hold: a kernel job is an asyncio task in the invocation that
    created it, so on serverless the task dies the moment `/query/submit` returns —
    there is nothing left to poll. And a `/jobs/{id}/cancel` arriving at a second
    instance cannot reach the connection blocking on the first. A disconnect travels
    the SAME socket as the query it cancels, so it is routed correctly by
    construction, needs no new endpoint, and makes the client's "Cancel" button an
    `AbortController` rather than a distributed-systems problem.

    **Why a watchdog rather than `asyncio.wait_for`.** Cancelling the *await* does
    nothing to the thread: the executor keeps running the blocking call to
    completion, holding a connection and burning warehouse time invisibly. Only the
    engine's own abort ends it, so the timeout has to interrupt, then still wait for
    the thread to unwind and close its connection in its own ``finally`` (the
    interrupt-never-close rule from ``DatabaseConnection.interrupt``).

    The abort is reported from what THIS function knows — that it asked the engine to
    stop — not from whether the future raised, because ``execute()`` turns the
    engine's interrupt into ``QueryResult.error`` rather than an exception. One
    consequence, stated rather than hidden: a statement that finishes inside the same
    watchdog tick in which the deadline expires is still reported as a timeout. At the
    default 60 s limit that window is the last 250 ms, and "exceeded 60000ms" remains
    true of a query that took 60.1 s.
    """
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, work)
    started = loop.time()
    deadline = started + (limit_ms / 1000.0) if limit_ms > 0 else None

    while True:
        done, _ = await asyncio.wait({fut}, timeout=_WATCH_INTERVAL_S)
        if done:
            return fut.result()

        if deadline is not None and loop.time() >= deadline:
            reason = "timeout"
        elif await request.is_disconnected():
            reason = "cancelled"
        else:
            continue

        if not db.interrupt():
            # This connector cannot abort a running statement. Waiting it out is the
            # only honest option: returning now would strand a thread still holding
            # the connection while telling the caller the query had stopped.
            return await fut

        # The engine raises on the worker thread; wait for it to unwind and close in
        # its own `finally` before reporting, so no thread outlives this request.
        try:
            await fut
        except Exception:
            pass  # the interrupt IS the expected outcome here
        raise QueryAborted(reason, (loop.time() - started) * 1000.0, limit_ms)


class _QueryRunRequest(BaseModel):
    conn_id: str
    sql: str
    limit: int = 500
    use_cache: bool = False
    use_bulk: bool = False
    # SE-0: "typed" returns JSON-native rows (real null, not the string "NULL"),
    # columns_typed [{name, type}] and an explicit truncated flag. The default
    # keeps the legacy stringified shape byte-identical.
    format: Literal["legacy", "typed"] = "legacy"
    # SE-0: which user surface issued the SQL — the audit/safety label. An
    # allow-list, never free text: a client-chosen label reaches gate_user_sql
    # and the audit log, and a dunder-shaped one would match the internal-query
    # bypass and skip PII redaction + audit entirely (the original
    # __querybuilder__ bug, pinned in test_query_safety_gate.py).
    source: Literal["query_builder", "query_workbench"] = "query_builder"
    # SE-4 H — values for the statement's `:name` parameters, executed as real BIND
    # VALUES. Never interpolated: a bound value cannot change the statement's
    # structure, which is the entire reason this is a separate field and not a
    # client-side string substitution before the request is sent.
    params: Optional[dict] = None


def _write_builder_receipt(conn_id: str, sql: str) -> Optional[str]:
    """WP-10: a signed provenance receipt for a Query Builder run — the exact SQL that ran +
    its input tables, resolvable via GET /receipt/{id} (so "Why this number" opens the same
    drawer as an answer). Best-effort. Keyed by the SQL hash, so re-running the same query
    versions one receipt rather than spamming the ledger."""
    try:
        import hashlib
        from aughor.kernel.ledger import Ledger
        from aughor.sql.tables import extract_tables
        tables = sorted({t.table for t in extract_tables(sql) if t.table})
        key = f"builder:{conn_id}:{hashlib.sha1(sql.encode('utf-8')).hexdigest()[:12]}"
        lineage = [("source_sql", "sql", sql)] + [("input", f"table:{t}", None) for t in tables]
        return Ledger.default().artifact_write(
            "builder", key,
            {"question": "Query Builder run", "headline": "", "sql": sql, "tables": tables},
            conn_id=conn_id, lineage=lineage,
        )
    except Exception as exc:
        from aughor.kernel.errors import tolerate
        tolerate(exc, "builder receipt is best-effort; the query result is unaffected",
                 counter="query.builder_receipt")
        return None


def _json_cell(v):
    """A DB value as a JSON-native cell: real null, native numbers/strings/bools,
    ISO strings for temporal types, strings for everything JSON can't say
    (bytes, UUIDs, intervals). Decimal → float: this is a display path, and the
    legacy string shape remains available where exactness matters."""
    import datetime as _dt
    import decimal as _dec
    import math as _math
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if _math.isfinite(v) else str(v)
    if isinstance(v, _dec.Decimal):
        return float(v)
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_json_cell(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_cell(x) for k, x in v.items()}
    return str(v)


def _infer_col_type(values) -> str:
    """Column type from the first non-null Python value — the fallback for cursors
    whose description carries no types (sqlite3). bool before int (bool subclasses
    int), datetime before date (same reason)."""
    import datetime as _dt
    import decimal as _dec
    for v in values:
        if v is None:
            continue
        if isinstance(v, bool):
            return "BOOLEAN"
        if isinstance(v, int):
            return "BIGINT"
        if isinstance(v, float):
            return "DOUBLE"
        if isinstance(v, _dec.Decimal):
            return "NUMERIC"
        if isinstance(v, _dt.datetime):
            return "TIMESTAMP"
        if isinstance(v, _dt.date):
            return "DATE"
        if isinstance(v, _dt.time):
            return "TIME"
        if isinstance(v, (bytes, memoryview)):
            return "BLOB"
        if isinstance(v, str):
            return "VARCHAR"
        return "UNKNOWN"
    return "UNKNOWN"


def _typed_response(result, payload: dict, limit: int, duration_ms: float,
                    receipt_id, caveats: list[str]) -> dict:
    """Assemble the format:"typed" response from an execute_typed payload. Rows are
    sliced back to the requested limit (the n+1 probe row never leaves the server);
    the probe row arriving is what makes `truncated` honest."""
    from aughor.tools.schema import norm_type
    rows = payload.get("rows") or []
    truncated = bool(payload.get("truncated"))
    if limit > 0 and len(rows) > limit:
        rows, truncated = rows[:limit], True
    cols = list(result.columns or [])
    raw_types = [str(t) for t in (payload.get("types") or [])]
    if len(raw_types) != len(cols):
        raw_types = [""] * len(cols)

    def _one_type(idx: int, raw: str) -> str:
        raw = (raw or "").strip()
        if not raw or raw.lower() == "none":
            return _infer_col_type(r[idx] for r in rows)
        return norm_type(raw)

    columns_typed = [{"name": c, "type": _one_type(i, raw_types[i])} for i, c in enumerate(cols)]
    return {
        "columns": cols,
        "columns_typed": columns_typed,
        "rows": [[_json_cell(v) for v in row] for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "duration_ms": round(duration_ms, 1),
        "sql": result.sql,
        "cached": False,
        "error": result.error,
        "receipt_id": receipt_id,
        "caveats": caveats,
        "format": "typed",
    }


@router.post("/query/run")
async def query_run(body: _QueryRunRequest, request: Request):
    """Execute a SQL query against a registered connection."""
    import time as _t
    from aughor.db.connection import (
        open_connection_for, gate_user_sql, is_metadata_statement,
    )

    _check_conn_org(request, body.conn_id)
    if not body.sql.strip():
        raise HTTPException(status_code=400, detail="sql is required")
    if body.format == "typed" and body.use_bulk:
        # bulk_read reaches ConnectorX directly and has no typed capture; refusing
        # is honest where silently serving strings under a "typed" label is not.
        raise HTTPException(status_code=400, detail="format 'typed' is not supported with use_bulk")

    # Safety gate on the RAW user SQL — before cache, wrapping, or dispatch.
    # The Query Builder is user-exposed, so user SQL goes through the same
    # SafetyChecker + audit as the chat path. This lives here (not only in the
    # connection layer) because bulk_read() reaches ConnectorX directly and the
    # runner wraps the SQL in a subquery before execute() ever sees it.
    blocked = gate_user_sql(body.conn_id, body.source, body.sql)
    if blocked is not None:
        return {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "duration_ms": 0.0,
            "sql": body.sql,
            "cached": False,
            "error": blocked.error,
            "receipt_id": None,          # a blocked query has no receipt
            "caveats": [],
        }

    # Under an active RBAC row policy these cached rows are post-RLS, but the cache is consulted before the
    # connection layer injects a principal's row filters — so the key must carry the principal/policy or one
    # principal's rows leak to another. `tenancy` is None (legacy key) until `rbac.row_policy` is live for an
    # identified user; it is computed here in the request context that also drives enforcement (the default
    # executor copies contextvars into `_work`), and reused for the paired put below.
    # Typed responses never touch the result cache: cached rows are stringified,
    # and a typed run wraps at LIMIT n+1 (the truncation probe), so caching its
    # result would let the legacy path serve one extra row later. Skip both sides.
    _typed = body.format == "typed"
    tenancy = None
    if body.use_cache and not _typed:
        from aughor.db.connection import result_cache_tenancy
        from aughor.db.matcache import get_cached
        tenancy = result_cache_tenancy()
        cached = get_cached(body.conn_id, body.sql, tenancy=tenancy)
        if cached is not None:
            return {
                "columns": cached.columns,
                "rows": cached.rows,
                "row_count": cached.row_count,
                "duration_ms": 0.0,
                "sql": cached.sql,
                "cached": True,
                "error": None,
                "receipt_id": _write_builder_receipt(body.conn_id, body.sql),
                "caveats": list(getattr(cached, "caveats", []) or []),
            }

    try:
        db = open_connection_for(body.conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    _sql_to_run = body.sql
    _use_bulk   = body.use_bulk
    _limit      = body.limit
    _source     = body.source
    # Only the workbench may run one, and only it skips the wrap — the connection
    # layer gates the same capability on the same label.
    _is_metadata = _source == "query_workbench" and is_metadata_statement(_sql_to_run)
    _params     = body.params or None

    def _work():
        t0 = _t.monotonic()
        typed_payload = None
        try:
            if _use_bulk:
                result = db.bulk_read(_sql_to_run, limit=_limit)
            else:
                sql = _sql_to_run.strip().rstrip(";")
                # SE-3 G — EXPLAIN/DESCRIBE/SHOW are not wrappable. The wrap is what
                # broke EXPLAIN (a parser error on `SELECT * FROM (EXPLAIN …) __q`);
                # these statements return a handful of rows by nature, so the LIMIT it
                # carried has nothing to bound.
                if _limit > 0 and not _is_metadata:
                    # Typed runs fetch one extra row as the truncation probe: the
                    # subquery wrap hides whether the raw query had more rows, so
                    # row n+1 arriving is the only honest "there was more" signal.
                    sql = f"SELECT * FROM ({sql}) __q LIMIT {_limit + 1 if _typed else _limit}"
                if _params:
                    # Parameters and the typed capture do not compose yet: the typed
                    # side-channel hangs off `execute()`, and binding takes its own
                    # path. Refusing beats serving strings under a "typed" label —
                    # the same call SE-0 made for `use_bulk`.
                    result = db.execute_with_params(_source, sql, _params)
                elif _typed:
                    result, typed_payload = db.execute_typed(_source, sql)
                else:
                    result = db.execute(_source, sql)
        finally:
            try:
                db.close()
            except Exception:
                pass
        return result, typed_payload, (_t.monotonic() - t0) * 1000

    # SE-3 F — the budget's `max_time_ms` stops being decorative here. It has always
    # been declared per connection and, until now, only ever compared against the
    # elapsed time AFTER the query returned: a limit that names a runaway query
    # instead of ending it (`security/sandbox.py`, "we cannot *cancel* an
    # already-running query without connection-level support"). The connectors now
    # have that support, so the same number becomes a real deadline.
    #
    # The workbench opts in; `query_builder` keeps the old wait-forever behaviour so
    # this cannot change what an existing surface does on the day it ships.
    from aughor.security.sandbox import get_budget
    _limit_ms = get_budget(body.conn_id).max_time_ms if _source == "query_workbench" else 0.0

    try:
        result, typed_payload, duration_ms = await _run_watched(
            db, _work, request=request, limit_ms=_limit_ms)
    except QueryAborted as ab:
        # 499 is nginx's "client closed request" — not an IANA code, but the accurate
        # one, and it keeps a user-initiated cancel out of the 5xx error budget where
        # it would read as the server breaking. A timeout IS ours to own, so it is 504.
        if ab.reason == "timeout":
            raise HTTPException(
                status_code=504,
                detail=(f"Query exceeded this connection's {ab.limit_ms:.0f}ms time limit "
                        f"and was stopped after {ab.elapsed_ms:.0f}ms."))
        raise HTTPException(status_code=499, detail="Query cancelled.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if body.use_cache and not _typed and not result.error:
        from aughor.db.matcache import put_cache
        put_cache(body.conn_id, body.sql, result, tenancy=tenancy)

    # WP-10: a successful run gets a signed receipt so the UI can open "Why this number".
    # Record the user's ORIGINAL SQL (not the internal LIMIT-wrapped form the executor ran).
    receipt_id = _write_builder_receipt(body.conn_id, body.sql) if not result.error else None
    caveats = list(getattr(result, "caveats", []) or [])

    if _typed and typed_payload is not None:
        return _typed_response(result, typed_payload, _limit, duration_ms, receipt_id, caveats)

    legacy = {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "duration_ms": round(duration_ms, 1),
        "sql": result.sql,
        "cached": False,
        "error": result.error,
        "receipt_id": receipt_id,
        "caveats": caveats,
    }
    if _typed:
        # The connector has no typed capture (or the security post-pass disarmed
        # it) — say so instead of serving strings under a "typed" label.
        legacy["format"] = "legacy"
    return legacy


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
async def query_semantic(body: _SemanticOpRequest, request: Request):
    """Apply a semantic operator (filter / extract / top_k / aggregate over a text column) to a result.

    Re-runs the SQL server-side (authoritative — never trusts client-sent rows), then applies the
    operator to the text residue. Returns the transformed result plus surfaced operator metadata."""
    from aughor.db.connection import gate_user_sql, open_connection_for
    from aughor.semops.operators import apply_step

    _check_conn_org(request, body.conn_id)
    if not body.sql.strip():
        raise HTTPException(status_code=400, detail="sql is required")
    # Safety gate on the RAW user SQL — same contract as /query/run: the runner
    # wraps it in `SELECT * FROM (…) __q LIMIT n`, which demotes a first-token
    # DELETE/DROP to a body token, so the inner gate can't be trusted alone.
    # This path was previously ungated AND unaudited (label `__semantic__`).
    if (blocked := gate_user_sql(body.conn_id, "semantic_operator", body.sql)) is not None:
        raise HTTPException(status_code=403, detail=blocked.error)
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
            base = db.execute("semantic_operator", wrapped)
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
            validate=True,
            # Champion validation is permanent (flag endgame Wave 5, 2026-08-06):
            # the strong model spot-checks 8 sampled filter verdicts per op —
            # self-checking is direction, and the call is bounded by the sample.
            validate_sample=8,
        )
        return op, base

    loop = asyncio.get_running_loop()
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


class _CrossSourceJoinRequest(BaseModel):
    left_conn_id: str
    left_sql: str
    left_key: str
    right_conn_id: str
    right_table: str
    right_key: str
    how: Literal["inner", "left"] = "inner"
    right_cols: Optional[list[str]] = None


@router.post("/query/cross-source-join")
async def query_cross_source_join(body: _CrossSourceJoinRequest, request: Request):
    """Join a result from ONE connection to a table on ANOTHER, N+1-free (batched foreach).

    The direct entry point for cross-source joins (the Rec 2 engine); the federated planner targets
    the same `cross_source_join`. Always available since flag endgame Wave 2 (2026-08-06;
    the route is the whole surface — calling it is the consent, receipt 41ec864723fb). The
    left SQL goes through the same safety gate as the Query Builder."""
    _check_conn_org(request, body.left_conn_id, body.right_conn_id)
    for field in ("left_conn_id", "left_sql", "left_key", "right_conn_id", "right_table", "right_key"):
        if not (getattr(body, field) or "").strip():
            raise HTTPException(status_code=400, detail=f"{field} is required")

    from aughor.db.connection import gate_user_sql
    if (blocked := gate_user_sql(body.left_conn_id, "cross_source_join", body.left_sql)) is not None:
        return {"columns": [], "rows": [], "row_count": 0, "sql": body.left_sql, "error": blocked.error}

    from aughor.connectors.remote_join import cross_source_join

    reconcile = True   # self-heal ill-formatted cross-source keys (Rec 3)

    def _work():
        return cross_source_join(
            body.left_conn_id, body.left_sql, body.left_key,
            body.right_conn_id, body.right_key,
            right_table=body.right_table, how=body.how,
            right_cols=body.right_cols, reconcile=reconcile,
        )

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"columns": res.columns, "rows": res.rows, "row_count": res.row_count,
            "sql": res.sql, "error": res.error}


class _FederatedAnswerRequest(BaseModel):
    question: str
    conn_ids: list[str]                        # two or more sources; the planner picks the driver + order
    reconcile: Optional[bool] = None           # None → follow the join.key_reconciliation flag


@router.post("/query/federated-answer")
async def query_federated_answer(body: _FederatedAnswerRequest, request: Request):
    """Answer a natural-language question that spans TWO OR MORE connections (Rec 2, Stage 3).

    One LLM call grounds every schema and emits a structured plan (an ordered list of grounded
    per-source sub-queries + link keys — the planner also picks the driver and chain order); the plan
    is validated deterministically and folded through the batched-foreach engine. Returns the merged
    result plus the plan and any validation issues (inspectable). Flag-gated on `federation.planner`
    (default off → 404)."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("federation.planner"):
        raise HTTPException(status_code=404, detail="federated planner is not enabled")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    if len(body.conn_ids) < 2:
        raise HTTPException(status_code=400, detail="at least two conn_ids are required")
    _check_conn_org(request, *body.conn_ids)

    from aughor.agent.federated_planner import answer_federated
    reconcile = body.reconcile if body.reconcile is not None else True

    def _work():
        return answer_federated(body.question, body.conn_ids, reconcile=reconcile)

    loop = asyncio.get_running_loop()
    try:
        ans = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    r = ans.result
    return {
        "columns": r.columns, "rows": r.rows, "row_count": r.row_count, "sql": r.sql, "error": r.error,
        "plan": ans.plan.model_dump() if ans.plan else None,
        "issues": ans.issues,
    }


class _AutoFederatedRequest(BaseModel):
    question: str
    conn_ids: list[str]                        # candidate pool — the selector picks the subset the question spans
    reconcile: Optional[bool] = None


@router.post("/query/auto-federated-answer")
async def query_auto_federated_answer(body: _AutoFederatedRequest, request: Request):
    """Answer a question WITHOUT being told which connections it spans (Rec 2, answer-path).

    A deterministic selector (lexical schema-relevance + greedy set-cover — no LLM) picks the subset of
    the candidate connections the question touches, then the federated planner answers over exactly those.
    Returns the answer plus the `selection` (which connections and the terms each grounded) so the routing
    is inspectable. Flag-gated on `federation.planner` (default off → 404)."""
    from aughor.kernel.flags import flag_enabled
    if not flag_enabled("federation.planner"):
        raise HTTPException(status_code=404, detail="federated planner is not enabled")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    if len(body.conn_ids) < 2:
        raise HTTPException(status_code=400, detail="at least two candidate conn_ids are required")
    _check_conn_org(request, *body.conn_ids)

    from aughor.agent.connection_selector import select_connections
    from aughor.agent.federated_planner import answer_federated
    reconcile = body.reconcile if body.reconcile is not None else True

    def _work():
        sel = select_connections(body.question, body.conn_ids)
        # Only a genuinely cross-source question goes to the federated (multi-DB) planner. A single-source
        # or zero-relevance question must NOT be handed to a planner prompted for cross-database joins.
        if not sel.conn_ids or not sel.multi_source:
            return sel, None
        return sel, answer_federated(body.question, sel.conn_ids, reconcile=reconcile)

    loop = asyncio.get_running_loop()
    try:
        sel, ans = await loop.run_in_executor(None, _work)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    selection = {"conn_ids": sel.conn_ids, "matched": sel.matched, "multi_source": sel.multi_source}
    if not sel.conn_ids:
        raise HTTPException(status_code=422, detail="no candidate connection is relevant to the question")
    if not sel.multi_source:
        # Honest routing: the question sits in one source — the caller should answer it via the normal path.
        return {
            "single_source": True, "selection": selection,
            "columns": [], "rows": [], "row_count": 0, "sql": "", "error": None,
            "plan": None, "issues": [],
            "message": f"single-source question — answer connection {sel.conn_ids[0]} via the normal query path",
        }

    r = ans.result
    return {
        "single_source": False,
        "columns": r.columns, "rows": r.rows, "row_count": r.row_count, "sql": r.sql, "error": r.error,
        "plan": ans.plan.model_dump() if ans.plan else None,
        "issues": ans.issues,
        "selection": selection,
    }


@router.post("/query/semantic/text-columns", dependencies=[gate(Capability.SEMANTIC_OPERATORS)])
async def query_semantic_text_columns(body: _QueryRunRequest, request: Request):
    """Detect which columns of a query's result read as free text — the operator candidates the UI
    should offer. Re-runs the SQL server-side and inspects the values (rows carry no dtypes)."""
    from aughor.db.connection import open_connection_for
    from aughor.semops.operators import detect_text_columns

    _check_conn_org(request, body.conn_id)
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

    loop = asyncio.get_running_loop()
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

    lines = ["SELECT", f"  {select_clause}", f"FROM {body.table}"]
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
    # SE-4 H — values for the statement's `:name` parameters, so the guards can read
    # them. See `_guard_sql` for why a verdict without them is not "clean".
    params: Optional[dict] = None


@router.post("/query/validate")
def query_validate(body: _QueryValidateRequest, request: Request):
    """On-demand governed validation of an answer's query: re-run the deterministic guard
    battery against the live connection — fan-out / chasm (static), join value-domain and
    filter value-domain (live probes) — and return a structured verdict. Each guard is
    fail-open: one that can't run is simply omitted, never an error. This is the explicit,
    user-triggered version of the guards that run inline during answer generation."""
    from aughor.db.connection import open_connection_for
    from aughor.kernel.errors import tolerate
    from aughor.sql.params import ParamRenderError, find_params, render_for_guards

    _check_conn_org(request, body.conn_id)
    if not (body.sql or "").strip():
        raise HTTPException(status_code=400, detail="sql is required")
    try:
        db = open_connection_for(body.conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    # SE-4 H — the guard battery reads LITERALS out of the SQL text. Measured on the
    # live warehouse: `WHERE country = 'Portugalx'` yields a value-domain warning
    # naming the typo and suggesting 'Portugal'; `WHERE country = $country` yields
    # ZERO warnings — the identical answer a CORRECT literal gives. So a parameterised
    # query checked as-is does not report "unverified", it reports CLEAN, and the
    # editor's header says "Guards clean" about a query no guard could see.
    #
    # The fix is a second rendering, for analysis only: substitute the values as
    # literals and guard THAT. Execution still binds (`execute_with_params`), so the
    # string built here never reaches an engine — there is deliberately no path from
    # this variable to `execute()`. When a value is missing or unrenderable, the
    # verdict says so instead of claiming a check it did not run.
    guard_note = ""
    sql = body.sql
    if find_params(sql):
        try:
            sql = render_for_guards(sql, body.params or {})
        except ParamRenderError as exc:
            guard_note = (f"Not checked — this query is parameterised and {exc}. "
                          "Fill in the parameters to run the guards.")
    dialect = getattr(db, "dialect", None) or body.dialect or "duckdb"
    fanout_hits: list = []
    join_warnings: list = []
    filter_warnings: list = []
    grain_warnings: list = []
    trust_findings: list = []
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
        # Grain / fan-out — LIVE uniqueness probe of each join key (catches over-counting that
        # depends on the actual data, not just the schema, so it complements the static scan above).
        try:
            from aughor.sql.grain_guard import detect_fanout

            def _grain_probe(s: str):
                r = db.execute("__grain_probe__", s)
                return (not r.error, r.rows, r.error or "")

            grain_warnings = [
                {"table": f.fanned_table, "join_key": f.join_key,
                 "ratio": round(f.ratio, 2), "caveat": f.caveat()}
                for f in detect_fanout(sql, _grain_probe, dialect)
            ]
        except Exception as exc:
            tolerate(exc, "validate: grain fan-out", counter="validate.grain")
        # CIDR-E1 trust checks — function-semantics footguns (timestamp/date-literal boundary,
        # lexicographic order of numeric text, text-vs-numeric compare). Pure AST; col_types best-
        # effort from information_schema, with a name heuristic fallback for the date-boundary case.
        try:
            # One source of truth for the col-types introspection (shared with the live E1
            # answer paths): uncapped scan, cached per connection, fail-open to the heuristic.
            from aughor.sql.trust_checks import connection_column_types, run_trust_checks
            col_types = connection_column_types(body.conn_id, db) or None
            trust_findings = [f.to_dict() for f in run_trust_checks(sql, col_types=col_types, dialect=dialect)]
        except Exception as exc:
            tolerate(exc, "validate: trust checks", counter="validate.trust")
    finally:
        try:
            db.close()
        except Exception as exc:
            tolerate(exc, "validate: db close", counter="validate.close")

    # AL-01 · Trust plane (behind trust.verify_facade): the AST read-only gate the answer
    # paths never ran on generated SQL. Additive — a mutating/DDL statement or a disallowed
    # function is a hard blocker, distinct from the advisory warnings above. Pure (no conn),
    # so it runs after the connection is closed.
    mutation_blockers: list = []
    try:
        from aughor.trust import verify as trust_verify, Scope
        verdict = trust_verify(sql, Scope(dialect=dialect))
        mutation_blockers = [{"name": c.name, "reason": c.reason, **c.detail}
                             for c in verdict.blockers]
    except Exception as exc:
        tolerate(exc, "validate: trust facade", counter="validate.trust_facade")

    issues = (len(fanout_hits) + len(join_warnings) + len(filter_warnings)
              + len(grain_warnings) + len(trust_findings) + len(mutation_blockers))
    if guard_note:
        # Not an issue COUNT — nothing was found because nothing could be looked at.
        # `passed` is false so no surface can render this as a clean bill of health.
        return {
            "passed": False, "issue_count": 0, "unchecked": True, "note": guard_note,
            "fanout_hits": [], "join_warnings": [], "filter_warnings": [],
            "grain_warnings": [], "trust_findings": [], "mutation_blockers": [],
        }
    return {
        "passed": issues == 0,
        "issue_count": issues,
        "unchecked": False,
        "fanout_hits": fanout_hits,
        "join_warnings": join_warnings,
        "filter_warnings": filter_warnings,
        "grain_warnings": grain_warnings,
        "trust_findings": trust_findings,
        "mutation_blockers": mutation_blockers,
    }


class _SemanticContextRequest(BaseModel):
    conn_id: str
    question: str = ""
    schema_name: str | None = None


@router.post("/query/semantic-context")
def query_semantic_context(body: _SemanticContextRequest, request: Request):
    """Resolve the Semantic plane (AL-05) for a question — what the platform knows about it:
    governed metrics, the ontology object model, the cached business profile, and whether the
    knowledge base covers it. The plane's read-only introspection surface; the same `resolve()`
    is what orchestration will attach to the live answer path. Reads caches only (no DB connect)."""
    if not (body.conn_id or "").strip():
        raise HTTPException(status_code=400, detail="conn_id is required")
    _check_conn_org(request, body.conn_id)
    from aughor.semantic.context import resolve
    return resolve(body.question or "", body.conn_id, body.schema_name).summary()


class _CapabilityAnswerRequest(BaseModel):
    conn_id: str
    question: str
    dialect: str = "duckdb"
    domain: str = "data"          # which Capability plane domain: "data" (SQL) | "metadata" (schema)


@router.post("/query/capability-answer")
def query_capability_answer(body: _CapabilityAnswerRequest, request: Request):
    """Answer a data question end-to-end through the Capability plane (AL-02): one
    `CapabilityPipeline` runs generate (NL→SQL) → validate (`trust.verify`) → execute → interpret
    and returns the whole result. The non-streaming, template-driven counterpart to /ask —
    permanent since flag endgame Wave 2 (2026-08-06, receipt 0dd2b45930c7: the route is the
    single gate, calling it is the consent)."""
    if not (body.question or "").strip():
        raise HTTPException(status_code=400, detail="question is required")
    _check_conn_org(request, body.conn_id)
    from aughor.db.connection import open_connection_for
    try:
        db = open_connection_for(body.conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        try:
            schema = db.get_schema()
        except Exception:
            schema = ""
        from aughor.pipeline import run_capability, CapabilityRequest
        from aughor.trust import Scope
        res = run_capability(body.domain or "data", CapabilityRequest(
            question=body.question,
            scope=Scope(conn=db, schema=schema, dialect=body.dialect or "duckdb")))
    finally:
        try:
            db.close()
        except Exception as exc:
            from aughor.kernel.errors import tolerate
            tolerate(exc, "capability-answer: db close", counter="capability_answer.close")
    if res is None:
        raise HTTPException(status_code=400, detail=f"unknown capability domain: {body.domain!r}")
    return {
        "ok": res.ok,
        "sql": res.artifact,
        "narrative": res.narrative,
        "columns": res.output.get("columns", []),
        "rows": res.output.get("rows", []),
        "row_count": res.output.get("row_count", 0),
        "error": res.error,
        "blockers": [{"name": c.name, "reason": c.reason}
                     for c in (res.verdict.blockers if res.verdict else [])],
        "trace": list(res.trace),
    }


class _PostprocRequest(BaseModel):
    columns: list[str]
    rows: list[list]
    op: Literal["pop", "contribution", "rolling", "cumulative"]
    value_col: str                 # the (numeric) measure column to transform
    window: int = 3                # for rolling
    agg: Literal["mean", "sum", "min", "max"] = "mean"   # for rolling


@router.post("/query/postproc")
def query_postproc(body: _PostprocRequest):
    """Apply an on-demand post-processing transform to a result set — period-over-period,
    share-of-total (Pareto), rolling aggregate, or cumulative total — appending a derived
    column. The same operators the stats surface auto-injects for the LLM, now user-driven.
    Pure (columns, rows) → (columns, rows); never touches the DB."""
    from aughor.tools import postproc as pp

    if body.value_col not in body.columns:
        raise HTTPException(status_code=400, detail=f"value_col '{body.value_col}' not in columns")
    # Pareto/share is only meaningful for an additive measure — refuse it on a rate/avg.
    if body.op == "contribution" and not pp.is_additive_measure(body.value_col):
        raise HTTPException(status_code=422,
                            detail=f"share-of-total is not meaningful for a non-additive measure ('{body.value_col}')")
    try:
        if body.op == "pop":
            cols, rows = pp.with_period_over_period(body.columns, body.rows, body.value_col)
        elif body.op == "contribution":
            cols, rows = pp.with_contribution(body.columns, body.rows, body.value_col)
        elif body.op == "rolling":
            cols, rows = pp.with_rolling(body.columns, body.rows, body.value_col, body.window, body.agg)
        else:  # cumulative
            cols, rows = pp.with_cumulative(body.columns, body.rows, body.value_col)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"transform failed: {exc}")
    return {"columns": cols, "rows": rows}


class _ChatFeedbackRequest(BaseModel):
    conn_id: str
    turn_id: str
    verdict: str          # "helpful" | "unhelpful"
    note: str = ""


@router.post("/chat/feedback")
def chat_feedback(body: _ChatFeedbackRequest, request: Request):
    """Record a helpful/unhelpful signal (and optional note) on a chat answer. Journaled to
    the ledger as a ``chat.feedback`` event so it rides the audit trail; fail-open.

    R10 (THUMBS→priors) — a HELPFUL verdict closes the loop: the turn's tables bump
    the same learned per-connection prior the overview drills and R14 query
    popularity feed, so thumbs teach ranking through the one existing signal path.
    Monotone by design: counters only grow — an unhelpful verdict journals the
    event (audit + future consumers) but never decrements a prior."""
    _check_conn_org(request, body.conn_id)
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
    if body.verdict == "helpful" and body.turn_id:
        try:
            from aughor.db.history import get_investigation
            from aughor.overview.drills import record_drill
            turn = get_investigation(body.turn_id)
            tables = ((turn or {}).get("report") or {}).get("tables_used") or []
            for t in tables[:8]:
                record_drill(body.conn_id, table=str(t).split(".")[-1])
        except Exception as exc:
            tolerate(exc, "thumbs→prior bump is best-effort; the verdict is already journaled",
                     counter="chat.feedback")
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
    from aughor.security.authz import org_visible_conn_ids
    org_conns = org_visible_conn_ids()  # DATA-06: only this org's saved queries
    return [
        q.model_dump()
        for q in list_saved_queries(connection_id)
        if org_conns is None or q.connection_id in org_conns
    ]


@router.post("/saved-queries", status_code=201)
def saved_queries_create(body: _SaveQueryRequest, request: Request):
    """Create a saved query from the current builder state."""
    from aughor.security.authz import check_owner, get_principal
    check_owner("connection", body.connection_id, get_principal(request))  # DATA-06
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
