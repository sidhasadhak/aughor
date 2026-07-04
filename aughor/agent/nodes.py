"""LangGraph node functions — each is a pure function over AgentState."""
from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aughor.db.connection import DatabaseConnection

from aughor.agent.prompts import (
    CONSISTENCY_CHECK_PROMPT,
    DECOMPOSE_PROMPT,
    FIX_SQL_PROMPT,
    PLAN_QUERIES_PROMPT,
    REPLAN_PROMPT,
    ROUTE_QUESTION_PROMPT,
    SCORE_EVIDENCE_PROMPT,
    SYNTHESIZE_PROMPT,
    format_pitfall_section,
)
from aughor.rules import get_rules_block
from aughor.agent.state import (
    AgentState,
    AnalysisReport,
    DataQualityNote,
    DecomposeOutput,
    EvidenceScore,
    Finding,
    Hypothesis,
    Pitfall,
    QueryPlanV2,
    QueryResult,
    ReplanDecision,
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

_CONSISTENCY_ENABLED = __import__("os").getenv("AUGHOR_CONSISTENCY_CHECK", "true").lower() != "false"
from aughor.llm.provider import get_provider
from aughor.tools.executor import format_result_for_llm
from aughor.tools.stats import analyze_query_result
from aughor import telemetry as _telemetry

MAX_ITER = int(__import__("os").getenv("AUGHOR_MAX_ITER", "6"))


# A DRIVER / RELATIONSHIP question ("do late deliveries lower reviews", "is there a correlation
# between order value and review score") is answered fastest and most consistently by the
# investigate path's cross-sectional comparison — segment the metric across the condition (the Q4
# comparison_segment route, ~30s) — NOT a multi-step explore decomposition that can take 5× longer
# for the same answer. We force investigate when the LLM routed such a question to explore. Precise:
# matches "correlation/relationship between", "correlate with", "do/does X <impact-verb> Y" — and
# NOT compound conditionals ("countries where acquisition grows but revenue/customer falls").
_DRIVER_RELATIONSHIP_RE = re.compile(
    r"\b(?:relationship|correlat\w+|association)\b.{0,30}\bbetween\b"
    r"|\bcorrelate[ds]?\b.{0,20}\bwith\b"
    r"|\b(?:do|does|did)\b.{0,60}\b(?:affect|affects|lower|lowers|raise|raises|drive|drives|driven|"
    r"hurt|hurts|improve|improves|increase|increases|reduce|reduces|impact|impacts|influence|"
    r"influences|lead\s+to|leads\s+to|result\s+in)\b"
    r"|\b(?:do|does|did)\b.{0,70}\b(?:chance|likelihood|probability|odds)\b",
    re.IGNORECASE,
)


# ── Node: route_question ─────────────────────────────────────────────────────

def classify_question(question: str) -> tuple[str, RouteDecision]:
    """Pure classifier — calls LLM and returns (effective_mode, decision).

    Separated from route_question so it can be called and tested independently
    without constructing a full AgentState.
    Low-confidence direct falls back to investigate: false-direct (shallow
    answer) is worse than false-investigate (extra thoroughness).

    MindsDB-style final_text path: if the question is definitional/ontological
    and the KB has a strong match, route to final_text without generating SQL.
    """
    # Cost-tiered routing (test-time scaling): a deterministic complexity assessment
    # picks the inference role — a simple question is classified by the cheap "fast"
    # model, a harder one by the frontier "coder" model (it never downgrades a hard
    # question). See docs/NL2SQL_WINNING_FORMULA_2026.md.
    from aughor.agent.complexity import assess_complexity, model_role_for
    _verdict = assess_complexity(question)
    llm = get_provider(model_role_for(_verdict))
    decision: RouteDecision = llm.complete(
        system="You are a routing classifier for a business intelligence agent. Classify questions precisely.",
        user=ROUTE_QUESTION_PROMPT.format(question=question),
        response_model=RouteDecision,
    )
    effective_mode = decision.mode if decision.confidence >= 0.65 else "investigate"

    # Driver/relationship questions go to investigate (fast cross-sectional comparison), not the
    # slower explore decomposition — consistent routing for the same question shape.
    if effective_mode == "explore" and _DRIVER_RELATIONSHIP_RE.search(question or ""):
        decision.mode = "investigate"
        effective_mode = "investigate"

    # Final-text path: definitional questions that the KB can answer without SQL
    if effective_mode == "direct":
        definitional = re.search(
            r"^(what is|what are|what does|define|explain|meaning of)",
            question,
            re.IGNORECASE,
        )
        if definitional:
            try:
                from aughor.semantic.kb_retriever import has_strong_kb_match
                if has_strong_kb_match(question, threshold=0.75, top_k=3):
                    decision.mode = "final_text"
                    effective_mode = "final_text"
            except Exception:
                pass

    # P5 declarative modes: apply file-driven route overrides from mode manifests.
    # No-op unless AUGHOR_DECLARATIVE_MODES is on (so the default path is unchanged);
    # when on, a manifest's route_keywords can retune routing without a code change.
    try:
        from aughor.agent.modes import apply_route_overrides
        effective_mode, decision = apply_route_overrides(question, effective_mode, decision)
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "declarative-mode route override is best-effort; keep the code route",
                 counter="modes.route_override")
    return effective_mode, decision


