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

import logging
import re
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aughor.tools.profiler import ColumnProfile, TableProfile

from aughor.ontology.models import (
    ActionParameter,
    EntityProperty,
    ObjectSet,
    OntologyAction,
    OntologyEntity,
    OntologyGraph,
    OntologyInterface,
    OntologyMetric,
    OntologyRelationship,
)
from aughor.tools.table_names import bare, leaf, resolve_in

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
    # Drop schema qualifier (case-preserved leaf — feeds PascalCasing below)
    base = leaf(table)
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
    base = bare(table)
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

# Columns whose low-cardinality values are geographic/ISO codes, not lifecycle
# states.  E.g. customer_state = "SP", seller_state = "CA" look like status
# columns but carry no process meaning.
_GEO_COL_EXCLUDE = re.compile(
    r"(country|state|region|city|province|prefecture|territory|locale|"
    r"_country_code|_state_code|_iso|_geo)$",
    re.IGNORECASE,
)

# Heuristic terminal-state keywords — used ONLY for lifecycle annotation,
# NOT for auto-generating active_filter.  The enricher LLM or the user
# decides which states should be filtered; these keywords just label states
# as "likely terminal" in the ontology display.
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
        and not _GEO_COL_EXCLUDE.search(cp.column)   # skip geographic columns
        and cp.is_low_cardinality
        and cp.top_values
    ]

    if not candidates:
        return None, [], [], None

    # Pick the best candidate: prefer shorter column name (more likely to be the main status)
    cp = min(candidates, key=lambda c: len(c.column))

    # Filter out values that look like geographic codes (2-letter ISO), formula
    # strings (contain "/" or operators), or multi-word phrases — these are not
    # lifecycle states.
    def _is_valid_state(v: object) -> bool:
        s = str(v).strip()
        if not s or s == "null":
            return False
        if "/" in s:                              # formula strings: "Revenue / Ad Spend"
            return False
        if re.fullmatch(r"[A-Z]{2}", s):          # bare 2-letter ISO codes: SP, CA, NY
            return False
        if len(s) > 30:                           # descriptions, not state identifiers
            return False
        return True

    states: list[str] = [str(v) for v in cp.top_values if _is_valid_state(v)]

    # Final column-level guard: real lifecycle states are terse (avg ≤ 15 chars,
    # avg word count ≤ 2).  KPI names / descriptions fail both.
    if states:
        avg_len = sum(len(s) for s in states) / len(states)
        avg_words = sum(len(s.split()) for s in states) / len(states)
        if avg_len > 15 or avg_words > 2:
            return None, [], [], None

    # If the filter removed everything meaningful, discard this candidate entirely
    if not states:
        return None, [], [], None

    terminal = [s for s in states if _is_terminal(s)]

    # Do NOT auto-generate active_filter from keyword heuristics.
    # Terminal states are annotated for display / LLM context, but filtering
    # is only applied when the user asks or the enricher LLM explicitly sets it.
    return cp.column, states, terminal, None


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


# ── Action parameter extraction ───────────────────────────────────────────────

