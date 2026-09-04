"""
M24c — Question-scoped semantic-layer injection for the NL2SQL prompt.

`render_ontology_annotations` (builder.py) emits the ENTITY MODEL block but
deliberately drops segments and computed properties. Those carry the highest
NL2SQL value — a named segment maps a phrase like "active orders" to a
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

`render_relationship_block` (below) is the same idea for the relationship graph:
verified/exact join edges with cardinality + confidence, existence-bound to the
schema being rendered. Injected schema-wide by `tools.schema.apply_schema_enrichment`
and question-scoped on the /ask Data-Catalog path (routers/investigations.py).
"""
from __future__ import annotations

from typing import Iterable, Optional

from aughor.ontology.models import OntologyGraph


def _bare(table: str) -> str:
    """Last path segment, lowercased: 'analytics.orders' -> 'orders'."""
    return table.rsplit(".", 1)[-1].strip().strip('"').lower()


# ── Relationship rendering (verified entity graph → the SQL prompt) ───────────
#
# The ontology's relationship graph carries cardinality, join_confidence and the
# probed value_overlap — and until this renderer existed, none of it reached the
# SQL-generation prompt: builder.render_ontology_annotations deliberately skips
# relationships ("already covered by JOIN HINTS"), while the JOIN HINTS block is
# name-heuristic only. The model picked join paths from name guesses while the
# verified graph fed only the /ontology API, and join correctness was enforced
# purely DOWNSTREAM by the fan-out/join-guard family. Cardinality in the prompt
# lets the model avoid a fan-out join upstream instead of being caught after.

#: Line cap — the block is schema-scoped (not question-scoped), so it must stay
#: small next to the table cap the Data Catalog build already enforces. Verified
#: edges outrank exact ones, so the cap sheds the weakest lines first.
_MAX_RELATIONSHIP_LINES = 40

_CONFIDENCE_ORDER = {"verified": 0, "exact": 1}


def _unambiguous_tables(table_cols: dict[str, list[str]]) -> dict[str, str]:
    """Bare name → the schema's own spelling; a bare name two qualified tables
    share resolves to NOTHING (an edge must never bind to the wrong twin)."""
    seen: dict[str, Optional[str]] = {}
    for t in table_cols:
        b = _bare(t)
        seen[b] = None if b in seen else t
    return {b: t for b, t in seen.items() if t is not None}


def render_relationship_block(
    graph: Optional[OntologyGraph],
    table_cols: dict[str, list[str]],
) -> str:
    """An ENTITY RELATIONSHIPS block for the SQL prompt, or "" when the graph
    holds nothing trustworthy for this schema.

    Verified/exact-gated: only relationships whose join key was probed against
    the live data (``join_confidence='verified'``) or matched on a real key
    suffix (``'exact'``) are rendered — a name-inferred edge adds nothing over
    the JOIN HINTS heuristics and is left out.

    Existence-bound to ``table_cols`` (the CURRENTLY rendered schema, from
    ``parse_schema_tables``): the cached graph may be older than the schema, so
    an edge renders only when both tables resolve unambiguously and both key
    columns still exist. A stale graph can therefore never inject a join for a
    table this schema no longer has.

    Sync note (Rec 5): this block travels INSIDE the enriched schema string, so
    the ``GET /ask/context`` receipt's schema-slice block shows it via the same
    producer the answer path uses — one source of truth, no second renderer to
    drift. Lines are ``- ``-prefixed deliberately: the schema linker's
    trailing-content pass strips 2-space-indented lines (it guts JOIN HINTS
    detail on a filtered slice), and a bullet survives it.
    """
    if graph is None or not graph.relationships or not table_cols:
        return ""

    resolve = _unambiguous_tables(table_cols)
    cols_of = {t: {c.lower() for c in cols} for t, cols in table_cols.items()}

    entries: list[tuple[int, str]] = []
    any_nullable = False
    for rel in graph.relationships.values():
        rank = _CONFIDENCE_ORDER.get(rel.join_confidence)
        if rank is None:
            continue
        ft = resolve.get(_bare(rel.from_table))
        tt = resolve.get(_bare(rel.to_table))
        if not ft or not tt:
            continue
        if (rel.from_col.lower() not in cols_of[ft]
                or rel.to_col.lower() not in cols_of[tt]):
            continue
        label = [rel.cardinality, rel.join_confidence]
        if rel.value_overlap is not None and rel.value_overlap >= 0:
            label.append(f"{rel.value_overlap:.0%} key overlap")
        if rel.nullable:
            label.append("nullable FK")
            any_nullable = True
        phrase = ""
        if rel.verb and rel.verb != "RELATES_TO":
            phrase = f" — {rel.from_entity} {rel.verb} {rel.to_entity}"
        entries.append((
            rank,
            f"- {ft}.{rel.from_col} → {tt}.{rel.to_col}"
            f" [{', '.join(label)}]{phrase}",
        ))

    if not entries:
        return ""
    entries.sort()
    lines = [
        "ENTITY RELATIONSHIPS (the verified entity graph for this schema — "
        "prefer these join paths over name-matched guesses):"
    ]
    lines += [line for _, line in entries[:_MAX_RELATIONSHIP_LINES]]
    lines.append(
        "CARDINALITY: the label reads left→right — 'a.x → b.y [N:1]' means many "
        "a-rows per b-row. Joining toward the '1' side never adds rows; pulling "
        "the 'N' side into a query grained on the '1' side multiplies rows and "
        "inflates SUM/AVG/COUNT — pre-aggregate the N side in a subquery first, "
        "or use COUNT(DISTINCT)."
    )
    if any_nullable:
        lines.append(
            "A nullable FK means an INNER JOIN silently drops the rows where it "
            "is NULL — use a LEFT JOIN when totals must cover every base row."
        )
    return "\n".join(lines)


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

    segment_lines: list[str] = []
    computed_lines: list[str] = []

    for entity in sorted(graph.entities.values(), key=lambda e: e.display_name):
        ent_tables = {_bare(t) for t in entity.source_tables}
        if not (ent_tables & wanted):
            continue
        table = entity.source_tables[0] if entity.source_tables else "?"
        label = entity.display_name or entity.id

        # Named segments → verified WHERE fragments (skip the all-rows default).
        for seg in entity.segments.values():
            if not seg.verified or not (seg.filter_sql or "").strip():
                continue
            segment_lines.append(
                f'  "{seg.display_name}" ({table}) → WHERE {seg.filter_sql}'
            )

        # Computed properties → exact, executed SELECT-clause expressions.
        for cp in entity.computed_properties:
            if not cp.verified:
                continue
            unit = f"  [{cp.unit}]" if cp.unit else ""
            computed_lines.append(
                f"  {label}.{cp.label} = {cp.formula_sql}{unit}"
            )

    if not segment_lines and not computed_lines:
        return ""

    sections: list[str] = [
        "VERIFIED SEMANTIC LAYER (executed against this database — use these exact "
        "expressions; do not re-derive):"
    ]
    if segment_lines:
        sections.append(
            "SEGMENTS (named saved row filters — apply the WHERE fragment when the "
            "question refers to this segment):"
        )
        sections.extend(segment_lines)
    if computed_lines:
        sections.append("COMPUTED PROPERTIES (verified derived metrics):")
        sections.extend(computed_lines)

    return "\n".join(sections)
