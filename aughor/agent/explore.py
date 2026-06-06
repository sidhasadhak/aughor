"""
Explore mode node functions — sequential investigative chunking.

Graph branch (entered when route_question returns mode="explore"):

  decompose_exploration
      ↓
  plan_and_execute_subq  ←──────────────┐
      ↓                                  │
  reason_over_result                     │  (loop)
      ↓                                  │
  route_after_reason ── [more Qs] ───────┘
      ↓ [all done / max iter]
  synthesize_exploration
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

from aughor.agent.prompts_explore import (
    BUILD_LEDGER_PROMPT,
    DECOMPOSE_EXPLORATION_PROMPT,
    PLAN_SUBQ_PROMPT,
    REASON_OVER_RESULT_PROMPT,
    SYNTHESIZE_EXPLORATION_PROMPT,
)
from aughor.agent.prompts import format_pitfall_section
from aughor.agent.state import (
    AgentState,
    DataQualityNote,
    ExplorationReport,
    Pitfall,
    QueryPlan,
    QueryResult,
    ReasoningOutput,
    SubQuestion,
    SubQuestionAnswer,
)
from aughor.llm.provider import get_provider
from aughor.tools.executor import format_result_for_llm
from aughor.tools.stats import analyze_query_result

from pydantic import BaseModel, Field
from typing import Literal, Optional

MAX_SUBQ = int(__import__("os").getenv("AUGHOR_MAX_SUBQ", "8"))


# ── Pydantic schema for decompose output ─────────────────────────────────────

class _ExplorationPlan(BaseModel):
    question_understanding: str
    constraints: list[str] = Field(default_factory=list)
    sub_questions: list[SubQuestion]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_prior_answers(answers: list[SubQuestionAnswer]) -> str:
    if not answers:
        return "None yet — this is the first sub-question."
    parts = []
    for a in answers:
        lines = [
            f"[{a.subq_id}] {a.question}",
            f"  Answer:  {a.answer}",
            f"  Insight: {a.insight}",
        ]
        if a.refinement:
            lines.append(f"  Refinement for downstream: {a.refinement}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _format_chain_summary(answers: list[SubQuestionAnswer]) -> str:
    parts = []
    for a in answers:
        result_snippet = ""
        if a.columns and a.rows:
            header = " | ".join(a.columns)
            rows = "\n".join("  " + " | ".join(str(v) for v in row) for row in a.rows[:8])
            result_snippet = f"\n  Data:\n  {header}\n{rows}"
            if a.row_count > 8:
                result_snippet += f"\n  … ({a.row_count - 8} more rows)"
        parts.append(
            f"[{a.subq_id}] {a.question} ({a.purpose})\n"
            f"  SQL: {a.sql}\n"
            f"  Answer: {a.answer}\n"
            f"  Insight: {a.insight}"
            + result_snippet
        )
    return "\n\n".join(parts)


def _attach_stats(result: QueryResult) -> QueryResult:
    try:
        stats = analyze_query_result(result)
        return QueryResult(**{**result.model_dump(), "stats": [s for s in stats]})
    except Exception:
        return result


# ── Analysis ledger — canonical definitions shared by every stage ─────────────

class _LedgerOut(BaseModel):
    ledger: str = Field(
        description="Short binding list of canonical entity identifiers, metric "
                    "SQL expressions, and segment definitions for this analysis."
    )


def build_analysis_ledger(state: AgentState) -> str:
    """Decide canonical entity/metric definitions ONCE so every downstream step
    uses the same identifiers and expressions (prevents figures drifting between
    stages, e.g. customer_id vs customer_unique_id). Best-effort — never blocks."""
    scan_context = state.get("scan_context") or ""
    scan_section = (
        f"DATA PORTRAIT (actual distributions):\n{scan_context}\n" if scan_context else ""
    )
    try:
        out: _LedgerOut = get_provider("coder").complete(
            system="You define canonical metric/entity definitions for a data analysis.",
            user=BUILD_LEDGER_PROMPT.format(
                question=state["question"],
                schema=state["schema_context"],
                scan_section=scan_section,
            ),
            response_model=_LedgerOut,
        )
        return (out.ledger or "").strip()
    except Exception:
        return ""


# ── Node: decompose_exploration ───────────────────────────────────────────────

def decompose_exploration(state: AgentState) -> dict[str, Any]:
    """Break the question into an ordered chain of sub-questions."""
    scan_context = state.get("scan_context") or ""
    scan_section = (
        f"DATA PORTRAIT (actual distributions — use these ranges in your SQL planning):\n{scan_context}\n"
        if scan_context else ""
    )

    # Pin canonical definitions for the whole run before planning any sub-questions.
    analysis_ledger = build_analysis_ledger(state)

    # Extract explicit user constraints from the question (re-use decompose pattern)
    constraint_section = "No explicit constraints detected."

    # Resilience: the planner is the single point where an exploration most often
    # dies (LLM/provider hiccup or an assertion-style prompt that yields no chain).
    # Retry once with a corrective nudge, then fall back to a deterministic floor
    # chain so the investigation ALWAYS proceeds to real queries + synthesis.
    sub_questions = _plan_exploration_chain(state, scan_section, constraint_section)
    if not sub_questions:
        sub_questions = _floor_chain(state)

    return {
        "sub_questions": sub_questions[:MAX_SUBQ],
        "current_subq_idx": 0,
        "subq_answers": [],
        "pitfalls": [],
        "iteration": 0,
        "analysis_ledger": analysis_ledger,
    }


def _plan_exploration_chain(state: AgentState, scan_section: str, constraint_section: str) -> list[SubQuestion]:
    """Run the decompose planner with one corrective retry. Never raises —
    returns [] only if the LLM truly can't produce a valid SQL-answerable chain."""
    llm = get_provider("coder")
    base_user = DECOMPOSE_EXPLORATION_PROMPT.format(
        question=state["question"],
        schema=state["schema_context"],
        scan_section=scan_section,
        constraint_section=constraint_section,
    )
    for attempt in range(2):
        user = base_user if attempt == 0 else (
            base_user
            + "\n\nYOUR PREVIOUS ATTEMPT RETURNED NO USABLE SUB-QUESTIONS. You MUST now "
            "return at least 3 concrete, SQL-answerable sub-questions that use ONLY tables "
            "and columns present in the schema above. Begin with a `landscape` question. "
            "If the input is a claim rather than a question, reframe it as a verification "
            "question (e.g. 'Is it true that …?')."
        )
        try:
            plan: _ExplorationPlan = llm.complete(
                system="You are a senior data analyst designing a sequential investigative chain.",
                user=user,
                response_model=_ExplorationPlan,
            )
            sqs = [sq for sq in (plan.sub_questions or []) if (sq.question or "").strip()]
            if sqs:
                return sqs
        except Exception:
            continue  # transient provider/parse error — fall through to retry / floor
    return []