# SQL type mapping from profiler dtype → SQL type for ActionParameter
_DTYPE_TO_SQL: dict[str, str] = {
    "INTEGER": "INTEGER", "BIGINT": "BIGINT", "INT": "INTEGER",
    "FLOAT": "NUMERIC", "DOUBLE": "NUMERIC", "NUMERIC": "NUMERIC", "DECIMAL": "NUMERIC",
    "DATE": "DATE", "TIMESTAMP": "TIMESTAMP", "DATETIME": "TIMESTAMP",
    "BOOLEAN": "BOOLEAN", "BOOL": "BOOLEAN",
    "VARCHAR": "VARCHAR", "TEXT": "VARCHAR", "STRING": "VARCHAR",
}

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _extract_action_parameters(
    sql_template: str,
    entity: "OntologyEntity",
) -> list[ActionParameter]:
    """
    Scan sql_template for {param_name} placeholders and build a typed parameter list.

    Data type inference order:
      1. Exact match on entity.properties column name → use that column's dtype
      2. Suffix heuristics (_id → INTEGER, _date/_at → DATE, _amount/_price → NUMERIC)
      3. Default → VARCHAR
    """
    seen: set[str] = set()
    params: list[ActionParameter] = []

    for m in _PLACEHOLDER_RE.finditer(sql_template):
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)

        # Try to match against a known property on the entity
        prop = entity.properties.get(name)
        if prop and prop.data_type:
            raw_dtype = prop.data_type.upper().split("(")[0].strip()
            sql_type = _DTYPE_TO_SQL.get(raw_dtype, "VARCHAR")
            description = prop.description or f"Value for {prop.display_name or name}"
        else:
            # Heuristic fallback from parameter name suffix
            low = name.lower()
            if low.endswith("_id") or low == "id":
                sql_type = "VARCHAR"
            elif low.endswith(("_date", "_at", "_time", "_ts")):
                sql_type = "DATE"
            elif low.endswith(("_amount", "_price", "_revenue", "_cost", "_value")):
                sql_type = "NUMERIC"
            elif low.endswith(("_count", "_qty", "_quantity", "_num")):
                sql_type = "INTEGER"
            else:
                sql_type = "VARCHAR"
            description = ""

        params.append(ActionParameter(
            name=name,
            display_name=_display_name_for_col(name),
            data_type=sql_type,
            required=True,
            description=description,
        ))

    return params


# ── Action generation (deterministic, M12a only) ─────────────────────────────

def _generate_deterministic_actions(
    entities: dict[str, OntologyEntity],
    table_to_entity: dict[str, str],
) -> dict[str, OntologyAction]:
    """
    Generate deterministic actions for every entity:
      • filter action  — for entities with an active_filter or lifecycle (get_active_*)
      • lookup action  — for every entity with a primary key (get_{entity}_by_id)

    Parameters are extracted from {placeholder} tokens in the SQL template.
    """
    actions: dict[str, OntologyAction] = {}

    for entity in entities.values():
        if not entity.source_tables:
            continue
        table = entity.source_tables[0]
        slug = entity.id.lower()

        # ── Filter action (active rows) ───────────────────────────────────────
        # Use active_filter if set; fall back to deriving it from terminal_states
        _active_filter = entity.active_filter
        if not _active_filter and entity.terminal_states and entity.lifecycle_column:
            tl = ", ".join(f"'{s}'" for s in entity.terminal_states)
            _active_filter = f"{entity.lifecycle_column} NOT IN ({tl})"

        if _active_filter:
            action_id = f"get_active_{slug}s"
            sql = f"SELECT * FROM {table}\nWHERE {_active_filter}"
            actions[action_id] = OntologyAction(
                id=action_id,
                display_name=f"Get Active {entity.display_name}s",
                description=(
                    f"Returns all non-terminal {entity.display_name} rows. "
                    f"Applies: {_active_filter}"
                ),
                entity=entity.id,
                action_type="filter",
                sql_template=sql,
                parameters=_extract_action_parameters(sql, entity),
                business_rules_enforced=[f"exclude_terminal_{slug}_states"],
                returns=f"All {table} rows that are not in a terminal lifecycle state",
                source_table=table,
            )

        # ── Lookup action (get by primary key) ────────────────────────────────
        if entity.identity_key:
            pk = entity.identity_key
            action_id = f"get_{slug}_by_id"
            sql = f"SELECT * FROM {table}\nWHERE {pk} = {{{pk}}}"
            actions[action_id] = OntologyAction(
                id=action_id,
                display_name=f"Get {entity.display_name} by ID",
                description=f"Fetch a single {entity.display_name} row by its primary key.",
                entity=entity.id,
                action_type="filter",
                sql_template=sql,
                parameters=_extract_action_parameters(sql, entity),
                business_rules_enforced=[],
                returns=f"One {table} row matching the given {pk}",
                source_table=table,
            )

    return actions


# ── Property extraction ───────────────────────────────────────────────────────

def _display_name_for_col(col: str) -> str:
    """Convert snake_case column name to Title Case display name."""
    return " ".join(w.capitalize() for w in col.replace("-", "_").split("_"))


