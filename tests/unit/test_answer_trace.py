"""Wave P1 — every answer resolves to the graph subgraph behind it.

The load-bearing property: the trace must have content in the DEFAULT configuration.
`graph.readback` is an off-by-default experiment, so a trace built only from the nodes the
planner was shown would be empty on every production answer — both ends of a feature
existing while the feature does not. These tests fix that by construction.
"""
from __future__ import annotations

import pytest

from aughor.ontology.answer_trace import build_answer_trace, trace_from_receipt
from aughor.ontology.context_graph import project_graph
from aughor.ontology.models import OntologyEntity, OntologyGraph, OntologyRelationship


def _graph():
    onto = OntologyGraph(connection_id="c", schema_name="main", schema_fingerprint="fp")
    onto.entities = {
        "Order": OntologyEntity(id="Order", display_name="Order", source_tables=["orders"],
                                identity_key="id", grain_verified=True, domain="Commerce"),
        "Customer": OntologyEntity(id="Customer", display_name="Customer",
                                   source_tables=["customers"], identity_key="id",
                                   grain_verified=True, domain="Customer"),
    }
    onto.relationships = {"r": OntologyRelationship(
        id="r", from_entity="Order", to_entity="Customer", cardinality="N:1",
        join_sql="orders.customer_id = customers.id", from_table="orders",
        from_col="customer_id", to_table="customers", to_col="id",
        join_confidence="verified", value_overlap=0.98)}
    return project_graph(onto, org_id="default", connection_id="c", schema_name="main")


@pytest.fixture
def store(monkeypatch, tmp_path):
    from aughor.ontology import context_graph_store as s
    monkeypatch.setattr(s, "_ROOT", tmp_path / "context_graph")
    s.save_graph(_graph())
    return s


# ── the property that makes this a feature and not a seam ────────────────────────

def test_trace_has_content_without_the_readback_experiment(store):
    """No cited nodes at all — the default configuration — and the walk is still real."""
    trace = build_answer_trace("c", tables=["orders", "customers"], org_id="default")
    assert trace is not None
    assert {n.id for n in trace.nodes} == {"table:Order", "table:Customer"}
    assert all(n.reason == "read" for n in trace.nodes)
    assert all(n.present for n in trace.nodes)


def test_the_walk_carries_the_join_between_the_tables_the_answer_read(store):
    """The join is the most checkable thing on a receipt — it is where wrong answers come
    from — and it arrives with the warrant behind it (P2)."""
    trace = build_answer_trace("c", tables=["orders", "customers"], org_id="default")
    joins = [e for e in trace.edges if e["kind"] == "joins_on"]
    assert len(joins) == 1
    assert joins[0]["warrant"]["warrant"] == "measured"
    assert "98%" in joins[0]["warrant"]["detail"]


def test_schema_qualified_table_names_resolve(store):
    trace = build_answer_trace("c", tables=["main.orders"], org_id="default")
    assert [n.id for n in trace.nodes] == ["table:Order"]


def test_a_table_the_graph_does_not_model_is_named_not_dropped(store):
    """Silently showing 3 of 4 tables would be the wrong answer to 'check every node'."""
    trace = build_answer_trace("c", tables=["orders", "shipments"], org_id="default")
    unresolved = [n for n in trace.nodes if not n.present]
    assert len(unresolved) == 1
    assert unresolved[0].label == "shipments"
    assert trace.has_unresolved is True
    # …and an unresolved node never contributes an edge to the walk
    assert all(e["from_id"] != unresolved[0].id and e["to_id"] != unresolved[0].id
               for e in trace.edges)


def test_cited_nodes_win_over_read_nodes(store):
    """A node BOTH shown to the planner and read by the SQL is attributed to the stronger
    fact — the planner saw it before writing the query."""
    trace = build_answer_trace("c", tables=["orders"], cited_node_ids=["table:Order"],
                               org_id="default")
    assert [n.reason for n in trace.nodes] == ["cited"]


