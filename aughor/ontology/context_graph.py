"""The connection knowledge graph — Wave C1 (the read-back artifact).

Promotes the structural ontology (:mod:`aughor.ontology`) into ONE typed,
provenance-complete graph per connection — the artifact every question will pass
through in C2. This module is the deterministic PROJECTION: it reads the
already-built :class:`OntologyGraph` plus the narrative stores (glossary, metrics,
findings, briefs, ambiguity ledger) and emits typed nodes and edges. It never
calls the LLM and never executes SQL — node summaries/tags and domain narration
are a later, narrow LLM emission (never an edge, never a number).

The load-bearing rule is **J4 — every node and edge carries real provenance, or it
does not exist.** :class:`Provenance` is a *required* field on both
:class:`GraphNode` and :class:`GraphEdge`, so an edge without evidence is not even
constructible. The measured confidence that annotates a ``joins_on`` edge is the
join guard's value-domain overlap (``OntologyRelationship.value_overlap``), already
computed and persisted at ontology-build time; a value-disjoint name coincidence is
dropped from the ontology upstream, so it never reaches this projection. The
self-reported model confidences (``EvidenceClaim.confidence``,
``pack_deltas.confidence``) are deliberately NOT allowed as edge provenance — they
are UA's hardcoded weights wearing a badge.

Wave-C node/edge type system (T3.1):
  nodes: table · metric · glossary_term · domain · finding · brief
  edges: joins_on · defines · derived_from · grounded_in · resolves
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from aughor.kernel.errors import tolerate

NodeKind = Literal["table", "metric", "glossary_term", "domain", "finding", "brief"]
EdgeKind = Literal["joins_on", "defines", "derived_from", "grounded_in", "resolves"]

# The provenance sources allowed on a node/edge. Every entry names a DETERMINISTIC
# origin (schema/profiler/guard/human-curated store). There is deliberately no
# "llm_inferred" source and no self-reported model-confidence source — see module
# docstring (J4).
ProvenanceSource = Literal[
    "ontology.entity",     # a projected OntologyEntity (schema + profiler)
    "ontology.metric",     # an OntologyMetric (governed formula)
    "ontology.domain",     # enricher-assigned domain grouping
    "join_guard",          # measured value-domain overlap (the strongest edge evidence)
    "glossary",            # human/dbt/auto-seed table+column definitions
    "metrics_catalog",     # the governed metrics store (owner/lineage/approved)
    "dossier",             # a finding's captured derivation (Ledger artifact)
    "exploration",         # a discovered exploration insight
    "evidence_ledger",     # an investigation EvidenceClaim (sql_source, not its confidence)
    "ambiguity_ledger",    # a crystallized resolution (probe|user|verdict)
    "briefing",            # a synthesized executive narrative
]


class Provenance(BaseModel):
    """Why a node or edge exists — the J4 carrier.

    ``measured`` is a real number (a join guard's value-domain overlap ∈ [0,1], a
    containment fraction) or ``None`` when the provenance is a *derivation* or
    *definition* rather than a *measurement*. ``note`` names the specific evidence
    (the ``join_confidence`` tier, the resolution source, the source table), so a
    reader can audit the edge without re-deriving it.
    """

    source: ProvenanceSource
    measured: Optional[float] = None  # e.g. join value_overlap; None ⇒ not a measurement
    note: str = ""


class GraphNode(BaseModel):
    id: str  # kind-prefixed and stable: "table:Order", "metric:revenue"
    kind: NodeKind
    label: str
    # Summary/tags are the ONLY LLM-emitted fields, filled by a later narrow pass;
    # empty at C1 (the projection is deterministic).
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    provenance: Provenance
    # Kind-specific payload — columns, formula_sql, source_tables, finding text, …
    data: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    # Stable id so a rebuild is idempotent: "{from}--{kind}-->{to}".
    id: str
    kind: EdgeKind
    from_id: str
    to_id: str
    # REQUIRED (no default): an edge without provenance is not constructible (J4).
    provenance: Provenance
    label: str = ""


class ContextGraph(BaseModel):
    """One typed graph per (org, connection, schema).

    Keyed on the ``(org_id, connection_id, schema_name)`` spine — the fix for the
    two global-by-name stores (glossary, metrics), which are read-time-scoped to the
    connection during projection. ``version`` is bumped on every rebuild
    (supersede-not-delete, mirroring the Ledger's ``finding`` artifact); the committed
    JSON file plus git carry the history.
    """

    org_id: str
    connection_id: str
    schema_name: str = ""
    # The DATA fingerprint — inherited from the ontology, which folds in row_count, so it
    # moves on every reload. Kept for provenance/back-compat.
    schema_fingerprint: str = ""
    # The STRUCTURAL fingerprint (tables + columns + types, NO row_count) — Wave C3. The
    # split is load-bearing: a nightly data reload changes schema_fingerprint but not this,
    # so freshness can tell "the data moved" (dirty) from "the schema changed" (stale/rebuild).
    structural_fingerprint: str = ""
    # Per-table structural fingerprints, so a change can be classified PARTIAL (only some
    # tables' columns moved → re-profile those) vs FULL (tables added/removed → re-cluster).
    table_fingerprints: dict[str, str] = Field(default_factory=dict)
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    version: int = 1
    nodes: dict[str, GraphNode] = Field(default_factory=dict)
    edges: dict[str, GraphEdge] = Field(default_factory=dict)

    # ── construction helpers ──────────────────────────────────────────────────
    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        # An edge whose endpoints are not both present would dangle; the projection
        # never emits one, but guard here so a partial source can't corrupt the graph.
        if edge.from_id in self.nodes and edge.to_id in self.nodes:
            self.edges[edge.id] = edge

    # ── read helpers (C2 leans on these) ──────────────────────────────────────
    def nodes_of(self, kind: NodeKind) -> list[GraphNode]:
        return [n for n in self.nodes.values() if n.kind == kind]

    def neighbors(self, node_id: str) -> list[GraphEdge]:
        """1-hop edges touching ``node_id`` (either direction) — the subgraph C2 pulls."""
        return [
            e for e in self.edges.values()
            if e.from_id == node_id or e.to_id == node_id
        ]

    def counts(self) -> dict[str, int]:
        """Node counts by kind + total edges — the shape a proof/receipt prints."""
        out: dict[str, int] = {}
        for n in self.nodes.values():
            out[n.kind] = out.get(n.kind, 0) + 1
        out["edges"] = len(self.edges)
        return out


# ── id helpers (stable, kind-prefixed) ────────────────────────────────────────

def _bare(table: str) -> str:
    """Bare, lowercased table name (schema qualifier stripped) — the join key the
    structural facts use, mirroring ``explorer.dossier._bare``."""
    return str(table).rsplit(".", 1)[-1].strip().strip('"').lower()


def _table_node_id(entity_id: str) -> str:
    return f"table:{entity_id}"


def _metric_node_id(metric_id: str) -> str:
    return f"metric:{metric_id}"


def _term_node_id(table: str, column: str) -> str:
    return f"glossary_term:{_bare(table)}.{str(column).lower()}"


def _domain_node_id(domain: str) -> str:
    return f"domain:{str(domain).strip().lower().replace(' ', '_')}"


def _finding_node_id(finding_id: str) -> str:
    return f"finding:{finding_id}"


def _brief_node_id(scope_key: str) -> str:
    """One node per brief SCOPE, not per generation: a regenerated brief supersedes
    the prior one (same id) rather than accumulating a node per refresh."""
    return f"brief:{scope_key}"


def _edge_id(from_id: str, kind: str, to_id: str) -> str:
    return f"{from_id}--{kind}-->{to_id}"


# ── the projection ────────────────────────────────────────────────────────────

def project_graph(
    ontology,
    *,
    org_id: str,
    connection_id: str,
    schema_name: str = "",
    merged_glossary: Optional[dict] = None,
    resolutions: Optional[list] = None,
    findings: Optional[list] = None,
    briefs: Optional[list] = None,
) -> ContextGraph:
    """Project an :class:`OntologyGraph` (+ narrative sources) into a typed
    :class:`ContextGraph`. Pure and deterministic; never raises on a missing/partial
    source (each source is folded in best-effort so one empty store can't block the
    build). ``findings`` is a list of normalized finding dicts (see
    :func:`aughor.ontology.context_graph_findings.load_findings`).
    """
    cg = ContextGraph(
        org_id=org_id,
        connection_id=connection_id,
        schema_name=schema_name or getattr(ontology, "schema_name", "") or "",
        schema_fingerprint=getattr(ontology, "schema_fingerprint", "") or "",
    )
    try:  # C3: stamp the structural fingerprints so freshness can classify changes
        from aughor.ontology.graph_freshness import structural_fingerprint, table_fingerprints
        cg.structural_fingerprint = structural_fingerprint(ontology)
        cg.table_fingerprints = table_fingerprints(ontology)
    except Exception as exc:
        tolerate(exc, "structural-fingerprint stamping is best-effort",
                 counter="context_graph.structural_fp")

    _project_tables_and_domains(cg, ontology)
    _project_metrics(cg, ontology)
    _project_joins(cg, ontology)
    _project_glossary_terms(cg, ontology, merged_glossary)
    _project_resolutions(cg, resolutions or [])
    _project_findings(cg, findings or [])
    # Briefs last: their `derived_from` edges point at finding nodes, which must
    # already exist or the citation is dropped as dangling.
    _project_briefs(cg, briefs or [])
    return cg


def _project_tables_and_domains(cg: ContextGraph, ontology) -> None:
    """`table` nodes from OntologyEntity (the business object over its source tables)
    and `domain` nodes from the enricher's grouping. Domain membership rides on the
    table node's ``data`` (the T3.1 edge set has no membership edge)."""
    domains: dict[str, list[str]] = {}
    for eid, ent in (getattr(ontology, "entities", {}) or {}).items():
        try:
            props = getattr(ent, "properties", {}) or {}
            node = GraphNode(
                id=_table_node_id(eid),
                kind="table",
                label=getattr(ent, "display_name", "") or eid,
                tags=list(getattr(ent, "implements", []) or []),
                provenance=Provenance(
                    source="ontology.entity",
                    note=f"entity_type={getattr(ent, 'entity_type', '')}"
                    f" grain_verified={getattr(ent, 'grain_verified', False)}",
                ),
                data={
                    "source_tables": list(getattr(ent, "source_tables", []) or []),
                    "identity_key": getattr(ent, "identity_key", ""),
                    "domain": getattr(ent, "domain", None),
                    "columns": sorted(props.keys()),
                    "column_count": len(props),
                    "has_lifecycle": bool(getattr(ent, "has_lifecycle", False)),
                    "exploration_insights": list(
                        getattr(ent, "exploration_insights", []) or []
                    ),
                },
            )
            cg.add_node(node)
            dom = getattr(ent, "domain", None)
            if dom:
                domains.setdefault(str(dom), []).append(node.id)
        except Exception as exc:  # a single malformed entity never sinks the graph
            tolerate(exc, "context-graph table projection is per-entity best-effort",
                     counter="context_graph.table_projection")

    for dom, members in domains.items():
        cg.add_node(GraphNode(
            id=_domain_node_id(dom),
            kind="domain",
            label=dom,
            provenance=Provenance(source="ontology.domain",
                                  note=f"{len(members)} member tables"),
            data={"members": members},
        ))


def _project_metrics(cg: ContextGraph, ontology) -> None:
    """`metric` nodes from the ontology's governed metrics + `derived_from` edges to
    the table nodes their formulas read. The ontology metrics are already
    connection-scoped, so no re-keying is needed here (unlike the global catalog)."""
    for mid, met in (getattr(ontology, "metrics", {}) or {}).items():
        try:
            node = GraphNode(
                id=_metric_node_id(mid),
                kind="metric",
                label=getattr(met, "display_name", "") or mid,
                provenance=Provenance(
                    source="ontology.metric",
                    note=f"verified={getattr(met, 'verified', False)}",
                ),
                data={
                    "formula_sql": getattr(met, "formula_sql", ""),
                    "unit": getattr(met, "unit", ""),
                    "grain": getattr(met, "grain", ""),
                    "tables": list(getattr(met, "tables", []) or []),
                    "verified": bool(getattr(met, "verified", False)),
                },
            )
            cg.add_node(node)
            # derived_from: metric → each table node whose entity materialises a table
            # the metric reads. Provenance is the metric's own table declaration.
            met_tables = {_bare(t) for t in (getattr(met, "tables", []) or [])}
            for tnode in cg.nodes_of("table"):
                src = {_bare(t) for t in (tnode.data.get("source_tables") or [])}
                if met_tables & src:
                    cg.add_edge(GraphEdge(
                        id=_edge_id(node.id, "derived_from", tnode.id),
                        kind="derived_from",
                        from_id=node.id,
                        to_id=tnode.id,
                        provenance=Provenance(
                            source="ontology.metric",
                            note="metric formula reads table",
                        ),
                        label="derived from",
                    ))
        except Exception as exc:
            tolerate(exc, "context-graph metric projection is per-metric best-effort",
                     counter="context_graph.metric_projection")


def _project_joins(cg: ContextGraph, ontology) -> None:
    """`joins_on` edges from OntologyRelationship — the J4 showcase. The measured
    value-domain overlap (``value_overlap``, already probed and persisted upstream)
    is carried as ``Provenance.measured``; a value-disjoint coincidence was dropped
    from the ontology and never reaches here, so every edge emitted is real."""
    for rid, rel in (getattr(ontology, "relationships", {}) or {}).items():
        try:
            from_id = _table_node_id(getattr(rel, "from_entity", ""))
            to_id = _table_node_id(getattr(rel, "to_entity", ""))
            if from_id not in cg.nodes or to_id not in cg.nodes:
                continue  # dangling endpoint — skip, never emit a floating edge
            overlap = getattr(rel, "value_overlap", None)
            confidence = getattr(rel, "join_confidence", "inferred")
            # Honest note: name the measurement when present, the tier otherwise.
            if overlap is not None:
                note = f"value_overlap={overlap:.3f} join_confidence={confidence}"
            else:
                note = f"unprobed join_confidence={confidence}"
            cg.add_edge(GraphEdge(
                id=_edge_id(from_id, "joins_on", to_id),
                kind="joins_on",
                from_id=from_id,
                to_id=to_id,
                provenance=Provenance(
                    source="join_guard",
                    measured=overlap,
                    note=note,
                ),
                label=getattr(rel, "verb", "") or "joins on",
            ))
        except Exception as exc:
            tolerate(exc, "context-graph join projection is per-edge best-effort",
                     counter="context_graph.join_projection")


def _project_glossary_terms(cg: ContextGraph, ontology, merged_glossary: Optional[dict]) -> None:
    """`glossary_term` nodes from the merged glossary's COLUMN definitions, scoped to
    THIS connection's tables (the read-time fix for the global-by-name store), plus
    `defines` edges term→metric on an exact name match. Only columns with a real
    description become terms — an undescribed column is a schema fact, not a term."""
    if not merged_glossary:
        return
    # The set of table names this connection actually exposes (from the ontology).
    conn_tables: set[str] = set()
    for tnode in cg.nodes_of("table"):
        for t in (tnode.data.get("source_tables") or []):
            conn_tables.add(_bare(t))
    metric_labels = {
        m.label.strip().lower(): m.id for m in cg.nodes_of("metric")
    }
    metric_ids = {mid.split(":", 1)[-1].strip().lower(): mid
                  for mid in (n.id for n in cg.nodes_of("metric"))}

    for table, meta in merged_glossary.items():
        if _bare(table) not in conn_tables:
            continue  # a different connection's table — global store, scoped out
        columns = (meta or {}).get("columns", {}) if isinstance(meta, dict) else {}
        for col, cmeta in (columns or {}).items():
            desc = (cmeta or {}).get("description", "") if isinstance(cmeta, dict) else ""
            if not desc:
                continue
            try:
                node = GraphNode(
                    id=_term_node_id(table, col),
                    kind="glossary_term",
                    label=str(col),
                    summary=str(desc),
                    provenance=Provenance(source="glossary",
                                          note=f"defined on {_bare(table)}"),
                    data={"table": _bare(table), "column": str(col),
                          "values": (cmeta or {}).get("values", ""),
                          "caveats": (cmeta or {}).get("caveats", ""),
                          # P2: whether the autodoc seeded this table's entry, so the
                          # warrant class can tell a written definition from a generated
                          # one. Table-level (the merge carries no per-column marker), so
                          # it reads "this description may be machine-written" — the
                          # honest direction: it only ever WEAKENS a claim.
                          "auto_generated": bool((meta or {}).get("auto_generated"))},
                )
                cg.add_node(node)
                # defines: term → metric when the column name matches a metric exactly.
                key = str(col).strip().lower()
                mid = metric_labels.get(key) or metric_ids.get(key)
                if mid:
                    cg.add_edge(GraphEdge(
                        id=_edge_id(node.id, "defines", mid),
                        kind="defines",
                        from_id=node.id,
                        to_id=mid,
                        provenance=Provenance(source="glossary",
                                              note="term name matches metric"),
                        label="defines",
                    ))
            except Exception as exc:
                tolerate(exc, "context-graph glossary-term projection is best-effort",
                         counter="context_graph.term_projection")


def _table_node_id_for_table(cg: ContextGraph, bare_table: str) -> Optional[str]:
    for tnode in cg.nodes_of("table"):
        if bare_table in {_bare(t) for t in (tnode.data.get("source_tables") or [])}:
            return tnode.id
    return None


def _project_resolutions(cg: ContextGraph, resolutions: list) -> None:
    """`resolves` edges from crystallized ambiguity resolutions → the glossary_term
    (or table) they resolve. Provenance is the resolution's own source tier
    (probe|user|verdict) — a genuine, auditable origin, never a model guess."""
    if not resolutions:
        return
    for res in resolutions:
        try:
            subject = str(getattr(res, "subject", "") or "").strip()
            if not subject:
                continue
            source_tier = getattr(res, "resolution_source", "") or "probe"
            # Point at what the resolution actually resolves: a glossary term, else a
            # metric of that name, else the table. If none exists in this graph the
            # resolution node is still emitted (findable in C2) but carries no dangling
            # edge.
            target_id = None
            key = subject.lower()
            for tnode in cg.nodes_of("glossary_term"):
                if tnode.data.get("column", "").lower() == key:
                    target_id = tnode.id
                    break
            if target_id is None:
                for mnode in cg.nodes_of("metric"):
                    if (mnode.label.strip().lower() == key
                            or mnode.id.split(":", 1)[-1].lower() == key):
                        target_id = mnode.id
                        break
            if target_id is None:
                target_id = _table_node_id_for_table(cg, _bare(subject))
            res_id = getattr(res, "id", "") or key
            # A synthetic source node for the resolution keeps the edge honest about
            # where it came from (the ledger), not floating off a term.
            src_node_id = f"resolution:{res_id}"
            cg.add_node(GraphNode(
                id=src_node_id,
                kind="glossary_term",  # a resolved reading IS a term-level fact
                label=subject,
                summary=str(getattr(res, "resolved_reading", "") or ""),
                provenance=Provenance(
                    source="ambiguity_ledger",
                    note=f"resolution_source={source_tier}",
                ),
                data={"subject": subject, "resolution_source": source_tier,
                      "evidence": getattr(res, "evidence", "") or ""},
            ))
            if target_id is not None:
                cg.add_edge(GraphEdge(
                    id=_edge_id(src_node_id, "resolves", target_id),
                    kind="resolves",
                    from_id=src_node_id,
                    to_id=target_id,
                    provenance=Provenance(
                        source="ambiguity_ledger",
                        note=f"resolution_source={source_tier}",
                    ),
                    label="resolves",
                ))
        except Exception as exc:
            tolerate(exc, "context-graph resolution projection is best-effort",
                     counter="context_graph.resolution_projection")


def add_findings(cg: ContextGraph, findings: list) -> list[str]:
    """Project findings into an EXISTING graph — the public entry point for an
    incremental write (Wave L1's live path), and the same projection a full build
    runs. Returns the node ids emitted (empty ⇒ every input was rejected).

    It exists so the answer path never has to reach into ``_project_findings``: one
    projector, so an incrementally-added node and the node a later rebuild emits from
    the same receipt are byte-identical rather than two hand-kept-in-sync shapes.
    ``add_node``/``add_edge`` are id-keyed, so re-adding a finding supersedes it.
    """
    return _project_findings(cg, findings)


def finding_node_data(f: dict) -> dict:
    """The finding node's payload — plus whatever N3 consolidation attached.

    The consolidation keys are emitted ONLY when present, so a graph built with
    ``graph.consolidate`` off serializes byte-identically to before N3. ``contested``
    carries the alternative conclusions with it: a node that survived a disagreement has
    to say so, or the artifact has resolved by timestamp what only a human may settle.
    """
    data = {"sql": f.get("sql", ""), "tables": list(f.get("tables") or []),
            "generated_at": f.get("generated_at", "")}
    if f.get("supersedes"):
        data["supersedes"] = int(f["supersedes"])
        data["superseded_ids"] = list(f.get("superseded_ids") or [])
    if f.get("contested"):
        data["contested"] = True
        data["contested_variants"] = list(f.get("contested_variants") or [])
    if f.get("stale"):
        data["stale"] = True
        data["stale_reason"] = str(f.get("stale_reason") or "")
    return data


def _project_findings(cg: ContextGraph, findings: list) -> list[str]:
    """`finding` nodes (the write-only half of the open loop, finally a node) +
    `grounded_in` edges finding → the table nodes its SQL reads. ``findings`` are
    normalized dicts: ``{id, text, sql, tables, source, confidence?}``. Provenance is
    the derivation source (dossier/exploration/evidence_ledger) — never the finding's
    self-reported confidence. Returns the node ids emitted."""
    emitted: list[str] = []
    if not findings:
        return emitted
    for f in findings:
        try:
            fid = str(f.get("id") or "")
            text = str(f.get("text") or "")
            if not fid or not text:
                continue
            source = f.get("source") or "exploration"
            node = GraphNode(
                id=_finding_node_id(fid),
                kind="finding",
                label=(text[:80] + "…") if len(text) > 80 else text,
                summary=text,
                provenance=Provenance(
                    source=source if source in (
                        "dossier", "exploration", "evidence_ledger") else "exploration",
                    note=f"finding from {source}",
                ),
                data=finding_node_data(f),
            )
            cg.add_node(node)
            emitted.append(node.id)
            for t in (f.get("tables") or []):
                tnode_id = _table_node_id_for_table(cg, _bare(t))
                if tnode_id:
                    cg.add_edge(GraphEdge(
                        id=_edge_id(node.id, "grounded_in", tnode_id),
                        kind="grounded_in",
                        from_id=node.id,
                        to_id=tnode_id,
                        provenance=Provenance(
                            source=node.provenance.source,
                            note="finding SQL reads table",
                        ),
                        label="grounded in",
                    ))
        except Exception as exc:
            tolerate(exc, "context-graph finding projection is per-finding best-effort",
                     counter="context_graph.finding_projection")
    return emitted


def add_briefs(cg: ContextGraph, briefs: list) -> list[str]:
    """Project briefs into an EXISTING graph — the public incremental entry point,
    and the same projection a full build runs (see :func:`add_findings`). Returns the
    node ids emitted."""
    return _project_briefs(cg, briefs)


def _project_briefs(cg: ContextGraph, briefs: list) -> list[str]:
    """`brief` nodes + `derived_from` edges brief → the findings it cited.

    ``brief`` was a declared node kind with no projector: the type existed, the header
    documented it, and nothing ever emitted one. A synthesized narrative is the most
    read artifact Aughor produces and it was absent from the graph that is supposed to
    hold what the connection knows.

    Provenance is ``briefing`` — a synthesis of cited findings. The edge is
    ``derived_from`` (the brief is derived FROM the finding), and it is only emitted
    when the cited finding is actually a node here: a citation to something outside
    this graph must not become a dangling edge.
    """
    emitted: list[str] = []
    if not briefs:
        return emitted
    for b in briefs:
        try:
            bid = str(b.get("id") or "")
            text = str(b.get("text") or "")
            if not bid or not text:
                continue
            theme = str(b.get("theme") or "")
            label = theme or ((text[:80] + "…") if len(text) > 80 else text)
            node = GraphNode(
                id=_brief_node_id(bid),
                kind="brief",
                label=label,
                summary=text,
                provenance=Provenance(
                    source="briefing",
                    note=f"synthesis of {len(b.get('citations') or [])} cited findings",
                ),
                data={"theme": theme, "scope": bid,
                      "generated_at": b.get("generated_at", "")},
            )
            cg.add_node(node)
            emitted.append(node.id)
            for insight_id in (b.get("citations") or []):
                target = _finding_node_id(str(insight_id))
                if target not in cg.nodes:
                    continue  # cited something this graph doesn't hold — no dangling edge
                cg.add_edge(GraphEdge(
                    id=_edge_id(node.id, "derived_from", target),
                    kind="derived_from",
                    from_id=node.id,
                    to_id=target,
                    provenance=Provenance(source="briefing",
                                          note="brief cites finding"),
                    label="cites",
                ))
        except Exception as exc:
            tolerate(exc, "context-graph brief projection is per-brief best-effort",
                     counter="context_graph.brief_projection")
    return emitted
