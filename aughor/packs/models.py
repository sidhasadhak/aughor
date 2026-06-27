"""Pydantic models for a Specialist Pack (P0).

The folder layout IS the definition (convention over configuration); these models mirror
the anatomy in docs/DOMAIN_EXPERTISE_PACKS.md §3. Every model ignores unknown fields so a
pack author can add forward-looking keys without breaking the loader.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

_GRAINS = ("cohort", "period", "point")
_STATUSES = ("draft", "active", "deprecated")


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PackManifest(_Base):
    """`pack.yaml` — identity, persona, routing weight, scope."""
    id: str
    name: str = ""
    version: int = 1
    persona: str = ""
    owner_team: str = ""
    default_temporal_grain: str = "period"        # cohort | period | point
    domains: list[str] = Field(default_factory=list)
    extends: list[str] = Field(default_factory=list)
    scope: dict = Field(default_factory=lambda: {"connections": ["*"]})
    status: str = "draft"                          # draft | active | deprecated


class MetricBinds(_Base):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)


class PackMetric(_Base):
    """`metrics/*.yaml` — a grounded metric recipe (same shape as the industry KB) plus a
    role-binding hint (`binds`) that references entity ROLES, never columns."""
    name: str
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    unit_or_range: str = ""
    formula: str = ""
    grain: str = ""
    anti_patterns: list[str] = Field(default_factory=list)
    binds: MetricBinds = Field(default_factory=MetricBinds)


class RoleSpec(_Base):
    """One entry in `entities.yaml` — a declared ROLE (customer, event, cohort_anchor…),
    never a table. The resolver (P1) maps roles → concrete tables/columns at deploy."""
    description: str = ""
    expects: dict = Field(default_factory=dict)
    default: Optional[str] = None
    one_of: list[str] = Field(default_factory=list)


class PackQuestions(_Base):
    """`questions.yaml` — drives routing (question→pack) and proactive Explorer angles."""
    canonical: list[str] = Field(default_factory=list)
    diagnostic: list[str] = Field(default_factory=list)
    explorer_angles: list[str] = Field(default_factory=list)
    intent_tags: list[str] = Field(default_factory=list)


class PackPlaybook(_Base):
    """`playbooks/*.yaml` — same shape as PlaybookEntry; seeded by the pack."""
    trigger_metric: str = ""
    trigger_condition: str = ""
    trigger_operator: str = ""
    recommendation: str = ""
    expected_impact: str = ""
    owner_role: str = ""
    tags: list[str] = Field(default_factory=list)


class PackSurface(_Base):
    """`surface.yaml` — the expert's dedicated view, composed of chart primitives."""
    title: str = ""
    panels: list[dict] = Field(default_factory=list)


class PackEval(_Base):
    """`evals/*.yaml` — a golden question + expected behaviour (per-pack scored suite)."""
    question: str
    expect: dict = Field(default_factory=dict)


class Pack(_Base):
    """A fully-loaded specialist pack."""
    manifest: PackManifest
    expertise: str = ""                              # expertise.md (markdown persona)
    metrics: list[PackMetric] = Field(default_factory=list)
    entities: dict[str, RoleSpec] = Field(default_factory=dict)
    questions: PackQuestions = Field(default_factory=PackQuestions)
    playbooks: list[PackPlaybook] = Field(default_factory=list)
    surface: Optional[PackSurface] = None
    evals: list[PackEval] = Field(default_factory=list)
    path: str = ""                                   # source folder

    @property
    def id(self) -> str:
        return self.manifest.id


# Re-exported for validators / callers that want the allowed enums.
VALID_GRAINS = _GRAINS
VALID_STATUSES = _STATUSES
