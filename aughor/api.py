"""FastAPI backend — SSE investigation streaming + connection management."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import AsyncGenerator, Optional

# Load .env from the project root (no-op if python-dotenv not installed)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from aughor.agent.graph import build_graph
from aughor.agent.state import AgentState
from aughor.db.connection import open_connection, open_connection_for
from aughor.db.history import (
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
from aughor.db.registry import (
    BUILTIN_ID,
    add_connection,
    delete_connection,
    get_dsn,
    list_connections,
    get_connection_settings,
    update_connection_settings,
)
from aughor.explorer.models import ExplorationPhase
from aughor.semantic.glossary import load_glossary, update_column, update_table
from aughor.semantic.metrics import MetricDefinition, delete_metric, get_metric, list_metrics, save_metric
from aughor.tools.schema import build_schema_context

logger = logging.getLogger(__name__)

app = FastAPI(title="Aughor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Schema string cache ───────────────────────────────────────────────────────
# Eliminates repeated COUNT(*) + profiling + ontology rebuild on every HTTP request.
# Each entry: conn_id → (timestamp_float, schema_str)
# TTL: 5 minutes. Invalidated on connection delete or explicit ontology rebuild.

import time as _time

_schema_cache: dict[str, tuple[float, str]] = {}
_SCHEMA_CACHE_TTL = 300.0  # seconds


def _get_schema_cached(conn_id: str, db) -> str:
    cached = _schema_cache.get(conn_id)
    if cached and (_time.monotonic() - cached[0]) < _SCHEMA_CACHE_TTL:
        return cached[1]
    schema = db.get_schema()
    _schema_cache[conn_id] = (_time.monotonic(), schema)
    return schema


def _invalidate_schema_cache(conn_id: str) -> None:
    _schema_cache.pop(conn_id, None)


# ── Background explorer registry ──────────────────────────────────────────────

_explorers: dict = {}       # conn_id → SchemaExplorer
_explorer_tasks: dict = {}  # conn_id → asyncio.Task


@app.on_event("startup")
async def _start_explorers() -> None:
    """Resume background exploration only for connections that were already in progress.

    We do NOT auto-start exploration for every registered connection — that wastes
    resources on connections the user isn't actively using.  Instead we only resume
    connections whose exploration store file already exists (i.e. they were previously
    started by the user).  New connections must be explicitly started via the
    POST /exploration/{conn_id}/resume  or  /restart  endpoints.
    """
    from aughor.explorer.agent import SchemaExplorer
    from pathlib import Path as _Path

    def _store_path(conn_id: str) -> _Path:
        return _Path("data") / f"exploration_{conn_id}.json"

    for conn_info in list_connections():
        conn_id = conn_info["id"]
        # Skip connections that have never been explored
        if not _store_path(conn_id).exists():
            logger.info("Explorer skipped for %s — no prior exploration state", conn_id)
            continue
        try:
            db = open_connection_for(conn_id)
            ok, msg = db.test()
            if not ok:
                logger.info("Explorer skipped for %s — connection unreachable: %s", conn_id, msg)
                db.close()
                continue
            explorer = SchemaExplorer(conn_id, db)
            _explorers[conn_id] = explorer
            task = asyncio.create_task(explorer.explore(), name=f"explorer-{conn_id}")
            _explorer_tasks[conn_id] = task
            logger.info("Explorer resumed for connection %s", conn_id)
        except Exception as exc:
            logger.warning("Could not resume explorer for %s: %s", conn_id, exc)


async def _ontology_refresh_loop() -> None:
    """Background loop that rebuilds ontology for connections with a scheduled refresh."""
    from datetime import datetime, timezone, timedelta
    from aughor.ontology.store import load_latest_ontology, invalidate as invalidate_ontology

    CHECK_INTERVAL = 3600  # check every hour
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            for conn_info in list_connections():
                conn_id = conn_info["id"]
                settings = get_connection_settings(conn_id)
                refresh_hours = settings.get("ontology_refresh_hours")
                if not refresh_hours:
                    continue
                try:
                    graph = load_latest_ontology(conn_id)
                    if graph is not None:
                        generated_at = datetime.fromisoformat(graph.generated_at)
                        age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600
                        if age_hours < refresh_hours:
                            continue
                    # Invalidate cache and trigger rebuild on next access
                    invalidate_ontology(conn_id)
                    # Eagerly rebuild
                    db = open_connection_for(conn_id)
                    db.get_schema()
                    db.close()
                    logger.info("Ontology refreshed for connection %s (age %.1fh >= %dh)", conn_id, age_hours if graph else -1, refresh_hours)
                except Exception as exc:
                    logger.warning("Ontology refresh failed for %s: %s", conn_id, exc)
        except Exception as exc:
            logger.warning("Ontology refresh loop error: %s", exc)


@app.on_event("startup")
async def _start_ontology_refresh_loop() -> None:
    asyncio.create_task(_ontology_refresh_loop(), name="ontology-refresh")


@app.on_event("startup")
async def _seed_playbook() -> None:
    """Seed playbook from KB on first startup when data/playbook.json is empty."""
    try:
        from aughor.playbook.builder import seed_from_kb
        n = seed_from_kb()
        if n:
            import logging
            logging.getLogger(__name__).info("Playbook seeded with %d entries from KB.", n)
    except Exception:
        pass


# ── Request / response models ────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    question: str
    connection_id: str = BUILTIN_ID
    hitl: bool = False
    skip_cache: bool = False  # when True, bypass semantic cache and run fresh


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


async def _aiter_sync(sync_iter):
    """
    Wrap a synchronous iterator so each next() call runs in the default
    thread-pool executor.  This prevents LangGraph node executions (LLM calls,
    SQL queries) from blocking FastAPI's asyncio event loop — allowing other
    HTTP requests (history, exploration status, etc.) to be served concurrently
    while an investigation is running.
    """
    loop = asyncio.get_event_loop()
    it = iter(sync_iter)
    while True:
        try:
            item = await loop.run_in_executor(None, next, it)
        except StopIteration:
            break
        yield item

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
        from aughor.agent.prompts import CHAT_PROMPT, CHAT_SQL_SYSTEM
        from aughor.llm.provider import get_provider
        from aughor.rules import get_chat_rules_block

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

        # Retrieve relevant KB patterns (business definitions, SQL patterns) for this question
        try:
            from aughor.semantic.kb_retriever import retrieve_for_planning
            kb_patterns_section = retrieve_for_planning(question, top_k=2)
            if kb_patterns_section:
                kb_patterns_section += "\n\n"
        except Exception:
            kb_patterns_section = ""

        # Retrieve validated SQL examples from past investigations on this connection
        try:
            from aughor.tools.prior_analyses import search_sql_examples
            sql_examples_section = search_sql_examples(question, connection_id)
        except Exception:
            sql_examples_section = ""

        prompt = CHAT_PROMPT.format(
            schema=schema,
            history_section=history_section,
            question=question,
            schema_qualifier=schema_qualifier,
            kb_patterns_section=kb_patterns_section,
            sql_examples_section=sql_examples_section,
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

        # One self-correction attempt on error OR suspicious zero-row result
        from aughor.agent.investigate import _zero_row_suspicious
        _chat_zero_diag = None
        if not result.error and result.row_count == 0:
            _chat_zero_diag = _zero_row_suspicious(final_sql)

        if result.error or _chat_zero_diag:
            from aughor.sql.writer import SqlWriter
            writer = SqlWriter(db, schema_str=schema)
            _fix_error = result.error or "Query returned 0 rows — the SQL logic is likely wrong."
            _fix_hint  = _chat_zero_diag or ""
            try:
                fix = writer.fix(final_sql, _fix_error, hint=_fix_hint, max_retries=1)
                if fix.ok:
                    retry = db.execute("chat", fix.sql)
                    if not retry.error and (retry.row_count > 0 or not _chat_zero_diag):
                        final_sql = fix.sql
                        result = retry
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

async def _stream_investigation(question: str, connection_id: str, request: Request, hitl: bool = False, skip_cache: bool = False) -> AsyncGenerator[str, None]:
    _TIMEOUT = int(os.getenv("AUGHOR_TIMEOUT_SECONDS", "600"))
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
    from aughor.tools.prior_analyses import find_similar_investigation
    from aughor.db.history import get_investigation
    cache_hit = None if (skip_cache or _looks_direct(question)) else find_similar_investigation(question, connection_id)
    if cache_hit:
        cached_id, score = cache_hit
        cached = get_investigation(cached_id)
        if cached and cached.get("report"):
            cached_report = cached["report"]
            report_type = cached_report.get("_report_type") if isinstance(cached_report, dict) else None
            yield _sse("start", {
                "question": question,
                "connection_id": connection_id,
                "investigation_id": cached_id,
            })
            if cached.get("hypotheses"):
                yield _sse("hypotheses", {"hypotheses": cached["hypotheses"]})
            qh = cached.get("query_history") or []
            if report_type == "investigate":
                yield _sse("ada_report", {
                    "ada_report": cached_report,
                    "investigation_id": cached_id,
                    "query_mode": "investigate",
                    "from_cache": True,
                    "cached_question": cached["question"],
                    "cache_score": round(score, 3),
                })
            elif report_type == "explore":
                yield _sse("explore_report", {
                    "explore_report": cached_report,
                    "sub_questions": cached_report.get("sub_questions", []),
                    "subq_answers": cached_report.get("subq_answers", []),
                    "query_count": cached.get("query_count", len(qh)),
                    "investigation_id": cached_id,
                    "query_mode": "explore",
                    "from_cache": True,
                    "cached_question": cached["question"],
                    "cache_score": round(score, 3),
                })
            else:
                yield _sse("report", {
                    "report": cached_report,
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

    _active_explorer = _explorers.get(connection_id)
    if _active_explorer:
        _active_explorer.pause()

    try:
        schema = db.get_schema()

        from aughor.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=hitl)

        initial_state: AgentState = {
            "question": question,
            "connection_id": connection_id,
            "investigation_id": inv_id,
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
            "max_iterations": int(os.getenv("AUGHOR_MAX_ITER", "6")),
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

        async for event in _aiter_sync(agent.stream(initial_state, config={"configurable": {"thread_id": inv_id}})):
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
                    from aughor.llm.provider import get_provider as _gp
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
                # Persist ADA investigation to history
                ada_save = dict(ada) if isinstance(ada, dict) else ada
                ada_save["_report_type"] = "investigate"
                complete_investigation(
                    inv_id,
                    report=ada_save,
                    hypotheses=merged.get("hypotheses", []),
                    query_history=qh,
                    question=question,
                    connection_id=connection_id,
                    skip_index=False,
                )

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
                sub_questions_raw = [sq.model_dump() for sq in merged.get("sub_questions", [])]
                subq_answers_raw = [a.model_dump() for a in answers]
                all_sql_e = " ".join(r.sql for r in query_history if r.sql)
                yield _sse("tables_used", {"tables": _extract_tables(all_sql_e)})
                yield _sse("explore_report", {
                    "explore_report": er.model_dump(),
                    "sub_questions": sub_questions_raw,
                    "subq_answers": subq_answers_raw,
                    "query_count": len(query_history),
                    "investigation_id": inv_id,
                    "query_mode": "explore",
                })
                # Follow-up suggestions for explore mode
                try:
                    from aughor.llm.provider import get_provider as _gp
                    class _FQX(BaseModel):
                        questions: list[str]
                    fqx: _FQX = _gp("narrator").complete(
                        system="Suggest exactly 3 concise follow-up questions (max 15 words each).",
                        user=f"Original question: {question}\nFindings: {er.headline}",
                        response_model=_FQX,
                    )
                    yield _sse("followups", {"questions": fqx.questions[:3]})
                except Exception:
                    pass
                # Persist explore investigation to history (store subq data inside report_json)
                explore_save = {
                    "_report_type": "explore",
                    **er.model_dump(),
                    "sub_questions": sub_questions_raw,
                    "subq_answers": subq_answers_raw,
                }
                complete_investigation(
                    inv_id,
                    report=explore_save,
                    hypotheses=[],
                    query_history=query_history,
                    question=question,
                    connection_id=connection_id,
                    skip_index=False,
                )

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
                    from aughor.llm.provider import get_provider as _gp
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
        if _active_explorer:
            _active_explorer.resume()
        db.close()
        yield _sse("done", {})


@app.post("/investigate")
async def investigate(req: InvestigateRequest, request: Request):
    return StreamingResponse(
        _stream_investigation(req.question, req.connection_id, request, hitl=req.hitl, skip_cache=req.skip_cache),
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
        from aughor.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=True)
        config = {"configurable": {"thread_id": inv_id}}

        # Seed merged with the full checkpointed state so synthesize's partial output
        # is merged on top (synthesize only returns {"report": ...}, not hypotheses)
        checkpoint = agent.get_state(config)
        merged: dict = dict(checkpoint.values) if checkpoint else {}

        # Inject analyst feedback into the checkpointed state
        agent.update_state(config, {"human_feedback": feedback})

        import time
        _TIMEOUT = int(os.getenv("AUGHOR_TIMEOUT_SECONDS", "600"))
        deadline = time.monotonic() + _TIMEOUT

        async for event in _aiter_sync(agent.stream(None, config=config)):
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
async def create_connection(req: AddConnectionRequest):
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

    # Kick off background exploration for the new connection
    try:
        from aughor.explorer.agent import SchemaExplorer
        db_explorer = open_connection(req.conn_type, req.dsn, schema_name=req.schema_name)
        explorer = SchemaExplorer(conn_id, db_explorer)
        _explorers[conn_id] = explorer
        task = asyncio.create_task(explorer.explore(), name=f"explorer-{conn_id}")
        _explorer_tasks[conn_id] = task
    except Exception as exc:
        logger.warning("Could not start explorer for new connection %s: %s", conn_id, exc)

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
        schema = _get_schema_cached(conn_id, db)
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
        from aughor.tools.schema import build_rich_schema
        schema = _get_schema_cached(conn_id, db)
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
        from aughor.tools.schema import build_mermaid_er
        schema = _get_schema_cached(conn_id, db)
        db.close()
        return {"diagram": build_mermaid_er(schema)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/connections/{conn_id}", status_code=204)
def remove_connection(conn_id: str):
    # Stop background explorer before removing the connection
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


@app.get("/exploration/{conn_id}/status")
def get_exploration_status(conn_id: str):
    """Return the current background exploration status for a connection."""
    from aughor.explorer import store as _expl_store
    explorer = _explorers.get(conn_id)
    if explorer:
        return explorer._status.to_dict()
    # Explorer not running — return a summary derived from the persisted state
    state = _expl_store.load(conn_id)
    return {
        "connection_id": conn_id,
        "phase": state.get("phase", "pending"),
        "paused": False,
        "tables_total": 0,
        "columns_total": 0,
        "joins_total": 0,
        "null_meanings_resolved": len(state.get("null_meanings", {})),
        "joins_verified": sum(1 for j in state.get("join_verifications", []) if j.get("verified")),
        "lifecycles_mapped": len(state.get("lifecycle_maps", {})),
        "distributions_profiled": len(state.get("distributions", {})),
        "insights_found": len(state.get("insights", [])),
        "queries_executed": 0,
        "facts_discovered": 0,
        "started_at": None,
        "completed_at": None,
        "error": None,
    }


@app.get("/exploration/{conn_id}/findings")
def get_exploration_findings(conn_id: str):
    """Return all exploration findings for a connection — null meanings, join verifications,
    lifecycle maps, distributions, and cross-table insights."""
    from aughor.explorer import store as _expl_store
    state = _expl_store.load(conn_id)
    distributions = state.get("distributions", {})

    # Backfill col_type for entries saved before the field was added
    if distributions and any("col_type" not in v for v in distributions.values()):
        try:
            import json
            from pathlib import Path
            cache_path = Path(__file__).parent.parent / "data" / "schema_profiles.json"
            if cache_path.exists():
                cache = json.loads(cache_path.read_text())
                # Find the most recent entry for this connection (any fingerprint)
                col_dtype_map: dict[str, str] = {}
                for cache_key, entry in cache.items():
                    if cache_key.startswith(f"{conn_id}:"):
                        for flat_key, col_data in entry.get("columns", {}).items():
                            if isinstance(col_data, dict) and "dtype" in col_data:
                                col_dtype_map[flat_key] = col_data["dtype"]
                if col_dtype_map:
                    for key, dist in distributions.items():
                        if "col_type" not in dist:
                            table, col = key.split(":", 1)
                            dist["col_type"] = col_dtype_map.get(f"{table}.{col}")
        except Exception:
            pass

    return {
        "connection_id": conn_id,
        "phase": state.get("phase", "pending"),
        "null_meanings": state.get("null_meanings", {}),
        "join_verifications": state.get("join_verifications", []),
        "lifecycle_maps": state.get("lifecycle_maps", {}),
        "distributions": distributions,
        "insights": state.get("insights", []),
    }


@app.get("/exploration/{conn_id}/domains")
def get_domain_insights(conn_id: str):
    """Return insights grouped by domain, with per-domain budget/coverage metadata."""
    from aughor.explorer import store as _expl_store
    state = _expl_store.load(conn_id)
    budgets  = state.get("domain_budgets", {})
    coverage = state.get("domain_coverage", {})
    by_domain = _expl_store.get_domain_insights(conn_id)
    result = {}
    for domain, insights in by_domain.items():
        result[domain] = {
            "insights": insights,
            "queries_used": budgets.get(domain, 0),
            "budget_cap":   budgets.get(f"{domain}__cap", 15),
            "angles_covered": coverage.get(domain, []),
        }
    return result


@app.post("/exploration/{conn_id}/domains/{domain}/extend")
async def extend_domain_budget(conn_id: str, domain: str):
    """Add 5 more queries to a domain's budget and re-trigger exploration if complete."""
    from aughor.explorer import store as _expl_store
    new_cap = _expl_store.extend_domain_budget(conn_id, domain, extra=5)

    existing = _explorers.get(conn_id)
    if existing is not None and existing.status.phase not in (
        ExplorationPhase.COMPLETE, ExplorationPhase.FAILED
    ):
        # Explorer is still running — update in-memory cap so the loop picks it up
        existing._state.setdefault("domain_budgets", {})[f"{domain}__cap"] = new_cap
    else:
        # Exploration finished — restart phase 8 only
        try:
            from aughor.explorer.agent import SchemaExplorer
            db = open_connection_for(conn_id)
            explorer = SchemaExplorer(conn_id, db)
            _explorers[conn_id] = explorer
            _explorer_tasks[conn_id] = asyncio.create_task(
                explorer.explore(domain_intel_only=True), name=f"explorer-{conn_id}-extend"
            )
        except Exception as exc:
            logger.warning("Could not restart explorer for %s after extend: %s", conn_id, exc)

    return {"ok": True, "domain": domain, "extra": 5}


