"""Pydantic models for a Specialist Pack (P0).

The folder layout IS the definition (convention over configuration); these models mirror
the anatomy in docs/DOMAIN_EXPERTISE_PACKS.md §3. Every model ignores unknown fields so a
pack author can add forward-looking keys without breaking the loader.
"""
from __future__ import annotations

from typing import Literal, Optional

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
    # VA-1 — provenance for a pack that came from somewhere else. Declared HERE because
    # `_Base` ignores unknown fields: written to pack.yaml and absent from the model,
    # these would vanish on load and the pack would silently lose its origin.
    source: str = ""                               # e.g. "awesome-agent-skills"
    source_url: str = ""
    licence: str = ""
    #: Prose only — no entities, metrics or goldens. An imported skill supplies
    #: one layer of a pack, and a surface must be able to say so rather than presenting a
    #: specialist that silently knows nothing about your data.
    partial: bool = False


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


class ExpectedObject(_Base):
    """An object type the industry map EXPECTS — matched to this schema's tables by name and
    alias, never invented. `roles` name what the object does (party, transaction, event…)."""
    name: str
    roles: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    description: str = ""


class ExpectedLink(_Base):
    """A link the map expects between two objects, with the cardinality the data must
    CONFIRM (from:to — many from-rows per to-row is N:1) and the key it is expected on."""
    from_object: str
    to_object: str
    cardinality: Literal["1:1", "1:N", "N:1", "N:N"] = "N:1"
    via: str = ""                       # the key column both sides are expected to carry
    to_side_optional: bool = False      # a from-row may have NO to-row (an order without a shipment)
    description: str = ""


class ExpectedLifecycle(_Base):
    """A lifecycle the map expects on an object: the column it usually lives in, the states
    a business usually has, the ones it expects to be terminal, and the END-STATE NAMES —
    words that read as final — which the lifecycle measurement reports as unconfirmed when
    a built terminal set omits them. Every entry is a claim; none is rendered as fact."""
    object: str
    column_hint: str = ""
    states: list[str] = Field(default_factory=list)
    terminal_states: list[str] = Field(default_factory=list)
    end_state_names: list[str] = Field(default_factory=list)


class ExpectedAliases(_Base):
    """A field the core declares HAS business-specific aliases — and leaves them EMPTY. The
    core knows that `country` is spelled many ways; only the business knows which spellings
    are its own (a market like DACH is not a country)."""
    field: str
    values: dict[str, list[str]] = Field(default_factory=dict)


class PackOntology(_Base):
    """`ontology.yaml` — the approximate map of an industry, as claims to measure (§3.15 ON-0a)."""
    objects: list[ExpectedObject] = Field(default_factory=list)
    links: list[ExpectedLink] = Field(default_factory=list)
    lifecycles: list[ExpectedLifecycle] = Field(default_factory=list)
    aliases: list[ExpectedAliases] = Field(default_factory=list)


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
    ontology: Optional[PackOntology] = None          # ontology.yaml — the core the business extends
    path: str = ""                                   # source folder

    @property
    def id(self) -> str:
        return self.manifest.id


# Re-exported for validators / callers that want the allowed enums.
VALID_GRAINS = _GRAINS
VALID_STATUSES = _STATUSES
