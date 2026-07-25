"""Wave C1 — the connection knowledge graph projection + store.

Hermetic: the projection is pure (no DB, no LLM), so every test constructs a
synthetic OntologyGraph in memory. The store tests redirect the artifact root to a
tmp path. These encode the C1 decision gate: every edge carries provenance citing
measured evidence, accepted joins_on edges surface value_overlap, and findings
(the write-only half of the open loop) become nodes.
"""
from __future__ import annotations

import types

import pytest
from pydantic import ValidationError

from aughor.ontology.models import (
    OntologyEntity,
    OntologyGraph,
    OntologyMetric,
    OntologyRelationship,
)
from aughor.ontology import context_graph as cg_mod
from aughor.ontology.context_graph import (
    ContextGraph,
    GraphEdge,
    Provenance,
    ProvenanceSource,
    project_graph,
)


def _entity(eid: str, table: str, *, domain: str | None = None, cols=("id",)) -> OntologyEntity:
    return OntologyEntity(
        id=eid,
        display_name=eid,
        source_tables=[table],
        identity_key="id",
        grain_verified=True,
        domain=domain,
        properties={c: {"name": c} for c in cols},  # EntityProperty coerces from dict
    )


def _rel(from_e: str, to_e: str, *, overlap, confidence="inferred") -> OntologyRelationship:
    return OntologyRelationship(
        id=f"{from_e}_to_{to_e}",
        from_entity=from_e,
        to_entity=to_e,
        cardinality="N:1",
        join_sql=f"{from_e.lower()}.id = {to_e.lower()}.id",
        from_table=from_e.lower(),
        from_col="id",
        to_table=to_e.lower(),
        to_col="id",
        join_confidence=confidence,
        value_overlap=overlap,
    )


def _ontology() -> OntologyGraph:
    g = OntologyGraph(connection_id="c1", schema_name="main", schema_fingerprint="fp1")
    g.entities = {
        "Order": _entity("Order", "orders", domain="Commerce", cols=("id", "customer_id", "revenue")),
        "Customer": _entity("Customer", "customers", domain="Customer"),
    }
    g.relationships = {"r1": _rel("Order", "Customer", overlap=0.98, confidence="verified")}
    g.metrics = {
        "revenue": OntologyMetric(
            id="revenue", display_name="Revenue", entity="Order",
            formula_sql="SUM(revenue)", tables=["orders"], verified=True,
        )
    }
    return g


def _build(**kw) -> ContextGraph:
    return project_graph(_ontology(), org_id="org1", connection_id="c1",
                         schema_name="main", **kw)


# ── the type system ───────────────────────────────────────────────────────────

def test_provenance_is_required_on_every_edge():
    """J4 by construction: an edge without provenance is not constructible."""
    with pytest.raises(ValidationError):
        GraphEdge(id="e", kind="joins_on", from_id="a", to_id="b")  # no provenance


def test_no_self_reported_confidence_source_exists():
    """The banned provenance sources (self-reported model confidences) must not be
    part of the allowed set — the design guarantee, checked as a ratchet."""
    allowed = set(ProvenanceSource.__args__)  # type: ignore[attr-defined]
    assert "evidence_confidence" not in allowed
    assert "llm_inferred" not in allowed
    # the strongest measured source IS present
    assert "join_guard" in allowed


# ── the projection ────────────────────────────────────────────────────────────

def test_tables_metrics_and_domains_projected():
    g = _build()
    tables = {n.id for n in g.nodes_of("table")}
    assert tables == {"table:Order", "table:Customer"}
    assert {n.id for n in g.nodes_of("metric")} == {"metric:revenue"}
    assert {n.label for n in g.nodes_of("domain")} == {"Commerce", "Customer"}
    # the table node carries its columns + domain, not just a name
    order = g.nodes["table:Order"]
    assert order.data["domain"] == "Commerce"
    assert "revenue" in order.data["columns"]


def test_every_edge_carries_provenance_with_a_source():
    """The C1 gate: zero edges without provenance."""
    g = _build()
    assert g.edges  # non-empty
    for e in g.edges.values():
        assert isinstance(e.provenance, Provenance)
        assert e.provenance.source  # non-empty ProvenanceSource


def test_joins_on_surfaces_the_measured_overlap():
    """The J4 showcase: an accepted join edge carries the measured value_overlap as a
    number (not collapsed to a boolean), sourced from the join guard."""
    g = _build()
    joins = g.nodes_of  # noqa: F841 (readability)
    edge = next(e for e in g.edges.values() if e.kind == "joins_on")
    assert edge.from_id == "table:Order" and edge.to_id == "table:Customer"
    assert edge.provenance.source == "join_guard"
    assert edge.provenance.measured == pytest.approx(0.98)
    assert "value_overlap=0.980" in edge.provenance.note


