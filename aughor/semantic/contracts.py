"""The one governed-metric contract (REC-U10).

Aughor carries a governed metric as *two* pydantic shapes that are the same concept
built twice: `semantic.metrics.MetricDefinition` (the human-curated catalog — the
approve/version governance surface) and `ontology.models.OntologyMetric` (the metric the
ontology builder derives + self-verifies from the data). They overlap almost entirely —
identifier, label, canonical SQL, tables, unit, and a byte-identical health-scorecard block
— yet planning, enforcement, and display each special-case both.

`SemanticContract` is the canonical union both serialize to (this is Part 1's #1 "20-year
ontology bet" — one metric type the whole platform points at). This module is **additive**:
it introduces the contract + the two adapters (`from_metric_definition` /
`from_ontology_metric`) and does NOT yet repoint any consumer — that migration is invasive
and lands incrementally behind a flag. What lands here is the type + a lossless-where-it-
matters bridge, with tests pinning the field mapping.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # avoid import cost / any cycle at module load — adapters import lazily
    from aughor.ontology.models import OntologyMetric
    from aughor.profile.models import NorthStarMetric
    from aughor.semantic.metrics import MetricDefinition


class SemanticContract(BaseModel):
    """One governed metric, source-agnostic — what the platform may trust and how to
    compute + present it. Built via the adapters, never hand-constructed in the hot path."""

    # Identity + computation
    key: str = Field(description="Stable snake_case identifier (MetricDefinition.name / OntologyMetric.id)")
    label: str = Field(description="Human display name")
    sql: str = Field(description="Canonical SQL expression (the approved/verified formula)")
    source: Literal["catalog", "profile", "ontology"] = Field(
        description="Which representation this was serialized from — the three governed-metric stores")
    description: str = ""

    # Shape / presentation
    unit: Optional[str] = None
    grain: Optional[str] = None                    # ontology carries this explicitly; catalog infers it
    tables: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)

    # Correctness guardrails
    caveats: Optional[str] = None
    additivity: Optional[str] = None               # "additive" | "non_additive" | None (infer)
    known_divergent_calculations: list[str] = Field(
        default_factory=list,
        description="Anti-patterns / wrong-usage examples — the 'never compute it this way' rules.",
    )

    # Health scorecard (identical in both source models)
    target_value: Optional[float] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    target_period: Optional[str] = None
    benchmark_source: Optional[str] = None

    # Governance / trust
    owner: Optional[str] = None
    approved_by: Optional[str] = None
    status: str = "draft"                           # draft | proposed | approved | deprecated
    version: int = 0
    verified: bool = False                          # SQL executed clean against the live DB
    verification_note: str = ""

    @property
    def is_trusted(self) -> bool:
        """Whether the SQL may be injected as 'use this exact expression'. Governance approval
        (catalog) OR live self-verification (ontology) each earn trust."""
        return self.verified or self.status == "approved"

    @property
    def rank(self) -> int:
        """Precedence when the same `key` resolves from more than one store — higher wins.
        Mirrors the legacy `canonical._SOURCE_RANK`: a human-curated catalog metric outranks the
        connection's governed north-star, which outranks a self-verified ontology formula, which
        outranks an unverified one. This is the dedup authority the whole platform points at."""
        if self.source == "catalog":
            return 4
        if self.source == "profile":
            return 3
        return 2 if self.verified else 1        # ontology: verified outranks unverified

    @property
    def injectable(self) -> bool:
        """Whether this formula renders as an authoritative 'use this EXACT SQL' line — the
        legacy `CanonicalMetric.verified` render policy, preserved byte-for-byte: catalog and
        profile SQL are authoritative by provenance (a human/audit wrote them); an ontology
        formula is authoritative only once the builder has self-verified it against live data.
        (Governance-tightening a draft catalog metric out of this set is a deliberate future
        step tracked under U10 — this property intentionally does NOT gate on `status`.)"""
        return self.source in ("catalog", "profile") or self.verified

    # ── Adapters — the single bridge each source crosses to become the one contract ──────────

    @classmethod
    def from_metric_definition(cls, md: "MetricDefinition") -> "SemanticContract":
        """Serialize a curated catalog metric. Its lifecycle `status` is the trust signal
        (an approved metric is trusted); `wrong_usage_examples` are the divergence rules."""
        return cls(
            key=md.name,
            label=md.label,
            sql=md.sql,
            source="catalog",
            unit=md.unit,
            tables=list(md.tables),
            dimensions=list(md.dimensions),
            filters=list(md.filters),
            caveats=md.caveats,
            additivity=md.additivity,
            known_divergent_calculations=list(md.wrong_usage_examples),
            target_value=md.target_value,
            warning_threshold=md.warning_threshold,
            critical_threshold=md.critical_threshold,
            target_period=md.target_period,
            benchmark_source=md.benchmark_source,
            owner=md.owner,
            approved_by=md.approved_by,
            status=md.status,
            version=md.version,
            verified=(md.status == "approved"),
        )

    @classmethod
    def from_ontology_metric(cls, om: "OntologyMetric") -> "SemanticContract":
        """Serialize an ontology-derived metric. Its `verified` flag is the trust signal
        (a self-validated formula is trusted); it maps to an approved/draft lifecycle."""
        return cls(
            key=om.id,
            label=om.display_name,
            sql=om.formula_sql,
            source="ontology",
            description=om.description,
            unit=om.unit or None,
            grain=om.grain or None,
            tables=list(om.tables),
            known_divergent_calculations=list(om.known_divergent_calculations),
            target_value=om.target_value,
            warning_threshold=om.warning_threshold,
            critical_threshold=om.critical_threshold,
            target_period=om.target_period,
            benchmark_source=om.benchmark_source,
            status=("approved" if om.verified else "draft"),
            verified=om.verified,
            verification_note=om.verification_note,
        )

    @classmethod
    def from_north_star_metric(cls, nsm: "NorthStarMetric") -> "SemanticContract":
        """Serialize a connection's governed north-star metric (the BusinessProfile's build-time-
        audited KPI formulas — the same `value_sql` the Briefing/KPI strip run). These are
        authoritative by provenance: governed + audited at build time, so `verified=True` /
        `status="approved"`. `definition` is the plain-English caveat; `unit_or_range` the unit.
        Maps the same fields the legacy `CanonicalMetric` profile-governed row carried."""
        return cls(
            key=nsm.name,
            label=nsm.name,
            sql=nsm.value_sql,
            source="profile",
            description=nsm.definition,
            unit=nsm.unit_or_range or None,
            caveats=(nsm.definition or "")[:160],
            status="approved",
            verified=True,
        )


def _norm_key(key: str) -> str:
    """Normalize a contract key for dedup — mirrors `canonical._norm` (so "Net Revenue" and
    "net_revenue" collapse to the same metric across stores)."""
    return (key or "").strip().lower().replace(" ", "_").replace("-", "_")


def dedup_by_rank(contracts) -> list["SemanticContract"]:
    """Collapse same-key contracts to the highest-`rank` source, sorted by key — the ONE dedup
    authority both the planning resolver (`canonical.resolve_contracts`) and the display path
    (`SemanticContext.contracts`) share, so a metric resolves to the same governed definition
    everywhere. Skips entries with an empty key or empty SQL. Order-independent: precedence is
    by `rank`, never insertion order (catalog > profile > verified ontology > unverified)."""
    by_key: dict[str, "SemanticContract"] = {}
    for c in contracts:
        if not (getattr(c, "key", "") or "").strip() or not (getattr(c, "sql", "") or "").strip():
            continue
        k = _norm_key(c.key)
        cur = by_key.get(k)
        if cur is None or c.rank > cur.rank:
            by_key[k] = c
    return sorted(by_key.values(), key=lambda c: c.key)
