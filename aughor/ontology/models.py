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
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ComputedProperty(BaseModel):
    id: str                  # snake_case: "days_since_last_order"
    label: str               # human-readable: "Days Since Last Order"
    formula_sql: str         # SELECT-clause expression, e.g. "DATEDIFF('day', MAX(created_at), NOW())"
    unit: str = ""           # "days", "%", "$", etc.


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

    # Temporal
    created_at_col: Optional[str] = None      # primary event-time column

    # Business rules — extracted from glossary caveats
    default_filters: list[str] = Field(default_factory=list)
    exclude_when: list[str] = Field(default_factory=list)  # human-readable descriptions

    # Per-entity derived KPIs (LLM-generated, one SELECT-clause expression each)
    computed_properties: list[ComputedProperty] = Field(default_factory=list)


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


class OntologyAction(BaseModel):
    id: str                                    # "get_active_orders"
    display_name: str
    description: str
    entity: str                                # entity this acts on
    action_type: Literal["filter", "compute", "traverse", "aggregate", "validate"]
    sql_template: str                          # complete, ready-to-run SQL (no params for M12a)
    parameters: dict[str, Any] = Field(default_factory=dict)
    business_rules_enforced: list[str] = Field(default_factory=list)
    returns: str                               # description of what the SQL returns
    source_table: str                          # primary table this queries


class OntologyGraph(BaseModel):
    connection_id: str
    schema_fingerprint: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    enriched: bool = False                     # True after M12b LLM enrichment pass
    enrichment_version: int = 0               # bump when enrichment prompt/schema changes

    entities: dict[str, OntologyEntity] = Field(default_factory=dict)
    relationships: dict[str, OntologyRelationship] = Field(default_factory=dict)
    metrics: dict[str, OntologyMetric] = Field(default_factory=dict)
    actions: dict[str, OntologyAction] = Field(default_factory=dict)

    # Fast-lookup reverse maps
    entity_to_tables: dict[str, list[str]] = Field(default_factory=dict)
    table_to_entity: dict[str, str] = Field(default_factory=dict)
    relationship_index: dict[str, list[str]] = Field(default_factory=dict)

    def entity_for_table(self, table: str) -> Optional[OntologyEntity]:
        eid = self.table_to_entity.get(table)
        return self.entities.get(eid) if eid else None

    def actions_for_entity(self, entity_id: str) -> list[OntologyAction]:
        return [a for a in self.actions.values() if a.entity == entity_id]
