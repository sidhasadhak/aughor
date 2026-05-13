"""LangGraph node functions — each is a pure function over AgentState."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hermes.db.connection import DatabaseConnection

from hermes.agent.prompts import (
    DECOMPOSE_PROMPT,
    FIX_SQL_PROMPT,
    PLAN_QUERIES_PROMPT,
    SCORE_EVIDENCE_PROMPT,
    SYNTHESIZE_PROMPT,
    format_pitfall_section,
)
from hermes.agent.state import (
    AgentState,
    AnalysisReport,
    DecomposeOutput,
    EvidenceScore,
    Hypothesis,
    Pitfall,
    QueryPlan,
    QueryResult,
    SQLFix,
)
from hermes.llm.provider import get_provider
from hermes.tools.executor import format_result_for_llm

MAX_ITER = int(__import__("os").getenv("HERMES_MAX_ITER", "6"))


# ── Node: decompose_question ─────────────────────────────────────────────────

def decompose_question(state: AgentState) -> dict[str, Any]:
    llm = get_provider()
    output: DecomposeOutput = llm.complete(
        system="You are a senior data analyst. Decompose the question into testable hypotheses.",
        user=DECOMPOSE_PROMPT.format(
            question=state["question"],
            schema=state["schema_context"],
        ),
        response_model=DecomposeOutput,
    )
    return {
        "hypotheses": output.hypotheses,
        "current_hypothesis_idx": 0,
        "iteration": 0,
        "pitfalls": [],
    }


# ── Node: plan_and_execute ────────────────────────────────────────────────────

def plan_and_execute(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    hypotheses = state["hypotheses"]
    idx = state["current_hypothesis_idx"]

    if idx >= len(hypotheses):
        return {}

    h = hypotheses[idx]
    prior_context = _format_prior_context(state.get("query_history", []))
    known_pitfalls = state.get("pitfalls", [])

    llm = get_provider()
    plan: QueryPlan = llm.complete(
        system="You are a senior data analyst writing SQL to test a hypothesis.",
        user=PLAN_QUERIES_PROMPT.format(
            hypothesis_id=h.id,
            hypothesis_description=h.description,
            schema=state["schema_context"],
            prior_context=prior_context or "None yet.",
            pitfall_section=format_pitfall_section(known_pitfalls),
        ),
        response_model=QueryPlan,
    )

    results: list[QueryResult] = []
    new_pitfalls: list[Pitfall] = []

    for sql in plan.queries:
        result = conn.execute(h.id, sql)

        # ── Self-correction: retry failed queries once ────────────────────
        if result.error:
            fix: SQLFix = llm.complete(
                system="You are a SQL expert. Fix the broken query.",
                user=FIX_SQL_PROMPT.format(
                    dialect=conn.dialect,
                    sql=sql,
                    error=result.error,
                    schema=state["schema_context"],
                ),
                response_model=SQLFix,
            )

            retry = conn.execute(h.id, fix.fixed_sql)

            # Record the pitfall regardless of whether the retry succeeded
            new_pitfalls.append(Pitfall(
                original_sql=sql,
                error=result.error,
                fixed_sql=fix.fixed_sql,
                fix_explanation=fix.fix_explanation,
                data_quality_issue=fix.data_quality_issue,
            ))

            # Use the retried result (even if it also errored — at least we tried)
            results.append(retry)
        else:
            results.append(result)

    return {
        "query_history": results,   # operator.add appends
        "pitfalls": new_pitfalls,   # operator.add appends
    }


# ── Node: score_evidence ──────────────────────────────────────────────────────

def score_evidence(state: AgentState) -> dict[str, Any]:
    idx = state["current_hypothesis_idx"]
    hypotheses = state["hypotheses"]

    if idx >= len(hypotheses):
        return {"iteration": state.get("iteration", 0) + 1}

    h = hypotheses[idx]
    hyp_results = [r for r in state.get("query_history", []) if r.hypothesis_id == h.id]

    all_errored = hyp_results and all(r.error for r in hyp_results)

    if not hyp_results:
        score = EvidenceScore(
            hypothesis_id=h.id,
            confidence=0.5,
            verdict="inconclusive",
            key_finding="No queries were executed for this hypothesis.",
            should_continue=False,
        )
    elif all_errored:
        # Every query failed — this is a technical problem, not evidence against the hypothesis
        errors = "; ".join(dict.fromkeys(r.error for r in hyp_results if r.error))
        score = EvidenceScore(
            hypothesis_id=h.id,
            confidence=0.5,
            verdict="inconclusive",
            key_finding=f"All queries failed technically — could not test this hypothesis. Errors: {errors[:200]}",
            should_continue=True,
        )
    else:
        formatted = "\n\n".join(format_result_for_llm(r) for r in hyp_results)
        llm = get_provider()
        score: EvidenceScore = llm.complete(
            system="You are a senior data analyst evaluating evidence for a hypothesis.",
            user=SCORE_EVIDENCE_PROMPT.format(
                hypothesis_id=h.id,
                hypothesis_description=h.description,
                query_results=formatted,
            ),
            response_model=EvidenceScore,
        )

    updated = [
        Hypothesis(
            id=existing.id,
            description=existing.description,
            confidence=score.confidence if existing.id == h.id else existing.confidence,
            verdict=score.verdict if existing.id == h.id else existing.verdict,
            key_finding=score.key_finding if existing.id == h.id else existing.key_finding,
        )
        for existing in hypotheses
    ]

    return {
        "hypotheses": updated,
        "evidence_scores": [score],
        "current_hypothesis_idx": idx + 1,
        "iteration": state.get("iteration", 0) + 1,
    }


# ── Node: synthesize_report ───────────────────────────────────────────────────

def synthesize_report(state: AgentState) -> dict[str, Any]:
    pitfalls = state.get("pitfalls", [])
    llm = get_provider()
    report: AnalysisReport = llm.complete(
        system="You are a senior data analyst writing an executive-level investigation report.",
        user=SYNTHESIZE_PROMPT.format(
            question=state["question"],
            hypothesis_summary=_format_hypothesis_summary(state["hypotheses"]),
            evidence_log=_format_full_evidence(state.get("query_history", [])),
            pitfall_section=_format_pitfalls_for_synthesis(pitfalls),
        ),
        response_model=AnalysisReport,
    )
    return {"report": report}


# ── Routing ───────────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> str:
    iteration = state.get("iteration", 0)
    hypotheses = state.get("hypotheses", [])
    idx = state.get("current_hypothesis_idx", 0)

    if iteration >= MAX_ITER:
        return "synthesize"

    if idx < len(hypotheses):
        return "plan_and_execute"

    return "synthesize"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_prior_context(history: list[QueryResult]) -> str:
    if not history:
        return ""
    parts = []
    for r in history[-6:]:
        status = f"ERROR: {r.error}" if r.error else f"{r.row_count} rows"
        parts.append(f"[{r.hypothesis_id}] {r.sql[:120]}  → {status}")
    return "\n".join(parts)


def _format_hypothesis_summary(hypotheses: list[Hypothesis]) -> str:
    lines = []
    for i, h in enumerate(hypotheses, 1):
        bar = "█" * int(h.confidence * 10) + "░" * (10 - int(h.confidence * 10))
        lines.append(
            f"H{i} [{h.verdict.upper()} {h.confidence:.0%}]  {bar}\n"
            f"  {h.description}\n"
            f"  Finding: {h.key_finding or 'Not scored'}"
        )
    return "\n\n".join(lines)


def _format_full_evidence(history: list[QueryResult]) -> str:
    if not history:
        return "No queries were executed."
    return "\n\n---\n\n".join(format_result_for_llm(r) for r in history)


def _format_pitfalls_for_synthesis(pitfalls: list[Pitfall]) -> str:
    if not pitfalls:
        return ""
    lines = [
        "SQL CORRECTIONS MADE DURING INVESTIGATION:",
        "(These indicate either dialect incompatibilities or data quality issues)",
    ]
    for i, p in enumerate(pitfalls, 1):
        lines.append(f"\n{i}. Fix: {p.fix_explanation}")
        if p.data_quality_issue:
            lines.append(f"   Data quality issue found: {p.data_quality_issue}")
    return "\n".join(lines) + "\n"
