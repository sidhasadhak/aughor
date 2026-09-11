"""
Ontology data models — M12a (structural, no LLM).

Four core types (the shape came out of a study; see
docs/PALANTIR_FOUNDRY_STUDY_2026-07-22.md):
  OntologyEntity       — a business object with identity, lifecycle, and business rules
  OntologyRelationship — a typed, directional relationship between two entities
  OntologyMetric       — a computable KPI defined in terms of entities
  QueryTemplate        — a parameterized SQL template with business-rule enforcement

All fields are JSON-serialisable so the graph can be cached as plain JSON.
Pydantic is used for construction-time validation only — the store serialises
via model_dump() and deserialises via model_validate().
"""
from __future__ import annotations

import re

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, computed_field, model_validator


class ComputedProperty(BaseModel):
    id: str                  # snake_case: "days_since_last_order"
    label: str               # human-readable: "Days Since Last Order"
    formula_sql: str         # SELECT-clause expression, e.g. "DATEDIFF('day', MAX(created_at), NOW())"
    unit: str = ""           # "days", "%", "$", etc.
    # Self-validation (M24c): executed against the live DB by ontology.validator.
    # Only verified formulas are injected into the NL2SQL prompt with authority.
    verified: bool = False
    verification_note: str = ""   # why it failed, when not verified


class Segment(BaseModel):
    """A saved, named filter over one entity's rows.

    Examples:
      - "Active Orders"    filter_sql="order_status NOT IN ('canceled', 'delivered')"
      - "Delivered Orders" filter_sql="order_status = 'delivered'"
      - "All Orders"       filter_sql=""  (no filter — full table)

    Segments complement active_filter (which remains the single fast-path SQL fragment
    used by the investigation pipeline). The default segment's filter_sql is always
    kept in sync with active_filter on the parent entity.
    """
    id: str                      # snake_case: "active_orders", "delivered_orders"
    display_name: str            # "Active Orders"
    description: str = ""
    filter_sql: str = ""         # WHERE-clause fragment; empty string = all rows
    is_default: bool = False     # the primary view; filter_sql mirrors entity.active_filter
    source: Literal["lifecycle", "exploration", "manual"] = "manual"
    # Self-validation (M24c): filter_sql executed as WHERE against the live DB.
    # Empty filter_sql (all rows) is trivially verified.
    verified: bool = False
    verification_note: str = ""


class EntityProperty(BaseModel):
    """First-class property on an entity.

    Sourced from ColumnProfile at build time; description enriched from glossary.
    A property is the semantic label on a column — not the raw column itself.
    """
    name: str                           # column name as-is: "order_id", "created_at"
    display_name: str = ""             # human-readable: "Order ID", "Created At"
    data_type: str = ""                # dtype from profiler: "INTEGER", "VARCHAR", "TIMESTAMP"
    semantic_type: str = ""            # profiler semantic: "identifier", "measure", "timestamp", "dimension"
    description: str = ""             # from glossary column annotations; LLM may enrich
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_nullable: bool = False          # null_rate > 0
    null_rate: float = 0.0             # fraction of nulls in the column
    null_meaning: str = ""            # from phase-3 exploration: "event not yet occurred", "unknown", etc.
    is_derived: bool = False           # True for computed/formula columns, not raw source columns
    value_interpretation: str = ""    # "currency", "fraction 0-1", "count", "duration_days"
    measure_grain: str = ""            # additivity: "per_unit" (×qty for a line total) | "per_line" | ""
    unit: str = ""                     # "USD", "days", "%"
    sample_values: list[str] = Field(default_factory=list)   # top_values from profiler (dimensions only)
    # Distribution stats from phase-6 exploration (numeric columns only)
    distribution_shape: str = ""      # "normal", "skewed_right", "skewed_left", "uniform", "bimodal"
    p25: Optional[float] = None       # 25th percentile
    p50: Optional[float] = None       # median
    p75: Optional[float] = None       # 75th percentile


