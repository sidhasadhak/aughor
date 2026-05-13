"""FastAPI backend — SSE investigation streaming + connection management."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hermes.agent.graph import build_graph
from hermes.agent.state import AgentState
from hermes.db.connection import open_connection
from hermes.db.registry import (
    BUILTIN_ID,
    add_connection,
    delete_connection,
    get_dsn,
    list_connections,
)
from hermes.tools.schema import build_schema_context

app = FastAPI(title="Hermes API")

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


class AddConnectionRequest(BaseModel):
    name: str
    conn_type: str       # "duckdb" | "postgres"
    dsn: str             # e.g. "postgresql://user:pass@host:5432/db" or path to .duckdb


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── Investigation endpoint ────────────────────────────────────────────────────

async def _stream_investigation(question: str, connection_id: str) -> AsyncGenerator[str, None]:
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

    try:
        schema = db.get_schema()

        # For Postgres connections we need a DuckDB-compatible execute shim —
        # wrap the DatabaseConnection so the agent nodes can call it uniformly.
        # build_graph expects a duckdb connection but we've abstracted it away;
        # pass the DatabaseConnection object directly via a thin adapter.
        from hermes.agent.graph import build_graph_generic
        agent = build_graph_generic(db)

        initial_state: AgentState = {
            "question": question,
            "schema_context": schema,
            "hypotheses": [],
            "current_hypothesis_idx": 0,
            "query_history": [],
            "evidence_scores": [],
            "pitfalls": [],
            "iteration": 0,
            "max_iterations": int(os.getenv("HERMES_MAX_ITER", "6")),
            "report": None,
        }

        yield _sse("start", {"question": question, "connection_id": connection_id})
        merged = initial_state.copy()

        for event in agent.stream(initial_state):
            node_name = next(iter(event))
            partial = event[node_name]
            merged = {**merged, **partial}

            if node_name == "decompose" and merged.get("hypotheses"):
                yield _sse("hypotheses", {
                    "hypotheses": [h.model_dump() for h in merged["hypotheses"]],
                })

            elif node_name == "plan_and_execute":
                history = merged.get("query_history", [])
                recent = history[-3:]
                pitfalls = merged.get("pitfalls", [])
                new_pitfalls = pitfalls[-(len(recent)):] if pitfalls else []
                yield _sse("queries_executed", {
                    "iteration": merged.get("iteration", 0),
                    "hypothesis_idx": merged.get("current_hypothesis_idx", 0),
                    "queries": [{"sql": r.sql, "row_count": r.row_count, "error": r.error} for r in recent],
                    "corrections": [p.model_dump() for p in new_pitfalls],
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
                yield _sse("report", {
                    "report": merged["report"].model_dump(),
                    "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])],
                    "query_count": len(merged.get("query_history", [])),
                })

    except Exception as e:
        yield _sse("error", {"message": str(e)})
    finally:
        db.close()
        yield _sse("done", {})


@app.post("/investigate")
async def investigate(req: InvestigateRequest):
    return StreamingResponse(
        _stream_investigation(req.question, req.connection_id),
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


@app.get("/health")
def health():
    fixture = Path(__file__).parent.parent / "data" / "hermes.duckdb"
    return {"status": "ok", "fixture_db": fixture.exists()}
