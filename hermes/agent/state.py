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
    verdict: Literal["confirmed", "refuted", "inconclusive", "untested"] = "untested"
    key_finding: str = ""


class RouteDecision(BaseModel):
    mode: Literal["direct", "investigate"]
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
    queries: list[str] = Field(
        description="1-3 SQL SELECT queries that together confirm or refute this hypothesis. Use only tables and columns from the provided schema."
    )
    reasoning: str = Field(
        description="Why these specific queries test this hypothesis"
    )


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


class SQLFix(BaseModel):
    fixed_sql: str = Field(description="The corrected SELECT query. Must be valid for the target dialect.")
    fix_explanation: str = Field(description="One sentence explaining what was wrong and the general rule to avoid it")
    data_quality_issue: Optional[str] = Field(
        default=None,
        description="If the error reveals a data quality problem in the underlying data, describe it concisely. Otherwise null."
    )


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

class AgentState(TypedDict):
    question: str
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