@app.get("/exploration/{conn_id}/episodes")
def get_exploration_episodes(conn_id: str, phase: str = "", limit: int = 300):
    """Return the last N episode entries from the JSONL log, optionally filtered by phase."""
    p = Path("data") / f"episodes_{conn_id}.jsonl"
    if not p.exists():
        return []
    lines = p.read_text().strip().splitlines()
    entries: list[dict] = []
    for line in lines:
        try:
            e = json.loads(line)
            if not phase or e.get("phase") == phase:
                entries.append(e)
        except Exception:
            pass
    return entries[-limit:]


@app.post("/exploration/{conn_id}/stop")
def stop_exploration(conn_id: str):
    """Stop the background explorer for a connection."""
    explorer = _explorers.get(conn_id)
    if explorer:
        explorer.stop()
        explorer._status.paused = True   # mark as stopped so status reflects it across tab switches
    task = _explorer_tasks.get(conn_id)
    if task and not task.done():
        task.cancel()
    return {"ok": True, "stopped": explorer is not None}


@app.post("/exploration/{conn_id}/resume")
async def resume_exploration(conn_id: str):
    """Resume exploration from saved state — skips already-completed phases."""
    existing = _explorers.get(conn_id)
    if existing and existing.status.phase not in (
        ExplorationPhase.COMPLETE, ExplorationPhase.FAILED
    ):
        return {"ok": False, "reason": "already running"}
    try:
        from aughor.explorer.agent import SchemaExplorer
        db = open_connection_for(conn_id)
        explorer = SchemaExplorer(conn_id, db)
        _explorers[conn_id] = explorer
        _explorer_tasks[conn_id] = asyncio.create_task(
            explorer.explore(), name=f"explorer-{conn_id}-resume"
        )
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/exploration/{conn_id}/restart")
async def restart_exploration(conn_id: str):
    """Wipe exploration findings and start a completely fresh run."""
    # Stop any running explorer first
    explorer = _explorers.get(conn_id)
    if explorer:
        explorer.stop()
    task = _explorer_tasks.get(conn_id)
    if task and not task.done():
        task.cancel()
    # Clear all persisted state — findings AND episode log
    p = Path("data") / f"exploration_{conn_id}.json"
    if p.exists():
        p.unlink()
    ep = Path("data") / f"episodes_{conn_id}.jsonl"
    if ep.exists():
        ep.unlink()
    try:
        from aughor.explorer.agent import SchemaExplorer
        db = open_connection_for(conn_id)
        new_explorer = SchemaExplorer(conn_id, db)
        _explorers[conn_id] = new_explorer
        _explorer_tasks[conn_id] = asyncio.create_task(
            new_explorer.explore(), name=f"explorer-{conn_id}-restart"
        )
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class RetryQueryRequest(BaseModel):
    sql: str
    error: str
    hint: str = ""
    domain: str = ""


