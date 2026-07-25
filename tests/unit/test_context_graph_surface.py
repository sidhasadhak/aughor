"""Wave C4 — the graph surface endpoint (GET /graph). Hermetic: builds a synthetic
graph, saves it to an isolated store, and calls the handler directly."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from aughor.ontology.context_graph import project_graph
from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyRelationship


def _graph():
    onto = OntologyGraph(connection_id="c", schema_name="main", schema_fingerprint="fp")
    onto.entities = {
        "Order": OntologyEntity(id="Order", display_name="Order", source_tables=["orders"],
                                identity_key="id", grain_verified=True, domain="Commerce",
                                properties={"id": {"name": "id"}, "revenue": {"name": "revenue"}}),
        "Customer": OntologyEntity(id="Customer", display_name="Customer", source_tables=["customers"],
                                   identity_key="id", grain_verified=True, domain="Customer"),
    }
    onto.relationships = {"r": OntologyRelationship(
        id="r", from_entity="Order", to_entity="Customer", cardinality="N:1",
        join_sql="orders.customer_id = customer.id", from_table="orders", from_col="customer_id",
        to_table="customers", to_col="id", join_confidence="verified", value_overlap=1.0)}
    return project_graph(onto, org_id="default", connection_id="c", schema_name="main")


def test_graph_endpoint_404_when_flag_off(monkeypatch):
    monkeypatch.setenv("AUGHOR_GRAPH_SURFACE", "0")
    from aughor.routers.ontology import get_context_graph
    with pytest.raises(HTTPException) as ei:
        get_context_graph("c", None)
    assert ei.value.status_code == 404


def test_graph_endpoint_serves_nodes_edges_and_domain_aggregation(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    monkeypatch.setenv("AUGHOR_GRAPH_SURFACE", "1")
    store.save_graph(_graph())

    from aughor.routers.ontology import get_context_graph
    payload = get_context_graph("c", "main")

    assert "nodes" in payload and "edges" in payload
    assert payload["counts"]["table"] == 2
    # level-1 aggregation: two domains, cross-domain joins collapsed to a count
    labels = {d["label"] for d in payload["domains"]}
    assert {"Commerce", "Customer"} <= labels
    dedge = payload["domain_edges"][0]
    assert dedge["count"] >= 1  # Commerce↔Customer join, aggregated
    assert payload["staleness"] in ("fresh", "dirty", "stale", "unknown")


def test_graph_domain_aggregation_collapses_cross_domain_edges():
    from aughor.routers.ontology import _graph_domain_aggregation
    agg = _graph_domain_aggregation(_graph())
    # one aggregated edge per domain pair (never a per-table hairball)
    assert len(agg["domain_edges"]) == 1
    assert agg["domain_edges"][0]["count"] == 1
