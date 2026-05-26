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

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

from aughor.agent.prompts_explore import (
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


# ── Node: decompose_exploration ───────────────────────────────────────────────

def decompose_exploration(state: AgentState) -> dict[str, Any]:
    """Break the question into an ordered chain of sub-questions."""
    scan_context = state.get("scan_context") or ""
    scan_section = (
        f"DATA PORTRAIT (actual distributions — use these ranges in your SQL planning):\n{scan_context}\n"
        if scan_context else ""
    )

    # Extract explicit user constraints from the question (re-use decompose pattern)
    constraint_section = "No explicit constraints detected."

    llm = get_provider("coder")
    plan: _ExplorationPlan = llm.complete(
        system="You are a senior data analyst designing a sequential investigative chain.",
        user=DECOMPOSE_EXPLORATION_PROMPT.format(
            question=state["question"],
            schema=state["schema_context"],
            scan_section=scan_section,
            constraint_section=constraint_section,
        ),
        response_model=_ExplorationPlan,
    )

    sub_questions = plan.sub_questions[:MAX_SUBQ]

    return {
        "sub_questions": sub_questions,
        "current_subq_idx": 0,
        "subq_answers": [],
        "pitfalls": [],
        "iteration": 0,
    }


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

    llm = get_provider("coder")
    plan: QueryPlan = llm.complete(
        system="You are a senior data analyst writing SQL for an investigative sub-question.",
        user=PLAN_SUBQ_PROMPT.format(
            question=state["question"],
            subq_id=subq.id,
            purpose=subq.purpose,
            subq_question=subq.question,
            expected_output=subq.expected_output,
            prior_answers=_format_prior_answers(prior_answers),
            schema=state["schema_context"],
            pitfall_section=format_pitfall_section(known_pitfalls),
            events_section=events_section,
        ),
        response_model=QueryPlan,
    )

    # Guard: ensure at least one query
    queries = [q for q in plan.queries if q and q.strip()]
    if not queries:
        import re as _re
        _tm = _re.search(r"^TABLE:\s+(\w+)", state["schema_context"], _re.MULTILINE)
        fallback_table = _tm.group(1) if _tm else "unknown"
        queries = [f'SELECT COUNT(*) AS row_count FROM "{fallback_table}"']

    results: list[QueryResult] = []
    new_pitfalls: list[Pitfall] = []

    for sql in queries[:2]:  # explore mode: cap at 2 queries per sub-question
        result = conn.execute(subq.id, sql)

        # Attach predictions
        _d = result.model_dump()
        _d["expected_if_true"] = plan.expected_if_true or None
        _d["expected_if_false"] = plan.expected_if_false or None
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
        answer_obj: ReasoningOutput = llm.complete(
            system="You are a senior data analyst interpreting query results.",
            user=REASON_OVER_RESULT_PROMPT.format(
                question=state["question"],
                subq_id=subq.id,
                purpose=subq.purpose,
                subq_question=subq.question,
                expected_output=subq.expected_output,
                query_results=formatted,
                prior_context=_format_prior_answers(prior_answers),
            ),
            response_model=ReasoningOutput,
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
            chain_summary=chain_summary,
            events_section=events_section,
        ),
        response_model=ExplorationReport,
    )

    # Merge any dq_notes found during execution
    if dq_notes:
        existing = list(report.data_quality_notes or [])
        report = ExplorationReport(**{**report.model_dump(), "data_quality_notes": existing + dq_notes})

    return {"explore_report": report}
