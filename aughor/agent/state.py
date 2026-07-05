from __future__ import annotations

from typing import Annotated, Any, Literal, Optional
from typing_extensions import NotRequired, TypedDict

from pydantic import BaseModel, Field, field_validator
import operator

# The query-execution result contract lives on the PLATFORM side so the data plane
# (db / connectors) returns it without importing the agent. Re-exported here so the
# many `from aughor.agent.state import QueryResult` call sites stay unchanged.
from aughor.platform.contracts.execution import QueryResult, StatResult  # noqa: F401


# ── Pydantic output schemas (structured LLM responses) ──────────────────────

class Hypothesis(BaseModel):
    id: str
    description: str
    confidence: float = 0.0
    verdict: Literal["confirmed", "refuted", "inconclusive", "untested", "skipped"] = "untested"
    key_finding: str = ""


class RouteDecision(BaseModel):
    mode: Literal["direct", "investigate", "explore", "final_text"]
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence (0–1)")
    reasoning: str = Field(description="One sentence explaining the classification")


class DecomposeOutput(BaseModel):
    question_understanding: str = Field(
        description="Restate the question in analytical terms — what metric, what time window, what comparison"
    )
    hypotheses: list[Hypothesis] = Field(
        description="3-5 concrete, mutually-exclusive hypotheses that could explain the observation. Each must be independently testable with SQL."
    )


class QueryPlan(BaseModel):
    hypothesis_id: str
    tables: list[str] = Field(
        default_factory=list,
        description="All table names this plan will touch. List every table before writing any SQL — this forces you to verify they exist in the schema.",
    )
    expected_if_true: str = Field(
        default="",
        description="Concrete prediction: what pattern/numbers would you expect to see in the query results IF this hypothesis is correct? Be specific (e.g. 'APAC revenue share > 40% and declining month-over-month').",
    )
    expected_if_false: str = Field(
        default="",
        description="Concrete prediction: what pattern/numbers would you expect to see in the query results IF this hypothesis is WRONG? Be specific (e.g. 'Revenue decline is uniform across all regions, not concentrated in APAC').",
    )
    queries: list[str] = Field(
        min_length=1,
        description="1-3 SQL SELECT queries that together confirm or refute this hypothesis. Use only tables and columns from the provided schema. You MUST supply at least one query — an empty list is never valid.",
    )
    reasoning: str = Field(
        description="Why these specific queries test this hypothesis"
    )


class QueryIntent(BaseModel):
    """Describes WHAT a single query should measure — no SQL."""
    description: str = Field(
        description="One sentence: what this query should measure and what pattern to look for."
    )
    tables: list[str] = Field(
        default_factory=list,
        description="Subset of the plan's tables this query touches.",
    )
    filters: list[str] = Field(
        default_factory=list,
        description="WHERE conditions in plain English (e.g. 'region = APAC', 'last 30 days', 'active users only').",
    )
    aggregation: str = Field(
        default="",
        description="GROUP BY columns and aggregate metric in plain English (e.g. 'GROUP BY region and month, SUM(revenue)').",
    )


class QueryPlanV2(BaseModel):
    """Planning-only output — no SQL. SQL is generated separately by execute_planned_queries."""
    hypothesis_id: str
    tables: list[str] = Field(
        default_factory=list,
        description="All tables this plan will touch. Every table must exist verbatim in the schema.",
    )
    expected_if_true: str = Field(
        default="",
        description="Concrete prediction if the hypothesis is correct.",
    )
    expected_if_false: str = Field(
        default="",
        description="Concrete prediction if the hypothesis is wrong.",
    )
    reasoning: str = Field(default="", description="Why these queries test this hypothesis.")
    query_intents: list[QueryIntent] = Field(
        min_length=1,
        description="1-3 query intents describing what to measure. Each will be translated to SQL separately.",
    )


class SQLOutput(BaseModel):
    """Single SQL query produced from a QueryIntent."""
    sql: str = Field(description="A valid SQL SELECT query for the target dialect.")
    reasoning: str = Field(default="", description="One sentence: what this query measures.")


