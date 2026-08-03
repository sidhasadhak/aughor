"""Wave C4 — the graph surface endpoint (GET /graph). Hermetic: builds a synthetic
graph, saves it to an isolated store, and calls the handler directly."""
from __future__ import annotations


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


def test_graph_endpoint_serves_nodes_edges_and_domain_aggregation(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
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


# ── Wave P2 — the warrant class on the surface, and the audit scorecard ──────────

def test_graph_endpoint_stamps_a_warrant_on_every_node_and_edge(monkeypatch, tmp_path):
    """Derived at READ time: the artifact on disk is untouched, but no surface has to
    re-derive 'how do we know this' from a source name it cannot rank."""
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    store.save_graph(_graph())

    from aughor.routers.ontology import get_context_graph
    payload = get_context_graph("c", "main")

    assert all("warrant" in n for n in payload["nodes"].values())
    assert all("warrant" in e for e in payload["edges"].values())
    join = next(e for e in payload["edges"].values() if e["kind"] == "joins_on")
    assert join["warrant"]["warrant"] == "measured"      # value_overlap=1.0 was probed
    assert join["warrant"]["label"] == "Measured"

    # …and the artifact itself never gained the field (structural truth stays structural).
    on_disk = store.load_graph("default", "c", "main")
    assert on_disk is not None
    assert "warrant" not in on_disk.edges[join["id"]].model_dump()


def test_graph_audit_reports_the_warrant_mix_with_both_freshness_axes(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    store.save_graph(_graph())

    from aughor.routers.ontology import get_context_graph_audit
    out = get_context_graph_audit("c", "main")

    assert out["totals"]["edges"] >= 1
    assert out["edges"]["measured"] >= 1
    # every class present even at zero — a scorecard that hid its empty weak classes
    # would read as "nothing weak here"
    assert set(out["edges"]) == set(out["order"])
    assert 0.0 <= out["edge_grounded_share"] <= 1.0
    # both freshness axes travel with the mix; neither may be silently omitted
    assert "staleness" in out
    assert "drift" in out