def test_edge_ids_in_the_citation_list_are_not_mistaken_for_nodes(store):
    """The read-back cites joins by EDGE id; an edge is not a node."""
    edge_id = next(iter(_graph().edges))
    trace = build_answer_trace("c", tables=["orders"], cited_node_ids=[edge_id],
                               org_id="default")
    assert all(n.id != edge_id for n in trace.nodes)
    assert trace.has_unresolved is False


def test_no_graph_returns_none_not_an_empty_walk(monkeypatch, tmp_path):
    """An empty walk reads as 'nothing grounded this answer', which is a different and
    false claim from 'this connection has no graph'."""
    from aughor.ontology import context_graph_store as s
    monkeypatch.setattr(s, "_ROOT", tmp_path / "context_graph")
    assert build_answer_trace("c", tables=["orders"], org_id="default") is None


def test_build_never_raises_into_the_answer_path(monkeypatch):
    import aughor.ontology.answer_trace as mod

    def _boom(*a, **k):
        raise RuntimeError("store is down")

    monkeypatch.setattr(mod, "_build", _boom)
    assert mod.build_answer_trace("c", tables=["orders"]) is None


def test_metrics_resolve_to_metric_nodes(store):
    from aughor.ontology.context_graph import GraphNode, Provenance
    g = _graph()
    g.add_node(GraphNode(id="metric:revenue", kind="metric", label="Revenue",
                         provenance=Provenance(source="ontology.metric")))
    store.save_graph(g)
    trace = build_answer_trace("c", tables=[], metrics=["revenue"], org_id="default")
    assert [(n.id, n.reason) for n in trace.nodes] == [("metric:revenue", "metric")]


# ── the receipt seam ─────────────────────────────────────────────────────────────

def test_trace_from_receipt_handles_the_real_metrics_shape(store):
    """`metrics.used` is a list of NAMES; its sibling `drifted` is a list of dicts.
    Assuming dicts raised on every real receipt while a unit test passing an empty list
    stayed green — the route test is what caught it, so the shape is pinned here."""
    from aughor.ontology.context_graph import GraphNode, Provenance
    g = _graph()
    g.add_node(GraphNode(id="metric:revenue", kind="metric", label="Revenue",
                         provenance=Provenance(source="ontology.metric")))
    store.save_graph(g)
    receipt = {
        "id": "r1", "connection": {"id": "c"}, "input_tables": ["orders"],
        "metrics": {"used": ["revenue"],                       # ← strings
                    "drifted": [{"metric": "margin", "detail": None}],
                    "available": [], "proposed": []},
        "grounded_in_graph": [],
    }
    out = trace_from_receipt(receipt, org_id="default")
    assert {n["id"] for n in out["nodes"]} == {"table:Order", "metric:revenue"}


def test_trace_from_receipt_reads_the_receipts_own_fields(store):
    receipt = {
        "id": "r1",
        "connection": {"id": "c"},
        "input_tables": ["orders", "customers"],
        "metrics": {"used": [], "drifted": [], "available": [], "proposed": []},
        "grounded_in_graph": [],
    }
    out = trace_from_receipt(receipt, org_id="default")
    assert out is not None
    assert out["counts"]["nodes"] == 2
    assert out["counts"]["edges"] == 1
    assert out["nodes"][0]["why"]                      # every node explains why it is here


def test_trace_from_receipt_without_a_connection_is_none(store):
    assert trace_from_receipt({"id": "r1", "connection": {}}, org_id="default") is None


# ── the invariant that nearly shipped broken ─────────────────────────────────────

