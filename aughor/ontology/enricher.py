"""
M12b — Semantic enrichment of the structural ontology via one LLM batch call.

Runs once per (connection_id, fingerprint), result cached via graph.enriched = True.
Caller is responsible for persisting the returned graph to the ontology store.

If the LLM call fails for any reason the graph is returned unchanged (not enriched),
so the structural ontology continues to work normally.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from aughor.ontology.models import OntologyAction, OntologyGraph

# Bump this whenever the enrichment prompt or output schema changes meaningfully.
# Cached graphs with a lower version will be re-enriched automatically.
ENRICHMENT_VERSION = 3


# ── Pydantic models for structured LLM output ────────────────────────────────

class _ActionDef(BaseModel):
    id: str
    display_name: str
    description: str
    entity: str
    action_type: Literal["filter", "compute", "traverse", "aggregate"]
    sql_template: str
    business_rules_enforced: list[str] = []
    returns: str
    source_table: str


class _ComputedPropDef(BaseModel):
    id: str        # snake_case
    label: str     # human label
    formula_sql: str  # SELECT-clause expression only
    unit: str = ""


class EnrichmentOutput(BaseModel):
    # Clean business-facing names (may differ from the auto-generated PascalCase id)
    # e.g. "BcOrder" → "Customer Order",  "ProductMaster" → "Product"
    entity_display_names: dict[str, str] = {}

    # Palantir-style entity classification override
    # reference_data | business_object | event | standalone
    entity_types: dict[str, str] = {}

    # Domain grouping: entity_id → domain label (e.g. "Commerce", "Customer", "Operations")
    entity_domains: dict[str, str] = {}

    # Relationship verb override: rel_id → lowercase active-voice verb phrase
    # e.g. "Order_RELATES_TO_Customer" → "placed by"
    relationship_verbs: dict[str, str] = {}

    # One-sentence business descriptions keyed by entity_id
    entity_descriptions: dict[str, str] = {}

    # Per-entity computed properties (at most 3 per entity)
    entity_computed_properties: dict[str, list[_ComputedPropDef]] = {}

    # New compute / traverse actions (at most 2 per entity)
    action_definitions: list[_ActionDef] = []

    # Canonical SQL for metric formulas keyed by metric_id
    metric_formulas: dict[str, str] = {}


# ── Internal rendering helpers ────────────────────────────────────────────────

def _render_structural_summary(graph: OntologyGraph) -> str:
    lines: list[str] = []

    lines.append("ENTITIES (id → display_name | source_tables | entity_type):")
    for eid, e in graph.entities.items():
        line = (
            f"  {eid} → \"{e.display_name}\"  "
            f"tables: {', '.join(e.source_tables)},  "
            f"type: {e.entity_type},  "
            f"key: {e.identity_key}"
        )
        if e.has_lifecycle:
            states_preview = ", ".join(e.lifecycle_states[:6])
            line += f",  lifecycle: {e.lifecycle_column} ({states_preview})"
        if e.active_filter:
            line += f",  active_filter: {e.active_filter}"
        if e.description:
            line += f"\n    description: {e.description}"
        lines.append(line)

    if graph.relationships:
        lines.append("\nRELATIONSHIPS:")
        for rid, r in graph.relationships.items():
            lines.append(
                f"  {rid}: {r.from_entity} --[{r.verb}]--> {r.to_entity}"
                f" ({r.cardinality}) via {r.join_sql}"
            )

    if graph.metrics:
        lines.append("\nMETRICS:")
        for mid, m in graph.metrics.items():
            lines.append(
                f"  {mid}: {m.display_name} — entity: {m.entity},"
                f" formula: {m.formula_sql[:80]}"
            )

    if graph.actions:
        lines.append("\nEXISTING ACTIONS (auto-generated filter type):")
        for aid, a in graph.actions.items():
            lines.append(f"  {aid}: {a.display_name} — {a.description}")

    return "\n".join(lines)


def _render_glossary_excerpt(glossary: dict) -> str:
    if not glossary:
        return "(no glossary available)"

    lines: list[str] = []
    tables = glossary.get("tables", {})
    for tname, tinfo in list(tables.items())[:12]:
        if isinstance(tinfo, dict):
            desc = tinfo.get("description", "")
            caveats = tinfo.get("caveats", [])
        else:
            desc = str(tinfo)
            caveats = []
        if desc:
            lines.append(f"{tname}: {desc[:120]}")
        for c in caveats[:2]:
            lines.append(f"  RULE: {str(c)[:100]}")

    return "\n".join(lines) if lines else "(no relevant glossary entries)"


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_ontology_semantics(
    graph: OntologyGraph,
    coder_llm: Any,
    glossary: dict,
    schema_context: str,
) -> OntologyGraph:
    """Enrich a structural OntologyGraph with LLM-derived semantic meaning.

    Makes one structured LLM call. Returns the modified graph with
    graph.enriched = True so the store can cache it correctly.
    """
    from aughor.agent.prompts_ontology import ENRICH_ONTOLOGY_PROMPT

    structural_summary = _render_structural_summary(graph)
    glossary_excerpt = _render_glossary_excerpt(glossary)
    schema_truncated = schema_context[:6000] if len(schema_context) > 6000 else schema_context

    enrichment: EnrichmentOutput = coder_llm.complete(
        system=(
            "You are a data ontology specialist. "
            "Enrich the provided structural ontology with precise semantic meaning."
        ),
        user=ENRICH_ONTOLOGY_PROMPT.format(
            structural_summary=structural_summary,
            glossary_excerpt=glossary_excerpt,
            schema=schema_truncated,
        ),
        response_model=EnrichmentOutput,
    )

    _VALID_TYPES = {"reference_data", "business_object", "event", "standalone"}

    # Apply clean display names (always overwrite — the whole point of enrichment)
    for entity_id, name in enrichment.entity_display_names.items():
        if entity_id in graph.entities and name and name.strip():
            graph.entities[entity_id] = graph.entities[entity_id].model_copy(
                update={"display_name": name.strip()}
            )

    # Apply entity type classification (only if valid and entity exists)
    for entity_id, etype in enrichment.entity_types.items():
        if entity_id in graph.entities and etype in _VALID_TYPES:
            graph.entities[entity_id] = graph.entities[entity_id].model_copy(
                update={"entity_type": etype}
            )

    # Apply relationship verbs — normalise to lowercase, replace generic placeholder
    for rel_id, verb in enrichment.relationship_verbs.items():
        if rel_id in graph.relationships and verb:
            clean_verb = verb.strip().lower().replace("_", " ")
            if clean_verb not in ("relates to", "relates_to", ""):
                graph.relationships[rel_id] = graph.relationships[rel_id].model_copy(
                    update={"verb": clean_verb}
                )

    # Apply entity descriptions (fill blanks only — never overwrite glossary/human values)
    for entity_id, desc in enrichment.entity_descriptions.items():
        if entity_id in graph.entities and desc:
            entity = graph.entities[entity_id]
            if not entity.description:
                graph.entities[entity_id] = entity.model_copy(update={"description": desc})

    # Apply domain grouping
    for entity_id, domain in enrichment.entity_domains.items():
        if entity_id in graph.entities and domain and domain.strip():
            graph.entities[entity_id] = graph.entities[entity_id].model_copy(
                update={"domain": domain.strip()}
            )

    # Apply computed properties (replace wholesale — enrichment is authoritative)
    from aughor.ontology.models import ComputedProperty
    for entity_id, props in enrichment.entity_computed_properties.items():
        if entity_id in graph.entities and props:
            computed = [
                ComputedProperty(
                    id=p.id, label=p.label, formula_sql=p.formula_sql, unit=p.unit
                )
                for p in props if p.id and p.formula_sql.strip()
            ]
            if computed:
                graph.entities[entity_id] = graph.entities[entity_id].model_copy(
                    update={"computed_properties": computed}
                )

    # Apply corrected metric formulas
    for metric_id, formula in enrichment.metric_formulas.items():
        if metric_id in graph.metrics and formula:
            graph.metrics[metric_id] = graph.metrics[metric_id].model_copy(
                update={"formula_sql": formula}
            )

    # Add new compute / traverse actions (skip if id already exists)
    for adef in enrichment.action_definitions:
        if adef.id not in graph.actions and adef.sql_template.strip():
            graph.actions[adef.id] = OntologyAction(
                id=adef.id,
                display_name=adef.display_name,
                description=adef.description,
                entity=adef.entity,
                action_type=adef.action_type,
                sql_template=adef.sql_template,
                business_rules_enforced=adef.business_rules_enforced,
                returns=adef.returns,
                source_table=adef.source_table,
            )

    graph.enriched = True
    graph.enrichment_version = ENRICHMENT_VERSION
    return graph