def _build_entity_properties(
    table: str,
    grain_column: str,
    column_profiles: "dict[str, ColumnProfile]",
    glossary: dict,
) -> "dict[str, EntityProperty]":
    """
    Build the EntityProperty dict for an entity from its column profiles.

    - Primary key status comes from grain_column match.
    - FK status comes from ColumnProfile.is_fk.
    - Descriptions are pulled from the glossary column annotations if present.
    - sample_values are only included for low-cardinality dimension columns
      (avoids bloating the ontology with thousands of ID values).
    """
    props: dict[str, EntityProperty] = {}
    table_glossary_cols = (
        glossary.get("tables", {}).get(table, {}).get("columns") or {}
    )

    for key, cp in column_profiles.items():
        if not key.startswith(f"{table}."):
            continue

        col = cp.column
        gloss = table_glossary_cols.get(col, {}) or {}
        description = str(gloss.get("description", "") or "").strip()

        # Only include sample values for genuine dimension columns to keep
        # the ontology cache lean — skip IDs, measures, and high-cardinality cols.
        include_samples = (
            cp.is_low_cardinality
            and cp.semantic_type not in ("identifier", "measure")
            and cp.top_values
        )

        props[col] = EntityProperty(
            name=col,
            display_name=_display_name_for_col(col),
            data_type=cp.dtype or "",
            semantic_type=cp.semantic_type or "",
            description=description,
            is_primary_key=(col == grain_column),
            is_foreign_key=bool(cp.is_fk),
            is_nullable=(cp.null_rate or 0) > 0,
            null_rate=round(cp.null_rate or 0, 4),
            value_interpretation=cp.value_interpretation or "",
            unit=cp.unit or "",
            sample_values=[str(v) for v in (cp.top_values or [])][:10] if include_samples else [],
        )

    return props


# ── Object set generation ─────────────────────────────────────────────────────

def _build_object_sets(
    entity_id: str,
    lifecycle_col: Optional[str],
    lifecycle_states: list[str],
    terminal_states: list[str],
    active_filter: Optional[str],
) -> "dict[str, ObjectSet]":
    """
    Auto-generate named ObjectSets from lifecycle data.

    Produces:
      - "All {Entity}"    — no filter, full table
      - "Active {Entity}" — non-terminal rows (filter_sql = active_filter); is_default=True
      - One set per terminal state: "Delivered {Entity}", "Canceled {Entity}", …

    For entities with no lifecycle, only the "All" set is generated.
    """
    sets: dict[str, ObjectSet] = {}
    label = entity_id  # e.g. "Order"

    # Always include an unfiltered "All" set
    all_id = f"all_{label.lower()}s"
    sets[all_id] = ObjectSet(
        id=all_id,
        display_name=f"All {label}s",
        description=f"Every {label} row with no filters applied.",
        filter_sql="",
        is_default=not bool(active_filter),  # default if there's no active filter
        source="lifecycle",
    )

    if not lifecycle_col or not lifecycle_states:
        return sets

    # Derive active filter from terminal_states if not explicitly set
    _active_filter = active_filter
    if not _active_filter and terminal_states:
        tl = ", ".join(f"'{s}'" for s in terminal_states)
        _active_filter = f"{lifecycle_col} NOT IN ({tl})"

    # Active set (non-terminal rows)
    active_id = f"active_{label.lower()}s"
    active_display = f"Active {label}s"
    if _active_filter:
        sets[active_id] = ObjectSet(
            id=active_id,
            display_name=active_display,
            description=f"{label}s that are currently in-progress (non-terminal states).",
            filter_sql=_active_filter,
            is_default=True,
            source="lifecycle",
        )
        # "All" set is no longer default since we have an explicit active set
        sets[all_id].is_default = False

    # One set per terminal state
    for state in terminal_states:
        state_id = f"{state.lower().replace(' ', '_').replace('-', '_')}_{label.lower()}s"
        state_display = f"{state.capitalize()} {label}s"
        sets[state_id] = ObjectSet(
            id=state_id,
            display_name=state_display,
            description=f"{label}s with status '{state}'.",
            filter_sql=f"{lifecycle_col} = '{state}'",
            is_default=False,
            source="lifecycle",
        )

    return sets


