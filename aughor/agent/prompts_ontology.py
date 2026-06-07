"""Ontology-related prompts for M12b semantic enrichment."""

ENRICH_ONTOLOGY_PROMPT = """\
You are building a Palantir-style semantic ontology for a business data warehouse.
You have the STRUCTURAL ONTOLOGY derived automatically from schema profiling.
Your job: enrich it with precise semantic meaning so the canvas reads like a live
business process map — not a database schema diagram.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 1 — CLEAN DISPLAY NAMES  (entity_display_names)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Provide a clean, human-facing singular noun phrase for each entity.
Rules:
  • Use Title Case proper nouns: "Customer", "Sales Order", "Product Category"
  • Remove technical artefacts: no "Dim", "Fact", "Tbl", "Bc", "Stg" in the name
  • Use domain vocabulary from the glossary when available
  • If the auto-generated name is already correct (e.g. "Order"), still include it
  • Max 3 words
Examples of corrections:
  BcOrder       → "Customer Order"
  DimProduct    → "Product"
  FactDailySale → "Daily Sale"
  OrderItem     → "Order Line"      (if context supports it)
  ProductMaster → "Product"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 2 — ENTITY TYPE CLASSIFICATION  (entity_types)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Classify each entity as ONE of:
  reference_data  — Master / lookup data others depend on.  Created independently,
                    rarely changes.  Examples: Customer, Product, Category, Region.
  business_object — Operational entity with a lifecycle / status.
                    Examples: Order, Contract, Support Ticket, Subscription.
  event           — Append-only record or transaction line item.
                    Examples: Payment, Order Line, Log Entry, Shipment Event.
  standalone      — No modelled relationships; purpose unclear from schema alone.

Signal: tables named dim_* / *_lookup / *_reference → reference_data.
        tables named *_items / *_lines / *_events / *_log → event.
        tables with a status column that has lifecycle states → business_object.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 3 — RELATIONSHIP VERBS  (relationship_verbs)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Replace generic "RELATES_TO" with a precise, lowercase, active-voice verb phrase
written from the perspective of the FROM entity.
Rules:
  • Lowercase only: "placed by", "contains", "belongs to", "ships to"
  • Max 3 words
  • Active voice from FROM entity: "Order placed by Customer", NOT "Customer has Orders"
  • The key must EXACTLY match a relationship id from the structural ontology below
Typical patterns:
  FK-holder → PK-target (N:1):  "placed by", "belongs to", "assigned to", "ships to"
  Parent → child (1:N):         "contains", "has", "includes"
  Peer ↔ peer:                   "associated with", "linked to"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 4 — ENTITY DESCRIPTIONS  (entity_descriptions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
One sentence per entity describing the business concept — not the table.
Bad:  "The orders table stores order records."
Good: "A confirmed purchase made by a customer, progressing from placed through
       fulfillment to delivery or cancellation."
Only provide descriptions you are confident about; omit if unsure.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 5 — COMPUTE & TRAVERSE ACTIONS  (action_definitions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Define at most 2 new actions per entity (skip entities that already have actions).
Priority:
  aggregate  — total revenue, average basket size, LTV
  traverse   — all orders for a customer, all line items in an order
Each action must be a complete, self-contained SELECT with no CTEs.
Only define actions where every referenced column appears in the SCHEMA below.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 6 — METRIC FORMULAS  (metric_formulas)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For any metric whose formula_sql looks wrong or incomplete, provide the canonical
SQL expression (SELECT clause only, no semicolon).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 7 — DOMAIN GROUPING  (entity_domains)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Assign each entity to a business domain. Use 2–4 domains that make sense for this
schema (e.g. "Commerce", "Customer", "Catalog", "Operations", "Finance", "Marketing").
Rules:
  • Every entity must have a domain
  • Use the same label for entities in the same domain (exact string match)
  • Max 5 words per domain label, title case
  • Prefer business vocabulary, not technical: "Customer" not "User Management"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 8 — COMPUTED PROPERTIES  (entity_computed_properties)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Define per-entity computed KPIs derived from a single entity's own table — scalar
expressions an analyst would want per-record or in aggregate.
Return a FLAT LIST of objects (NOT a nested object). Each list item MUST have:
  • entity: the entity id (PascalCase) this property belongs to — exactly as in the
    structural ontology above
  • id: snake_case, descriptive (e.g. "days_since_order", "lifetime_value")
  • label: human-readable label
  • formula_sql: SELECT-clause expression only (no FROM, no WHERE, no semicolons)
  • unit: "$", "%", "days", "count", or "" if dimensionless
Rules:
  • At most 3 per entity; use only columns in the SCHEMA for that entity's source table(s)
  • Skip entities where no meaningful computed property is possible (pure lookup tables)
  • Reject: id counts, PK columns, any formula requiring a JOIN to another table
Example (flat list — note the repeated entity key):
  [{{"entity":"Customer","id":"avg_order_value","label":"Avg Order Value","formula_sql":"SUM(amount)/COUNT(*)","unit":"$"}},
   {{"entity":"Order","id":"discount_rate","label":"Discount Rate","formula_sql":"SUM(discount)/NULLIF(SUM(gross),0)","unit":"%"}}]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRUCTURAL ONTOLOGY (auto-derived — enrich this):
{structural_summary}

GLOSSARY (business definitions and caveats):
{glossary_excerpt}

SCHEMA (column reference — only use tables/columns that appear here):
{schema}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTRAINTS:
  • Keys in entity_display_names / entity_types / entity_descriptions must EXACTLY
    match entity ids (PascalCase) from the structural ontology above.
  • Keys in relationship_verbs must EXACTLY match relationship ids above.
  • SQL in action_definitions / metric_formulas: SELECT only, no DDL/DML, no CTEs.
    Use exact table names as shown in the schema (no added schema prefixes).
  • Omit rather than hallucinate — only return fields you are confident about.
"""