def test_the_trace_is_not_folded_into_the_signed_receipt(store, monkeypatch):
    """`_canonical` signs EVERY field except `signature`, so attaching a live, mutable
    trace to the receipt body would break `verify()` on the next read. The trace is a
    separate call for exactly this reason — this test fails if someone merges it back in.
    """
    monkeypatch.setenv("AUGHOR_SECRET_KEY", "test-secret")
    from aughor.trust.receipt import build_public_receipt, verify

    raw = {
        "artifact": {"id": "r1", "kind": "chat_answer", "conn_id": "c",
                     "created_at": "2026-08-04T00:00:00Z",
                     "payload": {"question": "q", "headline": "h", "sql": "SELECT 1",
                                 "tables": ["orders"]}},
        "lineage": [{"relation": "input", "ref": "table:orders", "detail": None},
                    {"relation": "grounded_in_graph", "ref": "table:Order", "detail": None}],
    }
    receipt = build_public_receipt(raw, connection={"id": "c", "name": None, "dialect": None})
    assert receipt["grounded_in_graph"] == ["table:Order"]   # ids ARE signed (immutable)
    assert verify(receipt)

    receipt["grounding_trace"] = {"nodes": [], "edges": []}
    assert not verify(receipt), "a trace attached to the signed body invalidates the signature"


# ── the seam that was structurally dead ──────────────────────────────────────────

def test_citations_cross_the_executor_boundary(monkeypatch, tmp_path):
    """A ContextVar `.set()` inside `contextvars.copy_context().run(...)` NEVER propagates
    back to the submitter — and the deep-analysis path builds its priors in exactly such a
    pool. The citations were therefore invisible to the receipt writer on the request
    context: the read-back fired and the receipt recorded nothing, silently, because an
    empty list is also what 'the flag is off' looks like.

    This proves the explicit hand-back works across the real executor.
    """
    from aughor.kernel.concurrency import ContextThreadPoolExecutor
    from aughor.ontology.context_graph_readback import (
        _last_cited, last_cited_nodes, publish_cited_nodes,
    )

    _last_cited.set([])

    def _worker():
        # Stand in for build_graph_prior, which sets the contextvar inside the worker.
        _last_cited.set(["table:Order", "finding:f1"])
        return last_cited_nodes()

    with ContextThreadPoolExecutor(max_workers=1) as pool:
        produced = pool.submit(_worker).result()

    assert produced == ["table:Order", "finding:f1"]
    # Without the hand-back the parent context still sees nothing — the defect itself.
    assert last_cited_nodes() == []
    publish_cited_nodes(produced)
    assert last_cited_nodes() == ["table:Order", "finding:f1"]


def test_publishing_an_empty_list_does_not_erase_real_citations():
    """The chat path sets the var directly; a later empty publish must not wipe it."""
    from aughor.ontology.context_graph_readback import (
        _last_cited, last_cited_nodes, publish_cited_nodes,
    )
    _last_cited.set(["table:Order"])
    publish_cited_nodes([])
    assert last_cited_nodes() == ["table:Order"]


def test_two_schemas_with_the_same_bare_table_do_not_cross_resolve(store):
    """`merge_graphs` unions one graph per schema, so `sales.orders` and `staging.orders`
    both reduce to the bare key `orders`. Rendering one schema's node for the other's
    table would show the wrong label, summary, warrant and edges."""
    from aughor.ontology.context_graph import GraphNode, Provenance
    g = _graph()
    g.add_node(GraphNode(id="table:StagingOrder", kind="table", label="Staging Order",
                         provenance=Provenance(source="ontology.entity"),
                         data={"source_tables": ["staging.orders"]}))
    # table:Order already backs "orders" (bare, from the fixture)
    store.save_graph(g)

    # The qualified name resolves exactly…
    t = build_answer_trace("c", tables=["staging.orders"], org_id="default")
    assert [n.id for n in t.nodes] == ["table:StagingOrder"]

    # …and an AMBIGUOUS bare name resolves to nothing rather than to whichever node was
    # iterated first.
    g2 = _graph()
    g2.add_node(GraphNode(id="table:Other", kind="table", label="Other",
                          provenance=Provenance(source="ontology.entity"),
                          data={"source_tables": ["orders"]}))
    store.save_graph(g2)
    t2 = build_answer_trace("c", tables=["orders"], org_id="default")
    assert all(not n.present for n in t2.nodes), \
        "an ambiguous bare table name must not silently pick a winner"
