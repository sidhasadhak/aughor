"""
Ontology builder — M12a Phase 1: structural extraction (no LLM).

Derives typed entities, relationships, metrics, and deterministic actions from
the existing column profiles, join map, and glossary.  Everything here is
pure computation — no LLM calls, no DB calls beyond what the profiler already ran.

Build pipeline:
  1. Entity identification  — grain-verified tables become entities
  2. Lifecycle extraction   — status/state columns → lifecycle states + active_filter
  3. Business-rule extraction — glossary caveats → default_filters
  4. Relationship mapping    — join map + cardinality from distinct counts
  5. Metric lifting          — metrics.json Catalog → OntologyMetric objects
  6. Action generation       — one deterministic filter action per entity with lifecycle
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from aughor.tools.profiler import ColumnProfile, TableProfile

from aughor.ontology.models import (
    OntologyAction,
    OntologyEntity,
    OntologyGraph,
    OntologyMetric,
    OntologyRelationship,
)

# ── Identifier helpers ────────────────────────────────────────────────────────

_WORD_BOUNDARY = re.compile(r"[_\s]+")

# Common DWH / ETL table prefixes that carry no business meaning.
_DWH_PREFIX = re.compile(
    r"^(dim|fact|fct|stg|staging|raw|mart|int|intermediate|rpt|report|"
    r"bc|tbl|tb|t|v|vw|view|src|ods|dds|dw|bi)_",
    re.IGNORECASE,
)
# Similarly strip "_fact", "_dim", "_hist" / "_history" suffixes
_DWH_SUFFIX = re.compile(r"_(fact|dim|hist|history|snapshot|snap|daily|monthly|weekly)$", re.IGNORECASE)


def _table_to_entity_name(table: str) -> str:
    """
    Convert a raw table name (possibly schema-qualified, with DWH prefixes) to
    a clean PascalCase entity id.

      orders            → Order
      order_items       → OrderItem
      dim_customer      → Customer
      fact_daily_sales  → DailySale
      bc_orders         → Order
      stg_product_catalog → ProductCatalog
    """
    # Drop schema qualifier
    base = table.rsplit(".", 1)[-1].strip()
    # Strip DWH prefixes iteratively (some tables have two: stg_dim_customer)
    for _ in range(3):
        cleaned = _DWH_PREFIX.sub("", base)
        if cleaned == base:
            break
        base = cleaned
    base = _DWH_SUFFIX.sub("", base)
    words = _WORD_BOUNDARY.split(base)
    # Singularise the last word
    last = words[-1]
    if last.endswith(("ches", "shes", "xes", "zes", "sses")) and len(last) > 4:
        words[-1] = last[:-2]
    elif last.endswith("s") and len(last) > 3:
        words[-1] = last[:-1]
    return "".join(w.capitalize() for w in words if w)


# ── Entity-type heuristics ────────────────────────────────────────────────────

_EVENT_PATTERNS = re.compile(
    r"(item|line|detail|entry|log|event|transaction|txn|payment|shipment|"
    r"movement|transfer|adjustment|audit|history|hist|snapshot)s?$",
    re.IGNORECASE,
)
_REFERENCE_PREFIX = re.compile(
    r"^(dim_|dim|dimension|lookup|reference|ref_|config|catalog|catalogue|"
    r"master|mst_|code|classification)",
    re.IGNORECASE,
)
_REFERENCE_SUFFIX = re.compile(
    r"(type|types|category|categories|status|statuses|code|codes|"
    r"lookup|reference|config|region|regions|country|countries|"
    r"currency|currencies)s?$",
    re.IGNORECASE,
)


_FACT_PREFIX = re.compile(r"^(fact|fct)_", re.IGNORECASE)


def _infer_entity_type(
    table: str,
    has_lifecycle: bool,
    grain_verified: bool,
) -> str:
    """
    Heuristic entity-type classification based on table name patterns and profile.

    Returns one of: reference_data | business_object | event | standalone
    """
    base = table.rsplit(".", 1)[-1].lower()
    # fact_ / fct_ prefix always signals an event/measure table
    if _FACT_PREFIX.match(base):
        return "event"
    if _REFERENCE_PREFIX.match(base) or _REFERENCE_SUFFIX.search(base):
        return "reference_data"
    if _EVENT_PATTERNS.search(base):
        return "event"
    if has_lifecycle:
        return "business_object"
    # Unverified grain often means composite-key line items → event
    if not grain_verified:
        return "event"
    return "business_object"


# ── Lifecycle extraction ──────────────────────────────────────────────────────

_STATUS_COL_NAMES = re.compile(
    r"(status|state|stage|phase|lifecycle|step|condition)$", re.IGNORECASE
)

# State names that mark a lifecycle terminal — no further transitions expected.
_TERMINAL_KEYWORDS = {
    "cancel", "cancelled", "canceled",
    "deliver", "delivered",
    "complet", "completed",
    "clos", "closed",
    "fail", "failed",
    "reject", "rejected",
    "return", "returned",
    "archived", "archive",
    "resolved", "done", "void",
}


def _is_terminal(state: str) -> bool:
    s = state.lower().strip()
    return any(s.startswith(kw) or s == kw for kw in _TERMINAL_KEYWORDS)


def _extract_lifecycle(
    table: str,
    column_profiles: "dict[str, ColumnProfile]",
) -> tuple[Optional[str], list[str], list[str], Optional[str]]:
    """
    Find a status/state column and extract lifecycle info.

    Returns:
      (lifecycle_column, lifecycle_states, terminal_states, active_filter)
    """
    candidates = [
        cp
        for key, cp in column_profiles.items()
        if key.startswith(f"{table}.")
        and _STATUS_COL_NAMES.search(cp.column)
        and cp.is_low_cardinality
        and cp.top_values
    ]

    if not candidates:
        return None, [], [], None

    # Pick the best candidate: prefer shorter column name (more likely to be the main status)
    cp = min(candidates, key=lambda c: len(c.column))
    states: list[str] = [str(v) for v in cp.top_values if v is not None and v != "null"]

    terminal = [s for s in states if _is_terminal(s)]
    active = [s for s in states if not _is_terminal(s)]

    if not terminal:
        return cp.column, states, [], None

    terminal_list = ", ".join(f"'{s}'" for s in terminal)
    active_filter = f"{cp.column} NOT IN ({terminal_list})"

    return cp.column, states, terminal, active_filter


# ── Default-filter extraction from glossary caveats ──────────────────────────

# Patterns that look like embedded SQL conditions in human-readable caveat text.
_FILTER_HINT = re.compile(
    r"filter\s+(with\s+)?(?:WHERE\s+)?([a-zA-Z_]+\s*(?:=|!=|<>|NOT IN|IN)\s*['\w,\s()]+)",
    re.IGNORECASE,
)
_NOT_IN_HINT = re.compile(
    r"exclude\s+([a-z_]+(?:\s+[a-z_]+)?)\s+(?:rows?|orders?|records?|items?)",
    re.IGNORECASE,
)


def _extract_default_filters(
    table: str,
    glossary: dict,
) -> tuple[list[str], list[str]]:
    """
    Parse glossary caveats for a table to extract filter hints.

    Returns (default_filters: list[SQL fragment], exclude_when: list[human text]).
    """
    default_filters: list[str] = []
    exclude_when: list[str] = []

    table_meta = glossary.get("tables", {}).get(table, {})
    if not table_meta:
        return [], []

    # Check table-level description / caveats
    sources: list[str] = []
    if table_meta.get("description"):
        sources.append(str(table_meta["description"]))

    for col_meta in (table_meta.get("columns") or {}).values():
        if col_meta.get("caveats"):
            sources.append(str(col_meta["caveats"]))

    for text in sources:
        for m in _FILTER_HINT.finditer(text):
            fragment = m.group(2).strip().rstrip(".,;")
            if fragment not in default_filters:
                default_filters.append(fragment)
        for m in _NOT_IN_HINT.finditer(text):
            description = m.group(0).strip().rstrip(".,;")
            if description not in exclude_when:
                exclude_when.append(description)

    return default_filters, exclude_when


# ── Cardinality inference from column profiles ────────────────────────────────

def _infer_cardinality(
    from_table: str,
    from_col: str,
    to_table: str,
    to_col: str,
    table_profiles: "dict[str, TableProfile]",
    column_profiles: "dict[str, ColumnProfile]",
) -> str:
    """
    Infer cardinality from distinct counts vs row counts.

    from_table is the FK-holder (e.g. orders),
    to_table is the PK-target (e.g. customers).
    Returns one of "1:1", "1:N", "N:1", "N:N".
    """
    from_tp = table_profiles.get(from_table)
    to_tp = table_profiles.get(to_table)
    from_cp = column_profiles.get(f"{from_table}.{from_col}")
    to_cp = column_profiles.get(f"{to_table}.{to_col}")

    if not from_tp or not to_tp:
        return "N:1"  # most common case — assume many-to-one

    from_rows = from_tp.row_count or 1
    to_rows = to_tp.row_count or 1

    # A side is "1" if its distinct count equals its row count (i.e. the column is unique)
    from_unique = (
        from_cp is not None and from_cp.distinct_count >= from_rows * 0.99
    )
    to_unique = (
        to_tp.grain_verified  # verified PK → definitely unique
        or (to_cp is not None and to_cp.distinct_count >= to_rows * 0.99)
    )

    if from_unique and to_unique:
        return "1:1"
    if to_unique:
        return "N:1"
    if from_unique:
        return "1:N"
    return "N:N"


# ── Metric lifting from Metrics Catalog ──────────────────────────────────────

def _lift_metrics(
    table_to_entity: dict[str, str],
) -> dict[str, OntologyMetric]:
    """
    Lift metrics from data/metrics.json into OntologyMetric objects.
    Assigns each metric to an entity based on its source tables.
    Best-effort: missing or malformed entries are silently skipped.
    """
    metrics: dict[str, OntologyMetric] = {}
    try:
        from aughor.semantic.metrics import list_metrics
        for m in list_metrics():
            entity = "unknown"
            for t in (m.tables or []):
                if t in table_to_entity:
                    entity = table_to_entity[t]
                    break
            mid = re.sub(r"[^\w]", "_", m.name.lower())
            metrics[mid] = OntologyMetric(
                id=mid,
                display_name=m.name,
                description=m.caveats or "",
                entity=entity,
                formula_sql=m.sql,
                grain=", ".join(m.dimensions or []),
                unit=m.unit or "",
                tables=m.tables or [],
            )
    except Exception:
        pass
    return metrics


# ── Action generation (deterministic, M12a only) ─────────────────────────────

def _generate_deterministic_actions(
    entities: dict[str, OntologyEntity],
    table_to_entity: dict[str, str],
) -> dict[str, OntologyAction]:
    """
    Generate one deterministic filter action for every entity that has an active_filter.
    E.g. for Order with active_filter 'order_status NOT IN (...)':
      get_active_orders() → SELECT * FROM orders WHERE order_status NOT IN (...)
    """
    actions: dict[str, OntologyAction] = {}

    for entity in entities.values():
        if not entity.active_filter or not entity.source_tables:
            continue
        table = entity.source_tables[0]
        slug = entity.id.lower()
        # Simple plural heuristic: add 's' if doesn't already end with s
        plural = table  # use the actual table name as-is (already plural)
        action_id = f"get_active_{slug}s"
        sql = f"SELECT * FROM {table}\nWHERE {entity.active_filter}"
        actions[action_id] = OntologyAction(
            id=action_id,
            display_name=f"Get Active {entity.display_name}s",
            description=(
                f"Returns all non-terminal {entity.display_name} rows. "
                f"Applies: {entity.active_filter}"
            ),
            entity=entity.id,
            action_type="filter",
            sql_template=sql,
            parameters={},
            business_rules_enforced=[f"exclude_terminal_{slug}_states"],
            returns=f"All {plural} rows that are not in a terminal lifecycle state",
            source_table=table,
        )

    return actions


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_structural_ontology(
    connection_id: str,
    schema_fingerprint: str,
    table_profiles: "dict[str, TableProfile]",
    column_profiles: "dict[str, ColumnProfile]",
    join_map: dict,           # {"joins": [...], "no_join": [...]} from _compute_join_map
    glossary: dict,
) -> OntologyGraph:
    """
    Build a structural OntologyGraph from profiler output + join map + glossary.
    No LLM calls.  All computation is deterministic.

    Raises nothing — returns a minimal/empty graph on any error.
    """
    entities: dict[str, OntologyEntity] = {}
    table_to_entity: dict[str, str] = {}

    # ── Step 1: Identify entity tables ───────────────────────────────────────
    # A table is an entity candidate if its grain column is identified.
    # We prefer grain_verified=True but also accept unverified PK candidates
    # (grain_column is set) so we don't miss entities in small datasets.

    for table, tp in table_profiles.items():
        if tp.grain_column is None:
            continue  # no PK candidate found at all — skip

        entity_id = _table_to_entity_name(table)

        # Glossary description for this table
        description = (
            glossary.get("tables", {}).get(table, {}).get("description", "")
            or ""
        )
        description = description.replace("\n", " ").strip()

        # Lifecycle
        lifecycle_col, lifecycle_states, terminal_states, active_filter = (
            _extract_lifecycle(table, column_profiles)
        )

        # Default filters from glossary
        default_filters, exclude_when = _extract_default_filters(table, glossary)

        has_lifecycle = lifecycle_col is not None
        entity_type = _infer_entity_type(table, has_lifecycle, bool(tp.grain_verified))

        # display_name starts as the entity_id; the enricher may improve it
        entity = OntologyEntity(
            id=entity_id,
            display_name=entity_id,
            description=description,
            source_tables=[table],
            identity_key=tp.grain_column,
            grain_verified=bool(tp.grain_verified),
            entity_type=entity_type,
            has_lifecycle=has_lifecycle,
            lifecycle_column=lifecycle_col,
            lifecycle_states=lifecycle_states,
            terminal_states=terminal_states,
            active_filter=active_filter,
            created_at_col=tp.primary_timestamp,
            default_filters=default_filters,
            exclude_when=exclude_when,
        )
        entities[entity_id] = entity
        table_to_entity[table] = entity_id

    entity_to_tables: dict[str, list[str]] = {
        eid: [t for t, e in table_to_entity.items() if e == eid]
        for eid in entities
    }

    # ── Step 2: Map joins to typed relationships ──────────────────────────────
    relationships: dict[str, OntologyRelationship] = {}
    relationship_index: dict[str, list[str]] = {eid: [] for eid in entities}

    for join in join_map.get("joins", []):
        t1, c1 = join["t1"], join["c1"]
        t2, c2 = join["t2"], join["c2"]
        confidence = "exact" if join.get("match") == "exact" else "inferred"

        from_entity = table_to_entity.get(t1)
        to_entity = table_to_entity.get(t2)

        # Both sides must resolve to a known entity
        if not from_entity or not to_entity or from_entity == to_entity:
            continue

        cardinality = _infer_cardinality(t1, c1, t2, c2, table_profiles, column_profiles)

        rel_id = f"{from_entity}_RELATES_TO_{to_entity}"
        # Avoid duplicate pairs
        if rel_id in relationships:
            continue

        # Is the FK column nullable?
        fk_cp = column_profiles.get(f"{t1}.{c1}")
        nullable = (fk_cp.null_rate > 0) if fk_cp else False

        rel = OntologyRelationship(
            id=rel_id,
            from_entity=from_entity,
            to_entity=to_entity,
            verb="RELATES_TO",
            cardinality=cardinality,
            join_sql=f"{t1}.{c1} = {t2}.{c2}",
            from_table=t1,
            from_col=c1,
            to_table=t2,
            to_col=c2,
            join_confidence=confidence,
            nullable=nullable,
        )
        relationships[rel_id] = rel
        relationship_index.setdefault(from_entity, []).append(to_entity)
        relationship_index.setdefault(to_entity, []).append(from_entity)

    # ── Step 3: Lift metrics from Metrics Catalog ─────────────────────────────
    metrics = _lift_metrics(table_to_entity)

    # ── Step 4: Generate deterministic actions ────────────────────────────────
    actions = _generate_deterministic_actions(entities, table_to_entity)

    return OntologyGraph(
        connection_id=connection_id,
        schema_fingerprint=schema_fingerprint,
        entities=entities,
        relationships=relationships,
        metrics=metrics,
        actions=actions,
        entity_to_tables=entity_to_tables,
        table_to_entity=table_to_entity,
        relationship_index=relationship_index,
    )


# ── Schema context rendering ──────────────────────────────────────────────────

def render_ontology_annotations(graph: OntologyGraph) -> str:
    """
    Produce a compact ENTITY MODEL block to append to the schema context string.

    Token-budget-aware: one header line + 1-3 lines per entity.
    Relationships are NOT re-emitted here (already covered by JOIN HINTS block).
    Actions are listed only by name + rule — SQL expansion happens in plan_and_execute.
    """
    if not graph.entities:
        return ""

    lines: list[str] = [
        "ENTITY MODEL (grain-verified business objects — use these rules when writing SQL):"
    ]

    for entity in sorted(graph.entities.values(), key=lambda e: e.display_name):
        table = entity.source_tables[0] if entity.source_tables else "?"
        grain_mark = "✓" if entity.grain_verified else "?"
        # Use display_name for human readability; id for SQL reference
        label = entity.display_name
        if entity.display_name != entity.id:
            label += f" [{entity.id}]"
        line = f"  {label} ({table})  grain: {entity.identity_key} {grain_mark}"
        if entity.created_at_col:
            line += f"  | event_time: {entity.created_at_col}"
        if entity.entity_type != "business_object":
            line += f"  | type: {entity.entity_type}"
        lines.append(line)

        if entity.has_lifecycle and entity.lifecycle_states:
            state_str = " → ".join(entity.lifecycle_states[:8])
            if len(entity.lifecycle_states) > 8:
                state_str += " …"
            lines.append(f"    lifecycle: {state_str}")
            if entity.terminal_states:
                t_str = ", ".join(f"'{s}'" for s in entity.terminal_states)
                lines.append(f"    terminal states: {t_str}")

        if entity.active_filter:
            lines.append(
                f"    RULE: when querying active {entity.display_name}s — "
                f"WHERE {entity.active_filter}"
            )

        if entity.default_filters:
            for f in entity.default_filters[:2]:
                lines.append(f"    NOTE: {f}")

    # Actions section
    if graph.actions:
        lines.append("")
        lines.append("ONTOLOGY ACTIONS (call with ACTION:<id>() in your query plan):")
        for action in sorted(graph.actions.values(), key=lambda a: a.id):
            lines.append(
                f"  ACTION:{action.id}()  "
                f"→ {action.description}"
            )

    return "\n".join(lines)
