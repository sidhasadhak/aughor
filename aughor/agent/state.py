from __future__ import annotations

from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict

from pydantic import BaseModel, Field
import operator


# ── Pydantic output schemas (structured LLM responses) ──────────────────────

class Hypothesis(BaseModel):
    id: str
    description: str
    confidence: float = 0.0
    verdict: Literal["confirmed", "refuted", "inconclusive", "untested", "skipped"] = "untested"
    key_finding: str = ""


class RouteDecision(BaseModel):
    mode: Literal["direct", "investigate", "explore"]
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


class StatResult(BaseModel):
    type: str
    interpretation: str
    is_significant: bool
    sigma: Optional[float] = None
    p_value: Optional[float] = None


class QueryResult(BaseModel):
    hypothesis_id: str
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    error: Optional[str] = None
    stats: list[StatResult] = Field(default_factory=list)
    # Predictions set at plan time; carried through for comparison at score time
    expected_if_true: Optional[str] = None
    expected_if_false: Optional[str] = None


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


class ExplorationReport(BaseModel):
    headline: str = Field(description="One sentence direct answer to the original question. Board-ready.")
    conclusion: str = Field(description="2-3 sentence explanation of the answer with supporting numbers.")
    narrative: str = Field(description="Flowing paragraph connecting all sub-questions into a coherent story.")
    recommended_actions: list[str] = Field(description="Concrete next steps based on the findings.")
    data_quality_notes: list["DataQualityNote"] = Field(default_factory=list)


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
    table: str
    column: Optional[str]
    issue: str
    impact: str
    recommended_fix: str


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


class ADARecommendation(TypedDict):
    action: str
    expected_impact: str
    owner: str
    timeline: str


class ADAReport(TypedDict):
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
    recommendations: list[ADARecommendation]
    data_gaps: list[str]


class AgentState(TypedDict):
    question: str
    connection_id: str
    schema_context: str

    # Investigation state
    hypotheses: list[Hypothesis]
    current_hypothesis_idx: int
    query_history: Annotated[list[QueryResult], operator.add]
    evidence_scores: Annotated[list[EvidenceScore], operator.add]

    # Accumulated pitfalls — injected into all subsequent query-planning prompts
    pitfalls: Annotated[list[Pitfall], operator.add]

    # Relevant past investigation summaries (fetched once at decompose time)
    prior_analyses: list[str]

    # Loop control
    iteration: int
    max_iterations: int

    # Output
    report: Optional[AnalysisReport]

    # Human-in-the-Loop (optional — only present when hitl_enabled=True)
    hitl_enabled: bool
    human_feedback: Optional[str]

    # Routing: set by route_question node; None until classified
    query_mode: Optional[Literal["direct", "investigate"]]
    route_reasoning: Optional[str]
    route_confidence: Optional[float]

    # Consistency check: contradictions found before synthesis (investigate mode only)
    unresolved_tensions: list[str]

    # Data portrait produced by exploratory_scan before decompose (investigate mode only)
    scan_context: str

    # Business calendar events relevant to the investigation window (set by exploratory_scan)
    events_context: str

    # Adaptive replan decision produced after each score_evidence (investigate mode only)
    replan_decision: Optional[ReplanDecision]

    # Explore mode state (only when query_mode == "explore")
    sub_questions: list[SubQuestion]
    current_subq_idx: int
    subq_answers: Annotated[list[SubQuestionAnswer], operator.add]
    explore_report: Optional[ExplorationReport]

    # ADA investigate mode state (only when query_mode == "investigate")
    investigation_phases: list[InvestigationPhaseResult]
    ada_report: Optional[ADAReport]
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
