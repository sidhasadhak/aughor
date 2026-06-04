"""Investigations — chat, investigate, HITL feedback, history, outcomes, reindex."""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from aughor.agent.state import AgentState
from aughor.db.connection import open_connection_for
from aughor.db.history import (
    complete_investigation,
    create_investigation,
    delete_investigation,
    fail_investigation,
    get_investigation,
    get_session_turns,
    list_investigations,
    pause_investigation,
    save_chat_turn,
)
from aughor.db.registry import BUILTIN_ID
from aughor.routers._shared import explorers as _explorers

router = APIRouter(tags=["investigations"])


def _record_memory(inv_id: str, connection_id: str, question: str, state: dict) -> None:
    """Persist this run's reflection signals (confidence/surprise/plausibility/
    pitfalls) into the unified agent memory.  Best-effort: never breaks the stream."""
    try:
        from aughor.memory import record_run
        record_run(inv_id, connection_id, question, state)
    except Exception:
        pass
    # Graduated skill promotion: once a connection has EARNED L2 trust, a
    # high-confidence, grounded, read-only run auto-crystallizes into a reusable
    # learned skill — stored under the exact graph.schema_name the planner reads
    # from, gated by a read-only EXPLAIN dry-run.  Below L2 it's left as a
    # candidate for the UI to confirm.  Best-effort: never breaks the stream.
    # (auto_crystallize opens a connection only for L2+ skill-worthy runs.)
    try:
        from aughor.memory.skills import auto_crystallize
        auto_crystallize(inv_id, connection_id)
    except Exception:
        pass


# ── SSE + stream helpers ──────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


_TABLE_RE = re.compile(r'\b(?:FROM|JOIN)\s+(?:\w+\.)?(\w+)', re.IGNORECASE)
# Matches CTE definitions: anything of the form `name AS (`  (only valid for CTEs in SQL)
_CTE_DEF_RE = re.compile(r'\b(\w+)\s+AS\s*\(', re.IGNORECASE)


def _extract_tables(sql: str) -> list[str]:
    # Collect CTE names defined in WITH clauses so we can exclude them from the chip list.
    # CTEs look like:  WITH cte_name AS ( ... ), other_cte AS ( ... )
    cte_names = {m.group(1).lower() for m in _CTE_DEF_RE.finditer(sql)}

    seen: dict[str, None] = {}
    for m in _TABLE_RE.finditer(sql):
        t = m.group(1)
        if t.lower() not in seen and t.lower() not in cte_names:
            seen[t.lower()] = None
    return list(seen.keys())


_DIRECT_SIGNALS = re.compile(
    r'\b(show|list|what is|what are|what was|what were|how many|how much|'
    r'top \d|top\d|give me|fetch|get me|display|count|sum|total|average|avg|'
    r'breakdown|share of|distribution of|calculate|find|return)\b',
    re.IGNORECASE,
)
_INVESTIGATE_SIGNALS = re.compile(
    r'\b(why|cause|caused|causing|driver|drivers|reason|explain|diagnose|'
    r'investigate|what changed|what.s behind|contributing|anomaly|spike|drop|decline|surge)\b',
    re.IGNORECASE,
)


def _looks_direct(question: str) -> bool:
    if bool(_INVESTIGATE_SIGNALS.search(question)):
        return False
    return bool(_DIRECT_SIGNALS.search(question))


async def _aiter_sync(sync_iter):
    loop = asyncio.get_event_loop()
    it = iter(sync_iter)
    while True:
        try:
            item = await loop.run_in_executor(None, next, it)
        except StopIteration:
            break
        yield item


def _stall_summary(merged: dict) -> str:
    """Build a human-readable terminal message when an investigation ends without
    a report.  Prefers the agent's own last verdict/finding, then falls back to a
    digest of the SQL errors that blocked it."""
    scores = merged.get("evidence_scores") or []
    if scores:
        last = scores[-1]
        finding = getattr(last, "key_finding", None) or (last.get("key_finding") if isinstance(last, dict) else None)
        if finding:
            return f"Investigation ended without a conclusive report. Last assessment: {str(finding)[:400]}"

    qh = merged.get("query_history") or []
    errs: list[str] = []
    for r in qh:
        e = getattr(r, "error", None) if not isinstance(r, dict) else r.get("error")
        if e and e not in errs:
            errs.append(str(e))
    total = len(qh)
    failed = len(errs)
    if errs:
        shown = "; ".join(errs[:3])
        return (
            f"Investigation could not complete: {failed} of {total} "
            f"{'query' if total == 1 else 'queries'} failed and no conclusive "
            f"answer could be formed. Errors: {shown[:500]}"
        )
    return (
        "Investigation ended without producing a report. No conclusive evidence "
        "was gathered — try rephrasing the question or narrowing the time range."
    )


