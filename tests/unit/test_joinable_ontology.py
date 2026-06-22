"""Persist joinable_with as first-class ontology edges (ROADMAP §3). At ontology-build the
relationships' join edges are value-verified: a real FK gets join_confidence='verified' + its
probed value_overlap stamped, and a value-DISJOINT name coincidence is DROPPED from the graph
entirely — so the persisted (cross-process, reviewable) ontology never carries a fabricating edge,
beyond the in-process catalog cache. This tests the pure overlay `apply_join_verifications`."""
from __future__ import annotations

from aughor.ontology.builder import apply_join_verifications, _edge_key
from aughor.ontology.models import OntologyGraph, OntologyRelationship
from aughor.sql.join_guard import VerifiedJoin


def _rel(rid, fe, te, ft, fc, tt, tc, conf="inferred"):
    return OntologyRelationship(
        id=rid, from_entity=fe, to_entity=te, cardinality="N:1",
        join_sql=f"{ft}.{fc} = {tt}.{tc}", from_table=ft, from_col=fc,
        to_table=tt, to_col=tc, join_confidence=conf)


def _graph(*rels):
    return OntologyGraph(connection_id="c", schema_fingerprint="f",
                         relationships={r.id: r for r in rels})


def test_verified_edge_is_stamped_and_marked_verified():
    g = _graph(_rel("R1", "Order", "Customer", "orders", "customer_id", "customers", "customer_id"))
    apply_join_verifications(g, [VerifiedJoin("orders", "customer_id", "customers", "customer_id", 1.0)], [])
    r = g.relationships["R1"]
    assert r.value_overlap == 1.0 and r.join_confidence == "verified"


def test_value_disjoint_edge_is_dropped():
    g = _graph(
        _rel("R1", "Order", "Customer", "orders", "customer_id", "customers", "customer_id"),
        _rel("R2", "Order", "Product", "orders", "order_id", "products", "product_id"),  # name-shape coincidence
    )
    apply_join_verifications(
        g,
        verified=[VerifiedJoin("orders", "customer_id", "customers", "customer_id", 1.0)],
        rejected=[VerifiedJoin("orders", "order_id", "products", "product_id", 0.0)],
    )
    assert "R2" not in g.relationships and "R1" in g.relationships     # the disjoint edge is gone


def test_relationship_index_is_rebuilt_after_a_drop():
    g = _graph(
        _rel("R1", "Order", "Customer", "orders", "customer_id", "customers", "customer_id"),
        _rel("R2", "Order", "Product", "orders", "order_id", "products", "product_id"),
    )
    apply_join_verifications(g, [], [VerifiedJoin("orders", "order_id", "products", "product_id", 0.0)])
    # Product is no longer reachable from Order (the false edge was pruned from the index)
    assert "Product" not in g.relationship_index.get("Order", [])
    assert "Customer" in g.relationship_index.get("Order", [])


def test_unprobeable_edge_is_left_untouched():
    g = _graph(_rel("R1", "A", "B", "a", "k", "b", "k", conf="inferred"))
    apply_join_verifications(g, [VerifiedJoin("a", "k", "b", "k", -1.0)], [])   # -1 = couldn't probe
    r = g.relationships["R1"]
    assert r.value_overlap is None and r.join_confidence == "inferred"   # never demote what we can't check


def test_edge_match_is_order_independent_and_qualification_tolerant():
    # relationship carries schema-qualified tables + reversed orientation vs the probe result
    g = _graph(_rel("R1", "Order", "Customer", "missimi.orders", "customer_id", "missimi.customers", "customer_id"))
    apply_join_verifications(g, [VerifiedJoin("customers", "customer_id", "orders", "customer_id", 0.97)], [])
    assert g.relationships["R1"].value_overlap == 0.97


def test_edge_key_normalizes_orientation_and_schema():
    assert _edge_key("missimi.orders", "CUSTOMER_ID", "customers", "customer_id") == \
        _edge_key("customers", "customer_id", "orders", "customer_id")