@app.post("/exploration/{conn_id}/retry-query")
async def retry_query(conn_id: str, body: RetryQueryRequest):
    """Fix a failed SQL query using SqlWriter, execute it, and return the result."""
    from aughor.sql.writer import SqlWriter

    try:
        db = open_connection_for(conn_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Connection not found: {e}")

    writer = SqlWriter(db)
    fix = writer.fix(body.sql, body.error, hint=body.hint, max_retries=2)

    if not fix.ok:
        raise HTTPException(status_code=422, detail=f"LLM correction failed: {fix.final_error}")

    # Execute the corrected SQL
    try:
        result = db.execute("__retry__", fix.sql)
        if result.error:
            return {
                "ok": False,
                "corrected_sql": fix.sql,
                "explanation": fix.explanation,
                "error": result.error,
                "rows": [],
                "columns": [],
            }
        rows = (result.rows or [])[:50]
        return {
            "ok": True,
            "corrected_sql": fix.sql,
            "explanation": fix.explanation,
            "rows": [[str(c) for c in r] for r in rows],
            "columns": result.columns or [],
            "row_count": result.row_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {e}")


@app.get("/dev/stats")
def get_dev_stats():
    """Return in-process stats counters — corrections, tier gates, RAG, enrichment."""
    from aughor.stats import stats
    return stats.snapshot()


@app.post("/dev/stats/reset")
def reset_dev_stats():
    """Reset all counters to zero. Useful when starting a fresh measurement window."""
    from aughor.stats import stats
    stats.reset()
    return {"ok": True}


_INSTRUCTIONS_FILE = Path(__file__).parent.parent / "data" / "instructions.json"


def _load_instructions() -> dict:
    if _INSTRUCTIONS_FILE.exists():
        return json.loads(_INSTRUCTIONS_FILE.read_text())
    return {}


@app.get("/connections/{conn_id}/freshness")
def connection_freshness(conn_id: str):
    """Return the most recent data timestamp found across date columns in the connection."""
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        from aughor.tools.schema import _parse_schema_tables
        schema_str = db.get_schema()
        table_cols = _parse_schema_tables(schema_str)
    except Exception:
        db.close()
        return {"freshness": None, "source": None}

    _DATE_PAT = re.compile(
        r"(_at|_date|_time|_ts|timestamp|created|updated|modified|inserted)$",
        re.IGNORECASE,
    )
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


@app.get("/connections/{conn_id}/tables/{table}/sample")
def table_sample(conn_id: str, table: str, limit: int = 100):
    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        # Use parameterised table name to prevent injection via identifier quoting
        safe_table = table.replace('"', '')
        result = db.execute("sample", f'SELECT * FROM "{safe_table}" LIMIT {int(limit)}')
        columns = result.columns
        rows = [[str(v) if v is not None else None for v in row] for row in result.rows]
        db.close()
        return {"columns": columns, "rows": rows}
    except Exception as e:
        try:
            db.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))


