"""Wave C3 — graph freshness: the change-classifier, staleness, refresh, token budget.

The classifier is the gate's heart: a nightly reload (row counts move, structure
identical) must NOT rebuild; a column add is PARTIAL; a table add/drop is FULL. All
deterministic — no LLM, no infra (refresh runs with reindex=False so no Qdrant/Ollama).
"""
from __future__ import annotations

from aughor.ontology.context_graph import project_graph
from aughor.ontology.graph_freshness import (
    classify,
    structural_fingerprint,
    table_fingerprints,
)
from aughor.ontology.models import OntologyEntity, OntologyGraph


def _ent(eid: str, table: str, cols: dict[str, str]) -> OntologyEntity:
    return OntologyEntity(
        id=eid, display_name=eid, source_tables=[table], identity_key="id",
        grain_verified=True,
        properties={c: {"name": c, "data_type": t} for c, t in cols.items()},
    )


def _onto(entities, *, data_fp: str) -> OntologyGraph:
    g = OntologyGraph(connection_id="c", schema_name="main", schema_fingerprint=data_fp)
    g.entities = {e.id: e for e in entities}
    return g


def _order(cols) -> OntologyEntity:
    return _ent("Order", "orders", cols)


def _graph_of(onto):
    return project_graph(onto, org_id="o", connection_id="c", schema_name="main")


# ── fingerprints ────────────────────────────────────────────────────────────

def test_structural_fingerprint_ignores_row_count():
    """The load-bearing split: two ontologies identical in structure but with different
    DATA fingerprints (row counts moved) have the SAME structural fingerprint."""
    a = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d1")
    b = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d2")
    assert structural_fingerprint(a) == structural_fingerprint(b)
    assert a.schema_fingerprint != b.schema_fingerprint


def test_structural_fingerprint_moves_on_a_column_change():
    a = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d1")
    b = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL", "status": "VARCHAR"})], data_fp="d1")
    assert structural_fingerprint(a) != structural_fingerprint(b)
    assert table_fingerprints(a)["Order"] != table_fingerprints(b)["Order"]


# ── the classifier ───────────────────────────────────────────────────────────

def test_no_change_is_skip_fresh():
    a = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d1")
    v = classify(_graph_of(a), a)
    assert v.change == "skip" and v.staleness == "fresh" and not v.needs_rebuild


def test_nightly_reload_is_dirty_but_not_rebuilt():
    """The gate: row counts changed, structure identical ⇒ SKIP (no rebuild), DIRTY."""
    a = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d1")
    graph = _graph_of(a)
    reloaded = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d2")
    v = classify(graph, reloaded)
    assert v.change == "skip" and v.staleness == "dirty" and not v.needs_rebuild


def test_column_add_is_partial_naming_the_table():
    a = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d1")
    graph = _graph_of(a)
    b = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL", "status": "VARCHAR"})], data_fp="d1")
    v = classify(graph, b)
    assert v.change == "partial" and v.needs_rebuild
    assert v.changed_tables == ["Order"]


def test_table_add_is_full():
    a = _onto([_order({"id": "INTEGER"})], data_fp="d1")
    graph = _graph_of(a)
    b = _onto([_order({"id": "INTEGER"}), _ent("Customer", "customers", {"id": "INTEGER"})],
              data_fp="d1")
    v = classify(graph, b)
    assert v.change == "full" and v.needs_rebuild


def test_table_drop_is_full():
    a = _onto([_order({"id": "INTEGER"}), _ent("Customer", "customers", {"id": "INTEGER"})],
              data_fp="d1")
    graph = _graph_of(a)
    b = _onto([_order({"id": "INTEGER"})], data_fp="d1")
    assert classify(graph, b).change == "full"


def test_no_ontology_is_unknown_and_no_prev_is_full():
    a = _onto([_order({"id": "INTEGER"})], data_fp="d1")
    assert classify(_graph_of(a), None).change == "unknown"
    first = classify(None, a)
    assert first.change == "full" and first.staleness == "stale"


# ── the read-back token budget ───────────────────────────────────────────────

