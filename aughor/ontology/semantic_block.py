"""
M24c — Question-scoped semantic-layer injection for the NL2SQL prompt.

`render_ontology_annotations` (builder.py) emits the ENTITY MODEL block but
deliberately drops object sets and computed properties. Those carry the highest
NL2SQL value — a named object set maps a phrase like "active orders" to a
*verified* WHERE fragment, and a computed property gives the model the exact,
executed formula for a derived KPI — yet the generator never saw them.

This renderer closes that gap. It is:
  • question-scoped — only entities whose source tables appear in `linked_tables`
    are rendered, so the token cost is small and relevant; and
  • verified-gated — only items the ontology.validator confirmed against the live
    DB are injected, so a hallucinated formula can never reach the prompt.

Metrics are NOT emitted here — they flow through the unified METRICS CATALOG
(semantic.metrics.build_metrics_block with the ontology overlay) to avoid
duplication.
"""
from __future__ import annotations

from typing import Iterable, Optional

from aughor.ontology.models import OntologyGraph


def _bare(table: str) -> str:
    """Last path segment, lowercased: 'analytics.orders' -> 'orders'."""
    return table.rsplit(".", 1)[-1].strip().strip('"').lower()


def render_semantic_layer(
    graph: Optional[OntologyGraph],
    linked_tables: Iterable[str],
) -> str:
    """Return a VERIFIED SEMANTIC LAYER block for the entities touching
    `linked_tables`, or "" when there is nothing verified to add."""
    if graph is None or not graph.entities:
        return ""

    wanted = {_bare(t) for t in linked_tables if t}
    if not wanted:
        return ""

    object_lines: list[str] = []
    computed_lines: list[str] = []

    for entity in sorted(graph.entities.values(), key=lambda e: e.display_name):
        ent_tables = {_bare(t) for t in entity.source_tables}
        if not (ent_tables & wanted):
            continue
        table = entity.source_tables[0] if entity.source_tables else "?"
        label = entity.display_name or entity.id

        # Named object sets → verified WHERE fragments (skip the all-rows default).
        for os_ in entity.object_sets.values():
            if not os_.verified or not (os_.filter_sql or "").strip():
                continue
            object_lines.append(
                f'  "{os_.display_name}" ({table}) → WHERE {os_.filter_sql}'
            )

        # Computed properties → exact, executed SELECT-clause expressions.
        for cp in entity.computed_properties:
            if not cp.verified:
                continue
            unit = f"  [{cp.unit}]" if cp.unit else ""
            computed_lines.append(
                f"  {label}.{cp.label} = {cp.formula_sql}{unit}"
            )

    if not object_lines and not computed_lines:
        return ""

    sections: list[str] = [
        "VERIFIED SEMANTIC LAYER (executed against this database — use these exact "
        "expressions; do not re-derive):"
    ]
    if object_lines:
        sections.append(
            "OBJECT SETS (named row filters — apply the WHERE fragment when the "
            "question refers to this set):"
        )
        sections.extend(object_lines)
    if computed_lines:
        sections.append("COMPUTED PROPERTIES (verified derived metrics):")
        sections.extend(computed_lines)

    return "\n".join(sections)