class InstructionsRequest(BaseModel):
    text: str


@app.get("/connections/{conn_id}/instructions")
def get_instructions(conn_id: str):
    data = _load_instructions()
    return {"text": data.get(conn_id, {}).get("text", "")}


@app.put("/connections/{conn_id}/instructions")
def put_instructions(conn_id: str, req: InstructionsRequest):
    data = _load_instructions()
    data.setdefault(conn_id, {})["text"] = req.text
    _INSTRUCTIONS_FILE.write_text(json.dumps(data, indent=2))
    return {"ok": True}


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
    target_value: Optional[float] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    target_period: Optional[str] = None
    benchmark_source: Optional[str] = None


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


@app.get("/connections/{conn_id}/health-scorecard")
def get_health_scorecard(conn_id: str):
    """
    For each MetricDefinition with a target_value, execute its SQL against the
    connection and return current value, target, variance, and health status.
    """
    targeted = [m for m in list_metrics() if m.target_value is not None]
    if not targeted:
        return []

    try:
        db = open_connection_for(conn_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection not found")

    results = []
    for metric in targeted:
        try:
            qr = db.execute(f"SELECT ({metric.sql}) AS _v")
            rows = qr.rows if qr else []
            current: Optional[float] = None
            if rows and rows[0]:
                raw = rows[0][0] if isinstance(rows[0], (list, tuple)) else list(rows[0].values())[0]
                try:
                    current = float(raw)
                except (TypeError, ValueError):
                    current = None

            if current is None:
                status = "unknown"
                variance = None
            else:
                variance = (current - metric.target_value) / metric.target_value if metric.target_value else None
                if metric.critical_threshold is not None and abs(current - metric.target_value) >= metric.critical_threshold:
                    status = "red"
                elif metric.warning_threshold is not None and abs(current - metric.target_value) >= metric.warning_threshold:
                    status = "yellow"
                else:
                    status = "green"

            results.append({
                "name": metric.name,
                "label": metric.label,
                "current": current,
                "target": metric.target_value,
                "variance": variance,
                "status": status,
                "unit": metric.unit,
                "target_period": metric.target_period,
                "benchmark_source": metric.benchmark_source,
            })
        except Exception:
            results.append({
                "name": metric.name,
                "label": metric.label,
                "current": None,
                "target": metric.target_value,
                "variance": None,
                "status": "unknown",
                "unit": metric.unit,
                "target_period": metric.target_period,
                "benchmark_source": metric.benchmark_source,
            })

    try:
        db.close()
    except Exception:
        pass
    return results


# ── Playbook ──────────────────────────────────────────────────────────────────

class PlaybookEntryRequest(BaseModel):
    trigger_metric: str
    trigger_condition: str
    trigger_operator: str = "any"
    trigger_value: float = 0.0
    recommendation: str
    expected_impact: str = ""
    typical_timeline: str = ""
    owner_role: str = ""
    tags: list[str] = []
    status: str = "draft"
    source_kb_id: Optional[str] = None


@app.get("/playbook")
def get_playbook():
    from aughor.playbook.store import list_entries
    return [e.model_dump() for e in list_entries()]


@app.get("/playbook/{entry_id}")
def get_playbook_entry(entry_id: str):
    from aughor.playbook.store import get_entry
    e = get_entry(entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Entry not found")
    return e.model_dump()


@app.post("/playbook", status_code=201)
def create_playbook_entry(req: PlaybookEntryRequest):
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.store import save_entry
    import uuid
    entry = PlaybookEntry(id=f"user_{uuid.uuid4().hex[:12]}", **req.model_dump())
    save_entry(entry)
    return entry.model_dump()


@app.put("/playbook/{entry_id}")
def update_playbook_entry(entry_id: str, req: PlaybookEntryRequest):
    from aughor.playbook.models import PlaybookEntry
    from aughor.playbook.store import get_entry, save_entry
    existing = get_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Entry not found")
    updated = PlaybookEntry(
        id=entry_id,
        evidence_sources=existing.evidence_sources,
        historical_success_rate=existing.historical_success_rate,
        **req.model_dump(),
    )
    save_entry(updated)
    return updated.model_dump()


@app.delete("/playbook/{entry_id}")
def delete_playbook_entry(entry_id: str):
    from aughor.playbook.store import delete_entry
    if not delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True, "id": entry_id}


@app.post("/playbook/seed")
def reseed_playbook():
    """Force re-seed of playbook from KB (overwrites existing entries)."""
    from aughor.playbook.builder import seed_from_kb
    n = seed_from_kb(force=True)
    return {"seeded": n}


# ── Outcome Tracking ─────────────────────────────────────────────────────────

class OutcomeRequest(BaseModel):
    rec_text: str
    status: str  # accepted | rejected | implemented | verified | dismissed
    metric_name: Optional[str] = None
    metric_before: Optional[float] = None
    metric_after: Optional[float] = None


@app.post("/investigations/{inv_id}/recommendations/{rec_index}/outcome", status_code=201)
def log_recommendation_outcome(inv_id: str, rec_index: int, req: OutcomeRequest):
    from aughor.playbook.outcomes import log_outcome, update_playbook_success_rates
    outcome = log_outcome(
        inv_id=inv_id,
        rec_index=rec_index,
        rec_text=req.rec_text,
        status=req.status,  # type: ignore[arg-type]
        metric_name=req.metric_name,
        metric_before=req.metric_before,
        metric_after=req.metric_after,
    )
    if req.status in ("verified", "rejected"):
        update_playbook_success_rates()
    return outcome.model_dump()


@app.get("/investigations/{inv_id}/outcomes")
def get_investigation_outcomes(inv_id: str):
    from aughor.playbook.outcomes import load_outcomes_for_inv
    return [o.model_dump() for o in load_outcomes_for_inv(inv_id)]


@app.get("/investigations/indexed-ids")
def get_indexed_ids():
    """Return the set of investigation IDs that have been indexed in Qdrant."""
    from aughor.tools.prior_analyses import INVESTIGATIONS_COLLECTION
    from aughor.semantic.vector_store import scroll_payloads
    payloads = scroll_payloads(INVESTIGATIONS_COLLECTION)
    return {"ids": [p["inv_id"] for p in payloads if p.get("inv_id")]}


@app.get("/investigations")
def get_investigations(limit: int = 50):
    return list_investigations(limit=limit)


# ── Document Ingestion ────────────────────────────────────────────────────────

@app.post("/documents/upload", status_code=201)
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF, Word, Markdown, or plain-text document for semantic indexing."""
    import tempfile
    from pathlib import Path as _Path
    allowed = {".pdf", ".docx", ".md", ".txt", ".markdown"}
    suffix = _Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(allowed))}",
        )
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = _Path(tmp.name)
    try:
        from aughor.knowledge.indexer import index_file
        entry = index_file(tmp_path, title=_Path(file.filename or "").stem.replace("_", " ").replace("-", " ").title())
        entry["filename"] = file.filename or entry["filename"]
        return entry
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Document indexing failed")
        raise HTTPException(status_code=500, detail=f"Indexing failed: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/documents")
def list_documents_endpoint():
    from aughor.knowledge.indexer import list_documents
    return list_documents()


@app.delete("/documents/{doc_id}")
def delete_document_endpoint(doc_id: str):
    from aughor.knowledge.indexer import delete_document
    if not delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True, "doc_id": doc_id}


@app.post("/documents/search")
def search_documents_endpoint(body: dict):
    from aughor.knowledge.indexer import search_documents
    query = body.get("query", "")
    top_k = int(body.get("top_k", 5))
    return search_documents(query, top_k=top_k)


# ── Process Map ───────────────────────────────────────────────────────────────

@app.get("/connections/{conn_id}/process-map/{entity_id}")
def get_process_map(conn_id: str, entity_id: str):
    """Return live ProcessMap (node counts + LAG-based transitions) for an entity."""
    try:
        from aughor.process.mapper import build_process_map
        pm = build_process_map(entity_id, conn_id)
        return pm.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("process_map failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/connections/{conn_id}/causal-graph")
def get_causal_graph(conn_id: str):
    """Return confirmed causal edges for this connection."""
    from aughor.process.causal import load_causal_graph
    edges = load_causal_graph(conn_id)
    return [e.model_dump() for e in edges]


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
    from aughor.tools.prior_analyses import index_investigation
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
    fixture = Path(__file__).parent.parent / "data" / "aughor.duckdb"
    return {"status": "ok", "fixture_db": fixture.exists()}


# ── Ontology endpoints (M12a) ─────────────────────────────────────────────────

class _EntityOverride(BaseModel):
    description: Optional[str] = None
    active_filter: Optional[str] = None
    default_filters: Optional[list[str]] = None
    exclude_when: Optional[list[str]] = None
    lifecycle_states: Optional[list[str]] = None
    terminal_states: Optional[list[str]] = None


def _get_ontology_graph(connection_id: str):
    """
    Open the connection, call get_schema() to ensure profiles + ontology are built,
    then return the OntologyGraph.  Returns None if unavailable.
    """
    from aughor.ontology.store import get_or_build_ontology
    try:
        db = open_connection_for(connection_id)
        db.get_schema()   # triggers profiling + ontology build (cached on 2nd+ call)
        return db.get_ontology()
    except Exception:
        return None


def _latest_fingerprint(connection_id: str) -> Optional[str]:
    """Return the most recent schema fingerprint in the ontology cache for this connection."""
    from aughor.ontology.store import _load, _key as _okey
    cache = _load()
    prefix = f"{connection_id}:"
    matches = [k for k in cache if k.startswith(prefix)]
    if not matches:
        return None
    return matches[-1][len(prefix):]


@app.get("/ontology")
def get_ontology(connection_id: str = BUILTIN_ID):
    """Return the full OntologyGraph for a connection (triggers build if not cached)."""
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available for this connection")
    return graph.model_dump()


@app.get("/ontology/entities")
def get_ontology_entities(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {eid: e.model_dump() for eid, e in graph.entities.items()}


@app.get("/ontology/relationships")
def get_ontology_relationships(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {rid: r.model_dump() for rid, r in graph.relationships.items()}


@app.get("/ontology/actions")
def get_ontology_actions(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {aid: a.model_dump() for aid, a in graph.actions.items()}


@app.get("/ontology/metrics")
def get_ontology_metrics(connection_id: str = BUILTIN_ID):
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    return {mid: m.model_dump() for mid, m in graph.metrics.items()}


@app.put("/ontology/entities/{entity_id}")
def override_ontology_entity(
    entity_id: str,
    body: _EntityOverride,
    connection_id: str = BUILTIN_ID,
):
    """
    Apply human overrides to a single entity in the cached ontology.
    Only the fields supplied in the request body are changed — all other
    auto-extracted fields are preserved.
    """
    from aughor.ontology.store import patch_entity, _load, _key as _okey

    fingerprint = _latest_fingerprint(connection_id)
    if not fingerprint:
        # No cache yet — build it first
        graph = _get_ontology_graph(connection_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint

    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = patch_entity(connection_id, fingerprint, entity_id, overrides)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{entity_id}' not found in ontology for connection '{connection_id}'"
        )
    return updated.entities[entity_id].model_dump()


class _ActionOverride(BaseModel):
    description: Optional[str] = None
    sql_template: Optional[str] = None
    business_rules_enforced: Optional[list[str]] = None
    returns: Optional[str] = None


@app.put("/ontology/actions/{action_id}")
def override_ontology_action(
    action_id: str,
    body: _ActionOverride,
    connection_id: str = BUILTIN_ID,
):
    """Apply human overrides to a single action in the cached ontology."""
    from aughor.ontology.store import patch_action

    fingerprint = _latest_fingerprint(connection_id)
    if not fingerprint:
        graph = _get_ontology_graph(connection_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Ontology not available")
        fingerprint = graph.schema_fingerprint

    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = patch_action(connection_id, fingerprint, action_id, overrides)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Action '{action_id}' not found in ontology for connection '{connection_id}'"
        )
    return updated.actions[action_id].model_dump()


@app.get("/ontology/entities/{entity_id}/lifecycle-counts")
def get_entity_lifecycle_counts(entity_id: str, connection_id: str = BUILTIN_ID):
    """
    Run a live GROUP BY query on the entity's primary source table, bucketed by
    lifecycle_column.  Returns [{state, count}] sorted by count desc.
    """
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="Ontology not available")
    entity = graph.entities.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")
    if not entity.has_lifecycle or not entity.lifecycle_column:
        return []
    if not entity.source_tables:
        return []

    table  = entity.source_tables[0]
    col    = entity.lifecycle_column
    where  = f"WHERE {entity.active_filter}" if entity.active_filter else ""
    sql    = f"SELECT {col} AS state, COUNT(*) AS cnt FROM {table} {where} GROUP BY {col} ORDER BY cnt DESC LIMIT 50"

    try:
        db  = open_connection_for(connection_id)
        res = db.execute("lifecycle_counts", sql)
        db.close()
        if res.error:
            raise HTTPException(status_code=500, detail=res.error)
        rows = [{"state": str(r[0]), "count": int(r[1])} for r in (res.rows or [])]
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Connection settings (refresh schedule, etc.) ─────────────────────────────

class _ConnectionSettings(BaseModel):
    ontology_refresh_hours: Optional[int] = None  # None = disabled


@app.get("/connections/{conn_id}/settings")
def get_conn_settings(conn_id: str):
    """Return per-connection settings including ontology refresh schedule."""
    return get_connection_settings(conn_id)


@app.put("/connections/{conn_id}/settings")
def put_conn_settings(conn_id: str, body: _ConnectionSettings):
    """Update per-connection settings. Only provided fields are changed."""
    updates = body.model_dump(exclude_none=False)
    result = update_connection_settings(conn_id, updates)
    return result


@app.post("/ontology/rebuild")
def rebuild_ontology(connection_id: str = BUILTIN_ID):
    """Force-invalidate the ontology cache and rebuild from scratch."""
    from aughor.ontology.store import invalidate as invalidate_ontology
    invalidate_ontology(connection_id)
    _invalidate_schema_cache(connection_id)
    graph = _get_ontology_graph(connection_id)
    if graph is None:
        raise HTTPException(status_code=500, detail="Ontology rebuild failed")
    return {"ok": True, "generated_at": graph.generated_at, "entities": len(graph.entities)}


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
    from aughor.semantic.suggestions_cache import (
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

    from aughor.llm.provider import get_provider
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