def test_readback_slice_respects_its_token_budget(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    from aughor.ontology.context_graph import ContextGraph, GraphEdge, GraphNode, Provenance
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    monkeypatch.setenv("AUGHOR_GRAPH_READBACK", "1")

    # a graph with many long findings on one table — the slice would blow a small budget
    cg = ContextGraph(org_id="o", connection_id="c", schema_name="main")
    cg.add_node(GraphNode(id="table:Order", kind="table", label="Order",
                          provenance=Provenance(source="ontology.entity"),
                          data={"source_tables": ["orders"], "columns": ["id"]}))
    for i in range(20):
        cg.add_node(GraphNode(id=f"finding:f{i}", kind="finding", label=f"finding {i} about orders",
                              summary="orders " + ("blah " * 60), provenance=Provenance(source="dossier"),
                              data={"tables": ["orders"]}))
        cg.add_edge(GraphEdge(id=f"e{i}", kind="grounded_in", from_id=f"finding:f{i}",
                              to_id="table:Order", provenance=Provenance(source="dossier")))
    store.save_graph(cg)

    from aughor.ontology.context_graph_readback import build_graph_prior
    budget = 400
    p = build_graph_prior("orders", "c", org_id="o", max_chars=budget)
    assert p.fired
    # respects the budget (+ the short truncation marker + trailing newline)
    assert len(p.section) <= budget + 60
    assert "truncated to budget" in p.section


# ── refresh (deterministic; reindex off so no Qdrant/Ollama) ──────────────────

def test_refresh_gated_off_is_noop(monkeypatch):
    from aughor.ontology.graph_freshness import refresh_context_graph
    monkeypatch.setenv("AUGHOR_GRAPH_FRESHNESS", "0")
    assert refresh_context_graph("any-conn") is None


def test_refresh_builds_then_skips(monkeypatch):
    """First refresh (no committed graph) is FULL and rebuilds; a second with the same
    ontology is SKIP and does no work — refresh cost proportional to change."""
    from aughor.ontology.store import save_ontology
    from aughor.ontology.graph_freshness import refresh_context_graph
    monkeypatch.setenv("AUGHOR_GRAPH_FRESHNESS", "1")
    monkeypatch.setenv("AUGHOR_GRAPH_BUILD", "1")

    onto = _onto([_order({"id": "INTEGER", "revenue": "DECIMAL"})], data_fp="d1")
    save_ontology("c", "main", "d1", onto)

    first = refresh_context_graph("c", "main", org_id="o", reindex=False)
    assert first is not None and first.verdict.change == "full" and first.rebuilt

    second = refresh_context_graph("c", "main", org_id="o", reindex=False)
    assert second is not None and second.verdict.change == "skip" and not second.rebuilt

    # Wave L1: an exploration writes FINDINGS, which the schema classifier cannot see —
    # so a run that discovered a dozen insights and changed no column classifies SKIP.
    # `force` rebuilds anyway; without it those findings would never land.
    forced = refresh_context_graph("c", "main", org_id="o", reindex=False, force=True)
    assert forced is not None and forced.verdict.change == "skip" and forced.rebuilt


def test_forced_refresh_bypasses_the_freshness_flag_but_not_the_build_flag(monkeypatch):
    """`graph.freshness` gates change CLASSIFICATION, and a forced caller isn't asking
    for one — but the WRITE is still gated by `graph.build`, so flag-off stays
    byte-identical."""
    from aughor.ontology.store import save_ontology
    from aughor.ontology.graph_freshness import refresh_context_graph
    monkeypatch.setenv("AUGHOR_GRAPH_FRESHNESS", "0")
    save_ontology("cf", "main", "d1",
                  _onto([_order({"id": "INTEGER"})], data_fp="d1"))

    monkeypatch.setenv("AUGHOR_GRAPH_BUILD", "0")
    off = refresh_context_graph("cf", "main", org_id="o", reindex=False, force=True)
    assert off is not None and not off.rebuilt        # ran, but wrote nothing

    monkeypatch.setenv("AUGHOR_GRAPH_BUILD", "1")
    on = refresh_context_graph("cf", "main", org_id="o", reindex=False, force=True)
    assert on is not None and on.rebuilt