# ── Interface detection ───────────────────────────────────────────────────────
#
# Each spec: (id, display_name, description, column_re | None)
# None means "special-case logic" (HasLifecycle, HasDuration).

_INTERFACE_SPECS: list[tuple[str, str, str, str, re.Pattern | None]] = [
    (
        "HasTimestamp",
        "Has Timestamp",
        "Entity records when events occurred — has at least one temporal column.",
        "_at, _time, _timestamp, _date columns",
        re.compile(r"(^created_at$|^updated_at$|^deleted_at$|_at$|_time$|_timestamp$|^timestamp$)", re.IGNORECASE),
    ),
    (
        "HasMonetaryValue",
        "Has Monetary Value",
        "Entity carries financial figures — prices, amounts, revenues, or costs.",
        "_amount, _price, _value, _cost, _fee, _total columns",
        re.compile(r"(_amount$|_price$|_value$|_revenue$|_cost$|_fee$|_total$|_subtotal$|_payment$)", re.IGNORECASE),
    ),
    (
        "HasLifecycle",
        "Has Lifecycle",
        "Entity progresses through named states — has a status or state column with defined transitions.",
        "status / state column with enumerated lifecycle values",
        None,  # detected from entity.has_lifecycle flag
    ),
    (
        "HasRating",
        "Has Rating",
        "Entity carries a user-assigned quality score, rating, or review.",
        "_score, _rating, _stars, _grade columns",
        re.compile(r"(_score$|_rating$|_stars$|_grade$|_rank$)", re.IGNORECASE),
    ),
    (
        "HasGeolocation",
        "Has Geolocation",
        "Entity has geographic coordinates or a location reference.",
        "_lat, _lng, _latitude, _longitude, geolocation_id columns",
        re.compile(r"(_lat$|_lng$|_latitude$|_longitude$|geolocation_id$|_zip$|_zipcode$|_postal$)", re.IGNORECASE),
    ),
    (
        "HasDuration",
        "Has Duration",
        "Entity spans a time interval — has both a start and end timestamp.",
        "paired start/end timestamp columns",
        None,  # special: requires both a start-ish AND end-ish column
    ),
]

# Patterns for HasDuration special detection
_DURATION_START_RE = re.compile(
    r"(^start_|_start$|^begin|_from$|^from_|_open$|_opened$|_purchase_|_shipped_)",
    re.IGNORECASE,
)
_DURATION_END_RE = re.compile(
    r"(^end_|_end$|_until$|_close$|_closed$|_to$|^to_|_delivered|_arrival|_finish)",
    re.IGNORECASE,
)


def _detect_interfaces(
    entities: dict[str, "OntologyEntity"],
) -> dict[str, OntologyInterface]:
    """
    Scan all entity properties to detect which Palantir-style interfaces each
    entity implements.  Mutates entity.implements in-place; returns the
    interfaces dict (only includes interfaces with at least one implementor).
    """
    implementors: dict[str, list[str]] = {spec[0]: [] for spec in _INTERFACE_SPECS}

    for entity in entities.values():
        prop_names = list(entity.properties.keys())

        for spec in _INTERFACE_SPECS:
            iid, _display, _desc, _patterns_label, pattern = spec

            if pattern is not None:
                qualifies = any(pattern.search(col) for col in prop_names)
            elif iid == "HasLifecycle":
                qualifies = entity.has_lifecycle
            elif iid == "HasDuration":
                has_start = any(_DURATION_START_RE.search(c) for c in prop_names)
                has_end   = any(_DURATION_END_RE.search(c) for c in prop_names)
                qualifies = has_start and has_end
            else:
                qualifies = False

            if qualifies:
                implementors[iid].append(entity.id)
                if iid not in entity.implements:
                    entity.implements.append(iid)

    interfaces: dict[str, OntologyInterface] = {}
    for iid, display_name, description, patterns_label, _pattern in _INTERFACE_SPECS:
        if implementors[iid]:
            interfaces[iid] = OntologyInterface(
                id=iid,
                display_name=display_name,
                description=description,
                property_patterns=[patterns_label],
                implementing_entities=sorted(implementors[iid]),
            )
    return interfaces