@_telemetry.node_span("route_question")
def route_question(state: AgentState) -> dict[str, Any]:
    effective_mode, decision = classify_question(state["question"])
    # Carry the deterministic complexity verdict into the run state (and a stats
    # counter) so the cost tier we routed to is observable on the receipt / fleet view.
    from aughor.agent.complexity import assess_complexity
    _v = assess_complexity(state["question"])
    try:
        from aughor.stats import stats as _st
        _st.inc(f"route.tier.{_v.tier}")
    except Exception:
        pass
    base = {"route_reasoning": decision.reasoning, "route_confidence": decision.confidence,
            "route_complexity_tier": _v.tier, "route_complexity_score": _v.score,
            "route_ambiguous": _v.ambiguous}
    if effective_mode == "direct":
        return {
            **base,
            "query_mode": "direct",
            "hypotheses": [Hypothesis(id="direct", description=state["question"], confidence=0.0, verdict="untested")],
            "current_hypothesis_idx": 0,
            "iteration": 0,
            "pitfalls": [],
            # Preserve any origin seed (a drill or a follow-up base) — route_question
            # runs first, so there are no stale priors to clear, and the direct/explore
            # branches read prior_analyses to compose on that base (REC follow-up).
            "prior_analyses": state.get("prior_analyses") or [],
        }
    if effective_mode == "final_text":
        return {
            **base,
            "query_mode": "final_text",
            "hypotheses": [],
            "current_hypothesis_idx": 0,
            "iteration": 0,
            "pitfalls": [],
            # Preserve any origin seed (a drill or a follow-up base) — route_question
            # runs first, so there are no stale priors to clear, and the direct/explore
            # branches read prior_analyses to compose on that base (REC follow-up).
            "prior_analyses": state.get("prior_analyses") or [],
        }
    if effective_mode == "explore":
        return {
            **base,
            "query_mode": "explore",
            "sub_questions": [],
            "current_subq_idx": 0,
            "subq_answers": [],
            "explore_report": None,
            "pitfalls": [],
            # Preserve any origin seed (a drill or a follow-up base) — route_question
            # runs first, so there are no stale priors to clear, and the direct/explore
            # branches read prior_analyses to compose on that base (REC follow-up).
            "prior_analyses": state.get("prior_analyses") or [],
        }
    return {**base, "query_mode": "investigate"}


def route_after_classify(state: AgentState) -> str:
    mode = state.get("query_mode")
    if mode == "direct":
        return "plan_queries"
    if mode == "final_text":
        return "answer_text_only"
    if mode == "explore":
        return "exploratory_scan_explore"
    return "exploratory_scan"



# ── Node: answer_text_only ─────────────────────────────────────────────────
# MindsDB-style final_text path: answer definitional/ontological questions
# from the KB without generating SQL.

def answer_text_only(state: AgentState) -> dict[str, Any]:
    """Compose a natural-language answer from KB, connection KB, and playbook.

    No database connection needed. Returns a headline + findings report.
    """
    question = state["question"]
    conn_id = state.get("connection_id") or ""

    snippets: list[str] = []

    # 1. Global KB
    try:
        from aughor.semantic.kb_retriever import retrieve_for_planning
        kb = retrieve_for_planning(question, top_k=3)
        if kb:
            snippets.append(kb)
    except Exception:
        pass

    # 2. Connection-specific KB
    try:
        from aughor.semantic.connection_kb import retrieve_for_question as _conn_kb
        ckb = _conn_kb(question, conn_id)
        if ckb:
            snippets.append(ckb)
    except Exception:
        pass

    # 3. Playbook
    try:
        from aughor.playbook.retriever import retrieve_for_metric_and_phases
        pb_entries = retrieve_for_metric_and_phases([question], limit=3)
        if pb_entries:
            for e in pb_entries:
                if e.get("recommendation"):
                    snippets.append(e["recommendation"])
    except Exception:
        pass

    answer = " ".join(snippets).strip()
    if not answer:
        answer = (
            f"I don\'t have a stored definition for '{question}'. "
            "Try rephrasing as a data query (e.g. 'Show me...')."
        )

    return {
        "final_text_answer": answer,
        "query_mode": "final_text",
        "report": {
            "headline": answer,
            "verdict": "",
            "key_findings": [],
            "what_is_not_the_cause": [],
            "data_quality_notes": [],
            "risks": [],
            "recommended_actions": [],
        },
    }

# ── Node: exploratory_scan ────────────────────────────────────────────────────