def _floor_chain(state: AgentState) -> list[SubQuestion]:
    """Deterministic safety-net chain (no LLM) so an exploration never starts
    empty even if the planner fails entirely. Anchors on the first schema table
    and the original question, then lets the per-sub-question SQL planner do the
    real work against the live schema."""
    import re as _re
    m = _re.search(r"^(?:TABLE:|##)\s+([^\s\[(]+)", state.get("schema_context", "") or "", _re.MULTILINE)
    table = m.group(1) if m else "the primary table"
    q = (state.get("question") or "the original question").strip()
    return [
        SubQuestion(
            id="Q1", purpose="landscape", depends_on=[],
            question=f"What is the overall volume and the key measurable dimensions in the data most relevant to: {q}?",
            expected_output=f"A small summary of row counts and key aggregates from {table} and directly related tables.",
        ),
        SubQuestion(
            id="Q2", purpose="synthesis", depends_on=["Q1"],
            question=f"Based on the landscape above, what is the most direct, evidence-backed answer to: {q}?",
            expected_output="A focused aggregate (grouped/ranked as needed) that directly addresses the original question.",
        ),
    ]


# ── Node: plan_and_execute_subq ───────────────────────────────────────────────

def plan_and_execute_subq(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    """Plan SQL for the current sub-question, execute it, accumulate results."""
    sub_questions = state.get("sub_questions", [])
    idx = state.get("current_subq_idx", 0)
    prior_answers = state.get("subq_answers", [])

    if idx >= len(sub_questions):
        return {}

    subq = sub_questions[idx]
    known_pitfalls = state.get("pitfalls", [])

    raw_events = state.get("events_context") or ""
    events_section = f"{raw_events}\n" if raw_events else ""

    # Per-sub-question schema context: prefer structured Data Catalog if available,
    # else fall back to linked schema text.
    subq_schema = state.get("data_catalog") or state["schema_context"]
    if not subq_schema:
        subq_schema = state["schema_context"]
    try:
        from aughor.tools.schema_linker import link_schema
        linked = link_schema(
            subq.question, subq_schema, top_k_tables=4, top_k_cols=8,
            connection_id=state.get("connection_id"),
        )
        if linked:
            subq_schema = linked
    except Exception:
        logger.warning("schema-linking failed for sub-question; using unlinked schema", exc_info=True)

    llm = get_provider("coder")
    # Resilience: a single sub-question's planner hiccup (provider timeout, parse
    # error, oversized context) must NOT abort the whole chain. If the LLM raises,
    # fall back to a deterministic landscape query so this step still produces
    # evidence and the chain advances to the next sub-question.
    plan: Optional[QueryPlan] = None
    try:
        plan = llm.complete(
            system="You are a senior data analyst writing SQL for an investigative sub-question.",
            user=PLAN_SUBQ_PROMPT.format(
                question=state["question"],
                subq_id=subq.id,
                purpose=subq.purpose,
                subq_question=subq.question,
                expected_output=subq.expected_output,
                prior_answers=_format_prior_answers(prior_answers),
                analysis_ledger=state.get("analysis_ledger") or "(none)",
                schema=subq_schema,
                pitfall_section=format_pitfall_section(known_pitfalls),
                events_section=events_section,
                data_portrait=state.get("subq_data_portrait", {}).get(subq.id, ""),
            ),
            response_model=QueryPlan,
        )
    except Exception:
        plan = None

    # Guard: ensure at least one query (covers planner failure AND empty plans)
    queries = [q for q in (plan.queries if plan else []) if q and q.strip()]
    if not queries:
        import re as _re
        _tm = _re.search(r"^(?:TABLE:|##)\s+([\w.]+)", state["schema_context"], _re.MULTILINE)
        fallback_table = _tm.group(1) if _tm else "unknown"
        queries = [f'SELECT COUNT(*) AS row_count FROM "{fallback_table}"']

    results: list[QueryResult] = []
    new_pitfalls: list[Pitfall] = []

    for sql in queries[:2]:  # explore mode: cap at 2 queries per sub-question
        result = conn.execute(subq.id, sql)

        # Attach predictions
        _d = result.model_dump()
        _d["expected_if_true"] = (plan.expected_if_true if plan else None) or None
        _d["expected_if_false"] = (plan.expected_if_false if plan else None) or None
        result = QueryResult(**_d)

        if result.error:
            from aughor.agent.state import SQLFix
            from aughor.agent.prompts import FIX_SQL_PROMPT
            from aughor.semantic.kb_retriever import retrieve_for_fix_sql
            from aughor.tools.error_classifier import classify_sql_error

            original_error = result.error
            kb_fix_patterns = retrieve_for_fix_sql(original_error, sql)
            diagnosis = classify_sql_error(original_error, sql, conn.dialect)
            error_diagnosis_block = f"DIAGNOSIS:\n{diagnosis}\n" if diagnosis else ""

            fix: SQLFix = get_provider("coder").complete(
                system="You are a SQL expert. Fix the broken query.",
                user=FIX_SQL_PROMPT.format(
                    dialect=conn.dialect,
                    sql=sql,
                    error=original_error,
                    error_diagnosis=error_diagnosis_block,
                    schema=state["schema_context"],
                    kb_patterns_section=kb_fix_patterns,
                ),
                response_model=SQLFix,
            )
            retry = conn.execute(subq.id, fix.fixed_sql)
            new_pitfalls.append(Pitfall(
                original_sql=sql,
                error=original_error,
                fixed_sql=fix.fixed_sql,
                fix_explanation=fix.fix_explanation,
                data_quality_issue=fix.data_quality_issue,
                retry_error=retry.error or None,
            ))
            results.append(_attach_stats(retry))
        else:
            results.append(_attach_stats(result))

    # Stash results in state temporarily (reason_over_result picks them up)
    return {
        "query_history": results,   # operator.add appends — stays compatible with investigate mode
        "pitfalls": new_pitfalls,
    }



# ── Node: exploratory_scan_subq ───────────────────────────────────────────────
# MindsDB-style mid-chain discovery: before planning SQL for a sub-question,
# run 1–2 quick probes to discover cardinalities, ranges, and distinct values.
# Results feed into the planner as a "Data Portrait" paragraph.

def exploratory_scan_subq(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    """Run quick discovery queries for the current sub-question.

    Max 2 queries, max 3 seconds each. Produces a short markdown paragraph
    stored in state["subq_data_portrait"][subq.id].
    """
    import time as _time
    sub_questions = state.get("sub_questions", [])
    idx = state.get("current_subq_idx", 0)
    if idx >= len(sub_questions):
        return {}

    subq = sub_questions[idx]
    purpose = subq.purpose

    # Extract first table from schema context
    import re as _re
    m = _re.search(r'^(?:TABLE:|##)\s+([\w.]+)', state.get("schema_context", ""), _re.MULTILINE)
    table = m.group(1) if m else None
    if not table:
        return {}

    discoveries: list[str] = []
    _MAX_Q = 2
    _TIMEOUT = 3.0

    def _timed(sql: str) -> tuple[list[str], list[list]]:
        t0 = _time.time()
        try:
            result = conn.execute(subq.id + "_scan", sql)
            if _time.time() - t0 > _TIMEOUT:
                return [], []
            return result.columns, result.rows
        except Exception:
            return [], []

    queries_run = 0

    # Landscape / drill_down: cardinality + date range
    if purpose in ("landscape", "drill_down"):
        # Count distinct key column (first non-date column)
        cols, rows = _timed(f"SELECT * FROM {table} LIMIT 1")
        if rows and cols:
            key_col = next((c for c in cols if not _re.search(r'date|time|_at$', c, _re.I)), cols[0])
            c2, r2 = _timed(f'SELECT COUNT(DISTINCT "{key_col}") AS distinct_count FROM {table}')
            if r2 and queries_run < _MAX_Q:
                discoveries.append(f"Distinct {key_col}: {r2[0][0]}")
                queries_run += 1
        # Date range
        date_col = next((c for c in (cols or []) if _re.search(r'date|time|_at$', c, _re.I)), None)
        if date_col and queries_run < _MAX_Q:
            c3, r3 = _timed(f'SELECT MIN("{date_col}") AS min_date, MAX("{date_col}") AS max_date FROM {table}')
            if r3:
                discoveries.append(f"{date_col} range: {r3[0][0]} to {r3[0][1]}")
                queries_run += 1

    # Relationship: distinct categorical values
    elif purpose == "relationship":
        cols, rows = _timed(f"SELECT * FROM {table} LIMIT 1")
        if rows and cols:
            cat_col = next((c for c in cols if _re.search(r'name|type|category|status|region|state$', c, _re.I)), cols[0])
            if queries_run < _MAX_Q:
                c2, r2 = _timed(f'SELECT DISTINCT "{cat_col}" FROM {table} LIMIT 20')
                if r2:
                    vals = [str(r[0]) for r in r2[:20]]
                    discoveries.append(f"Distinct {cat_col} values: {', '.join(vals)}")
                    queries_run += 1

    # Threshold / confounder: numeric summary
    elif purpose in ("threshold", "confounder"):
        cols, rows = _timed(f"SELECT * FROM {table} LIMIT 1")
        if rows and cols:
            num_col = next((c for c in cols if _re.search(r'amount|price|total|revenue|count|score|value$', c, _re.I)), cols[0])
            if queries_run < _MAX_Q:
                c2, r2 = _timed(f'SELECT MIN("{num_col}") AS min_v, MAX("{num_col}") AS max_v, AVG("{num_col}")::FLOAT AS avg_v FROM {table}')
                if r2 and r2[0]:
                    discoveries.append(
                        f"{num_col} summary: min={r2[0][0]}, max={r2[0][1]}, avg={r2[0][2] if len(r2[0]) > 2 else 'N/A'}"
                    )
                    queries_run += 1

    portrait = "\n".join(f"- {d}" for d in discoveries) if discoveries else ""
    current_portraits = state.get("subq_data_portrait", {})
    updated_portraits = {**current_portraits, subq.id: portrait}

    return {"subq_data_portrait": updated_portraits}

# ── Node: reason_over_result ──────────────────────────────────────────────────

def reason_over_result(state: AgentState) -> dict[str, Any]:
    """
    Interpret results for the current sub-question. Marks it done.
    Injects refinements into the next sub-question if needed.
    Advances current_subq_idx.
    """
    sub_questions = state.get("sub_questions", [])
    idx = state.get("current_subq_idx", 0)
    prior_answers = state.get("subq_answers", [])

    if idx >= len(sub_questions):
        return {"current_subq_idx": idx + 1, "iteration": state.get("iteration", 0) + 1}

    subq = sub_questions[idx]

    # Gather the query results produced by plan_and_execute_subq for this sub-question
    all_history = state.get("query_history", [])
    subq_results = [r for r in all_history if r.hypothesis_id == subq.id]

    if not subq_results or all(r.error for r in subq_results):
        # Technical failure — record as inconclusive, don't block chain
        answer_obj = ReasoningOutput(
            answer=f"Could not retrieve data for {subq.id} due to SQL errors.",
            insight="No data available — this sub-question's findings are missing from the final answer.",
            refinement=None,
        )
    else:
        formatted = "\n\n".join(format_result_for_llm(r) for r in subq_results)
        llm = get_provider("coder")
        try:
            answer_obj = llm.complete(
                system="You are a senior data analyst interpreting query results.",
                user=REASON_OVER_RESULT_PROMPT.format(
                    question=state["question"],
                    subq_id=subq.id,
                    purpose=subq.purpose,
                    subq_question=subq.question,
                    expected_output=subq.expected_output,
                    query_results=formatted,
                    analysis_ledger=state.get("analysis_ledger") or "(none)",
                    prior_context=_format_prior_answers(prior_answers),
                ),
                response_model=ReasoningOutput,
            )
        except Exception:
            # Reasoning hiccup must not abort the chain — record the raw result as
            # an inconclusive answer and let downstream steps / synthesis proceed.
            answer_obj = ReasoningOutput(
                answer=f"Query for {subq.id} returned data but automated interpretation failed; see the raw result.",
                insight="Interpretation step errored — figures above are from the query but not narrated.",
                refinement=None,
            )

    # Use the first non-errored result for SQL/columns/rows in the answer record
    best_result = next((r for r in subq_results if not r.error), subq_results[0] if subq_results else None)
    answer = SubQuestionAnswer(
        subq_id=subq.id,
        question=subq.question,
        purpose=subq.purpose,
        sql=best_result.sql if best_result else "",
        columns=best_result.columns if best_result else [],
        rows=best_result.rows if best_result else [],
        row_count=best_result.row_count if best_result else 0,
        error=best_result.error if best_result else "No queries ran",
        answer=answer_obj.answer,
        insight=answer_obj.insight,
        refinement=answer_obj.refinement,
    )

    # Mark sub-question done and inject refinement into the next sub-question
    updated_subqs = list(sub_questions)
    updated_subqs[idx] = SubQuestion(**{**subq.model_dump(), "done": True, "answer": answer_obj.answer, "refinement": answer_obj.refinement})

    # Insert promoted sub-question if data revealed one
    if answer_obj.new_sub_question:
        updated_subqs.insert(idx + 1, answer_obj.new_sub_question)

    # Inject refinement text into the next sub-question's expected_output description
    if answer_obj.refinement and idx + 1 < len(updated_subqs):
        next_subq = updated_subqs[idx + 1]
        updated_subqs[idx + 1] = SubQuestion(**{
            **next_subq.model_dump(),
            "expected_output": f"{next_subq.expected_output}\n[Refinement from {subq.id}: {answer_obj.refinement}]",
        })

    return {
        "sub_questions": updated_subqs,
        "subq_answers": [answer],      # operator.add appends
        "current_subq_idx": idx + 1,
        "iteration": state.get("iteration", 0) + 1,
    }


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_reason(state: AgentState) -> str:
    idx = state.get("current_subq_idx", 0)
    sub_questions = state.get("sub_questions", [])
    iteration = state.get("iteration", 0)

    if iteration >= MAX_SUBQ:
        return "synthesize_exploration"
    if idx >= len(sub_questions):
        return "synthesize_exploration"
    return "plan_and_execute_subq"


# ── Node: synthesize_exploration ──────────────────────────────────────────────

# ── Schema learning models (used by _learn_from_exploration) ─────────────────

class _ColumnCaveat(BaseModel):
    table: str = Field(description="Exact table name as it appears in the schema")
    column: str = Field(description="Exact column name")
    caveat: str = Field(
        description="One-sentence warning an analyst must know to avoid wrong results. "
                    "Must be directly supported by data observed in this investigation. "
                    "Example: 'customer_id is a per-order hash — use customer_unique_id "
                    "to identify unique customers across orders.'"
    )


class _SchemaLearning(BaseModel):
    caveats: list[_ColumnCaveat] = Field(
        default_factory=list,
        description="Schema-level column caveats discovered during this exploration. "
                    "Only include findings directly supported by actual query results above. "
                    "Empty list if no concrete schema issues were found.",
    )


def _learn_from_exploration(
    report: ExplorationReport,
    chain_summary: str,
    conn_id: str,
) -> int:
    """
    Persist schema discoveries from an exploration run back to the glossary.

    Two passes:
      1. Structured  — extract from report.data_quality_notes (no LLM, zero cost)
      2. LLM-based   — lightweight coder pass over the chain summary to catch
                       subtler patterns the structured notes missed

    Returns the number of new caveat entries written. Never raises — best-effort only.
    """
    try:
        from aughor.semantic.glossary import load_glossary, update_column

        written = 0
        glossary = load_glossary()

        def _existing_caveat(table: str, column: str) -> str:
            return (glossary.get("tables", {})
                            .get(table, {})
                            .get("columns", {})
                            .get(column, {})
                            .get("caveats", "") or "")

        def _write_caveat(table: str, column: str, text: str) -> bool:
            """Write caveat only if it adds new information. Returns True if written."""
            nonlocal glossary
            if not table or not column or not text or len(text) < 15:
                return False
            existing = _existing_caveat(table, column)
            if text in existing:
                return False
            combined = f"{existing} | {text}" if existing else text
            update_column(table, column, caveats=combined)
            # Reload so subsequent writes see the updated state
            glossary = load_glossary()
            return True

        # ── Pass 1: data_quality_notes (structured, free) ────────────────────
        for note in (report.data_quality_notes or []):
            table = (note.table or "").strip()
            column = (note.column or "").strip()
            issue = (note.issue or "").strip()
            if not table or not issue or table in ("SQL Execution", ""):
                continue
            if column and _write_caveat(table, column, issue):
                written += 1

        # ── Pass 2: LLM extraction from chain summary ─────────────────────────
        if not chain_summary:
            return written

        try:
            llm = get_provider("coder")
            learning: _SchemaLearning = llm.complete(
                system=(
                    "You are auditing an analytics investigation for schema-level data quality issues. "
                    "Extract ONLY concrete, column-specific caveats that were directly observed in "
                    "the findings below. Do not infer or guess. "
                    "Focus on: wrong identifier columns, per-row hashes mistaken for stable IDs, "
                    "NULL patterns that skew aggregations, type mismatches, and FK mismatches."
                ),
                user=(
                    f"INVESTIGATION FINDINGS:\n{chain_summary[:4000]}\n\n"
                    f"CONCLUSION: {report.conclusion}\n\n"
                    "List any schema caveats (column-level gotchas) that an analyst must know "
                    "to avoid getting wrong answers on this dataset. "
                    "Only include findings directly evidenced by the data above. "
                    "Return an empty list if no clear schema issues were found."
                ),
                response_model=_SchemaLearning,
            )

            for caveat in (learning.caveats or []):
                table = (caveat.table or "").strip()
                column = (caveat.column or "").strip()
                text = (caveat.caveat or "").strip()
                if _write_caveat(table, column, text):
                    written += 1

        except Exception:
            pass  # LLM pass failing is fine — pass 1 already wrote what it could

        return written

    except Exception:
        return 0  # Never crash the pipeline


def synthesize_exploration(state: AgentState) -> dict[str, Any]:
    """Produce the final ExplorationReport from the completed Q→A chain."""
    answers = state.get("subq_answers", [])
    pitfalls = state.get("pitfalls", [])

    if not answers:
        return {
            "explore_report": ExplorationReport(
                headline="No data could be retrieved for this investigation.",
                conclusion="All sub-questions failed technically. Check the schema and query logs.",
                narrative="The investigative chain could not be completed due to SQL execution failures.",
                recommended_actions=["Check the connection and retry."],
            )
        }

    chain_summary = _format_chain_summary(answers)

    # Honesty guard: if the chain ended early (fewer answered sub-questions than
    # planned, e.g. a salvaged partial run), tell the writer NOT to present the
    # report as comprehensive. Prevents "given all of the above" on a 1-step chain.
    planned = state.get("sub_questions", []) or []
    answered_ids = {a.subq_id for a in answers}
    unanswered = [sq for sq in planned if sq.id not in answered_ids and not getattr(sq, "done", False)]
    if planned and (len(answers) < len(planned) or unanswered):
        gap = "; ".join(f"{sq.id}: {sq.question}" for sq in unanswered[:6]) or "later planned steps"
        chain_summary = (
            f"⚠️ INCOMPLETE CHAIN — only {len(answers)} of {len(planned)} planned sub-questions "
            f"actually ran. The following were NOT investigated and have NO data: {gap}. "
            f"Do NOT claim a comprehensive analysis or use phrases like 'given all of the above'. "
            f"Answer only from the completed steps below and explicitly note what remains unknown.\n\n"
            + chain_summary
        )

    # Collect data quality notes from pitfalls
    dq_notes: list[DataQualityNote] = []
    for p in pitfalls:
        if p.data_quality_issue:
            dq_notes.append(DataQualityNote(
                table="SQL Execution",
                column=None,
                issue=p.data_quality_issue,
                impact="May have affected data quality in the investigative chain.",
                recommended_fix=p.fix_explanation,
            ))

    raw_events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR CONTEXT (use to attribute findings to known events):\n{raw_events}\n" if raw_events else ""

    llm = get_provider("narrator")
    report: ExplorationReport = llm.complete(
        system="You are a senior data analyst writing an executive investigation report.",
        user=SYNTHESIZE_EXPLORATION_PROMPT.format(
            question=state["question"],
            analysis_ledger=state.get("analysis_ledger") or "(none)",
            chain_summary=chain_summary,
            events_section=events_section,
        ),
        response_model=ExplorationReport,
    )

    # Merge any dq_notes found during execution
    if dq_notes:
        existing = list(report.data_quality_notes or [])
        report = ExplorationReport(**{**report.model_dump(), "data_quality_notes": existing + dq_notes})

    # ── Learning loop: persist schema discoveries back to the glossary ────────
    conn_id = state.get("connection_id", "")
    _learn_from_exploration(report, chain_summary, conn_id)

    return {"explore_report": report}
