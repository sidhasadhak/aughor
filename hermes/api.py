"""FastAPI backend — SSE investigation streaming + connection management."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

# Load .env from the project root (no-op if python-dotenv not installed)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hermes.agent.graph import build_graph
from hermes.agent.state import AgentState
from hermes.db.connection import open_connection
from hermes.db.history import (
    complete_investigation,
    create_investigation,
    fail_investigation,
    get_investigation,
    list_investigations,
    pause_investigation,
)
from hermes.db.registry import (
    BUILTIN_ID,
    add_connection,
    delete_connection,
    get_dsn,
    list_connections,
)
from hermes.semantic.glossary import load_glossary, update_column, update_table
from hermes.tools.schema import build_schema_context

app = FastAPI(title="Aughor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response models ────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    question: str
    connection_id: str = BUILTIN_ID
    hitl: bool = False


class FeedbackRequest(BaseModel):
    feedback: str


class AddConnectionRequest(BaseModel):
    name: str
    conn_type: str       # "duckdb" | "postgres"
    dsn: str             # e.g. "postgresql://user:pass@host:5432/db" or path to .duckdb


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── Investigation endpoint ────────────────────────────────────────────────────

async def _stream_investigation(question: str, connection_id: str, request: Request, hitl: bool = False) -> AsyncGenerator[str, None]:
    _TIMEOUT = int(os.getenv("HERMES_TIMEOUT_SECONDS", "300"))
    try:
        conn_type, dsn = get_dsn(connection_id)
    except KeyError as e:
        yield _sse("error", {"message": str(e)})
        return

    try:
        db = open_connection(conn_type, dsn)
    except Exception as e:
        yield _sse("error", {"message": f"Could not connect: {e}"})
        return

    # ── Cache check: short-circuit if a very similar investigation exists ────────
    from hermes.tools.prior_analyses import find_similar_investigation
    from hermes.db.history import get_investigation
    cache_hit = find_similar_investigation(question)
    if cache_hit:
        cached_id, score = cache_hit
        cached = get_investigation(cached_id)
        if cached and cached.get("report"):
            yield _sse("start", {
                "question": question,
                "connection_id": connection_id,
                "investigation_id": cached_id,
            })
            if cached.get("hypotheses"):
                yield _sse("hypotheses", {"hypotheses": cached["hypotheses"]})
            qh = cached.get("query_history") or []
            yield _sse("report", {
                "report": cached["report"],
                "hypotheses": cached.get("hypotheses") or [],
                "query_count": cached.get("query_count", len(qh)),
                "query_history": qh,
                "investigation_id": cached_id,
                "from_cache": True,
                "cached_question": cached["question"],
                "cache_score": round(score, 3),
            })
            yield _sse("done", {})
            return

    inv_id = create_investigation(question, connection_id)
    yield _sse("start", {"question": question, "connection_id": connection_id, "investigation_id": inv_id})

    try:
        schema = db.get_schema()

        from hermes.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=hitl)

        initial_state: AgentState = {
            "question": question,
            "schema_context": schema,
            "hypotheses": [],
            "current_hypothesis_idx": 0,
            "query_history": [],
            "evidence_scores": [],
            "pitfalls": [],
            "prior_analyses": [],
            "iteration": 0,
            "max_iterations": int(os.getenv("HERMES_MAX_ITER", "6")),
            "report": None,
            "hitl_enabled": hitl,
            "human_feedback": None,
            "query_mode": None,
        }

        import time
        merged = initial_state.copy()
        deadline = time.monotonic() + _TIMEOUT
        timed_out = False

        for event in agent.stream(initial_state, config={"configurable": {"thread_id": inv_id}}):
            # ── Disconnect check ──────────────────────────────────────────────
            if await request.is_disconnected():
                fail_investigation(inv_id, status="timed_out")
                return

            # ── Wall-clock timeout check ──────────────────────────────────────
            if time.monotonic() > deadline:
                timed_out = True
                break

            # ── HITL interrupt ────────────────────────────────────────────────
            if "__interrupt__" in event:
                yield _sse("paused", {
                    "investigation_id": inv_id,
                    "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])],
                    "scores": [s.model_dump() for s in merged.get("evidence_scores", [])],
                })
                pause_investigation(inv_id)
                yield _sse("done", {})
                return

            node_name = next(iter(event))
            partial = event[node_name]
            merged = {**merged, **partial}

            if node_name == "route_question":
                yield _sse("mode", {
                    "query_mode": merged.get("query_mode"),
                })

            elif node_name == "decompose" and merged.get("hypotheses"):
                yield _sse("hypotheses", {
                    "hypotheses": [h.model_dump() for h in merged["hypotheses"]],
                })

            elif node_name == "plan_and_execute":
                history = merged.get("query_history", [])
                recent = history[-3:]
                pitfalls = merged.get("pitfalls", [])
                new_pitfalls = pitfalls[-(len(recent)):] if pitfalls else []
                all_stats = [s.model_dump() for r in recent for s in (r.stats or [])]
                yield _sse("queries_executed", {
                    "iteration": merged.get("iteration", 0),
                    "hypothesis_idx": merged.get("current_hypothesis_idx", 0),
                    "queries": [{"sql": r.sql, "row_count": r.row_count, "error": r.error, "stats": [s.model_dump() for s in (r.stats or [])]} for r in recent],
                    "corrections": [p.model_dump() for p in new_pitfalls],
                    "stats": all_stats,
                })

            elif node_name == "score_evidence":
                scores = merged.get("evidence_scores", [])
                if scores:
                    yield _sse("score", {
                        "iteration": merged.get("iteration", 0),
                        "score": scores[-1].model_dump(),
                        "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])],
                    })

            elif node_name == "synthesize" and merged.get("report"):
                query_history = merged.get("query_history", [])
                yield _sse("report", {
                    "report": merged["report"].model_dump(),
                    "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])],
                    "query_count": len(query_history),
                    "query_history": [
                        {
                            "hypothesis_id": r.hypothesis_id,
                            "sql": r.sql,
                            "row_count": r.row_count,
                            "error": r.error,
                            "columns": r.columns,
                            "rows": r.rows[:50],
                        }
                        for r in query_history
                    ],
                    "investigation_id": inv_id,
                    "query_mode": merged.get("query_mode"),
                })
                # Persist + index (only on clean completion)
                complete_investigation(
                    inv_id,
                    report=merged["report"],
                    hypotheses=merged.get("hypotheses", []),
                    query_history=query_history,
                    question=question,
                )

        # ── Post-loop: handle timeout ─────────────────────────────────────────
        if timed_out:
            yield _sse("error", {"message": f"Investigation timed out after {_TIMEOUT}s. Partial results may be available in history."})
            fail_investigation(inv_id, status="timed_out")

    except Exception as e:
        fail_investigation(inv_id, status="failed")
        yield _sse("error", {"message": str(e)})
    finally:
        db.close()
        yield _sse("done", {})


@app.post("/investigate")
async def investigate(req: InvestigateRequest, request: Request):
    return StreamingResponse(
        _stream_investigation(req.question, req.connection_id, request, hitl=req.hitl),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_resume(inv_id: str, feedback: str, request: Request) -> AsyncGenerator[str, None]:
    """Resume a paused investigation with human feedback, streaming the synthesize step."""
    inv = get_investigation(inv_id)
    if not inv:
        yield _sse("error", {"message": "Investigation not found"})
        yield _sse("done", {})
        return

    if inv.get("status") != "paused":
        yield _sse("error", {"message": f"Investigation is not paused (status: {inv.get('status')})"})
        yield _sse("done", {})
        return

    try:
        conn_type, dsn = get_dsn(inv["connection_id"])
    except KeyError as e:
        yield _sse("error", {"message": str(e)})
        yield _sse("done", {})
        return

    try:
        db = open_connection(conn_type, dsn)
    except Exception as e:
        yield _sse("error", {"message": f"Could not reconnect: {e}"})
        yield _sse("done", {})
        return

    try:
        from hermes.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=True)
        config = {"configurable": {"thread_id": inv_id}}

        # Seed merged with the full checkpointed state so synthesize's partial output
        # is merged on top (synthesize only returns {"report": ...}, not hypotheses)
        checkpoint = agent.get_state(config)
        merged: dict = dict(checkpoint.values) if checkpoint else {}

        # Inject analyst feedback into the checkpointed state
        agent.update_state(config, {"human_feedback": feedback})

        import time
        _TIMEOUT = int(os.getenv("HERMES_TIMEOUT_SECONDS", "300"))
        deadline = time.monotonic() + _TIMEOUT

        for event in agent.stream(None, config=config):
            if await request.is_disconnected():
                fail_investigation(inv_id, status="timed_out")
                return

            if time.monotonic() > deadline:
                yield _sse("error", {"message": "Timed out waiting for synthesis."})
                fail_investigation(inv_id, status="timed_out")
                return

            if "__interrupt__" in event:
                continue

            node_name = next(iter(event))
            partial = event[node_name]
            merged = {**merged, **partial}

            if node_name == "synthesize" and merged.get("report"):
                query_history = merged.get("query_history", [])
                yield _sse("report", {
                    "report": merged["report"].model_dump(),
                    "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])],
                    "query_count": len(query_history),
                    "query_history": [
                        {
                            "hypothesis_id": r.hypothesis_id,
                            "sql": r.sql,
                            "row_count": r.row_count,
                            "error": r.error,
                            "columns": r.columns,
                            "rows": r.rows[:50],
                        }
                        for r in query_history
                    ],
                    "investigation_id": inv_id,
                })
                complete_investigation(
                    inv_id,
                    report=merged["report"],
                    hypotheses=merged.get("hypotheses", []),
                    query_history=query_history,
                    question=inv["question"],
                )

    except Exception as e:
        fail_investigation(inv_id, status="failed")
        yield _sse("error", {"message": str(e)})
    finally:
        db.close()
        yield _sse("done", {})


@app.post("/investigations/{inv_id}/feedback")
async def submit_feedback(inv_id: str, req: FeedbackRequest, request: Request):
    return StreamingResponse(
        _stream_resume(inv_id, req.feedback, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Connection management endpoints ──────────────────────────────────────────

@app.get("/connections")
def get_connections():
    return list_connections()


@app.post("/connections", status_code=201)
def create_connection(req: AddConnectionRequest):
    # Validate the connection before saving
    try:
        db = open_connection(req.conn_type, req.dsn)
        ok, msg = db.test()
        db.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")

    if not ok:
        raise HTTPException(status_code=400, detail=f"Connection test failed: {msg}")

    conn_id = add_connection(name=req.name, conn_type=req.conn_type, dsn=req.dsn)
    return {"id": conn_id, "message": "Connection added", "test_result": msg}


@app.post("/connections/{conn_id}/test")
def test_connection(conn_id: str):
    try:
        conn_type, dsn = get_dsn(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        db = open_connection(conn_type, dsn)
        ok, msg = db.test()
        db.close()
        return {"ok": ok, "message": msg}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/connections/{conn_id}/schema")
def connection_schema(conn_id: str):
    try:
        conn_type, dsn = get_dsn(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        db = open_connection(conn_type, dsn)
        schema = db.get_schema()
        db.close()
        return {"schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/connections/{conn_id}", status_code=204)
def remove_connection(conn_id: str):
    try:
        delete_connection(conn_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")


@app.get("/glossary")
def get_glossary():
    return load_glossary()


class UpdateTableRequest(BaseModel):
    description: Optional[str] = None
    grain: Optional[str] = None
    joins: Optional[list[str]] = None


class UpdateColumnRequest(BaseModel):
    description: Optional[str] = None
    values: Optional[str] = None
    caveats: Optional[str] = None


@app.put("/glossary/{table}")
def put_table_glossary(table: str, req: UpdateTableRequest):
    update_table(table, description=req.description, grain=req.grain, joins=req.joins)
    return {"ok": True, "table": table}


@app.put("/glossary/{table}/{column}")
def put_column_glossary(table: str, column: str, req: UpdateColumnRequest):
    update_column(table, column, description=req.description, values=req.values, caveats=req.caveats)
    return {"ok": True, "table": table, "column": column}


@app.get("/investigations/indexed-ids")
def get_indexed_ids():
    """Return the set of investigation IDs that have been indexed in Qdrant."""
    from hermes.tools.prior_analyses import INVESTIGATIONS_COLLECTION
    from hermes.semantic.vector_store import scroll_payloads
    payloads = scroll_payloads(INVESTIGATIONS_COLLECTION)
    return {"ids": [p["inv_id"] for p in payloads if p.get("inv_id")]}


@app.get("/investigations")
def get_investigations(limit: int = 50):
    return list_investigations(limit=limit)


@app.get("/investigations/{inv_id}")
def get_investigation_detail(inv_id: str):
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


@app.post("/investigations/reindex")
def reindex_investigations():
    """Backfill Qdrant with all completed investigations from history.db."""
    from hermes.tools.prior_analyses import index_investigation
    rows = list_investigations(limit=1000)
    indexed, skipped = 0, 0
    for row in rows:
        if not row.get("headline"):
            skipped += 1
            continue
        full = get_investigation(row["id"])
        if not full or not full.get("report"):
            skipped += 1
            continue
        key_findings = [f.get("claim", "") for f in (full["report"].get("key_findings") or [])]
        index_investigation(
            inv_id=row["id"],
            question=row["question"],
            headline=row["headline"],
            key_findings=key_findings,
        )
        indexed += 1
    return {"indexed": indexed, "skipped": skipped}


@app.get("/health")
def health():
    fixture = Path(__file__).parent.parent / "data" / "hermes.duckdb"
    return {"status": "ok", "fixture_db": fixture.exists()}
