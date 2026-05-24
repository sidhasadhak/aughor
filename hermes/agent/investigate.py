"""
ADA (Autonomous Data Analyst) — structured investigation engine.

Replaces the hypothesis-scoring pipeline for investigate-mode questions with
an 8-phase analytical lifecycle that produces a progressive, number-backed
narrative instead of confidence-scored hypothesis cards.

Each phase is a separate LangGraph node so api.py can stream phase results
progressively as they complete.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from hermes.agent.state import (
    AgentState,
    ADAReport,
    ADARecommendation,
    InvestigationFinding,
    InvestigationPhaseResult,
    PhaseKeyNumber,
    WaterfallEntry,
)
from hermes.tools.executor import format_result_for_llm
from hermes.tools.stats import analyze_query_result

if TYPE_CHECKING:
    from hermes.db.connection import DatabaseConnection


# ── Dimension priority ordering (Spec §2, Tier 2V) ───────────────────────────
# Run customer-type first (new vs returning splits the cause tree), then
# channel, category, geography, everything else last.

_DIMENSION_PRIORITY_KEYWORDS: list[list[str]] = [
    ["customer_type", "customer_segment", "is_new", "new_customer", "returning", "customer_class"],
    ["channel", "source", "medium", "acquisition", "referrer", "utm"],
    ["category", "product_category", "product_type", "business_line", "vertical", "department"],
    ["region", "country", "geography", "geo", "city", "state", "market"],
    ["device", "platform", "browser", "os"],
    ["payment", "payment_method", "payment_type"],
]


def _prioritize_dimensions(dimensions: list[str]) -> list[str]:
    """Sort dimensions by spec-mandated priority: customer → channel → category → geo → other."""
    def _rank(dim: str) -> int:
        dl = dim.lower()
        for i, keywords in enumerate(_DIMENSION_PRIORITY_KEYWORDS):
            if any(kw in dl for kw in keywords):
                return i
        return len(_DIMENSION_PRIORITY_KEYWORDS)

    return sorted(dimensions, key=_rank)


# ── Router functions (read by graph.py conditional edges) ────────────────────

_DIMENSION_QUESTION_RE = re.compile(
    r'\b(which|what|top|breakdown|by|per|across|segment|split|attribution|influence|'
    r'channel|source|medium|region|country|geo|product|category|device|platform|'
    r'customer|segment|cohort|campaign|referrer|utm)\b',
    re.IGNORECASE,
)


def _question_asks_for_dimension(question: str) -> bool:
    """
    Return True when the user explicitly asked about a specific dimension
    (e.g. "which channel", "by region", "top product category").
    When True, Tier 0 termination is suppressed — we must run dimensional analysis
    even if the overall metric change is within normal variance.
    """
    q = question.lower()
    # "which X" or "what X" followed by a dimension keyword
    if re.search(r'\b(which|what)\b.{0,40}\b(channel|source|region|product|category|device|segment|campaign)\b', q):
        return True
    # Explicit attribution phrasing
    if re.search(r'\b(influence|attribution|drove|driving|caused|responsible|contributed|contribution)\b', q):
        return True
    # "breakdown by" / "split by" / "per channel" patterns
    if re.search(r'\b(breakdown|split|breakdown|segment)\s+(by|across|per)\b', q):
        return True
    return False


def route_after_baseline(state: AgentState) -> str:
    """
    Tier 0 gate: if the decline is within normal variance, skip straight to
    synthesis so we don't run 4 more expensive phases on non-anomalies.

    EXCEPTION: when the user explicitly asked about a specific dimension
    (e.g. "which channel had most influence"), always proceed to dimensional
    analysis — the user wants the breakdown regardless of anomaly status.

    Decision hierarchy:
      1. User asked about a dimension → always proceed to ada_decompose
      2. stats.py code-level sigma (authoritative, deterministic)
      3. LLM interpretation's is_significant flags (fallback)
      4. Unknown → proceed (don't block on uncertainty)
    """
    question = state.get("question", "")
    if _question_asks_for_dimension(question):
        return "ada_decompose"  # never skip when user wants dimensional breakdown

    sigma = state.get("_baseline_sigma")
    code_sig = state.get("_baseline_significant")

    # Code-level signal: stats.py ran and says "not significant"
    if code_sig is False and (sigma is None or sigma < 1.5):
        return "ada_synthesize"  # early stop → "within normal variance" report

    # LLM interpretation signal
    phases = state.get("investigation_phases") or []
    for phase in phases:
        if phase.get("phase_id") == "baseline":
            for f in phase.get("findings", []):
                if f.get("is_significant"):
                    return "ada_decompose"
            # Baseline phase found, but no finding flagged significant
            if code_sig is False:
                return "ada_synthesize"

    # No definitive signal → proceed (conservative: don't block)
    return "ada_decompose"


def route_after_decompose(state: AgentState) -> str:
    """Currently always proceeds to dimensional. Reserved for future pause-point logic."""
    return "ada_dimensional"


def route_after_dimensional(state: AgentState) -> str:
    """Currently always proceeds to behavioral (with dominant finding injected)."""
    return "ada_behavioral"


# ── Helpers ───────────────────────────────────────────────────────────────────

# Groq free tier hard cap is ~12k tokens per request.
# Rough char-to-token ratio for mixed SQL/prose is ~3.5 chars/token.
# Budget: 8000 tokens for schema+scan combined → ~28000 chars total.
_SCHEMA_CHAR_LIMIT = 20_000
_SCAN_CHAR_LIMIT = 6_000


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated {len(text) - limit} chars]"


def _filter_schema(schema: str, table_names: list[str]) -> str:
    """
    Keep only the schema blocks for tables mentioned in table_names.
    Uses word-boundary matching to avoid 'orders' matching 'order_items'.
    Falls back to full schema if nothing matches.
    """
    if not table_names or not schema:
        return schema

    # Normalise: extract bare table names (strip schema prefix like analytics.)
    bare = {t.split(".")[-1].lower() for t in table_names if t}

    # Build a single regex that matches any bare name at a word boundary
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(n) for n in bare) + r')\b',
        re.IGNORECASE,
    )

    blocks: list[str] = []
    current: list[str] = []

    def _flush():
        if current:
            block_text = "\n".join(current)
            if pattern.search(current[0]):
                blocks.append(block_text)
            current.clear()

    for line in schema.splitlines():
        if line.strip() == "":
            _flush()
        else:
            current.append(line)
    _flush()

    filtered = "\n\n".join(blocks)
    return filtered if filtered.strip() else schema


def _provider(role="coder"):
    from hermes.llm.provider import get_provider
    return get_provider(role)


def _execute_safe(conn: "DatabaseConnection", phase_id: str, sql: str):
    """Execute SQL with one self-correction retry. Returns QueryResult."""
    from hermes.agent.prompts import FIX_SQL_PROMPT
    from hermes.agent.prompts_investigate import PhasePlan
    from pydantic import BaseModel

    result = conn.execute(phase_id, sql)
    if result.error:
        class _Fix(BaseModel):
            fixed_sql: str
            explanation: str

        try:
            _err = result.error or ""
            if "does not have a column named" in _err or ("column" in _err.lower() and "not" in _err.lower()):
                _diag = (
                    "DIAGNOSIS: A column name in the query does not exist. "
                    "Use ONLY the exact column names listed in the SCHEMA. "
                    "Do NOT invent or rename columns — find the correct column or join to a table that has it.\n"
                )
            elif "does not exist" in _err and "table" in _err.lower():
                _diag = (
                    "DIAGNOSIS: A table name in the query does not exist. "
                    "Use ONLY the table names listed in the SCHEMA above.\n"
                )
            else:
                _diag = ""
            fix_prompt = FIX_SQL_PROMPT.format(
                dialect=conn.dialect,
                sql=sql,
                error=result.error,
                schema=conn.get_schema(),
                kb_patterns_section="",
                error_diagnosis=_diag,
            )
            fix = _provider("coder").complete(
                system="Fix this SQL error. Return fixed_sql and a one-line explanation.",
                user=fix_prompt,
                response_model=_Fix,
            )
            result = conn.execute(phase_id, fix.fixed_sql)
            if not result.error:
                result.sql = fix.fixed_sql
        except Exception:
            pass
    return result


def _results_to_text(results) -> str:
    """Render a list of QueryResults as compact text for LLM interpretation."""
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(f"--- Query {i} ---")
        parts.append(format_result_for_llm(r, max_rows=12))
    return "\n\n".join(parts)


def _phase_result(
    phase_id: str,
    phase_name: str,
    phase_icon: str,
    status: str,
    summary: str,
    findings: list[InvestigationFinding],
    skipped_reason: Optional[str] = None,
) -> InvestigationPhaseResult:
    return InvestigationPhaseResult(
        phase_id=phase_id,
        phase_name=phase_name,
        phase_icon=phase_icon,
        status=status,
        summary=summary,
        findings=findings,
        skipped_reason=skipped_reason,
    )


def _finding_from_result_and_model(
    finding_id: str,
    result,
    model,
    plan_chart_type: str = "auto",
) -> InvestigationFinding:
    chart = model.chart_type if model.chart_type != "auto" else plan_chart_type
    return InvestigationFinding(
        finding_id=finding_id,
        title=model.title,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows[:50],
        row_count=result.row_count,
        error=result.error,
        interpretation=model.interpretation,
        key_numbers=[
            PhaseKeyNumber(
                label=kn.label,
                value=kn.value,
                delta=kn.delta,
                context=kn.context,
            )
            for kn in model.key_numbers
        ],
        chart_type=chart,
        stat_note=model.stat_note,
        is_significant=model.is_significant,
    )


def _skipped_finding(phase_id: str, reason: str) -> InvestigationFinding:
    return InvestigationFinding(
        finding_id=f"{phase_id}_skip",
        title="Skipped",
        sql="",
        columns=[],
        rows=[],
        row_count=0,
        error=None,
        interpretation=reason,
        key_numbers=[],
        chart_type="none",
        stat_note=None,
        is_significant=False,
    )


def _phases_summary(phases: list[InvestigationPhaseResult]) -> str:
    lines = []
    for p in phases:
        lines.append(f"[{p['phase_name']}] {p['summary']}")
        for f in p["findings"]:
            if not f["error"] and f["interpretation"]:
                lines.append(f"  • {f['title']}: {f['interpretation'][:200]}")
    return "\n".join(lines)


def _phases_evidence(phases: list[InvestigationPhaseResult]) -> str:
    lines = []
    for p in phases:
        lines.append(f"\n=== {p['phase_name']} ===")
        for f in p["findings"]:
            if f["sql"]:
                lines.append(f"SQL: {f['sql']}")
            if f["error"]:
                lines.append(f"ERROR: {f['error']}")
            elif f["columns"] and f["rows"]:
                col_str = " | ".join(f["columns"])
                lines.append(col_str)
                lines.append("-" * len(col_str))
                for row in f["rows"][:20]:
                    lines.append(" | ".join(str(v) for v in row))
                if f["row_count"] > 20:
                    lines.append(f"... ({f['row_count'] - 20} more rows)")
    return "\n".join(lines)


# ── Phase nodes ───────────────────────────────────────────────────────────────

def ada_intake(state: AgentState) -> dict:
    """
    Phase 1 — Question Intake.
    Parses the question into: metric SQL, observation period, comparison period,
    date column, metric table, available dimensions.
    Returns updated state with ada_intake stored in investigation_phases[0].
    """
    from hermes.agent.prompts_investigate import INTAKE_PROMPT, IntakeOutput

    question = state["question"]
    schema = _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT)
    scan = _trim(state.get("scan_context") or "", _SCAN_CHAR_LIMIT)
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""

    prompt = INTAKE_PROMPT.format(
        question=question,
        schema=schema,
        scan_context=scan,
        events_section=events_section,
    )

    try:
        intake: IntakeOutput = _provider("coder").complete(
            system="You are a precise data analyst parsing a business question. Return a structured investigation specification.",
            user=prompt,
            response_model=IntakeOutput,
        )
    except Exception as e:
        intake = None
        intake_error = str(e)

    if intake is None:
        phase = _phase_result(
            "intake", "Question Intake", "🔍", "error",
            "Could not parse investigation specification.",
            [_skipped_finding("intake", intake_error)],
        )
        return {
            "investigation_phases": [phase],
            "ada_report": None,
        }

    # Store the intake spec in state via a synthetic phase (no SQL, just metadata)
    finding = InvestigationFinding(
        finding_id="intake_spec",
        title="Investigation Specification",
        sql="",
        columns=["field", "value"],
        rows=[
            ["Metric", f"{intake.metric_label} ({intake.metric_sql})"],
            ["Observation", f"{intake.observation_label} ({intake.observation_start} → {intake.observation_end})"],
            ["Comparison", f"{intake.comparison_label} ({intake.comparison_start} → {intake.comparison_end})"],
            ["Date column", intake.date_column],
            ["Primary table", intake.metric_table],
            ["Dimensions", ", ".join(intake.dimensions[:8])],
        ],
        row_count=6,
        error=None,
        interpretation=intake.intake_notes or f"Investigating {intake.metric_label} in {intake.observation_label}.",
        key_numbers=[],
        chart_type="none",
        stat_note=None,
        is_significant=False,
    )
    phase = _phase_result(
        "intake", "Question Intake", "🔍", "complete",
        f"Measuring {intake.metric_label} in {intake.observation_label} vs {intake.comparison_label}.",
        [finding],
    )
    # Build a filtered schema containing only the tables intake identified
    relevant_tables = [intake.metric_table] + [
        d.split(".")[0] for d in intake.dimensions if "." in d
    ]
    filtered_schema = _filter_schema(state["schema_context"], relevant_tables)

    intake_dict = intake.model_dump()
    intake_dict["filtered_schema"] = filtered_schema

    return {
        "investigation_phases": [phase],
        "_ada_intake": intake_dict,
    }


def ada_baseline(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 2 — Baseline & Anomaly Assessment.
    Confirms the anomaly is real and statistically significant.
    """
    from hermes.agent.prompts_investigate import (
        BASELINE_PLAN_PROMPT,
        BASELINE_INTERPRET_PROMPT,
        PhasePlan,
        PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT)
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""
    phases = state.get("investigation_phases", [])
    metric_label = intake_data.get("metric_label", "the core metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "the observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    comp_label = intake_data.get("comparison_label", "the comparison period")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")

    # Step 1: Plan SQL
    plan_prompt = BASELINE_PLAN_PROMPT.format(
        question=question,
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=f"{obs_label} ({obs_start} to {obs_end})",
        comparison_basis=f"{comp_label} ({comp_start} to {comp_end})",
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
        events_section=events_section,
    )
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write SQL queries for baseline anomaly detection. Return a JSON object with a 'queries' list.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "baseline", "Baseline & Anomaly Assessment", "📊", "error",
            "Could not plan baseline queries.",
            [_skipped_finding("baseline", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    # Step 2: Execute
    results = []
    for q in plan.queries:
        if not q.sql or not q.sql.strip():
            continue
        r = _execute_safe(conn, "baseline", q.sql)
        r.hypothesis_id = "baseline"
        results.append((q, r))

    if not results:
        phase = _phase_result(
            "baseline", "Baseline & Anomaly Assessment", "📊", "error",
            "All baseline queries failed to execute.",
            [_skipped_finding("baseline", "No queries produced results.")],
        )
        return {"investigation_phases": phases + [phase]}

    # Step 3: Interpret
    results_text = _results_to_text([r for _, r in results])
    interpret_prompt = BASELINE_INTERPRET_PROMPT.format(
        question=question,
        results_text=results_text,
        events_section=events_section,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="You are a senior data analyst interpreting query results. Be precise. Cite real numbers.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception as e:
        interpretation = None

    # ── Stats.py: code-level significance check (runs before LLM interpretation) ──
    # Compute z-score on the baseline time series. The LLM is asked to compute
    # the same thing in SQL, but this gives us a deterministic Python-level gate
    # that the router can trust unconditionally.
    code_sigma: Optional[float] = None
    code_significant: Optional[bool] = None
    for _, r in results:
        if r.error or not r.rows or not r.columns:
            continue
        stat_results = analyze_query_result(r.columns, r.rows)
        for sr in stat_results:
            if sr.sigma is not None:
                if code_sigma is None or sr.sigma > code_sigma:
                    code_sigma = sr.sigma
        if code_sigma is not None:
            code_significant = code_sigma >= 2.0
            break  # first successful result is enough

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"baseline_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
        passes_to_next = interpretation.passes_to_next
        # If stats.py couldn't compute sigma, fall back to LLM's is_significant flags
        if code_significant is None:
            code_significant = any(f["is_significant"] for f in findings)
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"baseline_{i}",
                title=q.title,
                sql=r.sql,
                columns=r.columns,
                rows=r.rows[:50],
                row_count=r.row_count,
                error=r.error,
                interpretation=f"Query executed: {r.row_count} rows returned." if not r.error else r.error,
                key_numbers=[],
                chart_type=q.chart_type,
                stat_note=None,
                is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = f"Baseline computed for {obs_label}."
        passes_to_next = summary
        if code_significant is None:
            code_significant = True  # unknown → assume significant, don't block

    # Append sigma note to summary if available
    if code_sigma is not None:
        sig_label = "significant anomaly" if code_significant else "within normal variance"
        summary = f"{summary} [stats.py: σ={code_sigma:.2f} — {sig_label}]"

    phase = _phase_result(
        "baseline", "Baseline & Anomaly Assessment", "📊",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {
        "investigation_phases": phases + [phase],
        "_baseline_summary": summary,
        "_baseline_passes": passes_to_next,
        "_baseline_significant": code_significant,
        "_baseline_sigma": code_sigma,
    }


def ada_decompose(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 3 — Metric Decomposition.
    Splits the metric into sub-drivers (volume vs value, new vs returning, etc.)
    """
    from hermes.agent.prompts_investigate import (
        DECOMPOSE_PLAN_PROMPT, DECOMPOSE_INTERPRET_PROMPT,
        PhasePlan, PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT)
    phases = state.get("investigation_phases", [])
    baseline_summary = state.get("_baseline_summary", "Baseline established.")

    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")

    plan_prompt = DECOMPOSE_PLAN_PROMPT.format(
        question=question,
        baseline_summary=baseline_summary,
        total_change="(see baseline findings)",
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=obs_label,
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
    )
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write SQL for metric decomposition. Decompose the metric into additive sub-drivers.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "decomposition", "Metric Decomposition", "🧩", "error",
            "Could not plan decomposition queries.",
            [_skipped_finding("decomposition", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    results = []
    for q in plan.queries:
        if not q.sql or not q.sql.strip():
            continue
        r = _execute_safe(conn, "decomposition", q.sql)
        r.hypothesis_id = "decomposition"
        results.append((q, r))

    if not results:
        phase = _phase_result(
            "decomposition", "Metric Decomposition", "🧩", "error",
            "Decomposition queries failed.",
            [_skipped_finding("decomposition", "No results.")],
        )
        return {"investigation_phases": phases + [phase]}

    results_text = _results_to_text([r for _, r in results])
    prior_summary = f"Baseline: {baseline_summary}"
    interpret_prompt = DECOMPOSE_INTERPRET_PROMPT.format(
        question=question,
        baseline_summary=baseline_summary,
        results_text=results_text,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="Interpret metric decomposition results. State clearly whether volume or value drove the change.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception:
        interpretation = None

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"decomp_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
        passes_to_next = interpretation.passes_to_next
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"decomp_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type,
                stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Metric decomposition complete."
        passes_to_next = summary

    phase = _phase_result(
        "decomposition", "Metric Decomposition", "🧩",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {
        "investigation_phases": phases + [phase],
        "_decomp_summary": summary,
        "_decomp_passes": passes_to_next,
    }


def ada_dimensional(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 4 — Dimensional Drill-Down.
    Contribution analysis: WHERE did the change concentrate?
    """
    from hermes.agent.prompts_investigate import (
        DIMENSIONAL_PLAN_PROMPT, DIMENSIONAL_INTERPRET_PROMPT,
        PhasePlan, PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT)
    phases = state.get("investigation_phases", [])

    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")
    dimensions = intake_data.get("dimensions", [])

    baseline_summary = state.get("_baseline_summary", "")
    decomp_summary = state.get("_decomp_summary", "")
    prior_summary = f"Baseline: {baseline_summary}\nDecomposition: {decomp_summary}"

    # Sort dimensions by spec-mandated priority: customer → channel → category → geo
    # This ensures the LLM picks the analytically highest-value dimensions first.
    prioritized_dims = _prioritize_dimensions(dimensions)
    dimensions_list = "\n".join(
        f"  - {d}" for d in prioritized_dims[:8]
    ) if prioritized_dims else "  (none identified)"

    plan_prompt = DIMENSIONAL_PLAN_PROMPT.format(
        question=question,
        baseline_summary=baseline_summary,
        decomposition_summary=decomp_summary,
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=obs_label,
        obs_start=obs_start,
        obs_end=obs_end,
        comp_start=comp_start,
        comp_end=comp_end,
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
        dimensions_list=dimensions_list,
    )
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write contribution-analysis SQL for each dimension. Sort by absolute_change ASC.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "dimensional", "Dimensional Analysis", "🔬", "error",
            "Could not plan dimensional queries.",
            [_skipped_finding("dimensional", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    results = []
    for q in plan.queries[:4]:  # cap at 4 dimensions
        if not q.sql or not q.sql.strip():
            continue
        r = _execute_safe(conn, "dimensional", q.sql)
        r.hypothesis_id = "dimensional"
        results.append((q, r))

    if not results:
        phase = _phase_result(
            "dimensional", "Dimensional Analysis", "🔬", "error",
            "Dimensional queries failed.",
            [_skipped_finding("dimensional", "No results.")],
        )
        return {"investigation_phases": phases + [phase]}

    results_text = _results_to_text([r for _, r in results])
    interpret_prompt = DIMENSIONAL_INTERPRET_PROMPT.format(
        question=question,
        prior_summary=prior_summary,
        results_text=results_text,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="Interpret contribution analysis. Identify concentrated vs. diffuse decline.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception:
        interpretation = None

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"dim_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
        passes_to_next = interpretation.passes_to_next
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"dim_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type,
                stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Dimensional analysis complete."
        passes_to_next = summary

    phase = _phase_result(
        "dimensional", "Dimensional Analysis", "🔬",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {
        "investigation_phases": phases + [phase],
        "_dimensional_summary": summary,
        "_dimensional_passes": passes_to_next,
    }


def ada_behavioral(state: AgentState, conn: "DatabaseConnection") -> dict:
    """
    Phase 5+6 — Behavioral & Operational Diagnostics.
    WHO changed behaviour + WHAT changed operationally.
    """
    from hermes.agent.prompts_investigate import (
        BEHAVIORAL_PLAN_PROMPT, BEHAVIORAL_INTERPRET_PROMPT,
        PhasePlan, PhaseInterpretation,
    )

    question = state["question"]
    intake_data = state.get("_ada_intake") or {}
    schema = intake_data.get("filtered_schema") or _trim(state["schema_context"], _SCHEMA_CHAR_LIMIT)
    phases = state.get("investigation_phases", [])
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""

    metric_label = intake_data.get("metric_label", "the metric")
    metric_sql = intake_data.get("metric_sql", "SUM(revenue)")
    obs_start = intake_data.get("observation_start", "")
    obs_end = intake_data.get("observation_end", "")
    obs_label = intake_data.get("observation_label", "observation period")
    comp_start = intake_data.get("comparison_start", "")
    comp_end = intake_data.get("comparison_end", "")
    date_col = intake_data.get("date_column", "")
    metric_table = intake_data.get("metric_table", "")

    prior_summary = " | ".join(filter(None, [
        state.get("_baseline_summary", ""),
        state.get("_decomp_summary", ""),
        state.get("_dimensional_summary", ""),
    ]))

    # Dominant finding from Tier 2: the `passes_to_next` string from dimensional
    # interpretation carries the most concentrated finding (e.g. "channel=mobile
    # accounts for 68% of the order drop"). Injecting this makes Tier-3 queries
    # targeted instead of running the same generic checklist every time.
    dominant_finding = (
        state.get("_dimensional_passes")
        or state.get("_dimensional_summary")
        or "No specific segment concentration identified — run broad diagnostics."
    )

    plan_prompt = BEHAVIORAL_PLAN_PROMPT.format(
        question=question,
        prior_summary=prior_summary,
        dominant_finding=dominant_finding,
        metric_label=metric_label,
        metric_sql=metric_sql,
        observation_period=obs_label,
        obs_start=obs_start,
        obs_end=obs_end,
        comp_start=comp_start,
        comp_end=comp_end,
        date_column=date_col,
        metric_table=metric_table,
        schema=schema,
        events_section=events_section,
    )
    try:
        plan: PhasePlan = _provider("coder").complete(
            system="Write SQL for behavioral and operational diagnostics.",
            user=plan_prompt,
            response_model=PhasePlan,
        )
    except Exception as e:
        phase = _phase_result(
            "behavioral", "Behavioral & Operational", "👥", "error",
            "Could not plan behavioral queries.",
            [_skipped_finding("behavioral", str(e))],
        )
        return {"investigation_phases": phases + [phase]}

    results = []
    for q in plan.queries[:4]:
        if not q.sql or not q.sql.strip():
            continue
        r = _execute_safe(conn, "behavioral", q.sql)
        r.hypothesis_id = "behavioral"
        results.append((q, r))

    if not results:
        phase = _phase_result(
            "behavioral", "Behavioral & Operational", "👥", "skipped",
            "Behavioral/operational tables not available in this schema.",
            [_skipped_finding("behavioral", "Required tables (sessions, refunds, etc.) not in schema.")],
        )
        return {"investigation_phases": phases + [phase]}

    results_text = _results_to_text([r for _, r in results])
    interpret_prompt = BEHAVIORAL_INTERPRET_PROMPT.format(
        question=question,
        prior_summary=prior_summary,
        results_text=results_text,
    )
    try:
        interpretation: PhaseInterpretation = _provider("narrator").complete(
            system="Interpret behavioral and operational findings. Be specific about what changed.",
            user=interpret_prompt,
            response_model=PhaseInterpretation,
        )
    except Exception:
        interpretation = None

    if interpretation and interpretation.findings:
        findings = [
            _finding_from_result_and_model(
                f"beh_{i}", r, interpretation.findings[min(i, len(interpretation.findings) - 1)],
                q.chart_type,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = interpretation.phase_summary
    else:
        findings = [
            InvestigationFinding(
                finding_id=f"beh_{i}", title=q.title, sql=r.sql,
                columns=r.columns, rows=r.rows[:50], row_count=r.row_count,
                error=r.error, interpretation="Query executed.",
                key_numbers=[], chart_type=q.chart_type,
                stat_note=None, is_significant=False,
            )
            for i, (q, r) in enumerate(results)
        ]
        summary = "Behavioral and operational analysis complete."

    phase = _phase_result(
        "behavioral", "Behavioral & Operational", "👥",
        "complete" if any(not f["error"] for f in findings) else "partial",
        summary, findings,
    )
    return {
        "investigation_phases": phases + [phase],
        "_behavioral_summary": summary,
    }


def ada_synthesize(state: AgentState) -> dict:
    """
    Phase 8 — Synthesis: Attribution Waterfall + Recommendations.
    Assembles all phase findings into an ADAReport.
    """
    from hermes.agent.prompts_investigate import ADA_SYNTHESIZE_PROMPT, ADASynthesisModel
    from hermes.agent.state import ADAReport, WaterfallEntry, ADARecommendation

    question = state["question"]
    phases = state.get("investigation_phases", [])
    events = state.get("events_context") or ""
    events_section = f"BUSINESS CALENDAR:\n{events}\n" if events else ""
    intake_data = state.get("_ada_intake") or {}

    # Detect early-stop: if only baseline (and intake) phases exist, the Tier-0
    # gate fired and we should label this as a "no anomaly" report.
    phase_ids = {p["phase_id"] for p in phases}
    early_stop = phase_ids <= {"intake", "baseline"}
    sigma = state.get("_baseline_sigma")
    early_stop_note = ""
    if early_stop:
        sigma_str = f" (z={sigma:.2f})" if sigma is not None else ""
        early_stop_note = (
            f"\n\nNOTE: The investigation stopped at Tier 0{sigma_str}. "
            "The observed change is within normal historical variance — no anomaly was detected. "
            "Your headline, executive_summary, and waterfall should reflect this: "
            "explain that the decline is consistent with typical fluctuation, not a new problem. "
            "confidence should be HIGH (we're confident there is no anomaly). "
            "recommendations should be empty or advisory only."
        )

    phases_summary = _phases_summary(phases)
    evidence_log = _phases_evidence(phases)

    synth_prompt = ADA_SYNTHESIZE_PROMPT.format(
        question=question,
        phases_summary=phases_summary,
        evidence_log=evidence_log[:6000],
        events_section=events_section,
    ) + early_stop_note
    try:
        synth: ADASynthesisModel = _provider("narrator").complete(
            system=(
                "You are a senior data analyst writing a board-level investigation report. "
                "Every number must trace to the evidence log. No fabrication. "
                "Be definitive where evidence is strong; honest about uncertainty where it isn't."
            ),
            user=synth_prompt,
            response_model=ADASynthesisModel,
        )
    except Exception as e:
        synth = None

    if synth:
        waterfall = [
            WaterfallEntry(
                cause=w.cause,
                amount_label=w.amount_label,
                pct_of_total=w.pct_of_total,
                controllable=w.controllable,
                structural=w.structural,
            )
            for w in synth.attribution_waterfall
        ]
        recommendations = [
            ADARecommendation(
                action=r.action,
                expected_impact=r.expected_impact,
                owner=r.owner,
                timeline=r.timeline,
            )
            for r in synth.recommendations
        ]
        ada_report = ADAReport(
            headline=synth.headline,
            executive_summary=synth.executive_summary,
            metric=intake_data.get("metric_label", ""),
            observation_period=intake_data.get("observation_label", ""),
            comparison_basis=intake_data.get("comparison_label", ""),
            total_change_label=synth.total_change_label,
            phases=phases,
            attribution_waterfall=waterfall,
            confidence=synth.confidence,
            confidence_justification=synth.confidence_justification,
            recommendations=recommendations,
            data_gaps=synth.data_gaps,
        )
    else:
        ada_report = ADAReport(
            headline="Investigation complete — synthesis failed.",
            executive_summary="See individual phase findings above for details.",
            metric=intake_data.get("metric_label", ""),
            observation_period=intake_data.get("observation_label", ""),
            comparison_basis=intake_data.get("comparison_label", ""),
            total_change_label="",
            phases=phases,
            attribution_waterfall=[],
            confidence="LOW",
            confidence_justification="Synthesis LLM call failed.",
            recommendations=[],
            data_gaps=[],
        )

    # Also produce a legacy AnalysisReport for backward compat (history, cache)
    from hermes.agent.state import AnalysisReport, Finding
    legacy_findings = []
    for p in phases:
        for f in p["findings"]:
            if f["interpretation"] and not f["error"]:
                legacy_findings.append(Finding(
                    claim=f["title"],
                    evidence=f["interpretation"][:300],
                    confidence=0.8 if f["is_significant"] else 0.5,
                    hypothesis_id=p["phase_id"],
                ))
    legacy_report = AnalysisReport(
        headline=ada_report["headline"],
        verdict=ada_report["executive_summary"],
        key_findings=legacy_findings[:5],
        what_is_not_the_cause=[g for g in ada_report["data_gaps"]],
        risks=[r["action"] for r in ada_report["recommendations"][:2]],
        recommended_actions=[r["action"] for r in ada_report["recommendations"]],
    )

    return {
        "ada_report": ada_report,
        "report": legacy_report,
        "investigation_phases": phases,
    }