# StatResult + QueryResult moved to aughor.platform.contracts.execution (imported at
# the top of this module). They remain importable from here for back-compat.


class EvidenceScore(BaseModel):
    hypothesis_id: str
    confidence: float = Field(ge=0.0, le=1.0, description="0 = fully refuted, 1 = fully confirmed")
    verdict: Literal["confirmed", "refuted", "inconclusive"]
    key_finding: str = Field(description="One sentence: what the data showed")
    should_continue: bool = Field(description="True if more queries are needed to reach a confident conclusion")
    new_hypothesis: Optional[str] = Field(
        default=None,
        description="If the data revealed an unexpected angle worth investigating, describe it as a new hypothesis. Otherwise null."
    )


class Finding(BaseModel):
    claim: str
    evidence: str
    confidence: float
    hypothesis_id: Optional[str] = None


class Pitfall(BaseModel):
    """A SQL failure that was detected and corrected during the investigation."""
    original_sql: str
    error: str
    fixed_sql: str
    fix_explanation: str = Field(
        description="One sentence: what the problem was and the general rule to avoid it (e.g. 'use EXTRACT(EPOCH FROM ...) not date subtraction in Postgres')"
    )
    data_quality_issue: Optional[str] = Field(
        default=None,
        description="If the error reveals a data quality problem (NULLs, bad types, missing values), describe it. Otherwise null."
    )
    retry_error: Optional[str] = Field(
        default=None,
        description="If the auto-corrected query also failed, the error from the retry. None if the fix succeeded."
    )


class SQLFix(BaseModel):
    fixed_sql: str = Field(description="The corrected SELECT query. Must be valid for the target dialect.")
    fix_explanation: str = Field(description="One sentence explaining what was wrong and the general rule to avoid it")
    data_quality_issue: Optional[str] = Field(
        default=None,
        description="If the error reveals a data quality problem in the underlying data, describe it concisely. Otherwise null."
    )


class SubQuestion(BaseModel):
    id: str = Field(description="Q1, Q2, … in execution order")
    question: str
    depends_on: list[str] = Field(default_factory=list, description="IDs of sub-questions that must complete first")
    purpose: Literal["landscape", "relationship", "threshold", "drill_down", "confounder", "synthesis"]
    expected_output: str = Field(description="What shape of data this query should return")
    done: bool = False
    answer: Optional[str] = None      # populated by reason_over_result
    refinement: Optional[str] = None  # downstream hint produced by reason_over_result


class SubQuestionAnswer(BaseModel):
    subq_id: str
    question: str
    purpose: str
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    error: Optional[str] = None
    answer: str    # natural-language answer produced by reason_over_result
    insight: str   # the most actionable single insight
    refinement: Optional[str] = None  # hint injected into downstream sub-questions


class ReasoningOutput(BaseModel):
    answer: str = Field(description="Direct answer to the sub-question, one sentence.")
    insight: str = Field(description="The single most actionable or surprising finding from the data.")
    refinement: Optional[str] = Field(
        default=None,
        description="Concrete hint to update a downstream sub-question's SQL approach. "
                    "E.g. 'Q3 should use 1pp bands between 10% and 30% instead of coarse buckets'. "
                    "Null if no refinement is needed.",
    )
    new_sub_question: Optional["SubQuestion"] = Field(
        default=None,
        description="If the data revealed an unexpected angle worth exploring, define a new sub-question to insert. Otherwise null.",
    )

    @field_validator("new_sub_question", mode="before")
    @classmethod
    def _coerce_new_sub_question(cls, v):
        """LLMs sometimes return nested objects as JSON strings. Parse them."""
        if isinstance(v, str):
            import json
            try:
                v = json.loads(v)
            except (ValueError, TypeError):
                return None  # unparseable string → treat as no new sub-question
        return v


class VerificationCheck(BaseModel):
    """One guard/check the engine should have run on this investigation — and whether it
    actually did. Defeats class-E silent failures (a guard that's off but assumed on):
    a check that did NOT run is surfaced, never silently treated as passed."""
    name: str
    label: str
    status: Literal["ran", "not_run", "n/a"]   # n/a = the check had nothing applicable to do
    detail: Optional[str] = None


