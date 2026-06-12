"""
Data models for the proactive schema explorer.
All are lightweight dataclasses — no Pydantic overhead at exploration time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def elapsed_seconds(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[float]:
    """Seconds between two ISO timestamps, or None if either is missing/unparseable.
    Used for the time-to-first-insight KPI (B-6)."""
    if not start_iso or not end_iso:
        return None
    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        return round((end - start).total_seconds(), 1)
    except (ValueError, TypeError):
        return None


class ExplorationPhase(str, Enum):
    PENDING            = "pending"
    NULL_MEANING       = "null_meaning"
    JOIN_VERIFICATION  = "join_verification"
    LIFECYCLE_MAPPING  = "lifecycle_mapping"
    DISTRIBUTION       = "distribution"
    CROSS_TABLE        = "cross_table"
    DOMAIN_INTEL       = "domain_intel"
    COMPLETE           = "complete"
    FAILED             = "failed"


class NullMeaning(str, Enum):
    NOT_APPLICABLE          = "not_applicable"           # always populated (null_rate == 0)
    PENDING                 = "pending"                  # event hasn't happened yet
    NOT_APPLICABLE_TERMINAL = "not_applicable_terminal"  # terminal state — event will never happen
    MISSING                 = "missing"                  # data quality issue
    MIXED                   = "mixed"                    # pattern varies by status
    UNKNOWN                 = "unknown"                  # couldn't determine


class DistributionShape(str, Enum):
    FRACTION_0_1  = "fraction_0_1"    # bounded ratio / percentage (0 – 1)
    SKEWED_RIGHT  = "skewed_right"    # long right tail (revenue, profit)
    SKEWED_LEFT   = "skewed_left"
    CONCENTRATED  = "concentrated"    # most values near the mean or zero
    UNIFORM       = "uniform"
    BIMODAL       = "bimodal"
    NORMAL        = "normal"
    UNKNOWN       = "unknown"


@dataclass
class NullMeaningResult:
    table: str
    column: str
    null_rate: float
    meaning: NullMeaning
    business_rule: Optional[str] = None   # "NULL when status IN ('canceled','pending')"
    evidence_sql: Optional[str] = None


@dataclass
class JoinVerificationResult:
    from_table: str
    from_col: str
    to_table: str
    to_col: str
    orphan_count: int
    fk_distinct: int
    pk_distinct: int
    verified: bool       # True when orphan_count == 0
    cardinality: str     # "1:1" | "N:1" | "1:N" | "N:N"


@dataclass
class LifecycleTransition:
    from_state: str
    to_state: str
    count: int


@dataclass
class LifecycleMap:
    table: str
    status_column: str
    states: list[str]
    terminal_states: list[str]
    active_states: list[str]
    transitions: list[LifecycleTransition]   # empty for grain-verified (static) tables


@dataclass
class DistributionProfile:
    table: str
    column: str
    shape: DistributionShape
    p25: Optional[float] = None
    p50: Optional[float] = None
    p75: Optional[float] = None
    pct_zero: Optional[float] = None
    mean: Optional[float] = None


@dataclass
class OntologyInsight:
    id: str
    entities_involved: list[str]
    dimensions: list[str]
    measures: list[str]
    finding: str
    sql: str
    confidence: float
    domain: str = ""
    angle: str = ""
    novelty: int = 3
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ExplorationStatus:
    connection_id: str
    phase: ExplorationPhase = ExplorationPhase.PENDING
    paused: bool = False
    canvas_id: Optional[str] = None

    tables_total: int = 0
    columns_total: int = 0
    joins_total: int = 0

    null_meanings_resolved: int = 0
    joins_verified: int = 0
    lifecycles_mapped: int = 0
    distributions_profiled: int = 0
    insights_found: int = 0
    queries_executed: int = 0
    facts_discovered: int = 0
    domain_budgets: dict = field(default_factory=dict)   # {domain: queries_used}
    domain_coverage: dict = field(default_factory=dict)  # {domain: [angles_covered]}

    started_at: Optional[str] = None
    # Time-to-first-insight KPI (B-6): when the FIRST insight from any phase
    # (cross-table Phase 7 or domain-intel Phase 8) was discovered. Lets the
    # connect→first-insight funnel be measured instead of being all-or-nothing.
    first_insight_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

    # Phase 8 (domain intelligence) can be skipped when its prerequisite ontology
    # fails to build — without this the run still completes with 0 insights and the
    # UI can't tell "never generated" from "couldn't generate". Surface the reason.
    domain_intel_skipped: bool = False
    domain_intel_note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "phase": self.phase.value if isinstance(self.phase, ExplorationPhase) else self.phase,
            "paused": self.paused,
            "canvas_id": self.canvas_id,
            "tables_total": self.tables_total,
            "columns_total": self.columns_total,
            "joins_total": self.joins_total,
            "null_meanings_resolved": self.null_meanings_resolved,
            "joins_verified": self.joins_verified,
            "lifecycles_mapped": self.lifecycles_mapped,
            "distributions_profiled": self.distributions_profiled,
            "insights_found": self.insights_found,
            "queries_executed": self.queries_executed,
            "facts_discovered": self.facts_discovered,
            "domain_budgets": self.domain_budgets,
            "domain_coverage": self.domain_coverage,
            "started_at": self.started_at,
            "first_insight_at": self.first_insight_at,
            "first_insight_seconds": elapsed_seconds(self.started_at, self.first_insight_at),
            "completed_at": self.completed_at,
            "error": self.error,
            "domain_intel_skipped": self.domain_intel_skipped,
            "domain_intel_note": self.domain_intel_note,
        }
