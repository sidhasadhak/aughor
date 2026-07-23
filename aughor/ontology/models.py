"""
Ontology data models — M12a (structural, no LLM).

Four core object types mirror a Palantir-style ontology:
  OntologyEntity      — a business object with identity, lifecycle, and business rules
  OntologyRelationship — a typed, directional relationship between two entities
  OntologyMetric      — a computable KPI defined in terms of entities
  OntologyAction      — a parameterized SQL template with business-rule enforcement

All fields are JSON-serialisable so the graph can be cached as plain JSON.
Pydantic is used for construction-time validation only — the store serialises
via model_dump() and deserialises via model_validate().
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ComputedProperty(BaseModel):
    id: str                  # snake_case: "days_since_last_order"
    label: str               # human-readable: "Days Since Last Order"
    formula_sql: str         # SELECT-clause expression, e.g. "DATEDIFF('day', MAX(created_at), NOW())"
    unit: str = ""           # "days", "%", "$", etc.
    # Self-validation (M24c): executed against the live DB by ontology.validator.
    # Only verified formulas are injected into the NL2SQL prompt with authority.
    verified: bool = False
    verification_note: str = ""   # why it failed, when not verified


class ObjectSet(BaseModel):
    """A named, reusable filtered view of an entity's rows — mirrors Palantir's Object Set concept.

    Examples:
      - "Active Orders"    filter_sql="order_status NOT IN ('canceled', 'delivered')"
      - "Delivered Orders" filter_sql="order_status = 'delivered'"
      - "All Orders"       filter_sql=""  (no filter — full table)

    object_sets complement active_filter (which remains the single fast-path SQL fragment
    used by the investigation pipeline). The default object set's filter_sql is always
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
    """First-class property on an entity — mirrors Palantir's Property concept.

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


class OntologyEntity(BaseModel):
    id: str                                    # PascalCase: "Order", "Customer"
    display_name: str                          # human-readable business name, set/corrected by enricher
    description: str = ""                     # from glossary; LLM enriches in M12b
    source_tables: list[str]                  # tables that materialise this entity
    identity_key: str                          # canonical PK column, e.g. "order_id"
    grain_verified: bool                       # COUNT(*) == COUNT(DISTINCT identity_key)

    # Domain grouping (e.g. "Commerce", "Customer", "Operations") — set by enricher
    domain: Optional[str] = None

    # Palantir-style entity classification (set by enricher; heuristic fallback in builder)
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

    # Named object sets — composable, reusable filters over this entity's rows.
    # Auto-generated from lifecycle states; enriched by exploration findings.
    # Keyed by ObjectSet.id for fast lookup.
    object_sets: dict[str, ObjectSet] = Field(default_factory=dict)

    # Temporal
    created_at_col: Optional[str] = None      # primary event-time column

    # Business rules — extracted from glossary caveats
    default_filters: list[str] = Field(default_factory=list)
    exclude_when: list[str] = Field(default_factory=list)  # human-readable descriptions

    # First-class properties — one entry per column on the source table(s).
    # Keyed by column name. Sourced from ColumnProfile at build time;
    # description enriched from glossary. Mirrors Palantir's Property concept.
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


class OntologyInterface(BaseModel):
    """A shared structural shape implemented by multiple entity types — mirrors Palantir's Interface concept.

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


class ActionParameter(BaseModel):
    """A typed, named input to an OntologyAction — mirrors Palantir's Action parameter concept.

    Parameters are extracted from {placeholder} tokens in the sql_template.
    Data type is inferred from column profiles where possible; falls back to VARCHAR.
    """
    name: str                           # matches {name} in sql_template
    display_name: str = ""             # "Customer ID", "Start Date"
    data_type: str = "VARCHAR"         # SQL type: "INTEGER", "VARCHAR", "DATE", "NUMERIC"
    required: bool = True
    description: str = ""
    default_value: Optional[str] = None  # serialised as string; cast at runtime


class OntologyAction(BaseModel):
    id: str                                    # "get_active_orders"
    display_name: str
    description: str
    entity: str                                # entity this acts on
    action_type: Literal["filter", "compute", "traverse", "aggregate", "validate"]
    sql_template: str                          # SQL with optional {param} placeholders
    parameters: list[ActionParameter] = Field(default_factory=list)
    business_rules_enforced: list[str] = Field(default_factory=list)
    returns: str                               # description of what the SQL returns
    source_table: str                          # primary table this queries

    # Provenance — how this action came to exist.  Additive, non-breaking:
    #   structural — derived by the ontology builder from schema shape (default)
    #   learned    — crystallized from a repeated high-confidence investigation
    #   manual     — authored/edited by a user
    # Learned actions live in a separate {conn}:{schema}-keyed store
    # (data/learned_actions.json) that survives ontology rebuilds, and are
    # overlaid into the graph at read time.
    origin: Literal["structural", "learned", "manual"] = "structural"
    # How many times a learned skill has been reused — feeds per-skill autonomy.
    usage_count: int = 0


# ── Wave K: declared, governed actions (the kinetic plane) ───────────────────────────
# A KineticAction is DISTINCT from OntologyAction (above, a read-side SQL-template shortcut)
# and from the ActionHub ActionTrigger (an outbound webhook). It is the write-surface unit:
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
    → ``kernel().submit``. ``config`` is opaque here; the executor validates it per kind."""
    kind: Literal["notify", "webhook", "trigger_investigation"]
    config: dict = Field(default_factory=dict)


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
    origin: Literal["manual", "learned", "structural"] = "manual"


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
    metrics: dict[str, OntologyMetric] = Field(default_factory=dict)
    actions: dict[str, OntologyAction] = Field(default_factory=dict)
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

    def actions_for_entity(self, entity_id: str) -> list[OntologyAction]:
        return [a for a in self.actions.values() if a.entity == entity_id]