# ── Relationship verb heuristics ─────────────────────────────────────────────
#
# Assigned at build time so relationships read naturally even without LLM
# enrichment.  The enricher may later override these with domain-specific verbs.
#
# All keys are lowercase.  From-entity perspective (active voice):
#   "OrderItem belongs to Order", "Payment settles Order"

_PAIR_VERBS: dict[tuple[str, str], str] = {
    # Commerce core
    ("order", "customer"):        "placed by",
    ("order", "seller"):          "sold by",
    ("orderitem", "order"):       "belongs to",
    ("orderitem", "product"):     "contains",
    ("payment", "order"):         "settles",
    ("review", "order"):          "reviews",
    ("review", "product"):        "rates",
    ("review", "customer"):       "written by",
    ("shipment", "order"):        "ships",
    ("shipment", "customer"):     "delivered to",
    # Finance / billing
    ("invoice", "order"):         "invoices",
    ("invoice", "customer"):      "billed to",
    ("transaction", "order"):     "settles",
    ("transaction", "customer"):  "belongs to",
    ("refund", "order"):          "refunds",
    ("refund", "customer"):       "returned by",
    # Support / CRM
    ("ticket", "customer"):       "raised by",
    ("ticket", "order"):          "relates to",
    ("subscription", "customer"): "held by",
    ("subscription", "product"):  "covers",
    # Marketing
    ("campaign", "customer"):     "targets",
    ("session", "customer"):      "belongs to",
    ("lead", "campaign"):         "generated by",
}

# Cardinality-only fallback (FK-holder perspective)
_CARDINALITY_VERBS: dict[str, str] = {
    "N:1": "belongs to",
    "1:N": "has",
    "1:1": "paired with",
    "N:N": "associated with",
}