class VerificationManifest(BaseModel):
    """The liveness + trust record for an investigation. `coverage` = fraction of applicable
    guards that ran. `earned_confidence`/`data_trust` are COMPUTED (never asserted by the
    LLM) so the report's confidence reflects evidence, not a vibe; `signals` is the
    provenance ('why this score')."""
    checks: list[VerificationCheck] = Field(default_factory=list)
    coverage: float = 0.0
    earned_confidence: float = 1.0          # 0-1: coverage × completeness × data_trust
    confidence_band: str = "high"           # high | medium | low
    data_trust: float = 1.0                 # 0-1: how trustworthy the underlying data looks
    signals: list[str] = Field(default_factory=list)   # why the score is what it is


class ExplorationReport(BaseModel):
    headline: str = Field(description="One sentence direct answer to the original question. Board-ready.")
    conclusion: str = Field(description="2-3 sentence explanation of the answer with supporting numbers.")
    narrative: str = Field(description="Flowing paragraph connecting all sub-questions into a coherent story.")
    recommended_actions: list[str] = Field(description="Concrete next steps based on the findings.")
    data_quality_notes: list["DataQualityNote"] = Field(default_factory=list)
    # Liveness record — which guards actually ran on this investigation (Bet 0). Set by
    # synthesize_exploration; the LLM never fills this. Optional so older reports stay valid.
    verification: Optional["VerificationManifest"] = None

    @field_validator("data_quality_notes", mode="before")
    @classmethod
    def _drop_empty_notes(cls, v):
        """Drop malformed DataQualityNote entries that are missing required fields.

        Handles both raw dicts (from LLM output) and already-instantiated
        DataQualityNote objects (from synthesize_exploration's dq_notes merge).
        """
        if not isinstance(v, list):
            return []
        result = []
        for n in v:
            if isinstance(n, dict):
                # Raw dict from LLM — keep only if it has the minimum fields
                if n.get("issue") or n.get("table"):
                    result.append(n)
            else:
                # Already a DataQualityNote instance — pass through as-is
                result.append(n)
        return result


class ReplanDecision(BaseModel):
    next_action: Literal["test_next", "deepen_current", "promote_new", "skip_to", "synthesize"]
    target_hypothesis_id: Optional[str] = Field(
        default=None,
        description="For skip_to: the hypothesis ID to jump to next. For deepen_current: same as current hypothesis.",
    )
    promoted_hypothesis: Optional["Hypothesis"] = Field(
        default=None,
        description="For promote_new: a brand-new hypothesis the data revealed that wasn't in the original decomposition.",
    )
    reasoning: str = Field(description="One sentence explaining the routing decision.")


class DataQualityNote(BaseModel):
    table: str = ""
    column: Optional[str] = None
    issue: str = ""          # LLMs sometimes omit this — default to empty
    impact: str = ""
    recommended_fix: str = ""


class AnalysisReport(BaseModel):
    headline: str = Field(description="One sentence, board-ready. Lead with the most important finding.")
    verdict: str = Field(description="2-3 sentence diagnosis. What happened, why, which segments.")
    key_findings: list[Finding] = Field(description="Top 3-5 findings, ranked by evidence strength")
    what_is_not_the_cause: list[str] = Field(description="Hypotheses that were tested and refuted — important for ruling things out")
    data_quality_notes: list[DataQualityNote] = Field(
        default_factory=list,
        description="Structural data issues discovered during the investigation — NULLs, type problems, missing data. Empty list if none found."
    )
    risks: list[str] = Field(description="What to watch — forward-looking concerns")
    recommended_actions: list[str] = Field(description="Concrete next steps, including any data quality fixes needed")


# ── LangGraph state ──────────────────────────────────────────────────────────

# ── ADA Investigation types (new structured investigate mode) ─────────────────

class PhaseKeyNumber(TypedDict):
    label: str
    value: str        # formatted: "$1.4M", "-18.4%", "2.6σ"
    delta: Optional[str]   # "+5pp vs prior period"
    context: Optional[str] # "February 2026 vs January 2026"