def test_unprobed_join_is_honest_not_faked():
    """An unprobed relationship still projects (it is a real ontology edge) but says
    so — measured is None and the note reads 'unprobed', never a fabricated number."""
    g = OntologyGraph(connection_id="c1", schema_fingerprint="fp")
    g.entities = {"A": _entity("A", "a"), "B": _entity("B", "b")}
    g.relationships = {"r": _rel("A", "B", overlap=None)}
    out = project_graph(g, org_id="o", connection_id="c1")
    edge = next(e for e in out.edges.values() if e.kind == "joins_on")
    assert edge.provenance.measured is None
    assert "unprobed" in edge.provenance.note


def test_dangling_edge_is_never_emitted():
    """A relationship whose endpoint has no entity node must not produce a floating
    edge (the anti-hairball / integrity guarantee)."""
    g = OntologyGraph(connection_id="c1", schema_fingerprint="fp")
    g.entities = {"A": _entity("A", "a")}  # B is missing
    g.relationships = {"r": _rel("A", "B", overlap=0.9)}
    out = project_graph(g, org_id="o", connection_id="c1")
    assert not [e for e in out.edges.values() if e.kind == "joins_on"]


def test_derived_from_links_metric_to_its_tables():
    g = _build()
    edge = next(e for e in g.edges.values() if e.kind == "derived_from")
    assert edge.from_id == "metric:revenue"
    assert edge.to_id == "table:Order"  # revenue reads the orders table


def test_glossary_terms_are_scoped_to_the_connection():
    """The global-by-name store is read-time-scoped: a term on a table this
    connection does not expose is dropped; only described columns become terms."""
    merged = {
        "orders": {"columns": {
            "revenue": {"description": "gross booking value, pre-refund"},
            "id": {},  # no description → not a term
        }},
        "unrelated_table": {"columns": {"x": {"description": "some other connection"}}},
    }
    g = _build(merged_glossary=merged)
    terms = {n.label for n in g.nodes_of("glossary_term")}
    assert "revenue" in terms
    assert "id" not in terms
    assert "x" not in terms  # scoped out — different connection's table
    # defines edge: term 'revenue' → metric:revenue (exact name match)
    assert any(e.kind == "defines" and e.to_id == "metric:revenue"
               for e in g.edges.values())


def test_findings_become_nodes_with_grounded_in_edges():
    """The write-only half of the open loop, finally a node. Provenance is the
    derivation source — never the finding's self-reported confidence."""
    findings = [{
        "id": "f1",
        "text": "32% of orders never reach a terminal state",
        "sql": "SELECT ... FROM orders",
        "tables": ["orders"],
        "source": "dossier",
        "generated_at": "2026-07-25T00:00:00Z",
    }]
    g = _build(findings=findings)
    fnode = g.nodes["finding:f1"]
    assert fnode.kind == "finding"
    assert fnode.provenance.source == "dossier"
    assert fnode.provenance.measured is None  # confidence is NOT laundered into a measurement
    edge = next(e for e in g.edges.values() if e.kind == "grounded_in")
    assert edge.from_id == "finding:f1" and edge.to_id == "table:Order"


def test_resolutions_project_to_resolves_edges():
    res = types.SimpleNamespace(
        id="res1", subject="revenue", resolved_reading="gross, pre-refund",
        resolution_source="verdict", evidence="reviewer accepted",
    )
    g = _build(resolutions=[res])
    edge = next(e for e in g.edges.values() if e.kind == "resolves")
    assert edge.provenance.source == "ambiguity_ledger"
    assert "resolution_source=verdict" in edge.provenance.note


def test_counts_shape():
    g = _build()
    c = g.counts()
    assert c["table"] == 2 and c["metric"] == 1 and c["edges"] == len(g.edges)


# ── the committed-artifact store ──────────────────────────────────────────────

def test_store_roundtrip_and_version_bump(tmp_path, monkeypatch):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")

    g = _build()
    path = store.save_graph(g)
    assert path.exists()
    assert g.version == 1

    loaded = store.load_graph("org1", "c1", "main")
    assert loaded is not None
    assert set(loaded.nodes) == set(g.nodes)
    assert set(loaded.edges) == set(g.edges)

    # a rebuild supersedes: version bumps, one file (git holds history)
    again = store.save_graph(_build())
    assert store.load_graph("org1", "c1", "main").version == 2
    assert again == path  # same committed path


def test_store_missing_returns_none(tmp_path, monkeypatch):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    assert store.load_graph("org1", "nope", "main") is None


# ── the flag gate (byte-identical when off) ───────────────────────────────────

def test_build_returns_none_when_flag_off():
    """Default off ⇒ the projection is never invoked and nothing is written."""
    from aughor.ontology.context_graph_build import build_context_graph
    # graph.build is default-off; no override set here.
    assert build_context_graph("any-conn") is None


def test_module_has_no_llm_or_sql_imports():
    """The projection must be a real program calling neither — a ratchet against the
    pipeline-as-prompt anti-pattern creeping in."""
    import inspect
    src = inspect.getsource(cg_mod)
    assert "provider" not in src and "complete(" not in src
    assert "execute(" not in src and "db.execute" not in src
