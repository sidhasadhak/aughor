"""Pydantic models for a Specialist Pack (P0).

The folder layout IS the definition (convention over configuration); these models mirror
the anatomy in docs/DOMAIN_EXPERTISE_PACKS.md §3. Every model ignores unknown fields so a
pack author can add forward-looking keys without breaking the loader.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_GRAINS = ("cohort", "period", "point")
_STATUSES = ("draft", "active", "deprecated")
#: IP-1 — the knowledge layers a package carries (ROADMAP §3.17 "Layers"). An INDUSTRY
#: package holds one industry's curated knowledge; a FUNCTION (finance, marketing,
#: product, customer) is read by every industry; a BASE is what every analysis shares.
#: "" is every other pack: an ontology, an organisation function group, an engine.
KNOWLEDGE_LAYERS = ("industry", "function", "base")
#: IP-3 — the package anatomy a pack declares (`anatomy:` in pack.yaml; ROADMAP §3.17 "The package"). 0 is every pack
#: written before it; 1 is the anatomy the static gate (`aughor/packs/gate3.py`) holds a package to: cited sources,
#: metrics as formulas over role attributes with a sourced sane range, bound plays, and goldens on a named dataset.
ANATOMY_VERSIONS = (0, 1)
#: The three kinds of play a package carries (§3.17): what to investigate when a metric moves, what to check the
#: number itself for, and a move for the business.
PLAY_KINDS = ("diagnostic", "data_quality", "practice")
#: The units a metric's value is stated in, so a measured value and its sane range are read the same way.
METRIC_UNITS = ("ratio", "percent", "minutes", "hours", "miles", "count", "currency", "number")
#: The kinds of attribute a role carries. `currency` is an amount of money: a balance, or income over a period.
ATTRIBUTE_TYPES = ("flag", "number", "count", "currency", "minutes", "hours", "miles", "date", "time", "code", "text")


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
    #: One sentence a roster shows: what this pack carries.
    description: str = ""
    #: IP-1 — the knowledge layer this pack is a package of (`KNOWLEDGE_LAYERS`), or "".
    #: A package's `kb/*.json` and (for an industry) `industry.json` are what the agents
    #: read as reference, resolved by `aughor/packs/knowledge.py` — the one reader that
    #: replaced the four hard-coded `data/kb` loaders.
    layer: str = ""
    #: IP-1 — the closed industry id an INDUSTRY package carries ("airline",
    #: "food_delivery" — the ids `industry_scope` returns). "" for every other layer.
    industry: str = ""
    #: IP-3 — the package anatomy this pack declares (`ANATOMY_VERSIONS`); 1 puts it under the static gate.
    anatomy: int = 0

    @property
    def steers(self) -> bool:
        """Whether this pack can steer an answer: active, and not a knowledge package. A knowledge package's
        `status` says whether the agents read it as reference (§3.17 gate 6: a person's review moves a draft
        to active); it never makes it a pack a question is routed to, disclosed as or read through."""
        return self.status == "active" and self.layer not in KNOWLEDGE_LAYERS


class MetricBinds(_Base):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)


class SaneRange(_Base):
    """IP-3 — the band a metric's value is plausible in, the population and period that band was published for
    (`basis`), and the sources that published it. A band is a claim like any other: the static gate refuses one
    without a source, and gate 4 checks what it measures against it."""
    min: Optional[float] = None
    max: Optional[float] = None
    basis: str = ""
    sources: list[str] = Field(default_factory=list)


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
    #: IP-3 — the name a person reads ("On-time arrival rate"); `name` stays the id plays and goldens bind to.
    title: str = ""
    #: IP-3 — what the value is stated in (`METRIC_UNITS`).
    unit: str = ""
    #: IP-3 — the sourced band the value is plausible in.
    sane_range: Optional[SaneRange] = None


class RoleAttribute(_Base):
    """IP-3 — one attribute a role carries: a flight's `cancelled` flag, its `arrival_delay` in minutes. A formula
    names it `{{role.flight.cancelled}}`; a dataset's binding maps it to that dataset's column."""
    type: str = "text"
    description: str = ""


class RoleSpec(_Base):
    """One entry in `entities.yaml` — a declared ROLE (customer, event, cohort_anchor…),
    never a table. The resolver (P1) maps roles → concrete tables/columns at deploy."""
    description: str = ""
    expects: dict = Field(default_factory=dict)
    default: Optional[str] = None
    one_of: list[str] = Field(default_factory=list)
    #: IP-3 — the attributes a formula may name on this role.
    attributes: dict[str, RoleAttribute] = Field(default_factory=dict)


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
    #: IP-3 — a stable id, the kind of play (`PLAY_KINDS`) and the sources behind it.
    id: str = ""
    kind: str = ""
    sources: list[str] = Field(default_factory=list)
    #: IP-3 — for a data-quality play: an aggregate over role attributes that counts the rows showing the pitfall's
    #: shape (a flight arriving three hours before its schedule). Gate 4 runs it; a count is exposure, not a defect.
    detection: str = ""


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


class ExpectedPromise(_Base):
    """A promise the core expects a stage to carry (ON-9) — with its TERMS left to the business: whether it dispatches
    in two days or five, and which deadline column it keeps, only the business knows. `within_days` stays empty in a
    core map; `deadline_hints` are the column-name fragments a per-object deadline is usually spelled with, and
    `grain` the object it is usually kept per (a marketplace keeps a shipping limit per order LINE)."""
    name: str = ""
    kind: Literal["within_days", "deadline"] = "within_days"
    within_days: Optional[int] = None
    deadline_hints: list[str] = Field(default_factory=list)
    grain: str = ""


class ExpectedStage(_Base):
    """One stage of an expected process: its name, and the column-name fragments the moment an object reaches it is
    usually spelled with, in preference order."""
    name: str
    timestamp_hints: list[str] = Field(default_factory=list)
    promise: Optional[ExpectedPromise] = None


class ExpectedProcess(_Base):
    """A process the core expects an object to go through (ON-9): its stages in order, where each one's moment is
    usually found, and where a business usually makes a promise. A CLAIM like everything in the map — matched to this
    graph's moments by name, never declared on its own; a person declares the process and the platform counts it."""
    name: str
    object: str
    stages: list[ExpectedStage] = Field(default_factory=list)
    description: str = ""


