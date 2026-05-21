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
from hermes.db.connection import open_connection, open_connection_for
from hermes.db.history import (
    delete_investigation,
    save_chat_turn,
    get_session_turns,
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
from hermes.semantic.metrics import MetricDefinition, delete_metric, get_metric, list_metrics, save_metric
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
    conn_type: str            # "duckdb" | "postgres"
    dsn: str                  # e.g. "postgresql://user:pass@host:5432/db" or path to .duckdb
    schema_name: Optional[str] = None  # restrict introspection + queries to this schema


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


import re as _re

# ── SQL table extractor ───────────────────────────────────────────────────────
_TABLE_RE = _re.compile(
    r'\b(?:FROM|JOIN)\s+(?:\w+\.)?(\w+)',
    _re.IGNORECASE,
)

def _extract_tables(sql: str) -> list[str]:
    """Return deduplicated table names referenced in FROM/JOIN clauses."""
    seen: dict[str, None] = {}
    for m in _TABLE_RE.finditer(sql):
        t = m.group(1)
        if t.lower() not in seen:
            seen[t.lower()] = None
    return list(seen.keys())


_DIRECT_SIGNALS = _re.compile(
    r'\b(show|list|what is|what are|what was|what were|how many|how much|'
    r'top \d|top\d|give me|fetch|get me|display|count|sum|total|average|avg|'
    r'breakdown|share of|distribution of|calculate|find|return)\b',
    _re.IGNORECASE,
)
_INVESTIGATE_SIGNALS = _re.compile(
    r'\b(why|cause|caused|causing|driver|drivers|reason|explain|diagnose|'
    r'investigate|what changed|what.s behind|contributing|anomaly|spike|drop|decline|surge)\b',
    _re.IGNORECASE,
)

def _looks_direct(question: str) -> bool:
    """
    Lightweight pre-filter: returns True if the question is likely a direct data
    retrieval request (so the semantic cache should be skipped).
    Errs on the side of skipping cache — false negatives (missed cache hits) are
    acceptable; false positives (caching live data) are not.
    """
    has_investigate = bool(_INVESTIGATE_SIGNALS.search(question))
    has_direct = bool(_DIRECT_SIGNALS.search(question))
    # Definite investigate signals override direct signals
    if has_investigate:
        return False
    return has_direct


# ── Chat endpoint ─────────────────────────────────────────────────────────────

class ChatHistoryTurn(BaseModel):
    question: str
    sql: str
    columns: list[str] = []
    headline: str = ""

class ChatRequest(BaseModel):
    question: str
    connection_id: str
    history: list[ChatHistoryTurn] = []
    session_id: str = ""

class _ChatAnswer(BaseModel):
    sql: str
    headline: str
    chart_type: str = "auto"

async def _stream_chat(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    request: Request,
    session_id: str = "",
) -> AsyncGenerator[str, None]:
    try:
        db = open_connection_for(connection_id)
    except KeyError as e:
        yield _sse("error", {"message": str(e)})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Could not connect: {e}"})
        return

    try:
        from hermes.agent.prompts import CHAT_PROMPT, CHAT_SQL_SYSTEM
        from hermes.llm.provider import get_provider
        from hermes.rules import get_chat_rules_block

        schema = db.get_schema()
        rules_block = get_chat_rules_block()

        # Build history section from last 3 turns
        history_section = ""
        if history:
            recent = history[-3:]
            lines = [
                "CONVERSATION HISTORY (use to resolve 'also', 'add', 'filter by', 'compare to'):"
            ]
            for i, t in enumerate(recent, 1):
                cols_str = ", ".join(t.columns[:6]) if t.columns else "—"
                lines.append(f"[Turn {i}] Q: {t.question!r}")
                lines.append(f"         SQL: {t.sql}")
                lines.append(f"         Columns: {cols_str}")
                if t.headline:
                    lines.append(f"         Headline: {t.headline}")
            history_section = "\n".join(lines) + "\n"

        # Compute schema qualifier for fully-qualified table names
        _schema_name = getattr(db, "_schema_name", None)
        if db.dialect == "duckdb":
            schema_qualifier = _schema_name or "main"
        else:
            schema_qualifier = _schema_name or "public"

        prompt = CHAT_PROMPT.format(
            schema=schema,
            history_section=history_section,
            question=question,
            schema_qualifier=schema_qualifier,
        )
        if rules_block:
            prompt = rules_block + prompt

        answer: _ChatAnswer = get_provider("coder").complete(
            system=CHAT_SQL_SYSTEM,
            user=prompt,
            response_model=_ChatAnswer,
        )

        final_sql = answer.sql
        yield _sse("sql", {"sql": final_sql})

        result = db.execute("chat", final_sql)

        # One self-correction attempt on error
        if result.error:
            from hermes.agent.prompts import FIX_SQL_PROMPT

            class _Fix(BaseModel):
                corrected_sql: str
                explanation: str
                data_quality_note: str = ""

            fix_prompt = FIX_SQL_PROMPT.format(
                schema=schema,
                dialect=db.dialect,
                sql=final_sql,
                error=result.error,
                kb_patterns_section="",
                error_diagnosis="",
            )
            try:
                fix: _Fix = get_provider("coder").complete(
                    system="Fix the SQL error. Return corrected_sql and a one-line explanation.",
                    user=fix_prompt,
                    response_model=_Fix,
                )
                result = db.execute("chat", fix.corrected_sql)
                if not result.error:
                    final_sql = fix.corrected_sql
                    yield _sse("sql", {"sql": final_sql})
            except Exception:
                pass

        if result.error:
            yield _sse("error", {"message": result.error})
            return

        yield _sse("columns", {"columns": result.columns})
        yield _sse("rows", {"rows": result.rows[:10000]})
        yield _sse("headline", {"headline": answer.headline})
        yield _sse("chart_type", {"chart_type": answer.chart_type})

        # Tables used + follow-up question suggestions
        yield _sse("tables_used", {"tables": _extract_tables(final_sql)})
        try:
            class _FollowUps(BaseModel):
                questions: list[str]
            fq: _FollowUps = get_provider("narrator").complete(
                system="Suggest exactly 3 concise follow-up data questions (max 12 words each).",
                user=(
                    f"Question: {question}\n"
                    f"Answer: {answer.headline}\n"
                    f"Columns: {', '.join(result.columns[:8])}"
                ),
                response_model=_FollowUps,
            )
            yield _sse("followups", {"questions": fq.questions[:3]})
        except Exception:
            pass  # follow-ups are best-effort

        # Persist to chat history (best-effort)
        try:
            save_chat_turn(
                question=question,
                connection_id=connection_id,
                headline=answer.headline or question,
                sql=final_sql or "",
                session_id=session_id,
                columns=result.columns,
                rows=result.rows,
                chart_type=answer.chart_type,
            )
        except Exception:
            pass

        yield _sse("done", {})

    except Exception as e:
        yield _sse("error", {"message": str(e)})
    finally:
        try:
            db.close()
        except Exception:
            pass


@app.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    return StreamingResponse(
        _stream_chat(req.question, req.connection_id, req.history, request, session_id=req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Investigation endpoint ────────────────────────────────────────────────────

async def _stream_investigation(question: str, connection_id: str, request: Request, hitl: bool = False) -> AsyncGenerator[str, None]:
    _TIMEOUT = int(os.getenv("HERMES_TIMEOUT_SECONDS", "600"))
    try:
        db = open_connection_for(connection_id)
    except KeyError as e:
        yield _sse("error", {"message": str(e)})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Could not connect: {e}"})
        return

    # ── Cache check: only for investigate-type questions ─────────────────────────
    # Direct queries fetch live data — cached results would be stale.
    # We use the same keyword signals as the router prompt to pre-filter cheaply,
    # without an extra LLM call. False-negatives (missed cache hits) are acceptable;
    # false-positives (caching a direct query result) are not.
    from hermes.tools.prior_analyses import find_similar_investigation
    from hermes.db.history import get_investigation
    cache_hit = None if _looks_direct(question) else find_similar_investigation(question, connection_id)
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
            "connection_id": connection_id,
            "schema_context": schema,
            "unresolved_tensions": [],
            "scan_context": "",
            "events_context": "",
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
            "route_reasoning": None,
            "route_confidence": None,
            "replan_decision": None,
            "sub_questions": [],
            "current_subq_idx": 0,
            "subq_answers": [],
            "explore_report": None,
            "investigation_phases": [],
            "ada_report": None,
            "_ada_intake": None,
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
                    "route_reasoning": merged.get("route_reasoning"),
                    "route_confidence": merged.get("route_confidence"),
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

            # ── ADA investigate phase events ──────────────────────────────────
            elif node_name in ("ada_intake", "ada_baseline", "ada_decompose",
                               "ada_dimensional", "ada_behavioral"):
                phases = merged.get("investigation_phases", [])
                if phases:
                    latest_phase = phases[-1]
                    yield _sse("phase_complete", {
                        "phase": latest_phase,
                        "all_phases": phases,
                    })

            elif node_name == "ada_synthesize" and merged.get("ada_report"):
                ada = merged["ada_report"]
                qh = merged.get("query_history", [])
                all_sql = " ".join(r.sql for r in qh if r.sql)
                yield _sse("tables_used", {"tables": _extract_tables(all_sql)})
                yield _sse("ada_report", {
                    "ada_report": ada,
                    "investigation_id": inv_id,
                    "query_mode": "investigate",
                })
                try:
                    from hermes.llm.provider import get_provider as _gp
                    class _FQ(BaseModel):
                        questions: list[str]
                    headline = ada.get("headline", "") if isinstance(ada, dict) else str(ada)[:200]
                    fq: _FQ = _gp("narrator").complete(
                        system="Suggest exactly 3 concise follow-up investigation questions (max 15 words each).",
                        user=f"Original question: {question}\nFindings: {headline}",
                        response_model=_FQ,
                    )
                    yield _sse("followups", {"questions": fq.questions[:3]})
                except Exception:
                    pass

            elif node_name == "decompose_exploration":
                subqs = merged.get("sub_questions", [])
                yield _sse("explore_plan", {
                    "sub_questions": [sq.model_dump() for sq in subqs],
                })

            elif node_name == "plan_and_execute_subq":
                # Reuse queries_executed event shape — subq_id in hypothesis_idx slot
                history = merged.get("query_history", [])
                idx = merged.get("current_subq_idx", 0)
                subqs = merged.get("sub_questions", [])
                current_subq = subqs[idx] if idx < len(subqs) else None
                recent = [r for r in history if r.hypothesis_id == (current_subq.id if current_subq else "")][-3:]
                pitfalls = merged.get("pitfalls", [])
                yield _sse("queries_executed", {
                    "iteration": merged.get("iteration", 0),
                    "hypothesis_idx": idx,
                    "subq_id": current_subq.id if current_subq else "",
                    "queries": [{"sql": r.sql, "row_count": r.row_count, "error": r.error, "stats": [s.model_dump() for s in (r.stats or [])]} for r in recent],
                    "corrections": [p.model_dump() for p in pitfalls[-2:]],
                    "stats": [s.model_dump() for r in recent for s in (r.stats or [])],
                })

            elif node_name == "reason_over_result":
                answers = merged.get("subq_answers", [])
                if answers:
                    latest = answers[-1]
                    yield _sse("subq_answer", {
                        "subq_id": latest.subq_id,
                        "question": latest.question,
                        "purpose": latest.purpose,
                        "answer": latest.answer,
                        "insight": latest.insight,
                        "refinement": latest.refinement,
                        "sql": latest.sql,
                        "columns": latest.columns,
                        "rows": latest.rows[:30],
                        "row_count": latest.row_count,
                        "error": latest.error,
                    })

            elif node_name == "synthesize_exploration" and merged.get("explore_report"):
                er = merged["explore_report"]
                answers = merged.get("subq_answers", [])
                query_history = merged.get("query_history", [])
                yield _sse("explore_report", {
                    "explore_report": er.model_dump(),
                    "sub_questions": [sq.model_dump() for sq in merged.get("sub_questions", [])],
                    "subq_answers": [a.model_dump() for a in answers],
                    "query_count": len(query_history),
                    "investigation_id": inv_id,
                    "query_mode": "explore",
                })

            elif node_name == "synthesize" and merged.get("report"):
                query_history = merged.get("query_history", [])
                all_sql = " ".join(r.sql for r in query_history if r.sql)
                yield _sse("tables_used", {"tables": _extract_tables(all_sql)})
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
                            "stats": [s.model_dump() for s in (r.stats or [])],
                        }
                        for r in query_history
                    ],
                    "investigation_id": inv_id,
                    "query_mode": merged.get("query_mode"),
                })
                try:
                    from hermes.llm.provider import get_provider as _gp
                    class _FQR(BaseModel):
                        questions: list[str]
                    rep = merged["report"]
                    summary = getattr(rep, "summary", "") or getattr(rep, "headline", "")
                    fqr: _FQR = _gp("narrator").complete(
                        system="Suggest exactly 3 concise follow-up investigation questions (max 15 words each).",
                        user=f"Original question: {question}\nFindings: {str(summary)[:300]}",
                        response_model=_FQR,
                    )
                    yield _sse("followups", {"questions": fqr.questions[:3]})
                except Exception:
                    pass

                # Persist to history; skip Qdrant indexing for direct queries
                # (live data changes — cached direct results would be stale)
                complete_investigation(
                    inv_id,
                    report=merged["report"],
                    hypotheses=merged.get("hypotheses", []),
                    query_history=query_history,
                    question=question,
                    connection_id=connection_id,
                    skip_index=merged.get("query_mode") == "direct",
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
        db = open_connection_for(inv["connection_id"])
    except KeyError as e:
        yield _sse("error", {"message": str(e)})
        yield _sse("done", {})
        return
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
        _TIMEOUT = int(os.getenv("HERMES_TIMEOUT_SECONDS", "600"))
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
                            "stats": [s.model_dump() for s in (r.stats or [])],
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
                    connection_id=inv.get("connection_id", ""),
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
    # Validate the connection before saving (with schema filter applied)
    try:
        db = open_connection(req.conn_type, req.dsn, schema_name=req.schema_name)
        ok, msg = db.test()
        db.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")

    if not ok:
        raise HTTPException(status_code=400, detail=f"Connection test failed: {msg}")

    meta = {"schema_name": req.schema_name} if req.schema_name else {}
    conn_id = add_connection(name=req.name, conn_type=req.conn_type, dsn=req.dsn, meta=meta)
    return {"id": conn_id, "message": "Connection added", "test_result": msg}


@app.post("/connections/{conn_id}/test")
def test_connection(conn_id: str):
    try:
        db = open_connection_for(conn_id)
        ok, msg = db.test()
        db.close()
        return {"ok": ok, "message": msg}
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/connections/{conn_id}/schema")
def connection_schema(conn_id: str):
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        schema = db.get_schema()
        db.close()
        return {"schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connections/{conn_id}/schema/rich")
def connection_schema_rich(conn_id: str):
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        from hermes.tools.schema import build_rich_schema
        schema = db.get_schema()
        db.close()
        return build_rich_schema(schema)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connections/{conn_id}/schema/mermaid")
def connection_schema_mermaid(conn_id: str):
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        from hermes.tools.schema import build_mermaid_er
        schema = db.get_schema()
        db.close()
        return {"diagram": build_mermaid_er(schema)}
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


# ── Metrics Catalog ───────────────────────────────────────────────────────────

class MetricRequest(BaseModel):
    name: str
    label: str
    sql: str
    tables: list[str] = []
    dimensions: list[str] = []
    filters: list[str] = []
    unit: Optional[str] = None
    caveats: Optional[str] = None


@app.get("/metrics")
def get_metrics():
    return [m.model_dump() for m in list_metrics()]


@app.post("/metrics", status_code=201)
def create_metric(req: MetricRequest):
    if get_metric(req.name):
        raise HTTPException(status_code=409, detail=f"Metric '{req.name}' already exists. Use PUT to update.")
    m = MetricDefinition(**req.model_dump())
    save_metric(m)
    return m.model_dump()


@app.put("/metrics/{name}")
def update_metric(name: str, req: MetricRequest):
    m = MetricDefinition(**{**req.model_dump(), "name": name})
    save_metric(m)
    return m.model_dump()


@app.delete("/metrics/{name}")
def remove_metric(name: str):
    if not delete_metric(name):
        raise HTTPException(status_code=404, detail=f"Metric '{name}' not found.")
    return {"ok": True, "name": name}


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


@app.get("/chat-sessions/{session_id}/turns")
def get_chat_session_turns(session_id: str):
    turns = get_session_turns(session_id)
    if not turns:
        raise HTTPException(status_code=404, detail="Session not found")
    return turns


@app.get("/investigations/{inv_id}")
def get_investigation_detail(inv_id: str):
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


@app.delete("/investigations/{inv_id}", status_code=204)
def delete_investigation_endpoint(inv_id: str):
    deleted = delete_investigation(inv_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Investigation not found")


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
            connection_id=row.get("connection_id", ""),
        )
        indexed += 1
    return {"indexed": indexed, "skipped": skipped}


@app.get("/health")
def health():
    fixture = Path(__file__).parent.parent / "data" / "hermes.duckdb"
    return {"status": "ok", "fixture_db": fixture.exists()}


# ── Schema-aware starter suggestions ─────────────────────────────────────────

class _Suggestion(BaseModel):
    text: str
    mode: str   # "ask" | "investigate"

class _Suggestions(BaseModel):
    suggestions: list[_Suggestion]

@app.get("/suggestions")
def get_suggestions(connection_id: str = BUILTIN_ID):
    """Return 6 starter questions tailored to the schema of the given connection.

    Flow:
      1. Fetch schema summary from the DB connection.
      2. Compute a fingerprint of the summary.
      3. Check Qdrant for cached suggestions matching (connection_id, fingerprint).
         → Cache hit:  return instantly, zero LLM calls.
         → Cache miss: call LLM, embed results, store in Qdrant, return.
    """
    from hermes.semantic.suggestions_cache import (
        schema_fingerprint, get_cached, store as cache_store,
    )

    try:
        db = open_connection_for(connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        schema_summary: str = db.get_schema()
        db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    fingerprint = schema_fingerprint(schema_summary)

    # ── Cache hit ─────────────────────────────────────────────────────────────
    try:
        cached = get_cached(connection_id, fingerprint)
        if cached:
            return {"suggestions": cached, "cached": True}
    except Exception:
        pass  # Qdrant unavailable — fall through to LLM

    # ── Cache miss: generate via LLM ─────────────────────────────────────────
    system = (
        "You are a data analyst assistant. Given a database schema, produce exactly 6 "
        "starter questions a business user might ask. "
        "Mix question types: 4 should be simple analytical questions (mode='ask') and "
        "2 should be deeper diagnostic questions (mode='investigate'). "
        "Make every question specific to the actual table and column names provided — "
        "no generic placeholders. Keep each question concise (under 12 words)."
    )
    user = f"Database schema:\n{schema_summary}\n\nReturn 6 starter questions."

    from hermes.llm.provider import get_provider
    result: _Suggestions = get_provider("coder").complete(
        system=system,
        user=user,
        response_model=_Suggestions,
        temperature=0.4,
    )
    suggestions = [s.model_dump() for s in result.suggestions]

    # ── Store in Qdrant asynchronously (best-effort) ──────────────────────────
    try:
        cache_store(connection_id, fingerprint, suggestions)
    except Exception:
        pass  # embedding or Qdrant failure — still return the suggestions

    return {"suggestions": suggestions, "cached": False}