def _try_salvage(merged: dict, inv_id: str, question: str, connection_id: str):
    """Best-effort terminal synthesis when the graph stops without a report.

    A SOTA investigation must never end with nothing: if ANY evidence was gathered
    (explore sub-answers or ADA phases), synthesise a best-effort report from it,
    persist it, and return the SSE string to emit. Returns ``None`` only when there
    is genuinely no evidence to salvage. Never raises."""
    try:
        qmode = merged.get("query_mode")
        qh = merged.get("query_history") or []

        # Explore: synthesise from whatever sub-questions completed.
        if merged.get("subq_answers"):
            from aughor.agent.explore import synthesize_exploration
            out = synthesize_exploration(merged)
            er = out.get("explore_report")
            if er:
                sq_raw = [sq.model_dump() for sq in merged.get("sub_questions", [])]
                sa_raw = [a.model_dump() for a in merged.get("subq_answers", [])]
                explore_save = {"_report_type": "explore", **er.model_dump(),
                                "sub_questions": sq_raw, "subq_answers": sa_raw,
                                "_partial": True}
                complete_investigation(inv_id, report=explore_save, hypotheses=[],
                                       query_history=qh, question=question,
                                       connection_id=connection_id, skip_index=False)
                return _sse("explore_report", {
                    "explore_report": er.model_dump(), "sub_questions": sq_raw,
                    "subq_answers": sa_raw, "query_count": len(qh),
                    "investigation_id": inv_id, "query_mode": "explore", "partial": True,
                })

        # ADA / investigate: synthesise from whatever phases completed.
        if merged.get("investigation_phases"):
            from aughor.agent.investigate import ada_synthesize
            out = ada_synthesize(merged)
            ada = out.get("ada_report")
            if ada:
                ada_save = (dict(ada) if isinstance(ada, dict) else ada.model_dump())
                ada_save["_report_type"] = "investigate"
                ada_save["_partial"] = True
                complete_investigation(inv_id, report=ada_save,
                                       hypotheses=merged.get("hypotheses", []),
                                       query_history=qh, question=question,
                                       connection_id=connection_id, skip_index=False)
                payload = ada_save if isinstance(ada, dict) else ada.model_dump()
                return _sse("ada_report", {
                    "ada_report": payload, "investigation_id": inv_id,
                    "query_mode": "investigate", "partial": True,
                })
    except Exception:
        return None
    return None


# ── Request models ────────────────────────────────────────────────────────────

class InvestigateRequest(BaseModel):
    question: str
    connection_id: str = BUILTIN_ID
    canvas_id: Optional[str] = None
    hitl: bool = False
    skip_cache: bool = False


class FeedbackRequest(BaseModel):
    feedback: str


class ChatHistoryTurn(BaseModel):
    question: str
    sql: str
    columns: list[str] = []
    headline: str = ""


class ChatRequest(BaseModel):
    question: str
    connection_id: str
    canvas_id: Optional[str] = None
    history: list[ChatHistoryTurn] = []
    session_id: str = ""


class OutcomeRequest(BaseModel):
    rec_text: str
    status: str
    metric_name: Optional[str] = None
    metric_before: Optional[float] = None
    metric_after: Optional[float] = None


_VALID_CHART_TYPES = {"auto", "bar", "bar_horizontal", "bar_vertical", "line", "area", "pie", "stacked_bar", "scatter",
                      "multi_line", "heatmap", "treemap"}


def _coerce_list_str(v: object) -> list[str]:
    """Coerce a value that should be list[str] but may arrive as a JSON-encoded
    string from local models (Ollama/qwen).  Handles:
      - already a list                  → items cast to str
      - '["a","b","c"]'                 → single JSON array string
      - '["a"]\\n["b"]'                 → one array per line (qwen quirk)
      - plain multi-line text           → each non-empty line becomes an item
    """
    if isinstance(v, list):
        return [str(item) for item in v]
    if not isinstance(v, str) or not v.strip():
        return []
    try:
        parsed = json.loads(v)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, ValueError):
        pass
    steps: list[str] = []
    for line in v.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed_line = json.loads(line)
            if isinstance(parsed_line, list):
                steps.extend(str(item) for item in parsed_line)
            else:
                steps.append(str(parsed_line))
        except (json.JSONDecodeError, ValueError):
            steps.append(line)
    return steps