class InvestigationFinding(TypedDict):
    finding_id: str
    title: str
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    error: Optional[str]
    interpretation: str   # 2-3 sentences citing real numbers
    key_numbers: list[PhaseKeyNumber]
    chart_type: str       # "bar"|"line"|"stacked_bar"|"auto"|"none"
    stat_note: Optional[str]  # "z-score = -2.4, significant at α=0.05"
    is_significant: bool
    trust_caveat: Optional[str]  # advisory from the trust battery (e.g. "fan-out", "impossible magnitude") — never blocks the answer
    # Per-column display unit so every surface (chart axis, data labels, table, key numbers) formats
    # a value the SAME way — e.g. {"metric_total": "percent"} tells the UI a rate stored as 0.4096 is
    # "41.0%", not "0.4". Absent → the UI falls back to its column-name heuristics. Units: "percent".
    column_units: NotRequired[dict[str, str]]


class InvestigationPhaseResult(TypedDict):
    phase_id: str       # "baseline"|"decomposition"|"dimensional"|"behavioral"|"operational"
    phase_name: str
    phase_icon: str     # emoji for UI
    status: str         # "complete"|"partial"|"skipped"|"error"
    summary: str        # one-sentence headline finding for this phase
    findings: list[InvestigationFinding]
    skipped_reason: Optional[str]


class WaterfallEntry(TypedDict):
    cause: str
    amount_label: str   # "$287K" or "~18% of gap"
    pct_of_total: float # 0–100 (signed: positive = contributor to decline)
    controllable: bool
    structural: bool    # vs transient


class AnswerRecommendation(TypedDict):
    action: str
    expected_impact: str
    owner: str
    timeline: str


class AnswerReport(TypedDict):
    headline: str
    executive_summary: str
    metric: str
    observation_period: str
    comparison_basis: str
    total_change_label: str    # "-$330K (-18.4% MoM)"
    phases: list[InvestigationPhaseResult]
    attribution_waterfall: list[WaterfallEntry]
    confidence: str            # "HIGH"|"MEDIUM"|"LOW"
    confidence_justification: str
    recommendations: list[AnswerRecommendation]
    data_gaps: list[str]
    # Phase-2 structural trust artifacts (Orchestrator). Optional — older cached reports
    # may omit them; the UI reads each via .get(). See agent/orchestrator.py.
    contradiction_report: Optional[dict]   # typed cross-phase ContradictionReport.to_dict()
    orchestration_plan: Optional[dict]     # the Analyst's declared phase plan (plan of record)
    plan_reconciliation: Optional[dict]    # planned-vs-actual phases at the synthesis seam


