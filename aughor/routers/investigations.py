"""Investigations — chat, investigate, HITL feedback, history, outcomes, reindex."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

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
from aughor.routers._shared import explorers as _explorers, explorers_for_connection as _explorers_for_connection

logger = logging.getLogger(__name__)
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


def _pb_serialize(entries) -> list[dict]:
    """Shape matched playbook entries for the `playbook_refs` SSE event so the UI
    can show them and offer keep / modify / remove."""
    out = []
    for e in entries or []:
        out.append({
            "id": e.id,
            "recommendation": e.recommendation,
            "trigger_condition": e.trigger_condition,
            "status": e.status,
            "tags": e.tags[:6],
            "historical_success_rate": e.historical_success_rate,
            "source_kb_id": e.source_kb_id,
        })
    return out


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


_VALID_CHART_TYPES = {"auto", "bar", "bar_horizontal", "bar_vertical", "line", "area", "pie", "pareto", "stacked_bar", "scatter",
                      "multi_line", "heatmap", "treemap", "combo"}

# Concentration / 80-20 intent — only the QUESTION carries this, so the chart
# selection has to read it here (the renderer never sees the question). Models
# inconsistently emit a share column or the literal "pareto" chart_type, so this
# makes the intent deterministic.
_CONCENTRATION_RE = re.compile(
    r"80[\s/_-]?20|pareto|concentrat|cumulative\s+share|long\s+tail|"
    r"(few|handful|top)\b.{0,40}\b(drive|account|make up|generate)\b.{0,20}\b(most|majority|bulk)",
    re.IGNORECASE,
)
_PARETO_BLOCK = {"line", "none", "heatmap", "scatter", "stacked_bar", "multi_line", "area"}
_ID_COL_RE = re.compile(r"(^|_)(id|key|sk|pk|code)$", re.IGNORECASE)


def _maybe_pareto(question: str, columns: list[str], rows: list, current: str) -> str:
    """Force a Pareto when the question asks about concentration/80-20 and the
    result is a single category(+id) ranking over a measure. The renderer
    computes the cumulative curve itself, so no share column is required."""
    if current in _PARETO_BLOCK:
        return current
    if not question or not _CONCENTRATION_RE.search(question):
        return current
    if not columns or len(rows) < 4:
        return current
    sample = rows[0]
    if not isinstance(sample, (list, tuple)):
        return current

    def _numlike(v: object) -> bool:
        # QueryResult stringifies every cell, so numbers arrive as strings.
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float)):
            return True
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if not s or s == "NULL":
                return False
            try:
                float(s)
                return True
            except ValueError:
                return False
        return False

    num_idx = [i for i, v in enumerate(sample) if _numlike(v)]
    cat_idx = [i for i in range(len(columns)) if i not in num_idx]
    # A ranking = at least one dimension + at least one measure. When the only
    # dimension is an id (numeric → counted above), still treat it as a ranking.
    if num_idx and cat_idx:
        return "pareto"
    if len(num_idx) >= 2 and any(_ID_COL_RE.search(c) for c in columns):
        return "pareto"
    return current


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
    # MindsDB-style: chart config generated alongside SQL so chart always matches data
    chart_config: dict = Field(default_factory=dict, description=
        "Vega-Lite chart configuration: {type, x_field, y_field, color_field, title}. "
        "Empty dict if the result is not chartable.")

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


class _InsightResult(BaseModel):
    """Rich analytical insight generated from SQL results — anomaly detection, trend, comparison."""
    narrative: str = Field(default="", description="2-3 tight sentences that lead with the answer and wrap decisive numbers in **bold**.")
    anomalies: list[str] = Field(default_factory=list, description="List of detected anomalies or unexpected patterns.")
    trend: str = Field(default="stable", description="One of: up, down, stable, mixed.")
    confidence: str = Field(default="medium", description="One of: high, medium, low.")


class _PostAnswer(_InsightResult):
    """Combined post-answer enrichment: analytical insight + follow-up questions
    in ONE narrator call (was two separate narrator round-trips per answer).
    Inherits insight fields; adds the follow-up list with the same coercion guard."""
    questions: list[str] = Field(default_factory=list, description="Exactly 3 concise follow-up data questions, max 12 words each.")

    @field_validator("questions", mode="before")
    @classmethod
    def coerce_questions(cls, v: object) -> list[str]:
        return _coerce_list_str(v)

class _ClarifyingQuestions(BaseModel):
    """Clarifying questions generated before a deep analysis to narrow scope."""
    questions: list[str] = Field(default_factory=list, description="1-2 concise clarifying questions (max 15 words each).")
    context_note: str = Field(default="", description="One sentence explaining why these questions matter.")
# ── Chat streaming ────────────────────────────────────────────────────────────

# ── Headline grounding ────────────────────────────────────────────────────────
# The coder emits a headline alongside the SQL BEFORE execution (a prediction), so it
# can name a leader/number the actual rows contradict ("AMERICA leading at $1.62B" when
# the data shows EUROPE at $45.8B). We validate the emitted headline against the real
# rows and replace it with a grounded one ONLY on a genuine contradiction.
_HL_NUM_RE = re.compile(r"-?\$?\s?([\d][\d,]*(?:\.\d+)?)\s*([bmk])?\b", re.I)
_LEADER_RE = re.compile(r"\b(lead|leads|leading|tops?|topping|highest|most|largest|biggest|#1)\b", re.I)
_MONEY_COL_RE = re.compile(r"revenue|sales|price|value|spend|cost|profit|margin|gmv|income|amount|aov", re.I)


def _hl_to_float(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _headline_numbers(text):
    out = []
    for m in _HL_NUM_RE.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")) * {"b": 1e9, "m": 1e6, "k": 1e3}.get((m.group(2) or "").lower(), 1.0))
        except Exception:
            pass
    return out


def _col_is_numeric(rows, idx):
    return any(idx < len(r) and _hl_to_float(r[idx]) is not None for r in rows[:8])


def _approx_in(x, pool, tol=0.02):
    return any((abs(x) < 1 if p == 0 else abs(x - p) / abs(p) <= tol) for p in pool)


def _humanize_col(col):
    return re.sub(r"_+", " ", str(col or "")).strip().title()


def _fmt_value(col, v):
    f = _hl_to_float(v)
    if f is None:
        return str(v)
    money = bool(_MONEY_COL_RE.search(str(col or "")))
    a = abs(f)
    if a >= 1e9:
        s = f"{f / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"{f / 1e6:.2f}M"
    elif f == int(f):
        s = f"{int(f):,}"
    else:
        s = f"{f:,.2f}"
    return ("$" + s) if money else s


def _primary_num_idx(columns, rows):
    fallback = None
    for i, c in enumerate(columns):
        if not _col_is_numeric(rows, i):
            continue
        cl = str(c).lower()
        if re.search(r"(^|_)(id|key|sk|code|count|n)($|_)", cl) or re.search(r"pct|percent|share|_of_total", cl):
            fallback = i if fallback is None else fallback
            continue
        return i
    return fallback


def _ground_headline(headline, columns, rows):
    """Return the headline unchanged when it is consistent with the data; otherwise a
    grounded replacement built from the actual top row. Conservative: only fires on a
    clear contradiction (a sizable number matching nothing — not even a column sum/mean
    — or a superlative naming a non-leader entity)."""
    if not headline or not rows or not columns:
        return headline
    # pool of acceptable numbers: individual cell values (top rows) + each column's sum & mean
    pool = [f for r in rows[:8] for f in (_hl_to_float(v) for v in r) if f is not None]
    for ci in range(len(columns)):
        vals = [_hl_to_float(r[ci]) for r in rows if ci < len(r)]
        vals = [v for v in vals if v is not None]
        if vals:
            pool.append(sum(vals))
            pool.append(sum(vals) / len(vals))
    unmatched = [n for n in _headline_numbers(headline) if abs(n) >= 100 and not _approx_in(n, pool)]
    cat_idx = next((i for i in range(len(columns)) if not _col_is_numeric(rows, i)), None)
    leader_bad = False
    if cat_idx is not None and _LEADER_RE.search(headline) and cat_idx < len(rows[0]):
        leader = str(rows[0][cat_idx])
        named = [str(r[cat_idx]) for r in rows[:8]
                 if cat_idx < len(r) and str(r[cat_idx]) and str(r[cat_idx]).lower() in headline.lower()]
        if named and leader.lower() not in headline.lower():
            leader_bad = True
    if not unmatched and not leader_bad:
        return headline
    num_idx = _primary_num_idx(columns, rows)
    if num_idx is None or num_idx >= len(rows[0]):
        return headline
    fval = _fmt_value(columns[num_idx], rows[0][num_idx])
    metric = _humanize_col(columns[num_idx])
    if cat_idx is not None and len(rows) > 1 and cat_idx < len(rows[0]):
        return f"{rows[0][cat_idx]} leads {metric.lower()} at {fval}"
    return f"{metric}: {fval}"


async def _stream_chat(
    question: str,
    connection_id: str,
    history: list[ChatHistoryTurn],
    request: Request,
    session_id: str = "",
    canvas_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    # Resolve canvas scope so table names resolve correctly AND the model only
    # sees in-scope tables. Multi-dataset connections (local_upload) expose every
    # dataset and carry schema_name=None with a table-list scope, so the
    # schema_name override below constrains nothing — without an explicit table
    # filter a Bakehouse canvas can answer from the ecommerce schema.
    canvas_scope_schema: str | None = None
    canvas_scope_tables: list[str] = []
    canvas_scope_full = True
    if canvas_id:
        try:
            from aughor.canvas.store import get_canvas
            canvas = get_canvas(canvas_id)
            if canvas and canvas.scopes:
                _scope = canvas.scopes[0]
                canvas_scope_schema = _scope.schema_name
                canvas_scope_tables = list(_scope.tables or [])
                canvas_scope_full = _scope.is_full_schema
        except Exception:
            pass
    try:
        if canvas_id and canvas_scope_schema:
            from aughor.db.connection import open_connection_for_with_schema
            db = open_connection_for_with_schema(connection_id, schema_name=canvas_scope_schema)
        else:
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

        # ── Context retrieval — independent, side-effect-free fetches run
        # CONCURRENTLY (none consumes another's output; results slot into fixed
        # prompt sections, so completion order is irrelevant). Cuts the prelude
        # wait from the sum of these calls to roughly the slowest single one.
        def _kb() -> str:
            from aughor.semantic.kb_retriever import retrieve_for_planning
            s = retrieve_for_planning(question, top_k=2) or ""
            return (s + "\n\n") if s else ""

        def _ckb() -> str:
            from aughor.semantic.connection_kb import retrieve_for_question as _r
            s = _r(question, connection_id)
            return (s + "\n\n") if s else ""

        def _sqlex() -> str:
            from aughor.tools.prior_analyses import search_sql_examples
            return search_sql_examples(question, connection_id) or ""

        def _expl() -> str:
            from aughor.explorer.store import render_exploration_annotations
            s = render_exploration_annotations(connection_id)
            return (s + "\n\n") if s else ""

        def _causal() -> str:
            from aughor.process.causal import build_causal_context_section
            s = build_causal_context_section(question, conn_id=connection_id)
            return (s + "\n") if s else ""

        def _docs() -> str:
            from aughor.knowledge.indexer import build_external_context_section
            s = build_external_context_section(question, top_k=2)
            return (s + "\n\n") if s else ""

        def _pb_match():
            from aughor.playbook.retriever import retrieve_for_metric_and_phases
            return retrieve_for_metric_and_phases([question], limit=4)

        async def _safe(fn):
            try:
                return await asyncio.to_thread(fn)
            except Exception:
                return ""

        async def _safe_list(fn):
            try:
                return await asyncio.to_thread(fn)
            except Exception:
                return []

        (
            schema, kb_patterns_section, conn_kb_section, sql_examples_section,
            exploration_section, causal_section, document_section,
            pb_entries,
        ) = await asyncio.gather(
            asyncio.to_thread(db.get_schema),  # critical: a failure here propagates
            _safe(_kb), _safe(_ckb), _safe(_sqlex),
            _safe(_expl), _safe(_causal), _safe(_docs), _safe_list(_pb_match),
        )

        # Restrict the schema to the canvas's scoped tables. Table-list scopes on
        # multi-dataset connections have schema_name=None, so the schema_name
        # override doesn't constrain anything — filter explicitly, mirroring the
        # Deep Analysis path's build_canvas_schema_context. Falls back to the full
        # schema if filtering yields nothing.
        if canvas_scope_tables and not canvas_scope_full:
            try:
                from aughor.tools.schema import get_schema_for_tables
                _scoped = get_schema_for_tables(schema, canvas_scope_tables)
                if _scoped and _scoped.strip():
                    schema = _scoped
            except Exception:
                logger.warning("Canvas table-scope filter failed; using full schema", exc_info=True)

        # Metrics built AFTER schema (needs the column set to filter out metrics
        # whose tables/columns aren't in THIS connection — metrics are global, so
        # an unfiltered block leaks another connection's formula). Kept out of the
        # gather to avoid a concurrent get_schema on the same db connection.
        metrics_section = ""
        try:
            from aughor.semantic.metrics import build_metrics_block
            _mb = build_metrics_block(schema_text=schema, connection_id=connection_id)
            metrics_section = (_mb + "\n\n") if _mb else ""
        except Exception:
            metrics_section = ""

        # Schema-linking pre-filter: narrow schema to relevant tables/columns
        # for this specific question. Reduces hallucination by 30-60%.
        _full_schema = schema  # keep the un-narrowed schema for FK-neighbour expansion
        try:
            from aughor.tools.schema_linker import link_schema_for_prompt
            schema = link_schema_for_prompt(question, schema, top_k_tables=8, top_k_cols=8, connection_id=connection_id)
        except Exception:
            logger.warning("Schema-linking pre-filter failed; using full schema", exc_info=True)

        # Build structured Data Catalog from linked tables (MindsDB-style),
        # expanded with FK neighbours so bridge/output tables a multi-table
        # question needs only via a join are present.
        semantic_layer_section = ""
        try:
            from aughor.tools.data_catalog import build_data_catalog
            from aughor.tools.schema import _parse_schema_tables, fk_neighbor_expand, temporal_dimension_tables
            linked_tables = list(_parse_schema_tables(schema).keys())
            if linked_tables:
                # Add the date/time dimension first (before FK expansion + the
                # 10-table cap) so a temporal question keeps it.
                for _dt in temporal_dimension_tables(_full_schema, linked_tables, question):
                    if _dt not in linked_tables:
                        linked_tables.append(_dt)
                linked_tables = fk_neighbor_expand(_full_schema, linked_tables, cap=10)
                # M24c: verified semantic layer (object sets + computed properties)
                # for the linked entities — only items validated against the live DB.
                try:
                    from aughor.ontology.store import load_latest_ontology
                    from aughor.ontology.semantic_block import render_semantic_layer
                    semantic_layer_section = render_semantic_layer(
                        load_latest_ontology(connection_id), linked_tables
                    )
                except Exception:
                    semantic_layer_section = ""
                data_catalog = await asyncio.to_thread(
                    lambda: build_data_catalog(db, linked_tables)
                )
                if data_catalog:
                    schema = data_catalog
        except Exception:
            logger.warning("Data Catalog build failed; using linked schema text", exc_info=True)

        # Hard cap: max 10 tables in context (MindsDB best practice)
        try:
            from aughor.tools.data_catalog import enforce_context_cap
            schema = enforce_context_cap(schema, max_tables=10)
        except Exception:
            pass

        # ── final_text path (MindsDB-style): definitional questions answered from KB ──
        definitional = re.search(
            r"^(what is|what are|what does|define|explain|meaning of)",
            question,
            re.IGNORECASE,
        )
        if definitional:
            try:
                from aughor.semantic.kb_retriever import has_strong_kb_match, retrieve_for_planning
                if has_strong_kb_match(question, threshold=0.75, top_k=3):
                    kb_answer = retrieve_for_planning(question, top_k=3) or ""
                    # Also pull connection KB
                    try:
                        from aughor.semantic.connection_kb import retrieve_for_question as _ckb_fn
                        ckb = _ckb_fn(question, connection_id)
                        if ckb:
                            kb_answer = kb_answer + "\n\n" + ckb
                    except Exception:
                        pass
                    if kb_answer.strip():
                        _answer_text = kb_answer.strip()
                        # Emit as `headline` — the only text channel the chat turn
                        # renders for a no-SQL answer (final_text/definitional path).
                        # The previous `answer` event had no frontend handler, so the
                        # turn rendered blank. `mode` tags it so it shows as a Quick turn.
                        yield _sse("mode", {"query_mode": "final_text"})
                        yield _sse("headline", {"headline": _answer_text})
                        yield _sse("done", {})
                        try:
                            await asyncio.to_thread(
                                lambda: save_chat_turn(
                                    question=question, connection_id=connection_id,
                                    headline=_answer_text[:2000], sql="", session_id=session_id,
                                    columns=[], rows=[], chart_type="none", tables_used=[],
                                    intent="", approach=[],
                                    canvas_id=canvas_id,
                                )
                            )
                        except Exception:
                            pass
                        return
            except Exception:
                pass

        # Inject schema-prefix note when canvas-scoped
        if canvas_scope_schema:
            schema = (
                f"DEFAULT SCHEMA: {canvas_scope_schema}\n"
                "CRITICAL: Every table reference in SQL MUST include this schema prefix "
                f"(e.g. {canvas_scope_schema}.table_name). Do NOT use bare table names.\n\n"
                + schema
            )
        elif canvas_scope_tables and not canvas_scope_full:
            # Table-list scope (multi-dataset connection, schema_name=None): name
            # the allowed universe so the model can't wander into another dataset.
            schema = (
                "ALLOWED TABLES — this canvas is scoped to ONLY these tables:\n"
                f"{chr(10).join('  - ' + t for t in canvas_scope_tables)}\n"
                "CRITICAL: Query ONLY these tables, using the exact schema prefixes shown. "
                "Do NOT reference any other schema or dataset.\n\n"
                + schema
            )

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
        # Playbook context — when org playbook items match this question, give them
        # to the model AND surface them to the user (emitted below) so they can
        # keep / modify / remove them.
        if pb_entries:
            try:
                from aughor.playbook.retriever import build_playbook_prompt_section
                _pbsec = build_playbook_prompt_section(pb_entries)
                if _pbsec:
                    prompt = _pbsec + "\n" + prompt
            except Exception:
                pass

        # M24c: verified semantic layer — object sets (named WHERE filters) and
        # computed properties for the linked entities, all executed against the
        # live DB. Prepended below the trusted block so trusted patterns stay on top.
        if semantic_layer_section:
            prompt = semantic_layer_section + "\n\n" + prompt

        # Trusted query templates (authoritative, data-team-reviewed). When the
        # question matches a verified pattern, inject it at the top so the model
        # reuses its exact structure — fixes model-reasoning gaps (fan-out, grain)
        # that prompt rules can't. Surfaced to the user via `trusted` SSE below.
        _trusted_used = []
        try:
            from aughor.semantic.trusted_queries import retrieve_trusted, build_trusted_block
            _tmatches = retrieve_trusted(question, connection_id)
            _tblk = build_trusted_block(_tmatches)
            if _tblk:
                prompt = _tblk + "\n" + prompt
                _trusted_used = [{"question": tq.question, "note": tq.note, "score": sc}
                                 for tq, sc in _tmatches]
        except Exception:
            _trusted_used = []

        # Semantic Compiler fast-path (backlog #11): for the safe analytical shapes
        # (scalar / timeseries / breakdown / ranking) assemble grounded SQL deterministically
        # from the verified ontology instead of free-form generation. The LLM still writes the
        # headline/chart/approach around it, but the executed SQL is the compiled one — which
        # can't hallucinate columns or fan out. Coverage-gated + fallback-safe (None → no-op).
        _compiled_sql = None
        _compiled_intent = None
        if os.getenv("AUGHOR_COMPILER", "1").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from aughor.semantic.compiler import compile_question
                _cc = compile_question(question, connection_id, dialect=db.dialect)
                if _cc:
                    _compiled_sql, _compiled_intent = _cc
                    prompt = ("VERIFIED SQL (assembled from the verified semantic layer — this is "
                              "the exact query to run; build your headline/chart around it):\n"
                              f"{_compiled_sql}\n\n" + prompt)
            except Exception:
                _compiled_sql = None

        # Run the (blocking) LLM call in a worker thread so the event loop stays
        # free to serve other pages (catalog/inbox/home) while the query runs.
        answer: _ChatAnswer = await asyncio.to_thread(
            lambda: get_provider("coder").complete(
                system=CHAT_SQL_SYSTEM, user=prompt, response_model=_ChatAnswer,
            )
        )

        final_sql = answer.sql
        # Guarantee the deterministic, grounded SQL is what executes.
        if _compiled_sql:
            final_sql = _compiled_sql
            yield _sse("compiled", {
                "intent_type": _compiled_intent.intent_type,
                "entity": _compiled_intent.entity or _compiled_intent.table,
                "measure": _compiled_intent.measure or _compiled_intent.metric,
                "dimension": _compiled_intent.dimension,
            })

        # ── Semantic column alignment — deterministic pre-execution check ─────
        # Catches wrong entity column (e.g. product_id used for seller analysis)
        # and injects a fix hint into SqlWriter if a rewrite is needed.
        _semantic_fix_hint = ""
        try:
            from aughor.tools.semantic_validator import check_entity_column_alignment
            _sem_warnings = check_entity_column_alignment(question, final_sql, schema)
            if _sem_warnings:
                _semantic_fix_hint = " | ".join(w.to_prompt_text() for w in _sem_warnings)
        except Exception:
            pass

        # ── Fan-out detection (M24d) — multi-fact join amplification ───────────
        # Conservative, zero-false-positive detector (validated on 121 official
        # TPC-H/TPC-DS queries). When ≥2 satellites of a shared hub are aggregated
        # across a direct join, the totals over-count; the hint drives a directed
        # pre-aggregate rewrite below (adopted only if it re-executes cleanly).
        _fanout_fix_hint = ""
        try:
            from aughor.sql.fanout import detect_fanout
            from aughor.tools.schema import _parse_schema_tables as _pst
            _ff = detect_fanout(final_sql, _pst(_full_schema), dialect=db.dialect)
            if _ff:
                _fanout_fix_hint = _ff.to_prompt_text()
                yield _sse("fanout", {"hub": _ff.hub_root, "satellites": _ff.satellites})
        except Exception:
            pass

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

        # Also trigger a rewrite when semantic column warnings exist, even if
        # the SQL executed successfully (wrong columns produce wrong results silently).
        if result.error or _chat_zero_diag or _semantic_fix_hint or _fanout_fix_hint:
            _writer2 = SqlWriter(db, schema_str=schema)
            _fix_error = (
                result.error or
                (_semantic_fix_hint if _semantic_fix_hint else None) or
                (_fanout_fix_hint if _fanout_fix_hint else None) or
                "Query returned 0 rows — the SQL logic is likely wrong."
            )
            _combined_hint = " | ".join(filter(None, [_chat_zero_diag or "", _semantic_fix_hint, _fanout_fix_hint]))
            try:
                fix = await asyncio.to_thread(
                    lambda: _writer2.fix(final_sql, _fix_error, hint=_combined_hint, max_retries=1)
                )
                if fix.ok:
                    retry = await asyncio.to_thread(db.execute, "chat", fix.sql)
                    if not retry.error and (retry.row_count > 0 or not _chat_zero_diag or _semantic_fix_hint or _fanout_fix_hint):
                        final_sql = fix.sql
                        result = retry
                        yield _sse("sql", {"sql": final_sql})
            except Exception:
                pass

        if result.error:
            yield _sse("error", {"message": result.error})
            return

        # Ground the headline in the ACTUAL rows — the coder's headline is a pre-execution
        # prediction and can contradict the data it ran on.
        _grounded_headline = _ground_headline(answer.headline, result.columns, result.rows)
        # Deterministic concentration→pareto (the renderer never sees the question).
        answer.chart_type = _maybe_pareto(question, result.columns, result.rows, answer.chart_type)
        yield _sse("columns", {"columns": result.columns})
        yield _sse("rows", {"rows": result.rows[:10000]})
        yield _sse("headline", {"headline": _grounded_headline})
        yield _sse("chart_type", {"chart_type": answer.chart_type})
        if answer.chart_config:
            yield _sse("chart_config", {"chart_config": answer.chart_config})
        yield _sse("tables_used", {"tables": _extract_tables(final_sql)})
        if answer.intent or answer.approach:
            yield _sse("analysis", {"intent": answer.intent, "steps": answer.approach})
        if pb_entries:
            yield _sse("playbook_refs", {"items": _pb_serialize(pb_entries)})
        if _trusted_used:
            yield _sse("trusted", {"items": _trusted_used})

        # Persist, then mark DONE the moment the answer is ready — so the
        # "Completed in …" time reflects when the user got their answer, not when
        # the post-answer enrichment (inspect + follow-ups) finishes.
        _chat_inv_id = ""
        try:
            _chat_inv_id = await asyncio.to_thread(
                lambda: save_chat_turn(
                    question=question, connection_id=connection_id, headline=_grounded_headline or question,
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

        # ── Post-answer enrichment (streams in after DONE, never delays it) ──
        # ONE narrator call produces BOTH the analytical insight and the
        # follow-up questions (was two separate round-trips). For trivial result
        # shapes (a single scalar / empty set) there's no trend to interpret, so
        # we ask only for follow-ups and skip the narrative — same single call.
        _insight_dict = None
        _insight_worth_it = len(result.rows) >= 2 or (len(result.rows) == 1 and len(result.columns) >= 3)
        try:
            # Bounded sample: up to 20 rows × 8 columns
            _sample_rows = result.rows[:20]
            _sample_cols = result.columns[:8]
            _rows_text = "\n".join(
                ", ".join(str(r[i]) for i in range(len(_sample_cols))) for r in _sample_rows
            )
            if _insight_worth_it:
                _system = (
                    "You are an analytical data interpreter writing for a clean published brief. "
                    "Given a user question, the SQL that answered it, and a sample of the results: "
                    "(1) produce a tight analytical insight (2-3 sentences) that LEADS WITH THE ANSWER, "
                    "wraps each decisive number in **double asterisks** for bold (e.g. **$2,112**, **+18%**), "
                    "names any genuine anomaly (unexpected value, spike, drop, outlier) in plain words, and "
                    "states the overall trend and your confidence. Start with the finding — no preamble, no "
                    "hedging, no 'the data shows' scaffolding. Use ONLY numbers present in the results; never "
                    "invent values, and bold never licenses invented precision. "
                    "Then (2) suggest exactly 3 concise follow-up data questions (max 12 words each)."
                )
            else:
                _system = (
                    "Given a user question and its answer, suggest exactly 3 concise follow-up data questions "
                    "(max 12 words each). Leave the narrative empty."
                )
            _user = (
                f"Question: {question}\n"
                f"SQL: {final_sql}\n"
                f"Answer: {answer.headline}\n"
                f"Results (sample of {len(_sample_rows)} rows):\n"
                f"Columns: {', '.join(_sample_cols)}\n"
                f"{_rows_text}"
            )
            _pa: _PostAnswer = await asyncio.to_thread(
                lambda: get_provider("narrator").complete(
                    system=_system,
                    user=_user,
                    response_model=_PostAnswer,
                    temperature=0.2,
                )
            )
            if _insight_worth_it and _pa.narrative:
                _insight_dict = {
                    "narrative": _pa.narrative,
                    "anomalies": _pa.anomalies[:3],
                    "trend": _pa.trend,
                    "confidence": _pa.confidence,
                }
                yield _sse("insight", _insight_dict)
                # Persist insight so it survives page reload / history navigation
                if _chat_inv_id:
                    try:
                        from aughor.db.history import update_chat_turn_insight
                        await asyncio.to_thread(lambda: update_chat_turn_insight(_chat_inv_id, _insight_dict))
                    except Exception:
                        pass
            if _pa.questions:
                yield _sse("followups", {"questions": _pa.questions[:3]})
        except Exception:
            pass

        # Semantic inspect — logical validation
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
    canvas_scope_schema: str | None = None
    if canvas_id:
        try:
            from aughor.canvas.store import get_canvas, resolve_connection_id
            from aughor.tools.schema import build_canvas_schema_context
            canvas = get_canvas(canvas_id)
            if canvas and canvas.primary_connection_id:
                connection_id = canvas.primary_connection_id
                canvas_scope_schema = canvas.scopes[0].schema_name if canvas.scopes else None
                canvas_schema_context = build_canvas_schema_context(canvas)
        except Exception:
            pass

    try:
        if canvas_id and canvas_scope_schema:
            from aughor.db.connection import open_connection_for_with_schema
            db = open_connection_for_with_schema(connection_id, schema_name=canvas_scope_schema)
        else:
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

    # Surface matched org-playbook items up front (they're also injected into ADA
    # synthesis). The user can keep / modify / remove them from the result.
    try:
        from aughor.playbook.retriever import retrieve_for_metric_and_phases
        _pb = await asyncio.to_thread(lambda: retrieve_for_metric_and_phases([question], limit=4))
        if _pb:
            yield _sse("playbook_refs", {"items": _pb_serialize(_pb)})
    except Exception:
        pass

    # Pause EVERY explorer bound to this connection — the connection explorer AND any
    # canvas explorers on the same connection — so background exploration doesn't contend
    # with the investigation's queries. (Previously only the connection explorer paused,
    # so a canvas explorer kept hammering the DB through the run.) Skip ones already paused
    # (e.g. user-paused) so we only resume what we actually paused.
    _paused_explorers = []
    for _e in _explorers_for_connection(connection_id):
        try:
            _e.pause()
            _paused_explorers.append(_e)
        except Exception:
            pass

    merged: dict = {}  # bound before try so the except/salvage path can read partial state
    try:
        full_schema = await asyncio.to_thread(db.get_schema)
        # When a Canvas is active, use the pre-filtered canvas schema context so the
        # agent only sees the tables selected for that Canvas.
        schema = canvas_schema_context if canvas_schema_context else full_schema
        # Inject a schema-prefix note so the LLM always uses fully-qualified names
        if canvas_scope_schema:
            schema = (
                f"DEFAULT SCHEMA: {canvas_scope_schema}\n"
                "CRITICAL: Every table reference in SQL MUST include this schema prefix "
                f"(e.g. {canvas_scope_schema}.table_name). Do NOT use bare table names.\n\n"
                + schema
            )
        # Schema-linking pre-filter: narrow to relevant tables/columns per question.
        try:
            from aughor.tools.schema_linker import link_schema
            schema = link_schema(question, schema, top_k_tables=4, top_k_cols=8, connection_id=connection_id)
        except Exception:
            logger.warning("Schema-linking pre-filter failed (agentic path); using full schema", exc_info=True)
        # Build structured Data Catalog (MindsDB-style) from linked tables
        data_catalog = ""
        try:
            from aughor.tools.data_catalog import build_data_catalog
            from aughor.tools.schema import _parse_schema_tables, fk_neighbor_expand, temporal_dimension_tables
            linked_tables = list(_parse_schema_tables(schema).keys())
            if linked_tables:
                # Complete the join paths BEFORE building the catalog (mirrors the /chat path):
                # schema-linking picks ~4 tables by keyword, missing bridge/parent tables a join
                # needs — e.g. the timestamp on `orders` when revenue is on `invoices`. Without
                # this the ADA coder can't see the date column and hallucinates one on the metric
                # table. Expand against the FULL schema, capped at 10 tables.
                for _dt in temporal_dimension_tables(full_schema, linked_tables, question):
                    if _dt not in linked_tables:
                        linked_tables.append(_dt)
                linked_tables = fk_neighbor_expand(full_schema, linked_tables, cap=10)
                data_catalog = await asyncio.to_thread(
                    lambda: build_data_catalog(db, linked_tables)
                )
        except Exception:
            logger.warning("Data Catalog build failed (agentic path); using linked schema", exc_info=True)

        # Hard cap: max 10 tables in context (MindsDB best practice)
        try:
            from aughor.tools.data_catalog import enforce_context_cap
            schema = enforce_context_cap(schema, max_tables=10)
            if data_catalog:
                data_catalog = enforce_context_cap(data_catalog, max_tables=10)
        except Exception:
            pass

        # Prefer structured Data Catalog as the primary schema context (MindsDB-style)
        schema_for_agent = data_catalog if data_catalog else schema

        # Inject the CANONICAL METRIC formulas so ADA resolves a metric (e.g. "revenue")
        # to the SAME approved SQL the /chat path uses — closing the "revenue means two
        # different things" gap. Reconciles the curated catalog (data/metrics.json) with
        # the ontology's verified OntologyMetric.formula_sql. No-op when none exist.
        try:
            from aughor.semantic.canonical import canonical_metrics_block
            _canon = canonical_metrics_block(connection_id, canvas_scope_schema)
            if _canon:
                schema_for_agent = f"{schema_for_agent}\n\n{_canon}"
        except Exception:
            logger.warning("Canonical metrics injection failed (agentic path)", exc_info=True)

        from aughor.agent.graph import build_graph_generic
        agent = build_graph_generic(db, hitl=hitl)

        initial_state: AgentState = {
            "question": question, "connection_id": connection_id, "investigation_id": inv_id,
            "trace_id": trace_id,
            "schema_context": schema_for_agent, "unresolved_tensions": [], "scan_context": "", "events_context": "",
            "hypotheses": [], "current_hypothesis_idx": 0, "query_history": [], "evidence_scores": [],
            "pitfalls": [], "prior_analyses": [], "iteration": 0,
            "max_iterations": int(os.getenv("AUGHOR_MAX_ITER", "6")),
            "report": None, "hitl_enabled": hitl, "human_feedback": None,
            "query_mode": None, "route_reasoning": None, "route_confidence": None, "replan_decision": None,
            "sub_questions": [], "current_subq_idx": 0, "subq_answers": [], "explore_report": None,
            "investigation_phases": [], "ada_report": None, "_ada_intake": None,
            "canvas_id": canvas_id, "canvas_schema_context": canvas_schema_context,
            "data_catalog": data_catalog or "",
            "subq_data_portrait": {},
            "final_text_answer": "",
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
                # For investigate/explore modes, stream clarifying questions after routing
                # so the user sees what the agent is about to probe before it runs expensive queries.
                if merged.get("query_mode") in ("investigate", "explore"):
                    try:
                        _cq_system = (
                            "You are a senior data analyst about to run a deep investigation. "
                            "Given the user's question, ask 1-2 short clarifying questions that would "
                            "sharpen the analysis. Focus on time range, metric definition, or segment. "
                            "Also write a one-sentence note explaining why these matter."
                        )
                        _cq: _ClarifyingQuestions = await asyncio.to_thread(
                            lambda: get_provider("narrator").complete(
                                system=_cq_system,
                                user=f"Question: {question}",
                                response_model=_ClarifyingQuestions,
                                temperature=0.3,
                            )
                        )
                        if _cq.questions:
                            yield _sse("clarifying_questions", {
                                "questions": _cq.questions[:2],
                                "context_note": _cq.context_note,
                            })
                    except Exception:
                        pass
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
        for _e in _paused_explorers:
            try:
                _e.resume()
            except Exception:
                pass
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
    # Resume with canvas schema override if applicable
    canvas_scope_schema: str | None = None
    if inv.get("canvas_id"):
        try:
            from aughor.canvas.store import get_canvas
            canvas = get_canvas(inv["canvas_id"])
            if canvas and canvas.scopes:
                canvas_scope_schema = canvas.scopes[0].schema_name
        except Exception:
            pass
    try:
        if canvas_scope_schema:
            from aughor.db.connection import open_connection_for_with_schema
            db = open_connection_for_with_schema(inv["connection_id"], schema_name=canvas_scope_schema)
        else:
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


@router.get("/investigations/evidence/recent")
def get_recent_evidence(connection_id: str, canvas_id: Optional[str] = None, limit: int = 50):
    """Return recent evidence claims across a scope (connection, optionally a canvas),
    newest-first — the scope-level Evidence layer. The ledger keys only by
    investigation_id, so we resolve the scope to its investigation IDs first.

    Registered before /investigations/{inv_id}/evidence so the literal 'evidence'
    segment can't be captured as an investigation id.
    """
    from aughor.db.history import list_investigation_ids
    from aughor.evidence import store as _ev_store
    inv_ids = list_investigation_ids(connection_id, canvas_id)
    claims = _ev_store.get_recent_claims_for_investigations(inv_ids, limit)
    return [c.model_dump() for c in claims]


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