class _ChatAnswer(BaseModel):
    sql: str
    headline: str
    chart_type: str = "auto"
    intent: str = ""         # "You want to see…" — plain-English restatement of the question
    approach: list[str] = [] # 3-5 concise steps describing how the answer is calculated

    @field_validator("approach", mode="before")
    @classmethod
    def coerce_approach(cls, v: object) -> list[str]:
        return _coerce_list_str(v)


class _FollowUpBase(BaseModel):
    """Shared model for all follow-up question responses.
    Guards against local models (Ollama/qwen) returning questions as a
    JSON-encoded string instead of a proper list."""
    questions: list[str] = []

    @field_validator("questions", mode="before")
    @classmethod
    def coerce_questions(cls, v: object) -> list[str]:
        return _coerce_list_str(v)

    def model_post_init(self, __context: object) -> None:
        if self.chart_type not in _VALID_CHART_TYPES:
            self.chart_type = "auto"


# ── Chat streaming ────────────────────────────────────────────────────────────

async def _stream_chat(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    request: Request,
    session_id: str = "",
    canvas_id: Optional[str] = None,
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

        schema = await asyncio.to_thread(db.get_schema)
        rules_block = get_chat_rules_block()

        history_section = ""
        if history:
            recent = history[-3:]
            lines = ["CONVERSATION HISTORY (use to resolve 'also', 'add', 'filter by', 'compare to'):"]
            for i, t in enumerate(recent, 1):
                cols_str = ", ".join(t.columns[:6]) if t.columns else "—"
                lines.append(f"[Turn {i}] Q: {t.question!r}")
                lines.append(f"         SQL: {t.sql}")
                lines.append(f"         Columns: {cols_str}")
                if t.headline:
                    lines.append(f"         Headline: {t.headline}")
            history_section = "\n".join(lines) + "\n"

        _schema_name = getattr(db, "_schema_name", None)
        schema_qualifier = (_schema_name or "main") if db.dialect == "duckdb" else (_schema_name or "public")

        kb_patterns_section = ""
        try:
            from aughor.semantic.kb_retriever import retrieve_for_planning
            kb_patterns_section = retrieve_for_planning(question, top_k=2) or ""
            if kb_patterns_section:
                kb_patterns_section += "\n\n"
        except Exception:
            pass

        # Per-connection knowledge store — retrieved, not dumped
        conn_kb_section = ""
        try:
            from aughor.semantic.connection_kb import retrieve_for_question as _ckb_retrieve
            _ckb = _ckb_retrieve(question, connection_id)
            if _ckb:
                conn_kb_section = _ckb + "\n\n"
        except Exception:
            pass

        sql_examples_section = ""
        try:
            from aughor.tools.prior_analyses import search_sql_examples
            sql_examples_section = search_sql_examples(question, connection_id)
        except Exception:
            pass

        metrics_section = ""
        try:
            from aughor.semantic.metrics import build_metrics_block
            _mb = build_metrics_block()
            if _mb:
                metrics_section = _mb + "\n\n"
        except Exception:
            pass

        exploration_section = ""
        try:
            from aughor.explorer.store import render_exploration_annotations
            _ea = render_exploration_annotations(connection_id)
            if _ea:
                exploration_section = _ea + "\n\n"
        except Exception:
            pass

        causal_section = ""
        try:
            from aughor.process.causal import build_causal_context_section
            _cc = build_causal_context_section(question, conn_id=connection_id)
            if _cc:
                causal_section = _cc + "\n"
        except Exception:
            pass

        document_section = ""
        try:
            from aughor.knowledge.indexer import build_external_context_section
            _ds = build_external_context_section(question, top_k=2)
            if _ds:
                document_section = _ds + "\n\n"
        except Exception:
            pass

        prompt = CHAT_PROMPT.format(
            schema=schema,
            history_section=history_section,
            question=question,
            schema_qualifier=schema_qualifier,
            kb_patterns_section=kb_patterns_section,
            conn_kb_section=conn_kb_section,
            sql_examples_section=sql_examples_section,
            metrics_section=metrics_section,
            exploration_section=exploration_section,
            causal_section=causal_section,
            document_section=document_section,
        )
        if rules_block:
            prompt = rules_block + prompt

        # Run the (blocking) LLM call in a worker thread so the event loop stays
        # free to serve other pages (catalog/inbox/home) while the query runs.
        answer: _ChatAnswer = await asyncio.to_thread(
            lambda: get_provider("coder").complete(
                system=CHAT_SQL_SYSTEM, user=prompt, response_model=_ChatAnswer,
            )
        )

        final_sql = answer.sql

        # ── Lint before execution — catch known anti-patterns in code, not prompts ──
        from aughor.sql.lint import lint as _lint_sql, error_hint as _lint_hint, has_errors as _lint_has_errors
        from aughor.sql.writer import SqlWriter
        _lint_issues = _lint_sql(final_sql, dialect=db.dialect)
        if _lint_has_errors(_lint_issues):
            try:
                _writer = SqlWriter(db, schema_str=schema)
                _lint_fix = await asyncio.to_thread(
                    lambda: _writer.fix(
                        final_sql,
                        "SQL quality issues detected before execution",
                        hint=_lint_hint(_lint_issues),
                        max_retries=1,
                    )
                )
                if _lint_fix.ok:
                    final_sql = _lint_fix.sql
            except Exception:
                pass   # non-fatal — proceed with original SQL

        yield _sse("sql", {"sql": final_sql})
        result = await asyncio.to_thread(db.execute, "chat", final_sql)

        from aughor.agent.investigate import _zero_row_suspicious
        _chat_zero_diag = None
        if not result.error and result.row_count == 0:
            _chat_zero_diag = _zero_row_suspicious(final_sql)

        if result.error or _chat_zero_diag:
            _writer2 = SqlWriter(db, schema_str=schema)
            _fix_error = result.error or "Query returned 0 rows — the SQL logic is likely wrong."
            try:
                fix = await asyncio.to_thread(
                    lambda: _writer2.fix(final_sql, _fix_error, hint=_chat_zero_diag or "", max_retries=1)
                )
                if fix.ok:
                    retry = await asyncio.to_thread(db.execute, "chat", fix.sql)
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
        yield _sse("tables_used", {"tables": _extract_tables(final_sql)})
        if answer.intent or answer.approach:
            yield _sse("analysis", {"intent": answer.intent, "steps": answer.approach})

        # ── Semantic Inspect — non-blocking logical validation ──────────────
        try:
            from aughor.sql.inspect import inspect as _inspect_sql
            _ir = await asyncio.to_thread(
                lambda: _inspect_sql(question, final_sql, result.columns, result.rows)
            )
            if not _ir.valid and _ir.issues:
                yield _sse("inspect_warning", {
                    "issues":        _ir.issues,
                    "suggested_fix": _ir.suggested_fix,
                })
        except Exception:
            pass

        try:
            fq: _FollowUpBase = await asyncio.to_thread(
                lambda: get_provider("narrator").complete(
                    system="Suggest exactly 3 concise follow-up data questions (max 12 words each).",
                    user=f"Question: {question}\nAnswer: {answer.headline}\nColumns: {', '.join(result.columns[:8])}",
                    response_model=_FollowUpBase,
                )
            )
            yield _sse("followups", {"questions": fq.questions[:3]})
        except Exception:
            pass

        try:
            await asyncio.to_thread(
                lambda: save_chat_turn(
                    question=question, connection_id=connection_id, headline=answer.headline or question,
                    sql=final_sql or "", session_id=session_id, columns=result.columns,
                    rows=result.rows, chart_type=answer.chart_type,
                    tables_used=_extract_tables(final_sql or ""),
                    intent=answer.intent, approach=answer.approach,
                    canvas_id=canvas_id,
                )
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


# ── Investigation streaming ───────────────────────────────────────────────────

async def _stream_investigation(
    question: str,
    connection_id: str,
    request: Request,
    hitl: bool = False,
    skip_cache: bool = False,
    canvas_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    _TIMEOUT = int(os.getenv("AUGHOR_TIMEOUT_SECONDS", "600"))

    canvas_schema_context: str = ""
    if canvas_id:
        try:
            from aughor.canvas.store import get_canvas, resolve_connection_id
            from aughor.tools.schema import build_canvas_schema_context
            canvas = get_canvas(canvas_id)
            if canvas and canvas.primary_connection_id:
                connection_id = canvas.primary_connection_id
                canvas_schema_context = build_canvas_schema_context(canvas)
        except Exception:
            pass

    try:
        db = open_connection_for(connection_id)
    except KeyError as e:
        yield _sse("error", {"message": str(e)})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Could not connect: {e}"})
        return

    from aughor.tools.prior_analyses import find_similar_investigation
    cache_hit = None if (skip_cache or _looks_direct(question)) else await asyncio.to_thread(find_similar_investigation, question, connection_id)
    if cache_hit:
        cached_id, score = cache_hit
        cached = get_investigation(cached_id)
        if cached and cached.get("report"):
            cached_report = cached["report"]
            report_type = cached_report.get("_report_type") if isinstance(cached_report, dict) else None
            yield _sse("start", {"question": question, "connection_id": connection_id, "investigation_id": cached_id})
            if cached.get("hypotheses"):
                yield _sse("hypotheses", {"hypotheses": cached["hypotheses"]})
            qh = cached.get("query_history") or []
            if report_type == "investigate":
                yield _sse("ada_report", {"ada_report": cached_report, "investigation_id": cached_id, "query_mode": "investigate", "from_cache": True, "cached_question": cached["question"], "cache_score": round(score, 3)})
            elif report_type == "explore":
                yield _sse("explore_report", {"explore_report": cached_report, "sub_questions": cached_report.get("sub_questions", []), "subq_answers": cached_report.get("subq_answers", []), "query_count": cached.get("query_count", len(qh)), "investigation_id": cached_id, "query_mode": "explore", "from_cache": True, "cached_question": cached["question"], "cache_score": round(score, 3)})
            else:
                yield _sse("report", {"report": cached_report, "hypotheses": cached.get("hypotheses") or [], "query_count": cached.get("query_count", len(qh)), "query_history": qh, "investigation_id": cached_id, "from_cache": True, "cached_question": cached["question"], "cache_score": round(score, 3)})
            yield _sse("done", {})
            return

    inv_id = create_investigation(question, connection_id, canvas_id=canvas_id)
    from aughor import telemetry as _telemetry
    trace_id = _telemetry.new_trace(inv_id, question, connection_id)
    yield _sse("start", {"question": question, "connection_id": connection_id, "investigation_id": inv_id, "trace_id": trace_id})

    _active_explorer = _explorers.get(connection_id)
    if _active_explorer:
        _active_explorer.pause()

    merged: dict = {}  # bound before try so the except/salvage path can read partial state
    try:
        schema = await asyncio.to_thread(db.get_schema)
        from aughor.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=hitl)

        initial_state: AgentState = {
            "question": question, "connection_id": connection_id, "investigation_id": inv_id,
            "trace_id": trace_id,
            "schema_context": schema, "unresolved_tensions": [], "scan_context": "", "events_context": "",
            "hypotheses": [], "current_hypothesis_idx": 0, "query_history": [], "evidence_scores": [],
            "pitfalls": [], "prior_analyses": [], "iteration": 0,
            "max_iterations": int(os.getenv("AUGHOR_MAX_ITER", "6")),
            "report": None, "hitl_enabled": hitl, "human_feedback": None,
            "query_mode": None, "route_reasoning": None, "route_confidence": None, "replan_decision": None,
            "sub_questions": [], "current_subq_idx": 0, "subq_answers": [], "explore_report": None,
            "investigation_phases": [], "ada_report": None, "_ada_intake": None,
            "canvas_id": canvas_id, "canvas_schema_context": canvas_schema_context,
        }

        import time
        merged = initial_state.copy()
        deadline = time.monotonic() + _TIMEOUT
        timed_out = False
        report_emitted = False  # did the graph reach a terminal synthesis node?

        async for event in _aiter_sync(agent.stream(initial_state, config={"configurable": {"thread_id": inv_id}})):
            if await request.is_disconnected():
                fail_investigation(inv_id, status="timed_out")
                return
            if time.monotonic() > deadline:
                timed_out = True
                break
            if "__interrupt__" in event:
                yield _sse("paused", {"investigation_id": inv_id, "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])], "scores": [s.model_dump() for s in merged.get("evidence_scores", [])]})
                pause_investigation(inv_id)
                yield _sse("done", {})
                return

            node_name = next(iter(event))
            partial = event[node_name]
            merged = {**merged, **partial}

            if node_name == "route_question":
                yield _sse("mode", {"query_mode": merged.get("query_mode"), "route_reasoning": merged.get("route_reasoning"), "route_confidence": merged.get("route_confidence")})
            elif node_name == "decompose" and merged.get("hypotheses"):
                yield _sse("hypotheses", {"hypotheses": [h.model_dump() for h in merged["hypotheses"]]})
            elif node_name == "plan_and_execute":
                history = merged.get("query_history", [])
                recent = history[-3:]
                pitfalls = merged.get("pitfalls", [])
                yield _sse("queries_executed", {"iteration": merged.get("iteration", 0), "hypothesis_idx": merged.get("current_hypothesis_idx", 0), "queries": [{"sql": r.sql, "row_count": r.row_count, "error": r.error, "stats": [s.model_dump() for s in (r.stats or [])]} for r in recent], "corrections": [p.model_dump() for p in pitfalls[-(len(recent)):]], "stats": [s.model_dump() for r in recent for s in (r.stats or [])]})
            elif node_name == "score_evidence":
                scores = merged.get("evidence_scores", [])
                if scores:
                    yield _sse("score", {"iteration": merged.get("iteration", 0), "score": scores[-1].model_dump(), "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])]})
            elif node_name in ("ada_intake", "ada_baseline", "ada_decompose", "ada_dimensional", "ada_behavioral"):
                phases = merged.get("investigation_phases", [])
                if phases:
                    yield _sse("phase_complete", {"phase": phases[-1], "all_phases": phases})
            elif node_name == "ada_synthesize" and merged.get("ada_report"):
                ada = merged["ada_report"]
                qh = merged.get("query_history", [])
                yield _sse("tables_used", {"tables": _extract_tables(" ".join(r.sql for r in qh if r.sql))})
                yield _sse("ada_report", {"ada_report": ada, "investigation_id": inv_id, "query_mode": "investigate"})
                try:
                    from aughor.llm.provider import get_provider as _gp
                    fq: _FollowUpBase = _gp("narrator").complete(system="Suggest exactly 3 concise follow-up investigation questions (max 15 words each).", user=f"Original question: {question}\nFindings: {ada.get('headline', '') if isinstance(ada, dict) else str(ada)[:200]}", response_model=_FollowUpBase)
                    yield _sse("followups", {"questions": fq.questions[:3]})
                except Exception:
                    pass
                ada_save = dict(ada) if isinstance(ada, dict) else ada
                ada_save["_report_type"] = "investigate"
                await asyncio.to_thread(lambda: complete_investigation(inv_id, report=ada_save, hypotheses=merged.get("hypotheses", []), query_history=qh, question=question, connection_id=connection_id, skip_index=False))
                await asyncio.to_thread(_record_memory, inv_id, connection_id, question, merged)
                report_emitted = True
            elif node_name == "decompose_exploration":
                yield _sse("explore_plan", {"sub_questions": [sq.model_dump() for sq in merged.get("sub_questions", [])]})
            elif node_name == "plan_and_execute_subq":
                history = merged.get("query_history", [])
                idx = merged.get("current_subq_idx", 0)
                subqs = merged.get("sub_questions", [])
                current_subq = subqs[idx] if idx < len(subqs) else None
                recent = [r for r in history if r.hypothesis_id == (current_subq.id if current_subq else "")][-3:]
                yield _sse("queries_executed", {"iteration": merged.get("iteration", 0), "hypothesis_idx": idx, "subq_id": current_subq.id if current_subq else "", "queries": [{"sql": r.sql, "row_count": r.row_count, "error": r.error, "stats": [s.model_dump() for s in (r.stats or [])]} for r in recent], "corrections": [p.model_dump() for p in merged.get("pitfalls", [])[-2:]], "stats": [s.model_dump() for r in recent for s in (r.stats or [])]})
            elif node_name == "reason_over_result":
                answers = merged.get("subq_answers", [])
                if answers:
                    latest = answers[-1]
                    yield _sse("subq_answer", {"subq_id": latest.subq_id, "question": latest.question, "purpose": latest.purpose, "answer": latest.answer, "insight": latest.insight, "refinement": latest.refinement, "sql": latest.sql, "columns": latest.columns, "rows": latest.rows[:30], "row_count": latest.row_count, "error": latest.error})
            elif node_name == "synthesize_exploration" and merged.get("explore_report"):
                er = merged["explore_report"]
                answers = merged.get("subq_answers", [])
                qh = merged.get("query_history", [])
                sq_raw = [sq.model_dump() for sq in merged.get("sub_questions", [])]
                sa_raw = [a.model_dump() for a in answers]
                yield _sse("tables_used", {"tables": _extract_tables(" ".join(r.sql for r in qh if r.sql))})
                yield _sse("explore_report", {"explore_report": er.model_dump(), "sub_questions": sq_raw, "subq_answers": sa_raw, "query_count": len(qh), "investigation_id": inv_id, "query_mode": "explore"})
                try:
                    from aughor.llm.provider import get_provider as _gp
                    fqx: _FollowUpBase = _gp("narrator").complete(system="Suggest exactly 3 concise follow-up questions (max 15 words each).", user=f"Original question: {question}\nFindings: {er.headline}", response_model=_FollowUpBase)
                    yield _sse("followups", {"questions": fqx.questions[:3]})
                except Exception:
                    pass
                explore_save = {"_report_type": "explore", **er.model_dump(), "sub_questions": sq_raw, "subq_answers": sa_raw}
                await asyncio.to_thread(lambda: complete_investigation(inv_id, report=explore_save, hypotheses=[], query_history=qh, question=question, connection_id=connection_id, skip_index=False))
                await asyncio.to_thread(_record_memory, inv_id, connection_id, question, merged)
                report_emitted = True
            elif node_name == "synthesize" and merged.get("report"):
                qh = merged.get("query_history", [])
                yield _sse("tables_used", {"tables": _extract_tables(" ".join(r.sql for r in qh if r.sql))})
                yield _sse("report", {"report": merged["report"].model_dump(), "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])], "query_count": len(qh), "query_history": [{"hypothesis_id": r.hypothesis_id, "sql": r.sql, "row_count": r.row_count, "error": r.error, "columns": r.columns, "rows": r.rows[:50], "stats": [s.model_dump() for s in (r.stats or [])]} for r in qh], "investigation_id": inv_id, "query_mode": merged.get("query_mode")})
                try:
                    from aughor.llm.provider import get_provider as _gp
                    rep = merged["report"]
                    summary = getattr(rep, "summary", "") or getattr(rep, "headline", "")
                    fqr: _FollowUpBase = _gp("narrator").complete(system="Suggest exactly 3 concise follow-up investigation questions (max 15 words each).", user=f"Original question: {question}\nFindings: {str(summary)[:300]}", response_model=_FollowUpBase)
                    yield _sse("followups", {"questions": fqr.questions[:3]})
                except Exception:
                    pass
                await asyncio.to_thread(lambda: complete_investigation(inv_id, report=merged["report"], hypotheses=merged.get("hypotheses", []), query_history=qh, question=question, connection_id=connection_id, skip_index=merged.get("query_mode") == "direct"))
                await asyncio.to_thread(_record_memory, inv_id, connection_id, question, merged)
                report_emitted = True

        if timed_out:
            # Even on timeout, salvage a partial report from gathered evidence first.
            salvaged = _try_salvage(merged, inv_id, question, connection_id)
            if salvaged:
                yield salvaged
            else:
                yield _sse("error", {"message": f"Investigation timed out after {_TIMEOUT}s."})
                fail_investigation(inv_id, status="timed_out")
        elif not report_emitted:
            # The graph terminated without reaching a synthesis node — e.g. every
            # query errored and the loop exhausted its iterations. First try a
            # best-effort synthesis from whatever evidence exists; only if there's
            # genuinely nothing to salvage do we surface a terminal stall message.
            salvaged = _try_salvage(merged, inv_id, question, connection_id)
            if salvaged:
                yield salvaged
            else:
                yield _sse("error", {"message": _stall_summary(merged)})
                fail_investigation(inv_id, status="failed")

    except Exception as e:
        # An unhandled node exception still shouldn't lose partial work — salvage
        # a best-effort report from gathered evidence before surfacing the error.
        salvaged = _try_salvage(merged, inv_id, question, connection_id)
        if salvaged:
            yield salvaged
        else:
            fail_investigation(inv_id, status="failed")
            yield _sse("error", {"message": str(e)})
    finally:
        _telemetry.end_trace(trace_id)
        if _active_explorer:
            _active_explorer.resume()
        db.close()
        yield _sse("done", {})


# ── HITL resume streaming ─────────────────────────────────────────────────────

async def _stream_resume(inv_id: str, feedback: str, request: Request) -> AsyncGenerator[str, None]:
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
    except Exception as e:
        yield _sse("error", {"message": str(e)})
        yield _sse("done", {})
        return

    try:
        from aughor.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=True)
        config = {"configurable": {"thread_id": inv_id}}
        checkpoint = agent.get_state(config)
        merged: dict = dict(checkpoint.values) if checkpoint else {}
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
            merged = {**merged, **event[node_name]}
            if node_name == "synthesize" and merged.get("report"):
                qh = merged.get("query_history", [])
                yield _sse("report", {"report": merged["report"].model_dump(), "hypotheses": [h.model_dump() for h in merged.get("hypotheses", [])], "query_count": len(qh), "query_history": [{"hypothesis_id": r.hypothesis_id, "sql": r.sql, "row_count": r.row_count, "error": r.error, "columns": r.columns, "rows": r.rows[:50], "stats": [s.model_dump() for s in (r.stats or [])]} for r in qh], "investigation_id": inv_id})
                complete_investigation(inv_id, report=merged["report"], hypotheses=merged.get("hypotheses", []), query_history=qh, question=inv["question"], connection_id=inv.get("connection_id", ""))
                _record_memory(inv_id, inv.get("connection_id", ""), inv["question"], merged)
    except Exception as e:
        fail_investigation(inv_id, status="failed")
        yield _sse("error", {"message": str(e)})
    finally:
        db.close()
        yield _sse("done", {})


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    conn_id = req.connection_id
    if req.canvas_id:
        from aughor.canvas.store import resolve_connection_id
        resolved = resolve_connection_id(req.canvas_id)
        if resolved:
            conn_id = resolved
    return StreamingResponse(
        _stream_chat(req.question, conn_id, req.history, request, session_id=req.session_id, canvas_id=req.canvas_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/investigate")
async def investigate(req: InvestigateRequest, request: Request):
    conn_id = req.connection_id
    if req.canvas_id:
        from aughor.canvas.store import resolve_connection_id
        resolved = resolve_connection_id(req.canvas_id)
        if resolved:
            conn_id = resolved
    return StreamingResponse(
        _stream_investigation(req.question, conn_id, request, hitl=req.hitl, skip_cache=req.skip_cache, canvas_id=req.canvas_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/investigations/{inv_id}/feedback")
async def submit_feedback(inv_id: str, req: FeedbackRequest, request: Request):
    return StreamingResponse(
        _stream_resume(inv_id, req.feedback, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/investigations")
def get_investigations(limit: int = 50):
    return list_investigations(limit=limit)


@router.get("/investigations/indexed-ids")
def get_indexed_ids():
    from aughor.tools.prior_analyses import INVESTIGATIONS_COLLECTION
    from aughor.semantic.vector_store import scroll_payloads
    payloads = scroll_payloads(INVESTIGATIONS_COLLECTION)
    return {"ids": [p["inv_id"] for p in payloads if p.get("inv_id")]}


@router.get("/investigations/{inv_id}")
def get_investigation_detail(inv_id: str):
    inv = get_investigation(inv_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


@router.delete("/investigations/{inv_id}", status_code=204)
def delete_investigation_endpoint(inv_id: str):
    if not delete_investigation(inv_id):
        raise HTTPException(status_code=404, detail="Investigation not found")


@router.post("/investigations/reindex")
def reindex_investigations():
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
        index_investigation(inv_id=row["id"], question=row["question"], headline=row["headline"], key_findings=key_findings, connection_id=row.get("connection_id", ""))
        indexed += 1
    return {"indexed": indexed, "skipped": skipped}


@router.get("/chat-sessions/{session_id}/turns")
def get_chat_session_turns(session_id: str):
    turns = get_session_turns(session_id)
    if not turns:
        raise HTTPException(status_code=404, detail="Session not found")
    return turns


@router.post("/investigations/{inv_id}/recommendations/{rec_index}/outcome", status_code=201)
def log_recommendation_outcome(inv_id: str, rec_index: int, req: OutcomeRequest):
    from aughor.playbook.outcomes import log_outcome, update_playbook_success_rates
    outcome = log_outcome(inv_id=inv_id, rec_index=rec_index, rec_text=req.rec_text, status=req.status, metric_name=req.metric_name, metric_before=req.metric_before, metric_after=req.metric_after)  # type: ignore[arg-type]
    if req.status in ("verified", "implemented", "rejected"):
        update_playbook_success_rates()
        try:
            from aughor.process.causal import promote_on_outcome
            promote_on_outcome(inv_id, contradicted=(req.status == "rejected"))
        except Exception:
            pass
    return outcome.model_dump()


@router.get("/investigations/{inv_id}/outcomes")
def get_investigation_outcomes(inv_id: str):
    from aughor.playbook.outcomes import load_outcomes_for_inv
    return [o.model_dump() for o in load_outcomes_for_inv(inv_id)]


# ── Evidence Ledger endpoints ─────────────────────────────────────────────────

class EvidenceFeedbackRequest(BaseModel):
    feedback: str   # "validated" | "disputed" | "needs_context"
    note: Optional[str] = None


@router.get("/investigations/{inv_id}/evidence")
def get_investigation_evidence(inv_id: str):
    """Return all evidence claims for an investigation, ordered by confidence."""
    from aughor.evidence import store as _ev_store
    claims = _ev_store.get_claims_for_investigation(inv_id)
    return [c.model_dump() for c in claims]


@router.post("/investigations/{inv_id}/evidence/{claim_id}/feedback")
def submit_claim_feedback(inv_id: str, claim_id: str, req: EvidenceFeedbackRequest):
    """Set owner feedback on an evidence claim."""
    from aughor.evidence import store as _ev_store
    VALID = {"validated", "disputed", "needs_context"}
    if req.feedback not in VALID:
        raise HTTPException(status_code=422, detail=f"feedback must be one of {VALID}")
    updated = _ev_store.update_feedback(claim_id, req.feedback, req.note)
    if not updated:
        raise HTTPException(status_code=404, detail="Claim not found")
    return updated.model_dump()