def exploratory_scan(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    """
    Produce a DATA PORTRAIT for the decomposer.

    Fast path (Sprint 1+): if profiles are already cached (built at connection time),
    render the portrait directly from the profile cache — zero SQL queries.

    Fallback: if profiles are not available (cold start, profiler disabled, etc.),
    fall back to the original ad-hoc SQL approach.

    Results are NOT added to query_history — they exist only as formatted text.
    """
    # ── Fast path: read from profile cache ────────────────────────────────────
    try:
        from aughor.tools.profile_cache import get_or_build_profiles
        from aughor.tools.profiler import render_profile_annotations
        from aughor.tools.schema import parse_schema_tables, compute_join_map

        schema_str = state["schema_context"]
        table_cols_map = parse_schema_tables(schema_str)
        tables = list(table_cols_map.keys())

        if tables:
            jmap = compute_join_map(table_cols_map)
            fk_hints: dict[str, set[str]] = {t: set() for t in tables}
            for j in jmap.get("joins", []):
                fk_hints.setdefault(j["t1"], set()).add(j["c1"])
                fk_hints.setdefault(j["t2"], set()).add(j["c2"])

            conn_id = state.get("connection_id") or getattr(conn, "_connection_id", "") or "fixture"
            tp, cp = get_or_build_profiles(conn, conn_id, tables, fk_hints)

            if tp:
                portrait = (
                    "DATA PORTRAIT — actual counts and distributions (from profile cache):\n"
                    "Hypotheses must be grounded in what the data can plausibly show.\n\n"
                    + render_profile_annotations(tp, cp)
                )
                # Compute overall data date range from table profiles
                all_date_ranges = [p.date_range for p in tp.values() if p.date_range]
                data_range = (
                    (min(d[0] for d in all_date_ranges), max(d[1] for d in all_date_ranges))
                    if all_date_ranges else None
                )
                events_ctx = _get_events_context(state["question"], conn, data_range)
                return {"scan_context": portrait, "events_context": events_ctx}
    except Exception:
        pass  # fall through to ad-hoc SQL

    # ── Fallback: ad-hoc SQL recon ────────────────────────────────────────────
    from aughor.tools.schema import SECTION_STOP

    schema_str = state["schema_context"]
    table_col_types: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line in schema_str.splitlines():
        if SECTION_STOP.match(line):
            current = None
            continue
        m = re.match(r"^TABLE:\s+([\w.]+)", line)
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
    # Track the overall data date range found across all tables (for events scoping)
    _all_min_dates: list[str] = []
    _all_max_dates: list[str] = []

    for table, col_type_pairs in list(table_col_types.items())[:4]:
        date_cols = [c for c, t in col_type_pairs if _is_date(t)]
        num_cols  = [c for c, t in col_type_pairs if _is_numeric(t)]
        cat_cols  = [c for c, t in col_type_pairs if _is_text(t) and not c.lower().endswith("_id")]

        lines: list[str] = [f"TABLE: {table}"]

        if date_cols:
            dc = _q(date_cols[0])
            r = conn.execute("scan", f'SELECT COUNT(*) AS n, MIN({dc})::VARCHAR, MAX({dc})::VARCHAR FROM {_q(table)}')
            if not r.error and r.rows:
                n, min_d, max_d = r.rows[0]
                lines.append(f"  {int(n):,} rows | {date_cols[0]}: {min_d} → {max_d}")
                # Capture for events window
                if min_d:
                    _all_min_dates.append(str(min_d))
                if max_d:
                    _all_max_dates.append(str(max_d))
        else:
            r = conn.execute("scan", f'SELECT COUNT(*) AS n FROM {_q(table)}')
            if not r.error and r.rows:
                lines.append(f"  {int(r.rows[0][0]):,} rows")

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

        for cc in cat_cols[:2]:
            r = conn.execute("scan", f'SELECT {_q(cc)}, COUNT(*) AS n FROM {_q(table)} GROUP BY 1 ORDER BY 2 DESC LIMIT 8')
            if not r.error and r.rows:
                vals = ", ".join(f"{row[0]}({row[1]})" for row in r.rows)
                lines.append(f"  {cc}: {vals}")

        portrait_parts.append("\n".join(lines))

    # Build data date range from what we found in the portrait queries
    fallback_data_range = (
        (min(_all_min_dates), max(_all_max_dates))
        if _all_min_dates and _all_max_dates else None
    )

    if not portrait_parts:
        events_ctx = _get_events_context(state["question"], conn, fallback_data_range)
        return {"scan_context": "", "events_context": events_ctx}

    from aughor.util.prompt_safety import UNTRUSTED_DATA_NOTE, fence_untrusted
    portrait = (
        "DATA PORTRAIT — run this before forming any hypothesis:\n"
        "These are actual counts and distributions from the database. "
        "Hypotheses must be grounded in what the data can plausibly show.\n"
        # SEC-03: the values below are untrusted DB content — fence them so they
        # can't be read as instructions, and neutralize any delimiter break-out.
        + UNTRUSTED_DATA_NOTE + "\n\n"
        + fence_untrusted("\n\n".join(portrait_parts), max_chars=12000)
    )
    events_ctx = _get_events_context(state["question"], conn, fallback_data_range)
    return {"scan_context": portrait, "events_context": events_ctx}


# ── Node: decompose_question ─────────────────────────────────────────────────

@_telemetry.node_span("decompose")
def decompose_question(state: AgentState) -> dict[str, Any]:
    from aughor.tools.prior_analyses import search_prior_investigations
    from aughor.semantic.kb_retriever import retrieve_for_decompose
    from aughor.stats import stats as _decomp_stats
    prior_analyses = search_prior_investigations(state["question"], connection_id=state.get("connection_id", ""))
    if prior_analyses:
        _decomp_stats.inc("rag_hits")
    else:
        _decomp_stats.inc("rag_misses")
    kb_domain = retrieve_for_decompose(state["question"])

    scan_context = state.get("scan_context") or ""
    scan_section = (
        f"STEP 1.5 — STUDY THE DATA PORTRAIT before forming hypotheses:\n{scan_context}\n"
        if scan_context else ""
    )

    # Inject exploration findings (null semantics, lifecycles, cross-table insights)
    exploration_section = ""
    try:
        from aughor.explorer.store import render_exploration_annotations
        _ea = render_exploration_annotations(state.get("connection_id", ""))
        if _ea:
            exploration_section = f"EXPLORATION FINDINGS (background schema analysis):\n{_ea}\n\n"
    except Exception:
        pass

    rules_block = get_rules_block()
    llm = get_provider("coder")
    output: DecomposeOutput = llm.complete(
        system="You are a senior data analyst. Decompose the question into testable hypotheses.",
        user=rules_block + exploration_section + DECOMPOSE_PROMPT.format(
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
        # Preserve any seeded prior analyses (e.g. a Finding Dossier handed in for a
        # "deeper" drill) ahead of the RAG-retrieved ones; default seed is [].
        "prior_analyses": list(state.get("prior_analyses") or []) + prior_analyses,
    }


# ── Node: plan_queries ────────────────────────────────────────────────────────

@_telemetry.node_span("plan_queries")
def plan_queries(state: AgentState) -> dict[str, Any]:
    """LLM planning call — decides WHAT to measure, produces QueryPlanV2 (no SQL)."""
    hypotheses = state["hypotheses"]
    idx = state["current_hypothesis_idx"]

    if idx >= len(hypotheses):
        return {}

    h = hypotheses[idx]
    prior_context = _format_prior_context(state.get("query_history", []), h.id)
    known_pitfalls = state.get("pitfalls", [])

    from aughor.semantic.retriever import retrieve_relevant_schema
    from aughor.semantic.kb_retriever import retrieve_for_planning
    schema_for_hypothesis = retrieve_relevant_schema(h.description, state["schema_context"])
    kb_patterns = retrieve_for_planning(h.description)

    prior_analyses = state.get("prior_analyses", [])
    prior_analyses_text = (
        "RELEVANT PAST INVESTIGATIONS:\n" + "\n\n".join(prior_analyses)
        if prior_analyses else ""
    )

    raw_events = state.get("events_context") or ""
    events_section = f"{raw_events}\n" if raw_events else ""

    # Inject causal context from prior verified investigations
    causal_section = ""
    try:
        from aughor.process.causal import build_causal_context_section
        _cc = build_causal_context_section(h.description, conn_id=state.get("connection_id"))
        if _cc:
            causal_section = _cc + "\n"
    except Exception:
        pass

    # P1 close-the-loop: read past human corrections for this database BACK into planning,
    # so a mistake a reviewer already flagged is not planned again. Empty (zero-cost) when
    # nothing relevant is stored or the flag is off, so the default path is unchanged.
    priors_section = ""
    priors_fired = False
    try:
        from aughor.verify.priors import build_corrections_section
        priors_section = build_corrections_section(state.get("question") or h.description,
                                                   state.get("connection_id") or "")
        priors_fired = bool(priors_section)
    except Exception:
        pass

    rules_block = get_rules_block()
    llm = get_provider("coder")
    plan: QueryPlanV2 = llm.complete(
        system="You are a senior data analyst planning how to test a hypothesis. Do NOT write SQL.",
        user=rules_block + causal_section + priors_section + PLAN_QUERIES_PROMPT.format(
            hypothesis_id=h.id,
            hypothesis_description=h.description,
            schema=schema_for_hypothesis,
            prior_context=prior_context or "None yet.",
            prior_analyses_section=prior_analyses_text,
            pitfall_section=format_pitfall_section(known_pitfalls),
            kb_patterns_section=kb_patterns,
            events_section=events_section,
        ),
        response_model=QueryPlanV2,
    )

    out: dict[str, Any] = {"current_plan": plan.model_dump()}
    if priors_fired:
        # Liveness (Bet 0): prove the prior actually reached the planner, so a silent
        # no-op can't masquerade as "closed loop enabled".
        out["verification_checks"] = ["priors_injected"]
    return out


# ── Node: execute_planned_queries ─────────────────────────────────────────────

@_telemetry.node_span("execute_planned_queries")
def execute_planned_queries(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    """Translates each QueryIntent from current_plan into SQL, then executes with self-correction."""
    hypotheses = state["hypotheses"]
    idx = state["current_hypothesis_idx"]

    if idx >= len(hypotheses):
        return {}

    h = hypotheses[idx]
    plan_dict = state.get("current_plan") or {}

    # Retrieve validated SQL examples for the SQL-writing step
    from aughor.tools.prior_analyses import search_sql_examples
    connection_id = state.get("connection_id", "")
    sql_examples_section = search_sql_examples(h.description, connection_id)

    # Build ontology context for SQL generation + action expansion
    from aughor.ontology.actions import build_actions_prompt_section, expand_actions
    from aughor.stats import stats as _stats
    ontology_graph = conn.get_ontology()
    ontology_actions_section = build_actions_prompt_section(ontology_graph)

    known_pitfalls = state.get("pitfalls", [])
    pitfall_section = format_pitfall_section(known_pitfalls)

    intents = plan_dict.get("query_intents") or []
    expected_if_true = plan_dict.get("expected_if_true") or None
    expected_if_false = plan_dict.get("expected_if_false") or None

    # Generate SQL for each query intent — parallelized (LLM calls are independent HTTP requests).
    # Context-propagating pool so per-run metering reaches these LLM calls.
    from aughor.kernel.concurrency import ContextThreadPoolExecutor as _ThreadPool

    llm = get_provider("coder")
    _schema_ctx = state["schema_context"]
    _dialect = conn.dialect

    # R8: when in-SQL AI columns are enabled, teach the generator the governed prompt()/embedding()
    # operators exist (conservative — text-only, row-bounded). No-op + zero prompt cost when off.
    try:
        from aughor.semops.ai_sql import ai_sql_enabled, ai_sql_operator_hint
        if ai_sql_enabled():
            _schema_ctx = _schema_ctx + "\n\n" + ai_sql_operator_hint()
    except Exception as _exc:
        from aughor.kernel.errors import tolerate
        tolerate(_exc, "ai-sql generator hint is best-effort", counter="ai_sql.hint")

    # Build ontology formula injection section — if the hypothesis/intent mentions
    # a known metric name, inject its approved formula_sql so the LLM can't hallucinate it.
    _ontology_formulas_section = ""
    _targeted_metrics: list = []   # governed metrics this hypothesis targets (B-7 gate)
    try:
        from aughor.semantic.metrics import list_metrics as _list_metrics
        all_metrics = _list_metrics()
        hyp_lower = h.description.lower()
        matched_formulas: list[str] = []
        for m in all_metrics:
            label_lower = m.label.lower()
            name_lower = m.name.lower()
            if any(token in hyp_lower for token in [name_lower, label_lower] if len(token) > 3):
                _targeted_metrics.append(m)
                formula_line = f"  {m.label} ({m.name}): {m.sql}"
                if m.caveats:
                    formula_line += f"  — NOTE: {m.caveats}"
                if m.wrong_usage_examples:
                    formula_line += f"  — NEVER: {'; '.join(m.wrong_usage_examples[:2])}"
                matched_formulas.append(formula_line)
        if matched_formulas:
            _ontology_formulas_section = (
                "\nAPPROVED METRIC FORMULAS (use these exact SQL expressions — do NOT re-derive):\n"
                + "\n".join(matched_formulas[:8])
                + "\n"
            )
    except Exception:
        pass

    def _gen_sql(intent: dict) -> str | None:
        intent_tables = ", ".join(intent.get("tables") or []) or "(all plan tables)"
        intent_filters = "; ".join(intent.get("filters") or []) or "none"
        intent_aggregation = intent.get("aggregation") or "none"
        # Per-intent: also try to match the intent description against metrics
        intent_formula_section = _ontology_formulas_section
        try:
            if not intent_formula_section:
                from aughor.semantic.metrics import list_metrics as _lm2
                intent_lower = intent.get("description", "").lower()
                for m in _lm2():
                    if m.name in intent_lower or m.label.lower() in intent_lower:
                        intent_formula_section = (
                            f"\nAPPROVED FORMULA: {m.label} = {m.sql}"
                            + (f"  — NOTE: {m.caveats}" if m.caveats else "")
                            + "\n"
                        )
                        break
        except Exception:
            pass
        def _write(extra: str = "") -> str | None:
            # One WRITE_SQL_PROMPT call site — delegate to the shared NL→SQL generator that the
            # Capability plane also uses (AL-02 convergence). Same prompt, same `coder` provider;
            # its internal fail-open now goes through tolerate() instead of a silent except-pass.
            from aughor.capability.sql_generate import generate_sql
            return generate_sql(
                h.description, schema_text=_schema_ctx, dialect=_dialect,
                intent_description=intent.get("description", ""),
                intent_tables=intent_tables, intent_filters=intent_filters,
                intent_aggregation=intent_aggregation,
                pitfall_section=pitfall_section, sql_examples_section=sql_examples_section,
                ontology_actions_section=ontology_actions_section + intent_formula_section + extra,
                provider=llm,
            ) or None

        sql = _write()
        # B-7 hard gate — if the SQL drifted from a governed formula this hypothesis
        # targets, regenerate ONCE with a pointed corrective directive naming the exact
        # formula + the wrong form. `enforce_gate` keeps the rewrite only if it reduces
        # drift, so it never replaces a query with a worse one.
        if sql and _targeted_metrics:
            try:
                from aughor.semantic.enforcement import enforce_gate
                _qtext = f"{h.description} {intent.get('description', '')}"
                sql = enforce_gate(_qtext, sql, _targeted_metrics, _write)
            except Exception:
                pass
        return sql

    if len(intents) > 1:
        with _ThreadPool(max_workers=len(intents)) as pool:
            raw = list(pool.map(_gen_sql, intents))
    else:
        raw = [_gen_sql(intents[0])] if intents else []

    queries: list[str] = [s for s in raw if s]
    # Initialised before the consistency block below — that block appends alias/join
    # divergence pitfalls, so `new_pitfalls` must already exist (was previously declared
    # further down, raising UnboundLocalError whenever a divergence note fired).
    new_pitfalls: list[Pitfall] = []

    # ── Cross-query consistency: normalize date functions, detect alias drift ─
    if queries:
        from aughor.tools.sql_consistency import normalize_parallel_queries
        queries, consistency_notes = normalize_parallel_queries(queries, conn.dialect)
        for cn in consistency_notes:
            if cn.kind in ("alias_mismatch", "join_divergence"):
                # Inject alias/join divergence as a pitfall so the synthesizer
                # knows these queries may have column-alignment issues.
                new_pitfalls.append(Pitfall(
                    original_sql=" | ".join(queries[i] for i in cn.query_indices if i < len(queries))[:200],
                    error=cn.to_prompt_text(),
                    fixed_sql="",
                    fix_explanation=cn.to_prompt_text(),
                ))

    # Expand ACTION:name() tokens before execution
    queries, _action_notes = expand_actions(queries, ontology_graph)
    if _action_notes:
        _stats.inc("action_expansions", len(_action_notes))

    # Fallback: if no queries were generated, run a diagnostic count
    if not queries:
        import re as _re
        _tm = _re.search(r"^TABLE:\s+([\w.]+)", state["schema_context"], _re.MULTILINE)
        fallback_table = _tm.group(1) if _tm else "unknown"
        queries = [
            f'SELECT COUNT(*) AS row_count, \'{h.id} — planner returned no query intents; '
            f'this is a diagnostic fallback\' AS _note FROM "{fallback_table}"'
        ]

    results: list[QueryResult] = []
    # (new_pitfalls initialised above, before the consistency block)

    for sql in queries:
        # ── Pre-flight: detect unqualified columns and invalid join paths ──
        from aughor.tools.ambiguity import detect_ambiguous_columns, detect_invalid_joins
        from aughor.tools.semantic_validator import check_entity_column_alignment
        ambiguity_warnings = detect_ambiguous_columns(sql, state["schema_context"])
        join_warnings = detect_invalid_joins(sql, state["schema_context"])
        # ── Value-domain join guard: catch joins whose key values don't overlap ─
        # Kept separate from name-based join_warnings: domain mismatches are
        # empirically grounded (0% sampled overlap) and strong enough to drive a
        # regeneration even when the query executes cleanly.
        from aughor.sql.join_guard import check_join_value_domains
        domain_warnings = check_join_value_domains(conn, sql)
        # ── Semantic column alignment: catch wrong identifier columns ─────────
        semantic_warnings = check_entity_column_alignment(
            state["question"], sql, state["schema_context"]
        )
        for sw in semantic_warnings:
            new_pitfalls.append(Pitfall(
                original_sql=sql,
                error=sw.to_prompt_text(),
                fixed_sql=sql,
                fix_explanation=sw.to_prompt_text(),
            ))

        for jw in join_warnings:
            new_pitfalls.append(Pitfall(
                original_sql=sql,
                error=jw.to_prompt_text(),
                fixed_sql=sql,
                fix_explanation=jw.to_prompt_text(),
            ))

        result = conn.execute(h.id, sql)
        # Attach plan-time predictions so the scorer can compare prediction vs reality
        _d = result.model_dump()
        _d["expected_if_true"] = expected_if_true
        _d["expected_if_false"] = expected_if_false
        result = QueryResult(**_d)

        # ── Self-correction: retry failed queries once ────────────────────
        if result.error:
            original_error = result.error
            _stats.inc("sql_correction_retries")
            from aughor.semantic.kb_retriever import retrieve_for_fix_sql
            from aughor.tools.error_classifier import classify_sql_error, classify_error_type, error_class_guidance
            kb_fix_patterns = retrieve_for_fix_sql(original_error, sql)
            diagnosis = classify_sql_error(original_error, sql, conn.dialect)
            _g = error_class_guidance(classify_error_type(original_error, sql, conn.dialect))  # R3: route by type
            if _g:
                diagnosis = f"ERROR CLASS — {_g}\n{diagnosis}".strip()
            pre_flight = ambiguity_warnings + join_warnings + domain_warnings + semantic_warnings
            if pre_flight:
                warn_text = "\n".join(w.to_prompt_text() for w in pre_flight)
                diagnosis = f"{diagnosis}\n{warn_text}".strip()
            error_diagnosis_block = f"DIAGNOSIS:\n{diagnosis}\n" if diagnosis else ""

            # Inject metrics catalog so fix knows approved formulas
            _fix_metrics = ""
            try:
                from aughor.semantic.metrics import build_metrics_block
                _fix_metrics = build_metrics_block()
                if _fix_metrics:
                    _fix_metrics += "\n"
            except Exception:
                pass

            fix: SQLFix = get_provider("coder").complete(
                system="You are a SQL expert. Fix the broken query.",
                user=FIX_SQL_PROMPT.format(
                    dialect=conn.dialect,
                    sql=sql,
                    error=original_error,
                    error_diagnosis=error_diagnosis_block,
                    schema=state["schema_context"],
                    kb_patterns_section=kb_fix_patterns,
                    metrics_section=_fix_metrics,
                ),
                response_model=SQLFix,
            )

            retry = conn.execute(h.id, fix.fixed_sql)
            if not retry.error:
                _stats.inc("sql_correction_successes")

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
        elif domain_warnings:
            # Query executed cleanly but joins on value-disjoint keys → the result
            # is unreliable. Regenerate ONCE with the mismatch as the diagnosis;
            # adopt the rewrite only if it executes clean AND clears the mismatch
            # (never replace a query with one that still has a disjoint join).
            _stats.inc("join_domain_repairs")
            warn_text = "\n".join(w.to_prompt_text() for w in domain_warnings)
            try:
                fix: SQLFix = get_provider("coder").complete(
                    system="You are a SQL expert. Fix the broken query.",
                    user=FIX_SQL_PROMPT.format(
                        dialect=conn.dialect,
                        sql=sql,
                        error="A join is on value-disjoint columns — the result is unreliable.",
                        error_diagnosis=f"DIAGNOSIS:\n{warn_text}\n",
                        schema=state["schema_context"],
                        kb_patterns_section="",
                        metrics_section="",
                    ),
                    response_model=SQLFix,
                )
                retry = conn.execute(h.id, fix.fixed_sql)
                retry_domain = check_join_value_domains(conn, fix.fixed_sql)
                if not retry.error and not retry_domain:
                    _stats.inc("join_domain_repair_successes")
                    new_pitfalls.append(Pitfall(
                        original_sql=sql,
                        error=warn_text,
                        fixed_sql=fix.fixed_sql,
                        fix_explanation=fix.fix_explanation,
                        data_quality_issue=fix.data_quality_issue,
                    ))
                    result = _attach_stats(retry)
                else:
                    # Regeneration didn't clear it — keep the original result but
                    # carry the warning forward as a data-quality pitfall so the
                    # narrator flags the join rather than reporting a clean number.
                    new_pitfalls.append(Pitfall(
                        original_sql=sql,
                        error=warn_text,
                        fixed_sql=sql,
                        fix_explanation=warn_text,
                        data_quality_issue=warn_text,
                    ))
                    result = _attach_stats(result)
            except Exception as _exc:
                from aughor.kernel.errors import tolerate
                tolerate(_exc, "join-domain repair best-effort; original result kept",
                         counter="join_guard.repair_error")
                result = _attach_stats(result)
            results.append(result)
        else:
            results.append(_attach_stats(result))

    return {
        "query_history": results,   # operator.add appends
        "pitfalls": new_pitfalls,   # operator.add appends
    }


# kept for backward-compatibility with any external callers; delegates to plan_queries + execute_planned_queries
def plan_and_execute(state: AgentState, conn: "DatabaseConnection") -> dict[str, Any]:
    plan_state = plan_queries(state)
    merged = {**state, **plan_state}
    return execute_planned_queries(merged, conn)


# ── Node: score_evidence ──────────────────────────────────────────────────────

@_telemetry.node_span("score_evidence")
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

        # Build predictions section from plan-time annotations (first result carries them)
        _first = hyp_results[0]
        if _first.expected_if_true or _first.expected_if_false:
            predictions_section = (
                f"IF TRUE:  {_first.expected_if_true or '(not specified)'}\n"
                f"IF FALSE: {_first.expected_if_false or '(not specified)'}"
            )
        else:
            predictions_section = "(No predictions were recorded for this hypothesis — score on evidence alone.)"

        score = get_provider("coder").complete(
            system="You are a senior data analyst evaluating evidence for a hypothesis.",
            user=SCORE_EVIDENCE_PROMPT.format(
                hypothesis_id=h.id,
                hypothesis_description=h.description,
                predictions_section=predictions_section,
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

@_telemetry.node_span("synthesize_report")
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

    # ── Metric divergence check (deterministic, ontology-based) ──────────────
    try:
        from aughor.ontology.divergence import check_metric_consistency
        from aughor.ontology.store import load_latest_ontology
        connection_id = state.get("connection_id") or "fixture"
        ontology = load_latest_ontology(connection_id)
        if ontology:
            metric_warnings = check_metric_consistency(
                hypotheses, state.get("query_history", []), ontology
            )
            unresolved_tensions.extend(metric_warnings)
    except Exception:
        pass  # divergence check is best-effort

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

    raw_events = state.get("events_context") or ""
    events_section_synth = f"\nBUSINESS CALENDAR CONTEXT (use to attribute anomalies to known events):\n{raw_events}\n" if raw_events else ""

    # ── Pre-synthesis numeric guard: build a verified-numbers block so the narrator
    # can only cite figures that actually appear in the query results.
    pre_check_section = ""
    try:
        from aughor.agent.verify import build_pre_synthesis_number_check
        pre_check_section = build_pre_synthesis_number_check(state.get("query_history", []))
    except Exception:
        pass

    report: AnalysisReport = llm.complete(
        system="You are a senior data analyst writing an executive-level investigation report.",
        user=rules_block + SYNTHESIZE_PROMPT.format(
            question=state["question"],
            hypothesis_summary=_format_hypothesis_summary(hypotheses),
            evidence_log=_format_full_evidence(state.get("query_history", []), hypotheses),
            pitfall_section=_format_pitfalls_for_synthesis(pitfalls),
            human_feedback_section=feedback_section,
            events_section=events_section_synth,
        ) + tensions_section + pre_check_section,
        response_model=AnalysisReport,
    )
    # ── Override narrator confidence with score_evidence values (deterministic) ─
    # The narrator cannot be trusted to honour evidence-depth ceilings when it
    # writes key findings. Overwrite Finding.confidence with the authoritative
    # score already computed by score_evidence for the same hypothesis.
    scored_conf = {h.id: h.confidence for h in hypotheses}
    if scored_conf:
        # Safety: when a Finding claims a hypothesis_id that doesn't exist in
        # the scored set, the narrator invented or abbreviated an ID.  Fall back
        # to the *lowest* scored confidence so we never over-state certainty.
        min_scored_conf = min(scored_conf.values()) if scored_conf else 0.3
        unmatched_ids: list[str] = []
        corrected_findings = []
        for f in report.key_findings:
            if f.hypothesis_id and f.hypothesis_id in scored_conf:
                corrected_findings.append(
                    Finding(**{**f.model_dump(), "confidence": scored_conf[f.hypothesis_id]})
                )
            elif f.hypothesis_id and f.hypothesis_id not in scored_conf:
                # ID mismatch — apply floor confidence
                unmatched_ids.append(f.hypothesis_id)
                corrected_findings.append(
                    Finding(**{**f.model_dump(), "confidence": min_scored_conf})
                )
            else:
                corrected_findings.append(f)
        report = AnalysisReport(**{**report.model_dump(), "key_findings": corrected_findings})
        if unmatched_ids:
            # Surface the mismatch as a data quality note so analysts see it
            id_note = DataQualityNote(
                table="Report Structure",
                column=None,
                issue=(
                    f"Finding(s) referenced unrecognised hypothesis IDs: "
                    f"{', '.join(unmatched_ids)}. "
                    f"Expected: {', '.join(scored_conf.keys())}. "
                    f"Confidence floored to {min_scored_conf:.0%} for affected findings."
                ),
                impact="Confidence scores for these findings may be unreliable.",
                recommended_fix="Re-run the investigation to regenerate findings with correct hypothesis IDs.",
            )
            report = AnalysisReport(
                **{**report.model_dump(), "data_quality_notes": list(report.data_quality_notes) + [id_note]}
            )

    # ── Post-synthesis verifiers (numeric grounding + narration inversion) ────
    try:
        from aughor.agent.verify import verify_numeric_claims, verify_universal_claims
        _qh = state.get("query_history", [])
        unverified = verify_numeric_claims(report, _qh)
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
        # A finding that asserts a per-group value as UNIVERSAL ("all orders have 3
        # items") while the result is a varying distribution — caveat, never drop a
        # whole report over one over-generalised sentence.
        inversions = verify_universal_claims(report, _qh)
        if inversions:
            inv_note = DataQualityNote(
                table="Report Narrative",
                column=None,
                issue=(
                    "A claim states a value as universal that the data shows varies: "
                    + "; ".join(inversions) + ". Read it as a per-group value, not 'every' entity."
                ),
                impact="Over-generalising a per-group value misrepresents the distribution.",
                recommended_fix="State the range or the per-group split instead of a single universal value.",
            )
            report = AnalysisReport(
                **{**report.model_dump(), "data_quality_notes": list(report.data_quality_notes) + [inv_note]}
            )
        # Measure-grain misuse: a query that summed a measure at the wrong grain
        # (per-unit without ×quantity → under-count; per-line ×quantity → double-count).
        from aughor.semantic.measure_grain import connection_measure_grains, measure_grain_misuse
        from aughor.tools.schema import parse_schema_tables
        from aughor.db.connection import open_connection_for
        from aughor.routers._shared import get_schema_cached
        cid = state.get("connection_id") or ""
        _sqls = [r.sql for r in _qh if getattr(r, "sql", "") and not getattr(r, "error", None)]
        if cid and _sqls:
            _db = open_connection_for(cid)
            _dial = getattr(_db, "dialect", "duckdb")
            try:
                _sch = get_schema_cached(cid, _db)
                _mg, _qc = connection_measure_grains(cid, _db, parse_schema_tables(_sch))
            finally:
                _db.close()
            # Metric feasibility: the question needs a metric this connection can't support
            # (profit with no cost; efficiency with no conversions) → a fabricated verdict.
            from aughor.semantic.metric_feasibility import unsupported_metric_gap
            _fgap = unsupported_metric_gap(state.get("question", ""), _sch)
            if _fgap:
                report = AnalysisReport(**{**report.model_dump(), "data_quality_notes": list(report.data_quality_notes) + [DataQualityNote(
                    table="Report Narrative", column=None,
                    issue="The question asks for a metric this connection cannot support: " + _fgap + ".",
                    impact="Any profit/efficiency verdict here is inferred, not measured — treat it as unsupported.",
                    recommended_fix="Report what IS measurable (revenue, volume, spend) and state that the missing data blocks the verdict.",
                )]})
            _ghits: list[str] = []
            for _s in _sqls:
                _m = measure_grain_misuse(_s, _mg, _qc, dialect=_dial)
                if _m and _m not in _ghits:
                    _ghits.append(_m)
            if _ghits:
                gnote = DataQualityNote(
                    table="Report Narrative", column=None,
                    issue="A query aggregated a measure at the wrong grain: " + "; ".join(_ghits) + ".",
                    impact="A per-unit measure summed without quantity under-counts; a per-line measure × quantity double-counts.",
                    recommended_fix="Re-aggregate at the correct grain — per-unit measures × quantity, per-line measures summed directly.",
                )
                report = AnalysisReport(
                    **{**report.model_dump(), "data_quality_notes": list(report.data_quality_notes) + [gnote]}
                )
    except Exception:
        pass  # verifiers are best-effort — never block the report

    return {"report": report, "unresolved_tensions": unresolved_tensions}


# ── Routing ───────────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> str:
    iteration = state.get("iteration", 0)
    hypotheses = state.get("hypotheses", [])
    idx = state.get("current_hypothesis_idx", 0)

    if iteration >= MAX_ITER:
        return "synthesize"

    if idx < len(hypotheses):
        return "plan_queries"

    return "synthesize"


# ── Node: replan ─────────────────────────────────────────────────────────────

def replan(state: AgentState) -> dict[str, Any]:
    """
    Adaptive routing node that runs after each score_evidence.

    Makes one LLM call to decide between:
      test_next       — proceed linearly
      deepen_current  — run more queries on same hypothesis
      promote_new     — inject a data-revealed hypothesis
      skip_to         — jump over moot hypotheses
      synthesize      — stop early with high confidence

    Fast-path: if we're in direct mode, or if all hypotheses are tested,
    skip the LLM call and go straight to synthesize / test_next.
    """
    # Direct mode never replans
    if state.get("query_mode") != "investigate":
        return {"replan_decision": ReplanDecision(next_action="test_next", reasoning="Direct mode — no replan.")}

    hypotheses = state.get("hypotheses", [])
    idx = state.get("current_hypothesis_idx", 0)
    iteration = state.get("iteration", 0)

    # All hypotheses tested — synthesize
    if idx >= len(hypotheses):
        return {"replan_decision": ReplanDecision(next_action="synthesize", reasoning="All hypotheses tested.")}

    # Hit iteration ceiling — synthesize
    if iteration >= MAX_ITER:
        return {"replan_decision": ReplanDecision(next_action="synthesize", reasoning="Iteration ceiling reached.")}

    # Find the most recently scored hypothesis (idx was already incremented by score_evidence)
    latest_idx = idx - 1
    if latest_idx < 0 or latest_idx >= len(hypotheses):
        return {"replan_decision": ReplanDecision(next_action="test_next", reasoning="No scored hypothesis yet.")}

    latest_h = hypotheses[latest_idx]

    # Retrieve the EvidenceScore for the latest hypothesis to get should_continue + new_hypothesis
    evidence_scores = state.get("evidence_scores", [])
    latest_score = next((s for s in reversed(evidence_scores) if s.hypothesis_id == latest_h.id), None)

    new_hyp_suggestion = (latest_score.new_hypothesis or "") if latest_score else ""
    should_cont = latest_score.should_continue if latest_score else False

    # Fast-path: if there's nothing interesting, proceed linearly
    if not new_hyp_suggestion and not should_cont:
        return {"replan_decision": ReplanDecision(next_action="test_next", reasoning="No new signals — proceeding linearly.")}

    # Full LLM replan call
    llm = get_provider("coder")
    decision: ReplanDecision = llm.complete(
        system="You are the investigation controller for an autonomous data analyst. Route the investigation efficiently.",
        user=REPLAN_PROMPT.format(
            question=state["question"],
            hypothesis_summary=_format_hypothesis_summary(hypotheses),
            latest_hypothesis_id=latest_h.id,
            latest_verdict=latest_h.verdict,
            latest_confidence=latest_h.confidence,
            latest_key_finding=latest_h.key_finding or "(none)",
            new_hypothesis_suggestion=new_hyp_suggestion or "null",
        ),
        response_model=ReplanDecision,
    )

    # Apply mutations to state
    updated_hypotheses = list(hypotheses)
    updated_idx = idx

    if decision.next_action == "skip_to" and decision.target_hypothesis_id:
        # Find the target hypothesis and jump to it, marking skipped ones
        target_id = decision.target_hypothesis_id
        for i, h in enumerate(updated_hypotheses):
            if h.id == target_id:
                updated_idx = i
                break
        # Mark all untested hypotheses between current idx and target as skipped
        for i in range(idx, updated_idx):
            h = updated_hypotheses[i]
            if h.verdict == "untested":
                updated_hypotheses[i] = Hypothesis(
                    id=h.id, description=h.description,
                    confidence=0.0, verdict="skipped",
                    key_finding=f"Skipped: {decision.reasoning}",
                )

    elif decision.next_action == "promote_new" and decision.promoted_hypothesis:
        # Insert the new hypothesis right after the current position
        new_h = decision.promoted_hypothesis
        updated_hypotheses.insert(updated_idx, new_h)
        # updated_idx stays — the new hypothesis is at position updated_idx

    elif decision.next_action == "deepen_current":
        # Step back so plan_and_execute re-runs for the same hypothesis
        updated_idx = max(0, idx - 1)

    return {
        "replan_decision": decision,
        "hypotheses": updated_hypotheses,
        "current_hypothesis_idx": updated_idx,
    }


def route_after_replan(state: AgentState) -> str:
    decision = state.get("replan_decision")
    if decision and decision.next_action == "synthesize":
        return "synthesize"
    idx = state.get("current_hypothesis_idx", 0)
    hypotheses = state.get("hypotheses", [])
    if idx >= len(hypotheses):
        return "synthesize"
    return "plan_queries"


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
        stat_results = analyze_query_result(result.columns, result.rows, result.sql)
        if stat_results:
            from aughor.agent.state import StatResult
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


def _get_events_context(question: str, conn, data_range) -> str:
    """Wrapper around events.get_events_context — best-effort, never raises."""
    try:
        from aughor.tools.events import get_events_context
        return get_events_context(question, conn=conn, data_date_range=data_range) or ""
    except Exception:
        return ""


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