class ExpectedRule(_Base):
    """A definition the core expects the business to hold (ON-9) — a value set over a field (a market like DACH), or
    a named condition — with its values left EMPTY, like `aliases`: the core knows the business groups these values,
    and only the business knows how."""
    name: str
    object: str
    kind: Literal["value_set", "condition"] = "value_set"
    property_hint: str = ""
    values: list[str] = Field(default_factory=list)
    description: str = ""


class PackOntology(_Base):
    """`ontology.yaml` — the approximate map of an industry, as claims to measure (§3.15 ON-0a)."""
    objects: list[ExpectedObject] = Field(default_factory=list)
    links: list[ExpectedLink] = Field(default_factory=list)
    lifecycles: list[ExpectedLifecycle] = Field(default_factory=list)
    aliases: list[ExpectedAliases] = Field(default_factory=list)
    #: ON-9 — the processes the core expects, with placeholder promises, and the definitions it expects a business to hold.
    processes: list[ExpectedProcess] = Field(default_factory=list)
    rules: list[ExpectedRule] = Field(default_factory=list)


class PackEval(_Base):
    """`evals/*.yaml` — a golden question + expected behaviour (per-pack scored suite).

    IP-3 — a golden on a named public dataset carries, in `expect`: `metric` (a pack metric's name), `dataset` (a
    `datasets/*.yaml` id), `where` (a filter over role attributes), `value` and `tolerance` (the published figure
    the recipe must reproduce, in the metric's unit) and `source` (the `sources.yaml` id that published it). Gate 4
    computes it with no model."""
    question: str
    expect: dict = Field(default_factory=dict)


