"""Ontology-related prompts for M12b semantic enrichment."""

ENRICH_ONTOLOGY_PROMPT = """\
You are building a semantic ontology for a business data warehouse.
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


#: ON-7b — the explorer that maps the BUSINESS first (ROADMAP §3.15, the second movement). It proposes; the platform
#: measures every claim before anything lands, and a person confirms. Bump `aughor.ontology.explorer.EXPLORER_VERSION`
#: when this changes — it is the `@<version>` of every proposal's provenance.
EXPLORE_BUSINESS_PROMPT = """\
You are mapping the BUSINESS behind a data warehouse — the things the business speaks of and how they relate — on top
of a catalogue of its tables. Today every table is its own entity, because the platform made one per table. A business
does not speak that way: an order HAS lines, a payment and a shipment; a return HAS its logistics record; a customer
HAS support tickets; a product HAS a price history. Say which tables are one business thing, and which things relate —
then the processes the business's objects go through, and the sets of objects it names.

You PROPOSE. The platform measures every proposal against the data before it lands — whether a column really carries
an entity's key, how many of its objects it reaches, whether two columns ever hold the same values — and refuses what
the data does not hold. A person confirms what survives. Propose what the catalogue supports, spelling every entity
id, table and column exactly as the catalogue spells them.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PARTS  (parts)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A PART is a table whose rows each belong to ONE object of another entity and are not a business thing on their own:
an order's lines, its payment, its shipment; a return's logistics record; a customer's support tickets; a product's
price readings. For each part:
  • entity — the id of the entity it belongs to, from the catalogue (e.g. Order)
  • table — the part's table, as listed
  • key — the part table's column that holds the ENTITY's key (order_items.order_id for Order)
  • name — how the business speaks of it, snake_case: lines, payment, shipment, logistics, tickets, price_history
  • time_column — only when its rows are readings over time (a price history's valid_from); otherwise ""
  • rollups — only when there are MANY rows per object: what the business counts or sums for each object, e.g.
    {{"property": "units", "column": "quantity", "agg": "sum"}} or
    {{"property": "line_count", "column": "order_item_id", "agg": "count"}}; agg is sum, avg, min, max or count
  • reason — one short sentence
Rules:
  • A table others refer to as a thing in its own right — a product, a customer, a brand, a warehouse, a country, a
    date — is an ENTITY, never a part.
  • The MEASURED BY THE DATA lines are the platform's own counts: a table carrying an entity's key on many rows per
    object is a strong part candidate; one row per object (a payment per order) can be a part too.
  • A part belongs to exactly one entity, and to a top-level one: never make a part of a part.
  • Skip everything under ALREADY DECLARED.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINKS  (links)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Relations the business names that the JOINS list does not already hold: an order is placed_by a customer, a shipment
ships_from a warehouse. For each:
  • from_entity, to_entity — entity ids from the catalogue
  • verb — snake_case, read from → to: placed_by, ships_from, sold_by, located_in
  • from_column — a column of from_entity's OWN table; to_column — a column of to_entity's OWN table that holds the
    same values (a name joins a name, an id joins an id — read the sample values)
  • reason — one short sentence
Skip any pair of columns the JOINS list already joins.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROCESSES  (processes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A PROCESS is the stages one entity's objects move through, in order: an order is placed, then shipped, then delivered.
For each:
  • id — snake_case: order_fulfilment
  • entity — the entity whose objects go through it, from the catalogue
  • display_name — how the business names it
  • stages — in order, at least two; each {{"name": snake_case, "timestamp": a date or timestamp column of the entity}},
    or where only the lifecycle records it {{"name": ..., "state": [values], "property": the lifecycle column}} —
    spelling each state exactly as the lifecycle line lists it
  • reason — one short sentence
Propose the stages alone: how fast the business promises to move through them is the business's to say.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES  (rules)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A RULE is a set of objects the business names. Two kinds:
  • value_set — the values of one dimension column grouped under one name:
    {{"id": "dach", "entity": "Customer", "kind": "value_set", "property": "country", "values": ["DE", "AT", "CH"]}} —
    spelling every value exactly as the column's sample values spell them
  • condition — filters on the entity's columns:
    {{"id": "fulfilled_orders", "entity": "Order", "kind": "condition",
      "conditions": [{{"path": "status", "op": "not_in", "values": ["cancelled", "refunded"]}}]}};
    op is =, !=, >, >=, <, <=, in, not_in, is_null or not_null
Each with a reason — one short sentence. A rule that admits no object, or every object, is refused.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENTITIES  (entities) — rarely needed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Only for a business thing NO table stands for yet, read through ONE SELECT that returns one row per object:
  • id — PascalCase; display_name; description — one sentence; domain
  • sql — one SELECT over catalogue tables, no semicolon, one row per object
    (e.g. SELECT DISTINCT category FROM products)
  • key — the SELECT's column that names one object
  • reason — one short sentence
Most catalogues need none. Never declare an entity over a table the catalogue already lists.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{catalogue}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return five flat lists — entities, parts, links, processes, rules. Omit rather than guess: a proposal the data refutes
is refused.
"""