def snake_name(name: str) -> str:
    """`OrderItem` → `order_item`: the stable spelling an api_name defaults to."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name or "")
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s or "object"


class DisplayProperty(BaseModel):
    """ON-3b — the property whose value names one object of a type: a customer's `full_name`, a
    warehouse's `name`, an order's own key when nothing else names it.

    DECLARED on the type, never guessed per read: proposed from the profile when the builder leaves it
    empty (`propose_display_property`), or set by a person through the overrides tree — and MEASURED
    like every other claim since ON-0a: `rows`, `non_null` and `distinct` counted over the backing, the
    verdict and its evidence in `verified` and `note` (`aughor.ontology.display`). A refuted proposal
    gives way to the key; a person's declaration stands, its measurement shown beside it.
    """
    name: str = ""
    source: Literal["proposed", "human"] = "proposed"
    rows: Optional[int] = None
    non_null: Optional[int] = None
    distinct: Optional[int] = None
    verified: Optional[bool] = None
    note: str = ""


#: Property-name fragments that say a column names an instance, in preference order.
_NAME_HINTS = ("full_name", "display_name", "name", "title", "label")


def propose_display_property(entity: "OntologyEntity") -> DisplayProperty:
    """The display property the profile proposes: a text or dimension property named after the type itself
    (`brand` on Brand), else one whose name says it is a name (`full_name`, `product_name`, `title`), else
    the key. Deterministic and from the profile alone; whether it names objects is measured afterwards."""
    key = (entity.backing.primary_key if entity.backing is not None else "") or entity.identity_key
    candidates = [p for p in (entity.properties or {}).values()
                  if (p.semantic_type or "") in ("dimension", "text") and not p.is_primary_key
                  and (p.null_rate or 0.0) <= 0.5]
    type_words = {snake_name(entity.id), entity.api_name}
    for p in candidates:
        if p.name.lower() in type_words:
            return DisplayProperty(name=p.name, note=f"proposed: {p.name} is named after the type")
    for hint in _NAME_HINTS:
        for p in candidates:
            if hint in p.name.lower():
                return DisplayProperty(name=p.name, note=f"proposed: its name says {p.name} names an instance")
    return DisplayProperty(name=key, note="proposed: no property names an instance, so the key does")


class Backing(BaseModel):
    """What an object type is read FROM (ON-1: the noun decouples from the table).

    `table` today — the default every existing consumer reads, byte-identically — or a
    keyed SELECT (`kind="query"`) a human sets through the overrides tree, whose rows are
    the object's instances. `primary_key` is the column unique per instance; `verified`
    says the data agreed (COUNT(DISTINCT key) == COUNT(key) over the backing's rows) —
    measured, never assumed, like every other claim since ON-0a.
    """
    kind: Literal["table", "query"] = "table"
    table: Optional[str] = None
    sql: Optional[str] = None
    primary_key: str = ""
    verified: Optional[bool] = None
    verification_note: str = ""
    #: ON-3b: the rows the backing held when its key was measured — the "rows" fact the entity-type map
    #: shows. None until measured (POST /ontology/measure), never estimated from a profile.
    rows: Optional[int] = None

    def from_clause(self, alias: str = "b") -> str:
        """The FROM fragment a consumer queries this object through."""
        if self.kind == "query" and self.sql:
            return f"({self.sql.strip().rstrip(';')}) AS {alias}"
        return self.table or ""


class Binding(BaseModel):
    """ON-1b — a further source an object type's properties are read from (ROADMAP §3.15, amended 2026-09-11).

    The type's first binding IS its `backing`: the rows that are its objects. A further binding is a table or a
    keyed SELECT joined to the object on its key, with the properties it supplies, and a kind — `static` (one row
    per object) or `timeseries` (many rows per object over `time_column`). Its claim is MEASURED the ON-0a way
    (`aughor.ontology.bindings`): a static binding's key must be unique over its rows and reach objects that exist;
    a timeseries binding's key must reach objects that exist, its coverage recorded. A person sets one through the
    overrides tree; the data proposes one where another table carries the type's key, kept apart on
    `OntologyEntity.proposed_bindings` so a proposal changes nothing until a person binds it.
    """
    name: str
    kind: Literal["static", "timeseries"] = "static"
    table: Optional[str] = None
    sql: Optional[str] = None
    #: The binding's column that holds the object's key.
    key: str = ""
    #: Timeseries only: the column that places a row in time.
    time_column: str = ""
    #: Property name → the property it supplies.
    properties: dict[str, EntityProperty] = Field(default_factory=dict)
    #: Property name → the binding's column it is read from, for a property renamed to be free on the type (its
    #: `status` supplied as `payment_status`). A property not listed is read from the column of its own name.
    columns: dict[str, str] = Field(default_factory=dict)
    #: Columns the binding has but does not supply, each with why — a name the type already uses.
    skipped: dict[str, str] = Field(default_factory=dict)
    source: Literal["human", "proposed"] = "human"
    #: Measured — None until counted: the binding's rows, its rows with a key, its distinct keys, the objects it
    #: was measured against, how many of them it covers, and the distinct keys that reach no object.
    rows: Optional[int] = None
    non_null: Optional[int] = None
    distinct: Optional[int] = None
    objects: Optional[int] = None
    covered: Optional[int] = None
    orphans: Optional[int] = None
    verified: Optional[bool] = None
    note: str = ""

    @property
    def reads(self) -> str:
        """``query`` when the binding is a keyed SELECT, ``table`` otherwise."""
        return "query" if (self.sql or "").strip() else "table"


class OntologyEntity(BaseModel):
    id: str                                    # PascalCase: "Order", "Customer"
    display_name: str                          # human-readable business name, set/corrected by enricher
    description: str = ""                     # from glossary; LLM enriches in M12b
    source_tables: list[str]                  # tables that materialise this entity
    identity_key: str                          # canonical PK column, e.g. "order_id"
    grain_verified: bool                       # COUNT(*) == COUNT(DISTINCT identity_key)
    #: ON-1: the stable name the API, packs and playbooks bind to — never the table's name.
    #: Filled from the id (`OrderItem` → `order_item`) when the builder leaves it empty.
    api_name: str = ""
    #: ON-1: what this object is read FROM — one table by default (`source_tables[0]` +
    #: `identity_key`), a keyed SELECT when a human sets one. Consumers that read the
    #: table directly are unchanged; the validator and ON-2's compiler read the backing.
    backing: Optional[Backing] = None
    #: ON-3b: the property that names one instance (see DisplayProperty) — proposed from the profile when
    #: the builder leaves it empty, so every graph built before carries one; measured on the measure door.
    display_property: Optional[DisplayProperty] = None
    #: ON-1b: the further bindings a person set — tables or keyed SELECTs joined to the object on its key, each
    #: supplying properties the backing does not carry (see Binding). The first binding is `backing`; this list
    #: holds the rest, and is empty on every graph built before, which therefore loads unchanged.
    bindings: list[Binding] = Field(default_factory=list)
    #: ON-1b: the bindings the data proposes — another table carrying this type's key, measured one row per
    #: object. Kept apart so a proposal changes no query, no page and no answer until a person binds it.
    proposed_bindings: list[Binding] = Field(default_factory=list)

    # Domain grouping (e.g. "Commerce", "Customer", "Operations") — set by enricher
    domain: Optional[str] = None

    # Entity classification (set by enricher; heuristic fallback in builder)
    # reference_data  — master/lookup data referenced by others (Customer, Product, Category)
    # business_object — operational entity with state transitions (Order, Contract, Ticket)
    # event           — append-only record or line-item (Payment, OrderItem, LogEntry)
    # standalone      — no inbound or outbound relationships
    entity_type: Literal[
        "reference_data", "business_object", "event", "standalone"
    ] = "business_object"

    # Lifecycle — derived from status/state columns
    has_lifecycle: bool = False
    lifecycle_column: Optional[str] = None    # e.g. "order_status"
    lifecycle_states: list[str] = Field(default_factory=list)
    terminal_states: list[str] = Field(default_factory=list)
    active_filter: Optional[str] = None       # SQL fragment: "order_status NOT IN ('canceled')"
    #: ON-0a: the lifecycle MEASURED against the data. None until measured; False when the
    #: data contradicts it (an observed state the lists never named, or a claimed terminal
    #: state whose timestamp is set on rows now in another state); True otherwise. The note
    #: carries the evidence, and the end-state names the core expects but the terminal set
    #: omits are reported there as UNCONFIRMED — a snapshot cannot prove a state is final.
    lifecycle_verified: Optional[bool] = None
    lifecycle_note: str = ""

    # Routing guidance (Wave 2 / Layer 1.1) — "for questions of this shape, query
    # {table} rather than this entity's own table". Human-authored only: it arrives
    # through the override store, which existence-binds the named table first, and an
    # unbound value is never enforced. Shape: {"table", "scope", "reason"}. Advisory
    # by construction — enforcement ADDS the preferred table to the schema the model
    # sees and never removes the deprecated one, because scope matching is fuzzy and
    # adding information is safe where removing it is not.
    use_instead: Optional[dict] = None

    # Named segments — composable, reusable saved filters over this entity's rows.
    # Auto-generated from lifecycle states; enriched by exploration findings.
    # Keyed by Segment.id for fast lookup.
    #
    # `object_sets` stays a VALIDATION alias so every ontology already cached as JSON
    # (data/ontology_cache.json, written before the rename) still deserialises into
    # `segments` instead of silently coming back empty.
    segments: dict[str, Segment] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("segments", "object_sets"),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def object_sets(self) -> dict[str, Segment]:
        """Deprecated copy of ``segments`` — RETAINED FOR ONE RELEASE.

        Emitted by ``model_dump()`` so every consumer of the entity payload (the HTTP
        views, the JSON cache, an out-of-tree client) keeps reading the old key while it
        migrates. Delete this property — and the ``object_sets`` validation alias above —
        in the release after the one that introduced ``segments``.
        """
        return self.segments

    # Temporal
    created_at_col: Optional[str] = None      # primary event-time column

    # Business rules — extracted from glossary caveats
    default_filters: list[str] = Field(default_factory=list)
    exclude_when: list[str] = Field(default_factory=list)  # human-readable descriptions

    # First-class properties — one entry per column on the source table(s).
    # Keyed by column name. Sourced from ColumnProfile at build time;
    # description enriched from glossary.
    properties: dict[str, EntityProperty] = Field(default_factory=dict)

    # Per-entity derived KPIs (LLM-generated, one SELECT-clause expression each)
    computed_properties: list[ComputedProperty] = Field(default_factory=list)

    # Interfaces this entity implements — set by the builder's interface detector.
    # e.g. ["HasTimestamp", "HasMonetaryValue", "HasLifecycle"]
    implements: list[str] = Field(default_factory=list)

    # Top insights from phase-8 exploration, sorted by novelty desc.
    # Each entry is a plain-English finding sentence (e.g. "32 % of orders
    # never reach a terminal state — possible data pipeline gap").
    exploration_insights: list[str] = Field(default_factory=list)


    @model_validator(mode="after")
    def _fill_object_defaults(self) -> "OntologyEntity":
        if not self.api_name:
            self.api_name = snake_name(self.id)
        if self.backing is None:
            self.backing = Backing(kind="table", table=self.source_tables[0] if self.source_tables else None,
                                   primary_key=self.identity_key)
        if self.display_property is None:
            self.display_property = propose_display_property(self)
        return self

class OntologyInterface(BaseModel):
    """A shared structural shape implemented by multiple entity types.

    Interfaces let you write polymorphic queries across entity types without
    knowing specific table schemas.  Examples:
      HasTimestamp  — any entity that records event time (created_at, updated_at)
      HasMonetaryValue — any entity that carries a financial amount
      HasLifecycle  — any entity with a named status / state machine

    Auto-detected by the ontology builder from property name patterns and entity flags.
    """
    id: str                                  # "HasTimestamp", "HasMonetaryValue"
    display_name: str                        # "Has Timestamp"
    description: str = ""
    property_patterns: list[str] = Field(default_factory=list)   # human-readable pattern descriptions
    implementing_entities: list[str] = Field(default_factory=list)  # entity ids


class OntologyRelationship(BaseModel):
    id: str                                    # "Order_RELATES_TO_Customer"
    from_entity: str                           # FK-holder entity: "Order"
    to_entity: str                             # PK-target entity: "Customer"
    verb: str = "RELATES_TO"                  # placeholder; LLM enriches in M12b
    cardinality: Literal["1:1", "1:N", "N:1", "N:N"]
    join_sql: str                              # "orders.customer_id = customer.customer_id"
    from_table: str
    from_col: str
    to_table: str
    to_col: str
    join_confidence: Literal["exact", "inferred", "verified"] = "inferred"
    nullable: bool = False                     # FK col has null rows
    # Value-verification (joinable_with): the max containment fraction the two keys actually
    # SHARE, probed at build time. None = unprobed; ~1.0 = a real FK; a value-DISJOINT name
    # coincidence (≈0) is dropped from the graph entirely, never persisted as a relationship.
    value_overlap: Optional[float] = None
    #: The cardinality MEASURED against the data (ON-0a): a side is "1" when its key is unique
    #: over its non-null rows. None until measured. When it contradicts the authored label,
    #: `cardinality` is replaced by it and the authored value survives in `cardinality_note` —
    #: the block renders what the data says, never a verified-looking guess.
    measured_cardinality: Optional[Literal["1:1", "1:N", "N:1", "N:N"]] = None
    cardinality_note: str = ""
    #: ON-1: a link has a stable name on EACH side (`order_item_to_order` / `order_to_order_item`),
    #: filled from the entity ids when the builder leaves them empty.
    api_name: str = ""
    reverse_api_name: str = ""
    #: ON-3b: the business-verb link name a PERSON set through the overrides tree (`shipment_ships_order`).
    #: Empty means the name is proposed from the verb at read time (`business_name`), so an enriched verb
    #: renames the link without leaving a stale copy; the mechanical pair above stays the stable fallback
    #: every query and page still accepts.
    name: str = ""

    @model_validator(mode="after")
    def _fill_link_names(self) -> "OntologyRelationship":
        if not self.api_name:
            self.api_name = f"{snake_name(self.from_entity)}_to_{snake_name(self.to_entity)}"
        if not self.reverse_api_name:
            self.reverse_api_name = f"{snake_name(self.to_entity)}_to_{snake_name(self.from_entity)}"
        return self

    def business_name(self) -> str:
        """The link's business-verb name, read from→to: the person's when set, else `<from>_<verb>_<to>` from
        the verb on record — or "" while the verb is still the placeholder that names nothing."""
        if self.name:
            return self.name
        verb = snake_name(self.verb or "")
        if not (self.verb or "").strip() or verb in _PLACEHOLDER_VERBS:
            return ""
        return f"{snake_name(self.from_entity)}_{verb}_{snake_name(self.to_entity)}"

    def business_name_source(self) -> str:
        """``human`` when a person named the link, ``proposed`` when its verb did, "" when nothing names it."""
        return "human" if self.name else ("proposed" if self.business_name() else "")


#: ON-3b — the verb the builder writes before enrichment names nothing, so no link name is proposed from it.
_PLACEHOLDER_VERBS = frozenset({"relates_to"})
#: A business-verb link name is a path segment: snake_case, bounded.
LINK_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class DefinitionSource(BaseModel):
    """One place a definition for a metric was found, and whose it is.

    Ported from the warehouse-vendor context layer studied 2026-09-08: a business
    definition is not a fact the warehouse holds, it is a CLAIM some asset makes and some
    person is behind. When two dashboards disagree about "revenue", the useful question is
    not which string is prettier — it is which claim came from where, who stands behind
    it, and how many things already rely on it.

    🔑 What we do NOT port is ranking by authority alone. That design weighs source
    authority, reliance and freshness; we already do something strictly stronger for the
    part that matters, which is EXECUTE the formula against the live database. So
    `verified` is a tier, not a tiebreak: a verified definition outranks an unverified one
    no matter who wrote it or how popular it is. Authority only orders candidates that are
    equally verified. Popularity is evidence about people; execution is evidence about the
    data. See :mod:`aughor.ontology.authority`.
    """
    #: What THIS source says the metric is. May disagree with its siblings — that
    #: disagreement is the thing worth surfacing, not a conflict to silently resolve.
    formula_sql: str = ""
    #: The asset the claim came from, by name: "DAIS 2026 Sales Dashboard",
    #: "rpt_summit_registration", a saved query's title, a document.
    source_asset: str = ""
    source_kind: Literal["dashboard", "query", "table", "pipeline",
                         "document", "manual", "unknown"] = "unknown"
    #: WHOSE definition. Empty is honest — an unattributed claim is weaker evidence, and
    #: `authority` scores it that way rather than inventing an owner.
    author: str = ""
    recorded_at: str = ""
    #: How many things already rely on this definition. Reliance is evidence about people.
    use_count: int = 0
    #: The SOURCE is a blessed/certified asset (not: the formula is correct).
    certified: bool = False
    #: THIS formula executed successfully against the live database. The only field here
    #: that is evidence about the DATA, which is why it outranks all the others.
    verified: bool = False
    verification_note: str = ""


class OntologyMetric(BaseModel):
    id: str                                    # "revenue", "customer_ltv"
    display_name: str
    description: str = ""
    entity: str                                # which entity this belongs to
    formula_sql: str                           # canonical SQL expression
    grain: str = ""
    unit: str = ""
    tables: list[str] = Field(default_factory=list)
    known_divergent_calculations: list[str] = Field(default_factory=list)
    # Health scorecard fields (M13a)
    target_value: Optional[float] = None
    warning_threshold: Optional[float] = None   # yellow zone boundary
    critical_threshold: Optional[float] = None  # red zone boundary
    target_period: Optional[str] = None         # "monthly", "quarterly", "ytd"
    benchmark_source: Optional[str] = None      # "internal: FY2025 plan", "industry: ecommerce"
    # Self-validation (M24c): formula_sql executed against the live DB. Unverified
    # formulas are demoted (never injected with "use this exact expression").
    verified: bool = False
    verification_note: str = ""
    #: Every definition we have SEEN for this metric, with its provenance — including the
    #: ones that lost. `known_divergent_calculations` records THAT the warehouse disagrees
    #: with itself; this records WHERE each disagreeing claim came from and who is behind
    #: it, which is what a person needs to settle it. Additive and defaulted: every graph
    #: written before this field loads unchanged with an empty list.
    definitions: list[DefinitionSource] = Field(default_factory=list)


class ActionParameter(BaseModel):
    """A typed, named input to a QueryTemplate *or* to a declared, governed write action.

    Deliberately NOT renamed alongside QueryTemplate: this one type is shared by the
    read-side template (``QueryTemplate.parameters``) and the write-surface unit's
    ``params`` (the declared-action model below), and "action" is still the right word
    for the latter. Naming it ``QueryTemplateParameter`` would mislabel every declared
    write-action parameter.

    Parameters are extracted from {placeholder} tokens in the sql_template.
    Data type is inferred from column profiles where possible; falls back to VARCHAR.
    """
    name: str                           # matches {name} in sql_template
    display_name: str = ""             # "Customer ID", "Start Date"
    data_type: str = "VARCHAR"         # SQL type: "INTEGER", "VARCHAR", "DATE", "NUMERIC"
    required: bool = True
    description: str = ""
    default_value: Optional[str] = None  # serialised as string; cast at runtime
    #: ON-4 — ``value`` is a typed scalar. ``object`` names ONE object of ``object_type`` (an ON-1
    #: object type), passed as ``"<Type>:<key>"``; it is read live when the action is validated or
    #: run, and its properties reach the submission criteria as ``<param>.<property>``.
    kind: Literal["value", "object"] = "value"
    object_type: str = ""


class QueryTemplate(BaseModel):
    """A reusable, governed SQL template over one entity — read-only, never a write.

    Was ``OntologyAction``. It never acted on anything: it is a parameterized SELECT with
    business rules attached, which is what the planner reuses instead of re-deriving the
    query. "Action" now means exactly one thing (a governed write to the data), so this
    type had to give the word back — the declared-action model below is the write surface.

    The persisted spelling is frozen: these live under ``OntologyGraph.actions`` in the
    JSON cache and under ``data/learned_actions.json``, and ``action_type`` / ``origin``
    are stored values. Only the Python symbol moved.
    """
    id: str                                    # "get_active_orders"
    display_name: str
    description: str
    entity: str                                # entity this template queries
    action_type: Literal["filter", "compute", "traverse", "aggregate", "validate"]
    sql_template: str                          # SQL with optional {param} placeholders
    parameters: list[ActionParameter] = Field(default_factory=list)
    business_rules_enforced: list[str] = Field(default_factory=list)
    returns: str                               # description of what the SQL returns
    source_table: str                          # primary table this queries

    # Provenance — how this template came to exist.  Additive, non-breaking:
    #   structural — derived by the ontology builder from schema shape (default)
    #   learned    — crystallized from a repeated high-confidence investigation
    #   manual     — authored/edited by a user
    # Learned templates live in a separate {conn}:{schema}-keyed store
    # (data/learned_actions.json) that survives ontology rebuilds, and are
    # overlaid into the graph at read time.
    origin: Literal["structural", "learned", "manual"] = "structural"
    # How many times a learned skill has been reused — feeds per-skill autonomy.
    usage_count: int = 0


# ── Wave K: declared, governed actions (the kinetic plane) ───────────────────────────
# A KineticAction is DISTINCT from QueryTemplate (above, a read-side SQL-template shortcut)
# and from the notification ActionTrigger (an outbound webhook). It is the write-surface unit:
# typed parameters + submission criteria + graduated approval, composing the other two. It
# never mutates source data — its `kind` is an annotation, a side effect, or a governed read
# query. Declared by a human in the per-connection ontology overlay (overrides.py), not built.

class SubmissionCriterion(BaseModel):
    """A deterministic precondition on a KineticAction's parameters.

    ``expr`` is a restricted predicate over the action's params, evaluated DETERMINISTICALLY by
    the Wave-K executor (K2) — never by a model. ``message`` is the AUTHORED failure text shown
    VERBATIM to the human AND the LLM when the criterion fails, so it is a required, non-empty
    string that must never be paraphrased anywhere in the pipeline. A criterion missing either
    field fails validation, which rejects the whole action at parse — it never reaches the graph."""
    expr: str = Field(min_length=1)
    message: str = Field(min_length=1)


class SideEffect(BaseModel):
    """A declared consequence of a KineticAction, dispatched by the executor (K2) through an
    existing primitive: ``notify``/``webhook`` → ``actions.fire_action``, ``trigger_investigation``
    → ``runners.investigation`` (H5), which submits it as a supervised kernel job. ``config`` is
    opaque here; the executor validates it per kind — for ``trigger_investigation`` it carries the
    ``question`` (``{param}`` placeholders filled from the action's declared parameters) and
    optionally ``connection_id`` / ``schema_name`` / ``agent_id``."""
    #: DS-13 — ``http`` is the declarative custom component: a real call to a vendor's own
    #: API, described rather than coded. ``webhook`` posts AUGHOR's envelope
    #: (``{action, kind, params, config}``) to a URL, which is right for a receiver written
    #: for us and useless for one that was not — PagerDuty wants PagerDuty's body. ``http``
    #: carries method, headers, an encrypted auth header and a body TEMPLATE, so the same
    #: plane that governs a declared write can now perform one against a service nobody
    #: here wrote an adapter for. Still no ``exec``: a template is filled, never evaluated.
    kind: Literal["notify", "webhook", "trigger_investigation", "http"]
    config: dict = Field(default_factory=dict)


#: DS-13 — the config keys of an ``http`` side effect that hold a CREDENTIAL.
#:
#: Encrypted on the way into an override file and masked on the way out, which is the same
#: arrangement `ProviderApp.client_secret` and the Slack bot tokens already use. It matters
#: more here than in either: an ontology override is a FILE, and files in this repo are
#: tracked. Ciphertext under ``AUGHOR_SECRET_KEY`` — which is not in git — is what makes a
#: declared PagerDuty component safe to commit alongside the entity it belongs to.
HTTP_SECRET_FIELDS = ("auth_secret",)


def encrypt_action_secrets(fields: dict, previous: Optional[dict] = None) -> dict:
    """Encrypt the credentials in an authored action, carrying forward unchanged ones.

    A form that shows a masked secret sends the MASK back when the person edits the
    description and not the key. Storing that would replace the credential with a row of
    bullets and break the component at 03:00 — the edit-form trap this codebase has met on
    every secret-bearing record it owns. A masked or empty incoming value therefore keeps
    what is already stored, and only a genuinely new value is encrypted.
    """
    from aughor.secretvault import encrypt_secret, is_encrypted, is_masked

    prior = {}
    for se in (previous or {}).get("side_effects", []) or []:
        if isinstance(se, dict):
            prior[str(se.get("kind", ""))] = se.get("config") or {}

    out = dict(fields)
    effects = []
    for se in out.get("side_effects", []) or []:
        if not isinstance(se, dict) or se.get("kind") != "http":
            effects.append(se)
            continue
        cfg = dict(se.get("config") or {})
        for key in HTTP_SECRET_FIELDS:
            value = cfg.get(key)
            if value is None or is_masked(value) or value == "":
                kept = (prior.get("http") or {}).get(key)
                if kept:
                    cfg[key] = kept
                else:
                    cfg.pop(key, None)
            elif not is_encrypted(value):
                cfg[key] = encrypt_secret(str(value))
        effects.append({**se, "config": cfg})
    if "side_effects" in out:
        out["side_effects"] = effects
    return out


def mask_action_secrets(dumped: dict) -> dict:
    """The API-facing form of a declared action: credentials masked, never returned.

    Masked rather than dropped, unlike `Connection`'s token fields, and the difference is
    the surface: this feeds an EDIT form, which must be able to show that a credential is
    set without being able to read it. A dropped field would make "no key" and "a key you
    may not see" look identical, and the author would re-enter it every time.
    """
    from aughor.secretvault import mask_secret

    out = dict(dumped)
    effects = []
    for se in out.get("side_effects", []) or []:
        if not isinstance(se, dict) or se.get("kind") != "http":
            effects.append(se)
            continue
        cfg = dict(se.get("config") or {})
        for key in HTTP_SECRET_FIELDS:
            if cfg.get(key):
                cfg[key] = mask_secret(str(cfg[key]))
        effects.append({**se, "config": cfg})
    if "side_effects" in out:
        out["side_effects"] = effects
    return out


class ObjectEdit(BaseModel):
    """ON-4 — one property an ``annotate`` action sets on an object it takes.

    Written to the edits overlay keyed ``(object_type, key, property)`` and merged onto that object
    at read time; the source row is never touched. ``value`` and ``note`` are templates filled from
    the action's declared parameters (``{reason}``), so what an accept writes is declared by the
    author, never improvised by whoever proposed it."""
    object: str = Field(min_length=1)        # the action's `object` parameter this edit lands on
    property: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: str = ""
    note: str = ""


class KineticAction(BaseModel):
    """A declared, governed action — the Wave K write-surface unit (see the block comment above)."""
    id: str
    display_name: str = ""
    description: str = ""
    entity: str = ""                              # optional owning entity id
    kind: Literal["annotate", "side_effect", "query"]
    params: list[ActionParameter] = Field(default_factory=list)
    rule: str = ""                                # SQL template (kind="query"); empty otherwise
    submission_criteria: list[SubmissionCriterion] = Field(default_factory=list)
    side_effects: list[SideEffect] = Field(default_factory=list)
    # Risk tier for the graduated-approval gate; K2 maps this to ``govern.ActionRisk``. Default
    # HIGH is fail-safe: an unclassified declared action requires approval, never auto-fires.
    risk: Literal["read_only", "low", "high"] = "high"
    # Wave R5 — may two runs of this action proceed CONCURRENTLY? Default False, and
    # fail-safe for the same reason `risk` defaults to high: an undeclared action is not
    # dispatchable inside a fan-out. The failure this prevents is not a crash — it is two
    # refunds, or a webhook delivered twice, with no error anywhere and no SQL for the
    # read-only gate to inspect. Only a genuinely independent action (a pure query, an
    # idempotent annotate) should declare True. Checked in exactly one place:
    # `aughor.kernel.parallel_safety.assert_dispatchable`, called from the executor.
    parallel_safe: bool = False
    origin: Literal["manual", "learned", "structural"] = "manual"
    #: ON-4 — the object type this action is about, and the overlay properties an ``annotate``
    #: action sets on the objects it takes (see ObjectEdit).
    object_type: str = ""
    edits: list[ObjectEdit] = Field(default_factory=list)

    @model_validator(mode="after")
    def _objects_hold_together(self):
        taken = {p.name for p in self.params if p.kind == "object"}
        loose = [p.name for p in self.params if p.kind == "object" and not p.object_type.strip()]
        if loose:
            raise ValueError(f"object parameter {', '.join(loose)} must name its object_type")
        if self.edits and self.kind != "annotate":
            raise ValueError("only an annotate action declares edits")
        for edit in self.edits:
            if edit.object not in taken:
                raise ValueError(f"the edit setting '{edit.property}' lands on '{edit.object}', "
                                 "which is not one of this action's object parameters")
        return self


class CoreClaim(BaseModel):
    """One claim from an industry map (a pack's `ontology.yaml`), evaluated against THIS
    graph and data (§3.15 ON-0a). Tiers: `expected` (declared, not yet measurable here),
    `measured-true`, `measured-false` (the data contradicts the core — the data wins),
    `human` (an override settled it). Never rendered into a prompt: what reaches the model
    is the measured label on the relationship or entity itself."""
    kind: Literal["object", "link", "lifecycle", "alias"]
    subject: str
    expected: str
    measured: Optional[str] = None
    tier: Literal["expected", "measured-true", "measured-false", "human"] = "expected"
    provenance: str = ""                       # "pack:<id>"
    note: str = ""


class OntologyGraph(BaseModel):
    connection_id: str
    schema_name: str = ""          # DB schema this ontology covers (e.g. "analytics", "public")
    schema_fingerprint: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    enriched: bool = False                     # True after M12b LLM enrichment pass
    enrichment_version: int = 0               # bump when enrichment prompt/schema changes
    validated: bool = False                    # True after M24c semantic self-validation pass
    validation_version: int = 0               # bump when validator logic changes

    entities: dict[str, OntologyEntity] = Field(default_factory=dict)
    relationships: dict[str, OntologyRelationship] = Field(default_factory=dict)
    #: ON-0a: the industry map's claims, evaluated here (see CoreClaim). Kept beside the
    #: graph so a UI can show what the core expected and what the data said, per tier.
    core_claims: list[CoreClaim] = Field(default_factory=list)
    metrics: dict[str, OntologyMetric] = Field(default_factory=dict)
    # Key frozen as `actions`: it is a persisted JSON key in data/ontology_cache.json and
    # the shape of GET /ontology/actions. The TYPE is a QueryTemplate (see above).
    actions: dict[str, QueryTemplate] = Field(default_factory=dict)
    # Wave K: human-declared governed actions, overlaid at read time (kept separate from the
    # read-side `actions` dict above so the two "action" concepts never collide). Additive —
    # defaults empty, so an old JSON-cached graph deserialises unchanged.
    kinetic_actions: dict[str, KineticAction] = Field(default_factory=dict)
    interfaces: dict[str, OntologyInterface] = Field(default_factory=dict)

    # Fast-lookup reverse maps
    entity_to_tables: dict[str, list[str]] = Field(default_factory=dict)
    table_to_entity: dict[str, str] = Field(default_factory=dict)
    relationship_index: dict[str, list[str]] = Field(default_factory=dict)

    def entity_for_table(self, table: str) -> Optional[OntologyEntity]:
        eid = self.table_to_entity.get(table)
        return self.entities.get(eid) if eid else None

    def actions_for_entity(self, entity_id: str) -> list[QueryTemplate]:
        return [a for a in self.actions.values() if a.entity == entity_id]

    def declared_actions(self) -> list:
        """The human-declared governed actions overlaid on this graph, in id order — the write
        surface's roster, read without reaching into the dict every consumer used to spell out."""
        declared = self.kinetic_actions
        return [declared[action_id] for action_id in sorted(declared)]