class SourceFigure(_Base):
    """One figure a source publishes, with the words it was published in."""
    label: str = ""
    value: Optional[float] = None
    unit: str = ""
    quote: str = ""


class PackSource(_Base):
    """IP-3 — `sources.yaml`: a cited source a sane range, a play or a golden rests on. A benchmark is a measurement
    with a date and a population, so a source carries when it was published and when it was read."""
    id: str = ""
    title: str = ""
    publisher: str = ""
    url: str = ""
    published: str = ""        # ISO date
    retrieved: str = ""        # ISO date
    figures: list[SourceFigure] = Field(default_factory=list)
    notes: str = ""

    @field_validator("published", "retrieved", mode="before")
    @classmethod
    def _date_as_text(cls, value):
        """YAML reads an unquoted 2019-03-29 as a date; keep it as the ISO text an author wrote."""
        return value.isoformat() if isinstance(value, date) else value


class DatasetRoleBinding(_Base):
    """How a dataset holds one role: the table (after its load statements) and a column per attribute."""
    table: str = ""
    columns: dict[str, str] = Field(default_factory=dict)


class PackDataset(_Base):
    """IP-3 — `datasets/*.yaml`: a named public dataset the package is measured on (gate 4). The one place a package
    names tables: what the public file holds, how it is loaded, and how its columns bind the package's roles."""
    id: str = ""
    title: str = ""
    source: str = ""           # the sources.yaml id describing the dataset
    url: str = ""
    bytes: int = 0
    sha256: str = ""
    licence: str = ""
    member: str = ""           # the file to read inside a downloaded archive
    load: list[str] = Field(default_factory=list)      # DuckDB statements; {data} is the extracted file's path
    binding: dict[str, DatasetRoleBinding] = Field(default_factory=dict)
    measures: list[str] = Field(default_factory=list)  # the metrics this dataset can measure


class PackFunctionGroup(_Base):
    """The function group a pack ships (HB-6, §6 24 c). `id` defaults to the pack id at
    install; it must be a group slug because it lands inside `group:<id>` principals."""
    id: str = ""
    name: str = ""
    description: str = ""


class PackGrant(_Base):
    """One default grant the function layer ships: the group gets `privilege` on
    `securable`. Privileges are the rbac ladder's words (view/subscribe/edit/manage/own)."""
    securable: str
    privilege: str = "subscribe"


class PackFunction(_Base):
    """`function.yaml` — the function layer a pack ships (HB-6): its group, its
    subscriptions and default grants, and its automations.

    `automations` stays a list of RAW mappings on purpose: each entry is validated at
    install by constructing the real `Automation` model, so the automations plane keeps
    its one set of save-time laws and no field silently vanishes behind a thinner copy
    declared here (the `extra="ignore"` trap the manifest's VA-1 note documents).
    The pack's `domains` double as the layer's tags: install subscribes the group to
    `domain:<value>` for each one — grants by tag are what make a function group
    self-maintaining (§6 24 b)."""
    group: PackFunctionGroup = Field(default_factory=PackFunctionGroup)
    #: Securables the group is subscribed to (a subscription IS a subscribe-level grant).
    subscriptions: list[str] = Field(default_factory=list)
    grants: list[PackGrant] = Field(default_factory=list)
    automations: list[dict] = Field(default_factory=list)


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
    function: Optional[PackFunction] = None          # function.yaml — the group the pack ships (HB-6)
    sources: list[PackSource] = Field(default_factory=list)    # sources.yaml (IP-3)
    datasets: list[PackDataset] = Field(default_factory=list)  # datasets/*.yaml (IP-3)
    path: str = ""                                   # source folder

    @property
    def id(self) -> str:
        return self.manifest.id


# Re-exported for validators / callers that want the allowed enums.
VALID_GRAINS = _GRAINS
VALID_STATUSES = _STATUSES
