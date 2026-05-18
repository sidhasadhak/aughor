"""LangGraph node functions — each is a pure function over AgentState."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from hermes.db.connection import DatabaseConnection

from hermes.agent.prompts import (
    CONSISTENCY_CHECK_PROMPT,
    DECOMPOSE_PROMPT,
    FIX_SQL_PROMPT,
    PLAN_QUERIES_PROMPT,
    ROUTE_QUESTION_PROMPT,
    SCORE_EVIDENCE_PROMPT,
    SYNTHESIZE_PROMPT,
    format_pitfall_section,
)
from hermes.rules import get_rules_block
from hermes.agent.state import (
    AgentState,
    AnalysisReport,
    DataQualityNote,
    DecomposeOutput,
    EvidenceScore,
    Hypothesis,
    Pitfall,
    QueryPlan,
    QueryResult,
    RouteDecision,
    SQLFix,
)
from pydantic import BaseModel as _BaseModel

class _Contradiction(_BaseModel):
    claim_a: str
    claim_b: str
    dimension: str
    proposed_resolution: str

class _ConsistencyReport(_BaseModel):
    contradictions: list[_Contradiction]
    passed: bool

_CONSISTENCY_ENABLED = __import__("os").getenv("HERMES_CONSISTENCY_CHECK", "true").lower() != "false"
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
    # Low-confidence direct classifications fall back to investigate —
    # false-direct (shallow answer) is worse than false-investigate (extra thoroughness)
    effective_mode = decision.mode if decision.confidence >= 0.65 else "investigate"
    base = {"route_reasoning": decision.reasoning, "route_confidence": decision.confidence}
    if effective_mode == "direct":
        return {
            **base,
            "query_mode": "direct",
            "hypotheses": [Hypothesis(id="direct", description=state["question"], confidence=0.0, verdict="untested")],
            "current_hypothesis_idx": 0,
            "iteration": 0,
            "pitfalls": [],
            "prior_analyses": [],
        }
    return {**base, "query_mode": "investigate"}


def route_after_classify(state: AgentState) -> str:
    return "plan_and_execute" if state.get("query_mode") == "direct" else "exploratory_scan"


# ── Node: exploratory_scan ────────────────────────────────────────────────────

def exploratory_scan(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    """
    Run a small set of heuristic orientation queries before hypothesis formation.

    Produces a DATA PORTRAIT — row counts, date ranges, metric totals, and
    categorical distributions — that is injected into decompose_question so
    hypotheses are grounded in actual data, not schema column names alone.

    Results are NOT added to query_history; they exist only as formatted text.
    Every query is best-effort: failures are silently skipped.
    """
    import re
    from hermes.tools.schema import _SECTION_STOP

    schema_str = state["schema_context"]

    # Parse column types from the schema context string
    table_col_types: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line in schema_str.splitlines():
        if _SECTION_STOP.match(line):
            current = None
            continue
        m = re.match(r"^TABLE:\s+(\w+)", line)
        if m:
            current = m.group(1)
            table_col_types[current] = []
        elif current:
            col_m = re.match(r"^\s{2}(.+?)\s{2,}(\S+)", line)
            if col_m and not line.strip().startswith("--"):
                table_col_types[current].append((col_m.group(1), col_m.group(2)))

    def _is_numeric(t: str) -> bool:
        return bool(re.search(r"INT|FLOAT|DOUBLE|DECIMAL|NUMERIC|REAL|HUGEINT", t.upper()))

    def _is_date(t: str) -> bool:
        return bool(re.search(r"DATE|TIMESTAMP|DATETIME", t.upper()))

    def _is_text(t: str) -> bool:
        return bool(re.search(r"VARCHAR|TEXT|STRING|CHAR", t.upper()))

    def _q(name: str) -> str:
        return f'"{name}"'

    portrait_parts: list[str] = []

    for table, col_type_pairs in list(table_col_types.items())[:4]:
        date_cols = [c for c, t in col_type_pairs if _is_date(t)]
        num_cols  = [c for c, t in col_type_pairs if _is_numeric(t)]
        # Skip _id columns — too high cardinality to be meaningful categoricals
        cat_cols  = [c for c, t in col_type_pairs if _is_text(t) and not c.lower().endswith("_id")]

        lines: list[str] = [f"TABLE: {table}"]

        # Row count + date range
        if date_cols:
            dc = _q(date_cols[0])
            r = conn.execute("scan", f'SELECT COUNT(*) AS n, MIN({dc})::VARCHAR, MAX({dc})::VARCHAR FROM {_q(table)}')
            if not r.error and r.rows:
                n, min_d, max_d = r.rows[0]
                lines.append(f"  {int(n):,} rows | {date_cols[0]}: {min_d} → {max_d}")
        else:
            r = conn.execute("scan", f'SELECT COUNT(*) AS n FROM {_q(table)}')
            if not r.error and r.rows:
                lines.append(f"  {int(r.rows[0][0]):,} rows")

        # Key metric aggregates (sum + avg for up to 3 numeric columns)
        if num_cols:
            agg = ", ".join(
                f'ROUND(SUM({_q(c)}), 1) AS "sum_{c}", ROUND(AVG({_q(c)}), 2) AS "avg_{c}"'
                for c in num_cols[:3]
            )
            r = conn.execute("scan", f'SELECT {agg} FROM {_q(table)}')
            if not r.error and r.rows and r.columns:
                pairs = [
                    f"{col}={val}"
                    for col, val in zip(r.columns, r.rows[0])
                    if val is not None and val != "NULL"
                ]
                if pairs:
                    lines.append(f"  Metrics: {', '.join(pairs)}")

        # Categorical distributions (top 8 values with counts, up to 2 columns)
        for cc in cat_cols[:2]:
            r = conn.execute("scan", f'SELECT {_q(cc)}, COUNT(*) AS n FROM {_q(table)} GROUP BY 1 ORDER BY 2 DESC LIMIT 8')
            if not r.error and r.rows:
                vals = ", ".join(f"{row[0]}({row[1]})" for row in r.rows)
                lines.append(f"  {cc}: {vals}")

        portrait_parts.append("\n".join(lines))

    if not portrait_parts:
        return {"scan_context": ""}

    portrait = (
        "DATA PORTRAIT — run this before forming any hypothesis:\n"
        "These are actual counts and distributions from the database. "
        "Hypotheses must be grounded in what the data can plausibly show.\n\n"
        + "\n\n".join(portrait_parts)
    )
    return {"scan_context": portrait}


# ── Node: decompose_question ─────────────────────────────────────────────────

def decompose_question(state: AgentState) -> dict[str, Any]:
    from hermes.tools.prior_analyses import search_prior_investigations
    from hermes.semantic.kb_retriever import retrieve_for_decompose
    prior_analyses = search_prior_investigations(state["question"], connection_id=state.get("connection_id", ""))
    kb_domain = retrieve_for_decompose(state["question"])

    scan_context = state.get("scan_context") or ""
    scan_section = (
        f"STEP 1.5 — STUDY THE DATA PORTRAIT before forming hypotheses:\n{scan_context}\n"
        if scan_context else ""
    )

    rules_block = get_rules_block()
    llm = get_provider("coder")
    output: DecomposeOutput = llm.complete(
        system="You are a senior data analyst. Decompose the question into testable hypotheses.",
        user=rules_block + DECOMPOSE_PROMPT.format(
            question=state["question"],
            schema=state["schema_context"],
            kb_domain_section=kb_domain,
            scan_section=scan_section,
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
    prior_context = _format_prior_context(state.get("query_history", []), h.id)
    known_pitfalls = state.get("pitfalls", [])

    # Retrieve only schema tables relevant to this hypothesis (no-op for small schemas)
    from hermes.semantic.retriever import retrieve_relevant_schema
    from hermes.semantic.kb_retriever import retrieve_for_planning
    schema_for_hypothesis = retrieve_relevant_schema(h.description, state["schema_context"])
    kb_patterns = retrieve_for_planning(h.description)

    # Prepend any relevant prior investigation summaries
    prior_analyses = state.get("prior_analyses", [])
    prior_analyses_text = (
        "RELEVANT PAST INVESTIGATIONS:\n" + "\n\n".join(prior_analyses)
        if prior_analyses else ""
    )

    rules_block = get_rules_block()
    llm = get_provider("coder")
    plan: QueryPlan = llm.complete(
        system="You are a senior data analyst writing SQL to test a hypothesis.",
        user=rules_block + PLAN_QUERIES_PROMPT.format(
            hypothesis_id=h.id,
            hypothesis_description=h.description,
            schema=schema_for_hypothesis,
            prior_context=prior_context or "None yet.",
            prior_analyses_section=prior_analyses_text,
            pitfall_section=format_pitfall_section(known_pitfalls),
            kb_patterns_section=kb_patterns,
        ),
        response_model=QueryPlan,
    )

    results: list[QueryResult] = []
    new_pitfalls: list[Pitfall] = []

    # Guard: planner must return at least one query. If the model slips through
    # the Pydantic min_length=1 constraint (e.g. via a provider that strips
    # validation), inject a single-row diagnostic so score_evidence always has
    # evidence to work with and never silently produces a no-query hypothesis.
    queries = [q for q in plan.queries if q and q.strip()]
    if not queries:
        # Build the least-assumption diagnostic: count rows for the first table
        # visible in the schema. This can never refute a hypothesis but it forces
        # the evidence pipeline to run and flags the gap in the scored output.
        import re as _re
        _tm = _re.search(r"^TABLE:\s+(\w+)", state["schema_context"], _re.MULTILINE)
        fallback_table = _tm.group(1) if _tm else "unknown"
        queries = [
            f'SELECT COUNT(*) AS row_count, \'{h.id} — planner returned no queries; '
            f'this is a diagnostic fallback\' AS _note FROM "{fallback_table}"'
        ]

    for sql in queries:
        # ── Pre-flight: detect unqualified columns that exist in 2+ tables ──
        from hermes.tools.ambiguity import detect_ambiguous_columns
        ambiguity_warnings = detect_ambiguous_columns(sql, state["schema_context"])

        result = conn.execute(h.id, sql)

        # ── Self-correction: retry failed queries once ────────────────────
        if result.error:
            original_error = result.error
            from hermes.semantic.kb_retriever import retrieve_for_fix_sql
            from hermes.tools.error_classifier import classify_sql_error
            kb_fix_patterns = retrieve_for_fix_sql(original_error, sql)
            # Structured diagnosis from known error patterns
            diagnosis = classify_sql_error(original_error, sql, conn.dialect)
            # Append any ambiguity warnings detected before execution
            if ambiguity_warnings:
                warn_text = "\n".join(w.to_prompt_text() for w in ambiguity_warnings)
                diagnosis = f"{diagnosis}\n{warn_text}".strip()
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

            retry = conn.execute(h.id, fix.fixed_sql)

            new_pitfalls.append(Pitfall(
                original_sql=sql,
                error=original_error,
                fixed_sql=fix.fixed_sql,
                fix_explanation=fix.fix_explanation,
                data_quality_issue=fix.data_quality_issue,
                retry_error=retry.error or None,
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
            confidence=0.0,
            verdict="inconclusive",
            key_finding="No queries were executed for this hypothesis.",
            should_continue=False,
        )
    elif all_errored:
        # Every query failed — this is a technical problem, not evidence against the hypothesis
        errors = "; ".join(dict.fromkeys(r.error for r in hyp_results if r.error))
        score = EvidenceScore(
            hypothesis_id=h.id,
            confidence=0.1,
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
        # Apply evidence-depth confidence ceiling (deterministic, post-LLM)
        successful = [r for r in hyp_results if not r.error]
        n_success = len(successful)
        if n_success == 1:
            score = EvidenceScore(**{**score.model_dump(), "confidence": min(score.confidence, 0.60)})
        elif n_success == 2:
            score = EvidenceScore(**{**score.model_dump(), "confidence": min(score.confidence, 0.80)})

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
    query_history = state.get("query_history", [])
    pitfalls = state.get("pitfalls", [])

    # ── Direct mode: all queries failed — skip narrator, return factual error report ──
    if state.get("query_mode") == "direct" and query_history and all(r.error for r in query_history):
        pitfall_by_original = {p.original_sql: p for p in pitfalls}
        pitfall_by_fixed = {p.fixed_sql: p for p in pitfalls}
        dq_notes: list[DataQualityNote] = []
        for r in query_history[:3]:
            p = pitfall_by_fixed.get(r.sql) or pitfall_by_original.get(r.sql)
            if p:
                was_retried = p.retry_error is not None
                issue = (
                    f"Auto-correction attempted but retry also failed.\n"
                    f"Original error: {p.error}\n"
                    f"Retry error: {p.retry_error}"
                ) if was_retried else f"Auto-correction succeeded but a different error occurred: {r.error}"
                fix_hint = p.fix_explanation
            else:
                issue = r.error
                fix_hint = "Review the query and retry the question."
            dq_notes.append(DataQualityNote(
                table="SQL Execution",
                column=None,
                issue=issue,
                impact="No results were retrieved. The question cannot be answered until this is resolved.",
                recommended_fix=fix_hint,
            ))
        return {"report": AnalysisReport(
            headline="Query execution failed",
            verdict="",
            key_findings=[],
            what_is_not_the_cause=[],
            data_quality_notes=dq_notes,
            risks=[],
            recommended_actions=["Try rephrasing the question, or check that the referenced tables and columns exist in the schema."],
        )}

    # ── Consistency check (investigate mode only) ─────────────────────────────
    hypotheses = state.get("hypotheses", [])
    unresolved_tensions: list[str] = list(state.get("unresolved_tensions") or [])
    if _CONSISTENCY_ENABLED and state.get("query_mode") == "investigate" and hypotheses:
        try:
            check: _ConsistencyReport = get_provider("coder").complete(
                system="You are a senior analyst reviewing findings for logical contradictions.",
                user=CONSISTENCY_CHECK_PROMPT.format(
                    hypothesis_summary=_format_hypothesis_summary(hypotheses),
                ),
                response_model=_ConsistencyReport,
            )
            if not check.passed and check.contradictions:
                # Collect human-readable tension descriptions
                for c in check.contradictions:
                    tension = (
                        f"Contradiction on '{c.dimension}': {c.claim_a!r} vs {c.claim_b!r}. "
                        f"Resolution: {c.proposed_resolution}"
                    )
                    unresolved_tensions.append(tension)
                # Downgrade affected hypothesis confidences by 0.30 (floor 0.20)
                affected_ids: set[str] = set()
                for c in check.contradictions:
                    # Find hypotheses whose key_finding contains either claim
                    for h in hypotheses:
                        if (
                            h.key_finding and (
                                c.claim_a[:40].lower() in h.key_finding.lower()
                                or c.claim_b[:40].lower() in h.key_finding.lower()
                            )
                        ):
                            affected_ids.add(h.id)
                if affected_ids:
                    hypotheses = [
                        Hypothesis(
                            id=h.id,
                            description=h.description,
                            confidence=max(h.confidence - 0.30, 0.20) if h.id in affected_ids else h.confidence,
                            verdict=h.verdict,
                            key_finding=h.key_finding,
                        )
                        for h in hypotheses
                    ]
        except Exception:
            pass  # consistency check is best-effort

    human_feedback = state.get("human_feedback") or ""
    feedback_section = (
        f"\nANALYST FEEDBACK (incorporate this before finalising the report):\n{human_feedback}\n"
        if human_feedback else ""
    )
    rules_block = get_rules_block()
    llm = get_provider("narrator")
    tensions_section = ""
    if unresolved_tensions:
        tensions_section = (
            "\nUNRESOLVED CONTRADICTIONS DETECTED (surface these in risks, do not paper over them):\n"
            + "\n".join(f"- {t}" for t in unresolved_tensions)
            + "\n"
        )

    report: AnalysisReport = llm.complete(
        system="You are a senior data analyst writing an executive-level investigation report.",
        user=rules_block + SYNTHESIZE_PROMPT.format(
            question=state["question"],
            hypothesis_summary=_format_hypothesis_summary(hypotheses),
            evidence_log=_format_full_evidence(state.get("query_history", []), hypotheses),
            pitfall_section=_format_pitfalls_for_synthesis(pitfalls),
            human_feedback_section=feedback_section,
        ) + tensions_section,
        response_model=AnalysisReport,
    )
    # ── Override narrator confidence with score_evidence values (deterministic) ─
    # The narrator cannot be trusted to honour evidence-depth ceilings when it
    # writes key findings. Overwrite Finding.confidence with the authoritative
    # score already computed by score_evidence for the same hypothesis.
    scored_conf = {h.id: h.confidence for h in hypotheses}
    if scored_conf:
        corrected_findings = []
        for f in report.key_findings:
            if f.hypothesis_id and f.hypothesis_id in scored_conf:
                corrected_findings.append(
                    Finding(**{**f.model_dump(), "confidence": scored_conf[f.hypothesis_id]})
                )
            else:
                corrected_findings.append(f)
        report = AnalysisReport(**{**report.model_dump(), "key_findings": corrected_findings})

    # ── Post-synthesis numeric verifier ──────────────────────────────────────
    try:
        from hermes.agent.verify import verify_numeric_claims
        unverified = verify_numeric_claims(report, state.get("query_history", []))
        if unverified:
            note = DataQualityNote(
                table="Report Narrative",
                column=None,
                issue=(
                    f"The following numbers in the report could not be verified against "
                    f"executed queries or stats: {', '.join(unverified)}. "
                    f"Treat these claims with caution."
                ),
                impact="Numeric claims without traceable sources reduce report reliability.",
                recommended_fix="Re-run the investigation or verify the numbers manually against the raw data.",
            )
            report = AnalysisReport(
                **{**report.model_dump(), "data_quality_notes": list(report.data_quality_notes) + [note]}
            )
    except Exception:
        pass  # verifier is best-effort — never block the report

    return {"report": report, "unresolved_tensions": unresolved_tensions}


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

def _format_prior_context(history: list[QueryResult], current_hypothesis_id: str = "") -> str:
    """Format recent query history for injection into the planner.
    Labels each entry with its hypothesis so the planner knows which evidence belongs to which hypothesis.
    """
    if not history:
        return ""
    parts = []
    for r in history[-6:]:
        status = f"ERROR: {r.error}" if r.error else f"{r.row_count} rows"
        label = f"[{r.hypothesis_id}]" if r.hypothesis_id != current_hypothesis_id else f"[{r.hypothesis_id} — THIS hypothesis, prior iteration]"
        parts.append(f"{label} {r.sql[:120]}  → {status}")
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


def _format_full_evidence(history: list[QueryResult], hypotheses: list | None = None) -> str:
    """Format query history partitioned by hypothesis so the narrator cannot cross-attribute evidence."""
    if not history:
        return "No queries were executed."
    if not hypotheses:
        return "\n\n---\n\n".join(format_result_for_llm(r) for r in history)

    by_hyp: dict[str, list[QueryResult]] = {}
    for r in history:
        by_hyp.setdefault(r.hypothesis_id, []).append(r)

    parts = []
    for h in hypotheses:
        section_header = f"=== {h.id} EVIDENCE (for hypothesis: {h.description[:100]}) ==="
        hyp_results = by_hyp.get(h.id, [])
        if hyp_results:
            body = "\n\n".join(format_result_for_llm(r) for r in hyp_results)
        else:
            body = "No queries were executed for this hypothesis. Findings must state 'could not be tested'."
        parts.append(f"{section_header}\n{body}")

    # Any results not associated with a known hypothesis
    known_ids = {h.id for h in hypotheses}
    orphans = [r for r in history if r.hypothesis_id not in known_ids]
    if orphans:
        parts.append(
            "=== UNATTRIBUTED QUERIES ===\n"
            + "\n\n".join(format_result_for_llm(r) for r in orphans)
        )

    return "\n\n---\n\n".join(parts)


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
