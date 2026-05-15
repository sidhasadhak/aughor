"""LangGraph node functions — each is a pure function over AgentState."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hermes.db.connection import DatabaseConnection

from hermes.agent.prompts import (
    DECOMPOSE_PROMPT,
    FIX_SQL_PROMPT,
    PLAN_QUERIES_PROMPT,
    ROUTE_QUESTION_PROMPT,
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
    RouteDecision,
    SQLFix,
)
from hermes.llm.provider import get_provider
from hermes.tools.executor import format_result_for_llm
from hermes.tools.stats import analyze_query_result, StatResult as _StatResult

MAX_ITER = int(__import__("os").getenv("HERMES_MAX_ITER", "6"))


# ── Node: route_question ─────────────────────────────────────────────────────

def route_question(state: AgentState) -> dict[str, Any]:
    llm = get_provider("coder")
    decision: RouteDecision = llm.complete(
        system="You are a routing classifier for a business intelligence agent. Classify questions precisely.",
        user=ROUTE_QUESTION_PROMPT.format(question=state["question"]),
        response_model=RouteDecision,
    )
    if decision.mode == "direct":
        return {
            "query_mode": "direct",
            "hypotheses": [Hypothesis(id="direct", description=state["question"], confidence=0.0, verdict="untested")],
            "current_hypothesis_idx": 0,
            "iteration": 0,
            "pitfalls": [],
            "prior_analyses": [],
        }
    return {"query_mode": "investigate"}


def route_after_classify(state: AgentState) -> str:
    return "plan_and_execute" if state.get("query_mode") == "direct" else "decompose"


# ── Node: decompose_question ─────────────────────────────────────────────────

def decompose_question(state: AgentState) -> dict[str, Any]:
    from hermes.tools.prior_analyses import search_prior_investigations
    prior_analyses = search_prior_investigations(state["question"])

    llm = get_provider("coder")
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
        "prior_analyses": prior_analyses,
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

    # Retrieve only schema tables relevant to this hypothesis (no-op for small schemas)
    from hermes.semantic.retriever import retrieve_relevant_schema
    schema_for_hypothesis = retrieve_relevant_schema(h.description, state["schema_context"])

    # Prepend any relevant prior investigation summaries
    prior_analyses = state.get("prior_analyses", [])
    prior_analyses_text = (
        "RELEVANT PAST INVESTIGATIONS:\n" + "\n\n".join(prior_analyses)
        if prior_analyses else ""
    )

    llm = get_provider("coder")
    plan: QueryPlan = llm.complete(
        system="You are a senior data analyst writing SQL to test a hypothesis.",
        user=PLAN_QUERIES_PROMPT.format(
            hypothesis_id=h.id,
            hypothesis_description=h.description,
            schema=schema_for_hypothesis,
            prior_context=prior_context or "None yet.",
            prior_analyses_section=prior_analyses_text,
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
            fix: SQLFix = get_provider("coder").complete(
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

            new_pitfalls.append(Pitfall(
                original_sql=sql,
                error=result.error,
                fixed_sql=fix.fixed_sql,
                fix_explanation=fix.fix_explanation,
                data_quality_issue=fix.data_quality_issue,
            ))

            result = _attach_stats(retry)
            results.append(result)
        else:
            results.append(_attach_stats(result))

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
        llm = get_provider("coder")
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
    human_feedback = state.get("human_feedback") or ""
    feedback_section = (
        f"\nANALYST FEEDBACK (incorporate this before finalising the report):\n{human_feedback}\n"
        if human_feedback else ""
    )
    llm = get_provider("narrator")
    report: AnalysisReport = llm.complete(
        system="You are a senior data analyst writing an executive-level investigation report.",
        user=SYNTHESIZE_PROMPT.format(
            question=state["question"],
            hypothesis_summary=_format_hypothesis_summary(state["hypotheses"]),
            evidence_log=_format_full_evidence(state.get("query_history", [])),
            pitfall_section=_format_pitfalls_for_synthesis(pitfalls),
            human_feedback_section=feedback_section,
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


def _attach_stats(result: QueryResult) -> QueryResult:
    """Run statistical analysis on a successful query result and attach findings."""
    if result.error or not result.rows:
        return result
    try:
        stat_results = analyze_query_result(result.columns, result.rows)
        if stat_results:
            from hermes.agent.state import StatResult
            result = QueryResult(
                **{
                    **result.model_dump(),
                    "stats": [
                        StatResult(**s.__dict__) for s in stat_results
                    ],
                }
            )
    except Exception:
        pass  # stats are best-effort — never block the investigation
    return result


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