class AgentState(TypedDict):
    question: str
    connection_id: str
    investigation_id: str
    schema_context: str
    # Telemetry — Langfuse trace ID (== investigation_id). Empty string when disabled.
    trace_id: str

    # Canvas context (Sprint 21) — set when request arrives via canvas_id.
    # canvas_id: the Canvas the user launched the investigation from.
    # canvas_schema_context: pre-filtered schema string (Canvas table selection
    #   applied). When present, nodes use this instead of re-building from
    #   connection_id. Empty string when no Canvas is active.
    canvas_id: Optional[str]
    canvas_schema_context: str
    # scope_schema: the single owning schema the investigation is pinned to (canvas
    # table-list scope OR an explicit schema-scoped run). Nodes use it to reject/repair
    # any generated SQL that references a sibling schema. "" when the run is unscoped.
    scope_schema: str

    # Investigation state
    hypotheses: list[Hypothesis]
    current_hypothesis_idx: int
    query_history: Annotated[list[QueryResult], operator.add]
    evidence_scores: Annotated[list[EvidenceScore], operator.add]

    # Accumulated pitfalls — injected into all subsequent query-planning prompts
    pitfalls: Annotated[list[Pitfall], operator.add]

    # Relevant past investigation summaries (fetched once at decompose time, via RAG).
    # This is "similar PAST investigations" — NOT the finding being drilled (see
    # origin_finding for that). Kept separate so the two never overload one channel.
    prior_analyses: list[str]

    # The specific, already-established briefing finding this investigation is DRILLING
    # (None for a cold-start question). A structured seed — set ONCE at entry and never
    # returned by any node, so it survives the whole run (a plain channel, no reducer).
    # ada_intake anchors its spec on it (metric/tables/window) instead of re-deriving,
    # and it carries provenance (insight_id) into the report. Shape:
    #   {insight_id, finding, sql, tables[], result_cells, structural[], narrative}
    origin_finding: Optional[dict]

    # Loop control
    iteration: int
    max_iterations: int

    # Output
    report: Optional[AnalysisReport]

    # final_text mode: answer from KB/ontology without SQL (MindsDB final_text path)
    final_text_answer: str

    # Human-in-the-Loop (optional — only present when hitl_enabled=True)
    hitl_enabled: bool
    human_feedback: Optional[str]

    # Routing: set by route_question node; None until classified
    query_mode: Optional[Literal["direct", "investigate", "explore", "final_text"]]
    route_reasoning: Optional[str]
    route_confidence: Optional[float]
    # Deterministic complexity assessment → cost-tiered routing (Part 2). The tier the
    # run was routed at, its score, and whether the question looked under-specified
    # (the seam a later clarification step gates on).
    route_complexity_tier: Optional[str]
    route_complexity_score: Optional[float]
    route_ambiguous: Optional[bool]

    # Consistency check: contradictions found before synthesis (investigate mode only)
    unresolved_tensions: list[str]

    # Data portrait produced by exploratory_scan before decompose (investigate mode only)
    scan_context: str

    # Business calendar events relevant to the investigation window (set by exploratory_scan)
    events_context: str

    # Canonical entity/metric definitions decided once at the start of a run and
    # reused by every downstream planning/synthesis step so figures stay consistent
    # across stages (e.g. "unique customer = customer_unique_id"). Set by the
    # decompose step in both explore and investigate modes.
    analysis_ledger: str

    # Structured Data Catalog (MindsDB-style): compact markdown with column defs
    # + 5-row samples for only the relevant tables. Built once per investigation.
    data_catalog: str

    # Adaptive replan decision produced after each score_evidence (investigate mode only)
    replan_decision: Optional[ReplanDecision]

    # Explore mode state (only when query_mode == "explore")
    sub_questions: list[SubQuestion]
    current_subq_idx: int
    subq_answers: Annotated[list[SubQuestionAnswer], operator.add]
    explore_report: Optional[ExplorationReport]

    # Liveness recorder (Bet 0): each guard appends its name when it actually runs, so
    # synthesize can prove which checks fired (defeats class-E silent failures).
    verification_checks: Annotated[list[str], operator.add]

    # Per-sub-question data portrait produced by exploratory_scan_subq.
    # Key = subq.id, value = formatted markdown paragraph of discovery results.
    subq_data_portrait: dict[str, str]

    # ADA investigate mode state (only when query_mode == "investigate")
    investigation_phases: list[InvestigationPhaseResult]
    answer_report: Optional[AnswerReport]
    _ada_intake: Optional[dict]      # intake spec passed between ADA phase nodes

    # Plan-then-SQL: set by plan_queries, consumed by execute_planned_queries
    current_plan: Optional[dict]

    # ADA inter-phase signals (set by each phase node, read by routers + next phases)
    _baseline_summary: Optional[str]
    _baseline_passes: Optional[str]
    _baseline_significant: Optional[bool]  # code-level (stats.py) significance flag
    _baseline_sigma: Optional[float]       # z-score magnitude from stats.py
    _decomp_summary: Optional[str]
    _decomp_passes: Optional[str]
    _dimensional_summary: Optional[str]
    _dimensional_passes: Optional[str]     # dominant finding → seeds Tier-3 targeting
    _behavioral_summary: Optional[str]

    # AL-05 (Semantic plane) — the SemanticContext resolved once at seed (metrics · ontology ·
    # profile · KB), carried so every node reads one consistent context instead of re-consulting
    # ad-hoc. NotRequired + None when the semantic.resolve_live flag is off (the default).
    semantic_context: NotRequired[Optional[Any]]
