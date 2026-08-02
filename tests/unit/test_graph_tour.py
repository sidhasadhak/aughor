"""Wave C5 — the connection tour. The gate: an ORDERED CURRICULUM (topology order, every
step connects to a prior), not a notability listicle. All deterministic — no LLM."""
from __future__ import annotations


from aughor.ontology.context_graph import ContextGraph, GraphEdge, GraphNode, Provenance
from aughor.ontology.graph_tour import build_tour


def _star(org: str = "o") -> ContextGraph:
    """A star schema: Sale (fact) joins Product/Customer/Store (dims); Log is standalone;
    Revenue is a metric derived from Sale."""
    cg = ContextGraph(org_id=org, connection_id="c", schema_name="main")
    for t in ["Sale", "Product", "Customer", "Store", "Log"]:
        cg.add_node(GraphNode(id=f"table:{t}", kind="table", label=t,
                              provenance=Provenance(source="ontology.entity"),
                              data={"source_tables": [t.lower()], "columns": ["id"]}))
    for dim in ["Product", "Customer", "Store"]:
        cg.add_edge(GraphEdge(id=f"e_{dim}", kind="joins_on", from_id="table:Sale",
                              to_id=f"table:{dim}", provenance=Provenance(source="join_guard", measured=0.9)))
    cg.add_node(GraphNode(id="metric:revenue", kind="metric", label="Revenue",
                          provenance=Provenance(source="ontology.metric"), data={}))
    cg.add_edge(GraphEdge(id="e_rev", kind="derived_from", from_id="metric:revenue",
                          to_id="table:Sale", provenance=Provenance(source="ontology.metric")))
    return cg


def test_entry_is_the_hub():
    tour = build_tour(_star())
    assert tour.steps[0].node_id == "table:Sale"       # highest join degree
    assert tour.steps[0].connects_to is None


def test_every_step_after_first_connects_to_an_earlier_step():
    """The curriculum property: a step never dangles — it names a prior step it builds on."""
    tour = build_tour(_star())
    seen: set[str] = set()
    for s in tour.steps:
        if s.order == 0:
            assert s.connects_to is None
        else:
            assert s.connects_to is not None
            assert s.connects_to in seen, f"{s.label} connects to a step not yet seen"
        seen.add(s.node_id)


def test_order_is_bfs_topology_not_notability():
    tour = build_tour(_star())
    table_ids = [s.node_id for s in tour.steps if s.kind == "table"]
    assert table_ids[0] == "table:Sale"                # hub first
    assert set(table_ids[1:4]) == {"table:Customer", "table:Product", "table:Store"}  # its dims next


def test_metrics_are_the_capstone():
    tour = build_tour(_star())
    kinds = [s.kind for s in tour.steps]
    last_table = max(i for i, k in enumerate(kinds) if k == "table")
    first_metric = min(i for i, k in enumerate(kinds) if k == "metric")
    assert last_table < first_metric                   # every table before every metric
    m = next(s for s in tour.steps if s.kind == "metric")
    assert m.connects_to == "table:Sale"               # tied to the table it derives from


def test_standalone_table_follows_the_core_and_connects_to_entry():
    tour = build_tour(_star())
    log = next(s for s in tour.steps if s.node_id == "table:Log")
    assert log.connects_to == "table:Sale"             # no joins → tied to the hub
    assert log.order > 0


def test_deterministic_across_runs():
    a = [s.node_id for s in build_tour(_star()).steps]
    b = [s.node_id for s in build_tour(_star()).steps]
    assert a == b


def test_empty_graph_is_an_empty_tour():
    assert build_tour(ContextGraph(org_id="o", connection_id="c")).steps == []


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_tour_endpoint_serves_the_ordered_curriculum(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as store
    monkeypatch.setattr(store, "_ROOT", tmp_path / "context_graph")
    store.save_graph(_star(org="default"))

    from aughor.routers.ontology import get_context_graph_tour
    payload = get_context_graph_tour("c", "main", False)  # narrate=False → no LLM
    assert payload["steps"][0]["node_id"] == "table:Sale"
    assert payload["narrated"] is False
    assert all(s["connects_to"] for s in payload["steps"][1:])
