"""Pydantic models for the Business/Industry Profile.

These are the LLM's structured output (content only). Persistence metadata
(connection_id, generated_at, model) is added by the store layer, not the LLM —
keeping this model clean so instructor never tries to fabricate those fields.
"""
from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field


class NorthStarMetric(BaseModel):
    """A KPI that matters for THIS industry, grounded in the real schema.

    `unit_or_range` is load-bearing: it lets downstream sanity-checks catch the
    nonsense the generic explorer produced (a "conversion rate" of 1.42, a
    revenue figure of 5.69e-11) by knowing what a sane value looks like.
    """
    name: str = Field(description="Metric name, e.g. 'Average Order Value', 'Load Factor'")
    definition: str = Field(description="Plain-English definition / formula")
    maps_to: str = Field(description="The REAL tables/columns this is computed from (must exist in the schema)")
    why_it_matters: str = Field(description="Why an operator in this industry watches this")
    unit_or_range: str = Field(description="Expected unit and sane range, e.g. 'ratio 0-1', 'USD', 'days', 'percent 0-100'")


class BusinessProfile(BaseModel):
    """What kind of business this dataset represents, and what matters for it."""
    industry: str = Field(description="Specific industry/vertical, e.g. 'DTC Beauty E-commerce', 'Commercial Aviation', 'B2B SaaS'")
    business_model: str = Field(description="e.g. transactional-retail, subscription, marketplace, freight, ad-supported")
    summary: str = Field(description="1-2 sentence characterization of the business")
    north_star_metrics: List[NorthStarMetric] = Field(
        description="6-8 KPIs that matter MOST for this industry, each grounded in real columns"
    )
    key_questions: List[str] = Field(
        description="6-8 canonical questions an analyst in THIS vertical asks, answerable from this data"
    )
    confidence: float = Field(description="0-1 confidence in the industry classification")
    evidence: str = Field(description="Which schema signals (tables/columns) led to this inference")