def _infer_relationship_verb(
    from_entity: str,
    to_entity: str,
    from_col: str,
    cardinality: str,
) -> str:
    """
    Assign a readable relationship verb before the LLM enrichment pass.

    Priority:
      1. Known entity-pair pattern  (e.g. Order → Customer → "placed by")
      2. FK column name encodes the target entity ("customer_id" → "belongs to")
      3. Cardinality fallback       (N:1 → "belongs to", 1:N → "has", …)
    """
    pair = (from_entity.lower(), to_entity.lower())
    if pair in _PAIR_VERBS:
        return _PAIR_VERBS[pair]

    # FK col is "{to_entity_lower}_id" or close variant → membership join
    to_lower = re.sub(r"[^a-z]", "", to_entity.lower())
    fc_lower = from_col.lower()
    if cardinality in ("N:1", "1:1") and fc_lower == f"{to_lower}_id":
        return "belongs to"
    # Handle singularisation variance: sellers → seller, customers → customer
    if cardinality in ("N:1", "1:1") and (
        fc_lower.startswith(to_lower + "_") or fc_lower.rstrip("s_id") == to_lower
    ):
        return "belongs to"

    return _CARDINALITY_VERBS.get(cardinality, "relates to")


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_structural_ontology(
    connection_id: str,
    schema_name: str,
    schema_fingerprint: str,
    table_profiles: "dict[str, TableProfile]",
    column_profiles: "dict[str, ColumnProfile]",
    join_map: dict,           # {"joins": [...], "no_join": [...]} from compute_join_map
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
    # table = entity: every profiled table becomes an entity.  A detected grain
    # column upgrades the entity to grain_verified and supplies its identity_key;
    # its absence (high-cardinality tables where the profiler couldn't confirm a
    # single-column PK, or genuinely composite-key tables like order_items) is a
    # quality signal — identity_key stays None — not grounds to drop the table.

    for table, tp in table_profiles.items():
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

        # Properties — one EntityProperty per column on the source table
        properties = _build_entity_properties(
            table=table,
            grain_column=tp.grain_column,
            column_profiles=column_profiles,
            glossary=glossary,
        )

        # Object sets — named composable filters derived from lifecycle states
        object_sets = _build_object_sets(
            entity_id=entity_id,
            lifecycle_col=lifecycle_col,
            lifecycle_states=lifecycle_states,
            terminal_states=terminal_states,
            active_filter=active_filter,
        )

        # display_name starts as the entity_id; the enricher may improve it
        entity = OntologyEntity(
            id=entity_id,
            display_name=entity_id,
            description=description,
            source_tables=[table],
            identity_key=tp.grain_column or "",
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
            properties=properties,
            object_sets=object_sets,
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

        # Resolve to an entity tolerant of qualified-vs-bare table names (the join
        # map can carry schema-qualified names while table_to_entity is keyed by
        # bare names). Canonical resolution lives in tools.table_names so this can
        # never silently skip joins again.
        from_entity = resolve_in(table_to_entity, t1)
        to_entity = resolve_in(table_to_entity, t2)

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

        verb = _infer_relationship_verb(from_entity, to_entity, c1, cardinality)

        rel = OntologyRelationship(
            id=rel_id,
            from_entity=from_entity,
            to_entity=to_entity,
            verb=verb,
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

    # ── Step 5: Detect interface types ────────────────────────────────────────
    interfaces = _detect_interfaces(entities)

    return OntologyGraph(
        connection_id=connection_id,
        schema_name=schema_name,
        schema_fingerprint=schema_fingerprint,
        entities=entities,
        relationships=relationships,
        metrics=metrics,
        actions=actions,
        interfaces=interfaces,
        entity_to_tables=entity_to_tables,
        table_to_entity=table_to_entity,
        relationship_index=relationship_index,
    )


def _edge_key(t1, c1, t2, c2) -> frozenset:
    """Order-independent, qualification-tolerant key for a join edge — bare table stem + lc col."""
    a = (str(t1).split(".")[-1].lower(), str(c1).lower())
    b = (str(t2).split(".")[-1].lower(), str(c2).lower())
    return frozenset({a, b})


def apply_join_verifications(graph: "OntologyGraph", verified: list, rejected: list) -> "OntologyGraph":
    """Persist joinable_with into the ontology: stamp each relationship's probed ``value_overlap``
    and DROP the value-disjoint name-coincidences (a relationship whose two keys hold disjoint
    values is not a real edge — keeping it lets a consumer draw a fabricating join). The verified
    FKs get ``join_confidence='verified'``; an unprobeable edge (overlap −1) is left untouched
    (fail-open — never demote what we couldn't check). Rebuilds ``relationship_index`` from the
    survivors. Mutates + returns ``graph``; pure w.r.t. the DB (the caller does the probing)."""
    ov_by_edge: dict = {}
    for vj in (verified or []):
        ov_by_edge[_edge_key(vj.t1, vj.c1, vj.t2, vj.c2)] = vj.overlap
    rejected_edges = {_edge_key(vj.t1, vj.c1, vj.t2, vj.c2) for vj in (rejected or [])}

    survivors: dict = {}
    dropped = 0
    for rid, rel in graph.relationships.items():
        k = _edge_key(rel.from_table, rel.from_col, rel.to_table, rel.to_col)
        if k in rejected_edges:
            dropped += 1
            continue                              # value-disjoint coincidence → not a real edge
        ov = ov_by_edge.get(k)
        if ov is not None and ov >= 0:
            rel.value_overlap = ov
            rel.join_confidence = "verified"
        survivors[rid] = rel

    graph.relationships = survivors
    idx: dict = {eid: [] for eid in graph.entities}
    for rel in survivors.values():
        idx.setdefault(rel.from_entity, []).append(rel.to_entity)
        idx.setdefault(rel.to_entity, []).append(rel.from_entity)
    graph.relationship_index = idx
    if dropped:
        logger.info("[ontology:%s] dropped %d value-disjoint relationship(s) at build time",
                    graph.connection_id, dropped)
    return graph


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
                f"    active_filter (apply only when user asks for active/valid rows): "
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
